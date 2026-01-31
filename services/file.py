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


def get_audio_library_dir() -> str:
    """Get the path to the audio library directory.

    Unlike get_writable_dir(), this is NOT versioned - audio library persists
    across Wingman AI updates. Location: APPDATA/WingmanAI/audio_library/
    """
    dirs = PlatformDirs(
        appname=APP_NAME,
        appauthor=APP_AUTHOR,
        ensure_exists=True,
        roaming=True,
    )
    audio_library_path = path.join(dirs.user_data_dir, "audio_library")
    if not path.exists(audio_library_path):
        makedirs(audio_library_path)
    return audio_library_path


def get_generated_files_dir(skill_name: str) -> str:
    """Get the path to a skill's generated files directory.

    Unlike get_writable_dir(), this is NOT versioned - generated files persist
    across Wingman AI updates. Location: APPDATA/WingmanAI/generated_files/[skill_name]/

    Args:
        skill_name: The name of the skill (e.g., 'auto_screenshot', 'file_manager')

    Returns:
        The absolute path to the skill's generated files directory
    """
    dirs = PlatformDirs(
        appname=APP_NAME,
        appauthor=APP_AUTHOR,
        ensure_exists=True,
        roaming=True,
    )
    generated_files_path = path.join(dirs.user_data_dir, "generated_files", skill_name)
    if not path.exists(generated_files_path):
        makedirs(generated_files_path)
    return generated_files_path

def get_custom_voices_dir() -> str:
    """Get the path to the custom voices directory used for PocketTTS or future cloning providers.

    Unlike get_writable_dir(), this is NOT versioned - custom voices persist
    across Wingman AI updates. Location: APPDATA/WingmanAI/custom_voices/
    """
    dirs = PlatformDirs(
        appname=APP_NAME,
        appauthor=APP_AUTHOR,
        ensure_exists=True,
        roaming=True,
    )
    custom_voices_path = path.join(dirs.user_data_dir, "custom_voices")
    if not path.exists(custom_voices_path):
        makedirs(custom_voices_path)
    return custom_voices_path