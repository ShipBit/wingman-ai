"""
HUD Server Constants

Centralized constants and configuration values for the HUD Server.
"""

# Server Configuration
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7862
DEFAULT_FRAMERATE = 60
DEFAULT_LAYOUT_MARGIN = 20
DEFAULT_LAYOUT_SPACING = 15

# Timeouts (seconds)
SERVER_STARTUP_TIMEOUT = 5.0
SERVER_STARTUP_CHECK_INTERVAL = 0.1
SERVER_SHUTDOWN_TIMEOUT = 5.0
OVERLAY_SHUTDOWN_TIMEOUT = 2.0
HTTP_CONNECT_TIMEOUT = 5.0
SYNC_OPERATION_TIMEOUT = 10.0

# Cache Limits
MAX_IMAGE_CACHE_SIZE = 20
MAX_BASE64_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB decoded
MAX_INLINE_TOKEN_CACHE_SIZE = 100
MAX_TEXT_WRAP_CACHE_SIZE = 200
MAX_TEXT_SIZE_CACHE_SIZE = 2000

# Thread Names
THREAD_NAME_SERVER = "HUDServerThread"
THREAD_NAME_OVERLAY = "HUDOverlayThread"
THREAD_NAME_CLIENT_LOOP = "HUDClientLoopThread"

# API Paths
PATH_HEALTH = "/health"
PATH_GROUPS = "/groups"
PATH_MESSAGE = "/message"
PATH_MESSAGE_APPEND = "/message/append"
PATH_MESSAGE_HIDE = "/message/hide"
PATH_LOADER = "/loader"
PATH_ITEMS = "/items"
PATH_PROGRESS = "/progress"
PATH_TIMER = "/timer"
PATH_CHAT_WINDOW = "/chat/window"
PATH_CHAT_MESSAGE = "/chat/message"
PATH_CHAT_MESSAGES = "/chat/messages"
PATH_CHAT_SHOW = "/chat/show"
PATH_CHAT_HIDE = "/chat/hide"
PATH_ELEMENT_SHOW = "/element/show"
PATH_ELEMENT_HIDE = "/element/hide"
PATH_DEFAULTS = "/defaults"
PATH_PREVIEW = "/preview"

# Shared containers every Wingman writes to; their look comes from the defaults
GROUP_CHAT = "wingman_chat"  # element "message"
GROUP_INFO = "wingman_info"  # element "persistent"

# Layout Anchors
ANCHOR_TOP_LEFT = "top_left"
ANCHOR_TOP_CENTER = "top_center"
ANCHOR_TOP_RIGHT = "top_right"
ANCHOR_RIGHT_CENTER = "right_center"
ANCHOR_BOTTOM_RIGHT = "bottom_right"
ANCHOR_BOTTOM_CENTER = "bottom_center"
ANCHOR_BOTTOM_LEFT = "bottom_left"
ANCHOR_LEFT_CENTER = "left_center"
ANCHOR_CENTER = "center"

# Log Messages
LOG_SERVER_STARTED = "[HUD] Server started on http://{}:{}/docs"
LOG_SERVER_STOPPED = "[HUD] Server stopped"
LOG_SERVER_STARTUP_TIMEOUT = "[HUD] Failed to start within {}s timeout"
LOG_SERVER_ALREADY_RUNNING = "[HUD] Server already running"
LOG_OVERLAY_STARTED = "[HUD] Overlay renderer started"
LOG_OVERLAY_STOPPED = "[HUD] Overlay renderer stopped"
LOG_OVERLAY_NOT_AVAILABLE = "[HUD] Overlay not available (PIL missing)"
LOG_OVERLAY_UNSUPPORTED = "[HUD] Overlay not started: {}"
LOG_OVERLAY_ALREADY_RUNNING = "[HUD] Overlay already running"
LOG_MONITORS_AVAILABLE = "[HUD] Available monitors: {}"
LOG_MONITOR_NONE = "[HUD] No monitors detected via EnumDisplayMonitors, using GetSystemMetrics"
LOG_MONITOR_SELECTED = "[HUD] Screen {} selected: {}x{}"
LOG_MONITOR_FALLBACK_UNAVAILABLE = "[HUD] Screen {} requested but not available, falling back to screen {}: {}x{}"
LOG_MONITOR_NONE_AVAILABLE = "[HUD] No monitors available, using hardcoded fallback: 1920x1080"
LOG_MONITOR_ERROR = "[HUD] Error enumerating monitors: {}"
