# Elite companion evidence — partial interactive companion

## Current delivery and user-directed validation

The player confirmed production input for lights and night vision. After the
revision-3 user-operated restart, Core identity matched and a directly routed
voice request (transcribed as “Enable lights.”) produced exactly one Insert press
and release. The player confirmed lights on; an independent status read agreed.
The original requested speech was “Lights key sent.” The player requested natural,
varied AI acknowledgments instead, and explicitly rejected a manual spoken test
of every control. Those later instructions supersede the original exhaustive
manual acceptance gate and deterministic successful-response wording.

The delivered continuation runs all 43 catalog entries through actual Core
dispatch, skill validation and controller logic using synthetic OS/game doubles.
Each catalog action is dispatched twice; repeated toggle wording and blocked
contexts are covered separately. Twelve predefined workflows cover both travel/
exploration and combat/operations, including SRV and on-foot. Each completes three
synthetic runs, with interruption and uncertain-result regressions. This is
automated coverage, not a claim of 43 observed live outcomes or live workflow runs.

The player restarted Core and confirmed loading after the speech/workflow update.
The new managed process passed the runtime identity, source-fingerprint and
profile checks with no deployment issues. No per-control spoken acceptance exercise is
required of this user. The longer protocol below remains an opt-in diagnostic
for investigating a specific failure. The verdict is **partial interactive
companion**; full supervised gameplay acceptance is
not claimed.

## Current contract: one press per command

The player requested single-press behavior in place of state-setting for individual
controls. `Turn lights on`, `turn lights off` and `toggle lights` each press the
lights binding once, including repeated requests. Repeated on/off wording can
therefore invert the game state. Successful input gets a short, varied acknowledgment
from the configured AI after execution, without claiming the resulting state. Questions and contextual
assistance remain separate from key commands.

Recognized control phrases now route directly after transcription, including cold
activation, before legacy command matching or a model call. Normal key commands
retain vehicle/session/menu/binding prerequisites, held-key checks and cancellation,
but do not suppress a press based on a switch flag or wait for resulting state.
Duplicate delivery of one call ID is still suppressed; deliberate new requests
press again. The internal state-aware primitive remains for explicit supervised
prerequisites and historical replay tests, not ordinary spoken commands.

This is control schema revision **3**. Workflow modules and speech modules are
included in deployment fingerprints and installation manifests. No public Core
API fields or endpoints were added. See the [workflow guide](elite-dangerous-workflows.md).

## Earlier state-setting investigation (revision 2)

The repaired source had automated regression coverage and initial live ship-light
evidence, but full gameplay acceptance is pending. Core was stopped at the first
read-only deployment check. The first user-operated startup exposed a missing `psutil` dependency
in the new identity recorder. That dependency was removed, and the native Windows
process-time lookup and identity writer now have direct regression coverage.
The corrected fresh-process startup passed runtime identity comparison, and the
user confirmed the companion in the Load dropdown. Physical ship lights changed
on/off with matching telemetry. A docked night-vision trial had an audible cue but
no observed status change; the original visual report was subsequently clarified
by the player. That failed trial is retained. After undocking, the player visually
confirmed night vision on and telemetry agreed. This diagnoses a test-context
problem; it is not evidence of injected input working. The baseline now requires
an undocked cockpit and an exterior view.

Direct production input then changed ship lights on and off. Windows accepted one
press and release for each change; the player reported lights on and visually
confirmed the off change. A repeated on request correctly sent no input. Immediate
verification failed because Elite's status timestamp was 0.248 seconds ahead of
the system clock. The original `Unverified` results remain intact. The observer
now waits up to a fixed 1.1-second budget for timestamps at most one second ahead
to become current, then re-reads the session and status. It never accepts a future
timestamp or sends another keypress. Regressions cover this live timing case,
larger clock errors, shutdown during the wait and cancellation. The corrected
source was loaded by a user-operated restart and passed both lights changes with
matching telemetry and player confirmation. The next night-vision-on press was
also visibly effective, but its immediate status read caught an incomplete file
write and remained `Unverified`. The observer now retries only incomplete or
temporarily unreadable status files, at most five times at 25 ms intervals within
the same overall time budget. Persistent malformed data, session loss and clock
errors still fail; no input is replayed. After another user-operated restart,
runtime identity matched the corrected source and direct night-vision on/off both
returned `Confirmed` with changed telemetry. The player confirmed both visible
changes. The first voice trial also changed lights on: the recorded transcript,
canonical tool intent, changed telemetry, player observation and audible
`Confirmed: lights on.` agreed. The harness originally compared transcripts
verbatim; it now checks canonical intent using the production validator so
`turn lights on` and `turn on lights` are equivalent. That initial assessment and
its correction are retained; opposite states, negation and unwanted toggles fail.

The subsequent repeated-on trial produced conversational “already on” replies with
no controller event in the armed trace. The player then requested one keypress per
command. Revision 3 addresses both that routing failure and the changed semantics;
the earlier successful trials do not establish revision-3 live acceptance.

Repeatability, voice and persistence still need acceptance.
This is **acceptance pending**, not a software-control
feasibility failure verdict. The player's later validation direction is recorded above.

## Delivered control path

- `elite_control` keeps canonical IDs and requires the model to supply `state`.
  An omitted legacy state can be inferred from wording; an explicit conflicting
  `toggle` is rejected. Negated, conditional, compound and ambiguous instructions
  require clarification without input.
- Core captures a user-turn ID before skill activation and carries the tool-call
  ID through task-local context. The skill checks the originating text, including
  cold activation. A newer turn stops pending input. Duplicate call IDs do not
  repeat input; separate user turns remain separate requests.
- Internal results contain intent, request ID, outcome, reason, failing stage,
  timing, Windows insertion events, observations and runtime identity. Spoken
  input receipts remain deterministic. Individual commands return `input_sent`;
  one bounded, tool-free AI call then creates a fresh short acknowledgment using
  persona and recent replies. A separate correlated speech event records it.
  Unsupported claims, repeats or provider failure use a varied fallback, never
  another input attempt. Partial insertion and cancellation after input retain
  factual `Unverified` reporting. Already-set suppression is limited to explicit
  workflow prerequisites, not individual commands.
- Physical **Escape** cancels active companion control locally. Cleanup releases
  only companion-owned keys. No uncertain action is automatically retried.
- Core writes `elite-runtime.json` beside its versioned `configs` directory after
  profile initialization. It records PID/process start, instance ID, source paths
  and import-time fingerprints, schema revision, profile, config root, loaded
  skills, duplicate defaults and legacy command conflicts. This adds no endpoint
  and changes no client API types.

The Windows insertion count proves insertion into an input stream, not that Elite
performed an action. Integrity restrictions also apply; see
[Microsoft SendInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput).

## Launch and prerequisites

Use **Elite Companion - Managed Core** on the desktop. Install or inspect it with:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools/install-companion-shortcut.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools/install-companion-shortcut.ps1 -CheckOnly
.\.venv-core\Scripts\python.exe tools/managed_launch.py --check
```

This distinct shortcut uses this checkout's `.venv-core` and the installed GUI.
Existing Wingman shortcuts may still start the packaged Core. The installer does
not repoint them or start Core. The check reads actual shortcut properties and
reports drift. The launcher detects another process on port 49111 and never kills
it. Its runtime report separates process matching, `/ping` readiness and deployment
issues. A ready process alone does not pass acceptance.

Dependencies are the existing Core environment (`requirements.txt`), installed
Wingman GUI, bundled `keyboard.keyboard`, PyYAML, the two Elite skills,
and the game's active binding files and Live journal. External reference tools
remain MCP tools. Source mode loads the checkout's skills first; standalone custom
copies of the new control skill also require the updated Core provenance service.

Before testing, inspect all configured bindings using `control_setup inspect` as
described in [controls setup](elite-dangerous-controls.md). Preserve physical
controller assignments. The implementation snapshot found the ship lights on
**Insert** and night vision on **numpad minus**, but every trial re-resolves the
active files. It also found two default-marked profile directories. Core's existing
protected configuration repair must resolve that at startup, preserving customized
copies. Check the visible **Load** dropdown and selected companion after both starts.

## Optional private live diagnostic sequence

This extended sequence is retained for reproducibility, not as a requirement that
the player perform hundreds of spoken tests. Current validation follows the
automated coverage and limited live evidence described above. Initialize a new
ledger after source changes if choosing to run an additional live diagnostic.

First initialize a new ledger, before starting Core. Substitute local paths:

```powershell
.\.venv-core\Scripts\python.exe -m integrations.elite_dangerous.acceptance init `
  --profile "$env:APPDATA\ShipBit\WingmanAI\2_1_1\configs\_Elite Dangerous\EliteDangerous-Copilot.yaml" `
  --presets 'C:\Games\Steam\steamapps\common\Elite Dangerous\Products\elite-dangerous-odyssey-64\ControlSchemes' `
  --journal "$env:USERPROFILE\Saved Games\Frontier Developments\Elite Dangerous"
```

Game version is read from the journal, or supplied with `--game-version` when it
cannot be established. Evidence lives only under ignored `.elite-local/acceptance`.
Do not commit journals, screenshots, transcripts, profiles or these receipts.

Start Core yourself with the companion shortcut, log in if needed, select the
companion and check the Load dropdown. Closing the GUI alone does not stop an
existing managed Core; use the [user restart procedure](audio-recovery.md#restarting-core-after-a-source-update).
Then record the observation:

```powershell
.\.venv-core\Scripts\python.exe -m integrations.elite_dangerous.acceptance restart `
  --dropdown-visible --notes 'Selected companion is visible in Load; customized profiles remain available.'
.\.venv-core\Scripts\python.exe -m integrations.elite_dangerous.acceptance next
```

`restart` reads the identity produced inside Core and compares the live process,
loaded code, profile and bindings against the ledger. It does not restart anything.
Do not attest to a dropdown that was not observed. Missing/stale identity, source
changes, profile changes or binding changes stop the sequence. Initialize a new
sequence after correcting them; old evidence remains intact.

Remain safely stationary and undocked, looking at the exterior with chat and menus
closed. The player handles undocking, flying and stopping. Follow the next case
shown by `next`, one at a time:

```powershell
# Physical key trial: five seconds to focus Elite, then an eight-second window.
.\.venv-core\Scripts\python.exe -m integrations.elite_dangerous.acceptance physical
# Player-paced alternative: capture before, press the key, then capture after.
.\.venv-core\Scripts\python.exe -m integrations.elite_dangerous.acceptance physical-before
.\.venv-core\Scripts\python.exe -m integrations.elite_dangerous.acceptance physical-after
# Production controller, bypassing the model: one explicitly armed action.
.\.venv-core\Scripts\python.exe -m integrations.elite_dangerous.acceptance direct --send-input
# Voice: arm the case, focus Elite, and say the displayed spoken_request.
.\.venv-core\Scripts\python.exe -m integrations.elite_dangerous.acceptance arm-voice
```

For the repetition phase, `direct-block --send-input --delay 5` runs the remaining
cases for one action, stopping on the first uncertain result or unexpected input.
Escape cancels during execution or between trials. Revision 3 uses individual
`arm-voice` / `checkpoint` trials, allowing independent after-state captures.
`arm-voice-block` is retained for legacy state-setting sequences only. Every trial
still needs visual observation, and voice trials also need audible confirmation.
Use `checkpoint-block --all-matched --notes '...'` only when the player explicitly
confirms every visible state in a direct block.
Otherwise record the individual failed or uncertain checkpoint; never infer a
player observation from telemetry. Raw events remain immutable; voice association
uses request IDs and execution timestamps and exposes extra calls as failures.

Do not issue voice commands during physical or direct trials. After each attempt,
record what was actually visible, and for voice copy what was actually heard:

```powershell
.\.venv-core\Scripts\python.exe -m integrations.elite_dangerous.acceptance checkpoint `
  --visible on --heard 'Copy that, Commander.' --notes 'Observed the ship lights change.'
.\.venv-core\Scripts\python.exe -m integrations.elite_dangerous.acceptance report
```

Use `--visible unknown` if obscured or uncertain. A missing tool call fails routing;
a mismatched transcript, incorrect action, missing observation or false spoken
success fails its stage. Recording the same case again fails the sequence instead
of erasing its first trial. The speech event means speech was requested; the player
checkpoint is still required to establish that it was heard correctly.

The revision-3 protocol has 138 action cases: physical off/on/off for each basic
action, then **on/on/off/off five times**, and toggles from both states for
each action through direct, voice and voice-after-restart paths. Before the last
voice block, perform another user-operated Core restart and record the Load
dropdown again. Two records of the same process do not count as two starts.

Begin each action/path with an observed off baseline. Every command presses once,
so visible states alternate on/off regardless of the spoken on/off words. Each
22-command block ends off. The harness observes after-state separately; ordinary
commands do not perform this wait. A key-sent receipt alone cannot pass acceptance.
Historical revision-2 ledgers retain their original 144-case state-setting rules.

Failure trials are separate supervised checks: focus loss, chat/menu, stale
session, changed binding, Escape cancellation, unavailable control, negated request
and contradictory request. Preserve their actual trace and player observation in
private JSON with `first_failing_stage`, `input_events`, `observation` and `speech`.
Record each using `failure-check --check <name> --result pass|fail --evidence <file>`.
These are player-attested live checks, not automatically manufactured passes.
Check that no inappropriate new keydown occurs; cancellation must release owned
keys. A failure prevents basic acceptance. Do not change bindings during the
ordinary repeatability block; use a separate failure trial and restart acceptance
after any corrective binding change.

## Capability gates and remaining work

| Capability | Configuration evidence | Windows insertion evidence | Gameplay acceptance |
| --- | --- | --- | --- |
| Ship lights | Current binding inspected; catalog regressions | Revision-2 direct and revision-3 voice press/release accepted | Player and telemetry agreed; extended repetition not completed |
| Night vision | Current binding and undocked physical changes inspected | On/off press/release accepted in revision 2 | Direct changes matched player observations; revision-3 repetition and voice pending |
| Other existing ship controls | 25/25 configured; full catalog synthetic routing/controller coverage | Per-action live insertion not measured | Available as input commands; not individually gameplay-certified |
| Existing SRV controls | 10/11 configured; drive assist hold-mode excluded; synthetic coverage for all 11 | Per-mode live insertion not measured | Configured actions available; no live per-action certification |
| Existing on-foot controls | 7/7 configured; synthetic coverage | Per-mode live insertion not measured | Available; no live per-action certification |
| Travel/exploration workflows | Four predefined checklists, three synthetic runs each | Production controller exercised with doubles | Implemented; live runs not performed |
| Combat/operations workflows | Eight predefined checklists, three synthetic runs each | Production controller exercised with doubles | Implemented; live runs not performed |
| Screen-assisted checkpoints | Explicit player checkpoints; no image-driven automatic continuation | Not applicable | Automatic image interpretation not implemented |

The current 43-action catalog is not a claim that 43 actions work in the game.
Controls lacking reliable observation remain input-only and require a player
checkpoint. English intent validation intentionally uses a bounded grammar;
unrecognized phrasing asks for clarification rather than guessing.

If direct input fails, preserve the first failing stage, compare physical and
injected input under identical conditions, and vary one factor at a time. Only
then test an isolated sender and any evidence-supported documented software
alternative. A second wrapper around SendInput is not a distinct mechanism.
Those investigations have not yet been performed and no feasibility verdict has
been needed to explain the successful live input. No universal feasibility claim
has been made.

The implemented state machines use observed prerequisites where supported and
explicit player checkpoints elsewhere. Three synthetic runs plus interruption
tests establish software coverage. The original request for three live runs each
has not been performed and is not relabeled as a pass. Uncertain execution stops;
uncertain toggles and consumables are never replayed automatically.

## Update, rollback and verification

The implementation backup is local under `.elite-local/acceptance-backup-*`, with
the pre-change source, personal configuration, bindings and Git status. Existing
audio work was preserved. A second source snapshot before the key-command change
is under `.elite-local/before-key-commands-*`. Restore only the specific changed source files after
reviewing later edits; never reset the whole working tree. Existing binding/profile
installation receipts support guarded rollback through `control_setup restore`.

The new shortcut can be removed with `install-companion-shortcut.ps1 -Restore`;
it refuses removal if the shortcut no longer matches its recorded bytes. Old
shortcut backups remain available. No Core restart is automated by these steps.

Automated checks (mocked/replayed inputs, not game acceptance):

```powershell
.\.venv-core\Scripts\python.exe -m unittest discover -s tests -p 'test_elite*.py' -q
.\.venv-core\Scripts\python.exe -m unittest discover -s tests -p 'test_config*.py' -q
.\.venv-core\Scripts\python.exe -m unittest discover -s tests -p 'test_tool_execution_context.py' -q
git diff --check
```

Revalidate after changes to input code, deployment, bindings, game version or
observation rules. A new binary, a version label, passing tests or a healthy ping
cannot replace the observed acceptance sequence.
