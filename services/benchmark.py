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
        if execution_time >= 1000:
            formatted_execution_time = f"{execution_time/1000:.1f}s"
        else:
            formatted_execution_time = f"{int(execution_time)}ms"

        return BenchmarkResult(
            label=label,
            execution_time_ms=execution_time,
            formatted_execution_time=formatted_execution_time,
        )
