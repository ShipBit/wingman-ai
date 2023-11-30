import customtkinter as ctk
from gui.components.icon import Icon
from gui.components.icon_button import IconButton
from services.version_check import VersionCheck, LOCAL_VERSION
from services.printr import Printr


printr = Printr()
version_check = VersionCheck()

class Header(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.grid_columnconfigure(1, weight=1)

        txt_logo = Icon(icon="wingman-ai-text", size=(512, 62))

        self.logo = ctk.CTkLabel(self, text="", image=txt_logo)
        self.logo.grid(row=0, column=0, padx=5, pady=5, sticky="w")

        self.version = ctk.CTkLabel(self)
        if version_check.current_version_is_latest():
            self.version.configure(text=f"v{LOCAL_VERSION}")
        else:
            self.version.configure(text=f"v{LOCAL_VERSION}  ⇪", text_color="#dd6633")
            printr.print_info(f"A new Wingman AI version is available! Get the latest version ({version_check.get_latest_version()}) at https://wingman-ai.com")
        self.version.grid(row=0, column=0, padx=20, pady=10, sticky="es")

        # TODO: add links for 'discord', 'patreon' and 'github'

        # TODO: just for debugging -> move to config
        self.appearance_switcher = ctk.CTkSegmentedButton(self, values=["🌙", "⚙️", "☀️"], command=self.set_appearance)
        self.appearance_switcher.set("⚙️")
        self.appearance_switcher.grid(row=0, column=2, padx=5, pady=5, sticky="e")

        self.button = IconButton(self,
                                icon="✖️",
                                emoji=True,
                                size=32,
                                themed=False,
                                command=master.quit)
        self.button.grid(row=0, column=3, padx=5, pady=5, sticky="e")

    def set_appearance(self, value):
        # TODO: just for debugging
        # also: should be an enum

        match value:
            case "🌙":
                ctk.set_appearance_mode("dark")
            case "☀️":
                ctk.set_appearance_mode("light")
            case _:
                ctk.set_appearance_mode("system")
