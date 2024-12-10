from datetime import datetime
import logging
from logging import Formatter
from logging.handlers import RotatingFileHandler
from os import path
from api.commands import LogCommand, ToastCommand
from api.enums import CommandTag, LogSource, LogType, ToastType
from services.file import get_writable_dir
from services.websocket_user import WebSocketUser


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
            cls._instance.logger = logging.getLogger('file_logger')
            cls._instance.logger.setLevel(logging.INFO)

            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

            # Info file handler with timestamp
            fh = RotatingFileHandler(
                path.join(get_writable_dir("logs"), f"wingman-core.{timestamp}.log")
            )
            fh.setLevel(logging.DEBUG)
            file_formatter = Formatter('%(asctime)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
            fh.setFormatter(file_formatter)
            cls._instance.logger.addHandler(fh)

            # Console logger with color
            cls._instance.console_logger = logging.getLogger('console_logger')
            cls._instance.console_logger.setLevel(logging.INFO)
            ch = logging.StreamHandler()
            ch.setLevel(logging.INFO)
            console_formatter = Formatter('%(message)s')
            ch.setFormatter(console_formatter)
            cls._instance.console_logger.addHandler(ch)
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
    ):
        if self._connection_manager is None:
            raise ValueError("connection_manager has not been set.")

        elif toast_type is not None:
            await self._connection_manager.broadcast(
                command=ToastCommand(text=text, toast_type=toast_type)
            )
        else:
            await self._connection_manager.broadcast(
                command=LogCommand(
                    text=text,
                    log_type=log_type,
                    source=source,
                    source_name=source_name,
                    tag=command_tag,
                    skill_name=skill_name,
                    additional_data=additional_data,
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
    ):
        # print to server (terminal)
        self.print_colored(text, color=self.get_terminal_color(color))

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
