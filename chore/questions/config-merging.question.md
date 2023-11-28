---
title: 'Can I just add new config sections and settings for my custom Wingman?'
alt_titles:
  - 'How is the config merged with general settings?'
---

Yes, you can! We take all the "general" sections (currently: `openai`, `features` and `edge_tts`) from the top of the config, and then copy the wingman config section over, so that the wingman always takes precedence.

So if you want to override something, just mirror the general structure in your wingman config:

`features > tts_provider: default` is overridden by `my-wingman > features > tts_provider: edge_tts`.

Because of this mechanism, you can also add completely new config settings and sections to your custom Wingman. Just add something new to your wingman's config, override `Wingman.validate()` to validate it if necessary, and then you can use it safely.
