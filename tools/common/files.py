"""Shared file IO helpers for repository tooling."""

from __future__ import annotations

import csv
import json
import os
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any


def ensure_parent(path: str | Path) -> Path:
    """Create a file path's parent directory and return the normalized path."""

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


def read_text(path: str | Path, *, encoding: str = "utf-8", errors: str | None = None) -> str:
    """Read text with a consistent default encoding."""

    kwargs: dict[str, str] = {"encoding": encoding}
    if errors is not None:
        kwargs["errors"] = errors
    return Path(path).read_text(**kwargs)


def write_text(path: str | Path, text: str, *, encoding: str = "utf-8") -> None:
    """Write text after creating the parent directory."""

    ensure_parent(path).write_text(text, encoding=encoding)


def write_text_atomic(path: str | Path, text: str, *, encoding: str = "utf-8") -> None:
    """Write text via same-directory replace so readers never see partial files."""

    out = ensure_parent(path)
    tmp = out.with_name(f".{out.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(text, encoding=encoding)
        os.replace(tmp, out)
    finally:
        if tmp.exists():
            tmp.unlink()


def read_json(path: str | Path, *, encoding: str = "utf-8") -> Any:
    """Read JSON from disk using the common text encoding default."""

    return json.loads(Path(path).read_text(encoding=encoding))


def write_json(
    path: str | Path,
    payload: Any,
    *,
    indent: int | None = 2,
    sort_keys: bool = True,
    trailing_newline: bool = False,
    atomic: bool = False,
) -> None:
    """Write deterministic JSON after creating the parent directory."""

    text = json.dumps(payload, indent=indent, sort_keys=sort_keys)
    if trailing_newline:
        text += "\n"
    writer = write_text_atomic if atomic else write_text
    writer(path, text)


def read_yaml(path: str | Path, *, encoding: str = "utf-8") -> Any:
    """Read YAML with PyYAML imported only by callers that need it."""

    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to load YAML files.") from exc
    return yaml.safe_load(Path(path).read_text(encoding=encoding))


def write_csv(
    path: str | Path,
    fieldnames: Sequence[str],
    rows: Iterable[Mapping[str, object]],
    *,
    extrasaction: str = "raise",
    encoding: str = "utf-8",
) -> None:
    """Write dictionaries as CSV using an explicit stable header order."""

    out = ensure_parent(path)
    with out.open("w", newline="", encoding=encoding) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), extrasaction=extrasaction)
        writer.writeheader()
        writer.writerows(rows)
