from os import makedirs, path
from platformdirs import PlatformDirs
from services.system_manager import LOCAL_VERSION

APP_NAME = "WingmanAI"
APP_AUTHOR = "ShipBit"


def get_writable_dir(subdir: str = None) -> str:
    dirs = PlatformDirs(
        appname=APP_NAME,
        appauthor=APP_AUTHOR,
        version=LOCAL_VERSION.replace(".", "_"),
        ensure_exists=True,
        roaming=True,
    )
    if subdir is None:
        return dirs.user_data_dir

    full_path = path.join(dirs.user_data_dir, subdir)
    if not path.exists(full_path):
        makedirs(full_path)
    return full_path


def get_users_dir() -> str:
    dirs = PlatformDirs(
        appname=APP_NAME,
        appauthor=APP_AUTHOR,
        ensure_exists=True,
        roaming=True,
    )
    return dirs.user_data_dir


def get_custom_skills_dir() -> str:
    """Get the path to the custom skills directory.

    Unlike get_writable_dir(), this is NOT versioned - custom skills persist
    across Wingman AI updates. Location: APPDATA/WingmanAI/custom_skills/
    """
    dirs = PlatformDirs(
        appname=APP_NAME,
        appauthor=APP_AUTHOR,
        ensure_exists=True,
        roaming=True,
    )
    custom_skills_path = path.join(dirs.user_data_dir, "custom_skills")
    if not path.exists(custom_skills_path):
        makedirs(custom_skills_path)
    return custom_skills_path
