import customtkinter as ctk
from gui.sections.context_switcher import ContextSwitcher
from gui.sections.context_runner import ContextRunner

class ContextView(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)

        self.core = master.core

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)


        self.context_switcher = ContextSwitcher(self, width=88, corner_radius=0)
        self.context_switcher.grid(row=0, column=0, sticky="ns")

        self.context_runner = ContextRunner(self, context="", fg_color="transparent", bg_color="transparent")
        self.context_runner.grid(row=0, column=1, pady=5, sticky="nesw")


    def update_context(self, context=""):
        self.context_runner.destroy()
        self.context_runner = ContextRunner(self, context=context, fg_color="transparent", bg_color="transparent")
        self.context_runner.grid(row=0, column=1, pady=5, sticky="nesw")
