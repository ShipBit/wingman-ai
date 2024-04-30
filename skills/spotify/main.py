import spotipy
from spotipy.oauth2 import SpotifyOAuth
from skills.skill_base import Skill
from api.interface import WingmanConfig, WingmanInitializationError


class Spotify(Skill):

    def __init__(self, config: WingmanConfig) -> None:
        super().__init__(config=config)
        self.spotify: spotipy.Spotify = None
        self.available_devices = []

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
                        "streaming",
                        "user-modify-playback-state",
                    ],
                )
            )
        return errors

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
                                    "enum": ["getDevices", "setActiveDevice"],
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
                                        "next",
                                        "previous",
                                        "setVolume",
                                        "mute",
                                        "getCurrentTrack",
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
        function_response = "Unable to control Spotify."
        instant_response = ""

        if tool_name == "control_spotify_device":
            print(f"Executing control_spotify_device with parameters: {parameters}")

            action = parameters.get("action")
            if action == "getDevices":
                active_devices = self.get_active_devices()
                active_device_names = ", ".join(
                    [device["name"] for device in active_devices]
                )
                available_device_names = ", ".join(
                    [device["name"] for device in self.get_available_devices()]
                )
                if active_devices and len(active_devices) > 0:
                    function_response = f"Your available devices are: {available_device_names}. Your active devices are: {active_device_names}."
                else:
                    function_response = f"No active device found but these are the available devices: {available_device_names}"

            elif action == "setActiveDevice":
                device_name = parameters.get("device_name")
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
                        function_response = "OK"
                    else:
                        function_response = f"Device '{device_name}' not found."
                else:
                    function_response = "Device name not provided."

        elif tool_name == "control_spotify_playback":
            print(f"Executing control_spotify_playback with parameters: {parameters}")

            action = parameters.get("action")
            if action == "play":
                self.spotify.start_playback()
                function_response = "OK"
            elif action == "pause" or action == "stop":
                self.spotify.pause_playback()
                function_response = "OK"
            elif action == "next":
                self.spotify.next_track()
                function_response = "OK"
            elif action == "previous":
                self.spotify.previous_track()
                function_response = "OK"
            elif action == "setVolume":
                volume_level = parameters.get("volume_level")
                if volume_level:
                    self.spotify.volume(volume_level)
                    function_response = "OK"
                else:
                    function_response = "Volume level not provided."
            elif action == "mute":
                self.spotify.volume(0)
            elif action == "getCurrentTrack":
                current_playback = self.spotify.current_playback()
                if current_playback:
                    artist = current_playback["item"]["artists"][0]["name"]
                    track = current_playback["item"]["name"]
                    function_response = f"Currently playing '{track}' by '{artist}'."
                else:
                    function_response = "No track playing."

        elif tool_name == "play_song_with_spotify":
            print(f"Executing play_song_with_spotify with parameters: {parameters}")

            track = parameters.get("track")
            artist = parameters.get("artist")
            queue = parameters.get("queue")

            results = self.spotify.search(q=f"{track} {artist}", type="track", limit=1)
            track = results["tracks"]["items"][0]
            if track:
                track_name = track["name"]
                artist_name = track["artists"][0]["name"]
                if queue:
                    self.spotify.add_to_queue(track["uri"])
                    function_response = (
                        f"Added '{track_name}' by '{artist_name}' to the queue."
                    )
                else:
                    self.spotify.start_playback(uris=[track["uri"]])
                    function_response = (
                        f"Now playing '{track_name}' by '{artist_name}'."
                    )

        return function_response, instant_response
