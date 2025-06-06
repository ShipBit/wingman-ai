from os import path
from pathlib import Path
import re
import json
import gc
import requests
import torch
import torchaudio
import numpy as np
from TTS.api import TTS
from api.interface import (
    XTTS2Settings,
    XTTS2TtsConfig,
    SoundConfig,
)
from services.audio_player import AudioPlayer
from services.file import get_writable_dir
from services.printr import Printr

# Todo: maybe allow direct use of mantella or other XTTS2 servers for super advanced users, input IP address like external provider
# Todo: some voices create a lot of noise, which might be related to sample_rate (?)
MODEL_DIR = "xtts2_model"
RECORDING_PATH = "audio_output"
OUTPUT_FILE: str = "xtts2.wav"
CLONING_WAVS_PATH = "xtts2_cloning_wavs"
LATENTS_PATH = "xtts2_latents"

printr = Printr()


# Todo: changing speed and temperature (and output streaming?) in the UI only works if you change the voice back and forth afterwards
class XTTS2:
    def __init__(self, settings: XTTS2Settings):
        self.tts = None
        self.current_device = settings.device
        self.tts_model_loaded = False
        self.xtts2_model_installed = False
        self.settings = settings

        # Only download XTTS2 model once someone enables it, alternative would be downloading on first run, which the code also will do if necessary
        if settings.enable:
            checkpoint_dir, config_path = self.download_xtts2_main_model()

    async def play_audio(
        self,
        text: str,
        config: XTTS2TtsConfig,
        sound_config: SoundConfig,
        audio_player: AudioPlayer,
        wingman_name: str,
    ):
        # Only load model once there's a request for generation; this adds a slight delay but ensures XTTS2 uses no resources unless the user really wants to use it this session
        if not self.tts or not self.tts_model_loaded:
            await self.load_xtts2(self.settings.device)

        self.handle_vram_change(self.settings.device)

        text_lines = self.split_text_for_xtts2(text, config.language)
        combined_audio = np.array([], dtype=np.float32)
        if not config.output_streaming:
            for text_line in text_lines:
                output_file = await self.__generate_speech(
                    text=text_line,
                    voice=config.voice,
                    temperature=config.temperature,
                    speed=config.speed,
                    language=config.language,
                    device=self.settings.device,
                )
                audio, sample_rate = audio_player.get_audio_from_file(output_file)
                combined_audio = np.concatenate((combined_audio, audio))
            await audio_player.play_with_effects(
                input_data=(combined_audio, sample_rate),
                config=sound_config,
                wingman_name=wingman_name,
            )
        # streaming:
        else:
            for text_line in text_lines:
                await self.__generate_streaming_speech(
                    sound_config=sound_config,
                    audio_player=audio_player,
                    wingman_name=wingman_name,
                    text=text_line,
                    voice=config.voice,
                    temperature=config.temperature,
                    speed=config.speed,
                    language=config.language,
                    device=self.settings.device,
                )

        self.handle_vram_change("cpu")

    # This is called when the user changes XTTS2 settings in the UI. Settings are the new settings.
    def update_settings(self, settings: XTTS2Settings):
        # Detect change to model enabled state
        if settings.enabled != self.settings.enabled:
            # User has now enabled model
            if settings.enabled:
                self.load_xtts2(settings.device)
            else:
                self.unload_xtts2()
        # Detect change to desired device
        if settings.enabled and (settings.device != self.settings.device):
            self.handle_vram_change(settings.device)
        
        # Cache new settings
        self.settings = settings
        
        printr.print("XTTS2 settings updated.", server_only=True)

    # Generate speech depending on whether using XTTS2 built in voices, cloning from wav files, or generating from shared latents (e.g. the output of wav file cloning)
    async def __generate_speech(
        self,
        text: str,
        voice: str,
        temperature: float,
        speed: float,
        language: str,
        device: str,
    ):
        if not text:
            return

        completed_file_path = ""

        file_path = path.join(get_writable_dir(RECORDING_PATH), OUTPUT_FILE)

        if not voice.startswith(CLONING_WAVS_PATH) and not voice.startswith(
            LATENTS_PATH
        ):
            completed_file_path = self.tts.tts_to_file(
                text=text,
                speaker=voice,
                language=language,
                file_path=file_path,
                temperature=temperature,
                speed=speed,
            )
        elif voice.startswith(CLONING_WAVS_PATH):
            full_path = Path(get_writable_dir(voice))
            voices_list = None
            if full_path.is_dir():
                # It's a directory: collect all .wav files
                voices_list = [
                    str(wav_path)
                    for wav_path in full_path.glob("*.wav")
                    if wav_path.is_file()
                ]
            elif full_path.is_file() and full_path.suffix == ".wav":
                # It's a single .wav file
                voices_list = [str(full_path)]
            completed_file_path = self.tts.tts_to_file(
                text=text,
                speaker_wav=voices_list,
                language=language,
                file_path=file_path,
                temperature=temperature,
                speed=speed,
            )
        elif voice.startswith(LATENTS_PATH):
            voice_with_extension = voice + ".json"
            voice_file_path = get_writable_dir(voice_with_extension)
            gpt_cond_latent, speaker_embedding = self.load_latents_from_json(
                device, voice_file_path
            )
            out = self.tts.synthesizer.tts_model.inference(
                text,
                language,
                gpt_cond_latent=gpt_cond_latent,
                speaker_embedding=speaker_embedding,
                temperature=temperature,
                speed=speed,
            )
            torchaudio.save(file_path, torch.tensor(out["wav"]).unsqueeze(0), 24000)
            completed_file_path = file_path

        return completed_file_path

    def _process_model_stream(self, stream_iterator):
        for chunk in stream_iterator:
            if chunk is None:
                continue

            # Convert to NumPy
            if not isinstance(chunk, np.ndarray):
                chunk = chunk.cpu().numpy()

            # Safety: Ensure it's 1D
            if chunk.ndim > 1:
                chunk = chunk.flatten()

            # Clip, scale, convert to int16 PCM bytes
            chunk = np.clip(chunk, -1.0, 1.0)
            int16_chunk = (chunk * 32767).astype(np.int16)
            yield int16_chunk.tobytes()

    async def __generate_streaming_speech(
        self,
        sound_config: SoundConfig,
        audio_player: AudioPlayer,
        wingman_name: str,
        text: str,
        voice: str,
        temperature: float,
        speed: float,
        language: str,
        device: str,
    ):
        if not text:
            return

        if voice.startswith(LATENTS_PATH):
            voice_with_extension = voice + ".json"
            voice_file_path = get_writable_dir(voice_with_extension)
            gpt_cond_latent, speaker_embedding = self.load_latents_from_json(
                device, voice_file_path
            )
        elif voice.startswith(CLONING_WAVS_PATH):
            full_path = Path(get_writable_dir(voice))
            voices_list = None
            if full_path.is_dir():
                voices_list = [
                    str(wav_path)
                    for wav_path in full_path.glob("*.wav")
                    if wav_path.is_file()
                ]
            elif full_path.is_file() and full_path.suffix == ".wav":
                voices_list = [str(full_path)]
            gpt_cond_latent, speaker_embedding = (
                self.tts.synthesizer.tts_model.get_conditioning_latents(
                    audio_path=voices_list
                )
            )
        else:
            # built in voices -> latents, see https://gist.github.com/ichabodcole/1c0d19ef4c33b7b5705b0860c7c27f7b
            model_version = "main"
            speakers_dir = path.join(
                get_writable_dir(MODEL_DIR), f"{model_version}", "speakers_xtts.pth"
            )
            speaker_data = torch.load(speakers_dir)
            speaker = list(speaker_data[voice].values())
            gpt_cond_latent = speaker[0]
            speaker_embedding = speaker[1]

        output_iterator = self.tts.synthesizer.tts_model.inference_stream(
            text,
            language,
            gpt_cond_latent=gpt_cond_latent,
            speaker_embedding=speaker_embedding,
            temperature=temperature,
            speed=speed,
            stream_chunk_size=20,
        )

        generator_instance = self._process_model_stream(output_iterator)
        incomplete_buffer = b""

        def buffer_callback(audio_buffer):
            nonlocal incomplete_buffer
            try:
                chunk = next(generator_instance)
                chunk = incomplete_buffer + chunk
                remainder = len(chunk) % 2  # assuming int16 samples

                if remainder:
                    incomplete_buffer = chunk[-remainder:]
                    chunk = chunk[:-remainder]
                else:
                    incomplete_buffer = b""

                audio_buffer[: len(chunk)] = chunk
                return len(chunk)
            except StopIteration:
                if incomplete_buffer:
                    chunk_length = len(incomplete_buffer)
                    audio_buffer[:chunk_length] = incomplete_buffer
                    incomplete_buffer = b""
                    return chunk_length
                return 0

        # Todo: if possible, it might be way easier to convert to sample_rate 16000 if possible
        await audio_player.stream_with_effects(
            buffer_callback=buffer_callback,
            config=sound_config,
            wingman_name=wingman_name,
            sample_rate=24000,
            channels=1,
            dtype="int16",
        )

    # Move model in and out of VRAM between generations to reduce performance impact
    def handle_vram_change(self, desired_device):
        if not self.tts:
            return
        self.current_device = str(self.tts.synthesizer.tts_model.device)
        if torch.cuda.is_available():
            printr.print(
                f"XTTS2 synth device: {self.tts.synthesizer.tts_model.device}",
                server_only=True,
            )
            if "cuda" in desired_device:
                if "cuda" not in self.current_device:
                    printr.print("XTTS2: Moving XTTS2 model to GPU", server_only=True)
                    self.tts.synthesizer.tts_model.to(desired_device)
                    gc.collect()
                    self.current_device = desired_device
            if "cpu" in desired_device:
                if "cpu" not in self.current_device:
                    printr.print("XTTS2: Moving model to CPU", server_only=True)
                    self.tts.synthesizer.tts_model.to(desired_device)
                    torch.cuda.empty_cache()
                    gc.collect()
                    self.current_device = desired_device

    # Generic helper functions
    def split_text_for_xtts2(self, text, lang="en"):
        # Do not split short passages
        if len(text) <= 175:
            return [text]

        if not self.tts:
            return [text]
        
        # Use segmenter built into coqui-tts library to split sentences
        try:
            self.tts.synthesizer.seg = self.tts.synthesizer._get_segmenter(lang)
        except Exception as e:
            printr.print(f"XTTS2: Getting segmenter for language: {lang} failed, defaulting to English.  Reason: {e}.", server_only=True)
        text_lines = self.tts.synthesizer.split_into_sentences(text)

        return text_lines

    def create_directory_if_not_exists(self, directory):
        directory = Path(directory)
        if not directory.exists():
            directory.mkdir(parents=True, exist_ok=True)

    # TODO: propagate this to the UI using a socket command so that we can show a progress indicator
    def download_file(self, url, destination):
        # no timeout here, this takes a while
        try:
            response = requests.get(url, stream=True)
            total_size_in_bytes = int(response.headers.get("content-length", 0))
            block_size = 1024  # 1 Kibibyte
            printr.print(
                f"XTTS2: Downloading file at {url}, please wait...", server_only=True
            )

            with open(destination, "wb") as file:
                for data in response.iter_content(block_size):
                    file.write(data)
            printr.print(f"XTTS2: File downloaded to {destination}.", server_only=True)
        except Exception as e:
            printr.print(
                f"XTTS2: Could not download file at {url}.  Error was {e}.  Manual download may be required to {destination}.", server_only=False
            )

    def download_model(self, this_dir, model_version):
        # Define paths
        base_path = this_dir
        model_path = base_path / f"{model_version}"

        # Define files and their corresponding URLs
        files_to_download = {
            "config.json": f"https://huggingface.co/coqui/XTTS-v2/raw/{model_version}/config.json",
            "model.pth": f"https://huggingface.co/coqui/XTTS-v2/resolve/{model_version}/model.pth?download=true",
            "vocab.json": f"https://huggingface.co/coqui/XTTS-v2/raw/{model_version}/vocab.json",
            "speakers_xtts.pth": "https://huggingface.co/coqui/XTTS-v2/resolve/main/speakers_xtts.pth?download=true",
        }

        # Check and create directories
        self.create_directory_if_not_exists(base_path)
        self.create_directory_if_not_exists(model_path)

        # Download files if they don't exist
        for filename, url in files_to_download.items():
            destination = model_path / filename
            if not destination.exists():
                printr.print(f"XTTS2: Downloading {filename}...", server_only=True)
                self.download_file(url, destination)
        return True

    def load_latents_from_json(self, device, file_path):
        with open(file_path, "r", encoding="UTF-8") as json_file:
            data = json.load(json_file)
        # Use the class's device setting for tensor allocation
        gpt_cond_latent = torch.tensor(data["gpt_cond_latent"], device=device)
        speaker_embedding = torch.tensor(data["speaker_embedding"], device=device)
        return gpt_cond_latent, speaker_embedding

    # Todo: we need to tell the UI when the downloads starts and when it's finishes, so that we can show a progress indicator. We can use a socket command for that.
    def download_xtts2_main_model(self):
        """Use to download the main xtts2 model files and store them in a designated directory"""

        this_dir = Path(get_writable_dir(MODEL_DIR))
        model_version = "main"
        config_path = this_dir / f"{model_version}" / "config.json"
        checkpoint_dir = this_dir / f"{model_version}"
        # Return if we know already installed
        if self.xtts2_model_installed:
            return checkpoint_dir, config_path
        finished = self.download_model(this_dir, model_version)
        self.create_directory_if_not_exists(Path(get_writable_dir(CLONING_WAVS_PATH)))
        self.create_directory_if_not_exists(Path(get_writable_dir(LATENTS_PATH)))
        self.xtts2_model_installed = True
        # Return the paths we need for the checkpoint dir and config path
        return checkpoint_dir, config_path

    # Load the XTTS2 model into memory
    async def load_xtts2(self, device):
        # If we already know tts model is loaded, skip
        if self.tts_model_loaded and self.tts:
            return

        # Just in case, make sure model is downloaded before proceeeding; this should have happened on enabled
        checkpoint_dir, config_path = self.download_xtts2_main_model()

        # Initialize TTS
        self.tts = TTS(model_path=checkpoint_dir, config_path=config_path).to(device)
        self.tts_model_loaded = True
    
    # Reset when user sets xtts2 to disabled
    def unload_xtts2(self):
        # Is there some function in xtts2 for unloading?
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            gc.collect()
        self.tts = None
        self.current_device = None
        self.tts_model_loaded = False
        self.xtts2_model_installed = False
        self.settings = None