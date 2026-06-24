#!/usr/bin/env python3
"""Tests for Vocera badge-side RF validation tooling."""

from __future__ import annotations

import csv
import binascii
import contextlib
import io
import json
import struct
import tempfile
import zipfile
import zlib
from datetime import timedelta
from pathlib import Path

import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.vocera_rf_validation.badge_diag_parser import parse_badge_input  # noqa: E402
from tools.vocera_rf_validation import cli as rf_cli  # noqa: E402
from tools.vocera_rf_validation.config import load_config  # noqa: E402
from tools.vocera_rf_validation.correlate import (  # noqa: E402
    build_manual_entry_template,
    correlate_template_csv,
    correlate_template_rows,
    resolve_vendor_offset,
    summarize_match_alignment,
    write_template_csv,
)
from tools.vocera_rf_validation.ekahau_importer import parse_ekahau_json  # noqa: E402
from tools.vocera_rf_validation.ipad_client_detail import parse_client_detail_input, parse_client_detail_inputs  # noqa: E402
from tools.vocera_rf_validation.models import derive_band_from_channel, normalize_mac  # noqa: E402
from tools.vocera_rf_validation.sql_export import emit_sql  # noqa: E402
from tools.vocera_rf_validation.stats import annotate_outliers  # noqa: E402
from tools.study_web.sample_statistics import summarize_metric, summarize_samples  # noqa: E402


FIXTURES = ROOT / "tests" / "fixtures" / "vocera_rf_validation"
TEST_RUN_ID = "srhc_basement_vocera_ekahau_2026_05_21_0947"


def require(condition: bool, message: str) -> None:
    """Raise an assertion with a clear fixture-specific message."""

    if not condition:
        raise AssertionError(message)


def _approx(actual: float | None, expected: float, tol: float = 1e-6) -> bool:
    return actual is not None and abs(actual - expected) <= tol


def test_manual_sample_statistics() -> None:
    """Verify central-limit summary statistics and outlier flagging for Cal Delta."""
    import statistics as _stats

    delta_values = [-5.0, -6.0, -4.0, -5.5, -4.5, 18.0]
    samples = [
        {"sample_id": f"s{i}", "calibrated_delta_db": str(v)}
        for i, v in enumerate(delta_values)
    ]
    result = summarize_samples(samples, z_threshold=2.0)
    delta = result["statistics"]["cal_delta"]

    require(delta["count"] == len(delta_values), "cal delta count mismatch")
    require(_approx(delta["mean"], _stats.mean(delta_values)), "cal delta mean mismatch")
    require(_approx(delta["stddev"], _stats.stdev(delta_values)), "cal delta stddev mismatch")
    require(_approx(delta["min"], -6.0) and _approx(delta["max"], 18.0), "cal delta min/max mismatch")
    require(_approx(delta["sem"], _stats.stdev(delta_values) / (len(delta_values) ** 0.5)), "cal delta sem mismatch")
    require(delta["p05"] is not None and delta["p95"] is not None, "cal delta percentiles missing")
    require(delta["p05"] <= delta["p50"] <= delta["p95"], "cal delta percentiles not ordered")
    require(delta["ci95_low"] is not None and delta["ci95_high"] is not None, "cal delta 95% CI missing")

    # The lone +18 dB delta is the outlier; the clustered values are not.
    require(delta["outlier_count"] == 1, f"expected one cal delta outlier, got {delta['outlier_count']}")
    outliers = [s for s in result["samples"] if s["cal_delta_is_outlier"]]
    require(len(outliers) == 1, f"expected one flagged sample, got {len(outliers)}")
    require(_approx(float(outliers[0]["calibrated_delta_db"]), 18.0), "wrong cal delta outlier flagged")
    require(outliers[0].get("is_outlier") is True, "combined outlier flag not set")

    # Empty and single-sample edge cases must not raise.
    empty = summarize_metric([])
    require(empty["count"] == 0 and empty["mean"] is None, "empty metric should be null")
    single = summarize_metric([42.0])
    require(single["count"] == 1 and _approx(single["mean"], 42.0), "single metric mean mismatch")
    require(single["stddev"] is None and single["sem"] is None, "single metric stddev/sem should be null")

    # Samples with no numeric Cal Delta are ignored without error.
    blank = summarize_samples([{"sample_id": "b", "calibrated_delta_db": ""}])
    require(blank["statistics"]["cal_delta"]["count"] == 0, "blank sample should not count")


def test_normalization() -> None:
    """Verify shared MAC and channel-band normalization helpers."""

    require(normalize_mac("0009.ef54.5f46") == "00:09:ef:54:5f:46", "failed dotted MAC normalization")
    require(derive_band_from_channel(1) == "2.4GHz", "channel 1 should be 2.4GHz")
    require(derive_band_from_channel(140) == "5GHz", "channel 140 should be 5GHz")
    require(derive_band_from_channel(5, op_class=131) == "6GHz", "6GHz op_class should override ambiguous channel")


def test_badge_parser() -> None:
    """Verify badge diagnostic parsing for roam candidates and radio samples."""

    result = parse_badge_input(
        FIXTURES / "badge_sys_single_roam.txt",
        test_run_id=TEST_RUN_ID,
        badge_mac="00:09:ef:54:5f:46",
    )
    require(result.parse_success, "badge parser did not report success")
    require(len(result.events) == 1, f"expected one event, got {len(result.events)}")
    event = result.events[0]
    require(event.roam_reason == "BRCMF_E_REASON_LOW_RSSI[1]", f"bad roam reason: {event.roam_reason}")
    require(event.total_aps == 2, f"bad total AP count: {event.total_aps}")
    require(event.outage_ms == 101, f"bad outage: {event.outage_ms}")
    require(event.connected_bssid == "f0:d8:05:1f:74:96", f"bad connected BSSID: {event.connected_bssid}")
    require(len(event.candidates) == 2, f"expected two candidates, got {len(event.candidates)}")
    require(event.candidates[0].selected, "first candidate should be selected")
    require(event.candidates[0].band == "5GHz", f"bad band: {event.candidates[0].band}")
    require(event.candidates[1].band == "2.4GHz", f"bad band: {event.candidates[1].band}")
    require(len(result.rrm_neighbors) == 2, f"expected two RRM neighbors, got {len(result.rrm_neighbors)}")
    require(result.rrm_neighbors[0].bssid == "f0:d8:05:1f:74:96", "bad first RRM neighbor BSSID")
    require(result.rrm_neighbors[1].bssid == "50:5c:88:00:ce:a6", "bad second RRM neighbor BSSID")
    require(len(result.radio_signal_samples) == 1, f"expected one radio signal sample, got {len(result.radio_signal_samples)}")
    sample = result.radio_signal_samples[0]
    require(sample.noise_dbm == -90, f"bad radio noise floor: {sample.noise_dbm}")
    require(sample.snr_db == 44, f"bad radio SNR: {sample.snr_db}")
    require(sample.channel == 140, f"bad radio channel: {sample.channel}")


def test_ekahau_timestamp_parser() -> None:
    """Verify Ekahau JSON survey timestamps and coordinates are parsed."""

    config = load_config(ROOT / "config" / "vocera-rf-validation.example.yaml")
    result = parse_ekahau_json(FIXTURES / "ekahau_export_sample.json", test_run_id=TEST_RUN_ID, config=config)
    require(result.parse_success, "Ekahau parser did not report success")
    require(len(result.survey_points) == 2, f"expected two survey points, got {len(result.survey_points)}")
    point = result.survey_points[0]
    require(point.survey_point_id == "p1", f"bad survey point id: {point.survey_point_id}")
    require(point.floor == "Basement", f"bad floor: {point.floor}")
    require(point.x_m == 12.3, f"bad x coordinate: {point.x_m}")


def test_ipad_client_detail_parser_uses_only_client_scan_reports() -> None:
    """Verify iPad WLC parsing ignores Nearby AP and AP-side statistics rows."""

    result = parse_client_detail_input(
        FIXTURES / "ipad_client_detail_scan_reports.txt",
        test_run_id="ipad_wlc_ekahau_test",
        client_mac="aa:bb:cc:dd:ee:ff",
    )
    require(result.parse_success, f"iPad client-detail parse failed: {result.parse_error}")
    require(len(result.events) == 1, f"expected one iPad scan event, got {len(result.events)}")
    event = result.events[0]
    require(event.badge_model == "iPad", f"bad iPad model label: {event.badge_model}")
    require(event.event_time.isoformat() == "2026-05-21T09:46:30-05:00", f"bad scan-report time: {event.event_time}")
    require(event.connected_bssid == "50:5c:88:02:80:79", f"bad connected BSSID: {event.connected_bssid}")
    require(len(event.candidates) == 2, f"expected two Client Scan Reports rows, got {len(event.candidates)}")
    bssids = {candidate.bssid for candidate in event.candidates}
    require("f0:d8:05:1f:74:c9" not in bssids, "Nearby AP Statistics row should not be imported")
    selected = next(candidate for candidate in event.candidates if candidate.bssid == "50:5c:88:02:80:79")
    require(selected.selected, "connected BSSID should be marked selected")
    require(selected.rssi_dbm == -71, f"bad iPad scan RSSI: {selected.rssi_dbm}")
    require(selected.snr_db == 27, f"bad iPad scan SNR: {selected.snr_db}")
    require(selected.noise_dbm == -98, f"bad iPad derived noise floor: {selected.noise_dbm}")

    merged = parse_client_detail_inputs(
        [FIXTURES / "ipad_client_detail_scan_reports.txt", FIXTURES / "ipad_client_detail_scan_reports.txt"],
        test_run_id="ipad_wlc_ekahau_test",
        client_mac="aa:bb:cc:dd:ee:ff",
    )
    require(len(merged.events) == 1, f"duplicate snapshots should dedupe identical events, got {len(merged.events)}")


def test_ekahau_esx_survey_archive_parser() -> None:
    """Verify Ekahau .esx archives parse route points and AP metadata."""

    config = load_config(ROOT / "config" / "vocera-rf-validation.example.yaml")
    with tempfile.TemporaryDirectory() as tmp:
        esx_path = Path(tmp) / "survey.esx"
        with zipfile.ZipFile(esx_path, "w") as archive:
            archive.writestr(
                "floorPlans.json",
                json.dumps(
                    {
                        "floorPlans": [
                            {"id": "floor-5", "name": "SRHC - 5th floor"},
                        ]
                    }
                ),
            )
            archive.writestr(
                "accessPoints.json",
                json.dumps({"accessPoints": [{"id": "ap1", "name": "SFB-LAB-AP2"}]}),
            )
            archive.writestr(
                "accessPointMeasurements.json",
                json.dumps(
                    {
                        "accessPointMeasurements": [
                            {"id": "m1", "mac": "f0:d8:05:1f:74:96"},
                        ]
                    }
                ),
            )
            archive.writestr(
                "measuredRadios.json",
                json.dumps({"measuredRadios": [{"accessPointId": "ap1", "accessPointMeasurementIds": ["m1"]}]}),
            )
            archive.writestr(
                "survey-one.json",
                json.dumps(
                    {
                        "surveys": [
                            {
                                "id": "survey-one",
                                "name": "walk one",
                                "startTime": "2026-04-16T17:48:49.534Z",
                                "floorPlanId": "floor-5",
                                "routePoints": [
                                    [
                                        {"time": 3_000_000, "location": {"x": 10.0, "y": 20.0}},
                                        {"time": 5_004_000_000, "location": {"x": 11.0, "y": 21.0}},
                                    ]
                                ],
                            }
                        ]
                    }
                ),
            )
            archive.writestr(
                "survey-two.json",
                json.dumps(
                    {
                        "surveys": [
                            {
                                "id": "survey-two",
                                "startTime": "2026-04-16T18:00:00Z",
                                "floorPlanId": "floor-5",
                                "routePoints": [{"time": 1_000_000_000, "location": {"x": 12.0, "y": 22.0}}],
                            }
                        ]
                    }
                ),
            )

        result = parse_ekahau_json(esx_path, test_run_id=TEST_RUN_ID, config=config)

    require(result.parse_success, "Ekahau .esx parser did not report success")
    require(len(result.survey_points) == 3, f"expected three route points, got {len(result.survey_points)}")
    require(result.survey_points[0].floor == "SRHC - 5th floor", f"bad floor: {result.survey_points[0].floor}")
    require(result.ap_name_by_bssid["f0:d8:05:1f:74:96"] == "SFB-LAB-AP2", "bad BSSID to AP name mapping")
    require(result.survey_points[0].measured_at.isoformat().startswith("2026-04-16T12:48:49.537"), "bad nanosecond offset conversion")
    require(result.survey_points[1].measured_at.isoformat().startswith("2026-04-16T12:48:54.538"), "bad second route point conversion")


def test_ekahau_streaming_esx_without_central_directory() -> None:
    """Verify partially streamed .esx ZIP data can still be parsed."""

    config = load_config(ROOT / "config" / "vocera-rf-validation.example.yaml")

    def local_zip_entry(name: str, payload: bytes) -> bytes:
        """Build a local ZIP entry with a data descriptor and no central directory."""

        compressor = zlib.compressobj(level=6, wbits=-zlib.MAX_WBITS)
        compressed = compressor.compress(payload) + compressor.flush()
        encoded_name = name.encode("utf-8")
        header = struct.pack(
            "<IHHHHHIIIHH",
            0x04034B50,
            20,
            0x08,
            8,
            0,
            0,
            0,
            0,
            0,
            len(encoded_name),
            0,
        )
        descriptor = struct.pack("<IIII", 0x08074B50, binascii.crc32(payload) & 0xFFFFFFFF, len(compressed), len(payload))
        return header + encoded_name + compressed + descriptor

    with tempfile.TemporaryDirectory() as tmp:
        esx_path = Path(tmp) / "streaming.esx"
        esx_path.write_bytes(
            local_zip_entry("floorPlans.json", json.dumps({"floorPlans": [{"id": "floor-5", "name": "SRHC - 5th floor"}]}).encode("utf-8"))
            + local_zip_entry(
                "survey-one.json",
                json.dumps(
                    {
                        "surveys": [
                            {
                                "id": "survey-one",
                                "startTime": "2026-04-16T17:48:49.534Z",
                                "floorPlanId": "floor-5",
                                "routePoints": [{"time": 3_000_000, "location": {"x": 10.0, "y": 20.0}}],
                            }
                        ]
                    }
                ).encode("utf-8"),
            )
        )

        result = parse_ekahau_json(esx_path, test_run_id=TEST_RUN_ID, config=config)

    require(result.parse_success, "streaming Ekahau .esx parser did not report success")
    require(len(result.survey_points) == 1, f"expected one streaming route point, got {len(result.survey_points)}")
    require(result.survey_points[0].floor == "SRHC - 5th floor", f"bad streaming floor: {result.survey_points[0].floor}")


def test_template_and_correlation() -> None:
    """Verify automatic badge/Ekahau template rows and manual correlation math."""

    config = load_config(ROOT / "config" / "vocera-rf-validation.example.yaml")
    badge = parse_badge_input(
        FIXTURES / "badge_sys_single_roam.txt",
        test_run_id=TEST_RUN_ID,
        badge_mac="00:09:ef:54:5f:46",
    )
    ekahau = parse_ekahau_json(FIXTURES / "ekahau_export_sample.json", test_run_id=TEST_RUN_ID, config=config)
    ekahau.ap_name_by_bssid["f0:d8:05:1f:74:96"] = "SFB-LAB-AP2"
    rows = build_manual_entry_template(badge, ekahau, config=config)
    require(len(rows) == 2, f"expected two manual template rows, got {len(rows)}")
    require(rows[0].survey_point_id == "p1", "template should use matching Ekahau timestamp")
    require(rows[0].match_quality == "exact_1s", f"bad match quality: {rows[0].match_quality}")
    require(rows[0].ap_name == "SFB-LAB-AP2", f"bad AP name: {rows[0].ap_name}")
    require(rows[0].badge_noise_floor_dbm == -90, f"bad badge noise floor: {rows[0].badge_noise_floor_dbm}")
    require(rows[0].badge_snr_db == 44, f"bad badge SNR: {rows[0].badge_snr_db}")
    require(
        rows[0].badge_snr_source == "associated_radio_signal_level_minus_snr",
        f"bad badge SNR source: {rows[0].badge_snr_source}",
    )
    require(rows[1].badge_snr_db == 44, f"bad event-level non-associated badge SNR: {rows[1].badge_snr_db}")
    require(rows[1].badge_snr_source == "associated_radio_signal_event_level", f"bad non-associated SNR source: {rows[1].badge_snr_source}")
    require(rows[0].ekahau_rssi_dbm is None, "template should leave manual RSSI blank")

    with tempfile.TemporaryDirectory() as tmp:
        template_path = Path(tmp) / "manual.csv"
        write_template_csv(rows, template_path)
        with template_path.open(newline="", encoding="utf-8") as handle:
            reader = list(csv.DictReader(handle))
        reader[0]["ekahau_rssi_dbm"] = "-38"
        reader[0]["ekahau_snr_db"] = "32"
        reader[1]["ekahau_rssi_dbm"] = "-55"
        reader[1]["ekahau_snr_db"] = "24"
        with template_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=reader[0].keys())
            writer.writeheader()
            writer.writerows(reader)

        matches = correlate_template_csv(template_path, config=config)

    require(len(matches) == 2, f"expected two matches, got {len(matches)}")
    five_ghz = next(match for match in matches if match.band == "5GHz")
    require(five_ghz.ap_name == "SFB-LAB-AP2", f"bad correlated AP name: {five_ghz.ap_name}")
    require(five_ghz.badge_snr_db == 44, f"bad correlated badge SNR: {five_ghz.badge_snr_db}")
    require(five_ghz.badge_noise_floor_dbm == -90, f"bad correlated noise floor: {five_ghz.badge_noise_floor_dbm}")
    require(five_ghz.vendor_offset_db == -8, f"bad 5GHz offset: {five_ghz.vendor_offset_db}")
    require(five_ghz.expected_badge_rssi_dbm == -46, f"bad expected badge RSSI: {five_ghz.expected_badge_rssi_dbm}")
    require(five_ghz.calibrated_delta_db == 0, f"bad calibrated delta: {five_ghz.calibrated_delta_db}")
    two_ghz = next(match for match in matches if match.band == "2.4GHz")
    require(two_ghz.vendor_offset_db == -5, f"bad 2.4GHz offset: {two_ghz.vendor_offset_db}")
    require(two_ghz.expected_badge_rssi_dbm == -60, f"bad expected badge RSSI: {two_ghz.expected_badge_rssi_dbm}")
    require(two_ghz.calibrated_delta_db == -9, f"bad calibrated delta: {two_ghz.calibrated_delta_db}")


def test_template_honors_configurable_match_window() -> None:
    """Verify the timestamp match window defaults to one second and is configurable."""

    config = load_config(ROOT / "config" / "vocera-rf-validation.example.yaml")
    badge = parse_badge_input(
        FIXTURES / "badge_sys_single_roam.txt",
        test_run_id=TEST_RUN_ID,
        badge_mac="00:09:ef:54:5f:46",
    )

    ekahau_at_boundary = parse_ekahau_json(FIXTURES / "ekahau_export_sample.json", test_run_id=TEST_RUN_ID, config=config)
    ekahau_at_boundary.survey_points[0].measured_at += timedelta(seconds=1)
    boundary_rows = build_manual_entry_template(badge, ekahau_at_boundary, config=config)
    require(len(boundary_rows) == 2, f"expected 1s boundary match rows, got {len(boundary_rows)}")
    require(boundary_rows[0].match_quality == "exact_1s", f"bad boundary quality: {boundary_rows[0].match_quality}")

    ekahau_outside_default = parse_ekahau_json(FIXTURES / "ekahau_export_sample.json", test_run_id=TEST_RUN_ID, config=config)
    ekahau_outside_default.survey_points[0].measured_at += timedelta(milliseconds=1001)
    outside_rows = build_manual_entry_template(badge, ekahau_outside_default, config=config)
    require(len(outside_rows) == 0, f"expected no rows outside default 1s window, got {len(outside_rows)}")

    widened_config = dict(config)
    widened_config["default_match_window_seconds"] = 5
    widened_rows = build_manual_entry_template(badge, ekahau_outside_default, config=widened_config)
    require(len(widened_rows) == 2, f"expected widened-window rows to admit ~1.001s delta, got {len(widened_rows)}")
    require(
        widened_rows[0].match_quality in {"exact_1s", "close_5s"},
        f"unexpected widened-window quality label: {widened_rows[0].match_quality}",
    )

    stale_rows = list(boundary_rows)
    for row in stale_rows:
        row.time_delta_seconds = 1.001
        row.ekahau_rssi_dbm = -40
    matches = correlate_template_rows(stale_rows, config=config)
    require(len(matches) == 0, f"expected old >1s template rows to be ignored under default config, got {len(matches)}")


def test_executor_builds_run_scoped_config_with_match_window() -> None:
    """The executor must turn a run's match window into effective run config.

    This is the wiring that makes per-run tolerance real: correlate already
    honors default_match_window_seconds (see test above), but only if execution
    actually passes the run's window into the config it runs with.
    """

    from tools.vocera_rf_validation.run_executor import build_effective_run_config

    base = load_config(ROOT / "config" / "vocera-rf-validation.example.yaml")
    base_window = base.get("default_match_window_seconds")

    # An explicit run window overrides the base config value.
    effective = build_effective_run_config(base, {"default_match_window_seconds": 5})
    require(effective["default_match_window_seconds"] == 5, f"run window not applied: {effective.get('default_match_window_seconds')}")

    # The base config must not be mutated.
    require(base.get("default_match_window_seconds") == base_window, "base config was mutated by build_effective_run_config")

    # Missing, sub-1s, or non-numeric windows keep the base config value.
    require(
        build_effective_run_config(base, {})["default_match_window_seconds"] == base_window,
        "missing run window should keep base config value",
    )
    require(
        build_effective_run_config(base, {"default_match_window_seconds": "0"})["default_match_window_seconds"] == base_window,
        "sub-1s run window should keep base config value",
    )
    require(
        build_effective_run_config(base, {"default_match_window_seconds": "not-a-number"})["default_match_window_seconds"] == base_window,
        "non-numeric run window should keep base config value",
    )


def test_tolerance_sweep_summary() -> None:
    """Verify the non-destructive tolerance sweep counts matches/near-edge/ambiguous."""

    from tools.study_web.time_alignment import normalize_windows, summarize_tolerance_sweep

    # e1 is the nearest badge reading for two points (ambiguous once both are in
    # window); e2 and e3 are nearest to one point each.
    points = [
        {"delta_seconds": 0.5, "event_id": "e1"},
        {"delta_seconds": -0.9, "event_id": "e1"},
        {"delta_seconds": 1.8, "event_id": "e2"},
        {"delta_seconds": 4.0, "event_id": "e3"},
    ]
    result = summarize_tolerance_sweep(points, [1, 2, 5])
    by_window = {row["window_seconds"]: row for row in result["windows"]}

    # window 1: 0.5 and 0.9 match; both nearest to e1 -> ambiguous; 0.9 > 0.8 -> near edge.
    require(by_window[1]["matched_points"] == 2, f"w1 matched: {by_window[1]['matched_points']}")
    require(by_window[1]["ambiguous_points"] == 2, f"w1 ambiguous: {by_window[1]['ambiguous_points']}")
    require(by_window[1]["near_edge_points"] == 1, f"w1 near edge: {by_window[1]['near_edge_points']}")

    # window 2: adds 1.8 (e2); e1 still shared -> 2 ambiguous; near edge (>1.6) is just 1.8.
    require(by_window[2]["matched_points"] == 3, f"w2 matched: {by_window[2]['matched_points']}")
    require(by_window[2]["ambiguous_points"] == 2, f"w2 ambiguous: {by_window[2]['ambiguous_points']}")
    require(by_window[2]["near_edge_points"] == 1, f"w2 near edge: {by_window[2]['near_edge_points']}")

    # window 5: all four match.
    require(by_window[5]["matched_points"] == 4, f"w5 matched: {by_window[5]['matched_points']}")

    require(result["survey_point_count_with_same_date_badge"] == 4, "sweep point count mismatch")
    require(result["signed_deltas"] == [0.5, -0.9, 1.8, 4.0], "signed deltas should be preserved in order")

    require(normalize_windows([2, 1, 1, 5], current=3) == [1, 2, 3, 5], "window normalize/dedup/current failed")
    require(normalize_windows([0, -1, "x"]) == [], "invalid/sub-1 windows should be dropped")

    # Empty input must not raise and yields zeroed windows.
    empty = summarize_tolerance_sweep([], [1, 2])
    require(empty["windows"][0]["matched_points"] == 0, "empty sweep should report zero matches")
    require(empty["abs_delta_median_seconds"] is None, "empty sweep median should be null")


def test_overlap_window() -> None:
    """Verify the timeline overlap-window trimming helper."""

    from tools.study_web.time_alignment import overlap_window

    require(overlap_window(0, 100, 50, 200, margin_seconds=5) == (45, 105), "overlap with margin mismatch")
    require(overlap_window(0, 100, 100, 200) == (100, 100), "touching ranges should overlap at a point")
    require(overlap_window(0, 50, 60, 100) is None, "disjoint ranges should yield None without margin")
    # A gap smaller than the margin is still matchable, so the margin must be
    # applied before rejecting the ranges as disjoint.
    require(overlap_window(0, 50, 60, 100, margin_seconds=10) == (50, 60), "margin should rescue a near-disjoint gap")
    require(overlap_window(0, 50, 80, 100, margin_seconds=10) is None, "gap wider than 2x margin stays disjoint")
    require(overlap_window(None, 100, 50, 200) is None, "missing bound should yield None")
def test_run_comparison_summary() -> None:
    """Verify per-run completion percent and the plain-English interpretation."""

    from tools.study_web.run_comparison import build_run_comparison, completion_percent

    require(completion_percent(3, 1) == 75.0, "completion percent should be completed/(completed+pending)")
    require(completion_percent(0, 0) is None, "no candidates should yield null completion")

    rows = [
        {"test_run_id": "r1", "match_window_seconds_used": 1, "default_match_window_seconds": 1,
         "candidate_match_count": 7, "pending_candidate_match_count": 2, "completed_match_count": 6, "outlier_count": 0},
        {"test_run_id": "r2", "match_window_seconds_used": 5, "default_match_window_seconds": 1,
         "candidate_match_count": 26, "pending_candidate_match_count": 10, "completed_match_count": 6, "outlier_count": 4},
    ]
    result = build_run_comparison(rows)
    by_id = {row["test_run_id"]: row for row in result["rows"]}
    require(by_id["r1"]["completion_percent"] == 75.0, f"r1 completion: {by_id['r1']['completion_percent']}")
    require(by_id["r2"]["completion_percent"] == 37.5, f"r2 completion: {by_id['r2']['completion_percent']}")
    interpretation = result["interpretation"]
    require("increased" in interpretation, f"expected a trend direction: {interpretation}")
    require("7" in interpretation and "26" in interpretation, f"expected candidate counts: {interpretation}")

    require("Only one run" in build_run_comparison([rows[0]])["interpretation"], "single-run wording missing")
    require("No runs" in build_run_comparison([])["interpretation"], "empty wording missing")

    same_window = build_run_comparison([
        {"test_run_id": "a", "match_window_seconds_used": 1, "candidate_match_count": 5, "pending_candidate_match_count": 0, "completed_match_count": 5, "outlier_count": 0},
        {"test_run_id": "b", "match_window_seconds_used": 1, "candidate_match_count": 8, "pending_candidate_match_count": 0, "completed_match_count": 8, "outlier_count": 1},
    ])
    require("same match window" in same_window["interpretation"], f"same-window wording: {same_window['interpretation']}")


def test_template_requires_same_measurement_date() -> None:
    """Verify badge and Ekahau points must share a local measurement date."""

    config = load_config(ROOT / "config" / "vocera-rf-validation.example.yaml")
    widened_config = dict(config)
    widened_config["default_match_window_seconds"] = 90_000
    badge = parse_badge_input(
        FIXTURES / "badge_sys_single_roam.txt",
        test_run_id=TEST_RUN_ID,
        badge_mac="00:09:ef:54:5f:46",
    )
    ekahau = parse_ekahau_json(FIXTURES / "ekahau_export_sample.json", test_run_id=TEST_RUN_ID, config=config)
    for point in ekahau.survey_points:
        point.measured_at += timedelta(days=1)

    rows = build_manual_entry_template(badge, ekahau, config=widened_config)
    require(len(rows) == 0, f"expected no cross-date template rows even with a wide window, got {len(rows)}")
    alignment = summarize_match_alignment(badge, ekahau, config=widened_config)
    require(alignment["matched_survey_point_count"] == 0, f"cross-date points should not align: {alignment}")
    require(alignment["unmatched_reason"] == "no_same_date_overlap", f"bad unmatched reason: {alignment}")
    require(alignment["same_measurement_dates"] == [], f"cross-date inputs should not share dates: {alignment}")
    require(alignment["nearest_delta_any_date_seconds"] is not None, f"missing any-date nearest delta: {alignment}")

    same_day_ekahau = parse_ekahau_json(FIXTURES / "ekahau_export_sample.json", test_run_id=TEST_RUN_ID, config=config)
    stale_rows = build_manual_entry_template(badge, same_day_ekahau, config=config)
    for row in stale_rows:
        row.survey_time += timedelta(days=1)
        row.time_delta_seconds = 0
        row.ekahau_rssi_dbm = -40
    matches = correlate_template_rows(stale_rows, config=widened_config)
    require(len(matches) == 0, f"expected stale cross-date CSV rows to be ignored, got {len(matches)}")


def test_offset_policy_and_outlier_labels() -> None:
    """Verify vendor offsets and low-sample outlier labels."""

    config = load_config(ROOT / "config" / "vocera-rf-validation.example.yaml")
    require(resolve_vendor_offset(config, None, "5GHz") == -8, "5GHz offset should be -8 without badge model")
    require(resolve_vendor_offset(config, None, "2.4GHz") == -5, "2.4GHz offset should be -5 without badge model")
    require(resolve_vendor_offset(config, "B7000", "6GHz") is None, "6GHz offset should remain undefined")

    badge = parse_badge_input(
        FIXTURES / "badge_sys_single_roam.txt",
        test_run_id=TEST_RUN_ID,
        badge_mac="00:09:ef:54:5f:46",
    )
    ekahau = parse_ekahau_json(FIXTURES / "ekahau_export_sample.json", test_run_id=TEST_RUN_ID, config=config)
    rows = build_manual_entry_template(badge, ekahau, config=config)
    rows[0].ekahau_rssi_dbm = -38
    rows[1].ekahau_rssi_dbm = -55

    annotated = annotate_outliers(correlate_template_rows(rows, config=config), minimum_samples=30)
    require(all(row["outlier_status"] == "insufficient_samples" for row in annotated), "small samples should be low confidence")


def test_sql_export_inserts_all_referenced_source_files() -> None:
    """Verify SQL export includes every source file referenced by parsed rows."""

    config = load_config(ROOT / "config" / "vocera-rf-validation.example.yaml")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        archive_path = tmp_path / "badge_multi.zip"
        content = (FIXTURES / "badge_sys_single_roam.txt").read_bytes()
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("diag-a/sys", content)
            archive.writestr("diag-b/sys", content)

        badge = parse_badge_input(archive_path, test_run_id=TEST_RUN_ID, badge_mac="00:09:ef:54:5f:46")
        ekahau = parse_ekahau_json(FIXTURES / "ekahau_export_sample.json", test_run_id=TEST_RUN_ID, config=config)
        badge_json = tmp_path / "badge.json"
        ekahau_json = tmp_path / "ekahau.json"
        badge_json.write_text(json.dumps(badge.to_dict()), encoding="utf-8")
        ekahau_json.write_text(json.dumps(ekahau.to_dict()), encoding="utf-8")

        sql = emit_sql(badge_json=badge_json, ekahau_json=ekahau_json)

    source_ids = {event.source_file_id for event in badge.events}
    require(len(source_ids) == 2, f"expected two archive source ids, got {source_ids}")
    for source_id in source_ids:
        require(
            f"insert into validation_source_files (source_file_id" in sql and source_id in sql,
            f"missing validation_source_files insert for {source_id}",
        )
    require(
        "create temporary table _vocera_rf_validation_preserved_manual_observations" in sql,
        "SQL import should preserve completed manual observations before run reload",
    )
    require(
        "insert into manual_ekahau_observations" in sql
        and "from _vocera_rf_validation_preserved_manual_observations" in sql,
        "SQL import should restore preserved manual observations after survey reload",
    )
    require(
        "set candidate_match_id = c.id" in sql,
        "SQL import should attach completed match rows to freshly parsed candidate rows",
    )
    require(
        "set manual_entry_status = 'complete'" in sql
        and "m.manual_entry_status in ('complete', 'missing_vendor_offset')" in sql,
        "SQL import should only mark candidates complete when a completed match row already exists",
    )
    require(
        "from manual_ekahau_observations o" not in sql
        or "where lower(o.bssid) = lower(c.bssid)" not in sql,
        "SQL import should not auto-materialize matches from preserved manual observations",
    )
    require(
        "survey_point_id is not distinct from c.survey_point_id" not in sql,
        "SQL import should not require regenerated survey_point_id values to match",
    )
    require(
        "where o.test_run_id = c.test_run_id" not in sql,
        "SQL import should not require existing manual observations to come from the same parser run id",
    )


def test_rf_study_workflow_sql_contract() -> None:
    """Verify the RF validation app exposes the modern project/study/run workflow."""

    schema_sql = (ROOT / "sql" / "vocera_rf_validation_schema.sql").read_text(encoding="utf-8")
    views_sql = (ROOT / "sql" / "vocera_rf_validation_views.sql").read_text(encoding="utf-8")

    require(
        "create table if not exists vocera_rf_validation_input_files" in schema_sql
        and "create table if not exists vocera_rf_validation_run_input_files" in schema_sql,
        "RF validation schema should define input-file inventory and run selection tables",
    )
    require(
        "create table if not exists vocera_projects" in schema_sql
        and "create table if not exists vocera_studies" in schema_sql
        and "study_scope text not null default 'vocera_badge'" in schema_sql
        and "vocera_studies_study_scope_check" in schema_sql
        and "add column if not exists study_id text references vocera_studies(study_id)" in schema_sql,
        "RF validation schema should expose first-class projects, scoped studies, and run study attachment",
    )
    require(
        "project_rf_validation_default" in schema_sql
        and "study_rf_validation_vocera_badge_default" in schema_sql
        and "set study_scope = 'ipad'" in schema_sql
        and "update validation_test_runs" in schema_sql
        and "where study_id is null" in schema_sql,
        "RF validation schema should backfill existing runs into scoped default RF studies",
    )
    require(
        "add column if not exists run_name text" in schema_sql
        and "add column if not exists run_status text not null default 'draft'" in schema_sql
        and "add column if not exists deleted_at timestamptz" in schema_sql,
        "RF validation runs should expose CRUD lifecycle metadata",
    )
    require(
        "create or replace function vocera_rf_validation_delete_run" in schema_sql
        and "delete from vocera_rf_validation_run_input_files" in schema_sql,
        "RF validation schema should define a run-scoped delete function",
    )
    require(
        "where c.test_run_id = v_candidate.test_run_id\n    and lower(c.bssid)" in schema_sql
        and "where m.test_run_id = v_candidate.test_run_id\n    and lower(m.bssid)" in schema_sql
        and "where o.test_run_id = v_candidate.test_run_id\n    and lower(o.bssid)" in schema_sql
        and "where c.test_run_id = p_test_run_id\n    and lower(c.bssid)" in schema_sql
        and "where m.test_run_id = p_test_run_id\n    and lower(m.bssid)" in schema_sql
        and "where o.test_run_id = p_test_run_id\n    and lower(o.bssid)" in schema_sql,
        "RF validation manual-entry writes should be scoped by run before matching BSSID/time",
    )
    require(
        "when coalesce(p_test_run_id, '') like 'ipad_%' then 'ipad'" in schema_sql,
        "RF validation study scope should keep iPad rows separate from badge rows",
    )
    require(
        "create or replace view v_vocera_rf_validation_input_files" in views_sql
        and "create or replace view v_vocera_rf_validation_runs" in views_sql
        and "create or replace view v_vocera_rf_validation_run_files" in views_sql,
        "RF validation views should expose run CRUD read models",
    )
    require(
        "create or replace view v_vocera_projects" in views_sql
        and "create or replace view v_vocera_studies" in views_sql
        and "create or replace view v_vocera_rf_project_canonical_completed_matches" in views_sql
        and "create or replace view v_vocera_rf_project_duplicate_datapoints" in views_sql
        and "v_vocera_rf_project_completed_matches" in views_sql,
        "RF validation views should expose project/study summaries, canonical results, and duplicate datapoint warnings",
    )
    require(
        "(sum(active_run_count) filter (where deleted_at is null))::integer as active_run_count" in views_sql
        and "where canonical_rank = 1" in views_sql,
        "RF validation project views should exclude deleted studies from active metrics and rank canonical results",
    )
    require(
        (ROOT / "scripts" / "manage_vocera_rf_validation_study.sh").is_file(),
        "RF validation should include an operator study-management script",
    )
    require(
        (ROOT / "scripts" / "audit_vocera_rf_validation_run.py").is_file(),
        "RF validation should include a pipeline audit script for web run artifacts and DB rows",
    )
    require(
        (ROOT / "scripts" / "smoke_vocera_rf_project_study_workflow.py").is_file(),
        "RF validation should include a live smoke script for project/study SQL and API checks",
    )
    require(
        (ROOT / "tools" / "vocera_rf_validation" / "study_web.py").is_file(),
        "RF validation should include a collector-hosted study web app",
    )
    require(
        (ROOT / "tools" / "vocera_rf_validation" / "run_executor.py").is_file(),
        "RF validation should include a run executor module for selected source files",
    )
    run_executor_text = (ROOT / "tools" / "vocera_rf_validation" / "run_executor.py").read_text(encoding="utf-8")
    require(
        "def execute_selected_run" in run_executor_text
        and "parse-badge" in run_executor_text
        and "parse-ipad-client-detail" in run_executor_text
        and "parse-ekahau-json" in run_executor_text
        and "emit-sql" in run_executor_text,
        "RF validation run executor should wire selected files through the parser/import pipeline",
    )
    fastapi_text = (ROOT / "tools" / "study_web" / "main.py").read_text(encoding="utf-8")
    require(
        "execute_selected_run" in fastapi_text
        and "run_status = 'running'" in fastapi_text
        and "run_status = 'complete'" in fastapi_text
        and "run_status = 'failed'" in fastapi_text
        and "Run execution is intentionally deferred" not in fastapi_text,
        "FastAPI study web app should execute selected RF runs instead of returning a placeholder",
    )
    require(
        "@app.post(\"/api/rf/input-files/upload\")" in fastapi_text
        and "UploadFile" in fastapi_text
        and "upload_dir_for" in fastapi_text
        and "incoming" in fastapi_text,
        "FastAPI study web app should upload RF source files into scoped incoming folders",
    )
    require(
        "@app.post(\"/api/rf/run-bundles/upload\")" in fastapi_text
        and "safe_extract_zip" in fastapi_text
        and "discover_bundle_sources" in fastapi_text
        and "survey/" in fastapi_text
        and "badge-log/" in fastapi_text,
        "FastAPI study web app should adapt Windows RF validation bundles into run file selections",
    )
    require(
        "@app.get(\"/api/projects\")" in fastapi_text
        and "@app.post(\"/api/projects\")" in fastapi_text
        and "@app.get(\"/api/projects/{project_id}/studies\")" in fastapi_text
        and "@app.post(\"/api/studies/{study_id}/runs\")" in fastapi_text
        and "@app.get(\"/api/projects/{project_id}/rf-results/raw\")" in fastapi_text
        and "@app.get(\"/api/projects/{project_id}/duplicates\")" in fastapi_text,
        "FastAPI study web app should expose project/study hierarchy endpoints",
    )
    require(
        "expected_scope = active_scope()" in fastapi_text
        and "Cannot delete a project while it has active studies." in fastapi_text
        and "Cannot change study_scope after runs have been attached." in fastapi_text
        and "v_vocera_rf_project_canonical_completed_matches" in fastapi_text,
        "FastAPI study web app should enforce scoped study workflow rules and default project results to canonical rows",
    )
    require(
        "@app.get(\"/api/grafana/status\")" in fastapi_text
        and "@app.api_route(\"/grafana/{grafana_path:path}\"" in fastapi_text
        and "STUDY_WEB_GRAFANA_UPSTREAM" in fastapi_text
        and "STUDY_WEB_GRAFANA_PROXY_ENABLED" in fastapi_text
        and "X-Forwarded-Prefix" in fastapi_text,
        "FastAPI study web app should expose Grafana status diagnostics and a same-origin /grafana proxy",
    )
    grafana_panel_text = (ROOT / "web" / "study-ui" / "src" / "components" / "GrafanaPanel.tsx").read_text(encoding="utf-8")
    require(
        "Grafana panel not configured" in grafana_panel_text
        and "Open panel URL" in grafana_panel_text
        and "var-${key}" in grafana_panel_text,
        "Study UI Grafana panels should render missing-config diagnostics and pass dashboard variables",
    )
    grafana_diagnostics_text = (ROOT / "web" / "study-ui" / "src" / "components" / "GrafanaDiagnostics.tsx").read_text(encoding="utf-8")
    require(
        "getGrafanaStatus" in grafana_diagnostics_text
        and "Grafana Embed Diagnostics" in grafana_diagnostics_text
        and "upstream_health" in grafana_diagnostics_text,
        "Study UI should include a Grafana embed diagnostics panel",
    )
    requirements_text = (ROOT / "tools" / "study_web" / "requirements.txt").read_text(encoding="utf-8")
    require(
        "python-multipart" in requirements_text,
        "Study web requirements should include python-multipart for browser file uploads",
    )
    require(
        (ROOT / "scripts" / "install_vocera_rf_validation_study_web.sh").is_file(),
        "RF validation should include a systemd installer for the study web app",
    )
    require(
        (ROOT / "systemd" / "vocera-rf-validation-study-web.service").is_file(),
        "RF validation should include a study web app systemd unit",
    )
    study_web_text = (ROOT / "tools" / "vocera_rf_validation" / "study_web.py").read_text(encoding="utf-8")
    require(
        "project_canonical_view" in study_web_text,
        "RF validation backend status should report canonical project result view readiness",
    )
    require(
        "project_duplicate_view" in study_web_text
        and "run_delete_function" in study_web_text
        and "archive_table" not in study_web_text.split("def backend_status_sql", 1)[1].split("def current_study_sql", 1)[0]
        and "combine_function" not in study_web_text.split("def backend_status_sql", 1)[1].split("def current_study_sql", 1)[0],
        "RF validation backend status should treat archive/combine objects as optional compatibility, not core readiness",
    )
    require(
        "class Handler" in study_web_text and "ThreadingHTTPServer" in study_web_text,
        "RF validation study web app should expose a small HTTP form UI",
    )
    makefile_text = (ROOT / "Makefile").read_text(encoding="utf-8")
    require(
        "vocera-rf-validation-study-web:" in makefile_text
        and "vocera-rf-validation-study-web-install:" in makefile_text,
        "Makefile should expose run/install targets for the RF validation study web app",
    )
    for dashboard_path in (
        ROOT
        / "grafana"
        / "dashboards-dev"
        / "Platform - Wireless RF"
        / "vocera-badge-ekahau-rf-validation__vocera_badge_ekahau_rf_validation.json",
        ROOT
        / "grafana"
        / "dashboards-prod"
        / "Platform - Wireless RF"
        / "vocera-badge-ekahau-rf-validation__vocera_badge_ekahau_rf_validation.json",
    ):
        require(
            not dashboard_path.exists(),
            "RF validation Grafana dashboard should be retired from the final two-dashboard inventory",
        )
    rf_page_text = (ROOT / "web" / "study-ui" / "src" / "pages" / "RfValidationStudy.tsx").read_text(encoding="utf-8")
    client_text = (ROOT / "web" / "study-ui" / "src" / "api" / "client.ts").read_text(encoding="utf-8")
    manual_entry_text = (ROOT / "web" / "study-ui" / "src" / "components" / "ManualEntryWorkbench.tsx").read_text(encoding="utf-8")
    duplicate_text = (ROOT / "web" / "study-ui" / "src" / "components" / "DuplicateWarningsList.tsx").read_text(encoding="utf-8")
    results_summary_text = (ROOT / "web" / "study-ui" / "src" / "components" / "ProjectResultsSummary.tsx").read_text(encoding="utf-8")
    require(
        "LegacyArchiveTools" not in rf_page_text
        and "createCombinedStudy" not in rf_page_text
        and "clearArchiveSelection" not in rf_page_text
        and "makeArchiveCurrent" not in rf_page_text
        and "archive-selection" not in rf_page_text
        and "Run workflow" not in rf_page_text
        and "current-study" not in client_text
        and "/api/rf/archive" not in client_text
        and "manual archive selection" not in duplicate_text,
        "React RF page should expose Projects -> Studies -> Runs -> Results without legacy archive/combine controls",
    )
    workflow_markers = [
        'title="Project and study"',
        "ProjectManager",
        "StudyManager",
        "Selected project",
        'title="Runs and source files"',
        "RF Validation Runs",
        'title="Complete candidate matches"',
        "ManualEntryWorkbench",
        'title="Project analysis"',
        "ProjectResultsSummary",
        "DuplicateWarningsList",
        'title="Cal Delta statistics"',
        "StudyStatisticsWorkbench",
        'title="Diagnostics"',
        "Run history",
        "GrafanaDiagnostics",
    ]
    rf_render_text = rf_page_text.split("return (", 1)[1]
    marker_positions = [rf_render_text.find(marker) for marker in workflow_markers]
    require(
        all(position >= 0 for position in marker_positions)
        and marker_positions == sorted(marker_positions)
        and "Windows field collection script" in rf_page_text
        and "manualEntryAvailable" in rf_page_text
        and "manualEntries.pending.length > 0 || manualEntries.completed.length > 0" in rf_page_text
        and "manual study combining" not in results_summary_text,
        "RF page should read top-to-bottom as project/study selection, runs, manual entry, results, statistics, diagnostics",
    )
    require(
        "Save &amp; Next" in manual_entry_text
        and "onSaveDraftAndNext" in manual_entry_text
        and "nextPendingManualEntryRow" in rf_page_text
        and "Cal Delta severity:" in manual_entry_text
        and "Normal &lt;= 5 dB" in manual_entry_text
        and "Review &gt; 5 dB" in manual_entry_text
        and "High concern &gt; 10 dB" in manual_entry_text
        and "Timestamp-only match" in manual_entry_text,
        "Manual entry UI should support Save & Next, Cal Delta severity badges, and timestamp-only match labeling",
    )


def test_cli_archives_parser_inputs_outputs_and_log() -> None:
    """Verify parser CLI archiving captures inputs, outputs, and logs."""

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        json_out = tmp_path / "badge_scan_events.json"
        archive_dir = tmp_path / "archives"

        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            rc = rf_cli.main(
                [
                    "--config",
                    str(ROOT / "config" / "vocera-rf-validation.example.yaml"),
                    "--archive-dir",
                    str(archive_dir),
                    "parse-badge",
                    "--test-run-id",
                    TEST_RUN_ID,
                    "--input",
                    str(FIXTURES / "badge_sys_single_roam.txt"),
                    "--badge-mac",
                    "00:09:ef:54:5f:46",
                    "--json-out",
                    str(json_out),
                ]
            )

        archives = sorted(archive_dir.glob("*.zip"))
        require(rc == 0, f"CLI parse-badge failed with rc={rc}")
        require(len(archives) == 1, f"expected one run archive, got {archives}")
        with zipfile.ZipFile(archives[0]) as archive:
            names = archive.namelist()
        require("manifest.json" in names, "archive missing manifest")
        require("logs/run.log" in names, "archive missing run log")
        require(any(name.endswith("/badge_sys_single_roam.txt") for name in names), f"archive missing badge input: {names}")
        require(any(name.endswith("/badge_scan_events.json") for name in names), f"archive missing badge JSON output: {names}")


def main() -> int:
    """Run the standalone Vocera RF validation tests."""

    test_normalization()
    test_manual_sample_statistics()
    test_badge_parser()
    test_ekahau_timestamp_parser()
    test_ipad_client_detail_parser_uses_only_client_scan_reports()
    test_ekahau_esx_survey_archive_parser()
    test_ekahau_streaming_esx_without_central_directory()
    test_template_and_correlation()
    test_template_honors_configurable_match_window()
    test_executor_builds_run_scoped_config_with_match_window()
    test_tolerance_sweep_summary()
    test_overlap_window()
    test_run_comparison_summary()
    test_template_requires_same_measurement_date()
    test_offset_policy_and_outlier_labels()
    test_sql_export_inserts_all_referenced_source_files()
    test_rf_study_workflow_sql_contract()
    test_cli_archives_parser_inputs_outputs_and_log()
    print("OK: vocera RF validation tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
