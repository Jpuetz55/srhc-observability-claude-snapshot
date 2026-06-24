"""Configuration loading for RF validation tools."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
from typing import Any

try:
    from tools.common.config import load_mapping_config
except ModuleNotFoundError as exc:
    if exc.name != "tools":
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from tools.common.config import load_mapping_config


DEFAULT_CONFIG: dict[str, Any] = {
    "timezone": "America/Chicago",
    "default_match_window_seconds": 1,
    "minimum_samples_for_outlier_stats": 30,
    "outlier_z_score_threshold": 2.0,
    "rssi_offsets": {
        "default_source": "Stryker Vocera WLAN Requirements and Best Practices, Ekahau Sidekick offsets",
        "by_band": {"2.4GHz": -5, "5GHz": -8, "6GHz": None},
    },
    "ekahau_json": {
        "timestamp_keys": ["timestamp", "time", "measuredAt", "measurementTime", "surveyTime", "collectionTime", "createdAt"],
        "id_keys": ["id", "uuid", "guid", "measurementId", "surveyPointId"],
        "floor_keys": ["floor", "floorName", "mapName", "level"],
        "area_keys": ["area", "zone", "room"],
        "x_keys": ["x", "x_m", "positionX"],
        "y_keys": ["y", "y_m", "positionY"],
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merge nested config dictionaries without mutating DEFAULT_CONFIG."""
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load YAML config over defaults; missing config files use defaults."""

    if not path:
        return deepcopy(DEFAULT_CONFIG)
    payload = load_mapping_config(
        path,
        default={},
        allow_missing=True,
        description="RF validation config",
    )
    return _deep_merge(DEFAULT_CONFIG, payload)
