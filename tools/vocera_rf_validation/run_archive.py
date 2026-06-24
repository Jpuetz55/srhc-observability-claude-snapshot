"""Small ZIP run archives for parser inputs, outputs, and operator logs."""

from __future__ import annotations

import json
import os
import re
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def _safe_token(value: str) -> str:
    """Convert an arbitrary workflow/label string to a filename token."""
    token = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip()).strip("._")
    return token[:96] or "run"


def _path_for_manifest(path: Path) -> dict[str, Any]:
    """Return manifest metadata for a requested input or output path."""
    info: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
    }
    if not path.exists():
        return info
    try:
        stat = path.stat()
    except OSError as exc:
        info["stat_error"] = str(exc)
        return info
    info.update(
        {
            "is_dir": path.is_dir(),
            "is_file": path.is_file(),
            "size_bytes": stat.st_size if path.is_file() else None,
            "mtime_seconds": stat.st_mtime,
        }
    )
    return info


def _relative_name(path: Path) -> str:
    """Return a stable archive member path for repo-local or absolute files."""
    # Keep archive member names useful without leaking absolute path roots into
    # the top level of the ZIP. Paths outside the repo are stored without the
    # leading slash under inputs/ or outputs/.
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path.absolute()
    try:
        return resolved.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        parts = resolved.parts
        if parts and parts[0] == os.sep:
            parts = parts[1:]
        return Path(*parts).as_posix() if parts else _safe_token(path.name)


def _iter_archive_members(path: Path, role: str) -> Iterable[tuple[Path, str]]:
    """Yield files and archive names under the given input/output role."""
    if not path.exists():
        return
    if path.is_dir():
        base = path.parent
        for child in sorted(item for item in path.rglob("*") if item.is_file()):
            yield child, f"{role}/{child.relative_to(base).as_posix()}"
        return
    if path.is_file():
        yield path, f"{role}/{_relative_name(path)}"


def _dedupe_arcname(arcname: str, used: set[str]) -> str:
    """Avoid duplicate member names when inputs and outputs overlap."""
    if arcname not in used:
        used.add(arcname)
        return arcname
    path = Path(arcname)
    stem = path.with_suffix("").as_posix()
    suffix = path.suffix
    index = 2
    while True:
        candidate = f"{stem}.{index}{suffix}"
        if candidate not in used:
            used.add(candidate)
            return candidate
        index += 1


def _write_file(archive: zipfile.ZipFile, path: Path, arcname: str) -> None:
    """Write a file to the ZIP while preserving mtime and file mode bits."""
    stat = path.stat()
    timestamp = max(stat.st_mtime, 315532800)
    date_time = datetime.fromtimestamp(timestamp, timezone.utc).timetuple()[:6]
    info = zipfile.ZipInfo(arcname, date_time=date_time)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (stat.st_mode & 0xFFFF) << 16
    with path.open("rb") as source, archive.open(info, "w") as target:
        shutil.copyfileobj(source, target)


def create_run_archive(
    *,
    archive_dir: str | Path,
    workflow: str,
    command: str,
    inputs: Iterable[str | Path] = (),
    outputs: Iterable[str | Path] = (),
    metadata: dict[str, Any] | None = None,
    log_lines: Iterable[str] = (),
    label: str | None = None,
) -> Path:
    """Create one ZIP containing run inputs, outputs, a manifest, and a log."""

    archive_root = Path(archive_dir)
    archive_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    label_token = f"-{_safe_token(label)}" if label else ""
    archive_path = archive_root / f"{_safe_token(workflow)}-{timestamp}-{os.getpid()}{label_token}.zip"

    input_paths = [Path(path) for path in inputs if path not in (None, "")]
    output_paths = [Path(path) for path in outputs if path not in (None, "")]
    manifest: dict[str, Any] = {
        "workflow": workflow,
        "command": command,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "cwd": str(Path.cwd()),
        "metadata": metadata or {},
        "requested_inputs": [_path_for_manifest(path) for path in input_paths],
        "requested_outputs": [_path_for_manifest(path) for path in output_paths],
        "members": [],
    }

    used: set[str] = set()
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for role, paths in (("inputs", input_paths), ("outputs", output_paths)):
            for path in paths:
                for member_path, arcname in _iter_archive_members(path, role):
                    final_arcname = _dedupe_arcname(arcname, used)
                    _write_file(archive, member_path, final_arcname)
                    manifest["members"].append(
                        {
                            "role": role,
                            "source_path": str(member_path),
                            "archive_path": final_arcname,
                        }
                    )
        log_text = "\n".join(str(line) for line in log_lines)
        if log_text and not log_text.endswith("\n"):
            log_text += "\n"
        archive.writestr("logs/run.log", log_text)
        archive.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
    archive_path.chmod(0o644)
    return archive_path
