"""Backward-compatibility shim.

``OpenAiWingman`` has been merged into :class:`wingmen.wingman.Wingman`.
This module re-exports ``Wingman`` under the old name so that existing
skills, custom wingmen, tower, and other code that imports
``from wingmen.open_ai_wingman import OpenAiWingman`` continues to work.
"""

from wingmen.wingman import Wingman as OpenAiWingman  # noqa: F401

__all__ = ["OpenAiWingman"]
