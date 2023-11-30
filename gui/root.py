import customtkinter as ctk
from gui.sections.header import Header
from gui.views.context_view import ContextView

class WingmanUI(ctk.CTk):
    def __init__(self, core):
        super().__init__()
        self.core = core

        self.title("Wingman AI")
        self.geometry("1024x800+200+150")
        self.minsize(400, 150)
        # self.eval('tk::PlaceWindow . center')

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)

        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("assets/themes/wingman-ai.json")


        self.header = Header(self, height=74, corner_radius=0)
        self.header.grid(row=0, column=0, columnspan=2, sticky="we")

        self.context_view = ContextView(self, width=88, corner_radius=0, fg_color="transparent")
        self.context_view.grid(row=1, column=0, sticky="nesw")
