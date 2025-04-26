import time
import datetime
import random
import os
import traceback
import cv2
import pygetwindow
import pyautogui
import base64
from typing import List, Optional, Dict, Any, Tuple, Union
import numpy as np
import json
import shutil


DEBUG = False
TEST = False
SHOW_SCREENSHOTS = False

def print_debug(to_print):
    if DEBUG:
        print(to_print)


try:
    import pydirectinput as key_module
    print_debug("pydirectinput imported")
except AttributeError:
    # TODO: Instead of creating a banner make this an icon in the header
    # printr.print_warn(
    #     "pydirectinput is only supported on Windows. Falling back to pyautogui which might not work in games.",
    #     wait_for_gui=True
    # )
    import pyautogui as key_module
    print_debug("pyautogui imported")




ENHANCE_IMAGES = True  # Schaltet die Verbesserung generell an/aus
CLAHE_CLIP_LIMIT = (
    5.0  # Kontrastlimit (höher = stärkerer Kontrast, kann Rauschen verstärken)
)
CLAHE_TILE_GRID_SIZE = (4, 4)  # Größe der Kacheln für lokale Anpassung
DEFAULT_SC_SCREENSHOT_DIR = (
    "C:/Program Files/Roberts Space Industries/StarCitizen/LIVE/ScreenShots"
)



def take_screenshot(data_dir_path, *subdirectories, **image_name_placeholders):
    """
    Captures and saves a screenshot of the active window if it meets specific criteria,
    optionally returning a random image from a directory in test mode.

    This function captures the entire area of the currently active window, if the window title
    contains "Star Citizen". The screenshot is saved to a directory that is constructed from
    the provided path components. The filename is generated using a combination of provided
    placeholders and a timestamp.

    In test mode, instead of taking a screenshot, a random image from the "examples" directory
    is returned if existing.

    Args:
        data_dir_path (str): The root directory path where the screenshots directory exists or will be created.
        *subdirectories (str): Variable length argument list specifying subdirectories under the root directory.
        test (bool, optional): If True, function operates in test mode and returns a random image. Defaults to False.
        **image_name_placeholders (dict): Keyword arguments that are used to construct the filename of the screenshot
                                          with key-value pairs joined by dashes. Each key-value pair is separated by an underscore.

    Returns:
        str: The full path to the saved screenshot, or a random image if in test mode. None if conditions aren't met.
    """

    # Format the path for subdirectories correctly
    subdir_path = "/".join(subdirectories)
    path = data_dir_path

    is_test = TEST
    if "test" in image_name_placeholders.keys() and is_test is False:
        is_test = image_name_placeholders["test"]

    if is_test:
        path = os.path.join(path, "examples", subdir_path)
        return random_image_from_directory(path)

    path = os.path.join(data_dir_path, "screenshots", subdir_path)

    if not os.path.exists(path):
        os.makedirs(path)

    active_window = pygetwindow.getActiveWindow()
    if active_window and "Star Citizen" in active_window.title:
        # Capture the current time
        now = datetime.datetime.now()
        timestamp = now.strftime(
            "%Y%m%d_%H%M%S_%f"
        )  # Format: YearMonthDay_HourMinuteSecond_Milliseconds

        # Process placeholders in the filename
        placeholder_part = "_".join(
            f"{key}-{value}" for key, value in image_name_placeholders.items()
        )

        # Create the full path and filename
        filename = f"screenshot_{placeholder_part}_{timestamp}.png"
        full_path = os.path.normpath(os.path.join(path, filename))

        # Determine window position and size
        x, y, width, height = (
            active_window.left,
            active_window.top,
            active_window.width,
            active_window.height,
        )

        # Determine window position and size
        x, y, width, height = (
            active_window.left,
            active_window.top,
            active_window.width,
            active_window.height,
        )
        # Take a screenshot of the specified area
        screenshot_pil = pyautogui.screenshot(region=(x, y, width, height))  # PIL Image

        # Konvertiere PIL Image zu OpenCV Format (BGR)
        screenshot_cv = cv2.cvtColor(np.array(screenshot_pil), cv2.COLOR_RGB2BGR)

        # Speichere das *originale* Bild
        cv2.imwrite(full_path, screenshot_cv)
        print_debug(f"Original screenshot saved to {full_path}")

        if ENHANCE_IMAGES:
            try:
                # Lade das gerade gespeicherte Bild
                img_to_enhance = cv2.imread(full_path, cv2.IMREAD_COLOR)
                if img_to_enhance is not None:
                    enhanced_image = enhance_text_visibility(img_to_enhance)
                    # Speichere das verbesserte Bild (überschreibt das Original oder speichere unter neuem Namen)
                    # Hier überschreiben wir die Originaldatei mit der verbesserten Graustufenversion:
                    enhanced_filename = full_path  # Oder z.B. full_path.replace(".png", "_enhanced.png")
                    success = cv2.imwrite(enhanced_filename, enhanced_image)
                    if success:
                        print_debug(f"Enhanced screenshot saved to {enhanced_filename}")
                    else:
                        print_debug(
                            f"Failed to save enhanced screenshot to {enhanced_filename}"
                        )
                else:
                    print_debug(
                        f"Failed to reload screenshot for enhancement: {full_path}"
                    )
            except Exception as e:
                print_debug(f"Error during post-save enhancement: {e}")
                traceback.print_exc()

        return full_path

    return None


def random_image_from_directory(data_dir_path):
    """
    Selects a random image from a specified directory.

    Args:
    directory (str): Path to the directory containing images.
    image_extensions (list, optional): List of acceptable image file extensions.

    Returns:
    str: Path to a randomly selected image.
    """
    image_extensions = [".jpg", ".jpeg", ".png", ".gif", ".bmp"]
    # List all files in the directory
    files = os.listdir(data_dir_path)

    # Filter files to get only those with the specified extensions
    images = [
        file for file in files if any(file.endswith(ext) for ext in image_extensions)
    ]

    if not images:
        return None  # No images found

    # Randomly select an image
    image = random.choice(images)
    full_path = os.path.join(data_dir_path, image)
    print_debug(f"returning random image {full_path}")
    return full_path


def debug_show_screenshot(image, show_screenshot):
    if not show_screenshot or image is None:
        return
    # --- Verbesserung für die Anzeige anwenden ---
    # Wichtig: Erstelle eine Kopie, falls das Originalbild an anderer Stelle noch unverändert gebraucht wird
    display_image = image.copy()
    enhanced_display_image = enhance_text_visibility(display_image)
    # --- Ende Verbesserung ---

    print_debug("displaying enhanced image, press Enter to continue")
    try:
        # Zeige das verbesserte Bild an
        cv2.imshow("Enhanced Debug Screenshot", enhanced_display_image)
        while True:
            key = cv2.waitKey(0) & 0xFF
            if key == 13:  # Warten auf die Eingabetaste (Enter)
                break
            elif key == ord("s"):  # Option zum Speichern des angezeigten Bildes
                save_path = f"debug_enhanced_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                cv2.imwrite(save_path, enhanced_display_image)
                print_debug(f"Debug image saved to {save_path}")

        cv2.destroyAllWindows()
    except Exception:
        traceback.print_exc()
        print_debug("could not display enhanced image")
        # Fallback: Versuche, das Original anzuzeigen, wenn die Verbesserung fehlschlägt
        try:
            cv2.imshow("Original Debug Screenshot", image)
            while True:
                if cv2.waitKey(0) == 13:
                    break
            cv2.destroyAllWindows()
        except Exception:
            print_debug("could not display original image either")
    return


def __get_best_template_matching_coordinates(
    data_dir_path, screenshot, image_area, template_corner, cash_key=None
):
    highest_score = -1
    best_template = ""
    matching_coordinates = None
    next_template_index = 1

    # We'll store the final bounding rect for debug
    final_top_left = None
    final_w, final_h = None, None

    # Construct the cache key
    if cash_key:
        cash_key = f"{cash_key}_{image_area}_{template_corner}"
        cache_file = os.path.join(data_dir_path, "template_cache.txt")

        # Check if the cache file exists and contains the key
        if os.path.exists(cache_file):
            with open(cache_file, "r") as f:
                for line in f:
                    parts = line.strip().split(",")
                    if parts[0] == cash_key:
                        if len(parts) >= 4:
                            print_debug(
                                f"Cache hit for key: {cash_key}: {parts[1]}, {parts[2]}, template: {parts[3]}"
                            )
                        else:
                            print_debug(
                                f"Cache hit for key: {cash_key}: {parts[1]}, {parts[2]}"
                            )
                        return (int(parts[1]), int(parts[2]))

    while True:
        filename = None
        filename1 = f"{data_dir_path}/templates/template_{image_area.lower()}_{next_template_index}.png"
        filename2 = (
            f"{data_dir_path}/template_{image_area.lower()}_{next_template_index}.png"
        )

        if os.path.exists(filename1):
            filename = filename1
        elif os.path.exists(filename2):
            filename = filename2

        if not filename:
            break  # No more templates available

        template = cv2.imread(filename, cv2.IMREAD_COLOR)
        if template is None:
            print_debug(f"Could not read {filename}")
            break

        proof_position = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(proof_position)

        print_debug(f"matchTemplate for {filename} => max_val={max_val}")
        print_debug(f"max_loc: {max_loc}")

        # If this match is better than the previous best, update
        if max_val > highest_score:
            highest_score = max_val
            best_template = filename
            h, w, _ = template.shape

            # We'll store the top-left corner for debug drawing
            # (top-left is always `max_loc`, because matchTemplate gives that corner).
            final_top_left = max_loc
            final_w, final_h = w, h

            # Set matching_coordinates (the corner we *use* for cropping logic)
            if template_corner == "LOWER_LEFT":
                matching_coordinates = (max_loc[0], max_loc[1] + h)
            elif template_corner == "LOWER_RIGHT":
                matching_coordinates = (max_loc[0] + w, max_loc[1] + h)
            elif template_corner == "UPPER_RIGHT":
                matching_coordinates = (max_loc[0] + w, max_loc[1])
            elif template_corner == "UPPER_LEFT":
                matching_coordinates = max_loc
            else:
                raise ValueError(
                    f"Unknown requested_corner_coordinates: {template_corner}"
                )

        next_template_index += 1

    print_debug(
        f"best template found: {best_template} with score {highest_score} and coordinates {matching_coordinates}"
    )

    # Save the result to the cache file (including the winning template)
    if cash_key and matching_coordinates:
        with open(cache_file, "a") as f:
            print_debug(
                f"Writing cache entry for key: {cash_key}: {matching_coordinates}, template: {best_template}"
            )
            f.write(
                f"{cash_key},{matching_coordinates[0]},{matching_coordinates[1]},{best_template}\n"
            )

    # --- Debug Drawing Part ---
    # If you want to visually confirm the final best match:
    if DEBUG and SHOW_SCREENSHOTS and final_top_left is not None:
        # We'll draw on a *copy* so as not to mutate the original screenshot
        debug_img = screenshot.copy()
        top_left = final_top_left
        bottom_right = (top_left[0] + final_w, top_left[1] + final_h)

        cv2.rectangle(debug_img, top_left, bottom_right, (0, 0, 255), 2)
        cv2.imshow("Best Match Debug", debug_img)
        print_debug("Press any key to continue...")
        cv2.waitKey(0)
        cv2.destroyAllWindows()

    return matching_coordinates


def crop_screenshot_coordinates(
    data_dir_path: str,
    screenshot: Union[str, np.ndarray],
    instructions: List[Dict[str, Any]],
    cash_key: Optional[str] = None,
    select_sides: Optional[List[str]] = None,
) -> Optional[np.ndarray]:
    """
    Crop an image based on explicit coordinates and cache the resulting rectangle.

    If `cash_key` is provided and an entry exists in
    data_dir_path/coords_cache.txt, the stored coords are used.
    Otherwise we compute the crop from `instructions` and append it to the cache.

    Args:
        data_dir_path: Root folder for cache file.
        screenshot_file: Path to the image to crop.
        instructions: List of dicts, each with:
            - 'strategy': 'AREA'|'VERTICAL'|'HORIZONTAL'
            - 'coords':
                * AREA: ((x1,y1),(x2,y2))
                * VERTICAL: [x] or [x1,x2]
                * HORIZONTAL: [y] or [y1,y2]
        cash_key: Optional key under dem diese Instruktion geloggt wird.
        select_sides: For single‐line cuts, wähle welche Hälfte:
            VERTICAL → ['LEFT'] oder ['RIGHT']
            HORIZONTAL → ['TOP'] oder ['BOTTOM']

    Returns:
        Das gecroppte BGR‐Image als numpy.ndarray oder None.

    This function allows you to crop a screenshot using a sequence of instructions that define the cropping strategy and coordinates. Optionally, it can cache the computed crop rectangle for faster repeated access.
    If `cash_key` is provided and a matching entry exists in the cache file (`coords_cache.txt`), the cached coordinates are used to crop the image. Otherwise, the crop is computed from the given instructions and appended to the cache.

    Examples:
        # Crop a rectangular area from (100, 200) to (400, 600)
        crop_screenshot_coordinates(
            data_dir_path="cache",
            screenshot_file="screen.png",
            instructions=[{'strategy': 'AREA', 'coords': ((100, 200), (400, 600))}]
        )
        # Crop the left half of the image at vertical line x=500
        crop_screenshot_coordinates(
            data_dir_path="cache",
            screenshot_file="screen.png",
            instructions=[{'strategy': 'VERTICAL', 'coords': [500]}],
            select_sides=['LEFT']
        )
        # Crop the bottom half of the image at horizontal line y=300, with caching
        crop_screenshot_coordinates(
            data_dir_path="cache",
            screenshot_file="screen.png",
            instructions=[{'strategy': 'HORIZONTAL', 'coords': [300]}],
            select_sides=['BOTTOM'],
            cash_key="screen_bottom_half"
        )
    """
    cache_file = os.path.join(data_dir_path, "coords_cache.txt")

    # 1) Cache‐Lookup
    if cash_key and os.path.exists(cache_file):
        with open(cache_file, "r") as f:
            for line in f:
                key, instr_json, x_min, x_max, y_min, y_max = line.strip().split(";")
                if key == cash_key:
                    if isinstance(screenshot, str):
                        img = cv2.imread(screenshot, cv2.IMREAD_COLOR)
                    else:
                        img = screenshot
                    if img is None:
                        print_debug(f"Could not open screenshot '{screenshot}'")
                        return None
                    return img[int(y_min) : int(y_max), int(x_min) : int(x_max)]

    # 2) Bild laden
    if isinstance(screenshot, str):
        if not os.path.exists(screenshot):
            print_debug(f"File not existing '{screenshot}'")
            return None
        img = cv2.imread(screenshot, cv2.IMREAD_COLOR)
        if img is None:
            print_debug(f"Could not open screenshot '{screenshot}'")
            return None
    else:
        img = screenshot

    h, w = img.shape[:2]
    x_min, x_max = 0, w
    y_min, y_max = 0, h

    # 3) Koordinaten aus Anweisungen berechnen
    for instr in instructions:
        strat = instr.get("strategy")
        coords = instr.get("coords")

        if strat == "AREA":
            (x1, y1), (x2, y2) = coords  # type: ignore
            x_min, x_max = sorted((x1, x2))
            y_min, y_max = sorted((y1, y2))

        elif strat == "VERTICAL":
            xs = coords  # type: ignore
            if len(xs) == 1:
                cut = xs[0]
                if select_sides and "LEFT" in select_sides:
                    x_min, x_max = 0, cut
                else:
                    x_min, x_max = cut, w
            elif len(xs) == 2:
                x_min, x_max = sorted(xs)

        elif strat == "HORIZONTAL":
            ys = coords  # type: ignore
            if len(ys) == 1:
                cut = ys[0]
                if select_sides and "TOP" in select_sides:
                    y_min, y_max = 0, cut
                else:
                    y_min, y_max = cut, h
            elif len(ys) == 2:
                y_min, y_max = sorted(ys)

        else:
            print_debug(f"Unknown strategy: {strat}")
            return None

    # 4) Validierung
    if x_max <= x_min or y_max <= y_min:
        print_debug("Invalid crop dimensions.")
        return None

    # 5) Cache schreiben
    if cash_key:
        os.makedirs(data_dir_path, exist_ok=True)
        entry = ";".join(
            [
                cash_key,
                json.dumps(instructions, separators=(",", ":")),
                str(x_min),
                str(x_max),
                str(y_min),
                str(y_max),
            ]
        )
        with open(cache_file, "a") as f:
            f.write(entry + "\n")

    # 6) Ausgeben wie die Original‐Methode
    cropped_image = img[y_min:y_max, x_min:x_max]

    # Optional Debug-Anzeige des verbesserten Bildes
    debug_show_screenshot(cropped_image, SHOW_SCREENSHOTS)

    return cropped_image  # Gib das verbesserte Bild zurück


def crop_screenshot(
    data_dir_path: str,
    screenshot: Union[str, np.ndarray],
    areas_and_corners_and_cropstrat: List[Tuple[str, str, str]],
    cash_key: Optional[str] = None,
    select_sides: Optional[List[str]] = None,
) -> Optional[np.ndarray]:
    """
    Crops a screenshot based on template matching against specified areas of the screenshot. This method supports
    flexible cropping strategies, allowing for area-based, vertical, or horizontal cropping.

    Args:
    - data_dir_path (str): The directory path where template images are stored. Convention: root path that contains a "templates" folder.
        This folder contains template images that could (and should) be found in the given screenshot file.
        This method will iterate over every numbered template file according to it's demanded area. Filename must be in this format:
        "template_{area-name}_{index}.png"
        If "UPPER_LEFT" is demanded, the method will only select files of the pattern "template_upper_left_{index}.png".
        It will try to match this template in the screenshot, if matched fine, if not, it will try with the next availabl index.

    - `screenshot` as a file path (str) or
        as an OpenCV image array (np.ndarray)

    - areas_and_corners_and_cropstrat (list of tuples): A list where each tuple contains:
        - area (str): The area name that corresponds to a template image ("UPPER_LEFT" or "LOWER_RIGHT").

        - corner (str): The corner of interest from the template matching result. Valid values are "UPPER_LEFT",
                        "LOWER_LEFT", "UPPER_RIGHT", and "LOWER_RIGHT".
                        This allows to control at what corner of the match the crop should be based on.

        - crop_strategy (str): The cropping strategy to apply. Valid values are "AREA", "VERTICAL" and "HORIZONTAL".
                               - "AREA": for cropping based on the area between two corners:
                                  This requires 2 AREA templates, usually UPPER_LEFT and LOWER_RIGHT.
                                  The exact crop than depends on the selected corner and will be the rectangle between the 2 template matches
                               - "VERTICAL": for cropping vertically based on x-coordinates. The returned crop is then selected by
                                 the value of "selected_sides"
                               - "HORIZONTAL" for cropping horizontally based on y-coordinates. The returned crop is then selected by
                                 the value of "selected_sides"

        - selected_sides [str] (optional): A list of strings that controls what portion of the screenshot is returned on "HORIZONTAL" or "VERTICAL" slices.
                               - LEFT / RIGHT for VERTICAL slice: return left side or right side of the screenshot
                               - TOP / BOTTOM for HORIZONTAL slice: return top or bottom side of the screenshot
                               Beware on how you apply this when you have mixed cropping strategies (HORIZONTAL and VERTICAL, or 2 HORIZONTAL slides)

    Returns:
    - cropped_screenshot (ndarray or None): The cropped screenshot as a numpy ndarray. Returns None if the cropping
                                            cannot be performed due to invalid dimensions or if no matching templates
                                            are found.

    The function first checks if the screenshot file exists. It then reads the screenshot and initializes cropping
    coordinates to the full image dimensions. For each specified area and corner, it attempts to match the corresponding
    template within the screenshot. Depending on the cropping strategy, it adjusts the cropping coordinates accordingly.

    If only "VERTICAL" or "HORIZONTAL" strategies are applied without "AREA", it ensures that the cropping does not adjust
    the unspecified dimension beyond the screenshot's bounds. The method finally crops the screenshot based on the determined
    coordinates and returns the cropped image. If no valid crop dimensions are found, or if a matching template is not
    detected, it logs an error and returns None.
    """
    # --- 1) Load or validate image input ---
    if isinstance(screenshot, str):
        # Input is a filesystem path: verify existence and load
        if not os.path.isfile(screenshot):
            print_debug(f"File not existing '{screenshot}'")
            return None
        img = cv2.imread(screenshot, cv2.IMREAD_COLOR)
        if img is None:
            print_debug(f"Could not open screenshot '{screenshot}'")
            return None
        source_path = screenshot  # remember for debug-saving
    elif isinstance(screenshot, np.ndarray):
        # Input is already an image array: just use it
        img = screenshot
        source_path = None
    else:
        # Type guard: unsupported type
        print_debug(f"Unsupported type for screenshot: {type(screenshot)}")
        return None

    # --- 2) Determine if AREA-based or slices ---
    area_entries = [t for t in areas_and_corners_and_cropstrat if t[2] == "AREA"]
    if len(area_entries) == 2:
        # AREA crop
        x_min, x_max, y_min, y_max = _crop_area(
            img, data_dir_path, areas_and_corners_and_cropstrat, cash_key
        )
        if None in (x_min, x_max, y_min, y_max):
            print_debug("AREA cropping not possible => returning None")
            return None
        vertical_applied = horizontal_applied = False
    else:
        # VERTICAL/HORIZONTAL slices
        x_min, x_max, y_min, y_max, vertical_applied, horizontal_applied = _crop_slices(
            img, data_dir_path, areas_and_corners_and_cropstrat, cash_key
        )

    # --- 3) Apply quadrant or side selection ---
    cropped = _apply_quadrant_selection(
        img,
        x_min,
        x_max,
        y_min,
        y_max,
        vertical_applied,
        horizontal_applied,
        select_sides,
    )

    # --- 4) Optional debug save (only when original was a file) ---
    # Zeige/Speichere optional das *verbesserte* Bild
    if cropped is not None and DEBUG and source_path:
        directory = os.path.dirname(source_path)
        base = os.path.basename(source_path)
        # Speichere das verbesserte gecroppte Bild
        debug_name = os.path.join(directory, f"cropped_{base}")
        cv2.imwrite(debug_name, cropped)
        # Zeige das verbesserte gecroppte Bild
        debug_show_screenshot(
            cropped, SHOW_SCREENSHOTS
        )  # Ruft jetzt debug_show auf, das intern auch verbessert

    # Gib das verbesserte Bild zurück
    return cropped


def convert_cv2_image_to_base64_jpeg(cv2_image):
    """
    Takes an OpenCV BGR image (ndarray) and returns a data-url string:
    'data:image/jpeg;base64,<...>'
    """
    # Encode as JPEG in memory
    success, encoded_img = cv2.imencode(".jpg", cv2_image)
    if not success:
        raise RuntimeError("Could not encode image to JPEG")

    # encoded_img ist ein numpy-array => Byte-Array draus machen
    base64_str = base64.b64encode(encoded_img).decode("utf-8")

    # data-URL bauen
    data_url = f"data:image/jpeg;base64,{base64_str}"
    return data_url


def enhance_text_visibility(image: np.ndarray, method="adaptive_thresh") -> np.ndarray:
    """
    Verbessert die Sichtbarkeit von Text in einem Bild mit verschiedenen Methoden.

    Args:
        image (np.ndarray): Das Eingabebild (BGR oder Graustufen).
        method (str): 'clahe', 'invert', 'adaptive_thresh', 'clahe_adaptive_thresh'.

    Returns:
        np.ndarray: Das verbesserte Bild (oft Graustufen).
                    Gibt das Originalbild zurück, wenn ENHANCE_IMAGES False ist oder bei Fehlern.
    """
    if not ENHANCE_IMAGES or image is None:
        return image

    try:
        # Immer zuerst in Graustufen konvertieren, da die meisten Methoden darauf basieren
        if len(image.shape) == 3 and image.shape[2] == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        elif len(image.shape) == 2:
            gray = image  # Ist bereits Graustufen
        else:
            # Unerwartetes Format (z.B. BGRA), versuchen zu konvertieren
            try:
                gray = cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
            except:
                print_debug("Could not convert image to grayscale for enhancement.")
                return image

        if method == "invert":
            # Einfache Inversion
            enhanced = cv2.bitwise_not(gray)
            return enhanced

        elif method == "adaptive_thresh":
            # Adaptive Thresholding - gut für Text auf ungleichmäßigem Hintergrund
            # blockSize: Größe des Nachbarschaftsbereichs (ungerade Zahl > 1)
            # C: Konstante, die vom Mittelwert/gewichteten Mittelwert abgezogen wird
            enhanced = cv2.adaptiveThreshold(
                gray,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY_INV,
                blockSize=5,
                C=2,
            )
            # THRESH_BINARY_INV: Invertiert, damit Text weiß auf schwarz wird (typisch für OCR)
            # Wenn du schwarzen Text auf weißem Hintergrund willst, nimm THRESH_BINARY
            # Experimentiere mit blockSize (z.B. 9, 11, 15, ...) und C (z.B. 2, 5, 7, ...)
            return enhanced

        elif method == "clahe":
            # Standard CLAHE (wie zuvor)
            clahe = cv2.createCLAHE(
                clipLimit=CLAHE_CLIP_LIMIT, tileGridSize=CLAHE_TILE_GRID_SIZE
            )
            enhanced = clahe.apply(gray)
            return enhanced

        elif method == "clahe_adaptive_thresh":
            # Erst CLAHE zur allgemeinen Kontrastverbesserung, dann Adaptive Thresholding
            clahe = cv2.createCLAHE(
                clipLimit=CLAHE_CLIP_LIMIT, tileGridSize=CLAHE_TILE_GRID_SIZE
            )
            clahe_enhanced = clahe.apply(gray)
            enhanced = cv2.adaptiveThreshold(
                clahe_enhanced,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY_INV,
                blockSize=15,
                C=7,
            )
            return enhanced

        else:
            print_debug(
                f"Unknown enhancement method: {method}. Returning grayscale image."
            )
            return gray  # Gibt zumindest das Graustufenbild zurück

    except Exception as e:
        print_debug(f"Error enhancing image visibility with method '{method}': {e}")
        traceback.print_exc()
        # Versuche, zumindest das Graustufenbild zurückzugeben, wenn möglich
        try:
            if "gray" in locals():
                return gray
        except:
            pass
        return image  # Im Fehlerfall das Original zurückgeben


def _apply_quadrant_selection(
    screenshot,
    x_min,
    x_max,
    y_min,
    y_max,
    vertical_applied,
    horizontal_applied,
    select_sides,
):
    if x_max <= x_min or y_max <= y_min:
        print_debug("Invalid crop dimensions.")
        return None

    if select_sides:
        if vertical_applied and "LEFT" in select_sides:
            x_max = x_min
            x_min = 0
        # standard behaviour to select right side sizes
        # elif vertical_applied and "RIGHT" in select_sides:
        #     x_max = screenshot.shape[1]

        if horizontal_applied and "BOTTOM" in select_sides:
            y_min = y_max
            y_max = screenshot.shape[0]
        # standard behaviour to select TOP side sizes
        # elif horizontal_applied and "TOP" in select_sides:

    return screenshot[y_min:y_max, x_min:x_max]


def _crop_area(screenshot, data_dir_path, instructions, cash_key=None):
    """
    Erwarte: 2 Templates (UPPER_LEFT, UPPER_LEFT, AREA) und (LOWER_RIGHT, LOWER_RIGHT, AREA).
    Return: (x_min, x_max, y_min, y_max)
    """
    # Standard: Startwerte None
    x_min = None
    y_min = None
    x_max = None
    y_max = None

    # Finde die Koordinaten beider Ecken
    # Man kann hier auch mal "Vorsichtschecks" machen, ob es tatsächlich GENAU 2 Einträge gibt
    # => wir filtern alle Einträge, die "AREA" als Strategie haben
    area_entries = [t for t in instructions if t[2] == "AREA"]
    # area_entries = [("UPPER_LEFT", "UPPER_LEFT", "AREA"), ("LOWER_RIGHT", "LOWER_RIGHT", "AREA")]
    if len(area_entries) != 2:
        print_debug(
            "Warning: Expected EXACTLY 2 AREA instructions, but got something else."
        )
        return None, None, None, None

    for area, corner, strategy in area_entries:
        coords = __get_best_template_matching_coordinates(
            data_dir_path=data_dir_path,
            screenshot=screenshot,
            cash_key=cash_key,
            image_area=area,
            template_corner=corner,
        )
        if not coords:
            print_debug(f"AREA corner not found: {area} / {corner}")
            return None, None, None, None

        this_x, this_y = coords

        if area.upper() == "UPPER_LEFT":
            # => definieren wir x_min, y_min
            x_min = this_x
            y_min = this_y
        elif area.upper() == "LOWER_RIGHT":
            # => definieren wir x_max, y_max
            x_max = this_x
            y_max = this_y
        else:
            # Falls Du wirklich nur UPPER_LEFT/LOWER_RIGHT willst,
            # könnte man hier z.B. debuggen
            print_debug(f"Skipping unknown area: {area}")

    # Falls x_min/x_max etc. None sind => Return None
    if x_min is None or x_max is None or y_min is None or y_max is None:
        return None, None, None, None

    # Ensure x_min < x_max, y_min < y_max (ggf. swap)
    if x_min > x_max:
        x_min, x_max = x_max, x_min
    if y_min > y_max:
        y_min, y_max = y_max, y_min

    return x_min, x_max, y_min, y_max


def _crop_slices(screenshot, data_dir_path, instructions, cash_key=None):
    """
    Verarbeite VERTICAL / HORIZONTAL Schnitte.

    Szenarien laut Vorgabe:
    - 1 Horizontal => links / rechts
    - 1 Vertical => oben / unten
    - 2 Horizontal => 'Mitte' zw. den 2 Koordinaten
    - 2 Vertical => 'Mitte' zw. den 2 Koordinaten
    - 1 Horizontal + 1 Vertical => Quadrant
    - etc.

    Return: (x_min, x_max, y_min, y_max, vertical_applied, horizontal_applied)
    """
    img_h, img_w = screenshot.shape[0], screenshot.shape[1]

    # Defaults: das ganze Bild
    x_min, x_max = 0, img_w
    y_min, y_max = 0, img_h

    # Finde alle "VERTICAL" und "HORIZONTAL" in instructions
    vertical_entries = [
        (area, corner, strat)
        for (area, corner, strat) in instructions
        if strat == "VERTICAL"
    ]
    horizontal_entries = [
        (area, corner, strat)
        for (area, corner, strat) in instructions
        if strat == "HORIZONTAL"
    ]

    # Flags für apply_quadrant_selection
    vertical_applied = len(vertical_entries) > 0
    horizontal_applied = len(horizontal_entries) > 0

    # --- Verarbeite VERTICAL ---
    # Sammle x-Koordinaten
    x_coords = []
    for area, corner, strat in vertical_entries:
        coords = __get_best_template_matching_coordinates(
            data_dir_path=data_dir_path,
            screenshot=screenshot,
            cash_key=cash_key,
            image_area=area,
            template_corner=corner,
        )
        if coords:
            this_x, this_y = coords
            x_coords.append((corner, this_x))
        else:
            print_debug(f"No match found for vertical: {area}/{corner}")

    # Falls x_coords length=1 => wir nehmen "Links oder Rechts" an
    # Falls length=2 => wir nehmen die Mitte zwischen den beiden Koords
    # Das kann man beliebig ausgestalten, hier nur exemplarisch

    if len(x_coords) == 1:
        corner, x_c = x_coords[0]
        if corner in ["UPPER_LEFT", "LOWER_LEFT"]:
            x_min = x_c
        else:
            x_max = x_c
    elif len(x_coords) == 2:
        # z.B. "Mitte" zwischen den beiden x-Koordinaten
        x_sorted = sorted(x_coords, key=lambda e: e[1])
        # x_sorted => [(cornerA, xA), (cornerB, xB)] mit xA <= xB
        # Wir können jetzt sagen: wir wollen nur den Bereich zwischen xA und xB:
        x_min = x_sorted[0][1]
        x_max = x_sorted[1][1]

    # --- Verarbeite HORIZONTAL ---
    # Sammle y-Koordinaten
    y_coords = []
    for area, corner, strat in horizontal_entries:
        coords = __get_best_template_matching_coordinates(
            data_dir_path, screenshot, area, corner
        )
        if coords:
            this_x, this_y = coords
            y_coords.append((corner, this_y))
        else:
            print_debug(f"No match found for horizontal: {area}/{corner}")

    if len(y_coords) == 1:
        corner, y_c = y_coords[0]
        if corner in ["UPPER_LEFT", "UPPER_RIGHT"]:
            y_min = y_c
        else:
            y_max = y_c
    elif len(y_coords) == 2:
        # z.B. "Mitte" zwischen den beiden y-Koordinaten
        y_sorted = sorted(y_coords, key=lambda e: e[1])
        y_min = y_sorted[0][1]
        y_max = y_sorted[1][1]

    return x_min, x_max, y_min, y_max, vertical_applied, horizontal_applied


def find_and_activate_sc_window() -> Optional[pygetwindow.Win32Window]:
    """Versucht das Star Citizen Fenster zu finden und zu aktivieren."""
    active_window = pygetwindow.getActiveWindow()
    sc_window = None
    window_title_search = "Star Citizen"  # Haupttitel

    if active_window and window_title_search in active_window.title:
        print_debug("Star Citizen window is already active.")
        return active_window
    else:
        windows = pygetwindow.getWindowsWithTitle(window_title_search)
        if windows:
            sc_window = windows[0]
            print_debug(f"Found Star Citizen window: {sc_window.title}. Activating...")
            try:
                # Manchmal braucht es einen Moment oder einen zweiten Versuch
                sc_window.activate()
                time.sleep(0.5)  # Kurz warten bis Aktivierung wirkt
                # Überprüfen ob es geklappt hat
                if pygetwindow.getActiveWindow().title != sc_window.title:
                    print_debug("Activation might have failed, trying again...")
                    sc_window.restore()  # Falls minimiert
                    sc_window.activate()
                    time.sleep(0.5)

                if pygetwindow.getActiveWindow().title == sc_window.title:
                    print_debug("Activation successful.")
                    return sc_window
                else:
                    print_debug("Error: Failed to activate Star Citizen window.")
                    return None
            except Exception as e:
                print_debug(f"Error activating Star Citizen window: {e}")
                traceback.print_exc()
                return None
        else:
            print_debug(
                f"Error: Could not find any window with title containing '{window_title_search}'."
            )
            return None


def take_screenshot_ingame(
    data_dir_path: str,  # Ziel-Basisverzeichnis (wie in original take_screenshot)
    *subdirectories: str,  # Ziel-Unterverzeichnisse (wie in original take_screenshot)
    game_screenshot_dir: str = DEFAULT_SC_SCREENSHOT_DIR,  # Quellverzeichnis (wo das Spiel speichert)
    wait_time: float = 1.0,
    filename_prefix: str = "ScreenShot-",
    filename_ext: str = ".jpg",
    **image_name_placeholders: Any,  # Platzhalter für Ziel-Dateinamen (wie in original take_screenshot)
) -> Optional[str]:
    """
    Löst die Ingame-Screenshot-Funktion aus, findet die neueste Datei und
    verschiebt/benennt sie gemäß den data_dir_path/subdirectories/placeholders.
    Unterstützt auch einen Test-Modus wie die ursprüngliche Funktion.

    Args:
        data_dir_path (str): Das Basisverzeichnis für die Zieldatei.
        *subdirectories (str): Ziel-Unterverzeichnisse unter data_dir_path/screenshots/.
        game_screenshot_dir (str): Pfad zum Screenshot-Verzeichnis von Star Citizen (Quelle).
        wait_time (float): Wartezeit in Sekunden nach dem Tastendruck. Defaults to 2.0.
        filename_prefix (str): Erwarteter Anfang des Spiel-Dateinamens. Defaults to "ScreenShot-".
        filename_ext (str): Erwartete Dateiendung der Spiel-Datei (inkl. Punkt). Defaults to ".jpg".
        **image_name_placeholders (Any): Schlüsselwortargumente für den Zieldateinamen.
                                         Enthält optional 'test=True', um den Testmodus zu aktivieren.

    Returns:
        Optional[str]: Der vollständige Pfad zur verschobenen/umbenannten Zieldatei,
                       oder Pfad zu einem zufälligen Bild im Testmodus, oder None bei Fehlern.
    """

    # --- Test Modus Check (wie im original take_screenshot) ---
    is_test = TEST  # Globale Variable
    if "test" in image_name_placeholders:
        # Wenn 'test' explizit übergeben wird, hat es Vorrang
        is_test = image_name_placeholders.pop(
            "test"
        )  # Entferne 'test' aus den Placeholdern für den Dateinamen

    if is_test:
        # Zielpfad für Zufallsbilder konstruieren
        subdir_path_test = "/".join(subdirectories)
        random_img_dir = os.path.join(data_dir_path, "examples", subdir_path_test)
        return random_image_from_directory(random_img_dir)
    # --- Ende Test Modus Check ---

    print_debug("Attempting in-game screenshot via PrintScreen key.")
    print_debug(f"Game screenshot directory (source): {game_screenshot_dir}")

    # 1. Quellverzeichnis prüfen
    if not os.path.isdir(game_screenshot_dir):
        print_debug(
            f"Error: Game screenshot source directory does not exist: {game_screenshot_dir}"
        )
        return None

    # 2. Star Citizen Fenster finden und aktivieren
    sc_window = find_and_activate_sc_window()
    if not sc_window:
        print_debug("Cannot proceed without active Star Citizen window.")
        return None

    # Zeit *vor* dem Tastendruck merken
    time_before_press = time.time()
    relevant_time_threshold = time_before_press - 1.0

    # 3. 'Druck'-Taste simulieren
    try:
        print_debug("Pressing 'printscreen' key...")
        key_module.press("printscreen")
    except Exception as e:
        print_debug(f"Error pressing 'printscreen' key: {e}")
        traceback.print_exc()
        return None

    # 4. Warten
    print_debug(f"Waiting {wait_time} seconds for file to be saved...")
    time.sleep(wait_time)

    # 5. Nach der neuesten Datei im *Spielverzeichnis* suchen
    newest_source_file = None
    latest_mtime = relevant_time_threshold

    try:
        print_debug("Scanning game directory for the newest matching screenshot...")
        for filename in os.listdir(game_screenshot_dir):
            # Stelle sicher, dass die Dateiendung case-insensitive geprüft wird
            if filename.startswith(filename_prefix) and filename.lower().endswith(
                filename_ext.lower()
            ):
                file_path = os.path.join(game_screenshot_dir, filename)
                try:
                    mtime = os.path.getmtime(file_path)
                    if mtime > latest_mtime:
                        latest_mtime = mtime
                        newest_source_file = file_path
                        print_debug(
                            f"  Candidate: {filename} (mtime: {datetime.datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S.%f')})"
                        )
                except (FileNotFoundError, OSError) as e:
                    print_debug(
                        f"Warning: Could not access file metadata for {file_path}: {e}"
                    )
                    continue
    except Exception as e:
        print_debug(f"Error scanning directory {game_screenshot_dir}: {e}")
        traceback.print_exc()
        return None

    # 6. Prüfen, ob eine Datei gefunden wurde
    if not newest_source_file:
        print_debug(
            f"Error: Could not find any new screenshot file matching '{filename_prefix}*{filename_ext.lower()}' "
            f"in {game_screenshot_dir} created/modified after {datetime.datetime.fromtimestamp(relevant_time_threshold).strftime('%Y-%m-%d %H:%M:%S.%f')}."
        )
        return None

    print_debug(f"Found newest game screenshot: {newest_source_file}")

    # --- 7. Zielpfad und Dateinamen konstruieren (wie im original take_screenshot) ---
    try:
        subdir_path_target = "/".join(subdirectories)
        target_base_path = os.path.join(
            data_dir_path, "screenshots", subdir_path_target
        )

        if not os.path.exists(target_base_path):
            print_debug(f"Creating target directory: {target_base_path}")
            os.makedirs(target_base_path)

        now = datetime.datetime.now()
        timestamp = now.strftime("%Y%m%d_%H%M%S_%f")
        placeholder_part = "_".join(
            f"{key}-{value}" for key, value in image_name_placeholders.items()
        )

        # Den Original-Dateityp (.jpg) beibehalten
        original_ext = os.path.splitext(newest_source_file)[1]
        target_filename = f"screenshot_{placeholder_part}_{timestamp}{original_ext}"
        target_full_path = os.path.normpath(
            os.path.join(target_base_path, target_filename)
        )

        print_debug(f"Target path for moving: {target_full_path}")

        # --- 8. Datei verschieben und umbenennen ---
        print_debug(f"Moving '{newest_source_file}' to '{target_full_path}'...")
        shutil.move(newest_source_file, target_full_path)
        print_debug("Move successful.")

        # 9. Den neuen Pfad zurückgeben
        return target_full_path

    except OSError as e:
        print_debug(f"Error creating target directory {target_base_path}: {e}")
        traceback.print_exc()
        return None
    except Exception as e:
        print_debug(f"Error constructing target path or moving file: {e}")
        traceback.print_exc()
        # Optional: Wenn das Verschieben fehlschlägt, gib den Pfad zur Originaldatei zurück?
        # Oder besser None, um klar zu signalisieren, dass der Prozess nicht wie erwartet ablief.
        return None


def test_refineries():
    data_dir_path_test = "star_citizen_data/mining-data/"
    screenshot_file_test = (
        "star_citizen_data/mining-data/examples/ScreenShot-2024-04-02_09-36-15-B2C.jpg"
    )
    # areas_and_corners = [("UPPER_LEFT", "LOWER_LEFT", "AREA"), ("LOWER_RIGHT", "LOWER_RIGHT", "AREA")]
    # cropped_image = crop_screenshot(data_dir_path_test, screenshot_file_test, areas_and_corners)

    # debug_show_screenshot(cropped_image, DEBUG)

    # areas_and_corners = [("UPPER_LEFT", "UPPER_LEFT", "VERTICAL"), ("LOWER_RIGHT", "LOWER_RIGHT", "VERTICAL")]
    # cropped_image = crop_screenshot(data_dir_path_test, screenshot_file_test, areas_and_corners)

    # debug_show_screenshot(cropped_image, DEBUG)

    areas_and_corners = [
        ("UPPER_LEFT", "UPPER_LEFT", "VERTICAL"),
        ("LOWER_RIGHT", "LOWER_RIGHT", "HORIZONTAL"),
    ]
    cropped_image = crop_screenshot(
        data_dir_path_test, screenshot_file_test, areas_and_corners
    )

    debug_show_screenshot(cropped_image, True)

    # areas_and_corners = [("UPPER_LEFT", "UPPER_LEFT", "HORIZONTAL"), ("LOWER_RIGHT", "LOWER_RIGHT", "HORIZONTAL")]
    # cropped_image = crop_screenshot(data_dir_path_test, screenshot_file_test, areas_and_corners)

    # debug_show_screenshot(cropped_image, DEBUG)

    areas_and_corners = [
        ("UPPER_LEFT", "UPPER_LEFT", "VERTICAL"),
        ("LOWER_RIGHT", "LOWER_RIGHT", "HORIZONTAL"),
    ]
    cropped_image = crop_screenshot(
        data_dir_path_test, screenshot_file_test, areas_and_corners, ["TOP", "LEFT"]
    )

    debug_show_screenshot(cropped_image, True)

    areas_and_corners = [
        ("UPPER_LEFT", "UPPER_LEFT", "VERTICAL"),
        ("LOWER_RIGHT", "LOWER_RIGHT", "HORIZONTAL"),
    ]
    cropped_image = crop_screenshot(
        data_dir_path_test, screenshot_file_test, areas_and_corners, ["BOTTOM", "LEFT"]
    )

    debug_show_screenshot(cropped_image, True)

    areas_and_corners = [
        ("UPPER_LEFT", "UPPER_LEFT", "VERTICAL"),
        ("LOWER_RIGHT", "LOWER_RIGHT", "HORIZONTAL"),
    ]
    cropped_image = crop_screenshot(
        data_dir_path_test, screenshot_file_test, areas_and_corners, ["BOTTOM", "RIGHT"]
    )

    debug_show_screenshot(cropped_image, True)

    areas_and_corners = [
        ("UPPER_LEFT", "UPPER_LEFT", "VERTICAL"),
        ("LOWER_RIGHT", "LOWER_RIGHT", "HORIZONTAL"),
    ]
    cropped_image = crop_screenshot(
        data_dir_path_test, screenshot_file_test, areas_and_corners, ["TOP", "RIGHT"]
    )

    debug_show_screenshot(cropped_image, True)


def test_selling_terminal():
    data_dir_path_test = "star_citizen_data/uex/kiosk_analyzer/commodity_info_area"
    screenshot_file_test = "star_citizen_data/uex/kiosk_analyzer/examples/sell/screenshot_test-False_operation-sell_tradeport-TDORI_20250114_233403_980585.png"
    # areas_and_corners = [("UPPER_LEFT", "LOWER_LEFT", "AREA"), ("LOWER_RIGHT", "LOWER_RIGHT", "AREA")]
    # cropped_image = crop_screenshot(data_dir_path_test, screenshot_file_test, areas_and_corners)
    cropped_image = crop_screenshot(
        data_dir_path=data_dir_path_test,
        screenshot=screenshot_file_test,
        areas_and_corners_and_cropstrat=[
            ("UPPER_LEFT", "LOWER_LEFT", "HORIZONTAL"),
            ("UPPER_LEFT", "LOWER_LEFT", "VERTICAL"),
        ],
        cash_key="Ori",
        select_sides=["BOTTOM", "RIGHT"],
    )
    debug_show_screenshot(cropped_image, True)

    screenshot_file_test = "star_citizen_data/uex/kiosk_analyzer/examples/sell/screenshot_test-False_operation-sell_tradeport-TDA18_20250121_161512_577425.png"
    cropped_image = crop_screenshot(
        data_dir_path=data_dir_path_test,
        screenshot=screenshot_file_test,
        areas_and_corners_and_cropstrat=[
            ("UPPER_LEFT", "LOWER_LEFT", "HORIZONTAL"),
            ("UPPER_LEFT", "LOWER_LEFT", "VERTICAL"),
            ("UPPER_RIGHT", "LOWER_RIGHT", "VERTICAL"),
        ],
        cash_key="A18",
        select_sides=["BOTTOM", "RIGHT"],
    )
    debug_show_screenshot(cropped_image, True)

    screenshot_file_test = "star_citizen_data/uex/kiosk_analyzer/examples/sell/screenshot_test-False_operation-sell_tradeport-TDA18_20250121_161512_577425.png"
    cropped_image = crop_screenshot(
        data_dir_path=data_dir_path_test,
        screenshot=screenshot_file_test,
        areas_and_corners_and_cropstrat=[
            ("UPPER_LEFT", "LOWER_LEFT", "AREA"),
            ("LOWER_RIGHT", "LOWER_RIGHT", "AREA"),
        ],
        cash_key="A18",
    )
    debug_show_screenshot(cropped_image, True)

    screenshot_file_test = "star_citizen_data/uex/kiosk_analyzer/examples/sell/screenshot_test-False_operation-sell_tradeport-TDA18_20250121_161512_577425.png"
    cropped_image = crop_screenshot(
        data_dir_path=data_dir_path_test,
        screenshot=screenshot_file_test,
        areas_and_corners_and_cropstrat=[
            ("UPPER_LEFT", "LOWER_LEFT", "AREA"),
            ("LOWER_RIGHT", "LOWER_RIGHT", "AREA"),
        ],
        cash_key="A18",
    )
    debug_show_screenshot(cropped_image, True)


def test_mining_scouting():
    data_dir_path_test = "star_citizen_data/mining-data/templates/scans"
    screenshot_file_test = (
        "star_citizen_data/mining-data/examples/scans/Prospector_1.jpg"
    )
    # areas_and_corners = [("UPPER_LEFT", "LOWER_LEFT", "AREA"), ("LOWER_RIGHT", "LOWER_RIGHT", "AREA")]
    # cropped_image = crop_screenshot(data_dir_path_test, screenshot_file_test, areas_and_corners)
    print(f"testing screenshot: {screenshot_file_test}")
    cropped_image = crop_screenshot(
        data_dir_path_test,
        screenshot_file_test,
        [("UPPER_LEFT", "UPPER_LEFT", "AREA"), ("LOWER_RIGHT", "LOWER_RIGHT", "AREA")],
    )

    debug_show_screenshot(cropped_image, True)

    screenshot_file_test = (
        "star_citizen_data/mining-data/examples/scans/Prospector_2.jpg"
    )
    # areas_and_corners = [("UPPER_LEFT", "LOWER_LEFT", "AREA"), ("LOWER_RIGHT", "LOWER_RIGHT", "AREA")]
    # cropped_image = crop_screenshot(data_dir_path_test, screenshot_file_test, areas_and_corners)
    print(f"testing screenshot: {screenshot_file_test}")
    cropped_image = crop_screenshot(
        data_dir_path_test,
        screenshot_file_test,
        [("UPPER_LEFT", "UPPER_LEFT", "AREA"), ("LOWER_RIGHT", "LOWER_RIGHT", "AREA")],
    )

    debug_show_screenshot(cropped_image, True)

    screenshot_file_test = (
        "star_citizen_data/mining-data/examples/scans/Prospector_3.jpg"
    )
    # areas_and_corners = [("UPPER_LEFT", "LOWER_LEFT", "AREA"), ("LOWER_RIGHT", "LOWER_RIGHT", "AREA")]
    # cropped_image = crop_screenshot(data_dir_path_test, screenshot_file_test, areas_and_corners)
    print(f"testing screenshot: {screenshot_file_test}")
    cropped_image = crop_screenshot(
        data_dir_path_test,
        screenshot_file_test,
        [("UPPER_LEFT", "UPPER_LEFT", "AREA"), ("LOWER_RIGHT", "LOWER_RIGHT", "AREA")],
    )

    debug_show_screenshot(cropped_image, True)


# Example usage
if __name__ == "__main__":
    # test_mining_scouting()
    test_selling_terminal()
