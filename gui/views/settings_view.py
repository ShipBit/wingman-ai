import customtkinter as ctk
from gui.components.icon_button import IconButton
from gui.components.key_value_list import KeyValueList
from services.config_manager import ConfigManager


class SettingsView(ctk.CTkFrame):
    SYSTEM_APPEARANCE_MAP: dict[str, str] = {
        "Dark": "dark",
        "Light": "light",
        "System": "system",
    }

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)

        self.core = master.core
        self.config_manager: ConfigManager = self.core.config_manager
        self.secret_keeper = self.core.secret_keeper

        self.grid_rowconfigure(4, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(3, weight=1)
        padding = {"padx": 15, "pady": 10}

        self.headline = ctk.CTkLabel(
            self, text="Settings", font=("TkHeadingFont", 20, "bold")
        )
        self.headline.grid(row=0, column=1, columnspan=2, **padding)
        self.close_button = IconButton(
            self,
            icon="close",
            size=16,
            padding=8,
            themed=False,
            command=lambda: master.show_view("context"),
        )
        self.close_button.grid(row=0, column=3, **padding, sticky="e")

        # TODO: change!
        appearance_options = ["Dark", "System", "Light"]
        self.appearance_label = ctk.CTkLabel(self, text="UI Appearance: ")
        self.appearance_label.grid(row=1, column=1, **padding, sticky="w")
        self.appearance_switcher = ctk.CTkSegmentedButton(
            self, values=appearance_options, command=self.set_appearance
        )
        self.appearance_switcher.grid(row=1, column=2, **padding, sticky="w")
        self.__load_gui_config()

        self.spacer = ctk.CTkLabel(self, text="")
        self.spacer.grid(row=2, column=1, **padding, sticky="ew")

        self.key_list = KeyValueList(
            self,
            label_text="API Keys",
            key_name="Service Name",
            key_placeholder="e.g. elevenlabs",
            value_name="API Key",
            value_placeholder="Your Key",
            hide_values=True,
            data=self.secret_keeper.secrets,
            update_callback=self.__update_secrets,
        )
        self.key_list.grid(row=4, column=0, columnspan=4, **padding, sticky="nesw")
        self.hide_keys_button = ctk.CTkButton(
            self, text="Toggle API Key Visibility", command=self.key_list.hide_values
        )
        self.hide_keys_button.grid(row=3, column=2, **padding, sticky="w")

    def tkraise(self, aboveThis=None):
        super().tkraise(aboveThis)
        self.key_list.update(self.secret_keeper.secrets)

    def __load_gui_config(self):
        config = self.config_manager.load_gui_config()

        mapped_value = list(self.SYSTEM_APPEARANCE_MAP.keys())[
            list(self.SYSTEM_APPEARANCE_MAP.values()).index(
                config.get("appearance", "system")
            )
        ]
        self.appearance_switcher.set(mapped_value)

    def __update_secrets(self, data):
        self.secret_keeper.secrets = data
        self.secret_keeper.save()

    def set_appearance(self, value):
        mapped_value = self.SYSTEM_APPEARANCE_MAP[value]
        self.config_manager.gui_config["appearance"] = mapped_value
        self.config_manager.save_gui_config()
        ctk.set_appearance_mode(mapped_value)
