"""Prometheus textfile renderer for Catalyst Center badge client metrics."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable

try:
    from tools.common.prometheus import emit_metric, format_labels
except ModuleNotFoundError as exc:
    if exc.name != "tools":
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from tools.common.prometheus import emit_metric, format_labels

from .client_models import BadgeClientSnapshot


def _label_text(pairs: dict[str, object]) -> str:
    """Render already-normalized label pairs into Prometheus syntax."""

    return format_labels(pairs)


def stable_labels(snapshot: BadgeClientSnapshot, extra: dict[str, object] | None = None) -> str:
    """Labels shared by client-detail metrics with stable cardinality."""

    pairs: dict[str, object] = {
        "client_mac": snapshot.client_mac,
        "device_group": snapshot.device_group,
        "badge_model": snapshot.badge_model,
        "wlc": snapshot.wlc,
        "ssid": snapshot.ssid,
        "ap_name": snapshot.ap_name,
        "site_tag": snapshot.site_tag,
        "band": snapshot.band,
    }
    if extra:
        pairs.update(extra)
    return _label_text(pairs)


def current_ap_labels(snapshot: BadgeClientSnapshot) -> str:
    """Labels for the attachment-info series used by AP/client joins."""

    return _label_text(
        {
            "client_mac": snapshot.client_mac,
            "device_group": snapshot.device_group,
            "badge_model": snapshot.badge_model,
            "wlc": snapshot.wlc,
            "ssid": snapshot.ssid,
            "ap_name": snapshot.ap_name,
            "site_tag": snapshot.site_tag,
            "policy_tag": snapshot.policy_tag,
            "rf_tag": snapshot.rf_tag,
            "band": snapshot.band,
            "channel": snapshot.channel,
            "akm": snapshot.akm,
            "ft_state": snapshot.ft_state,
        }
    )


def render_badge_prometheus(snapshots: Iterable[BadgeClientSnapshot]) -> str:
    """Render badge snapshots into node-exporter textfile exposition format."""

    lines: list[str] = [
        "# HELP wireless_badge_client_present_cc 1 when a configured badge client was present in the latest collection.\n",
        "# TYPE wireless_badge_client_present_cc gauge\n",
        "# HELP wireless_badge_client_rssi_dbm_cc Client RSSI in dBm from Catalyst Center client detail.\n",
        "# TYPE wireless_badge_client_rssi_dbm_cc gauge\n",
        "# HELP wireless_badge_client_snr_db_cc Client SNR in dB from Catalyst Center client detail.\n",
        "# TYPE wireless_badge_client_snr_db_cc gauge\n",
        "# HELP wireless_badge_client_rx_retry_pct_cc Client receive retry percentage.\n",
        "# TYPE wireless_badge_client_rx_retry_pct_cc gauge\n",
        "# HELP wireless_badge_client_latency_voice_us_cc Client voice latency in microseconds.\n",
        "# TYPE wireless_badge_client_latency_voice_us_cc gauge\n",
        "# HELP wireless_badge_client_latency_be_us_cc Client Best Effort latency in microseconds.\n",
        "# TYPE wireless_badge_client_latency_be_us_cc gauge\n",
        "# HELP wireless_badge_client_max_roaming_duration_ms_cc Maximum roaming duration in milliseconds.\n",
        "# TYPE wireless_badge_client_max_roaming_duration_ms_cc gauge\n",
        "# HELP wireless_badge_client_average_auth_duration_ms_cc Average authentication duration in milliseconds.\n",
        "# TYPE wireless_badge_client_average_auth_duration_ms_cc gauge\n",
        "# HELP wireless_badge_client_average_assoc_duration_ms_cc Average association duration in milliseconds.\n",
        "# TYPE wireless_badge_client_average_assoc_duration_ms_cc gauge\n",
        "# HELP wireless_badge_client_average_dhcp_duration_ms_cc Average DHCP duration in milliseconds.\n",
        "# TYPE wireless_badge_client_average_dhcp_duration_ms_cc gauge\n",
        "# HELP wireless_badge_client_session_duration_s_cc Client session duration in seconds.\n",
        "# TYPE wireless_badge_client_session_duration_s_cc gauge\n",
        "# HELP wireless_badge_client_onboarding_attempts_cc Onboarding attempts observed for the client.\n",
        "# TYPE wireless_badge_client_onboarding_attempts_cc gauge\n",
        "# HELP wireless_badge_client_ft_state_cc 1 for the client's observed FT state, labeled by ft_state and akm.\n",
        "# TYPE wireless_badge_client_ft_state_cc gauge\n",
        "# HELP wireless_badge_client_current_ap_info_cc Current AP attachment labels for a badge client.\n",
        "# TYPE wireless_badge_client_current_ap_info_cc gauge\n",
    ]

    for snapshot in snapshots:
        # These are client-detail/MDT-derived metrics. They are intentionally
        # emitted with a _cc suffix so recording rules can distinguish them
        # from WLC AP traffic-distribution latency metrics.
        base = stable_labels(snapshot)
        lines.append(emit_metric("wireless_badge_client_present_cc", base, 1))
        lines.append(emit_metric("wireless_badge_client_rssi_dbm_cc", base, snapshot.rssi_dbm))
        lines.append(emit_metric("wireless_badge_client_snr_db_cc", base, snapshot.snr_db))
        lines.append(emit_metric("wireless_badge_client_rx_retry_pct_cc", base, snapshot.rx_retry_pct))
        lines.append(emit_metric("wireless_badge_client_latency_voice_us_cc", base, snapshot.latency_voice_us))
        lines.append(emit_metric("wireless_badge_client_latency_be_us_cc", base, snapshot.latency_be_us))
        lines.append(emit_metric("wireless_badge_client_max_roaming_duration_ms_cc", base, snapshot.max_roaming_duration_ms))
        lines.append(emit_metric("wireless_badge_client_average_auth_duration_ms_cc", base, snapshot.average_auth_duration_ms))
        lines.append(emit_metric("wireless_badge_client_average_assoc_duration_ms_cc", base, snapshot.average_assoc_duration_ms))
        lines.append(emit_metric("wireless_badge_client_average_dhcp_duration_ms_cc", base, snapshot.average_dhcp_duration_ms))
        lines.append(emit_metric("wireless_badge_client_session_duration_s_cc", base, snapshot.session_duration_s))
        lines.append(emit_metric("wireless_badge_client_onboarding_attempts_cc", base, snapshot.onboarding_attempts))
        lines.append(
            emit_metric(
                "wireless_badge_client_ft_state_cc",
                stable_labels(snapshot, {"ft_state": snapshot.ft_state, "akm": snapshot.akm}),
                1,
            )
        )
        lines.append(emit_metric("wireless_badge_client_current_ap_info_cc", current_ap_labels(snapshot), 1))

    return "".join(line for line in lines if line)
