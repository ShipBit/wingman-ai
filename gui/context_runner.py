import customtkinter as ctk
from gui.wingmen_list import WingmenList

class ContextRunner(ctk.CTkFrame):
    def __init__(self, master, context=None, **kwargs):
        super().__init__(master, **kwargs)

        self.core = master.core
        self.core.load_context(context)
        tower = self.core.tower

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)


        self.welcome_msg = ctk.CTkLabel(self, text="Welcome, Commander! o7")
        self.welcome_msg.grid(row=0, column=0, padx=20, pady=10,)

        wingmen = tower.get_wingmen()
        self.wingmen_list = WingmenList(self, wingmen=wingmen)
        self.wingmen_list.grid(row=1, column=0, padx=20, pady=10, sticky="ew")

        broken_wingmen = tower.get_broken_wingmen()
        if len(broken_wingmen) > 0:
            self.broken_wingmen_list = WingmenList(self, wingmen=broken_wingmen, broken=True)
            self.broken_wingmen_list.grid(row=2, column=0, padx=20, pady=10, sticky="ew")

        self.terminal = ctk.CTkTextbox(self)
        self.terminal.grid(row=3, column=0, padx=20, pady=10, sticky="nesw")
        self.terminal.insert("0.0", "Lorem Wingsum\n")

        self.button = ctk.CTkButton(self, text="Run", command=self.toggle_listener)
        self.button.grid(row=4, column=0, padx=20, pady=10, sticky="ew")


    def toggle_listener(self):
        if self.core.active:
            self.core.deactivate()
            self.button.configure(text="Run")
        else:
            self.core.activate()
            self.button.configure(text="Stop")
