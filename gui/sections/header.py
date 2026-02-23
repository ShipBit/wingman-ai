import customtkinter as ctk
from os import path
from PIL import Image
from gui.components.icon_button import IconButton

class Header(ctk.CTkFrame):
    THEME = {
        "panel": "#0d1b2d",
        "panel_alt": "#102239",
        "border": "#1c3f64",
        "text": "#d7efff",
        "muted": "#83a4c6",
        "accent_hover": "#3ec5ff",
    }

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.theme = self.THEME

        self.grid_columnconfigure(1, weight=1)
        self.configure(fg_color=self.theme["panel_alt"])

        self.logo_image = None
        logo_path = path.join(
            master.core.app_root_dir, "assets", "cora-sc", "Cora_Box.png"
        )
        if path.exists(logo_path):
            logo_asset = Image.open(logo_path)
            logo_target_height = 38
            logo_target_width = max(
                1, int(logo_asset.size[0] * (logo_target_height / logo_asset.size[1]))
            )
            self.logo_image = ctk.CTkImage(
                light_image=logo_asset,
                dark_image=logo_asset,
                size=(logo_target_width, logo_target_height),
            )
            self.brand_label = ctk.CTkLabel(
                self,
                text="",
                image=self.logo_image,
                fg_color="transparent",
            )
        else:
            self.brand_label = ctk.CTkLabel(
                self,
                text="CORA SC",
                text_color=self.theme["text"],
                font=("Segoe UI", 22, "bold"),
            )
        self.brand_label.grid(row=0, column=0, padx=(14, 8), pady=8, sticky="w")

        self.subtitle_label = ctk.CTkLabel(
            self,
            text="Star Citizen Control Interface",
            text_color=self.theme["muted"],
            font=("Segoe UI", 11),
        )
        self.subtitle_label.grid(row=0, column=1, padx=5, pady=8, sticky="w")

        self.settings_button = IconButton(self,
                                icon="settings",
                                size=32,
                                themed=False,
                                hover_color=self.theme["accent_hover"],
                                command=lambda: master.show_view("settings"))
        self.settings_button.grid(row=0, column=4, padx=8, pady=5, sticky="e")

