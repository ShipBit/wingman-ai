from sys import platform
import tkinter as tk
from typing import Literal
import customtkinter as ctk
from gui.components.notification_banner import NotificationBanner
from gui.sections.header import Header
from gui.views.context_view import ContextView
from gui.views.settings_view import SettingsView
from gui.views.about_view import AboutView


class WingmanUI(ctk.CTk):
    VIEWS = Literal["context", "settings", "about"]
    _views: dict[VIEWS, ctk.CTkFrame | None] = dict(
        context=None, settings=None, about=None
    )

    def __init__(self, core):
        super().__init__()
        self.core = core

        self.about_window = None

        ctk.set_appearance_mode(
            self.core.config_manager.gui_config.get("appearance", "system")
        )
        # TODO: add themes
        # ctk.set_default_color_theme(path.join(self.core.app_root_dir, "assets", "themes", "wingman-ai.json"))

        self.title("Wingman AI")
        self.geometry("1024x800+200+150")
        self.minsize(400, 150)
        # no way to set this on MacOS
        self.iconbitmap(self.core.app_root_dir + "/assets/wingman-ai.ico")

        if platform == "darwin":
            mac_dock_icon = tk.Image(
                "photo", file=self.core.app_root_dir + "/assets/icons/wingman-ai.png"
            )
            self.iconphoto(True, mac_dock_icon)
            self.menubar = tk.Menu(self)
            self.system_menu = tk.Menu(self.menubar, name="apple")
            self.system_menu.add_command(label="Exit Wingman AI", command=self.quit)
            self.menubar.add_cascade(label="System", menu=self.system_menu)
            self.help_menu = tk.Menu(self.menubar, tearoff=0)
            self.help_menu.add_command(
                label="About Wingman AI", command=lambda: self.show_view("about")
            )
            self.menubar.add_cascade(label="Help", menu=self.help_menu)
            self.config(menu=self.menubar)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.header = Header(self, height=74, corner_radius=0)
        self.header.grid(row=0, column=0, sticky="we")

        view_grid = {"row": 1, "column": 0, "sticky": "nesw"}
        self._views["about"] = AboutView(self, corner_radius=0, fg_color="transparent")
        self._views["about"].grid(**view_grid)

        self._views["settings"] = SettingsView(
            self, corner_radius=0, fg_color="transparent"
        )
        self._views["settings"].grid(**view_grid)

        self._views["context"] = ContextView(
            self, corner_radius=0, fg_color="transparent"
        )
        self._views["context"].grid(**view_grid)

        self.notification_banner = NotificationBanner(self, corner_radius=0)
        self.notification_banner.set_grid_position(row=2, column=0)

    def switch_view(self, view: VIEWS, show=True):
        toggle_view = self._views.get(view)
        if isinstance(toggle_view, ctk.CTkFrame):
            if show:
                toggle_view.tkraise()
            else:
                toggle_view.lower()

    def show_view(self, view: VIEWS):
        self.switch_view(view, show=True)

    def hide_view(self, view: VIEWS):
        self.switch_view(view, show=False)
