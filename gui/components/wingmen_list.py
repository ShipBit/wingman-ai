import customtkinter as ctk


class WingmenList(ctk.CTkFrame):
    def __init__(self, master, wingmen, broken=False, **kwargs):
        super().__init__(master, **kwargs)

        self.grid_columnconfigure(2, weight=1)
        self.grid_rowconfigure(0, weight=1)

        count = len(wingmen)
        self.wingmen_list = []

        if count:
            if broken:
                intro = f"Looks like {count} of your Wingmen {'is' if count == 1 else 'are'} not operational:"
            else:
                intro = f"You currently have {count} Wingm{'a' if count == 1 else 'e'}n registered"
            self.intro_label = ctk.CTkLabel(self, text=intro)
            self.intro_label.grid(row=0, column=0, columnspan=3, padx=10, pady=10)

            self.header_label = ctk.CTkLabel(
                self, text="Activation Key", text_color=("gray40", "gray55")
            )
            self.header_label.grid(row=1, column=0, padx=10)

            self.header_label2 = ctk.CTkLabel(
                self, text="Wingman to activate", text_color=("gray40", "gray55")
            )
            self.header_label2.grid(row=1, column=2, padx=10, sticky="w")

            for i, wingman in enumerate(wingmen):
                row_index = i + 2

                key = wingman["name"] if broken else wingman.get_record_key()
                key_label = ctk.CTkLabel(self, text=key)
                key_label.grid(row=row_index, column=0, padx=10)

                delimiter_label = ctk.CTkLabel(self, text="〉")
                delimiter_label.grid(row=row_index, column=1, padx=10)

                value = wingman["error"] if broken else wingman.name
                value_label = ctk.CTkLabel(self, text=value)
                value_label.grid(row=row_index, column=2, padx=10, sticky="w")
                self.wingmen_list.append([key_label, delimiter_label, value_label])
        else:
            if not broken:
                self.warning_label = ctk.CTkLabel(self, text="⚠️ WARNING ⚠️")
                self.warning_label.grid(row=0, column=1, padx=10, pady=10)
                self.warning_msg = ctk.CTkLabel(
                    self,
                    text="Seems like you don't have any functional wingmen registered.",
                )
                self.warning_msg.grid(row=1, column=1, padx=10, pady=0)
