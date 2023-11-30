import sys
import customtkinter as ctk
from PIL import Image
from gui.header import Header
from gui.context_switcher import ContextSwitcher

class WingmanAI(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Wingman AI")
        self.geometry("800x600")
        self.minsize(400, 150)

        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)

        ctk.set_appearance_mode("system")

        # img = Image.open("assets/wingman-ai.png")

        self.header = Header(master=self, height=74, corner_radius=0)
        self.header.grid(row=0, column=0, columnspan=2, sticky="we")

        self.context_switcher = ContextSwitcher(master=self, width=88, corner_radius=0)
        self.context_switcher.grid(row=1, column=0, rowspan=2, sticky="ns")

        self.label = ctk.CTkLabel(self, text="Wingman AI", font=("Barlow", 30))
        self.label.grid(row=1, column=1, padx=20, pady=20)
        # label.pack(padx=20, pady=20)

        self.button = ctk.CTkButton(self, text="🔚 Exit", command=self.button_callback)
        self.button.grid(row=2, column=1, padx=20, pady=20, sticky="ew")
        # button.pack(padx=20, pady=20)

    def button_callback(self):
        print("by by o7")
        sys.exit(0)
