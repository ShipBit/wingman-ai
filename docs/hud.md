# The HUD

Wingman AI draws a transparent overlay on top of your game: the conversation
with your Wingmen, and an info panel they and their skills pin things to. It
runs on Windows, macOS and Linux (X11, or XWayland in a Wayland session). It is on
from the start;
switch it off under **Settings → HUD Overlay**.

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

Each profile's info panels come back after a restart when its *Restore info
panels* is on.

## HUD profiles

Where the containers are and how they look is a **HUD profile**, under
**Settings → HUD**. A profile holds:

- the **chat area** and the **info panel area**: left, top, right and bottom
  edge in pixels on the HUD screen, plus where the container sits in its
  area while its content is shorter: in the **center**, growing both ways
  (the default), at the **top**, growing down, or at the **bottom**, growing
  up,
- the look: font, size, colours, background and overall transparency, corner
  radius, padding, typewriter effect. While a Wingman works, the bottom edge
  of its window glows softly in the accent colour; tables use a shade of the
  background and are as see-through as the background,
- how long chat messages stay, whether the chat shows tool names, and the
  name the chat calls you. Left empty, it is the name you are signed in to
  Wingman AI with, or "User" when you are not signed in,
- the **chat flow**: off, the chat shows only the newest message, with the
  Wingman's picture and the tools it used. On, it shows the running
  conversation like a messenger: each Wingman's message with its picture,
  name and tools, your own as bubbles on the right, the newest at the bottom.
  It hides the same way and comes back with the earlier messages.

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

A profile becomes active when a config's Wingmen load. Until then, as on
start before Wingman AI is signed in, the HUD shows nothing and keeps the saved
info panels for later.

Each profile has its own chat and info panel. When loading a config switches
the profile, the chat and the info panel are made anew in the new profile's
layout and show what they held when that profile was last on screen: its info
panels (timers count on meanwhile) and, with the chat flow, its conversation,
out of sight until the next message. Nothing carries over from one profile to
another.

### Preview

Switch a profile to **preview** and its two containers appear on the screen as
preview panels: sample content in the profile's real look, always as large as
the whole area; with the chat flow on, the chat panel shows a short
conversation. Only one profile is previewed at a time.

While the preview is on, you can use the mouse on the panels:

- drag the **middle** to move a container,
- drag an **edge** or **corner** to resize it.

The fields in the settings follow while you drag, and the new area is saved
when you let go. The real containers step aside during the preview and come
back when you switch it off.

With Windows display scaling the areas count in scaled pixels: a 3840×2160
monitor at 125 % is 3072×1728 for the HUD. On macOS they count in points, as
macOS lays out windows: a 5K display at default scaling is 2560×1440. On Linux
they count in screen pixels; desktop scaling does not apply to the HUD, so on a
scaled display it looks smaller. Dragging always matches what you see.

On Linux the HUD needs an X display, which a Wayland session provides through
XWayland, and a compositor for its transparent windows (every desktop has one).
Games under Proton and most native games run on XWayland too, so the HUD sits
above them. A native Wayland game in fullscreen may cover it. Under gamescope (the Steam Deck's and
Bazzite's game mode) the HUD marks its windows as an overlay, the way MangoHud
does; that only works when Wingman AI runs inside that gamescope session.

## Streaming and OBS Studio

To capture the HUD in OBS Studio (e.g. on top of a game captured via Game Capture):

1. Add a **Browser** source to your OBS scene.
2. Set the URL to:
   ```
   http://127.0.0.1:7862/obs
   ```
3. Set the width and height to the HUD's screen size, as shown by
   `http://127.0.0.1:7862/obs/status` (`width` and `height`). With Windows
   display scaling that is less than the monitor's resolution: a 3840×2160
   monitor at 125 % is `3072` × `1728`. Another size scales the HUD to fit,
   and a larger one makes it look slightly blurry.
4. Set **FPS** to match your HUD server framerate (e.g. `60`, OBS defaults new browser sources to 30).
5. Place the Browser source above your Game Capture source.
6. Tick **Refresh browser when scene becomes active**. When OBS starts before
   Wingman AI, the page can't load yet; refresh it then (or press **Refresh**
   in the source's properties). Once loaded, it reconnects on its own.

The page shows the HUD on a transparent background, the size of the screen
the HUD is on. Each window is sent only when it changes, so an idle HUD costs
nothing. For a second streaming PC, set the HUD server's host to `0.0.0.0`
(it listens on this PC only by default) and use the gaming PC's local IP in the
URL instead of `127.0.0.1`. The page only connects through an IP address or
`localhost`, not a host name.

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

Commands that called the skill's actions (hide or show the HUD) do nothing
now; the migration log names them, so you can edit or delete them.
