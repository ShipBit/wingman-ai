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
    PitchShift,
    Distortion,
    
)
from api.interface import SoundConfig


# Credits to our community members @JaydiCodes and @Thaendril!
class SoundEffects(Enum):
    ROBOT = Pedalboard(
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

    RADIO = Pedalboard(
        [
        HighpassFilter(cutoff_frequency_hz=800),  # Slightly lower high-pass filter to cut off low frequencies
        LowpassFilter(cutoff_frequency_hz=4000),  # Slightly lower low-pass filter to cut off high frequencies
        Resample(target_sample_rate=8000),  # Lower resample rate to simulate radio bandwidth more closely
        Compressor(threshold_db=-18, ratio=6),  # Adjust compressor settings for a tighter dynamic range
        Gain(gain_db=83)  # Increase gain to ensure presence
        ]
    )
    INTERIOR_HELMET = Pedalboard(
        [
       HighpassFilter(cutoff_frequency_hz=100),  # Remove low-frequency rumble
    LowpassFilter(cutoff_frequency_hz=8000),  # Remove very high frequencies to reduce sibilance
    PitchShift(semitones=-10),  # Lower the pitch by 5 semitones for a female demonic effect / 12 = 1 full octive
    Distortion(drive_db=8),  # Add distortion for a gritty sound
    Chorus(rate_hz=1.5, depth=1.0, mix=0.8),  # Strong chorus effect for multiple voices
       Reverb(room_size=0.1, damping=0.5, dry_level=0.8, wet_level=0.2, width=0.5),  # Minimal reverb to reduce echo
    Compressor(threshold_db=-30, ratio=10),  # Apply compression to smooth out the sound
    Gain(gain_db=20)
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
