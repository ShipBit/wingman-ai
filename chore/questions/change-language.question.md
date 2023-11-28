---
title: 'How can I change the language?'
alt_titles:
  - 'Does Wingman speak other languages?'
  - 'Does it support my language?'
---

Wingman supports all languages that OpenAI (or your configured AI provider) supports. Setting this up in Wingman is really easy:

Find the `context` setting in `config.xaml` for the wingman you want to change.

Now add a simple sentence to the `context` prompt:

`Always answer in the language I'm using to talk to you.`

or something like:

`Always answer in Portuguese.`

The cool thing is that you can now trigger commands in the language of your choice without changing/translating the `name` of the commands - the AI will do that for you.
