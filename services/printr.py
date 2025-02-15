from datetime import datetime
import logging
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


class StreamToLogger:
    def __init__(self, logger, log_level=logging.INFO, stream=sys.stdout):
        self.logger = logger
        self.log_level = log_level
        self.stream = stream

    def write(self, buf):
        try:
            for line in buf.rstrip().splitlines():
                self.logger.log(self.log_level, line.rstrip())
                if isinstance(line, str):
                    self.stream.write(line.encode('utf-8', errors='replace').decode('utf-8') + "\n")
                else:
                    self.stream.write(line + "\n")
        except Exception as e:
            original_stderr = getattr(sys, '__stderr__', sys.stderr)
            original_stderr.write(f"Error in StreamToLogger: {str(e)} - Buffer: {buf}\n")

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
                encoding='utf-8'
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
        color: LogType = LogType.SUBTLE,
        source=LogSource.SYSTEM,
        source_name: str = "",
        toast: ToastType = None,
        server_only=False,
        command_tag: CommandTag = None,
        additional_data: dict = None,
    ):
        # print to server (terminal)
        self.print_colored(text, color=self.get_terminal_color(color))

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
        color: LogType = LogType.SUBTLE,
        source=LogSource.SYSTEM,
        source_name: str = "",
        toast: ToastType = None,
        server_only=False,
        command_tag: CommandTag = None,
        skill_name: str = "",
        additional_data: dict = None,
        benchmark_result: BenchmarkResult = None,
    ):
        # print to server (terminal)
        self.print_colored(
            (
                text
                if not benchmark_result
                else f"{text} ({benchmark_result.formatted_execution_time})"
            ),
            color=self.get_terminal_color(color),
        )
        if benchmark_result and benchmark_result.snapshots:
            for snapshot in benchmark_result.snapshots:
                self.print_colored(
                    f"  - {snapshot.label}: {snapshot.formatted_execution_time}",
                    color=self.get_terminal_color(color),
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
        if tag == LogType.SUBTLE:
            return "\033[90m"
        elif tag == LogType.INFO:
            return "\033[94m"
        elif tag == LogType.HIGHLIGHT:
            return "\033[96m"
        elif tag == LogType.POSITIVE:
            return "\033[92m"
        elif tag == LogType.WARNING:
            return "\033[93m"
        elif tag == LogType.ERROR:
            return "\033[91m"
        elif tag == LogType.PURPLE:
            return "\033[95m"
        else:
            return self.CLEAR

    def clr(self, text, color):
        return f"{color}{text}{Printr.CLEAR}"

    def print_colored(self, text, color):
        self.console_logger.info(self.clr(text, color))
        self.logger.info(text)
