"""The telemetry message classes, built at runtime from the bundled schema.

`schema.desc` is the serialized FileDescriptorSet of `sc_telemetry.proto` (rebuild it with
`python -m grpc_tools.protoc -Iservices/sc_telemetry --descriptor_set_out=services/sc_telemetry/schema.desc
services/sc_telemetry/sc_telemetry.proto`).
Building the classes from it, instead of shipping generated `_pb2` modules, keeps the service independent of the
protobuf version Wingman happens to have: generated code refuses to load on a runtime version mismatch.
The classes live in their own descriptor pool, so they never clash with another library's messages.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from google.protobuf import descriptor_pb2, descriptor_pool, json_format, message_factory

SCHEMA_FILE = Path(__file__).with_name("schema.desc")
PACKAGE = "sc.game.telemetry.v1"
SERVICE = f"{PACKAGE}.GameTelemetryService"
STREAM_METHOD = f"/{SERVICE}/TelemetryStream"


@lru_cache(maxsize=1)
def message_classes() -> tuple[type, type]:
    """(TelemetryStreamRequest, TelemetryStreamResponse)."""
    files = descriptor_pb2.FileDescriptorSet.FromString(SCHEMA_FILE.read_bytes())
    pool = descriptor_pool.DescriptorPool()
    for file_proto in files.file:
        pool.AddSerializedFile(file_proto.SerializeToString())
    request = pool.FindMessageTypeByName(f"{PACKAGE}.TelemetryStreamRequest")
    response = pool.FindMessageTypeByName(f"{PACKAGE}.TelemetryStreamResponse")
    return message_factory.GetMessageClass(request), message_factory.GetMessageClass(response)


def to_dict(message) -> dict:
    """The frame as a dict with the schema's field names. Fields at their default value (0, false, "") are left
    out, int64 values come as strings, and an enum value the schema does not know comes as its number."""
    return json_format.MessageToDict(message, preserving_proto_field_name=True)
