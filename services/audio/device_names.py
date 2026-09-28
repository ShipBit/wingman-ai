"""Full device names for the MME devices the client lists.

Windows MME cuts device names to 31 characters (MAXPNAMELEN is 32 including
the terminating null), so "Microphone (Steam Streaming Microphone)" arrives as
"Microphone (Steam Streaming Mic". WASAPI and DirectSound report the same
device with its full name. We look the full name up there, for display only:
settings still store the raw MME name, so saved device choices keep matching.
"""

MME_NAME_LIMIT = 31

# Host APIs to take full names from, best first.
_FULL_NAME_HOSTAPIS = ("Windows WASAPI", "Windows DirectSound")


def _direction(device: dict) -> tuple[bool, bool]:
    return device["max_input_channels"] > 0, device["max_output_channels"] > 0


def with_full_names(devices: list[dict], hostapis: list[dict]) -> list[dict]:
    """Return copies of `devices` where truncated MME names are replaced by the
    full name another host API reports for the same device.

    A name is only replaced when exactly one longer name with the same prefix
    and direction exists, so two devices sharing their first 31 characters
    keep the truncated name instead of getting swapped.
    """
    hostapi_names = {i: api["name"] for i, api in enumerate(hostapis)}
    mme = next((i for i, name in hostapi_names.items() if name == "MME"), None)

    result = [dict(device) for device in devices]
    if mme is None:
        return result

    for device in result:
        name = device["name"]
        if device["hostapi"] != mme or len(name) < MME_NAME_LIMIT:
            continue

        for api_name in _FULL_NAME_HOSTAPIS:
            candidates = {
                other["name"]
                for other in devices
                if hostapi_names.get(other["hostapi"]) == api_name
                and _direction(other) == _direction(device)
                and len(other["name"]) > len(name)
                and other["name"].startswith(name)
            }
            if len(candidates) == 1:
                device["name"] = candidates.pop()
                break
            if candidates:
                break

    return result
