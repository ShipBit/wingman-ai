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
        #self.contexts = contexts  #TODO use service
        self.contexts = ["", "test"] #NOTE dummy data
        self.context_buttons = []

        self.spacer = ctk.CTkLabel(self, text="")
        self.spacer.grid(row=0, column=0)

        for i, value in enumerate(self.contexts):
            context = IconButton(self,
                                icon=f"context-icon_{CONTEXT_COLORS[i % len(CONTEXT_COLORS)]}" if value else "context-icon",
                                themed=False,
                                command=lambda v=value: master.update_context(v))
            context.grid(row=i+1, column=0, padx=14, pady=14)
            self.context_buttons.append(context)

