from enum import Enum
from pedalboard import (
    Compressor,
    HighpassFilter,
    LowpassFilter,
    PeakFilter,
    Pedalboard,
    Chorus,
    PitchShift,
    Resample,
    Reverb,
    Delay,
    Gain,
)
from api.interface import SoundConfig


# Credits to Discord community member @psigen aka GH @JaydiCodes!
class SoundEffects(Enum):
    ROBOT = Pedalboard(
        [
            PitchShift(semitones=-1),
            Delay(delay_seconds=0.01, feedback=0.5, mix=0.2),
            Chorus(rate_hz=0.5, depth=0.8, mix=0.5, centre_delay_ms=2, feedback=0.3),
            Reverb(
                room_size=0.05, dry_level=0.5, wet_level=0.5, freeze_mode=0.5, width=0.3
            ),
            Gain(gain_db=8),
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
    INTERIOR_HELMET = Pedalboard(
        [
            PeakFilter(1000, 6, 2),
            Delay(delay_seconds=0.01, mix=0.02),
            Reverb(
                room_size=0.01,
                damping=0.9,
                dry_level=0.8,
                wet_level=0.2,
                freeze_mode=1,
                width=0.05,
            ),
        ]
    )
    INTERIOR_SMALL = Pedalboard(
        [
            Delay(delay_seconds=0.03, mix=0.05),
            Reverb(
                room_size=0.03, damping=0.7, dry_level=0.7, wet_level=0.3, width=0.1
            ),
        ]
    )
    INTERIOR_MEDIUM = Pedalboard(
        [
            Delay(delay_seconds=0.09, mix=0.07),
            Reverb(
                room_size=0.05, damping=0.6, dry_level=0.6, wet_level=0.4, width=0.2
            ),
        ]
    )
    INTERIOR_LARGE = Pedalboard(
        [
            Delay(delay_seconds=0.2, mix=0.1),
            Reverb(room_size=0.2, dry_level=0.5, wet_level=0.5, width=0.5),
        ]
    )


def get_sound_effects(config: SoundConfig):
    if config is None or not config.effects or len(config.effects) == 0:
        return []

    sound_effects = []

    mapping = {
        "ROBOT": SoundEffects.ROBOT.value,
        "RADIO": SoundEffects.RADIO.value,
        "INTERIOR_HELMET": SoundEffects.INTERIOR_HELMET.value,
        "INTERIOR_SMALL": SoundEffects.INTERIOR_SMALL.value,
        "INTERIOR_MEDIUM": SoundEffects.INTERIOR_MEDIUM.value,
        "INTERIOR_LARGE": SoundEffects.INTERIOR_LARGE.value,
    }

    for effect in config.effects:
        effect_name = effect.value
        effect = mapping.get(effect_name)
        if effect:
            sound_effects.append(effect)

    return sound_effects
