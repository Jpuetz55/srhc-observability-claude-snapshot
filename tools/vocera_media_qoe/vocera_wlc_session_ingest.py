#!/usr/bin/env python3
"""Pure, side-effect-light primitives for WLC capture-session SCP ingest.

The WLC SCP-pushes an exported EPC into ``<session>/incoming/``. The collector
must detect a *completed* upload, validate it is a real capture container, and
finalize it as a service-owned artifact in ``<session>/pcaps/`` before
registering and parsing it. This module holds only the deterministic building
blocks for that flow -- file-stability decisions, capture-container magic-byte
checks, hashing, owner-controlled finalization, package-path parsing, and
traversal guards -- so they can be unit tested without a database or the Study
Web service.

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
import shutil
import stat
import sys
import time
import uuid
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

# Structured finalization/quarantine categories persisted by Study Web. Keep the
# strings stable: operators, tests, and future reports refer to them directly.
FAIL_INVALID_MAGIC = "invalid_magic"
FAIL_TRUNCATED_CONTAINER = "truncated_container"
FAIL_SYMLINK_REJECTED = "symlink_rejected"
FAIL_HARDLINK_REJECTED = "hardlink_rejected"
FAIL_NOT_REGULAR_FILE = "not_regular_file"
FAIL_SIZE_LIMIT_EXCEEDED = "size_limit_exceeded"
FAIL_DISK_SPACE_INSUFFICIENT = "disk_space_insufficient"
FAIL_SOURCE_CHANGED = "source_changed_during_claim"
FAIL_PROMOTION_COPY_FAILED = "promotion_copy_failed"
FAIL_PROMOTION_HASH_MISMATCH = "promotion_hash_mismatch"
FAIL_CAPTURE_REGISTRATION_FAILED = "capture_registration_failed"
FAIL_PARSER_FAILED = "parser_failed"
FAIL_RETRY_LIMIT_REACHED = "retry_limit_reached"

SOURCE_QUARANTINE_REASONS = {
    FAIL_INVALID_MAGIC,
    FAIL_TRUNCATED_CONTAINER,
    FAIL_SYMLINK_REJECTED,
    FAIL_HARDLINK_REJECTED,
    FAIL_NOT_REGULAR_FILE,
    FAIL_SIZE_LIMIT_EXCEEDED,
    FAIL_SOURCE_CHANGED,
    FAIL_PROMOTION_HASH_MISMATCH,
}

DEFAULT_MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_MIN_FREE_BYTES = 512 * 1024 * 1024


class IngestFinalizationError(RuntimeError):
    """Structured failure raised while finalizing an SCP-uploaded EPC.

    ``category`` is intentionally machine-readable. Study Web stores it in
    artifact metadata so recovery and audit views can distinguish a bad upload
    (quarantine) from a transient service condition (retry/failure).
    """

    def __init__(self, category: str, message: str, *, metadata: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.category = category
        self.message = message
        self.metadata = metadata or {}


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
    solely at ``incoming/`` -- never ``pcaps/`` (already finalized), ``cli/``,
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

    This is retained for legacy tests and generic same-owner file moves. It is
    **not** the WLC EPC evidence finalization primitive because a rename from
    ``incoming/`` would preserve the SCP upload account's file ownership and
    mode. WLC EPC ingest must use :func:`finalize_upload_to_pcaps`.
    """

    src_path = Path(src)
    dst_path = Path(dst)
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    os.replace(src_path, dst_path)
    return dst_path


def _same_inode(left: os.stat_result, right: os.stat_result) -> bool:
    """Return true when two stat results describe the same filesystem object."""

    return int(left.st_dev) == int(right.st_dev) and int(left.st_ino) == int(right.st_ino)


def _same_claim_signature(left: os.stat_result, right: os.stat_result) -> bool:
    """Return true when an opened source still matches the claimed stable file."""

    return (
        _same_inode(left, right)
        and int(left.st_size) == int(right.st_size)
        and int(left.st_mtime_ns) == int(right.st_mtime_ns)
        and int(left.st_ctime_ns) == int(right.st_ctime_ns)
    )


def _open_no_follow(path: Path, flags: int, mode: int = 0o600) -> int:
    """Open ``path`` with ``O_NOFOLLOW`` and ``O_CLOEXEC`` where available."""

    open_flags = flags
    if hasattr(os, "O_NOFOLLOW"):
        open_flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        open_flags |= os.O_CLOEXEC
    return os.open(path, open_flags, mode)


def _fsync_directory(path: Path) -> None:
    """Best-effort fsync of a directory after final rename or unlink."""

    try:
        dir_fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _write_all(fd: int, data: bytes) -> None:
    """Write every byte in ``data`` to ``fd``."""

    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("short write while finalizing WLC EPC artifact")
        view = view[written:]


def finalize_upload_to_pcaps(
    src: "Path | str",
    dst: "Path | str",
    *,
    final_uid: int = 0,
    final_gid: int = 0,
    final_mode: int = 0o440,
    max_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
    min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
    chunk_size: int = 1024 * 1024,
    before_commit_hook: Any | None = None,
) -> dict[str, Any]:
    """Validate and finalize one stable ``incoming/`` EPC as trusted evidence.

    The WLC SCP account owns the uploaded file in ``incoming/``. A plain rename
    into ``pcaps/`` would preserve that owner and mode, allowing the upload
    account to modify finalized evidence. This function instead opens the
    source without following symlinks, rejects unsafe filesystem objects, copies
    bytes into a collector-created temporary file in ``pcaps/``, fsyncs the
    content, sets final ownership/mode, atomically renames the temp file into
    place, verifies the final SHA-256, and removes the original only when the
    path still points at the claimed source inode.

    Returns a JSON-serializable finalization summary. Raises
    :class:`IngestFinalizationError` with a stable ``category`` when the source
    should be quarantined or the finalization should be retried.
    """

    src_path = Path(src)
    dst_path = Path(dst)
    dst_dir = dst_path.parent
    tmp_path = dst_dir / f".{dst_path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}"
    src_fd: int | None = None
    tmp_fd: int | None = None

    try:
        try:
            source_lstat = os.lstat(src_path)
        except OSError as exc:
            raise IngestFinalizationError(FAIL_PROMOTION_COPY_FAILED, f"Could not lstat source upload: {exc}") from exc
        if stat.S_ISLNK(source_lstat.st_mode):
            raise IngestFinalizationError(FAIL_SYMLINK_REJECTED, "Incoming upload is a symlink; refusing to ingest.")
        if not stat.S_ISREG(source_lstat.st_mode):
            raise IngestFinalizationError(FAIL_NOT_REGULAR_FILE, "Incoming upload is not a regular file.")
        if int(source_lstat.st_nlink) != 1:
            raise IngestFinalizationError(FAIL_HARDLINK_REJECTED, "Incoming upload has multiple hard links.")
        if int(source_lstat.st_size) <= 0:
            raise IngestFinalizationError(FAIL_TRUNCATED_CONTAINER, "Incoming upload is empty.")
        if max_bytes > 0 and int(source_lstat.st_size) > int(max_bytes):
            raise IngestFinalizationError(
                FAIL_SIZE_LIMIT_EXCEEDED,
                f"Incoming upload exceeds the configured maximum size ({source_lstat.st_size} > {max_bytes}).",
                metadata={"size_bytes": int(source_lstat.st_size), "max_bytes": int(max_bytes)},
            )

        dst_dir.mkdir(parents=True, exist_ok=True)
        free_bytes = shutil.disk_usage(dst_dir).free
        required_free = int(source_lstat.st_size) + max(0, int(min_free_bytes))
        if free_bytes < required_free:
            raise IngestFinalizationError(
                FAIL_DISK_SPACE_INSUFFICIENT,
                f"Insufficient free space to finalize upload ({free_bytes} available, {required_free} required).",
                metadata={"free_bytes": int(free_bytes), "required_free_bytes": int(required_free)},
            )

        try:
            src_fd = _open_no_follow(src_path, os.O_RDONLY)
        except OSError as exc:
            raise IngestFinalizationError(FAIL_SOURCE_CHANGED, f"Could not safely open source upload: {exc}") from exc
        fd_stat = os.fstat(src_fd)
        if not _same_inode(source_lstat, fd_stat):
            raise IngestFinalizationError(FAIL_SOURCE_CHANGED, "Source upload changed before it could be claimed.")
        if not stat.S_ISREG(fd_stat.st_mode):
            raise IngestFinalizationError(FAIL_NOT_REGULAR_FILE, "Opened source is not a regular file.")

        head = os.read(src_fd, 4)
        if len(head) < 4:
            raise IngestFinalizationError(FAIL_TRUNCATED_CONTAINER, "Incoming upload is too short to contain a pcap header.")
        if head not in PCAP_MAGIC_NUMBERS and head != PCAPNG_SECTION_HEADER_BLOCK:
            raise IngestFinalizationError(FAIL_INVALID_MAGIC, "Incoming upload is not a pcap or pcapng capture container.")
        os.lseek(src_fd, 0, os.SEEK_SET)

        try:
            tmp_fd = _open_no_follow(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except OSError as exc:
            raise IngestFinalizationError(FAIL_PROMOTION_COPY_FAILED, f"Could not create final temp file: {exc}") from exc

        digest = hashlib.sha256()
        copied = 0
        while True:
            chunk = os.read(src_fd, chunk_size)
            if not chunk:
                break
            digest.update(chunk)
            _write_all(tmp_fd, chunk)
            copied += len(chunk)
        source_sha256 = digest.hexdigest()

        current_fd_stat = os.fstat(src_fd)
        try:
            current_lstat = os.lstat(src_path)
        except OSError as exc:
            raise IngestFinalizationError(FAIL_SOURCE_CHANGED, f"Source upload disappeared during finalization: {exc}") from exc
        if not _same_claim_signature(fd_stat, current_fd_stat) or not _same_inode(fd_stat, current_lstat):
            raise IngestFinalizationError(FAIL_SOURCE_CHANGED, "Source upload changed during finalization; final artifact not trusted.")

        if before_commit_hook is not None:
            before_commit_hook(src_path)
            try:
                hook_lstat = os.lstat(src_path)
            except OSError as exc:
                raise IngestFinalizationError(FAIL_SOURCE_CHANGED, f"Source upload disappeared before commit: {exc}") from exc
            if not _same_inode(fd_stat, hook_lstat):
                raise IngestFinalizationError(FAIL_SOURCE_CHANGED, "Source upload inode changed before commit.")

        os.fchown(tmp_fd, int(final_uid), int(final_gid))
        os.fchmod(tmp_fd, int(final_mode))
        os.fsync(tmp_fd)
        os.close(tmp_fd)
        tmp_fd = None

        os.replace(tmp_path, dst_path)
        _fsync_directory(dst_dir)
        final_sha256 = sha256_file(dst_path)
        if final_sha256 != source_sha256:
            try:
                dst_path.unlink()
            finally:
                _fsync_directory(dst_dir)
            raise IngestFinalizationError(
                FAIL_PROMOTION_HASH_MISMATCH,
                "Final artifact hash does not match the claimed source hash.",
                metadata={"source_sha256": source_sha256, "final_sha256": final_sha256},
            )

        source_removed = False
        try:
            unlink_lstat = os.lstat(src_path)
            if _same_inode(fd_stat, unlink_lstat):
                src_path.unlink()
                source_removed = True
                _fsync_directory(src_path.parent)
        except FileNotFoundError:
            source_removed = False

        final_stat = os.stat(dst_path)
        return {
            "final_path": str(dst_path),
            "sha256": final_sha256,
            "size_bytes": int(final_stat.st_size),
            "final_owner_uid": int(final_stat.st_uid),
            "final_owner_gid": int(final_stat.st_gid),
            "final_mode": oct(stat.S_IMODE(final_stat.st_mode)),
            "finalization_method": "copy_fsync_chown_chmod_atomic_rename",
            "source_removed": source_removed,
        }
    except IngestFinalizationError:
        raise
    except OSError as exc:
        raise IngestFinalizationError(FAIL_PROMOTION_COPY_FAILED, f"Finalization failed: {exc}") from exc
    finally:
        if src_fd is not None:
            try:
                os.close(src_fd)
            except OSError:
                pass
        if tmp_fd is not None:
            try:
                os.close(tmp_fd)
            except OSError:
                pass
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass


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
