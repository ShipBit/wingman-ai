"""
Htmldate extracts original and updated publication dates from URLs and web pages.
"""

# meta
__title__ = "htmldate"
__author__ = "Adrien Barbaresi"
__license__ = "Apache-2.0"
__copyright__ = "Copyright 2017-2024, Adrien Barbaresi"
__version__ = "1.8.1"


import logging

from datetime import datetime

try:
    datetime.fromisoformat  # type: ignore[attr-defined]
# Python 3.6
except AttributeError:  # pragma: no cover
    from backports.datetime_fromisoformat import MonkeyPatch  # type: ignore

    MonkeyPatch.patch_fromisoformat()

from .core import find_date

logging.getLogger(__name__).addHandler(logging.NullHandler())
