import customtkinter as ctk
from gui.components.icon_button import IconButton
from services.config_manager import ConfigManager

class SettingsView(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)

        self.core = master.core
        self.config_manager = self.core.config_manager

        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(4, weight=1)

        self.headline = ctk.CTkLabel(self, text="Settings")
        self.headline.grid(row=0, column=0, columnspan=3, padx=5, pady=5)
        self.close_button = IconButton(self,
                                        icon="✖️",
                                        emoji=True,
                                        size=32,
                                        themed=False,
                                        command=lambda: master.hide_view("settings"))
        self.close_button.grid(row=0, column=4, padx=5, pady=5, sticky="e")

        appearance_options: list[ConfigManager.SYSTEM_APPEARANCE_OPTIONS] = ["🌙", "⚙️", "☀️"]
        self.appearance_switcher = ctk.CTkSegmentedButton(self, values=appearance_options, command=self.set_appearance)
        self.appearance_switcher.set("⚙️")
        self.appearance_switcher.grid(row=1, column=1, padx=5, pady=5, sticky="w")


    def set_appearance(self, value):
        ctk.set_appearance_mode(ConfigManager.SYSTEM_APPEARANCE_MAP[value])
