import os
import time
from pathlib import Path
from typing import TYPE_CHECKING
import pygetwindow as gw
from clipboard import Clipboard
from api.interface import SettingsConfig, SkillConfig
from api.enums import LogType
from services.benchmark import Benchmark
from skills.skill_base import Skill, tool
import mouse.mouse as mouse

if TYPE_CHECKING:
    from wingmen.open_ai_wingman import OpenAiWingman


class ControlWindows(Skill):

    # Paths to Start Menu directories
    start_menu_paths: list[Path] = [
        Path(os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs"),
        Path(
            os.environ["PROGRAMDATA"], "Microsoft", "Windows", "Start Menu", "Programs"
        ),
    ]

    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "OpenAiWingman",
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)

    # Function to recursively list files in a directory
    def list_files(self, directory, extension=""):
        for item in directory.iterdir():
            if item.is_dir():
                yield from self.list_files(item, extension)
            elif item.is_file() and item.suffix == extension:
                yield item

    # Microsoft does odd things with its tab titles, see https://github.com/asweigart/PyGetWindow/issues/54, so use this function to try to find matching windows to app name and if match not found try adding unicode special character
    def get_and_check_windows(self, app_name):
        windows = gw.getWindowsWithTitle(app_name)
        if not windows and "Microsoft Edge".lower() in app_name.lower():
            app_name = app_name.replace("Microsoft Edge", "Microsoft\u200b Edge")
            app_name = app_name.replace("microsoft edge", "Microsoft\u200b Edge")
            windows = gw.getWindowsWithTitle(app_name)
            if not windows:
                return None
        return windows

    # Function to search and start an application
    def search_and_start(self, app_name):
        for start_menu_path in self.start_menu_paths:
            if start_menu_path.exists():
                for file_path in self.list_files(start_menu_path, ".lnk"):
                    if app_name.lower() in file_path.stem.lower():
                        # Attempt to start the application
                        try:
                            os.startfile(str(file_path))
                        # subprocess.Popen([str(file_path)])
                        except:
                            return False

                        return True

        return False

    def execute_ui_command(self, app_name: str, command: str):

        windows = self.get_and_check_windows(app_name)
        if windows and len(windows) > 0:
            for window in windows:
                try:
                    getattr(window, command)()
                except AttributeError:
                    pass

            return True

        return False

    @tool(
        description="Activate (bring to front) an application. Use when user says 'switch to', 'show me', 'open', or 'bring up' an app that's already running."
    )
    async def activate_application(self, app_name: str) -> str:
        """
        Activate (bring to front) an application.

        Args:
            app_name: The name of the application to activate.
        """
        windows = self.get_and_check_windows(app_name)
        if windows and len(windows) > 0:
            for window in windows:
                # See https://github.com/asweigart/PyGetWindow/issues/36#issuecomment-919332733 for why just regular "activate" may not work
                try:
                    window.minimize()
                    window.restore()
                    window.activate()
                except:
                    return "Error: Application not found or could not be activated."

            return "Application activated."

        return "Error: Application not found or could not be activated."

    @tool(
        description="Move an application window to a specific position (left, right, top, bottom). Use for window management, split-screen layouts, or organizing desktop."
    )
    async def move_application(self, app_name: str, position: str) -> str:
        """
        Move an application window to a specific position.

        Args:
            app_name: The name of the application to move.
            position: The position to move the window to (left, right, top, bottom).
        """
        if position.lower() not in ["left", "right", "top", "bottom"]:
            return "Error: Invalid position. Must be one of: left, right, top, bottom."

        command = position.lower()
        windows = self.get_and_check_windows(app_name)

        if self.settings.debug_mode:
            await self.printr.print_async(
                f"Windows found in move_application function matching {app_name}: {windows}",
                color=LogType.INFO,
            )

        if windows and len(windows) > 0:
            for window in windows:
                if self.settings.debug_mode:
                    await self.printr.print_async(
                        f"Executing move_application command for: {window.title}",
                        color=LogType.INFO,
                    )
                # Make sure application is active before moving it
                try:
                    window.minimize()
                    window.restore()
                    # Temporarily maximize it, let windows do the work of what maximize means based on the user's setup
                    window.maximize()
                    time.sleep(0.5)
                except:
                    pass
                # Assume that maximize is a proxy for the appropriate full size of a window in this setup, use that to calculate resize
                monitor_width, monitor_height = window.size
                if self.settings.debug_mode:
                    await self.printr.print_async(
                        f"Before resize and move, {window.title} is {window.size} and is located at {window.topleft}.",
                        color=LogType.INFO,
                    )

                try:
                    if "left" in command:
                        window.resizeTo(int(monitor_width * 0.5), int(monitor_height))
                        window.moveTo(0, 0)
                    if "right" in command:
                        window.resizeTo(int(monitor_width * 0.5), int(monitor_height))
                        window.moveTo(int(monitor_width * 0.5), 0)
                    if "top" in command:
                        window.resizeTo(int(monitor_width), int(monitor_height * 0.5))
                        window.moveTo(0, 0)
                    if "bottom" in command:
                        window.resizeTo(int(monitor_width), int(monitor_height * 0.5))
                        window.moveTo(0, int(monitor_height * 0.5))
                    if self.settings.debug_mode:
                        await self.printr.print_async(
                            f"Executed move_application command {command}; {window.title} is now {window.size} and is located at {window.topleft}.",
                            color=LogType.INFO,
                        )
                    # Check if resize and move command really worked, if not return false so wingmanai does not tell user command was successful when it was not
                    if (monitor_width, monitor_height) == window.size:
                        # Try last ditch manual move if moving to left or right
                        if "left" in command:
                            mouse.move(int(monitor_width * 0.5), 10, duration=1.0)
                            time.sleep(0.1)
                            mouse.press(button="left")
                            mouse.move(20, 10, duration=1.0)
                            time.sleep(0.1)
                            mouse.release(button="left")
                            return f"Application moved to {position}."

                        elif "right" in command:
                            mouse.move(int(monitor_width * 0.5), 10, duration=1.0)
                            time.sleep(0.1)
                            mouse.press(button="left")
                            mouse.move(monitor_width - 20, 10, duration=1.0)
                            time.sleep(0.1)
                            mouse.release(button="left")
                            return f"Application moved to {position}."
                        # Return False as failed if could not move through any method
                        return "There was a problem moving that application. The application may not support moving it through automation."
                    return f"Application moved to {position}."

                # If any errors in trying to move and resize windows, return false as well
                except:
                    return "There was a problem moving that application. The application may not support moving it through automation."

        # If no windows found, return false
        return "There was a problem moving that application. The application may not support moving it through automation."

    @tool(
        description="List all open application windows. Use when user asks 'what apps are open?', 'show running programs', or needs to find a specific window."
    )
    async def list_applications(self) -> str:
        """List all open application windows."""
        window_titles = gw.getAllTitles()
        if window_titles:
            titles_as_string = ", ".join(window_titles)
            if self.settings.debug_mode:
                await self.printr.print_async(
                    f"list_applications command found these applications: {titles_as_string}",
                    color=LogType.INFO,
                )
            return f"List of all application window titles found: {titles_as_string}."
        return "There was a problem getting your list of applications."

    @tool(
        description="Place text on the clipboard. Use when user says 'copy this', 'put on clipboard', or needs text ready to paste elsewhere."
    )
    async def place_text_on_clipboard(self, text: str) -> str:
        """
        Place text on the clipboard.

        Args:
            text: The text to place on the clipboard.
        """
        try:
            with Clipboard() as clipboard:
                clipboard.set_clipboard(text)
                return "Text successfully placed on clipboard."
        except KeyError:
            return "Error: Cannot save content to Clipboard as text.  Images and other non-text content cannot be processed."
        except Exception as e:
            return f"Error: {str(e)}"

    @tool(
        description="Read the content of the clipboard. Use when user says 'what did I copy?', 'read clipboard', or wants to analyze copied text."
    )
    async def read_clipboard_content(self) -> str:
        """Read the content of the clipboard."""
        try:
            with Clipboard() as clipboard:
                text = clipboard["text"]
                return f"Text copied from clipboard: {text}"
        except KeyError:
            return "Error: Clipboard has no text.  Images and other non-text content of the clipboard cannot be processed."
        except Exception as e:
            return f"Error: {str(e)}"

    @tool(
        description="Open an application. Use when user says 'launch', 'start', 'run', or 'open' a program that isn't currently running."
    )
    async def open_application(self, app_name: str) -> str:
        """
        Open an application.

        Args:
            app_name: The name of the application to open.
        """
        app_started = self.search_and_start(app_name)
        if app_started:
            return "Application started."
        return "Error: Application not found or could not be started."

    @tool(
        description="Close an application. Use when user says 'close', 'exit', 'quit', or 'shut down' a program."
    )
    async def close_application(self, app_name: str) -> str:
        """
        Close an application.

        Args:
            app_name: The name of the application to close.
        """
        windows = self.get_and_check_windows(app_name)
        if windows and len(windows) > 0:
            for window in windows:
                try:
                    window.close()
                except:
                    return "Error: Application not found or could not be closed."

            return "Application closed."

        return "Error: Application not found or could not be closed."

    @tool(description="Minimize an application window.")
    async def minimize_application(self, app_name: str) -> str:
        """
        Minimize an application window.

        Args:
            app_name: The name of the application to minimize.
        """
        if self.execute_ui_command(app_name, "minimize"):
            return "Application minimized."
        return "Error: Application not found or could not be minimized."

    @tool(description="Maximize an application window.")
    async def maximize_application(self, app_name: str) -> str:
        """
        Maximize an application window.

        Args:
            app_name: The name of the application to maximize.
        """
        if self.execute_ui_command(app_name, "maximize"):
            return "Application maximized."
        return "Error: Application not found or could not be maximized."

    @tool(description="Restore an application window.")
    async def restore_application(self, app_name: str) -> str:
        """
        Restore an application window.

        Args:
            app_name: The name of the application to restore.
        """
        if self.execute_ui_command(app_name, "restore"):
            return "Application restored."
        return "Error: Application not found or could not be restored."
