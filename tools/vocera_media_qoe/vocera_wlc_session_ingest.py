#!/usr/bin/env python3
"""Pure, side-effect-light primitives for WLC capture-session SCP ingest.

The WLC SCP-pushes an exported EPC into ``<session>/incoming/``. The collector
must detect a *completed* upload, validate it is a real capture container, hash
it, and atomically promote it into ``<session>/pcaps/`` before registering and
parsing it. This module holds only the deterministic building blocks for that
flow -- file-stability decisions, capture-container magic-byte checks, hashing,
atomic moves, package-path parsing, and traversal guards -- so they can be unit
tested without a database or the Study Web service.

The database orchestration (artifact rows, capture registration, parser
execution) lives in Study Web, which owns the parser executor; this module is
imported by both Study Web and the tests. A small ``main`` is provided for a
non-mutating, no-database dry-run scan that is handy for operators debugging a
stuck upload.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator


# A WLC EPC export is a classic pcap or a pcapng file. We accept either by
# inspecting the leading bytes; we never trust the extension alone.
PCAP_MAGIC_NUMBERS: tuple[bytes, ...] = (
    b"\xa1\xb2\xc3\xd4",  # pcap, big-endian, microsecond timestamps
    b"\xd4\xc3\xb2\xa1",  # pcap, little-endian, microsecond timestamps
    b"\xa1\xb2\x3c\x4d",  # pcap, big-endian, nanosecond timestamps
    b"\x4d\x3c\xb2\xa1",  # pcap, little-endian, nanosecond timestamps
)
PCAPNG_SECTION_HEADER_BLOCK = b"\x0a\x0d\x0d\x0a"  # pcapng Section Header Block type

DEFAULT_ALLOWED_EXTENSIONS: frozenset[str] = frozenset({".pcap", ".pcapng", ".cap"})

# Sub-directory contract inside one session package.
INCOMING_SUBDIR = "incoming"
PCAPS_SUBDIR = "pcaps"

# Stability poll states returned by :func:`plan_ingest_decision`.
DECISION_WAIT_NEW = "wait_new"          # first time we have seen this file
DECISION_WAIT_CHANGED = "wait_changed"  # size/mtime changed since last poll
DECISION_WAIT_TOO_SOON = "wait_too_soon"  # unchanged, but not yet for long enough
DECISION_READY = "ready"                # unchanged for long enough; safe to ingest


def utc_now() -> datetime:
    """Return an aware UTC timestamp."""

    return datetime.now(timezone.utc)


def magic_bytes(source: "bytes | Path | str") -> bytes:
    """Return the leading 4 bytes of ``source`` (bytes pass through)."""

    if isinstance(source, (bytes, bytearray)):
        return bytes(source[:4])
    with open(source, "rb") as handle:
        return handle.read(4)


def looks_like_pcap(source: "bytes | Path | str") -> bool:
    """Return True when ``source`` starts with a pcap or pcapng magic number.

    Accepts a path or a raw byte string so callers and tests can validate either
    a file on disk or an in-memory fixture. A truncated/empty file is rejected.
    """

    head = magic_bytes(source)
    if len(head) < 4:
        return False
    return head in PCAP_MAGIC_NUMBERS or head == PCAPNG_SECTION_HEADER_BLOCK


def sha256_file(path: "Path | str", *, chunk_size: int = 1024 * 1024) -> str:
    """Return the hex SHA-256 of a file, streamed so large EPCs stay bounded."""

    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_signature(path: "Path | str") -> dict[str, int]:
    """Return the size/mtime signature used to detect an in-progress upload."""

    stat = os.stat(path)
    return {"size_bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)}


def is_within(root: "Path | str", candidate: "Path | str") -> bool:
    """Return True when ``candidate`` resolves inside ``root`` (traversal guard)."""

    root_resolved = Path(root).resolve(strict=False)
    candidate_resolved = Path(candidate).resolve(strict=False)
    try:
        candidate_resolved.relative_to(root_resolved)
        return True
    except ValueError:
        return False


def parse_session_rel(session_root: "Path | str", path: "Path | str") -> dict[str, str] | None:
    """Decompose a package path into ``study_id``/``session_id``/subdir/name.

    Returns ``None`` when ``path`` is not a four-part
    ``<root>/<study>/<session>/<subdir>/<name>`` file inside ``session_root`` so
    callers never act on a path outside the session package contract.
    """

    root = Path(session_root).resolve(strict=False)
    resolved = Path(path).resolve(strict=False)
    try:
        rel = resolved.relative_to(root)
    except ValueError:
        return None
    parts = rel.parts
    if len(parts) != 4:
        return None
    study_id, session_id, subdir, name = parts
    if not study_id or not session_id or not name:
        return None
    return {"study_id": study_id, "session_id": session_id, "subdir": subdir, "name": name}


def iter_incoming_pcaps(
    session_root: "Path | str",
    *,
    allowed_extensions: Iterable[str] = DEFAULT_ALLOWED_EXTENSIONS,
) -> Iterator[Path]:
    """Yield candidate capture files under ``<root>/*/*/incoming/`` only.

    The generic raw-file scanner deliberately ignores ``wlc-sessions/``; this
    scanner is the *only* path that looks at session packages, and it looks
    solely at ``incoming/`` -- never ``pcaps/`` (already promoted), ``cli/``,
    ``attempts/``, or anywhere else.
    """

    root = Path(session_root)
    if not root.is_dir():
        return
    allowed = {ext.lower() if ext.startswith(".") else f".{ext.lower()}" for ext in allowed_extensions}
    # <root>/<study>/<session>/incoming/<file>
    for incoming_dir in sorted(root.glob(f"*/*/{INCOMING_SUBDIR}")):
        if not incoming_dir.is_dir():
            continue
        for candidate in sorted(incoming_dir.iterdir()):
            try:
                if not candidate.is_file():
                    continue
            except OSError:
                continue
            if candidate.suffix.lower() not in allowed:
                continue
            if parse_session_rel(root, candidate) is None:
                continue
            yield candidate


def promoted_path(session_root: "Path | str", incoming_file: "Path | str") -> Path | None:
    """Return the stable ``pcaps/`` destination for an ``incoming/`` file."""

    info = parse_session_rel(session_root, incoming_file)
    if info is None or info["subdir"] != INCOMING_SUBDIR:
        return None
    root = Path(session_root).resolve(strict=False)
    return root / info["study_id"] / info["session_id"] / PCAPS_SUBDIR / info["name"]


def artifact_id_for(session_id: str, artifact_kind: str, source_name: str) -> str:
    """Return a deterministic artifact id so re-detection upserts one row.

    Keyed on the stable pre-hash identity (session + kind + filename) because the
    content hash is unknown until the upload completes. Identical-content dedup
    is enforced separately by a unique ``(capture_session_id, sha256)`` index.
    """

    raw = f"{session_id}\x00{artifact_kind}\x00{source_name}".encode("utf-8")
    return "wlcart_" + hashlib.sha256(raw).hexdigest()[:24]


def _elapsed_seconds(start: datetime | None, now: datetime) -> float | None:
    if start is None:
        return None
    return (now - start).total_seconds()


def plan_ingest_decision(
    *,
    prev_signature: dict[str, int] | None,
    prev_observed_at: datetime | None,
    current_signature: dict[str, int],
    now: datetime | None = None,
    min_gap_seconds: float,
) -> str:
    """Decide whether an incoming file is stable enough to ingest.

    Pure decision function driven by the *previous* observation (persisted by the
    caller) and the *current* on-disk signature. The collector polls once per
    timer tick, so two unchanged observations spaced ``min_gap_seconds`` apart
    mean the SCP upload has finished.

    Returns one of :data:`DECISION_WAIT_NEW`, :data:`DECISION_WAIT_CHANGED`,
    :data:`DECISION_WAIT_TOO_SOON`, or :data:`DECISION_READY`. The caller stores
    ``current_signature``/``now`` on the wait_new and wait_changed outcomes,
    leaves them untouched on wait_too_soon (so the stable interval keeps
    growing), and proceeds on ready.
    """

    moment = now or utc_now()
    if prev_signature is None:
        return DECISION_WAIT_NEW
    if current_signature != prev_signature:
        return DECISION_WAIT_CHANGED
    elapsed = _elapsed_seconds(prev_observed_at, moment)
    if elapsed is None:
        return DECISION_WAIT_NEW
    if elapsed < float(min_gap_seconds):
        return DECISION_WAIT_TOO_SOON
    return DECISION_READY


def is_stable(
    path: "Path | str",
    *,
    polls: int = 2,
    delay_seconds: float = 20.0,
    sleep=time.sleep,
) -> bool:
    """Return True when size+mtime are unchanged across ``polls`` reads.

    A synchronous fallback used by the dry-run CLI and tests. Production ingest
    uses the timer-cadence :func:`plan_ingest_decision` so the HTTP request does
    not block. ``sleep`` is injectable so tests run instantly.
    """

    if polls < 2:
        polls = 2
    try:
        previous = file_signature(path)
    except OSError:
        return False
    for _ in range(polls - 1):
        sleep(delay_seconds)
        try:
            current = file_signature(path)
        except OSError:
            return False
        if current != previous:
            return False
        previous = current
    return True


def atomic_move(src: "Path | str", dst: "Path | str") -> Path:
    """Atomically move ``src`` to ``dst`` (same-filesystem rename).

    ``incoming/`` and ``pcaps/`` are siblings in one session package, so they
    always share a filesystem and ``os.replace`` is atomic. The destination
    directory is created first; an existing destination is replaced.
    """

    src_path = Path(src)
    dst_path = Path(dst)
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    os.replace(src_path, dst_path)
    return dst_path


# ---------------------------------------------------------------------------
# Dry-run CLI: scan and report candidate decisions without touching anything.
# ---------------------------------------------------------------------------

def scan_report(
    session_root: "Path | str",
    *,
    min_gap_seconds: float = 20.0,
    allowed_extensions: Iterable[str] = DEFAULT_ALLOWED_EXTENSIONS,
) -> list[dict[str, Any]]:
    """Return a non-mutating report of incoming files and their readiness.

    This treats each file as freshly observed (no persisted history), so a file
    that is currently being written reports its raw signature for an operator to
    compare across two manual runs; it never claims a file is importable.
    """

    report: list[dict[str, Any]] = []
    for candidate in iter_incoming_pcaps(session_root, allowed_extensions=allowed_extensions):
        info = parse_session_rel(session_root, candidate) or {}
        try:
            signature = file_signature(candidate)
        except OSError as exc:
            report.append({"path": str(candidate), "error": str(exc)})
            continue
        report.append(
            {
                "path": str(candidate),
                "study_id": info.get("study_id"),
                "session_id": info.get("session_id"),
                "name": info.get("name"),
                "size_bytes": signature["size_bytes"],
                "mtime_ns": signature["mtime_ns"],
                "looks_like_pcap": looks_like_pcap(candidate),
            }
        )
    return report


def main(argv: "list[str] | None" = None) -> int:
    """Print a dry-run JSON scan of incoming session uploads (no DB writes)."""

    parser = argparse.ArgumentParser(
        description="Dry-run scan of WLC capture-session incoming/ uploads (no database writes).",
    )
    parser.add_argument(
        "--session-root",
        default="/var/lib/vocera-media-qoe/raw/wlc-sessions",
        help="Root directory holding <study>/<session> capture-session packages.",
    )
    parser.add_argument("--min-gap-seconds", type=float, default=20.0)
    args = parser.parse_args(sys.argv[1:] if argv is None else list(argv))
    report = scan_report(args.session_root, min_gap_seconds=args.min_gap_seconds)
    print(json.dumps({"session_root": str(args.session_root), "candidates": report}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
