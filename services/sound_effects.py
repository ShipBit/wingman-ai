from enum import Enum
from pedalboard import (
    Compressor,
    HighpassFilter,
    LowpassFilter,
    Pedalboard,
    Chorus,
    PitchShift,
    Resample,
    Reverb,
    Delay,
    Gain,
)


# Credits to Discord community member @psigen!
class SoundEffects(Enum):
    ROBOT = Pedalboard(
        [
            PitchShift(semitones=-1),
            Delay(delay_seconds=0.01, feedback=0.5, mix=0.2),
            Chorus(rate_hz=0.5, depth=0.8, mix=0.5, centre_delay_ms=2, feedback=0.3),
            Reverb(
                room_size=0.05, dry_level=0.5, wet_level=0.5, freeze_mode=0.5, width=0.3
            ),
            Gain(gain_db=3),
        ]
    )
    RADIO = Pedalboard(
        [
            HighpassFilter(1000),
            LowpassFilter(5000),
            Resample(10000),
            Gain(gain_db=3),
            Compressor(threshold_db=-21, ratio=3.5, attack_ms=1, release_ms=50),
            Gain(gain_db=6),
        ]
    )
    INTERIOR_SMALL = Pedalboard(
        [
            Delay(delay_seconds=0.1, mix=0.9),
            Reverb(room_size=0.05, dry_level=0.5, wet_level=0.3, width=0.2),
        ]
    )


def get_sound_effects_from_config(config: dict):
    sound_effects_config = config.get("sound", {}).get("effects", [])
    if not sound_effects_config or len(sound_effects_config) == 0:
        return []

    sound_effects = []

    mapping = {
        "ROBOT": SoundEffects.ROBOT.value,
        "RADIO": SoundEffects.RADIO.value,
        "INTERIOR_SMALL": SoundEffects.INTERIOR_SMALL.value,
    }

    for effect_name in sound_effects_config:
        effect = mapping.get(effect_name)
        if effect:
            sound_effects.append(effect)
        else:
            print(f"Unknown sound effect: {effect_name}")

    return sound_effects
