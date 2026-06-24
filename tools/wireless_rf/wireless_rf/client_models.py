"""Data model for Catalyst Center badge client-detail snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# Keep this order stable: CSV exports, SQLite inserts, and dashboard fixture
# checks all use the same field list.
BADGE_CLIENT_ROW_FIELDS = [
    "client_mac",
    "device_group",
    "badge_model",
    "wlc",
    "ssid",
    "ap_name",
    "site_tag",
    "policy_tag",
    "rf_tag",
    "band",
    "channel",
    "rssi_dbm",
    "snr_db",
    "rx_retry_pct",
    "latency_voice_us",
    "latency_be_us",
    "max_roaming_duration_ms",
    "average_auth_duration_ms",
    "average_assoc_duration_ms",
    "average_dhcp_duration_ms",
    "session_duration_s",
    "onboarding_attempts",
    "akm",
    "ft_state",
    "source",
    "collected_at_ms",
]


@dataclass
class BadgeClientSnapshot:
    """Normalized client-detail record for one badge at one collection time."""

    client_mac: str
    device_group: str = "VOCERA"
    badge_model: str = "unknown"
    wlc: str = "unknown"
    ssid: str = "unknown"
    ap_name: str = "unknown"
    site_tag: str = "unknown"
    policy_tag: str = "unknown"
    rf_tag: str = "unknown"
    band: str = "unknown"
    channel: str = "unknown"

    rssi_dbm: Optional[float] = None
    snr_db: Optional[float] = None
    rx_retry_pct: Optional[float] = None
    latency_voice_us: Optional[float] = None
    latency_be_us: Optional[float] = None

    max_roaming_duration_ms: Optional[float] = None
    average_auth_duration_ms: Optional[float] = None
    average_assoc_duration_ms: Optional[float] = None
    average_dhcp_duration_ms: Optional[float] = None
    session_duration_s: Optional[float] = None
    onboarding_attempts: Optional[float] = None

    akm: str = "unknown"
    ft_state: str = "unknown"
    source: str = "catalyst_center"
    collected_at_ms: Optional[int] = None

    def to_row(self) -> dict[str, object]:
        """Flatten the snapshot using the stable export/storage field order."""

        return {field: getattr(self, field) for field in BADGE_CLIENT_ROW_FIELDS}
