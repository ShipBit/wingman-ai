import time
from tkinter import Tk, Label, Toplevel, Canvas
from PIL import Image, ImageTk, ImageDraw, ImageFont, ImageColor
from screeninfo import get_monitors

from gui.root import WingmanUI  

DEBUG = False
TEST = False


def print_debug(to_print):
    if DEBUG:
        print(to_print)


class StarCitizenOverlay:
    
    def __init__(self, config=None):
        self.overlay_shown = False
        self.overlay_root = None
        self.overlay_label = None
        self.overlay_after_id = None
        self.overlay_text_key = None
        self.debug_rectangle_root = None
        self.debug_rectangle_geometry = None
        self.debug_rectangle_after_id = None
        self.status_dot_root = None
        self.status_dot_canvas = None
        self.status_dot_item = None
        self.status_dot_after_id = None
        self.status_dot_reset_after_id = None
        self.status_dot_geometry = None
        self.new_text = True
        self.screen_width = None
        self.screen_height = None

        # Erstelle ein temporäres Fenster, um Bildschirmabmessungen zu erhalten
        self.screen_width, self.screen_height = self.get_primary_monitor_resolution()
          
        if TEST:
            # self.display_overlay_text("Test 1: kurz")
            # time.sleep(8)
            self.display_overlay_text("Test 2: ein sehr langer test text")

    def create_glow_text_image(self, text, font_path='arial.ttf', font_size=20, transparent_color="gray", text_color='white', glow_color="black"):
        """Erstellt ein Bild mit Text und Glow-Effekt."""
        # Erstelle ein Font-Objekt
        font = ImageFont.truetype(font_path, font_size)
        
        # Convert color string to RGB values
        glow_color_rgb = ImageColor.getrgb(glow_color)
        glow_color_rgba = (glow_color_rgb[0], glow_color_rgb[1], glow_color_rgb[2], 0)

        # Convert color string to RGB values
        transparent_color_rgb = ImageColor.getrgb(transparent_color)
        transparent_color_rgba = (transparent_color_rgb[0], transparent_color_rgb[1], transparent_color_rgb[2], 0)

        # Convert color string to RGB values
        text_color_rgb = ImageColor.getrgb(text_color)
        text_color_rgba = (text_color_rgb[0], text_color_rgb[1], text_color_rgb[2], 0)


        # Erstelle ein Dummy-Image, um die Textgröße zu bekommen
        dummy_image = Image.new('RGB', (1, 1))
        draw_dummy = ImageDraw.Draw(dummy_image)
        text_width, text_height = int(draw_dummy.textlength(text, font=font)), font_size

        print_debug(f'text width: {text_width} height: {text_height}')

        # Erstelle ein neues Image mit transparentem Hintergrund (weiß wird transparent)
        # colored_bg = Image.new('RGBA', (text_width + 2, text_height + 2), transparent_color_rgba)
        text_image = Image.new('RGBA', (text_width + 5, text_height + 4), text_color_rgba)
        
        # find starting coordinates of the text position
        text_x = (text_image.width - text_width) / 2
        text_y = (text_image.height - text_height) / 2
        
        draw = ImageDraw.Draw(text_image)
        
        # transparency values of text frames
        transparency_values = [255, 230, 200]

        for i, value in enumerate(transparency_values):
            glow_color_rgba = (glow_color_rgb[0], glow_color_rgb[1], glow_color_rgb[2], value)
            draw.text((text_x, text_y), text, glow_color_rgba, font=font, stroke_width=i, spacing=5)
 
        draw.text((text_x, text_y), text, text_color_rgb, font=font, stroke_width=0, spacing=5)
        return text_image

    def display_overlay_text(self, text, vertical_position_ratio=4, display_duration=15000):
        """
            displays the text as centered overlay. Ratio provided relative to screen-hight 4 beeing upper 4th part of screen. display_duration in milliseconds, default 15 Seconds. 
        """
        self.new_text = True

        def create_overlay():
            overlay_key = ("center", text, int(vertical_position_ratio))
            if self.overlay_shown and self.overlay_root and self.overlay_text_key == overlay_key:
                self._reschedule_overlay_close(self.overlay_root, display_duration)
                try:
                    self.overlay_root.lift()
                except Exception:
                    pass
                return

            if self.overlay_shown:
                close_overlay(self.overlay_root)

            print_debug(f"showing overlay {time.time()}")

            self.overlay_shown = True
            root = WingmanUI.get_instance()
            overlay_root = Toplevel(root)
            overlay_root.overrideredirect(True)
            overlay_root.attributes('-topmost', True)

            transparent_color = "gray"
            overlay_root.attributes("-transparentcolor", transparent_color)

            text_image = self.create_glow_text_image(text=text, transparent_color=transparent_color)
            photo = ImageTk.PhotoImage(text_image)

            overlay_root.image = photo

            overlay_label = Label(overlay_root, image=photo, bg=transparent_color)
            overlay_label.pack()

            overlay_root.update()

            # Fenstergröße
            window_width = overlay_root.winfo_width()
            window_height = overlay_root.winfo_height()

            print_debug(f'screen width: {self.screen_width} height: {self.screen_height}')
            print_debug(f'overlay width: {window_width} overlay: {window_height}')

            # Berechne die Position
            x_position = (self.screen_width - window_width) // 2
            y_position = self.screen_height // vertical_position_ratio - window_height // 2

            print_debug(f'overlay pos x: {x_position} y: {y_position}')

            # Center the overlay horizontally
            overlay_root.geometry(f"+{x_position}+{y_position}")
            if display_duration and display_duration > 0:
                self.overlay_after_id = overlay_root.after(display_duration, lambda: close_overlay(overlay_root))

            self.overlay_root = overlay_root
            self.overlay_text_key = overlay_key

        def close_overlay(overlay_window):
            print_debug(f"closing overlay {time.time()}") 
            self._cancel_overlay_close()
            overlay_window.destroy()
            self.overlay_shown = False
            self.overlay_root = None
            self.overlay_text_key = None

        WingmanUI.enqueue_tkinter_command(create_overlay)

    def display_overlay_text_at(self, text, x_center, y_bottom, display_duration=15000):
        """
            Displays text with its horizontal center at x_center and its bottom edge at y_bottom.
        """
        self.new_text = True

        def create_overlay():
            overlay_key = ("at", text, int(x_center), int(y_bottom))
            if self.overlay_shown and self.overlay_root and self.overlay_text_key == overlay_key:
                self._reschedule_overlay_close(self.overlay_root, display_duration)
                try:
                    self.overlay_root.lift()
                except Exception:
                    pass
                return
            if (
                self.overlay_shown
                and self.overlay_root
                and isinstance(self.overlay_text_key, tuple)
                and len(self.overlay_text_key) >= 2
                and self.overlay_text_key[0] == "at"
                and self.overlay_text_key[1] == text
            ):
                self._reschedule_overlay_close(self.overlay_root, display_duration)
                try:
                    self.overlay_root.update_idletasks()
                    window_width = self.overlay_root.winfo_width()
                    window_height = self.overlay_root.winfo_height()
                    x_position = int(x_center - window_width // 2)
                    y_position = int(y_bottom - window_height)
                    self.overlay_root.geometry(f"+{x_position}+{y_position}")
                    self.overlay_root.lift()
                    self.overlay_text_key = overlay_key
                    return
                except Exception:
                    pass

            if self.overlay_shown:
                close_overlay(self.overlay_root)

            print_debug(f"showing overlay {time.time()}")

            self.overlay_shown = True
            root = WingmanUI.get_instance()
            overlay_root = Toplevel(root)
            overlay_root.overrideredirect(True)
            overlay_root.attributes('-topmost', True)

            transparent_color = "gray"
            overlay_root.attributes("-transparentcolor", transparent_color)

            text_image = self.create_glow_text_image(text=text, transparent_color=transparent_color)
            photo = ImageTk.PhotoImage(text_image)

            overlay_root.image = photo

            overlay_label = Label(overlay_root, image=photo, bg=transparent_color)
            overlay_label.pack()

            overlay_root.update()

            window_width = overlay_root.winfo_width()
            window_height = overlay_root.winfo_height()
            x_position = int(x_center - window_width // 2)
            y_position = int(y_bottom - window_height)

            overlay_root.geometry(f"+{x_position}+{y_position}")
            if display_duration and display_duration > 0:
                self.overlay_after_id = overlay_root.after(display_duration, lambda: close_overlay(overlay_root))

            self.overlay_root = overlay_root
            self.overlay_text_key = overlay_key

        def close_overlay(overlay_window):
            print_debug(f"closing overlay {time.time()}")
            self._cancel_overlay_close()
            overlay_window.destroy()
            self.overlay_shown = False
            self.overlay_root = None
            self.overlay_text_key = None

        WingmanUI.enqueue_tkinter_command(create_overlay)

    def clear_overlay_text(self):
        def close_current_overlay():
            if not self.overlay_shown or not self.overlay_root:
                return
            try:
                self._cancel_overlay_close()
                self.overlay_root.destroy()
            except Exception:
                pass
            self.overlay_root = None
            self.overlay_shown = False
            self.overlay_text_key = None

        WingmanUI.enqueue_tkinter_command(close_current_overlay)

    def _cancel_overlay_close(self):
        if self.overlay_root and self.overlay_after_id:
            try:
                self.overlay_root.after_cancel(self.overlay_after_id)
            except Exception:
                pass
        self.overlay_after_id = None

    def _reschedule_overlay_close(self, overlay_root, display_duration):
        self._cancel_overlay_close()
        if display_duration and display_duration > 0:
            self.overlay_after_id = overlay_root.after(
                display_duration,
                self.clear_overlay_text,
            )

    def display_debug_rectangle(self, x, y, width, height, color="red", line_width=3, padding=4, auto_clear_ms=None):
        """
            Displays a transparent debug rectangle around a screen area.
            The border is drawn outside the provided area to avoid polluting screenshots of that area.
        """
        geometry = (
            int(x) - int(padding),
            int(y) - int(padding),
            int(width) + int(padding) * 2,
            int(height) + int(padding) * 2,
            str(color),
            int(line_width),
            int(padding),
        )

        def create_or_update_rectangle():
            rect_x, rect_y, rect_width, rect_height, rect_color, rect_line_width, _ = geometry
            if rect_width <= 0 or rect_height <= 0:
                return

            if self.debug_rectangle_root and self.debug_rectangle_geometry == geometry:
                try:
                    self.debug_rectangle_root.lift()
                    self._schedule_debug_rectangle_clear(auto_clear_ms)
                    return
                except Exception:
                    self.debug_rectangle_root = None
                    self.debug_rectangle_geometry = None

            if self.debug_rectangle_root:
                try:
                    self.debug_rectangle_root.destroy()
                except Exception:
                    pass

            root = WingmanUI.get_instance()
            rectangle_root = Toplevel(root)
            rectangle_root.overrideredirect(True)
            rectangle_root.attributes("-topmost", True)

            transparent_color = "gray"
            rectangle_root.attributes("-transparentcolor", transparent_color)
            rectangle_root.configure(bg=transparent_color)
            rectangle_root.geometry(f"{rect_width}x{rect_height}+{rect_x}+{rect_y}")

            canvas = Canvas(
                rectangle_root,
                width=rect_width,
                height=rect_height,
                bg=transparent_color,
                highlightthickness=0,
                bd=0,
            )
            canvas.pack(fill="both", expand=True)
            half_line = max(1, rect_line_width // 2)
            canvas.create_rectangle(
                half_line,
                half_line,
                rect_width - half_line - 1,
                rect_height - half_line - 1,
                outline=rect_color,
                width=rect_line_width,
            )

            self.debug_rectangle_root = rectangle_root
            self.debug_rectangle_geometry = geometry
            self._schedule_debug_rectangle_clear(auto_clear_ms)

        WingmanUI.enqueue_tkinter_command(create_or_update_rectangle)

    def _schedule_debug_rectangle_clear(self, auto_clear_ms):
        if self.debug_rectangle_root and self.debug_rectangle_after_id:
            try:
                self.debug_rectangle_root.after_cancel(self.debug_rectangle_after_id)
            except Exception:
                pass
            self.debug_rectangle_after_id = None

        if not self.debug_rectangle_root or not auto_clear_ms or auto_clear_ms <= 0:
            return

        self.debug_rectangle_after_id = self.debug_rectangle_root.after(
            int(auto_clear_ms),
            self._destroy_debug_rectangle,
        )

    def clear_debug_rectangle(self):
        WingmanUI.enqueue_tkinter_command(self._destroy_debug_rectangle)

    def _destroy_debug_rectangle(self):
        if self.debug_rectangle_root and self.debug_rectangle_after_id:
            try:
                self.debug_rectangle_root.after_cancel(self.debug_rectangle_after_id)
            except Exception:
                pass
        self.debug_rectangle_after_id = None
        if not self.debug_rectangle_root:
            return
        try:
            self.debug_rectangle_root.destroy()
        except Exception:
            pass
        self.debug_rectangle_root = None
        self.debug_rectangle_geometry = None

    def display_blinking_status_dot(
        self,
        x_center,
        y_center,
        color="white",
        size=10,
        blink_ms=450,
        hold_ms=None,
        reset_to_color=None,
        symbol=None,
    ):
        geometry = (
            int(x_center),
            int(y_center),
            int(size),
            str(color),
            int(blink_ms),
            str(symbol or ""),
        )

        def create_or_update_dot():
            dot_x_center, dot_y_center, dot_size, dot_color, dot_blink_ms, dot_symbol = geometry
            window_size = max(18 if dot_symbol else 8, dot_size + (14 if dot_symbol else 8))
            x_position = int(dot_x_center - window_size // 2)
            y_position = int(dot_y_center - window_size // 2)

            if self.status_dot_root and self.status_dot_geometry == geometry:
                try:
                    self.status_dot_root.lift()
                    self._schedule_status_dot_reset(
                        dot_x_center,
                        dot_y_center,
                        dot_size,
                        dot_blink_ms,
                        hold_ms,
                        reset_to_color,
                    )
                    return
                except Exception:
                    self.status_dot_root = None
                    self.status_dot_geometry = None

            self._destroy_status_dot()

            root = WingmanUI.get_instance()
            dot_root = Toplevel(root)
            dot_root.overrideredirect(True)
            dot_root.attributes("-topmost", True)

            transparent_color = "gray"
            dot_root.attributes("-transparentcolor", transparent_color)
            dot_root.configure(bg=transparent_color)
            dot_root.geometry(f"{window_size}x{window_size}+{x_position}+{y_position}")

            canvas = Canvas(
                dot_root,
                width=window_size,
                height=window_size,
                bg=transparent_color,
                highlightthickness=0,
                bd=0,
            )
            canvas.pack(fill="both", expand=True)
            padding = max(2, (window_size - dot_size) // 2)
            if dot_symbol:
                dot_item = canvas.create_text(
                    window_size // 2,
                    window_size // 2,
                    text=dot_symbol,
                    fill=dot_color,
                    font=("Arial", max(14, int(dot_size * 1.7)), "bold"),
                )
            else:
                dot_item = canvas.create_oval(
                    padding,
                    padding,
                    window_size - padding,
                    window_size - padding,
                    fill=dot_color,
                    outline=dot_color,
                )

            self.status_dot_root = dot_root
            self.status_dot_canvas = canvas
            self.status_dot_item = dot_item
            self.status_dot_geometry = geometry

            def blink_dot():
                if not self.status_dot_root or not self.status_dot_canvas or not self.status_dot_item:
                    return
                try:
                    current_state = self.status_dot_canvas.itemcget(self.status_dot_item, "state")
                    next_state = "hidden" if current_state != "hidden" else "normal"
                    self.status_dot_canvas.itemconfigure(self.status_dot_item, state=next_state)
                    self.status_dot_after_id = self.status_dot_root.after(dot_blink_ms, blink_dot)
                except Exception:
                    self._destroy_status_dot()

            self.status_dot_after_id = dot_root.after(dot_blink_ms, blink_dot)
            self._schedule_status_dot_reset(
                dot_x_center,
                dot_y_center,
                dot_size,
                dot_blink_ms,
                hold_ms,
                reset_to_color,
            )

        WingmanUI.enqueue_tkinter_command(create_or_update_dot)

    def clear_blinking_status_dot(self):
        WingmanUI.enqueue_tkinter_command(self._destroy_status_dot)

    def _schedule_status_dot_reset(
        self,
        x_center,
        y_center,
        size,
        blink_ms,
        hold_ms,
        reset_to_color,
    ):
        if self.status_dot_root and self.status_dot_reset_after_id:
            try:
                self.status_dot_root.after_cancel(self.status_dot_reset_after_id)
            except Exception:
                pass
        self.status_dot_reset_after_id = None

        if not self.status_dot_root or not hold_ms or hold_ms <= 0 or not reset_to_color:
            return

        self.status_dot_reset_after_id = self.status_dot_root.after(
            int(hold_ms),
            lambda: self.display_blinking_status_dot(
                x_center=x_center,
                y_center=y_center,
                color=reset_to_color,
                size=size,
                blink_ms=blink_ms,
            ),
        )

    def _destroy_status_dot(self):
        if self.status_dot_root and self.status_dot_after_id:
            try:
                self.status_dot_root.after_cancel(self.status_dot_after_id)
            except Exception:
                pass
        if self.status_dot_root and self.status_dot_reset_after_id:
            try:
                self.status_dot_root.after_cancel(self.status_dot_reset_after_id)
            except Exception:
                pass
        if self.status_dot_root:
            try:
                self.status_dot_root.destroy()
            except Exception:
                pass
        self.status_dot_root = None
        self.status_dot_canvas = None
        self.status_dot_item = None
        self.status_dot_after_id = None
        self.status_dot_reset_after_id = None
        self.status_dot_geometry = None

    def get_primary_monitor_resolution(self):
        monitors = get_monitors()
        if monitors:
            primary_monitor = monitors[0]  # Erster Monitor in der Liste
            return primary_monitor.width, primary_monitor.height
        else:
            return None
