from os import path
from pathlib import Path
import json
import gc
import requests
from api.interface import XTTS2Settings, XTTS2TtsConfig, SoundConfig # Needs to be created
from services.audio_player import AudioPlayer
from services.file import get_writable_dir
from services.printr import Printr
import torch
import torchaudio
from TTS.api import TTS

# To do - maybe allow custom latents and cloning paths for super advanced users
# To do - maybe allow direct use of mantella or other XTTS2 servers for super advanced users, input IP address like external provider
MODEL_DIR = "xtts2_model"
RECORDING_PATH = "audio_output"
OUTPUT_FILE: str = "xtts2.wav"
CLONING_WAVS_PATH = "xtts2_cloning_wavs"
LATENTS_PATH = "xtts2_latents"

printr = Printr()


class XTTS2:
    def __init__(self, settings: XTTS2Settings):
        self.tts = None
        self.current_device = "cpu"
        self.tts_model_loaded = False
        self.xtts2_model_installed = False
        
        # Only download XTTS2 model once someone enables it, alternative would be downloading on first run, which the code also will do if necessary
        if settings.enable:
            checkpoint_dir, config_path = self.download_xtts2_main_model()
        #checkpoint_dir, config_path = self.download_xtts2_main_model()

    async def play_audio(
        self,
        text: str,
        config: XTTS2TtsConfig, # needs to be created
        sound_config: SoundConfig,
        audio_player: AudioPlayer,
        wingman_name: str,
    ):
        output_file = await self.__generate_speech(
            text=text, voice=config.voice, temperature=config.temperature, speed=config.speed, language=config.language, device=config.device   # need these variables in config
        )
        audio, sample_rate = audio_player.get_audio_from_file(output_file)
        
        # TO DO, determine if streaming is viable
        await audio_player.play_with_effects(
            input_data=(audio, sample_rate),
            config=sound_config,
            wingman_name=wingman_name,
        )

    # Generate speech depending on whether using XTTS2 built in voices, cloning from wav files, or generating from shared latents (e.g. the output of wav file cloning)
    async def __generate_speech(
        self,
        text: str,
        voice: str = "Craig Gutsy",
        temperature: float = 0.75,
        speed: float = 1.20,
        language: str = "en",
        device: str = "cpu"
    ):
        if not text:
            return
        
        # Allow users to just use "gpu" for less advanced users, and translate this to cuda, while allowing more advanced users to select gpu number by using cuda:0, cuda:1, etc.
        if device == "gpu":
            device = "cuda"
        
        # Only load model once there's a request for generation; this adds a slight delay but ensures XTTS2 uses no resources unless the user really wants to use it this session
        if not self.tts or not self.tts_model_loaded:
            await self.load_xtts2(device)
        
        await self.handle_vram_change(device)
        
        completed_file_path = ""
        
        file_path = path.join(get_writable_dir(RECORDING_PATH), OUTPUT_FILE)
        
        if not voice.startswith(CLONING_WAVS_PATH) and not voice.startswith(LATENTS_PATH):
            completed_file_path = self.tts.tts_to_file(
                text=text,
                speaker=voice,
                language=language,
                file_path=file_path,
                temperature=temperature,
                speed=speed,
            )
        elif voice.startswith(CLONING_WAVS_PATH):
            completed_file_path = self.tts.tts_to_file(
                text=text,
                speaker_wav=[voice], # Will have to deal with how to make voice such if there's multiple wavs in a folder versus just one wav by itself
                language=language,
                file_path=file_path,
                temperature=temperature,
                speed=speed,
            )
        elif voice.startswith(LATENTS_PATH):
            gpt_cond_latent, speaker_embedding = self.load_latents_from_json(device, voice) # voice = "C:/OtherPrograms/Github/xtts2_test/mantella_latents/en/emperor.json"
            out = self.tts.synthesizer.tts_model.inference(
                text,
                language,
                gpt_cond_latent=gpt_cond_latent,
                speaker_embedding=speaker_embedding,
                temperature=temperature,
                speed=speed,
                ##**self.tts_settings, # Expands the object with the settings and applies them for generation
            )
            torchaudio.save(file_path, torch.tensor(out["wav"]).unsqueeze(0), 24000)
            completed_file_path = file_path

        await self.handle_vram_change("cpu")
        
        return completed_file_path
    
    
    # Move model in and out of VRAM between generations to reduce performance impact - TBD if this should be async
    async def handle_vram_change(self, desired_device):
        if not self.tts:
            return
        self.current_device = str(self.tts.synthesizer.tts_model.device)
        if torch.cuda.is_available():
            print(self.tts.synthesizer.tts_model.device)
            if "cuda" in desired_device:
                if "cuda" not in self.current_device:
                    print("Moving XTTS2 model to GPU")
                    self.tts.synthesizer.tts_model.to(desired_device)
                    gc.collect()
                    self.current_device = desired_device
            if "cpu" in desired_device:
                if "cpu" not in self.current_device:
                    print("Moving model to CPU")
                    self.tts.synthesizer.tts_model.to(desired_device)
                    torch.cuda.empty_cache()
                    gc.collect()
                    self.current_device = desired_device
    
    # Generic helper functions
    def create_directory_if_not_exists(self, directory):
        directory = Path(directory)
        if not directory.exists():
            directory.mkdir(parents=True, exist_ok=True)

    def download_file(self, url, destination):
        response = requests.get(url, stream=True)
        total_size_in_bytes = int(response.headers.get('content-length', 0))
        block_size = 1024  # 1 Kibibyte
        print(f"Downloading file at {url}, please wait...")

        with open(destination, 'wb') as file:
            for data in response.iter_content(block_size):
                file.write(data)
        print(f"File downloaded to {destination}.")

    def download_model(self, this_dir, model_version):
        # Define paths
        base_path = this_dir
        model_path = base_path / f'{model_version}'

        # Define files and their corresponding URLs
        files_to_download = {
             "config.json": f"https://huggingface.co/coqui/XTTS-v2/raw/{model_version}/config.json",
             "model.pth": f"https://huggingface.co/coqui/XTTS-v2/resolve/{model_version}/model.pth?download=true",
             "vocab.json": f"https://huggingface.co/coqui/XTTS-v2/raw/{model_version}/vocab.json",
             "speakers_xtts.pth": "https://huggingface.co/coqui/XTTS-v2/resolve/main/speakers_xtts.pth?download=true"
        }

        # Check and create directories
        self.create_directory_if_not_exists(base_path)
        self.create_directory_if_not_exists(model_path)

        # Download files if they don't exist
        for filename, url in files_to_download.items():
             destination = model_path / filename
             if not destination.exists():
                 print(f"[XTTS2] Downloading {filename}...")
                 self.download_file(url, destination)
        return True
    
    def load_latents_from_json(self, device, file_path):
        with open(file_path, 'r') as json_file:
            data = json.load(json_file)
        # Use the class's device setting for tensor allocation
        gpt_cond_latent = torch.tensor(data['gpt_cond_latent'], device=device)
        speaker_embedding = torch.tensor(data['speaker_embedding'], device=device)
        return gpt_cond_latent, speaker_embedding
    
    # Use to download the main xtts2 model files and store them in a designated directory
    def download_xtts2_main_model(self):  
        this_dir = Path(get_writable_dir(MODEL_DIR))
        model_version = "main"
        config_path = this_dir / f'{model_version}' / 'config.json'
        checkpoint_dir = this_dir / f'{model_version}'
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

        # Just in case, make sure model is downloaded before proceeeding; this should have happened on init
        checkpoint_dir, config_path = self.download_xtts2_main_model()

        # Initialize TTS
        self.tts = TTS(model_path=checkpoint_dir,config_path=config_path).to(device)
        self.tts_model_loaded = True
    