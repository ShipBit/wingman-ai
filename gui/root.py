import tkinter as tk
import customtkinter as ctk
from gui.sections.header import Header
from gui.views.context_view import ContextView

class WingmanUI(ctk.CTk):
    def __init__(self, core):
        super().__init__()
        self.core = core

        self.about_window = None

        ctk.set_appearance_mode("system")
        # ctk.set_default_color_theme("assets/themes/wingman-ai.json")

        self.title("Wingman AI")
        self.geometry("1024x800+200+150")
        self.minsize(400, 150)

        # TODO:
        self.menubar = tk.Menu(self)
        self.system_menu = tk.Menu(self.menubar, tearoff=0)
        self.system_menu.add_command(label="Exit", command=self.quit)
        self.menubar.add_cascade(label="System", menu=self.system_menu)
        self.help_menu = tk.Menu(self.menubar, tearoff=0)
        self.help_menu.add_command(label="About Wingman AI", command=self.show_info)
        self.menubar.add_cascade(label="Help", menu=self.help_menu)
        self.config(menu=self.menubar)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)

        self.header = Header(self, height=74, corner_radius=0)
        self.header.grid(row=0, column=0, columnspan=2, sticky="we")

        # self.notification_banner =

        self.context_view = ContextView(self, width=88, corner_radius=0, fg_color="transparent")
        self.context_view.grid(row=1, column=0, sticky="nesw")


    def show_info(self):
        # TODO: Move into own file & fill with info
        if self.about_window is None or not self.about_window.winfo_exists():
            self.about_window = ctk.CTkToplevel(self)
            self.placeholder_label = ctk.CTkLabel(self.about_window, text="INFO_PLACEHOLDER")
            self.placeholder_label.grid(padx=5)
        else:
            self.about_window.focus()  # if window exists focus it
