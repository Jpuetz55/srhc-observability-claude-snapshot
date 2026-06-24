#!/usr/bin/env python3
"""Smoke-check the Study Web Media QoE project/study API workflow."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


DEFAULT_PROJECT_ID = "project_media_qoe_default"
DEFAULT_STUDY_ID = "study_media_qoe_default"


def api_json(api_base: str, path: str) -> dict[str, Any]:
    url = urllib.parse.urljoin(api_base.rstrip("/") + "/", path.lstrip("/"))
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{url} returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{url} failed: {exc.reason}") from exc
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{url} did not return JSON: {payload[:200]!r}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"{url} returned non-object JSON: {data!r}")
    return data


def api_post_expect_error(api_base: str, path: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    url = urllib.parse.urljoin(api_base.rstrip("/") + "/", path.lstrip("/"))
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            success = response.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{url} unexpectedly succeeded: {success[:200]!r}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(detail)
        except json.JSONDecodeError:
            parsed = {"detail": detail}
        if not isinstance(parsed, dict):
            parsed = {"detail": parsed}
        return exc.code, parsed
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{url} failed: {exc.reason}") from exc


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"ok - {message}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", default="http://127.0.0.1:8097")
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--study-id", default=DEFAULT_STUDY_ID)
    args = parser.parse_args(argv)

    media_summary = api_json(args.api_base, "/api/media-qoe/summary")
    require(media_summary.get("ok") is True, "media summary endpoint returns ok")
    require(media_summary.get("project", {}).get("project_id") == args.project_id, "default media project is exposed")
    require(media_summary.get("summary", {}).get("project_id") == args.project_id, "default media project summary is exposed")

    execution_status = api_json(args.api_base, "/api/media-qoe/execution/status")
    require(execution_status.get("ok") is True, "media execution status endpoint returns ok")
    require(execution_status.get("archive_enabled") is False, "media execution archive generation is disabled")
    require(isinstance(execution_status.get("execution_enabled"), bool), "media execution enabled flag is boolean")
    require(execution_status.get("raw_dir_exists") is True, "media raw directory exists")
    require(execution_status.get("raw_dir_readable") is True, "media raw directory is readable")
    require("parse_running" in execution_status, "media execution status exposes parse_running")
    require("active_parse" in execution_status, "media execution status exposes active_parse")

    dnac_status = api_json(args.api_base, "/api/media-qoe/dnac/status")
    require(dnac_status.get("ok") is True, "media DNAC/iCAP status endpoint returns ok")
    require(isinstance(dnac_status.get("configured"), bool), "media DNAC/iCAP status exposes configured flag")
    require(isinstance(dnac_status.get("start_capture_available"), bool), "media DNAC/iCAP status exposes start-capture availability")
    require(isinstance(dnac_status.get("download_enabled"), bool), "media DNAC/iCAP status exposes download guardrail")
    require(dnac_status.get("start_capture_available") is False, "media DNAC/iCAP API-start is intentionally unavailable")
    require("password" not in dnac_status and "token" not in dnac_status, "media DNAC/iCAP status does not expose credentials")

    project_summary = api_json(args.api_base, f"/api/projects/{urllib.parse.quote(args.project_id)}/media-qoe/summary")
    require(project_summary.get("ok") is True, "project media summary endpoint returns ok")
    require(project_summary.get("summary", {}).get("project_id") == args.project_id, "project media summary is scoped")

    project_captures = api_json(args.api_base, f"/api/projects/{urllib.parse.quote(args.project_id)}/media-qoe/captures")
    require(project_captures.get("ok") is True and isinstance(project_captures.get("captures"), list), "project media captures endpoint returns rows")

    project_streams = api_json(args.api_base, f"/api/projects/{urllib.parse.quote(args.project_id)}/media-qoe/streams")
    require(project_streams.get("ok") is True and isinstance(project_streams.get("streams"), list), "project media streams endpoint returns rows")

    duplicates = api_json(args.api_base, f"/api/projects/{urllib.parse.quote(args.project_id)}/media-qoe/duplicates")
    require(duplicates.get("ok") is True and isinstance(duplicates.get("duplicates"), list), "project media duplicate endpoint returns rows")

    study_captures = api_json(args.api_base, f"/api/studies/{urllib.parse.quote(args.study_id)}/media-qoe/captures")
    require(study_captures.get("ok") is True and isinstance(study_captures.get("captures"), list), "study media captures endpoint returns rows")

    study_streams = api_json(args.api_base, f"/api/studies/{urllib.parse.quote(args.study_id)}/media-qoe/streams")
    require(study_streams.get("ok") is True and isinstance(study_streams.get("streams"), list), "study media streams endpoint returns rows")

    raw_files = api_json(args.api_base, f"/api/studies/{urllib.parse.quote(args.study_id)}/media-qoe/raw-files")
    require(raw_files.get("ok") is True and isinstance(raw_files.get("files"), list), "study raw-files endpoint returns ok")
    raw_dir = str(raw_files.get("raw_dir") or "/var/lib/vocera-media-qoe/raw")

    outside_code, outside_error = api_post_expect_error(
        args.api_base,
        f"/api/studies/{urllib.parse.quote(args.study_id)}/media-qoe/captures/register",
        {"source_path": "/etc/hosts.pcap", "capture_point": "ICAP"},
    )
    require(outside_code == 400 and "under" in str(outside_error.get("detail", "")).lower(), "register rejects non-raw-dir path")

    unsupported_code, unsupported_error = api_post_expect_error(
        args.api_base,
        f"/api/studies/{urllib.parse.quote(args.study_id)}/media-qoe/captures/register",
        {"source_path": f"{raw_dir.rstrip('/')}/unsupported.txt", "capture_point": "ICAP"},
    )
    require(unsupported_code == 400 and "unsupported" in str(unsupported_error.get("detail", "")).lower(), "register rejects unsupported extension")

    grafana = api_json(args.api_base, "/api/grafana/status")
    require("grafana" in grafana, "Grafana status endpoint still responds")

    print("OK: media QoE Study Web smoke checks passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - script should print concise failure context
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
