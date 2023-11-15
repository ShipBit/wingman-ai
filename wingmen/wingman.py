from importlib import import_module
from services.audio_player import AudioPlayer


class Wingman:
    def __init__(self, name: str, config: dict[str, any]):
        self.config = config
        self.name = name
        self.audio_player = AudioPlayer()

    @staticmethod
    def create_dynamically(
        module_path, class_name, name: str, config: dict[str, any], **kwargs
    ):
        module = import_module(module_path)
        DerivedWingmanClass = getattr(module, class_name)
        instance = DerivedWingmanClass(name, config, **kwargs)
        return instance

    def get_record_key(self) -> str:
        return self.config.get("record_key", None)

    async def process(self, audio_input_wav: str):
        transcript = self._transcribe(audio_input_wav)
        print(f" >> {transcript}")

        response = self._process_transcript(transcript)
        print(f" << {response}")

        self._finish_processing(response)

    # virtual methods:

    def _transcribe(self, audio_input_wav: str) -> str:
        print(
            "Called '_transcribe' function in base class. You should probably override this or the 'process' function."
        )
        return ""

    def _process_transcript(self, transcript: str) -> str:
        print(
            "Called '_process_transcript' function in base class. You should probably override this or the 'process' function."
        )
        return ""

    def _finish_processing(self, text: str):
        pass
