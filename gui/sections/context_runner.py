import customtkinter as ctk
from gui.components.wingmen_list import WingmenList
from services.printr import Printr

printr = Printr()

class ContextRunner(ctk.CTkFrame):
    def __init__(self, master, context="", **kwargs):
        super().__init__(master, **kwargs)

        self.core = master.core
        self.core.load_context(context)
        self.status_var = ctk.StringVar(self, "Inactive 🔴", "status")
        tower = self.core.tower

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        context_title = context.title().replace("_", " ").strip() if context else "Default"
        self.status = ctk.CTkLabel(self, text=context_title, font=('TkHeadingFont', 20, "bold"), text_color="#EB154D")
        self.status.grid(row=0, column=0, padx=20, pady=10, sticky="w")

        # self.welcome_msg = ctk.CTkLabel(self, text="Welcome, Commander! o7")
        # self.welcome_msg.grid(row=0, column=0, padx=20, pady=10)

        self.status = ctk.CTkLabel(self,
                                   textvariable=self.status_var,
                                   anchor="e",
                                   fg_color=("grey70", "grey30"),
                                   corner_radius=10,
                                   width=90,
                                   pady=3)
        self.status.grid(row=0, column=0, padx=20, pady=10, sticky="e")

        wingmen = []
        if tower:
            wingmen = tower.get_wingmen()
        self.wingmen_list = WingmenList(self, wingmen=wingmen)
        self.wingmen_list.grid(row=1, column=0, padx=20, pady=10, sticky="ew")

        broken_wingmen = []
        if tower:
            tower.get_broken_wingmen()
        if len(broken_wingmen) > 0:
            self.broken_wingmen_list = WingmenList(self, wingmen=broken_wingmen, broken=True)
            self.broken_wingmen_list.grid(row=2, column=0, padx=20, pady=10, sticky="ew")

        self.terminal = ctk.CTkTextbox(self)
        self.terminal.grid(row=3, column=0, padx=20, pady=10, sticky="nesw")
        # TODO: Remove playground code ^^  -----------------------------------------------------------------------------
        # self.terminal.insert("1.0", "Lorem Wingsum\n")
        # self.terminal.insert("2.0",
        #                      "While users can modify the text in the text widget interactively, your program can also make changes. Adding text is done with the insert method, which we used above to provide an initial value for the text widget.")
        # self.terminal.tag_add("here", "1.1", "1.4")
        # self.terminal.tag_add("here", "1.10", "1.12")
        # self.terminal.tag_config("here", foreground="red")
        # self.terminal.tag_add("there", "2.2 wordstart", "2.12 wordend")
        # self.terminal.tag_config("there", foreground="green")
        # self.terminal.insert("4.0",
        #                      "Tags can also be provided when first inserting text. The insert method supports an optional parameter containing a list of one or more tags to add to the text being inserted.",
        #                      ("black"))
        # self.terminal.tag_config("black", background="black")
        # # --------------------------------------------------------------------------------------------------------------
        self.terminal.configure(state="disabled", wrap="none")
        printr.set_output("main", self.terminal)


        self.button = ctk.CTkButton(self, text="Run", command=self.toggle_listener)
        self.button.grid(row=4, column=0, padx=20, pady=10, sticky="ew")
        if not tower:
            printr.print_err(f"Could not load context.\nPlease check your context configuration for `{context_title}`.")
            self.button.configure(state="disabled")
        elif len(wingmen) <= 0:
            printr.print_warn(f"No runnable Wingman found for `{context_title}`.")
            self.button.configure(state="disabled")


    def toggle_listener(self):
        if self.core.active:
            self.core.deactivate()
            self.status_var.set("Inactive 🔴")
            self.button.configure(text="Run")
        else:
            self.core.activate()
            self.status_var.set("Active 🟢")
            self.button.configure(text="Stop")
