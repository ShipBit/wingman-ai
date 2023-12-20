class Azure:
    async def validate_config(self, errors):
        if self.tts_provider == "azure":
            self.azure_keys["tts"] = await self.secret_keeper.retrieve(
                requester=self.name,
                key="azure_tts",
                prompt_if_missing=True,
            )
            if not self.azure_keys["tts"]:
                errors.append(
                    "Missing 'azure' tts API key. Please provide a valid key in the settings."
                )
                return

        if self.stt_provider == "azure" or self.stt_provider == "azure_speech":
            self.azure_keys["whisper"] = self.secret_keeper.retrieve(
                requester=self.name,
                key="azure_whisper",
                prompt_if_missing=True,
            )
            if not self.azure_keys["whisper"]:
                errors.append(
                    "Missing 'azure' whisper API key. Please provide a valid key in the settings."
                )
                return

        if self.conversation_provider == "azure":
            self.azure_keys["conversation"] = await self.secret_keeper.retrieve(
                requester=self.name,
                key="azure_conversation",
                prompt_if_missing=True,
            )
            if not self.azure_keys["conversation"]:
                errors.append(
                    "Missing 'azure' conversation API key. Please provide a valid key in the settings."
                )
                return

        if self.summarize_provider == "azure":
            self.azure_keys["summarize"] = await self.secret_keeper.retrieve(
                requester=self.name,
                key="azure_summarize",
                prompt_if_missing=True,
            )
            if not self.azure_keys["summarize"]:
                errors.append(
                    "Missing 'azure' summarize API key. Please provide a valid key in the settings."
                )
                return
