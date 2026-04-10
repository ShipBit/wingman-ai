"""Per-turn benchmark snapshot building and token-usage broadcasting."""

from api.enums import ConversationProvider
from api.interface import BenchmarkResult, WingmanConfig
from services.benchmark import Benchmark
from services.printr import Printr
from services.token_utils import count_tokens

printr = Printr()


class TurnMetrics:
    """Focused service for per-turn benchmark snapshots and token-usage broadcast.

    Owns the two token counters that were previously tracked directly on
    :class:`~wingmen.wingman.Wingman` and provides the formatting helpers
    that used to live there as private methods.
    """

    def __init__(
        self,
        wingman_name: str,
        config: WingmanConfig,
        conversation,
    ):
        self.wingman_name = wingman_name
        self.config = config
        self.conversation = conversation
        self.last_turn_prompt_tokens: int = 0
        self.last_turn_completion_tokens: int = 0

    # ──────────────────────────── public API ─────────────────────────── #

    def add_benchmark_snapshot(
        self, benchmark: Benchmark, label: str, execution_time_ms: float
    ) -> None:
        if execution_time_ms >= 1000:
            formatted_time = f"{execution_time_ms/1000:.1f}s"
        else:
            formatted_time = f"{int(execution_time_ms)}ms"

        benchmark.snapshots.append(
            BenchmarkResult(
                label=label,
                execution_time_ms=execution_time_ms,
                formatted_execution_time=formatted_time,
            )
        )

    def add_tool_execution_snapshot(
        self,
        benchmark: Benchmark,
        total_time_ms: float,
        tool_timings: list[tuple[str, float]],
    ) -> None:
        if total_time_ms >= 1000:
            formatted_time = f"{total_time_ms/1000:.1f}s"
        else:
            formatted_time = f"{int(total_time_ms)}ms"

        nested_snapshots = []
        for label, time_ms in tool_timings:
            if time_ms >= 1000:
                fmt = f"{time_ms/1000:.1f}s"
            else:
                fmt = f"{int(time_ms)}ms"
            nested_snapshots.append(
                BenchmarkResult(
                    label=label,
                    execution_time_ms=time_ms,
                    formatted_execution_time=fmt,
                )
            )

        benchmark.snapshots.append(
            BenchmarkResult(
                label="Tool Execution",
                execution_time_ms=total_time_ms,
                formatted_execution_time=formatted_time,
                snapshots=nested_snapshots if nested_snapshots else None,
            )
        )

    async def broadcast_token_usage(
        self, prompt_tokens: int, completion_tokens: int
    ) -> None:
        is_local = (
            self.config.features.conversation_provider == ConversationProvider.LOCAL_LLM
        )

        if is_local and prompt_tokens == 0:
            prompt_tokens = sum(
                count_tokens(
                    msg["content"]
                    if isinstance(msg.get("content"), str)
                    else str(msg.get("content", ""))
                )
                for msg in self.conversation.messages
            )
        if is_local and completion_tokens == 0 and self.conversation.messages:
            last = self.conversation.messages[-1]
            if last.get("role") == "assistant":
                content = last.get("content", "")
                completion_tokens = count_tokens(
                    content if isinstance(content, str) else str(content)
                )

        self.last_turn_prompt_tokens = prompt_tokens
        self.last_turn_completion_tokens = completion_tokens
        if prompt_tokens == 0 and completion_tokens == 0:
            return
        if not printr._connection_manager:
            return

        from api.commands import ConversationTokenUsageCommand

        await printr._connection_manager.broadcast(
            ConversationTokenUsageCommand(
                wingman_name=self.wingman_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                is_local=is_local,
            )
        )

    def reset_token_counters(self) -> None:
        self.last_turn_prompt_tokens = 0
        self.last_turn_completion_tokens = 0
