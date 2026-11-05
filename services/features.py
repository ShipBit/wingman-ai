"""Features that are built but not yet released on every update channel.

The channel comes from the build (services/build_channel.py), so the same
commit can ship a feature on unstable and leave it out of production. Where a
feature is not released, its code ships but nothing of it runs, and the client
shows nothing of it. Releasing it everywhere means removing it from
RELEASED_ON; once that is done, its checks can go.

A skill marks the settings of such a feature with `feature: <name>` on their
property group: Core drops the group and its settings where the feature is not
released, so the UI never offers them. Under `unreleased: {<name>: {...}}` a
skill names manifest fields, like its description, that replace its own there.
"""

from services import build_channel

SC_TELEMETRY = "sc_telemetry"

RELEASED_ON: dict[str, tuple[str, ...]] = {
    # Star Citizen's telemetry stream (services/sc_telemetry). Production
    # follows once testers on unstable have used it for a while.
    SC_TELEMETRY: ("unstable",),
}
"""The channels each feature is released on. A feature not listed is released everywhere."""


def released(feature: str) -> bool:
    channels = RELEASED_ON.get(feature)
    return channels is None or build_channel.CHANNEL in channels


def drop_unreleased_features(skill_manifest: dict | None) -> dict | None:
    """A skill's default_config.yaml as this build offers it: without the
    property groups of features that are not released, without the settings
    in them, and with the fields the skill replaces for such a feature."""
    if not skill_manifest:
        return skill_manifest
    overrides = skill_manifest.pop("unreleased", None)
    if isinstance(overrides, dict):
        for feature, fields in overrides.items():
            if not released(feature) and isinstance(fields, dict):
                skill_manifest.update(fields)
    if not skill_manifest.get("property_groups"):
        return skill_manifest
    dropped = {
        group.get("id")
        for group in skill_manifest["property_groups"]
        if isinstance(group, dict) and group.get("feature") and not released(group["feature"])
    }
    if not dropped:
        return skill_manifest
    skill_manifest["property_groups"] = [
        group
        for group in skill_manifest["property_groups"]
        if not isinstance(group, dict) or group.get("id") not in dropped
    ]
    if skill_manifest.get("custom_properties"):
        skill_manifest["custom_properties"] = [
            prop
            for prop in skill_manifest["custom_properties"]
            if not isinstance(prop, dict) or prop.get("group") not in dropped
        ]
    return skill_manifest
