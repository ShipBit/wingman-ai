import os
import psutil
from datetime import datetime

MEMORY_LOG_PATH = os.path.join("debug_data", "memory", "memory_usage.log")

# Set to True to enable memory usage logging
ENABLE_MEMORY_LOGGING = True


def log_memory_usage(tag: str) -> None:
    """Log current process memory usage with a tag if enabled."""
    if not ENABLE_MEMORY_LOGGING:
        return

    process = psutil.Process(os.getpid())
    mem_bytes = process.memory_info().rss
    mem_mb = mem_bytes / (1024 * 1024)

    os.makedirs(os.path.dirname(MEMORY_LOG_PATH), exist_ok=True)
    with open(MEMORY_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat()} - {tag}: {mem_mb:.2f} MB\n")

