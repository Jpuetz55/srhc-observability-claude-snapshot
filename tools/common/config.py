"""Shared config loading helpers for repository tooling."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def load_env_file(path: str | Path | None) -> dict[str, str]:
    """Load KEY=VALUE pairs from an optional shell-style env file."""

    if not path:
        return {}
    env_path = Path(path)
    if not env_path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def env_value(
    name: str,
    env_file_values: Mapping[str, str] | None = None,
    *,
    default: str | None = None,
    required: bool = False,
) -> str | None:
    """Return an environment value, falling back to env-file values and defaults."""

    value = os.environ.get(name)
    if value is None and env_file_values is not None:
        value = env_file_values.get(name)
    if value is None:
        value = default
    if required and (value is None or value == ""):
        raise RuntimeError(f"Missing required environment value: {name}")
    return value


def env_bool(
    name: str,
    default: bool = False,
    env_file_values: Mapping[str, str] | None = None,
) -> bool:
    """Read a boolean environment value using common shell config spellings."""

    value = env_value(name, env_file_values)
    if value is None or value == "":
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _read_config_payload(path: Path) -> Any:
    """Read JSON or YAML based on file suffix."""

    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(text)

    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError(f"PyYAML is required to load YAML config files: {path}") from exc
    return yaml.safe_load(text) or {}


def load_mapping_config(
    path: str | Path | None,
    *,
    default: Mapping[str, Any] | None = None,
    allow_missing: bool = False,
    description: str = "config",
) -> dict[str, Any]:
    """Load an optional JSON/YAML config file and require a mapping payload."""

    if not path:
        return dict(default or {})
    config_path = Path(path)
    if not config_path.exists():
        if allow_missing:
            return dict(default or {})
        raise RuntimeError(f"{description} file not found: {config_path}")

    payload = _read_config_payload(config_path)
    if payload is None:
        return dict(default or {})
    if not isinstance(payload, Mapping):
        raise RuntimeError(f"{description} must be a mapping: {config_path}")
    return dict(payload)


def require_keys(mapping: Mapping[str, object], keys: Sequence[str], *, description: str = "config") -> None:
    """Require non-empty values for a set of mapping keys."""

    missing = [key for key in keys if not mapping.get(key)]
    if missing:
        raise RuntimeError(f"{description} missing required values: " + ", ".join(missing))
