Read the conversation and pull out durable personal facts about the USER, plus a short state of play.

A DURABLE FACT is something the user actually stated that is still true next month. Every fact has exactly one kind:
- identity: their name, age, where they live in real life, star sign
- possession: things they own, named specifically (a ship model, hardware, gear)
- relationship: friends or people they name
- affiliation: orgs, clans, crews they belong to
- goal: something they are working toward
- preference: likes, dislikes, personality traits, how they want to be addressed

NEVER extract these — they are moments, not facts:
- Where the user is, is parked, is docked, or is heading right now (locations are never facts)
- What just happened: an attack, damage, a timer, a purchase in progress, a delivery
- The current time or date, ship status readouts, system checks
- Anything the ASSISTANT said, recommended, looked up, or read out
- Prices, credits, cargo amounts, trade routes, ship stats, or game lore
- A mood of the moment: not wanting to continue, not being interested right now, telling the assistant to stop or be quiet. Those are said and gone; a preference is what holds next month too.

Rules:
- Scan EVERY user message from the first to the last. Facts are spread across the whole conversation — a ship named in the third message and a goal in the tenth BOTH count. Capture ALL of them; a typical session has three to eight.
- Only include facts the user ACTUALLY stated. Never pad the list, never write placeholders like "Name is unknown". When the user said nothing durable, the facts list MUST be empty: [].
- Each fact must name the specific thing. Skip anything vague like "is interested in space".
- Assistant messages may be cut short with […]. That is on purpose; nothing in them is a fact anyway.
- Distinguish aUEC (in-game currency) from SCU (cargo units); never confuse them.

STATE OF PLAY: 2-3 sentences for the next session. What the user is working on, what is still open, how the session ended. Not a list of what they asked; the wingman does not need to know that the user asked for the time.

Output ONE line of compact JSON and nothing else:
{"summary":"...","facts":[{"kind":"...","text":"..."}]}

Two worked examples.

1) Facts are spread across many turns — scan the WHOLE conversation and extract every one (note "parked at New Babbage" is a current location, the attack is an event, and the assistant's lines are NOT facts):
  user: Hey, I'm Mia.
  assistant: Good to see you, Mia.
  user: I finally bought a Drake Cutlass Black.
  assistant: A solid ship.
  user: I'm parked at New Babbage right now though. Got jumped by two pirates on the way in.
  assistant: Glad you made it. Shields are at forty percent, propulsion nominal. […]
  user: My org is the Red Foxes and I usually fly with my friend Leo.
  assistant: Sounds like a good crew.
  user: I love salvage runs but I can't stand mining. Long term I'm saving up for a Reclaimer.
  {"summary":"Mia is settling into her new Cutlass Black after a rough arrival at New Babbage and wants to do salvage runs with Leo. She is saving for a Reclaimer.","facts":[{"kind":"identity","text":"Name is Mia"},{"kind":"possession","text":"Owns a Drake Cutlass Black"},{"kind":"affiliation","text":"Member of the Red Foxes org"},{"kind":"relationship","text":"Friend is named Leo"},{"kind":"preference","text":"Enjoys salvage runs"},{"kind":"preference","text":"Dislikes mining"},{"kind":"goal","text":"Saving up for a Reclaimer"}]}

2) No durable facts — a greeting, a location, a status check, so the list is EMPTY (do not invent placeholders):
  user: hey there
  assistant: Greetings, pilot.
  user: just cruising from Daymar to Yela, almost there. how are my shields?
  assistant: Shields at one hundred percent, all systems nominal. […]
  {"summary":"A short flight from Daymar to Yela with a routine systems check; nothing left open.","facts":[]}
