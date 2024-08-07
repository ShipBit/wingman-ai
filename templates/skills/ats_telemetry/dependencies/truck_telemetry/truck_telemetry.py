from multiprocessing.shared_memory import SharedMemory
from .telemetry_version import v1_10, v1_12

_mem = None
_telemetry_sdk_version = None

def init():
    global _mem, _telemetry_sdk_version
    _mem = SharedMemory(name="Local\\SCSTelemetry", create=False)
    for version in (v1_10, v1_12):
        if (version.is_same_version(_mem.buf)):
            _telemetry_sdk_version = version
            break
    if _telemetry_sdk_version == None:
        raise Exception("Not support this telemetry sdk version")

def get_data():
    return _telemetry_sdk_version.parse_data(_mem.buf)

def get_version_number():
    if _telemetry_sdk_version != None:
        return _telemetry_sdk_version.get_version_number()
    else:
        return 0

def deinit():
    global _mem, _telemetry_sdk_version
    if _mem != None:
        _mem.close()
        _mem = None
    _telemetry_sdk_version = None
