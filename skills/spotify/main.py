from os import path
from typing import TYPE_CHECKING, Literal, Optional
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from services.benchmark import Benchmark
from api.enums import LogType
from api.interface import SettingsConfig, SkillConfig, WingmanInitializationError
from services.file import get_writable_dir
from skills.skill_base import Skill, tool

if TYPE_CHECKING:
    from wingmen.open_ai_wingman import OpenAiWingman


class Spotify(Skill):

    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "OpenAiWingman",
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)

        self.data_path = get_writable_dir(path.join("skills", "spotify", "data"))
        self.spotify: spotipy.Spotify = None
        self.available_devices = []
        self.secret: str = None

    async def secret_changed(self, secrets: dict[str, any]):
        await super().secret_changed(secrets)

        if secrets["spotify_client_secret"] != self.secret:
            await self.validate()

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()

        self.secret = await self.retrieve_secret("spotify_client_secret", errors)
        client_id: str = self.retrieve_custom_property_value(
            "spotify_client_id", errors
        ).strip()
        redirect_url: str = self.retrieve_custom_property_value(
            "spotify_redirect_url", errors
        ).strip()
        if self.secret and client_id != "enter-your-client-id-here" and redirect_url:
            # now that we have everything, initialize the Spotify client
            cache_handler = spotipy.cache_handler.CacheFileHandler(
                cache_path=f"{self.data_path}/.cache"
            )
            self.spotify = spotipy.Spotify(
                auth_manager=SpotifyOAuth(
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
            )

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
                                "playlist": {
                                    "type": "string",
                                    "description": "The name of the playlist to interact with",
                                    "enum": [
                                        playlist["name"]
                                        for playlist in self.get_user_playlists()
                                    ],
                                },
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

            action = parameters.get("action", None)
            parameters.pop("action", None)
            function = getattr(self, action if action else tool_name)
            function_response = function(**parameters)

            benchmark.finish_snapshot()

        return function_response, instant_response

    # HELPERS

    def get_available_devices(self):
        if not self.spotify:
            return []
        try:
            devices = [
                device
                for device in self.spotify.devices().get("devices", [])
                if not device["is_restricted"]
            ]
            return devices
        except Exception:
            return []

    def get_active_devices(self):
        active_devices = [
            device
            for device in self.spotify.devices().get("devices")
            if device["is_active"]
        ]
        return active_devices

    def get_user_playlists(self):
        if not self.spotify:
            return []
        try:
            playlists = self.spotify.current_user_playlists()
            return playlists.get("items", [])
        except Exception:
            return []

    def get_playlist_uri(self, playlist_name: str):
        playlists = self.spotify.current_user_playlists()
        playlist = next(
            (
                playlist
                for playlist in playlists["items"]
                if playlist["name"].lower() == playlist_name.lower()
            ),
            None,
        )
        return playlist["uri"] if playlist else None

    # ACTIONS for dynamic enum tools

    def get_devices(self):
        active_devices = self.get_active_devices()
        active_device_names = ", ".join([device["name"] for device in active_devices])
        available_device_names = ", ".join(
            [device["name"] for device in self.get_available_devices()]
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
                    for device in self.get_available_devices()
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
        playlists = self.get_user_playlists()
        playlist_names = ", ".join([playlist["name"] for playlist in playlists])
        if playlist_names:
            return f"Your playlists are: {playlist_names}"

        return "No playlists found."

    def play_playlist(self, playlist: str = None):
        if not playlist:
            return "Which playlist would you like to play?"

        playlist_uri = self.get_playlist_uri(playlist)
        if playlist_uri:
            self.spotify.start_playback(context_uri=playlist_uri)
            return f"Playing playlist '{playlist}'."

        return f"Playlist '{playlist}' not found."

    # DECORATED TOOLS (static schemas)

    @tool(
        name="control_spotify_playback",
        description="Control Spotify playback with actions like play, pause, next/previous track, or set volume. Use when user wants to control music: 'play music', 'pause', 'skip', 'volume up'.",
    )
    def control_spotify_playback(
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
            import asyncio

            asyncio.create_task(
                self.printr.print_async(
                    f"Spotify: executing playback action '{action}'",
                    color=LogType.INFO,
                )
            )

        if action == "set_volume" and volume_level is not None:
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
    def play_song_with_spotify(
        self,
        track: Optional[str] = None,
        artist: Optional[str] = None,
        queue: bool = False,
    ) -> str:
        """Search for and play a song on Spotify."""
        if not track and not artist:
            return "What song or artist would you like to play?"

        results = self.spotify.search(q=f"{track} {artist}", type="track", limit=1)
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
        if volume_level:
            self.spotify.volume(volume_level)
            return "OK"

        return "Volume level not provided."

    def mute(self):
        self.spotify.volume(0)
        return "OK"

    def get_current_track(self):
        current_playback = self.spotify.current_playback()
        if current_playback:
            artist = current_playback["item"]["artists"][0]["name"]
            track = current_playback["item"]["name"]
            return f"Currently playing '{track}' by '{artist}'."

        return "No track playing."

    def like_song(self):
        current_playback = self.spotify.current_playback()
        if current_playback:
            track_id = current_playback["item"]["id"]
            self.spotify.current_user_saved_tracks_add([track_id])
            return "Track saved to 'Your Music' library."

        return "No track playing. Play a song, then tell me to like it."
