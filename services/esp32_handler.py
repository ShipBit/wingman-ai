import asyncio
import json
import wave

from fastapi import WebSocket

from wingman_core import WingmanCore


class Esp32Handler:
    def __init__(self, core: WingmanCore) -> None:
        self.to_device = asyncio.Queue()
        self.core = core

    async def receive_messages(self, websocket: WebSocket):
        byte_string = b''
        while True:
            data = await websocket.receive()
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
                            await self.core.send_audio_to_wingman_by_path("Computer", file_path="audio.wav")

                            for chunk in self.stream_tts("audio.wav"):
                                await self.to_device.put(chunk)

                except json.JSONDecodeError:
                    pass  # data is not JSON, leave it as is
            if "bytes" in data:
                byte_string += data["bytes"]

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
        with wave.open('audio.wav', 'wb') as wf:
            wf.setnchannels(nchannels)
            wf.setsampwidth(sampwidth)
            wf.setframerate(framerate)
            wf.writeframes(data)

    def stream_tts(self, audio_file):
        with open(audio_file, "rb") as f:
            audio_bytes = f.read()
        # os.remove(audio_file)

        file_type = "bytes.raw"
        chunk_size = 1024

        # Stream the audio
        yield {"role": "assistant", "type": "audio", "format": file_type, "start": True}
        for i in range(0, len(audio_bytes), chunk_size):
            chunk = audio_bytes[i : i + chunk_size]
            yield chunk
        yield {"role": "assistant", "type": "audio", "format": file_type, "end": True}