"""Text-only routing evaluation. No input backend is instantiated or called.

Call evaluate(call_model, output, model_label) with the configured provider callback.
Mocked regression results must never be presented as this accuracy measurement.
"""
import json
from pathlib import Path
import time

from skills.elite_dangerous_controls.routing import IntentRouter
from services.printr import Printr


CASES = (
    ("Kill the bloody headlights", "ship", 0, "execute", "lights", "off"),
    ("It's pitch black, give me night vision", "ship", 0, "execute", "night_vision", "on"),
    ("Would you mind lowering the undercarriage for me?", "ship", 0, "execute", "landing_gear", "on"),
    ("Low wake, please", "ship", 0, "execute", "supercruise", "toggle"),
    ("High wake us the hell out", "ship", 0, "execute", "request_hyperspace_jump", "toggle"),
    ("Give me a quick boost", "ship", 0, "execute", "boost", "toggle"),
    ("Switch FA off for me", "ship", 0, "execute", "flight_assist", "off"),
    ("Put a pip into SYS", "ship", 0, "execute", "increase_system_power", "toggle"),
    ("Dump a heatsink, we're cooking", "ship", 0, "execute", "deploy_heat_sink", "toggle"),
    ("Pop an SCB", "ship", 0, "execute", "use_shield_cell", "toggle"),
    ("Can you put it in full reverse?", "ship", 0, "execute", "full_reverse_throttle", "toggle"),
    ("Bring the ship back to my rover", "srv", 0, "execute", "recall_dismiss_ship", "toggle"),
    ("Fresh magazine please", "on_foot", 0, "execute", "reload_weapon", "toggle"),
    ("Put my gun away", "on_foot", 0, "execute", "holster_weapon", "toggle"),
    ("Select the energy link", "on_foot", 0, "execute", "select_recharge_tool", "toggle"),
    ("One menu item lower please", "ship", 2, "execute", "menu_down", "toggle"),
    ("Zoom this scanner in one step", "ship", 9, "execute", "fss_step_zoom_in", "toggle"),
    ("Get us out of here", "ship", 0, "clarify", "", ""),
    ("Turn on the lights and lower the gear", "ship", 0, "clarify", "", ""),
    ("Don't turn the lights off", "ship", 0, "conversation", "", ""),
    ("Are the hardpoints deployed?", "ship", 0, "conversation", "", ""),
    ('He said "boost now" but I disagree', "ship", 0, "conversation", "", ""),
    ("If we get attacked we could deploy chaff", "ship", 0, "conversation", "", ""),
    ("That's a beautiful nebula", "ship", 0, "conversation", "", ""),
    ("Hold down the trigger until it dies", "ship", 0, "unsupported", "", ""),
    ("Dock us automatically", "ship", 0, "unsupported", "", ""),
    ("Please jettison all our cargo", "ship", 0, "execute", "eject_all_cargo", "toggle"),
    ("Dump some weight so we can escape", "ship", 0, "clarify", "", ""),
    ("Reload my rifle", "ship", 0, "execute", "reload_weapon", "toggle"),
    ("Give me fifty percent astern", "ship", 0, "execute", "half_reverse_throttle", "toggle"),
    ("Make the fighter cover us", "ship", 0, "execute", "order_fighter_defend", "toggle"),
    ("I need the previous weapons group", "ship", 0, "execute", "previous_fire_group", "toggle"),
    ("Could you select the next hostile?", "ship", 0, "execute", "next_hostile_target", "toggle"),
    ("I'm out of suit power, use a battery", "on_foot", 0, "execute", "use_energy_cell", "toggle"),
    ("Please bring up the right hand panel", "ship", 0, "execute", "internal_panel", "on"),
    ("Turn off the torch for me", "on_foot", 0, "execute", "flashlight", "off"),
    ("If I say lights off, what would you do?", "ship", 0, "conversation", "", ""),

)


async def evaluate(call_model, output, model_label):
    router = IntentRouter(call_model)
    rows = []
    for text, mode, ui, kind, action, state in CASES:
        router.clear()
        started = time.monotonic()
        result = await router.route(text, {"mode": mode, "ui": ui})
        passed = result.kind == kind and (kind != "execute" or (result.action, result.state) == (action, state))
        rows.append({"text": text, "context": {"mode": mode, "ui": ui},
                     "expected": {"kind": kind, "action": action, "state": state},
                     "actual": result.__dict__, "passed": passed,
                     "seconds": round(time.monotonic() - started, 3)})
        # Persist progress without exposing provider credentials or raw responses.
        report = {"model": model_label, "input_sent": False, "speech_to_text_tested": False,
                  "passed": sum(r["passed"] for r in rows), "total": len(rows), "cases": rows}
        Path(output).write_text(json.dumps(report, indent=2), encoding="utf-8")
        if len(rows) % 8 == 0:
            Printr().print(f"Routing evaluation: {len(rows)}/{len(CASES)} classified; no game input.", server_only=True)
    context = {"mode": "ship", "ui": 0}
    router.clear()
    await router.route("Get us out of here", context)
    answer = await router.route("The hyperspace option", context)
    report["clarification_followup"] = {"actual": answer.__dict__,
        "passed": answer.kind == "execute" and answer.action == "request_hyperspace_jump"}
    Path(output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
