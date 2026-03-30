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

# Fixed ports for managed llama-server instances (offset from remote defaults)
MANAGED_SUPPORT_PORT = 49172
MANAGED_EMBED_PORT = 49173


class SupportResult(NamedTuple):
    """Result from a support model call with model-reported token usage."""

    text: Optional[str]
    prompt_tokens: int = 0
    completion_tokens: int = 0
    truncated: bool = False


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

    def _ensure_binary(self) -> bool:
        """Ensure llama-server binary is available, downloading if needed."""
        if self.model_manager.llama_server_available():
            return True
        return self.model_manager.download_llama_server_sync()

    def load_support_model(self) -> bool:
        """Start the support model server. Returns True on success."""
        if self._support_process is not None:
            return True

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
        rb = 0 if self.settings.reasoning_effort == 0 else -1
        backend = self.model_manager._get_active_backend()
        gpu_label = "metal" if platform.system() == "Darwin" else backend
        model_name = os.path.basename(model_path)
        printr.print(
            f"Starting support server: {model_name} "
            f"(n_ctx={n_ctx}, n_threads={n_threads}, gpu={gpu_label}, "
            f"reasoning={'off' if rb == 0 else 'on'}, port={MANAGED_SUPPORT_PORT})",
            color=LogType.INFO,
            server_only=True,
        )

        # reasoning_budget: 0 = disable thinking (fast), >0 = allow thinking tokens
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
        if self._embed_process is not None:
            return True

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
        """Update settings. If run_locally changed or models/backend changed, handle restart."""
        old = self.settings
        self.settings = new_settings
        self.model_manager.update_settings(new_settings)

        if old.run_locally and not new_settings.run_locally:
            self.unload_models()
        elif new_settings.run_locally:
            # Backend change requires full restart of both servers
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
    ) -> SupportResult:
        """Process text using the managed llama-server support model.

        Returns a SupportResult with text, token usage from the model's own
        tokenizer, and whether the output was truncated (finish_reason=length).
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
                temperature=0.3,
                frequency_penalty=0.5,
                presence_penalty=0.3,
            )
            raw = result.choices[0].message.content
            cleaned = self._deduplicate_lines(raw) if raw else None

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
        """Check if server processes are running."""
        return self._support_process is not None or self._embed_process is not None

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
