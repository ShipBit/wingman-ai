"""Per-turn benchmark snapshot building and token-usage broadcasting."""

from api.enums import ConversationProvider
from api.interface import BenchmarkResult, TokenUsage, WingmanConfig
from services.benchmark import Benchmark, format_ms
from services.printr import Printr
from services.token_utils import count_tokens

printr = Printr()


class TurnMetrics:
    """Focused service for per-turn benchmark snapshots and token-usage broadcast."""

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
        self._turn_usage: TokenUsage | None = None

    # ──────────────────────────── public API ─────────────────────────── #

    def add_benchmark_snapshot(
        self, benchmark: Benchmark, label: str, execution_time_ms: float
    ) -> None:
        benchmark.snapshots.append(
            BenchmarkResult(
                label=label,
                execution_time_ms=execution_time_ms,
                formatted_execution_time=format_ms(execution_time_ms),
            )
        )

    def add_system_one_snapshot(
        self, benchmark: Benchmark, decisions: list[tuple[str, float]]
    ) -> None:
        """What the decision layer cost this turn, and on what.

        One line in the tooltip with the individual decisions under it, the
        same shape tool execution uses. Nothing is added when the layer is
        off, so a user who never switched it on does not get an empty row
        asking what it is.
        """
        if not decisions:
            return
        benchmark.snapshots.append(
            BenchmarkResult(
                label="System 1 decision making",
                execution_time_ms=sum(ms for _label, ms in decisions),
                formatted_execution_time=format_ms(sum(ms for _label, ms in decisions)),
                snapshots=[
                    BenchmarkResult(
                        label=label,
                        execution_time_ms=ms,
                        formatted_execution_time=format_ms(ms),
                    )
                    for label, ms in decisions
                ],
            )
        )

    def add_tool_execution_snapshot(
        self,
        benchmark: Benchmark,
        total_time_ms: float,
        tool_timings: list[tuple[str, float]],
    ) -> None:
        nested_snapshots = [
            BenchmarkResult(
                label=label,
                execution_time_ms=time_ms,
                formatted_execution_time=format_ms(time_ms),
            )
            for label, time_ms in tool_timings
        ]

        benchmark.snapshots.append(
            BenchmarkResult(
                label="Tool Execution",
                execution_time_ms=total_time_ms,
                formatted_execution_time=format_ms(total_time_ms),
                snapshots=nested_snapshots or None,
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
                history_tokens=self.conversation.estimate_tokens(),
                summary_tokens=count_tokens(self.conversation.conversation_summary or ""),
            )
        )

    def start_turn_usage(self) -> None:
        """Forget what an earlier turn used, including one that ended early."""
        self._turn_usage = None

    def add_call_usage(self, usage: TokenUsage) -> None:
        """Add one model request to the turn.

        ``last_turn_prompt_tokens`` stays what the *last* request sent: that is
        the size of the context, which the status bar and the condenser need.
        What the turn used is every request added up, because each one sends
        the whole conversation again.
        """
        if not (usage.input_tokens or usage.output_tokens):
            return
        if self._turn_usage is None:
            self._turn_usage = usage.model_copy()
            return
        self._turn_usage.input_tokens += usage.input_tokens
        self._turn_usage.cached_tokens += usage.cached_tokens
        self._turn_usage.output_tokens += usage.output_tokens

    def take_turn_usage(self) -> TokenUsage | None:
        """What the turn used, once: the next message must not repeat it."""
        usage, self._turn_usage = self._turn_usage, None
        return usage
