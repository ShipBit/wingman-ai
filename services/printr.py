from api.commands import LogCommand, ToastCommand
from api.enums import CommandTag, LogSource, LogType, ToastType
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

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Printr, cls).__new__(cls)
        return cls._instance

    async def __send_to_gui(
        self,
        text,
        log_type: LogType,
        toast_type: ToastType,
        source=LogSource.SYSTEM,
        source_name: str = "",
        command_tag: CommandTag = None,
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
            )

    def toast(self, text: str):
        self.print(text, toast=ToastType.NORMAL)

    def toast_info(self, text: str):
        self.print(text, toast=ToastType.INFO)

    def toast_warning(self, text: str):
        self.print(text, toast=ToastType.WARNING)

    def toast_error(self, text: str):
        self.print(text, toast=ToastType.ERROR)

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
        print(self.clr(text, color), flush=True)
