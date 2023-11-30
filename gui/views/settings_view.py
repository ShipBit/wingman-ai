import customtkinter as ctk
from gui.components.icon_button import IconButton
from services.config_manager import ConfigManager

class SettingsView(ctk.CTkFrame):
    SYSTEM_APPEARANCE_MAP: dict[str, str] = {
        "🌙": "dark",
        "☀️": "light",
        "⚙️": "system"
    }

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)

        self.core = master.core
        self.config_manager: ConfigManager = self.core.config_manager

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

        appearance_options = ["🌙", "⚙️", "☀️"]
        self.appearance_switcher = ctk.CTkSegmentedButton(self, values=appearance_options, command=self.set_appearance)
        self.appearance_switcher.grid(row=1, column=1, padx=5, pady=5, sticky="w")
        self.__load_gui_config()


    def __load_gui_config(self):
        config = self.config_manager.load_gui_config()

        mapped_value = list(self.SYSTEM_APPEARANCE_MAP.keys())[list(self.SYSTEM_APPEARANCE_MAP.values()).index(
            config.get("appearance", "system")
        )]
        self.appearance_switcher.set(mapped_value)


    def set_appearance(self, value):
        mapped_value = self.SYSTEM_APPEARANCE_MAP[value]
        self.config_manager.gui_config["appearance"] = mapped_value
        self.config_manager.save_gui_config()
        ctk.set_appearance_mode(mapped_value)
