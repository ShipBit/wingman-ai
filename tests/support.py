"""Paths and helpers shared by more than one test module.

Fixtures live in conftest.py. This module holds plain functions and constants,
so test modules import them explicitly instead of from conftest.
"""

import importlib
import os
import queue
import shutil
from os import path
from types import SimpleNamespace

import yaml

from hud_server.platform.base import HudBackend, Monitor
from services.system_manager import LOCAL_VERSION

REPO_ROOT = path.dirname(path.dirname(path.abspath(__file__)))
TEMPLATES = path.join(REPO_ROOT, "templates", "configs")
FIXTURES = path.join(REPO_ROOT, "tests", "fixtures")
# The config folder name of the version under test, e.g. "3_2_5".
VERSION_DIR = LOCAL_VERSION.replace(".", "_")


def read_yaml(file_path: str):
    with open(file_path, "r", encoding="UTF-8") as f:
        return yaml.safe_load(f)


def write_yaml(file_path: str, content) -> None:
    with open(file_path, "w", encoding="UTF-8") as f:
        yaml.safe_dump(content, f)


def migration_modules() -> list:
    """Every config migration module, imported."""
    folder = path.join(REPO_ROOT, "services", "migrations")
    return [
        importlib.import_module(f"services.migrations.{name[:-3]}")
        for name in sorted(os.listdir(folder))
        if name.startswith("migration_") and name.endswith(".py")
    ]


def template(name: str):
    """A file from templates/configs, parsed."""
    return read_yaml(path.join(TEMPLATES, name))


def config_names(users_dir: str, version_dir: str = VERSION_DIR) -> list[str]:
    """The visible config folders of one version, sorted."""
    configs = path.join(users_dir, version_dir, "configs")
    return sorted(
        d
        for d in os.listdir(configs)
        if path.isdir(path.join(configs, d)) and not d.startswith(".")
    )


# ── an older install on disk ───────────────────────────────────────────


def make_old_version(users_dir: str, version_dir: str, config_dirs: dict) -> str:
    """Create the config folder an older Wingman left behind.

    `config_dirs` maps a folder name (legacy prefixes allowed) to its files:
    filename -> YAML content, or None to copy the shipped template wingman.
    settings.yaml and defaults.yaml are copied from the current templates.
    """
    old_configs = path.join(users_dir, version_dir, "configs")
    os.makedirs(old_configs)

    for filename in ("settings.yaml", "defaults.yaml"):
        shutil.copyfile(path.join(TEMPLATES, filename), path.join(old_configs, filename))

    # Every completed version has this marker. Without it the folder counts as
    # an interrupted migration.
    with open(path.join(old_configs, ".migration"), "w", encoding="UTF-8") as f:
        f.write(f"Version {version_dir} - test fixture\n")

    for dir_name, files in config_dirs.items():
        dir_path = path.join(old_configs, dir_name)
        os.makedirs(dir_path)
        for filename, content in files.items():
            file_path = path.join(dir_path, filename)
            if content is None:
                template_name = filename.lstrip(".").replace(".yaml", ".template.yaml")
                template_dir = dir_name.lstrip("._") or dir_name
                shutil.copyfile(path.join(TEMPLATES, template_dir, template_name), file_path)
            else:
                write_yaml(file_path, content)

    return old_configs


def migration_service(config_manager):
    from services.config_migration_service import ConfigMigrationService
    from services.system_manager import SystemManager

    return ConfigMigrationService(config_manager=config_manager, system_manager=SystemManager())


def boot_and_migrate(boot_config_manager):
    """Start the way main.py does: ConfigManager first, then the migrations."""
    config_manager = boot_config_manager()
    service = migration_service(config_manager)
    service.migrate_to_latest()
    return config_manager, service


# ── a ConfigManager over a plain folder ────────────────────────────────


class FakeConfigManager:
    """The few ConfigManager methods the voice and language helpers call,
    over `root/configs/<config>/<wingman>.yaml`."""

    def __init__(self, root):
        self.config_dir = str(root / "configs")

    def get_config_dirs(self):
        return [
            SimpleNamespace(name=d, directory=d)
            for d in sorted(os.listdir(self.config_dir))
            if path.isdir(path.join(self.config_dir, d))
        ]

    def get_wingmen_configs(self, config_dir):
        folder = path.join(self.config_dir, config_dir.directory)
        return [
            SimpleNamespace(name=f[:-5], file=f)
            for f in sorted(os.listdir(folder))
            if f.endswith(".yaml")
        ]

    def read_config(self, file_path):
        return read_yaml(file_path)

    def write_config(self, file_path, content):
        write_yaml(file_path, content)
        return True


# ── a HUD backend without an operating system ──────────────────────────


class FakeHudBackend(HudBackend):
    """The HUD's windows as plain records, so the overlay runs on any OS.
    `present` keeps a copy of the image; `pointer()` plays the mouse."""

    def __init__(self, monitors=None):
        self.screens = [Monitor(0, 0, 1920, 1080, True)] if monitors is None else monitors
        self.windows: list[SimpleNamespace] = []
        self.cursor = (0, 0)
        self.captured = None
        self.started = False

    def start(self):
        self.started = True

    def stop(self):
        self.started = False
        self.windows.clear()

    def pump_events(self):
        pass

    def create_window(self, title, x, y, width, height):
        window = SimpleNamespace(
            title=title, rect=(x, y, width, height), shown=True, image=None,
            opacity=0, click_through=True, handler=None, raised=0,
        )
        self.windows.append(window)
        return window

    def destroy_window(self, window):
        if window in self.windows:
            self.windows.remove(window)

    def move_window(self, window, x, y, width, height):
        window.rect = (x, y, width, height)

    def raise_window(self, window):
        window.raised += 1

    def show_window(self, window):
        window.shown = True

    def hide_window(self, window):
        window.shown = False

    def present(self, window, image, opacity):
        window.image = image.copy()
        window.opacity = opacity

    def set_click_through(self, window, click_through):
        window.click_through = click_through

    def set_pointer_handler(self, window, handler):
        window.handler = handler

    def capture_pointer(self, window):
        self.captured = window

    def release_pointer(self):
        self.captured = None

    def cursor_position(self):
        return self.cursor

    def monitors(self):
        return list(self.screens)

    def window(self, title: str):
        return next(w for w in self.windows if w.title == title)

    def pointer(self, window, event, x, y):
        """The mouse did `event` at screen (x, y) over `window`."""
        self.cursor = (x, y)
        return window.handler(event, x, y) if window.handler else None


def make_overlay(backend, events=None):
    """A HUD overlay on `backend`, fonts loaded, ready to step frames by hand."""
    from hud_server.overlay.overlay import HeadsUpOverlay

    overlay = HeadsUpOverlay(
        command_queue=queue.Queue(),
        error_queue=queue.Queue(),
        event_callback=(events.append if events is not None else None),
        backend=backend,
    )
    overlay._init_fonts()
    overlay.dt = 0.05
    return overlay


def run_frames(overlay, count=10):
    for _ in range(count):
        overlay._update_all_windows()


def overlay_errors(overlay) -> list:
    """The errors the overlay reported so far (heartbeats left out)."""
    reports = []
    while not overlay.error_queue.empty():
        report = overlay.error_queue.get()
        if isinstance(report, dict) and report.get("type") == "error":
            reports.append(report)
    return reports
