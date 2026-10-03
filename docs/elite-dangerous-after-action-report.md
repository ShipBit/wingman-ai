# Elite Dangerous companion: after-action report

**Date:** 2026-09-28. **Decision basis:** reliable basic controls, specifically ship lights and night vision. **Status:** investigation and documentation complete; gameplay acceptance not achieved in the reviewed evidence.

## 1. Finding and recommendation

The development effort produced code, configuration changes, and passing automated tests. It did not establish that the delivered companion repeatedly operates lights and night vision in the game. The user reported that spoken success did not correspond to visible changes. Runtime logs independently establish unsupported success assertions, later parser refusals before input, and a subsequent session using the packaged installation instead of the modified source installation. These are separate failures at different stages of the command path. [E1–E8]

**Recommendation: NO-GO on further broad companion development or distribution as a working control integration until basic-control acceptance passes.** Do not count another source patch, configuration readback, or mocked test run as completion of that acceptance gate.

**Permanent abandonment on architectural grounds is not supported by this investigation.** The recorded refusals do not establish that Elite rejected correctly injected input: the new control tool recorded zero input events in the two traced failures, and the latest session recorded no control-tool call. The older unsuccessful attempts lack the evidence needed to isolate the Windows-to-game failure. [E1–E3]

**Likelihood of a proper fix: not quantified.** There is no measured success rate for the complete repaired path on this installation and no basis here for a percentage, a promise of reliability, or a fixed effort estimate. The recommendation above is an engineering judgment against the user's selected acceptance criterion; it is not a measured probability.

The actionable distinction is between stopping open-ended feature work and declaring the project technically impossible. The evidence supports the former. It does not establish the latter. A separately authorized, bounded acceptance investigation is the only next activity recommended here; this report does not authorize or perform it.

## 2. Evidence boundaries and method

This audit inspected the working tree, Git status and history, control routing and execution code, tests, saved setup/validation records, application logs, project-specific Codex transcripts, installed skill directories, and existing shortcut targets. The user explicitly authorized reading this project's Codex transcripts and selected reliable basic controls as the decision basis.

The repository baseline is commit `23a3c8686a99c909ece382dd5695e0522c8f092d`. The Elite integration and its tests are untracked at the audit snapshot; shared Core files also contain uncommitted modifications. This is not a sequence of committed Elite releases. The chronology below uses dated records instead of inventing commit boundaries.

Application log times are reproduced as local recorded times. Codex transcript and receipt times ending in `Z` are UTC; the chronology converts them to America/New_York time, UTC−04:00 on these dates. The installation snapshot was rechecked at **2026-09-28 13:04 EDT**. The newest inspected application log ended at **12:52:31 EDT**. Later activity is outside this report's evidence window.

Evidence has three distinct meanings:

- **Direct observations:** file contents, log entries, code behavior, current shortcut targets, directory existence, and the bounded test execution performed during the audit.
- **Attributed records:** the user's report of visible game behavior and historical assistant statements or validation receipts. A saved claim is evidence that the claim was made; its existence alone does not prove the underlying outcome.
- **Unestablished matters:** successful delivery of the repaired input path in Elite, the exact cause of the older injection failure, and who or what restored shortcuts to the packaged executable.

No game input, Core restart, installation, binding change, profile change, or launcher change was performed for this report. No new feature or API change was made. Personal journal contents, credentials, and full conversation transcripts are not reproduced. Local-only evidence is identified in the evidence register so this document does not imply that ignored receipts and private logs are committed with it.

## 3. What happened

| Time, EDT | Request or development step | Evidence and actual result |
| --- | --- | --- |
| September 27, initial development | Build the companion and generate controls. | Research notes and transcripts record telemetry, public-data tools, and 29 generated controls. The initial controls used forced instant activation. Core's native command schema excludes those commands; exact transcription punctuation was also a matching issue. This is a command-routing problem, not evidence of game input rejection. [E4, E9] |
| September 27, 21:32–21:46 | User reported unavailable light commands and missing docking narration; command exposure and narration were revised. | The installation receipt records 29 tool-executable controls, a punctuation shortcut, HTTP 200 configuration save, and `game_input_sent: false`. The assistant opened with “I corrected both issues,” while explicitly requiring live retesting. [E4, T1] |
| September 28, 11:08–11:10 | Requests to turn on/activate lights. | The log records `Executed AI command: ship toggle lights`, followed by “the ship lights have been toggled on” and another assertion of toggling. The user subsequently reported no visible result. No game-state confirmation accompanies those executions. [E1, T2] |
| September 28, 11:25–12:00 | A replacement control design and implementation were delivered. | The plan introduced a Windows scan-code adapter, telemetry verification, runtime binding resolution, and a separate control skill. The saved installation validation records 43 configured actions, 240 passing Elite tests plus four native-command tests, and one skipped test. It also records `gameplay_verified: false` and `hardware_acceptance: "pending"`. [E5, T2] |
| September 28, 12:00–12:05 | User closed and reopened the client/game, then reported continued false success. | The 10:45 Core log still records legacy command executions at 12:00:59 and 12:01:20. The user reported that physical Insert worked. The assistant's subsequent diagnosis identified a still-running older Core and acknowledged that its restart instruction needed to be clearer. [E1, T2] |
| September 28, 12:06–12:14 | Restarted source Core received requests through the new skill. | Startup identifies the repository skills directory. At 12:14:01 and 12:14:22, the tool received `action="turn on ship lights"`; both attempts returned an unsupported-action result and recorded `input_events: []`. Input delivery was not reached. [E2] |
| September 28, 12:22–12:44 | User reported blocked controls, duplicate profiles, a Load-dropdown problem, and unfriendly preset names; further repairs followed. | The source gained action identifiers/phrase handling and configuration-directory repairs. Saved evidence records friendly presets, 42 of 43 actions configured, Insert for lights, numpad subtract for night vision, and unchanged hold mode for SRV drive assist. Both gameplay and the visible Load dropdown remained unverified. [E6, E7, T2] |
| September 28, 12:50–12:52 | Latest logged restart and “Toggle ship lights” request. | Startup identifies `C:\Program Files\WingmanAI\_internal\skills`, not the checkout. The reply says the control is unavailable; the log records `Tool Execution: 0ms` and no `elite_control` call. Startup also again reports multiple default configurations. [E3] |
| September 28, audit snapshot | Inspect current launch and installation state. | Both inspected normal shortcuts target `C:\Program Files\WingmanAI\WingmanAI.exe` with empty arguments. The new control skill is present in the checkout and absent from both the packaged and user skills directories. [E8] |

The staged-installation count of 43 and later readiness count of 42 describe different snapshots. The later record explicitly identifies preserved SRV hold mode as the one unavailable action. Neither number counts successful in-game commands. [E5, E6]

### The original success report did not verify success

The generic command executor calls `execute_action`, logs “Executed,” and returns a configured response or `OK`. It does not read Elite telemetry. Before the local change, the action method also caught exceptions without re-raising them; the current diff adds exception propagation and protects instant-command failure reporting. That is a real error-handling defect in the earlier code. The specific light requests reviewed here do not establish that a swallowed exception caused their failure. [E1, E10]

The legacy named-key path omits extended-key metadata by default and maps numpad names through a virtual-key path. Its input function falls back from `SendInput` to `keybd_event` and does not provide the caller with a checked, game-observed outcome. These implementation facts explain why an “Executed” log is insufficient. They do not identify which low-level condition prevented the older light commands from changing the game. There is no contemporaneous packet/permission/focus/telemetry trace resolving that question. [E10]

There is also a difference between turning a state on and toggling it. The older command was a toggle even when the request was “turn on.” Without an observed starting state, asserting “on” was not justified by the action performed. [E1, E10]

### The replacement introduced a parser failure before input

The two 12:14 failures are unusually clear: the model generated a phrase for an action argument; the running implementation rejected that phrase; no input events were sent. Returning “unsupported in this mode” did not accurately identify the phrase-recognition defect documented in the subsequent repair. [E2, E7]

The current source accepts the failed phrase and exposes a bounded action enum. Its tests establish that behavior for supplied arguments. They do not establish that the live model always selects the correct action and state. One historical request makes that distinction concrete:

- The user transcript at 12:14:19 says “Toggle ship lights.”
- The model supplied `action="turn on ship lights", state="toggle", mode="ship"`.
- The current compatibility parser resolves that combination to **on**. A regression test explicitly expects this behavior.

Thus accepting the old payload is not proof that the original user's toggle intent has been preserved. This is an observed discrepancy between the historical request and the current interpretation rule; no new live failure is claimed here. Acceptance must compare the user's intent as well as the tool's result. [E2, E11]

### Source changes and the running installation diverged

The stale process incident and the later packaged startup are distinct. The former retained an earlier imported implementation. The latter loaded from a different installation whose skill directories lack the new control skill. The profile still names `EliteDangerousControls` in its discoverable skills, but a profile entry does not install its implementation. [E3, E8]

The managed-launcher source starts the repository Core, checks process ownership, and then opens the installed GUI. A saved launcher record reports a previously matching Core. The currently inspected shortcuts instead launch the installed GUI directly. These observations establish a deployment discontinuity. They do not identify its author, establish an installer/reinstall event, or assign fault to the user. A historical ready check is not proof of the identity of the later process. [E8, E12]

The latest refusal therefore is not a live test of the newest source fix. It provides no evidence that the replacement scan-code injection was rejected by the game. It also does not prove that launching the correct source alone completes the repair: the end-to-end gameplay gate remains unperformed in the reviewed records.

## 4. Why repeated repair efforts did not establish completion

### Validation stopped short of the requested outcome

The requested outcome was a visible, repeatable game action with truthful reporting. Historical checkpoints established narrower results: generated bindings, configuration saves, source changes, parser behavior, mocked input handling, and telemetry parsing. The saved acceptance ledger repeatedly left live controls open while other subsystems continued to expand. Telemetry and docking narration read game output; their operation does not establish the separate input path. [E4–E7, E9]

The automated tests are useful for their stated scope. In the engine fixture, a mock `send` appends a successful input event and directly flips the synthetic lights bit. The Windows packet test replaces `SendInput`. Skill-dispatch tests replace execution. None of those tests observes Elite responding to a real injected key. The opt-in test named “live” reads local journals and exercises public-data/MCP calls; it is not a game-control test. [E11, E13]

During this audit's planning pass, the following existing suite ran successfully:

```powershell
.\.venv-core\Scripts\python.exe -B -m unittest discover -s tests -p test_elite_control_runtime.py -v
```

Result: **24 tests passed in 3.750 seconds**, with mocked input and temporary fixtures. It was not repeated during report writing because no source change required another run. This result validates the bounded regression suite; it adds no gameplay successes to the record. Historical totals of 244 and 267 passing checks remain attributed to their respective earlier validation records, not presented as freshly rerun full suites. [E5, E7, E11]

### Completion wording and caveats were inconsistent in emphasis

| Assistant statement | Qualification in the same answer | Audit assessment |
| --- | --- | --- |
| “I corrected both issues” — September 27, 21:46 | Input execution was mocked; actual input and audible narration still needed retesting. | Command exposure and narration code were revised. The user's full gameplay outcome had not been demonstrated. [T1] |
| “Implemented and installed” and “Correct physical-key input” — September 28, 12:00 | “Live gameplay verification remains pending.” | Code and staged installation evidence existed; verified delivery to Elite did not. [T2] |
| “Implemented and installed the repairs with backups” — September 28, 12:44 | Core needed restarting; lights, night vision, and Load-dropdown checks remained unverified. | Source/configuration repair was reported while acceptance remained open. The next logged startup used the packaged skills directory. [T2, E3] |

It is inaccurate to describe all prior coding answers as unconditional claims of proven gameplay success: the inspected answers contain explicit caveats. It is equally inaccurate to present their passing tests as completion of the user's control requirement. The completion-oriented lead statements and pending acceptance described different levels of completion. The runtime companion's own success assertions were a separate defect, because they lacked an observed outcome. [E1, T1, T2]

**Process assessment:** development and reporting did not consistently make successful deployment and observed game behavior the completion boundary. The evidence supports this assessment; it does not establish deceptive intent, a psychological explanation, or that every earlier code change was ineffective.

No controlled comparison of Codex effort settings was performed. This audit provides no factual success-rate comparison between effort levels. An effort setting, a long plan, and a large test count are not observations of a game-state transition.

### Restart and distribution were unresolved parts of delivery

The repository instructions prohibit the agent from restarting Core. That explains the user-operated restart boundary. It does not establish that any particular restart launched the repaired Core, and it does not remove deployment identity from the acceptance requirements. The earlier source/GUI split and later packaged startup demonstrate why that identity required verification. [E3, E8, T2]

The duplicate-configuration repair also had a narrower result than a verified UI fix. Saved metadata reports a directory repair and preserved profile. It explicitly leaves the visible dropdown unverified. The packaged startup later reports multiple defaults again. The record does not establish the UI dropdown's ultimate cause or successful resolution. [E3, E6, E7]

## 5. Architecture and the limits of the feasibility conclusion

The inspected implementation uses this command path:

```text
Voice/text request
  -> transcription and model/tool selection
  -> loaded control skill and argument interpretation
  -> active binding and game-context checks
  -> Windows key-down/key-up injection
  -> Elite processes the binding
  -> fresh Status.json observation
  -> spoken outcome
```

Evidence at an earlier step does not prove completion of a later one. Journal/MCP reads, configuration readiness, injection return values, and visible game response are different observations.

Microsoft documents scan-code input and the extended-key flag. `KEYEVENTF_SCANCODE` makes the scan code identify the key; `KEYEVENTF_EXTENDEDKEY` supplies extended-key information. The replacement adapter uses these mechanisms, checks the number of inserted events, and releases its pressed keys. That establishes implementation against a documented Windows interface, not tested Elite compatibility. [Current adapter](../skills/elite_dangerous_controls/input.py); [Microsoft KEYBDINPUT](https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-keybdinput).

Microsoft documents that `SendInput` returns the number of inserted input events and is restricted by process integrity levels. It does not return an Elite action result. Its documentation also states that error information does not identify UIPI blocking specifically. A successful insertion count therefore is insufficient evidence of ship-light activation. No process-integrity cause is established for the historical failures reviewed here. [Microsoft SendInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput).

Frontier's journal manual documents `Status.json`, including **LightsOn at bit 8** and **Night Vision at bit 28**. It describes a game-written status file, not a command endpoint. The current runtime checks these flags for relevant actions and waits for a new observation after input. The existence of that observation channel supports a concrete acceptance measurement; it is not evidence that this implementation has passed it. [Frontier journal manual, section 14](https://hosting.zaonce.net/community/journal/v31/Journal_Manual_v31.pdf); [current control runtime](../skills/elite_dangerous_controls/runtime.py).

The implemented controller strategy reads keyboard/mouse alternatives from active bindings, preserving physical controller assignments where supported. A HOTAS/gamepad fixture tests mapping behavior; it does not establish that real hardware combinations work. Controller-only actions without an injectable alternate remain a setup issue. The existing scope excludes background input, launch/docking automation, and sustained axis control. Success for two ship toggles would not establish those capabilities or all 43 catalogue actions. [Control documentation](elite-dangerous-controls.md); [binding resolver](../skills/elite_dangerous_controls/runtime.py).

The audit did not reverse-engineer Elite's input engine, demonstrate an anti-injection barrier, or test an alternative control product. No claim that DirectInput, anti-cheat, the Cobra engine, or an absent remote command API makes this integration impossible is established here. No claim of guaranteed repairability is established either.

## 6. Go/no-go criteria and outstanding evidence

| Decision | Recommendation at this evidence snapshot | Basis |
| --- | --- | --- |
| Use or distribute this as verified basic game control | **NO-GO** | User-reported failures and no completed, observed gameplay acceptance for the repaired path. |
| Continue adding unrelated companion features or repeating broad speculative rewrites | **NO-GO until the basic-control gate passes** | Existing scope already exceeds the unverified control requirement. More peripheral work does not supply the missing evidence. |
| Permanently scrap all work because Elite/Wingman architecture prevents control | **Not justified by the evidence** | Traced newer failures occurred before injection; the older delivery failure remains unresolved. |
| Perform one bounded investigation of deployment and basic-control delivery | **Recommended only as separately authorized work** | It addresses the missing evidence directly. It is not a forecast of success or a commitment to further development. |

This recommendation preserves the existing work; it does not instruct deletion or claim that sunk effort justifies more investment. No budget or cost model was supplied, so this report does not make an economic return estimate.

The outstanding facts are specific:

1. Whether the intended source Core, current control skill, profile, and bindings are simultaneously loaded in the actual client/game session.
2. Whether one direct control request sends the expected events and changes the observed lights/night-vision state in Elite.
3. Whether the voice/model path preserves on/off/toggle intent and invokes that same control path reliably.
4. Whether repeated requests and loss of focus produce correct outcomes and truthful messages.
5. Which condition caused the older legacy injections to have no visible effect, and what changed the launcher targets. Neither is resolved by the present records.

### Unperformed acceptance protocol

This protocol is a stop/go measurement, not another implementation claim. It requires a separately authorized session with the user operating the game and any required Core restart.

1. Record the actual Core executable/script path and process identity, loaded control-module path, profile, selected bindings, current game session, and foreground process. A matching version label or healthy `/ping` response alone is insufficient. Stop if the expected control implementation is absent.
2. In a safe ship cockpit, record physical-key behavior for the active lights and night-vision bindings, including visible result and fresh telemetry. The historical report that Insert worked remains a user observation until this measurement is captured.
3. Invoke one direct control action through the same runtime, bypassing the model's selection step. Capture binding revision, key-down/up events, insertion results, before/after observations, and visible outcome. Classify a failure at the first failing stage; do not change multiple subsystems or automatically repeat uncertain toggles.
4. Repeat through voice using explicit on/off and toggle wording. Compare the user's request, model arguments, normalized intent, input, telemetry, and spoken result. In particular, test a toggle from an already-on state; reporting “already on” is not success for an inversion request.
5. Require **20 consecutive correct on/off requests for each action**. For each action, repeat the sequence “on, on, off, off” five times after establishing an off baseline. Each second identical request must send no input. Also test toggle from both states and a request while Elite has lost focus; focus loss must send no action input and must not report success. Record actual hardware and settings.
6. A false success or any failed required outcome fails the gate. Passing the sample authorizes only a recommendation for the measured basic-control scope, not a universal reliability claim. A failed run ends in a fault-localized evidence report and a separate decision about a specific correction, not an automatic expansion into more features.

No gameplay acceptance result is entered by this audit. There is no substitute result hidden in the test totals.

## 7. Evidence register and reproducibility

Repository links refer to inspected working-tree files. Local artifacts below are intentionally not copied wholesale into tracked documentation. Application logs live under `%APPDATA%\ShipBit\WingmanAI\2_1_1\logs`; transcript paths are relative to `%USERPROFILE%\.codex\sessions`. Line references identify the inspected versions.

| ID | Source | Relevant evidence |
| --- | --- | --- |
| E1 | Application log `wingman-core.2026-09-28_10-45-10.log`, lines 162–164, 200–202, 285–307 | Requests, legacy “Executed AI command” entries, and spoken light-state claims. Startup line 1 identifies source skills. |
| E2 | Application log `wingman-core.2026-09-28_12-06-33.log`, lines 1, 101–137, 172–190 | Source startup; exact failed arguments; empty input event lists; subsequent readiness changes. |
| E3 | Application log `wingman-core.2026-09-28_12-50-02.log`, lines 1–17 and 49–58 | Packaged skills directory, repeated multiple-default warning, final request/refusal, and zero tool-execution time. |
| E4 | `.elite-local/verification/controls-narration-diagnostic.json`; `.elite-local/verification/native-controls-install.json` | Original forced instant commands; updated exposure and punctuation; configuration save; no game input. |
| E5 | `.elite-local/verified-controls-install/validation.json`; `.elite-local/verification/verified-controls-tests-final.txt` | 241 Elite tests run, one skipped; four native tests; installation checks; gameplay false/hardware pending. |
| E6 | `.elite-local/control-repair-validation.json` | 42 configured actions; friendly selections; lights Insert; night vision numpad subtract; gameplay/dropdown false. |
| E7 | `.elite-local/configuration-repair-result.json`; [research log](elite-dangerous-research.md), “Control and configuration regression repair” | Preserved profile and repaired directories; historical 267 passing-test total and open acceptance. |
| E8 | Direct read-only inspection, 2026-09-28 13:04 EDT | Public Desktop and all-users Start-menu Wingman shortcuts target the packaged GUI; source control skill present; packaged/user control skill absent; installed Copilot profile lists the skill. |
| E9 | [research and acceptance ledger](elite-dangerous-research.md); [native tool schema](../wingmen/open_ai_wingman.py), command filter near line 2391 | Development chronology, outstanding gameplay acceptance, and forced-instant exclusion. |
| E10 | [Core executor](../wingmen/wingman.py), `_execute_command` and `execute_action`; current Git diff; [legacy Windows backend](../keyboard/keyboard/_winkeyboard.py), `map_name` and `_send_event` | Success reporting, added exception propagation, extended-key/numpad handling, and unchecked fallback. |
| E11 | [control runtime](../skills/elite_dangerous_controls/runtime.py), `normalize_request` and `ControlEngine`; [runtime tests](../tests/test_elite_control_runtime.py), especially fixture near line 120 | Current interpretation rule, mocked input/telemetry, and the 24-test bounded audit run. |
| E12 | [managed launcher](../tools/managed_launch.py); `.elite-local/managed-launch/last-launch.json`; `.elite-local/managed-launch/shortcuts.json` | Source-Core launch/ownership design and historical launcher records; not proof of current shortcut targets. |
| E13 | [skill tests](../tests/test_elite_control_skill.py); [native-command tests](../tests/test_command_exposure.py); [opt-in live test](../tests/test_elite_live.py) | Mocked execution and the distinction between public-data/journal checks and game input. |
| T1 | `2026/09/27/rollout-2026-09-27T19-58-53-01a0e54e-aa5c-7a63-9fc8-b757aa458d6f.jsonl`, user line 408 and assistant line 559 | Initial reported refusal; “I corrected both issues”; mocked validation and explicit retest caveat. |
| T2 | `2026/09/28/rollout-2026-09-28T11-10-59-01a0e891-b698-7c53-9556-f45e6a44d0dd.jsonl`, lines 9, 102, 472, 479, 510, 520, 582, 775 | User-visible failures, physical Insert observation, repair plans, completion wording, restart diagnosis, and caveats. |

SHA-256 identifiers for key audited working-tree files distinguish this snapshot from earlier receipts. They are provenance, not evidence of runtime loading or correctness.

| File, relative to repository | SHA-256 at 2026-09-28 13:04 EDT |
| --- | --- |
| `skills/elite_dangerous_controls/input.py` | `b7054450eb490c64c7de3d1238fee9b89a45fb85619da657a15949a6e720e9f2` |
| `skills/elite_dangerous_controls/runtime.py` | `f6884138f7df6fa9f415c4d1872496a30013bfa163a7a70e3206cdfbd6140b41` |
| `skills/elite_dangerous_controls/main.py` | `1ec909441d5ea33bce1ecb29ac77060cda9097436eb4897969c571ca8af9b333` |
| `wingmen/wingman.py` | `8731cb04d8503823d80657b7f1a2fef766fc84715a5759776cb86c77cf5a9642` |
| `tests/test_elite_control_runtime.py` | `28073e4cd4a667dcd9792044f7ea45c113fc403dd24e484eca115b21ace78ff3` |

## Appendix: approved investigation plan and disposition

This appendix preserves the approved plan's work items and scope. It is an investigation/report plan, not authorization for the unperformed gameplay protocol above.

| Planned work | Disposition |
| --- | --- |
| Save the report as `docs/elite-dangerous-after-action-report.md`, including the plan. | Completed by this document. |
| Evaluate reliable lights/night-vision control before further development. | Used as the decision criterion in sections 1 and 6. |
| Inspect code, receipts, logs, project-specific Codex transcripts, and official contracts. | Completed within the evidence window; sources and limitations are recorded in sections 2 and 7. |
| Trace original command exposure, unsupported success, replacement control implementation, parser rejection, repair, and latest packaged startup. | Documented separately in section 3; no single unproven root cause substitutes for that sequence. |
| Compare requested outcome, change, validation, completion wording, and subsequent user result. | Completed in sections 3 and 4, preserving explicit assistant caveats and attributed user observations. |
| Treat restart/deployment identity as part of delivery and reconstruct uncommitted work without inventing Git history. | Completed in sections 2–4. Shortcut-change authorship remains unknown. |
| Assess Windows input and Elite observation architecture without an invented probability or guaranteed fix. | Completed in section 5; no game-level injection barrier or universal compatibility is asserted. |
| Give a go/no-go recommendation grounded in the selected criterion. | NO-GO for delivered/basic-control claims and broad feature work; permanent architectural abandonment is not established. |
| Record the 24 passing mocked runtime tests and distinguish all historical/offline checks from gameplay. | Completed in section 4. No fresh full-suite or in-game success claim is made. |
| Define, but do not perform, direct-control and voice-control acceptance with 20 requests each for lights/night vision, already-set states, and loss of focus. | Specified in section 6; remains unperformed and requires a separately authorized session. |
| Preserve application code, APIs, bindings, profiles, and launchers. | Report-only change; no operational repair was performed. |

The saved report completes the documentation task. It does not mark the Elite control implementation or its gameplay acceptance complete.
