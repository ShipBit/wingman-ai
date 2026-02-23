from os import path
from sys import platform
import tkinter as tk
from typing import Literal
import customtkinter as ctk
import queue
from threading import Thread
from gui.components.notification_banner import NotificationBanner
from gui.sections.header import Header
from gui.views.context_view import ContextView
from gui.views.settings_view import SettingsView
from gui.views.about_view import AboutView


class WingmanUI(ctk.CTk):
    #  make a singleton object of the window such that other modules can access and modify or enhance it
    _instance = None
    #  we need a possibility to work on the main ui thread from other modules, otherwise, we get errors
    _tkinter_queue = queue.Queue()

    VIEWS = Literal["context", "settings", "about"]
    _views: dict[VIEWS, ctk.CTkFrame | None] = dict(
        context=None, settings=None, about=None
    )
    THEME = {
        "bg": "#060f1d",
        "panel": "#0d1b2d",
        "panel_alt": "#102239",
        "border": "#1c3f64",
        "accent": "#2ab8ff",
    }
    
    @classmethod
    def get_instance(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = cls(*args, **kwargs)
        return cls._instance
    
    @classmethod
    def enqueue_tkinter_command(cls, command):
        cls._tkinter_queue.put(command)

    def process_tkinter_queue(self):
        while True:
            try:
                command = self._tkinter_queue.get_nowait()
                command()
            except queue.Empty:
                break
        self.after(100, self.process_tkinter_queue) 

    def __init__(self, core):
        super().__init__()
        self.core = core
        self.theme = self.THEME

        self.about_window = None

        theme_path = path.join(self.core.app_root_dir, "assets", "themes", "cora-sc.json")
        if path.exists(theme_path):
            ctk.set_default_color_theme(theme_path)
        ctk.set_appearance_mode(
            self.core.config_manager.gui_config.get("appearance", "system")
        )
        self.title("Cora SC")
        self.geometry("1024x800+200+150")
        self.minsize(400, 150)
        self.configure(fg_color=self.theme["bg"])

        icon_dir = path.join(self.core.app_root_dir, "assets", "cora-sc")
        icon_candidates = [
            "Cora_C_icon.png",
            "Cora_C_icon_250.png",
            "Cora_C_icon_150.png",
            "Cora_C_icon_100.png",
        ]
        self._app_icons = []
        for icon_name in icon_candidates:
            candidate_path = path.join(icon_dir, icon_name)
            if not path.exists(candidate_path):
                continue
            try:
                self._app_icons.append(tk.PhotoImage(file=candidate_path))
            except tk.TclError:
                continue

        if self._app_icons:
            self.iconphoto(True, *self._app_icons)
            self.wm_iconphoto(True, *self._app_icons)
        if platform.startswith("win"):
            app_icon_ico = path.join(
                self.core.app_root_dir, "assets", "cora-sc", "Cora_C_icon.ico"
            )
            if path.exists(app_icon_ico):
                try:
                    self.iconbitmap(app_icon_ico)
                except tk.TclError:
                    pass

        if platform == "darwin":
            self.menubar = tk.Menu(self)
            self.system_menu = tk.Menu(self.menubar, name="apple")
            self.system_menu.add_command(label="Exit Cora SC", command=self.quit)
            self.menubar.add_cascade(label="System", menu=self.system_menu)
            self.help_menu = tk.Menu(self.menubar, tearoff=0)
            self.help_menu.add_command(
                label="About Cora SC", command=lambda: self.show_view("about")
            )
            self.menubar.add_cascade(label="Help", menu=self.help_menu)
            self.config(menu=self.menubar)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.header = Header(
            self,
            height=74,
            corner_radius=0,
            fg_color=self.theme["panel_alt"],
            border_color=self.theme["border"],
            border_width=1,
        )
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

        self.notification_banner = NotificationBanner(
            self, corner_radius=0, fg_color=self.theme["panel_alt"]
        )
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
