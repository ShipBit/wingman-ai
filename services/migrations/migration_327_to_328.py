"""Migration from version 3.2.7 to 3.2.8.

3.2.7 is out with testers, so the next change to a user's config needs its own
step.

`settings.yaml` gains a `star_citizen` block. The Star Citizen folder moves
there from `sc_gamelog.game_path`: the log reader is the first feature that
reads the game's files, the key bindings come next, and both read the same
folder. Skills see it as `self.wingman.star_citizen`.

`star_citizen.plays` is null for every user, also for one who used Wingman
before. The client asks once after the update whether they play Star Citizen:
the log reader is new in 3.2.x and is on for everyone, and the answer
switches it and the other Star Citizen features on or off in one go.
"""

from services.migrations.base_migration import BaseMigration
from services.star_citizen.game_folder import DEFAULT_GAME_PATH


class Migration327To328(BaseMigration):
    """Migration from 3.2.7 to 3.2.8."""

    old_version = "3_2_7"
    new_version = "3_2_8"

    def migrate_settings(self, old: dict) -> dict:
        if "star_citizen" not in old:
            sc_gamelog = old.get("sc_gamelog")
            game_path = None
            if isinstance(sc_gamelog, dict):
                game_path = sc_gamelog.pop("game_path", None)
            game_path = game_path or DEFAULT_GAME_PATH
            old["star_citizen"] = {"plays": None, "game_path": game_path}
            self.log(f"- added star_citizen, game folder {game_path}")
        return old
