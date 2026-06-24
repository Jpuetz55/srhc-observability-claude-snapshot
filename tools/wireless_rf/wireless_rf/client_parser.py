"""Best-effort parser for Catalyst Center client-detail badge JSON."""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

from .client_models import BadgeClientSnapshot
from .parser import normalize_mac

MAC_TOKEN_RE = re.compile(
    r"(?:[0-9a-fA-F]{2}(?:[:-][0-9a-fA-F]{2}){5}|"
    r"[0-9a-fA-F]{4}\.[0-9a-fA-F]{4}\.[0-9a-fA-F]{4}|"
    r"[0-9a-fA-F]{12})"
)
NORMALIZED_MAC_RE = re.compile(r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}")
NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


def normalize_client_mac(value: object) -> str:
    """Normalize MAC text from API payloads, CSVs, env vars, or config."""

    text = str(value or "").strip().lower()
    text = text.replace("-", ":")
    if re.fullmatch(r"[0-9a-f]{12}", text):
        return ":".join(text[i:i + 2] for i in range(0, 12, 2))
    return normalize_mac(text)


def _key(value: object) -> str:
    """Canonicalize API keys so camelCase/snake_case variants compare equal."""

    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _is_empty(value: object) -> bool:
    """Return true for API placeholder values that should be ignored."""

    return value is None or value == "" or value == []


def _find_value_for_key(payload: object, wanted_key: str) -> object | None:
    """Recursively find the first non-empty value for a normalized key."""

    if isinstance(payload, Mapping):
        for key, value in payload.items():
            if _key(key) == wanted_key and not _is_empty(value):
                return value
        for value in payload.values():
            found = _find_value_for_key(value, wanted_key)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _find_value_for_key(value, wanted_key)
            if found is not None:
                return found
    return None


def _first_value(payload: object, keys: Iterable[str]) -> object | None:
    """Return the first recursively discovered value from a list of key aliases."""

    for key in keys:
        found = _find_value_for_key(payload, _key(key))
        if found is not None:
            return found
    return None


def _text(value: object, default: str = "unknown") -> str:
    """Coerce non-empty values to text for stable labels."""

    if _is_empty(value):
        return default
    text = str(value).strip()
    return text if text else default


def _number(value: object) -> float | None:
    """Extract a numeric value from API scalars or strings with units."""

    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = NUMBER_RE.search(str(value).replace(",", ""))
    return float(match.group(0)) if match else None


def _first_number(
    payload: object,
    keys_with_multiplier: Iterable[tuple[str, float]],
    min_value: float | None = None,
) -> float | None:
    """Read the first matching numeric field and apply unit conversion."""

    for key, multiplier in keys_with_multiplier:
        value = _first_value(payload, [key])
        number = _number(value)
        if number is not None:
            result = number * multiplier
            if min_value is not None and result < min_value:
                return None
            return result
    return None


def _normalize_band(value: object) -> str:
    """Map Cisco/API radio names onto the dashboard's band labels."""

    text = str(value or "").strip().lower()
    if not text:
        return "unknown"
    compact = text.replace(" ", "").replace("_", "").replace("-", "")
    if "2.4" in compact or compact.startswith("24") or compact.startswith("2g"):
        return "24ghz"
    if "5" in compact and "ghz" in compact or compact.startswith("5g"):
        return "5ghz"
    if "6" in compact and "ghz" in compact or compact.startswith("6g"):
        return "6ghz"
    if compact in {"80211a", "a"}:
        return "5ghz"
    if compact in {"80211b", "80211g", "b", "g"}:
        return "24ghz"
    return text


def _extract_ap_name(search_space: Mapping[str, Any]) -> str:
    """Extract AP name, preferring direct string fields over connectedDevice list."""

    direct = _first_value(search_space, ["ap_name", "apName", "clientConnection", "nwDeviceName", "connectedDeviceName", "accessPoint"])
    if direct and not isinstance(direct, list):
        return _text(direct)
    connected = _first_value(search_space, ["connectedDevice"])
    if isinstance(connected, list):
        for entry in connected:
            if isinstance(entry, dict) and str(entry.get("type", "")).upper() == "AP":
                return _text(entry.get("name") or entry.get("id") or "")
    if isinstance(direct, list):
        return _text(direct[0] if direct else "")
    return "unknown"


def _normalize_wlc(value: str) -> str:
    """Strip domain suffix from DNAC-reported FQDN so it matches MDT short hostnames."""
    return value.split(".")[0] if value else value


def _normalize_ft_state(value: object, akm: str) -> str:
    """Infer 802.11r/FT state from explicit fields or the AKM string."""

    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if text in {"ft", "fast_transition", "802.11r", "80211r", "enabled", "true", "yes"}:
        return "ft"
    if text in {"non_ft", "nonft", "not_ft", "disabled", "false", "no"}:
        return "non_ft"
    akm_text = akm.lower()
    if "802.11r" in akm_text or "80211r" in akm_text or re.search(r"\bft\b", akm_text):
        return "ft"
    return "unknown"


def _defaults(defaults: Mapping[str, object] | None) -> dict[str, object]:
    """Fill parser defaults supplied by a collection job."""

    defaults = defaults or {}
    return {
        "device_group": defaults.get("device_group") or "VOCERA",
        "badge_model": defaults.get("badge_model") or "unknown",
        "wlc": defaults.get("wlc") or "unknown",
        "ssid": defaults.get("ssid") or "unknown",
        "source": defaults.get("source") or "catalyst_center",
        "collected_at_ms": defaults.get("collected_at_ms"),
    }


def parse_client_detail_payload(
    payload: Mapping[str, Any],
    defaults: Mapping[str, object] | None = None,
) -> BadgeClientSnapshot | None:
    """Parse one Catalyst Center client-detail record into a normalized row."""

    base = _defaults(defaults)
    detail = payload.get("detail") or payload.get("client_detail") or payload.get("payload") or payload
    search_space = {"record": payload, "detail": detail}

    raw_mac = _first_value(search_space, ["client_mac", "clientMac", "macAddress", "hostMac", "host_mac", "mac"])
    client_mac = normalize_client_mac(raw_mac)
    if not NORMALIZED_MAC_RE.fullmatch(client_mac):
        # Client-detail endpoints sometimes return errors or partial records;
        # invalid MACs are skipped rather than emitting unusable time series.
        return None

    akm = _text(_first_value(search_space, ["akm", "authKeyMgmt", "auth_key_mgmt", "authenticationMethod"]))
    ft_state = _normalize_ft_state(_first_value(search_space, ["ft_state", "ftState", "fastTransitionState", "80211rState"]), akm)
    ssid = _text(_first_value(search_space, ["ssid", "wlanSsid", "wlanProfileName"]), str(base["ssid"]))
    badge_model = _text(
        _first_value(search_space, ["badge_model", "badgeModel", "deviceModel", "model", "deviceType", "device_type"]),
        str(base["badge_model"]),
    )

    return BadgeClientSnapshot(
        client_mac=client_mac,
        device_group=_text(_first_value(search_space, ["device_group", "deviceGroup"]), str(base["device_group"])),
        badge_model=badge_model,
        wlc=_normalize_wlc(_text(_first_value(search_space, ["wlc", "wlcName", "controller", "controllerName", "wirelessControllerName"]), str(base["wlc"]))),
        ssid=ssid,
        ap_name=_extract_ap_name(search_space),
        site_tag=_text(_first_value(search_space, ["site_tag", "siteTag", "site", "siteName"])),
        policy_tag=_text(_first_value(search_space, ["policy_tag", "policyTag"])),
        rf_tag=_text(_first_value(search_space, ["rf_tag", "rfTag"])),
        band=_normalize_band(_first_value(search_space, ["band", "frequency", "radioType", "radioBand"])),
        channel=_text(_first_value(search_space, ["channel", "radioChannel"])),
        rssi_dbm=_first_number(search_space, [("rssi_dbm", 1), ("rssiDbm", 1), ("rssi", 1)]),
        snr_db=_first_number(search_space, [("snr_db", 1), ("snrDb", 1), ("snr", 1)]),
        rx_retry_pct=_first_number(
            search_space,
            [
                ("rx_retry_pct", 1),
                ("rxRetryPct", 1),
                ("rxRetriesPct", 1),
                ("rxRetryPercent", 1),
                ("rxRetryPercentage", 1),
            ],
        ),
        latency_voice_us=_first_number(
            search_space,
            [
                ("latency_voice_us", 1),
                ("latencyVoiceUs", 1),
                ("voiceLatencyUs", 1),
                ("voice_latency_us", 1),
                ("latency_voice_ms", 1000),
                ("latencyVoiceMs", 1000),
                ("voiceLatencyMs", 1000),
                ("voice_latency_ms", 1000),
                ("latencyVoice", 1),
                ("voiceLatency", 1),
            ],
            min_value=0,
        ),
        latency_be_us=_first_number(
            search_space,
            [
                ("latency_be_us", 1),
                ("latencyBeUs", 1),
                ("beLatencyUs", 1),
                ("bestEffortLatencyUs", 1),
                ("latency_be_ms", 1000),
                ("latencyBeMs", 1000),
                ("beLatencyMs", 1000),
                ("bestEffortLatencyMs", 1000),
                ("latencyBe", 1),
                ("beLatency", 1),
                ("bestEffortLatency", 1),
            ],
            min_value=0,
        ),
        max_roaming_duration_ms=_first_number(
            search_space,
            [("max_roaming_duration_ms", 1), ("maxRoamingDurationMs", 1), ("maxRoamingDuration", 1)],
            min_value=0,
        ),
        average_auth_duration_ms=_first_number(
            search_space,
            [("average_auth_duration_ms", 1), ("averageAuthDurationMs", 1), ("averageAuthDuration", 1)],
            min_value=0,
        ),
        average_assoc_duration_ms=_first_number(
            search_space,
            [("average_assoc_duration_ms", 1), ("averageAssocDurationMs", 1), ("averageAssocDuration", 1)],
            min_value=0,
        ),
        average_dhcp_duration_ms=_first_number(
            search_space,
            [("average_dhcp_duration_ms", 1), ("averageDhcpDurationMs", 1), ("averageDhcpDuration", 1)],
            min_value=0,
        ),
        session_duration_s=_first_number(
            search_space,
            [("session_duration_s", 1), ("sessionDurationS", 1), ("sessionDurationSeconds", 1), ("sessionDuration", 1)],
            min_value=0,
        ),
        onboarding_attempts=_first_number(
            search_space,
            [("onboarding_attempts", 1), ("onboardingAttempts", 1)],
            min_value=0,
        ),
        akm=akm,
        ft_state=ft_state,
        source=str(base["source"]),
        collected_at_ms=int(base["collected_at_ms"]) if base.get("collected_at_ms") is not None else None,
    )


def parse_badge_client_raw(payload: object) -> list[BadgeClientSnapshot]:
    """Parse either the collector's multi-job payload or a flat client list."""

    snapshots: list[BadgeClientSnapshot] = []
    if isinstance(payload, Mapping) and isinstance(payload.get("jobs"), list):
        for job in payload["jobs"]:
            if not isinstance(job, Mapping):
                continue
            defaults = {
                "device_group": job.get("device_group"),
                "wlc": job.get("wlc"),
                "source": payload.get("source") or "catalyst_center",
                "collected_at_ms": job.get("collected_at_ms") or payload.get("collected_at_ms"),
            }
            ssids = job.get("ssids")
            badge_models = job.get("badge_models")
            if isinstance(ssids, list) and len(ssids) == 1:
                defaults["ssid"] = ssids[0]
            if isinstance(badge_models, list) and len(badge_models) == 1:
                defaults["badge_model"] = badge_models[0]
            for record in job.get("clients", []):
                if not isinstance(record, Mapping) or record.get("error"):
                    continue
                snapshot = parse_client_detail_payload(record, defaults)
                if snapshot:
                    snapshots.append(snapshot)
        return snapshots

    records: list[object]
    if isinstance(payload, Mapping) and isinstance(payload.get("clients"), list):
        records = payload["clients"]
    elif isinstance(payload, list):
        records = payload
    else:
        records = [payload]

    for record in records:
        if isinstance(record, Mapping):
            snapshot = parse_client_detail_payload(record)
            if snapshot:
                snapshots.append(snapshot)
    return snapshots


def filter_badge_snapshots(
    snapshots: Iterable[BadgeClientSnapshot],
    device_group: str | None = None,
    wlc: str | None = None,
    ssid: str | None = None,
    badge_model: str | None = None,
) -> list[BadgeClientSnapshot]:
    """Apply dashboard/job filters after parsing badge snapshots."""

    output: list[BadgeClientSnapshot] = []
    for snapshot in snapshots:
        if device_group and snapshot.device_group != device_group:
            continue
        if wlc and snapshot.wlc != wlc:
            continue
        if ssid and snapshot.ssid != ssid:
            continue
        if badge_model and snapshot.badge_model != badge_model:
            continue
        output.append(snapshot)
    return output
