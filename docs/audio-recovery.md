# Managed launch and audio recovery

For this source installation, the ordinary Wingman shortcuts start the modified
Core and then the installed graphical client. Loading the enabled Elite companion
starts its local monitor automatically. There is no recurring setup script or
spoken activation phrase. The existing `EliteDangerous-Copilot` profile inherits
the skill's activation default without replacing its prompts or controls.

## Normal use

Open Wingman using its Desktop or Start Menu shortcut, select the Elite companion,
and use push-to-talk or your existing voice-activation setting. Wingman can start
before Elite. Journals that appear later are picked up by the local monitor.
Fresh supported events are narrated subject to the existing busy-audio and
30-second cooldown rules. Historical catch-up remains silent.

Explicit microphone/output selections remain the preferred devices. When one is
missing, Wingman uses the current system default for that direction and returns
when the preferred device reappears. Unset selections follow system defaults.
Devices are matched by name and audio host, not old enumeration indices; ambiguous
duplicate names fall back to the default instead of guessing.

Device/resume notifications on Windows supplement fresh enumeration every five
seconds. Reconciliation coalesces notifications for one second. Capture retries
use delays of 1, 2, 5, then 10 seconds. Failed enumeration uses the same capped
backoff. Windows-specific imports are guarded; other platforms use reconciliation.
When a device opens but rejects the requested rate, the worker probes its native
rate and converts PCM using a stateful resampler. If a preferred device cannot
open, the worker also attempts the system default.

Physical audio runs in disposable worker processes with bounded requests and
three-second driver deadlines (five seconds for enumeration). A driver hang does
not require restarting Core. Workers exit on normal shutdown and watch their
parent so abrupt Core termination does not leave microphone workers behind.
Core retains the existing player interfaces, sound effects, and client API schemas.

Device loss discards an interrupted recording. Press push-to-talk again after
recovery; a partial command is never submitted automatically. Continuous listening
reopens itself only while it remains enabled and unmuted. Azure voice activation
now transcribes complete phrases captured through the same managed microphone.
Interrupted playback is cancelled, with completion delivered once; a later reply
uses the recovered output. Old speech and game actions are not replayed.
ElevenLabs PCM streaming also uses Core's player rather than an SDK-owned device.

No usable input/output suspends that direction. Text interaction and telemetry
remain available. Changes appear in the normal Wingman log/client messages;
permission denial, unavailable hardware, and provider failures still require the
underlying dependency to become usable. No recovery changes OS default devices.

## Installation and restoration

For the Elite companion, use the distinct **Elite Companion - Managed Core**
shortcut installed by `tools/install-companion-shortcut.ps1`. It preserves existing
Wingman shortcuts and checks actual target drift. See the [current deployment and
acceptance procedure](elite-dangerous-acceptance.md). The older shortcut replacement
installer below is retained for existing rollback receipts, not the current setup path.

### Restarting Core after a source update

Closing the Wingman GUI does **not** stop the managed background Core. Reopening
the shortcut reuses that process, including its loaded Python code and profile.
Reinstalling the GUI is unnecessary for a Core source update.

Close the Wingman GUI. In PowerShell, identify the Core listener:

```powershell
Get-NetTCPConnection -LocalPort 49111 -State Listen | Select-Object OwningProcess
```

In Task Manager's **Details** tab, find the `python.exe` with that exact PID.
Confirm it belongs to this managed Core, then end that process. Do not end all
Python processes. Reopen Wingman with the normal managed shortcut; with the port
free, the launcher starts a fresh Core. A newly dated Core log confirms startup.
Select the Elite profile and use a fresh conversation after changing its tools.

For control updates, also select the game presets listed in the controls setup
review. Preset installation and selection are separate steps. Source Core updates
do not require reinstalling the Wingman client.

`tools/install-managed-launcher.ps1` is a one-time installer. It finds Wingman
shortcuts on the Desktop, Start Menu, and taskbar; backs up their original bytes
under `.elite-local/managed-launch`; and targets this checkout's `pythonw.exe`
with `tools/managed_launch.py`. Shared shortcuts require Windows administrator
rights. It does not start or stop Core or change persistent execution policy.

The launcher serializes concurrent opens, waits up to three minutes for Core, and
checks that the port belongs to this checkout. An unrelated process on port 49111
produces a visible error; it is not stopped or silently reused. Startup errors are
recorded in `.elite-local/managed-launch/core-startup.log`. Do not move the checkout
or delete `.venv-core` while these shortcuts refer to it. App updates that replace
shortcuts require reinstalling the managed shortcuts.

On Windows, virtual-environment Python redirects into its base interpreter. The
identity check accepts the exact interpreter recorded in this checkout's
`pyvenv.cfg`, together with this checkout's absolute `main.py` path. The shortcuts
explicitly retain the installed application's icon. `--connect-only` can reopen
the client against an existing matching Core without starting another Core.

Installer commands for maintenance (not normal use):

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools/install-managed-launcher.ps1 -CheckOnly
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools/install-managed-launcher.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools/install-managed-launcher.ps1 -Restore
```

Restoration only overwrites shortcuts still pointing to this launcher. It retains
the backup files. Run restoration with administrator rights for shared shortcuts.

## Verification and remaining live acceptance

On 2026-09-28, the installed client connected to this checkout's Core and the
user confirmed an audible companion reply. The runtime log confirmed automatic
Elite monitor activation; the selected Elite configuration contained only the
renamed companion. A regenerated, unchanged Companion template was retained as
`.Companion.yaml`, Wingman's logical-deletion marker, to prevent duplicate monitors.
Both shared shortcuts retain their original Wingman icon and have backups.

Automated coverage includes activation/startup ordering, monitor restart/unload,
preferred-device return, default changes, missing/ambiguous devices, format probing,
busy-device fallback, hung-worker termination, stale callbacks, interrupted capture,
playback failure/completion, and preserving settings while a device is absent.
These tests mock physical audio and external providers. A separate real worker
enumeration probe verifies the installed PortAudio transport without recording.

```powershell
.\.venv-core\Scripts\python.exe -m unittest discover -s tests -p 'test_audio*.py'
.\.venv-elite\Scripts\python.exe -m unittest discover -s tests -p 'test_elite*.py'
```

Remaining live acceptance: hear a fresh supported gameplay announcement and
test FIFINE and the active output device through disconnect/reconnect,
disable/enable, system-default changes, input loss mid-phrase, output loss mid-reply,
sleep/resume, and repeated shortcut opens. Confirm muted voice activation remains
muted and subsequent replies recover. The target is recovery within 15 seconds
after Windows exposes a usable device; measure this on hardware rather than infer
it from mocked tests. Successful initial speech does not establish physical
hot-plug recovery. The final parent-process cleanup refinements load at the next
user-initiated Core restart; no agent restart was performed.
