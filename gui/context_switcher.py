import customtkinter as ctk
from PIL import Image

class ContextSwitcher(ctk.CTkFrame):
# class ContextSwitcher(ctk.CTkScrollableFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.grid_columnconfigure(0, weight=1)
        #self.contexts = contexts  #TODO use service

        img_logo = ctk.CTkImage(light_image=Image.open("assets/shipbit-logo.png"),
                            dark_image=Image.open("assets/shipbit-logo.png"),
                            size=(60, 60))

        self.spacer = ctk.CTkLabel(self, text="")
        self.spacer.grid(row=0, column=0)

        self.context_1 = ctk.CTkLabel(self, text="", image=img_logo)
        self.context_1.grid(row=1, column=0, padx=14, pady=14)

        self.context_2 = ctk.CTkLabel(self, text="", image=img_logo)
        self.context_2.grid(row=2, column=0, padx=14, pady=14)

        self.context_3 = ctk.CTkLabel(self, text="", image=img_logo)
        self.context_3.grid(row=3, column=0, padx=14, pady=14)

        # self.label = ctk.CTkLabel(self, text="CTX-SWITCHER")
        # self.label.grid(row=1, column=0)
