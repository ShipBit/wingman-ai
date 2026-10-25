"""A local OpenAI-compatible endpoint that answers with the Wingman's own model.

Mindcraft talks to "OpenAI" at a base URL of its choosing. This server is that
URL. It takes the bot's chat completion requests and answers them through
whatever model this Wingman uses: the Wingman AI subscription, the user's own
API key or a local model. The bot needs no API key of its own.

The server runs uvicorn on a daemon thread with its own event loop, like the
Accountant's dashboard. The ``backend`` decides how to answer: the skill passes
one that calls the facade, the tests pass a fake.

Mindcraft sends `Authorization: Bearer <OPENAI_API_KEY>`. The skill sets that
variable to a random token for the Mindcraft process, so the required key
doubles as the access check.
"""

from __future__ import annotations

import asyncio
import secrets
import socket
import threading
import time
import uuid
from collections import deque
from typing import Awaitable, Callable, Iterable, Optional, Protocol

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

MODEL_ID = "wingman"
WINDOW_SECONDS = 60.0


class ContextTooLong(Exception):
    """The Wingman's model refused the request as too long for its window."""


class ModelBackend(Protocol):
    async def chat(self, messages: list[dict]) -> str:
        """Answer a chat; '' when the model gave no answer. Raises ContextTooLong."""

    async def embed(self, texts: list[str]) -> Optional[list[list[float]]]:
        """Vectors for the texts, or None when embeddings are not available."""


class RateLimiter:
    """At most ``limit()`` requests per minute; a request over the limit waits.

    The brake on the bot's thinking: every request is one call on the user's
    model and plan, and a bot working on a goal asks every few seconds. The
    limit is read on every request, so a config change applies at once.
    """

    def __init__(
        self,
        limit: Callable[[], int],
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._limit = limit
        self._clock = clock
        self._sleep = sleep
        self._times: deque[float] = deque()

    async def acquire(self) -> float:
        """Wait for a free slot and take it. Returns how long it waited."""
        waited = 0.0
        while True:
            now = self._clock()
            while self._times and now - self._times[0] >= WINDOW_SECONDS:
                self._times.popleft()
            limit = max(1, int(self._limit() or 1))
            if len(self._times) < limit:
                self._times.append(now)
                return waited
            delay = WINDOW_SECONDS - (now - self._times[0])
            delay = max(0.05, delay)
            waited += delay
            await self._sleep(delay)


def _error(status: int, message: str, code: str, error_type: str = "invalid_request_error"):
    return JSONResponse(
        status_code=status,
        content={"error": {"message": message, "type": error_type, "code": code}},
    )


def clean_messages(messages: list) -> list[dict]:
    """Only role and content reach the model; anything else Mindcraft adds is dropped."""
    cleaned = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        content = message.get("content")
        if role not in ("system", "user", "assistant") or content is None:
            continue
        if not isinstance(content, (str, list)):
            content = str(content)
        cleaned.append({"role": role, "content": content})
    return cleaned


def apply_stop(text: str, stop) -> str:
    """Cut the answer at the first stop sequence, as the real API would."""
    if not text or not stop:
        return text
    sequences = [stop] if isinstance(stop, str) else [s for s in stop if isinstance(s, str)]
    cut = len(text)
    for sequence in sequences:
        if sequence:
            index = text.find(sequence)
            if index != -1:
                cut = min(cut, index)
    return text[:cut]


def create_app(
    backend: ModelBackend,
    tokens: "str | Iterable[str]",
    limiter: RateLimiter,
    *,
    log: Optional[Callable[[str], None]] = None,
) -> FastAPI:
    """The app. ``tokens`` are the bearer tokens it accepts: the skill's own
    random one, and the key from Mindcraft's keys.json if the user has one
    there, because Mindcraft presents that one instead."""
    accepted = {tokens} if isinstance(tokens, str) else {t for t in tokens if t}
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    def authorized(request: Request) -> bool:
        header = request.headers.get("authorization", "")
        scheme, _, presented = header.partition(" ")
        presented = presented.strip()
        return scheme.lower() == "bearer" and any(
            secrets.compare_digest(presented, token) for token in accepted
        )

    @app.get("/v1/models")
    async def models(request: Request):
        if not authorized(request):
            return _error(401, "Wrong or missing API key.", "invalid_api_key")
        return {"object": "list", "data": [{"id": MODEL_ID, "object": "model", "owned_by": "wingman-ai"}]}

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        if not authorized(request):
            return _error(401, "Wrong or missing API key.", "invalid_api_key")
        try:
            body = await request.json()
        except Exception:
            return _error(400, "Body must be JSON.", "invalid_json")
        messages = clean_messages(body.get("messages") or []) if isinstance(body, dict) else []
        if not messages:
            return _error(400, "messages is required.", "missing_messages")

        waited = await limiter.acquire()
        if waited and log:
            log(f"Bot request held back {waited:.0f}s by the requests-per-minute limit.")

        try:
            text = await backend.chat(messages)
        except ContextTooLong as error:
            return _error(400, str(error) or "Context length exceeded.", "context_length_exceeded")
        if not text:
            return _error(502, "The Wingman's model gave no answer.", "no_answer", "server_error")

        text = apply_stop(text, body.get("stop"))
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": body.get("model") or MODEL_ID,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    @app.post("/v1/embeddings")
    async def embeddings(request: Request):
        if not authorized(request):
            return _error(401, "Wrong or missing API key.", "invalid_api_key")
        try:
            body = await request.json()
        except Exception:
            return _error(400, "Body must be JSON.", "invalid_json")
        raw = body.get("input") if isinstance(body, dict) else None
        texts = [raw] if isinstance(raw, str) else [t for t in (raw or []) if isinstance(t, str)]
        if not texts:
            return _error(400, "input is required.", "missing_input")

        vectors = await backend.embed(texts)
        if not vectors:
            return _error(501, "Embeddings are not available on this Wingman.", "not_supported", "server_error")
        return {
            "object": "list",
            "data": [
                {"object": "embedding", "index": index, "embedding": list(vector)}
                for index, vector in enumerate(vectors)
            ],
            "model": body.get("model") or MODEL_ID,
            "usage": {"prompt_tokens": 0, "total_tokens": 0},
        }

    return app


class ProxyServer:
    """uvicorn on a daemon thread, bound to 127.0.0.1 on a free port."""

    def __init__(self, app: FastAPI) -> None:
        self.app = app
        self.port = 0
        self._thread: Optional[threading.Thread] = None
        self._server = None
        self._socket: Optional[socket.socket] = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> str:
        if self.running:
            return self.base_url
        import uvicorn

        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.bind(("127.0.0.1", 0))
            listener.listen(16)
            self.port = listener.getsockname()[1]
            self._socket = listener
            self._server = uvicorn.Server(
                uvicorn.Config(
                    self.app,
                    host="127.0.0.1",
                    port=self.port,
                    proxy_headers=False,
                    log_level="warning",
                    access_log=False,
                    ws="none",
                )
            )
            self._thread = threading.Thread(
                target=self._server.run,
                kwargs={"sockets": [listener]},
                name="minecraft-bot-llm-proxy",
                daemon=True,
            )
            self._thread.start()
            deadline = time.monotonic() + 5
            while not self._server.started:
                if not self._thread.is_alive() or time.monotonic() > deadline:
                    self.stop()
                    raise RuntimeError("The bot's model endpoint did not start.")
                time.sleep(0.02)
            return self.base_url
        except Exception:
            listener.close()
            raise

    def stop(self) -> None:
        if self._server:
            self._server.should_exit = True
        if self._thread:
            self._thread.join(timeout=5)
        if self._socket:
            try:
                self._socket.close()
            except OSError:
                pass
        self._thread = self._server = self._socket = None
