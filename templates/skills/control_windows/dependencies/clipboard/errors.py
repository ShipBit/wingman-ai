"""Clipboard errors."""


class FormatNotSupportedError(Exception):
    """Exception raised when a clipboard format is not supported."""


class GetClipboardError(Exception):
    """Exception raised when getting the clipboard fails."""


class SetClipboardError(Exception):
    """Exception raised when setting the clipboard fails."""


class EmptyClipboardError(Exception):
    """Exception raised when emptying the clipboard fails."""


class OpenClipboardError(Exception):
    """Exception raised when opening the clipboard fails."""


class ClipboardError(Exception):
    """Exception raised when clipboard operation fails."""


class LockError(Exception):
    """Exception raised when locking the clipboard fails."""


class GetFormatsError(Exception):
    """Exception raised when getting clipboard formats fails."""
