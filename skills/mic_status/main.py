"""
Microphone Status skill.

Displays a small HUD window showing a microphone icon that reflects the live
microphone state of Wingman AI:

- Unmuted (green mic) when voice activation is listening AND not playing back.
- Muted (grey mic with a red slash) in push-to-talk mode, when muted, or while
  audio is playing back (Core pauses listening during playback).
- Recording (the recording wingman's avatar with a red dot) while a push-to-talk /
  mouse / joystick key is held or a GUI mic toggle is active.

State comes entirely from the sanctioned facade: ``self.wingman.audio.mic_status``
for the current snapshot and ``self.wingman.audio.on_mic_status_changed`` for live
updates. No WebSocket connection, no reaching into Core internals.

The HUD server must be enabled in the global settings.
"""

import asyncio
import os
import re
import tempfile
from typing import TYPE_CHECKING, Optional

from api.interface import SettingsConfig, SkillConfig
from skills.skill_base import Skill
from hud_server.http_client import HudHttpClient
from hud_server.types import LayoutMode, PersistentProps, WindowType

if TYPE_CHECKING:
    from api.interface import MicStatusResponse
    from wingmen.wingman_context import WingmanContext


class MicStatus(Skill):

    # A single space keeps the panel icon-only; "" would hide the whole window.
    ITEM_TITLE = " "
    RETRY_SECONDS = 10

    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "WingmanContext",
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)

        self._group = re.sub(r"[^a-zA-Z0-9_-]", "_", self.wingman.name) + "_mic"

        skill_dir = os.path.dirname(os.path.abspath(__file__))
        self._mic_on_img = os.path.join(skill_dir, "mic_on.png").replace("\\", "/")
        self._mic_off_img = os.path.join(skill_dir, "mic_off.png").replace("\\", "/")

        self._client: Optional[HudHttpClient] = None
        self._task: Optional[asyncio.Task] = None
        self._subscription = None
        self._status: Optional["MicStatusResponse"] = None
        self._rendered_img: Optional[str] = None
        self._rec_img_cache: dict[str, str] = {}
        self._refresh_lock = asyncio.Lock()

    async def prepare(self) -> None:
        await super().prepare()
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run())

    async def update_config(self, new_config) -> None:
        """Apply placement/position/size changes to the HUD immediately."""
        old_config = self.config
        await super().update_config(new_config)
        if (old_config.custom_properties or []) == (new_config.custom_properties or []):
            return
        # No .connected check: a transient HUD hiccup flips it False with nothing here to
        # reset it, and HudHttpClient auto-reconnects on the next request anyway.
        if not self._client:
            return
        await self._client.delete_group(self._group, WindowType.PERSISTENT)
        await self._client.create_group(
            self._group, WindowType.PERSISTENT, props=self._build_props()
        )
        self._rendered_img = None
        await self._refresh()

    # ---- config helpers ----

    def _get_prop(self, key: str, default):
        val = self.retrieve_custom_property_value(key, [])
        return val if val is not None else default

    def _build_props(self) -> PersistentProps:
        common = dict(
            priority=100,
            width=int(self._get_prop("icon_size", 72)),
            content_padding=8,
            border_radius=12,
            bg_color="#1e212b00",
            opacity=1.0,
        )
        mode = str(self._get_prop("layout_mode", "auto")).lower()
        if mode == "manual":
            return PersistentProps(
                layout_mode=LayoutMode.MANUAL,
                x=int(self._get_prop("pos_x", 20)),
                y=int(self._get_prop("pos_y", 20)),
                **common,
            )
        return PersistentProps(
            layout_mode=LayoutMode.AUTO,
            anchor=str(self._get_prop("anchor", "top_right")),
            **common,
        )

    # ---- recording icon ----

    def _recording_image_for(self, name: str, avatar: Optional[str]) -> str:
        """Path to the "avatar + red dot" icon, cached on the avatar path + mtime so a
        newly saved avatar rebuilds it. Falls back to the plain mic-on icon."""
        name = name or "wingman"
        base = avatar if (avatar and os.path.exists(avatar)) else self._mic_on_img
        try:
            stamp = int(os.path.getmtime(base))
        except Exception:
            stamp = 0
        cache_key = f"{name}|{base}|{stamp}"

        cached = self._rec_img_cache.get(cache_key)
        if cached and os.path.exists(cached):
            return cached

        built = self._build_recording_image(name, avatar)
        img = built or self._mic_on_img
        if built:
            # One cache entry per wingman: drop stale keys from older avatars.
            for key in [k for k in self._rec_img_cache if k.startswith(f"{name}|")]:
                del self._rec_img_cache[key]
            self._rec_img_cache[cache_key] = built
        return img

    def _build_recording_image(self, name: str, avatar_path: Optional[str]) -> Optional[str]:
        """Composite the avatar with a red recording dot to a temp PNG, or None on failure."""
        try:
            from PIL import Image, ImageChops, ImageDraw
        except Exception:
            return None

        base_path = (
            avatar_path
            if avatar_path and os.path.exists(avatar_path)
            else self._mic_on_img
        )
        try:
            img = Image.open(base_path).convert("RGBA")
        except Exception:
            return None

        w, h = img.size
        # Round the avatar corners so the dot poking past the top-right isn't clipped.
        radius = max(2, int(min(w, h) * 0.18))
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, w - 1, h - 1], radius=radius, fill=255
        )
        img.putalpha(ImageChops.multiply(img.getchannel("A"), mask))

        diameter = max(12, int(min(w, h) * 0.30))
        margin = max(2, int(diameter * 0.15))
        x1, y0 = w - margin, margin
        x0, y1 = x1 - diameter, y0 + diameter
        draw = ImageDraw.Draw(img)
        ring = max(1, int(diameter * 0.08))
        draw.ellipse(
            [x0 - ring, y0 - ring, x1 + ring, y1 + ring],
            fill=(255, 255, 255, 235),
        )
        draw.ellipse([x0, y0, x1, y1], fill=(220, 32, 32, 255))

        try:
            out_dir = os.path.join(tempfile.gettempdir(), "wingman_mic_status")
            os.makedirs(out_dir, exist_ok=True)
            safe = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
            try:
                stamp = int(os.path.getmtime(base_path))
            except Exception:
                stamp = 0
            out = os.path.join(out_dir, f"{safe}_{stamp}_rec.png").replace("\\", "/")
            img.save(out)
            self._prune_stale_images(out_dir, safe, keep=out)
            return out
        except Exception:
            return None

    @staticmethod
    def _prune_stale_images(out_dir: str, safe: str, keep: str) -> None:
        """Delete older composites for the same wingman so %TEMP% doesn't accumulate."""
        pattern = re.compile(rf"^{re.escape(safe)}_\d+_rec\.png$")
        try:
            for file in os.listdir(out_dir):
                if pattern.match(file):
                    file_path = os.path.join(out_dir, file).replace("\\", "/")
                    if file_path != keep:
                        os.remove(file_path)
        except Exception:
            pass

    # ---- run + render ----

    async def _run(self) -> None:
        """Connect to the HUD and follow Core's mic state via the facade event."""
        hud_settings = getattr(self.settings, "hud_server", None)
        if not hud_settings or not getattr(hud_settings, "enabled", False):
            self.log.warning(
                "HUD server is not enabled in the global settings - mic indicator disabled.",
                server_only=True,
            )
            return

        host = getattr(hud_settings, "host", "127.0.0.1") or "127.0.0.1"
        hud_port = getattr(hud_settings, "port", 7862) or 7862
        self._client = HudHttpClient(base_url=f"http://{host}:{hud_port}")
        # The HUD server may start after this skill: retry until it is there.
        # Unload cancels this task.
        while True:
            try:
                if await self._client.connect(timeout=3.0) and (
                    await self._client.create_group(
                        self._group, WindowType.PERSISTENT, props=self._build_props()
                    )
                    is not None
                ):
                    break
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.log.warning(f"HUD connect failed: {error}", server_only=True)
            else:
                self.log.warning(
                    f"Could not reach the HUD server, retrying in {self.RETRY_SECONDS} s.",
                    server_only=True,
                )
            await asyncio.sleep(self.RETRY_SECONDS)

        # drop any leftover subscription before re-subscribing
        if self._subscription is not None:
            try:
                self._subscription.unsubscribe()
            except Exception:
                pass
        self._subscription = self.wingman.audio.on_mic_status_changed(self._on_mic_status)
        self._status = self.wingman.audio.mic_status
        await self._refresh()

    async def _on_mic_status(self, status: "MicStatusResponse") -> None:
        self._status = status
        await self._refresh()

    async def _refresh(self) -> None:
        """Draw the icon for the current state. Recording wins; else listening AND not playing."""
        if not self._client:
            return
        # Serialize and re-read the status inside the lock: two rapid state changes spawn
        # two refreshes, and without this the older draw could land on the HUD last.
        async with self._refresh_lock:
            status = self._status
            if status is not None and status.recording and status.recording_wingman:
                img = self._recording_image_for(
                    status.recording_wingman, status.recording_wingman_avatar
                )
            else:
                # No status yet: show muted - Core starts with the recognizer off
                # until the user/client unmutes.
                listening = status.listening if status is not None else False
                playing = status.playing if status is not None else False
                img = self._mic_on_img if (listening and not playing) else self._mic_off_img
            if img == self._rendered_img:
                return
            # Only remember the draw as done if the HUD actually accepted it, so a failed
            # draw (HUD down/restarting) is retried on the next refresh instead of skipped.
            if await self._draw(img):
                self._rendered_img = img

    async def _draw(self, img: str) -> bool:
        """Ensure the group exists with our props, then add the icon item; True only if
        the HUD accepted both. The create_group must come first on EVERY draw: after a
        HUD server restart the group is gone and add_item would auto-create it with
        default props (default-styled window). create_group is create-or-update and
        doesn't re-render an existing window, so this is cheap and flicker-free."""
        created = await self._client.create_group(
            self._group, WindowType.PERSISTENT, props=self._build_props()
        )
        if created is None:
            return False
        return await self._add_item(img) is not None

    async def _add_item(self, img: str):
        return await self._client.add_item(
            group_name=self._group,
            element=WindowType.PERSISTENT,
            title=self.ITEM_TITLE,
            description=f"![]({img})",
        )

    async def _cleanup(self) -> None:
        if self._subscription is not None:
            try:
                self._subscription.unsubscribe()
            except Exception:
                pass
            self._subscription = None
        if not self._client:
            return
        try:
            await self._client.delete_group(self._group, WindowType.PERSISTENT)
        except Exception:
            pass
        try:
            await self._client.disconnect()
        except Exception:
            pass
        self._client = None

    async def unload(self) -> None:
        await super().unload()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        await self._cleanup()
