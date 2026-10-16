# The HUD

Wingman AI draws a transparent overlay on top of your game: the conversation
with your Wingmen, and an info panel they and their skills pin things to. It
runs on Windows; macOS and Linux are not supported yet. Switch it on under
**Settings → HUD server**.

## Two containers for all Wingmen

All Wingmen of a config share two containers:

- **Chat** — what you said and what the Wingman answered, with its avatar and
  the tools it used. A message stays while the Wingman speaks and goes a
  moment after it stops (*Audio stop delay*), or after *Max display time* if
  nothing is spoken.
- **Info panel** — panels the Wingmen pin there ("put the cargo list on my
  HUD"), progress bars and countdowns. Skills use it too.

Each Wingman has two switches in its settings:

| Switch | On | Off |
|---|---|---|
| **HUD chat** | Its conversation appears in the chat container. | Its conversation stays off the HUD. |
| **HUD info panel** | It gets four tools: show or replace a panel, read the panel, remove a panel, show a progress bar or countdown. | No tools, nothing it adds. |

Every panel remembers who added it: a Wingman, or a skill of a Wingman. When
a Wingman reads the info panel it sees its own panels as "added by you" and
the others with their author, so it knows what is not its own. It can read
every panel or one by its title; it also hears whose panel it replaced or
removed.

There is no tool that clears the whole info panel: it belongs to every Wingman,
and one Wingman must not wipe what another put there. Ask to remove a panel by
its title instead. A title said differently ("the mining one") is matched by
System One when you have it.

Info panels come back after a restart when the profile's *Restore info panels*
is on.

## HUD profiles

Where the containers are and how they look is a **HUD profile**, under
**Settings → HUD**. A profile holds:

- the **chat area** and the **info panel area**: left, top, right and bottom
  edge in pixels on the HUD screen, plus where the container sits in its
  area while its content is shorter: in the **center**, growing both ways
  (the default), at the **top**, growing down, or at the **bottom**, growing
  up,
- the look: font, size, colours, background and overall transparency, corner
  radius, padding, typewriter effect. Tables and the loader take their colour
  from the accent colour, and tables are as see-through as the background,
- how long chat messages stay, and whether the chat shows tool names.

The HUD screen itself (which monitor) is a setting of the HUD server and the
same for every profile.

### Which profile applies

- One profile is the **default**. It applies to every config no other profile
  names. Exactly one profile is the default; the last profile left always is.
- A profile can name **configs**. When you load one of them, that profile
  applies. A config can be named by one profile only: adding it to a profile
  takes it away from the other.
- The default profile cannot be deleted. Make another profile the default
  first.

Renaming a config keeps its profile; deleting a config removes it from its
profile.

### Preview

Switch a profile to **preview** and its two containers appear on the screen as
preview panels: sample content in the profile's real look, always as large as
the whole area. Only one profile is previewed at a time.

While the preview is on, you can use the mouse on the panels:

- drag the **middle** to move a container,
- drag an **edge** or **corner** to resize it.

The fields in the settings follow while you drag, and the new area is saved
when you let go. The real containers step aside during the preview and come
back when you switch it off.

With Windows display scaling the areas count in scaled pixels: a 3840×2160
monitor at 125 % is 3072×1728 for the HUD. Dragging always matches what you see.

## Skills on the HUD

Skills write to the shared containers or draw a group of their own, such as
the microphone icon of the Mic Status skill. A skill's own group takes the
profile's look for everything it does not set itself. See
[the skill guide](../skills/README.md#selfwingmanhud--the-hud-overlay).

Other programs can use the HUD server's HTTP API: [hud_server/API.md](../hud_server/API.md).

## Coming from the HUD skill

The HUD skill is gone. When you update to 3.2.9, the skill settings of the
first Wingman that had it on become your default HUD profile: Wingmen that
were switched on before switched-off ones, the config Core starts with before
the others, then by name. The HUD skill settings of other Wingmen are not
carried over.

The chat and the info panel get the areas they had on your HUD screen,
measured with its resolution and Windows scaling, so the HUD looks the same
on the first start. An anchor at the top becomes **top**, one at the left or
right side becomes **center** (the screen's center counts as its left side),
one at the bottom becomes **bottom**. A chat and info panel that stacked at
one anchor each get their full height, one after the other. Info panels the
skill had saved are not carried over.

Every Wingman gets the chat and the info panel switched on, and so does every
Wingman you add later. Switch them off per Wingman in its settings.
