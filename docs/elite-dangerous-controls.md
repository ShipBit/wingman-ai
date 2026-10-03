# Elite Dangerous controls

**Partial interactive companion; source deployment verified:** the
[evidence record](elite-dangerous-acceptance.md) separates configured bindings,
automated coverage and observed gameplay. Lights and night vision have live input
evidence. The player requested automated coverage for the remaining catalog,
without a command-by-command spoken acceptance exercise.

The `EliteDangerousControls` skill supports 108 distinct action IDs across 151 ship, SRV and on-foot
combinations using the game's active bindings. It is separate from the read-only
telemetry skill and activates on demand. No controller driver or virtual joystick
is required. The player can keep keyboard/mouse, HOTAS, gamepad and mixed controls.

## What changed

Whole-command phrases still use the deterministic path. With the skill's
`semantic_routing` property enabled (the Elite profile default), unmatched speech
gets one tool-free call to the configured conversation model. It sees the original
transcript, current vehicle/UI context, reviewed action IDs and one pending
clarification. It returns execute, clarify, conversation or unsupported. It never
chooses keys or writes code. An in-process authorization binds execution to that
turn, action, state wording and vehicle; both the skill and engine check it.

“Kill the bloody headlights” can request lights off; “Are my lights on?” is a
conversation. “Get us out of here” asks whether the player means boost,
supercruise or hyperspace. Multiple unrelated controls ask which to handle first.
Clarifications expire after 30 seconds and clear after cancellation, intervening
requests or observed context changes. Cargo ejection requires an explicit order
to eject all cargo; escape language cannot authorize it.

Model routing has a five-second deadline, including synchronous provider adapters.
Timeouts, invalid output and unavailable models send no input and request a retry.
A late model result cannot acquire execution authority. Exact controls continue
to work with semantic routing disabled or while the provider is unavailable.
Semantic routing uses one extra call for unmatched speech; a successful input
still gets the existing separate acknowledgment call. The two progressively
activated tools remain compact; catalog metadata is sent only to the router.

The shared catalog covers reverse throttle presets, boost, flight assist, targets
and subsystems, wing targeting, fire groups, shield cells, HUD and panels, fighter
orders, SRV recall, on-foot equipment/interactions, and discrete FSS/SAA/menu
navigation. Menu commands read the GENERAL preset, including when vehicle
presets differ. Chat is always excluded. Menu and scanner controls require their
observable UI focus; ordinary flight controls require the cockpit. UI values
follow [Frontier's Journal manual](https://hosting.zaonce.net/community/journal/v31/Journal_Manual_v31.pdf).
Continuous movement, axes, held fire/charge, unobservable camera/editor commands,
and unattended docking/launch remain excluded. Hold-configured bindings remain
unavailable until the player changes the setting. No unknown XML tag becomes a tool.

`readiness.json` inventories every element of the installed selected presets as
supported, missing an injectable binding, or excluded with a reason. Counts
separate distinct IDs, vehicle/action combinations and distinct injectable
bindings; aliases do not count as new actions. The latest implementation,
model-only evaluation and deployment results are in the
[natural-language control report](elite-dangerous-natural-language-report.md).

The former exporter installed ordinary hotkey commands. A completed input call
was treated as execution, and an LLM could say the action succeeded without an
observation. The named-key backend also discarded extended-key information and
used virtual keys for numpad input. The new Windows adapter sends physical scan
codes with explicit extended flags and checks every injection result. It follows
[Microsoft's KEYBDINPUT contract](https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-keybdinput).

The skill requires Elite to be the foreground process. It checks process
permissions, the current journal session, vehicle mode, dashboard UI focus and
bindings before sending input. Windows prohibits injection into a process with
higher integrity; setup does not elevate either application automatically.
[SendInput reference](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput).

Individual control requests press the active binding once. As explicitly requested
by the player, `turn lights on`, `turn lights off` and `toggle lights` all press the
lights toggle key. Repeating `turn lights on` can therefore turn lights off.
Recognized phrases route directly after transcription, including cold activation,
without an LLM deciding whether to execute. The controller uses telemetry for
vehicle/session/menu prerequisites; it does not suppress presses based on the
reported switch state. Map commands additionally wait up to three seconds for
the expected `GuiFocus` transition (galaxy map 6, system map 7, cockpit 0 on
closing). Missing or unchanged telemetry produces an unverified result without
a second press. Contextual telemetry remains available separately.

After accepted non-map input, the configured AI composes a short acknowledgment
using the companion's persona and its six recent acknowledgments. The call has
no tools, cannot execute/replay input, and receives no claimed resulting game
state. Replies are bounded to 18 words and checked for unsupported state claims.
A timeout, repeated wording or invalid response uses a varied fallback; input is
never retried. Failure details remain factual. This adds one bounded model call
per successful individual command, not an AI polling loop.

| Result | Meaning |
| --- | --- |
| Confirmed: galaxy/system map open/closed | The expected map transition was observed after one press. |
| Varied acknowledgment, such as “Copy that, Commander.” | Windows accepted the keypress; no resulting game state is claimed. |
| Invalid request | The action wording or requested state is unsupported or conflicting; no input sent. |
| Blocked | No input was sent because a prerequisite failed. |
| Failed | Windows rejected the attempted input; no successful injection was recorded. |
| Unverified | Input was attempted/sent, but the requested outcome was not established. |

An uncertain action is never automatically repeated. A duplicate delivery of the
same tool-call ID sends no second press; a separate deliberate request does.
Consumables and cycling controls follow the same one-press rule. The internal
state-aware primitive is retained for replay/explicit supervised prerequisites,
but ordinary spoken controls use single-press semantics.

Common cockpit phrases include `deploy landing gear`, `retract hardpoints`,
`open cargo scoop`, `activate night vision`, `engage supercruise`, `launch chaff`
and `pips to engines`. They use the same one-press path. The
[workflow guide](elite-dangerous-workflows.md) describes explicit supervised
checklists, which use observed prerequisites and player checkpoints.

## Setup and upgrade

Run these commands from the source checkout with the Core Python environment.
Use the managed source Core for this installation. A custom skill copy also
requires the sibling telemetry folder and updated Core turn-provenance service.
No Core API types change.

Locate Elite's `ControlSchemes` folder under its installed product directory.
The runtime detects that directory from the focused game automatically. The
offline setup commands take `--presets` explicitly so they also work with the
game closed, custom Steam libraries and standalone installations.

```powershell
$elitePresets = 'C:\Games\Steam\steamapps\common\Elite Dangerous\Products\elite-dangerous-odyssey-64\ControlSchemes'
.\.venv-core\Scripts\python.exe -m integrations.elite_dangerous.control_setup inspect `
  --presets $elitePresets --output .elite-local\controls-readiness.json
.\.venv-core\Scripts\python.exe -m integrations.elite_dangerous.control_setup prepare `
  --presets $elitePresets --output .elite-local\controls-review
```

Setup detects the enabled profile in either `Elite Dangerous` or `_Elite Dangerous`,
including renamed profiles. Use `--profile <path>` when there are multiple
candidates, and `--config-dir`/`--bindings` for non-default installations.

Read `REVIEW.md` in the output directory. Preparation changes no live configuration.
It creates named copies of selected presets and fills free slots for missing or
conflicting actions. Original bindings, axes and controller identifiers remain
intact. Shortcut allocation checks active preset actions, UI bindings, push-to-talk
and reserved OS combinations, not just companion-supported actions. Free unmodified
keys are preferred. Modifier presses are checked too: Shift+F10 conflicts with
`UIFocus` bound to Shift alone, even though their final keys differ. Reviewed
controls in disjoint vehicle/UI contexts may reuse a key; unknown controls remain
conservative. Runtime and setup use the same conflict rules.

When both slots are occupied, the report requests a choice. Leave that action
unavailable, or create a JSON file such as:

```json
{"ship.NightVisionToggle": "Secondary"}
```

Pass `--choices choices.json` when preparing a **new output directory**. Only the
chosen slot in the copied preset is replaced. Hold-mode actions require changing
the game setting to toggle first. If no safe shortcut is free, setup reports it
instead of overwriting another action.

After exiting Elite, apply the reviewed plan:

```powershell
.\.venv-core\Scripts\python.exe -m integrations.elite_dangerous.control_setup apply `
  --plan .elite-local\controls-review\plan.json
```

This backs up and migrates receipt-owned legacy hotkey commands to the new skill.
Edited or unrecognized overlapping commands stop migration for review. Unrelated
commands, providers, voice settings and profile customizations are preserved.
Reload the profile (restart Core yourself if adding the new bundled skill requires
rediscovery). Start Elite and select the names listed in REVIEW.md in the ship,
SRV and on-foot Controls sections: **Wingman - Ship**, **Wingman - SRV**, and
**Wingman - On Foot**. A numerical suffix is used if that name already belongs to
another or edited preset. Ordinary setup leaves StartPreset.4.start unchanged. The `--select-presets` option includes its new selection and backup in the plan; no manual reselection is needed.

**Managed launcher:** closing/reopening the Wingman window leaves its background
Core running. Follow the [actual Core restart steps](audio-recovery.md#restarting-core-after-a-source-update)
after a source update. Reinstalling the client does not refresh that running
process. Start a fresh conversation after the updated profile loads.

Keep Elite focused and close chat, panels, maps and camera modes before ordinary
vehicle commands. Ask “turn on ship lights,” “turn off night vision,” or “controls
status.” Map actions may close their corresponding open map.

## Preset changes and recovery

To replace the old hash-based names, stage a naming upgrade using the original
applied installation receipt:

```powershell
.\.venv-core\Scripts\python.exe -m integrations.elite_dangerous.control_setup rename-presets `
  --plan .elite-local\controls-review\plan.json --output .elite-local\friendly-presets
.\.venv-core\Scripts\python.exe -m integrations.elite_dangerous.control_setup apply `
  --plan .elite-local\friendly-presets\plan.json
```

Apply with Elite closed. This upgrade copies the **currently selected** owned
presets, including edits saved by the game, and updates only matching selector
entries. It keeps the original files and backs up the selector. Its version-2
receipt supports `restore` with Elite closed without manual reselection. Restore
stops if the player subsequently edited the new files or original source presets.
Hold-mode settings are preserved and only the affected action remains unavailable.

The control tool accepts a catalog ID, such as `lights` and
`night_vision`, with separate `state` and `mode` arguments. Compatibility parsing
also accepts bounded phrases such as `turn on ship lights`; an explicit state in
that wording fills an omitted legacy state, but an explicitly conflicting state is
rejected. Negated, unknown, and compound instructions never trigger guessed input.

Core startup now reuses existing default-prefixed configuration directories and
deleted-profile markers. Existing template duplicates are repaired before copies
are installed. Backups live beside `configs`, under `config-backups/repair-*`.
Exact template clones are archived there; differing profiles receive a unique
`Recovered` configuration name. Only one default remains, and repeated startup
does not recreate the duplicates. The current customized default is retained when
repairing this installation. This fixes ambiguous configuration identities; the
client's Load menu still needs a visible selection check after restarting Core.

Bindings are reread before every action and watched while the control skill is
active. Changes are accepted only after a stable read; partial XML, selector
changes and missing device presets block execution instead of reusing stale
keys. The player may change presets freely. Existing keyboard/mouse alternates
work immediately; a new controller-only preset needs a supplement where it has
no injectable alternate. Use `--select-presets` to stage selection of the copies as part of the reversible upgrade.

Run `repair` with the same arguments as `prepare`, using a new output directory,
after switching to a preset that needs additional shortcuts. It is idempotent for
already-installed profile capabilities and reads the latest selected bindings.
Inspect its report, exit Elite, apply, and select any new copies.

To repair unsafe generated shortcuts from a previous installation, add
`--repair-from <applied-plan.json>` (repeat for multiple receipts) and
`--select-presets`. Only slots matching the original staged preset and recorded
shortcut are owned by that installation. The repair removes conflicting owned
slots, fills available slots with safe shortcuts and preserves player edits,
controller mappings and the profile's exact bytes. A working primary binding
needs no replacement secondary. Unowned/edited occupied slots require an explicit
`--choices` selection before replacement. Source hashes, staged hashes, backups,
game-closed checks and rollback apply to the repair as to any other installation.

To undo an installation, select the original presets in Elite, exit the game, and
run `restore --plan <the original plan.json>`. Restore verifies all ownership
hashes before changing files. If the game/client/player edited an installed file,
automatic restoration stops; the backup remains available for manual merging.
Neither repair nor restore discards later edits silently.

## Verification and limits

The automated tests mock injection. They cover physical-key packet flags,
keyboard layouts, held modifiers, release on cancellation, live preset changes,
mode/focus/session failures, new telemetry, duplicate on/off requests, setup
conflicts and transactional restoration. Run:

```powershell
.\.venv-core\Scripts\python.exe -m unittest discover -s tests -p 'test_elite*.py'
.\.venv-core\Scripts\python.exe -m unittest discover -s tests -p test_command_exposure.py
```

All 151 vehicle/action catalog entries run through actual Core dispatch, skill validation and
the controller with synthetic input/game doubles. Coverage includes each action
twice, repeated toggle wording, wrong vehicles, chat, missing bindings and negation.
Separate regressions cover focus/session changes, packet insertion, cancellation,
duplicates and held keys. All 12 workflow definitions complete three synthetic
runs and have interruption regressions. These are automated results, not live
gameplay confirmations. The longer live protocol remains opt-in for diagnosing
specific failures; the user is not required to recite the catalog. Re-run readiness
after Elite changes presets and revalidate affected logic when bindings or code change.

Not every cockpit submode or paused/menu condition is exposed by telemetry.
Camera modes and third-party overlays require the player's attention; do not use
vehicle commands there. Some state flags are unavailable or ambiguous on foot.
There is no launch/docking macro, sustained fire, steering/axis automation or
background input. Non-Windows Core and telemetry continue to work, but this
control skill is Windows-only. An observed state establishes the result, not
exclusive causation if the player also operates the controls simultaneously.

Readiness reports and Core logs distinguish configuration, attempted input and
observed outcomes. Automated tests and a successful SendInput return do not prove
in-game delivery. Do not publish an unconditional 100% reliability claim.
