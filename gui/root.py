import customtkinter as ctk
from gui.header import Header
from gui.context_switcher import ContextSwitcher
from gui.context_runner import ContextRunner

class WingmanUI(ctk.CTk):
    def __init__(self, core):
        super().__init__()
        self.core = core

        self.title("Wingman AI")
        self.geometry("800x600")
        self.minsize(400, 150)
        self.eval('tk::PlaceWindow . center')

        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)

        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("assets/themes/wingman-ai.json")

        # img = Image.open("assets/wingman-ai.png")

        self.header = Header(self, height=74, corner_radius=0)
        self.header.grid(row=0, column=0, columnspan=2, sticky="we")

        self.context_switcher = ContextSwitcher(self, width=88, corner_radius=0)
        self.context_switcher.grid(row=1, column=0, sticky="ns")

        # TODO: read context from config
        self.context_runner = ContextRunner(self, context="", fg_color="transparent", bg_color="transparent")
        self.context_runner.grid(row=1, column=1, sticky="nesw")

    def update_context(self, context=""):
        self.context_runner.destroy()
        self.context_runner = ContextRunner(self, context=context, fg_color="transparent", bg_color="transparent")
        self.context_runner.grid(row=1, column=1, sticky="nesw")
