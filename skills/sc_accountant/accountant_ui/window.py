"""
SC_Accountant — Standalone Accounting Window

Opens the accounting dashboard in the user's default browser.

Author: Mallachi
"""

from __future__ import annotations

import logging
import webbrowser

logger = logging.getLogger(__name__)


class AccountantWindow:
    """Manages the accounting dashboard browser tab."""

    def __init__(self, url: str = "http://127.0.0.1:7863") -> None:
        self._url = url
        self._opened = False

    def open(self) -> None:
        """Open the accounting dashboard in the default browser."""
        webbrowser.open(self._url)
        self._opened = True
        logger.info("Accountant dashboard opened in default browser")

    def close(self) -> None:
        """Mark the window as closed (browser tab cannot be closed programmatically)."""
        self._opened = False
        logger.info("Accountant dashboard marked as closed")

    @property
    def is_open(self) -> bool:
        """Whether the dashboard has been opened."""
        return self._opened
