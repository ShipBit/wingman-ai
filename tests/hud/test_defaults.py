"""HUD server defaults: values a group's own calls leave out."""

from hud_server.hud_manager import HudManager


def _manager_with_overlay():
    manager = HudManager()
    commands = []
    manager.register_command_callback(commands.append)
    return manager, commands


def test_a_group_inherits_the_defaults_for_what_it_does_not_set():
    manager, _ = _manager_with_overlay()
    manager.set_defaults(
        props={"font_size": 18, "accent_color": "#ff0000"},
        groups={"wingman_chat": {"x": 100, "width": 500}},
    )
    manager.create_group("wingman_chat", "message", {"accent_color": "#00ff00"})

    resolved = manager.resolve_props("wingman_chat", "message")

    assert resolved == {"font_size": 18, "accent_color": "#00ff00", "x": 100, "width": 500}


def test_group_defaults_only_apply_to_their_own_group():
    manager, _ = _manager_with_overlay()
    manager.set_defaults(props={"font_size": 18}, groups={"wingman_chat": {"x": 100}})

    assert manager.resolve_props("ATC_mic", "persistent") == {"font_size": 18}


def test_new_defaults_replace_the_old_ones_and_reach_the_overlay():
    manager, commands = _manager_with_overlay()
    manager.set_defaults(props={"font_size": 18}, groups={"wingman_chat": {"x": 100}})
    manager.set_defaults(props={"opacity": 0.5})

    assert manager.get_defaults() == {"props": {"opacity": 0.5}, "groups": {}}
    assert commands[-1] == {"type": "set_defaults", "props": {"opacity": 0.5}, "groups": {}}


def test_deleting_one_element_tells_the_overlay_which_one():
    manager, commands = _manager_with_overlay()
    manager.create_group("ATC", "message")
    manager.create_group("ATC", "persistent")

    manager.delete_group("ATC", "persistent")

    assert commands[-1] == {"type": "delete_group", "group": "ATC", "element": "persistent"}
    assert manager.get_groups() == ["message_ATC"]
