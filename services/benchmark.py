import time
from api.enums import LogType
from api.interface import BenchmarkResult
from services.printr import Printr


class Benchmark:
    def __init__(self, label: str):
        self.label = label
        self.snapshot_label: str = None
        self.start_time = time.perf_counter()
        self.snapshot_start_time: float = None
        self.snapshots: list[BenchmarkResult] = []
        self.printr = Printr()

    def finish(self):
        if self.snapshot_label or self.snapshot_start_time:
            self.finish_snapshot()
            self.printr.print(
                f"Snapshot benchmark '{self.snapshot_label}' was still running when finishing '{self.label}'.",
                color=LogType.WARNING,
                server_only=True,
            )
        result = self._create_benchmark_result(self.label, self.start_time)
        if len(self.snapshots) > 0:
            result.snapshots = self.snapshots
        return result

    def start_snapshot(self, label: str):
        if self.snapshot_label or self.snapshot_start_time:
            self.finish_snapshot()
            self.printr.print(
                f"Snapshot benchmark '{self.snapshot_label}' was still running when starting '{label}'.",
                color=LogType.WARNING,
                server_only=True,
            )
        self.snapshot_label = label
        self.snapshot_start_time = time.perf_counter()

    def finish_snapshot(self):
        try:
            result = self._create_benchmark_result(
                label=self.snapshot_label, start_time=self.snapshot_start_time
            )
            self.snapshots.append(result)
        except Exception:
            pass
        self.snapshot_label = None
        self.snapshot_start_time = None

    def _create_benchmark_result(self, label: str, start_time: float):
        end_time = time.perf_counter()
        execution_time = (end_time - start_time) * 1000  # Convert to milliseconds
        formatted_execution_time = self._format_time(execution_time)

        return BenchmarkResult(
            label=label,
            execution_time_ms=execution_time,
            formatted_execution_time=formatted_execution_time,
        )

    def _format_time(self, time_ms: float) -> str:
        """Format time in milliseconds to human-readable string.

        Args:
            time_ms: Time in milliseconds

        Returns:
            Formatted string (e.g., "1.5s" or "250ms")
        """
        if time_ms >= 1000:
            return f"{time_ms/1000:.1f}s"
        return f"{int(time_ms)}ms"

    def add_snapshot(self, label: str, execution_time_ms: float):
        """Add a snapshot with the given label and execution time.

        Args:
            label: Description of what was measured
            execution_time_ms: Execution time in milliseconds
        """
        self.snapshots.append(
            BenchmarkResult(
                label=label,
                execution_time_ms=execution_time_ms,
                formatted_execution_time=self._format_time(execution_time_ms),
            )
        )

    def add_tool_execution(
        self,
        total_time_ms: float,
        tool_timings: list[tuple[str, float]],
    ):
        """Add a tool execution snapshot with nested individual tool timings.

        Args:
            total_time_ms: Total time for all tool executions
            tool_timings: List of (tool_name, time_ms) tuples
        """
        # Create nested snapshots for individual tools
        nested_snapshots = [
            BenchmarkResult(
                label=label,
                execution_time_ms=time_ms,
                formatted_execution_time=self._format_time(time_ms),
            )
            for label, time_ms in tool_timings
        ]

        self.snapshots.append(
            BenchmarkResult(
                label="Tool Execution",
                execution_time_ms=total_time_ms,
                formatted_execution_time=self._format_time(total_time_ms),
                snapshots=nested_snapshots if nested_snapshots else None,
            )
        )
