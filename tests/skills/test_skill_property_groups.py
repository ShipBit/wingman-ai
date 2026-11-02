"""A skill groups its settings in the UI with `property_groups` in its manifest.

Groups only change how the settings look, so a mistake in them must never cost
the skill: a broken group is left out and its settings are shown ungrouped. The
group of a setting comes from the manifest alone, also for a Wingman saved
before the skill had groups.
"""

from unittest.mock import MagicMock

from api.interface import SkillConfig
from services.config_manager import ConfigManager
from services.skill_catalog import property_group_problems


def manifest(groups, props):
    return {
        "module": "skills.grouped.main",
        "name": "Grouped",
        "display_name": "Grouped",
        "description": {"en": "A fake skill."},
        "property_groups": groups,
        "custom_properties": props,
    }


def prop(prop_id, group=None):
    entry = {"id": prop_id, "name": prop_id, "value": True, "property_type": "boolean"}
    if group is not None:
        entry["group"] = group
    return entry


def test_groups_keep_the_order_of_the_manifest():
    config = SkillConfig(
        **manifest(
            [{"id": "combat", "name": "Combat", "hint": "In a fight."}, {"id": "body", "name": "Body"}],
            [prop("hunger", "body"), prop("shields", "combat"), prop("limit")],
        )
    )

    assert [(g.id, g.name, g.hint) for g in config.property_groups] == [
        ("combat", "Combat", "In a fight."),
        ("body", "Body", None),
    ]
    assert [p.group for p in config.custom_properties] == ["body", "combat", None]
    assert property_group_problems(config) == []


def test_broken_groups_are_left_out_instead_of_failing_the_skill():
    config = SkillConfig(
        **manifest(
            [
                {"id": "combat", "name": "Combat"},
                {"id": "nameless"},
                {"name": "No id"},
                "just a string",
                {"id": "combat", "name": "Second combat"},
                {"id": "body", "name": "Body", "hint": ["not", "text"]},
            ],
            [prop("shields", "combat")],
        )
    )

    assert [(g.id, g.name, g.hint) for g in config.property_groups] == [
        ("combat", "Combat", None),
        ("body", "Body", None),
    ]


def test_groups_that_are_no_list_mean_no_groups():
    config = SkillConfig(**manifest({"combat": "Combat"}, [prop("shields", "combat")]))

    assert config.property_groups is None


def test_a_group_that_is_no_text_shows_the_setting_ungrouped():
    config = SkillConfig(**manifest(None, [prop("shields", 5), prop("hull", ["a"]), prop("fuel", "")]))

    assert [p.group for p in config.custom_properties] == [None, None, None]


def test_settings_in_a_group_the_skill_does_not_define_are_reported():
    config = SkillConfig(
        **manifest(
            [{"id": "combat", "name": "Combat"}, {"id": "nameless"}],
            [prop("shields", "combat"), prop("hunger", "nameless"), prop("fuel", "typo")],
        )
    )

    problems = property_group_problems(config)

    assert len(problems) == 2
    assert "'hunger'" in problems[0] and "'nameless'" in problems[0]
    assert "'fuel'" in problems[1] and "'typo'" in problems[1]


def test_a_saved_wingman_gets_the_group_from_the_manifest():
    """Saved before the skill had groups: the stored entries have none."""
    manager = ConfigManager.__new__(ConfigManager)
    manager.printr = MagicMock()
    default = manifest(
        [{"id": "combat", "name": "Combat"}],
        [prop("shields", "combat"), prop("hull", "combat")],
    )
    saved = {
        "module": "skills.grouped.main",
        "custom_properties": [
            {"id": "shields", "value": False},
            # Older configs stored the whole property.
            {"id": "hull", "name": "Hull", "value": False, "property_type": "boolean"},
        ],
    }

    merged = SkillConfig(**manager._ConfigManager__deep_merge(default, saved))

    assert [(p.id, p.value, p.group) for p in merged.custom_properties] == [
        ("shields", False, "combat"),
        ("hull", False, "combat"),
    ]
    assert [g.id for g in merged.property_groups] == ["combat"]
