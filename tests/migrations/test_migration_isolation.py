"""Migration tests never reach the real user folder."""

from os import path

from tests.support import migration_modules

PATH_HELPERS = ("get_users_dir", "get_custom_skills_dir", "get_audio_library_dir", "get_writable_dir")


def test_every_migration_step_works_in_the_test_folder(users_dir):
    root = path.realpath(users_dir)
    for module in migration_modules():
        for name in PATH_HELPERS:
            helper = getattr(module, name, None)
            if helper is not None:
                assert path.realpath(helper()).startswith(root), f"{module.__name__}.{name}"
