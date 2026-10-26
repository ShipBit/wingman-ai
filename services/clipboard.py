"""The system clipboard for skills (`self.wingman.clipboard`), on every OS.

Windows reads and writes it with clip-util, macOS with pbpaste and pbcopy,
Linux with wl-clipboard in a Wayland session and xclip or xsel under X11.
Text only: an image or a file on the clipboard reads as "".

Blocking: the facade calls these from a thread.
"""

import os
import shutil
import subprocess
import sys

TIMEOUT = 5
"""Seconds to wait for the OS tool."""


class ClipboardError(RuntimeError):
    """The clipboard could not be reached; the message says what to do."""


def read_text() -> str:
    """The clipboard's text, "" when it holds none."""
    if sys.platform == "win32":
        return _windows_read()
    if sys.platform == "darwin":
        return _run(["pbpaste"])
    return _run(_linux_tool(read=True))


def write_text(text: str) -> None:
    """Put `text` on the clipboard, replacing what was there."""
    if sys.platform == "win32":
        _windows_write(text)
    elif sys.platform == "darwin":
        _feed(["pbcopy"], text)
    else:
        _feed(_linux_tool(read=False), text)


# --- Windows ---------------------------------------------------------------

def _windows_read() -> str:
    from clipboard import Clipboard

    with Clipboard() as clipboard:
        try:
            return clipboard["text"] or ""
        except KeyError:
            return ""


def _windows_write(text: str) -> None:
    from clipboard import Clipboard

    with Clipboard() as clipboard:
        clipboard.set_clipboard(text)


# --- macOS and Linux ---------------------------------------------------------

def _linux_tool(read: bool) -> list[str]:
    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-copy"):
        return ["wl-paste", "--no-newline"] if read else ["wl-copy"]
    if shutil.which("xclip"):
        return ["xclip", "-selection", "clipboard"] + (["-o"] if read else [])
    if shutil.which("xsel"):
        return ["xsel", "--clipboard"] + (["--output"] if read else ["--input"])
    raise ClipboardError(
        "The clipboard needs wl-clipboard (Wayland) or xclip (X11). "
        "Install one with your package manager."
    )


def _run(command: list[str]) -> str:
    try:
        result = subprocess.run(command, capture_output=True, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ClipboardError(f"Could not read the clipboard with {command[0]}: {error}") from error
    if result.returncode != 0:
        return ""  # xclip and xsel fail when the clipboard holds no text
    return result.stdout.decode("utf-8", "replace")


def _feed(command: list[str], text: str) -> None:
    try:
        # wl-copy and xclip stay in the background to serve the clipboard.
        process = subprocess.Popen(
            command, stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        process.stdin.write(text.encode("utf-8"))
        process.stdin.close()
    except OSError as error:
        raise ClipboardError(f"Could not write the clipboard with {command[0]}: {error}") from error
