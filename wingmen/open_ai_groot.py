from wingmen.open_ai_wingman import OpenAiWingman


class OpenAiGroot(OpenAiWingman):
    def __init__(self, name: str, config: dict[str, any], **kwargs):
        super().__init__(name, config)
        self.one_liner = kwargs.get("one_liner", "I am Groot!")

    async def process(self, _audio_input_wav: str):
        super()._play_audio(self.one_liner)
