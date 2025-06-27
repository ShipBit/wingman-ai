import base64
import json
from os import path
import threading
import queue
import time
import numpy as np
from typing import Optional
import requests
import aiofiles
from api.interface import (
    SoundConfig,
    VoiceInfo,
    WingmanInitializationError,
    InworldConfig,
)
from services.audio_player import AudioPlayer
from services.file import get_writable_dir
from services.printr import Printr
from services.secret_keeper import SecretKeeper

RECORDING_PATH = "audio_output"
OUTPUT_FILE: str = "inworld.mp3"


class Inworld:
    def __init__(self, api_key: str, wingman_name: str):
        self.wingman_name = wingman_name
        self.secret_keeper = SecretKeeper()
        self.printr = Printr()
        self.headers = {
            "Authorization": "Basic " + api_key,
            "Content-Type": "application/json",
        }

    def validate_config(
        self, config: InworldConfig, errors: list[WingmanInitializationError]
    ):
        return errors

    async def play_audio(
        self,
        text: str,
        config: InworldConfig,
        sound_config: SoundConfig,
        audio_player: AudioPlayer,
        wingman_name: str,
    ):  # Prepare audio config - override encoding for streaming
        audio_config = config.audio_config.model_dump()

        if config.output_streaming:
            # Replace the existing audio_encoding field (not audioEncoding)
            audio_config["audio_encoding"] = "LINEAR16"
            # Use standard sample rate for LINEAR16 streaming (better performance)
            audio_config["sample_rate_hertz"] = (
                24000  # Good balance of quality and performance
            )

        payload = {
            "text": text,
            "voiceId": config.voice_id,
            "modelId": config.model_id,
            "audioConfig": audio_config,
            "temperature": config.temperature,
        }

        response = requests.request(
            "POST",
            f"{config.tts_endpoint}{':stream' if config.output_streaming else ''}",
            headers=self.headers,
            json=payload,
            timeout=60,
            stream=config.output_streaming,  # Enable streaming for requests
        )

        if config.output_streaming:
            # True streaming: start playback early and continue as chunks arrive
            audio_queue = queue.Queue()
            stream_finished = False

            def process_response_stream():
                """Process the response stream in a separate thread"""
                nonlocal stream_finished
                chunk_count = 0
                try:
                    for chunk in response.iter_lines(decode_unicode=True):
                        if not chunk:
                            continue
                        try:
                            chunk_data = json.loads(chunk)
                            if (
                                "result" in chunk_data
                                and "audioContent" in chunk_data["result"]
                            ):
                                audio_content = chunk_data["result"]["audioContent"]
                                # Decode base64 audio content to raw PCM bytes
                                audio_bytes = base64.b64decode(audio_content)

                                # Skip WAV header if present (first 44 bytes)
                                if len(audio_bytes) > 44 and audio_bytes[:4] == b"RIFF":
                                    audio_bytes = audio_bytes[44:]  # Skip WAV header

                                if len(audio_bytes) > 0:
                                    chunk_count += 1
                                    print(
                                        f"Inworld: Received chunk {chunk_count}, size: {len(audio_bytes)} bytes"
                                    )
                                    audio_queue.put(audio_bytes)
                        except (json.JSONDecodeError, KeyError):
                            # Skip malformed chunks
                            continue
                finally:
                    stream_finished = True
                    audio_queue.put(None)  # Signal end of stream
                    print(f"Inworld: Stream finished, total chunks: {chunk_count}")

            # Start response processing in a background thread
            thread = threading.Thread(target=process_response_stream)
            thread.daemon = True
            thread.start()

            # Wait for first chunk to arrive before starting playback
            print("Inworld: Waiting for first chunk...")
            while audio_queue.empty() and not stream_finished:
                time.sleep(0.001)  # 1ms sleep

            print("Inworld: Starting streaming playback")

            # Streaming buffer management
            audio_buffer_data = b""

            def buffer_callback(audio_buffer):
                nonlocal audio_buffer_data, stream_finished
                try:
                    # Try to get new chunks from queue (non-blocking first)
                    while True:
                        try:
                            chunk = audio_queue.get_nowait()
                            if chunk is None:  # End of stream signal
                                print("Inworld: Stream end signal received")
                                stream_finished = True
                                break
                            else:
                                audio_buffer_data += chunk
                                print(
                                    f"Inworld: Added chunk to buffer, total: {len(audio_buffer_data)} bytes"
                                )
                        except queue.Empty:
                            break

                    # If we have data, return it
                    if len(audio_buffer_data) > 0:
                        bytes_to_copy = min(len(audio_buffer_data), len(audio_buffer))

                        # Ensure we copy complete 16-bit samples
                        if bytes_to_copy % 2 == 1:
                            bytes_to_copy -= 1

                        if bytes_to_copy > 0:
                            audio_buffer[:bytes_to_copy] = audio_buffer_data[
                                :bytes_to_copy
                            ]
                            audio_buffer_data = audio_buffer_data[bytes_to_copy:]
                            return bytes_to_copy

                    # No data available right now - check if stream is finished
                    if stream_finished:
                        print(
                            "Inworld: Stream complete and buffer empty, ending playback"
                        )
                        return 0  # Only return 0 when truly finished

                    # Stream not finished but no data available - wait for more data
                    try:
                        print("Inworld: Waiting for more chunks...")
                        chunk = audio_queue.get(timeout=1.0)  # Wait up to 1 second
                        if chunk is None:  # End of stream signal
                            print("Inworld: Stream end signal received while waiting")
                            # Set stream_finished and handle any remaining buffered data
                            stream_finished = True
                            if len(audio_buffer_data) > 0:
                                bytes_to_copy = min(
                                    len(audio_buffer_data), len(audio_buffer)
                                )
                                if bytes_to_copy % 2 == 1:
                                    bytes_to_copy -= 1
                                if bytes_to_copy > 0:
                                    audio_buffer[:bytes_to_copy] = audio_buffer_data[
                                        :bytes_to_copy
                                    ]
                                    audio_buffer_data = audio_buffer_data[
                                        bytes_to_copy:
                                    ]
                                    return bytes_to_copy
                            return 0
                        else:
                            audio_buffer_data += chunk
                            print(
                                f"Inworld: Added waited chunk to buffer, total: {len(audio_buffer_data)} bytes"
                            )
                            # Now try to return some data
                            bytes_to_copy = min(
                                len(audio_buffer_data), len(audio_buffer)
                            )
                            if bytes_to_copy % 2 == 1:
                                bytes_to_copy -= 1
                            if bytes_to_copy > 0:
                                audio_buffer[:bytes_to_copy] = audio_buffer_data[
                                    :bytes_to_copy
                                ]
                                audio_buffer_data = audio_buffer_data[bytes_to_copy:]
                                return bytes_to_copy
                    except queue.Empty:
                        # Timeout waiting for data - something might be wrong
                        print(
                            "Inworld: Timeout waiting for chunks, checking if finished..."
                        )
                        if stream_finished:
                            return 0
                        # Keep trying - NEVER return 0 if stream isn't finished!
                        # Return a recursive call to try again
                        print("Inworld: Stream not finished, trying again...")
                        return buffer_callback(audio_buffer)

                except Exception as e:
                    print(f"Inworld: Exception in buffer_callback: {e}")
                    # Only return 0 if stream is finished, otherwise try to continue
                    if stream_finished:
                        return 0
                    # Try to continue by making a recursive call
                    return buffer_callback(audio_buffer)

            await audio_player.stream_with_effects(
                buffer_callback=buffer_callback,
                config=sound_config,
                wingman_name=wingman_name,
                sample_rate=int(audio_config["sample_rate_hertz"]),
                channels=1,  # LINEAR16 is typically mono
                dtype="int16",  # LINEAR16 uses 16-bit integers
            )

            # Wait for the background thread to complete
            thread.join()
        else:
            response_data = response.json()
            audio_content = response_data.get("audioContent", "")

            output_file = await self.__write_result_to_file(audio_content)
            audio, sample_rate = audio_player.get_audio_from_file(output_file)

            await audio_player.play_with_effects(
                input_data=(audio, sample_rate),
                config=sound_config,
                wingman_name=wingman_name,
            )

    async def get_available_voices(
        self, filter_language: Optional[str] = None
    ) -> list[VoiceInfo]:
        voices: list[VoiceInfo] = []
        params = None
        if filter_language:
            params = {"filter": f"language={filter}"}

        response = requests.get(
            "https://api.inworld.ai/tts/v1/voices",
            headers=self.headers,
            params=params,
            timeout=10,
        )
        response_data = response.json()
        for voice in response_data.get("voices", []):
            voice_id = voice.get("voiceId", "")
            voices.append(
                VoiceInfo(
                    id=voice_id, name=voice_id, languages=voice.get("languages", [])
                )
            )
        return voices

    async def __write_result_to_file(self, base64_encoded_audio: str):
        file_path = path.join(get_writable_dir(RECORDING_PATH), OUTPUT_FILE)
        audio_data = base64.b64decode(base64_encoded_audio)
        async with aiofiles.open(file_path, "wb") as f:
            await f.write(audio_data)
        return file_path
