"""Domain models shared by the WLC RF parser, exporters, and storage layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class ApTags:
    """Static tag metadata from `show ap tag summary` for one AP."""

    ap_name: str
    ap_mac: str = ""
    site_tag: str = "unknown"
    policy_tag: str = "unknown"
    rf_tag: str = "unknown"


@dataclass
class Neighbor:
    """One nearby-AP row from auto-rf output."""

    neighbor_ap: str
    neighbor_mac: str = ""
    channel: Optional[int] = None
    rssi_dbm: Optional[int] = None
    raw_line: str = ""


@dataclass
class ApAccessCategoryLatency:
    """Traffic-distribution latency for one AP radio/access category/client generation."""

    slot_id: str
    band: str = "unknown"
    access_category: str = "voice"
    client_generation: str = "unknown"
    avg_latency_us: Optional[float] = None
    active_clients: Optional[int] = None
    packets_by_latency_level: Dict[str, int] = field(default_factory=dict)
    sample_end_timestamp_seconds: Optional[float] = None


@dataclass
class WirelessRfCollectionStats:
    """Run-level collection metadata emitted as Prometheus health gauges."""

    wlc: str = "unknown"
    last_success_timestamp_seconds: Optional[float] = None
    duration_seconds: Optional[float] = None
    commands_total: int = 0
    commands_failed_total: int = 0
    ap_count: int = 0
    latency_samples_total: int = 0
    last_error_reason: str = "none"


@dataclass
class ApRfSnapshot:
    """The parser's normalized AP/radio snapshot.

    A snapshot may contain auto-rf neighbor/DFS fields, traffic-distribution
    latency fields, or both. The parser merges command blocks by AP and band.
    """

    ap_name: str
    wlc: str = "unknown"
    band: str = "5ghz"
    site_tag: str = "unknown"
    policy_tag: str = "unknown"
    rf_tag: str = "unknown"
    current_channel: Optional[int] = None
    channel_width_mhz: Optional[int] = None
    receive_utilization_pct: Optional[float] = None
    transmit_utilization_pct: Optional[float] = None
    channel_utilization_pct: Optional[float] = None
    is_dfs_channel: bool = False
    cac_running: bool = False
    radar_changes_total: Optional[int] = None
    zero_wait_dfs_capable: Optional[bool] = None
    zero_wait_dfs_enabled: Optional[bool] = None
    neighbors: List[Neighbor] = field(default_factory=list)
    access_category_latencies: List[ApAccessCategoryLatency] = field(default_factory=list)
    source: str = "cli"
    has_auto_rf: bool = False

    @property
    def neighbor_count(self) -> int:
        """Return the number of parsed nearby AP rows."""

        return len(self.neighbors)

    @property
    def rssi_values(self) -> List[int]:
        """Return only neighbors with usable RSSI values."""

        return [n.rssi_dbm for n in self.neighbors if n.rssi_dbm is not None]

    @property
    def strongest_neighbor_rssi_dbm(self) -> Optional[int]:
        """Return the least-negative neighbor RSSI, if available."""

        values = self.rssi_values
        return max(values) if values else None

    @property
    def weakest_neighbor_rssi_dbm(self) -> Optional[int]:
        """Return the most-negative neighbor RSSI, if available."""

        values = self.rssi_values
        return min(values) if values else None

    @property
    def mean_neighbor_rssi_dbm(self) -> Optional[float]:
        """Return the average nearby-AP RSSI for overlap scoring."""

        values = self.rssi_values
        return sum(values) / len(values) if values else None

    @property
    def channel_list(self) -> List[int]:
        """Return unique nearby-AP channels in sorted order."""

        channels = [n.channel for n in self.neighbors if n.channel is not None]
        return sorted(set(channels))

    @property
    def unique_neighbor_channels(self) -> int:
        """Return the count of unique nearby-AP channels."""

        return len(self.channel_list)

    def neighbors_at_or_above(self, threshold_dbm: int) -> int:
        """Count nearby APs whose RSSI is stronger than the threshold."""

        return sum(1 for value in self.rssi_values if value >= threshold_dbm)

    def to_row(self) -> Dict[str, object]:
        """Flatten the snapshot for CSV, JSON table views, and Streamlit."""

        return {
            "wlc": self.wlc,
            "ap_name": self.ap_name,
            "site_tag": self.site_tag,
            "policy_tag": self.policy_tag,
            "rf_tag": self.rf_tag,
            "band": self.band,
            "current_channel": self.current_channel,
            "channel_width_mhz": self.channel_width_mhz,
            "receive_utilization_pct": self.receive_utilization_pct,
            "transmit_utilization_pct": self.transmit_utilization_pct,
            "channel_utilization_pct": self.channel_utilization_pct,
            "is_dfs_channel": self.is_dfs_channel,
            "cac_running": self.cac_running,
            "radar_changes_total": self.radar_changes_total,
            "zero_wait_dfs_capable": self.zero_wait_dfs_capable,
            "zero_wait_dfs_enabled": self.zero_wait_dfs_enabled,
            "nearby_ap_count": self.neighbor_count,
            "strongest_neighbor_rssi_dbm": self.strongest_neighbor_rssi_dbm,
            "weakest_neighbor_rssi_dbm": self.weakest_neighbor_rssi_dbm,
            "mean_neighbor_rssi_dbm": self.mean_neighbor_rssi_dbm,
            "neighbors_ge_neg65_dbm": self.neighbors_at_or_above(-65),
            "neighbors_ge_neg75_dbm": self.neighbors_at_or_above(-75),
            "neighbors_ge_neg80_dbm": self.neighbors_at_or_above(-80),
            "neighbors_ge_neg85_dbm": self.neighbors_at_or_above(-85),
            "unique_neighbor_channels": self.unique_neighbor_channels,
            "neighbor_channel_list": ",".join(str(ch) for ch in self.channel_list),
            "access_category_latency_observations": len(self.access_category_latencies),
            "source": self.source,
        }
