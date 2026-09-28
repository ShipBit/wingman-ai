"""SC_Accountant: Personal Accountant for Star Citizen."""

# Version targets the Star Citizen patch; the ERP requires separate live qualification, so
# dependent skills can verify SC-version compatibility. Within-patch updates
# append a dotted suffix (4.8.0.1, 4.8.0.2, …).
__version__ = "4.9.0.4"
__sc_target_version__ = "4.9.0"

__all__ = [
    "__version__",
    "__sc_target_version__",
]
