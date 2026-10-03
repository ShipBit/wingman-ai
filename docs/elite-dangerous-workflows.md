# Supervised Elite companion workflows

These checklists use the same production controller as individual voice commands.
The model cannot write a keystroke script. The commander retains movement, aiming,
approach, target decisions and engagement decisions. No driver, autonomous pilot,
launch macro or automatic docking routine is added.

Say **start travel preparation**, **workflow status**, **continue workflow** or
**cancel workflow**. “Prepare for travel,” “prepare for landing,” “prepare for
combat,” and “configure SRV” are also recognized. Continue means that you have
completed or checked the current player checkpoint. It is a gameplay decision,
not a request to perform a test routine.

| Start name | Steps and completion |
| --- | --- |
| travel preparation | Observe/retract gear, scoop and hardpoints; completes when all three are stowed. Start undocked. |
| route target | Player plots route; request next route target once; player checks selected system. No route entry macro. |
| arrival scanning | Player settles after arrival, operates discovery/FSS scanning and reviews results; checkpoints complete the checklist. Existing exploration queries remain available separately. |
| landing preparation | Observe/stow hardpoints and scoop; player obtains clearance/handles approach; lower and observe gear after the checkpoint. |
| combat preparation | Observe/stow gear and scoop; deploy/observe hardpoints; player checks target and fire group. No firing. |
| power targeting | Request balanced pips, one increase to weapons, then target ahead; each unobserved result requires a player checkpoint before the next press. |
| defensive heat sink | Explicitly requested heat-sink press once, then player checkpoint. No automatic second deployment. |
| defensive chaff | Explicitly requested chaff press once, then player checkpoint. |
| SRV configuration | Observe/stow scoop and leave turret view; request balanced pips; player checks pips and chooses drive-assist setting. |
| on foot equipment | Player chooses equipment and authorizes a shield toggle; one toggle followed by a player check. |
| on foot health | Explicitly requested health-pack press once, followed by a player check. |
| on foot energy | Explicitly requested energy-cell press once, followed by a player check. |

Individual commands always press once. Workflow `ensure` steps are different:
they inspect the relevant status flag, skip a switch already in the required
state, and wait up to three seconds for an observed change after pressing. Missing
observations stop the workflow. An uncertain toggle or consumable is never replayed.

Escape cancels locally without an AI response. Focus, session or binding changes,
profile unload and conflicting changes to previously verified controls stop the
workflow and release companion-owned keys. An individual control request ends
the current workflow. Stopped or cancelled workflows require a fresh start.
Workflow progress is deliberately not restored after restarting Core.

Route/scanning checkpoints allow their relevant in-game views; execution never
presses controls into those views. Close them before continuing. Screenshots do
not automatically advance a workflow; no screenshot loop or model-controlled
image prerequisite is implemented. Use an explicit player checkpoint whenever
the game does not provide a reliable automatic observation.

The two tools are progressively activated. A successful individual command gets
a fresh short acknowledgment from the configured AI, after the input receipt.
Workflow checkpoints retain their precise instructions and completion conditions.
External system/station/engineering queries remain in MCP; local state and event
narration remain in the existing telemetry skill.

All 12 definitions complete three consecutive **synthetic** runs, with tests for
uncertain observations, interruption, duplicate calls, wrong mode and no consumable
replay. Live end-to-end workflow acceptance has not been performed. Installation
and current live evidence are recorded in [acceptance](elite-dangerous-acceptance.md).
