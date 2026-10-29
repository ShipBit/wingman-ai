"""Helpers for the Star Citizen Telemetry tests: recorded moments, a replay, the skill and a fake game.

The moments in sc_telemetry_fixtures/ were cut from live field tests (Star Citizen 4.10.2, 2026-10-26 to
2026-10-28): one line per frame, {"t": unix time, "frame": the frame as JSON}.
"""

import gzip
import json
from concurrent import futures
from os import path
from types import SimpleNamespace

import grpc
import yaml
from google.protobuf.json_format import ParseDict

from api.interface import SkillConfig
from skills.sc_telemetry.handler import Handler, Thresholds
from skills.sc_telemetry.schema import message_classes
from tests.support import REPO_ROOT

FIXTURES = path.join(path.dirname(__file__), "sc_telemetry_fixtures")
CONFIG = path.join(REPO_ROOT, "skills", "sc_telemetry", "default_config.yaml")


def load_frames(name: str) -> list[tuple[float, dict]]:
    with gzip.open(path.join(FIXTURES, f"{name}.gz"), "rt", encoding="utf-8") as handle:
        return [(row["t"], row["frame"]) for row in map(json.loads, handle)]


def replay(frames: list, thresholds: Thresholds | None = None):
    handler = Handler()
    events, states = [], []
    for t, frame in frames:
        events.extend(handler.update(frame, t, thresholds or Thresholds()))
        states.append((t, handler.state))
    return handler, events, states


def ids(events) -> list[str]:
    return [event.id for event in events]


def make_skill(settings: dict):
    """The skill with its settings read from `settings` (missing keys fall back to the skill's defaults)."""
    from skills.sc_telemetry.main import SC_Telemetry

    with open(CONFIG, encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    skill = SC_Telemetry(SkillConfig(**raw), SimpleNamespace(), SimpleNamespace(name="Computer"))
    skill.retrieve_custom_property_value = lambda key, errors: settings.get(key)
    skill.logged = []
    skill.log = SimpleNamespace(info=lambda msg, **_: skill.logged.append(msg),
                                warning=lambda msg, **_: skill.logged.append(msg))
    return skill


def serve(frames: list[dict]):
    """A fake game on a free local port: streams the given frames, then ends the call."""
    request_cls, response_cls = message_classes()

    def stream(request, context):
        for frame in frames:
            yield ParseDict(frame, response_cls())

    handler = grpc.method_handlers_generic_handler("sc.game.telemetry.v1.GameTelemetryService", {
        "TelemetryStream": grpc.unary_stream_rpc_method_handler(
            stream, request_deserializer=request_cls.FromString,
            response_serializer=lambda m: m.SerializeToString())})
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
    server.add_generic_rpc_handlers((handler,))
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    return server, port
