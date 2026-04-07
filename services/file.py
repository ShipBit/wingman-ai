from os import makedirs, path
from functools import lru_cache
from platformdirs import PlatformDirs
from services.system_manager import LOCAL_VERSION

APP_NAME = "WingmanAI"
APP_AUTHOR = "ShipBit"

_PROMPTS_DIR = path.join(path.abspath(path.dirname(__file__)), "..", "prompts")


@lru_cache(maxsize=None)
def get_prompt(name: str) -> str:
    """Load a prompt template from the prompts/ directory.

    Args:
        name: Filename without extension, e.g. 'condense-conversation'.

    Returns:
        The prompt text with leading/trailing whitespace stripped.
    """
    filepath = path.join(_PROMPTS_DIR, f"{name}.md")
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read().strip()


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


def get_local_models_dir() -> str:
    """Get the path to the local AI models directory.

    NOT versioned - models persist across Wingman AI updates.
    Location: APPDATA/WingmanAI/local_models/
    """
    dirs = PlatformDirs(
        appname=APP_NAME,
        appauthor=APP_AUTHOR,
        ensure_exists=True,
        roaming=True,
    )
    local_models_path = path.join(dirs.user_data_dir, "local_models")
    if not path.exists(local_models_path):
        makedirs(local_models_path)
    return local_models_path


def get_models_dir() -> str:
    """Get the path to the unified models directory.

    NOT versioned - models persist across Wingman AI updates.
    Location: APPDATA/WingmanAI/models/
    """
    dirs = PlatformDirs(
        appname=APP_NAME,
        appauthor=APP_AUTHOR,
        ensure_exists=True,
        roaming=True,
    )
    models_path = path.join(dirs.user_data_dir, "models")
    if not path.exists(models_path):
        makedirs(models_path)
    return models_path


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
    _create_custom_voices_readme(custom_voices_path)
    return custom_voices_path


def get_persistent_memory_dir() -> str:
    """Get the path to the persistent memory directory.

    NOT versioned - persistent memory survives across Wingman AI updates.
    Location: APPDATA/WingmanAI/persistent_memory/
    """
    dirs = PlatformDirs(
        appname=APP_NAME,
        appauthor=APP_AUTHOR,
        ensure_exists=True,
        roaming=True,
    )
    persistent_memory_path = path.join(dirs.user_data_dir, "persistent_memory")
    if not path.exists(persistent_memory_path):
        makedirs(persistent_memory_path)
    return persistent_memory_path


def _create_custom_voices_readme(custom_voices_path: str) -> None:
    """Create a readme file in the custom voices directory with instructions in all supported languages."""
    content = """# Voice Cloning

To clone a voice, simply put a cloning sample into this directory here and reopen the voice selection dropdown in Wingman AI afterwards. There are 2 possible formats:
- safetensor: Very fast and recommended
- wav: Slower but also possible

Voice samples should be around 30secs long and contain clean audio of the voice to clone - without any background noise or other interference.

The best wav format to clone is 22.050Hz Mono.

---

# Stimmenklonen (Deutsch)

Um eine Stimme zu klonen, lege einfach eine Klonvorlage in dieses Verzeichnis und öffne anschließend das Stimmenauswahl-Dropdown in Wingman AI erneut. Es gibt 2 mögliche Formate:
- safetensor: Sehr schnell und empfohlen
- wav: Langsamer, aber ebenfalls möglich

Stimmproben sollten ca. 30 Sekunden lang sein und sauberes Audio der zu klonenden Stimme enthalten - ohne Hintergrundgeräusche oder andere Störungen.

Das beste WAV-Format zum Klonen ist 22.050Hz Mono.

---

# Clonación de voz (Español)

Para clonar una voz, simplemente coloca una muestra de clonación en este directorio y vuelve a abrir el menú desplegable de selección de voz en Wingman AI. Hay 2 formatos posibles:
- safetensor: Muy rápido y recomendado
- wav: Más lento pero también posible

Las muestras de voz deben tener unos 30 segundos de duración y contener audio limpio de la voz a clonar, sin ruido de fondo ni otras interferencias.

El mejor formato wav para clonar es 22.050Hz Mono.

---

# Clonage vocal (Français)

Pour cloner une voix, placez simplement un échantillon de clonage dans ce répertoire et rouvrez le menu déroulant de sélection de voix dans Wingman AI. Il existe 2 formats possibles :
- safetensor : Très rapide et recommandé
- wav : Plus lent mais également possible

Les échantillons vocaux doivent durer environ 30 secondes et contenir un audio propre de la voix à cloner, sans bruit de fond ni autre interférence.

Le meilleur format wav pour le clonage est 22.050Hz Mono.
"""
    readme_path = path.join(custom_voices_path, "README.txt")
    if not path.exists(readme_path):
        with open(readme_path, "w", encoding="utf-8") as f:
            f.write(content)
