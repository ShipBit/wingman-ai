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
    Distortion,
)


# Credits to Discord community member @psigen aka GH @JaydiCodes!
class SoundEffects(Enum):
    ROBOT = Pedalboard(
        [
            PitchShift(semitones=-1),  # nur leicht tiefer, damit weibliche Stimme erhalten bleibt
            Delay(delay_seconds=0.01, feedback=0.1, mix=0.1),  # noch dezenteres Echo
            Chorus(rate_hz=0.5, depth=0.5, mix=0.45, centre_delay_ms=2, feedback=0.2),  # mehr metallischer Charakter
            Reverb(room_size=0.01, dry_level=0.7, wet_level=0.2, freeze_mode=0.28, width=0.3),  # etwas mehr "metallisch"
            Distortion(drive_db=1),  # nur ganz leicht verzerren
            Gain(gain_db=-1),  # etwas lauter
        ]
    )
    RADIO = Pedalboard(
        [
            HighpassFilter(2000),  # oder höher
            LowpassFilter(2500),   # oder niedriger
            Resample(6000),  # oder ein anderer Wert
            Gain(gain_db=12),  # Erhöhe für mehr Gesamtlautstärke und Rauschen
            Compressor(threshold_db=-40, ratio=6, attack_ms=1, release_ms=50),
            Distortion(drive_db=0.3),  # Wert anpassen nach Bedarf
            Gain(gain_db=8),  # <--- Add extra gain after compression/distortion
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


def get_sound_effects_from_config(config: dict):
    sound_effects_config = config.get("sound", {}).get("effects", [])
    if not sound_effects_config or len(sound_effects_config) == 0:
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

    for effect_name in sound_effects_config:
        effect = mapping.get(effect_name)
        if effect:
            sound_effects.append(effect)
        else:
            print(f"Unknown sound effect: {effect_name}")

    return sound_effects
