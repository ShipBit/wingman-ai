# Elite Dangerous companion — PR readiness check

Review date: **2026-09-28**  
Review target: the current working-tree implementation, including uncommitted changes.  
Assessment: **Suitable for a draft PR; the checks below remain open before a general-user release.**

This review considers a new Wingman AI user with a new or existing Elite Dangerous installation and their own bindings. It covers installation, first-run behavior, command expectations, customization, and the scope of an upstream contribution. It does not certify every command in live gameplay.

The readiness gates below are review recommendations, not requirements issued by ShipBit. The comparison is grounded in ShipBit's documented emphasis on accessible client configuration, customizable commands, multilingual interaction, and efficient capability discovery: [product overview](https://www.wingman-ai.com/) and [skill development documentation](https://github.com/ShipBit/wingman-ai/blob/main/skills/README.md).

## Decision and priorities

The implementation reads the user's selected bindings, checks conflicts, preserves original presets during setup, and checks focus, vehicle context, cancellation, and duplicate delivery. Keep those protections.

The main readiness gaps concern turning a private installation into a supported first-run experience. Testing more commands alone will not resolve the defaults and integration issues below.

| ID | Readiness gate | Status |
| --- | --- | --- |
| PR-01 | Explicit on/off requests have predictable semantics | Open |
| PR-02 | Installation works through a supported distribution path | Open |
| PR-03 | Fresh or incomplete game configuration receives useful recovery guidance | Open |
| PR-04 | Users can understand and resolve unavailable controls | Open |
| PR-05 | Elite routing preserves existing command customization | Open |
| PR-06 | Model overhead and provider failures remain bounded | Open |
| PR-07 | Replies respect supported language and persona settings | Open |
| PR-08 | Public capability claims match the available evidence | Open |
| PR-09 | Shared Core changes have a reviewable scope and validation | Open |

## Findings and acceptance criteria

### PR-01 — Private toggle preferences became public command semantics

**Current assumption:** everyone wants explicit on/off instructions to press a toggle once.

“Turn lights on” presses the toggle even when the lights are already on. Repeating the instruction can turn them off. Deploy/retract instructions for gear and hardpoints use the same single-press approach. The documentation attributes this behavior to a private user preference.

**User impact:** the action can contradict an ordinary reading of the request, and a generic acknowledgment gives the user little help recognizing that mismatch.

- [ ] Define and document separate behavior for explicit state requests and toggle requests.
- [ ] For actions with reliable observations, satisfy an explicit state request without reversing an already-correct state.
- [ ] For actions without reliable observations, explain the limitation or require suitable toggle wording; do not imply the requested state was established.
- [ ] Preserve intentional single-press behavior as an explicit preference if it remains supported, with a clear public default.

Evidence: [documented command semantics](elite-dangerous-controls.md#what-changed), [control execution](../skills/elite_dangerous_controls/runtime.py), and [repeated on/off tests](../tests/test_elite_control_press.py).

### PR-02 — Installation assumes a developer checkout

**Current assumption:** a normal user can manage Python environments, absolute MCP paths, command-line setup plans, review files, and a managed source-Core launcher.

The MCP example points into `C:/Projects/wingman-ai`. The controls skill depends on additional Core services and a sibling telemetry folder. Copying one skill folder into an arbitrary installed release is therefore not a complete installation procedure.

**User impact:** a newcomer can follow part of the instructions, have the wrong Core running, or reach a profile whose advertised capabilities are not installed.

- [ ] Define the supported Core/client version and distribution method.
- [ ] Verify installation from the intended release artifact or installer, without relying on this checkout's virtual environments or private files.
- [ ] Generate or request machine-specific paths through the supported setup flow.
- [ ] Clearly distinguish telemetry, controls, and optional public-data MCP prerequisites, including provider/subscription requirements where applicable.
- [ ] Provide one coherent installation and update guide; keep private launcher and development instructions separate.

Evidence: [companion setup](elite-dangerous.md#setup), [controls setup](elite-dangerous-controls.md#setup-and-upgrade), [MCP example](../integrations/elite_dangerous/mcp.example.yaml), and [controls imports](../skills/elite_dangerous_controls/main.py).

### PR-03 — All required game files are assumed to exist and load together

**Current assumption:** the game has produced `StartPreset.4.start`, exactly four preset selections, and usable files for every selection.

An isolated probe with no saved controls raised `FileNotFoundError` for `StartPreset.4.start`. Another probe supplied a usable ship preset and a missing SRV preset; resolving the bindings failed on the SRV file before the ship action could become available. The implementation also expects version-4 bindings and requires Live telemetry for execution.

**User impact:** missing configuration for one vehicle can block another, and a fresh installation receives a file error rather than a first-run instruction.

- [ ] Detect missing or unsupported configuration before the first action and explain the next step, such as entering gameplay and saving controls.
- [ ] State the supported game edition, binding format, and operating-system scope explicitly.
- [ ] Isolate unrelated vehicle failures where possible while retaining required shared/general-preset checks.
- [ ] Recover cleanly when the user saves controls, changes presets, or repairs a missing file.

Evidence: [binding resolver](../skills/elite_dangerous_controls/runtime.py), [preset resolution](../skills/elite_dangerous_controls/bindings.py), and [Live observation requirements](../skills/elite_dangerous_controls/observation.py).

### PR-04 — A technical refusal is assumed to be sufficient guidance

**Current assumption:** users understand why a controller binding cannot be injected, why a hold-mode action is unavailable, and how to run controls inspection or repair.

Supported actions need injectable keyboard/mouse bindings even when the player uses HOTAS or a gamepad. Some failures direct the user to “Run controls inspect/repair.” Spoken readiness lists up to five unavailable actions and refers to a separate report for the rest. Readiness itself currently passes through foreground-game and telemetry prerequisites.

**User impact:** users discover incomplete setup during gameplay and must leave the client to work out what is missing.

- [ ] Provide an accessible readiness view with per-action reasons and concrete next steps.
- [ ] Distinguish “bindings configured,” “game ready for input,” and “outcome observed.”
- [ ] Allow configuration inspection while the game is closed where the required files are available.
- [ ] Explain keyboard alternates and hold/toggle limitations without requiring knowledge of XML tags or JSON choices files.
- [ ] Preserve existing controls and make supplemental presets, selection, and rollback understandable.

Evidence: [binding restrictions and readiness response](../skills/elite_dangerous_controls/runtime.py), [setup reports and supplementation](../integrations/elite_dangerous/control_setup.py), and [setup guide](elite-dangerous-controls.md#setup-and-upgrade).

### PR-05 — Elite routing takes precedence over existing commands

**Current assumption:** adding the Elite skill may change how the user's ordinary instant commands are dispatched.

Semantic routing is enabled by default. Unmatched speech reaches the Elite router before normal instant activation. When the router returns `conversation`, Core explicitly skips instant activation for that turn.

**User impact:** an existing custom instant command can lose its expected execution path after this skill is enabled.

- [ ] Define precedence between user commands, exact skill phrases, and semantic skill routing.
- [ ] Preserve unrelated instant commands when Elite routing declines a request.
- [ ] Keep duplicate-input prevention and turn-bound authorization intact.
- [ ] Verify an unrelated custom command, a deliberately overlapping command, ordinary conversation, and another configured skill with Elite routing enabled and disabled.

Evidence: [Core response dispatch and direct skill routing](../wingmen/open_ai_wingman.py), [Elite routing hook](../skills/elite_dangerous_controls/main.py), and [routing tests](../tests/test_elite_control_routing.py).

### PR-06 — Additional model calls and nominal timeouts are assumed acceptable

**Current assumption:** every unmatched interaction can incur a control-classification call, and every successful individual non-map input can incur a generated acknowledgment.

A sample routing payload contained **9,071 content characters and 108 action IDs**, before ordinary conversation processing. This is a character measurement, not a tokenizer-based token count. Router failures can replace an ordinary response with a request to repeat a control.

A separate acknowledgment probe used a provider double that blocked synchronously for 200 ms. With a 20 ms configured timeout, the call still completed in approximately 203 ms. `asyncio.wait_for` does not enforce that deadline while the provider blocks the event loop. Core has synchronous provider calls behind its async adapter.

**User impact:** extra cost, delayed conversation or feedback, and a risk of blocking the persistent runtime loop after input has already been sent.

- [ ] Measure routing and acknowledgment overhead with supported provider configurations, including ordinary conversation.
- [ ] Limit unnecessary classification work and define behavior when routing is unavailable.
- [ ] Make acknowledgment deadlines effective for synchronous as well as asynchronous providers.
- [ ] Ensure a late acknowledgment cannot obstruct cancellation or replay input.
- [ ] Provide a low-latency response option and document the behavior of exact commands during provider outages.

Evidence: [routing payload and timeout handling](../skills/elite_dangerous_controls/routing.py), [acknowledgment generation](../skills/elite_dangerous_controls/speech.py), and [Core provider adapter](../wingmen/open_ai_wingman.py).

### PR-07 — Responses assume English

**Current assumption:** an acknowledgment must contain an approved English expression.

The validator rejected `Verstanden, Kommandant.` and `Entendido, comandante.`, while accepting `Copy that.`. Rejected replies fall back to English. Many announcements and failure responses are also fixed English strings.

**User impact:** a companion configured for another language switches languages during controls and recovery, weakening both comprehension and persona consistency.

- [ ] Honor the supported language settings in acknowledgments, failures, clarifications, and event announcements.
- [ ] Validate factual constraints without requiring English acknowledgment words.
- [ ] Verify representative non-English requests and replies, including fallback behavior.
- [ ] Document any intentional language limitation before enabling the feature for users affected by it.

Evidence: [acknowledgment validator and fallbacks](../skills/elite_dangerous_controls/speech.py) and [event announcements](../skills/elite_dangerous/main.py).

### PR-08 — Installation-specific coverage can be mistaken for general readiness

**Current assumption to avoid:** configured bindings and synthetic command coverage establish successful gameplay for other users.

Catalog tests use simulated bindings, input, and game responses. They provide useful regression coverage but do not establish delivery through another user's device configuration, speech provider, or game context. The recorded language evaluation used one configured model and 37 utterances. Installed-readiness counts describe the reviewed private presets.

**User impact:** users may reasonably interpret a broad command catalog as a promise that every listed control is ready in their installation.

- [ ] Label evidence as static inspection, automated simulation, configured-model evaluation, or observed gameplay.
- [ ] Keep private installation counts and historical reports separate from general setup guarantees.
- [ ] Validate a representative fresh-install matrix rather than requiring every user to recite the entire catalog.
- [ ] Document unsupported actions, known limitations, and how users can report a failed command.
- [ ] Record the version, environment, binding family, and result for acceptance evidence used in the PR.

Evidence: [catalog test fixtures](../tests/test_elite_control_catalog.py), [natural-language evaluation](elite-dangerous-natural-language-report.md#configured-model-evaluation), and [gameplay acceptance record](elite-dangerous-acceptance.md).

### PR-09 — Companion work includes substantial shared Core changes

The working tree also changes audio capture/playback, provider integration, configuration repair, MCP handling, launch tooling, and shared command dispatch. Those changes can affect users who never enable Elite.

- [ ] Separate independent Core fixes into focused PRs where practical.
- [ ] Explain necessary shared dependencies in the companion PR and identify their effects outside Elite.
- [ ] Validate ordinary profiles, command dispatch, audio behavior, and startup on supported Core platforms for the shared changes being submitted.
- [ ] Keep machine-specific paths, private receipts, personal acceptance artifacts, and development environments out of the submitted change.
- [ ] Rewrite public-facing documentation around the supported implementation, removing private-session instructions from the main user path.

## Verification recorded during this review

The following focused automated suites passed:

```powershell
.\.venv-core\Scripts\python.exe -m unittest discover -s tests -p 'test_elite_control*.py'
# 114 tests passed

.\.venv-core\Scripts\python.exe -m unittest discover -s tests -p test_elite_companion_speech.py
# 4 tests passed
```

**Total: 118 tests passed.** These were focused checks, not a full repository test run or live gameplay certification.

Additional isolated probes produced these results:

| Probe | Observed result |
| --- | --- |
| No saved binding selector | `FileNotFoundError` for `StartPreset.4.start` |
| Usable ship preset with missing SRV preset | Full binding resolution failed on the missing SRV file |
| Routing payload for an ordinary ship-status question | 9,071 content characters; 108 action IDs |
| German and Spanish acknowledgment samples | Both rejected by the English-expression validator |
| Blocking acknowledgment provider with a 20 ms deadline | Returned after approximately 203 ms |

The probes used temporary files and simulated providers. They were exploratory checks, not newly committed regression tests. No game input was sent and no implementation files were changed during the review.

## Representative acceptance matrix

All rows remain pending. This matrix supplements automated regressions; it does not require manual execution of every catalog command.

| Scenario | Required evidence |
| --- | --- |
| Fresh supported Wingman installation | Companion installs and starts using the documented distribution path |
| Elite has not yet saved controls or produced journals | Clear first-run guidance and recovery once files exist |
| Existing keyboard/mouse bindings | Representative actions use the selected bindings and avoid conflicts |
| HOTAS/gamepad with missing keyboard alternates | Missing actions are explained; reviewed supplementation preserves existing mappings |
| Incomplete or changed presets | Affected capabilities are identified; unrelated supported controls remain usable where possible |
| Repeated explicit on/off requests | Behavior matches the documented public semantics |
| Existing custom instant commands and other skills | Adding Elite does not unexpectedly claim or suppress their requests |
| Slow, unavailable, or malformed provider output | Bounded response behavior; no repeated input; ordinary conversation has a defined fallback |
| Non-English companion configuration | Supported language is retained in normal and fallback responses |
| Wrong focus, chat, menus, or vehicle context | Input is appropriately blocked with useful guidance |
| Supported platform without Windows controls | Shared Core remains functional and the control limitation is clear |

## Before requesting merge approval

- [ ] Resolve each readiness gate above, or document a deliberate scope restriction and the evidence supporting it.
- [ ] Complete the relevant acceptance-matrix rows against the proposed distribution.
- [ ] Run regression checks appropriate to the final implementation and shared Core changes.
- [ ] Confirm templates, migration snapshots, configuration defaults, and public documentation agree.
- [ ] Describe the final supported behavior, remaining limitations, and validation in the PR.
- [ ] Make no unconditional reliability claim based on binding counts, successful input injection, or synthetic tests.
