import re
import customtkinter as ctk
from gui.components.icon_button import IconButton

class KeyValueList(ctk.CTkScrollableFrame):
    def __init__(self, master, data, update_callback, key_name="", value_name="", **kwargs):
        super().__init__(master, **kwargs)
        self.data = data
        self.update_callback = update_callback

        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        padding = {"padx": 10, "pady": 10}

        if key_name or value_name:
            font = ("TkTextFont", 16, "bold")
            self.name_label = ctk.CTkLabel(self, text=key_name, font=font)
            self.name_label.grid(row=0, column=0, **padding)
            self.key_label = ctk.CTkLabel(self, text=value_name, font=font)
            self.key_label.grid(row=0, column=1, **padding)

        self.rows = self.__create_rows_from_data(1)

        _last_column, last_row = self.grid_size()
        add_name_entry = ctk.CTkEntry(self, placeholder_text="e.g. elevenlabs")
        add_name_entry.grid(row=last_row, column=0, **padding, sticky='esw')
        add_key_entry = ctk.CTkEntry(self, placeholder_text="API Key")
        add_key_entry.grid(row=last_row, column=1, **padding, sticky='esw')
        add_button = IconButton(self, icon="➕", emoji=True, size=20, hover_color="#00dd33", command=self.__add_entry)
        add_button.grid(row=last_row, column=2, **padding, sticky="s")
        self.add_row = {"name": add_name_entry, "key": add_key_entry, "btn": add_button}


    def update(self, data=None):
        if not data:
            data = self.data
            # TODO: minor change -> update step by step

        self.__delete_rows()
        self.rows = self.__create_rows_from_data(1)

        _last_column, last_row = self.grid_size()
        for _name, widget in self.add_row.items():
            widget.grid(row=last_row)


    def __create_rows_from_data(self, row_offset=0):
        padding = {"padx": 10, "pady": 10}

        rows = {}
        for i, key_name in enumerate(self.data):
            name_entry = ctk.CTkLabel(self, text=key_name)
            name_entry.grid(row=i+row_offset, column=0, **padding, sticky="e")
            key_entry = ctk.CTkLabel(self, text=self.data.get(key_name, ""), fg_color=("grey90", "grey10"), corner_radius=5)
            key_entry.grid(row=i+row_offset, column=1, **padding, sticky="w")
            del_button = IconButton(self, icon="🗑️", emoji=True, size=20, hover_color="#dd0033", command=lambda k=key_name: self.__delete_entry(k))
            del_button.grid(row=i+row_offset, column=2, **padding)
            rows[key_name] = {"name": name_entry, "key": key_entry, "btn": del_button}

        return rows


    def __delete_rows(self):
        for _r_key, row in self.rows.items():
            for _w_key, widget in row.items():
                widget.destroy()


    def __delete_entry(self, entry):
        del self.data[entry]
        self.update_callback(self.data)
        self.update()


    def __add_entry(self):
        new_name_entry = self.add_row["name"]
        new_key_entry = self.add_row["key"]
        if new_name_entry and new_key_entry:
            new_name = self.__sanitize_key(new_name_entry.get())
            new_key = new_key_entry.get()
            if new_name and new_name not in self.data:
                self.data[new_name] = new_key
                self.update_callback(self.data)
                new_name_entry.delete(0, 'end')
                new_key_entry.delete(0, 'end')
                self.update()


    def __sanitize_key(self, key: str) -> str:
        """Delete every non alphanumeric char, except vor underscore, dash and whitespaces

        Args:
            key (str): The string that should be sanitized

        Returns:
            str: The sanitized string
        """
        clean_key = re.sub(r'[^\w\s_-]', '', key)
        return clean_key.replace(" ", "_")
