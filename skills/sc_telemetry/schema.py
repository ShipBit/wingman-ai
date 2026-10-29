"""The telemetry message classes, built at runtime from the bundled schema.

`schema.desc` is the serialized FileDescriptorSet of `sc_telemetry.proto` (rebuild it with
`python -m grpc_tools.protoc -Iskills/sc_telemetry --descriptor_set_out=skills/sc_telemetry/schema.desc
skills/sc_telemetry/sc_telemetry.proto`).
Building the classes from it, instead of shipping generated `_pb2` modules, keeps the skill independent of the
protobuf version Wingman happens to have: generated code refuses to load on a runtime version mismatch.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

try:
    from google.protobuf import descriptor_pb2, descriptor_pool, json_format, message_factory
except ImportError:  # no protobuf runtime
    descriptor_pb2 = descriptor_pool = json_format = message_factory = None

SCHEMA_FILE = Path(__file__).with_name("schema.desc")
PACKAGE = "sc.game.telemetry.v1"
STREAM_METHOD = f"/{PACKAGE}.GameTelemetryService/TelemetryStream"


@lru_cache(maxsize=1)
def message_classes() -> tuple[type, type]:
    """(TelemetryStreamRequest, TelemetryStreamResponse). Raises ImportError without protobuf."""
    if descriptor_pb2 is None:
        raise ImportError("protobuf is not available")
    files = descriptor_pb2.FileDescriptorSet.FromString(SCHEMA_FILE.read_bytes())
    pool = descriptor_pool.DescriptorPool()
    for file_proto in files.file:
        pool.Add(file_proto)
    request = pool.FindMessageTypeByName(f"{PACKAGE}.TelemetryStreamRequest")
    response = pool.FindMessageTypeByName(f"{PACKAGE}.TelemetryStreamResponse")
    if hasattr(message_factory, "GetMessageClass"):  # protobuf >= 4.21
        return message_factory.GetMessageClass(request), message_factory.GetMessageClass(response)
    factory = message_factory.MessageFactory(pool)  # older protobuf
    return factory.GetPrototype(request), factory.GetPrototype(response)


def to_dict(message) -> dict:
    """The frame as a dict with the schema's field names, the same shape the probe recordings use."""
    return json_format.MessageToDict(message, preserving_proto_field_name=True)
