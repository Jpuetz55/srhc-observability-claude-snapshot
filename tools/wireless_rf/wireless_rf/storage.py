"""SQLite persistence for parsed WLC RF snapshots and inferred DFS events."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from .models import ApRfSnapshot

SCHEMA = """
CREATE TABLE IF NOT EXISTS collection_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    wlc TEXT NOT NULL,
    source TEXT NOT NULL,
    raw_file TEXT
);

CREATE TABLE IF NOT EXISTS ap_rf_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    wlc TEXT NOT NULL,
    ap_name TEXT NOT NULL,
    site_tag TEXT NOT NULL,
    policy_tag TEXT NOT NULL,
    rf_tag TEXT NOT NULL,
    band TEXT NOT NULL,
    current_channel INTEGER,
    channel_width_mhz INTEGER,
    is_dfs_channel INTEGER NOT NULL,
    cac_running INTEGER NOT NULL,
    radar_changes_total INTEGER,
    nearby_ap_count INTEGER NOT NULL,
    strongest_neighbor_rssi_dbm INTEGER,
    weakest_neighbor_rssi_dbm INTEGER,
    mean_neighbor_rssi_dbm REAL,
    neighbors_json TEXT NOT NULL,
    UNIQUE(run_id, ap_name, band)
);

CREATE TABLE IF NOT EXISTS dfs_event_inferred (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    wlc TEXT NOT NULL,
    ap_name TEXT NOT NULL,
    site_tag TEXT NOT NULL,
    previous_radar_count INTEGER,
    current_radar_count INTEGER,
    delta INTEGER NOT NULL,
    current_channel INTEGER,
    is_dfs_channel INTEGER NOT NULL
);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open the RF SQLite DB and create tables if needed."""

    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def previous_radar_count(conn: sqlite3.Connection, wlc: str, ap_name: str, band: str) -> int | None:
    """Fetch the latest prior radar counter for AP/band delta inference."""

    row = conn.execute(
        """
        SELECT radar_changes_total
        FROM ap_rf_snapshot
        WHERE wlc = ? AND ap_name = ? AND band = ? AND radar_changes_total IS NOT NULL
        ORDER BY id DESC
        LIMIT 1
        """,
        (wlc, ap_name, band),
    ).fetchone()
    return int(row[0]) if row else None


def save_run(
    db_path: str | Path,
    snapshots: Iterable[ApRfSnapshot],
    wlc: str,
    source: str = "cli",
    raw_file: str | None = None,
) -> int:
    """Persist one RF collection run and infer radar-counter deltas."""

    snapshots = list(snapshots)
    conn = connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO collection_runs (wlc, source, raw_file) VALUES (?, ?, ?)",
            (wlc, source, raw_file),
        )
        run_id = int(cur.lastrowid)
        for snapshot in snapshots:
            prev = previous_radar_count(conn, snapshot.wlc, snapshot.ap_name, snapshot.band)
            conn.execute(
                """
                INSERT INTO ap_rf_snapshot (
                    run_id, wlc, ap_name, site_tag, policy_tag, rf_tag, band,
                    current_channel, channel_width_mhz, is_dfs_channel,
                    cac_running, radar_changes_total, nearby_ap_count,
                    strongest_neighbor_rssi_dbm, weakest_neighbor_rssi_dbm,
                    mean_neighbor_rssi_dbm, neighbors_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    snapshot.wlc,
                    snapshot.ap_name,
                    snapshot.site_tag,
                    snapshot.policy_tag,
                    snapshot.rf_tag,
                    snapshot.band,
                    snapshot.current_channel,
                    snapshot.channel_width_mhz,
                    1 if snapshot.is_dfs_channel else 0,
                    1 if snapshot.cac_running else 0,
                    snapshot.radar_changes_total,
                    snapshot.neighbor_count,
                    snapshot.strongest_neighbor_rssi_dbm,
                    snapshot.weakest_neighbor_rssi_dbm,
                    snapshot.mean_neighbor_rssi_dbm,
                    json.dumps([n.__dict__ for n in snapshot.neighbors], sort_keys=True),
                ),
            )
            if snapshot.radar_changes_total is not None:
                # The controller exposes a cumulative counter. The dashboard
                # needs per-run deltas, so store a non-negative delta against
                # the previous snapshot for the same AP/radio.
                delta = 0 if prev is None else max(0, snapshot.radar_changes_total - prev)
                conn.execute(
                    """
                    INSERT INTO dfs_event_inferred (
                        run_id, wlc, ap_name, site_tag, previous_radar_count,
                        current_radar_count, delta, current_channel, is_dfs_channel
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        snapshot.wlc,
                        snapshot.ap_name,
                        snapshot.site_tag,
                        prev,
                        snapshot.radar_changes_total,
                        delta,
                        snapshot.current_channel,
                        1 if snapshot.is_dfs_channel else 0,
                    ),
                )
        conn.commit()
        return run_id
    finally:
        conn.close()
