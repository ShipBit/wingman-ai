# Personal ERP for Star Citizen

Simple and Advanced are views of the same personal records. Switching preserves history.

| Simple | Advanced adds |
| --- | --- |
| Overview, operations, money, cargo, assets and attention | Production, planning, financial reports, evidence and cross-period history |
| Purchases, sales, transfers, costs and wallet reconciliation | Inventory costing, production inputs and outputs, cash/profit separation, forecasts and reversible corrections |

This is personal bookkeeping. Shared organisations, external market prices and automatic game actions are outside this release.

## Install in Wingman AI

1. Fully close Wingman AI, including its tray process.
2. Extract the entire ZIP and run `sc_accountant/install.bat` as your normal user.
3. Restart Wingman and enable **Star Citizen Personal ERP** in your profile.
4. Enable and configure **SC Log Reader 0.5.0 or newer** in the same profile.
5. Leave Accountant's **SC_LogReader database** blank. It finds the reader's
   Runtime Directory automatically and captures every 15 seconds by default.
6. About 15 seconds after loading, the dashboard card appears in Wingman chat.
   Click its computer link or scan the QR with a phone on the same network.
   You can also ask Wingman to open your accounting dashboard.

Accountant activates automatically when enabled. It waits and retries if the
reader starts later. No manually copied database or Python setup is needed.
If an existing profile explicitly overrides automatic activation, turn it on
there. Without a configured reader, manual bookkeeping remains available.

The startup card matches NavPoint: a three-line message, the computer's
`127.0.0.1` link, and a black-and-white QR attachment. The QR contains the phone
address and a session access key; no login entry is needed. Other network clients
cannot read or change the books without that session. A restarted skill issues a
new key, so scan the new card after restarting. Treat the QR as access to your
dashboard. If no local network address is available, the card offers the computer
link only. The optional standalone launcher remains local-only by default.

## Optional standalone use with a separate data folder

From the repository root:

    python -m skills.sc_accountant.erp_launcher --data-dir "D:\SC-ERP-data"

The dashboard opens locally. Stop with Ctrl+C. Add --no-browser for headless use, --port 7864 for another port, or --reader-db "D:\path\events.sqlite3" for capture. --mode advanced explicitly changes the view; omitting it preserves the saved selection. FastAPI and uvicorn are already Wingman dependencies. From an extracted portable skill folder, run python erp_launcher.py with the same options.

Records live in erp.sqlite3. Keep that database separate from the reader database. Stop the application before copying the data directory for backup. Run only one capture process per ERP database.

## Wingman setup and existing installs

Release 4.9.0.4 targets Wingman AI 3.2.2's Skill API 3. The public entry is skills.sc_accountant.main, class SC_Accountant; it delegates to erp_skill. The entry works with both package imports and Wingman's file-based custom loader without changing sys.path. The previous implementation is retained in legacy_main.py for reference and rollback; it is not a v3-compatible entry point.

The manifest declares api_version: 3 and auto_activate: true. It exposes three voice tools: erp_report, erp_record and erp_dashboard. Capture starts when Wingman prepares the enabled skill, without waiting for a voice request. Background capture makes no model calls.

After updating, restart Wingman so its catalog rescans. If an earlier startup automatically removed the incompatible accountant from your Wingman profile, enable it again in that profile. Ask to open the accounting dashboard to activate the ERP.

The default manifest must be replaced during this v3 migration: keeping the pre-v3 default_config.yaml would leave the skill marked legacy. Saved per-Wingman settings remain separate. Keep copies of any manually customized defaults and transfer complexity_layer, reader_database, auto_sync_interval and dashboard_port values. The ERP opens its own erp.sqlite3 in the generated-files folder and does not automatically import legacy ledgers.

Casual maps to Simple; Engaged and Industrial map to Advanced. A dashboard view selection persists until the Wingman setting changes again. A blank reader_database discovers the Runtime Directory of SC Log Reader in the same Wingman profile, including the older sc_log_reader_2 module name. An explicit full SQLite path overrides discovery. Multiple different reader directories require an explicit selection. No other profiles or folders are searched. auto_sync_interval of zero pauses capture.

## Reader evidence and gaps

Start the updated SC_LogReader service to initialize its durable feed. Legacy JSONL is not supported. The bundled client reads SQLite in read-only mode: it does not start a monitor, parse Game.log, repair the reader database or download updates.

Capture resumes by source identity and ordered cursor. Imported records and cursor commit together. Missing or incompatible databases, changed identity, a cursor ahead of the source, or a different observed player stop capture visibly. Restore the original source or use separate ERP records for another player. A connected database does not prove the game or reader monitor is running.

Requests remain pending until confirmed. Physical rewards and blueprints are not cash. Recorded balance is not guaranteed to match the game wallet. Unknown costs keep profit incomplete. Confirm only what you know; use Attention and wallet reconciliation to close gaps. Give manually recorded transactions an explicit operation when needed; the engine does not guess that nearby events belong together.

For an imported commodity sale, match its receipt to cargo lots to recognize stock cost without another cash payment. For unknown remaining stock cost, set its total remaining basis. For an unknown cost on a completed sale or loss, resolve the consumed cost. Reverse dependent corrections before reversing the original entry.

Production consumes inputs and records a fee, then separates ready status from collection into inventory. Record missing quantities and output details manually. Asset profitability counts explicitly linked transactions. Forecasts use your entered assumptions; they are not live game predictions.

New accounting periods preserve old history and continue the reader cursor. Old-period entries are read-only in History. This does not automatically carry stock or opening balances into a new economy.

## Legacy migration

No automatic conversion or deletion occurs. In Wingman, explicitly request import_legacy with confirmed: true. Import is limited to its own generated-files folder and empty ERP books. The dashboard cannot read arbitrary filesystem paths.

Supported files: transactions.jsonl, balance.json and assets.json. Back up first. Imported transactions remain identifiable cash history, opening balance is reconciled, and asset status is preserved. Historical profit is not reconstructed. Legacy positions, orders, futures, market estimates and unsupported records are not silently imported. Imported historical entries cannot be reversed; use a documented adjustment. Repeated import is blocked.

## Voice use

Ask for overview, operations, inventory, production, assets, reports, plans, attention, feed or history. jobs, finance and planning are accepted aliases. Use erp_report("help"), then erp_report("help:ACTION") for fields. erp_record takes an action and a JSON object string. Reports are deliberately brief; use the dashboard for details.

## Qualification

Automated fixture tests verify accounting and feed behavior; browser tests exercise the dashboard. A real installed-Wingman/game-session acceptance run is still needed before claiming live qualification. Game logs do not guarantee comprehensive wallet, inventory or production coverage. The implementation does not include shared-credit banking, cloud collaboration, depreciation or automatic game controls.

## Building a portable candidate

Run python build_erp_release.py --output dist/sc_accountant-4.9.0.4.zip from this skill folder. It uses the installer allowlist, refuses to overwrite an existing ZIP and includes no player database or test records. This creates a candidate; it does not install or publish it. The older update_release.py helper includes the ERP modules but replaces release_version when invoked, so prefer the ZIP builder for review.
