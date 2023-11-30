import customtkinter as ctk
from gui.components.icon_button import IconButton
from gui.components.key_value_list import KeyValueList
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

        self.grid_rowconfigure(3, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(3, weight=1)
        padding = {"padx":15, "pady":10}

        self.headline = ctk.CTkLabel(self, text="Settings", font=('TkHeadingFont', 20, "bold"))
        self.headline.grid(row=0, column=1, columnspan=2, **padding)
        self.close_button = IconButton(self,
                                        icon="✖️",
                                        emoji=True,
                                        size=32,
                                        themed=False,
                                        command=lambda: master.show_view("context"))
        self.close_button.grid(row=0, column=3, **padding, sticky="e")

        appearance_options = ["🌙", "⚙️", "☀️"]
        self.appearance_label = ctk.CTkLabel(self, text="UI Appearance: ")
        self.appearance_label.grid(row=1, column=1, **padding, sticky="w")
        self.appearance_switcher = ctk.CTkSegmentedButton(self, values=appearance_options, command=self.set_appearance)
        self.appearance_switcher.grid(row=1, column=2, **padding, sticky="w")
        self.__load_gui_config()

        self.spacer = ctk.CTkLabel(self, text="")
        self.spacer.grid(row=2, column=1, **padding, sticky="ew")

        self.key_list = KeyValueList(self, label_text="API Keys", key_name="Service Name", value_name="API Key", data=self.config_manager.api_keys, update_callback=self.__update_api_keys)
        self.key_list.grid(row=3, column=0, columnspan=4, **padding, sticky="nesw")


    def __load_gui_config(self):
        config = self.config_manager.load_gui_config()

        mapped_value = list(self.SYSTEM_APPEARANCE_MAP.keys())[list(self.SYSTEM_APPEARANCE_MAP.values()).index(
            config.get("appearance", "system")
        )]
        self.appearance_switcher.set(mapped_value)


    def __update_api_keys(self, data):
        self.config_manager.api_keys = data
        self.config_manager.save_api_keys()


    def set_appearance(self, value):
        mapped_value = self.SYSTEM_APPEARANCE_MAP[value]
        self.config_manager.gui_config["appearance"] = mapped_value
        self.config_manager.save_gui_config()
        ctk.set_appearance_mode(mapped_value)
