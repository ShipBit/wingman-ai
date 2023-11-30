import customtkinter as ctk
from gui.components.icon_button import IconButton

CONTEXT_COLORS = (
    "red",
    "blue",
    "green",
    "yellow"
)

class ContextSwitcher(ctk.CTkFrame):
# class ContextSwitcher(ctk.CTkScrollableFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self.master = master
        self.contexts = master.core.config_manager.contexts
        self.context_buttons = {}
        self.active_context = ""

        self.spacer = ctk.CTkLabel(self, text="")
        self.spacer.grid(row=0, column=0)

        for i, context_name in enumerate(self.contexts):
            context_button = IconButton(self,
                                icon=f"context-icon_{CONTEXT_COLORS[i % len(CONTEXT_COLORS)]}" if context_name else "context-icon",
                                themed=False,
                                command=lambda c=context_name: self.activate_context(c))
            context_button.grid(row=i+1, column=0, padx=14, pady=14)
            self.context_buttons[context_name] = context_button
            if not context_name:
                self.__set_context_button_state("", False)


    def __set_context_button_state(self, context, active=True):
        context_button = self.context_buttons.get(context)
        if context_button:
            context_button.configure(state="normal" if active else "disabled",
                                     fg_color="transparent" if active else ("grey60", "grey40"))


    def activate_context(self, context):
        self.__set_context_button_state(self.active_context, True)

        if self.master:
            update_context = getattr(self.master, "update_context", None)
            if callable(update_context):
                update_context(context)

            self.active_context = context
            self.__set_context_button_state(self.active_context, False)
