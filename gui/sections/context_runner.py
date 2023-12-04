import customtkinter as ctk
from gui.components.icon import Icon
from gui.components.wingmen_list import WingmenList
from services.printr import Printr

printr = Printr()


class ContextRunner(ctk.CTkFrame):
    def __init__(self, master, context="", **kwargs):
        super().__init__(master, **kwargs)

        self.core = master.core
        self.core.load_context(context)
        # TODO: use icon
        self.status_var = ctk.StringVar(self, "Inactive", "status")
        tower = self.core.tower

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        context_title = (
            context.title().replace("_", " ").strip() if context else "Default"
        )
        self.title = ctk.CTkLabel(
            self,
            text=context_title,
            font=("TkHeadingFont", 20, "bold"),
            text_color="#EB154D",
        )
        self.title.grid(row=0, column=0, padx=20, pady=10, sticky="w")

        # TODO: Make this a component
        self.status = ctk.CTkLabel(
            self,
            textvariable=self.status_var,
            anchor="w",
            fg_color=("grey70", "grey30"),
            corner_radius=10,
            width=65,
            pady=3,
        )
        self.status.grid(row=0, column=0, padx=20, pady=10, sticky="e")
        self.status_icon_active = Icon("state_active", 16, False)
        self.status_icon_inactive = Icon("state_inactive", 16, False)
        self.status_led = ctk.CTkLabel(
            self, image=self.status_icon_inactive, text="", fg_color="transparent"
        )
        self.status_led.grid(row=0, column=0, padx=95, pady=10, sticky="e")

        wingmen = []
        if tower:
            wingmen = tower.get_wingmen()
        self.wingmen_list = WingmenList(self, wingmen=wingmen)
        self.wingmen_list.grid(row=1, column=0, padx=20, pady=10, sticky="ew")

        broken_wingmen = []
        if tower:
            broken_wingmen = tower.get_broken_wingmen()
        if len(broken_wingmen) > 0:
            self.broken_wingmen_list = WingmenList(
                self, wingmen=broken_wingmen, broken=True
            )
            self.broken_wingmen_list.grid(
                row=2, column=0, padx=20, pady=10, sticky="ew"
            )

        self.terminal = ctk.CTkTextbox(self)
        self.terminal.grid(row=3, column=0, padx=20, pady=10, sticky="nesw")
        self.terminal.configure(state="disabled", wrap="word")
        printr.set_output("main", self.terminal)
        if len(wingmen):
            printr.print(
                f"Press 'Run' to start your wingm{'e' if len(wingmen) > 1 else 'a'}n!"
            )

        self.button = ctk.CTkButton(
            self,
            text="Run",
            command=self.toggle_listener,
            height=45,
            font=("TkHeadingFont", 22, "bold"),
        )
        self.button.grid(row=4, column=0, padx=20, pady=10, sticky="ew")
        if not tower:
            printr.print_err(
                f"Could not load context.\nPlease check your context configuration for `{context_title}`."
            )
            self.button.configure(state="disabled")
        elif len(wingmen) <= 0:
            printr.print_warn(f"No runnable Wingman found for `{context_title}`.")
            self.button.configure(state="disabled")

    def toggle_listener(self):
        if self.core.active:
            self.core.deactivate()
            # TODO: use icon
            self.status_var.set("Inactive")
            self.status_led.configure(image=self.status_icon_inactive)
            self.button.configure(text="Run")
            printr.print(
                f"Your Wingman is now inactive.\nPress 'Run' to start listening again."
            )
        else:
            self.core.activate()
            # TODO: use icon
            self.status_var.set("Active")
            self.status_led.configure(image=self.status_icon_active)
            self.button.configure(text="Stop")
            printr.print(
                f"Your Wingman is now listening for commands.\nPress 'Stop' to stop listening."
            )
