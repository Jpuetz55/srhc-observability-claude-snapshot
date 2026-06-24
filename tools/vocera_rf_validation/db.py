"""psql-based helpers for installing the RF validation schema."""

from __future__ import annotations

import subprocess
from pathlib import Path


def install_schema(*, postgres_url: str, schema_sql: Path, views_sql: Path, psql_bin: str = "psql") -> None:
    """Apply schema then views through the selected psql executable."""
    for sql_path in (schema_sql, views_sql):
        subprocess.run(
            [psql_bin, postgres_url, "-v", "ON_ERROR_STOP=1", "-f", str(sql_path)],
            check=True,
        )
