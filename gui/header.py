import customtkinter as ctk
from gui.components.icon import Icon
from gui.components.icon_button import IconButton

class Header(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.grid_columnconfigure(0, weight=1)

        txt_logo = Icon(icon="wingman-ai-text", size=(512, 62))

        self.logo = ctk.CTkLabel(self, text="", image=txt_logo)
        self.logo.grid(row=0, column=0, padx=5, pady=5, sticky="w")

        #TODO just for debugging -> move to config
        self.appearance_switcher = ctk.CTkSegmentedButton(self, values=["🌙", "⚙️", "☀️"], command=self.set_appearance)
        self.appearance_switcher.set("⚙️")
        self.appearance_switcher.grid(row=0, column=1, padx=5, pady=5, sticky="e")

        self.button = IconButton(self,
                                icon="✖️",
                                emoji=True,
                                size=32,
                                themed=False,
                                command=master.quit)
        self.button.grid(row=0, column=2, padx=5, pady=5, sticky="e")

    def set_appearance(self, value):
        #TODO just for debugging
        # also: should be an enum

        match value:
            case "🌙":
                ctk.set_appearance_mode("dark")
            case "☀️":
                ctk.set_appearance_mode("light")
            case _:
                ctk.set_appearance_mode("system")
