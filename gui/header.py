import customtkinter as ctk
from PIL import Image

class Header(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.grid_columnconfigure(0, weight=1)

        txt_logo = ctk.CTkImage(light_image=Image.open("assets/wingman-ai-text.png"),
                            dark_image=Image.open("assets/wingman-ai-text.png"),
                            size=(512, 62))

        self.logo = ctk.CTkLabel(self, text="", image=txt_logo)
        self.logo.grid(row=0, column=0, padx=5, pady=5, sticky="w")

        # self.label = ctk.CTkLabel(self, text="CTX-SWITCHER")
        # self.label.grid(row=1, column=0)
