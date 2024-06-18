"""Clipboard Formats"""

import ctypes
from enum import Enum
from enum import EnumMeta
from typing import Any
from typing import Optional

from clipboard._c_interface import CF_HTML
from clipboard._c_interface import CF_RTF
from clipboard._c_interface import GetClipboardFormatNameA


class ExtendedEnum(EnumMeta):
    """Extended Enum Meta Class"""

    def __contains__(cls, item: Any):
        return any(
            [
                item in cls.names,  # type: ignore
                item in cls.values,  # type: ignore
                item in ClipboardFormat.__members__.values(),
            ]
        )


class ClipboardFormat(Enum, metaclass=ExtendedEnum):
    """Clipboard Formats"""

    # Constants
    CF_TEXT = 1
    """ANSI text format. Lines end with CR-LF. Ends with null character."""
    CF_UNICODETEXT = 13
    """Unicode text format. Lines end with CR-LF. Ends with a null character."""
    CF_LOCALE = 16
    CF_DIB = 8
    """A memory object containing a
    [BITMAPINFO](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/
    ns-wingdi-bitmapinfo) structure followed by the bitmap bits."""

    # Registered Formats
    CF_HTML = CF_HTML
    CF_RTF = CF_RTF
    HTML_Format = 49418

    # Aliases
    text = CF_UNICODETEXT  # alias
    html = HTML_Format  # alias
    HTML = html  # alias
    rtf = CF_RTF  # alias

    @classmethod  # type: ignore
    @property
    def values(cls):
        """Get the values of the enum."""
        return [i.value for i in cls]

    @classmethod  # type: ignore
    @property
    def names(cls):
        """Get the names of the enum."""
        return [i.name for i in cls]

    def __str__(self):
        return f"{str(self.value)} {str(self.name)}"

    def __eq__(self, other):
        if isinstance(self, type(other)):
            return self.name == other.name and self.value == other.value
        elif isinstance(other, int):
            return self.value == other
        else:
            return False


def get_format_name(format_code: int) -> Optional[str]:
    """Get the name of the format by its number.

    C function does not work for standard types (e.g. 1 for CF_TEXT).
    So, this function will use ClipboardFormat for those in the standard.

    Returns
    -------
    str, optional
        The name of the format.
        None if the format is not found.
    """
    # Built-In
    if (
        format_code in ClipboardFormat.values
    ):  # pylint: disable=unsupported-membership-test
        return ClipboardFormat(format_code).name

    buffer_size = 256
    buffer = ctypes.create_string_buffer(buffer_size)
    return_code = GetClipboardFormatNameA(
        format_code,
        buffer,
        buffer_size,
    )

    # Failed
    if return_code == 0:
        last_error: int = ctypes.get_last_error()
        if last_error == 0:
            # No Error
            return None
        if last_error == 87:
            # This indicates that the first parameter is not a valid clipboard format.
            return None
        error = ctypes.WinError(last_error)
        raise error

    # ansi string
    format_name: str = buffer.value.decode("utf-8")

    return format_name
