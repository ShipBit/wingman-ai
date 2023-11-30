import customtkinter as ctk
from gui.components.icon import Icon

class IconButton(ctk.CTkButton):
    def __init__(self, master, icon="", size=42, padding=4, themed=True, emoji=False, **kwargs):
        char_count = len(icon)
        text = ""
        image = None
        dimension = size + 2 * padding

        if char_count < 1:
            pass
        elif emoji:
            text = icon
            #TODO apply size to font size
        else:
            image = Icon(icon=icon, size=size, themed=themed)

        super().__init__(master,
                        width=dimension,
                        height=dimension,
                        text=text,
                        image=image,
                        fg_color="transparent",
                        # hover_color="grey50",
                        **kwargs)
