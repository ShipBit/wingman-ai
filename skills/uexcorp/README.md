# UEXCorp

A [Wingman AI](https://wingman-ai.com) skill for **Star Citizen** with live market data from
[UEX](https://uexcorp.space): trade routes for your ship and budget, a step-by-step guide through
the route you pick (also on the HUD), and information about commodities, locations, ships and items.

> Market data is provided by **UEX Corp**. Prices, stock and demand are community reported and
> can be out of date.

---

## What it can do

| Ability | Ask things like… |
| --- | --- |
| **Find trade routes** | *"Best trade route for my Ironclad, I have 2 million"* · *"Three stops, only Stanton"* |
| **Guide you through a route** | *"Take route 2"* · *"Done here"* · *"I only got 2,100 SCU for 5.1 million"* |
| **Show the route on the HUD** | *"Show the trade route on the HUD"* · *"Hide it"* |
| **Commodity prices** | *"Where do I sell Laranite?"* · *"Best place to buy Agricium near Hurston?"* |
| **Locations and terminals** | *"What's at ARC-L4?"* · *"Does Seraphim have a loading dock?"* |
| **Ships and items** | *"How much cargo does a Hull C carry?"* · *"Where can I buy a Ballista?"* |

---

## Requirements

- Bundled with **Wingman AI Core**; no API key needed.
- Name matching ("Arc L4" → *Admin - ARC-L4*) uses Core's embeddings and System One when they are
  available, then the main model, then spelling similarity. Two names for the same place (a terminal
  and its station) are not asked about.

---

## Data and outages

All data comes from the Wingman AI **data relay** (`data-relay.de`), which mirrors the UEX API in two
bundles: locations, terminals, items and ships (refreshed about every two weeks) and prices
(about every two hours). It is the only source. A full download takes a few seconds; an unchanged
bundle is not downloaded again.

The data lives in the folder of the Core version, so a new Core version downloads it once on its
first start. When the relay can't be reached:

- **With stored data**, everything keeps working on it. The user gets one notice, prices older than
  four hours are said to be old, and the refresh is retried every ten minutes.
- **Without data** (first start during an outage), the tools say that UEX data is unavailable
  instead of answering, and the download is retried every minute.

---

## Tools

| Tool | What it does |
| --- | --- |
| `uex_get_trade_routes` | The best routes for a ship, budget, start, destination, number of stops (1-5, at most), star system jumps (`0` = one system only), round trips and more. Respects container sizes, loading docks, stock and demand. |
| `uex_active_trade_route` | The route being flown: `set` (pick a route by its number), `get`, `next`, `record_buy` / `record_sell` (what you really bought or sold), `clear`, `show_hud` / `hide_hud`. |
| `uex_get_commodity_information` | Prices, best buy and sell terminals for a commodity. |
| `uex_get_location_or_terminal_information` | Star systems, planets, stations, terminals and what they offer. |
| `uex_get_vehicle_information` | Ship and vehicle data, where to buy or rent. |
| `uex_get_item_information` | Components, weapons and other items. |
| `uex_calculate_profit` | Profit of a trade from prices and amounts. |

Notes the Wingman reads with a route:

- **volume notes** say why less is bought than fits the hold: estimated stock or demand, or the
  money left for that purchase (and which later stop needs the rest).
- **recorded amounts** that don't add up (more than the hold, more sold than aboard) are kept, with
  a warning for the Wingman to check them with you.
- **container notes** appear only when you have to pick smaller boxes than the buy terminal offers,
  because your ship or the sell terminal takes no bigger ones.
- The ship of your last search is remembered. A different ship is only taken over after it is
  named in two searches, so a misheard ship name doesn't stick.

---

## Settings

| Setting | Default | Meaning |
| --- | --- | --- |
| Default trade route count | 1 | Routes per search when you don't ask for a number. |
| Default trade route stops | 1 | Most stops when you don't ask for a number (1-5). |
| Use Estimated Availability | on | Take UEX's estimated stock and demand into account. |
| Trade route ranking | Profit per stop | Profit per stop, profit per distance or total profit. |
| Show advanced trade route info | off | More location data, profit per stop and return on investment. |

Configs saved before *Default trade route stops* and *Trade route ranking* existed use the defaults.

---

## Files

Everything lives in `%APPDATA%\ShipBit\WingmanAI\<version>\skills\uexcorp\data\`:

- `*_uexcorp.db`: the UEX data.
- `active_trade_route.json`: the route being flown, the last search and the remembered ship.
- `config\commodity_blacklist.yaml`, `config\terminal_blacklist.yaml`: commodities and terminals
  routes never use.
- `debug.log` (and `debug.log.1`, the previous 5 MB): the skill's log, tool calls and responses.
- `error.log` (and `error.log.1`, the previous 5 MB): errors, with tracebacks except for failed relay
  requests.

UEX can only be active on one Wingman at a time: the data, the active route and the HUD panel are
shared.

---

## Tests

The tests live in `tests/skills/uexcorp/` and are part of Core's test suite. From the Wingman AI project root:

```
python -m pytest tests/skills/uexcorp
```

---

## Changelog

### 3.0.0

- **Trade routes:** multi-stop routes with buy-only stops, round trips, `max_stops` (at most) and
  `max_system_jumps`, star systems ("only Stanton"); an exact cargo plan for the best routes; ranking setting.
- **Active trade route:** pick a route by number and get guided stop by stop, record the amounts
  and prices you really got, HUD panel with the route, hold, sell and buy tables and the money.
- **Notes the Wingman can explain:** stock, demand and money limits, container sizes, illegal cargo.
- Purchases that earn next to nothing are left out of routes; illegal cargo must earn at least 5 %
  of the route.
- Routes that only differ in the terminal of the last sale are one route that names the others.
- Name matching with Core's embeddings and System One, star system aware ("Nyx Gateway (Stanton)");
  stations, outposts and points of interest also by nickname ("Grim HEX", "Everus").
- Fixed: stock/demand on sell terminals (raw UEX names read the wrong way), ship rental prices
  (read from the purchase table), item stats in two units (quantum speed in Mm/s and km/s),
  "buy at a location" (also matched what is only sold there), ships listing every ship of their maker.
- **Data relay** instead of ~130 UEX API requests: a full download takes seconds. Relay outages are
  reported once and retried; without data the tools say so instead of rejecting names.
- Route searches run off Core's event loop; the background refresh survives errors.
- Removed: the *Add UEX names as hotwords* setting (Core's speech-to-text vocabulary covers them).
  The 3.2.9 migration removes it and the old default prompt from saved Wingmen.
