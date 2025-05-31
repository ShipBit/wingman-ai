import copy
import tkinter as tk
from tkinter import ttk
import tkinter.font as tkfont
import json

from PIL import Image, ImageTk
from screeninfo import get_monitors
import cv2  # hinzugefügt

from gui.root import WingmanUI
from wingmen.star_citizen_services.functions.uex_v2.uex_api_module import UEXApi2
from wingmen.star_citizen_services.helper import find_best_match as search
from wingmen.star_citizen_services.functions.uex_update_services.commodity_price_validator import CommodityPriceValidator


DEBUG = False


def print_debug(to_print):
    if DEBUG:
        print(to_print)


class MiningValidationPopup(tk.Toplevel):
    def __init__(
        self,
        master,
        work_order_info,
        anchor_coords=None,
        title="Work-Order Validierung",
        align="default",
        crop_image=None,
    ):
        super().__init__(master)
        self.attributes('-topmost', True)  # Overlay: Popup über alle anderen Fenster
        self.title(title)
        self.validated_data = None
        self.operation = "aborted"
        self.crop_image = crop_image

        # Bereite JSON-String vor und bestimme Maße für den Textbereich
        json_str = json.dumps(work_order_info, indent=4, ensure_ascii=False)
        lines = json_str.splitlines()
        num_lines = len(lines)

        # replace arbitrary factors with real font metrics
        font_obj = tkfont.Font(font=("Helvetica", 12))
        text_pixel_width  = max(font_obj.measure(line) for line in lines)
        text_pixel_height = font_obj.metrics("linespace") * num_lines

        # Wenn ein crop_image vorhanden, bestimme Bildgrößen und setze Gesamtmaße
        if self.crop_image is not None:
            if self.crop_image.__class__.__module__ == "numpy":
                self.crop_image = Image.fromarray(cv2.cvtColor(self.crop_image, cv2.COLOR_BGR2RGB))
            image_width, image_height = self.crop_image.size
            extra_margin = 40  # erhöhter Extra-Wert, um dem Bild mehr Breite zu geben
            adjusted_image_width = image_width + extra_margin
            total_width  = text_pixel_width + adjusted_image_width
            total_height = max(text_pixel_height, image_height)
        else:
            total_width  = max(400, text_pixel_width)
            total_height = max(250, text_pixel_height)

        # Positionierung
        if anchor_coords:
            if align == "left":
                x = anchor_coords[0] - total_width
                y = anchor_coords[1]
            else:
                offset = 20
                x = anchor_coords[0] + offset
                y = anchor_coords[1]
        else:
            screen_width = self.winfo_screenwidth()
            screen_height = self.winfo_screenheight()
            x = screen_width - total_width - 20
            y = int((screen_height - total_height) / 2)
        self.geometry(f"{total_width}x{total_height}+{x}+{y}")

        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=0)
        if self.crop_image is not None:
            # Zwei Spalten: Textbereich und Bild
            if align == "left":
                text_frame  = tk.Frame(self, width=text_pixel_width)
                image_frame = tk.Frame(self, width=adjusted_image_width)
                text_frame.grid(row=0, column=0, sticky="nsew")
                image_frame.grid(row=0, column=1, sticky="nsew")
            else:
                image_frame = tk.Frame(self, width=adjusted_image_width)
                text_frame  = tk.Frame(self, width=text_pixel_width)
                image_frame.grid(row=0, column=0, sticky="nsew")
                text_frame.grid(row=0, column=1, sticky="nsew")
            text_container = text_frame
        else:
            text_container = tk.Frame(self)
            text_container.grid(row=0, column=0, sticky="nsew")
        text_container.rowconfigure(0, weight=1)
        text_container.columnconfigure(0, weight=1)
        
        self.text = tk.Text(text_container, wrap=tk.NONE, font=("Helvetica", 12))
        # Breite in Zeichen bleibt, hier optional anpassen
        max_chars = max(len(line) for line in lines)
        self.text.config(width=min(max_chars, 80))
        scrollbar = ttk.Scrollbar(text_container, command=self.text.yview)
        self.text.configure(yscrollcommand=scrollbar.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.text.insert(tk.END, json_str)
        
        if self.crop_image is not None:
            self.image_tk = ImageTk.PhotoImage(self.crop_image)
            image_label = tk.Label(image_frame, image=self.image_tk)
            image_label.pack(expand=True, fill="both")
        
        # Button-Leiste über volle Breite, Buttons zentriert
        button_frame = tk.Frame(self)
        if self.crop_image is not None:
            button_frame.grid(row=1, column=0, columnspan=2, sticky="ew")
        else:
            button_frame.grid(row=1, column=0, sticky="ew")
        # flexible Ränder links (0) und rechts (3)
        button_frame.grid_columnconfigure(0, weight=1)
        button_frame.grid_columnconfigure(3, weight=1)
        # Buttons in Mitte (Spalten 1 und 2)
        confirm_button = tk.Button(button_frame, text="Bestätigen", bg="green", fg="white", font=("Helvetica", 14, "bold"), command=self.confirm)
        abort_button   = tk.Button(button_frame, text="Abbrechen", bg="red", fg="white",   font=("Helvetica", 14, "bold"), command=self.abort)
        confirm_button.grid(row=0, column=1, padx=10, pady=10)
        abort_button.grid  (row=0, column=2, padx=10, pady=10)
        
        self.update_idletasks()
        # passe Fenstergröße an den benötigten Inhalt an (inkl. Dekoration)
        width  = self.winfo_reqwidth()
        height = self.winfo_reqheight()
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        x = (screen_w - width) // 2
        y = (screen_h - height) // 2
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.bind("<Return>", lambda e: self.confirm())
        self.bind("<Escape>", lambda e: self.abort())
        self.focus_force()

    @staticmethod
    def show_popup(work_order_info, anchor_coords=None, title="Work-Order Validierung", align="default", crop_image=None):
        root = tk._get_default_root() or tk.Tk()
        root.withdraw()
        popup = MiningValidationPopup(root, work_order_info, anchor_coords=anchor_coords, title=title, align=align, crop_image=crop_image)
        root.wait_window(popup)
        return popup.validated_data, popup.operation

    def confirm(self):
        print_debug("Daten bestätigt")
        try:
            updated_text = self.text.get("1.0", tk.END).strip()
            self.validated_data = json.loads(updated_text)
        except Exception as e:
            print_debug("JSON parsing error: " + str(e))
            self.validated_data = None
        self.operation = "confirmed"
        self.destroy()

    def abort(self):
        print_debug("Prozess abgebrochen")
        self.validated_data = None
        self.operation = "aborted"
        self.destroy()
