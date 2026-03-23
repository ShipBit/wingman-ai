from datetime import datetime
import logging
import re
import sys
import inspect
from logging import Formatter
from logging.handlers import RotatingFileHandler
from os import path
from api.commands import LogCommand, ToastCommand
from api.enums import CommandTag, LogSource, LogType, ToastType
from api.interface import BenchmarkResult
from services.file import get_writable_dir
from services.websocket_user import WebSocketUser

_SENSITIVE_PARAM_PATTERN = re.compile(
    r'([?&](?:[a-zA-Z_]*(?:key|token|secret|password|auth)[a-zA-Z_]*)=)([^&\s"\']+)',
    re.IGNORECASE,
)


def _redact_sensitive_params(text: str) -> str:
    """Redact sensitive query parameters (e.g. api_key) from log text."""
    return _SENSITIVE_PARAM_PATTERN.sub(
        lambda m: m.group(1) + m.group(2)[:4] + "***REDACTED***",
        text,
    )


class StreamToLogger:
    def __init__(self, logger, log_level=logging.INFO, stream=sys.stdout):
        self.logger = logger
        self.log_level = log_level
        self.stream = stream

    def write(self, buf):
        try:
            for line in buf.rstrip().splitlines():
                redacted = _redact_sensitive_params(line.rstrip())
                self.logger.log(self.log_level, redacted)
                if isinstance(redacted, str):
                    self.stream.write(
                        redacted.encode("utf-8", errors="replace").decode("utf-8")
                        + "\n"
                    )
                else:
                    self.stream.write(redacted + "\n")
        except Exception as e:
            original_stderr = getattr(sys, "__stderr__", sys.stderr)
            original_stderr.write(
                f"Error in StreamToLogger: {str(e)} - Buffer: {buf}\n"
            )

    def flush(self):
        self.stream.flush()

    def isatty(self):
        return False


class Printr(WebSocketUser):
    """Singleton"""

    CLEAR = "\033[0m"
    # BOLD = "\033[1m"
    # FAINT = "\033[2m"
    # NORMAL_WEIGHT = "\033[22m"
    # UNDERLINE = "\033[4m"
    # END_UNDERLINE = "\033[24m"
    # OVERLINE = "\033[53m"
    # END_OVERLINE = "\033[55m"
    # FRAMED = "\033[51m"
    # ENCIRCLED = "\033[52m"
    # DELETE_LINE = "\033[2K\033[1G"
    # PREVIOUS_LINE = "\033[2F"

    _instance = None
    logger: logging.Logger

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Printr, cls).__new__(cls)

            # file logger
            cls._instance.logger = logging.getLogger("file_logger")
            cls._instance.logger.setLevel(logging.INFO)
            cls._instance.logger.propagate = False  # Prevent duplicate logging
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            # log file with timestamp
            fh = RotatingFileHandler(
                path.join(get_writable_dir("logs"), f"wingman-core.{timestamp}.log"),
                encoding="utf-8",
            )
            fh.setLevel(logging.DEBUG)
            file_formatter = Formatter(
                "%(asctime)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
            )
            fh.setFormatter(file_formatter)
            cls._instance.logger.addHandler(fh)

            # console logger with color
            cls._instance.console_logger = logging.getLogger("console_logger")
            cls._instance.console_logger.setLevel(logging.INFO)
            cls._instance.console_logger.propagate = False  # Prevent duplicate logging
            ch = logging.StreamHandler()
            ch.setLevel(logging.INFO)
            console_formatter = Formatter("%(message)s")
            ch.setFormatter(console_formatter)
            cls._instance.console_logger.addHandler(ch)

            # Redirect stdout and stderr
            sys.stdout = StreamToLogger(cls._instance.logger, logging.INFO, sys.stdout)
            sys.stderr = StreamToLogger(cls._instance.logger, logging.ERROR, sys.stderr)
        return cls._instance

    async def __send_to_gui(
        self,
        text,
        log_type: LogType,
        toast_type: ToastType,
        source=LogSource.SYSTEM,
        source_name: str = "",
        command_tag: CommandTag = None,
        skill_name: str = "",
        additional_data: dict = None,
        benchmark_result: BenchmarkResult = None,
    ):
        if self._connection_manager is None:
            raise ValueError("connection_manager has not been set.")

        elif toast_type is not None:
            await self._connection_manager.broadcast(
                command=ToastCommand(text=text, toast_type=toast_type)
            )
        else:
            wingman_name = None
            current_frame = inspect.currentframe()
            if current_frame is not None:
                while current_frame:
                    # Check if the caller is a method of a class
                    if "self" in current_frame.f_locals:
                        caller_instance = current_frame.f_locals["self"]
                        caller_instance_name = caller_instance.__class__.__name__
                        if (
                            caller_instance_name == "Wingman"
                            or caller_instance_name == "OpenAiWingman"
                        ):
                            wingman_name = caller_instance.name
                            break
                    # Move to the previous frame in the call stack
                    current_frame = current_frame.f_back

            await self._connection_manager.broadcast(
                command=LogCommand(
                    text=text,
                    log_type=log_type,
                    source=source,
                    source_name=source_name,
                    tag=command_tag,
                    skill_name=skill_name,
                    additional_data=additional_data,
                    wingman_name=wingman_name,
                    benchmark_result=benchmark_result,
                )
            )

    def print(
        self,
        text,
        color: LogType = LogType.SYSTEM,
        source=LogSource.SYSTEM,
        source_name: str = "",
        toast: ToastType = None,
        server_only=False,
        command_tag: CommandTag = None,
        additional_data: dict = None,
    ):
        # print to server (terminal) with source_name prefix
        self.print_colored(
            text, color=self.get_terminal_color(color), source_name=source_name
        )

        if not server_only and self._connection_manager is not None:
            # send to GUI without print() having to be async
            self.ensure_async(
                self.__send_to_gui(
                    text,
                    color,
                    toast_type=toast,
                    source=source,
                    source_name=source_name,
                    command_tag=command_tag,
                    additional_data=additional_data,
                )
            )

    async def print_async(
        self,
        text,
        color: LogType = LogType.SYSTEM,
        source=LogSource.SYSTEM,
        source_name: str = "",
        toast: ToastType = None,
        server_only=False,
        command_tag: CommandTag = None,
        skill_name: str = "",
        additional_data: dict = None,
        benchmark_result: BenchmarkResult = None,
        token_usage: tuple[int, int] = None,
    ):
        # Build the server (terminal) display string
        server_text = text
        suffix_parts = []
        if benchmark_result:
            suffix_parts.append(benchmark_result.formatted_execution_time)
        if token_usage:
            suffix_parts.append(f"{token_usage[0]} in / {token_usage[1]} out")
        if suffix_parts:
            server_text = f"{text} ({' | '.join(suffix_parts)})"
        # print to server (terminal) with source_name prefix
        self.print_colored(
            server_text,
            color=self.get_terminal_color(color),
            source_name=source_name,
        )
        if benchmark_result and benchmark_result.snapshots:
            for snapshot in benchmark_result.snapshots:
                self.print_colored(
                    f"  - {snapshot.label}: {snapshot.formatted_execution_time}",
                    color=self.get_terminal_color(color),
                    source_name=source_name,
                )

        if not server_only and self._connection_manager is not None:
            await self.__send_to_gui(
                text,
                color,
                toast_type=toast,
                source=source,
                source_name=source_name,
                command_tag=command_tag,
                skill_name=skill_name,
                additional_data=additional_data,
                benchmark_result=benchmark_result,
            )

    def toast(self, text: str):
        self.print(text, toast=ToastType.NORMAL)

    def toast_info(self, text: str):
        self.print(text, toast=ToastType.INFO)

    def toast_warning(self, text: str):
        self.print(text, toast=ToastType.WARNING)

    def toast_error(self, text: str):
        self.print(text, toast=ToastType.ERROR, color=LogType.ERROR)

    # INTERNAL METHODS

    def get_terminal_color(self, tag: LogType):
        # System/Runtime messages
        if tag == LogType.SYSTEM or tag.value == "system":
            return "\033[90m"  # Gray - lifecycle/system events
        elif tag == LogType.INFO or tag.value == "info":
            return "\033[38;5;75m"  # Light blue (#5fafff) - general runtime info
        elif tag == LogType.STARTUP or tag.value == "startup":
            return "\033[96m"  # Cyan/Teal - startup status, version, paths

        # Feature-specific categories
        elif tag == LogType.MCP or tag.value == "mcp":
            return "\033[38;5;39m"  # Deep sky blue (#00afff) - MCP messages
        elif tag == LogType.SKILL or tag.value == "skill":
            return "\033[38;5;214m"  # Orange (#ffaf00) - Skill messages
        elif tag == LogType.COMMAND or tag.value == "command":
            return "\033[38;5;159m"  # Pale blue (#afffff) - Command execution
        elif tag == LogType.WINGMAN or tag.value == "wingman":
            return "\033[38;5;183m"  # Light purple (#d7afff) - Wingman status

        # Attention messages
        elif tag == LogType.WARNING or tag.value == "warning":
            return "\033[93m"  # Yellow - warnings
        elif tag == LogType.ERROR or tag.value == "error":
            return "\033[91m"  # Red - errors

        # Conversation messages
        elif tag == LogType.USER or tag.value == "user":
            return "\033[95m"  # Magenta/Pink - user speech
        elif tag == LogType.POSITIVE or tag.value == "positive":
            return "\033[92m"  # Green - LLM responses, success

        else:
            return self.CLEAR

    def clr(self, text, color):
        return f"{color}{text}{Printr.CLEAR}"

    def print_colored(self, text, color, source_name: str = ""):
        # Add source_name prefix for console and file output only
        display_text = f"[{source_name}] {text}" if source_name else text
        self.console_logger.info(self.clr(display_text, color))
        self.logger.info(display_text)
