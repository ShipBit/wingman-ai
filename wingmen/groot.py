from wingmen.wingman import Wingman


class Groot(Wingman):
    async def process(self, _audio_input_wav: str):
        print("I. Am. Groot.")
