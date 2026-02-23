import customtkinter as ctk
from gui.sections.context_switcher import ContextSwitcher
from gui.sections.context_runner import ContextRunner

class ContextView(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)

        self.core = master.core
        context_names = [context for context in self.core.config_manager.contexts if context]
        self._show_context_switcher = len(context_names) > 1
        self._context_runner_column = 1 if self._show_context_switcher else 0

        if self._show_context_switcher:
            self.grid_columnconfigure(1, weight=1)
        else:
            self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        if self._show_context_switcher:
            self.context_switcher = ContextSwitcher(self, width=88, corner_radius=0)
            self.context_switcher.grid(row=0, column=0, sticky="ns")
            initial_context = ""
        else:
            self.context_switcher = None
            initial_context = context_names[0] if context_names else ""

        self.context_runner = ContextRunner(
            self,
            context=initial_context,
            fg_color="transparent",
            bg_color="transparent",
        )
        self.context_runner.grid(
            row=0,
            column=self._context_runner_column,
            pady=5,
            sticky="nesw",
        )


    def update_context(self, context=""):
        self.context_runner.destroy()
        self.context_runner = ContextRunner(
            self, context=context, fg_color="transparent", bg_color="transparent"
        )
        self.context_runner.grid(
            row=0,
            column=self._context_runner_column,
            pady=5,
            sticky="nesw",
        )
