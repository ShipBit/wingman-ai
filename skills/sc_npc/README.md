# Star Citizen NPCs

NPCs from content packs stand at places the game log names, talk in their own
voice, remember the player and hand out quests. The Wingman stays the
go-between: the user talks to the Wingman, the Wingman calls `talk_to_npc`,
the NPC answers aloud.

## Writing a pack

A pack is a folder with one `pack.yaml`. The bundled example is
`packs/starter/`. Your own packs go into the skill's files folder:

- Windows: `%APPDATA%\ShipBit\WingmanAI\generated_files\ScNpc\packs\<your-pack>\pack.yaml`
- macOS: `~/Library/Application Support/WingmanAI/generated_files/ScNpc/packs/<your-pack>/pack.yaml`

Restart the Wingman after a change. A pack with a problem is left out and the
problem is logged; `quests` with action `list` names it too.

### NPC

| Field | Required | What |
|---|---|---|
| `id` | yes | Short, unique, no spaces. Quests refer to it. |
| `name` | yes | As the player hears it. |
| `place` | yes | The place as the game log names it: `Lorville`, `Port Tressler`, `HDMS-Anderson`, `New Babbage`, `Area 18`, `GrimHEX`... |
| `persona` | yes | Who they are and how they talk, three to five sentences. This is what the model plays. |
| `shop` | no | The shop or spot at that place, shown on the HUD card. |
| `knows` | no | A list of things they can talk about. Everything else they say they don't know. |
| `wants` | no | What they are after. The hook for your quest. |
| `greeting` | no | Said word for word the first time the player talks to them. |
| `voices` | no | TTS provider id to voice: `edge_tts`, `openai`, `elevenlabs`, `wingman_pro`, `inworld`, `pocket_tts`... A provider without an entry uses the skill's "NPC voice" setting. |

### Quest

| Field | Required | What |
|---|---|---|
| `id`, `title` | yes | The title is what the player and the Wingman call it. |
| `giver` | yes | The `id` of the NPC who offers it. They bring it up in conversation. |
| `offer` | no | How the giver describes it. |
| `steps` | yes | In order, each with a `type`, a `hint` (what the player is told when the step becomes current) and an optional `done` line. |
| `reward` | no | Said when the last step is done. Words only; the skill cannot change the game. |

Step types:

- `visit` with `place`: done when the game log reports arrival there.
- `talk` with `npc`: done when the player talks to that NPC.
- `reach` with `target`: `"<body> <latitude> <longitude> <height m> [<tolerance m>]"`, done when the Star Citizen Position skill says the player is within tolerance. Stand at the spot, say "save this place as X" to the Position skill, and copy the numbers it reports. Stay at 500 m tolerance or more: planets turn, and a second of clock error moves a point by a few hundred metres.
- `confirm`: done when the player tells the Wingman so.

## What the player can say

- "Who is here?" and "I talk to Tecia" / "Tell her ..." → `talk_to_npc`
- "I'll take the job" → `quests accept`
- "Am I at the spot?" / "I found it" → `quests check`
- "What am I working on?" → `quests list`
