from services.audio.device_names import with_full_names

HOSTAPIS = [
    {"name": "MME"},
    {"name": "Windows DirectSound"},
    {"name": "Windows WASAPI"},
]


def _device(index, name, hostapi, inputs=2, outputs=0):
    return {
        "index": index,
        "name": name,
        "hostapi": hostapi,
        "max_input_channels": inputs,
        "max_output_channels": outputs,
    }


def _names(devices):
    return [d["name"] for d in devices]


def test_truncated_mme_name_gets_full_wasapi_name():
    devices = [
        _device(0, "Microfoon (Steam Streaming Micr", 0),
        _device(1, "Microfoon (Steam Streaming Microphone)", 2),
    ]
    assert _names(with_full_names(devices, HOSTAPIS)) == [
        "Microfoon (Steam Streaming Microphone)",
        "Microfoon (Steam Streaming Microphone)",
    ]


def test_directsound_is_the_fallback():
    devices = [
        _device(0, "SteelSeries Alias Pro Input (St", 0),
        _device(1, "SteelSeries Alias Pro Input (SteelSeries Alias Pro)", 1),
    ]
    assert with_full_names(devices, HOSTAPIS)[0]["name"] == (
        "SteelSeries Alias Pro Input (SteelSeries Alias Pro)"
    )


def test_short_names_stay_as_they_are():
    devices = [
        _device(0, "Speakers", 0, inputs=0, outputs=2),
        _device(1, "Speakers (Realtek(R) Audio)", 2, inputs=0, outputs=2),
    ]
    assert with_full_names(devices, HOSTAPIS)[0]["name"] == "Speakers"


def test_ambiguous_prefix_keeps_truncated_name():
    devices = [
        _device(0, "Microfoon (Steam Streaming Micr", 0),
        _device(1, "Microfoon (Steam Streaming Microphone)", 2),
        _device(2, "Microfoon (Steam Streaming Microphone 2)", 2),
    ]
    assert with_full_names(devices, HOSTAPIS)[0]["name"] == (
        "Microfoon (Steam Streaming Micr"
    )


def test_direction_must_match():
    devices = [
        _device(0, "Headset Earphone (HyperX Cloud ", 0, inputs=2, outputs=0),
        _device(1, "Headset Earphone (HyperX Cloud II)", 2, inputs=0, outputs=2),
    ]
    assert with_full_names(devices, HOSTAPIS)[0]["name"] == (
        "Headset Earphone (HyperX Cloud "
    )


def test_input_list_is_not_modified():
    devices = [
        _device(0, "Microfoon (Steam Streaming Micr", 0),
        _device(1, "Microfoon (Steam Streaming Microphone)", 2),
    ]
    with_full_names(devices, HOSTAPIS)
    assert devices[0]["name"] == "Microfoon (Steam Streaming Micr"
