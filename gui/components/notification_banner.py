from typing import Any
import customtkinter as ctk
from gui.components.icon_button import IconButton
from services.printr import Printr


class NotificationBanner(ctk.CTkFrame):
    notification_level: dict[Printr.CHANNEL, Any] = {
        "info": {"color": ("#113399", "#113399"), "font_color": "white"},
        "warning": {"color": ("yellow", "yellow"), "font_color": ("black", "black")},
        "error": {"color": "#dd0033", "font_color": "white"}
    }

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self._grid_position = {"row":0, "column":0}
        self.visible = False
        self.printr = Printr()
        self.grid_columnconfigure(0, weight=1)

        self.close_button = IconButton(self,
                                icon="✖️",
                                emoji=True,
                                size=32,
                                themed=False,
                                hover_color="white",
                                command=self.hide)
        self.close_button.grid(row=0, column=3, padx=5, pady=5, sticky="e")

        self.msg_vars = {}
        self.labels = {}
        for level, level_config in self.notification_level.items():
            self.msg_vars[level] = ctk.StringVar(self, name=level)
            self.msg_vars[level].trace_add("write", lambda *args, lvl=level: self.__change_handler(lvl))
            self.labels[level] = ctk.CTkLabel(self,
                                              pady=5,
                                              textvariable=self.msg_vars[level],
                                              text_color=level_config.get("font_color", ("black", "white")))
            self.printr.set_output(level, self.msg_vars[level])


    def __change_handler(self, level):
        for label_level, label in self.labels.items():
            if label_level == level:
                label.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
                banner_color = self.notification_level.get(level, []).get("color", "grey50")
                self.configure(fg_color=banner_color)
                # TODO: improve close_button color
                # btn_color = self.notification_level.get(level, []).get("font_color", "black")
                # self.close_button.configure(text_color=btn_color)
                self.show()
            else:
                label.grid_forget()


    def set_grid_position(self, row=0, column=0):
        self._grid_position = {"row":row, "column":column}
        if self.visible:
            self.show()


    def hide(self):
        if self.visible:
            self.grid_forget()
            self.visible = False


    def show(self):
        self.grid(
            row=self._grid_position.get("row", 0),
            column=self._grid_position.get("column", 0),
            sticky="ew"
        )
        self.visible = True
