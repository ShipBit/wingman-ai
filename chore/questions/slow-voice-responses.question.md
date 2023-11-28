---
title: 'Why does it take so long for the voice responses to play?'
alt_titles:
  - 'Audio latency'
  - 'Why is the audio so slow?'
---

**Non-techie version:**.
It should be like using ChatGPT: You hit enter and it starts typing immediately. Only this time with speech. But that's not happening right now because the OpenAI API is broken. Instead, we have to wait for all the audio to be generated and then start playing it.

Dev version:
There is currently a [known issue](https://github.com/openai/openai-python/issues/864) with Open AI's TTS API that our community member _meenie_ discovered and reported to them. Basically, their audio streaming doesn't work in Python. This results in much higher latency when starting the TTS conversion. We're waiting for a fix.

Until then, you can always use another TTS provider like EdgeTTS or 11Labs.
