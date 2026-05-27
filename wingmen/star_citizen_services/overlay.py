import time
from tkinter import Tk, Label, Toplevel
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
            overlay_root.after(display_duration, lambda: close_overlay(overlay_root))

            self.overlay_root = overlay_root

        def close_overlay(overlay_window):
            print_debug(f"closing overlay {time.time()}") 
            overlay_window.destroy()
            self.overlay_shown = False

        WingmanUI.enqueue_tkinter_command(create_overlay)

    def display_overlay_text_at(self, text, x_center, y_bottom, display_duration=15000):
        """
            Displays text with its horizontal center at x_center and its bottom edge at y_bottom.
        """
        self.new_text = True

        def create_overlay():
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
            overlay_root.after(display_duration, lambda: close_overlay(overlay_root))

            self.overlay_root = overlay_root

        def close_overlay(overlay_window):
            print_debug(f"closing overlay {time.time()}")
            overlay_window.destroy()
            self.overlay_shown = False

        WingmanUI.enqueue_tkinter_command(create_overlay)

    def get_primary_monitor_resolution(self):
        monitors = get_monitors()
        if monitors:
            primary_monitor = monitors[0]  # Erster Monitor in der Liste
            return primary_monitor.width, primary_monitor.height
        else:
            return None
