import copy
import json
import re
from pathlib import Path
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

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
        config_dir=None,
    ):
        super().__init__(master)
        self.attributes('-topmost', True)  # Overlay: Popup über alle anderen Fenster
        self.title(title)
        self.validated_data = None
        self.operation = "aborted"
        self.crop_image = crop_image
        self.config_path = None
        if config_dir:
            try:
                self.config_path = Path(config_dir).expanduser().resolve() / "popup_config.json"
            except Exception:
                self.config_path = Path(config_dir) / "popup_config.json"
        self._last_saved_geometry = None
        self._save_job = None
        self._initial_geometry_applied = False
        self._has_invalid_fields = False

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
            # Zwei Spalten: Bild links, Text rechts (unabhängig von 'align')
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
        self._has_invalid_fields = self._highlight_invalid_fields(json_str)
        
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
        self.confirm_button = tk.Button(button_frame, text="Bestätigen", bg="green", fg="white", font=("Helvetica", 14, "bold"), command=self.confirm)
        self.abort_button   = tk.Button(button_frame, text="Abbrechen", bg="red", fg="white",   font=("Helvetica", 14, "bold"), command=self.abort)
        self.confirm_button.grid(row=0, column=1, padx=10, pady=10)
        self.abort_button.grid  (row=0, column=2, padx=10, pady=10)
        
        self.update_idletasks()
        # passe Fenstergröße an den benötigten Inhalt an (inkl. Dekoration)
        width  = self.winfo_reqwidth()
        height = self.winfo_reqheight()
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        # Positionierung basierend auf align
        offset = 20
        if align == "left":
            x = 20
        elif align == "right":
            x = screen_w - width - 20
        elif anchor_coords:
            x = anchor_coords[0] + offset
        else:
            x = screen_w - width - 20
        if anchor_coords:
            y = anchor_coords[1]
        else:
            y = (screen_h - height) // 2
        default_config = {
            "countdown_seconds": 10,
            "position": {"x": x, "y": y},
            "size": {"width": width, "height": height},
        }
        self.popup_config = self._load_popup_config(default_config)
        size = self.popup_config.get("size", {})
        position = self.popup_config.get("position", {})
        width = size.get("width", width)
        height = size.get("height", height)
        x = position.get("x", x)
        y = position.get("y", y)
        self.base_countdown = self.popup_config.get("countdown_seconds", default_config["countdown_seconds"])
        self.countdown_seconds = self.base_countdown * (2 if self._has_invalid_fields else 1)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self._last_saved_geometry = {"width": width, "height": height, "x": x, "y": y}
        self._initial_geometry_applied = True
        self.bind("<Configure>", self._on_configure)
        # entferne direkten Fokus, setze Verzögerung von 5 Sekunden
        self.bind("<Return>", lambda e: self.confirm())
        self.bind("<Escape>", lambda e: self.abort())
        self.after(5000, self.focus_force)

        # Auto-Bestätigung nach Countdown
        self.auto_confirm_job = None
        self.countdown_active = True
        self._buttons_locked = True   # Sperre Buttons bis nach dem ersten Klick
        self._unlock_pending = False  # Wird true nach dem ersten Klick-Press
        self._update_confirm_button_text()
        self.auto_confirm_job = self.after(1000, self._run_auto_confirm_countdown)

        # Erster Mausklick (irgendwo) stoppt den Countdown; dieser Klick löst keine Aktion aus.
        self.bind_all("<ButtonPress>", self._on_first_mouse_press, add="+")
        self.bind_all("<ButtonRelease>", self._on_first_mouse_release, add="+")

        # Cursor auf den Abbrechen-Button legen, sobald alles gerendert ist
        self.foreground_window_before_cursor_move = self._get_foreground_window()
        self.after(0, self._move_cursor_to_abort_button)

    @staticmethod
    def show_popup(work_order_info, anchor_coords=None, title="Work-Order Validierung", align="default", crop_image=None, config_dir=None):
        root = tk._get_default_root() or tk.Tk()
        root.withdraw()
        popup = MiningValidationPopup(
            root,
            work_order_info,
            anchor_coords=anchor_coords,
            title=title,
            align=align,
            crop_image=crop_image,
            config_dir=config_dir,
        )
        root.wait_window(popup)
        return popup.validated_data, popup.operation

    def confirm(self):
        # Ignoriere Button-Klicks solange der Countdown aktiv ist.
        if self._buttons_locked:
            return
        self._cancel_auto_confirm()
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
        # Ignoriere Button-Klicks solange der Countdown aktiv ist.
        if self._buttons_locked:
            return
        self._cancel_auto_confirm()
        print_debug("Prozess abgebrochen")
        self.validated_data = None
        self.operation = "aborted"
        self.destroy()

    def destroy(self):
        # Stelle sicher, dass ein ausstehendes Geometry-Save ausgeführt wird.
        self._flush_pending_save()
        super().destroy()

    def _update_confirm_button_text(self):
        self.confirm_button.config(text=f"Bestätigen ({self.countdown_seconds})")

    def _run_auto_confirm_countdown(self):
        self.auto_confirm_job = None
        self.countdown_seconds -= 1
        if self.countdown_seconds <= 0:
            self.countdown_active = False
            self._buttons_locked = False  # Automatisches Bestätigen soll nicht blockiert werden
            self.confirm()
            return
        self._update_confirm_button_text()
        self.auto_confirm_job = self.after(1000, self._run_auto_confirm_countdown)

    def _cancel_auto_confirm(self):
        if self.auto_confirm_job is not None:
            self.after_cancel(self.auto_confirm_job)
            self.auto_confirm_job = None
        self.confirm_button.config(text="Bestätigen")
        self.countdown_active = False
        # Countdown ist aus, aber Buttons bleiben gesperrt bis nach dem ersten Klick-Release.

    def _move_cursor_to_abort_button(self):
        # Kurz den Fokus auf das Popup holen, Cursor bewegen, danach Fokus zurückgeben
        self.focus_force()
        self.update_idletasks()
        window_x = self.winfo_rootx()
        window_y = self.winfo_rooty()
        target_x = self.abort_button.winfo_rootx() - window_x + self.abort_button.winfo_width() // 2
        target_y = self.abort_button.winfo_rooty() - window_y + self.abort_button.winfo_height() // 2
        self.event_generate("<Motion>", warp=True, x=target_x, y=target_y)
        self.after(50, self._restore_foreground_window)

    def _get_foreground_window(self):
        try:
            import ctypes
            return ctypes.windll.user32.GetForegroundWindow()
        except Exception:
            return None

    def _restore_foreground_window(self):
        if not self.foreground_window_before_cursor_move:
            return
        try:
            import ctypes
            ctypes.windll.user32.SetForegroundWindow(self.foreground_window_before_cursor_move)
        except Exception:
            pass

    def _on_first_mouse_press(self, _event):
        if not self._buttons_locked:
            return
        # Stopp den Countdown, halte Buttons aber bis zum Loslassen gesperrt.
        self._cancel_auto_confirm()
        self._unlock_pending = True
        return "break"

    def _on_first_mouse_release(self, _event):
        if not self._buttons_locked and not self._unlock_pending:
            return
        # Nach dem ersten Klick-Release: Buttons freigeben.
        self._buttons_locked = False
        self._unlock_pending = False
        self.unbind_all("<ButtonPress>")
        self.unbind_all("<ButtonRelease>")
        return "break"

    def _on_configure(self, event):
        if event.widget is not self or not self._initial_geometry_applied:
            return
        if self._save_job is not None:
            self.after_cancel(self._save_job)
        self._save_job = self.after(300, self._save_current_geometry)

    def _save_current_geometry(self):
        self._save_job = None
        if not self.config_path or not self._initial_geometry_applied:
            return
        geometry = {
            "width": self.winfo_width(),
            "height": self.winfo_height(),
            "x": self.winfo_x(),
            "y": self.winfo_y(),
        }
        if geometry == self._last_saved_geometry:
            return
        config = {
            # Countdown aus der geladenen Konfiguration unverändert lassen
            "countdown_seconds": self.popup_config.get("countdown_seconds", 10),
            "position": {"x": geometry["x"], "y": geometry["y"]},
            "size": {"width": geometry["width"], "height": geometry["height"]},
        }
        self.popup_config = config
        self._write_popup_config(config)
        self._last_saved_geometry = geometry

    def _highlight_invalid_fields(self, json_str):
        """Markiere leere/null/0-Werte im JSON rot und liefere True, falls etwas markiert wurde."""
        try:
            self.text.tag_delete("invalid_value")
        except tk.TclError:
            pass
        self.text.tag_configure("invalid_value", foreground="red")
        patterns = [
            r":\s+null\b",
            r":\s+0(?:\.0+)?(?=[\s,\}\]])",
            r":\s+\"\"",
        ]
        invalid_found = False
        for pattern in patterns:
            for match in re.finditer(pattern, json_str):
                start_idx = f"1.0 + {match.start()}c"
                end_idx = f"1.0 + {match.end()}c"
                self.text.tag_add("invalid_value", start_idx, end_idx)
                invalid_found = True
        return invalid_found

    def _flush_pending_save(self):
        if self._save_job is not None:
            self.after_cancel(self._save_job)
            self._save_job = None
            self._save_current_geometry()
        else:
            self._save_current_geometry()

    def _load_popup_config(self, default_config):
        config = copy.deepcopy(default_config)
        if not self.config_path:
            return config
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            if not self.config_path.exists():
                self._write_popup_config(config)
                return config
            with open(self.config_path, "r", encoding="utf-8") as cfg:
                loaded = json.load(cfg)
            config["countdown_seconds"] = loaded.get("countdown_seconds", config["countdown_seconds"])
            config["position"].update(loaded.get("position", {}))
            config["size"].update(loaded.get("size", {}))
        except Exception as exc:
            print_debug(f"Failed to load popup config: {exc}")
        return config

    def _write_popup_config(self, config):
        if not self.config_path:
            return
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as cfg:
                json.dump(config, cfg, ensure_ascii=False, indent=2)
        except Exception as exc:
            print_debug(f"Failed to write popup config: {exc}")
