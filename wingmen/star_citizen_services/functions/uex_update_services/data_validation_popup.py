import copy
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
import json
from pathlib import Path
import locale

from PIL import Image, ImageTk
from screeninfo import get_monitors

from gui.root import WingmanUI

from wingmen.star_citizen_services.functions.uex_v2.uex_api_module import UEXApi2
from wingmen.star_citizen_services.helper import find_best_match as search
from wingmen.star_citizen_services.functions.uex_update_services.commodity_price_validator import CommodityPriceValidator


DEBUG = False


def print_debug(to_print):
    if DEBUG:
        print(to_print)


class OverlayPopup(tk.Toplevel):
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
        "success": "#11b67a",
        "success_hover": "#14cb88",
        "danger": "#d8456a",
        "danger_hover": "#ef587f",
        "table_bg": "#0a1628",
        "table_alt": "#0e1c30",
        "table_select": "#124169",
        "warning": "#ff8a7a",
        "edited": "#ffd385",
    }
    TREE_STYLE = "UexValidation.Treeview"
    V_SCROLL_STYLE = "UexValidation.Vertical.TScrollbar"
    H_SCROLL_STYLE = "UexValidation.Horizontal.TScrollbar"
    TABLE_COLUMNS = (
        "transmit",
        "commodity_name",
        "code",
        "inventory_scu",
        "inventory_state",
        "price_per_unit",
        "multiplier",
    )
    DISPLAY_COLUMNS = (
        "transmit",
        "commodity_name",
        "inventory_scu",
        "inventory_state",
        "price_per_unit",
        "multiplier",
    )
    VALIDATION_COLUMN = "#0"
    I18N = {
        "en": {
            "popup_title": "UEX Data-Runner Validation",
            "banner_title": "UEX Data-Runner Validation",
            "recognized_terminal_operation": "Recognized Terminal operation",
            "op_buy": "BUY",
            "op_sell": "SELL",
            "terminal": "Terminal",
            "prices_title": "Detected Commodity Prices",
            "workflow_title": "Workflow",
            "workflow_text": (
                "Switch BUY/SELL using the toggle.\n"
                "Edit terminal name by clicking the name or pencil icon.\n"
                "Type at least three letters to get matching terminal suggestions.\n"
                "Transmit toggles upload, Double-Click edits table values."
            ),
            "send_button": "Send to UEX",
            "abort_button": "Abort",
            "price_crop_title": "Terminal Snapshot",
            "col_transmit": "Transmit",
            "col_commodity_name": "Commodity Name",
            "col_code": "Code",
            "col_inventory_scu": "Inventory SCU",
            "col_inventory_state": "Inventory State",
            "col_price_per_unit": "Price",
            "col_multiplier": "Multiplier",
            "col_validation": "Validation",
            "validation_all_plausible": "All plausible",
            "validation_price_not_plausible": "Price not plausible",
            "validation_user_updated": "Manually adjusted",
            "validation_commodity_not_found": "Commodity not found",
            "validation_invalid_price_format": "Invalid price format",
            "validation_unknown": "Unknown validation state",
        },
        "de": {
            "popup_title": "UEXData-Runner Validierung",
            "banner_title": "UEX Data-Runner Validierung",
            "recognized_terminal_operation": "Erkannte Terminal-Operation",
            "op_buy": "KAUF",
            "op_sell": "VERKAUF",
            "terminal": "Terminal",
            "prices_title": "Erkannte Warenpreise",
            "workflow_title": "Workflow",
            "workflow_text": (
                "BUY/SELL per Toggle wechseln.\n"
                "Terminalname mit Klick auf Name oder Stift bearbeiten.\n"
                "Ab drei Buchstaben erscheinen passende Terminal-Vorschläge.\n"
                "Transmit toggelt den Upload, Double-Click bearbeitet Tabellenfelder."
            ),
            "send_button": "An UEX senden",
            "abort_button": "Abbrechen",
            "price_crop_title": "Terminal Snapshot",
            "col_transmit": "Übertragen",
            "col_commodity_name": "Ware",
            "col_code": "Code",
            "col_inventory_scu": "Bestand SCU",
            "col_inventory_state": "Bestandsstatus",
            "col_price_per_unit": "Preis",
            "col_multiplier": "Multiplikator",
            "col_validation": "Validierung",
            "validation_all_plausible": "Alles plausibel",
            "validation_price_not_plausible": "Preis nicht plausibel",
            "validation_user_updated": "Manuell angepasst",
            "validation_commodity_not_found": "Ware nicht gefunden",
            "validation_invalid_price_format": "Ungültiges Preisformat",
            "validation_unknown": "Unbekannter Validierungsstatus",
        },
    }

    def __init__(self, master, terminal_prices, operation, screenshot_prices, cropped_screenshot_prices, cropped_screenshot_location, initial_terminal_name=""):
        super().__init__(master)
        self.withdraw()
        self._ui_ready = False

        self.theme = self.THEME
        self.lang = self._detect_language()
        self.translations = self.I18N.get(self.lang, self.I18N["en"])
        self.terminal_prices = self._normalize_terminal_prices_input(terminal_prices)
        self.location_name_hint = str(initial_terminal_name or "").strip()
        first_terminal_price = self.terminal_prices[0] if self.terminal_prices else {}
        self.selected_terminal_id = first_terminal_price.get("id_terminal")
        self.selected_terminal_name = (
            first_terminal_price.get("terminal_name")
            or self.location_name_hint
            or "Select terminal"
        )
        self.updated_data = copy.deepcopy(screenshot_prices)
        self.user_updated_data = copy.deepcopy(screenshot_prices)
        self.operation = str(operation).lower() if operation else "buy"
        self.validation_messages = {}
        self.validation_tooltip_window = None
        self.validation_tooltip_target = None
        self.icon_images = {}
        self.validation_icon_images = {}
        self.button_icon_images = {}
        self.uex_service = None
        self.terminals_by_id = {}
        self.terminal_catalog = []
        self.tradeport_suggestion_terminals = []
        self._tradeport_suggestion_click_active = False

        print_debug(f"got data to validate: \n{json.dumps(self.updated_data, indent=2)}")

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.resizable(False, False)
        self.configure(bg=self.theme["bg"])
        self.title(self._t("popup_title"))
        self._configure_tree_style()
        self._drag_offset_x = 0
        self._drag_offset_y = 0

        self._load_ui_icons()

        self.main_frame = tk.Frame(
            self,
            bg=self.theme["bg"],
            padx=12,
            pady=12,
            highlightthickness=1,
            highlightbackground=self.theme["border"],
        )
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        self.main_frame.columnconfigure(0, weight=1)
        self.main_frame.rowconfigure(1, weight=1)

        banner_frame = tk.Frame(
            self.main_frame,
            bg=self.theme["panel_alt"],
            highlightthickness=1,
            highlightbackground=self.theme["border"],
            padx=12,
            pady=8,
        )
        banner_frame.grid(row=0, column=0, sticky="ew")
        banner_frame.columnconfigure(1, weight=1)

        cora_logo_path = Path(__file__).resolve().parents[4] / "assets" / "cora-sc" / "Cora_Box.png"
        if cora_logo_path.exists():
            cora_image = Image.open(cora_logo_path)
            self.cora_logo_tk = ImageTk.PhotoImage(cora_image)
            tk.Label(banner_frame, image=self.cora_logo_tk, bg=self.theme["panel_alt"], bd=0).grid(row=0, column=0, sticky="w", padx=(0, 10))

        banner_title = tk.Label(
            banner_frame,
            text=self._t("banner_title"),
            font=("Segoe UI", 15, "bold"),
            fg=self.theme["accent"],
            bg=self.theme["panel_alt"],
            anchor="w",
        )
        banner_title.grid(row=0, column=1, sticky="w")
        close_button = tk.Button(
            banner_frame,
            text="x",
            command=self.abort_process,
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
        close_button.grid(row=0, column=2, sticky="e")

        for widget in (banner_frame, banner_title):
            widget.bind("<ButtonPress-1>", self._start_window_drag)
            widget.bind("<B1-Motion>", self._on_window_drag)

        body_frame = tk.Frame(self.main_frame, bg=self.theme["bg"])
        body_frame.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        body_frame.columnconfigure(0, weight=3)
        body_frame.columnconfigure(1, weight=2)

        self.content_frame = tk.Frame(
            body_frame,
            bg=self.theme["bg"],
        )
        self.content_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        operation_card = tk.Frame(
            self.content_frame,
            bg=self.theme["panel"],
            highlightthickness=1,
            highlightbackground=self.theme["border"],
            padx=12,
            pady=10,
        )
        operation_card.pack(fill=tk.X, pady=(0, 10))
        tk.Label(
            operation_card,
            text=self._t("recognized_terminal_operation"),
            font=("Segoe UI", 11, "bold"),
            fg=self.theme["accent"],
            bg=self.theme["panel"],
            anchor="w",
        ).pack(fill=tk.X)

        operation_row = tk.Frame(operation_card, bg=self.theme["panel"])
        operation_row.pack(fill=tk.X, pady=(8, 0))
        operation_row.columnconfigure(0, weight=1)
        operation_row.columnconfigure(1, weight=1)

        toggle_frame = tk.Frame(operation_row, bg=self.theme["panel"])
        toggle_frame.grid(row=0, column=0, sticky="w", padx=(0, 12))
        self.buy_button = tk.Button(
            toggle_frame,
            text=self._t("op_buy"),
            command=lambda: self._set_operation("buy"),
            font=("Segoe UI", 12, "bold"),
            padx=14,
            pady=7,
            cursor="hand2",
            relief=tk.FLAT,
            bd=0,
        )
        self.buy_button.pack(side=tk.LEFT, padx=(0, 6))
        self.sell_button = tk.Button(
            toggle_frame,
            text=self._t("op_sell"),
            command=lambda: self._set_operation("sell"),
            font=("Segoe UI", 12, "bold"),
            padx=14,
            pady=7,
            cursor="hand2",
            relief=tk.FLAT,
            bd=0,
        )
        self.sell_button.pack(side=tk.LEFT)

        terminal_frame = tk.Frame(operation_row, bg=self.theme["panel"])
        terminal_frame.grid(row=0, column=1, sticky="ew")
        tk.Label(
            terminal_frame,
            text=self._t("terminal"),
            font=("Segoe UI", 10, "bold"),
            fg=self.theme["muted"],
            bg=self.theme["panel"],
            anchor="w",
        ).pack(fill=tk.X)

        terminal_value_frame = tk.Frame(terminal_frame, bg=self.theme["panel"])
        terminal_value_frame.pack(fill=tk.X, pady=(4, 0))
        terminal_value_frame.columnconfigure(0, weight=1)

        self.tradeport_name_label = tk.Label(
            terminal_value_frame,
            text=self.selected_terminal_name,
            font=("Segoe UI", 12, "bold"),
            fg=self.theme["text"],
            bg=self.theme["entry_bg"],
            padx=10,
            pady=6,
            cursor="hand2",
            anchor="w",
            highlightthickness=1,
            highlightbackground=self.theme["entry_border"],
        )
        self.tradeport_name_label.grid(row=0, column=0, sticky="ew")
        self.tradeport_name_label.bind("<Button-1>", self._activate_tradeport_edit)

        self.tradeport_edit_button = tk.Button(
            terminal_value_frame,
            text="✎",
            font=("Segoe UI", 12, "bold"),
            command=self._activate_tradeport_edit,
            cursor="hand2",
            relief=tk.FLAT,
            bd=0,
            bg=self.theme["panel_alt"],
            activebackground=self.theme["accent"],
            fg=self.theme["accent"],
            activeforeground=self.theme["bg"],
            padx=9,
            pady=5,
        )
        self.tradeport_edit_button.grid(row=0, column=1, padx=(6, 0))

        self.tradeport_entry = tk.Entry(
            terminal_value_frame,
            bg=self.theme["entry_bg"],
            fg=self.theme["text"],
            insertbackground=self.theme["accent"],
            highlightthickness=1,
            highlightbackground=self.theme["entry_border"],
            highlightcolor=self.theme["accent"],
            relief=tk.FLAT,
            bd=0,
            font=("Segoe UI", 12, "bold"),
        )
        self.tradeport_entry.insert(0, self.selected_terminal_name)
        self.tradeport_entry.bind("<Return>", self._submit_tradeport_edit)
        self.tradeport_entry.bind("<FocusOut>", self._submit_tradeport_edit)
        self.tradeport_entry.bind("<Escape>", self._cancel_tradeport_edit)
        self.tradeport_entry.bind("<KeyRelease>", self._on_tradeport_entry_key_release)
        self.tradeport_entry.bind("<Down>", self._on_tradeport_entry_down_key)
        self.tradeport_suggestion_listbox = tk.Listbox(
            terminal_value_frame,
            height=6,
            bg=self.theme["entry_bg"],
            fg=self.theme["text"],
            selectbackground=self.theme["accent"],
            selectforeground=self.theme["bg"],
            relief=tk.FLAT,
            bd=0,
            highlightthickness=1,
            highlightbackground=self.theme["entry_border"],
            font=("Segoe UI", 11),
        )
        self.tradeport_suggestion_listbox.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.tradeport_suggestion_listbox.grid_remove()
        self.tradeport_suggestion_listbox.bind("<ButtonPress-1>", self._on_tradeport_suggestion_press)
        self.tradeport_suggestion_listbox.bind("<ButtonRelease-1>", self._on_tradeport_suggestion_click)
        self.tradeport_suggestion_listbox.bind("<Double-Button-1>", self._on_tradeport_suggestion_click)
        self.tradeport_suggestion_listbox.bind("<Return>", self._on_tradeport_suggestion_enter)
        self.tradeport_suggestion_listbox.bind("<Escape>", self._cancel_tradeport_edit)
        self._tradeport_edit_active = False

        prices_card = tk.Frame(
            self.content_frame,
            bg=self.theme["panel"],
            highlightthickness=1,
            highlightbackground=self.theme["border"],
            padx=12,
            pady=10,
        )
        prices_card.pack(fill=tk.X, pady=(0, 10))
        tk.Label(
            prices_card,
            text=self._t("prices_title"),
            font=("Segoe UI", 11, "bold"),
            fg=self.theme["accent"],
            bg=self.theme["panel"],
            anchor="w",
        ).pack(fill=tk.X)

        table_container = tk.Frame(prices_card, bg=self.theme["panel"])
        table_container.pack(fill=tk.X, expand=False, pady=(8, 10))
        self.table_container = table_container

        visible_rows = max(1, len(self.updated_data))

        self.data_table = ttk.Treeview(
            table_container,
            style=self.TREE_STYLE,
            height=visible_rows,
            columns=self.TABLE_COLUMNS,
            displaycolumns=self.DISPLAY_COLUMNS,
            show="tree headings",
        )
        self.data_table.heading("#0", text=self._t("col_validation"))
        self.data_table.column("#0", width=68, minwidth=58, anchor=tk.CENTER, stretch=False)
        for col in self.data_table["columns"]:
            self.data_table.heading(col, text=self._t(f"col_{col}"))

        self.data_table.column("transmit", width=90, anchor=tk.CENTER)
        self.data_table.column("commodity_name", width=250, anchor=tk.W)
        self.data_table.column("code", width=0, minwidth=0, anchor=tk.CENTER)
        self.data_table.column("inventory_scu", width=120, anchor=tk.CENTER)
        self.data_table.column("inventory_state", width=170, anchor=tk.CENTER)
        self.data_table.column("price_per_unit", width=130, anchor=tk.CENTER)
        self.data_table.column("multiplier", width=95, anchor=tk.CENTER)
        for col in self.TABLE_COLUMNS:
            self.data_table.column(col, stretch=False)

        self.data_table.grid(row=0, column=0, sticky="nsew")
        table_container.rowconfigure(0, weight=1)
        table_container.columnconfigure(0, weight=1)

        for index, item in enumerate(self.updated_data):
            row = self._build_table_row(item)
            row_tags = self._row_tags_for_item(index, row, item.get("validation_result", ""))
            icon_image = self._validation_image_for_text(item.get("validation_result", ""))
            self.data_table.insert("", tk.END, image=icon_image, values=row, iid=str(index), tags=row_tags)
            self.validation_messages[str(index)] = item.get("validation_result", "")

        self.data_table.tag_configure("evenrow", background=self.theme["table_bg"], foreground=self.theme["text"])
        self.data_table.tag_configure("oddrow", background=self.theme["table_alt"], foreground=self.theme["text"])
        self.data_table.tag_configure("mutedrow", foreground="#6a8dac")
        self.data_table.tag_configure("warningrow", background="#4a4322", foreground=self.theme["text"])
        self.data_table.tag_configure("errorrow", background="#3b222a", foreground=self.theme["text"])
        self.data_table.tag_configure("editedrow", background="#1b2b3d", foreground=self.theme["text"])
        self._autosize_table_columns()

        button_frame = tk.Frame(prices_card, bg=self.theme["panel"])
        button_frame.pack(fill=tk.X, pady=(16, 4))
        button_inner = tk.Frame(button_frame, bg=self.theme["panel"])
        button_inner.pack(anchor="center")

        confirm_button = tk.Button(
            button_inner,
            text="",
            command=self.process_data,
            cursor="hand2",
            relief=tk.FLAT,
            bd=0,
            highlightthickness=0,
            padx=0,
            pady=0,
            bg=self.theme["panel"],
            activebackground=self.theme["panel"],
        )
        send_icon = self.button_icon_images.get("sent_to_uex")
        if send_icon:
            confirm_button.configure(image=send_icon)
        else:
            confirm_button.configure(
                text=self._t("send_button"),
                font=("Segoe UI", 12, "bold"),
                padx=16,
                pady=10,
                bg=self.theme["success"],
                activebackground=self.theme["success_hover"],
                fg="#eefcf8",
                activeforeground="#eefcf8",
            )
        confirm_button.grid(row=0, column=0, padx=(0, 14))

        abort_button = tk.Button(
            button_inner,
            text="",
            command=self.abort_process,
            cursor="hand2",
            relief=tk.FLAT,
            bd=0,
            highlightthickness=0,
            padx=0,
            pady=0,
            bg=self.theme["panel"],
            activebackground=self.theme["panel"],
        )
        abort_icon = self.button_icon_images.get("abort")
        if abort_icon:
            abort_button.configure(image=abort_icon)
        else:
            abort_button.configure(
                text=self._t("abort_button"),
                font=("Segoe UI", 12, "bold"),
                padx=16,
                pady=10,
                bg=self.theme["danger"],
                activebackground=self.theme["danger_hover"],
                fg="#ffecf0",
                activeforeground="#ffecf0",
            )
        abort_button.grid(row=0, column=1, padx=(14, 0))

        workflow_card = tk.Frame(
            self.content_frame,
            bg=self.theme["panel"],
            highlightthickness=1,
            highlightbackground=self.theme["border"],
            padx=12,
            pady=10,
        )
        workflow_card.pack(fill=tk.X)

        self.usage_label = tk.Label(
            workflow_card,
            text=self._t("workflow_title"),
            font=("Segoe UI", 11, "bold"),
            fg=self.theme["accent"],
            bg=self.theme["panel"],
            anchor="w",
        )
        self.usage_label.pack(anchor="w", fill=tk.X)

        self.data_label = tk.Label(
            workflow_card,
            text=self._t("workflow_text"),
            font=("Segoe UI", 10),
            fg=self.theme["muted"],
            bg=self.theme["panel"],
            anchor="w",
            justify="left",
        )
        self.data_label.pack(anchor="w", fill=tk.X, pady=(4, 0))

        self.screenshot_frame = tk.Frame(
            body_frame,
            bg=self.theme["panel_alt"],
            highlightthickness=1,
            highlightbackground=self.theme["border"],
            padx=10,
            pady=10,
        )
        self.screenshot_frame.grid(row=0, column=1, sticky="n")

        prices_screen = Image.fromarray(cropped_screenshot_prices)
        self.prices_image_tk = ImageTk.PhotoImage(prices_screen)
        self._create_screenshot_card(self.screenshot_frame, self._t("price_crop_title"), self.prices_image_tk).pack(fill=tk.X, expand=False)

        self._set_operation(self.operation, trigger_revalidation=False)
        self._set_terminal_name_display(self.selected_terminal_name)

        self._center_popup_on_active_monitor()
        self.bind("<Escape>", lambda _event: self.abort_process())

        self.setup_treeview_for_editing()

        self.protocol("WM_DELETE_WINDOW", self.abort_process)
        self._ui_ready = True
        if not self.terminal_prices:
            self.after(50, self._activate_tradeport_edit)

    @staticmethod
    def _normalize_terminal_prices_input(terminal_prices):
        if not terminal_prices:
            return []
        if isinstance(terminal_prices, dict):
            return list(terminal_prices.values())
        return list(terminal_prices)

    @staticmethod
    def show_data_validation_popup(terminal_prices, operation, screenshot_prices, cropped_screenshot, location_name_screen_crop, initial_terminal_name=""):
        root = WingmanUI.get_instance()
        popup = OverlayPopup(
            root,
            terminal_prices,
            operation,
            screenshot_prices,
            cropped_screenshot,
            location_name_screen_crop,
            initial_terminal_name=initial_terminal_name,
        )
        popup.show_popup()

        # Wait for the popup to close
        popup.wait_window()

        # Retrieve updated data after the popup is closed
        return popup.get_updated_data()
        
    def show_popup(self):
        # Show popup only after full UI build to avoid progressive rendering artifacts.
        if not self._ui_ready:
            self.update_idletasks()
        self.deiconify()
        self._center_popup_on_active_monitor()
        self.lift()
        try:
            self.focus_force()
        except Exception:
            pass

    def abort_process(self):
        self.user_updated_data = "aborted"
        self._hide_validation_tooltip()
        self.destroy()
    
    def process_data(self):
        # Ensure current tradeport entry text is applied even if user confirms immediately.
        if self._tradeport_edit_active:
            self.tradeport_update()
        if not self.selected_terminal_id:
            self._activate_tradeport_edit()
            return
        normalized_data = []
        for data in self.updated_data:
            item = data.copy()
            item.setdefault("transmit", True)
            if item["transmit"]:
                normalized_data.append(item)
        self.user_updated_data = normalized_data
        self._hide_validation_tooltip()
        self.destroy()

    # def collect_updated_data(self):
    #     updated_data = []
    #     for item in self.data_table.get_children():
    #         row_data = self.data_table.item(item, 'values')
    #         updated_data.append(row_data)
    #     return updated_data
    
    def get_updated_data(self):
        # Method to retrieve the updated data after the window is closed
        return self.user_updated_data, self.operation, self.selected_terminal_id
    
    def get_primary_monitor_resolution(self):
        monitors = get_monitors()
        if monitors:
            primary_monitor = monitors[0]  # Erster Monitor in der Liste
            return primary_monitor.width, primary_monitor.height
        return self.winfo_screenwidth(), self.winfo_screenheight()

    def _active_monitor_bounds(self):
        monitors = get_monitors()
        if not monitors:
            return 0, 0, self.winfo_screenwidth(), self.winfo_screenheight()
        try:
            pointer_x = self.winfo_pointerx()
            pointer_y = self.winfo_pointery()
        except Exception:
            pointer_x = None
            pointer_y = None

        if pointer_x is not None and pointer_y is not None:
            for monitor in monitors:
                min_x = monitor.x
                min_y = monitor.y
                max_x = monitor.x + monitor.width
                max_y = monitor.y + monitor.height
                if min_x <= pointer_x < max_x and min_y <= pointer_y < max_y:
                    return monitor.x, monitor.y, monitor.width, monitor.height

        monitor = monitors[0]
        return monitor.x, monitor.y, monitor.width, monitor.height

    def _center_popup_on_active_monitor(self):
        self.update_idletasks()
        window_width = max(self.winfo_width(), self.winfo_reqwidth())
        window_height = max(self.winfo_height(), self.winfo_reqheight())
        mon_x, mon_y, mon_width, mon_height = self._active_monitor_bounds()
        margin = 20

        pos_x = mon_x + (mon_width - window_width) // 2
        pos_y = mon_y + (mon_height - window_height) // 2

        min_x = mon_x + margin
        max_x = mon_x + mon_width - window_width - margin
        min_y = mon_y + margin
        max_y = mon_y + mon_height - window_height - margin

        if max_x < min_x:
            min_x = mon_x
            max_x = mon_x
        if max_y < min_y:
            min_y = mon_y
            max_y = mon_y

        pos_x = min(max(pos_x, min_x), max_x)
        pos_y = min(max(pos_y, min_y), max_y)
        self.geometry(f"{window_width}x{window_height}+{int(pos_x)}+{int(pos_y)}")

    def _configure_tree_style(self):
        style = ttk.Style(self)
        style.configure(
            self.TREE_STYLE,
            background=self.theme["table_bg"],
            fieldbackground=self.theme["table_bg"],
            foreground=self.theme["text"],
            rowheight=36,
            bordercolor=self.theme["border"],
            relief="flat",
            font=("Segoe UI", 12),
        )
        style.configure(
            f"{self.TREE_STYLE}.Heading",
            background=self.theme["panel_alt"],
            foreground=self.theme["accent"],
            font=("Segoe UI", 12, "bold"),
            relief="flat",
        )
        style.map(
            self.TREE_STYLE,
            background=[("selected", self.theme["table_select"])],
            foreground=[("selected", self.theme["text"])],
        )
        style.map(
            f"{self.TREE_STYLE}.Heading",
            background=[("active", self.theme["panel_alt"])],
            foreground=[("active", self.theme["accent_hover"])],
        )
        style.configure(
            self.V_SCROLL_STYLE,
            troughcolor=self.theme["panel"],
            background=self.theme["panel_alt"],
            bordercolor=self.theme["border"],
            arrowcolor=self.theme["accent"],
            relief="flat",
        )
        style.map(
            self.V_SCROLL_STYLE,
            background=[("active", self.theme["accent"])],
        )
        style.configure(
            self.H_SCROLL_STYLE,
            troughcolor=self.theme["panel"],
            background=self.theme["panel_alt"],
            bordercolor=self.theme["border"],
            arrowcolor=self.theme["accent"],
            relief="flat",
        )
        style.map(
            self.H_SCROLL_STYLE,
            background=[("active", self.theme["accent"])],
        )

    def _start_window_drag(self, event):
        self._drag_offset_x = event.x_root - self.winfo_x()
        self._drag_offset_y = event.y_root - self.winfo_y()

    def _on_window_drag(self, event):
        new_x = max(0, event.x_root - self._drag_offset_x)
        new_y = max(0, event.y_root - self._drag_offset_y)
        self.geometry(f"+{new_x}+{new_y}")

    def _set_operation(self, operation, trigger_revalidation=True):
        previous_operation = self.operation
        operation_value = "sell" if str(operation).lower() == "sell" else "buy"
        self.operation = operation_value
        is_buy = operation_value == "buy"
        self.buy_button.configure(text=self._t("op_buy"))
        self.sell_button.configure(text=self._t("op_sell"))
        self.buy_button.configure(
            bg=self.theme["accent"] if is_buy else self.theme["panel_alt"],
            fg=self.theme["bg"] if is_buy else self.theme["text"],
            activebackground=self.theme["accent_hover"] if is_buy else self.theme["panel"],
            activeforeground=self.theme["bg"] if is_buy else self.theme["text"],
        )
        self.sell_button.configure(
            bg=self.theme["accent"] if not is_buy else self.theme["panel_alt"],
            fg=self.theme["bg"] if not is_buy else self.theme["text"],
            activebackground=self.theme["accent_hover"] if not is_buy else self.theme["panel"],
            activeforeground=self.theme["bg"] if not is_buy else self.theme["text"],
        )
        if trigger_revalidation and previous_operation != operation_value and self.terminal_prices:
            self._revalidate_prices()

    def _set_terminal_name_display(self, terminal_name):
        self.tradeport_name_label.configure(text=terminal_name)
        self.tradeport_entry.delete(0, tk.END)
        self.tradeport_entry.insert(0, terminal_name)

    def _get_uex_service(self):
        if self.uex_service is None:
            self.uex_service = UEXApi2()
        return self.uex_service

    def _ensure_terminal_catalog(self):
        if self.terminals_by_id:
            return
        try:
            terminals = self._get_uex_service().get_data("terminals") or {}
        except Exception:
            terminals = {}
        if not isinstance(terminals, dict):
            terminals = {terminal.get("id"): terminal for terminal in terminals if isinstance(terminal, dict)}
        self.terminals_by_id = terminals
        self.terminal_catalog = [
            terminal
            for terminal in terminals.values()
            if str(terminal.get("type", "")).lower() == "commodity"
        ]

    @staticmethod
    def _terminal_location_anchor(terminal):
        for field in ("id_city", "id_outpost", "id_space_station", "id_orbit", "id_moon", "id_planet"):
            value = terminal.get(field)
            if value:
                return field, value
        return None, None

    def _terminals_near_selected_location(self):
        self._ensure_terminal_catalog()
        selected_terminal = self.terminals_by_id.get(self.selected_terminal_id)
        if not selected_terminal:
            selected_terminal = self.terminals_by_id.get(str(self.selected_terminal_id))
        if not selected_terminal:
            try:
                selected_id_int = int(self.selected_terminal_id)
            except (TypeError, ValueError):
                selected_id_int = None
            if selected_id_int is not None:
                selected_terminal = self.terminals_by_id.get(selected_id_int)
        if not selected_terminal:
            return self._terminals_matching_location_hint() or self.terminal_catalog

        anchor_field, anchor_value = self._terminal_location_anchor(selected_terminal)
        if not anchor_field or not anchor_value:
            return self.terminal_catalog

        same_location = [
            terminal
            for terminal in self.terminal_catalog
            if terminal.get(anchor_field) == anchor_value
            and terminal.get("id_star_system") == selected_terminal.get("id_star_system")
        ]
        return same_location or self.terminal_catalog

    def _terminals_matching_location_hint(self):
        self._ensure_terminal_catalog()
        hint = self.location_name_hint.strip().lower()
        if len(hint) < 2:
            return []

        return [
            terminal
            for terminal in self.terminal_catalog
            if self._terminal_contains_text(terminal, hint)
        ]

    @staticmethod
    def _terminal_contains_text(terminal, query):
        fields = (
            "name",
            "nickname",
            "displayname",
            "fullname",
            "space_station_name",
            "outpost_name",
            "city_name",
            "orbit_name",
            "moon_name",
            "planet_name",
        )
        return any(query in str(terminal.get(field, "")).lower() for field in fields)

    def _rank_tradeport_suggestions(self, query_text, terminals):
        query = query_text.strip().lower()
        ranked = []
        for terminal in terminals:
            name = str(terminal.get("name", ""))
            nickname = str(terminal.get("nickname", ""))
            displayname = str(terminal.get("displayname", ""))
            fullname = str(terminal.get("fullname", ""))
            searchable = [
                name,
                nickname,
                displayname,
                fullname,
                str(terminal.get("space_station_name", "")),
                str(terminal.get("outpost_name", "")),
                str(terminal.get("city_name", "")),
                str(terminal.get("orbit_name", "")),
                str(terminal.get("moon_name", "")),
                str(terminal.get("planet_name", "")),
            ]
            searchable_lower = [value.lower() for value in searchable if value]

            if not any(query in value for value in searchable_lower):
                continue

            score = 0
            name_lower = name.lower()
            nickname_lower = nickname.lower()
            displayname_lower = displayname.lower()
            if name_lower.startswith(query):
                score += 320
            if nickname_lower.startswith(query):
                score += 250
            if displayname_lower.startswith(query):
                score += 180
            if query in name_lower:
                score += 140
            if query in nickname_lower:
                score += 90
            if query in displayname_lower:
                score += 70
            if query in fullname.lower():
                score += 40
            if self._terminal_contains_text(terminal, query):
                score += 20

            ranked.append((score, name.lower(), terminal))

        ranked.sort(key=lambda item: (-item[0], item[1]))
        return [item[2] for item in ranked[:10]]

    def _build_tradeport_suggestion_label(self, terminal):
        name = str(terminal.get("name", ""))
        nickname = str(terminal.get("nickname", "")).strip()
        if nickname and nickname.lower() not in name.lower():
            return f"{name} ({nickname})"
        return name

    def _show_tradeport_suggestions(self):
        if self.tradeport_suggestion_terminals:
            self.tradeport_suggestion_listbox.grid()
        else:
            self.tradeport_suggestion_listbox.grid_remove()

    def _hide_tradeport_suggestions(self):
        self.tradeport_suggestion_listbox.grid_remove()
        self.tradeport_suggestion_listbox.selection_clear(0, tk.END)
        self.tradeport_suggestion_terminals = []

    def _update_tradeport_suggestions(self):
        if not self._tradeport_edit_active:
            self._hide_tradeport_suggestions()
            return

        query = self.tradeport_entry.get().strip()
        if len(query) < 3:
            self._hide_tradeport_suggestions()
            return

        candidates = self._terminals_near_selected_location()
        suggestions = self._rank_tradeport_suggestions(query, candidates)
        self.tradeport_suggestion_terminals = suggestions
        self.tradeport_suggestion_listbox.delete(0, tk.END)

        for terminal in suggestions:
            self.tradeport_suggestion_listbox.insert(tk.END, self._build_tradeport_suggestion_label(terminal))

        self._show_tradeport_suggestions()

    def _apply_selected_tradeport_suggestion(self):
        selected = self.tradeport_suggestion_listbox.curselection()
        if not selected:
            return
        selected_terminal = self.tradeport_suggestion_terminals[selected[0]]
        terminal_name = selected_terminal.get("name", "").strip()
        if not terminal_name:
            return

        self.tradeport_entry.delete(0, tk.END)
        self.tradeport_entry.insert(0, terminal_name)
        self._hide_tradeport_suggestions()
        self.tradeport_update()

    def _on_tradeport_entry_key_release(self, event=None):
        ignored_keys = {"Return", "Escape", "Up", "Down", "Left", "Right", "Tab"}
        if event and event.keysym in ignored_keys:
            return
        self._update_tradeport_suggestions()

    def _on_tradeport_entry_down_key(self, _event=None):
        if not self.tradeport_suggestion_terminals:
            return
        self.tradeport_suggestion_listbox.focus_set()
        self.tradeport_suggestion_listbox.selection_clear(0, tk.END)
        self.tradeport_suggestion_listbox.selection_set(0)
        self.tradeport_suggestion_listbox.activate(0)
        return "break"

    def _on_tradeport_suggestion_press(self, _event=None):
        self._tradeport_suggestion_click_active = True

    def _on_tradeport_suggestion_click(self, _event=None):
        self._tradeport_suggestion_click_active = False
        self._apply_selected_tradeport_suggestion()
        return "break"

    def _on_tradeport_suggestion_enter(self, _event=None):
        self._apply_selected_tradeport_suggestion()
        return "break"

    def _activate_tradeport_edit(self, _event=None):
        if self._tradeport_edit_active:
            return
        self._tradeport_edit_active = True
        self.tradeport_name_label.grid_remove()
        self.tradeport_entry.grid(row=0, column=0, sticky="ew", ipady=5)
        self.tradeport_entry.focus_set()
        self.tradeport_entry.icursor(tk.END)
        self.tradeport_entry.selection_range(0, tk.END)
        self._update_tradeport_suggestions()

    def _deactivate_tradeport_edit(self):
        if not self._tradeport_edit_active:
            return
        self._hide_tradeport_suggestions()
        self.tradeport_entry.grid_remove()
        self.tradeport_name_label.grid(row=0, column=0, sticky="ew")
        self._tradeport_edit_active = False

    def _submit_tradeport_edit(self, _event=None):
        if not self._tradeport_edit_active:
            return
        if self._tradeport_suggestion_click_active:
            return
        if self.focus_get() == self.tradeport_suggestion_listbox:
            return
        self._hide_tradeport_suggestions()
        self.tradeport_update()

    def _cancel_tradeport_edit(self, _event=None):
        self.revert_tradeport()
        self._deactivate_tradeport_edit()

    def _detect_language(self):
        try:
            lang = (locale.getlocale()[0] or "").lower()
        except Exception:
            lang = ""
        if not lang:
            env_lang = (locale.getdefaultlocale()[0] or "").lower() if hasattr(locale, "getdefaultlocale") else ""
            lang = env_lang
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
            image = Image.open(icon_path)
            if size:
                if hasattr(Image, "Resampling"):
                    image = image.resize(size, Image.Resampling.LANCZOS)
                else:
                    image = image.resize(size, Image.LANCZOS)
            return ImageTk.PhotoImage(image)
        return None

    def _load_ui_icons(self):
        self.validation_icon_images = {
            "all_plausible": self._load_icon_asset("check.png", size=(25, 25)),
            "price_not_plausible": self._load_icon_asset("warn.png", size=(25, 25)),
            "user_updated": self._load_icon_asset("changed.png", size=(25, 25)),
            "commodity_not_found": self._load_icon_asset("error.png", size=(25, 25)),
            "invalid_price_format": self._load_icon_asset("error.png", size=(25, 25)),
            "unknown": self._load_icon_asset("unknown.png", size=(25, 25)),
        }
        self.button_icon_images = {
            "sent_to_uex": self._load_icon_asset("sent_to_uex.png"),
            "abort": self._load_icon_asset("abort.png"),
        }
        # keep references centralized to avoid Tk garbage collection
        self.icon_images.update(self.validation_icon_images)
        self.icon_images.update(self.button_icon_images)

    def _build_table_row(self, item):
        transmit = "Yes" if item.get("transmit", True) else "No"
        return (
            transmit,
            item.get("commodity_name", ""),
            item.get("code", ""),
            self._format_integer_value(item.get("available_SCU_quantity", "")),
            item.get("inventory_state", ""),
            self._format_price_value(item.get("price_per_unit", ""), item.get("multiplier")),
            item.get("multiplier", ""),
        )

    @staticmethod
    def _format_integer_value(value):
        if value is None or value == "":
            return ""
        normalized = CommodityPriceValidator.normalize_price_for_display(value)
        return f"{normalized:,}"

    @staticmethod
    def _format_price_value(value, multiplier=None):
        if value is None or value == "":
            return ""
        normalized = CommodityPriceValidator.normalize_price_for_display(value, multiplier)
        if CommodityPriceValidator._normalized_multiplier(multiplier):
            if isinstance(normalized, int):
                return str(normalized)
            return f"{float(normalized):.8f}".rstrip("0").rstrip(".")
        return f"{int(round(float(normalized))):,}"

    def _table_value_index(self, column_name):
        try:
            return self.TABLE_COLUMNS.index(column_name)
        except ValueError:
            return None

    def _visible_table_columns(self):
        display_columns = self.data_table["displaycolumns"]
        if display_columns == "#all":
            return list(self.TABLE_COLUMNS)
        if isinstance(display_columns, str):
            return list(self.tk.splitlist(display_columns))
        return list(display_columns)

    def _column_name_from_tree_id(self, tree_column):
        if not tree_column or tree_column == self.VALIDATION_COLUMN:
            return None
        if not tree_column.startswith("#"):
            return tree_column
        try:
            visual_index = int(tree_column[1:]) - 1
        except (TypeError, ValueError):
            return None
        visible_columns = self._visible_table_columns()
        if visual_index < 0 or visual_index >= len(visible_columns):
            return None
        return visible_columns[visual_index]

    def _validation_key_for_text(self, validation_text):
        normalized = str(validation_text).strip().lower()
        if not normalized or "all plausible" in normalized:
            return "all_plausible"
        if "user updated" in normalized or "manual" in normalized:
            return "user_updated"
        if "not plausible" in normalized:
            return "price_not_plausible"
        if "not found" in normalized or "invalid price format" in normalized:
            if "invalid price format" in normalized:
                return "invalid_price_format"
            return "commodity_not_found"
        return "unknown"

    def _validation_image_for_text(self, validation_text):
        key = self._validation_key_for_text(validation_text)
        return self.validation_icon_images.get(key) or self.validation_icon_images.get("unknown")

    def _validation_tooltip_text(self, validation_text):
        normalized = str(validation_text).strip().lower()
        if not normalized or "all plausible" in normalized:
            return self._t("validation_all_plausible")
        if "user updated" in normalized or "manual" in normalized:
            return self._t("validation_user_updated")
        if "not plausible" in normalized:
            return self._t("validation_price_not_plausible")
        if "commodity not found" in normalized or "not found" in normalized:
            return self._t("validation_commodity_not_found")
        if "invalid price format" in normalized:
            return self._t("validation_invalid_price_format")
        return validation_text if validation_text else self._t("validation_unknown")

    def _set_row_validation(self, row_id, validation_text, table_values=None):
        self.validation_messages[str(row_id)] = validation_text or ""
        icon_image = self._validation_image_for_text(validation_text)
        if self.data_table.exists(row_id):
            self.data_table.item(row_id, image=icon_image)

    def _autosize_table_columns(self):
        if not hasattr(self, "data_table"):
            return
        self.update_idletasks()
        heading_font = tkfont.Font(font=("Segoe UI", 12, "bold"))
        body_font = tkfont.Font(font=("Segoe UI", 12))

        min_widths = {
            "transmit": 90,
            "commodity_name": 180,
            "code": 85,
            "inventory_scu": 120,
            "inventory_state": 150,
            "price_per_unit": 130,
            "multiplier": 95,
        }
        paddings = {
            "transmit": 28,
            "commodity_name": 28,
            "code": 28,
            "inventory_scu": 28,
            "inventory_state": 28,
            "price_per_unit": 28,
            "multiplier": 28,
        }

        column_widths = {}
        visible_columns = self._visible_table_columns()
        for col_name in visible_columns:
            col_index = self.TABLE_COLUMNS.index(col_name)
            max_px = heading_font.measure(self._t(f"col_{col_name}"))
            for item in self.updated_data:
                row_values = self._build_table_row(item)
                max_px = max(max_px, body_font.measure(str(row_values[col_index])))
            column_widths[col_name] = max(min_widths[col_name], max_px + paddings[col_name])

        validation_width = max(58, heading_font.measure(self._t("col_validation")) + 26)
        self.data_table.column("#0", width=validation_width, minwidth=58, stretch=False)

        for col_name, width in column_widths.items():
            self.data_table.column(col_name, width=width, stretch=False)

        available_width = self.table_container.winfo_width() if hasattr(self, "table_container") else 0
        if available_width <= 1:
            available_width = self.data_table.winfo_width()

        total_width = validation_width + sum(column_widths.values())
        if available_width > total_width and "commodity_name" in column_widths:
            extra = available_width - total_width
            self.data_table.column("commodity_name", width=column_widths["commodity_name"] + extra, stretch=True)

    def _refresh_table_from_updated_data(self):
        self.data_table.configure(height=max(1, len(self.updated_data)))
        existing_rows = set(self.data_table.get_children())
        for index, item in enumerate(self.updated_data):
            item.setdefault("transmit", True)
            iid = str(index)
            values = self._build_table_row(item)
            if iid in existing_rows:
                self.data_table.item(iid, values=values)
                existing_rows.remove(iid)
            else:
                self.data_table.insert("", tk.END, values=values, iid=iid, image=self._validation_image_for_text(item.get("validation_result", "")))
            self._set_row_validation(iid, item.get("validation_result", ""))
            self._apply_row_style(iid)

        for orphan in existing_rows:
            self.data_table.delete(orphan)
            self.validation_messages.pop(str(orphan), None)
        self._autosize_table_columns()

    def _revalidate_prices(self):
        screenshot_prices, _, _, _ = CommodityPriceValidator.validate_price_information(
            self.updated_data,
            self.terminal_prices,
            self.operation,
        )
        self.updated_data = screenshot_prices
        self._refresh_table_from_updated_data()

    def _on_table_motion(self, event):
        row_id = self.data_table.identify_row(event.y)
        column = self.data_table.identify_column(event.x)
        if not row_id or column != self.VALIDATION_COLUMN:
            self._hide_validation_tooltip()
            return
        validation_text = self.validation_messages.get(str(row_id), "")
        tooltip_text = self._validation_tooltip_text(validation_text)
        if not tooltip_text:
            self._hide_validation_tooltip()
            return
        target = (row_id, column, tooltip_text)
        if target == self.validation_tooltip_target:
            return
        self._hide_validation_tooltip()
        self.validation_tooltip_target = target
        self.validation_tooltip_window = tw = tk.Toplevel(self)
        tw.wm_overrideredirect(True)
        tw.attributes("-topmost", True)
        tw.configure(bg=self.theme["panel_alt"])
        x = self.data_table.winfo_rootx() + event.x + 14
        y = self.data_table.winfo_rooty() + event.y + 14
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            tw,
            text=tooltip_text,
            bg=self.theme["panel_alt"],
            fg=self.theme["text"],
            font=("Segoe UI", 10),
            padx=8,
            pady=5,
            relief="solid",
            bd=1,
            highlightthickness=1,
            highlightbackground=self.theme["border"],
        )
        label.pack()

    def _hide_validation_tooltip(self, _event=None):
        if self.validation_tooltip_window is not None:
            try:
                self.validation_tooltip_window.destroy()
            except Exception:
                pass
            self.validation_tooltip_window = None
        self.validation_tooltip_target = None

    def _create_screenshot_card(self, parent, title, image):
        card = tk.Frame(
            parent,
            bg=self.theme["panel"],
            highlightthickness=1,
            highlightbackground=self.theme["border"],
            padx=8,
            pady=8,
        )
        tk.Label(
            card,
            text=title,
            bg=self.theme["panel"],
            fg=self.theme["muted"],
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        ).pack(fill=tk.X, pady=(0, 6))
        image_label = tk.Label(card, image=image, bg=self.theme["panel"], bd=0)
        image_label.image = image
        image_label.pack(fill=tk.BOTH, expand=True)
        return card

    def _row_tags_for_item(self, row_index, row_values, validation_text=None):
        tags = []
        transmit = str(row_values[0]).lower() == "yes"
        validation_text = str(validation_text if validation_text is not None else "").lower()
        status_tag = None
        if "not plausible" in validation_text:
            status_tag = "warningrow"
        elif "invalid" in validation_text or "not found" in validation_text:
            status_tag = "errorrow"
        elif "user updated" in validation_text:
            status_tag = "editedrow"

        # Do not mix alternating-row background with status highlights.
        if status_tag:
            tags.append(status_tag)
        else:
            tags.append("evenrow" if row_index % 2 == 0 else "oddrow")

        if not transmit:
            tags.append("mutedrow")
        return tuple(tags)

    def _apply_row_style(self, row_id):
        values = self.data_table.item(row_id, "values")
        if not values:
            return
        row_index = int(row_id) if str(row_id).isdigit() else self.data_table.index(row_id)
        validation_text = self.validation_messages.get(str(row_id), "")
        self.data_table.item(row_id, tags=self._row_tags_for_item(row_index, values, validation_text))
        
    def setup_treeview_for_editing(self):
        self.data_table.bind('<Double-1>', self.on_double_click)  # Bind double click
        self.data_table.bind('<ButtonRelease-1>', self.on_table_click) # single click
        self.data_table.bind('<Motion>', self._on_table_motion)
        self.data_table.bind('<Leave>', self._hide_validation_tooltip)

    def on_double_click(self, event):
        # Get the item clicked
        item = self.data_table.identify('item', event.x, event.y)
        column = self.data_table.identify_column(event.x)
        column_name = self._column_name_from_tree_id(column)
        if not item or not column:
            return
        if column == self.VALIDATION_COLUMN or column_name in (None, "transmit"):
            return
        self.edit_item(item, column, column_name)

    def on_table_click(self, event):
        region = self.data_table.identify("region", event.x, event.y)
        if region == "cell":
            row_id = self.data_table.identify_row(event.y)
            column = self.data_table.identify_column(event.x)
            column_name = self._column_name_from_tree_id(column)
            if not row_id or not column:
                return
            if column_name == "transmit":
                self.toggle_checkbox(row_id)
            if column_name == "multiplier":
                self.toggle_multiplier(row_id, column)
            if column_name == "inventory_state":
                self.toggle_inventory_state(row_id, column)
                
    def tradeport_update(self, event=None):

        print_debug("Tradeport update")
        updated_tradeport_name = self.tradeport_entry.get().strip()
        
        if len(updated_tradeport_name) == 0:
            # revert
            self.revert_tradeport(event)
            self._deactivate_tradeport_edit()
            return

        if updated_tradeport_name == self.selected_terminal_name:
            self._deactivate_tradeport_edit()
            return
        
        uex = self._get_uex_service()

        uex_terminal = uex.get_terminal(updated_tradeport_name, search_fields=["nickname", "name", "space_station_name", "outpost_name", "city_name"], cutoff=50)
        
        if uex_terminal is None:
            matched_tradeport = {"terminal_name": self.selected_terminal_name}
        else:
            print_debug(f"found terminal: {uex_terminal['name']}")
            terminal_prices = uex.get_prices_of(price_category="commodities_prices", id_terminal=uex_terminal["id"]) or {}
            self.terminal_prices = list(terminal_prices.values())
            self.selected_terminal_id = uex_terminal["id"]
            if self.terminal_prices:
                matched_tradeport = self.terminal_prices[0]
            else:
                matched_tradeport = {"terminal_name": uex_terminal["name"]}
            self.selected_terminal_name = matched_tradeport["terminal_name"]

        screenshot_prices, validated_prices, invalid_prices, success = CommodityPriceValidator.validate_price_information(self.updated_data, self.terminal_prices, self.operation)
       
        self.updated_data = screenshot_prices
        self._refresh_table_from_updated_data()

        self._set_terminal_name_display(matched_tradeport["terminal_name"])
        self._deactivate_tradeport_edit()
        self.update() 

    def revert_tradeport(self, event=None):
        self._set_terminal_name_display(self.selected_terminal_name)

    def adjust_entry_width(self, entry):
        text_length = len(entry.get())
        entry.config(width=(text_length + 1) if text_length > 15 else 15)

    def toggle_operation(self, event=None):
        next_operation = "sell" if self.operation.lower() == "buy" else "buy"
        self._set_operation(next_operation)

    def toggle_checkbox(self, row_id):
        item = self.data_table.item(row_id)
        transmit_idx = self._table_value_index("transmit")
        if transmit_idx is None:
            return
        checkbox_value = item['values'][transmit_idx]
        new_value = 'No' if checkbox_value == 'Yes' else 'Yes'
        item['values'][transmit_idx] = new_value
        self.data_table.item(row_id, values=item['values'])
        self._apply_row_style(row_id)

        # Aktualisieren des 'transmit'-Werts in self.updated_data
        index = int(row_id)
        self.updated_data[index]['transmit'] = (new_value == 'Yes')

    def toggle_multiplier(self, row_id, column):
        next_value_map = {"None": "k", "k": "M", "M": "None"}

        item = self.data_table.item(row_id)
        multiplier_idx = self._table_value_index("multiplier")
        if multiplier_idx is None:
            return
        multiplier_value = item['values'][multiplier_idx]
        new_value = next_value_map.get(multiplier_value, "None")
        index = int(row_id)
        item['values'][multiplier_idx] = new_value
        self.update_price_by_multipler(new_value=new_value, row_index=index)
        self.updated_data[index]['multiplier'] = new_value
        self.updated_data[index]["validation_result"] = "user updated"
        self._set_row_validation(row_id, "user updated", item['values'])

        self.data_table.item(row_id, values=item['values'])
        self._apply_row_style(row_id)
        
    def toggle_inventory_state(self, row_id, column):
        # ["MAX INVENTORY", "VERY HIGH INVENTORY", "HIGH INVENTORY", "MEDIUM INVENTORY", "LOW INVENTORY", "VERY LOW INVENTORY", "OUT OF STOCK"]
        next_value_map = {
            "OUT OF STOCK": "VERY LOW INVENTORY", 
            "VERY LOW INVENTORY": "LOW INVENTORY", 
            "LOW INVENTORY": "MEDIUM INVENTORY",
            "MEDIUM INVENTORY": "HIGH INVENTORY",
            "HIGH INVENTORY": "VERY HIGH INVENTORY",
            "VERY HIGH INVENTORY": "MAX INVENTORY",
            "MAX INVENTORY": "OUT OF STOCK"
            }

        item = self.data_table.item(row_id)
        inventory_state_idx = self._table_value_index("inventory_state")
        if inventory_state_idx is None:
            return
        inventory_state = item['values'][inventory_state_idx]
        new_value = next_value_map.get(inventory_state, "OUT OF STOCK")
        item['values'][inventory_state_idx] = new_value

        # Aktualisieren des 'inventory_state'-Werts in self.updated_data
        index = int(row_id)
        self.updated_data[index]['inventory_state'] = new_value
        self.updated_data[index]["validation_result"] = "user updated"
        self._set_row_validation(row_id, "user updated", item['values'])

        self.data_table.item(row_id, values=item['values'])
        self._apply_row_style(row_id)

    def edit_item(self, item, column, column_name):
        # Get the bounds and value of the cell to edit
        if not item or not column or not column_name:
            return
        bbox = self.data_table.bbox(item, column)
        if not bbox:
            return
        x, y, width, height = bbox

        column_index = self._table_value_index(column_name)
        if column_index is None:
            return
        value = self.data_table.item(item, 'values')[column_index]

        # Create an entry widget for editing
        entry = tk.Entry(
            self.data_table,
            bg=self.theme["entry_bg"],
            fg=self.theme["text"],
            insertbackground=self.theme["accent"],
            relief=tk.FLAT,
            bd=0,
            highlightthickness=1,
            highlightbackground=self.theme["entry_border"],
            highlightcolor=self.theme["accent"],
            font=("Segoe UI", 12),
        )
        entry.place(x=x, y=y, width=width, height=height)
        entry.insert(0, value)
        entry.focus()
        entry.bind('<Return>', lambda e: self.save_edit(item, column_name, entry))
        entry.bind('<Escape>', lambda e: entry.destroy())
        entry.bind('<FocusOut>', lambda e: self.save_edit(item, column_name, entry))
    
    def save_edit(self, item, column_name, entry_widget):
        new_value = entry_widget.get()
        
        # Update the item with the new value
        row_index = int(item)  # Convert the row ID back to an integer
        column_index = self._table_value_index(column_name)
        if column_index is None:
            entry_widget.destroy()
            return
        table_values = list(self.data_table.item(item, 'values'))
        table_values[column_index] = new_value
        
        # Map Treeview column names to updated_data keys
        column_mapping = {
            "commodity_name": "commodity_name",
            "code": "code",
            "inventory_scu": "available_SCU_quantity",
            "inventory_state": "inventory_state",
            "price_per_unit": "price_per_unit",
            "multiplier": "multiplier",
        }

        column_key = column_mapping.get(column_name)

        if column_key:
            # Update the corresponding item in updated_data
            self.updated_data[row_index][column_key] = new_value
            self.updated_data[row_index]["validation_result"] = "user updated"
            self._set_row_validation(item, "user updated", table_values)

            if column_key == "price_per_unit":
                unit_price = CommodityPriceValidator.normalize_numeric_value(new_value, default=None)
                if unit_price is None:
                    # Handle the case where the user's input is not a valid number
                    self.updated_data[row_index]["validation_result"] = "Invalid price format"
                    self._set_row_validation(item, "Invalid price format", table_values)
                    self.data_table.item(item, values=table_values)
                    self.update()  # Update window to get size  

                    entry_widget.destroy()
                    return 

                multiplier = self.updated_data[row_index]["multiplier"]
                display_price = CommodityPriceValidator.normalize_price_for_display(unit_price, multiplier)
                self.updated_data[row_index]["price_per_unit"] = display_price
                self.updated_data[row_index]['uex_price'] = CommodityPriceValidator.calculate_uex_price(display_price, multiplier)
                table_values[column_index] = self._format_price_value(display_price, multiplier)

            if column_key == "multiplier":
                self.update_price_by_multipler(new_value, row_index)

            if column_key == "commodity_name":
                commodity_name = new_value
                # we want to find the commodity in the terminal prices list
                match_result, success = search.find_best_match(commodity_name, self.terminal_prices, attributes=["commodity_name"], score_cutoff=50)
                if not success:
                    self.updated_data[row_index]["validation_result"] = "commodity not found"
                    self._set_row_validation(item, "commodity not found", table_values)
                    self.data_table.item(item, values=table_values)
                    self._apply_row_style(item)
                    self.update()
                    entry_widget.destroy()
                    return
                
                uex_commodity_price_object = match_result["root_object"]
                self.updated_data[row_index]['commodity_name'] = uex_commodity_price_object["commodity_name"]
                commodity_idx = self._table_value_index("commodity_name")
                code_idx = self._table_value_index("code")
                if commodity_idx is not None:
                    table_values[commodity_idx] = uex_commodity_price_object["commodity_name"]
                self.updated_data[row_index]['code'] = uex_commodity_price_object["id_commodity"]
                if code_idx is not None:
                    table_values[code_idx] = uex_commodity_price_object["id_commodity"]
                multiplier = self.updated_data[row_index]["multiplier"]
                self.updated_data[row_index]['uex_price'] = CommodityPriceValidator.calculate_uex_price(
                    self.updated_data[row_index]["price_per_unit"],
                    multiplier,
                )

        #self.data_table.item(item, )
        self.data_table.item(item, values=table_values)
        self._apply_row_style(item)
        self._autosize_table_columns()
        self.update()  # Update window to get size  

        entry_widget.destroy()

    def update_price_by_multipler(self, new_value, row_index):
        multiplier = new_value
        unit_price = self.updated_data[row_index]["price_per_unit"]
        self.updated_data[row_index]["price_per_unit"] = CommodityPriceValidator.normalize_price_for_display(
            unit_price,
            multiplier,
        )
        self.updated_data[row_index]['uex_price'] = CommodityPriceValidator.calculate_uex_price(unit_price, multiplier)
                
