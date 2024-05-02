import spotipy
from spotipy.oauth2 import SpotifyOAuth
from api.interface import WingmanConfig, WingmanInitializationError
from skills.skill_base import Skill
from services.printr import Printr


class Spotify(Skill):

    def __init__(self, config: WingmanConfig) -> None:
        super().__init__(config=config)
        self.spotify: spotipy.Spotify = None
        self.available_devices = []
        self.printr = Printr()

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()

        secret = await self.retrieve_secret("spotify", errors)
        client_id = self.retrieve_custom_property_value("spotify_client_id", errors)
        redirect_url = self.retrieve_custom_property_value(
            "spotify_redirect_url", errors
        )
        if secret and client_id and redirect_url:
            # now that we have everything, initialize the Spotify client
            self.spotify = spotipy.Spotify(
                auth_manager=SpotifyOAuth(
                    client_id=client_id,
                    client_secret=secret,
                    redirect_uri=redirect_url,
                    scope=[
                        "user-library-read",
                        "user-read-currently-playing",
                        "user-read-playback-state",
                        "user-modify-playback-state",
                        "streaming",
                        # "playlist-modify-public",
                        "playlist-read-private",
                        # "playlist-modify-private",
                        "user-library-modify",
                        # "user-read-recently-played",
                        # "user-top-read"
                    ],
                )
            )
        return errors

    def get_tools(self) -> list[tuple[str, dict]]:
        tools = [
            (
                "control_spotify_device",
                {
                    "type": "function",
                    "function": {
                        "name": "control_spotify_device",
                        "description": "Retrieves or sets the audio device of he user that Spotify songs are played on.",
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
            ),
            (
                "control_spotify_playback",
                {
                    "type": "function",
                    "function": {
                        "name": "control_spotify_playback",
                        "description": "Control the Spotify audio playback with actions like play, pause/stop or play the previous/next track or set the volume level.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "action": {
                                    "type": "string",
                                    "description": "The playback action to take",
                                    "enum": [
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
                                },
                                "volume_level": {
                                    "type": "number",
                                    "description": "The volume level to set (in percent)",
                                },
                            },
                            "required": ["action"],
                        },
                    },
                },
            ),
            (
                "play_song_with_spotify",
                {
                    "type": "function",
                    "function": {
                        "name": "play_song_with_spotify",
                        "description": "Find a song with Spotify to either play it immediately or queue it.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "track": {
                                    "type": "string",
                                    "description": "The name of the track to play",
                                },
                                "artist": {
                                    "type": "string",
                                    "description": "The artist that created the track",
                                },
                                "queue": {
                                    "type": "boolean",
                                    "description": "If true, the song will be queued. Otherwise it will be played immediately.",
                                },
                            },
                        },
                    },
                },
            ),
        ]
        return tools

    async def execute_tool(
        self, tool_name: str, parameters: dict[str, any]
    ) -> tuple[str, str]:
        instant_response = ""  # not used here
        function_response = "Unable to control Spotify."

        if tool_name not in [
            "control_spotify_device",
            "control_spotify_playback",
            "play_song_with_spotify",
        ]:
            return function_response, instant_response

        self.printr.print(
            f"Spotify: Executing {tool_name} with parameters: {parameters}",
            server_only=True,
        )

        action = parameters.get("action", None)
        parameters.pop("action", None)
        function = getattr(self, action if action else tool_name)
        function_response = function(**parameters)

        return function_response, instant_response

    def get_available_devices(self):
        devices = [
            device
            for device in self.spotify.devices().get("devices")
            if not device["is_restricted"]
        ]
        return devices

    def get_active_devices(self):
        active_devices = [
            device
            for device in self.spotify.devices().get("devices")
            if device["is_active"]
        ]
        return active_devices

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

        return "No track playing."

    def play_song_with_spotify(
        self, track: str = None, artist: str = None, queue: bool = False
    ):
        if not track and not artist:
            return "What song or artist would you like to play?"
        results = self.spotify.search(q=f"{track} {artist}", type="track", limit=1)
        track = results["tracks"]["items"][0]
        if track:
            track_name = track["name"]
            artist_name = track["artists"][0]["name"]
            try:
                if queue:
                    self.spotify.add_to_queue(track["uri"])
                    return f"Added '{track_name}' by '{artist_name}' to the queue."
                else:
                    self.spotify.start_playback(uris=[track["uri"]])
                    return f"Now playing '{track_name}' by '{artist_name}'."
            except spotipy.SpotifyException as e:
                if e.reason == "NO_ACTIVE_DEVICE":
                    return "No active device found. Start Spotify on one of your devices first, then play a song or tell me to activate a device."
                return f"An error occurred while trying to play the song. Code: {e.code}, Reason: '{e.reason}'"

        return "No track found."
