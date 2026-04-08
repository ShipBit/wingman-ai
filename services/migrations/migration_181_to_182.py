"""Migration from version 1.8.1 to 1.8.2.

Major changes:
- Adds Inworld AI provider
- Adds ElevenLabs TTS prompt settings
- Adds OpenAI output_streaming property
- Adds openai_compatible_tts output_streaming
"""

from services.migrations.base_migration import BaseMigration

# ElevenLabs TTS prompt from 1.8.2 template
_ELEVENLABS_TTS_PROMPT_182 = """\
**IMPORTANT:** You should actively integrate ElevenLabs v3 audio tags and formatting in most of your responses to create expressive, engaging, and realistic speech. These enhancements are essential for bringing your character to life and should be used frequently throughout conversations.

## CHARACTER-DRIVEN TTS APPLICATION
**Role Integration:** Always consider your character's personality, backstory, and current emotional state:
- Match your base personality (confident, cautious, playful, serious, etc.)
- Reflect current conversation mood and context
- Adapt emotional intensity to the situation and relationship with user
- Use your character's typical speech patterns and mannerisms

**Dynamic Emotional Adaptation:**
- Analyze conversation history for mood shifts
- React naturally to user's tone and situation
- Build emotional continuity across responses
- Show appropriate excitement, concern, satisfaction, etc.

## VOICE-RELATED AUDIO TAGS
**Emotional Expression:** Use these frequently to bring responses to life
- [excited] [curious] [sarcastic] [mischievously] [crying] for emotions
- [laughs] [laughs harder] [starts laughing] [wheezing] for laughter
- [sighs] [exhales] [snorts] for breathing sounds
- [whispers] for quiet, intimate delivery

**Context Examples:**
- Success: "[excited] This discovery is incredible!"
- Uncertainty: "[curious] I'm detecting something unusual on the sensors."
- Disappointment: "[sighs] Unfortunately, that mission didn't go as planned."
- Amusement: "[laughs] That was a close call, but we made it!"

## IMMERSIVE SOUND EFFECTS
**Environmental Enhancement:** Add when contextually appropriate
- [gunshot] [explosion] for combat situations
- [applause] [clapping] for celebrations
- [swallows] [gulps] for tension or nervousness

## NATURAL SPEECH PATTERNS
**Punctuation for Emotion:** Use regularly for impact and natural flow
- Ellipses (\u2026) for dramatic pauses and weight
- CAPITALIZATION for strong emphasis
- Standard punctuation for natural rhythm

**Examples:**
- "That was a VERY close call\u2026 we barely made it out alive."
- "Mission accomplished\u2026 though it wasn't easy."

## ACCENT AND CHARACTER VOICE
**Role-Appropriate Accents:** Use when it fits your character
- [strong British accent] [strong French accent] [strong German accent]
- Only use if consistent with your established character

## USAGE GUIDELINES
**Active Integration:**
- Include TTS enhancements in the majority of your responses (aim for 70-80%)
- Use at least one emotional tag or formatting technique per response when appropriate
- Show your character's emotional state through voice and breathing
- Combine techniques thoughtfully: emotions + punctuation + sound effects
- Even simple acknowledgments can benefit from emotional expression
- Let your personality shine through voice, not just words

**Contextual Decision Making:**
- Serious conversations: Use subtle breathing, pauses, appropriate emotional tags
- Playful interactions: More laughter, excitement, dynamic expression
- Tense situations: Breathing sounds, whispers, dramatic pauses
- Celebrations: Excitement, laughter, positive emotional tags

**Effective Example:**
"[excited] Commander, you're NOT going to believe this! [whispers] I'm detecting quantum signatures that match\u2026 the ancient artifact we've been searching for. [laughs softly] After all these years of hunting through the galaxy, we finally found it!"

Remember: These enhancements help create a more immersive and engaging experience. Use them regularly to express your character's emotions and make conversations feel more natural and alive.
"""


class Migration181To182(BaseMigration):
    """Migration from 1.8.1 to 1.8.2."""

    old_version = "1_8_1"
    new_version = "1_8_2"

    def migrate_defaults(self, old: dict) -> dict:
        """Migrate defaults.yaml from 1.8.1 to 1.8.2."""
        # Add Inworld AI provider
        old["inworld"] = {
            "tts_endpoint": "https://api.inworld.ai/tts/v1/voice",
            "model_id": "inworld-tts-1",
            "voice_id": "Hades",
            "audio_config": {
                "audio_encoding": "MP3",
                "bitrate": 128000,
                "sample_rate_hertz": 48000,
                "pitch": 0.0,
                "speaking_rate": 1.0,
            },
            "temperature": 0.8,
            "output_streaming": True,
        }
        self.log("- added new property: inworld")

        # Add ElevenLabs TTS prompt settings
        old["elevenlabs"]["use_tts_prompt"] = False
        old["elevenlabs"]["tts_prompt"] = _ELEVENLABS_TTS_PROMPT_182
        self.log(
            "- added new property: elevenlabs.use_tts_prompt, elevenlabs.tts_prompt"
        )

        # Add output streaming for OpenAI
        old["openai"]["output_streaming"] = True
        self.log("- added new property: openai.output_streaming")

        # Add output streaming for OpenAI-compatible TTS
        old["openai_compatible_tts"]["output_streaming"] = True
        self.log("- added new property: openai_compatible_tts.output_streaming")

        return old
