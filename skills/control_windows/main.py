import asyncio
from typing import TYPE_CHECKING

from api.interface import SettingsConfig, SkillConfig
from skills.skill_base import Skill, tool
from skills.control_windows.desktop import DesktopError, get_desktop
from skills.control_windows.desktop.base import POSITIONS

if TYPE_CHECKING:
    from wingmen.wingman_context import WingmanContext


class ControlWindows(Skill):
    """Apps, windows and the clipboard on Windows, macOS and Linux. The OS
    work is in desktop/, one module per OS."""

    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "WingmanContext",
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)
        self._desktop = get_desktop()

    async def _run(self, function, *args, failure: str):
        """`function` off the event loop; a DesktopError says what the user
        has to do, any other error is the failure text."""
        try:
            return await asyncio.to_thread(function, *args)
        except DesktopError as e:
            return f"Error: {e}"
        except Exception as e:
            if self.settings.debug_mode:
                self.log.warning(f"{function.__name__} failed: {e}", server_only=True)
            return failure

    async def _window_command(self, function, app_name: str, done: str, failure: str) -> str:
        result = await self._run(function, app_name, failure=failure)
        if isinstance(result, str):
            return result
        return done if result else failure

    @tool(
        description="Activate (bring to front) an application. Use when user says 'switch to', 'show me', 'open', or 'bring up' an app that's already running."
    )
    async def activate_application(self, app_name: str) -> str:
        """
        Activate (bring to front) an application.

        Args:
            app_name: The name of the application to activate.
        """
        return await self._window_command(
            self._desktop.activate, app_name,
            "Application activated.", "Error: Application not found or could not be activated.",
        )

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
        position = position.lower()
        if position not in POSITIONS:
            return "Error: Invalid position. Must be one of: left, right, top, bottom."
        failure = "There was a problem moving that application. The application may not support moving it through automation."
        result = await self._run(self._desktop.move, app_name, position, failure=failure)
        if isinstance(result, str):
            return result
        return f"Application moved to {position}." if result else failure

    @tool(
        description="List all open application windows. Use when user asks 'what apps are open?', 'show running programs', or needs to find a specific window."
    )
    async def list_applications(self) -> str:
        """List all open application windows."""
        failure = "There was a problem getting your list of applications."
        titles = await self._run(self._desktop.list_windows, failure=failure)
        if isinstance(titles, str):
            return titles
        if not titles:
            return failure
        max_titles = 30
        listed = ", ".join(titles[:max_titles])
        more = len(titles) - max_titles
        if more > 0:
            listed += f" (and {more} more not shown)"
        if self.settings.debug_mode:
            self.log.info(f"list_applications found: {listed}", server_only=True)
        return f"List of all application window titles found: {listed}."

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
            await asyncio.to_thread(self._desktop.set_clipboard, text)
            return "Text successfully placed on clipboard."
        except DesktopError as e:
            return f"Error: {e}"
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
            text = await asyncio.to_thread(self._desktop.get_clipboard)
        except DesktopError as e:
            return f"Error: {e}"
        except KeyError:
            return "Error: Clipboard has no text.  Images and other non-text content of the clipboard cannot be processed."
        except Exception as e:
            return f"Error: {str(e)}"
        if len(text) > 2000:
            text = text[:2000] + f"... [truncated, {len(text) - 2000} more characters]"
        return f"Text copied from clipboard: {text}"

    @tool(
        description="Open an application. Use when user says 'launch', 'start', 'run', or 'open' a program that isn't currently running."
    )
    async def open_application(self, app_name: str) -> str:
        """
        Open an application.

        Args:
            app_name: The name of the application to open.
        """
        return await self._window_command(
            self._desktop.open_app, app_name,
            "Application started.", "Error: Application not found or could not be started.",
        )

    @tool(
        description="Close an application. Use when user says 'close', 'exit', 'quit', or 'shut down' a program."
    )
    async def close_application(self, app_name: str) -> str:
        """
        Close an application.

        Args:
            app_name: The name of the application to close.
        """
        return await self._window_command(
            self._desktop.close, app_name,
            "Application closed.", "Error: Application not found or could not be closed.",
        )

    @tool(description="Minimize an application window.")
    async def minimize_application(self, app_name: str) -> str:
        """
        Minimize an application window.

        Args:
            app_name: The name of the application to minimize.
        """
        return await self._window_command(
            self._desktop.minimize, app_name,
            "Application minimized.", "Error: Application not found or could not be minimized.",
        )

    @tool(description="Maximize an application window.")
    async def maximize_application(self, app_name: str) -> str:
        """
        Maximize an application window.

        Args:
            app_name: The name of the application to maximize.
        """
        return await self._window_command(
            self._desktop.maximize, app_name,
            "Application maximized.", "Error: Application not found or could not be maximized.",
        )

    @tool(description="Restore an application window.")
    async def restore_application(self, app_name: str) -> str:
        """
        Restore an application window.

        Args:
            app_name: The name of the application to restore.
        """
        return await self._window_command(
            self._desktop.restore, app_name,
            "Application restored.", "Error: Application not found or could not be restored.",
        )
