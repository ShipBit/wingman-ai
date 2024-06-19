import time
import google.generativeai as genai
from google.generativeai.types import generation_types
from openai.types.chat import ChatCompletion, ChatCompletionMessage
from openai.types.chat.chat_completion import Choice
from pydantic import BaseModel


class GoogleGenAI:
    def __init__(self, api_key: str):
        genai.configure(api_key=api_key)

    def ask(
        self,
        messages: list[dict[str, str]],
        model: str,
        stream: bool = False,
        tools: list[dict[str, any]] = None,
    ):
        aimodel = genai.GenerativeModel(model_name=model)

        contents = self.convert_messages(messages)
        response = aimodel.generate_content(contents=contents, stream=stream)
        completion = self.convert_response(response=response, model=model)

        return completion

    def convert_messages(self, openai_messages: list[dict[str, str]]):
        google_messages = []
        system_prompt = ""
        for message in openai_messages:
            if isinstance(message, BaseModel):
                message_dict = message.model_dump()
            else:
                message_dict = message

            if message_dict["role"] == "system":
                system_prompt = message_dict["content"]
            elif message_dict["role"] == "user":
                google_messages.append(
                    {"role": "user", "parts": [message_dict["content"]]}
                )
            elif message_dict["role"] == "assistant":
                google_messages.append(
                    {"role": "model", "parts": [message_dict["content"]]}
                )
        if system_prompt:
            google_messages[0]["parts"].insert(0, f"*{system_prompt}*")

        return google_messages

    def convert_response(
        self, response: generation_types.GenerateContentResponse, model: str
    ):
        timestamp = int(time.time())
        choices = [
            Choice(
                finish_reason="stop",
                index=0,
                message=ChatCompletionMessage(content=response.text, role="assistant"),
            )
        ]
        completion = ChatCompletion(
            id=str(timestamp),
            object="chat.completion",
            created=timestamp,
            model=model,
            choices=choices,
        )
        return completion
