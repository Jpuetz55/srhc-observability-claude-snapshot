"""Prometheus textfile renderer for normalized wireless RF snapshots."""

from __future__ import annotations

import time
import sys
from pathlib import Path
from typing import Iterable

try:
    from tools.common.prometheus import bool_value, emit_metric, escape_label, format_labels
except ModuleNotFoundError as exc:
    if exc.name != "tools":
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from tools.common.prometheus import bool_value, emit_metric, escape_label, format_labels

from .dfs import channel_family
from .models import ApRfSnapshot, WirelessRfCollectionStats


esc_label = escape_label


def labels(snapshot: ApRfSnapshot, extra: dict[str, object] | None = None) -> str:
    """Build the stable AP label set and allow metric-specific labels."""

    pairs = {
        "wlc": snapshot.wlc,
        "ap_name": snapshot.ap_name,
        "site_tag": snapshot.site_tag,
        "policy_tag": snapshot.policy_tag,
        "rf_tag": snapshot.rf_tag,
        "band": snapshot.band,
        "source": snapshot.source,
    }
    if extra:
        pairs.update(extra)
    return format_labels(pairs)


def _collection_stats_for_snapshots(
    snapshots: list[ApRfSnapshot],
    now: float,
    collection_stats: WirelessRfCollectionStats | None,
) -> WirelessRfCollectionStats:
    """Create conservative collection health metadata for parser-only runs."""

    if collection_stats is not None:
        return collection_stats
    wlc = snapshots[0].wlc if snapshots else "unknown"
    latency_samples_total = sum(
        1
        for snapshot in snapshots
        for latency in snapshot.access_category_latencies
        if latency.avg_latency_us is not None
    )
    return WirelessRfCollectionStats(
        wlc=wlc,
        last_success_timestamp_seconds=now,
        duration_seconds=0,
        ap_count=len({snapshot.ap_name for snapshot in snapshots if snapshot.ap_name != "unknown"}),
        latency_samples_total=latency_samples_total,
    )


def _render_collection_metrics(collection_stats: WirelessRfCollectionStats) -> list[str]:
    """Render run-level health and freshness metrics before per-AP samples."""

    collection_labels = f'wlc="{esc_label(collection_stats.wlc)}"'
    lines = [
        emit_metric(
            "wireless_rf_collection_last_success_timestamp_seconds",
            collection_labels,
            collection_stats.last_success_timestamp_seconds,
        ),
        emit_metric(
            "wireless_rf_collection_duration_seconds",
            collection_labels,
            collection_stats.duration_seconds,
        ),
        emit_metric(
            "wireless_rf_collection_commands_total",
            collection_labels,
            collection_stats.commands_total,
        ),
        emit_metric(
            "wireless_rf_collection_commands_failed_total",
            collection_labels,
            collection_stats.commands_failed_total,
        ),
        emit_metric("wireless_rf_collection_ap_count", collection_labels, collection_stats.ap_count),
        emit_metric(
            "wireless_rf_collection_latency_samples_total",
            collection_labels,
            collection_stats.latency_samples_total,
        ),
        emit_metric(
            "wireless_rf_collection_last_error",
            f'{collection_labels},reason="none"',
            0,
        ),
        emit_metric(
            "wireless_rf_collection_last_error",
            f'{collection_labels},reason="dnac_collect_failed"',
            1 if collection_stats.last_error_reason == "dnac_collect_failed" else 0,
        ),
    ]
    return lines


def render_prometheus(
    snapshots: Iterable[ApRfSnapshot],
    collection_stats: WirelessRfCollectionStats | None = None,
    now: float | None = None,
) -> str:
    """Render snapshots into node-exporter textfile exposition format."""

    snapshots = list(snapshots)
    now = time.time() if now is None else now
    collection_stats = _collection_stats_for_snapshots(snapshots, now, collection_stats)
    lines: list[str] = [
        "# HELP wireless_rf_collection_last_success_timestamp_seconds Unix timestamp of the last successful wireless RF raw-file parse/publish run.\n",
        "# TYPE wireless_rf_collection_last_success_timestamp_seconds gauge\n",
        "# HELP wireless_rf_collection_duration_seconds Duration of the latest wireless RF collection when known.\n",
        "# TYPE wireless_rf_collection_duration_seconds gauge\n",
        "# HELP wireless_rf_collection_commands_total CLI commands observed in the latest wireless RF raw evidence.\n",
        "# TYPE wireless_rf_collection_commands_total gauge\n",
        "# HELP wireless_rf_collection_commands_failed_total Failed, rejected, or blacklisted CLI command outputs observed in the latest raw evidence.\n",
        "# TYPE wireless_rf_collection_commands_failed_total gauge\n",
        "# HELP wireless_rf_collection_ap_count APs parsed in the latest wireless RF parse run.\n",
        "# TYPE wireless_rf_collection_ap_count gauge\n",
        "# HELP wireless_rf_collection_latency_samples_total AP traffic-distribution latency observations emitted in the latest parse run.\n",
        "# TYPE wireless_rf_collection_latency_samples_total gauge\n",
        "# HELP wireless_rf_collection_last_error 1 for the latest bounded wireless RF collection error reason, 0 otherwise.\n",
        "# TYPE wireless_rf_collection_last_error gauge\n",
        "# HELP wireless_ap_neighbor_count_cli Nearby AP count parsed from WLC auto-rf output.\n",
        "# TYPE wireless_ap_neighbor_count_cli gauge\n",
        "# HELP wireless_ap_neighbor_rssi_mean_dbm_cli Mean nearby AP RSSI in dBm parsed from WLC auto-rf output.\n",
        "# TYPE wireless_ap_neighbor_rssi_mean_dbm_cli gauge\n",
        "# HELP wireless_ap_neighbor_strongest_rssi_dbm_cli Strongest nearby AP RSSI in dBm.\n",
        "# TYPE wireless_ap_neighbor_strongest_rssi_dbm_cli gauge\n",
        "# HELP wireless_ap_neighbor_weakest_rssi_dbm_cli Weakest nearby AP RSSI in dBm.\n",
        "# TYPE wireless_ap_neighbor_weakest_rssi_dbm_cli gauge\n",
        "# HELP wireless_ap_neighbor_high_rssi_total_cli Nearby AP count at or above the labeled RSSI threshold.\n",
        "# TYPE wireless_ap_neighbor_high_rssi_total_cli gauge\n",
        "# HELP wireless_ap_neighbor_unique_channels_cli Unique nearby AP channels observed in the neighbor table.\n",
        "# TYPE wireless_ap_neighbor_unique_channels_cli gauge\n",
        "# HELP wireless_ap_current_channel_cli Current AP channel parsed from WLC output.\n",
        "# TYPE wireless_ap_current_channel_cli gauge\n",
        "# HELP wireless_ap_channel_width_mhz_cli Current AP channel width in MHz.\n",
        "# TYPE wireless_ap_channel_width_mhz_cli gauge\n",
        "# HELP wireless_ap_receive_utilization_pct_cli Receive utilization percentage parsed from WLC auto-rf load output.\n",
        "# TYPE wireless_ap_receive_utilization_pct_cli gauge\n",
        "# HELP wireless_ap_transmit_utilization_pct_cli Transmit utilization percentage parsed from WLC auto-rf load output.\n",
        "# TYPE wireless_ap_transmit_utilization_pct_cli gauge\n",
        "# HELP wireless_ap_channel_utilization_pct_cli Channel utilization percentage parsed from WLC auto-rf load output.\n",
        "# TYPE wireless_ap_channel_utilization_pct_cli gauge\n",
        "# HELP wireless_ap_channel_is_dfs_cli 1 when the current channel is a DFS channel.\n",
        "# TYPE wireless_ap_channel_is_dfs_cli gauge\n",
        "# HELP wireless_ap_dfs_cac_running_cli 1 when CAC appears to be running for the AP radio.\n",
        "# TYPE wireless_ap_dfs_cac_running_cli gauge\n",
        "# HELP wireless_ap_dfs_radar_changes_total_cli Channel changes due to radar counter parsed from WLC auto-rf output.\n",
        "# TYPE wireless_ap_dfs_radar_changes_total_cli counter\n",
        "# HELP wireless_ap_zero_wait_dfs_enabled_cli 1 when Zero Wait DFS appears enabled.\n",
        "# TYPE wireless_ap_zero_wait_dfs_enabled_cli gauge\n",
        "# HELP wireless_ap_ac_latency_avg_us_cli AP traffic-distribution average latency in microseconds by access category.\n",
        "# TYPE wireless_ap_ac_latency_avg_us_cli gauge\n",
        "# HELP wireless_ap_ac_latency_active_clients_cli Active clients sending the labeled access-category traffic.\n",
        "# TYPE wireless_ap_ac_latency_active_clients_cli gauge\n",
        "# HELP wireless_ap_ac_latency_packets_cli AP traffic-distribution packet count by access-category latency level.\n",
        "# TYPE wireless_ap_ac_latency_packets_cli gauge\n",
        "# HELP wireless_ap_ac_latency_sample_end_timestamp_seconds Unix timestamp parsed from the WLC traffic-distribution Time Period ending line.\n",
        "# TYPE wireless_ap_ac_latency_sample_end_timestamp_seconds gauge\n",
        "# HELP wireless_ap_ac_latency_sample_age_seconds Age of the WLC traffic-distribution sample when the Prometheus textfile was generated.\n",
        "# TYPE wireless_ap_ac_latency_sample_age_seconds gauge\n",
    ]
    lines.extend(_render_collection_metrics(collection_stats))

    for snapshot in snapshots:
        if snapshot.has_auto_rf:
            # Auto-rf metrics describe RF context for the AP/radio. Traffic
            # distribution latency is emitted below with a different source
            # label so dashboards do not mix RF context with AP voice samples.
            base = labels(snapshot, {"channel_family": channel_family(snapshot.current_channel)})
            lines.append(emit_metric("wireless_ap_neighbor_count_cli", base, snapshot.neighbor_count))
            lines.append(emit_metric("wireless_ap_neighbor_rssi_mean_dbm_cli", base, snapshot.mean_neighbor_rssi_dbm))
            lines.append(emit_metric("wireless_ap_neighbor_strongest_rssi_dbm_cli", base, snapshot.strongest_neighbor_rssi_dbm))
            lines.append(emit_metric("wireless_ap_neighbor_weakest_rssi_dbm_cli", base, snapshot.weakest_neighbor_rssi_dbm))
            lines.append(emit_metric("wireless_ap_neighbor_unique_channels_cli", base, snapshot.unique_neighbor_channels))
            lines.append(emit_metric("wireless_ap_current_channel_cli", base, snapshot.current_channel))
            lines.append(emit_metric("wireless_ap_channel_width_mhz_cli", base, snapshot.channel_width_mhz))
            lines.append(emit_metric("wireless_ap_receive_utilization_pct_cli", base, snapshot.receive_utilization_pct))
            lines.append(emit_metric("wireless_ap_transmit_utilization_pct_cli", base, snapshot.transmit_utilization_pct))
            lines.append(emit_metric("wireless_ap_channel_utilization_pct_cli", base, snapshot.channel_utilization_pct))
            lines.append(emit_metric("wireless_ap_channel_is_dfs_cli", base, snapshot.is_dfs_channel))
            lines.append(emit_metric("wireless_ap_dfs_cac_running_cli", base, snapshot.cac_running))
            lines.append(emit_metric("wireless_ap_dfs_radar_changes_total_cli", base, snapshot.radar_changes_total))
            lines.append(emit_metric("wireless_ap_zero_wait_dfs_enabled_cli", base, snapshot.zero_wait_dfs_enabled))
            for threshold in (-65, -75, -80, -85):
                threshold_labels = labels(
                    snapshot,
                    {
                        "channel_family": channel_family(snapshot.current_channel),
                        "threshold_dbm": threshold,
                    },
                )
                lines.append(
                    emit_metric(
                        "wireless_ap_neighbor_high_rssi_total_cli",
                        threshold_labels,
                        snapshot.neighbors_at_or_above(threshold),
                    )
                )

        for latency in snapshot.access_category_latencies:
            # AP traffic-distribution latency is AP-to-client access-category
            # data. It is intentionally separate from badge client-detail
            # latency metrics, which are emitted by client_prometheus.py.
            latency_labels = labels(
                snapshot,
                {
                    "band": latency.band,
                    "source": "traffic_distribution_cli",
                    "slot_id": latency.slot_id,
                    "access_category": latency.access_category,
                    "client_generation": latency.client_generation,
                },
            )
            lines.append(emit_metric("wireless_ap_ac_latency_avg_us_cli", latency_labels, latency.avg_latency_us))
            lines.append(emit_metric("wireless_ap_ac_latency_active_clients_cli", latency_labels, latency.active_clients))
            lines.append(
                emit_metric(
                    "wireless_ap_ac_latency_sample_end_timestamp_seconds",
                    latency_labels,
                    latency.sample_end_timestamp_seconds,
                )
            )
            sample_age_seconds = (
                now - latency.sample_end_timestamp_seconds
                if latency.sample_end_timestamp_seconds is not None
                else None
            )
            lines.append(emit_metric("wireless_ap_ac_latency_sample_age_seconds", latency_labels, sample_age_seconds))
            for level, value in latency.packets_by_latency_level.items():
                packet_labels = labels(
                    snapshot,
                    {
                        "band": latency.band,
                        "source": "traffic_distribution_cli",
                        "slot_id": latency.slot_id,
                        "access_category": latency.access_category,
                        "client_generation": latency.client_generation,
                        "latency_level": level,
                    },
                )
                lines.append(emit_metric("wireless_ap_ac_latency_packets_cli", packet_labels, value))

    return "".join(line for line in lines if line)
