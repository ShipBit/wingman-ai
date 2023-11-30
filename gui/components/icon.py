import customtkinter as ctk
from PIL import Image

class Icon(ctk.CTkImage):
    def __init__(self, icon, size=50, themed=True):
        if isinstance(size, int):
            size = (size, size)

        super().__init__(light_image=Image.open(f"assets/icons/{icon}{'_light' if themed else ''}.png"),
                        dark_image=Image.open(f"assets/icons/{icon}{'_dark' if themed else ''}.png"),
                        size=size)
