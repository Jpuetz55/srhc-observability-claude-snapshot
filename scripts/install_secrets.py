#!/usr/bin/env python3
"""Decrypt secrets/postgres.env.sops.yaml and write per-service env files.

Run as root from the repo root:
  sudo bash scripts/install_secrets.sh
  # or directly:
  sudo python3 scripts/install_secrets.py

Idempotent. Writes /etc/grafana-mimir-observability/secrets/<service>.env files
(0600 root) that the Grafana systemd drop-in picks up via EnvironmentFile=.
"""

from __future__ import annotations

import os
import pwd
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError:
    sys.exit("PyYAML is required: pip install pyyaml (or dnf install python3-pyyaml)")


REPO_ROOT = Path(__file__).resolve().parent.parent
SOPS_FILE = REPO_ROOT / "secrets" / "postgres.env.sops.yaml"
SECRETS_DIR = Path("/etc/grafana-mimir-observability/secrets")

# (output filename, env var name, path into the decrypted yaml)
MAPPING = [
    ("topology-postgres.env",
     "TOPOLOGY_POSTGRES_PASSWORD",
     ("topology", "password")),
    ("vocera-media-qoe-postgres.env",
     "VOCERA_MEDIA_QOE_POSTGRES_PASSWORD",
     ("vocera_media_qoe", "password")),
    ("vocera-rf-validation-postgres.env",
     "VOCERA_RF_VALIDATION_POSTGRES_PASSWORD",
     ("vocera_rf_validation", "password")),
]


def find_sops_binary() -> str:
    """Find sops even when sudo secure_path omits /usr/local/bin."""
    env_override = os.environ.get("SOPS_BIN")
    candidates = [
        env_override,
        shutil.which("sops"),
        "/usr/local/bin/sops",
        "/usr/bin/sops",
        "/bin/sops",
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    sys.exit(
        "sops binary not found. Install it or set SOPS_BIN=/path/to/sops "
        "(common local install path: /usr/local/bin/sops)."
    )


def find_age_key_file() -> Optional[str]:
    """Return an age identity file for sops, preferring explicit operator config."""
    explicit = os.environ.get("SOPS_AGE_KEY_FILE")
    if explicit:
        return explicit

    candidates = []
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user and sudo_user != "root":
        try:
            sudo_home = Path(pwd.getpwnam(sudo_user).pw_dir)
            candidates.append(sudo_home / ".config" / "sops" / "age" / "keys.txt")
        except KeyError:
            pass
    candidates.append(Path.home() / ".config" / "sops" / "age" / "keys.txt")

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def lookup(data, path):
    """Walk a (key, key, ...) path into a nested dict; raise a clean error on miss."""
    for key in path:
        if not isinstance(data, dict) or key not in data:
            raise KeyError(f"missing key '{key}' in decrypted secrets yaml")
        data = data[key]
    return data


def write_env_file(target: Path, key: str, value: str) -> None:
    """Write KEY="value" to target, escaping " and \\ so systemd parses it correctly."""
    quoted_value = '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    target.write_text(f"{key}={quoted_value}\n", encoding="utf-8")
    target.chmod(0o600)
    os.chown(target, 0, 0)


def main() -> int:
    if os.geteuid() != 0:
        sys.exit("install_secrets must run as root (use: sudo bash scripts/install_secrets.sh)")
    if not SOPS_FILE.exists():
        sys.exit(
            f"missing {SOPS_FILE}\n"
            f"bootstrap: cp {SOPS_FILE}.example {SOPS_FILE.name}, set real values, "
            f"then `sops --encrypt --in-place {SOPS_FILE}`."
        )
    sops_bin = find_sops_binary()
    decrypt_env = os.environ.copy()
    age_key_file = find_age_key_file()
    if age_key_file:
        decrypt_env["SOPS_AGE_KEY_FILE"] = age_key_file
    try:
        proc = subprocess.run(
            [sops_bin, "--decrypt", str(SOPS_FILE)],
            check=True, capture_output=True, text=True, env=decrypt_env,
        )
    except subprocess.CalledProcessError as exc:
        sys.exit(f"sops decrypt failed (exit {exc.returncode}):\n{exc.stderr}")

    data = yaml.safe_load(proc.stdout)
    if not isinstance(data, dict):
        sys.exit("decrypted secrets yaml is not a mapping")

    SECRETS_DIR.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    os.chown(SECRETS_DIR.parent, 0, 0)
    SECRETS_DIR.parent.chmod(0o755)

    SECRETS_DIR.mkdir(mode=0o750, exist_ok=True)
    os.chown(SECRETS_DIR, 0, 0)
    SECRETS_DIR.chmod(0o750)

    for filename, env_key, yaml_path in MAPPING:
        target = SECRETS_DIR / filename
        value = str(lookup(data, yaml_path))
        write_env_file(target, env_key, value)
        print(f"wrote {target} ({env_key}, {len(value)} chars)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
