import customtkinter as ctk
from gui.components.icon_button import IconButton

class ContextSwitcher(ctk.CTkFrame):
# class ContextSwitcher(ctk.CTkScrollableFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.grid_columnconfigure(0, weight=1)
        #self.contexts = contexts  #TODO use service
        self.contexts = ["", "test"] #NOTE dummy data
        self.context_buttons = []

        # img_logo = ctk.CTkImage(light_image=Image.open("assets/shipbit-logo.png"),
        #                     dark_image=Image.open("assets/shipbit-logo.png"),
        #                     size=(60, 60))

        self.spacer = ctk.CTkLabel(self, text="")
        self.spacer.grid(row=0, column=0)

        for i, value in enumerate(self.contexts):
            context = IconButton(self,
                                icon="shipbit-logo" if value else "wingman-ai",
                                themed=False,
                                command=lambda v=value: master.update_context(v))
            context.grid(row=i+1, column=0, padx=14, pady=14)
            self.context_buttons.append(context)

