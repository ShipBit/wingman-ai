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
  edge in pixels on the HUD screen, plus whether the container sticks to the
  **top** of its area and grows down, or to the **bottom** and grows up,
- the look: font, size, colours, background and overall transparency, corner
  radius, padding, typewriter effect,
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

On a display with Windows scaling, the pixels of the areas are the HUD's own
(unscaled) pixels; dragging always matches what you see.

## Skills on the HUD

Skills write to the shared containers or draw a group of their own, such as
the microphone icon of the Mic Status skill. A skill's own group takes the
profile's look for everything it does not set itself. See
[the skill guide](../skills/README.md#selfwingmanhud--the-hud-overlay).

Other programs can use the HUD server's HTTP API: [hud_server/API.md](../hud_server/API.md).

## Coming from the HUD skill

The HUD skill is gone. When you update, each Wingman that had it on hands its
settings to a HUD profile: the set most configs used becomes the default
profile, any other set a profile for the configs that used it. A container
that was placed at an anchor gets the area it had on your screen. Wingmen
that had the skill on keep their chat (unless *Show Chat Messages* was off)
and get the info panel tools; with the HUD on, Wingmen without the skill get
both switches off, so nothing new appears.
