"""SQLite persistence for badge client snapshots."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from .client_models import BADGE_CLIENT_ROW_FIELDS, BadgeClientSnapshot

SCHEMA = """
CREATE TABLE IF NOT EXISTS badge_collection_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    wlc TEXT NOT NULL,
    source TEXT NOT NULL,
    raw_file TEXT
);

CREATE TABLE IF NOT EXISTS badge_client_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    client_mac TEXT NOT NULL,
    device_group TEXT NOT NULL,
    badge_model TEXT NOT NULL,
    wlc TEXT NOT NULL,
    ssid TEXT NOT NULL,
    ap_name TEXT NOT NULL,
    site_tag TEXT NOT NULL,
    policy_tag TEXT NOT NULL,
    rf_tag TEXT NOT NULL,
    band TEXT NOT NULL,
    channel TEXT NOT NULL,
    rssi_dbm REAL,
    snr_db REAL,
    rx_retry_pct REAL,
    latency_voice_us REAL,
    latency_be_us REAL,
    max_roaming_duration_ms REAL,
    average_auth_duration_ms REAL,
    average_assoc_duration_ms REAL,
    average_dhcp_duration_ms REAL,
    session_duration_s REAL,
    onboarding_attempts REAL,
    akm TEXT NOT NULL,
    ft_state TEXT NOT NULL,
    source TEXT NOT NULL,
    collected_at_ms INTEGER
);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open the badge SQLite DB and create tables if needed."""

    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def save_badge_run(
    db_path: str | Path,
    snapshots: Iterable[BadgeClientSnapshot],
    wlc: str,
    source: str = "catalyst_center",
    raw_file: str | None = None,
) -> int:
    """Persist one badge collection run and all parsed client snapshots."""

    snapshots = list(snapshots)
    conn = connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO badge_collection_runs (wlc, source, raw_file) VALUES (?, ?, ?)",
            (wlc, source, raw_file),
        )
        run_id = int(cur.lastrowid)
        columns = BADGE_CLIENT_ROW_FIELDS
        placeholders = ", ".join("?" for _ in columns)
        for snapshot in snapshots:
            row = snapshot.to_row()
            conn.execute(
                f"""
                INSERT INTO badge_client_snapshot (
                    run_id, {", ".join(columns)}
                ) VALUES (?, {placeholders})
                """,
                (run_id, *(row[column] for column in columns)),
            )
        conn.commit()
        return run_id
    finally:
        conn.close()
