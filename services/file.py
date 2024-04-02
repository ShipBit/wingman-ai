from os import makedirs, path
from platformdirs import PlatformDirs
from services.system_manager import LOCAL_VERSION


def get_writable_dir(subdir: str = None) -> str:
    dirs = PlatformDirs(
        appname="WingmanAI",
        appauthor="ShipBit",
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
