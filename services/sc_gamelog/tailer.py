"""Follows one environment's Game.log and cuts it into records.

Star Citizen writes a fresh Game.log on every launch and moves the old one to
logbackups. A log is recognized by its first line, which holds the launch
time, so a new launch is a new "generation" and the same log read again after
a restart keeps its generation. Everything that was already in the file when
the reader first saw it is history ("catching up"): it builds the state, but
nobody is told about it as if it just happened.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from services.sc_gamelog.reader import (
    REGEX_TIMEOUT_SECONDS,
    Instructions,
    Record,
    RecordAssembler,
    _pattern,
)

FIRST_LINE_BYTES = 512
CHUNK_BYTES = 256 * 1024
# The build number is in the log header.
HEADER_BYTES = 64 * 1024


class LogTail:
    def __init__(self, environment: str, path: Path, instructions: Instructions) -> None:
        self.environment = environment
        self.path = path
        self.instructions = instructions
        self.generation: str | None = None
        self.offset = 0
        self.history_end = 0
        self.found = False
        self.behind = False
        """True while the last poll stopped before the end of the file."""
        self.game_build: str | None = None
        self._first_line: bytes = b""
        self._assembler: RecordAssembler | None = None
        self._first_look = True

    def use_rules(self, instructions: Instructions) -> None:
        """New rules may frame records differently. Start a fresh assembler
        at the current position; a half-read record is dropped."""
        self.instructions = instructions
        if self._assembler is not None:
            self._assembler = RecordAssembler(instructions, self.offset)

    def poll(self) -> list[tuple[Record, bool]]:
        """Read what was added since the last poll. Returns records with a
        flag that is True for history (catching up)."""
        try:
            with self.path.open("rb") as stream:
                size = stream.seek(0, 2)
                stream.seek(0)
                first_line = stream.read(FIRST_LINE_BYTES).split(b"\n", 1)[0]
                self.found = True
                if size <= len(first_line):
                    return []  # The game is still writing the first line.
                if self.generation is None or size < self.offset or first_line != self._first_line:
                    self._start_generation(first_line, size)
                    stream.seek(0)
                    self.game_build = self._find_build(stream.read(HEADER_BYTES))
                stream.seek(self.offset)
                chunk = stream.read(CHUNK_BYTES)
        except FileNotFoundError:
            self.found = False
            self._first_look = False
            return []

        self.behind = self.offset + len(chunk) < size
        records = self._assembler.feed(chunk) if chunk else []
        self.offset += len(chunk)
        records += self._assembler.expire()
        return [(record, record.start < self.history_end) for record in records]

    def _find_build(self, header: bytes) -> str | None:
        pattern = self.instructions.data["framing"].get("game_build")
        if not pattern:
            return None
        try:
            match = _pattern(pattern).search(
                header.decode("utf-8", errors="replace"), timeout=REGEX_TIMEOUT_SECONDS
            )
        except TimeoutError:
            return None
        return match[1] if match else None

    def _start_generation(self, first_line: bytes, size: int) -> None:
        self.generation = hashlib.sha256(
            self.environment.encode() + b"\0" + first_line
        ).hexdigest()[:32]
        self._first_line = first_line
        self.offset = 0
        # Only the log that was there when the reader started is history. A
        # log that appears later is a game launch happening right now.
        self.history_end = size if self._first_look else 0
        self._first_look = False
        self._assembler = RecordAssembler(self.instructions, 0)
