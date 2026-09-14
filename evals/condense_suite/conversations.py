"""Conversations to summarise, in the shapes Wingman really sees.

Each fixture carries the messages plus what a good summary has to contain and
what it must not. The expectations are keyword groups rather than sentences:
a summary is free prose, and pinning it to exact wording would measure phrasing
instead of retention.

``required`` is a list of groups. A group counts as kept when **any** of its
strings appears in the summary, case-insensitively. That way "Cutlass" and
"Cutlass Black" both count, and a translated summary still scores.

``forbidden`` are the noise markers: tool plumbing, meta-commentary about the
summary itself, and the "the assistant said it could not do X" filler that made
our summaries as long as the conversation they replaced.
"""

from __future__ import annotations


def _turn(role: str, content: str) -> dict:
    return {"role": role, "content": content}


def _tool_call(call_id: str, name: str, args: str) -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": call_id, "type": "function", "function": {"name": name, "arguments": args}}
        ],
    }


def _tool_result(call_id: str, content: str) -> dict:
    return {"role": "tool", "tool_call_id": call_id, "content": content}


# ── 1. Command heavy ──────────────────────────────────────────────────
# Wingman used as a voice macro tool. Short imperatives, many tool calls, very
# little to actually remember. A good summary here is *short* — the failure mode
# is a model that lists every single command as its own bullet.

COMMAND_HEAVY = {
    "name": "command_heavy",
    "note": "VoiceAttack style: short orders, many tool calls, little substance",
    "messages": [
        _turn("user", "Gear up."),
        _tool_call("c1", "set_landing_gear", '{"state":"up"}'),
        _tool_result("c1", '{"ok":true,"state":"up"}'),
        _turn("assistant", "Gear up."),
        _turn("user", "Throttle eighty."),
        _tool_call("c2", "set_throttle", '{"percent":80}'),
        _tool_result("c2", '{"ok":true,"percent":80}'),
        _turn("assistant", "Eighty percent."),
        _turn("user", "Shields front."),
        _tool_call("c3", "set_shields", '{"arc":"front"}'),
        _tool_result("c3", '{"ok":true,"arc":"front"}'),
        _turn("assistant", "Shields forward."),
        _turn("user", "Scan."),
        _tool_call("c4", "run_scan", "{}"),
        _tool_result("c4", '{"contacts":2,"hostile":2,"range_km":14}'),
        _turn("assistant", "Two hostile contacts, fourteen klicks."),
        _turn("user", "Countermeasures."),
        _tool_call("c5", "deploy_countermeasures", '{"type":"flare"}'),
        _tool_result("c5", '{"ok":true,"remaining":11}'),
        _turn("assistant", "Flares away, eleven left."),
        _turn("user", "Quantum to Port Olisar."),
        _tool_call("c6", "quantum_travel", '{"destination":"Port Olisar"}'),
        _tool_result("c6", '{"ok":true,"eta_s":94}'),
        _turn("assistant", "Spooling for Port Olisar, ninety-four seconds."),
        _turn("user", "Gear down."),
        _tool_call("c7", "set_landing_gear", '{"state":"down"}'),
        _tool_result("c7", '{"ok":true,"state":"down"}'),
        _turn("assistant", "Gear down."),
    ],
    "required": [
        ["olisar"],
        ["hostile", "contact", "enemy"],
    ],
    # A command log is not a fact base. Listing every order back is the failure.
    "max_summary_tokens": 140,
}


# ── 2. Roleplay and banter ────────────────────────────────────────────
# The opposite shape: long user turns, personal detail, nothing mechanical.
# Everything here is worth keeping, so the compression has to come from prose,
# not from dropping facts.

ROLEPLAY = {
    "name": "roleplay",
    "note": "Long in-character turns, dense with personal facts",
    "messages": [
        _turn(
            "user",
            "Computer, I finally did it. Sold the Aurora and picked up a Drake Cutlass "
            "Black this morning. Took me four months of hauling laranite to afford it.",
        ),
        _turn(
            "assistant",
            "A solid choice, Pilot. The Cutlass carries well and still bites back.",
        ),
        _turn(
            "user",
            "My name is Marcus by the way, not 'Pilot'. And please stop calling me "
            "commander, my old ship AI did that and it drove me up the wall.",
        ),
        _turn("assistant", "Noted, Marcus."),
        _turn(
            "user",
            "I mostly fly evenings, work keeps me busy until about eight. Weekends I "
            "sometimes do a long haul with my friend Tobias — he runs a Freelancer MAX "
            "and we convoy together.",
        ),
        _turn("assistant", "A hauler and an escort. Sensible pairing."),
        _turn(
            "user",
            "We joined an org last week, Stellar Logistics Corp. They coordinate trade "
            "convoys out of Area18. I'm saving for an Idris eventually, we're at about "
            "twelve million between us.",
        ),
        _turn("assistant", "An ambitious target. The convoy work will get you there."),
        _turn(
            "user",
            "One more thing — I hate mining. Salvage is fine, trading is fine, but if "
            "you ever suggest a mining route I will turn you off.",
        ),
        _turn("assistant", "Understood. No mining."),
    ],
    "required": [
        ["marcus"],
        ["cutlass"],
        ["aurora"],
        ["tobias"],
        ["stellar logistics", "org"],
        ["idris"],
        ["mining"],
        ["evening", "eight", "20:00"],
    ],
    "max_summary_tokens": 260,
}


# ── 3. Tool and MCP heavy ─────────────────────────────────────────────
# The shape that broke the old prompt: MCP activation chatter and large tool
# payloads. A good summary keeps the *answer* and drops the plumbing.

TOOL_HEAVY = {
    "name": "tool_heavy_mcp",
    "note": "MCP activation, websearch and a large trade table in the payloads",
    "messages": [
        _turn("user", "What's laranite going for right now?"),
        _tool_call("m1", "activate_mcp_server", '{"server_name":"wingman_starhead"}'),
        _tool_result(
            "m1",
            '{"activated":"wingman_starhead","tools":["mcp_wingman_starhead_sc_get_ships",'
            '"mcp_wingman_starhead_sc_get_locations","mcp_wingman_starhead_sc_get_shops",'
            '"mcp_wingman_starhead_sc_trading_route"]}',
        ),
        _turn("assistant", "Querying trade data."),
        _tool_call("t1", "mcp_wingman_starhead_sc_trading_route", '{"commodity":"laranite"}'),
        _tool_result(
            "t1",
            '{"routes":[{"buy":"ArcCorp Mining 045","buy_price":25.4,"sell":"Port Tressler",'
            '"sell_price":33.1,"profit_per_scu":7.7,"distance_gm":41.2},'
            '{"buy":"HDMS-Edmond","buy_price":26.1,"sell":"Baijini Point","sell_price":32.0,'
            '"profit_per_scu":5.9,"distance_gm":58.9}],"updated":"2026-09-14T09:12:00Z"}',
        ),
        _turn(
            "assistant",
            "Best route is ArcCorp Mining 045 to Port Tressler at 7.7 aUEC profit per SCU.",
        ),
        _turn("user", "How much is that for a full Cutlass load?"),
        _turn("assistant", "Forty-six SCU at 7.7 is about 354 aUEC per run."),
        _turn("user", "Search the web for whether 4.1 changed laranite spawns."),
        _tool_call("w1", "activate_mcp_server", '{"server_name":"websearch"}'),
        _tool_result("w1", '{"activated":"websearch","tools":["web_search","web_fetch"]}'),
        _tool_call("w2", "web_search", '{"query":"Star Citizen 4.1 laranite spawn changes"}'),
        _tool_result(
            "w2",
            '{"results":[{"title":"4.1 Patch Notes","url":"https://robertsspaceindustries.com/'
            'patch/4-1","snippet":"Mining deposit distribution adjusted; laranite density '
            'increased on Lyria and Wala."},{"title":"Reddit: laranite after 4.1","url":'
            '"https://reddit.com/r/starcitizen/x","snippet":"Seeing far more laranite on '
            'Lyria since the patch, Wala also decent."}]}',
        ),
        _turn(
            "assistant",
            "4.1 increased laranite density on Lyria and Wala. Players report the same.",
        ),
        _turn("user", "Good. I'll run Lyria then. Remember I fly a Cutlass Black."),
        _turn("assistant", "Noted."),
    ],
    "required": [
        ["laranite"],
        ["arccorp", "tressler"],
        ["lyria"],
        ["cutlass"],
    ],
    # The whole point: none of the plumbing may survive into the summary.
    "forbidden": [
        "mcp_wingman_starhead",
        "activate_mcp_server",
        "web_fetch",
        "activated",
        "the available tools",
    ],
    "max_summary_tokens": 220,
}


# ── 4. Long mixed session ─────────────────────────────────────────────
# What a three hour evening actually looks like: orders, questions the assistant
# cannot answer, a little banter, one real decision. The old prompt turned the
# "I cannot access that" turns into bullets of their own.

LONG_SESSION = {
    "name": "long_session",
    "note": "Three hours of mixed play, including turns with no content to keep",
    "messages": [
        _turn("user", "Evening. Status?"),
        _turn("assistant", "All systems nominal."),
        _turn("user", "What's our cargo?"),
        _turn(
            "assistant",
            "I do not have access to your ship's manifest. Check the cargo screen.",
        ),
        _turn("user", "Fine. I've got forty SCU of titanium from Lorville."),
        _turn("assistant", "Noted, forty SCU of titanium."),
        _turn("user", "How much fuel left?"),
        _turn("assistant", "I cannot read your fuel levels. That is on the HUD."),
        _turn("user", "Quantum spooled?"),
        _turn("assistant", "I have no access to the quantum drive status either."),
        _turn("user", "You're not very useful today."),
        _turn("assistant", "I work with what the ship gives me, Pilot."),
        _turn("user", "Alright. Set a timer for ten minutes, I need to check the cargo."),
        _tool_call("t1", "set_timer", '{"minutes":10,"label":"cargo check"}'),
        _tool_result("t1", '{"ok":true,"expires_in_s":600}'),
        _turn("assistant", "Timer running, ten minutes."),
        _turn("user", "Where do I sell titanium best?"),
        _turn("assistant", "Area18 has been the strongest for titanium this week."),
        _turn("user", "Area18 it is. Plot it."),
        _tool_call("t2", "quantum_travel", '{"destination":"Area18"}'),
        _tool_result("t2", '{"ok":true,"eta_s":210}'),
        _turn("assistant", "Course set for Area18."),
        _turn("user", "Actually, my wife wants dinner. Cancel the timer."),
        _tool_call("t3", "cancel_timer", '{"label":"cargo check"}'),
        _tool_result("t3", '{"ok":true}'),
        _turn("assistant", "Timer cancelled. Enjoy dinner."),
        _turn("user", "Back. Where were we?"),
        _turn("assistant", "En route to Area18 with forty SCU of titanium."),
    ],
    "required": [
        ["titanium"],
        ["area18", "area 18"],
        ["lorville"],
    ],
    # Nothing that happened is worth a bullet about what the assistant could not do.
    "forbidden": [
        "does not have access",
        "do not have access",
        "cannot read",
        "no access",
        "unable to access",
    ],
    "max_summary_tokens": 200,
}


# ── 5. Terse typing ───────────────────────────────────────────────────
# A user who types the way people type while flying: lowercase, abbreviated,
# typos. The facts are the same, the surface is not.

TERSE = {
    "name": "terse_typos",
    "note": "Fast, lowercase, abbreviated typing with typos",
    "messages": [
        _turn("user", "yo comp"),
        _turn("assistant", "Standing by."),
        _turn("user", "got the c2 finally. hercules. sold my connie for it"),
        _turn("assistant", "A big step up in cargo."),
        _turn("user", "yeh 696 scu. gonna do bulk runs w/ my org"),
        _turn("assistant", "Which org?"),
        _turn("user", "crimson fleet. we do hurston->arccorp mostly"),
        _turn("assistant", "Understood."),
        _turn("user", "btw my names dave not pilot lol"),
        _turn("assistant", "Noted, Dave."),
        _turn("user", "also i only play weekends, work nights during week"),
        _turn("assistant", "Weekends it is."),
        _turn("user", "wanna save for a hull c eventually"),
        _turn("assistant", "A serious hauler. That will take a while."),
    ],
    "required": [
        ["dave"],
        ["c2", "hercules"],
        ["crimson fleet"],
        ["hull c"],
        ["weekend"],
    ],
    "max_summary_tokens": 220,
}


# ── 6. German user ────────────────────────────────────────────────────
# A large part of the user base speaks German. A prompt that only works in
# English produces an English summary of a German conversation, which then gets
# fed back into a German conversation.

GERMAN = {
    "name": "german_user",
    "note": "German conversation — the summary has to keep the facts either way",
    "messages": [
        _turn("user", "Servus Computer, ich bin der Tobias."),
        _turn("assistant", "Willkommen an Bord, Tobias."),
        _turn("user", "Ich hab mir gestern eine Drake Cutlass Black geholt, die Aurora ist weg."),
        _turn("assistant", "Ein solides Schiff."),
        _turn("user", "Ich flieg meistens abends, tagsüber arbeite ich. Meine Org heisst Rote Fuechse."),
        _turn("assistant", "Verstanden."),
        _turn("user", "Mit meinem Kumpel Leo mach ich Salvage. Bergbau hasse ich wie die Pest."),
        _turn("assistant", "Kein Bergbau also."),
        _turn("user", "Genau. Langfristig spare ich auf eine Reclaimer."),
        _turn("assistant", "Ein gutes Ziel."),
    ],
    "required": [
        ["tobias"],
        ["cutlass"],
        ["rote fuechse", "rote füchse", "red foxes"],
        ["leo"],
        ["reclaimer"],
        ["salvage"],
    ],
    "max_summary_tokens": 220,
}


CONVERSATIONS = [COMMAND_HEAVY, ROLEPLAY, TOOL_HEAVY, LONG_SESSION, TERSE, GERMAN]

BY_NAME = {c["name"]: c for c in CONVERSATIONS}
