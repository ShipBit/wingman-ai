"""Detection and extraction of versioned Star Citizen keybinding resources."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any, Dict, Iterable, Optional
import xml.etree.ElementTree as ET


class SCGameFileError(RuntimeError):
    """Raised when installed Star Citizen files cannot be prepared."""


@dataclass(frozen=True)
class SCBuild:
    """Identity of one installed Star Citizen channel build."""

    channel: str
    branch: str
    build_id: str
    build_version: str
    version_directory: str


def version_directory_from_branch(branch: str) -> str:
    """Convert e.g. ``sc-alpha-4.10.0-hotfix`` to the repository's ``R4_100`` form."""
    match = re.search(
        r"(?:^|[-_])alpha[-_](?P<major>\d+)\.(?P<minor>\d+)(?:\.(?P<patch>\d+))?",
        branch,
        flags=re.IGNORECASE,
    )
    if not match:
        raise SCGameFileError(f"Unsupported Star Citizen branch format: {branch!r}")

    major = match.group("major")
    minor = match.group("minor")
    patch = match.group("patch")
    release = f"{minor}{patch}" if patch is not None else minor
    return f"R{major}_{release}"


def detect_installed_build(installation_dir: Path, channel: str) -> Optional[SCBuild]:
    """Read the channel's build_manifest.id, returning ``None`` when it is not installed."""
    manifest_path = installation_dir / channel / "build_manifest.id"
    if not manifest_path.is_file():
        return None

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        build_data = manifest["Data"]
        branch = str(build_data["Branch"])
        return SCBuild(
            channel=channel,
            branch=branch,
            build_id=str(build_data.get("BuildId", "")),
            build_version=str(build_data.get("Version", "")),
            version_directory=version_directory_from_branch(branch),
        )
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise SCGameFileError(f"Invalid Star Citizen build manifest: {manifest_path}") from exc


class SCGameFileExtractor:
    """Extract the SC files consumed by :class:`SCKeybindings` with unp4k-suite."""

    EXTRACTION_STATE_FILE = ".sc-extraction.json"
    DEFAULT_TRANSLATION_DIRECTORIES = {
        "en_GB": "english",
        "de_DE": "german_(germany)",
        "fr_FR": "french_(france)",
        "es_ES": "spanish_(spain)",
        "es_419": "spanish_(latin_america)",
        "it_IT": "italian_(italy)",
        "ja_JP": "japanese_(japan)",
        "ko_KR": "korean_(south_korea)",
        "pt_BR": "portuguese_(brazil)",
        "zh_CN": "chinese_(simplified)",
        "zh_TW": "chinese_(traditional)",
    }

    def __init__(
        self,
        mapping_config: Dict[str, Any],
        installation_dir: Path,
        command_languages: Iterable[str],
    ):
        self.mapping_config = mapping_config
        self.installation_dir = installation_dir
        self.command_languages = tuple(dict.fromkeys(command_languages))
        self.default_profile_name = mapping_config[
            "sc_unp4k_file_default_keybindings_filter"
        ]
        self.localization_name = mapping_config[
            "sc_unp4k_file_keybinding_localization_filter"
        ]
        self.translations_filter = mapping_config.get(
            "sc_unp4k_translations_filter", "global.ini"
        )
        self.english_target_name = mapping_config.get(
            "en_translation_file", "global_en_GB.ini"
        )
        self.timeout_seconds = int(mapping_config.get("sc_unp4k_timeout_seconds", 900))

        self.translation_directories = dict(self.DEFAULT_TRANSLATION_DIRECTORIES)
        self.translation_directories.update(
            mapping_config.get("sc_translation_language_directories", {})
        )

    def required_target_files(self) -> set[str]:
        required = {
            self.default_profile_name,
            self.localization_name,
            self.english_target_name,
        }
        required.update(f"global_{language}.ini" for language in self.command_languages)
        return required

    def ensure_extracted(self, build: SCBuild, version_dir: Path) -> bool:
        """Extract a build if its identity or any required output differs.

        Returns ``True`` when extraction was performed.
        """
        if not self._needs_extraction(build, version_dir):
            return False

        unp4k, unforge = self._resolve_tools()
        data_archive = self.installation_dir / build.channel / "Data.p4k"
        if not data_archive.is_file():
            raise SCGameFileError(f"Star Citizen archive not found: {data_archive}")

        with tempfile.TemporaryDirectory(prefix="wingman-sc-keybindings-") as temp_name:
            extraction_root = Path(temp_name)
            for file_filter in dict.fromkeys(
                (self.default_profile_name, self.localization_name, self.translations_filter)
            ):
                self._run_tool(unp4k, (data_archive, file_filter), extraction_root)

            default_profile = self._find_unique_file(
                extraction_root, self.default_profile_name
            )
            localization = self._find_unique_file(
                extraction_root, self.localization_name
            )
            self._convert_cryxml(unforge, default_profile, extraction_root)
            self._convert_cryxml(unforge, localization, extraction_root)
            self._validate_xml(default_profile)
            self._validate_xml(localization)

            normalized_dir = extraction_root / "normalized"
            normalized_dir.mkdir()
            shutil.copy2(default_profile, normalized_dir / self.default_profile_name)
            shutil.copy2(localization, normalized_dir / self.localization_name)
            self._normalize_translations(extraction_root, normalized_dir)

            missing = self.required_target_files() - {
                path.name for path in normalized_dir.iterdir() if path.is_file()
            }
            if missing:
                raise SCGameFileError(
                    "Extracted Star Citizen build is missing required files: "
                    + ", ".join(sorted(missing))
                )

            version_dir.mkdir(parents=True, exist_ok=True)
            for source in normalized_dir.iterdir():
                if source.is_file():
                    shutil.copy2(source, version_dir / source.name)

        state = {
            **asdict(build),
            "extracted_at": datetime.now(timezone.utc).isoformat(),
            "files": sorted(self.required_target_files()),
        }
        (version_dir / self.EXTRACTION_STATE_FILE).write_text(
            json.dumps(state, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return True

    def _needs_extraction(self, build: SCBuild, version_dir: Path) -> bool:
        if any(not (version_dir / name).is_file() for name in self.required_target_files()):
            return True

        state_path = version_dir / self.EXTRACTION_STATE_FILE
        if not state_path.is_file():
            return True
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return True
        return state.get("build_id") != build.build_id or state.get("branch") != build.branch

    def _resolve_tools(self) -> tuple[Path, Path]:
        configured = self.mapping_config.get("sc_unp4k_install_dir")
        if not configured:
            raise SCGameFileError(
                "sc_unp4k_install_dir must point to an installed unp4k-suite"
            )

        configured_path = Path(configured).expanduser()
        if configured_path.is_file():
            unp4k = configured_path
            tool_dir = configured_path.parent
        else:
            tool_dir = configured_path
            unp4k = self._first_existing(tool_dir / "unp4k.exe", tool_dir / "unp4k")
        unforge = self._first_existing(tool_dir / "unforge.exe", tool_dir / "unforge")

        if not unp4k or not unforge:
            raise SCGameFileError(
                f"unp4k/unforge executables not found in: {tool_dir}"
            )
        return unp4k, unforge

    @staticmethod
    def _first_existing(*candidates: Path) -> Optional[Path]:
        return next((candidate for candidate in candidates if candidate.is_file()), None)

    def _run_tool(self, executable: Path, args: Iterable[Any], cwd: Path) -> None:
        command = [str(executable), *(str(arg) for arg in args)]
        try:
            result = subprocess.run(
                command,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                errors="replace",
                timeout=self.timeout_seconds,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SCGameFileError(f"Could not run {executable.name}: {exc}") from exc
        if result.returncode != 0:
            details = (result.stderr or result.stdout or "no output").strip()[-2000:]
            raise SCGameFileError(
                f"{executable.name} failed with exit code {result.returncode}: {details}"
            )

    @staticmethod
    def _find_unique_file(root: Path, filename: str) -> Path:
        matches = [path for path in root.rglob(filename) if "normalized" not in path.parts]
        if len(matches) != 1:
            raise SCGameFileError(
                f"Expected one extracted {filename}, found {len(matches)}"
            )
        return matches[0]

    def _convert_cryxml(self, unforge: Path, xml_file: Path, cwd: Path) -> None:
        if xml_file.read_bytes()[:7] == b"CryXmlB":
            self._run_tool(unforge, (xml_file,), cwd)

    @staticmethod
    def _validate_xml(xml_file: Path) -> None:
        try:
            ET.parse(str(xml_file))
        except ET.ParseError as exc:
            raise SCGameFileError(f"Extracted XML is invalid: {xml_file.name}") from exc

    def _normalize_translations(self, extraction_root: Path, normalized_dir: Path) -> None:
        translations = {
            path.parent.name.casefold(): path
            for path in extraction_root.rglob(self.translations_filter)
            if "Localization" in path.parts and "normalized" not in path.parts
        }
        requested_locales = set(self.command_languages) | {"en_GB"}
        unmapped_locales = requested_locales - set(self.translation_directories)
        if unmapped_locales:
            raise SCGameFileError(
                "No Star Citizen translation directory mapping configured for: "
                + ", ".join(sorted(unmapped_locales))
            )

        for locale in requested_locales:
            directory_name = self.translation_directories[locale]
            source = translations.get(str(directory_name).casefold())
            if source:
                shutil.copy2(source, normalized_dir / f"global_{locale}.ini")

        english_source = translations.get(
            self.translation_directories["en_GB"].casefold()
        )
        if not english_source:
            raise SCGameFileError("English global.ini was not found in the extracted archive")
        shutil.copy2(english_source, normalized_dir / self.english_target_name)
        shutil.copy2(english_source, normalized_dir / "global.ini")
