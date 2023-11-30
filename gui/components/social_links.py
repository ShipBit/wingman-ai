import webbrowser
import customtkinter as ctk
from gui.components.icon_button import IconButton


class SocialLinks(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)

        padding = {"padx": 1, "pady": 1}
        btn_hover_color = "white"

        self.discord_button = IconButton(self,
                                icon="discord",
                                size=32,
                                hover_color=btn_hover_color,
                                themed=False,
                                command=lambda: self.__open_link("https://discord.gg/mqftEBUDEX"))
        self.discord_button.grid(row=0, column=0, **padding)
        self.github_button = IconButton(self,
                                icon="github",
                                size=32,
                                hover_color=btn_hover_color,
                                themed=False,
                                command=lambda: self.__open_link("https://github.com/ShipBit/wingman-ai"))
        self.github_button.grid(row=0, column=1, **padding)
        self.patreon_button = IconButton(self,
                                icon="patreon",
                                size=32,
                                hover_color=btn_hover_color,
                                themed=False,
                                command=lambda: self.__open_link("https://patreon.com/ShipBit"))
        self.patreon_button.grid(row=0, column=2, **padding)


    def __open_link(self, url):
        webbrowser.open(url, new=1)
