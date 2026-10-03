# Elite Dangerous integration: evidence and delivery plan

Status: implementation in progress; full compatibility is **not yet verified**.
Research checked 2026-09-27. This private fork should remain an ordinary Wingman
extension, with no Elite-specific changes to Core's public API or provider stack.

## Local evidence

- Clean Wingman checkout at the start of this work; Core reports version 2.1.1
  in `services/system_manager.py`.
- Game root: `C:\Games\Steam\steamapps\common\Elite Dangerous`.
- Installed product directory: `Products/elite-dangerous-odyssey-64`.
- Latest observed journal header: Live Odyssey, game version 4.4.1.1.
- Journal directory: `%USERPROFILE%\Saved Games\Frontier Developments\Elite Dangerous`.
  Observed Journal, Status, Cargo, and ShipLocker files. The observed journal ends
  with Shutdown. A file's existence does not establish that the pilot is in flight.
- No user Bindings directory was found at the usual Local AppData path on initial
  inspection. Installed ControlSchemes presets exist; none is proof of the user's
  active controls. Do not assume Star Citizen or default Elite keys.
  Later in this session the game created `StartPreset.4.start` and
  `Custom.4.2.binds`. The selector specifies KeyboardMouseOnly / Custom /
  KeyboardMouseOnly / KeyboardMouseOnly for general / ship / SRV / on-foot.
  The user confirmed keyboard and mouse. A staged generator now uses these files.
- No project virtual environment, Wingman installation under Program Files, or
  Wingman user data at the standard Roaming ShipBit path was found initially.
  Python on PATH is a WindowsApps alias; an Unreal Engine Python installation is
  available for isolated testing. Full Core setup remains to be verified.
- Personal identifiers, commander journal contents and account credentials should
  remain outside this repository. Tests must use synthetic journals.

## How Wingman is intended to be extended

`README.md`, `skills/README.md`, `skills/AGENTS.md`, and the implementation were
read before development. The existing Star Citizen suite consists of configured
characters, ordinary commands and domain providers, rather than a separate core.

| Existing extension point | Elite use |
| --- | --- |
| `templates/configs/_Star Citizen/Computer.template.yaml` | Model for a separate Elite pilot profile and personality |
| `skills/skill_base.py`, `@tool`, `prepare`, `unload` | Local journal reader, concise state tool, event speech |
| `Skill.get_prompt` | Small current-context summary when the skill is active |
| `services/skill_registry.py` and `capability_registry.py` | On-demand skill/MCP discovery |
| `services/mcp_client.py`, `McpServerConfig` | Independent external data tools; stdio or loopback HTTP |
| Wingman command configuration and command recorder | Commands derived from verified active Elite bindings |
| Existing voice/STT/TTS providers and HUD | Reuse configured voice, audio effects, and display behavior |
| Custom skill directory | Release installation without patching packaged Core |

The user approved the hybrid design: runtime skill plus MCP, no more than three
short runtime tools, bounded results, local event monitoring, and on-demand tool
activation. Skills are lazily prepared: on-demand activation must be reconciled
with monitoring startup explicitly, not assumed to mean background execution.

Important implementation finding: Wingman's stdio MCP tool path starts a **new
process per call** (`McpClient._call_tool_stdio`). In-memory caches and asynchronous
route-job state will not survive those calls. Use persistent bounded caches or a
loopback HTTP service for those features. External tool responses still use model
context tokens; MCP does not make tool output free.

Real-client verification also exposed two existing stdio bugs, now fixed with
small shared changes: Printr's stream wrapper did not expose `fileno()`, and
discovery retained anyio contexts that disconnect tried to close from another
task. Discovery now uses a scoped connection consistent with the existing
per-call tool design. Regression tests exercise subprocess descriptors and
discovery/call/disconnection across different tasks. No Core API changed.

## Sources and integration choices

| Resource | Intended use | Contract and limits |
| --- | --- | --- |
| [Frontier Player Journal manual](https://hosting.zaonce.net/community/journal/v31/Journal_Manual_v31.pdf) | Local authoritative player observations: location, ship, cargo, missions, materials, ranks, engineers, route and status | JSONL and companion JSON files; tolerate partial writes, missing fields, rotation, shutdown and multiple commanders. This manual is historical: newer events require updated evidence. |
| [EDCD EDMarketConnector](https://github.com/EDCD/EDMarketConnector) and [plugin contract](https://github.com/EDCD/EDMarketConnector/blob/main/PLUGINS.md) | Reference for current journal/CAPI handling; optional existing uploader | Keep Live and Legacy separate. Reuse EDMC for opt-in community uploads rather than silently uploading journals. |
| [EDSM API](https://www.edsm.net/en/api-v1), [system API](https://www.edsm.net/en/api-system-v1) | System coordinates, nearby systems, bodies, stations, factions | Direct public system and station lookups verified and implemented, including station `updateTime` fields. Other endpoints remain candidates. Documentation pages returned 403; the actual API worked. |
| [Spansh OpenAPI](https://docs.spansh.co.uk/) | Systems, bodies, station information and route/search integration where documented | Directly inspected embedded OpenAPI version 3.1.1: four documented paths, `/system/{id64}`, `/body/{id64}`, `/station/{marketId}`, `/dump/{id64}`. No route/search endpoint appeared in this schema. Do not invent those endpoints or present an untested website backend as a supported API. |
| [Inara developer guide](https://inara.cz/elite/inara-api-devguide/) and [API reference](https://inara.cz/elite/inara-api-docs/) | Commander synchronization if explicitly enabled; useful links to system/station/engineering pages | App registration/key requirements and request discipline apply. Do not equate website trade search with a public galaxy-market API. The documented deep links can be used without scraping. |
| [EDDN](https://github.com/EDCD/EDDN), [live developer docs](https://github.com/EDCD/EDDN/blob/live/docs/Developers.md) | Optional future ingestion; existing EDMC contribution recommended | A community event stream, not a historical query service. Running an independent whole-galaxy index has substantial storage and maintenance cost. EDDB is defunct. |
| [EDCD FDevIDs](https://github.com/EDCD/FDevIDs), [coriolis-data](https://github.com/EDCD/coriolis-data) | Identifier normalization and ship/engineering reference datasets | Pin versions and preserve applicable licenses before bundling. FDevIDs explicitly notes incomplete coverage. |
| [Frontier CAPI community documentation](https://github.com/EDCD/FDevIDs/tree/master/Frontier%20API) | Optional account data unavailable in the current journal | OAuth registration and token handling required. No game-password collection. Local journal support should not depend on CAPI. |
| [Official Elite news](https://www.elitedangerous.com/news), [Galnet](https://www.elitedangerous.com/galnet) | Patch-sensitive mechanics, narrative events, dated gameplay advice | Retrieve and cite current evidence; do not turn an old model answer into a current game fact. Feed/API contract remains to be verified. |

Community observations are incomplete and can be stale. Every data result needs a
source, retrieval time, source observation time when available, galaxy identity,
and uncertainty. A recent retrieval does not make an old station market fresh.
Unknown stock, pad access, permits or mechanics must remain unknown. For a trading
recommendation include cargo capacity, budget/rebuy reserve, pad size, distance,
supply/demand and observation ages before estimating profit.

## Subscription and runtime

[Wingman's current pricing](https://www.wingman-ai.com/pricing) places MCP in Ultra
and includes cloud AI/voice options. Ultra is the candidate fit for this hybrid
suite. No additional AI subscription is justified yet. A subscription does not
provide Elite telemetry or make community data real-time. The private fork's
client authentication, tool execution and voice path still require a real session
test. Retain the existing supported bring-your-own-provider path as a fallback;
do not bypass entitlement checks.

## Acceptance ledger (full objective remains open)

- [x] Inspect framework, extension guidance, game product and sample journal.
- [x] Choose extension architecture with user-approved token constraints.
- [x] Implement and test initial journal/status ingestion, session identity, freshness,
  partial writes, rotation, unavailable files and safe shutdown behavior.
- [x] Integrate a bounded telemetry tool and event speech through Wingman's actual
  Skill lifecycle; validate unload, config changes and speech throttling with
  mocked audio. Actual spoken playback and fresh-context conversation acceptance remain open.
- [ ] Verify and implement free external API providers with timeouts, caching,
  rate limits, provenance, no-result handling and outage behavior.
- [ ] Provide Elite profile, explicit setup, diagnostics, install/package path
  and migration snapshot synchronization where template configuration changes.
- [ ] Resolve active bindings and generate/test ordinary Wingman commands for
  ship, SRV and on-foot modes without hard-coded assumptions.
- [ ] Verify navigation, nearby services, trade/mining, outfitting, engineering,
  exploration/exobiology, missions, combat, faction/Powerplay, Odyssey, carriers
  and colonization workflows against their available evidence and constraints.
- [ ] Validate progression advice using the pilot's actual resources and goals;
  distinguish deterministic state from suggestions and externally sourced facts.
- [ ] Run Core/client with selected provider, test discovery and speech, then
  perform an in-game acceptance session with actual controls and current data.
- [ ] Audit all requirements; document any unsupported game/API surface without
  claiming universal compatibility from unit tests alone.

The local telemetry foundation, initial public data tools, profile wiring and
staged control generation are implemented. These are milestones, not a
replacement for the complete objective.

## Verification checkpoint, 2026-09-27

- Added `skills/elite_dangerous` (one on-demand tool, read-only journal projection,
  local monitoring, lifecycle speech adapter) and `integrations/elite_dangerous`
  (now four public-data MCP tools, persistent bounded cache and per-provider cooldown).
- Added an Elite Companion profile and its identical 2.1.1 template snapshot,
  an MCP configuration example, and a setup guide. No Core schema change or
  existing-user settings migration is needed for an additive profile. User
  settings have not been overwritten. The skill temporarily reuses Wingman's
  existing HUD icon; a distinct Elite icon is still desirable.
- `python -m unittest discover -s tests -p 'test_elite*.py' -v`: 50 discovered,
  49 passed, 1 intentionally skipped opt-in local/network test.
- Ran that opt-in test separately with `ELITE_LIVE_SMOKE=1`: passed. It read the
  real journal, connected through `McpClient`, queried Sol system and refuelling
  stations through the actual external MCP, queried Spansh station market data,
  exercised the trade comparison with an explicitly synthetic budget, and
  disconnected cleanly. Initial
  network results were cached and reused across subsequent subprocess calls.
  Non-personal evidence is in ignored `.elite-local/verification/results.json`.
- Real journal: Live Odyssey 4.4.1.1, session offline. This is an offline replay
  check, not evidence of in-flight behavior.
- Implemented Spansh station market/outfitting/shipyard sections and a bounded
  two-station trade comparison. Its documented `buy_price` is paid by the player;
  `sell_price` is received. Calculations enforce cargo, supply, demand, reserve,
  pad and age checks. Rare, ambiguous and reported prohibited entries are excluded.
  The observed sample market was older than the 24-hour default, demonstrating
  why retrieval time must not be substituted for observation time. No public
  routing/search contract was found in Spansh OpenAPI 3.1.1.
- Added port-bound local Market.json summaries, transaction invalidation, and
  date parsing that orders legacy and modern journal filenames correctly.
- Generated 29 ordinary commands from actual active controls into ignored
  `.elite-local/controls` (15 ship, 9 SRV, 5 on-foot); 14 unavailable mappings
  are explicitly reported. Unit tests cover separate mode selectors, preset
  versions, modifiers, mouse inputs, hold rejection, push-to-talk conflicts and
  invalid files. Input delivery, focus, layout and mode acceptance are untested.
- `git diff --check`: passed. Upstream Pydantic deprecation and MCP settings
  warnings remain in test output; they did not prevent these checks.
- Installed the complete repository requirements in ignored `.venv-core`;
  `pip check` reports no broken requirements. The same 50-test suite also passes
  there (49 passed, one opt-in test skipped). PowerShell marked redirected native
  stderr as an error record, but the unittest report itself ended `OK`.
- First source Core launch succeeded on loopback port 49111. `/ping` returned
  `ready`; FasterWhisper initialized on CUDA and PocketTTS loaded its fallback
  model. Registered `elite_public_data` and selected Elite Dangerous through
  existing Core APIs. Non-personal evidence: `.elite-local/verification/core-runtime.json`.
  No Core API changes, process restart, executable build or Git push was needed.
- The user has not yet installed/run the graphical client or signed in. Core
  correctly skips Tower initialization pending login. Client connection,
  subscription, conversation and actual in-game voice/controls remain unverified.
- Added `tools/start-core.ps1` for subsequent user-controlled local launches.
  It uses a separate full Core environment and refuses an occupied port. Windows
  restricts script execution here, so the documented invocation permits the
  checked-in script for that process only. The official download currently links
  a 2.1.1 client package; client UI is not built by this source repository.
- Named configuration read `/config?config_name=Elite%20Dangerous` returned
  Companion and `/startup-errors` was empty. An unnamed `/config` request exposed
  a pre-existing `UnboundLocalError` in `ConfigService.get_config`: its optional
  argument leaves `config_dir` uninitialized. Use the named request for now;
  this separate Core issue remains recorded for follow-up. It did not stop the
  server or prevent profile selection.

Next: extend navigation and progression support, reconcile inventories and
progression events, validate generated controls, and package/install the integration for a real
Core/client gameplay session. Maintain the full acceptance ledger above.

## Resource tracking checkpoint

- Added atomic engineering-material transactions against known category snapshots.
  Symbol/category aliases are normalized; duplicate snapshots, underflow, missing
  categories and malformed journal gaps require refreshed observations. Conversion
  previews do not consume materials. Mission rewards update inventory as well as
  the mission list. Legacy mixed broker ingredients remain explicitly unsupported.
- Merged engineer updates by ID without refreshing unrelated engineer dates.
- Added `planning` within the existing single runtime tool: independently dated
  credit, ship rebuy, capacity and cargo observations, with derived free space.
  Ship changes, loadout changes and known cargo mutations prevent reuse of
  invalidated inputs. An older dashboard cannot repair a known later cargo change.
- This is not a complete credit transaction ledger. A LoadGame balance is
  historical; a newer Status balance is used only when actually present. The
  real local Status file at inspection contained only timestamp/event/Flags,
  so the existence of a current Balance field was not established for this session.
- Cargo and Odyssey inventory deltas, engineer prerequisite reference data,
  navigation and the remaining gameplay workflows still need further work.
- Verification: 68 Elite tests discovered, 67 passed and the opt-in network test
  skipped. The actual Skill loader/schema and MCP regression checks remain in
  this suite. A fresh local replay completed without warnings; the latest file
  was offline and contained no resource observations, so it correctly supplied
  no balances or material quantities. This does not validate transactions during
  actual gameplay. Metadata only: `.elite-local/verification/resource-replay.json`.
- These changes preserve the one-tool, on-demand runtime design and do not alter
  Core's API. Template and 2.1.1 migration snapshot are synchronized. The existing
  user's copied profile still needs the new planning instructions merged during
  final installation/profile refresh; no running Core was restarted.

## Nearby services checkpoint

- Verified the documented EDSM `/api-v1/sphere-systems` endpoint against a real
  Sol query. The returned catalogue included zero-distance placeholder-like
  entries; only known populated systems and the returned origin are searched.
  This restriction is explicitly reported, not treated as exhaustive coverage.
  Contract: [EDSM systems API](https://www.edsm.net/pt/api-v1).
- Added `elite_nearby_services`, the fourth external MCP tool. It checks at most
  eight eligible systems within 1–100 ly, has a 24-second soft search budget and
  returns five service candidates. It reports source dates, provider failures,
  cache fallback, permit flags, unchecked systems and separate ly/ls distances.
  Carrier locations, pad suitability and actual docking access require other
  evidence. The server configuration now allows 45 seconds per call.
- Added tests for service matching, population/permit policy, identity mismatch,
  duplicate market IDs, unknown dates, partial/outage results, result bounds and
  deadline behavior. Full suite: 80 discovered, 79 passed, one opt-in test skipped.
  The opt-in real Wingman MCP/network test also passed separately, including a
  5-ly refuelling search around Sol. Evidence remains in ignored
  `.elite-local/verification/results.json`.
- Merged the new nearby-search and prior planning instructions into the existing
  local Companion profile, preserving other settings and saving an ignored
  backup. Registered the updated MCP settings and reloaded the profile using
  existing Core APIs. No process restart or API changes. Evidence:
  `.elite-local/verification/navigation-install.json`.
- Researched [EDData's published API](https://github.com/EDDataAPI/eddata-api/blob/main/API_OVERVIEW.md)
  as a candidate for direct nearest-service and wider market search. Both its
  public health and endpoint-catalogue requests timed out during this check, so
  it is not an implemented dependency. Its documentation also describes HTTP-200
  error payloads and price semantics that would require separate validation;
  do not reuse Spansh price assumptions for it.
- Exhaustive nearest-service search, multi-jump routing, engineering prerequisites,
  remaining gameplay workflows and real client/game acceptance remain open.

## Odyssey observation checkpoint

- Added `elite_status` topic `odyssey` within the existing single runtime tool.
  It reads equipped suit/weapon observations, backpack and ship-locker snapshots,
  and dashboard fields. Full inventory snapshots validate quantities and distinct
  ownership/mission stacks; owner identifiers are stripped before query filtering
  and model output. Missing categories are unknown rather than empty.
- BackpackChange is the sole delta source, avoiding duplicate debits from
  UseConsumable/CollectItems/DropItems. Locker purchases, sales, trades and equipment
  upgrades invalidate dated locker contents until the authoritative snapshot arrives.
  Snapshot markers permit a same-second file refresh; an unmarked same-second
  snapshot/change ambiguity requires a newer observation. Death, malformed records,
  out-of-order timestamps and unknown stack removals cannot silently restore counts.
- Event contracts were checked against the
  [Frontier journal manual](https://hosting.zaonce.net/community/journal/v31/Journal_Manual_v31.pdf)
  and current [EDCD journal consumer](https://github.com/EDCD/EDMarketConnector/blob/main/monitor.py).
  These were used as protocol references; no EDCD implementation was copied.
  Fileheader now accepts the documented lowercase `odyssey` field as well.
- Verification: 90 tests discovered, 89 passed and the opt-in live test skipped.
  Ten new synthetic sequence tests cover identity, atomic updates, duplicate-action
  prevention, invalidation/recovery, sidecar timing, equipped-loadout semantics,
  privacy and result bounds. The source Core still answers `/ping` with `ready`.
  This is not a live Odyssey gameplay or voice acceptance test. No Core restart,
  API changes or game-input injection was performed.
- Upgrade recipes/prerequisites, a complete locker transaction ledger and the
  other open acceptance items above remain outside this checkpoint.

## Native command installation checkpoint

- Added `integrations.elite_dangerous.controls` to prepare and apply binding-derived
  commands to an existing Wingman profile. Preparation leaves the installed profile
  untouched. Apply rechecks source files, preset selection (including newly added
  custom preset versions), staged content and destination hashes before writing.
- The merge preserves other settings and user commands, rejects name/phrase
  conflicts and checks named keyboard/mouse push-to-talk conflicts. Numeric
  scan-code PTT and compound chords require manual conflict verification. A receipt
  tracks owned commands so regeneration can replace changed mappings and remove
  unbound ones without overwriting user-edited commands. Original bytes are backed
  up; failure writing the second file rolls back the first if it has not since
  been changed externally. Writes are atomic per file, not a cross-file transaction.
- Installed 29 commands from this machine's current bindings: 15 ship, 9 SRV,
  5 on-foot. Fourteen unavailable mappings remain omitted. Reloaded Companion using
  the existing `/config` API and verified every installed command name appeared
  in Core's loaded profile. Other settings and the binding-derived actions were
  checked against the original profile and a fresh generator run. No input was
  sent, no game settings changed and no Core restart occurred. Backup and evidence:
  `.elite-local/controls-install/backup/`,
  `.elite-local/verification/controls-install.json`.
- Verification: 100 tests discovered, 99 passed, one opt-in live test skipped.
  Ten installer tests cover conflict rejection, setting preservation, changed
  inputs, new preset versions, owned-command updates, edited-command protection,
  PTT conflicts, tampered staging files, backup and rollback. Runtime voice and
  in-game input acceptance still require the client/account/game session.

## Client preparation and preflight checkpoint

- Revalidated the live source listener: Python Core PID 31648 owns loopback port
  49111 and `/ping` reports `ready`. No process was stopped or restarted.
- Found `WingmanAICoreClient-2.1.1-Installer.zip` in Downloads and extracted only
  its named installer into ignored `.elite-local/client/`. Authenticode status was
  `Valid`, signed by ShipBit UG. SHA-256:
  `23E849A60ED7E2AF0D47E83A5353805945F551AC193A872004F7CA834415DA34`.
  Metadata is in `.elite-local/verification/client-installer.json`. This verifies
  the local signature, not a published checksum comparison. No installer ran.
- The user explicitly deferred client installation and subscriber sign-in.
  Full voice, authenticated providers and gameplay acceptance remain pending;
  this does not pause independent implementation work. The
  [upstream installation guidance](https://github.com/ShipBit/wingman-ai#installing-wingman-ai)
  says the client auto-starts its bundled Core. Exact client behavior when this
  source listener is already present remains unverified; do not infer successful
  connection merely from the GUI launching.
- Added a read-only `diagnostics` CLI with bounded local HTTP responses and a
  metadata-only report. The real run confirms 29 matching configured commands,
  14 omitted mappings, selected Elite profile, registered/enabled public-data MCP,
  and available/enabled Elite skill. Core reports no signed-in account; MCP is not
  connected. Latest journal is offline Live Odyssey with no location observation
  and no ingestion warnings. Evidence: `.elite-local/verification/preflight.json`.
- The first skill-list request exceeded the diagnostic's 2-MiB cap because Core
  embeds all skill icons in the roughly 4.7-MB response. A bounded 16-MiB read now
  accommodates it; only availability flags enter the saved report.
- Fixed an existing `ConfigService.get_config` unbound-variable error for omitted
  or empty profile names. It now reads the selected config; explicit named reads
  preserve the current selection. Two real FastAPI endpoint regression tests pass
  in `.venv-core`. No interface/schema changes. The running process still has the
  old implementation until a user-initiated restart; named reads work meanwhile.
- Elite regression suite: 104 discovered, 103 passed, one opt-in live test skipped.
  Four new diagnostic tests cover privacy, unavailable Core, stale bindings,
  missing account state and malformed responses without claiming voice/gameplay
  success. The two separate Core endpoint tests also pass.

## Engineering reference checkpoint

- Added the fifth external MCP tool, `elite_engineering_lookup`. Runtime skill
  schema count remains one. The tool searches up to five ship blueprint recipes
  at an explicit grade and calculates listed material costs for 1-100 explicit
  applications. It joins display names to journal symbols through FDevIDs instead
  of guessing names. For example, Datamined Wake Exceptions maps to `dataminedwake`.
  Engineer support is reference availability, not proof of this pilot's access.
- Read the Coriolis data licence before integration. Its JSON data attribution is
  distinct from its application-code MIT licence. No upstream reference datasets
  are vendored. Public files are fetched into the existing bounded private cache.
  Fixed EDCD repository endpoints supply revision metadata (hourly cache) and
  immutable-revision JSON/CSV files (one-day cache). Requests use existing pacing,
  deadlines and cooldowns, including GitHub's quota-exhaustion 403 response.
- Verified against public Coriolis revision
  `0db9234b5b9ce8c939ea84133d7ce336eea88e27` (2026-04-24) and FDevIDs revision
  `c35612952dd6a547d1a7ac4cffab9c7051e86579` (2026-09-05). These dates establish
  reference versions, not completeness for the latest game patch. Reference
  updates are checked automatically; stale fallback and missing costs stay explicit.
- The opt-in live Wingman MCP test passed, discovered five tools, and checked
  an FSD increased-range grade-5 recipe with two explicitly requested applications.
  The test also exercised the prior EDSM/Spansh tools and clean disconnection.
  Metadata/reference evidence: `.elite-local/verification/results.json`.
- Synthetic regression: 114 discovered, 113 passed, one opt-in test skipped.
  New checks cover symbolic identity, ambiguous mappings, missing/invalid costs,
  result bounds, exact-ID versus keyword search, unavailable/stale references,
  invalid/future revisions, cached CSV parsing and persistent GitHub cooldowns.
- Profile/template and current migration snapshot contain engineering-use
  instructions. Merged those instructions and the MCP discovery metadata into
  the local profile, preserving 29 controls and backing up both configuration
  files. Existing APIs reloaded the profile without restarting Core. Evidence:
  `.elite-local/verification/engineering-install.json`.
- Full grade-climb estimates, experimental/suit recipes, new currency costs,
  unlock prerequisites and fitted-module compatibility still need additional
  evidence and implementation. Missing entries are never interpreted as free
  upgrades or proof that an upgrade does not exist.

## Exploration observation checkpoint

- Replaced the single latest exploration event with a bounded current-system
  catalogue. Body scans, mapping completion, surface signals and organic records
  retain their own observation dates. Up to 512 bodies and 32 organic entries per
  body are retained; filtered summaries stay within 6,000 characters and expose
  omitted counts. Large summaries preserve list structure and individual dates.
- Checked event contracts against
  [Frontier's journal manual](https://hosting.zaonce.net/community/journal/v31/Journal_Manual_v31.pdf):
  organic events identify the body with `Body`, while mapping events use `BodyID`.
  Only `ScanType: Analyse` establishes observed organic analysis. Repeated samples
  do not imply completion. Historical analysis does not establish unsold data,
  retained samples, first-footfall bonuses or payout. Player discoverer/mapper
  names are excluded from the catalogue.
- Supercruise travel preserves the catalogue; hyperspace departure and system
  changes clear it. Unknown systems, conflicting identities, invalid values and
  older observations cannot overwrite trusted records. Discovery counts do not
  imply complete body coverage. Journal gaps remain explicit after later scans.
- Ten exploration tests cover independent dates, organic phases, travel and
  commander boundaries, malformed observations, bounded/filterable catalogues,
  journal gaps and large-output truncation. Elite regression suite: 124 discovered,
  123 passed, one opt-in live test skipped. Four actual skill-loader checks also
  passed. No runtime tool or Core API schema was added.
- The real journal replay remains offline, Live Odyssey 4.4.1.1, with no ingestion
  warnings and no exploration observations. Metadata-only evidence is saved in
  `.elite-local/verification/exploration-replay.json`. Client installation and
  subscriber sign-in are deferred by the user; live exploration and spoken
  interaction remain unverified. No Core restart occurred.

## Plotted route and fuel checkpoint

- Navigation now matches the observed system address against the full plotted
  route before limiting output. It reports remaining stops, destination and
  geometric distances, with an explicit mismatch when the selected target is
  different. Repeated system addresses or an absent current system leave progress
  unknown. During hyperspace, arrival position is unconfirmed; supercruise keeps
  route progress. A next-target event recorded during a jump survives arrival.
- Consulted the [Frontier journal manual](https://hosting.zaonce.net/community/journal/v31/Journal_Manual_v31.pdf)
  for target event ordering, dashboard fuel and vessel flags. Its old `Route.json`
  example predates the released format; used the corrected `NavRoute.json` example
  and clear-event notes in [EDCD's plugin contract](https://github.com/EDCD/EDMarketConnector/blob/main/PLUGINS.md).
  The same EDCD reference identifies loadout `MaxJumpRange` as unladen range.
  Standard O/B/A/F/G/K/M scoop classes are corroborated by
  [Frontier's Fuel Rats spotlight](https://community.elitedangerous.com/en/node/338).
  Only exact standard classes produce the upcoming-star hint; missing hints do
  not prove the absence of other refuelling opportunities or secondary stars.
- Added bounded, atomic route validation (maximum 4,096 systems). Clear events
  cannot resurrect older plots, partial/malformed files invalidate progress, and
  a same-second replot cannot reuse an unchanged old file as proof of the new
  plot. Future timestamps cannot prevent recovery from a later valid snapshot.
  Journal gaps invalidate both route and location. New route and location
  observations are required to restore progress after that uncertainty.
- Fuel and unladen range retain separate dates. Main-ship fuel excludes known
  taxi, multicrew, fighter and SRV contexts and readings older than observed ship
  changes. No fuel-consumption model, current-range calculation, route generation,
  boost plan or reachability guarantee is implied by plotted geometric distances.
  Runtime tool count remains one and output remains capped at 6,000 characters.
- Fifteen new route tests cover progression beyond the output cap, target ordering,
  file races, clear/replot handling, malformed coordinates, route bounds, fuel
  provenance, vessel changes and journal gaps. Full Elite suite: 139 discovered,
  138 passed, one opt-in live test skipped. Real local replay remains offline Live
  Odyssey 4.4.1.1 with no ingestion warnings, route or fuel/range observations.
  Metadata-only evidence: `.elite-local/verification/route-replay.json`.
  Client/gameplay acceptance remains pending; Core was not restarted.

## Mission briefing checkpoint

- Expanded the existing `missions` topic with individually dated contracts,
  redirects, deadlines and cargo-depot observations. Missions are ordered by
  known expiry before the five-item cap; query filtering still happens before
  truncation. The runtime still exposes one tool and caps responses at 6,000
  characters. No model polling or Core API changes were introduced.
- Checked [Frontier's journal contract](https://hosting.zaonce.net/community/journal/v31/Journal_Manual_v31.pdf)
  for `Missions`, acceptance, redirection, completion/failure and `CargoDepot`.
  Snapshot `Expires` values are relative to the event time; positive values
  establish a derived deadline. Zero/negative values do not establish a future
  deadline. An elapsed deadline does not prove failure. `Complete` roster entries
  do not establish payment. Accepted rewards remain expected amounts, separate
  from completed-event reward observations and from cash on hand.
- Depot briefing uses delivered and required totals. Journal `Progress` represents
  goods in transit, so it is not used as completion percentage. Wing updates do
  not invalidate the pilot's cargo snapshot; personal collection/delivery does.
  Reaching the delivery total does not manufacture a completion event.
- Roster updates are atomic and bounded to 128 records, with up to 32 recent
  outcomes. Missing arrays, duplicate IDs, malformed values, impossible depot
  totals, older events and future timestamps cannot replace trusted observations.
  Journal gaps remain explicit through subsequent deltas. A complete roster
  restores membership but discards unconfirmed pre-gap contract/destination data.
  Commander changes clear both missions and outcome history.
- Fifteen new mission tests cover deadlines, redirects, reward separation, depot
  semantics, gaps, bounded output, terminal states and invalid data. Full Elite
  suite: 154 discovered, 153 passed, one opt-in live test skipped. Existing material
  reward reconciliation and actual skill activation/unload checks also pass.
- Real journal replay remains offline Live Odyssey 4.4.1.1 with no ingestion
  warnings, mission roster or mission observations. Metadata-only evidence:
  `.elite-local/verification/mission-replay.json`. Live mission dialogue remains
  pending client/account/gameplay acceptance. Full passenger manifests, objective
  progress for every mission type and mission-route optimization remain unfinished.

## Reproducible source configuration checkpoint

- Added `python -m integrations.elite_dangerous.setup prepare/apply`. It stages
  native Companion and MCP configuration using this checkout's paths, then checks
  source/default/interpreter hashes, staged contents and destination bytes before
  applying. Backups retain original bytes; writes are atomic per file and rollback
  preserves intervening user edits. It does not start/restart Core or use accounts.
- New profiles use the shipped template and Core's provider defaults. Existing
  prompts, controls, provider settings and skill overrides are preserved. Omitted
  MCP discovery lists retain Core's inherited defaults before Elite is added.
  Other MCP servers and explicit environment/timeout settings remain intact.
  Setup recognizes `_Elite Dangerous` without changing the default profile,
  refuses deleted/disabled profiles and ambiguous/conflicting configurations,
  and preserves equivalent path spellings to avoid unnecessary rewrites.
- Added the repository's pinned PyYAML version to the small integration
  requirements, since native configuration and binding tools need it. Confirmed
  PyYAML 6.0.3 is already installed in this machine's MCP environment. Interpreter
  paths retain virtualenv symlinks; dependency availability is still a separate
  setup prerequisite, not inferred from an executable file's existence.
- Fourteen setup tests cover fresh install, preservation, default directories,
  repeated no-op runs, conflicts, staging/source/default drift, mid-preparation
  edits, target-path restrictions and rollback. Full Elite suite: 168 discovered,
  167 passed, one opt-in live test skipped.
- Staged the real configuration in `.elite-local/source-setup-verified/` without
  writing installed settings. Both the new template and existing staged Companion
  passed Core's actual `ConfigManager.merge_configs` in the full Core environment.
  Existing Companion retains 29 configured controls; native inheritance produces
  30 total commands. Elite skill/MCP discovery and MCP registration validate.
  The final plan has zero changed files, so no configuration apply is needed on
  this machine. Evidence: `.elite-local/verification/source-setup.json`.
- Documented the repeatable setup workflow. Existing custom prompts are preserved,
  not upgraded automatically. Release skill copying, executable packaging,
  client authentication and live gameplay acceptance remain separate work.

## Cargo reconciliation checkpoint

- Added atomic cargo reconciliation for market and limpet purchases/sales,
  scooping, ejection and refining. Full snapshots validate vessel, canonical
  commodity/mission identity, counts, stolen subcounts and any reported total.
  A total can be derived from a complete inventory when the event omits it.
  Mission cargo remains separate from ordinary trade stock. Missing stolen
  quantities remain unknown; ownership is not a claim about local legality.
- Contracts checked against [Frontier's journal manual](https://hosting.zaonce.net/community/journal/v31/Journal_Manual_v31.pdf)
  and the [EDCD journal consumer](https://github.com/EDCD/EDMarketConnector/blob/main/monitor.py).
  Collection/refining supply a single unit when no explicit count is present.
  Purchases/sales/ejection require explicit positive counts. A partial removal
  from a mixed stolen/clean stack needs enough ownership information; otherwise
  the prior inventory is preserved and marked as requiring refresh. No underflow
  is clamped to zero and no missing baseline is treated as an empty hold.
- Reconciled totals feed the existing free-cargo calculation. Ship transactions
  cannot alter an SRV inventory, and vessel switches require a new observation.
  Transfers, limpet launch, synthesis, mission-bound cargo disposition and other
  unsupported changes await full snapshots. Taxi/on-foot/multicrew dashboard
  readings are excluded from main-ship hold-space estimates.
- Cargo marker events now await their snapshot file. Same-second snapshot/delta
  ambiguity cannot double-apply a transaction, and unchanged same-second files
  cannot repair an uncertain sequence. Cargo sidecars are skipped while journal
  batches are catching up. Partial files, invalid/future timestamps, duplicate
  identities and oversized inventories preserve prior data with explicit limits.
- Seventeen new cargo tests cover transaction counts, mission/ownership identity,
  vessel changes, resource planning, underflow, malformed data, file ordering,
  output bounds and filtering. Existing planning fixtures now contain complete,
  internally consistent inventories; unsupported transfer events retain coverage
  of invalidation behavior. Full Elite suite: 185 discovered, 184 passed, one
  opt-in live test skipped. Runtime tool count remains one.
- Real local replay remains offline Live Odyssey 4.4.1.1 with no ingestion warnings
  and no cargo observation; missing inventory is not reported as an empty hold.
  Metadata evidence: `.elite-local/verification/cargo-replay.json`. Live trading,
  input delivery and authenticated voice interaction still need acceptance testing.
  No Core restart or installed configuration change occurred.

## Progression checkpoint, 2026-09-27

- Reviewed the implemented career and engineer handling against the saved
  contract research: [Frontier's journal manual](https://hosting.zaonce.net/community/journal/v31/Journal_Manual_v31.pdf)
  and the [EDCD journal consumer](https://github.com/EDCD/EDMarketConnector/blob/main/monitor.py).
  No new provider research or network probes were needed for this local change.
- Career summaries combine ranks and percentages by category. Every rank,
  percentage and superpower reputation metric retains its own observation date;
  partial promotions leave other categories unchanged. Rank changes and first
  rank observations invalidate older percentages without inventing zero. Unknown
  rank context stays explicit. Raw numeric rank levels remain available without
  guessed labels. Military percentages above 100 retain their reported value and
  cap only the display value; they do not establish promotion, permits, ship
  access or completed unlocks.
- Career updates validate all reported fields before merging. Invalid, future or
  out-of-order observations preserve history with refresh flags. After journal
  gaps, reobserving one metric does not refresh the others. Engineer updates
  accept partial fields without `Progress`, preserve independent field dates,
  clear stale percentages on grade changes and clear earlier grades on reported
  non-`Unlocked` transitions. A positive grade without a state drops a stale
  non-`Unlocked` state without inferring its replacement. Partial engineer updates
  cannot repair a block invalidated by malformed data or a journal gap.
- Thirteen progression tests cover partial updates, dates, rank transitions,
  percentages above 100, unknown rank levels, atomic rejection, future/older
  events, gaps, engineer state changes, output bounds/filtering and commander
  reset. The saved full run discovered 198 tests: 197 passed, one opt-in live test
  skipped. During this follow-up, all 43 source/test/config/tool files recorded in
  the checkpoint matched their saved SHA256 hashes; no implementation changed
  and the suite was not repeated. Runtime tool count remains one. Existing prompt
  provenance guidance and the career summary's explicit scope are sufficient;
  no additional prompt instruction or schema change was needed.
- Fresh read-only local replay was offline Live Odyssey 4.4.1.1, with no warnings
  or catch-up pending, and no pilot, rank, percentage, reputation, engineer or
  Powerplay blocks. The progression summary was 365 characters. Metadata-only
  evidence: `.elite-local/verification/progression-replay.json`; replay helper:
  `.elite-local/verify-progression.py`. No raw journal or player values were
  exported. Missing progression is unknown, not zero.
- Progression documentation and replay checkpoint complete. The acceptance ledger
  remains open: client installation/sign-in was explicitly deferred, and live
  voice, controls and advice against actual pilot resources still need acceptance.
  Whitespace checks passed for tracked changes and the new documentation/replay
  helper. No Core restart or installed configuration change occurred.

## Live command and narration fixes, 2026-09-27

- Live testing reached the source Core, authenticated conversation, audible replies
  and a successful `elite_status` call. The active profile is now
  `EliteDangerous-Copilot`; its telemetry skill had to be enabled after the rename/
  copy. Local journal metadata confirmed recent system and ship observations.
- The transcribed light request ended in a period, which missed the original
  exact shortcut. All 29 generated controls also had `force_instant_activation`
  enabled, excluding them from Core's native `execute_command` schema. Generation
  now exposes those controls to the native tool and includes exact period and
  exclamation-mark variants. No new input executor, remote server or skill tool
  was added. Commands still require game focus and the corresponding vehicle mode.
- The journal contained the user's fresh docking event after skill activation,
  but the monitor belonged to the temporary voice-request loop. It now starts on
  Core's persistent audio loop and cancels/awaits cleanup on that same loop.
  Status queries also route fresh events through narration, preventing them from
  consuming events silently. Silent initial replay, the 15-second freshness
  window, 30-second cooldown and busy-audio suppression are retained.
- Added regressions for activation on a voice thread whose loop closes, subsequent
  docking narration and cross-loop unload, status-query event consumption, and
  migration of copied legacy controls without adopting modified actions. Full
  Elite suite: 202 discovered, 201 passed, one opt-in live test skipped. Two further
  full-Core tests verify the actual native command schema and exact punctuation
  matching, with keyboard execution mocked (`tests/test_command_exposure.py`).
- Applied the reviewed 29-control update to the current Copilot and saved it
  through Core's native API. Only commands changed in the effective profile;
  input actions, providers, prompts and other settings were preserved. Backups
  and a new receipt accompany the renamed profile. Metadata:
  `.elite-local/verification/native-controls-install.json`. No game input was sent.
- The running Python process retains its previously imported skill module.
  A user-initiated Core restart is required to load the narration fix, followed
  by skill activation and real control/docking retests. Those acceptance steps
  are not established by the regression tests or configuration readback.

## Control and configuration regression repair, 2026-09-28

- The restarted Core received `action="turn on ship lights"`, but the control
  parser only recognized short action names. Both failed attempts logged zero
  input events. The tool now advertises a bounded action enum and accepts explicit
  compatibility phrases while preserving on/off intent. Conflicting, negated or
  compound instructions fail without input. Actual logged arguments are covered
  through runtime and decorated-tool dispatch tests.
- Template copying ignored an existing default-prefixed configuration directory,
  recreating removed profiles and another template default. Startup now repairs
  duplicate identities with backups and reuses the canonical directory and
  deletion markers. Real-directory tests cover repeated startup, selection/load
  endpoints, frozen migration paths, collision refusal and rollback.
- Local repair retained the customized Copilot YAML byte-for-byte, archived exact
  template clones, and reduced the live API list to one Elite Dangerous entry and
  one default. Three friendly presets were installed and matching selections
  updated while Elite was closed. Every preset element and attribute other than
  its name matched the latest game-saved source, including minor-version upgrades.
  Original preset files and selector backups remain available.
- Readiness after migration: 42 of 43 actions configured. Ship lights resolve to
  Insert and ship night vision to numpad subtract. SRV drive assist is configured
  as hold; this setting is preserved and affects only that action. Evidence is in
  `.elite-local/control-repair-validation.json`,
  `.elite-local/configuration-repair-result.json`, and the naming migration receipt
  under `.elite-local/friendly-presets-repair-v2/`.
- Automated validation: 252 Elite tests (251 passed, one opt-in skipped), 12
  configuration tests and four native-command tests passed. The preset setup tests
  were rerun after adding compatibility for newer minor-version files saved by
  Elite. No game input was sent during automated verification.
- Acceptance remains open for the user-operated Core restart, visible Load-menu
  selection and live lights/night-vision confirmation. Correct configuration API
  identities do not establish that the dropdown rendering issue is fixed. No
  client reinstall or unconditional reliability claim is justified.
