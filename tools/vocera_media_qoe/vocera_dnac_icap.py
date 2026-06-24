#!/usr/bin/env python3
"""Download Catalyst Center ICAP packet captures for a specific client."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Mapping


try:
    from wireless_rf.dnac_client import CatalystCenterIcapReadClient
except ImportError as exc:  # pragma: no cover - exercised by operator environment
    raise RuntimeError("PYTHONPATH must include tools/wireless_rf for Catalyst Center ICAP downloads.") from exc


SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")
PCAP_EXTENSIONS = (".pcap", ".cap", ".pcapng")


def load_env_file(path: str | None) -> dict[str, str]:
    """Load KEY=VALUE pairs from an EnvironmentFile without shell expansion."""

    if not path:
        return {}
    env_path = Path(path)
    if not env_path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def _env_value(name: str, env_file_values: Mapping[str, str]) -> str | None:
    """Return an environment value, falling back to loaded EnvironmentFile values."""

    return os.environ.get(name) or env_file_values.get(name)


def _env_int(name: str, env_file_values: Mapping[str, str], default: int) -> int:
    """Return an integer environment setting with a default."""

    value = _env_value(name, env_file_values)
    return int(value) if value not in (None, "") else default


def normalize_mac(value: str, separator: str = ":") -> str:
    """Normalize a MAC address to lowercase hex pairs."""

    hex_chars = re.sub(r"[^0-9A-Fa-f]", "", value or "")
    if len(hex_chars) != 12:
        raise ValueError(f"invalid MAC address: {value!r}")
    pairs = [hex_chars[index:index + 2].lower() for index in range(0, 12, 2)]
    return separator.join(pairs)


def mac_token(value: str) -> str:
    """Return a filesystem-friendly MAC token."""

    return normalize_mac(value, separator="")


def safe_filename(value: str) -> str:
    """Constrain a Catalyst Center supplied file name to one path segment."""

    name = SAFE_FILENAME_RE.sub("_", value.strip()).strip("._")
    return name or "capture.pcap"


def _capture_value(capture: Mapping[str, Any], *keys: str) -> Any:
    """Return the first non-empty capture field from a list of aliases."""

    for key in keys:
        value = capture.get(key)
        if value not in (None, ""):
            return value
    return None


def capture_file_id(capture: Mapping[str, Any]) -> str:
    """Return the capture file identifier expected by the download endpoint."""

    value = _capture_value(capture, "id", "fileName", "name")
    if value is None:
        raise RuntimeError(f"ICAP capture file entry does not include id or fileName: {capture}")
    return str(value)


def capture_download_ids(capture: Mapping[str, Any]) -> list[str]:
    """Return candidate identifiers for Catalyst Center download variants."""

    candidates = []
    for key in ("id", "fileName", "name"):
        value = capture.get(key)
        if value not in (None, "") and str(value) not in candidates:
            candidates.append(str(value))
    if not candidates:
        raise RuntimeError(f"ICAP capture file entry does not include id or fileName: {capture}")
    return candidates


def capture_timestamp_ms(capture: Mapping[str, Any]) -> int:
    """Return a comparable capture timestamp in epoch milliseconds."""

    for key in ("fileCreationTimestamp", "lastUpdatedTimestamp", "startTime", "createdTime", "timestamp"):
        value = capture.get(key)
        if value in (None, ""):
            continue
        try:
            return int(float(value))
        except (TypeError, ValueError):
            continue
    return 0


def capture_file_size(capture: Mapping[str, Any]) -> int | None:
    """Return Catalyst Center's expected capture file size when present."""

    value = _capture_value(capture, "fileSize", "size", "length")
    try:
        size = int(value)
    except (TypeError, ValueError):
        return None
    return size if size > 0 else None


def capture_filename(capture: Mapping[str, Any], *, client_mac: str, capture_type: str) -> str:
    """Build a stable local file name for a downloaded ICAP capture."""

    raw_name = str(_capture_value(capture, "fileName", "id", "name") or "")
    name = safe_filename(raw_name)
    if not name.lower().endswith(PCAP_EXTENSIONS):
        name += ".pcap"

    token = mac_token(client_mac)
    if token not in name.replace(":", "").replace("-", "").replace("_", "").lower():
        timestamp = capture_timestamp_ms(capture)
        prefix_parts = ["dnac-icap", capture_type.lower(), token]
        if timestamp:
            prefix_parts.append(str(timestamp))
        name = safe_filename("-".join(prefix_parts) + "-" + name)
    return name


def _nested_mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    """Return a nested mapping value or an empty mapping."""

    value = payload.get(key)
    return value if isinstance(value, Mapping) else {}


def _first_string(*values: Any) -> str | None:
    """Return the first non-empty value as a string."""

    for value in values:
        if value not in (None, ""):
            return str(value)
    return None


def resolve_capture_ids(client_detail: Mapping[str, Any]) -> dict[str, str | None]:
    """Resolve Catalyst Center AP/WLC identifiers from client-detail payload."""

    detail = _nested_mapping(client_detail, "detail")
    connection_info = _nested_mapping(client_detail, "connectionInfo")
    topology = _nested_mapping(client_detail, "topology")
    connected_devices = detail.get("connectedDevice")
    connected_ap = connected_devices[0] if isinstance(connected_devices, list) and connected_devices else {}
    connected_ap = connected_ap if isinstance(connected_ap, Mapping) else {}

    ap_id = _first_string(connected_ap.get("id"))
    ap_name = _first_string(connection_info.get("nwDeviceName"), connected_ap.get("name"), detail.get("clientConnection"))
    ap_mac = _first_string(connection_info.get("nwDeviceMac"), connected_ap.get("mac"))
    wlc_id = _first_string(detail.get("wlcUuid"))
    wlc_name = _first_string(detail.get("wlcName"))

    nodes = topology.get("nodes")
    if isinstance(nodes, list):
        for node in nodes:
            if not isinstance(node, Mapping):
                continue
            description = str(node.get("description") or "").upper()
            family = str(node.get("family") or "").upper()
            if not ap_id and description == "AP":
                ap_id = _first_string(node.get("id"))
                ap_name = ap_name or _first_string(node.get("name"))
            if not wlc_id and (description == "WLC" or family == "WIRELESS CONTROLLER"):
                wlc_id = _first_string(node.get("id"))
                wlc_name = wlc_name or _first_string(node.get("name"))

    return {
        "ap_id": ap_id,
        "ap_name": ap_name,
        "ap_mac": ap_mac,
        "wlc_id": wlc_id,
        "wlc_name": wlc_name,
    }


def iter_capture_files(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Extract the response array from Catalyst Center ICAP list payloads."""

    response = payload.get("response", payload)
    if not isinstance(response, list):
        return []
    return [dict(item) for item in response if isinstance(item, Mapping)]


def _mac_matches(capture: Mapping[str, Any], expected_mac: str, field: str) -> bool:
    """Return true when an optional Catalyst Center MAC field matches."""

    value = capture.get(field)
    if not value:
        return True
    try:
        return normalize_mac(str(value)) == normalize_mac(expected_mac)
    except ValueError:
        return False


def filter_capture_files(
    captures: Iterable[Mapping[str, Any]],
    *,
    client_mac: str,
    ap_mac: str | None = None,
) -> list[dict[str, Any]]:
    """Apply local MAC filters in case Catalyst Center returns a wider page."""

    selected = []
    for capture in captures:
        if not _mac_matches(capture, client_mac, "clientMac"):
            continue
        if ap_mac and not _mac_matches(capture, ap_mac, "apMac"):
            continue
        selected.append(dict(capture))
    return selected


def select_latest_capture(captures: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Select the newest capture file by Catalyst Center timestamps."""

    ordered = sorted(captures, key=lambda item: (capture_timestamp_ms(item), str(_capture_value(item, "fileName", "id", "name") or "")))
    return dict(ordered[-1]) if ordered else None


def study_capture_ids(parsed_dir: Path) -> set[str]:
    """Return DNAC capture IDs and filenames already parsed into the study.

    Scans parsed_dir for batch-publisher cache JSONs and extracts the DNAC
    capture identity fields stored under source_pcap.dnac_metadata.capture.
    """
    known: set[str] = set()
    if not parsed_dir.is_dir():
        return known
    for json_path in parsed_dir.glob("*.json"):
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        source_pcap = payload.get("source_pcap")
        if not isinstance(source_pcap, dict):
            continue
        dnac_meta = source_pcap.get("dnac_metadata")
        if not isinstance(dnac_meta, dict):
            continue
        stored = dnac_meta.get("capture")
        if not isinstance(stored, dict):
            continue
        for key in ("id", "fileName", "name"):
            value = str(stored.get(key) or "").strip()
            if value:
                known.add(value)
    return known


def capture_in_study(capture: Mapping[str, Any], parsed_dir: Path) -> bool:
    """Return True when the capture already has a parse result in parsed_dir."""
    known = study_capture_ids(parsed_dir)
    if not known:
        return False
    for key in ("id", "fileName", "name"):
        value = str(capture.get(key) or "").strip()
        if value and value in known:
            return True
    return False


def write_metadata(path: Path, capture: Mapping[str, Any], output_path: Path, list_payload: Mapping[str, Any]) -> None:
    """Write a small sidecar JSON file for operator inspection."""

    payload = {
        "downloaded_at_seconds": int(time.time()),
        "capture": dict(capture),
        "output_path": str(output_path),
        "list_page": list_payload.get("page") if isinstance(list_payload, Mapping) else None,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def env_bool(name: str, default: bool = True, env_file_values: Mapping[str, str] | None = None) -> bool:
    """Read common boolean environment spellings."""

    env_file_values = env_file_values or {}
    value = _env_value(name, env_file_values)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def api_check_item(name: str, ok: bool, **fields: Any) -> dict[str, Any]:
    """Build one operator-facing API readiness check result."""

    result = {"name": name, "ok": ok}
    result.update(fields)
    return result


def api_error(exc: Exception) -> dict[str, Any]:
    """Return a bounded, non-secret error object for API check output."""

    message = str(exc)
    return {
        "error": message[:1200],
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse CLI arguments for ICAP API checks and completed-capture download."""

    parser = argparse.ArgumentParser(description="Download the newest Catalyst Center ICAP pcap for a client MAC.")
    parser.add_argument(
        "--env-file",
        default=os.environ.get("VOCERA_MEDIA_QOE_ENV_FILE", "/etc/grafana-mimir-observability/secrets/dnac-readonly.env"),
        help="Optional EnvironmentFile containing DNAC_* and VOCERA_MEDIA_QOE_DNAC_* values.",
    )
    parser.add_argument("--base-url", default=os.environ.get("DNAC_BASE_URL"))
    parser.add_argument("--username", default=os.environ.get("DNAC_USERNAME"))
    parser.add_argument("--password", default=os.environ.get("DNAC_PASSWORD"))
    parser.add_argument("--client-mac", default=os.environ.get("VOCERA_MEDIA_QOE_DNAC_CLIENT_MAC"), help="Client MAC to pass as the ICAP clientMac filter.")
    parser.add_argument("--ap-mac", help="Optional AP base radio MAC filter.")
    parser.add_argument("--capture-type", help="ICAP capture type, for example FULL, OTA, or ONBOARDING.")
    parser.add_argument("--check-api", action="store_true", help="Check Catalyst Center ICAP API readiness without starting a capture.")
    parser.add_argument("--lookback-minutes", type=int, help="Search window ending now. Use 0 to omit ICAP time filters.")
    parser.add_argument("--start-time-ms", type=int, help="Explicit ICAP startTime filter in epoch milliseconds.")
    parser.add_argument("--end-time-ms", type=int, help="Explicit ICAP endTime filter in epoch milliseconds.")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--offset", type=int, default=1)
    parser.add_argument("--out-dir")
    parser.add_argument("--metadata-out", help="Optional JSON sidecar path. Defaults beside the pcap.")
    parser.add_argument("--parsed-dir", help="Study parsed-output directory. When set, captures already present in the study are skipped without downloading.")
    parser.add_argument("--allow-empty", action="store_true", help="Exit 0 when no matching capture exists.")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing local file.")
    parser.add_argument("--print-path-only", action="store_true", help="Print only the selected local pcap path to stdout.")
    parser.add_argument("--insecure", action="store_true", help="Disable TLS certificate verification.")
    return parser.parse_args(argv)


def apply_env_defaults(args: argparse.Namespace, env_file_values: Mapping[str, str]) -> None:
    """Apply EnvironmentFile values to unset CLI options."""

    args.base_url = args.base_url or _env_value("DNAC_BASE_URL", env_file_values)
    args.username = args.username or _env_value("DNAC_USERNAME", env_file_values)
    args.password = args.password or _env_value("DNAC_PASSWORD", env_file_values)
    args.client_mac = args.client_mac or _env_value("VOCERA_MEDIA_QOE_DNAC_CLIENT_MAC", env_file_values)
    args.ap_mac = args.ap_mac or _env_value("VOCERA_MEDIA_QOE_DNAC_AP_MAC", env_file_values)
    args.capture_type = args.capture_type or _env_value("VOCERA_MEDIA_QOE_DNAC_CAPTURE_TYPE", env_file_values) or "FULL"
    if args.lookback_minutes is None:
        args.lookback_minutes = _env_int("VOCERA_MEDIA_QOE_DNAC_LOOKBACK_MINUTES", env_file_values, 0)
    if args.limit is None:
        args.limit = _env_int("VOCERA_MEDIA_QOE_DNAC_LIMIT", env_file_values, 20)
    args.out_dir = args.out_dir or _env_value("VOCERA_MEDIA_QOE_RAW_DIR", env_file_values) or "/var/lib/vocera-media-qoe/raw"
    args.parsed_dir = args.parsed_dir or _env_value("VOCERA_MEDIA_QOE_PARSED_DIR", env_file_values)
    if not args.insecure:
        args.insecure = not env_bool("DNAC_VERIFY_TLS", True, env_file_values)
    if not args.insecure:
        args.insecure = env_bool("VOCERA_MEDIA_QOE_DNAC_INSECURE", False, env_file_values)


def validate_args(args: argparse.Namespace) -> list[str]:
    """Return operator-facing validation errors for resolved arguments."""

    missing = [
        name for name, value in {
            "--base-url/DNAC_BASE_URL": args.base_url,
            "--username/DNAC_USERNAME": args.username,
            "--password/DNAC_PASSWORD": args.password,
            "--client-mac/VOCERA_MEDIA_QOE_DNAC_CLIENT_MAC": args.client_mac,
        }.items() if not value
    ]
    if args.lookback_minutes < 0:
        missing.append("--lookback-minutes must be zero or positive")
    if args.limit < 1:
        missing.append("--limit must be at least 1")
    if args.offset < 1:
        missing.append("--offset must be at least 1")
    return missing


def resolve_time_filters(args: argparse.Namespace) -> tuple[int | None, int | None]:
    """Resolve explicit or lookback ICAP time filters in epoch milliseconds."""

    if args.start_time_ms is not None or args.end_time_ms is not None:
        return args.start_time_ms, args.end_time_ms
    if args.lookback_minutes > 0:
        end_ms = int(time.time() * 1000)
        return end_ms - (args.lookback_minutes * 60 * 1000), end_ms
    return None, None


def check_api_readiness(client: CatalystCenterIcapReadClient, args: argparse.Namespace) -> int:
    """Check DNAC ICAP read/download API exposure without starting a capture."""

    checks: list[dict[str, Any]] = []
    client_mac = normalize_mac(args.client_mac)
    start_ms, end_ms = resolve_time_filters(args)

    try:
        client_detail = client.get_client_detail(client_mac)
        checks.append(api_check_item("client_detail", True, resolved=resolve_capture_ids(client_detail)))
    except Exception as exc:
        checks.append(api_check_item("client_detail", False, **api_error(exc)))

    try:
        payload = client.list_icap_capture_files(
            args.capture_type,
            client_mac=client_mac,
            start_time_ms=start_ms,
            end_time_ms=end_ms,
            limit=1,
            offset=1,
            sort_by="lastUpdatedTimestamp",
            order="desc",
        )
        checks.append(api_check_item("icap_capture_files", True, returned_files=len(iter_capture_files(payload))))
    except Exception as exc:
        checks.append(api_check_item("icap_capture_files", False, **api_error(exc)))

    ok = all(item["ok"] for item in checks)
    print(json.dumps({"checks": checks, "icap_download_ready": ok, "start_capture_available": False}, indent=2, sort_keys=True))
    return 0 if ok else 1


def command_download(args: argparse.Namespace) -> int:
    """Run the ICAP workflow: resolve config, optionally check, then download."""

    env_file_values = load_env_file(args.env_file)
    apply_env_defaults(args, env_file_values)
    missing = validate_args(args)
    if missing:
        print("ERROR: missing Catalyst Center ICAP values: " + ", ".join(missing), file=sys.stderr)
        return 2

    client_mac = normalize_mac(args.client_mac)
    ap_mac = normalize_mac(args.ap_mac) if args.ap_mac else None
    start_ms, end_ms = resolve_time_filters(args)

    client = CatalystCenterIcapReadClient(
        base_url=str(args.base_url),
        username=str(args.username),
        password=str(args.password),
        verify_tls=not args.insecure,
    )
    if args.check_api:
        return check_api_readiness(client, args)

    list_payload = client.list_icap_capture_files(
        args.capture_type,
        client_mac=client_mac,
        ap_mac=ap_mac,
        start_time_ms=start_ms,
        end_time_ms=end_ms,
        limit=args.limit,
        offset=args.offset,
        sort_by="lastUpdatedTimestamp",
        order="desc",
    )
    captures = filter_capture_files(iter_capture_files(list_payload), client_mac=client_mac, ap_mac=ap_mac)
    selected = select_latest_capture(captures)
    if not selected:
        message = f"no {args.capture_type} ICAP capture files found for client {client_mac}"
        if args.allow_empty:
            print(message, file=sys.stderr)
            return 0
        print("ERROR: " + message, file=sys.stderr)
        return 1

    if args.parsed_dir and not args.force:
        if capture_in_study(selected, Path(args.parsed_dir)):
            capture_id = str(_capture_value(selected, "id", "fileName", "name") or "<unknown>")
            print(f"Capture {capture_id} is already in the study ({args.parsed_dir}), skipping download", file=sys.stderr)
            return 0

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / capture_filename(selected, client_mac=client_mac, capture_type=args.capture_type)
    metadata_path = Path(args.metadata_out) if args.metadata_out else out_path.with_suffix(out_path.suffix + ".json")
    expected_size = capture_file_size(selected)

    if out_path.exists() and out_path.stat().st_size > 0 and not args.force:
        existing_size = out_path.stat().st_size
        if expected_size is None or existing_size == expected_size:
            write_metadata(metadata_path, selected, out_path, list_payload)
            if args.print_path_only:
                print(out_path)
            else:
                print(f"Using existing ICAP capture {out_path}", file=sys.stderr)
            return 0
        print(
            "Existing ICAP capture size does not match Catalyst Center metadata; "
            f"redownloading {out_path} local={existing_size} expected={expected_size}",
            file=sys.stderr,
        )

    data = b""
    last_error: Exception | None = None
    capture_id = capture_file_id(selected)
    for candidate_id in capture_download_ids(selected):
        capture_id = candidate_id
        try:
            data = client.download_icap_capture_file(candidate_id)
            break
        except Exception as exc:
            last_error = exc
    if not data and last_error:
        raise last_error
    if not data:
        print(f"ERROR: Catalyst Center returned an empty capture for {capture_id}", file=sys.stderr)
        return 1
    if expected_size is not None and len(data) != expected_size:
        print(
            "ERROR: downloaded ICAP capture size does not match Catalyst Center metadata: "
            f"downloaded={len(data)} expected={expected_size} capture={capture_id}",
            file=sys.stderr,
        )
        return 1
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp_path.write_bytes(data)
    tmp_path.replace(out_path)
    write_metadata(metadata_path, selected, out_path, list_payload)

    if args.print_path_only:
        print(out_path)
    else:
        print(f"Downloaded ICAP capture {capture_id} to {out_path}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint that reports bounded errors instead of stack traces."""

    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        return command_download(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
