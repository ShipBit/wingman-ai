from os import path
import sys
import asyncio
import threading
import traceback # Import traceback
from typing import Optional # Import Optional
from pynput import keyboard
from pynput import mouse
from services.audio_recorder import AudioRecorder
from services.secret_keeper import SecretKeeper
from services.tower import Tower
from services.printr import Printr
from services.config_manager import ConfigManager
from gui.root import WingmanUI
from wingmen.wingman import Wingman

printr = Printr()

DEBUG = False


def print_debug(to_print):
    if DEBUG:
        print(to_print)


def get_application_root(is_bundled: bool):
    if is_bundled:
        # Use sys._MEIPASS for bundled apps
        application_path = sys._MEIPASS
    else:
        # Use the directory of the main.py script for development
        application_path = path.dirname(path.abspath(__file__))
    # printr.print(f"Application Root: {application_path}", tags="debug") # Add debug print
    return application_path


class WingmanAI:
    def __init__(self):
        # pyinstaller things...
        self.app_is_bundled = getattr(sys, "frozen", False)
        self.app_root_dir = get_application_root(self.app_is_bundled)

        self.active = False
        self.active_recording = {"key": "", "wingman": None}
        self.tower: Optional[Tower] = None  # Use Optional typing
        self.config_manager = ConfigManager(self.app_root_dir, self.app_is_bundled)
        self.secret_keeper = SecretKeeper(self.app_root_dir)
        self.audio_recorder = AudioRecorder(self.app_root_dir)

    def load_context(self, context=""):
        self.active = False
        # Save caches before potentially switching context/reloading tower
        self.save_wingman_caches()
        try:
            # ConfigManager handles finding the correct config file
            config = self.config_manager.get_context_config(context)
            if not config:
                # Handle case where config file is empty or unreadable
                printr.print_err(f"Could not load or parse configuration for context '{context or 'default'}'.", wait_for_gui=True)
                self.tower = None
                return  # Stop loading if config is bad

            self.tower = Tower(
                config=config,
                secret_keeper=self.secret_keeper,
                app_root_dir=self.app_root_dir,
            )
            printr.print(f"Loaded context '{context or 'default'}'. Active Wingmen: {[w.name for w in self.tower.get_wingmen()]}", tags="info", wait_for_gui=True)
            if self.tower.get_broken_wingmen():
                printr.print_warn(f"Broken Wingmen: {self.tower.get_broken_wingmen()}", wait_for_gui=True)

        except FileNotFoundError:
            # This case should ideally be handled by ConfigManager creating default
            printr.print_err(f"Configuration file for context '{context or 'default'}' not found.", True)
            self.tower = None
        except Exception as e:
            # Catch other potential errors during Tower initialization
            printr.print_err(f"Error loading context '{context or 'default'}': {e}", True)
            traceback.print_exc()  # Print full traceback for debugging
            self.tower = None

    def activate(self):
        # Activate only if tower and wingmen are successfully loaded
        if self.tower and self.tower.get_wingmen():
            self.active = True
            printr.print("WingmanAI Activated", tags="success", wait_for_gui=True)
        else:
            self.active = False
            printr.print("WingmanAI cannot activate (no valid wingmen loaded).", tags="warn", wait_for_gui=True)

    def deactivate(self):
        self.active = False
        printr.print("WingmanAI Deactivated", tags="info")

    def on_press(self, key):
        # printr.print(f"key pressed: {key}", tags="debug") # Use printr for consistency
        if self.active and self.tower and self.active_recording["key"] == "":
            # Determine key identifier (char or name)
            key_id = None
            try:
                # Use key.char for printable characters
                key_id = key.char
            except AttributeError:
                # Use key.name for special keys (like shift, ctrl, f1, etc.)
                key_id = key.name
            except Exception as e:
                printr.print_err(f"Error getting key identifier: {e}")
                return # Don't proceed if we can't identify the key

            if key_id:  # Proceed only if we have a valid identifier
                wingman = self.tower.get_wingman_from_key(key_id)  # Pass the determined ID string
                if wingman:
                    printr.print(f"Recording started for Wingman: {wingman.name} (Key: {key_id})", tags="info")
                    self.active_recording = dict(key=key_id, wingman=wingman)  # Store key_id string
                    self.audio_recorder.start_recording()

    def on_release(self, key):
        # Determine key identifier
        key_id = None
        try:
            key_id = key.char
        except AttributeError:
            key_id = key.name
        except Exception as e:
            printr.print_err(f"Error getting key identifier on release: {e}")
            return

        if key_id and self.active and self.active_recording["key"] == key_id: # Check key_id exists
            wingman = self.active_recording["wingman"]
            printr.print(f"Recording stopped for Wingman: {wingman.name} (Key: {key_id})", tags="info")
            # Stop recording *before* resetting active_recording
            recorded_audio_wav = self.audio_recorder.stop_recording()
            # Reset active recording state
            self.active_recording = dict(key="", wingman=None)

            def run_async_process():
                # Each thread needs its own event loop
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    if isinstance(wingman, Wingman) and recorded_audio_wav: # Check audio exists
                        printr.print(f"Processing audio for {wingman.name}...", tags="info")
                        loop.run_until_complete(
                            wingman.process(str(recorded_audio_wav))
                        )
                        printr.print(f"Processing finished for {wingman.name}.", tags="info")
                    elif not recorded_audio_wav:
                        printr.print("No valid audio recorded to process.", tags="warn")

                except Exception as e:
                    printr.print_err(f"Error in async process for {wingman.name}: {e}")
                    traceback.print_exc()
                finally:
                    loop.close()

            if recorded_audio_wav:
                # Start processing in a separate thread to not block the listener
                process_thread = threading.Thread(target=run_async_process, daemon=True)  # Use daemon thread
                process_thread.start()
            # else: # Already handled in run_async_process
            #      printr.print("No valid audio recorded.", tags="warn")

    def on_press_mouse(self, x, y, button, pressed):
        # We only care about button.name == 'x1' based on original logic
        # Check if button has a name attribute first
        if not hasattr(button, 'name') or button.name != 'x1':
            return

        button_id = button.name  # Use button name as the key identifier string
        # printr.print(f"Mouse Button: {button_id}, Pressed: {pressed}", tags="debug")

        if pressed:
            # --- Mouse Press Start Recording ---
            if self.active and self.tower and self.active_recording["key"] == "":
                wingman = self.tower.get_wingman_from_key(button_id)  # Use button name string
                if wingman:
                    printr.print(f"Recording started for Wingman: {wingman.name} (Mouse: {button_id})", tags="info")
                    self.active_recording = dict(key=button_id, wingman=wingman)
                    self.audio_recorder.start_recording()
        else:
            # --- Mouse Release Stop Recording & Process ---
            if self.active and self.active_recording["key"] == button_id:
                wingman = self.active_recording["wingman"]
                printr.print(f"Recording stopped for Wingman: {wingman.name} (Mouse: {button_id})", tags="info")
                # Stop recording before resetting
                recorded_audio_wav = self.audio_recorder.stop_recording()
                # Reset state
                self.active_recording = dict(key="", wingman=None)

                def run_async_process():
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        if isinstance(wingman, Wingman) and recorded_audio_wav:
                            printr.print(f"Processing audio for {wingman.name} (mouse)...", tags="info")
                            loop.run_until_complete(
                                wingman.process(str(recorded_audio_wav))
                            )
                            printr.print(f"Processing finished for {wingman.name} (mouse).", tags="info")
                        elif not recorded_audio_wav:
                             printr.print("No valid audio recorded to process (mouse).", tags="warn")
                    except Exception as e:
                        printr.print_err(f"Error in async process for {wingman.name} (mouse): {e}")
                        traceback.print_exc()
                    finally:
                        loop.close()

                if recorded_audio_wav:
                    process_thread = threading.Thread(target=run_async_process, daemon=True)
                    process_thread.start()
                # else: # Already handled in run_async_process
                #      printr.print("No valid audio recorded (mouse).", tags="warn")

    def save_wingman_caches(self):
        """Iterates through wingmen and saves their caches if applicable."""
        if not self.tower:
            return
        print("Attempting to save wingman caches...")
        for wingman in self.tower.get_wingmen():
            # Check if the wingman has the save_caches method (duck typing)
            if hasattr(wingman, 'save_caches') and callable(wingman.save_caches):
                try:
                    wingman.save_caches()
                except Exception as e:
                    print(f"Error saving caches for wingman {wingman.name}: {e}")

    def shutdown(self):
        """Gracefully shuts down services."""
        print("Shutting down WingmanAI...")
        self.deactivate()
        # Save caches on shutdown
        self.save_wingman_caches()
        # Close audio recorder stream
        if self.audio_recorder:
            self.audio_recorder.close()
            print("Audio recorder closed.")
        # Stop listeners (though main loop exit should handle this)
        # No explicit stop needed here if main loop manages listeners


# ─────────────────────────────────── ↓ START ↓ ─────────────────────────────────────────
if __name__ == "__main__":
    core = WingmanAI()
    listener = None
    mouseListener = None
    ui = None

    try:
        # Initialize keyboard listener in a separate thread
        def keyboard_listener_thread():
            global listener
            try:
                listener = keyboard.Listener(on_press=core.on_press, on_release=core.on_release)
                listener.start()
                printr.print("Keyboard listener started.", tags="info")
                listener.join()  # Wait for listener to finish (on stop)
                # printr.print("Keyboard listener stopped.", tags="info") # Usually logged on shutdown
            except Exception as e:
                # Catch errors during listener start/run
                printr.print_err(f"Error in keyboard listener thread: {e}")
                traceback.print_exc()  # Use imported traceback

        k_thread = threading.Thread(target=keyboard_listener_thread, daemon=True)
        k_thread.start()

        # Initialize mouse listener in a separate thread
        def mouse_listener_thread():
            global mouseListener
            try:
                # Use on_click for both press and release events
                mouseListener = mouse.Listener(on_click=core.on_press_mouse)
                mouseListener.start()
                printr.print("Mouse listener started.", tags="info")
                mouseListener.join()  # Wait for listener to finish
                # printr.print("Mouse listener stopped.", tags="info") # Usually logged on shutdown
            except Exception as e:
                # Catch errors during listener start/run
                printr.print_err(f"Error in mouse listener thread: {e}")
                traceback.print_exc()  # Use imported traceback

        m_thread = threading.Thread(target=mouse_listener_thread, daemon=True)
        m_thread.start()

        # Create and run the UI in the main thread
        ui = WingmanUI.get_instance(core)
        ui.process_tkinter_queue()
        ui.mainloop()  # This blocks until the UI is closed

    except Exception as e:
        printr.print_err(f"An unexpected error occurred in the main loop: {e}", console_only=True)
        traceback.print_exc()  # Use imported traceback
    finally:
        Printr.set_global_console(True)
        printr.print("Main loop exited. Cleaning up...", tags="info")
        # --- Graceful Shutdown ---
        if core:
            core.shutdown()  # Saves caches, closes audio recorder

        # Stop listeners (best effort)
        if listener:  # Check if listener object exists
            try: 
                listener.stop()
            except Exception as e: 
                print(f"Minor error stopping keyboard listener: {e}")
        if mouseListener:  # Check if mouse listener object exists
            try: 
                mouseListener.stop()
            except Exception as e: 
                print(f"Minor error stopping mouse listener: {e}")
        printr.print("WingmanAI finished.", tags="info")
        # Allow daemon threads to exit
        sys.exit(0)