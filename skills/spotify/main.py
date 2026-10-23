import asyncio
import inspect
import time
from typing import TYPE_CHECKING, Literal, Optional
import spotipy
from spotipy.oauth2 import SpotifyOauthError, SpotifyOAuth, SpotifyStateError
from services.benchmark import Benchmark
from api.enums import LogSource, LogType, WingmanInitializationErrorType
from api.interface import SettingsConfig, SkillConfig, WingmanInitializationError
from skills.skill_base import Skill, command_action, tool

if TYPE_CHECKING:
    from wingmen.wingman_context import WingmanContext


class Spotify(Skill):

    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "WingmanContext",
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)

        self.data_path = self.get_generated_files_dir()
        self.spotify: spotipy.Spotify = None
        self.available_devices = []
        self.secret: str = None
        self._last_auth_url: str | None = None
        # Short-lived caches so building the tool list does not hit the Spotify API every turn
        self._cache_ttl = 60.0
        self._devices_cache: tuple[float, list] | None = None
        self._playlists_cache: tuple[float, list] | None = None

    async def secret_changed(self, secrets: dict[str, any]):
        await super().secret_changed(secrets)

        if secrets.get("spotify_client_secret") != self.secret:
            await self.validate()

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()

        self.secret = await self.wingman.secrets.retrieve("spotify_client_secret", errors)
        client_id: str = (
            self.retrieve_custom_property_value("spotify_client_id", errors) or ""
        ).strip()
        redirect_url: str = (
            self.retrieve_custom_property_value("spotify_redirect_url", errors) or ""
        ).strip()
        if not client_id or client_id == "enter-your-client-id-here":
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message="Spotify Client ID is not set. Enter the Client ID of your Spotify app in the skill settings.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                )
            )
        if not redirect_url:
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message="Spotify Redirect URL is not set. Enter the Redirect URL of your Spotify app in the skill settings.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                )
            )
        if self.secret and client_id != "enter-your-client-id-here" and client_id and redirect_url:
            # now that we have everything, initialize the Spotify client
            cache_handler = spotipy.cache_handler.CacheFileHandler(
                cache_path=f"{self.data_path}/.cache"
            )
            auth_manager = SpotifyOAuth(
                client_id=client_id,
                client_secret=self.secret,
                redirect_uri=redirect_url,
                scope=[
                    "user-library-read",
                    "user-read-currently-playing",
                    "user-read-playback-state",
                    "user-modify-playback-state",
                    "streaming",
                    "playlist-read-private",
                    "user-library-modify",
                ],
                cache_handler=cache_handler,
            )

            try:
                token_info = cache_handler.get_cached_token()
                has_valid_token = bool(
                    token_info and auth_manager.validate_token(token_info)
                )
            except (OSError, ValueError, SpotifyOauthError, SpotifyStateError):
                has_valid_token = False

            if not has_valid_token:
                try:
                    auth_url = auth_manager.get_authorize_url()
                except (ValueError, SpotifyOauthError, SpotifyStateError):
                    auth_url = ""

                if auth_url and auth_url != self._last_auth_url:
                    self._last_auth_url = auth_url
                    await self.printr.print_async(
                        text=(
                            "Spotify authentication required. If no browser window opened, "
                            f"open [this URL]({auth_url}) to authorize Wingman AI."
                        ),
                        color=LogType.INFO,
                        source=LogSource.WINGMAN,
                        source_name=(self.wingman.name if self.wingman else self.name),
                        skill_name=self.name,
                    )

            self.spotify = spotipy.Spotify(auth_manager=auth_manager)
            self._devices_cache = None
            self._playlists_cache = None

        return errors

    def get_tools(self) -> list[tuple[str, dict]]:
        # Get decorated tools first
        tools = super().get_tools()

        # Add tools with dynamic enums manually
        tools.append(
            (
                "control_spotify_device",
                {
                    "type": "function",
                    "function": {
                        "name": "control_spotify_device",
                        "description": "Retrieves or sets the audio device of the user that Spotify songs are played on.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "action": {
                                    "type": "string",
                                    "description": "The playback action to take",
                                    "enum": ["get_devices", "set_active_device"],
                                },
                                "device_name": {
                                    "type": "string",
                                    "description": "The name of the device to set as the active device.",
                                    "enum": [
                                        device["name"]
                                        for device in self.get_available_devices()
                                    ],
                                },
                            },
                            "required": ["action"],
                        },
                    },
                },
            )
        )

        tools.append(
            (
                "interact_with_spotify_playlists",
                {
                    "type": "function",
                    "function": {
                        "name": "interact_with_spotify_playlists",
                        "description": "Play a song from a Spotify playlist or list available playlists.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "action": {
                                    "type": "string",
                                    "description": "The action to take",
                                    "enum": ["get_playlists", "play_playlist"],
                                },
                                "playlist": self._playlist_parameter(),
                            },
                            "required": ["action"],
                        },
                    },
                },
            )
        )

        return tools

    async def execute_tool(
        self, tool_name: str, parameters: dict[str, any], benchmark: Benchmark
    ) -> tuple[str, str]:
        # Let base class handle decorated tools
        function_response, instant_response = await super().execute_tool(
            tool_name, parameters, benchmark
        )

        # Handle dynamic enum tools manually
        if tool_name in ["control_spotify_device", "interact_with_spotify_playlists"]:
            benchmark.start_snapshot(f"Spotify: {tool_name}")

            if self.settings.debug_mode:
                message = f"Spotify: executing tool '{tool_name}'"
                if parameters:
                    message += f" with params: {parameters}"
                await self.printr.print_async(text=message, color=LogType.INFO)

            parameters = dict(parameters or {})
            action = parameters.pop("action", None)
            allowed = {
                "control_spotify_device": {
                    "get_devices": self.get_devices,
                    "set_active_device": self.set_active_device,
                },
                "interact_with_spotify_playlists": {
                    "get_playlists": self.get_playlists,
                    "play_playlist": self.play_playlist,
                },
            }[tool_name]
            function = allowed.get(action)
            if function is None:
                benchmark.finish_snapshot()
                return f"Unknown action: {action}", instant_response

            # Only pass parameters the action really takes
            accepted = inspect.signature(function).parameters
            parameters = {k: v for k, v in parameters.items() if k in accepted}

            try:
                if inspect.iscoroutinefunction(function):
                    function_response = await function(**parameters)
                else:
                    # spotipy is blocking HTTP, keep it off the event loop
                    function_response = await asyncio.to_thread(function, **parameters)
            except spotipy.SpotifyException as e:
                function_response = (
                    f"Spotify error. Code: {e.http_status}, Reason: '{e.reason}'"
                )
            except Exception as e:
                function_response = f"Spotify action failed: {e}"

            benchmark.finish_snapshot()

        return function_response, instant_response

    # HELPERS

    def get_available_devices(self, force: bool = False):
        if not self.spotify:
            return []
        now = time.monotonic()
        if not force and self._devices_cache:
            fetched_at, cached = self._devices_cache
            if now - fetched_at < self._cache_ttl:
                return cached
        try:
            devices = [
                device
                for device in self.spotify.devices().get("devices", [])
                if not device["is_restricted"]
            ]
        except Exception:
            devices = []
        # Failures are cached too, so an offline Spotify blocks at most once per TTL
        self._devices_cache = (time.monotonic(), devices)
        return devices

    def get_active_devices(self):
        active_devices = [
            device
            for device in self.spotify.devices().get("devices", [])
            if device["is_active"]
        ]
        return active_devices

    def get_user_playlists(self, force: bool = False):
        if not self.spotify:
            return []
        now = time.monotonic()
        if not force and self._playlists_cache:
            fetched_at, cached = self._playlists_cache
            if now - fetched_at < self._cache_ttl:
                return cached
        try:
            playlists = self.spotify.current_user_playlists().get("items", [])
        except Exception:
            playlists = []
        self._playlists_cache = (time.monotonic(), playlists)
        return playlists

    def _playlist_parameter(self) -> dict:
        """How the model is told to name a playlist.

        Every playlist name used to be an `enum` here, which is carried in
        the tool schema on *every* LLM call while Spotify is active whether
        or not music comes up: 103 tokens at 14 playlists, 375 at 50, 900 at
        120. With System One the model says the name in the user's words and
        `_match_playlist` resolves it once, on the turns that need it.

        Without System One the enum stays. It is what makes the exact-match
        lookup below work, so taking it away would break the skill for anyone
        who switched the feature off.
        """
        parameter = {
            "type": "string",
            "description": "The name of the playlist to interact with",
        }
        system_one = self.wingman.system_one
        if not system_one or not system_one.available:
            parameter["enum"] = [p["name"] for p in self.get_user_playlists()]
        return parameter

    # Low on purpose: the worst this gets wrong is the wrong playlist
    # starting, which is one sentence to undo, while "not found" for a
    # playlist the user can see is the worse answer.
    #
    # Measured 2026-09-20 on four realistic playlists: "deutscher rap"
    # resolves at 0.92, "something for the car" at 0.63, and "opera" is
    # correctly refused. "my coding playlist" -> "Late Night Coding" sits on
    # the line at 0.42 and moves either side of it between runs, because the
    # none-of-these option takes 0.31 of the mass on its own. That one is not
    # reliably caught at any threshold that still refuses "opera", so it
    # stays unresolved — which is what happens today anyway.
    SYSTEM_ONE_MIN_CONFIDENCE = 0.4

    async def _match_playlist(self, playlist_name: str, playlists: list) -> dict | None:
        """The playlist meant, or None. Exact first, then System One."""
        exact = next(
            (p for p in playlists if p["name"].lower() == playlist_name.lower()), None
        )
        if exact or not playlists:
            return exact

        system_one = self.wingman.system_one
        if not system_one or not system_one.available:
            return None

        by_name = {p["name"]: p for p in playlists}
        criteria = {name: None for name in by_name}
        criteria["none_of_these"] = "none of the playlists is the one meant"
        answers = await system_one.decide(
            state={"asked_for": playlist_name, "playlists": list(by_name)},
            questions={
                "playlist": system_one.choice(
                    "Which of the user's playlists did they ask for? The name was "
                    "spoken, so it may be shortened, translated or worded loosely.",
                    criteria,
                )
            },
        )
        picked = answers.choice("playlist", min_confidence=self.SYSTEM_ONE_MIN_CONFIDENCE)
        return None if picked in (None, "none_of_these") else by_name[picked]

    async def get_playlist_uri(self, playlist_name: str):
        playlist = await self._match_playlist(
            playlist_name,
            await asyncio.to_thread(self.get_user_playlists, True),
        )
        return playlist["uri"] if playlist else None

    # ACTIONS for dynamic enum tools

    def get_devices(self):
        active_devices = self.get_active_devices()
        active_device_names = ", ".join([device["name"] for device in active_devices])
        available_device_names = ", ".join(
            [device["name"] for device in self.get_available_devices(force=True)]
        )
        if active_devices and len(active_devices) > 0:
            return f"Your available devices are: {available_device_names}. Your active devices are: {active_device_names}."
        if available_device_names:
            return f"No active device found but these are the available devices: {available_device_names}"

        return "No devices found. Start Spotify on one of your devices first, then try again."

    def set_active_device(self, device_name: str):
        if device_name:
            device = next(
                (
                    device
                    for device in self.get_available_devices(force=True)
                    if device["name"] == device_name
                ),
                None,
            )
            if device:
                self.spotify.transfer_playback(device["id"])
                return "OK"
            else:
                return f"Device '{device_name}' not found."

        return "Device name not provided."

    def get_playlists(self):
        playlists = self.get_user_playlists(force=True)
        playlist_names = ", ".join([playlist["name"] for playlist in playlists])
        if playlist_names:
            return f"Your playlists are: {playlist_names}"

        return "No playlists found."

    async def play_playlist(self, playlist: str = None):
        if not playlist:
            return "Which playlist would you like to play?"

        playlist_uri = await self.get_playlist_uri(playlist)
        if playlist_uri:
            await asyncio.to_thread(self.spotify.start_playback, context_uri=playlist_uri)
            return f"Playing playlist '{playlist}'."

        return f"Playlist '{playlist}' not found."

    # DECORATED TOOLS (static schemas)

    @tool(
        name="control_spotify_playback",
        description="Control Spotify playback with actions like play, pause, next/previous track, or set volume. Use when user wants to control music: 'play music', 'pause', 'skip', 'volume up'.",
    )
    @command_action(
        label="Control Spotify playback",
        description="Bind a fixed playback action (play, pause, skip, etc.) to a command. Set 'volume_level' only when the action is 'set_volume'.",
        respond="speak",
    )
    async def control_spotify_playback(
        self,
        action: Literal[
            "play",
            "pause",
            "stop",
            "play_next_track",
            "play_previous_track",
            "set_volume",
            "mute",
            "get_current_track",
            "like_song",
        ],
        volume_level: Optional[int] = None,
    ) -> str:
        """Execute a Spotify playback control action."""
        if self.settings.debug_mode:
            self.log.info(
                f"Spotify: executing playback action '{action}'", server_only=True
            )

        if not self.spotify:
            return "Spotify is not connected. Check the Spotify skill settings."

        # spotipy is blocking HTTP, keep it off the event loop
        try:
            return await asyncio.to_thread(self._playback_action, action, volume_level)
        except spotipy.SpotifyException as e:
            if e.reason == "NO_ACTIVE_DEVICE":
                return "No active device found. Start Spotify on one of your devices first, then try again."
            return f"Spotify error. Code: {e.http_status}, Reason: '{e.reason}'"

    def _playback_action(self, action: str, volume_level: Optional[int] = None) -> str:
        if action == "set_volume":
            return self.set_volume(volume_level)

        # Map action to method
        action_map = {
            "play": self.play,
            "pause": self.pause,
            "stop": self.stop,
            "play_next_track": self.play_next_track,
            "play_previous_track": self.play_previous_track,
            "mute": self.mute,
            "get_current_track": self.get_current_track,
            "like_song": self.like_song,
        }

        if action in action_map:
            return action_map[action]()

        return f"Unknown action: {action}"

    @tool(
        name="play_song_with_spotify",
        description="Search and play a specific song or artist on Spotify. Use when user says 'play [song/artist]', 'I want to hear', or requests specific music.",
    )
    async def play_song_with_spotify(
        self,
        track: Optional[str] = None,
        artist: Optional[str] = None,
        queue: bool = False,
    ) -> str:
        """Search for and play a song on Spotify."""
        if not track and not artist:
            return "What song or artist would you like to play?"
        if not self.spotify:
            return "Spotify is not connected. Check the Spotify skill settings."

        return await asyncio.to_thread(self._play_song, track, artist, queue)

    def _play_song(self, track: Optional[str], artist: Optional[str], queue: bool) -> str:
        query = " ".join(part for part in (track, artist) if part)
        results = self.spotify.search(q=query, type="track", limit=1)
        found_track = (
            results["tracks"]["items"][0] if results["tracks"]["items"] else None
        )

        if found_track:
            track_name = found_track["name"]
            artist_name = found_track["artists"][0]["name"]
            try:
                if queue:
                    self.spotify.add_to_queue(found_track["uri"])
                    return f"Added '{track_name}' by '{artist_name}' to the queue."
                else:
                    self.spotify.start_playback(uris=[found_track["uri"]])
                    return f"Now playing '{track_name}' by '{artist_name}'."
            except spotipy.SpotifyException as e:
                if e.reason == "NO_ACTIVE_DEVICE":
                    return "No active device found. Start Spotify on one of your devices first, then play a song or tell me to activate a device."
                return f"An error occurred while trying to play the song. Code: {e.code}, Reason: '{e.reason}'"

        return "No track found."

    # Helper playback methods

    def play(self):
        self.spotify.start_playback()
        return "OK"

    def pause(self):
        self.spotify.pause_playback()
        return "OK"

    def stop(self):
        return self.pause()

    def play_previous_track(self):
        self.spotify.previous_track()
        return "OK"

    def play_next_track(self):
        self.spotify.next_track()
        return "OK"

    def set_volume(self, volume_level: int):
        if volume_level is not None:
            self.spotify.volume(max(0, min(100, volume_level)))
            return "OK"

        return "Volume level not provided."

    def mute(self):
        self.spotify.volume(0)
        return "OK"

    def get_current_track(self):
        current_playback = self.spotify.current_playback()
        item = current_playback.get("item") if current_playback else None
        if item:
            artists = item.get("artists") or [{}]
            artist = artists[0].get("name", "unknown artist")
            track = item["name"]
            return f"Currently playing '{track}' by '{artist}'."

        return "No track playing."

    def like_song(self):
        current_playback = self.spotify.current_playback()
        item = current_playback.get("item") if current_playback else None
        if item and item.get("id"):
            track_id = item["id"]
            self.spotify.current_user_saved_tracks_add([track_id])
            return "Track saved to 'Your Music' library."

        return "No track playing. Play a song, then tell me to like it."
