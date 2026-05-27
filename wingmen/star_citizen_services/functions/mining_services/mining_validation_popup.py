import copy
import json
import locale
import re
import sys
from pathlib import Path
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

import cv2
from PIL import Image, ImageTk


DEBUG = False


def print_debug(to_print):
    if DEBUG:
        print(to_print)


class MiningValidationPopup(tk.Toplevel):
    THEME = {
        "bg": "#060f1d",
        "panel": "#0d1b2d",
        "panel_alt": "#102239",
        "border": "#1c3f64",
        "text": "#d7efff",
        "muted": "#83a4c6",
        "entry_bg": "#0a1730",
        "entry_border": "#2e6aa2",
        "accent": "#2ab8ff",
        "accent_hover": "#3ec5ff",
        "confirm": "#11b67a",
        "confirm_hover": "#14cb88",
        "danger": "#d8456a",
        "danger_hover": "#ef587f",
        "tooltip_bg": "#13233a",
        "tooltip_text": "#d5f0ff",
        "warning": "#ff8a7a",
    }
    SCROLLBAR_STYLE = "MiningValidation.Vertical.TScrollbar"
    H_SCROLLBAR_STYLE = "MiningValidation.Horizontal.TScrollbar"
    I18N = {
        "en": {
            "popup_title": "Mining Validation",
            "default_title": "Work-Order Validation",
            "banner_subtitle": "Validate extracted mining data and adjust JSON values where needed.",
            "json_block_title": "Recognized Data",
            "source_crop_title": "Snapshot",
            "save_position": "Save Position",
            "confirm": "Confirm",
            "abort": "Abort",
            "save_position_tooltip": "Save current popup position and size",
            "confirm_countdown": "Confirm ({seconds})",
            "autosubmit_countdown": "Autosubmit in {seconds}s",
            "autosubmit_paused": "Autosubmit paused",
        },
        "de": {
            "popup_title": "Mining Validierung",
            "default_title": "Work-Order Validierung",
            "banner_subtitle": "Prüfe extrahierte Mining-Daten und korrigiere JSON-Werte bei Bedarf.",
            "json_block_title": "Erkannte Daten",
            "source_crop_title": "Snapshot",
            "save_position": "Position speichern",
            "confirm": "Bestätigen",
            "abort": "Abbrechen",
            "save_position_tooltip": "Aktuelle Fensterposition und -größe speichern",
            "confirm_countdown": "Bestätigen ({seconds})",
            "autosubmit_countdown": "Autosubmit in {seconds}s",
            "autosubmit_paused": "Autosubmit pausiert",
        },
    }

    def __init__(
        self,
        master,
        work_order_info,
        anchor_coords=None,
        title=None,
        align="default",
        crop_image=None,
        config_dir=None,
        validation_context=None,
    ):
        super().__init__(master)
        self.withdraw()
        self._ui_ready = False
        self.theme = self.THEME
        self.lang = self._detect_language()
        self.translations = self.I18N.get(self.lang, self.I18N["en"])
        self.validation_context = validation_context or {}
        self.attributes("-topmost", True)
        self.overrideredirect(True)
        self.resizable(True, True)
        self.title(self._t("popup_title"))
        self.configure(bg=self.theme["bg"])
        self._configure_scrollbar_style()
        self._drag_offset_x = 0
        self._drag_offset_y = 0
        self.validated_data = None
        self.operation = "aborted"
        self.crop_image = crop_image
        if self.crop_image is not None and self.crop_image.__class__.__module__ == "numpy":
            self.crop_image = Image.fromarray(cv2.cvtColor(self.crop_image, cv2.COLOR_BGR2RGB))
        self.popup_variant_key = self._build_popup_variant_key(title, self.crop_image is not None)
        self.config_path = None
        if config_dir:
            try:
                self.config_path = Path(config_dir).expanduser().resolve() / f"popup_config_{self.popup_variant_key}.json"
            except Exception:
                self.config_path = Path(config_dir) / f"popup_config_{self.popup_variant_key}.json"
        self._last_saved_geometry = None
        self._tooltip_window = None
        self.base_countdown = 10
        self._has_invalid_fields = False
        self._validation_errors = []
        self._scan_validation_mode = self._is_ship_scan_payload(work_order_info)
        self._scan_percent_display_mode = self._scan_validation_mode
        self._interaction_window_handle = self._get_foreground_window()
        self._cursor_position_before_interaction = None
        self._focus_handoff_done = False
        self._global_click_poll_job = None
        self._last_global_click_state = self._read_global_mouse_buttons()
        self.icon_images = {}
        self.button_icon_images = {}
        self._load_ui_icons()

        banner_title_text = (title or self._t("default_title")).upper()

        display_data = self._prepare_scan_payload_for_display(work_order_info)
        json_str = json.dumps(display_data, indent=4, ensure_ascii=False)
        lines = json_str.splitlines() or ["{}"]
        num_lines = len(lines)
        max_line_chars = max(len(line) for line in lines)

        font_obj = tkfont.Font(font=("Consolas", 12))
        char_pixel_width = max(7, font_obj.measure("0"))
        line_pixel_height = max(14, font_obj.metrics("linespace"))
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()

        image_width = 0
        image_height = 0
        if self.crop_image is not None:
            image_width, image_height = self.crop_image.size

        image_panel_width = image_width + 40 if self.crop_image is not None else 0
        available_text_width_px = max(420, screen_width - image_panel_width - 120)
        available_text_height_px = max(260, screen_height - 300)
        max_visible_chars = max(44, available_text_width_px // char_pixel_width)
        max_visible_lines = max(14, available_text_height_px // line_pixel_height)
        self.text_width_chars = min(max_line_chars + 2, max_visible_chars)
        self.text_height_lines = min(num_lines + 1, max_visible_lines)

        text_pixel_width = (self.text_width_chars * char_pixel_width) + 50
        text_pixel_height = (self.text_height_lines * line_pixel_height) + 40

        if self.crop_image is not None:
            total_width = min(screen_width - 40, text_pixel_width + image_panel_width + 70)
            total_height = min(screen_height - 40, max(text_pixel_height + 220, image_height + 190))
        else:
            total_width = min(screen_width - 40, max(560, text_pixel_width + 80))
            total_height = min(screen_height - 40, max(400, text_pixel_height + 200))

        if anchor_coords:
            if align == "left":
                x = max(20, anchor_coords[0] - total_width)
                y = max(20, anchor_coords[1])
            elif align == "right":
                x = anchor_coords[0] + 20
                y = max(20, anchor_coords[1])
            else:
                x = anchor_coords[0] + 20
                y = max(20, anchor_coords[1])
        else:
            x = max(20, screen_width - total_width - 20)
            y = max(20, int((screen_height - total_height) / 2))

        self.rowconfigure(0, weight=0)
        self.rowconfigure(1, weight=1)
        self.rowconfigure(2, weight=0)
        self.rowconfigure(3, weight=0)
        self.columnconfigure(0, weight=1)
        if self.crop_image is not None:
            self.columnconfigure(1, weight=0)

        banner_frame = tk.Frame(
            self,
            bg=self.theme["panel_alt"],
            highlightthickness=1,
            highlightbackground=self.theme["border"],
            padx=12,
            pady=8,
        )
        banner_frame.grid(
            row=0,
            column=0,
            columnspan=2 if self.crop_image is not None else 1,
            sticky="ew",
            padx=14,
            pady=(14, 8),
        )
        banner_frame.columnconfigure(1, weight=1)

        self.cora_logo_tk = self._load_logo_image()
        if self.cora_logo_tk:
            tk.Label(
                banner_frame,
                image=self.cora_logo_tk,
                bg=self.theme["panel_alt"],
                bd=0,
            ).grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 10))

        banner_title = tk.Label(
            banner_frame,
            text=banner_title_text,
            bg=self.theme["panel_alt"],
            fg=self.theme["accent"],
            font=("Segoe UI", 14, "bold"),
            anchor="w",
        )
        banner_title.grid(row=0, column=1, sticky="w")
        banner_subtitle = tk.Label(
            banner_frame,
            text=self._t("banner_subtitle"),
            bg=self.theme["panel_alt"],
            fg=self.theme["muted"],
            font=("Segoe UI", 10),
            anchor="w",
            justify="left",
        )
        banner_subtitle.grid(row=1, column=1, sticky="ew", pady=(2, 0))
        self.banner_subtitle_label = banner_subtitle
        close_button = tk.Button(
            banner_frame,
            text="x",
            command=self.abort,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
            relief=tk.FLAT,
            bd=0,
            padx=8,
            pady=1,
            bg=self.theme["panel"],
            activebackground=self.theme["danger"],
            fg=self.theme["accent"],
            activeforeground="#ffffff",
        )
        close_button.grid(row=0, column=2, rowspan=2, sticky="e")

        for widget in (banner_frame, banner_title, banner_subtitle):
            widget.bind("<ButtonPress-1>", self._start_window_drag)
            widget.bind("<B1-Motion>", self._on_window_drag)
        banner_frame.bind("<Configure>", self._on_banner_resize, add="+")

        text_container = tk.Frame(
            self,
            bg=self.theme["panel"],
            highlightthickness=1,
            highlightbackground=self.theme["border"],
            padx=10,
            pady=10,
        )
        text_container.grid(row=1, column=0, sticky="nsew", padx=(14, 8 if self.crop_image is not None else 14), pady=(0, 8))
        text_container.rowconfigure(1, weight=1)
        text_container.columnconfigure(0, weight=1)

        tk.Label(
            text_container,
            text=self._t("json_block_title"),
            bg=self.theme["panel"],
            fg=self.theme["accent"],
            font=("Segoe UI", 11, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 8))

        editor_frame = tk.Frame(text_container, bg=self.theme["panel"])
        editor_frame.grid(row=1, column=0, sticky="nsew")
        editor_frame.rowconfigure(0, weight=1)
        editor_frame.columnconfigure(0, weight=1)

        self.text = tk.Text(
            editor_frame,
            wrap=tk.NONE,
            font=("Consolas", 12),
            bg=self.theme["entry_bg"],
            fg=self.theme["text"],
            insertbackground=self.theme["accent"],
            selectbackground="#124169",
            selectforeground=self.theme["text"],
            relief=tk.FLAT,
            bd=0,
            padx=10,
            pady=10,
            highlightthickness=1,
            highlightbackground=self.theme["entry_border"],
            highlightcolor=self.theme["accent"],
        )
        self.text.config(
            width=self.text_width_chars,
            height=self.text_height_lines,
        )
        self.v_scrollbar = ttk.Scrollbar(editor_frame, style=self.SCROLLBAR_STYLE, command=self.text.yview)
        self.h_scrollbar = ttk.Scrollbar(editor_frame, style=self.H_SCROLLBAR_STYLE, orient=tk.HORIZONTAL, command=self.text.xview)
        self.text.configure(yscrollcommand=self._on_text_vertical_scroll, xscrollcommand=self._on_text_horizontal_scroll)
        self.text.grid(row=0, column=0, sticky="nsew")
        self.v_scrollbar.grid(row=0, column=1, sticky="ns")
        self.h_scrollbar.grid(row=1, column=0, sticky="ew")
        self.text.insert(tk.END, json_str)
        self._has_invalid_fields = self._highlight_invalid_fields(json_str)
        self.after_idle(self._refresh_text_scrollbars)

        if self.crop_image is not None:
            image_frame = tk.Frame(
                self,
                bg=self.theme["panel_alt"],
                highlightthickness=1,
                highlightbackground=self.theme["border"],
                padx=10,
                pady=10,
            )
            image_frame.grid(row=1, column=1, sticky="n", padx=(8, 14), pady=(0, 8))
            tk.Label(
                image_frame,
                text=self._t("source_crop_title"),
                bg=self.theme["panel_alt"],
                fg=self.theme["muted"],
                font=("Segoe UI", 9, "bold"),
                anchor="w",
            ).pack(fill="x", pady=(0, 6))
            self.image_tk = ImageTk.PhotoImage(self.crop_image)
            image_label = tk.Label(image_frame, image=self.image_tk, bg=self.theme["panel_alt"], bd=0)
            image_label.pack(expand=True, fill="both")

        self.validation_frame = tk.Frame(
            self,
            bg="#2d0f17",
            highlightthickness=1,
            highlightbackground=self.theme["danger"],
            padx=10,
            pady=8,
        )
        self.validation_title_label = tk.Label(
            self.validation_frame,
            text="Validation",
            bg="#2d0f17",
            fg="#ffd3dd",
            font=("Segoe UI", 10, "bold"),
            anchor="w",
            justify="left",
        )
        self.validation_title_label.pack(fill="x")
        self.validation_message_label = tk.Label(
            self.validation_frame,
            text="",
            bg="#2d0f17",
            fg="#ffd3dd",
            font=("Segoe UI", 10),
            anchor="w",
            justify="left",
            wraplength=900,
        )
        self.validation_message_label.pack(fill="x", pady=(4, 0))
        self.validation_frame.grid(
            row=2,
            column=0,
            columnspan=2 if self.crop_image is not None else 1,
            sticky="ew",
            padx=14,
            pady=(0, 8),
        )
        self.validation_frame.grid_remove()

        button_frame = tk.Frame(self, bg=self.theme["bg"])
        if self.crop_image is not None:
            button_frame.grid(row=3, column=0, columnspan=2, sticky="ew", padx=14, pady=(0, 14))
        else:
            button_frame.grid(row=3, column=0, sticky="ew", padx=14, pady=(0, 14))

        button_inner = tk.Frame(button_frame, bg=self.theme["bg"])
        button_inner.pack(anchor="center")
        button_inner.grid_columnconfigure(0, weight=1)
        button_inner.grid_columnconfigure(1, weight=1)
        button_inner.grid_columnconfigure(2, weight=1)

        self.save_button = tk.Button(
            button_inner,
            text=self._t("save_position"),
            font=("Segoe UI", 11, "bold"),
            command=self._save_current_geometry,
            cursor="hand2",
            relief=tk.FLAT,
            bd=0,
            bg=self.theme["panel_alt"],
            activebackground=self.theme["panel"],
            fg=self.theme["accent"],
            activeforeground=self.theme["accent_hover"],
            padx=14,
            pady=10,
        )
        self.confirm_button = tk.Button(
            button_inner,
            text="",
            command=self.confirm,
            font=("Segoe UI", 11, "bold"),
            cursor="hand2",
            relief=tk.FLAT,
            bd=0,
            highlightthickness=0,
            padx=0,
            pady=0,
            bg=self.theme["bg"],
            activebackground=self.theme["bg"],
        )
        self.abort_button = tk.Button(
            button_inner,
            text="",
            command=self.abort,
            font=("Segoe UI", 11, "bold"),
            cursor="hand2",
            relief=tk.FLAT,
            bd=0,
            highlightthickness=0,
            padx=0,
            pady=0,
            bg=self.theme["bg"],
            activebackground=self.theme["bg"],
        )
        send_icon = self.button_icon_images.get("confirm")
        abort_icon = self.button_icon_images.get("abort")
        self._confirm_icon_loaded = bool(send_icon)
        self._abort_icon_loaded = bool(abort_icon)
        if send_icon:
            self.confirm_button.configure(image=send_icon)
        else:
            self.confirm_button.configure(
                text=self._t("confirm"),
                bg=self.theme["confirm"],
                activebackground=self.theme["confirm_hover"],
                fg="#eefcf8",
                activeforeground="#eefcf8",
                padx=14,
                pady=10,
            )
        if abort_icon:
            self.abort_button.configure(image=abort_icon)
        else:
            self.abort_button.configure(
                text=self._t("abort"),
                bg=self.theme["danger"],
                activebackground=self.theme["danger_hover"],
                fg="#ffecf0",
                activeforeground="#ffecf0",
                padx=14,
                pady=10,
            )
        self.save_button.grid(row=0, column=0, padx=(0, 12), pady=0, sticky="ew")
        self.confirm_button.grid(row=0, column=1, padx=12, pady=0, sticky="ew")
        self.abort_button.grid(row=0, column=2, padx=(12, 0), pady=0, sticky="ew")
        self._add_tooltip(self.save_button, self._t("save_position_tooltip"))
        self._add_tooltip(self.confirm_button, self._t("confirm"))
        self._add_tooltip(self.abort_button, self._t("abort"))

        self.autosubmit_label = tk.Label(
            button_frame,
            text="",
            bg=self.theme["bg"],
            fg=self.theme["muted"],
            font=("Segoe UI", 10),
            anchor="center",
            justify="center",
        )
        self.autosubmit_label.pack(anchor="center", pady=(8, 0))

        self.update_idletasks()
        width = self.winfo_reqwidth()
        height = self.winfo_reqheight()
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        if align == "left":
            x = 20
        elif align == "right":
            x = screen_w - width - 20
        elif anchor_coords:
            x = anchor_coords[0] + 20
        else:
            x = screen_w - width - 20
        if anchor_coords:
            y = max(20, anchor_coords[1])
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
        max_width = max(420, screen_w - 40)
        max_height = max(320, screen_h - 40)
        min_width = max(460, min(width, max_width))
        min_height = max(360, min(height, max_height))
        width = min(max_width, max(min_width, size.get("width", width)))
        height = min(max_height, max(min_height, size.get("height", height)))
        x = position.get("x", x)
        y = position.get("y", y)
        width, height, x, y = self._clamp_geometry_to_screen(width, height, x, y, screen_w, screen_h)
        self.base_countdown = self.popup_config.get("countdown_seconds", default_config["countdown_seconds"])
        self._refresh_validation_feedback_from_editor(adjust_countdown=False)
        if self._scan_validation_mode:
            self.base_countdown = 5
            self.countdown_seconds = 15 if self._validation_errors else 5
        else:
            self.countdown_seconds = self.base_countdown * (2 if self._has_invalid_fields else 1)
        self.minsize(min_width, min_height)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.update_idletasks()
        self._last_saved_geometry = self._get_current_geometry()
        self.bind("<Return>", lambda e: self.confirm())
        self.bind("<Escape>", lambda e: self.abort())
        self.text.edit_modified(False)
        self.text.bind("<<Modified>>", self._on_text_modified, add="+")

        self.auto_confirm_job = None
        self.countdown_active = True
        self._buttons_locked = True
        self._unlock_pending = False
        self._update_confirm_button_text()
        self.auto_confirm_job = self.after(1000, self._run_auto_confirm_countdown)

        self.bind_all("<ButtonPress>", self._on_first_mouse_press, add="+")
        self.bind_all("<ButtonRelease>", self._on_first_mouse_release, add="+")
        self.after(0, self._restore_game_focus_if_locked)
        self.after(80, self._start_global_click_watch)
        self._ui_ready = True

    def _configure_scrollbar_style(self):
        style = ttk.Style(self)
        style.configure(
            self.SCROLLBAR_STYLE,
            troughcolor=self.theme["panel"],
            background=self.theme["accent"],
            bordercolor=self.theme["panel"],
            arrowcolor=self.theme["panel"],
        )
        style.map(
            self.SCROLLBAR_STYLE,
            background=[("active", self.theme["accent_hover"])],
        )
        style.configure(
            self.H_SCROLLBAR_STYLE,
            troughcolor=self.theme["panel"],
            background=self.theme["accent"],
            bordercolor=self.theme["panel"],
            arrowcolor=self.theme["panel"],
        )
        style.map(
            self.H_SCROLLBAR_STYLE,
            background=[("active", self.theme["accent_hover"])],
        )

    def _start_window_drag(self, event):
        self._drag_offset_x = event.x_root - self.winfo_x()
        self._drag_offset_y = event.y_root - self.winfo_y()

    def _on_window_drag(self, event):
        new_x = max(0, event.x_root - self._drag_offset_x)
        new_y = max(0, event.y_root - self._drag_offset_y)
        self.geometry(f"+{new_x}+{new_y}")

    def _on_banner_resize(self, event):
        if not hasattr(self, "banner_subtitle_label"):
            return
        # Keep subtitle readable when logo + close button reduce title area width.
        wrap_length = max(260, event.width - 260)
        self.banner_subtitle_label.configure(wraplength=wrap_length)

    def _on_text_vertical_scroll(self, first, last):
        if hasattr(self, "v_scrollbar"):
            self.v_scrollbar.set(first, last)
            if float(first) <= 0.0 and float(last) >= 1.0:
                self.v_scrollbar.grid_remove()
            else:
                self.v_scrollbar.grid()

    def _on_text_horizontal_scroll(self, first, last):
        if hasattr(self, "h_scrollbar"):
            self.h_scrollbar.set(first, last)
            if float(first) <= 0.0 and float(last) >= 1.0:
                self.h_scrollbar.grid_remove()
            else:
                self.h_scrollbar.grid()

    def _refresh_text_scrollbars(self):
        x_first, x_last = self.text.xview()
        y_first, y_last = self.text.yview()
        self._on_text_horizontal_scroll(str(x_first), str(x_last))
        self._on_text_vertical_scroll(str(y_first), str(y_last))

    @staticmethod
    def show_popup(
        work_order_info,
        anchor_coords=None,
        title=None,
        align="default",
        crop_image=None,
        config_dir=None,
        validation_context=None,
    ):
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
            validation_context=validation_context,
        )
        if not popup._ui_ready:
            popup.update_idletasks()
        popup.deiconify()
        popup.lift()
        try:
            popup.focus_force()
        except Exception:
            pass
        root.wait_window(popup)
        return popup.validated_data, popup.operation

    def confirm(self):
        if self._buttons_locked:
            return
        self._cancel_auto_confirm()
        self._restore_input_context_after_interaction()
        print_debug("Data confirmed")
        try:
            updated_text = self.text.get("1.0", tk.END).strip()
            self.validated_data = json.loads(updated_text)
            self._apply_scan_percent_display_to_payload(self.validated_data)
            self._apply_ship_scan_fallback_defaults(self.validated_data)
        except Exception as e:
            print_debug(f"JSON parsing error: {e}")
            self.validated_data = None
        self.operation = "confirmed"
        self.destroy()

    def abort(self):
        if self._buttons_locked:
            return
        self._cancel_auto_confirm()
        self._restore_input_context_after_interaction()
        print_debug("Process aborted")
        self.validated_data = None
        self.operation = "aborted"
        self.destroy()

    def _update_confirm_button_text(self):
        if hasattr(self, "autosubmit_label"):
            self.autosubmit_label.config(
                text=self._t("autosubmit_countdown").format(seconds=self.countdown_seconds),
                fg=self.theme["muted"],
            )

    def _run_auto_confirm_countdown(self):
        self.auto_confirm_job = None
        self.countdown_seconds -= 1
        if self.countdown_seconds <= 0:
            self.countdown_active = False
            self._buttons_locked = False
            self.confirm()
            return
        self._update_confirm_button_text()
        self.auto_confirm_job = self.after(1000, self._run_auto_confirm_countdown)

    def _cancel_auto_confirm(self):
        if self.auto_confirm_job is not None:
            self.after_cancel(self.auto_confirm_job)
            self.auto_confirm_job = None
        if not getattr(self, "_confirm_icon_loaded", False):
            self.confirm_button.config(text=self._t("confirm"))
        if hasattr(self, "autosubmit_label"):
            self.autosubmit_label.config(
                text=self._t("autosubmit_paused"),
                fg=self.theme["warning"],
            )
        self.countdown_active = False

    def _on_text_modified(self, _event):
        try:
            if not self.text.edit_modified():
                return
            self.text.edit_modified(False)
        except tk.TclError:
            return
        self._refresh_validation_feedback_from_editor(adjust_countdown=self.countdown_active and self._buttons_locked)

    def _refresh_validation_feedback_from_editor(self, adjust_countdown=False):
        try:
            json_str = self.text.get("1.0", tk.END).strip()
        except Exception:
            return
        self._has_invalid_fields = self._highlight_invalid_fields(json_str)
        errors = []

        parsed = None
        if self._scan_validation_mode:
            try:
                parsed = json.loads(json_str) if json_str else {}
            except Exception:
                errors.append(self._scan_issue("invalid_json"))
            else:
                errors.extend(self._validate_ship_scan_payload(parsed))

        self._set_validation_errors(errors)

        if adjust_countdown and self._scan_validation_mode:
            self.countdown_seconds = 15 if errors else 5
            self._update_confirm_button_text()

    def _set_validation_errors(self, errors):
        self._validation_errors = errors
        if not errors:
            self.validation_frame.grid_remove()
            return

        title = "Validierungswarnungen" if self.lang == "de" else "Validation Warnings"
        self.validation_title_label.configure(text=title)
        self.validation_message_label.configure(text="\n".join(f"- {msg}" for msg in errors))
        self.validation_frame.grid()

    @staticmethod
    def _is_ship_scan_payload(payload):
        return isinstance(payload, dict) and isinstance(payload.get("captureShipRockScan"), dict)

    @staticmethod
    def _normalize_enum_key(value):
        if not isinstance(value, str):
            return ""
        return "".join(ch for ch in value.upper() if ch.isalnum())

    @classmethod
    def _normalize_rock_type_key(cls, value):
        key = cls._normalize_enum_key(value)
        for suffix in ("DEPOSITS", "DEPOSIT", "CLUSTERS", "CLUSTER", "ROCKS", "ROCK"):
            if key.endswith(suffix) and len(key) > len(suffix):
                key = key[: -len(suffix)]
        return key

    @staticmethod
    def _normalize_scan_ore_name(value):
        if not isinstance(value, str):
            return ""
        value = value.upper()
        value = re.sub(r"\([^)]*\)", "", value)
        value = value.replace(" ", "").replace("-", "").replace("_", "")
        value = value.replace("MATERIALS", "MATERIAL")
        for suffix in ("RAW", "ORE"):
            if value.endswith(suffix) and len(value) > len(suffix):
                value = value[: -len(suffix)]
        return value

    @staticmethod
    def _to_float(value):
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            cleaned = value.strip().replace("%", "").replace(",", ".")
            try:
                return float(cleaned)
            except ValueError:
                return None
        return None

    @staticmethod
    def _contains_ocr_swap_digits(value):
        if value is None:
            return False
        text = str(value).strip()
        if not text:
            return False
        # Rule 3: warn if digit 0 or 8 appears in numeric OCR fields.
        return ("0" in text) or ("8" in text)

    def _scan_issue(self, key, **kwargs):
        messages = {
            "de": {
                "invalid_json": "JSON ist ungültig und kann nicht geparst werden.",
                "missing_payload": "Kein gültiger 'captureShipRockScan'-Payload vorhanden.",
                "composition_sum": "Regel 1: Summe der Zusammensetzungsprozente muss 1 ± 0.01 sein (aktuell: {value:.4f}).",
                "inst_zero": "Regel 2: 'inst' ist 0. Fallback beim Senden: 1.0.",
                "res_zero": "Regel 2: 'res' ist 0. Fallback beim Senden: 0.01.",
                "zero_or_eight": "Regel 3: Mögliche OCR-Vertauschung (Ziffer 0/8) gefunden in: {fields}.",
                "rocktype_unmapped": "Regel 4: Rock Type ist nicht erkannt oder nicht mapbar: '{value}'.",
                "rocktype_missing_map": "Regel 4: Rock-Type-Mappingdaten fehlen.",
                "ore_unmapped": "Regel 5: Inhaltsstoffe nicht mapbar: {ores}.",
                "ore_missing_map": "Regel 5: Ore-Mappingdaten fehlen.",
                "inert_missing": "Regel 1: INERT MATERIAL fehlt in der Zusammensetzung.",
            },
            "en": {
                "invalid_json": "JSON is invalid and cannot be parsed.",
                "missing_payload": "No valid 'captureShipRockScan' payload found.",
                "composition_sum": "Rule 1: Composition percent sum must be 1 ± 0.01 (current: {value:.4f}).",
                "inst_zero": "Rule 2: 'inst' is 0. Send fallback: 1.0.",
                "res_zero": "Rule 2: 'res' is 0. Send fallback: 0.01.",
                "zero_or_eight": "Rule 3: Possible OCR digit swap (0/8) found in: {fields}.",
                "rocktype_unmapped": "Rule 4: Rock type is missing or cannot be mapped: '{value}'.",
                "rocktype_missing_map": "Rule 4: Rock type mapping data is missing.",
                "ore_unmapped": "Rule 5: Ores cannot be mapped: {ores}.",
                "ore_missing_map": "Rule 5: Ore mapping data is missing.",
                "inert_missing": "Rule 1: INERT MATERIAL is missing from composition.",
            },
        }
        lang = "de" if self.lang == "de" else "en"
        return messages[lang][key].format(**kwargs)

    def _validate_ship_scan_payload(self, payload):
        issues = []
        scan_payload = payload.get("captureShipRockScan")
        if not isinstance(scan_payload, dict):
            issues.append(self._scan_issue("missing_payload"))
            return issues

        ship_ores = self.validation_context.get("ship_ores") or []
        rock_types = self.validation_context.get("rock_types") or []
        ore_map = {
            self._normalize_enum_key(name): name for name in ship_ores if isinstance(name, str)
        }
        rock_map = {
            self._normalize_enum_key(name): name for name in rock_types if isinstance(name, str)
        }

        inst_value = self._to_float(scan_payload.get("inst"))
        res_value = self._to_float(scan_payload.get("res"))
        if inst_value == 0:
            issues.append(self._scan_issue("inst_zero"))
        if res_value == 0:
            issues.append(self._scan_issue("res_zero"))

        suspicious_fields = []
        numeric_candidates = {
            "mass": scan_payload.get("mass"),
            "inst": scan_payload.get("inst"),
            "res": scan_payload.get("res"),
        }
        ores = scan_payload.get("ores", [])
        if isinstance(ores, list):
            for idx, ore in enumerate(ores, start=1):
                if isinstance(ore, dict):
                    numeric_candidates[f"ore[{idx}].percent"] = ore.get("percent")

        for field, raw_value in numeric_candidates.items():
            num = self._to_float(raw_value)
            if num is None:
                continue
            if (
                abs(num) < 1e-12
                or abs(num - 8.0) < 1e-12
                or self._contains_ocr_swap_digits(raw_value)
            ):
                suspicious_fields.append(field)

        rock_type_raw = scan_payload.get("rockType")
        if not rock_map:
            issues.append(self._scan_issue("rocktype_missing_map"))
        else:
            rock_key = self._normalize_rock_type_key(rock_type_raw)
            if rock_key not in rock_map:
                issues.append(self._scan_issue("rocktype_unmapped", value=rock_type_raw))

        if not ore_map:
            issues.append(self._scan_issue("ore_missing_map"))

        composition_sum = 0.0
        has_inert = False
        unmapped_ores = []
        if not isinstance(ores, list) or not ores:
            unmapped_ores.append("<empty>")
        else:
            for ore in ores:
                if not isinstance(ore, dict):
                    continue
                ore_raw = ore.get("ore")
                ore_key = self._normalize_enum_key(ore_raw)
                normalized_key = self._normalize_scan_ore_name(ore_raw)
                mapped = ore_map.get(ore_key) or ore_map.get(normalized_key)
                if normalized_key in ("INERTMATERIAL", "INERTMATERIALS"):
                    mapped = "INERTMATERIAL"
                if not mapped:
                    unmapped_ores.append(str(ore_raw))
                if mapped == "INERTMATERIAL":
                    has_inert = True

                percent_value = self._to_float(ore.get("percent"))
                if percent_value is None:
                    continue
                if percent_value > 1:
                    percent_value = percent_value / 100
                composition_sum += percent_value

        if unmapped_ores:
            issues.append(self._scan_issue("ore_unmapped", ores=", ".join(sorted(set(unmapped_ores)))))
        # Full ore sums of 99.99% or 100% are valid without INERT material.
        full_ore_sum_without_inert = (not has_inert) and (abs(composition_sum - 1.0) <= 0.0002)
        if full_ore_sum_without_inert:
            suspicious_fields = [field for field in suspicious_fields if not field.startswith("ore[")]

        if suspicious_fields:
            issues.append(self._scan_issue("zero_or_eight", fields=", ".join(suspicious_fields)))

        if not has_inert and not full_ore_sum_without_inert:
            issues.append(self._scan_issue("inert_missing"))
        if abs(composition_sum - 1.0) > 0.01:
            issues.append(self._scan_issue("composition_sum", value=composition_sum))

        return issues

    def _apply_ship_scan_fallback_defaults(self, payload):
        if not self._scan_validation_mode or not isinstance(payload, dict):
            return
        scan_payload = payload.get("captureShipRockScan")
        if not isinstance(scan_payload, dict):
            return

        inst_value = self._to_float(scan_payload.get("inst"))
        res_value = self._to_float(scan_payload.get("res"))
        if inst_value == 0:
            scan_payload["inst"] = 1.0
        if res_value == 0:
            scan_payload["res"] = 0.01

    def _prepare_scan_payload_for_display(self, payload):
        if not self._scan_percent_display_mode or not isinstance(payload, dict):
            return payload

        display_payload = copy.deepcopy(payload)
        scan_payload = display_payload.get("captureShipRockScan")
        if not isinstance(scan_payload, dict):
            return display_payload

        ores = scan_payload.get("ores")
        if not isinstance(ores, list):
            return display_payload

        for ore in ores:
            if not isinstance(ore, dict):
                continue
            percent_value = self._to_float(ore.get("percent"))
            if percent_value is None:
                continue
            # UI shows percentages (0-100) to match in-game scan display.
            if percent_value <= 1:
                ore["percent"] = round(percent_value * 100, 4)
            else:
                ore["percent"] = percent_value

        return display_payload

    def _apply_scan_percent_display_to_payload(self, payload):
        if not self._scan_percent_display_mode or not isinstance(payload, dict):
            return

        scan_payload = payload.get("captureShipRockScan")
        if not isinstance(scan_payload, dict):
            return

        ores = scan_payload.get("ores")
        if not isinstance(ores, list):
            return

        for ore in ores:
            if not isinstance(ore, dict):
                continue
            percent_value = self._to_float(ore.get("percent"))
            if percent_value is None:
                continue
            # Convert UI percentage format back to backend ratio format (0-1).
            if percent_value > 1:
                ore["percent"] = percent_value / 100
            else:
                ore["percent"] = percent_value

    def _prepare_popup_manual_interaction(self):
        if self._focus_handoff_done:
            return
        self._cursor_position_before_interaction = self._get_cursor_position()
        unblock_mouse = self._temporarily_block_mouse_input()
        self._focus_popup_window()
        self.update_idletasks()
        self._move_cursor_to_abort_button()
        self.after(220, unblock_mouse)
        self._focus_handoff_done = True

    def _move_cursor_to_abort_button(self):
        self.update_idletasks()
        target_x = self.abort_button.winfo_rootx() + (self.abort_button.winfo_width() // 2)
        target_y = self.abort_button.winfo_rooty() + (self.abort_button.winfo_height() // 2)
        self._set_cursor_position(target_x, target_y)

    def _restore_input_context_after_interaction(self):
        self._stop_global_click_watch()
        if not self._focus_handoff_done:
            return
        unblock_mouse = self._temporarily_block_mouse_input()
        if self._cursor_position_before_interaction:
            self._set_cursor_position(
                self._cursor_position_before_interaction[0],
                self._cursor_position_before_interaction[1],
            )
        self._restore_game_focus()
        self.after(220, unblock_mouse)

    def _focus_popup_window(self):
        self.lift()
        try:
            self.focus_force()
        except Exception:
            pass
        if sys.platform != "win32":
            return
        try:
            import ctypes

            ctypes.windll.user32.SetForegroundWindow(int(self.winfo_id()))
        except Exception as exc:
            print_debug(f"SetForegroundWindow(popup) failed: {exc}")

    def _restore_game_focus(self):
        if not self._interaction_window_handle or sys.platform != "win32":
            return
        try:
            import ctypes

            ctypes.windll.user32.SetForegroundWindow(int(self._interaction_window_handle))
        except Exception as exc:
            print_debug(f"SetForegroundWindow(game) failed: {exc}")

    def _restore_game_focus_if_locked(self):
        if not self._focus_handoff_done:
            self._restore_game_focus()

    def _start_global_click_watch(self):
        if sys.platform != "win32":
            return
        if not self._buttons_locked or self._focus_handoff_done:
            return
        self._last_global_click_state = self._read_global_mouse_buttons()
        self._poll_global_click_watch()

    def _stop_global_click_watch(self):
        if self._global_click_poll_job is None:
            return
        try:
            self.after_cancel(self._global_click_poll_job)
        except Exception:
            pass
        self._global_click_poll_job = None

    def _poll_global_click_watch(self):
        self._global_click_poll_job = None
        if not self.winfo_exists() or not self._buttons_locked or self._focus_handoff_done:
            return
        left_down, right_down = self._read_global_mouse_buttons()
        prev_left, prev_right = self._last_global_click_state
        self._last_global_click_state = (left_down, right_down)
        if (left_down and not prev_left) or (right_down and not prev_right):
            self._handle_first_manual_input(triggered_by_global_click=True)
            return
        self._global_click_poll_job = self.after(30, self._poll_global_click_watch)

    @staticmethod
    def _get_foreground_window():
        if sys.platform != "win32":
            return None
        try:
            import ctypes

            return ctypes.windll.user32.GetForegroundWindow()
        except Exception:
            return None

    @staticmethod
    def _get_cursor_position():
        if sys.platform != "win32":
            return None
        try:
            import ctypes

            class POINT(ctypes.Structure):
                _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

            point = POINT()
            if ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
                return int(point.x), int(point.y)
        except Exception:
            return None
        return None

    @staticmethod
    def _set_cursor_position(x, y):
        if sys.platform != "win32":
            return
        try:
            import ctypes

            ctypes.windll.user32.SetCursorPos(int(x), int(y))
        except Exception:
            pass

    @staticmethod
    def _read_global_mouse_buttons():
        if sys.platform != "win32":
            return False, False
        try:
            import ctypes

            left_down = bool(ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000)
            right_down = bool(ctypes.windll.user32.GetAsyncKeyState(0x02) & 0x8000)
            return left_down, right_down
        except Exception:
            return False, False

    @staticmethod
    def _temporarily_block_mouse_input():
        if sys.platform != "win32":
            return lambda: None
        try:
            import ctypes

            success = bool(ctypes.windll.user32.BlockInput(True))
            if not success:
                return lambda: None
        except Exception as exc:
            print_debug(f"BlockInput failed: {exc}")
            return lambda: None

        released = {"done": False}

        def unblock():
            if released["done"]:
                return
            released["done"] = True
            try:
                ctypes.windll.user32.BlockInput(False)
            except Exception as unblock_exc:
                print_debug(f"BlockInput release failed: {unblock_exc}")

        return unblock

    def _handle_first_manual_input(self, triggered_by_global_click=False):
        if not self._buttons_locked:
            return
        self._cancel_auto_confirm()
        self._prepare_popup_manual_interaction()
        if triggered_by_global_click:
            self._unlock_interaction_controls()

    def _unlock_interaction_controls(self):
        self._buttons_locked = False
        self._unlock_pending = False
        self.unbind_all("<ButtonPress>")
        self.unbind_all("<ButtonRelease>")
        self._stop_global_click_watch()

    def _on_first_mouse_press(self, _event):
        if not self._buttons_locked:
            return
        self._handle_first_manual_input()
        self._unlock_pending = True
        return "break"

    def _on_first_mouse_release(self, _event):
        if not self._buttons_locked and not self._unlock_pending:
            return
        self._unlock_interaction_controls()
        return "break"

    def _save_current_geometry(self):
        if not self.config_path:
            return
        geometry = self._get_current_geometry()
        if geometry == self._last_saved_geometry:
            return
        config = {
            "countdown_seconds": self.base_countdown,
            "position": {"x": geometry["x"], "y": geometry["y"]},
            "size": {"width": geometry["width"], "height": geometry["height"]},
        }
        self.popup_config = config
        self._write_popup_config(config)
        self._last_saved_geometry = geometry

    def _add_tooltip(self, widget, text):
        def enter(_):
            self._show_tooltip(widget, text)

        def leave(_):
            self._hide_tooltip()

        widget.bind("<Enter>", enter)
        widget.bind("<Leave>", leave)

    def _show_tooltip(self, widget, text):
        self._hide_tooltip()
        self._tooltip_window = tw = tk.Toplevel(widget)
        tw.wm_overrideredirect(True)
        tw.attributes("-topmost", True)
        x = widget.winfo_rootx() + widget.winfo_width() // 2
        y = widget.winfo_rooty() + widget.winfo_height() + 4
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            tw,
            text=text,
            background=self.theme["tooltip_bg"],
            foreground=self.theme["tooltip_text"],
            relief="solid",
            borderwidth=1,
            font=("Segoe UI", 9),
            padx=4,
            pady=2,
        )
        label.pack(ipadx=4, ipady=2)

    def _hide_tooltip(self):
        if self._tooltip_window is not None:
            try:
                self._tooltip_window.destroy()
            except Exception:
                pass
            self._tooltip_window = None

    @staticmethod
    def _build_popup_variant_key(title, has_crop_image):
        if title:
            title_key = re.sub(r"[^a-z0-9]+", "_", title.strip().lower()).strip("_")
            if not title_key:
                title_key = "default"
        else:
            title_key = "default"
        image_key = "with_crop" if has_crop_image else "no_crop"
        return f"{title_key}_{image_key}"

    @staticmethod
    def _clamp_geometry_to_screen(width, height, x, y, screen_w, screen_h):
        width = max(1, min(int(width), int(screen_w)))
        height = max(1, min(int(height), int(screen_h)))
        max_x = max(0, int(screen_w) - width)
        max_y = max(0, int(screen_h) - height)
        x = min(max(0, int(x)), max_x)
        y = min(max(0, int(y)), max_y)
        return width, height, x, y

    def _get_current_geometry(self):
        self.update_idletasks()
        geometry_str = self.geometry()
        match = re.match(r"^(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$", geometry_str)
        if match:
            return {
                "width": int(match.group(1)),
                "height": int(match.group(2)),
                "x": int(match.group(3)),
                "y": int(match.group(4)),
            }
        return {
            "width": int(self.winfo_width()),
            "height": int(self.winfo_height()),
            "x": int(self.winfo_x()),
            "y": int(self.winfo_y()),
        }

    def _highlight_invalid_fields(self, json_str):
        try:
            self.text.tag_delete("invalid_value")
            self.text.tag_delete("ocr_swap_digit")
        except tk.TclError:
            pass
        self.text.tag_configure("invalid_value", foreground=self.theme["warning"])
        self.text.tag_configure("ocr_swap_digit", foreground=self.theme["danger"])
        patterns = [
            r":\s+null\b",
            r":\s+0(?:\.0+)?(?=[\s,\}\]])",
            r':\s+""',
        ]
        invalid_found = False
        for pattern in patterns:
            for match in re.finditer(pattern, json_str):
                start_idx = f"1.0 + {match.start()}c"
                end_idx = f"1.0 + {match.end()}c"
                self.text.tag_add("invalid_value", start_idx, end_idx)
                invalid_found = True

        if self._scan_validation_mode:
            # Highlight suspicious OCR digits (0/8) inside numeric JSON values.
            number_value_pattern = r":\s*(-?\d+(?:[.,]\d+)?)\s*(?=[,\}\]])"
            for match in re.finditer(number_value_pattern, json_str):
                number_text = match.group(1)
                number_start = match.start(1)
                for offset, char in enumerate(number_text):
                    if char in ("0", "8"):
                        start_idx = f"1.0 + {number_start + offset}c"
                        end_idx = f"1.0 + {number_start + offset + 1}c"
                        self.text.tag_add("ocr_swap_digit", start_idx, end_idx)
                        invalid_found = True
        return invalid_found

    def _load_popup_config(self, default_config):
        config = copy.deepcopy(default_config)
        if not self.config_path:
            return config
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            if not self.config_path.exists():
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

    def _detect_language(self):
        try:
            lang = (locale.getlocale()[0] or "").lower()
        except Exception:
            lang = ""
        if not lang and hasattr(locale, "getdefaultlocale"):
            try:
                lang = (locale.getdefaultlocale()[0] or "").lower()
            except Exception:
                lang = ""
        return "de" if lang.startswith("de") else "en"

    def _t(self, key):
        return self.translations.get(key, self.I18N["en"].get(key, key))

    def _asset_base_directories(self):
        root_assets = Path(__file__).resolve().parents[4] / "assets"
        return [root_assets / "cora-sc", root_assets / "sc-cora"]

    def _load_icon_asset(self, file_name, size=None):
        for asset_dir in self._asset_base_directories():
            icon_path = asset_dir / file_name
            if not icon_path.exists():
                continue
            try:
                image = Image.open(icon_path)
                if size:
                    if hasattr(Image, "Resampling"):
                        image = image.resize(size, Image.Resampling.LANCZOS)
                    else:
                        image = image.resize(size, Image.LANCZOS)
                return ImageTk.PhotoImage(image)
            except Exception as exc:
                print_debug(f"Failed to load icon asset '{icon_path}': {exc}")
        return None

    def _load_ui_icons(self):
        self.button_icon_images = {
            "confirm": self._load_icon_asset("check.png"),
            "abort": self._load_icon_asset("abort.png"),
        }
        self.icon_images.update(self.button_icon_images)

    def _load_logo_image(self):
        return self._load_icon_asset("Cora_Box.png")
