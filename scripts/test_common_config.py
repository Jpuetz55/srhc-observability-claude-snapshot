#!/usr/bin/env python3
"""Fixture-style tests for shared config helpers."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.common.config import env_bool  # noqa: E402
from tools.common.config import env_value  # noqa: E402
from tools.common.config import load_env_file  # noqa: E402
from tools.common.config import load_mapping_config  # noqa: E402
from tools.common.config import require_keys  # noqa: E402


def require(condition: bool, message: str) -> None:
    """Raise AssertionError with a concise common-helper failure message."""

    if not condition:
        raise AssertionError(message)


def test_env_file(root: Path) -> None:
    """Verify shell-style env-file parsing and env precedence."""

    path = root / "service.env"
    path.write_text(
        "\n".join(
            [
                "# ignored",
                "PLAIN=value",
                "export QUOTED='two words'",
                'DOUBLE="three words"',
                "EMPTY=",
            ]
        ),
        encoding="utf-8",
    )
    values = load_env_file(path)
    require(values["PLAIN"] == "value", "plain env value should parse")
    require(values["QUOTED"] == "two words", "single quotes should be stripped")
    require(values["DOUBLE"] == "three words", "double quotes should be stripped")
    require(values["EMPTY"] == "", "empty env value should parse")

    os.environ["PLAIN"] = "from-os-env"
    try:
        require(env_value("PLAIN", values) == "from-os-env", "real environment should win over env file")
    finally:
        os.environ.pop("PLAIN", None)


def test_env_bool() -> None:
    """Verify common boolean spellings."""

    values = {"YES_VALUE": "yes", "NO_VALUE": "off", "EMPTY_VALUE": ""}
    require(env_bool("YES_VALUE", env_file_values=values), "yes should parse as true")
    require(not env_bool("NO_VALUE", default=True, env_file_values=values), "off should parse as false")
    require(env_bool("EMPTY_VALUE", default=True, env_file_values=values), "empty bool should use default")


def test_mapping_config(root: Path) -> None:
    """Verify JSON/YAML mapping config loading and missing-file defaults."""

    json_path = root / "config.json"
    json_path.write_text('{"b": 2, "a": 1}', encoding="utf-8")
    require(load_mapping_config(json_path) == {"a": 1, "b": 2}, "JSON mapping should load")

    yaml_path = root / "config.yaml"
    yaml_path.write_text("jobs:\n  - name: demo\n", encoding="utf-8")
    require(load_mapping_config(yaml_path) == {"jobs": [{"name": "demo"}]}, "YAML mapping should load")

    missing = root / "missing.yaml"
    require(
        load_mapping_config(missing, allow_missing=True, default={"enabled": True}) == {"enabled": True},
        "missing optional config should return default",
    )


def test_require_keys() -> None:
    """Verify required-key validation."""

    require_keys({"a": 1}, ["a"], description="demo")
    try:
        require_keys({"a": ""}, ["a", "b"], description="demo")
    except RuntimeError as exc:
        require("a, b" in str(exc), "missing keys should be reported")
    else:
        raise AssertionError("require_keys should fail for empty/missing values")


def main() -> int:
    """Run common config helper tests without requiring pytest."""

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        test_env_file(root)
        test_env_bool()
        test_mapping_config(root)
        test_require_keys()
    print("OK: common config helper tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
