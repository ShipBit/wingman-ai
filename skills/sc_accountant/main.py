"""Wingman v3 entry point, including its file-based custom-skill loader."""

from __future__ import annotations

if __package__:
    from .erp_skill import SC_Accountant
else:
    # Release hosts load main.py outside the skills package. Give the ERP its
    # own package path without exposing generic sibling modules on sys.path.
    from hashlib import sha256
    from importlib import import_module
    from pathlib import Path
    import sys
    from types import ModuleType

    _directory = str(Path(__file__).absolute().parent)
    _package_name = "_sc_accountant_erp_" + sha256(_directory.encode()).hexdigest()[:16]
    if _package_name not in sys.modules:
        _package = ModuleType(_package_name)
        _package.__path__ = [_directory]
        _package.__package__ = _package_name
        sys.modules[_package_name] = _package
    SC_Accountant = import_module(_package_name + ".erp_skill").SC_Accountant

__all__ = ["SC_Accountant"]
