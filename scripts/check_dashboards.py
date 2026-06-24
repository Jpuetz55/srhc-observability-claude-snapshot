#!/usr/bin/env python3
"""Validate basic Grafana dashboard JSON invariants."""

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.common.dashboard import dashboard_environment  # noqa: E402
from tools.common.dashboard import dashboard_paths  # noqa: E402
from tools.common.dashboard import dashboard_title  # noqa: E402
from tools.common.dashboard import dashboard_uid  # noqa: E402
from tools.common.dashboard import load_dashboard  # noqa: E402


def die(msg: str) -> None:
    """Print a validation error and exit non-zero."""

    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> int:
    """Validate checked-in Grafana dashboards."""

    repo_root = Path(os.environ.get("REPO_ROOT") or ROOT)
    paths = dashboard_paths(repo_root)
    if not paths:
        die("No dashboards found under grafana/dashboards-dev or grafana/dashboards-prod")

    uids_by_env = {"dev": {}, "prod": {}}
    for path in paths:
        # Provisioned dashboards need stable UID/title fields and unique UIDs per
        # environment; Grafana itself allows confusing duplicates.
        data = load_dashboard(path)
        uid = dashboard_uid(data)
        title = dashboard_title(data)
        if not isinstance(uid, str) or not uid.strip():
            die(f"Dashboard missing uid: {path}")
        if not isinstance(title, str) or not title.strip():
            die(f"Dashboard missing title: {path}")
        env = dashboard_environment(path)
        prev = uids_by_env[env].get(uid)
        if prev and prev != path:
            die(f"Duplicate dashboard uid within {env}: {uid}: {prev} and {path}")
        uids_by_env[env][uid] = path

    print(f"OK: validated {len(paths)} dashboards ({len(uids_by_env['dev'])} dev, {len(uids_by_env['prod'])} prod)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
