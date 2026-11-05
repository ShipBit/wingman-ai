"""Features that are built but not yet released on every update channel.

develop keeps every flag on, so unstable builds get the feature. A stable
release branch turns a flag off in one commit: the code ships, but nothing of
it runs and the client shows nothing of it. Once the feature is released, its
flag and this check go away.

A skill marks the settings of such a feature with `feature: <name>` on their
property group. Core drops the group and its settings while the feature is
off, so the UI never offers them.
"""

SC_TELEMETRY = "sc_telemetry"

SC_TELEMETRY_RELEASED = False
"""Star Citizen's telemetry stream (services/sc_telemetry). Off on stable
until it has been tested more on unstable."""


def released(feature: str) -> bool:
    if feature == SC_TELEMETRY:
        return SC_TELEMETRY_RELEASED
    return True


def drop_unreleased_properties(skill_manifest: dict | None) -> dict | None:
    """A skill's default_config.yaml without the property groups of features
    that are not released, and without the settings in them."""
    if not skill_manifest or not skill_manifest.get("property_groups"):
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
