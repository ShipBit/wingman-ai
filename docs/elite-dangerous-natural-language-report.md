# Natural-language Elite controls — implementation and verification

## Modifier-binding repair — 2026-09-28

The player's failed map requests were found in Core's 17:54 log. Both system-map
paraphrases resolved to `system_map`; the exact galaxy-map phrase selected
`GalaxyMapOpen`. Each sent one configured chord and recorded Windows acceptance,
but no gameplay verification. Manual reproduction failed too. Left Shift was
also bound to `UIFocus`, explaining the observed camera motion. The player then
bound galaxy map to numpad `/` and confirmed it worked; a natural-language lights
request also worked. The routing was retained.

Runtime and setup now check the modifier presses themselves, in addition to the
final key, against controls active in the same vehicle/UI context. Setup prefers
free unmodified keys. Receipt-based repair can recognize unchanged generated slots
inherited through later installed presets; edited or unowned slots remain protected.
Map execution still sends exactly one press, then observes the expected `GuiFocus`
transition for up to three seconds. Only an observed transition returns confirmed.
Missing telemetry or no transition returns unverified, without an automatic retry
or a generic acknowledgment. Other individual controls retain their existing behavior.

The repair was installed with Elite closed. It changed 28 generated binding slots
in new preset copies and selected **Wingman - General 2**, **Wingman - Ship 3**,
**Wingman - SRV 3**, and **Wingman - On Foot 3**. The profile is byte-for-byte
unchanged. Structural comparison verified every unlisted XML element was preserved,
including controller bindings and settings. Ship galaxy map retains the player's
primary **numpad /**; system map now uses **numpad 7**. Installed readiness remains
149/151 vehicle/action pairs. The same two hold-mode controls listed below remain
unavailable.

Verification: the full Elite run passed 348 tests with one skipped (349 total).
After the final receipt-inheritance change, all 22 setup tests passed, including
the added inheritance regression. Five shared Core dispatch tests also passed.
The map regressions cover opening/closing, semantic authorization, stale or missing
telemetry, deadlines, unexpected context, cancellation and duplicate delivery.
These are automated tests and installed-binding checks, not new live gameplay
acceptance. Core must be started/restarted by the user to load the code changes.

Local records: `.elite-local/modifier-binding-repair-final/` contains the plan,
review, backups, apply receipt, staged validation and installed readiness.
`.elite-local/modifier-repair-tests.log` contains the full suite results.
To restore this repair with Elite closed:

```powershell
.\.venv-core\Scripts\python.exe -m integrations.elite_dangerous.control_setup restore `
  --plan .elite-local\modifier-binding-repair-final\plan.json
```

## Earlier natural-language expansion

Implemented and installed on 2026-09-28 with Elite closed. Six configuration files
were updated through the hash-checked plan and backed up. The installed presets
were reread successfully: 125 injectable bindings and 149 vehicle/action pairs.
Core must be restarted by the user to load the new code.
No public Core API or client type changes were made.

## Delivery

- Exact phrases retain their deterministic path. An optional async skill hook
  routes unmatched speech before legacy instant commands, including cold activation.
- One tool-free call uses the configured provider/model with a five-second deadline.
  The Elite profile defaults `semantic_routing` to true; existing explicit false
  values survive migration and repair. Provider, persona and voice settings remain.
- Internal turn-bound authorization is checked at skill and engine boundaries.
  Conversations and clarification cannot authorize later Elite tool calls in the
  same turn. Duplicate delivery, cancellation, stale turns, changed bindings,
  vehicle/session changes and foreground-game checks prevent additional input.
- One clarification survives for 30 seconds. Changed context, cancellation and
  intervening unrelated requests clear it. Multiple controls request a choice.
- On/off wording still sends one press. Acknowledgments retain the existing varied
  companion speech and make no claim about an unobserved resulting game state.
- Named workflows remain available. Continuous movement, axes, held fire/charge,
  unobservable camera/editor contexts and unattended launch/docking are excluded.
  Ejecting all cargo requires an explicit order.

## Coverage and readiness

The catalog contains **108 distinct action IDs**, **151 vehicle/action pairs**, and
**127 distinct reviewed bindings**. All 43 original vehicle/action mappings remain.
Aliases are not included in expansion counts. See the complete
[command coverage table](elite-dangerous-command-coverage.md).

The installed presets resolve **125 injectable bindings**, covering
**149/151 vehicle/action pairs**. Two current player settings require held input
and remain unavailable: SRV drive assist (`ToggleDriveAssist`) and the surface
scanner view switch (`ExplorationSAAChangeScannedAreaViewToggle`). Setup preserves
those settings rather than converting them to toggles.

Private local artifacts are under `.elite-local/natural-language-upgrade-final/`:

- `plan.json`, staged profile and preset copies: hash-checked reversible upgrade.
- `REVIEW.md`: supplemental shortcuts and unavailable entries.
- `readiness.json`: original selected-preset inventory, including excluded tags.
- `after-readiness.json`: validation against temporary copies of staged presets.
- `applied.json`, `backup/`, `installed-readiness.json`: application receipt,
  original files and the post-installation inventory.

The upgrade includes the GENERAL selector for UI commands and preserves existing
keyboard/controller mappings, axes and player-edited presets by creating new
named copies. Applying is refused while Elite is running or source hashes differ.
Restore refuses later user edits instead of overwriting them. To restore with
Elite closed:

```powershell
.\.venv-core\Scripts\python.exe -m integrations.elite_dangerous.control_setup restore `
  --plan .elite-local\natural-language-upgrade-final\plan.json
```

## Automated verification

The full Elite suite ran **334 tests: 333 passed, one skipped**. An additional
focused run passed **73 checks**, overlapping some of that suite and including
shared Core dispatch and command exposure. Logs are in
`.elite-local/natural-language-all-tests.log` and
`.elite-local/natural-language-focused-final.log`.

Every catalog entry exercises Core/skill/engine dispatch with synthetic input and
valid vehicle/UI context. Coverage includes repeated on/off presses, chat, wrong
vehicle, missing/changed bindings, negation, cancellation and duplicate delivery.
Routing checks cover malformed output, blocking providers/timeouts, cold requests,
expired/context-changed clarifications, intervening turns, destructive intent,
multi-action requests, conversation denial and exact-path precedence. Setup checks
cover free-slot allocation, controller preservation, edited presets, rollback and
all four preset selectors. Existing workflow regressions pass.

## Configured-model evaluation

Text-only evaluation used **Wingman Pro / gpt-4.1-mini**, the installed conversation
configuration. The release run matched the expected intent/action/state on
**35/37 representative utterances (94.6%)**. A separate ambiguous-escape follow-up
correctly resolved “The hyperspace option.” The test includes paraphrases, slang,
profanity, questions, quoted/negated/conditional speech, multiple actions, unsupported
requests and vehicle/UI context. Eight utterances were added after initial prompt
development. This is a small development benchmark, not a population accuracy estimate.

Both release misses returned unsupported without input: “It's pitch black, give me
night vision” in a ship, and “Reload my rifle” while ship context was active. The
first wrongly denied a supported ship control; the second recognized unavailable
vehicle context but should have retained the intended reload action for the engine
to reject. Exact night-vision phrases and on-foot reload controls remain available.
The release sample contained no wrong-action execution decision. Earlier development
runs did include a wrong panel decision; directional aliases and explicit UI labels
corrected that case in the release run. Models can still misunderstand other speech.

The complete release results are in
`.elite-local/natural-language-model-evaluation-release.json`; earlier runs are
retained separately. Initial strict-format errors caused safe refusals and led to
the smaller per-decision schemas. Mocked tests are not counted as model accuracy.

**No live game input, speech-to-text exercise or gameplay acceptance was performed
for this expansion.** Binding readiness, synthetic execution and text classification
are separate evidence. Existing historical lights/night-vision gameplay evidence
does not establish delivery of the newly added controls. Live troubleshooting is
needed only if a specific problem appears after the user restarts Core.
