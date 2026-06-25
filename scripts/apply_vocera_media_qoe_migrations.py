#!/usr/bin/env python3
"""Apply versioned Vocera Media QoE PostgreSQL migrations.

The monolithic schema remains the bootstrap path for new local containers. This
runner is the production path for additive changes: it applies each immutable
SQL file in ``sql/migrations`` once, records its SHA-256, and refuses to proceed
if an already-applied migration has been edited.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import subprocess
import sys
from io import StringIO
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MIGRATIONS_DIR = ROOT / "sql" / "migrations"


LEDGER_SQL = """
create table if not exists schema_migrations (
  migration_id text primary key,
  checksum text not null,
  applied_at timestamptz not null default now(),
  applied_by text not null,
  source_commit text not null
);

create index if not exists idx_schema_migrations_applied_at
  on schema_migrations (applied_at desc);
"""


def sql_literal(value: object) -> str:
    if value is None:
        return "null"
    return "'" + str(value).replace("'", "''") + "'"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_commit() -> str:
    env_commit = os.environ.get("VOCERA_MEDIA_QOE_SOURCE_COMMIT", "").strip()
    if env_commit:
        return env_commit
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if completed.returncode == 0 and completed.stdout.strip():
        return completed.stdout.strip()
    return "unknown"


def psql_rows(psql_bin: str, postgres_url: str, sql: str) -> list[dict[str, str]]:
    completed = subprocess.run(
        [psql_bin, postgres_url, "-X", "--csv", "-v", "ON_ERROR_STOP=1", "-c", sql],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(detail or f"{psql_bin} exited {completed.returncode}")
    output = completed.stdout.strip()
    return list(csv.DictReader(StringIO(output))) if output else []


def psql_exec(psql_bin: str, postgres_url: str, sql: str) -> None:
    completed = subprocess.run(
        [psql_bin, postgres_url, "-X", "-v", "ON_ERROR_STOP=1", "-c", sql],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(detail or f"{psql_bin} exited {completed.returncode}")


def psql_file(psql_bin: str, postgres_url: str, path: Path) -> None:
    completed = subprocess.run(
        [psql_bin, postgres_url, "-X", "-v", "ON_ERROR_STOP=1", "-f", str(path)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(detail or f"{psql_bin} exited {completed.returncode}")


def migration_files(migrations_dir: Path) -> list[Path]:
    files = sorted(path for path in migrations_dir.glob("*.sql") if path.is_file())
    if not files:
        raise RuntimeError(f"No migration files found under {migrations_dir}")
    return files


def apply_migrations(*, postgres_url: str, psql_bin: str, migrations_dir: Path, dry_run: bool = False) -> list[dict[str, str]]:
    psql_exec(psql_bin, postgres_url, LEDGER_SQL)
    applied_by = os.environ.get("USER") or os.environ.get("LOGNAME") or "unknown"
    commit = source_commit()
    results: list[dict[str, str]] = []

    for path in migration_files(migrations_dir):
        migration_id = path.name
        checksum = sha256_file(path)
        rows = psql_rows(
            psql_bin,
            postgres_url,
            "select checksum from schema_migrations "
            f"where migration_id = {sql_literal(migration_id)};",
        )
        if rows:
            existing = rows[0].get("checksum")
            if existing != checksum:
                raise RuntimeError(
                    f"Applied migration {migration_id} checksum mismatch: "
                    f"database has {existing}, file has {checksum}"
                )
            results.append({"migration_id": migration_id, "status": "already_applied"})
            continue

        if dry_run:
            results.append({"migration_id": migration_id, "status": "pending"})
            continue

        psql_file(psql_bin, postgres_url, path)
        psql_exec(
            psql_bin,
            postgres_url,
            "insert into schema_migrations (migration_id, checksum, applied_by, source_commit) values ("
            f"{sql_literal(migration_id)}, {sql_literal(checksum)}, "
            f"{sql_literal(applied_by)}, {sql_literal(commit)}"
            ");",
        )
        results.append({"migration_id": migration_id, "status": "applied"})

    return results


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres-url", default=os.environ.get("VOCERA_MEDIA_QOE_DATABASE_URL", ""))
    parser.add_argument("--psql-bin", default=os.environ.get("VOCERA_MEDIA_QOE_PSQL_BIN", "psql"))
    parser.add_argument("--migrations-dir", type=Path, default=DEFAULT_MIGRATIONS_DIR)
    parser.add_argument("--dry-run", action="store_true", help="Report pending migrations without applying them.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if not args.postgres_url:
        print("Set --postgres-url or VOCERA_MEDIA_QOE_DATABASE_URL.", file=sys.stderr)
        return 2
    results = apply_migrations(
        postgres_url=args.postgres_url,
        psql_bin=args.psql_bin,
        migrations_dir=args.migrations_dir,
        dry_run=bool(args.dry_run),
    )
    for result in results:
        print(f"{result['status']}: {result['migration_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
