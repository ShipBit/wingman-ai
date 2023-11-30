import customtkinter as ctk

class ContextRunner(ctk.CTkFrame):
    def __init__(self, master, context=None, **kwargs):
        super().__init__(master, **kwargs)

        #self.key_logger = keyboard.Listener(on_press=self.on_press, on_release=self.on_release, target=self.target)
        self.core = master.core
        self.core.load_context(context)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.label = ctk.CTkLabel(self, text="Wingman AI", font=("Barlow", 30))
        self.label.grid(row=0, column=0, padx=20, pady=20)

        self.button = ctk.CTkButton(self, text="Run", command=self.toggle_listener)
        self.button.grid(row=1, column=0, padx=20, pady=20, sticky="ew")


    def toggle_listener(self):
        if self.core.active:
            self.core.deactivate()
            self.button.configure(text="Run")
        else:
            self.core.activate()
            self.button.configure(text="Stop")
