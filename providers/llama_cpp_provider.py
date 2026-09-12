import atexit
import ctypes
import gc
import os
import platform
import subprocess
import time
from typing import NamedTuple, Optional

import requests as http_requests
from openai import OpenAI

from api.enums import LogType
from api.interface import LlamaCppSettings
from services.local_model_manager import LocalModelManager
from services.printr import Printr
from services.token_utils import count_tokens

printr = Printr()


def _create_windows_job_object():
    """Create a Windows Job Object that kills child processes when the parent dies.

    This ensures llama-server subprocesses are cleaned up even if the parent
    process is force-killed via Task Manager.
    """
    kernel32 = ctypes.windll.kernel32

    # CreateJobObjectW(lpJobAttributes, lpName)
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None

    # JOBOBJECT_EXTENDED_LIMIT_INFORMATION
    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", ctypes.c_uint32),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", ctypes.c_uint32),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", ctypes.c_uint32),
            ("SchedulingClass", ctypes.c_uint32),
        ]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = 0x2000

    # SetInformationJobObject(hJob, JobObjectExtendedLimitInformation, &info, sizeof(info))
    # JobObjectExtendedLimitInformation = 9
    kernel32.SetInformationJobObject(
        job, 9, ctypes.byref(info), ctypes.sizeof(info)
    )

    return job


def _assign_process_to_job(job, process: subprocess.Popen):
    """Assign a subprocess to a Windows Job Object."""
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1FFFFF, False, process.pid)  # PROCESS_ALL_ACCESS
    if handle:
        kernel32.AssignProcessToJobObject(job, handle)
        kernel32.CloseHandle(handle)

# Fixed ports for managed llama-server instances (offset from remote defaults)
MANAGED_SUPPORT_PORT = 49172
MANAGED_EMBED_PORT = 49173


class SupportResult(NamedTuple):
    """Result from a support model call with model-reported token usage."""

    text: Optional[str]
    prompt_tokens: int = 0
    completion_tokens: int = 0
    truncated: bool = False
    # The model's <think> block when reasoning is enabled (llama.cpp returns it
    # separately from the answer in ``reasoning_content``). None when reasoning
    # is off or the build doesn't surface it.
    reasoning_content: Optional[str] = None


def resolve_enable_thinking(reasoning: bool | None) -> bool:
    """Decide whether a single support call should think.

    Reasoning is opt-in per call and defaults to OFF (fast): callers that want
    quality on background work pass ``reasoning=True`` (e.g. memory extraction),
    while latency-sensitive paths (greetings, skill/tool calls) leave it unset.
    There is no global user toggle — the support model is fast by default.
    """
    return bool(reasoning)


def build_support_extra_body(top_k: int, enable_thinking: bool) -> dict:
    """Build the ``extra_body`` for a support-model chat completion.

    When thinking is disabled we must request it per call via
    ``chat_template_kwargs``. Newer llama.cpp builds (verified b9488) ignore the
    ``--reasoning-budget 0`` launch flag for Qwen3.5, so without this the model
    spends its entire token budget emitting a ``<think>`` block (returned in
    ``reasoning_content``) and leaves ``content`` empty — which the caller reads
    as an empty response. Older builds (b8400) accept it harmlessly, and it also
    covers remote servers whose launch flags we can't control.
    """
    extra_body: dict = {"top_k": top_k}
    if not enable_thinking:
        extra_body["chat_template_kwargs"] = {"enable_thinking": False}
    return extra_body


def extract_reasoning_content(message) -> Optional[str]:
    """Pull the model's <think> block from a chat-completion message, if any.

    llama.cpp returns reasoning separately from the answer in a non-standard
    ``reasoning_content`` field. The OpenAI client keeps unknown fields, so we
    read it directly with a ``model_extra`` fallback. Returns None when absent
    or empty (reasoning off, or a build that doesn't surface it)."""
    value = getattr(message, "reasoning_content", None)
    if value is None:
        extra = getattr(message, "model_extra", None)
        if extra:
            value = extra.get("reasoning_content")
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return None


class LlamaCppProvider:
    """Local llama.cpp provider using managed llama-server subprocesses.

    Instead of loading models in-process via the stale llama-cpp-python package,
    this provider starts llama-server binaries (from official llama.cpp releases)
    as subprocesses and communicates via the OpenAI-compatible HTTP API.
    """

    def __init__(
        self,
        settings: LlamaCppSettings,
        model_manager: LocalModelManager,
    ):
        self.settings = settings
        self.model_manager = model_manager
        self._support_process: Optional[subprocess.Popen] = None
        self._embed_process: Optional[subprocess.Popen] = None
        self._support_client: Optional[OpenAI] = None
        self._embed_client: Optional[OpenAI] = None

        # On Windows, create a Job Object so the OS kills child processes
        # automatically if the parent is force-killed (e.g. Task Manager).
        self._job_object = None
        if platform.system() == "Windows":
            try:
                self._job_object = _create_windows_job_object()
            except Exception:
                pass

        # Last-resort cleanup: kill any orphan llama-server processes on exit
        atexit.register(self._atexit_kill_servers)

    def _resolve_n_threads(self) -> int:
        """Resolve thread count: 0 means auto (half of logical cores, min 2, max 8)."""
        n = self.settings.n_threads
        if n > 0:
            return n
        cores = os.cpu_count() or 4
        return max(2, min(cores // 2, 8))

    def _start_server(
        self,
        model_path: str,
        port: int,
        embedding: bool = False,
        n_ctx: int = 4096,
        reasoning_budget: int = -1,
    ) -> Optional[subprocess.Popen]:
        """Start a llama-server process bound to localhost.

        Args:
            reasoning_budget: Token budget for thinking. 0 = disable thinking entirely.
                              -1 = use model default.
        """
        binary_path = self.model_manager.get_llama_server_path()
        if not binary_path or not os.path.exists(binary_path):
            printr.print(
                "llama-server binary not found.",
                color=LogType.ERROR,
                server_only=True,
            )
            return None

        cmd = [
            binary_path,
            "--model",
            model_path,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--ctx-size",
            str(n_ctx),
            "--threads",
            str(self._resolve_n_threads()),
            "-ngl",
            "99",
        ]
        if embedding:
            cmd.append("--embeddings")
            cmd.extend(["--ubatch-size", str(n_ctx)])
        if reasoning_budget >= 0:
            cmd.extend(["--reasoning-budget", str(reasoning_budget)])

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            # Assign to Job Object so it dies with the parent on force-kill
            if self._job_object:
                try:
                    _assign_process_to_job(self._job_object, process)
                except Exception:
                    pass
            return process
        except Exception as e:
            printr.print(
                f"Failed to start llama-server: {e}",
                color=LogType.ERROR,
                server_only=True,
            )
            return None

    def _wait_for_server(
        self, port: int, process: subprocess.Popen, timeout: int = 120
    ) -> bool:
        """Wait for server to become healthy, checking that the process is still alive."""
        url = f"http://127.0.0.1:{port}/health"
        start = time.time()
        while time.time() - start < timeout:
            # Check if the process died
            if process.poll() is not None:
                return False
            try:
                r = http_requests.get(url, timeout=2)
                if r.status_code == 200:
                    return True
            except Exception:
                pass
            time.sleep(0.5)
        return False

    def _stop_process(self, process: Optional[subprocess.Popen]):
        """Gracefully stop a server process."""
        if process is None:
            return
        try:
            process.terminate()
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        except Exception:
            pass

    def _atexit_kill_servers(self):
        """Last-resort synchronous cleanup called by atexit.

        Forcefully kills any still-running llama-server processes to prevent
        orphan processes from holding VRAM after Wingman AI exits.
        """
        for proc in (self._support_process, self._embed_process):
            if proc is None:
                continue
            try:
                if proc.poll() is None:  # still running
                    proc.kill()
                    proc.wait(timeout=5)
            except Exception:
                pass

    def _ensure_binary(self) -> bool:
        """Ensure llama-server binary is available, downloading if needed."""
        if self.model_manager.llama_server_available():
            return True
        return self.model_manager.download_llama_server_sync()

    def _running(self, process: Optional[subprocess.Popen]) -> bool:
        """Whether a handle still points at a live process.

        `is not None` is not enough: a server that crashed, was killed, or lost
        its port to a leftover from an earlier run leaves the handle behind. The
        loaders below used to read that as "already running" and never start it
        again — which showed up as memory silently not working after switching
        the support model from Local back to Cloud.
        """
        return process is not None and process.poll() is None

    def load_support_model(self) -> bool:
        """Start the support model server. Returns True on success."""
        if self._running(self._support_process):
            return True
        self._support_process = None
        self._support_client = None

        if not self._ensure_binary():
            return False

        if not self.model_manager.support_model_available():
            printr.print(
                "Support model not downloaded yet.",
                color=LogType.WARNING,
                server_only=True,
            )
            return False

        model_path = self.model_manager.get_support_model_path()
        n_ctx = self.settings.n_ctx
        n_threads = self._resolve_n_threads()
        # Always launch with thinking AVAILABLE (-1 = model default). Whether a
        # given call actually thinks is decided per-call via enable_thinking in
        # build_support_extra_body, which is the only mechanism newer llama.cpp
        # builds honour for Qwen3.5. Baking reasoning off at launch (-budget 0)
        # would make per-task reasoning (e.g. memory extraction) impossible.
        rb = -1
        backend = self.model_manager._get_active_backend()
        gpu_label = "metal" if platform.system() == "Darwin" else backend
        model_name = os.path.basename(model_path)
        printr.print(
            f"Starting support server: {model_name} "
            f"(n_ctx={n_ctx}, n_threads={n_threads}, gpu={gpu_label}, "
            f"reasoning=per-call, port={MANAGED_SUPPORT_PORT})",
            color=LogType.INFO,
            server_only=True,
        )

        self._support_process = self._start_server(
            model_path=model_path,
            port=MANAGED_SUPPORT_PORT,
            n_ctx=n_ctx,
            reasoning_budget=rb,
        )
        if self._support_process is None:
            return False

        if self._wait_for_server(MANAGED_SUPPORT_PORT, self._support_process):
            self._support_client = OpenAI(
                base_url=f"http://127.0.0.1:{MANAGED_SUPPORT_PORT}/v1",
                api_key="not-needed",
            )
            printr.print(
                "Support server ready.",
                color=LogType.INFO,
                server_only=True,
            )
            return True
        else:
            printr.print(
                "Support server failed to start. Check model compatibility with llama-server.",
                color=LogType.ERROR,
                server_only=True,
            )
            self._stop_process(self._support_process)
            self._support_process = None
            return False

    def load_embed_model(self) -> bool:
        """Start the embedding server. Returns True on success."""
        if self._running(self._embed_process):
            return True
        self._embed_process = None
        self._embed_client = None

        if not self._ensure_binary():
            return False

        if not self.model_manager.embed_model_available():
            printr.print(
                "Embed model not downloaded yet.",
                color=LogType.WARNING,
                server_only=True,
            )
            return False

        model_path = self.model_manager.get_embed_model_path()
        n_threads = self._resolve_n_threads()
        backend = self.model_manager._get_active_backend()
        gpu_label = "metal" if platform.system() == "Darwin" else backend
        model_name = os.path.basename(model_path)
        printr.print(
            f"Starting embed server: {model_name} "
            f"(n_ctx=2048, n_threads={n_threads}, gpu={gpu_label}, port={MANAGED_EMBED_PORT})",
            color=LogType.INFO,
            server_only=True,
        )

        self._embed_process = self._start_server(
            model_path=model_path,
            port=MANAGED_EMBED_PORT,
            embedding=True,
            n_ctx=2048,
        )
        if self._embed_process is None:
            return False

        if self._wait_for_server(MANAGED_EMBED_PORT, self._embed_process):
            self._embed_client = OpenAI(
                base_url=f"http://127.0.0.1:{MANAGED_EMBED_PORT}/v1",
                api_key="not-needed",
            )
            printr.print(
                "Embed server ready.",
                color=LogType.INFO,
                server_only=True,
            )
            return True
        else:
            printr.print(
                "Embed server failed to start. Check model compatibility with llama-server.",
                color=LogType.ERROR,
                server_only=True,
            )
            self._stop_process(self._embed_process)
            self._embed_process = None
            return False

    def unload_models(self):
        """Stop both server processes and free resources."""
        if self._support_process is not None:
            self._stop_process(self._support_process)
            self._support_process = None
            self._support_client = None
            printr.print(
                "Support server stopped.",
                color=LogType.INFO,
                server_only=True,
            )
        if self._embed_process is not None:
            self._stop_process(self._embed_process)
            self._embed_process = None
            self._embed_client = None
            printr.print(
                "Embed server stopped.",
                color=LogType.INFO,
                server_only=True,
            )
        gc.collect()

    def update_settings(self, new_settings: LlamaCppSettings):
        """Update settings, stopping or restarting the servers as needed."""
        from api.enums import LocalAiMode

        old = self.settings
        self.settings = new_settings
        self.model_manager.update_settings(new_settings)

        if new_settings.mode == LocalAiMode.SERVER:
            self.unload_models()
            return

        # Cloud mode keeps the embedding server and drops the support server:
        # the vector database still needs embeddings computed here, but nothing
        # is going to ask this machine for a summary any more.
        if (
            new_settings.mode == LocalAiMode.CLOUD
            and self._support_process is not None
        ):
            self._stop_process(self._support_process)
            self._support_process = None
            self._support_client = None

        # A changed backend needs both servers restarted; a changed model or
        # thread count only the one it belongs to.
        backend_changed = old.gpu_backend != new_settings.gpu_backend
        support_changed = backend_changed or (
            old.support_model != new_settings.support_model
            or old.n_ctx != new_settings.n_ctx
            or old.n_threads != new_settings.n_threads
        )
        if support_changed and self._support_process is not None:
            self._stop_process(self._support_process)
            self._support_process = None
            self._support_client = None
        embed_changed = backend_changed or (
            old.embed_model != new_settings.embed_model
            or old.n_threads != new_settings.n_threads
        )
        if embed_changed and self._embed_process is not None:
            self._stop_process(self._embed_process)
            self._embed_process = None
            self._embed_client = None

    def support(
        self,
        text: str,
        system_prompt: str = "",
        max_tokens: int = 512,
        temperature: float = 1.0,
        top_p: float = 1.0,
        top_k: int = 20,
        presence_penalty: float = 2.0,
        reasoning: bool | None = None,
    ) -> SupportResult:
        """Process text using the managed llama-server support model.

        Returns a SupportResult with text, token usage from the model's own
        tokenizer, and whether the output was truncated (finish_reason=length).

        Sampling defaults follow Qwen3.5 recommendations for non-thinking mode.
        ``reasoning`` overrides thinking for this call (None = global default).
        """
        if not system_prompt:
            from services.file import get_prompt

            system_prompt = get_prompt("support-default")
        if not self.load_support_model():
            return SupportResult(text=None)

        try:
            result = self._support_client.chat.completions.create(
                model="local-model",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                presence_penalty=presence_penalty,
                extra_body=build_support_extra_body(
                    top_k, resolve_enable_thinking(reasoning)
                ),
            )
            message = result.choices[0].message
            raw = message.content
            cleaned = self._deduplicate_lines(raw) if raw else None
            reasoning_content = extract_reasoning_content(message)

            # Extract real token counts from the model's native tokenizer
            prompt_tokens = 0
            completion_tokens = 0
            if result.usage:
                prompt_tokens = result.usage.prompt_tokens or 0
                completion_tokens = result.usage.completion_tokens or 0

            truncated = (
                result.choices[0].finish_reason == "length" if result.choices else False
            )

            return SupportResult(
                text=cleaned,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                truncated=truncated,
                reasoning_content=reasoning_content,
            )
        except Exception as e:
            input_tokens = count_tokens(system_prompt) + count_tokens(text) if text else 0
            printr.print(
                f"Local support model call failed (~{input_tokens} input tokens, n_ctx={self.settings.n_ctx}): {e}",
                color=LogType.ERROR,
                server_only=True,
            )
            return SupportResult(text=None)

    def embed(self, texts: list[str]) -> Optional[list[list[float]]]:
        """Generate embeddings via the managed llama-server."""
        if not self.load_embed_model():
            return None

        # Ensure all inputs are non-empty strings (guards against multimodal content lists)
        sanitized = [t if isinstance(t, str) and t.strip() else "" for t in texts]
        if not any(sanitized):
            return None

        try:
            response = self._embed_client.embeddings.create(
                model="local-model",
                input=sanitized,
            )
            return [item.embedding for item in response.data]
        except Exception as e:
            printr.print(
                f"Embedding failed: {e}",
                color=LogType.ERROR,
                server_only=True,
            )
            return None

    def is_ready(self) -> bool:
        """Check if any server process is running."""
        return self._running(self._support_process) or self._running(self._embed_process)

    def support_is_ready(self) -> bool:
        """Whether the support model is loaded here.

        Distinct from :meth:`is_ready` since cloud mode runs the embedding server
        on its own — "a process is up" no longer implies "the support model is
        up", and a caller that confuses the two sends a summarisation request to
        an embedding server.
        """
        return self._running(self._support_process)

    def embed_is_ready(self) -> bool:
        """Whether the embedding model is loaded here."""
        return self._running(self._embed_process)

    @staticmethod
    def _deduplicate_lines(text: str) -> str:
        """Remove duplicate lines from model output to fix small-model repetition loops."""
        seen = set()
        result = []
        for line in text.split("\n"):
            normalized = line.strip().lower()
            if not normalized or normalized not in seen:
                seen.add(normalized)
                result.append(line)
        return "\n".join(result).strip()
