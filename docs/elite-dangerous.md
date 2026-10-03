# Elite Dangerous companion (private fork, in development)

This is a **partial interactive companion**, with source deployment verified. Use **Elite Companion -
Managed Core** shortcut and the [runtime identity and gameplay acceptance guide](elite-dangerous-acceptance.md).
Lights and night vision have observed production-input results. Per the player's
request, the remaining catalog and [supervised workflows](elite-dangerous-workflows.md)
use automated coverage instead of a manual spoken test of every control. Successful
individual commands receive a brief varied AI acknowledgment after execution.

This integration uses Wingman's existing Skill, MCP and profile mechanisms.
It preserves Core's API schemas and Star Citizen profiles. Native command
errors now propagate instead of being reported as successful execution. Shared audio capture/playback now uses supervised workers; see the
[automatic startup and audio recovery guide](audio-recovery.md). The full intended suite is still under development; see the
[research and acceptance ledger](elite-dangerous-research.md).
Small shared compatibility fixes support this checkout:
`StreamToLogger.fileno()` delegates to the wrapped stream, and MCP discovery
closes its temporary SDK session in the task that opened it, matching Core's
existing per-call tool transport. Discovery no longer leaves a process/cancel
scope open for another task to close. A third fix makes `GET /config` without a
profile name read the selected profile instead of raising an unbound-variable
error. The endpoint schema is unchanged. An already running Core needs a normal
user-initiated restart to load that source fix.

## What works in the current implementation

- One runtime tool, `elite_status`, reads timestamped journal
  observations for overview, ship, cargo, materials, progression, missions,
  navigation, exploration, planning, Odyssey and the current port's local market. Use `query` to narrow list entries before the
  five-item output limit. Status and inventory data remain observations, not
  a promise that the game is currently running.
- When an enabled companion loads, local monitoring automatically narrates new arrivals, dockings and mission
  completions through the configured Wingman voice. It does not ask the LLM to
  poll the game. It skips old events and busy audio, and limits speech to once
  every 30 seconds. Disable `Announce gameplay events` in the skill UI to mute it.
  The monitor runs on Core's persistent audio event loop, so it continues after
  the voice request that activated the skill finishes. Status queries use the
  same event handling and cannot silently consume a fresh narration event.
- Material counts reconcile exact journal transactions for collection/discard,
  trades, synthesis, crafting/conversion, research, engineer contributions,
  mission rewards and current-format technology broker purchases. Updates are
  atomic and require a known category baseline. Invalid quantities, unresolved
  categories, journal gaps and older broker formats require a new snapshot.
- Cargo snapshots validate commodity/mission identities, stolen quantities and
  total counts. Supported purchases, sales, scooping, ejection, refining and
  limpet purchases/sales reconcile those exact stacks atomically. Available hold
  space can use the resulting dated total. Ship transactions cannot update an
  SRV inventory; a vessel change requires a fresh snapshot. Mixed-ownership
  removals without enough detail, underflows, transfers, drone launch, synthesis,
  mission-cargo disposition changes and other unsupported transactions require
  a full observation. Same-second file/event ambiguity cannot double-count a
  transaction, and cargo files are not read ahead during journal catch-up.
  Up to 512 stacks are retained; only five filtered entries enter a summary.
  Missing stolen counts remain unknown, and ownership does not prove local legality.
- Topic `progression` combines career ranks and percentages by category, keeping
  independent observation dates for each rank, percentage and superpower
  reputation value. Partial `Promotion` events update only the reported ranks.
  A changed or first-observed rank marks its earlier percentage as requiring
  refresh; it does not invent a new zero percent. Percentages without a confirmed
  rank retain unknown rank context. Raw numeric ranks are preserved, including
  unfamiliar levels, without guessed labels. Military progress can exceed 100:
  `reported_percent` retains that value while `display_percent` caps it at 100.
  Neither value proves promotion, permits, ship access or unlock completion.
  Invalid or older observations preserve historical values with refresh flags;
  observing one metric again does not refresh other metrics after a journal gap.
- Engineer snapshots and individual updates merge by engineer ID, with separate
  dates for each reported field. Partial grade/percentage updates do not require
  a `Progress` state. A grade change without a new percentage removes the old
  percentage; a reported non-`Unlocked` state clears earlier grade observations.
  A positive grade without `Progress` drops a stale non-`Unlocked` state without
  guessing its replacement. After invalid data or a journal gap, a partial update
  cannot clear the need for a full engineer snapshot.
- Topic `planning` returns dated balance, rebuy and cargo-space observations
  without assuming a cash reserve or landing-pad requirement. Changed ships/loadouts
  invalidate earlier capacity and rebuy values until a new loadout arrives.
- Topic `odyssey` returns the observed equipped suit and weapon loadout, backpack,
  ship locker and dashboard. Backpack changes reconcile distinct ownership and
  mission stacks atomically; owner IDs are excluded from summaries. Companion
  action events such as using a consumable do not debit the same item twice.
  Locker transactions require a new full snapshot rather than guessed quantities.
  Missing categories remain unknown. Ambiguous same-second file/change ordering,
  malformed data and deaths require refreshed inventory observations. Suit upgrades
  invalidate the old loadout until a new equipped-loadout event arrives. Creating
  a saved loadout does not equip it. This does not calculate upgrade recipes.
- Topic `exploration` retains observations for the current system visit, with
  separate dates for body scans, completed mapping, surface signals and organic
  scans. Supercruise travel preserves them; hyperspace departure clears them.
  The catalogue holds up to 512 observed bodies and 32 organic entries per body.
  Query a body or signal name before the five-item output limit; summaries stay
  within 6,000 characters and report omitted entries. Discovery-scan counts do
  not prove that the local catalogue includes every body. Only an explicit
  organic `Analyse` event records analysis completion, as a historical observation;
  it does not establish retained samples, unsold data or payout. Journal gaps
  remain marked even after later scans arrive.
- Topic `missions` sorts known deadlines first and filters mission details before
  the five-item limit. Accepted contracts, redirects and depot totals retain
  separate dates. Startup time-left values are anchored to their journal timestamp;
  elapsed deadlines do not prove failure. A startup `Complete` entry is kept as
  a reported roster state, without assuming reward payment. Accepted rewards are
  expected amounts; completed-event rewards and fines are observations in a
  bounded history of the last 32 outcomes, without modifying the credit balance.
  Delivery totals may include wing contributions and do not establish onboard
  cargo or mission completion. A full roster repairs membership after a journal
  gap, but earlier destinations and contract details then remain unknown until
  observed again. Up to 128 mission records are retained; larger or malformed
  snapshots leave the prior observations marked as requiring refresh. Passenger
  requirements reported on acceptance are retained; this is not a full passenger
  manifest or a mission-route optimizer.
- Topic `navigation` follows the game's plotted route by current system address,
  showing remaining stops, destination and geometric distance. Filtering applies
  before the five-stop output limit; progress counts still describe the whole
  remaining route. It identifies the next standard O/B/A/F/G/K/M primary star
  along that route, without assuming a fitted scoop or enough fuel to reach it.
  Selected targets that differ from the next plotted stop are explicit. Route
  changes, incomplete files, journal gaps and ambiguous positions withhold
  progress until the required observations arrive. Routes over 4,096 systems
  are rejected in full. Fuel and unladen maximum jump range retain separate
  dates; taxi, fighter and SRV readings are not presented as main-ship fuel.
  This follows an existing plot; it does not calculate a new route, fuel
  endurance, boost requirements or current jump feasibility.
- The MCP tool `elite_system_lookup` queries EDSM for system details
  or up to five stations in a named system. Station filters match names, types
  and service names such as `Refuel` or `Vista Genomics`. This is not yet a
  nearest-services search across multiple systems.
- `elite_nearby_services` searches up to eight nearby known populated systems
  for refuelling, repair, restock, cartographics, Vista Genomics, factors, traders,
  brokers, markets, shipyards or outfitting. It returns at most five candidates,
  with service dates and separate system/arrival distances. The radius is 1–100
  light years (default 20); permit-required/unknown-permit systems can be excluded.
  It reports checked and omitted systems, request failures and a time-budget stop.
  It excludes carriers and unknown/zero-population systems except the origin if
  returned. This is a bounded candidate search, not an exhaustive nearest-service
  finder or jump-route planner. Use station lookup to verify pads and access.
- `elite_station_lookup` uses Spansh's documented station endpoint for market,
  outfitting and shipyard observations. Get a market ID from telemetry or EDSM
  station lookup. Each dataset has its own observation date; retrieval time is
  not evidence of fresh prices. Filtered lists return at most five entries.
- `elite_trade_compare` compares two specified stations with explicit free cargo,
  credits, rebuy reserve and pad size. It refuses estimates with stale or unknown
  market dates, provider outages or unconfirmed compatible pads. It checks supply,
  demand and affordability and excludes rare and reported prohibited commodities.
  Results are alternative single-commodity loads, with conditional gross profit;
  permits, actual docking access, complete legality and arrival prices remain
  unverified. It is not a galaxy-wide trade search or jump-route planner.
- `elite_engineering_lookup` searches ship blueprint IDs, names and module names
  in Coriolis's public data. Specify grade 1-5 and 1-100 applications (default one).
  Up to five matching recipes include listed material costs, exact journal symbols
  from FDevIDs and engineers reported to support that grade. Costs cover those
  applications only; the tool does not infer a full grade climb or invent missing
  recipes, experimental effects, suit recipes, currency costs, prerequisites or
  fitted-module compatibility. Compare symbols with dated local material and
  engineer observations before giving shortage or spending advice. For example,
  `FSD_LongRange`, grade 5, applications 2 requests two applications at grade 5;
  it does not mean upgrading an unengineered FSD all the way to grade 5.
  Both repository revisions and dates are returned. A recent fetch is not proof
  that every entry reflects the current patch. Failed refreshes explicitly mark
  cached references stale; no-match results do not establish in-game absence.
- Public data is cached on disk for five minutes, with at most 32 responses of
  two MiB each. This survives Wingman's per-call stdio process. Cached fallback
  after an outage is explicitly marked stale. Requests are paced, bounded and
  time-limited; HTTP 429 imposes a persistent cooldown. Engineering references
  check upstream GitHub revisions at most hourly and cache files addressed by
  immutable commit IDs for a day. GitHub quota-exhaustion 403s also impose a
  cooldown. Engineering lookup has a 30-second request budget.

Raw journals and Frontier IDs are not uploaded by this extension. Using a cloud
conversation provider sends the returned summaries to that provider as ordinary
tool context. Public system/station lookup sends the requested system name to
EDSM and requested station IDs to Spansh. These implemented public endpoints
require no account/key. No commander budget or inventory is sent to either
provider; the trade calculation runs in the local MCP process.

## Setup

1. Set up Wingman Core/client using [the Windows development guide](develop-windows.md)
   or an installed compatible release. The small `.venv-elite` created during
   development runs the external MCP and tests; it is **not a full Core runtime**.
2. For source Core, the skill is in `skills/elite_dangerous`. For a release,
   copy that whole folder to
   `%APPDATA%\ShipBit\WingmanAI\custom_skills\elite_dangerous`.
   It uses only Python's standard library beyond Wingman's own classes and
   requires no bundled third-party packages. macOS/Linux can read an explicitly
   selected copied/mounted journal directory; native Elite gameplay there has
   not been validated.
3. The source checkout includes the **Elite Dangerous / Companion** profile.
   For release Core, create a separate Elite configuration and use
   `templates/configs/Elite Dangerous/Companion.template.yaml` as its
   `Companion.yaml`. Retain your normal provider/voice settings. The current
   2.1.1 migration snapshot contains the same additive profile; there are no new
   Core schema fields requiring a data migration.
4. With Python 3.11 available, create an isolated environment and install the MCP
   dependency (the environment already exists in this development checkout):

   ```powershell
   python -m venv .venv-elite
   .\.venv-elite\Scripts\python.exe -m pip install -r integrations/elite_dangerous/requirements.txt
   ```

5. Merge the one server in
   [`mcp.example.yaml`](../integrations/elite_dangerous/mcp.example.yaml) into the
   existing `servers` list in your Wingman `mcp.yaml`, or add those settings in
   the client's MCP configuration. Use absolute interpreter, script and cache
   paths. The usual Windows Core config location is
   `%APPDATA%\ShipBit\WingmanAI\2_1_1\configs`. Preserve existing servers and
   secrets. Enable `elite_public_data` for Companion.
6. Choose a supported conversation and voice provider. The researched candidate
   is Wingman Ultra for MCP access; actual subscription/client authentication
   remains to be tested. `wingman_websearch` in the profile uses Wingman's
   existing service when available. No additional paid AI service is currently
   required by this implementation.
7. Open Wingman using the [managed shortcut](audio-recovery.md), then select the
   enabled companion (including a renamed profile such as EliteDangerous-Copilot).
   Local monitoring starts automatically. Say **"Read my Elite Dangerous ship
   status"** to query current observations. The journal
   directory normally resolves from Windows Saved Games; override it in the UI
   if needed. The game's install directory is not its journal directory.

Try “What ship and cargo do I have?”, “Show my engineering materials containing
iron”, “Find refuelling candidates near my current system”, or “Which stations in
Sol have refuelling?” Sol requires a permit; the
lookup is an example, not a travel recommendation.

## Repeatable source configuration

For this source checkout, the setup command replaces the manual profile/MCP
merge in steps 3 and 5. First initialize Core's normal configuration directory
and install the integration requirements from step 4. Run from the repository
root using the MCP environment; that interpreter becomes the MCP command:

```powershell
.\.venv-elite\Scripts\python.exe -m integrations.elite_dangerous.setup prepare `
  --config-dir "$env:APPDATA/ShipBit/WingmanAI/2_1_1/configs" `
  --cache-dir '.elite-local/cache' `
  --output '.elite-local/setup-review'

# Review REVIEW.md, plan.json and both staged YAML files, then apply:
.\.venv-elite\Scripts\python.exe -m integrations.elite_dangerous.setup apply `
  --plan '.elite-local/setup-review/plan.json'
```

Use a new review directory each time. `--python` can select a different existing
MCP interpreter; dependency installation is a separate prerequisite. Paths are
derived from this checkout, so moving it requires a new preparation. The tool
recognizes both ordinary and default Elite configuration directories without
changing the selected/default configuration. Deleted or disabled profiles and
conflicting server names require resolution in the client first.

New Companion profiles use the shipped template and inherit normal Core provider
defaults. Existing prompts, controls, provider choices and skill overrides are
preserved; setup adds capability discovery entries and updates this integration's
MCP paths/reference metadata. Other MCP servers and explicit timeout/environment
settings are retained. Existing custom prompts are not rewritten from the latest
template. Repeat runs preserve original bytes when nothing needs to change.

Apply checks source/default/interpreter hashes, staged bytes and current target
contents. It backs up existing files in the review directory and writes each file
atomically. A subsequent write failure rolls back earlier writes only while their
bytes still match this operation; intervening user edits are preserved. This is
not a transaction across all files. Reports contain metadata; the staged YAML and
backups remain private local configuration. The tool never reads `secrets.yaml`.

Changed files load at the next user-initiated Core startup. This command does not
start/restart Core, copy release skills, install dependencies, log into an account,
generate game controls or verify gameplay. For release Core, follow the custom
skill instructions above and account for this fork's shared Core compatibility
fixes. Generate/install bindings using the separate controls command below.

## Run this fork locally without publishing

This repository contains Core, not the separate graphical client. No Git push,
installer build or code-signing credentials are needed to run the changed Python
source. Keep the small MCP environment and the full Core environment separate:

```powershell
# Run from the repository root with Python 3.11.
python -m venv .venv-core
.\.venv-core\Scripts\python.exe -m pip install -r requirements.txt
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools/start-core.ps1
```

The command permits this script only in the new PowerShell process; it does not
change the machine's persistent execution policy. The launch script binds to
`127.0.0.1:49111`, refuses an occupied port, and uses
Core's existing `--sidecar` option so account/provider credentials can be handled
through the client. It neither stops nor restarts an existing Core. Core writes
its normal configuration and logs under `%APPDATA%\ShipBit\WingmanAI\2_1_1`.
First startup may download local speech models. Dependency installation includes
large PyTorch and NVIDIA packages, as specified by the repository.

The API is available at `http://127.0.0.1:49111/docs` once startup finishes.
In this checkout, the complete dependency install and `pip check` succeeded.
The first source launch returned `{"state":"ready"}` from `/ping`; FasterWhisper
initialized on CUDA and PocketTTS loaded its fallback model. The Elite profile
was selected and its MCP server registered through the existing configuration
API. This verifies backend startup and configuration, not account-dependent
conversation, audible output, transcription accuracy or in-game control.
The [official Wingman download](https://www.wingman-ai.com/) provides the separate
graphical client and its account sign-in. Its public download link pointed to
the 2.1.1 client package when checked on 2026-09-27. Use the client with this
local Core; an installed bundled Core alone will not contain this fork's changes.
The exact client connection/startup behavior still needs acceptance testing.
Account credentials belong in the client, not in this repository or chat.

The downloaded 2.1.1 installer has been extracted to
`.elite-local/client/WingmanAI_2.1.1_x64-setup.exe`. Windows Authenticode reported
a valid ShipBit signature; the digest and signer metadata are recorded in
`.elite-local/verification/client-installer.json`. The installer has not been
run by this integration. Client installation and subscriber sign-in are deferred
at the user's request. The client normally starts its bundled Core, so verify
that the client is connected to the source process before accepting the test.
The current source process was PID 31648 on loopback port 49111 at inspection;
that PID is an observation, not a permanent setting.

The current CI release workflow also signs and publishes artifacts using
ShipBit's private credentials. Pushing a private fork does not supply those
credentials or build the graphical client. Local executable packaging is a
separate later step; the existing spec currently assumes a `venv` directory.

## Verified game controls

Use the [controls setup and recovery guide](elite-dangerous-controls.md) for the
`EliteDangerousControls` skill, physical-key injection, desired-state requests,
active preset discovery, controller-compatible supplemental bindings and backups.
The legacy `bindings`/`controls` exporters remain available for compatibility;
new installations should use `control_setup`. Existing generated commands need
the receipt-aware upgrade so they cannot bypass verification.

## Validation and remaining limits

Run a read-only preflight before the client/gameplay session:

```powershell
.\.venv-elite\Scripts\python.exe -m integrations.elite_dangerous.diagnostics `
  --profile "$env:APPDATA/ShipBit/WingmanAI/2_1_1/configs/Elite Dangerous/Companion.yaml" `
  --bindings "$env:LOCALAPPDATA/Frontier Developments/Elite Dangerous/Options/Bindings" `
  --presets 'C:/Games/Steam/steamapps/common/Elite Dangerous/Products/elite-dangerous-odyssey-64/ControlSchemes' `
  --output '.elite-local/verification/preflight.json'
```

This checks the on-disk commands against current bindings, recent journal
metadata, Core readiness, selected profile, whether Core reports a signed-in
account, startup-error count, and the configured skill/MCP visibility. It makes
only local GET requests, sends no input, does not invoke models or external
providers, and omits account names, commander IDs, raw configuration and journals
from the report. `public_data_connected: false` before login/activation is not by
itself a provider failure. No preflight result proves that the correct source
process owns the port, audio works, or game controls were delivered.

For the live acceptance session:

1. Confirm the listening process is this checkout's Core, select Elite Dangerous,
   and sign in through the official client. Verify the intended provider and
   microphone/output devices. Keep credentials in the client.
2. Ask for the ship/location in a fresh conversation. Check skill discovery and
   that the answer agrees with current journal observations or explicitly says
   the session is offline. Start the game and repeat to check refreshed context.
3. Ask for dated station/service information. Confirm the external MCP is
   discovered and the answer distinguishes retrieval time from observation age.
4. Speak a harmless information question, then check transcription and audible
   reply. Follow the controls guide for repeated ship light/night-vision state
   checks and mode-appropriate tests. Observe actual results in game. The preflight does not perform these actions.
5. Observe a new supported journal event after loading the companion and check a single
   timely announcement. Verify that old replay events are silent and unload
   stops monitoring. Record any failed step before declaring compatibility.

Run the synthetic tests with the isolated environment after installing the
minimal configuration dependencies from Wingman's `requirements.txt`
(`pydantic`, `fastapi`, `PyYAML`, `requests`, `platformdirs`, `packaging`) as well
as MCP:

```powershell
.\.venv-elite\Scripts\python.exe -m unittest discover -s tests -p 'test_elite*.py' -v
```

Tests exercise replay, partial writes, multipart journals, session changes,
freshness, shutdown, invalidated cargo, local market identity, mixed old/new
journal filename formats, route clearing, output bounds, provider
caching/outages/rate limits, price direction, trade constraints, active control
selection and generated command schemas, independently dated progression and
partial engineer updates, the actual Skill base and MCP protocol. Audio and
secret services are test doubles; these tests do not prove audible speech,
client discovery, subscription operation or in-game commands.

The progression checkpoint's full Elite suite run on 2026-09-27 discovered 198
tests: 197 passed and one opt-in live test was skipped. Source and test hashes
still matched that checkpoint during the documentation follow-up; the suite was
not repeated. A fresh read-only local replay was offline Live Odyssey 4.4.1.1,
with no warnings, no journal catch-up pending and no career, reputation or
engineer observations. Its 365-character summary did not imply zero progression.
Metadata-only evidence is in `.elite-local/verification/progression-replay.json`.
Client installation/sign-in and live gameplay acceptance remain deferred.

The shared default-config endpoint regression uses the complete Core environment:
`.\.venv-core\Scripts\python.exe -m unittest discover -s tests -p 'test_config_service.py' -v`.

The reader currently reconstructs the latest journal session, including its
parts. Missions that predate it may expose only startup roster fields, without
destinations or contract details. Materials and cargo reconcile the supported
transaction events above; unsupported cargo changes and ship-locker transactions
require dated full observations. Backpack
changes reconcile the supported Odyssey events described above. Engineer
progress is merged and blueprint material references are available, but
prerequisites and unlock routes are not yet a complete planner. Exploration is a
bounded catalogue of observations from the current system visit, not a complete
expedition log, valuation tool or biome strategy planner. Credit values are dated observations and must not
be assumed to include every subsequent transaction. Old commander-specific
sidecars are rejected using session timestamps.

In-game command acceptance, route planning, galaxy-wide market search, full inventory
transaction reconciliation, detailed engineering/exobiology strategy, carriers,
Powerplay and colonization need further implementation and acceptance testing.
The local game was shut down during the initial inspection. Source Core startup
now works; a logged-in client and gameplay acceptance session are still required
before calling this complete.

## Sources

Ship blueprint costs and engineer availability come from
[EDCD Coriolis data](https://github.com/EDCD/coriolis-data), joined to
[FDevIDs material symbols](https://github.com/EDCD/FDevIDs/blob/master/material.csv).
References are fetched into the private cache, not bundled into this fork.
Coriolis's [data attribution and licence](https://github.com/EDCD/coriolis-data/blob/master/LICENSE.md)
distinguishes Frontier-owned data from its MIT-licensed application code; this
integration does not relabel the data as MIT. The actual commit IDs appear in
each result, and the provider sends no journal inventory or player identifiers.

Contracts checked against [Frontier's journal manual](https://hosting.zaonce.net/community/journal/v31/Journal_Manual_v31.pdf),
[EDCD dashboard flag definitions](https://github.com/EDCD/EDMarketConnector/blob/main/edmc_data.py),
[EDSM system API](https://www.edsm.net/en/api-v1),
[EDSM station API](https://www.edsm.net/en/api-system-v1) and actual public
responses, and [Spansh's OpenAPI station contract](https://docs.spansh.co.uk/).
Control mappings come from the active local selector and game XML files, with
key names checked against Wingman's bundled input library. Subscription features were checked on
[Wingman's pricing page](https://www.wingman-ai.com/pricing). The research ledger
records other candidate providers and their limits.
