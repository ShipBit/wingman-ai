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

# Limits and Bounds
MIN_PORT = 1024
MAX_PORT = 65535
MIN_FRAMERATE = 1
MAX_FRAMERATE = 240
MIN_FONT_SIZE = 8
MAX_FONT_SIZE = 72
MIN_WIDTH = 100
MAX_WIDTH = 3840  # 4K width
MIN_HEIGHT = 100
MAX_HEIGHT = 2160  # 4K height
MAX_MESSAGE_LENGTH = 50000
MAX_GROUP_NAME_LENGTH = 100
MAX_TITLE_LENGTH = 200

# Timeouts (seconds)
SERVER_STARTUP_TIMEOUT = 5.0
SERVER_STARTUP_CHECK_INTERVAL = 0.1
SERVER_SHUTDOWN_TIMEOUT = 5.0
OVERLAY_SHUTDOWN_TIMEOUT = 2.0
HTTP_CONNECT_TIMEOUT = 5.0
HTTP_REQUEST_TIMEOUT = 10.0
SYNC_OPERATION_TIMEOUT = 10.0

# Cache Limits
MAX_IMAGE_CACHE_SIZE = 20
MAX_FONT_CACHE_SIZE = 10
MAX_PROGRESS_TRACK_CACHE_SIZE = 20
MAX_PROGRESS_GRADIENT_CACHE_SIZE = 20
MAX_CORNER_CACHE_SIZE = 30
MAX_LOADING_BAR_CACHE_SIZE = 10
MAX_INLINE_TOKEN_CACHE_SIZE = 100
MAX_TEXT_WRAP_CACHE_SIZE = 200
MAX_TEXT_SIZE_CACHE_SIZE = 2000

# Colors (hex format)
DEFAULT_BG_COLOR = "#1e212b"
DEFAULT_TEXT_COLOR = "#f0f0f0"
DEFAULT_ACCENT_COLOR = "#00aaff"
DEFAULT_LOADING_COLOR = "#00aaff"

# Visual Defaults
DEFAULT_OPACITY = 0.85
DEFAULT_BORDER_RADIUS = 12
DEFAULT_FONT_SIZE = 16
DEFAULT_FONT_FAMILY = "Segoe UI"
DEFAULT_CONTENT_PADDING = 16
DEFAULT_LINE_HEIGHT = 26

# Behavior Defaults
DEFAULT_TYPEWRITER_SPEED = 200  # chars per second
DEFAULT_FADE_DELAY = 8.0  # seconds
DEFAULT_FADE_DURATION = 0.5  # seconds
DEFAULT_AUTO_HIDE_DELAY = 10.0  # seconds

# Layout
DEFAULT_ANCHOR = "top_left"
DEFAULT_LAYOUT_MODE = "auto"
DEFAULT_PRIORITY = 10
DEFAULT_Z_ORDER = 0

# Chat
DEFAULT_MAX_MESSAGES = 50
DEFAULT_MESSAGE_SPACING = 8

# Progress/Timer
PROGRESS_TRANSITION_DURATION = 0.5  # seconds

# Thread Names
THREAD_NAME_SERVER = "HUDServerThread"
THREAD_NAME_OVERLAY = "HUDOverlayThread"
THREAD_NAME_CLIENT_LOOP = "HUDClientLoopThread"

# API Paths
PATH_HEALTH = "/health"
PATH_ROOT = "/"
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
PATH_CHAT_SHOW = "/chat/show"
PATH_CHAT_HIDE = "/chat/hide"
PATH_ELEMENT_SHOW = "/element/show"
PATH_ELEMENT_HIDE = "/element/hide"
PATH_STATE = "/state"
PATH_STATE_RESTORE = "/state/restore"

# Window Types
WINDOW_TYPE_MESSAGE = "message"
WINDOW_TYPE_PERSISTENT = "persistent"
WINDOW_TYPE_CHAT = "chat"

# Fade States
FADE_STATE_HIDDEN = 0
FADE_STATE_FADE_IN = 1
FADE_STATE_VISIBLE = 2
FADE_STATE_FADE_OUT = 3

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

# Layout Modes
LAYOUT_MODE_AUTO = "auto"
LAYOUT_MODE_MANUAL = "manual"
LAYOUT_MODE_HYBRID = "hybrid"

# HTTP Status Codes
HTTP_OK = 200
HTTP_NOT_FOUND = 404
HTTP_VALIDATION_ERROR = 422
HTTP_INTERNAL_ERROR = 500

# Log Messages
LOG_SERVER_STARTED = "[HUD] Server started on http://{}:{}/docs"
LOG_SERVER_STOPPED = "[HUD] Server stopped"
LOG_SERVER_STARTUP_TIMEOUT = "[HUD] Failed to start within {}s timeout"
LOG_SERVER_ALREADY_RUNNING = "[HUD] Server already running"
LOG_OVERLAY_STARTED = "[HUD] Overlay renderer started"
LOG_OVERLAY_STOPPED = "[HUD] Overlay renderer stopped"
LOG_OVERLAY_NOT_AVAILABLE = "[HUD] Overlay not available (PIL or HeadsUpOverlay missing)"
LOG_OVERLAY_ALREADY_RUNNING = "[HUD] Overlay already running"
LOG_MONITORS_AVAILABLE = "[HUD] Available monitors: {}"
LOG_MONITOR_NONE = "[HUD] No monitors detected via EnumDisplayMonitors, using GetSystemMetrics"
LOG_MONITOR_SELECTED = "[HUD] Screen {} selected: {}x{}"
LOG_MONITOR_FALLBACK_GETSYSTEMMETRICS = "[HUD] Screen {} requested, falling back to GetSystemMetrics: {}x{}"
LOG_MONITOR_FALLBACK_UNAVAILABLE = "[HUD] Screen {} requested but not available, falling back to screen {}: {}x{}"
LOG_MONITOR_NONE_AVAILABLE = "[HUD] No monitors available, using hardcoded fallback: 1920x1080"
LOG_MONITOR_ERROR = "[HUD] Error enumerating monitors: {}"
