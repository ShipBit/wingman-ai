"""The update channel this build of Core ships on: "unstable" or "production".

CI writes it before PyInstaller runs (scripts/set_build_channel.py), from the
channel the build was started for. A source checkout says "unstable", like
develop. services/features.py decides by it which features this build offers.
"""

CHANNEL = "unstable"
