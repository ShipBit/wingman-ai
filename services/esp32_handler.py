import asyncio
import json
from os import path
import wave

from fastapi import WebSocket, WebSocketDisconnect

from services.file import get_writable_dir
from wingman_core import WingmanCore


class Esp32Handler:
    def __init__(self, core: WingmanCore) -> None:
        self.to_device = asyncio.Queue()
        self.core = core
        self.wait_for_response = False
        self.recording_path = "audio_output"
        self.recording_file = "client_recording.wav"
        self.recording_file_path = path.join(
            get_writable_dir(self.recording_path), self.recording_file
        )

        core.audio_player.stream_event.subscribe("audio", self.handle_stream_playback)
        core.audio_player.playback_events.subscribe("started", self.handle_start)
        core.audio_player.playback_events.subscribe("finished", self.handle_end)

    async def handle_start(self, _):
        if self.wait_for_response:
            await self.to_device.put({"role": "assistant", "type": "audio", "format": "bytes.raw", "start": True})

    async def handle_end(self, _):
        if self.wait_for_response:
            self.wait_for_response = False
            await self.to_device.put({"role": "assistant", "type": "audio", "format": "bytes.raw", "end": True})

    async def handle_stream_playback(self, audio_stream):
        if self.wait_for_response:
            for chunk in self.direct_stream(audio_stream):
                await self.to_device.put(chunk)
    
    async def receive_messages(self, websocket: WebSocket):
        byte_string = b''
        while True:
            try:
                try:
                    data = await websocket.receive()
                except Exception as e:
                    print(str(e))
                    return
                if "text" in data:
                    try:
                        data = json.loads(data["text"])
                        if data["role"] == "user":
                            if "start" in data:
                                byte_string = b''
                            elif "end" in data:
                                # Set the parameters for the WAV file
                                nchannels = 1  # Mono audio
                                sampwidth = 2  # 2 bytes per sample for 16-bit audio
                                framerate = 16000  # Sample rate

                                # Save the received stream of bytes as a WAV file
                                loop = asyncio.get_event_loop()
                                await loop.run_in_executor(None, self.save_wav, byte_string, nchannels, sampwidth, framerate)
                                
                                self.wait_for_response = True
                                self.core.on_audio_recorder_speech_recorded(self.recording_file_path)

                    except json.JSONDecodeError:
                        pass  # data is not JSON, leave it as is
                if "bytes" in data:
                    byte_string += data["bytes"]
            except WebSocketDisconnect as e:
                if e.code == 1000:
                    print("Websocket connection closed normally.")
                    return
                else:
                    raise

    async def send_messages(self, websocket: WebSocket):
        while True:
            message = await self.to_device.get()
            try:
                if isinstance(message, dict):
                    await websocket.send_json(message)
                elif isinstance(message, bytes):
                    await websocket.send_bytes(message)
                else:
                    raise TypeError("Message must be a dict or bytes")
            except:
                # Make sure to put the message back in the queue if you failed to send it
                await self.to_device.put(message)
                raise

    def save_wav(self, data, nchannels, sampwidth, framerate):
        with wave.open(self.recording_file_path, "wb") as wf:
            wf.setnchannels(nchannels)
            wf.setsampwidth(sampwidth)
            wf.setframerate(framerate)
            wf.writeframes(data)

    def direct_stream(self, audio_bytes):
        chunk_size = 2048

        # Stream the audio
        for i in range(0, len(audio_bytes), chunk_size):
            chunk = audio_bytes[i : i + chunk_size]
            yield chunk