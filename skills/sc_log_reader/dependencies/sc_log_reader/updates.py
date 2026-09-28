"""Validated JSON staging, next-process activation and offline recovery."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from contextlib import contextmanager
from http.client import HTTPException
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .host_boundary import (
    WindowsBoundary,
    assert_standalone_available,
    capture_boundary,
    validate_boundary,
)
from .reader import (
    MAX_PACKAGE_BYTES,
    InstructionError,
    Instructions,
    Reader,
    ReaderUpgradeRequired,
    bundled_bytes,
)


class UpdateError(ValueError):
    pass


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def validate_url(url):
    try:
        p = urlsplit(url)
        if (
            p.scheme != "https"
            or p.hostname != "raw.githubusercontent.com"
            or p.port not in (None, 443)
            or p.username
            or p.password
            or p.query
            or p.fragment
            or len(p.path.split("/")) < 5
            or not p.path.endswith(".json")
            or ".." in p.path.split("/")
        ):
            raise ValueError
    except ValueError as exc:
        raise UpdateError(
            "Use a raw.githubusercontent.com HTTPS JSON URL without credentials or query parameters"
        ) from exc
    return url


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise UpdateError(
            "Update redirects are not accepted; configure the direct raw JSON URL"
        )


def fetch_json(url):
    validate_url(url)
    req = Request(
        url, headers={"Accept": "application/json", "User-Agent": "SC-Log-Reader-2/0.1"}
    )
    with build_opener(_NoRedirect).open(req, timeout=10) as response:
        size = response.headers.get("Content-Length")
        if size and int(size) > MAX_PACKAGE_BYTES:
            raise UpdateError("Update exceeds size limit")
        data = response.read(MAX_PACKAGE_BYTES + 1)
    if len(data) > MAX_PACKAGE_BYTES:
        raise UpdateError("Update exceeds size limit")
    return data


def atomic_write(path, raw):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def _lock(root):
    """OS lock releases on process exit; shared by host and approval CLI."""
    root.mkdir(parents=True, exist_ok=True)
    with (root / "update.lock").open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        until = time.monotonic() + 2
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if time.monotonic() > until:
                    raise UpdateError(
                        "Another instruction update is in progress"
                    ) from exc
                time.sleep(0.02)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class UpdateManager:
    def __init__(self, root, url=None, *, fetch=fetch_json, boundary_provider=None):
        self.root = Path(root)
        self.url = validate_url(url) if url else None
        self.fetch = fetch
        self.running = None
        self.boundary_provider = boundary_provider or WindowsBoundary()
        self.activation_notice = None
        self.baseline = Instructions.load(bundled_bytes())
        self.base_digest = digest(self.baseline.raw)
        self.source_generation = None
        if self.url:
            # An explicit new manager selects configuration once. Later reads,
            # actions and download completions must never reselect an old URL.
            with _lock(self.root):
                m = self._manifest()
                if m.get("source_url") != self.url:
                    if m.get("source_url"):
                        m.update(candidate=None, staged=None, skipped=None)
                        m["notice"] = (
                            "Update publisher changed; downloaded candidates and scheduled changes "
                            "were cancelled. Updates will be checked against the new publisher."
                        )
                    m.update(
                        source_url=self.url,
                        source_generation=m.get("source_generation", 0) + 1,
                        candidate_source_url=None,
                        staged_source_url=None,
                        staged_kind=None,
                    )
                    self._save(m)
                self.source_generation = m["source_generation"]

    def _initial(self):
        return {
            "active": self.base_digest,
            "previous": None,
            "candidate": None,
            "staged": None,
            "highest_revision": self.baseline.revision,
            "revisions": {str(self.baseline.revision): self.base_digest},
            "source_url": None,
            "source_generation": 0,
            "candidate_source_url": None,
            "staged_source_url": None,
            "staged_kind": None,
            "rejected_revisions": [],
            "recovery_selection": "automatic",
        }

    def _manifest(self):
        p = self.root / "manifest.json"
        if not p.exists():
            return self._initial()
        try:
            if p.stat().st_size > 65536:
                raise ValueError
            value = json.loads(p.read_bytes())
            if (
                not isinstance(value, dict)
                or not {
                    "active",
                    "previous",
                    "candidate",
                    "staged",
                    "highest_revision",
                    "revisions",
                }
                <= value.keys()
            ):
                raise ValueError
            for k in ("active", "previous", "candidate", "staged"):
                if value[k] is not None and not re.fullmatch(r"[a-f0-9]{64}", value[k]):
                    raise ValueError
            if type(value["highest_revision"]) is not int or not isinstance(
                value["revisions"], dict
            ):
                raise ValueError
            rejected = value.get("rejected_revisions", [])
            if (
                not isinstance(rejected, list)
                or len(rejected) > 128
                or any(type(r) is not int or r < 1 for r in rejected)
                or value.get("recovery_selection", "automatic")
                not in ("automatic", "restore_previous")
            ):
                raise ValueError
            return self._reconcile_source(value)
        except (ValueError, TypeError, OSError):
            initial = self._initial()
            initial["error"] = "Invalid update manifest; using bundled definitions"
            return initial

    def _reconcile_source(self, m):
        """Migrate legacy state and bind every pending download to its publisher.

        A source-less manager is an offline local review of the recorded source;
        it is not a request to remove that source. Never infer legacy provenance.
        Caller holds the manifest lock.
        """
        before = dict(m)
        source = m.get("source_url")
        if source:
            validate_url(source)
        for name in ("candidate_source_url", "staged_source_url"):
            if m.get(name):
                validate_url(m[name])
        generation = m.get("source_generation", 0)
        if type(generation) is not int or generation < 0:
            raise ValueError("Invalid publisher generation")
        unknown_candidate = m["candidate"] and (
            not source or m.get("candidate_source_url") != source
        )
        unknown_stage = m["staged"] and (
            m.get("staged_kind") not in ("update", "rollback")
            or (
                m.get("staged_kind") == "update"
                and (not source or m.get("staged_source_url") != source)
            )
        )
        if unknown_candidate or unknown_stage:
            m.update(candidate=None, staged=None, skipped=None)
            m["notice"] = (
                "Pending instructions had missing or mismatched publisher provenance "
                "and were cancelled. Download them again from the configured publisher."
            )
        m.update(source_url=source, source_generation=generation)
        if not m["candidate"]:
            m["candidate_source_url"] = None
        if not m["staged"]:
            m.update(staged_source_url=None, staged_kind=None)
        if m != before:
            self._save(m)
        return m

    def _assert_source(self, m):
        if self.url and (
            self.url != m.get("source_url")
            or self.source_generation != m.get("source_generation")
        ):
            raise UpdateError(
                "Update publisher configuration changed; reopen the review with the current configuration"
            )

    @staticmethod
    def _assert_review(m, generation):
        if generation is not None and generation != m.get("source_generation"):
            raise UpdateError(
                "Publisher configuration changed since review; reopen the review"
            )

    def _save(self, m):
        if not m.get("staged"):
            m["staged_boundary"] = None
        raw = json.dumps(m, separators=(",", ":")).encode()
        if len(raw) > 65536:
            raise UpdateError("Update manifest exceeds 64 KiB; change was not saved")
        atomic_write(self.root / "manifest.json", raw)

    def _read(self, key):
        if key == self.base_digest:
            return self.baseline
        if not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{64}", key):
            raise UpdateError("Invalid instruction digest")
        try:
            with (self.root / "objects" / (key + ".json")).open("rb") as stream:
                raw = stream.read(MAX_PACKAGE_BYTES + 1)
            if digest(raw) != key:
                raise UpdateError("Stored instruction digest mismatch")
            return Instructions.load(raw)
        except (OSError, InstructionError) as exc:
            raise UpdateError("Stored instructions are missing or invalid") from exc

    @staticmethod
    def _smoke(instructions):
        """Engine-owned historical compatibility checks, not publisher claims.

        These catch gross semantic breakage; passing is not build qualification.
        """
        reader = Reader(instructions)
        cases = [
            (
                "<2026-09-16T12:00:00Z> User Login Success Handle[SmokePlayer]",
                "user_login",
                {"player_name": "SmokePlayer"},
            ),
            (
                '<2026-09-16T12:00:00Z> <SHUDEvent> Added notification "Awarded 500 aUEC:" [14] to queue.',
                "reward_earned",
                {"amount": "500", "currency": "aUEC"},
            ),
        ]
        for text, kind, expected in cases:
            event = reader.parse(text)
            if (
                event is None
                or event.errors
                or event.event_type != kind
                or any(event.fields.get(k) != v for k, v in expected.items())
            ):
                raise UpdateError(
                    "Instruction compatibility smoke test failed: " + kind
                )

    def status(self):
        with _lock(self.root):
            m = self._manifest()
            out = {
                "active_sha256": m["active"],
                "staged_sha256": m["staged"],
                "source_configured": bool(self.url or m.get("source_url")),
                "source_url": m.get("source_url"),
                "source_generation": m.get("source_generation"),
                "candidate_source_url": m.get("candidate_source_url"),
                "staged_source_url": m.get("staged_source_url"),
                "staged_kind": m.get("staged_kind"),
                "runtime_directory": str(self.root.parent.resolve()),
                "activation_notice": self.activation_notice,
                "staged_boundary": m.get("staged_boundary"),
                "rejected_revisions": m.get("rejected_revisions", []),
                "recovery_selection": m.get("recovery_selection", "automatic"),
            }
            try:
                active = self._read(m["active"])
                out.update(active_version=active.version, active_revision=active.revision)
                if m["staged"]:
                    staged = self._read(m["staged"])
                    out.update(staged_version=staged.version, staged_revision=staged.revision)
                if m["candidate"]:
                    c = self._read(m["candidate"])
                    out.update(
                        candidate_version=c.version,
                        sha256=m["candidate"],
                        release_notes=c.data["release_notes"],
                        minimum_reader_version=c.data.get(
                            "minimum_reader_version", "0.1.0"
                        ),
                        verified_game_builds=c.data["verified_game_builds"],
                        skipped=m.get("skipped") == m["candidate"],
                    )
            except UpdateError as exc:
                out["error"] = str(exc)
            target = m["previous"] or self.base_digest
            try:
                rollback = self._read(target)
                self._smoke(rollback)
                if rollback.revision in m.get("rejected_revisions", []):
                    raise UpdateError("Previous revision was rejected")
            except UpdateError:
                target, rollback = self.base_digest, self.baseline
                out["rollback_fallback_reason"] = (
                    "Previous instructions unavailable; bundled definitions selected"
                )
            out.update(rollback_sha256=target, rollback_version=rollback.version)
            if "notice" in m:
                out["notice"] = m["notice"]
            if "error" in m:
                out["error"] = m["error"]
            if self.running:
                out["running_version"] = self.running.version
            return out

    def host_startup(self, lease):
        """Pin one decision for this process, including a no-stage decision."""

        def choose():
            chosen = self._startup(host=True)
            return chosen, self.activation_notice

        self.running, self.activation_notice = lease.pin(choose)
        return self.running

    def startup(self, *, standalone_owner=None):
        if standalone_owner is None:
            assert_standalone_available(self.root.parent)
        else:
            standalone_owner.assert_held(self.root.parent)
        return self._startup(host=False)

    def _host_eligible(self, m):
        try:
            identity = self.boundary_provider.identity()
        except OSError:
            identity = None
        pid = identity[0] if identity and len(identity) == 2 else None
        valid_identity = (
            type(pid) is int
            and pid > 0
            and type(identity[1]) is int
            and identity[1] > 0
        )
        active_boundary = m.get("active_boundary")
        if active_boundary is not None:
            try:
                validate_boundary(active_boundary)
            except ValueError as exc:
                raise UpdateError(
                    "Invalid active activation boundary; restart cannot qualify this manifest"
                ) from exc
            if active_boundary["kind"] == "unresolved":
                recovered = capture_boundary(self.boundary_provider)
                if recovered["kind"] == "unresolved":
                    raise UpdateError(
                        "Active instruction process snapshot remains unavailable; "
                        "a later successful snapshot and another Wingman restart are required"
                    )
                # Standalone promotion can carry an unresolved approval fence.
                # Commit its conservative recovery even though this startup is
                # refused; only a later process outside this census may load it.
                m["active_boundary"] = recovered
                self._save(m)
                raise UpdateError(
                    "Active instruction process snapshot recovered; restart Wingman"
                )
            if not valid_identity or pid in active_boundary["pids"]:
                raise UpdateError(
                    "Active instructions require a new Wingman process; restart Wingman"
                )
        if not m["staged"]:
            return False
        boundary = m.get("staged_boundary")
        if boundary is not None:
            try:
                validate_boundary(boundary)
            except ValueError as exc:
                raise UpdateError(
                    "Invalid staged activation boundary; review and approve again"
                ) from exc
        if boundary is None or boundary["kind"] == "unresolved":
            m["staged_boundary"] = capture_boundary(self.boundary_provider)
            self.activation_notice = "Update process snapshot unavailable; an additional Wingman restart may be required."
            return False
        if not valid_identity or pid in boundary["pids"]:
            self.activation_notice = (
                "Scheduled instructions deferred until a new Wingman process startup."
            )
            return False
        return True

    def _startup(self, *, host):
        # Calling this again on a running service must never hot-apply a stage.
        if self.running is not None:
            return self.running
        with _lock(self.root):
            # Retain this engine's bundled fallback across future engine upgrades.
            atomic_write(
                self.root / "objects" / (self.base_digest + ".json"), self.baseline.raw
            )
            m = self._manifest()
            self._assert_source(m)
            eligible = self._host_eligible(m) if host else True
            target = (m["staged"] if eligible else None) or m["active"]
            try:
                chosen = self._read(target)
                self._smoke(chosen)
                if eligible and m["staged"] and target != m["active"]:
                    previous = m["active"]
                    try:
                        self._read(previous)
                    except UpdateError:
                        previous = self.base_digest
                    m.update(
                        previous=None if m.get("staged_kind") == "rollback" else previous,
                        active=target,
                        staged=None,
                        active_boundary=m.get("staged_boundary"),
                    )
                    m.pop("error", None)
                if eligible and m["staged"] == m["active"]:
                    m["staged"] = None
                if m["candidate"] == m["active"]:
                    m["candidate"] = None
            except UpdateError as exc:
                m["error"] = str(exc)
                self._reject_key(m, target)
                if m["candidate"] == target:
                    m["candidate"] = None
                chosen = None
                for fallback in (m["active"], m["previous"], self.base_digest):
                    try:
                        valid = self._read(fallback)
                        self._smoke(valid)
                        chosen = valid
                        m["active"] = fallback
                        break
                    except UpdateError:
                        continue
                m["staged"] = None
                if chosen is None:
                    raise UpdateError(
                        "No usable instruction fallback is available"
                    ) from exc
            if not m["candidate"]:
                m["candidate_source_url"] = None
            if not m["staged"]:
                m.update(staged_source_url=None, staged_kind=None)
            self._save(m)
            self.running = chosen
            return chosen

    def check(self, *, automatic=False):
        if not self.url:
            return {"status": "not_configured"}
        with _lock(self.root):
            m = self._manifest()
            self._assert_source(m)
            if automatic and m.get("staged_kind") == "rollback":
                return {"status": "rollback_pending"}
        try:
            raw = self.fetch(self.url)
            candidate = Instructions.load(raw)
            self._smoke(candidate)
        except ReaderUpgradeRequired as exc:
            return {"status": "reader_upgrade_required", "reason": str(exc)}
        except (OSError, ValueError, HTTPException) as exc:
            raise UpdateError(
                "Could not fetch or validate instruction update: " + str(exc)
            ) from exc
        key = digest(raw)
        with _lock(self.root):
            m = self._manifest()
            self._assert_source(m)
            known = m["revisions"].get(str(candidate.revision))
            if known and known != key:
                raise UpdateError("Published content changed without a new revision")
            if candidate.revision in m.get("rejected_revisions", []):
                return {"status": "rejected", "revision": candidate.revision,
                        "version": candidate.version}
            if automatic and m.get("staged_kind") == "rollback":
                return {"status": "rollback_pending"}
            active = self._read(m["active"])
            if (
                candidate.revision <= active.revision
                or candidate.revision < m["highest_revision"]
            ):
                return {"status": "up_to_date", "version": active.version}
            atomic_write(self.root / "objects" / (key + ".json"), raw)
            m.update(
                candidate=key,
                candidate_source_url=self.url,
                highest_revision=max(candidate.revision, m["highest_revision"]),
            )
            m["revisions"][str(candidate.revision)] = key
            # Retain bounded revision history; never lower the highest revision.
            m["revisions"] = dict(
                sorted(m["revisions"].items(), key=lambda x: int(x[0]))[-128:]
            )
            status = "skipped" if m.get("skipped") == key else "available"
            if automatic and status == "available":
                if m["staged"] != key or m.get("staged_kind") != "update":
                    self._stage_update(m, key)
                status = "staged_for_next_startup"
            self._save(m)
        return {
            "status": status,
            "version": candidate.version,
            "revision": candidate.revision,
            "sha256": key,
            "release_notes": candidate.data["release_notes"],
            "verified_game_builds": candidate.data["verified_game_builds"],
        }

    def check_automatically(self):
        """Host-owned download and staging; never hot-reload running instructions."""
        return self.check(automatic=True)

    def _stage_update(self, m, key):
        m.update(
            staged=key,
            staged_source_url=m["candidate_source_url"],
            staged_kind="update",
            staged_boundary=capture_boundary(self.boundary_provider),
        )

    @staticmethod
    def _reject_key(m, key):
        rejected = set(m.get("rejected_revisions", []))
        rejected.update(int(r) for r, value in m["revisions"].items() if value == key)
        m["rejected_revisions"] = sorted(rejected)[-128:]

    def approve(self, sha256, *, source_url=None, source_generation=None):
        """Call only from a human-controlled CLI/UI, never an LLM tool."""
        with _lock(self.root):
            m = self._manifest()
            self._assert_source(m)
            if source_generation is not None and source_generation != m.get(
                "source_generation"
            ):
                raise UpdateError(
                    "Publisher configuration changed since review; review the current candidate again"
                )
            if sha256 == m["active"]:
                return {"status": "already_active", "sha256": sha256}
            if not m["candidate"] or sha256 != m["candidate"]:
                raise UpdateError(
                    "Approval does not match the current reviewed candidate"
                )
            if source_url is not None and source_url != m.get("candidate_source_url"):
                raise UpdateError(
                    "Publisher changed since review; review the current candidate again"
                )
            candidate = self._read(sha256)
            if candidate.revision in m.get("rejected_revisions", []):
                raise UpdateError("This revision was rejected; wait for a newer revision")
            self._smoke(candidate)
            self._stage_update(m, sha256)
            m.pop("skipped", None)
            self._save(m)
        return {"status": "staged_for_next_startup", "sha256": sha256}

    def skip(self, sha256, *, source_generation=None):
        """Human-controlled choice: suppress this digest, never future revisions."""
        with _lock(self.root):
            m = self._manifest()
            self._assert_source(m)
            self._assert_review(m, source_generation)
            if not m["candidate"] or sha256 != m["candidate"]:
                raise UpdateError("Skip does not match the reviewed candidate")
            m["skipped"] = sha256
            if m["staged"] == sha256:
                m.update(staged=None, staged_source_url=None, staged_kind=None)
            self._save(m)
        return {"status": "skipped", "sha256": sha256}

    def cancel(self, *, source_generation=None, expected_sha256=None):
        """Human-only cancellation; keep active and available instructions intact."""
        with _lock(self.root):
            m = self._manifest()
            self._assert_source(m)
            self._assert_review(m, source_generation)
            if expected_sha256 is not None and m["staged"] != expected_sha256:
                raise UpdateError(
                    "Scheduled change changed since review; reopen the review"
                )
            m.update(staged=None, staged_source_url=None, staged_kind=None)
            self._save(m)
        return {"status": "scheduled_change_cancelled"}

    def rollback(self, *, expected_sha256=None, source_generation=None):
        with _lock(self.root):
            m = self._manifest()
            self._assert_source(m)
            self._assert_review(m, source_generation)
            result = self._rollback(m, expected_sha256)
            self._save(m)
            return result

    def recover(self, selection):
        """Consume the human settings selection once, including across restarts."""
        if selection not in ("automatic", "restore_previous"):
            raise UpdateError("Unknown instruction recovery selection")
        with _lock(self.root):
            m = self._manifest()
            self._assert_source(m)
            if m.get("recovery_selection", "automatic") == selection:
                return {"status": "unchanged"}
            result = (
                self._rollback(m) if selection == "restore_previous"
                else {"status": "recovery_control_reset"}
            )
            m["recovery_selection"] = selection
            self._save(m)
            return result

    def _rollback(self, m, expected_sha256=None):
        target = m["previous"] or self.base_digest
        reason = None
        try:
            previous = self._read(target)
            self._smoke(previous)
            if previous.revision in m.get("rejected_revisions", []):
                raise UpdateError("Previous revision was rejected")
        except UpdateError:
            target = self.base_digest
            self._smoke(self.baseline)
            reason = "Previous instructions unavailable; current bundled definitions selected"
        if expected_sha256 is not None and expected_sha256 != target:
            raise UpdateError(
                "Rollback target changed since review; review the current target again"
            )
        # Reject both the version being abandoned and any update waiting to
        # replace it, so a concurrent/later check cannot undo recovery.
        for key in (m["active"], m["staged"], m["candidate"]):
            if key and key != target:
                self._reject_key(m, key)
        m.update(
            staged=target,
            staged_source_url=None,
            staged_kind="rollback",
            staged_boundary=capture_boundary(self.boundary_provider),
            candidate=None,
            candidate_source_url=None,
        )
        return {
            "status": "rollback_staged_for_next_startup",
            "sha256": target,
            "version": self._read(target).version,
            "fallback_reason": reason,
        }
