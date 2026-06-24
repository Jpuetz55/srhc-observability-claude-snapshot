"""Badge client-detail collection and active-MAC discovery helpers."""

from __future__ import annotations

import csv
import json
import os
import sqlite3
import ssl
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Mapping

try:
    from tools.common.config import load_mapping_config
except ModuleNotFoundError as exc:
    if exc.name != "tools":
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from tools.common.config import load_mapping_config

from .client_parser import MAC_TOKEN_RE, normalize_client_mac
from .dnac_client import CatalystCenterIcapReadClient


def load_badge_config(path: str | Path) -> dict[str, Any]:
    """Load and minimally validate the badge collection YAML config."""

    config_path = Path(path)
    payload = load_mapping_config(config_path, description="Badge client config")
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise RuntimeError(f"Badge client config must contain a jobs list: {config_path}")
    return payload


def select_jobs(config: Mapping[str, Any], job_name: str | None = None) -> list[dict[str, Any]]:
    """Return configured jobs, optionally narrowed to a single named job."""

    jobs = [job for job in config.get("jobs", []) if isinstance(job, dict)]
    if job_name:
        jobs = [job for job in jobs if job.get("name") == job_name]
        if not jobs:
            raise RuntimeError(f"No badge client job named {job_name!r} found in config.")
    return jobs


def _extract_mac_tokens(text: str) -> list[str]:
    """Extract and normalize every MAC-looking token from free-form text."""

    return [normalize_client_mac(match.group(0)) for match in MAC_TOKEN_RE.finditer(text)]


def _extract_macs_from_json(value: object) -> list[str]:
    """Walk JSON-like inventory data and collect MAC-looking values."""

    macs: list[str] = []
    if isinstance(value, str):
        macs.extend(_extract_mac_tokens(value))
    elif isinstance(value, list):
        for item in value:
            macs.extend(_extract_macs_from_json(item))
    elif isinstance(value, dict):
        for key, item in value.items():
            if "mac" in str(key).lower():
                macs.extend(_extract_macs_from_json(item))
            elif isinstance(item, (dict, list)):
                macs.extend(_extract_macs_from_json(item))
    return macs


def _read_inventory_file(path: str | Path) -> list[str]:
    """Read badge MACs from JSON, CSV, or plain-text inventory files."""

    inventory_path = Path(path)
    text = inventory_path.read_text(encoding="utf-8", errors="replace")
    if inventory_path.suffix.lower() == ".json":
        return _extract_macs_from_json(json.loads(text))
    if inventory_path.suffix.lower() == ".csv":
        rows = csv.DictReader(text.splitlines())
        macs: list[str] = []
        for row in rows:
            for field in ("client_mac", "mac", "mac_address", "macAddress"):
                if row.get(field):
                    macs.extend(_extract_mac_tokens(row[field] or ""))
                    break
            else:
                macs.extend(_extract_mac_tokens(",".join(row.values())))
        return macs
    return _extract_mac_tokens(text)


def _oui_prefixes(values: Iterable[object]) -> set[str]:
    """Normalize OUI allowlist entries to colon-separated prefixes."""

    prefixes: set[str] = set()
    for value in values:
        normalized = normalize_client_mac(str(value).replace(":", "")[:6])
        compact = normalized.replace(":", "")
        if len(compact) >= 6:
            prefixes.add(":".join(compact[i:i + 2] for i in range(0, 6, 2)))
    return prefixes


def resolve_badge_macs(job: Mapping[str, Any]) -> list[str]:
    """Resolve the static MAC list from config/env/inventory.

    Returns an empty list if no static sources are configured. Callers should
    decide whether to error out or fall back to a dynamic source (e.g.
    SQLite).
    """
    macs: list[str] = []
    for value in job.get("mac_addresses") or []:
        macs.extend(_extract_mac_tokens(str(value)))

    env_name = job.get("mac_addresses_env")
    if env_name and os.environ.get(str(env_name)):
        macs.extend(_extract_mac_tokens(os.environ[str(env_name)]))

    path = job.get("mac_inventory_path")
    path_env = job.get("mac_inventory_path_env")
    if path_env and os.environ.get(str(path_env)):
        path = os.environ[str(path_env)]
    if path:
        macs.extend(_read_inventory_file(path))

    unique = sorted({mac for mac in macs if mac})
    allowlist = _oui_prefixes(job.get("mac_oui_allowlist") or [])
    if allowlist:
        unique = [mac for mac in unique if any(mac.startswith(prefix) for prefix in allowlist)]
    return unique


def _env_value(config: Mapping[str, Any], key: str) -> str | None:
    """Resolve a config value directly or through its companion *_env key."""

    env_name = config.get(f"{key}_env")
    if env_name:
        return os.environ.get(str(env_name))
    value = config.get(key)
    return str(value) if value else None


def _client_from_job(job: Mapping[str, Any]) -> CatalystCenterIcapReadClient:
    """Create a Catalyst Center client from a badge collection job."""

    cc = job.get("catalyst_center") or {}
    if not isinstance(cc, Mapping):
        raise RuntimeError("catalyst_center config must be a mapping.")
    base_url = _env_value(cc, "base_url")
    username = _env_value(cc, "username")
    credential = _env_value(cc, "password")
    required_values = {"base_url": base_url, "username": username}
    required_values["password"] = credential
    missing = [name for name, value in required_values.items() if not value]
    if missing:
        raise RuntimeError("Missing Catalyst Center values for badge collection: " + ", ".join(missing))
    client_kwargs = {
        "base_url": str(base_url),
        "username": str(username),
        "verify_tls": bool(cc.get("verify_tls", True)),
    }
    client_kwargs["password"] = str(credential)
    return CatalystCenterIcapReadClient(**client_kwargs)


def _active_macs_from_prometheus(
    prom_url: str,
    query: str,
    max_badges: int,
    allowlist: set[str] | None = None,
    timeout: int = 15,
    verify_tls: bool = True,
) -> list[str]:
    """Query a Prometheus/Mimir instant-query API for active badge MACs.

    The query must return a vector with a `client_mac` label. Results are
    sorted by sample value descending (use `topk(N, ...)` in the query) and
    the top max_badges normalized MACs are returned.
    """
    base = prom_url.rstrip("/")
    url = f"{base}/api/v1/query?{urllib.parse.urlencode({'query': query})}"
    ctx = None if verify_tls else ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(url, timeout=timeout, context=ctx) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"WARN: Prometheus discovery query failed: {exc}")
        return []

    if payload.get("status") != "success":
        print(f"WARN: Prometheus discovery returned non-success: {payload}")
        return []

    series = payload.get("data", {}).get("result", []) or []
    # Prefer high-valued samples so callers can pass topk-style activity
    # queries without doing a second ranking step locally.
    series.sort(key=lambda s: float(s.get("value", [0, "0"])[1] or 0), reverse=True)
    macs: list[str] = []
    seen: set[str] = set()
    for sample in series:
        raw_mac = (sample.get("metric") or {}).get("client_mac")
        if not raw_mac:
            continue
        mac = normalize_client_mac(str(raw_mac))
        if not mac or mac in seen:
            continue
        if allowlist and not any(mac.startswith(p) for p in allowlist):
            continue
        seen.add(mac)
        macs.append(mac)
        if len(macs) >= max_badges:
            break
    return macs


def _active_macs_from_sqlite(
    db_path: str | Path,
    max_badges: int,
    window_seconds: int,
    allowlist: set[str] | None = None,
) -> list[str]:
    """Return up to max_badges MACs seen in SQLite within window_seconds.

    Ranked by most-recently-seen first. Returns [] if the DB is missing,
    empty, or unreadable.
    """
    db = Path(db_path)
    if not db.exists():
        return []

    cutoff_ms = int((time.time() - window_seconds) * 1000)
    try:
        conn = sqlite3.connect(db)
        try:
            rows = conn.execute(
                """
                SELECT client_mac, MAX(collected_at_ms) AS last_seen
                FROM badge_client_snapshot
                WHERE collected_at_ms >= ?
                GROUP BY client_mac
                ORDER BY last_seen DESC
                """,
                (cutoff_ms,),
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return []

    macs = [str(row[0]) for row in rows if row[0]]
    if allowlist:
        macs = [m for m in macs if any(m.startswith(p) for p in allowlist)]
    return macs[:max_badges]


def _prometheus_settings(job: Mapping[str, Any]) -> tuple[str, str, bool]:
    """Resolve Prometheus URL, discovery query, and verify_tls from the job."""
    prom = job.get("prometheus") or {}
    if not isinstance(prom, Mapping):
        prom = {}
    url = _env_value(prom, "url") or os.environ.get("PROMETHEUS_URL", "")
    query = str(prom.get("discovery_query") or "")
    verify_tls = bool(prom.get("verify_tls", True))
    return str(url or ""), query, verify_tls


def _resolve_collection_macs(job: Mapping[str, Any]) -> list[str]:
    """Pick the MAC list for a collection cycle.

    Order of precedence:
      1. Prometheus discovery — query MDT-derived metrics for active badges
         (no static list, no bootstrap needed).
      2. SQLite history — fallback when Prometheus is unreachable.
      3. Static config (mac_addresses / env / inventory) — used to bootstrap
         when neither discovery source has data.
    """
    max_badges = int(job.get("max_badges") or 0) or 50
    window_seconds = int(job.get("active_window_seconds") or 3600)
    allowlist = _oui_prefixes(job.get("mac_oui_allowlist") or [])
    db_path = (job.get("outputs") or {}).get("sqlite", "")

    prom_url, prom_query, prom_verify = _prometheus_settings(job)
    if prom_url:
        if not prom_query:
            window_minutes = max(1, window_seconds // 60)
            prom_query = (
                f"topk({max_badges}, max by (client_mac) "
                f"(last_over_time(wireless_badge_client_present[{window_minutes}m])))"
            )
        active = _active_macs_from_prometheus(
            prom_url, prom_query, max_badges, allowlist or None, verify_tls=prom_verify
        )
        if active:
            return active
        print("WARN: Prometheus discovery returned no badges; falling back to SQLite history.")

    if db_path:
        # SQLite is a local fallback for steady-state runs when Mimir is
        # unreachable but recent collection history is still available.
        active = _active_macs_from_sqlite(db_path, max_badges, window_seconds, allowlist or None)
        if active:
            return active

    static_macs = resolve_badge_macs(job)
    if not static_macs:
        raise RuntimeError(
            "Badge collection could not discover active MACs. Tried: "
            f"Prometheus ({prom_url or 'not configured'}), "
            f"SQLite ({db_path or 'not configured'}, last {window_seconds}s), "
            "and static seed list (empty). Configure prometheus.url + "
            "prometheus.discovery_query, or set mac_addresses / "
            "mac_addresses_env / mac_inventory_path to bootstrap."
        )
    return static_macs[:max_badges]


def collect_badge_job(job: Mapping[str, Any], timestamp_ms: int | None = None) -> dict[str, Any]:
    """Collect client-detail records for one configured badge job."""

    client = _client_from_job(job)
    collected_at_ms = int(time.time() * 1000)
    all_macs = _resolve_collection_macs(job)
    clients: list[dict[str, Any]] = []
    for mac in all_macs:
        record: dict[str, Any] = {"client_mac": mac}
        try:
            record["detail"] = client.get_client_detail(mac, timestamp_ms=timestamp_ms)
        except Exception as exc:
            # Keep per-client failures in the raw evidence so one bad badge
            # does not abort the entire collection cycle.
            record["error"] = str(exc)
        clients.append(record)

    return {
        "name": job.get("name", "badge-client-job"),
        "device_group": job.get("device_group", "VOCERA"),
        "wlc": job.get("wlc", "unknown"),
        "ssids": job.get("ssids", []),
        "badge_models": job.get("badge_models", []),
        "collected_at_ms": collected_at_ms,
        "collection_interval_seconds": job.get("collection_interval_seconds"),
        "clients": clients,
    }


def collect_configured_badge_jobs(
    config_path: str | Path,
    job_name: str | None = None,
    timestamp_ms: int | None = None,
) -> dict[str, Any]:
    """Run selected badge jobs and write per-job raw outputs when configured."""

    config = load_badge_config(config_path)
    selected = select_jobs(config, job_name=job_name)
    payload = {
        "source": "wireless_rf_badge_client_collector",
        "config": str(config_path),
        "collected_at_ms": int(time.time() * 1000),
        "jobs": [],
    }
    for job in selected:
        job_payload = collect_badge_job(job, timestamp_ms=timestamp_ms)
        payload["jobs"].append(job_payload)
        raw_path = (job.get("outputs") or {}).get("raw")
        if raw_path:
            path = Path(raw_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({**payload, "jobs": [job_payload]}, indent=2, sort_keys=True),
                encoding="utf-8",
            )
    return payload
