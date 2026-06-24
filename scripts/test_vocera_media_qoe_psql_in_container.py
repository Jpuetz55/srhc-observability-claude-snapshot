#!/usr/bin/env python3
"""Verify the container psql wrapper honors the database in a PostgreSQL URL."""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts" / "vocera_media_qoe_psql_in_container.sh"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_wrapper(url: str) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as temp_dir:
        fake_podman = Path(temp_dir) / "podman"
        fake_podman.write_text(
            """#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "container" && "${2:-}" == "exists" ]]; then
  exit 0
fi

if [[ "${1:-}" == "exec" ]]; then
  for ((index = 1; index <= $#; index++)); do
    if [[ "${!index}" == "--dbname" ]]; then
      next=$((index + 1))
      printf 'dbname=%s\\n' "${!next}"
      exit 0
    fi
  done
fi

echo "unexpected fake podman invocation: $*" >&2
exit 99
""",
            encoding="utf-8",
        )
        fake_podman.chmod(fake_podman.stat().st_mode | stat.S_IXUSR)

        environment = os.environ.copy()
        environment.update(
            {
                "PATH": f"{temp_dir}:{environment['PATH']}",
                "PGPASSWORD": "test-password",
                "VOCERA_MEDIA_QOE_POSTGRES_DB": "vocera_media_qoe",
                "VOCERA_MEDIA_QOE_POSTGRES_CONTAINER_NAME": "fake-vocera-postgres",
            }
        )

        return subprocess.run(
            [str(WRAPPER), url, "-v", "ON_ERROR_STOP=1", "-c", "select 1"],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )


def main() -> int:
    rehearsal = "vocera_media_qoe_rehearsal_20260624_113230"
    result = run_wrapper(f"postgresql://vocera_media_qoe@127.0.0.1:15434/{rehearsal}")

    require(result.returncode == 0, result.stderr)
    require(
        result.stdout.strip() == f"dbname={rehearsal}",
        f"wrapper did not honor URL database: stdout={result.stdout!r}",
    )

    invalid = run_wrapper("postgresql://vocera_media_qoe@127.0.0.1:15434/invalid-name")
    require(invalid.returncode != 0, "invalid database name should be rejected")
    require(
        "Unsupported database name" in invalid.stderr,
        f"unexpected invalid URL error: {invalid.stderr!r}",
    )

    print("OK: container psql wrapper honors PostgreSQL URL database selection")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
