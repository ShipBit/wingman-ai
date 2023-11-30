import os
from tkinter import BOTH
import customtkinter as ctk
from gui.components.icon_button import IconButton

class AboutView(ctk.CTkFrame):

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)

        self.core = master.core

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        padding = {"padx":15, "pady":10}

        self.headline = ctk.CTkLabel(self, text="About Wingman AI", font=('TkHeadingFont', 20, "bold"))
        self.headline.grid(row=0, column=0, columnspan=2, **padding)
        self.close_button = IconButton(self,
                                        icon="✖️",
                                        emoji=True,
                                        size=32,
                                        themed=False,
                                        command=lambda: master.show_view("context"))
        self.close_button.grid(row=0, column=1, **padding, sticky="e")

        self.tab_view = ctk.CTkTabview(self)
        self.tab_view.grid(row=1, column=0, columnspan=2, **padding, sticky="nesw")

        self.__create_license_tab()
        self.__create_patreon_tab()
        self.__create_modules_tab()

    # ──────────────────────────────────────────────────────────────────────────
    def __create_license_tab(self):
        self.license_tab = self.tab_view.add("LICENSE")
        self.license_box = ctk.CTkTextbox(self.license_tab)
        self.license_box.tag_config("center", justify="center")
        license_file = os.path.join(self.core.app_root_dir, "LICENSE")
        with open(license_file, "r", encoding="UTF-8") as f:
            self.license_box.insert("end", str(f.read()), "center")
        self.license_box.configure(state="disabled")
        self.license_box.pack(fill=BOTH, expand=True)

    # ──────────────────────────────────────────────────────────────────────────
    def __create_patreon_tab(self):
        self.patreon_tab = self.tab_view.add("Patreon")
        self.patreon_box = ctk.CTkTextbox(self.patreon_tab)
        self.patreon_box.insert("end", "- PATREON - \n\nfrom File")
        self.patreon_box.configure(state="disabled")
        self.patreon_box.pack(fill=BOTH, expand=True)

    # ──────────────────────────────────────────────────────────────────────────
    def __create_modules_tab(self):
        self.modules_tab = self.tab_view.add("Modules")
        self.modules_box = ctk.CTkTextbox(self.modules_tab)
        self.modules_box.insert("end", "- used modules - \n\nfrom File")
        self.modules_box.configure(state="disabled")
        self.modules_box.pack(fill=BOTH, expand=True)
