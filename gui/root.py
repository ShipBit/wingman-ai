import tkinter as tk
from typing import Literal
import customtkinter as ctk
from gui.components.notification_banner import NotificationBanner
from gui.sections.header import Header
from gui.views.context_view import ContextView
from gui.views.settings_view import SettingsView

class WingmanUI(ctk.CTk):
    VIEWS = Literal["context", "settings"]
    _views: dict[VIEWS, ctk.CTkFrame | None] = dict(
        context=None,
        settings=None
    )

    def __init__(self, core):
        super().__init__()
        self.core = core

        self.about_window = None

        ctk.set_appearance_mode(self.core.config_manager.gui_config.get("appearance", "system"))
        # TODO: add themes
        # ctk.set_default_color_theme("assets/themes/wingman-ai.json")

        self.title("Wingman AI")
        self.geometry("1024x800+200+150")
        self.minsize(400, 150)

        # TODO:
        self.menubar = tk.Menu(self)
        self.system_menu = tk.Menu(self.menubar, name="apple")
        self.system_menu.add_command(label="Exit Wingman AI", command=self.quit)
        self.menubar.add_cascade(label="System", menu=self.system_menu)
        self.help_menu = tk.Menu(self.menubar, tearoff=0)
        self.help_menu.add_command(label="About Wingman AI", command=self.show_info)
        self.menubar.add_cascade(label="Help", menu=self.help_menu)
        self.config(menu=self.menubar)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.header = Header(self, height=74, corner_radius=0)
        self.header.grid(row=0, column=0, sticky="we")

        self._views["settings"] = SettingsView(self, corner_radius=0, fg_color="transparent")
        self._views["settings"].grid(row=1, column=0, sticky="nesw")

        self._views["context"] = ContextView(self, corner_radius=0, fg_color="transparent")
        self._views["context"].grid(row=1, column=0, sticky="nesw")

        self.notification_banner = NotificationBanner(self, corner_radius=0)
        self.notification_banner.set_grid_position(row=2, column=0)


    def switch_view(self, view:VIEWS, show=True):
        toggle_view = self._views.get(view)
        if isinstance(toggle_view, ctk.CTkFrame):
            if show:
                toggle_view.tkraise()
            else:
                toggle_view.lower()

    def show_view(self, view:VIEWS):
        self.switch_view(view, show=True)

    def hide_view(self, view:VIEWS):
        self.switch_view(view, show=False)


    def show_info(self):
        # TODO: Move into own file & fill with info
        if self.about_window is None or not self.about_window.winfo_exists():
            self.about_window = ctk.CTkToplevel(self)
            self.placeholder_label = ctk.CTkLabel(self.about_window, text="INFO_PLACEHOLDER")
            self.placeholder_label.grid(padx=5)
        else:
            self.about_window.focus()  # if window exists focus it
