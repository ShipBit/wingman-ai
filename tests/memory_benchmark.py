#!/usr/bin/env python3
"""Benchmark memory extraction against representative conversations."""

import json
import sys
import requests

BASE_URL = "http://localhost:49111"
WINGMAN = "ATC"

# ── Test Conversations ─────────────────────────────────────────────

CONVERSATIONS = {
    # 1. Short casual chat (~2 min play session)
    "short_casual": {
        "description": "Short casual exchange, user mentions personal details",
        "messages": [
            {"role": "user", "content": "Hey, I just jumped into my Cutlass Black at Port Olisar."},
            {"role": "assistant", "content": "Welcome aboard, Commander! Port Olisar is a solid starting point. Where are you headed today?"},
            {"role": "user", "content": "Thinking about heading to Hurston for some bounty missions. I've been doing those a lot lately."},
            {"role": "assistant", "content": "Good choice! Hurston has plenty of bounty contracts. Watch out for the comm arrays though — if they go down, you might pick up a crimestat accidentally."},
            {"role": "user", "content": "Yeah I learned that the hard way last week. Lost my ship and 50k credits."},
            {"role": "assistant", "content": "Ouch, that's a tough lesson. At least now you know to check the comm array status before engaging."},
        ],
        "expect_summary": True,
        "expect_facts": ["Cutlass Black", "bounty"],
    },

    # 2. Medium gameplay session (~10 min, mixed topics)
    "medium_gameplay": {
        "description": "Medium session with gameplay, lore questions, and personal info",
        "messages": [
            {"role": "user", "content": "I'm at Lorville trying to find the armor shop. This city is so confusing."},
            {"role": "assistant", "content": "Lorville can be tricky to navigate! The armor shop is in the L19 district of the CBD. Take the Metro line to the CBD terminal and follow signs for Tammany and Sons."},
            {"role": "user", "content": "Found it, thanks! I need heavy armor because I keep dying in cave missions."},
            {"role": "assistant", "content": "Heavy armor is a good call for caves. I'd recommend the Overlord set — it has great ballistic protection. Make sure to bring a Pyro RYT multi-tool with a mining attachment too."},
            {"role": "user", "content": "I already have the multi-tool. My org mates told me about it. We're in an org called Stellar Dynamics, about 20 members."},
            {"role": "assistant", "content": "Nice! Stellar Dynamics sounds like a solid crew. Having org mates for cave missions makes things much safer — someone can watch the entrance while others mine."},
            {"role": "user", "content": "Exactly. We usually run 3-4 person squads. Hey, what's the lore behind Hurston Dynamics? I see their name everywhere."},
            {"role": "assistant", "content": "Hurston Dynamics is one of the oldest companies in the UEE. They manufacture weapons and are known for questionable labor practices. The Hurston family basically owns the entire planet Hurston — it's a corporate-run world where the company IS the government."},
            {"role": "user", "content": "That's wild. Reminds me of some real-world megacorps. Anyway, I'm heading into the cave now. Wish me luck!"},
            {"role": "assistant", "content": "Good luck in there, Commander! Stay close to your squad and watch your oxygen levels. Those caves can get deep."},
            {"role": "user", "content": "We made it out! Got about 150k worth of hadanite. Not bad for 30 minutes of work."},
            {"role": "assistant", "content": "That's an excellent haul! 150k in hadanite from a single run is well above average. Your squad coordination must be on point."},
        ],
        "expect_summary": True,
        "expect_facts": ["Stellar Dynamics", "cave", "squad"],
    },

    # 3. Long immersive session (~20 min, narrative arc)
    "long_narrative": {
        "description": "Extended session with a story arc — combat encounter, near-death, rescue",
        "messages": [
            {"role": "user", "content": "I'm doing a cargo run from Area 18 to Microtech. Got my C2 Hercules loaded with laranite."},
            {"role": "assistant", "content": "A laranite run in a C2 — that's a high-value haul! The Area 18 to Microtech route is fairly safe, but keep an eye on your quantum fuel. That's a long jump."},
            {"role": "user", "content": "Yeah, I've done this route dozens of times. It's my main money maker. Usually pull about 200k profit per run."},
            {"role": "assistant", "content": "Consistent income! With that kind of margin, you must have a good feel for the commodity market fluctuations."},
            {"role": "user", "content": "I track prices in a spreadsheet actually. My buddy Marcus and I share it. He runs the same route in his Caterpillar."},
            {"role": "assistant", "content": "Smart approach! Having a shared price tracker gives you both an edge. The Cat is a solid hauler too, though the C2 has better combat survivability if things go south."},
            {"role": "user", "content": "Speaking of which... I just got interdicted. Two Eclipses and a Hammerhead. This doesn't look good."},
            {"role": "assistant", "content": "That's a serious ambush! With a loaded C2, your best bet is to boost toward a clear vector and spool your quantum drive. Don't try to fight a Hammerhead — just run."},
            {"role": "user", "content": "Spooling now... taking heavy fire. Shields are down to 20%. Come on come on..."},
            {"role": "assistant", "content": "Stay calm! Divert all power to shields and keep that nose pointed at your QT marker. The C2 can take a beating."},
            {"role": "user", "content": "I made it! Quantum jumped out with 5% hull. My hands are literally shaking right now."},
            {"role": "assistant", "content": "What a close call! That's the kind of moment that makes Star Citizen unforgettable. You saved a 200k cargo run with nerves of steel."},
            {"role": "user", "content": "I need to repair before I get to Microtech. Is there a station on the way?"},
            {"role": "assistant", "content": "CRU-L1 is along that route — it has repair, refuel, and rearm services. I'd stop there to patch up before the final leg."},
            {"role": "user", "content": "Good call. Heading there now. That ambush was at the Stanton-Microtech L1 point, I think pirates camp there a lot."},
            {"role": "assistant", "content": "You're right — the Lagrange points are notorious pirate camping spots, especially on high-traffic trade routes. Some traders travel with escorts for exactly this reason."},
            {"role": "user", "content": "Maybe I should hire some of my org mates as escorts. The profit margin is big enough to split."},
            {"role": "assistant", "content": "That's a smart business decision. Even splitting 200k three ways gives everyone a decent payout, and the protection virtually eliminates the risk of losing your cargo."},
            {"role": "user", "content": "Alright, I'm repaired and heading to Microtech now. Sold the laranite for 210k profit. Best run yet despite the drama!"},
            {"role": "assistant", "content": "210k profit AND a great story — can't ask for more than that! The pirate encounter probably got your heart rate up more than any FPS mission."},
            {"role": "user", "content": "For sure. I'm gonna log off after this. Thanks for the help today — you're the best wingman!"},
            {"role": "assistant", "content": "Thanks, Commander! Great flying today, especially that escape. Fly safe and see you next time!"},
        ],
        "expect_summary": True,
        "expect_facts": ["C2 Hercules", "laranite", "Marcus", "spreadsheet"],
    },

    # 4. Technical / ship-fitting session
    "technical_loadout": {
        "description": "User asking detailed ship loadout questions, reveals playstyle preferences",
        "messages": [
            {"role": "user", "content": "I want to upgrade my Gladius for PvP. Right now I have the stock loadout and it's not cutting it."},
            {"role": "assistant", "content": "The stock Gladius is decent but definitely needs upgrades for PvP. What's your playstyle — do you prefer getting in close with repeaters or staying at range with cannons?"},
            {"role": "user", "content": "I like getting up close and personal. I used to fly DCS World competitively so I'm comfortable with close-range dogfighting."},
            {"role": "assistant", "content": "With a DCS background, you've got the stick skills for it! For aggressive close-range PvP, I'd recommend swapping to three Mantis GT-220 gatling guns. They have excellent DPS at close range and are very forgiving with aim."},
            {"role": "user", "content": "What about shields? I run FR-66 right now."},
            {"role": "assistant", "content": "FR-66 is solid for general use, but for PvP I'd switch to Sukoran shields. They have a unique mechanic where they don't regenerate but have massive HP pools, which suits aggressive playstyles that don't disengage."},
            {"role": "user", "content": "Interesting. And power plant?"},
            {"role": "assistant", "content": "The Centurion is the go-to for the Gladius. It provides enough power headroom for three repeaters and the Sukoran shield without any issues. You might also want to look at overclocking your coolers."},
            {"role": "user", "content": "I fly with a Virpil constellation alpha stick and throttle by the way. Dual stick setup."},
            {"role": "assistant", "content": "Excellent hardware! The Virpil Alpha is one of the best sticks for space combat. With dual stick (HOSAS), you have full 6DOF control which is a massive advantage in close-range fights."},
            {"role": "user", "content": "Yeah, I can't go back to mouse and keyboard after this. Alright, I'll try the GT-220 + Sukoran setup tonight. Thanks!"},
            {"role": "assistant", "content": "You're going to love it! With your flight sim background and that HOSAS setup, the Gladius will be a monster. Let me know how it goes!"},
        ],
        "expect_summary": True,
        "expect_facts": ["Gladius", "DCS", "Virpil", "PvP"],
    },

    # 5. Minimal / low-signal conversation (should extract very little)
    "minimal_noise": {
        "description": "Very short, low-information exchange — should produce minimal extraction",
        "messages": [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hey there, Commander! How can I help you today?"},
            {"role": "user", "content": "Just testing things out"},
            {"role": "assistant", "content": "No problem! Let me know if you need anything."},
        ],
        "expect_summary": False,
        "expect_facts": [],
    },

    # 6. Multi-topic session with emotional beats
    "multi_topic_emotional": {
        "description": "Session covering exploration, frustration, discovery, and personal goals",
        "messages": [
            {"role": "user", "content": "I've been trying to find a good mining spot on Aberdeen for hours and I'm getting frustrated."},
            {"role": "assistant", "content": "Aberdeen mining can be hit or miss. The best deposits tend to spawn in the rocky valleys near the equator. Are you looking for quantanium or something more common?"},
            {"role": "user", "content": "Quantanium. I want to save up for a Reclaimer. That's my dream ship. I've been grinding for weeks."},
            {"role": "assistant", "content": "The Reclaimer is an awesome goal! It's around 14.5 million aUEC in-game. How far along are you in your savings?"},
            {"role": "user", "content": "About 8 million. So I'm over halfway there. I mine in my Prospector with a Lancet head."},
            {"role": "assistant", "content": "You're making great progress! The Lancet is perfect for quantanium — its precision mode helps with those unstable rocks. At your current rate, you might want to consider selling at the TDD on New Babbage for the best prices."},
            {"role": "user", "content": "Wait, I've been selling at Lorville this whole time. Is New Babbage better?"},
            {"role": "assistant", "content": "For quantanium specifically, New Babbage's TDD often pays 10-15% more than Lorville. That could shave days off your grind."},
            {"role": "user", "content": "Oh man, I wish I'd known that earlier. That's probably hundreds of thousands I've left on the table."},
            {"role": "assistant", "content": "Don't worry about the past runs — from here on out, you'll be earning more per load. Think of it as a lesson learned!"},
            {"role": "user", "content": "You're right. Okay, I found a big quantanium rock! 5800 mass, 22% concentration. This is a good one!"},
            {"role": "assistant", "content": "That's an excellent find! 22% concentration on a 5800 mass rock could net you around 200k+ if you mine it clean. Take your time with the fracturing — quantanium is volatile."},
            {"role": "user", "content": "Got it! Clean extraction. Heading to New Babbage now. Today was worth it after all."},
            {"role": "assistant", "content": "From frustration to a perfect rock — that's the mining life! Let me know what price you get at New Babbage. That Reclaimer fund is growing!"},
        ],
        "expect_summary": True,
        "expect_facts": ["Reclaimer", "Prospector", "8 million"],
    },
}


def run_test(name: str, convo: dict) -> dict:
    """Run a single extraction test and return results."""
    url = f"{BASE_URL}/memories/{WINGMAN}/test-extraction"
    resp = requests.post(url, json=convo["messages"], timeout=120)
    if resp.status_code != 200:
        return {"name": name, "error": f"HTTP {resp.status_code}: {resp.text}"}

    data = resp.json()
    parsed = data.get("parsed")
    return {
        "name": name,
        "description": convo["description"],
        "message_count": data.get("message_count"),
        "conversation_length": data.get("conversation_length"),
        "raw_response": data.get("raw_response"),
        "parsed": parsed,
        "summary": parsed.get("summary", "") if parsed else None,
        "facts": parsed.get("facts", []) if parsed else None,
    }


def evaluate(result: dict, convo: dict) -> dict:
    """Evaluate extraction quality."""
    issues = []
    scores = {}

    summary = result.get("summary") or ""
    facts = result.get("facts") or []

    # Summary quality
    if convo["expect_summary"]:
        if not summary:
            issues.append("MISSING: Expected a summary but got none")
            scores["summary"] = 0
        elif len(summary) < 40:
            issues.append(f"WEAK: Summary too short ({len(summary)} chars)")
            scores["summary"] = 0.3
        elif len(summary) > 500:
            issues.append(f"VERBOSE: Summary too long ({len(summary)} chars)")
            scores["summary"] = 0.5
        else:
            scores["summary"] = 1.0
    else:
        if summary and len(summary) > 20:
            issues.append("NOISE: Got summary for minimal conversation")
            scores["summary"] = 0.5
        else:
            scores["summary"] = 1.0

    # Facts quality — keyword matching (all keywords in expect must appear)
    expected = convo["expect_facts"]
    if expected:
        matched = 0
        for exp in expected:
            keywords = exp.lower().split()
            if any(
                all(kw in f.lower() for kw in keywords)
                for f in facts
            ):
                matched += 1
        scores["fact_recall"] = matched / len(expected) if expected else 1.0
        if matched < len(expected):
            missed = [
                e for e in expected
                if not any(
                    all(kw in f.lower() for kw in e.lower().split())
                    for f in facts
                )
            ]
            issues.append(f"MISSED FACTS: {missed}")
    else:
        if len(facts) > 1:
            issues.append(f"NOISE: Got {len(facts)} facts for minimal conversation")
            scores["fact_recall"] = 0.5
        else:
            scores["fact_recall"] = 1.0

    # Fact quality: check for non-durable / noisy facts
    noise_words = ["conversation", "asked about", "the assistant", "this session", "currently at", "heading to"]
    noisy = [f for f in facts if any(nw in f.lower() for nw in noise_words)]
    if noisy:
        issues.append(f"NOISY FACTS: {noisy}")
        scores["fact_precision"] = max(0, 1.0 - len(noisy) / max(len(facts), 1))
    else:
        scores["fact_precision"] = 1.0

    overall = sum(scores.values()) / len(scores) if scores else 0
    return {"scores": scores, "overall": overall, "issues": issues}


def main():
    print("=" * 70)
    print("MEMORY EXTRACTION BENCHMARK")
    print("=" * 70)

    results = []
    for name, convo in CONVERSATIONS.items():
        print(f"\n{'─' * 60}")
        print(f"TEST: {name}")
        print(f"  {convo['description']}")
        print(f"  Messages: {len(convo['messages'])}")
        print(f"  Running...", end=" ", flush=True)

        result = run_test(name, convo)

        if "error" in result:
            print(f"ERROR: {result['error']}")
            results.append(result)
            continue

        print("OK")
        eval_result = evaluate(result, convo)
        result["evaluation"] = eval_result
        results.append(result)

        s = result.get("summary") or ""
        print(f"\n  SUMMARY ({len(s)} chars):")
        print(f"    {s[:200]}{'...' if len(s) > 200 else ''}")
        print(f"\n  FACTS ({len(result.get('facts') or [])}):")
        for f in (result.get("facts") or []):
            print(f"    - {f}")
        print(f"\n  SCORES: {eval_result['scores']}")
        print(f"  OVERALL: {eval_result['overall']:.2f}")
        if eval_result["issues"]:
            print(f"  ISSUES:")
            for issue in eval_result["issues"]:
                print(f"    ! {issue}")

    # Overall summary
    print(f"\n{'=' * 70}")
    print("OVERALL RESULTS")
    print(f"{'=' * 70}")
    scored = [r for r in results if "evaluation" in r]
    if scored:
        avg = sum(r["evaluation"]["overall"] for r in scored) / len(scored)
        print(f"  Average score: {avg:.2f}")
        for r in scored:
            e = r["evaluation"]
            status = "PASS" if e["overall"] >= 0.8 else "WARN" if e["overall"] >= 0.5 else "FAIL"
            print(f"  [{status}] {r['name']:30s} {e['overall']:.2f}  {', '.join(e['issues']) if e['issues'] else 'clean'}")
    print()


if __name__ == "__main__":
    main()
