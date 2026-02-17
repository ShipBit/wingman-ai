"""Validation utilities for HUD server settings."""

import ipaddress


def validate_hud_settings(hud_settings) -> dict:
    """Validate HUD server settings and return dict with defaults for invalid values.

    Args:
        hud_settings: Object with hud_server settings attributes

    Returns:
        Dict with validated/fixed values: host, port, framerate, layout_margin, layout_spacing, screen
    """
    defaults = {
        'host': '127.0.0.1',
        'port': 7862,
        'framerate': 60,
        'layout_margin': 20,
        'layout_spacing': 15,
        'screen': 1,
    }

    host = getattr(hud_settings, 'host', defaults['host'])
    port = getattr(hud_settings, 'port', defaults['port'])
    framerate = getattr(hud_settings, 'framerate', defaults['framerate'])
    layout_margin = getattr(hud_settings, 'layout_margin', defaults['layout_margin'])
    layout_spacing = getattr(hud_settings, 'layout_spacing', defaults['layout_spacing'])
    screen = getattr(hud_settings, 'screen', defaults['screen'])

    invalid = {}

    # Validate host
    try:
        ipaddress.IPv4Address(host)
    except (ipaddress.AddressValueError, ValueError):
        invalid['host'] = (host, defaults['host'])
        host = defaults['host']

    # Validate port
    if not isinstance(port, int) or port < 1 or port > 65535:
        invalid['port'] = (port, defaults['port'])
        port = defaults['port']

    # Validate framerate
    if not isinstance(framerate, int) or framerate < 1:
        invalid['framerate'] = (framerate, defaults['framerate'])
        framerate = defaults['framerate']

    # Validate layout_margin
    if not isinstance(layout_margin, int) or layout_margin < 0:
        invalid['layout_margin'] = (layout_margin, defaults['layout_margin'])
        layout_margin = defaults['layout_margin']

    # Validate layout_spacing
    if not isinstance(layout_spacing, int) or layout_spacing < 0:
        invalid['layout_spacing'] = (layout_spacing, defaults['layout_spacing'])
        layout_spacing = defaults['layout_spacing']

    # Validate screen
    if not isinstance(screen, int) or screen < 1:
        invalid['screen'] = (screen, defaults['screen'])
        screen = defaults['screen']

    return {
        'host': host,
        'port': port,
        'framerate': framerate,
        'layout_margin': layout_margin,
        'layout_spacing': layout_spacing,
        'screen': screen,
        '_invalid': invalid,  # Track invalid values for logging
    }


def get_invalid_summary(invalid: dict) -> str:
    """Generate a formatted summary of invalid settings changes.

    Args:
        invalid: Dict of {field: (old_value, new_value)} from validate_hud_settings

    Returns:
        Formatted string for logging
    """
    if not invalid:
        return ""
    lines = ["Invalid settings detected, using defaults:"]
    lines.extend(f"  - {k}: {v[0]!r} → {v[1]!r}" for k, v in invalid.items())
    return "\n".join(lines)
