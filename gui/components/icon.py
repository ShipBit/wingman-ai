from os import path
import customtkinter as ctk
from PIL import Image

class Icon(ctk.CTkImage):
    def __init__(self, icon: str, size: int | tuple[int, int]=50, themed=True):
        if isinstance(size, int):
            size = (size, size)

        icon_dir = path.join(path.abspath(path.dirname(__file__)), "..", "..", "assets", "icons")
        super().__init__(light_image=Image.open(path.join(icon_dir, f"{icon}{'_light' if themed else ''}.png")),
                        dark_image=Image.open(path.join(icon_dir, f"{icon}{'_dark' if themed else ''}.png")),
                        size=size)
