from typing import Literal
import customtkinter as ctk


class Printr(object):
    _instance = None

    LILA = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CLEAR = "\033[0m"
    BOLD = "\033[1m"
    FAINT = "\033[2m"
    NORMAL_WEIGHT = "\033[22m"
    UNDERLINE = "\033[4m"
    END_UNDERLINE = "\033[24m"
    OVERLINE = "\033[53m"
    END_OVERLINE = "\033[55m"
    FRAMED = "\033[51m"
    ENCIRCLED = "\033[52m"
    DELETE_LINE = "\033[2K\033[1G"
    PREVIOUS_LINE = "\033[2F"

    tags = [
        # {"tagName": "bold", "font": "TkTextFont bold"},
        {"tagName": "info", "foreground": "#6699ff"},
        {"tagName": "warn", "foreground": "orange"},
        {"tagName": "err", "foreground": "red"},

        {"tagName": "green", "foreground": "#33cc33"},
        {"tagName": "blue", "foreground": "#6699ff"},
        {"tagName": "violet", "foreground": "#aa33dd"},
        {"tagName": "grey", "foreground": "grey"}
    ]

    CHANNEL = Literal["main", "error", "warning", "info"]
    OUTPUT_TYPES = None | ctk.StringVar | ctk.CTkTextbox

    _message_stacks: dict[CHANNEL, list] = dict(
        main=[],
        error=[],
        warning=[],
        info=[]
    )

    # NOTE this is a singleton class
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Printr, cls).__new__(cls)

            cls.out: dict[Printr.CHANNEL, Printr.OUTPUT_TYPES ] = dict(
                main=None,
                error=None,
                warning=None,
                info=None
            )
        return cls._instance


    def set_output(self, output_channel: CHANNEL, output_element: OUTPUT_TYPES):
        if isinstance(output_element, ctk.CTkTextbox):
            for tag in self.tags:
                output_element.tag_config(**tag)

        self.out[output_channel] = output_element

        msg_stack = self._message_stacks.get(output_channel, [])
        if len(msg_stack) > 0:
            msg = "\n".join(msg_stack)
            self.print(msg, output_channel)
            # TODO: clear stack?
            for _ in range(len(msg_stack)):
                msg_stack.pop()



    def print(self, text, output_channel: CHANNEL = "main", tags=None, wait_for_gui=False, console_only=False):
        channel = self.out.get(output_channel, None)
        if channel and not console_only:
            if isinstance(channel, ctk.CTkTextbox):
                channel.configure(state="normal")
                channel.insert("end", f"{text}\n", tags=tags)
                channel.configure(state="disabled")
            else:
                # output type -> StringVar
                channel.set(text)
        elif wait_for_gui and not console_only:
            # message should only be shown in GUI
            # so add it to the queue to wait for GUI initialization
            self._message_stacks.get(output_channel, []).append(text)
        else:
            # no special output type -> terminal output
            print(text)


    def print_err(self, text, wait_for_gui=True):
        self.print(text, output_channel="error", wait_for_gui=wait_for_gui)

    def print_warn(self, text, wait_for_gui=True):
        self.print(text, output_channel="warning", wait_for_gui=wait_for_gui)

    def print_info(self, text, wait_for_gui=True):
        self.print(text, output_channel="info", wait_for_gui=wait_for_gui)


    @staticmethod
    def clr(text, color_format):
        return f"{color_format}{text}{Printr.CLEAR}"

    @staticmethod
    def clr_print(text, color_format):
        print(Printr.clr(text, color_format))

    @staticmethod
    def sys_print(text, headline="", color=RED, first_message=True):
        if first_message:
            print("")
            if headline.strip():
                print(
                    Printr.clr(f"{Printr.BOLD}{headline}{Printr.NORMAL_WEIGHT}", color)
                )
        else:
            print(Printr.PREVIOUS_LINE)
        print(Printr.clr(f"⎢ {text}", color))
        print("")

    @staticmethod
    def err_print(text, first_message=True):
        Printr.sys_print(text, "Something went wrong!", first_message=first_message)

    @staticmethod
    def warn_print(text, first_message=True):
        Printr.sys_print(text, "Please note:", Printr.YELLOW, first_message)

    @staticmethod
    def info_print(text, first_message=True):
        Printr.sys_print(text, "", Printr.BLUE, first_message)

    @staticmethod
    def hl_print(text, first_message=True):
        Printr.sys_print(text, "", Printr.CYAN, first_message)

    @staticmethod
    def override_print(text):
        print(f"{Printr.DELETE_LINE}{text}")

    @staticmethod
    def box_start():
        print(
            f"{Printr.CYAN}⎡{Printr.OVERLINE}⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊{Printr.END_OVERLINE}⎤"
        )
        print(f"⎢{Printr.CLEAR}")

    @staticmethod
    def box_end():
        print(f"{Printr.CYAN}⎢")
        print(
            f"⎣{Printr.UNDERLINE}⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊⑊{Printr.END_UNDERLINE}⎦{Printr.CLEAR}"
        )

    @staticmethod
    def box_print(text):
        print(f"{Printr.CYAN}⎜{Printr.CLEAR}  {text}")
