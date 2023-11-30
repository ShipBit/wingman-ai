import customtkinter as ctk
from gui.components.icon import Icon
from gui.components.icon_button import IconButton
from gui.components.social_links import SocialLinks
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

        self.social_links = SocialLinks(self, fg_color=("grey80", "grey40"))
        self.social_links.grid(row=0, column=1, padx=5, pady=5)

        # TODO: Move to Burger-Menu
        self.about_button = IconButton(self,
                                icon="ℹ️",
                                emoji=True,
                                size=32,
                                themed=False,
                                command=lambda: master.show_view("about"))
        self.about_button.grid(row=0, column=3, padx=5, pady=5, sticky="e")
        self.settings_button = IconButton(self,
                                icon="⚙️",
                                emoji=True,
                                size=32,
                                themed=False,
                                command=lambda: master.show_view("settings"))
        self.settings_button.grid(row=0, column=4, padx=5, pady=5, sticky="e")

