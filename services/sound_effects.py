from enum import Enum
from pedalboard import (
    HighpassFilter,
    LowpassFilter,
    Pedalboard,
    Chorus,
    Resample,
    Reverb,
    Delay,
    Gain,
    Bitcrush,
    Compressor,
    Distortion,
)
from api.enums import SoundEffect
from api.interface import SoundConfig


# Credits to our community members @JaydiCodes and @Thaendril!
class SoundEffects(Enum):
    AI = Pedalboard(
        [
            Bitcrush(
                bit_depth=12
            ),  # Moderate bitcrusher effect for subtle digital tone
            Chorus(
                rate_hz=1.5, depth=0.6, mix=0.4, centre_delay_ms=10, feedback=0.2
            ),  # Smooth chorus for subtle modulation
            Reverb(
                room_size=0.1, dry_level=0.8, wet_level=0.2, freeze_mode=0.0, width=0.3
            ),  # Light reverb for slight spatial enhancement
            Delay(
                delay_seconds=0.01, feedback=0.1, mix=0.1
            ),  # Very subtle delay for slight echo
            Gain(
                gain_db=-1
            ),  # Careful with gain, it adds presence but can cause peaking.
        ]
    )

    LOW_QUALITY_RADIO = Pedalboard(
        [
            Distortion(drive_db=30),
            HighpassFilter(cutoff_frequency_hz=800),
            LowpassFilter(cutoff_frequency_hz=3400),
            Resample(target_sample_rate=8000),  # Lower resample rate for tinny effect
            Reverb(room_size=0.1, damping=0.3, wet_level=0.1, dry_level=0.9),
            Gain(gain_db=-17),
        ]
    )
    MEDIUM_QUALITY_RADIO = Pedalboard(
        [
            Distortion(drive_db=15),
            HighpassFilter(cutoff_frequency_hz=300),
            LowpassFilter(cutoff_frequency_hz=5000),
            Resample(target_sample_rate=16000),
            Reverb(room_size=0.01, damping=0.3, wet_level=0.1, dry_level=0.9),
            Compressor(threshold_db=-18, ratio=4),
            Gain(gain_db=4),
        ]
    )
    HIGH_END_RADIO = Pedalboard(
        [
            HighpassFilter(cutoff_frequency_hz=100),
            LowpassFilter(cutoff_frequency_hz=8000),  # Adjust cutoff to avoid conflicts
            Compressor(threshold_db=-10, ratio=2),
            Reverb(room_size=0.001, damping=0.3, wet_level=0.1, dry_level=0.9),
            Resample(target_sample_rate=44100),
            Gain(gain_db=2),
        ]
    )
    LOW_QUALITY_RADIO_GAIN_BOOST = Pedalboard(
        [
            Distortion(drive_db=30),
            HighpassFilter(cutoff_frequency_hz=800),
            LowpassFilter(cutoff_frequency_hz=3400),
            Resample(target_sample_rate=8000),  # Lower resample rate for tinny effect
            Reverb(room_size=0.1, damping=0.3, wet_level=0.1, dry_level=0.9),
            Gain(gain_db=70),
        ]
    )
    MEDIUM_QUALITY_RADIO_GAIN_BOOST = Pedalboard(
        [
            Distortion(drive_db=15),
            HighpassFilter(cutoff_frequency_hz=300),
            LowpassFilter(cutoff_frequency_hz=5000),
            Resample(target_sample_rate=16000),
            Reverb(room_size=0.01, damping=0.3, wet_level=0.1, dry_level=0.9),
            Compressor(threshold_db=-18, ratio=4),
            Gain(gain_db=82),
        ]
    )
    HIGH_END_RADIO_GAIN_BOOST = Pedalboard(
        [
            HighpassFilter(cutoff_frequency_hz=100),
            LowpassFilter(cutoff_frequency_hz=8000),  # Adjust cutoff to avoid conflicts
            Compressor(threshold_db=-10, ratio=2),
            Reverb(room_size=0.001, damping=0.3, wet_level=0.1, dry_level=0.9),
            Resample(target_sample_rate=44100),
            Gain(gain_db=30),
        ]
    )

    INTERIOR_SMALL = Pedalboard(
        [
            Delay(
                delay_seconds=0.03, mix=0.05
            ),  # Subtle delay to simulate room reflections
            Reverb(
                room_size=0.03, damping=0.7, dry_level=0.7, wet_level=0.3, width=0.1
            ),  # Reverb to enhance room effect
            Gain(gain_db=-3),  # Reduced to solve clipping
        ]
    )
    INTERIOR_MEDIUM = Pedalboard(
        [
            Delay(
                delay_seconds=0.05, mix=0.05
            ),  # Subtle delay to simulate room reflections
            Reverb(
                room_size=0.5, damping=0.5, dry_level=0.7, wet_level=0.3, width=0.5
            ),  # Reverb to enhance room effect
            Gain(gain_db=-3),  # Slight reduction in gain to prevent clipping
        ]
    )
    INTERIOR_LARGE = Pedalboard(
        [
            Delay(
                delay_seconds=0.07, mix=0.1
            ),  # Subtle delay to simulate large room reflections
            Reverb(
                room_size=0.7, damping=0.5, dry_level=0.7, wet_level=0.3, width=0.8
            ),  # Reverb to enhance large room effect
            Gain(gain_db=-3),  # Slight reduction in gain to prevent clipping
        ]
    )


def get_sound_effects(config: SoundConfig, use_gain_boost: bool = False):
    if config is None or not config.effects or len(config.effects) == 0:
        return []

    sound_effects = []

    mapping = {
        SoundEffect.AI.value: SoundEffects.AI.value,
        SoundEffect.LOW_QUALITY_RADIO.value: SoundEffects.LOW_QUALITY_RADIO.value,
        SoundEffect.MEDIUM_QUALITY_RADIO.value: SoundEffects.MEDIUM_QUALITY_RADIO.value,
        SoundEffect.HIGH_END_RADIO.value: SoundEffects.HIGH_END_RADIO.value,
        SoundEffect.LOW_QUALITY_RADIO.value
        + "_GAIN_BOOST": SoundEffects.LOW_QUALITY_RADIO_GAIN_BOOST.value,
        SoundEffect.MEDIUM_QUALITY_RADIO.value
        + "_GAIN_BOOST": SoundEffects.MEDIUM_QUALITY_RADIO_GAIN_BOOST.value,
        SoundEffect.HIGH_END_RADIO.value
        + "_GAIN_BOOST": SoundEffects.HIGH_END_RADIO_GAIN_BOOST.value,
        SoundEffect.INTERIOR_SMALL.value: SoundEffects.INTERIOR_SMALL.value,
        SoundEffect.INTERIOR_MEDIUM.value: SoundEffects.INTERIOR_MEDIUM.value,
        SoundEffect.INTERIOR_LARGE.value: SoundEffects.INTERIOR_LARGE.value,
    }

    for effect in config.effects:
        effect_name = effect.value
        if use_gain_boost and f"{effect_name}_GAIN_BOOST" in mapping:
            effect_name += "_GAIN_BOOST"
        effect = mapping.get(effect_name)
        if effect:
            sound_effects.append(effect)

    return sound_effects


def get_additional_layer_file(effect: SoundEffect):
    if effect == SoundEffect.LOW_QUALITY_RADIO:
        return "low_quality_radio.wav"
    elif effect == SoundEffect.MEDIUM_QUALITY_RADIO:
        return "Radio_Static.wav"
    return None
