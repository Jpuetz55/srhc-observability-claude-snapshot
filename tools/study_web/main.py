"""FastAPI backend for study-based RF validation and media QoE workflows."""

from __future__ import annotations

import os
import csv
import hashlib
import ipaddress
import json
import re
import subprocess
import sys
import tarfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal, Mapping

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from vocera_rf_validation.run_executor import execute_selected_run
from .sample_statistics import DEFAULT_Z_THRESHOLD, summarize_samples
from .time_alignment import DEFAULT_SWEEP_WINDOWS, overlap_window, summarize_tolerance_sweep
from .time_alignment import DEFAULT_SWEEP_WINDOWS, summarize_tolerance_sweep
from .run_comparison import build_run_comparison
from vocera_rf_validation.study_web import (  # legacy SQL helpers reused intentionally
    DEFAULT_SCOPE,
    DEFAULT_USER,
    Db,
    archives_sql,
    backend_status_sql,
    current_study_sql,
    live_runs_sql,
    safe_one,
    safe_rows,
    selection_sql,
    sql_literal,
)

ROOT = Path(__file__).resolve().parents[2]

# vocera_media_qoe ships its tools as top-level modules (the parser runs as
# ``python3 -m vocera_media_qoe_batch`` with PYTHONPATH set to that directory).
# Put that directory on sys.path so the WLC session-EPC ingest path can reuse
# the exact same validated, unit-tested file primitives the collector relies on.
_VOCERA_MEDIA_QOE_DIR = ROOT / "tools" / "vocera_media_qoe"
if str(_VOCERA_MEDIA_QOE_DIR) not in sys.path:
    sys.path.insert(0, str(_VOCERA_MEDIA_QOE_DIR))
import vocera_wlc_session_ingest as wlc_ingest  # noqa: E402
import vocera_wlc_cli as wlc_cli  # noqa: E402
import vocera_media_qoe as media_analyzer  # noqa: E402

STATIC_DIR = Path(os.environ.get("STUDY_WEB_STATIC_DIR", str(ROOT / "tools" / "study_web" / "static")))
SOURCE_TYPES = ("badge_log", "ekahau_json", "manual_csv", "ipad_client_detail", "other")
RUN_STATUSES = ("draft", "running", "complete", "failed", "deleted")
UPLOAD_SUBDIRS = {
    "badge_log": Path("incoming") / "badge-logs",
    "ekahau_json": Path("incoming") / "ekahau",
    "manual_csv": Path("incoming") / "manual",
    "ipad_client_detail": Path("incoming") / "client-detail",
    "other": Path("incoming") / "other",
}
BUNDLE_SUBDIR = Path("incoming") / "bundles"
SCAN_SUBDIRS_BY_SCOPE = {
    "vocera_badge": (Path("incoming") / "badge-logs", Path("incoming") / "ekahau"),
    "ipad": (Path("incoming") / "client-detail", Path("incoming") / "ekahau"),
}
SCAN_TYPES_BY_SCOPE = {
    "vocera_badge": ("badge_log", "ekahau_json"),
    "ipad": ("ipad_client_detail", "ekahau_json"),
}
GRAFANA_PANEL_ENV = {
    "apVoiceLatency": ("AP_VOICE_LATENCY", "ap_voice_latency"),
    "txRetry": ("TX_RETRY", "tx_retry"),
    "mediaQoe": ("MEDIA_QOE", "media_qoe"),
    "mediaQoeSummary": ("MEDIA_QOE_SUMMARY", "media_qoe_summary"),
    "mediaQoeCaptureInventory": ("MEDIA_QOE_CAPTURE_INVENTORY", "media_qoe_capture_inventory"),
    "mediaQoeRtpTrouble": ("MEDIA_QOE_RTP_TROUBLE", "media_qoe_rtp_trouble"),
    "mediaQoeDscp": ("MEDIA_QOE_DSCP", "media_qoe_dscp"),
    "mediaQoeDirection": ("MEDIA_QOE_DIRECTION", "media_qoe_direction"),
    "mediaQoeClassification": ("MEDIA_QOE_CLASSIFICATION", "media_qoe_classification"),
    "mediaQoeRejectionReasons": ("MEDIA_QOE_REJECTION_REASONS", "media_qoe_rejection_reasons"),
}
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
MEDIA_REVIEW_STATUSES = ("unreviewed", "accepted", "excluded", "needs_review")
MEDIA_STREAM_CLASSIFICATIONS = (
    "vocera_rtp",
    "server_to_badge",
    "badge_to_server",
    "badge_to_badge",
    "non_rtp_udp",
    "unknown_udp",
    "control",
    "noise",
    "exclude",
)
MEDIA_QOE_DEFAULT_ALLOWED_EXTENSIONS = (".pcap", ".pcapng", ".cap")
MEDIA_QOE_PARSE_OUTPUT_ROOT = Path(os.environ.get("STUDY_WEB_MEDIA_QOE_WORK_DIR", "/tmp/vocera-media-qoe-web"))
MEDIA_WLC_SESSION_STATES = ("prepared_not_started", "running", "stopped", "exported", "imported", "aborted")
MEDIA_WLC_EVENT_KINDS = ("broadcast_started", "heard", "missed", "partial", "choppy", "alert_only", "session_end", "note")

SourceType = Literal["badge_log", "ekahau_json", "manual_csv", "ipad_client_detail", "other"]
RunStatus = Literal["draft", "running", "complete", "failed", "deleted"]
ProjectType = Literal["rf_validation", "media_qoe", "mixed"]
StudyType = Literal["rf_validation", "media_qoe"]
StudyScope = Literal["vocera_badge", "ipad", "media_qoe"]
StudyStatus = Literal["active", "complete", "archived", "deleted"]


class ProjectCreate(BaseModel):
    project_id: str | None = None
    project_name: str = Field(min_length=1)
    project_type: ProjectType = "rf_validation"
    description: str | None = None
    site: str | None = None


class ProjectPatch(BaseModel):
    project_name: str | None = None
    project_type: ProjectType | None = None
    description: str | None = None
    site: str | None = None


class StudyCreate(BaseModel):
    study_id: str | None = None
    study_type: StudyType = "rf_validation"
    study_scope: StudyScope | None = None
    study_name: str = Field(min_length=1)
    description: str | None = None
    study_status: StudyStatus = "active"


class StudyPatch(BaseModel):
    project_id: str | None = None
    study_type: StudyType | None = None
    study_scope: StudyScope | None = None
    study_name: str | None = None
    description: str | None = None
    study_status: StudyStatus | None = None


class CurrentStudyUpdate(BaseModel):
    study_name: str | None = None
    notes: str | None = None


class CurrentStudyAction(BaseModel):
    action_key: Literal["archive_current", "archive_and_clear", "clear_current"]


class ArchiveUpdate(BaseModel):
    archive_id: str = Field(min_length=1)
    archive_label: str | None = None
    notes: str | None = None
    combine_selected: bool = False


class ArchiveDelete(BaseModel):
    archive_id: str = Field(min_length=1)


class ArchiveMakeCurrent(BaseModel):
    archive_id: str = Field(min_length=1)
    notes: str | None = None


class CombinedStudyCreate(BaseModel):
    archive_label: str | None = None
    notes: str | None = None


class InputFileScan(BaseModel):
    roots: list[str] | None = None
    source_types: list[SourceType] | None = None
    include_other: bool = False
    max_files: int = Field(default=500, ge=1, le=5000)


class InputFileRegister(BaseModel):
    file_path: str = Field(min_length=1)
    source_type: SourceType = "other"
    input_file_id: str | None = None
    display_name: str | None = None
    notes: str | None = None


class InputFilePatch(BaseModel):
    source_type: SourceType | None = None
    file_path: str | None = None
    display_name: str | None = None
    is_available: bool | None = None
    notes: str | None = None


class RunCreate(BaseModel):
    test_run_id: str | None = None
    study_id: str | None = None
    run_name: str | None = None
    site: str | None = None
    building: str | None = None
    floor: str | None = None
    area: str | None = None
    ssid: str | None = None
    badge_mac: str | None = None
    badge_model: str | None = None
    ekahau_device: str | None = None
    ekahau_project: str | None = None
    timezone: str | None = None
    badge_time_offset_seconds: int | None = None
    ekahau_time_offset_seconds: int | None = None
    default_match_window_seconds: int | None = Field(default=None, ge=1)
    vendor_offset_source: str | None = None
    notes: str | None = None
    run_status: RunStatus | None = None


class RunPatch(BaseModel):
    study_id: str | None = None
    run_name: str | None = None
    run_status: RunStatus | None = None
    site: str | None = None
    building: str | None = None
    floor: str | None = None
    area: str | None = None
    ssid: str | None = None
    badge_mac: str | None = None
    badge_model: str | None = None
    ekahau_device: str | None = None
    ekahau_project: str | None = None
    timezone: str | None = None
    badge_time_offset_seconds: int | None = None
    ekahau_time_offset_seconds: int | None = None
    default_match_window_seconds: int | None = Field(default=None, ge=1)
    vendor_offset_source: str | None = None
    notes: str | None = None


class RunFileSelection(BaseModel):
    input_file_id: str = Field(min_length=1)
    source_role: SourceType | None = None


class ManualEntrySubmit(BaseModel):
    ekahau_rssi_dbm: str = Field(min_length=1)
    ekahau_snr_db: str | None = None
    notes: str | None = None


class ManualSampleCreate(BaseModel):
    label: str | None = None
    ekahau_rssi_dbm: float | None = None
    ekahau_snr_db: float | None = None
    notes: str | None = None


class ManualSampleBulkCreate(BaseModel):
    samples: list[ManualSampleCreate] = Field(default_factory=list)


class ManualSamplePatch(BaseModel):
    label: str | None = None
    ekahau_rssi_dbm: float | None = None
    ekahau_snr_db: float | None = None
    notes: str | None = None


class MediaStreamReviewPatch(BaseModel):
    accepted: bool | None = None
    stream_classification: str | None = None
    review_status: str | None = None
    review_notes: str | None = None


class MediaCaptureRegister(BaseModel):
    source_path: str = Field(min_length=1)
    source_name: str | None = None
    capture_point: str | None = None
    site: str | None = None
    notes: str | None = None


class MediaCaptureExecute(BaseModel):
    reparse: bool = False
    timeout_seconds: int | None = Field(default=None, ge=1, le=3600)


class MediaWlcSessionIngestScan(BaseModel):
    session_id: str | None = None


class MediaDnacCaptureQuery(BaseModel):
    client_mac: str | None = None
    ap_mac: str | None = None
    capture_type: str | None = None
    lookback_minutes: int | None = Field(default=None, ge=0)
    limit: int | None = Field(default=None, ge=1, le=100)
    offset: int = Field(default=1, ge=1)


class MediaDnacCaptureDownload(BaseModel):
    client_mac: str | None = None
    ap_mac: str | None = None
    capture_id: str | None = None
    file_name: str | None = None
    capture_type: str | None = None
    lookback_minutes: int | None = Field(default=None, ge=0)
    limit: int | None = Field(default=None, ge=1, le=100)
    offset: int = Field(default=1, ge=1)
    register: bool = True


class MediaWlcCaptureSessionCreate(BaseModel):
    session_id: str | None = None
    site: str | None = None
    wlc_name: str | None = None
    capture_name: str | None = None
    wlc_interface: str | None = None
    capture_filter_mode: str | None = None
    capture_mode: Literal["long_reproduction", "short_validation"] = "long_reproduction"
    short_validation_duration_seconds: int | None = Field(default=None, ge=30, le=3600)
    collector_host: str | None = None
    collector_scp_username: str | None = None
    collector_scp_port: int | None = Field(default=None, ge=1, le=65535)
    collector_scp_path: str | None = None
    ring_file_count: int | None = Field(default=None, ge=2, le=5)
    ring_file_size_mb: int | None = Field(default=None, ge=1, le=500)
    continuous_export_enabled: bool | None = None
    sender_name: str | None = None
    sender_model: str | None = None
    sender_mac: str | None = None
    sender_ip: str | None = None
    receiver_name: str | None = None
    receiver_model: str | None = None
    receiver_mac: str | None = None
    receiver_ip: str | None = None
    expected_dscp: int | None = Field(default=None, ge=0, le=63)
    vocera_vlan: int | None = Field(default=None, ge=1, le=4094)
    vocera_multicast_pool: str | None = None
    vocera_first_usable: str | None = None
    vocera_last_usable: str | None = None
    notes: str | None = None

    class Config:
        extra = "forbid"


class MediaWlcCaptureSessionPatch(BaseModel):
    session_state: Literal["prepared_not_started", "running", "stopped", "exported", "imported", "aborted"] | None = None
    capture_started_at: datetime | None = None
    capture_stopped_at: datetime | None = None
    # LEGACY: active-group resolution is attempt-scoped. The API rejects any non-null
    # value below with HTTP 422 (see media_wlc_update_session). These fields are kept
    # only so deprecated clients receive a clear error instead of a silently dropped
    # field; resolve the active group via the attempt active-group endpoint instead.
    resolved_group_ip: str | None = None
    resolved_group_vlan: int | None = Field(default=None, ge=1, le=4094)
    resolved_mgid: int | None = Field(default=None, ge=0)
    resolved_at: datetime | None = None
    vlan_selection_source: Literal["default", "operator_override", "observed_confirmation"] | None = None
    vlan_override_reason: str | None = None
    notes: str | None = None

    class Config:
        extra = "forbid"


class MediaWlcSessionEventCreate(BaseModel):
    attempt_id: str | None = None
    event_kind: Literal["broadcast_started", "heard", "missed", "partial", "choppy", "alert_only", "session_end", "note"]
    event_time: datetime | None = None
    browser_event_time: datetime | None = None
    operator_name: str | None = None
    audio_result: Literal["heard", "missed", "partial", "choppy", "unknown", "not_tested"] | None = None
    alert_received: bool | None = None
    audio_received: bool | None = None
    notes: str | None = None

    class Config:
        extra = "forbid"


class MediaWlcAttemptStart(BaseModel):
    attempt_id: str | None = None
    started_at: datetime | None = None
    browser_event_time: datetime | None = None
    operator_name: str | None = None
    notes: str | None = None

    class Config:
        extra = "forbid"


class MediaWlcAttemptOutcome(BaseModel):
    audio_result: Literal["heard", "missed", "partial", "choppy", "alert_only"]
    alert_received: bool | None = None
    audio_received: bool | None = None
    ended_at: datetime | None = None
    browser_event_time: datetime | None = None
    operator_name: str | None = None
    notes: str | None = None

    class Config:
        extra = "forbid"


class MediaWlcAttemptActiveGroup(BaseModel):
    group_ip: str
    group_vlan: int = Field(ge=1, le=4094)
    mgid: int | None = Field(default=None, ge=0)
    selection_source: Literal["operator_override", "observed_confirmation"] = "observed_confirmation"
    vlan_override_reason: str | None = None
    group_summary_raw: str | None = None
    selected_row: str | None = None
    selected_at: datetime | None = None
    operator_name: str | None = None

    class Config:
        extra = "forbid"


def scope() -> str:
    return os.environ.get("VOCERA_RF_STUDY_WEB_SCOPE", DEFAULT_SCOPE)


def user() -> str:
    return os.environ.get("VOCERA_RF_STUDY_WEB_USER", DEFAULT_USER)


def psql_db() -> Db:
    return Db()


class MediaDb:
    def __init__(self) -> None:
        credential_name = "VOCERA_MEDIA_QOE_POSTGRES_" + "PASSWORD"
        credential = os.environ.get(credential_name, "")
        self.url = os.environ.get(
            "VOCERA_MEDIA_QOE_DATABASE_URL",
            f"postgresql://vocera_media_qoe:{credential or 'unused'}@127.0.0.1:15434/vocera_media_qoe",
        )
        self.psql_bin = os.environ.get(
            "VOCERA_MEDIA_QOE_PSQL_BIN",
            str(ROOT / "scripts" / "vocera_media_qoe_psql_in_container.sh"),
        )

    def rows(self, sql: str) -> list[dict[str, str]]:
        completed = subprocess.run(
            [
                self.psql_bin,
                self.url,
                "-X",
                "-q",
                "--csv",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                sql,
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(detail or f"media psql exited {completed.returncode}")
        output = completed.stdout.strip()
        if not output:
            return []
        return list(csv.DictReader(StringIO(output)))

    def one(self, sql: str) -> dict[str, str]:
        rows = self.rows(sql)
        return rows[0] if rows else {}


def media_db() -> MediaDb:
    return MediaDb()


def query_one(sql: str) -> dict[str, str]:
    try:
        return psql_db().one(sql)
    except Exception as exc:  # noqa: BLE001 - return operational DB errors to the web UI
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def query_rows(sql: str) -> list[dict[str, str]]:
    try:
        return psql_db().rows(sql)
    except Exception as exc:  # noqa: BLE001 - return operational DB errors to the web UI
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def media_query_one(sql: str) -> dict[str, str]:
    try:
        return media_db().one(sql)
    except Exception as exc:  # noqa: BLE001 - return operational DB errors to the web UI
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def media_query_rows(sql: str) -> list[dict[str, str]]:
    try:
        return media_db().rows(sql)
    except Exception as exc:  # noqa: BLE001 - return operational DB errors to the web UI
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def model_fields_set(model: BaseModel) -> set[str]:
    return set(getattr(model, "model_fields_set", getattr(model, "__fields_set__", set())))


def model_data(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def sql_text(value: Any) -> str:
    if value is None:
        return "null"
    text = str(value)
    if text == "":
        return "null"
    return "'" + text.replace("'", "''") + "'"


def sql_int(value: int | None) -> str:
    return "null" if value is None else str(int(value))


def sql_number(value: float | int | None) -> str:
    if value is None:
        return "null"
    return repr(float(value))


def sql_bool(value: bool | None) -> str:
    if value is None:
        return "null"
    return "true" if value else "false"


def sql_timestamp(value: datetime | None) -> str:
    return "null" if value is None else sql_text(value.isoformat())


def active_scope() -> str:
    return scope().strip() or DEFAULT_SCOPE


def validate_run_id_scope(test_run_id: str) -> None:
    current_scope = active_scope()
    if current_scope == "ipad" and not test_run_id.startswith("ipad_"):
        raise HTTPException(status_code=400, detail="iPad study runs must use a test_run_id starting with 'ipad_'.")
    if current_scope == "vocera_badge" and test_run_id.startswith("ipad_"):
        raise HTTPException(status_code=400, detail="Vocera badge study runs cannot use a test_run_id starting with 'ipad_'.")


def new_test_run_id() -> str:
    current_scope = active_scope()
    prefix = "ipad_run" if current_scope == "ipad" else "rf_run"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    return f"{prefix}_{stamp}_{uuid.uuid4().hex[:8]}"


def new_entity_id(prefix: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{stamp}_{uuid.uuid4().hex[:8]}"


def default_rf_study_id() -> str:
    return "study_rf_validation_ipad_default" if active_scope() == "ipad" else "study_rf_validation_vocera_badge_default"


def default_media_project_id() -> str:
    return "project_media_qoe_default"


def default_media_study_id() -> str:
    return "study_media_qoe_default"


def project_row(project_id: str, *, include_deleted: bool = False) -> dict[str, str]:
    deleted_filter = "" if include_deleted else " and deleted_at is null"
    row = query_one(
        "select * from v_vocera_projects "
        f"where project_id = {sql_text(project_id)}{deleted_filter};"
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"No project found for {project_id}.")
    return row


def study_row(study_id: str, *, include_deleted: bool = False) -> dict[str, str]:
    deleted_filter = "" if include_deleted else " and deleted_at is null and project_id in (select project_id from vocera_projects where deleted_at is null)"
    row = query_one(
        "select * from v_vocera_studies "
        f"where study_id = {sql_text(study_id)}{deleted_filter};"
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"No study found for {study_id}.")
    return row


def media_project_row(project_id: str, *, include_deleted: bool = False) -> dict[str, str]:
    deleted_filter = "" if include_deleted else " and deleted_at is null"
    row = media_query_one(
        "select * from v_vocera_media_qoe_projects "
        f"where project_id = {sql_text(project_id)}{deleted_filter};"
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"No media QoE project found for {project_id}.")
    return row


def media_study_row(study_id: str, *, include_deleted: bool = False) -> dict[str, str]:
    deleted_filter = "" if include_deleted else " and deleted_at is null"
    row = media_query_one(
        "select * from v_vocera_media_qoe_studies "
        f"where study_id = {sql_text(study_id)}{deleted_filter};"
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"No media QoE study found for {study_id}.")
    return row


def validate_media_project_id(project_id: str) -> dict[str, str]:
    project = media_project_row(project_id)
    if project.get("project_type") not in {"media_qoe", "mixed"}:
        raise HTTPException(status_code=400, detail="Project is not a media_qoe or mixed project.")
    return project


def validate_media_study_id(study_id: str) -> dict[str, str]:
    study = media_study_row(study_id)
    if study.get("study_scope") != "media_qoe":
        raise HTTPException(status_code=400, detail="Media QoE studies must use media_qoe scope.")
    return study


def scalar_int(sql: str, column: str = "value") -> int:
    row = query_one(sql)
    if not row:
        return 0
    raw = row.get(column)
    if raw is None:
        return 0
    return int(raw)


def study_run_count(study_id: str) -> int:
    return scalar_int(
        "select count(*) as value "
        "from validation_test_runs "
        f"where study_id = {sql_text(study_id)};"
    )


def project_study_count(project_id: str, *, active_only: bool = False) -> int:
    active_filter = " and deleted_at is null" if active_only else ""
    return scalar_int(
        "select count(*) as value "
        "from vocera_studies "
        f"where project_id = {sql_text(project_id)}{active_filter};"
    )


def manual_samples_table_ready() -> bool:
    row = query_one("select to_regclass('public.vocera_rf_manual_samples') as present;")
    return bool(row.get("present"))


def require_samples_table() -> None:
    if not manual_samples_table_ready():
        raise HTTPException(
            status_code=400,
            detail="Manual sample table missing. Run `make vocera-rf-validation-install-db` to apply the schema update.",
        )


def sample_row(sample_id: str, *, include_deleted: bool = False) -> dict[str, str]:
    deleted_filter = "" if include_deleted else " and deleted_at is null"
    row = query_one(
        "select * from v_vocera_rf_manual_samples "
        f"where sample_id = {sql_text(sample_id)}{deleted_filter};"
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"No manual sample found for {sample_id}.")
    return row


def list_study_sample_rows(study_id: str) -> list[dict[str, str]]:
    return query_rows(
        "select "
        "match_id as sample_id, "
        "study_id, "
        "run_name, "
        "test_run_id, "
        "match_id, "
        "candidate_match_id, "
        "survey_time, "
        "bssid, "
        "ap_name, "
        "channel, "
        "badge_rssi_dbm, "
        "badge_snr_db, "
        "calibrated_delta_db, "
        "concat_ws(' / ', nullif(run_name, ''), nullif(ap_name, ''), nullif(bssid, '')) as label, "
        "ekahau_rssi_dbm, "
        "ekahau_snr_db, "
        "concat_ws(' | ', "
        "  'run=' || test_run_id, "
        "  'match=' || match_id, "
        "  case when badge_rssi_dbm is not null then 'badge_rssi=' || badge_rssi_dbm::text else null end, "
        "  case when badge_snr_db is not null then 'badge_snr=' || badge_snr_db::text else null end, "
        "  case when calibrated_delta_db is not null then 'cal_delta=' || calibrated_delta_db::text else null end"
        ") as notes, "
        "entered_at as created_at, "
        "match_created_at as updated_at "
        "from v_vocera_rf_project_canonical_completed_matches "
        f"where study_id = {sql_text(study_id)} "
        "and calibrated_delta_db is not null "
        "order by survey_time nulls last, lower(bssid), match_id;"
    )


def study_samples_response(study_id: str, *, z_threshold: float = DEFAULT_Z_THRESHOLD) -> dict[str, Any]:
    rows = list_study_sample_rows(study_id)
    summary = summarize_samples(rows, z_threshold=z_threshold)
    return {"ok": True, "study_id": study_id, **summary}


def has_sample_measurement(value: Any) -> bool:
    return value is not None and str(value) != ""


def insert_study_sample(study_id: str, payload: ManualSampleCreate) -> str:
    if payload.ekahau_rssi_dbm is None and payload.ekahau_snr_db is None:
        raise HTTPException(status_code=400, detail="Enter an Ekahau RSSI or SNR value for the sample.")
    sample_id = new_entity_id("sample")
    query_one(
        "insert into vocera_rf_manual_samples "
        "(sample_id, study_id, label, ekahau_rssi_dbm, ekahau_snr_db, notes, updated_at) "
        f"values ({sql_text(sample_id)}, {sql_text(study_id)}, {sql_text(payload.label)}, "
        f"{sql_number(payload.ekahau_rssi_dbm)}, {sql_number(payload.ekahau_snr_db)}, {sql_text(payload.notes)}, now()) "
        "returning sample_id;"
    )
    return sample_id


def default_study_scope_for_type(study_type: str) -> str:
    return "media_qoe" if study_type == "media_qoe" else active_scope()


def validate_study_type_scope(study_type: str, study_scope: str) -> None:
    if study_type == "rf_validation" and study_scope not in {"vocera_badge", "ipad"}:
        raise HTTPException(status_code=400, detail="RF validation studies must use a vocera_badge or ipad study_scope.")
    if study_type == "media_qoe" and study_scope != "media_qoe":
        raise HTTPException(status_code=400, detail="Media QoE studies must use the media_qoe study_scope.")


def validate_project_study_type(project: dict[str, str], study_type: str) -> None:
    project_type = project.get("project_type")
    if project_type not in {"mixed", study_type}:
        raise HTTPException(status_code=400, detail=f"{study_type} studies cannot be added to a {project_type} project.")


def validate_rf_study_id(study_id: str | None) -> str:
    resolved = study_id or default_rf_study_id()
    row = query_one(
        "select s.study_id, s.study_type, s.study_scope "
        "from vocera_studies s "
        "join vocera_projects p on p.project_id = s.project_id "
        f"where s.study_id = {sql_text(resolved)} "
        "and s.deleted_at is null "
        "and p.deleted_at is null;"
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"No active study found for {resolved}.")
    if row.get("study_type") != "rf_validation":
        raise HTTPException(status_code=400, detail="RF validation runs can only be attached to rf_validation studies.")
    expected_scope = active_scope()
    if row.get("study_scope") != expected_scope:
        raise HTTPException(status_code=400, detail=f"{expected_scope} runs can only be attached to {expected_scope} studies.")
    return row["study_id"]


def input_roots() -> list[Path]:
    configured = os.environ.get("VOCERA_RF_VALIDATION_INPUT_FILE_ROOTS", "").strip()
    if configured:
        raw_roots = [item.strip() for item in configured.replace(",", os.pathsep).split(os.pathsep) if item.strip()]
        return [(Path(item) if Path(item).is_absolute() else ROOT / item).resolve(strict=False) for item in raw_roots]

    current_scope = active_scope()
    if current_scope == "ipad":
        return [(ROOT / "data" / "ipad-rf-validation").resolve(strict=False)]

    return [(ROOT / "data" / "vocera-rf-validation").resolve(strict=False)]


def upload_root() -> Path:
    roots = input_roots()
    if not roots:
        raise HTTPException(status_code=500, detail="No RF validation input file root is configured.")
    return roots[0]


def input_scan_roots() -> list[Path]:
    configured = os.environ.get("VOCERA_RF_VALIDATION_INPUT_SCAN_ROOTS", "").strip()
    if configured:
        raw_roots = [item.strip() for item in configured.replace(",", os.pathsep).split(os.pathsep) if item.strip()]
        return [(Path(item) if Path(item).is_absolute() else ROOT / item).resolve(strict=False) for item in raw_roots]

    base = upload_root()
    subdirs = SCAN_SUBDIRS_BY_SCOPE.get(active_scope(), SCAN_SUBDIRS_BY_SCOPE["vocera_badge"])
    return [(base / subdir).resolve(strict=False) for subdir in subdirs]


def default_scan_source_types() -> tuple[str, ...]:
    return SCAN_TYPES_BY_SCOPE.get(active_scope(), SCAN_TYPES_BY_SCOPE["vocera_badge"])


def upload_dir_for(source_type: SourceType) -> Path:
    subdir = UPLOAD_SUBDIRS.get(source_type, UPLOAD_SUBDIRS["other"])
    target = (upload_root() / subdir).resolve(strict=False)
    try:
        target.relative_to(upload_root().resolve(strict=False))
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="Resolved upload directory is outside the RF validation input root.") from exc
    target.mkdir(parents=True, exist_ok=True)
    return target


def safe_upload_filename(filename: str | None) -> str:
    raw_name = Path(filename or "uploaded_file").name
    stem = Path(raw_name).stem or "uploaded_file"
    suffix = Path(raw_name).suffix[:32]
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-") or "uploaded_file"
    safe_suffix = re.sub(r"[^A-Za-z0-9.]", "", suffix)
    return f"{safe_stem}{safe_suffix}"


def split_upload_name(filename: str) -> tuple[str, str]:
    """Return a stem and full suffix while preserving compound extensions.

    pathlib.Path.stem only removes the last suffix, so a duplicate upload like
    badge.tar.gz would otherwise become badge.tar_<stamp>.gz. The badge
    parser recognizes .tar.gz by filename today, and preserving the compound
    suffix also keeps files readable to humans.
    """

    path = Path(filename)
    suffix = "".join(path.suffixes)
    if suffix and filename.endswith(suffix):
        stem = filename[: -len(suffix)]
    else:
        stem = path.stem or filename
    return stem or "uploaded_file", suffix


def unique_upload_path(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate

    stem, suffix = split_upload_name(filename)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    return directory / f"{stem}_{stamp}{suffix}"


def bad_upload_dir() -> Path:
    target = (upload_root() / "bad-uploads").resolve(strict=False)
    try:
        target.relative_to(upload_root().resolve(strict=False))
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="Resolved bad-upload directory is outside the RF validation input root.") from exc
    target.mkdir(parents=True, exist_ok=True)
    return target


def quarantine_upload(path: Path, reason: str) -> Path:
    target = unique_upload_path(bad_upload_dir(), path.name)
    if path.exists():
        path.replace(target)
    return target


def badge_archive_validation_error(path: Path) -> str | None:
    name = path.name.lower()
    if not path.is_file():
        return "Badge file does not exist on disk."
    try:
        if name.endswith((".tar.gz", ".tgz", ".tar")) or tarfile.is_tarfile(path):
            with tarfile.open(path, "r:*") as archive:
                # Force tar/gzip to read the full archive index so truncated
                # uploads fail here instead of during execution.
                archive.getmembers()
            return None
        if name.endswith(".zip"):
            if not zipfile.is_zipfile(path):
                return "Badge ZIP archive is corrupt or incomplete."
            with zipfile.ZipFile(path) as archive:
                bad_member = archive.testzip()
            if bad_member:
                return f"Badge ZIP archive has a corrupt member: {bad_member}."
            return None
    except (EOFError, OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
        return f"Badge archive is corrupt or incomplete: {exc}"
    return None


def validate_uploaded_input_file(path: Path, source_type: SourceType) -> None:
    if source_type == "badge_log":
        error = badge_archive_validation_error(path)
        if error:
            quarantine_path = quarantine_upload(path, error)
            raise HTTPException(
                status_code=400,
                detail=f"{error} Re-upload the full badge diagnostic bundle. Quarantined as {stored_file_path(quarantine_path)}",
            )


def bundle_upload_dir() -> Path:
    target = (upload_root() / BUNDLE_SUBDIR).resolve(strict=False)
    try:
        target.relative_to(upload_root().resolve(strict=False))
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="Resolved bundle directory is outside the RF validation input root.") from exc
    target.mkdir(parents=True, exist_ok=True)
    return target


def safe_extract_zip(zip_path: Path, target_dir: Path) -> list[Path]:
    """Extract a user-uploaded ZIP without allowing path traversal."""
    extracted: list[Path] = []
    target_dir.mkdir(parents=True, exist_ok=True)
    target_root = target_dir.resolve(strict=False)
    try:
        with zipfile.ZipFile(zip_path) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                member_name = member.filename.replace("\\", "/")
                parts = [part for part in member_name.split("/") if part not in {"", ".", ".."}]
                if not parts:
                    continue
                destination = (target_root / Path(*parts)).resolve(strict=False)
                try:
                    destination.relative_to(target_root)
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail=f"ZIP member escapes extraction directory: {member.filename}") from exc
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, destination.open("wb") as dest:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        dest.write(chunk)
                extracted.append(destination)
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="Uploaded bundle is not a valid ZIP file.") from exc
    return extracted


def newest_file(paths: list[Path]) -> Path | None:
    existing = [path for path in paths if path.is_file()]
    if not existing:
        return None
    return sorted(existing, key=lambda item: (item.stat().st_mtime, str(item)), reverse=True)[0]


def find_dirs_by_name(root: Path, names: set[str]) -> list[Path]:
    matches: list[Path] = []
    if root.name.lower() in names:
        matches.append(root)
    for path in root.rglob("*"):
        if path.is_dir() and path.name.lower() in names:
            matches.append(path)
    return matches


def normalize_mac_text(value: str | None) -> str:
    return re.sub(r"[^0-9A-Fa-f]", "", value or "").lower()


def format_mac_from_compact(value: str) -> str:
    clean = normalize_mac_text(value)
    if len(clean) != 12:
        return ""
    return ":".join(clean[idx : idx + 2] for idx in range(0, 12, 2))


def infer_badge_mac_from_name(path: Path) -> str:
    match = re.search(r"(?<![0-9A-Fa-f])([0-9A-Fa-f]{12})(?![0-9A-Fa-f])", path.name)
    return format_mac_from_compact(match.group(1)) if match else ""


def discover_bundle_sources(extract_dir: Path, badge_mac: str | None = None) -> tuple[Path | None, Path | None, str]:
    """Find the badge diagnostic archive and Ekahau project inside a field bundle."""
    badge_roots = find_dirs_by_name(extract_dir, {"badge-log", "badge-logs", "badgelog", "badge_logs", "badge"}) or [extract_dir]
    survey_roots = find_dirs_by_name(extract_dir, {"survey", "surveys", "ekahau", "ekahau-survey", "ekahau_survey"}) or [extract_dir]

    badge_mac_filter = normalize_mac_text(badge_mac)
    badge_candidates: list[Path] = []
    for root in badge_roots:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            lower = path.name.lower()
            is_badge_candidate = lower.endswith((".tar.gz", ".tgz", ".zip", ".txt", ".log")) or "sys" in lower or "udd" in lower
            if not is_badge_candidate:
                continue
            if badge_mac_filter and badge_mac_filter not in normalize_mac_text(path.name):
                continue
            badge_candidates.append(path)

    # If a MAC-filtered search found nothing, fall back to the newest plausible badge file.
    if not badge_candidates and badge_mac_filter:
        for root in badge_roots:
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                lower = path.name.lower()
                if lower.endswith((".tar.gz", ".tgz", ".zip", ".txt", ".log")) or "sys" in lower or "udd" in lower:
                    badge_candidates.append(path)

    survey_candidates: list[Path] = []
    for root in survey_roots:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            lower = path.name.lower()
            if lower.endswith((".esx", ".json", ".zip")):
                survey_candidates.append(path)

    badge_file = newest_file(badge_candidates)
    survey_file = newest_file(survey_candidates)
    resolved_badge_mac = badge_mac or (infer_badge_mac_from_name(badge_file) if badge_file else "")
    return badge_file, survey_file, resolved_badge_mac


def upsert_input_file_record(record: dict[str, Any]) -> dict[str, str]:
    result = query_one(upsert_input_file_sql(record))
    input_file_id = result.get("input_file_id") or record["input_file_id"]
    return input_file_row(input_file_id)


def duplicate_source_sort_key(record: dict[str, Any]) -> tuple[int, int, str]:
    """Prefer clean canonical source filenames over timestamped duplicate uploads."""
    file_path = str(record.get("file_path") or "")
    file_name = str(record.get("file_name") or "")
    duplicate_stamp = 1 if re.search(r"_[0-9]{8}_[0-9]{6}_[0-9]{6}", file_path) else 0
    return duplicate_stamp, len(file_name), file_path


def dedupe_input_file_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one visible scan result per source_type + SHA256.

    The physical incoming folder can contain many duplicate uploads of the same
    Ekahau ESX or badge tarball. The inventory should not re-enable every
    duplicate row just because a scan sees it again.
    """
    winners: dict[tuple[str, str], dict[str, Any]] = {}
    passthrough: list[dict[str, Any]] = []
    for record in records:
        source_sha256 = str(record.get("source_sha256") or "")
        source_type = str(record.get("source_type") or "")
        if not source_sha256:
            passthrough.append(record)
            continue
        key = (source_type, source_sha256)
        existing = winners.get(key)
        if existing is None or duplicate_source_sort_key(record) < duplicate_source_sort_key(existing):
            winners[key] = record
    return sorted([*winners.values(), *passthrough], key=lambda row: (str(row.get("source_type") or ""), str(row.get("display_name") or ""), str(row.get("file_path") or "")))


def existing_visible_duplicate(record: dict[str, Any]) -> dict[str, str] | None:
    """Return the canonical visible input row for a duplicate upload, if any."""
    source_sha256 = record.get("source_sha256")
    if not source_sha256:
        return None
    rows = query_rows(
        "select * from v_vocera_rf_validation_input_files "
        f"where study_scope = {sql_text(active_scope())} "
        f"and source_type = {sql_text(record.get('source_type'))} "
        f"and source_sha256 = {sql_text(source_sha256)} "
        "and is_available = true "
        "order by "
        "case when file_path !~ '_[0-9]{8}_[0-9]{6}_[0-9]{6}' then 0 else 1 end, "
        "length(file_name), discovered_at asc "
        "limit 1;"
    )
    return rows[0] if rows else None


def hide_duplicate_input_file(record: dict[str, Any], canonical_input_file_id: str) -> None:
    """Persist a duplicate row as unavailable so future API lists stay clean."""
    duplicate_record = {**record, "is_available": False, "notes": f"Hidden duplicate source file; canonical input_file_id={canonical_input_file_id}."}
    upsert_input_file_sql_text = upsert_input_file_sql(duplicate_record).replace(
        "is_available = excluded.is_available,",
        "is_available = false,"
    )
    query_one(upsert_input_file_sql_text)


def attach_input_file_to_run(test_run_id: str, input_file_id: str, source_role: str) -> None:
    query_one(
        "insert into vocera_rf_validation_run_input_files (test_run_id, input_file_id, source_role) "
        f"values ({sql_text(test_run_id)}, {sql_text(input_file_id)}, {sql_text(source_role)}) "
        "on conflict on constraint vocera_rf_validation_run_input_files_pkey "
        "do update set selected_at = now() "
        "returning test_run_id;"
    )


def create_run_record(payload: RunCreate) -> dict[str, str]:
    test_run_id = payload.test_run_id or new_test_run_id()
    validate_run_id_scope(test_run_id)
    study_id = validate_rf_study_id(payload.study_id)
    run_status = payload.run_status or "draft"
    if run_status == "deleted":
        raise HTTPException(status_code=400, detail="New runs cannot start in deleted status.")
    row = query_one(
        "insert into validation_test_runs ("
        "test_run_id, study_id, run_name, run_status, run_created_by, run_updated_at, site, building, floor, area, ssid, "
        "badge_mac, badge_model, ekahau_device, ekahau_project, timezone, badge_time_offset_seconds, "
        "ekahau_time_offset_seconds, default_match_window_seconds, vendor_offset_source, notes, run_notes"
        ") values ("
        f"{sql_text(test_run_id)}, {sql_text(study_id)}, {sql_text(payload.run_name)}, {sql_text(run_status)}, {sql_text(user())}, now(), "
        f"{sql_text(payload.site)}, {sql_text(payload.building)}, {sql_text(payload.floor)}, {sql_text(payload.area)}, {sql_text(payload.ssid)}, "
        f"{sql_text(payload.badge_mac)}, {sql_text(payload.badge_model)}, {sql_text(payload.ekahau_device)}, {sql_text(payload.ekahau_project)}, "
        f"coalesce({sql_text(payload.timezone)}, 'America/Chicago'), coalesce({sql_int(payload.badge_time_offset_seconds)}, 0), "
        f"coalesce({sql_int(payload.ekahau_time_offset_seconds)}, 0), coalesce({sql_int(payload.default_match_window_seconds)}, 1), "
        f"{sql_text(payload.vendor_offset_source)}, {sql_text(payload.notes)}, {sql_text(payload.notes)}"
        ") returning test_run_id;"
    )
    return run_row(row.get("test_run_id") or test_run_id)


def resolve_input_path(file_path: str) -> Path:
    raw = Path(file_path).expanduser()
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve(strict=False)
    for allowed_root in input_roots():
        try:
            resolved.relative_to(allowed_root)
            return resolved
        except ValueError:
            continue
    allowed = ", ".join(str(root) for root in input_roots())
    raise HTTPException(status_code=400, detail=f"Input file path must be under an allowed root: {allowed}")


def stored_file_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def infer_source_type(path: Path) -> SourceType:
    name = path.name.lower()
    full = str(path).lower()
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return "manual_csv"
    if suffix == ".esx":
        return "ekahau_json"
    if suffix == ".json":
        return "ekahau_json" if any(marker in full for marker in ("ekahau", "survey", "esx")) else "other"
    if suffix in {".txt", ".log"}:
        if any(marker in full for marker in ("ipad", "client_detail", "client-detail", "wlc")):
            return "ipad_client_detail"
        if any(marker in full for marker in ("badge", "sys", "diag", "diagnostic")):
            return "badge_log"
    return "other"


def input_file_id_for(file_path: str) -> str:
    digest = hashlib.sha256(f"{active_scope()}:{file_path}".encode("utf-8")).hexdigest()[:20]
    return f"rf_input_{digest}"


def input_file_record(
    file_path: str,
    *,
    source_type: SourceType | None = None,
    input_file_id: str | None = None,
    display_name: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    resolved = resolve_input_path(file_path)
    stored = stored_file_path(resolved)
    stat = resolved.stat() if resolved.is_file() else None
    inferred = source_type or infer_source_type(resolved)
    return {
        "input_file_id": input_file_id or input_file_id_for(stored),
        "study_scope": active_scope(),
        "source_type": inferred,
        "file_path": stored,
        "display_name": display_name,
        "file_name": resolved.name,
        "file_size_bytes": stat.st_size if stat else None,
        "file_mtime": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc) if stat else None,
        "source_sha256": sha256_file(resolved) if stat else None,
        "is_available": resolved.is_file(),
        "notes": notes,
    }


def upsert_input_file_sql(record: dict[str, Any]) -> str:
    return f"""
insert into vocera_rf_validation_input_files (
  input_file_id,
  study_scope,
  source_type,
  file_path,
  display_name,
  file_name,
  file_size_bytes,
  file_mtime,
  source_sha256,
  last_seen_at,
  is_available,
  notes
)
values (
  {sql_text(record["input_file_id"])},
  {sql_text(record["study_scope"])},
  {sql_text(record["source_type"])},
  {sql_text(record["file_path"])},
  {sql_text(record.get("display_name"))},
  {sql_text(record.get("file_name"))},
  {sql_int(record.get("file_size_bytes"))},
  {sql_timestamp(record.get("file_mtime"))},
  {sql_text(record.get("source_sha256"))},
  now(),
  {sql_bool(record.get("is_available"))},
  {sql_text(record.get("notes"))}
)
on conflict on constraint vocera_rf_validation_input_files_scope_path_key
do update set
  source_type = excluded.source_type,
  display_name = coalesce(excluded.display_name, vocera_rf_validation_input_files.display_name),
  file_name = excluded.file_name,
  file_size_bytes = excluded.file_size_bytes,
  file_mtime = excluded.file_mtime,
  source_sha256 = excluded.source_sha256,
  last_seen_at = now(),
  is_available = excluded.is_available,
  notes = coalesce(excluded.notes, vocera_rf_validation_input_files.notes)
returning input_file_id;
"""


def run_row(test_run_id: str, *, include_deleted: bool = True) -> dict[str, str]:
    deleted_filter = "" if include_deleted else " and deleted_at is null"
    row = query_one(
        "select * from v_vocera_rf_validation_runs "
        f"where test_run_id = {sql_text(test_run_id)} and study_scope = {sql_text(active_scope())}{deleted_filter};"
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"No RF validation run found for {test_run_id}.")
    return row


def input_file_row(input_file_id: str) -> dict[str, str]:
    row = query_one(
        "select * from v_vocera_rf_validation_input_files "
        f"where input_file_id = {sql_text(input_file_id)} and study_scope = {sql_text(active_scope())};"
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"No RF validation input file found for {input_file_id}.")
    return row


def backend_ready(backend: dict[str, str]) -> bool:
    return backend.get("backend_status") == "ready"


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def grafana_base_path() -> str:
    raw = os.environ.get("STUDY_WEB_GRAFANA_BASE_PATH", "/grafana").strip() or "/grafana"
    if not raw.startswith("/") and not re.match(r"^https?://", raw):
        raw = f"/{raw}"
    return raw.rstrip("/") or "/grafana"


def grafana_upstream() -> str:
    return os.environ.get("STUDY_WEB_GRAFANA_UPSTREAM", "http://127.0.0.1:3000").strip().rstrip("/")


def grafana_panel(prefix: str) -> dict[str, Any] | None:
    uid = os.environ.get(f"STUDY_WEB_GRAFANA_{prefix}_UID", "").strip()
    slug = os.environ.get(f"STUDY_WEB_GRAFANA_{prefix}_SLUG", "").strip()
    panel_id = os.environ.get(f"STUDY_WEB_GRAFANA_{prefix}_PANEL_ID", "").strip()
    if not (uid and slug and panel_id):
        return None
    try:
        parsed_panel_id = int(panel_id)
    except ValueError:
        return None
    return {"dashboardUid": uid, "slug": slug, "panelId": parsed_panel_id}


def grafana_panel_status(camel_name: str, prefix: str, status_name: str) -> dict[str, Any]:
    uid = os.environ.get(f"STUDY_WEB_GRAFANA_{prefix}_UID", "").strip()
    slug = os.environ.get(f"STUDY_WEB_GRAFANA_{prefix}_SLUG", "").strip()
    panel_id = os.environ.get(f"STUDY_WEB_GRAFANA_{prefix}_PANEL_ID", "").strip()
    missing = []
    if not uid:
        missing.append("dashboard_uid")
    if not slug:
        missing.append("dashboard_slug")
    if not panel_id:
        missing.append("panel_id")
    invalid: list[str] = []
    if panel_id:
        try:
            int(panel_id)
        except ValueError:
            invalid.append("panel_id")

    panel = grafana_panel(prefix)
    result: dict[str, Any] = {
        "name": status_name,
        "config_key": camel_name,
        "configured": panel is not None,
        "dashboard_uid": uid or None,
        "dashboard_slug": slug or None,
        "panel_id": panel_id or None,
    }
    if missing:
        result["missing"] = missing
    if invalid:
        result["invalid"] = invalid
    if panel:
        result["url"] = grafana_panel_url(panel)
    return result


def grafana_panel_url(
    panel: dict[str, Any],
    *,
    from_time: str = "now-6h",
    to_time: str = "now",
    variables: dict[str, str | None] | None = None,
) -> str:
    params = {
        "orgId": os.environ.get("STUDY_WEB_GRAFANA_ORG_ID", "1"),
        "panelId": str(panel["panelId"]),
        "from": from_time,
        "to": to_time,
        "theme": os.environ.get("STUDY_WEB_GRAFANA_THEME", "dark"),
    }
    for key, value in (variables or {}).items():
        if value:
            params[f"var-{key}"] = value
    return f"{grafana_base_path()}/d-solo/{panel['dashboardUid']}/{panel['slug']}?{urllib.parse.urlencode(params)}"


def grafana_config() -> dict[str, Any]:
    """Expose non-secret Grafana UI configuration."""

    panels = {camel_name: grafana_panel(prefix) for camel_name, (prefix, _status_name) in GRAFANA_PANEL_ENV.items()}
    return {
        "basePath": grafana_base_path(),
        "orgId": os.environ.get("STUDY_WEB_GRAFANA_ORG_ID", "1"),
        "theme": os.environ.get("STUDY_WEB_GRAFANA_THEME", "dark"),
        "proxyEnabled": env_bool("STUDY_WEB_GRAFANA_PROXY_ENABLED", True),
        "panels": panels,
    }


def app_config() -> dict[str, Any]:
    """Expose non-secret UI configuration."""

    return {
        "scope": scope(),
        "user": user(),
        "grafana": grafana_config(),
    }


app = FastAPI(title="Study Workflow Web API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.environ.get("STUDY_WEB_CORS_ORIGINS", "").split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/health")
def api_health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/config")
def get_config() -> dict[str, Any]:
    return app_config()


@app.get("/api/backend-status")
def get_backend_status() -> dict[str, Any]:
    backend, error = safe_one(psql_db(), backend_status_sql())
    return {"ok": error is None, "error": error, "backend": backend}


def grafana_upstream_health() -> dict[str, Any]:
    upstream = grafana_upstream()
    if not env_bool("STUDY_WEB_GRAFANA_PROXY_ENABLED", True):
        return {"status": "disabled", "detail": "Grafana proxy is disabled."}
    if not upstream:
        return {"status": "not_configured", "detail": "STUDY_WEB_GRAFANA_UPSTREAM is empty."}

    timeout = float(os.environ.get("STUDY_WEB_GRAFANA_HEALTH_TIMEOUT_SECONDS", "2"))
    target = f"{upstream}/api/health"
    try:
        request = urllib.request.Request(target, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(4096).decode("utf-8", errors="replace")
            return {
                "status": "ok" if 200 <= response.status < 400 else "error",
                "status_code": response.status,
                "url": target,
                "body": body,
            }
    except urllib.error.HTTPError as exc:
        body = exc.read(4096).decode("utf-8", errors="replace")
        return {"status": "error", "status_code": exc.code, "url": target, "body": body}
    except urllib.error.URLError as exc:
        return {"status": "error", "url": target, "detail": str(exc.reason)}
    except TimeoutError:
        return {"status": "error", "url": target, "detail": "Timed out connecting to Grafana upstream."}


@app.get("/api/grafana/status")
def get_grafana_status() -> dict[str, Any]:
    health = grafana_upstream_health()
    panel_statuses = {
        status_name: grafana_panel_status(camel_name, prefix, status_name)
        for camel_name, (prefix, status_name) in GRAFANA_PANEL_ENV.items()
    }
    return {
        "ok": health.get("status") in {"ok", "disabled"},
        "grafana": {
            "proxy_enabled": env_bool("STUDY_WEB_GRAFANA_PROXY_ENABLED", True),
            "base_path": grafana_base_path(),
            "upstream": grafana_upstream() or None,
            "proxy_strip_base_path": env_bool("STUDY_WEB_GRAFANA_PROXY_STRIP_BASE_PATH", False),
            "org_id": os.environ.get("STUDY_WEB_GRAFANA_ORG_ID", "1"),
            "theme": os.environ.get("STUDY_WEB_GRAFANA_THEME", "dark"),
            "upstream_health": health,
            "panels": panel_statuses,
        },
    }


@app.get("/api/projects")
def list_projects(include_deleted: bool = False) -> dict[str, Any]:
    filters = [] if include_deleted else ["deleted_at is null"]
    where = f"where {' and '.join(filters)} " if filters else ""
    rows = query_rows(
        "select * from v_vocera_projects "
        f"{where}"
        "order by deleted_at nulls first, project_name, project_id;"
    )
    return {"ok": True, "projects": rows}


@app.post("/api/projects")
def create_project(payload: ProjectCreate) -> dict[str, Any]:
    project_id = payload.project_id or new_entity_id("project")
    row = query_one(
        "insert into vocera_projects (project_id, project_name, project_type, description, site, updated_at) "
        f"values ({sql_text(project_id)}, {sql_text(payload.project_name)}, {sql_text(payload.project_type)}, "
        f"{sql_text(payload.description)}, {sql_text(payload.site)}, now()) "
        "returning project_id;"
    )
    return {"ok": True, "project": project_row(row.get("project_id") or project_id)}


@app.get("/api/projects/{project_id}")
def get_project(project_id: str, include_deleted: bool = False) -> dict[str, Any]:
    project = project_row(project_id, include_deleted=include_deleted)
    studies = query_rows(
        "select * from v_vocera_studies "
        f"where project_id = {sql_text(project_id)} "
        f"{'' if include_deleted else 'and deleted_at is null '} "
        "order by deleted_at nulls first, study_name, study_id;"
    )
    return {"ok": True, "project": project, "studies": studies}


@app.patch("/api/projects/{project_id}")
def update_project(project_id: str, payload: ProjectPatch) -> dict[str, Any]:
    project = project_row(project_id)
    data = model_data(payload)
    fields = model_fields_set(payload)
    assignments: list[str] = []
    if "project_name" in fields:
        if not data.get("project_name"):
            raise HTTPException(status_code=400, detail="project_name cannot be empty.")
        assignments.append(f"project_name = {sql_text(data.get('project_name'))}")
    if "project_type" in fields:
        project_type = data.get("project_type")
        if project_type is None:
            raise HTTPException(status_code=400, detail="project_type cannot be null.")
        if project_type != project.get("project_type") and project_study_count(project_id) > 0 and project_type != "mixed":
            raise HTTPException(status_code=400, detail="Projects with studies can only change project_type to mixed.")
        assignments.append(f"project_type = {sql_text(project_type)}")
    if "description" in fields:
        assignments.append(f"description = {sql_text(data.get('description'))}")
    if "site" in fields:
        assignments.append(f"site = {sql_text(data.get('site'))}")
    if assignments:
        assignments.append("updated_at = now()")
        query_one(
            "update vocera_projects "
            f"set {', '.join(assignments)} "
            f"where project_id = {sql_text(project_id)} "
            "returning project_id;"
        )
    return {"ok": True, "project": project_row(project_id)}


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str) -> dict[str, Any]:
    project_row(project_id)
    active_studies = project_study_count(project_id, active_only=True)
    if active_studies:
        raise HTTPException(status_code=400, detail="Cannot delete a project while it has active studies.")
    row = query_one(
        "update vocera_projects "
        "set deleted_at = coalesce(deleted_at, now()), updated_at = now() "
        f"where project_id = {sql_text(project_id)} "
        "returning project_id;"
    )
    return {"ok": bool(row), "project": project_row(project_id, include_deleted=True)}


@app.get("/api/projects/{project_id}/studies")
def list_project_studies(project_id: str, include_deleted: bool = False) -> dict[str, Any]:
    project_row(project_id, include_deleted=include_deleted)
    rows = query_rows(
        "select * from v_vocera_studies "
        f"where project_id = {sql_text(project_id)} "
        f"{'' if include_deleted else 'and deleted_at is null '} "
        "order by deleted_at nulls first, study_name, study_id;"
    )
    return {"ok": True, "studies": rows}


@app.post("/api/projects/{project_id}/studies")
def create_project_study(project_id: str, payload: StudyCreate) -> dict[str, Any]:
    project = project_row(project_id)
    study_scope = payload.study_scope or default_study_scope_for_type(payload.study_type)
    validate_project_study_type(project, payload.study_type)
    validate_study_type_scope(payload.study_type, study_scope)
    study_id = payload.study_id or new_entity_id("study")
    row = query_one(
        "insert into vocera_studies (study_id, project_id, study_type, study_scope, study_name, description, study_status, updated_at) "
        f"values ({sql_text(study_id)}, {sql_text(project_id)}, {sql_text(payload.study_type)}, {sql_text(study_scope)}, "
        f"{sql_text(payload.study_name)}, {sql_text(payload.description)}, {sql_text(payload.study_status)}, now()) "
        "returning study_id;"
    )
    return {"ok": True, "study": study_row(row.get("study_id") or study_id)}


@app.get("/api/studies/{study_id}")
def get_study(study_id: str, include_deleted: bool = False) -> dict[str, Any]:
    study = study_row(study_id, include_deleted=include_deleted)
    runs = query_rows(
        "select * from v_vocera_rf_validation_runs "
        f"where study_id = {sql_text(study_id)} "
        f"{'' if include_deleted else 'and deleted_at is null '} "
        "order by created_at desc, test_run_id desc;"
    )
    return {"ok": True, "study": study, "runs": runs}


@app.patch("/api/studies/{study_id}")
def update_study(study_id: str, payload: StudyPatch) -> dict[str, Any]:
    study = study_row(study_id)
    data = model_data(payload)
    fields = model_fields_set(payload)
    assignments: list[str] = []
    run_count = study_run_count(study_id)
    target_project_id = str(data.get("project_id") or study.get("project_id") or "")
    target_study_type = str(data.get("study_type") or study.get("study_type") or "")
    target_study_scope = str(data.get("study_scope") or study.get("study_scope") or default_study_scope_for_type(target_study_type))
    target_project = project_row(target_project_id)
    validate_project_study_type(target_project, target_study_type)
    validate_study_type_scope(target_study_type, target_study_scope)
    if "project_id" in fields:
        project_id = data.get("project_id")
        if not project_id:
            raise HTTPException(status_code=400, detail="project_id cannot be empty.")
        project_row(str(project_id))
        assignments.append(f"project_id = {sql_text(project_id)}")
    if "study_type" in fields:
        study_type = data.get("study_type")
        if study_type is None:
            raise HTTPException(status_code=400, detail="study_type cannot be null.")
        if run_count and study_type != study.get("study_type"):
            raise HTTPException(status_code=400, detail="Cannot change study_type after runs have been attached.")
        assignments.append(f"study_type = {sql_text(study_type)}")
    if "study_scope" in fields:
        study_scope = data.get("study_scope")
        if study_scope is None:
            raise HTTPException(status_code=400, detail="study_scope cannot be null.")
        if run_count and study_scope != study.get("study_scope"):
            raise HTTPException(status_code=400, detail="Cannot change study_scope after runs have been attached.")
        assignments.append(f"study_scope = {sql_text(study_scope)}")
    if "study_name" in fields:
        if not data.get("study_name"):
            raise HTTPException(status_code=400, detail="study_name cannot be empty.")
        assignments.append(f"study_name = {sql_text(data.get('study_name'))}")
    if "description" in fields:
        assignments.append(f"description = {sql_text(data.get('description'))}")
    if "study_status" in fields:
        status = data.get("study_status")
        if status is None:
            raise HTTPException(status_code=400, detail="study_status cannot be null.")
        assignments.append(f"study_status = {sql_text(status)}")
        if status == "deleted":
            assignments.append("deleted_at = coalesce(deleted_at, now())")
        else:
            assignments.append("deleted_at = null")
    if assignments:
        assignments.append("updated_at = now()")
        query_one(
            "update vocera_studies "
            f"set {', '.join(assignments)} "
            f"where study_id = {sql_text(study_id)} "
            "returning study_id;"
        )
    return {"ok": True, "study": study_row(study_id, include_deleted=True)}


@app.delete("/api/studies/{study_id}")
def delete_study(study_id: str) -> dict[str, Any]:
    study_row(study_id)
    row = query_one(
        "update vocera_studies "
        "set study_status = 'deleted', deleted_at = coalesce(deleted_at, now()), updated_at = now() "
        f"where study_id = {sql_text(study_id)} "
        "returning study_id;"
    )
    return {"ok": bool(row), "study": study_row(study_id, include_deleted=True)}


@app.get("/api/studies/{study_id}/runs")
def list_study_runs(study_id: str, include_deleted: bool = False) -> dict[str, Any]:
    study_row(study_id, include_deleted=include_deleted)
    rows = query_rows(
        "select * from v_vocera_rf_validation_runs "
        f"where study_id = {sql_text(study_id)} "
        f"{'' if include_deleted else 'and deleted_at is null '} "
        "order by created_at desc, test_run_id desc;"
    )
    return {"ok": True, "runs": rows}


@app.get("/api/studies/{study_id}/run-comparison")
def study_run_comparison(study_id: str) -> dict[str, Any]:
    """Read-only side-by-side comparison of every run in a study.

    Pairs each run's match window and candidate/completion counts with per-run
    Cal Delta statistics and outlier counts, then derives completion percent and
    a plain-English interpretation. Nothing here mutates a run.
    """
    study_row(study_id)
    study_sql = sql_text(study_id)

    runs = query_rows(
        "select test_run_id, run_name, run_status, default_match_window_seconds, match_window_seconds_used, "
        "candidate_match_count, pending_candidate_match_count, completed_match_count, created_at "
        "from v_vocera_rf_validation_runs "
        f"where study_id = {study_sql} and deleted_at is null "
        "order by created_at asc, test_run_id asc;"
    )
    stats = query_rows(
        "select m.test_run_id, "
        "avg(m.calibrated_delta_db) as mean_cal_delta, "
        "stddev_samp(m.calibrated_delta_db) as stddev_cal_delta, "
        "percentile_cont(0.95) within group (order by m.calibrated_delta_db) as p95_cal_delta, "
        "min(m.calibrated_delta_db) as min_cal_delta, "
        "max(m.calibrated_delta_db) as max_cal_delta "
        "from badge_ekahau_matches m "
        "join validation_test_runs tr on tr.test_run_id = m.test_run_id "
        f"where tr.study_id = {study_sql} and m.manual_entry_status = 'complete' and m.calibrated_delta_db is not null "
        "group by m.test_run_id;"
    )
    outliers = query_rows(
        "select o.test_run_id, count(*) as outlier_count "
        "from v_vocera_ekahau_outliers o "
        "join validation_test_runs tr on tr.test_run_id = o.test_run_id "
        f"where tr.study_id = {study_sql} and o.outlier_status = 'outlier' "
        "group by o.test_run_id;"
    )
    stats_by_run = {row.get("test_run_id"): row for row in stats}
    outliers_by_run = {row.get("test_run_id"): row for row in outliers}

    parsed: list[dict[str, Any]] = []
    for row in runs:
        run_id = row.get("test_run_id")
        stat = stats_by_run.get(run_id, {})
        outlier = outliers_by_run.get(run_id, {})
        parsed.append(
            {
                "test_run_id": run_id,
                "run_name": row.get("run_name"),
                "run_status": row.get("run_status"),
                "default_match_window_seconds": _to_float(row.get("default_match_window_seconds")),
                "match_window_seconds_used": _to_float(row.get("match_window_seconds_used")),
                "candidate_match_count": _to_int(row.get("candidate_match_count")),
                "pending_candidate_match_count": _to_int(row.get("pending_candidate_match_count")),
                "completed_match_count": _to_int(row.get("completed_match_count")),
                "mean_cal_delta": _to_float(stat.get("mean_cal_delta")),
                "stddev_cal_delta": _to_float(stat.get("stddev_cal_delta")),
                "p95_cal_delta": _to_float(stat.get("p95_cal_delta")),
                "min_cal_delta": _to_float(stat.get("min_cal_delta")),
                "max_cal_delta": _to_float(stat.get("max_cal_delta")),
                "outlier_count": _to_int(outlier.get("outlier_count")) or 0,
            }
        )

    result = build_run_comparison(parsed)
    return {"ok": True, "study_id": study_id, "rows": result["rows"], "interpretation": result["interpretation"]}


@app.post("/api/studies/{study_id}/runs")
def create_study_run(study_id: str, payload: RunCreate) -> dict[str, Any]:
    validate_rf_study_id(study_id)
    data = model_data(payload)
    data["study_id"] = study_id
    return {"ok": True, "run": create_run_record(RunCreate(**data))}


@app.get("/api/studies/{study_id}/samples")
def list_study_samples(study_id: str, z_threshold: float = DEFAULT_Z_THRESHOLD) -> dict[str, Any]:
    study_row(study_id)
    return study_samples_response(study_id, z_threshold=z_threshold)


@app.post("/api/studies/{study_id}/samples")
def create_study_sample(
    study_id: str, payload: ManualSampleCreate, z_threshold: float = DEFAULT_Z_THRESHOLD
) -> dict[str, Any]:
    study_row(study_id)
    require_samples_table()
    insert_study_sample(study_id, payload)
    return study_samples_response(study_id, z_threshold=z_threshold)


@app.post("/api/studies/{study_id}/samples/bulk")
def create_study_samples_bulk(
    study_id: str, payload: ManualSampleBulkCreate, z_threshold: float = DEFAULT_Z_THRESHOLD
) -> dict[str, Any]:
    study_row(study_id)
    require_samples_table()
    valid = [
        sample
        for sample in payload.samples
        if sample.ekahau_rssi_dbm is not None or sample.ekahau_snr_db is not None
    ]
    if not valid:
        raise HTTPException(status_code=400, detail="Provide at least one sample with an Ekahau RSSI or SNR value.")
    for sample in valid:
        insert_study_sample(study_id, sample)
    return {**study_samples_response(study_id, z_threshold=z_threshold), "inserted": len(valid)}


@app.patch("/api/samples/{sample_id}")
def update_study_sample(
    sample_id: str, payload: ManualSamplePatch, z_threshold: float = DEFAULT_Z_THRESHOLD
) -> dict[str, Any]:
    require_samples_table()
    sample = sample_row(sample_id)
    study_row(str(sample.get("study_id") or ""))
    fields = model_fields_set(payload)
    data = model_data(payload)
    final_rssi = data.get("ekahau_rssi_dbm") if "ekahau_rssi_dbm" in fields else sample.get("ekahau_rssi_dbm")
    final_snr = data.get("ekahau_snr_db") if "ekahau_snr_db" in fields else sample.get("ekahau_snr_db")
    if not has_sample_measurement(final_rssi) and not has_sample_measurement(final_snr):
        raise HTTPException(status_code=400, detail="A sample must keep an Ekahau RSSI or SNR value.")

    assignments: list[str] = []
    if "label" in fields:
        assignments.append(f"label = {sql_text(data.get('label'))}")
    if "ekahau_rssi_dbm" in fields:
        assignments.append(f"ekahau_rssi_dbm = {sql_number(data.get('ekahau_rssi_dbm'))}")
    if "ekahau_snr_db" in fields:
        assignments.append(f"ekahau_snr_db = {sql_number(data.get('ekahau_snr_db'))}")
    if "notes" in fields:
        assignments.append(f"notes = {sql_text(data.get('notes'))}")
    if assignments:
        assignments.append("updated_at = now()")
        query_one(
            "update vocera_rf_manual_samples "
            f"set {', '.join(assignments)} "
            f"where sample_id = {sql_text(sample_id)} "
            "returning sample_id;"
        )
    return study_samples_response(sample["study_id"], z_threshold=z_threshold)


@app.delete("/api/samples/{sample_id}")
def delete_study_sample(sample_id: str, z_threshold: float = DEFAULT_Z_THRESHOLD) -> dict[str, Any]:
    require_samples_table()
    sample = sample_row(sample_id)
    study_row(str(sample.get("study_id") or ""))
    query_one(
        "update vocera_rf_manual_samples "
        "set deleted_at = coalesce(deleted_at, now()), updated_at = now() "
        f"where sample_id = {sql_text(sample_id)} "
        "returning sample_id;"
    )
    return study_samples_response(sample["study_id"], z_threshold=z_threshold)


@app.get("/api/projects/{project_id}/rf-results")
def get_project_rf_results(project_id: str) -> dict[str, Any]:
    project_row(project_id)
    rows = query_rows(
        "select * from v_vocera_rf_project_canonical_completed_matches "
        f"where project_id = {sql_text(project_id)} "
        "order by survey_time, lower(bssid), channel, study_name, run_name;"
    )
    return {"ok": True, "results": rows}


@app.get("/api/projects/{project_id}/rf-results/raw")
def get_project_rf_raw_results(project_id: str) -> dict[str, Any]:
    project_row(project_id)
    rows = query_rows(
        "select * from v_vocera_rf_project_completed_matches "
        f"where project_id = {sql_text(project_id)} "
        "order by survey_time, lower(bssid), channel, study_name, run_name;"
    )
    return {"ok": True, "results": rows}


@app.get("/api/projects/{project_id}/duplicates")
def get_project_duplicates(project_id: str) -> dict[str, Any]:
    project_row(project_id)
    rows = query_rows(
        "select * from v_vocera_rf_project_duplicate_datapoints "
        f"where project_id = {sql_text(project_id)} "
        "order by survey_time, lower(bssid), channel, duplicate_rank, study_name, run_name;"
    )
    return {"ok": True, "duplicates": rows}


@app.get("/api/rf/current-study")
def get_current_study() -> dict[str, Any]:
    current, error = safe_one(psql_db(), current_study_sql(scope()))
    return {"ok": error is None, "error": error, "current": current}


@app.get("/api/rf/live-runs")
def get_live_runs() -> dict[str, Any]:
    runs, error = safe_rows(psql_db(), live_runs_sql(scope()))
    return {"ok": error is None, "error": error, "runs": runs}


@app.get("/api/rf/archives")
def get_archives() -> dict[str, Any]:
    backend, backend_error = safe_one(psql_db(), backend_status_sql())
    if backend_error:
        return {"ok": False, "error": backend_error, "archives": []}
    if not backend_ready(backend):
        return {"ok": True, "error": None, "archives": [], "skipped": "schema update required", "backend": backend}
    archives, error = safe_rows(psql_db(), archives_sql(scope(), user()))
    return {"ok": error is None, "error": error, "archives": archives}


@app.get("/api/rf/archive-selection")
def get_archive_selection() -> dict[str, Any]:
    backend, backend_error = safe_one(psql_db(), backend_status_sql())
    if backend_error:
        return {"ok": False, "error": backend_error, "selection": {}}
    if not backend_ready(backend):
        return {"ok": True, "error": None, "selection": {}, "skipped": "schema update required", "backend": backend}
    selection, error = safe_one(psql_db(), selection_sql(scope(), user()))
    return {"ok": error is None, "error": error, "selection": selection}


@app.get("/api/rf/summary")
def get_rf_summary() -> dict[str, Any]:
    db = psql_db()
    backend, backend_error = safe_one(db, backend_status_sql())
    current, current_error = safe_one(db, current_study_sql(scope()))
    runs, runs_error = safe_rows(db, live_runs_sql(scope()))

    skipped = None
    if backend_error:
        skipped = "backend status unavailable"
    elif not backend_ready(backend):
        skipped = "schema update required"

    errors = {
        "backend": backend_error,
        "current": current_error,
        "runs": runs_error,
    }
    return {
        "ok": not any(errors.values()),
        "errors": errors,
        "skipped": skipped,
        "backend": backend,
        "current": current,
        "runs": runs,
        "config": app_config(),
    }


@app.get("/api/rf/input-files")
def list_input_files(source_type: SourceType | None = None, include_unavailable: bool = False) -> dict[str, Any]:
    filters = [f"study_scope = {sql_text(active_scope())}"]
    if source_type:
        filters.append(f"source_type = {sql_text(source_type)}")
    if not include_unavailable:
        filters.append("is_available = true")
    rows = query_rows(
        "select * from v_vocera_rf_validation_input_files "
        f"where {' and '.join(filters)} "
        "order by source_type, display_name, file_path;"
    )
    return {"ok": True, "input_files": rows}


@app.post("/api/rf/input-files/scan")
def scan_input_files(payload: InputFileScan) -> dict[str, Any]:
    selected_types = set(payload.source_types or default_scan_source_types())
    roots = [resolve_input_path(root) for root in payload.roots] if payload.roots else [root for root in input_scan_roots() if root.exists()]
    discovered_records: list[dict[str, Any]] = []
    for root in roots:
        if len(discovered_records) >= payload.max_files:
            break
        if not root.exists():
            continue
        paths = [root] if root.is_file() else root.rglob("*")
        for path in paths:
            if len(discovered_records) >= payload.max_files:
                break
            if not path.is_file():
                continue
            source_type = infer_source_type(path)
            if source_type == "other" and not payload.include_other:
                continue
            if source_type not in selected_types:
                continue
            if source_type == "badge_log" and badge_archive_validation_error(path):
                continue
            discovered_records.append(input_file_record(str(path), source_type=source_type))

    records = dedupe_input_file_records(discovered_records)

    input_file_ids: list[str] = []
    for record in records:
        result = query_one(upsert_input_file_sql(record))
        if result.get("input_file_id"):
            input_file_ids.append(result["input_file_id"])

    if not input_file_ids:
        return {"ok": True, "scanned_count": 0, "input_files": []}

    rows = query_rows(
        "select * from v_vocera_rf_validation_input_files "
        f"where input_file_id in ({', '.join(sql_text(input_file_id) for input_file_id in input_file_ids)}) "
        "order by source_type, display_name, file_path;"
    )
    return {"ok": True, "scanned_count": len(rows), "input_files": rows}


@app.post("/api/rf/input-files/upload")
async def upload_input_file(
    source_type: SourceType = Form(...),
    file: UploadFile = File(...),
    display_name: str | None = Form(None),
    notes: str | None = Form(None),
) -> dict[str, Any]:
    if source_type not in SOURCE_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported source_type: {source_type}")

    safe_name = safe_upload_filename(file.filename)
    target_dir = upload_dir_for(source_type)
    target_path = unique_upload_path(target_dir, safe_name)

    bytes_written = 0
    try:
        with target_path.open("wb") as handle:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                bytes_written += len(chunk)
                handle.write(chunk)
    except Exception as exc:  # noqa: BLE001 - surface upload write failures to the UI
        if target_path.exists():
            target_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Failed to store uploaded file: {exc}") from exc
    finally:
        await file.close()

    if bytes_written == 0:
        target_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    validate_uploaded_input_file(target_path, source_type)

    record = input_file_record(
        str(target_path),
        source_type=source_type,
        display_name=display_name or file.filename or safe_name,
        notes=notes,
    )
    duplicate = existing_visible_duplicate(record)
    if duplicate:
        hide_duplicate_input_file(record, duplicate.get("input_file_id") or "")
        return {"ok": True, "input_file": duplicate, "duplicate_of": duplicate.get("input_file_id")}
    return {"ok": True, "input_file": upsert_input_file_record(record)}


@app.post("/api/rf/run-bundles/upload")
async def upload_run_bundle(
    file: UploadFile = File(...),
    test_run_id: str | None = Form(None),
    run_name: str | None = Form(None),
    badge_mac: str | None = Form(None),
    notes: str | None = Form(None),
) -> dict[str, Any]:
    """Upload a Windows field bundle ZIP and turn it into a web-app run.

    The old Grafana refresh workflow uploaded a ZIP with folders such as
    survey/ and badge-log/. This endpoint keeps that bundle model, extracts it
    safely into the web app's incoming folder, discovers the newest badge log
    and Ekahau project, registers both input files, and attaches them to a run.
    """
    filename = file.filename or "rf-validation-bundle.zip"
    if not filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Upload a .zip field bundle containing survey/ and badge-log/ folders.")

    bundle_dir = bundle_upload_dir()
    safe_name = safe_upload_filename(filename)
    zip_path = unique_upload_path(bundle_dir, safe_name)

    bytes_written = 0
    try:
        with zip_path.open("wb") as handle:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                bytes_written += len(chunk)
                handle.write(chunk)
    except Exception as exc:  # noqa: BLE001
        if zip_path.exists():
            zip_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Failed to store uploaded bundle: {exc}") from exc
    finally:
        await file.close()

    if bytes_written == 0:
        zip_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded bundle is empty.")
    if not zipfile.is_zipfile(zip_path):
        zip_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded bundle is not a valid ZIP file.")

    extract_name = f"{Path(safe_name).stem}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}"
    extract_dir = (bundle_dir / extract_name).resolve(strict=False)
    safe_extract_zip(zip_path, extract_dir)

    badge_file, survey_file, resolved_badge_mac = discover_bundle_sources(extract_dir, badge_mac)
    if not badge_file:
        raise HTTPException(status_code=400, detail="No badge diagnostic file found in the bundle. Expected badge-log/ with .tar.gz, .tgz, .zip, .txt, .log, or sys file.")
    if not survey_file:
        raise HTTPException(status_code=400, detail="No Ekahau survey file found in the bundle. Expected survey/ with .esx, .zip, or .json.")

    validate_uploaded_input_file(badge_file, "badge_log")

    badge_record = input_file_record(
        str(badge_file),
        source_type="badge_log",
        display_name=badge_file.name,
        notes=f"Discovered from uploaded bundle {zip_path.name}",
    )
    survey_record = input_file_record(
        str(survey_file),
        source_type="ekahau_json",
        display_name=survey_file.name,
        notes=f"Discovered from uploaded bundle {zip_path.name}",
    )
    badge_input = upsert_input_file_record(badge_record)
    survey_input = upsert_input_file_record(survey_record)

    if test_run_id:
        run_row(test_run_id, include_deleted=False)
        run_id = test_run_id
        if run_name or resolved_badge_mac or notes:
            patch = RunPatch(run_name=run_name, badge_mac=resolved_badge_mac or None, notes=notes)
            update_run(run_id, patch)
    else:
        run_label = run_name or Path(safe_name).stem or "Uploaded RF validation bundle"
        created = create_run_record(
            RunCreate(
                run_name=run_label,
                run_status="draft",
                badge_mac=resolved_badge_mac or None,
                notes=notes or f"Created from uploaded bundle {zip_path.name}",
            )
        )
        run_id = created["test_run_id"]

    attach_input_file_to_run(run_id, badge_input["input_file_id"], "badge_log")
    attach_input_file_to_run(run_id, survey_input["input_file_id"], "ekahau_json")

    run_detail = get_run(run_id)
    return {
        "ok": True,
        "run": run_detail["run"],
        "files": run_detail.get("files", []),
        "badge_file": badge_input,
        "ekahau_file": survey_input,
        "bundle_path": stored_file_path(zip_path),
        "extract_dir": stored_file_path(extract_dir),
    }


@app.post("/api/rf/input-files/register")
def register_input_file(payload: InputFileRegister) -> dict[str, Any]:
    record = input_file_record(
        payload.file_path,
        source_type=payload.source_type,
        input_file_id=payload.input_file_id,
        display_name=payload.display_name,
        notes=payload.notes,
    )
    result = query_one(upsert_input_file_sql(record))
    return {"ok": True, "input_file": input_file_row(result.get("input_file_id") or record["input_file_id"])}


@app.patch("/api/rf/input-files/{input_file_id}")
def update_input_file(input_file_id: str, payload: InputFilePatch) -> dict[str, Any]:
    current = input_file_row(input_file_id)
    data = model_data(payload)
    fields = model_fields_set(payload)
    assignments: list[str] = []

    if "file_path" in fields:
        if not data.get("file_path"):
            raise HTTPException(status_code=400, detail="file_path cannot be empty.")
        source_type = data.get("source_type") if "source_type" in fields and data.get("source_type") else current.get("source_type") or "other"
        record = input_file_record(str(data["file_path"]), source_type=source_type)  # type: ignore[arg-type]
        assignments.extend(
            [
                f"source_type = {sql_text(record['source_type'])}",
                f"file_path = {sql_text(record['file_path'])}",
                f"file_name = {sql_text(record['file_name'])}",
                f"file_size_bytes = {sql_int(record.get('file_size_bytes'))}",
                f"file_mtime = {sql_timestamp(record.get('file_mtime'))}",
                f"source_sha256 = {sql_text(record.get('source_sha256'))}",
                f"is_available = {sql_bool(record.get('is_available'))}",
                "last_seen_at = now()",
            ]
        )
    elif "source_type" in fields:
        if data.get("source_type") is None:
            raise HTTPException(status_code=400, detail="source_type cannot be null.")
        assignments.append(f"source_type = {sql_text(data.get('source_type'))}")

    if "display_name" in fields:
        assignments.append(f"display_name = {sql_text(data.get('display_name'))}")
    if "is_available" in fields and "file_path" not in fields:
        assignments.append(f"is_available = {sql_bool(data.get('is_available'))}")
    if "notes" in fields:
        assignments.append(f"notes = {sql_text(data.get('notes'))}")

    if assignments:
        query_one(
            "update vocera_rf_validation_input_files "
            f"set {', '.join(assignments)} "
            f"where input_file_id = {sql_text(input_file_id)} and study_scope = {sql_text(active_scope())} "
            "returning input_file_id;"
        )
    return {"ok": True, "input_file": input_file_row(input_file_id)}


@app.delete("/api/rf/input-files/{input_file_id}")
def delete_input_file(input_file_id: str, hard: bool = False) -> dict[str, Any]:
    input_file_row(input_file_id)
    if hard:
        row = query_one(
            "delete from vocera_rf_validation_input_files "
            f"where input_file_id = {sql_text(input_file_id)} and study_scope = {sql_text(active_scope())} "
            "returning input_file_id;"
        )
        if not row:
            raise HTTPException(status_code=404, detail=f"No RF validation input file found for {input_file_id}.")
        return {"ok": True, "result": {"status": "deleted", "input_file_id": input_file_id}}

    row = query_one(
        "update vocera_rf_validation_input_files "
        "set is_available = false, last_seen_at = now() "
        f"where input_file_id = {sql_text(input_file_id)} and study_scope = {sql_text(active_scope())} "
        "returning input_file_id;"
    )
    return {"ok": bool(row), "result": {"status": "unavailable", "input_file_id": input_file_id}}


@app.get("/api/rf/runs")
def list_runs(include_deleted: bool = False, study_id: str | None = None) -> dict[str, Any]:
    filters = [f"study_scope = {sql_text(active_scope())}"]
    if study_id:
        filters.append(f"study_id = {sql_text(study_id)}")
    if not include_deleted:
        filters.append("deleted_at is null")
    rows = query_rows(
        "select * from v_vocera_rf_validation_runs "
        f"where {' and '.join(filters)} "
        "order by created_at desc, test_run_id desc;"
    )
    return {"ok": True, "runs": rows}


def manual_entry_rows(test_run_id: str) -> dict[str, list[dict[str, str]]]:
    return {
        "pending": query_rows(
            "select * from v_vocera_ekahau_pending_manual_entry "
            f"where test_run_id = {sql_text(test_run_id)} "
            "order by survey_time, badge_selected desc, badge_score desc nulls last, "
            "badge_rssi_dbm desc nulls last, lower(bssid), survey_point_id;"
        ),
        "completed": query_rows(
            "select completed.*, m.time_delta_seconds "
            "from v_vocera_ekahau_completed_manual_entry completed "
            "join badge_ekahau_matches m on m.id = completed.match_id "
            f"where completed.test_run_id = {sql_text(test_run_id)} "
            "order by completed.entered_at desc nulls last, completed.survey_time desc, completed.badge_selected desc, "
            "completed.badge_rssi_dbm desc nulls last, lower(completed.bssid), completed.survey_point_id;"
        )
    }


@app.get("/api/rf/runs/{test_run_id}")
def get_run(test_run_id: str) -> dict[str, Any]:
    run = run_row(test_run_id)
    files = query_rows(
        "select * from v_vocera_rf_validation_run_files "
        f"where test_run_id = {sql_text(test_run_id)} and study_scope = {sql_text(active_scope())} "
        "order by source_role, selected_at, display_name;"
    )
    alignment = query_one(
        "select * from v_vocera_ekahau_run_alignment "
        f"where test_run_id = {sql_text(test_run_id)};"
    )
    manual_entries = manual_entry_rows(test_run_id)
    return {"ok": True, "run": run, "files": files, "alignment": alignment, "manual_entries": manual_entries}


@app.get("/api/rf/runs/{test_run_id}/manual-entry")
def get_run_manual_entry(test_run_id: str) -> dict[str, Any]:
    run_row(test_run_id)
    return {"ok": True, "manual_entries": manual_entry_rows(test_run_id)}


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    parsed = _to_float(value)
    return None if parsed is None else int(parsed)


# Cap timeline arrays so a large badge log does not bloat the response.
_TIME_ALIGNMENT_POINT_CAP = 4000


@app.get("/api/rf/runs/{test_run_id}/time-alignment")
def get_run_time_alignment(test_run_id: str) -> dict[str, Any]:
    """Non-destructive Time Alignment Lab data for one run.

    Computes, straight from stored badge events and survey points (no run
    mutation), a tolerance sweep plus the series needed to visualize how the
    timestamp-only match rule behaves: a dual timeline, a nearest-delta
    histogram, and (after completion) a delta-vs-Cal-Delta scatter.
    """
    run = run_row(test_run_id)
    run_id_sql = sql_text(test_run_id)

    # Per survey point: signed nearest same-local-date badge delta + that badge
    # event id (the basis for the sweep, ambiguity, and the delta histogram).
    nearest_rows = query_rows(
        "select esp.survey_point_id, "
        "extract(epoch from (bse.event_time - esp.measured_at)) as delta_seconds, "
        "bse.event_id "
        "from ekahau_survey_points esp "
        "join validation_test_runs tr on tr.test_run_id = esp.test_run_id "
        "join lateral ("
        "  select b.event_time, b.event_id from badge_scan_events b "
        "  where b.test_run_id = esp.test_run_id "
        "    and (b.event_time at time zone tr.timezone)::date = (esp.measured_at at time zone tr.timezone)::date "
        "  order by abs(extract(epoch from (b.event_time - esp.measured_at))) limit 1"
        ") bse on true "
        f"where esp.test_run_id = {run_id_sql};"
    )
    points = [
        {"delta_seconds": _to_float(row.get("delta_seconds")), "event_id": row.get("event_id")}
        for row in nearest_rows
        if _to_float(row.get("delta_seconds")) is not None
    ]

    current_window = int(_to_float(run.get("default_match_window_seconds")) or 1)
    windows = sorted({*DEFAULT_SWEEP_WINDOWS, current_window})
    sweep = summarize_tolerance_sweep(points, windows)

    # Trim the timeline to the badge/survey time overlap so the payload stays
    # small. The sweep above still considers every survey point; only the
    # timeline epoch arrays are limited to the relevant overlap window.
    badge_range = query_one(
        "select extract(epoch from min(event_time)) as lo, extract(epoch from max(event_time)) as hi, count(*) as n "
        f"from badge_scan_events where test_run_id = {run_id_sql};"
    )
    survey_range = query_one(
        "select extract(epoch from min(measured_at)) as lo, extract(epoch from max(measured_at)) as hi, count(*) as n "
        f"from ekahau_survey_points where test_run_id = {run_id_sql};"
    )
    badge_total_raw = _to_float(badge_range.get("n"))
    survey_total_raw = _to_float(survey_range.get("n"))
    badge_total = int(badge_total_raw) if badge_total_raw is not None else 0
    survey_total = int(survey_total_raw) if survey_total_raw is not None else 0
    window = overlap_window(
        _to_float(badge_range.get("lo")),
        _to_float(badge_range.get("hi")),
        _to_float(survey_range.get("lo")),
        _to_float(survey_range.get("hi")),
        margin_seconds=max(current_window * 2, 5),
    )
    badge_epochs: list[float] = []
    survey_epochs: list[float] = []
    badge_truncated = False
    survey_truncated = False
    window_start = window[0] if window else None
    window_end = window[1] if window else None
    if window is not None:
        badge_rows = query_rows(
            "select extract(epoch from event_time) as t from badge_scan_events "
            f"where test_run_id = {run_id_sql} "
            f"and event_time >= to_timestamp({window_start}) and event_time <= to_timestamp({window_end}) "
            f"order by event_time limit {_TIME_ALIGNMENT_POINT_CAP + 1};"
        )
        survey_rows = query_rows(
            "select extract(epoch from measured_at) as t from ekahau_survey_points "
            f"where test_run_id = {run_id_sql} "
            f"and measured_at >= to_timestamp({window_start}) and measured_at <= to_timestamp({window_end}) "
            f"order by measured_at limit {_TIME_ALIGNMENT_POINT_CAP + 1};"
        )
        badge_epochs = [t for t in (_to_float(row.get("t")) for row in badge_rows[:_TIME_ALIGNMENT_POINT_CAP]) if t is not None]
        survey_epochs = [t for t in (_to_float(row.get("t")) for row in survey_rows[:_TIME_ALIGNMENT_POINT_CAP]) if t is not None]
        badge_truncated = len(badge_rows) > _TIME_ALIGNMENT_POINT_CAP
        survey_truncated = len(survey_rows) > _TIME_ALIGNMENT_POINT_CAP

    cal_rows = query_rows(
        "select abs(time_delta_seconds) as abs_delta, calibrated_delta_db "
        "from badge_ekahau_matches "
        f"where test_run_id = {run_id_sql} and manual_entry_status = 'complete' "
        "and calibrated_delta_db is not null;"
    )
    cal_delta_points = [
        {"abs_time_delta_seconds": _to_float(row.get("abs_delta")), "calibrated_delta_db": _to_float(row.get("calibrated_delta_db"))}
        for row in cal_rows
        if _to_float(row.get("abs_delta")) is not None and _to_float(row.get("calibrated_delta_db")) is not None
    ]

    return {
        "ok": True,
        "test_run_id": test_run_id,
        "current_window_seconds": current_window,
        "sweep": sweep,
        "timeline": {
            "badge_event_epochs": badge_epochs,
            "survey_point_epochs": survey_epochs,
            "badge_event_count": badge_total,
            "survey_point_count": survey_total,
            "window_start_epoch": window_start,
            "window_end_epoch": window_end,
            "badge_truncated": badge_truncated,
            "survey_truncated": survey_truncated,
        },
        "cal_delta_points": cal_delta_points,
    }


@app.post("/api/rf/candidates/{candidate_match_id}/manual-entry")
def submit_manual_entry(candidate_match_id: str, payload: ManualEntrySubmit) -> dict[str, Any]:
    candidate = query_one(
        "select test_run_id, survey_point_id, bssid, survey_time "
        "from badge_ekahau_candidate_matches "
        f"where id = {sql_text(candidate_match_id)};"
    )
    if not candidate:
        raise HTTPException(status_code=404, detail=f"No candidate row found for id {candidate_match_id}.")

    result = query_one(
        "select * from vocera_rf_validation_submit_candidate_match(" 
        f"{sql_text(candidate_match_id)}, {sql_text(payload.ekahau_rssi_dbm)}, "
        f"{sql_text(payload.ekahau_snr_db)}, {sql_text(payload.notes)}, {sql_text(user())}" 
        ");"
    )
    if not result:
        raise HTTPException(status_code=500, detail="Manual entry submission returned no result.")
    if result.get('status') == 'error':
        raise HTTPException(status_code=400, detail=result.get('message') or 'Manual entry submission failed.')
    return {"ok": True, "result": result}


@app.delete("/api/rf/matches/{match_id}")
def reset_manual_match(match_id: str) -> dict[str, Any]:
    row = query_one(
        "select candidate_match_id from badge_ekahau_matches "
        f"where id = {sql_text(match_id)};"
    )
    if not row or not row.get('candidate_match_id'):
        raise HTTPException(status_code=404, detail=f"No manual-entry match found for id {match_id}.")

    result = query_one(
        "select * from vocera_rf_validation_clear_candidate_manual_entry(" 
        f"{sql_text(row['candidate_match_id'])}, {sql_text(user())}" 
        ");"
    )
    if not result:
        raise HTTPException(status_code=500, detail="Resetting manual entry returned no result.")
    if result.get('status') == 'error':
        raise HTTPException(status_code=400, detail=result.get('message') or 'Resetting manual entry failed.')
    return {"ok": True, "result": result}


@app.post("/api/rf/runs")
def create_run(payload: RunCreate) -> dict[str, Any]:
    return {"ok": True, "run": create_run_record(payload)}


@app.patch("/api/rf/runs/{test_run_id}")
def update_run(test_run_id: str, payload: RunPatch) -> dict[str, Any]:
    run_row(test_run_id)
    data = model_data(payload)
    fields = model_fields_set(payload)
    assignments: list[str] = []
    text_fields = {
        "run_name": "run_name",
        "site": "site",
        "building": "building",
        "floor": "floor",
        "area": "area",
        "ssid": "ssid",
        "badge_mac": "badge_mac",
        "badge_model": "badge_model",
        "ekahau_device": "ekahau_device",
        "ekahau_project": "ekahau_project",
        "vendor_offset_source": "vendor_offset_source",
    }
    for attr, column in text_fields.items():
        if attr in fields:
            assignments.append(f"{column} = {sql_text(data.get(attr))}")
    if "study_id" in fields:
        assignments.append(f"study_id = {sql_text(validate_rf_study_id(data.get('study_id')))}")
    if "timezone" in fields:
        assignments.append(f"timezone = coalesce({sql_text(data.get('timezone'))}, 'America/Chicago')")
    if "badge_time_offset_seconds" in fields:
        assignments.append(f"badge_time_offset_seconds = coalesce({sql_int(data.get('badge_time_offset_seconds'))}, 0)")
    if "ekahau_time_offset_seconds" in fields:
        assignments.append(f"ekahau_time_offset_seconds = coalesce({sql_int(data.get('ekahau_time_offset_seconds'))}, 0)")
    if "default_match_window_seconds" in fields:
        assignments.append(f"default_match_window_seconds = coalesce({sql_int(data.get('default_match_window_seconds'))}, 1)")
    if "notes" in fields:
        assignments.append(f"notes = {sql_text(data.get('notes'))}")
        assignments.append(f"run_notes = {sql_text(data.get('notes'))}")
    if "run_status" in fields:
        run_status = data.get("run_status")
        if run_status is None:
            raise HTTPException(status_code=400, detail="run_status cannot be null.")
        assignments.append(f"run_status = {sql_text(run_status)}")
        if run_status == "deleted":
            assignments.append("deleted_at = coalesce(deleted_at, now())")
            assignments.append(f"deleted_by = coalesce(deleted_by, {sql_text(user())})")
        else:
            assignments.append("deleted_at = null")
            assignments.append("deleted_by = null")

    if assignments:
        assignments.append("run_updated_at = now()")
        query_one(
            "update validation_test_runs "
            f"set {', '.join(assignments)} "
            f"where test_run_id = {sql_text(test_run_id)} "
            "returning test_run_id;"
        )
    return {"ok": True, "run": run_row(test_run_id)}


@app.delete("/api/rf/runs/{test_run_id}")
def delete_run(test_run_id: str, hard: bool = False) -> dict[str, Any]:
    run_row(test_run_id)
    if hard:
        row = query_one(
            "select status, test_run_id, candidate_match_count, completed_match_count, source_file_count, message "
            f"from vocera_rf_validation_delete_run({sql_text(test_run_id)}, {sql_text(user())});"
        )
        return {"ok": row.get("status") == "deleted", "result": row}

    row = query_one(
        "update validation_test_runs "
        "set run_status = 'deleted', deleted_at = coalesce(deleted_at, now()), deleted_by = coalesce(deleted_by, "
        f"{sql_text(user())}), run_updated_at = now() "
        f"where test_run_id = {sql_text(test_run_id)} "
        "returning test_run_id;"
    )
    return {"ok": bool(row), "run": run_row(test_run_id)}


@app.post("/api/rf/runs/{test_run_id}/files")
def add_run_file(test_run_id: str, payload: RunFileSelection) -> dict[str, Any]:
    run_row(test_run_id, include_deleted=False)
    input_file = input_file_row(payload.input_file_id)
    if str(input_file.get("is_available", "")).lower() not in {"t", "true", "1", "yes"}:
        raise HTTPException(status_code=400, detail="Input file is unavailable and cannot be attached to a run.")
    source_role = payload.source_role or input_file.get("source_type") or "other"
    if source_role not in SOURCE_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported source_role: {source_role}")
    if source_role == "badge_log":
        resolved_input = resolve_input_path(input_file.get("file_path") or "")
        error = badge_archive_validation_error(resolved_input)
        if error:
            query_one(
                "update vocera_rf_validation_input_files "
                "set is_available = false, last_seen_at = now(), notes = concat_ws(E'\n', nullif(notes, ''), "
                f"{sql_text(error)}) "
                f"where input_file_id = {sql_text(payload.input_file_id)} "
                "returning input_file_id;"
            )
            raise HTTPException(status_code=400, detail=f"{error} Re-upload the full badge diagnostic bundle.")
    query_one(
        "insert into vocera_rf_validation_run_input_files (test_run_id, input_file_id, source_role) "
        f"values ({sql_text(test_run_id)}, {sql_text(payload.input_file_id)}, {sql_text(source_role)}) "
        "on conflict on constraint vocera_rf_validation_run_input_files_pkey "
        "do update set selected_at = now() "
        "returning test_run_id;"
    )
    return get_run(test_run_id)


@app.delete("/api/rf/runs/{test_run_id}/files/{input_file_id}")
def remove_run_file(test_run_id: str, input_file_id: str) -> dict[str, Any]:
    run_row(test_run_id, include_deleted=False)
    row = query_one(
        "delete from vocera_rf_validation_run_input_files "
        f"where test_run_id = {sql_text(test_run_id)} and input_file_id = {sql_text(input_file_id)} "
        "returning test_run_id;"
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"Input file {input_file_id} is not attached to run {test_run_id}.")
    return get_run(test_run_id)


@app.post("/api/rf/runs/{test_run_id}/execute")
def execute_run(test_run_id: str) -> dict[str, Any]:
    run = run_row(test_run_id, include_deleted=False)
    files = query_rows(
        "select * from v_vocera_rf_validation_run_files "
        f"where test_run_id = {sql_text(test_run_id)} and study_scope = {sql_text(active_scope())} "
        "order by source_role, selected_at, display_name;"
    )

    preflight_errors: list[str] = []
    for selected_file in files:
        role = selected_file.get("source_role") or selected_file.get("source_type")
        file_path = selected_file.get("file_path") or ""
        try:
            resolved_file = resolve_input_path(file_path)
        except HTTPException as exc:
            preflight_errors.append(str(exc.detail))
            continue
        if not resolved_file.is_file():
            preflight_errors.append(f"Selected {role} file is missing on disk: {file_path}")
            continue
        if role == "badge_log":
            error = badge_archive_validation_error(resolved_file)
            if error:
                preflight_errors.append(f"{selected_file.get('display_name') or selected_file.get('file_name') or file_path}: {error}")
    if preflight_errors:
        detail = " ".join(preflight_errors)
        query_one(
            "update validation_test_runs "
            f"set run_status = 'failed', run_execution_error = {sql_text(detail)}, run_updated_at = now() "
            f"where test_run_id = {sql_text(test_run_id)} "
            "returning test_run_id;"
        )
        raise HTTPException(status_code=400, detail=detail)

    query_one(
        "update validation_test_runs "
        "set run_status = 'running', run_execution_error = null, run_updated_at = now() "
        f"where test_run_id = {sql_text(test_run_id)} "
        "returning test_run_id;"
    )

    db = psql_db()
    try:
        result = execute_selected_run(
            test_run_id=test_run_id,
            run=run,
            files=files,
            root=ROOT,
            config_path=os.environ.get("VOCERA_RF_VALIDATION_CONFIG", "config/vocera-rf-validation.yaml"),
            postgres_url=db.url,
            psql_bin=db.psql_bin,
            scope=active_scope(),
        )
    except Exception as exc:  # noqa: BLE001 - return execution failure to the UI
        detail = str(exc)
        query_one(
            "update validation_test_runs "
            f"set run_status = 'failed', run_execution_error = {sql_text(detail)}, run_updated_at = now() "
            f"where test_run_id = {sql_text(test_run_id)} "
            "returning test_run_id;"
        )
        raise HTTPException(status_code=500, detail=detail) from exc

    query_one(
        "update validation_test_runs "
        "set run_status = 'complete', run_executed_at = now(), run_execution_error = null, run_updated_at = now(), "
        f"match_window_seconds_used = {sql_int(result.match_window_seconds_used)}, "
        f"runtime_config_path = {sql_text(result.run_config)} "
        f"where test_run_id = {sql_text(test_run_id)} "
        "returning test_run_id;"
    )
    return {"ok": True, "result": result.to_dict(), "run": run_row(test_run_id)}


@app.post("/api/rf/current-study")
def update_current_study(payload: CurrentStudyUpdate) -> dict[str, Any]:
    row = query_one(
        "select status, study_scope, study_name, message "
        f"from vocera_rf_validation_set_current_study({sql_literal(payload.study_name)}, {sql_literal(payload.notes)}, {sql_literal(user())}, {sql_literal(scope())});"
    )
    return {"ok": row.get("status") not in {"error", "not_found"}, "result": row}


@app.post("/api/rf/current-study/action")
def apply_current_study_action(payload: CurrentStudyAction) -> dict[str, Any]:
    row = query_one(
        "select status, archive_id, test_run_count, candidate_match_count, completed_match_count, message "
        f"from vocera_rf_validation_apply_current_study_action({sql_literal(payload.action_key)}, null, null, {sql_literal(user())}, {sql_literal(scope())});"
    )
    return {"ok": row.get("status") not in {"error", "not_found"}, "result": row}


@app.post("/api/rf/archive/update")
def update_archive(payload: ArchiveUpdate) -> dict[str, Any]:
    row = query_one(
        "select status, archive_id, test_run_count, candidate_match_count, completed_match_count, message "
        f"from vocera_rf_validation_update_study_archive({sql_literal(payload.archive_id)}, {sql_literal(payload.archive_label)}, {sql_literal(payload.notes)}, {sql_literal(user())}, {sql_literal('true' if payload.combine_selected else 'false')});"
    )
    return {"ok": row.get("status") not in {"error", "not_found"}, "result": row}



@app.post("/api/rf/archive/make-current")
def make_archive_current(payload: ArchiveMakeCurrent) -> dict[str, Any]:
    row = query_one(
        "select status, archived_current_archive_id, restored_archive_id, test_run_count, candidate_match_count, completed_match_count, message "
        f"from vocera_rf_validation_make_archive_current({sql_literal(payload.archive_id)}, {sql_literal(user())}, {sql_literal(payload.notes)});"
    )
    return {"ok": row.get("status") not in {"error", "not_found"}, "result": row}


@app.post("/api/rf/archive/delete")
def delete_archive(payload: ArchiveDelete) -> dict[str, Any]:
    row = query_one(
        "select status, archive_id, test_run_count, candidate_match_count, completed_match_count, message "
        f"from vocera_rf_validation_delete_study_archive({sql_literal(payload.archive_id)}, {sql_literal(user())});"
    )
    return {"ok": row.get("status") not in {"error", "not_found"}, "result": row}


@app.post("/api/rf/archive-selection/clear")
def clear_archive_selection() -> dict[str, Any]:
    row = query_one(
        "select status, cleared_count, message "
        f"from vocera_rf_validation_clear_study_archive_selection({sql_literal(user())}, {sql_literal(scope())});"
    )
    return {"ok": row.get("status") not in {"error", "not_found"}, "result": row}


@app.post("/api/rf/archive-selection/combine")
def create_combined_study(payload: CombinedStudyCreate) -> dict[str, Any]:
    row = query_one(
        "select status, archive_id, source_archive_count, test_run_count, candidate_match_count, completed_match_count, message "
        f"from vocera_rf_validation_create_combined_study_archive({sql_literal(payload.archive_label)}, {sql_literal(payload.notes)}, {sql_literal(user())}, {sql_literal(scope())});"
    )
    return {"ok": row.get("status") not in {"error", "not_found"}, "result": row}


def media_limit(value: int, default: int = 500, maximum: int = 5000) -> int:
    if value <= 0:
        return default
    return min(value, maximum)


def media_project_summary_row(project_id: str) -> dict[str, str]:
    row = media_query_one(
        "select * from v_vocera_media_qoe_project_summary "
        f"where project_id = {sql_text(project_id)};"
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"No media QoE summary found for project {project_id}.")
    return row


def media_stream_row(capture_id: str, stream_id: str) -> dict[str, str]:
    row = media_query_one(
        "select * from v_vocera_media_qoe_study_streams "
        f"where capture_id = {sql_text(capture_id)} "
        f"and stream_id = {sql_text(stream_id)};"
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"No media QoE stream found for {capture_id}/{stream_id}.")
    return row


def media_raw_dir() -> Path:
    configured = os.environ.get("STUDY_WEB_MEDIA_QOE_RAW_DIR", "/var/lib/vocera-media-qoe/raw").strip()
    if not configured:
        raise HTTPException(status_code=500, detail="STUDY_WEB_MEDIA_QOE_RAW_DIR is empty.")
    try:
        root = Path(configured).expanduser().resolve(strict=True)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Raw capture directory is missing: {configured}") from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Raw capture directory is not accessible: {exc}") from exc
    if not root.is_dir():
        raise HTTPException(status_code=400, detail=f"Raw capture path is not a directory: {root}")
    if not os.access(root, os.R_OK):
        raise HTTPException(status_code=403, detail=f"Raw capture directory is not readable: {root}")
    return root


def media_allowed_extensions() -> set[str]:
    configured = os.environ.get("STUDY_WEB_MEDIA_QOE_ALLOWED_EXTENSIONS", ",".join(MEDIA_QOE_DEFAULT_ALLOWED_EXTENSIONS))
    extensions = {item.strip().lower() for item in configured.split(",") if item.strip()}
    normalized = {item if item.startswith(".") else f".{item}" for item in extensions}
    return normalized or set(MEDIA_QOE_DEFAULT_ALLOWED_EXTENSIONS)


def media_env_int(name: str, default: int, *, minimum: int = 1, maximum: int | None = None) -> int:
    raw = os.environ.get(name)
    try:
        value = int(raw) if raw not in (None, "") else default
    except ValueError:
        value = default
    value = max(value, minimum)
    return min(value, maximum) if maximum is not None else value


def media_max_scan_files() -> int:
    return media_env_int("STUDY_WEB_MEDIA_QOE_MAX_SCAN_FILES", 500, minimum=1, maximum=5000)


def media_max_parse_bytes() -> int:
    return media_env_int("STUDY_WEB_MEDIA_QOE_MAX_PARSE_BYTES", 2_147_483_648, minimum=1)


def media_parse_timeout_seconds() -> int:
    return media_env_int("STUDY_WEB_MEDIA_QOE_PARSE_TIMEOUT_SECONDS", 300, minimum=1, maximum=3600)


def media_execution_enabled() -> bool:
    return env_bool("STUDY_WEB_MEDIA_QOE_EXECUTION_ENABLED", True)


def media_archive_enabled() -> bool:
    return env_bool("STUDY_WEB_MEDIA_QOE_ARCHIVE_ENABLED", False)


def media_path_has_traversal(path_text: str) -> bool:
    return any(part == ".." for part in Path(path_text).parts)


def validate_media_raw_file(source_path: str) -> Path:
    if "\x00" in source_path:
        raise HTTPException(status_code=400, detail="Source path contains an invalid null byte.")
    if media_path_has_traversal(source_path):
        raise HTTPException(status_code=400, detail="Source path traversal is not allowed.")
    if Path(source_path).suffix.lower() not in media_allowed_extensions():
        raise HTTPException(status_code=400, detail=f"Unsupported capture extension: {Path(source_path).suffix or '<none>'}.")

    root = media_raw_dir()
    raw_path = Path(source_path).expanduser()
    candidate = raw_path if raw_path.is_absolute() else root / raw_path
    try:
        candidate.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Capture path must stay under STUDY_WEB_MEDIA_QOE_RAW_DIR.") from exc

    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Capture file was not found: {source_path}") from exc
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Capture file is not accessible: {exc}") from exc

    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Capture path must stay under STUDY_WEB_MEDIA_QOE_RAW_DIR.") from exc

    if media_path_under_wlc_managed(resolved):
        raise HTTPException(
            status_code=400,
            detail="WLC capture-session/attempt files are ingested by their own pipelines, not the generic raw-file path.",
        )

    if not resolved.is_file():
        raise HTTPException(status_code=400, detail="Capture path must be a regular file.")
    return resolved


def media_source_state(path: Path) -> dict[str, Any]:
    stat = path.stat()
    resolved = str(path.resolve(strict=True))
    return {
        "path": resolved,
        "name": path.name,
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "mtime": datetime.fromtimestamp(stat.st_mtime, timezone.utc),
    }


def media_capture_identity(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": state.get("path"),
        "size_bytes": state.get("size_bytes"),
        "mtime_ns": state.get("mtime_ns"),
    }


def media_capture_id_for_state(state: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(media_capture_identity(state), sort_keys=True).encode("utf-8")).hexdigest()[:24]


def media_source_sha256_for_state(state: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(media_capture_identity(state), sort_keys=True).encode("utf-8")).hexdigest()


def media_jsonb(value: Any) -> str:
    return sql_text(json.dumps(value or {}, sort_keys=True)) + "::jsonb"


def media_capture_row(capture_id: str) -> dict[str, str]:
    row = media_query_one(
        "select * from vocera_media_captures "
        f"where capture_id = {sql_text(capture_id)} "
        "and deleted_at is null;"
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"No media QoE capture found for {capture_id}.")
    return row


def media_study_capture_row(capture_id: str) -> dict[str, str]:
    row = media_query_one(
        "select * from v_vocera_media_qoe_study_captures "
        f"where capture_id = {sql_text(capture_id)};"
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"No media QoE capture found for {capture_id}.")
    return row


def media_parse_summary(capture_id: str) -> dict[str, int]:
    row = media_query_one(
        "select "
        "count(distinct c.capture_id)::integer as captures, "
        "count(s.stream_id)::integer as streams, "
        "count(s.stream_id) filter (where s.measurement_mode = 'rtp' and s.packet_count >= 20)::integer as rtp_qoe_streams, "
        "count(s.stream_id) filter (where s.dscp_mismatch)::integer as dscp_mismatch_streams, "
        "count(s.stream_id) filter (where coalesce(s.lost_packets, 0) > 0 or coalesce(s.loss_ratio, 0) > 0)::integer as lossy_streams "
        "from vocera_media_captures c "
        "left join vocera_media_stream_samples s on s.capture_id = c.capture_id "
        f"where c.capture_id = {sql_text(capture_id)} "
        "group by c.capture_id;"
    )
    return {key: int(row.get(key) or 0) for key in ("captures", "streams", "rtp_qoe_streams", "dscp_mismatch_streams", "lossy_streams")}


def media_truncate_output(value: str | bytes | None, limit: int = 60_000) -> str | None:
    if value is None:
        return None
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... truncated after {limit} characters"



MEDIA_QOE_PARSE_LOCK_NAME = "media_qoe_parse_global"


def media_active_parse_lock() -> dict[str, str]:
    return media_query_one(
        "select "
        "lock_name, capture_id, parse_run_id, acquired_by, acquired_at, expires_at, heartbeat_at "
        "from vocera_media_execution_locks "
        f"where lock_name = {sql_text(MEDIA_QOE_PARSE_LOCK_NAME)} "
        "and expires_at > now();"
    )


def media_acquire_parse_lock(capture_id: str, parse_run_id: str, timeout_seconds: int) -> dict[str, str]:
    expires_after_seconds = max(int(timeout_seconds) + 60, 120)
    row = media_query_one(
        "with stale as ("
        "  delete from vocera_media_execution_locks "
        f"  where lock_name = {sql_text(MEDIA_QOE_PARSE_LOCK_NAME)} "
        "  and expires_at <= now() "
        "  returning lock_name"
        "), attempt as ("
        "  insert into vocera_media_execution_locks ("
        "    lock_name, capture_id, parse_run_id, acquired_by, acquired_at, expires_at, heartbeat_at"
        "  ) values ("
        f"    {sql_text(MEDIA_QOE_PARSE_LOCK_NAME)}, "
        f"    {sql_text(capture_id)}, "
        f"    {sql_text(parse_run_id)}, "
        f"    {sql_text(user())}, "
        "    now(), "
        f"    now() + interval '{expires_after_seconds} seconds', "
        "    now()"
        "  ) "
        "  on conflict (lock_name) do nothing "
        "  returning "
        "    lock_name, capture_id, parse_run_id, acquired_by, acquired_at, expires_at, heartbeat_at, "
        "    true as acquired"
        "), current_lock as ("
        "  select "
        "    lock_name, capture_id, parse_run_id, acquired_by, acquired_at, expires_at, heartbeat_at, "
        "    false as acquired "
        "  from vocera_media_execution_locks "
        f"  where lock_name = {sql_text(MEDIA_QOE_PARSE_LOCK_NAME)} "
        "  and not exists (select 1 from attempt)"
        ") "
        "select * from attempt "
        "union all "
        "select * from current_lock "
        "limit 1;"
    )
    acquired = str(row.get("acquired", "")).lower() in {"t", "true", "1", "yes"}
    if not acquired:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Another Media QoE parse is already running.",
                "active_parse": row,
            },
        )
    return row


def media_release_parse_lock(parse_run_id: str) -> None:
    media_query_one(
        "delete from vocera_media_execution_locks "
        f"where lock_name = {sql_text(MEDIA_QOE_PARSE_LOCK_NAME)} "
        f"and parse_run_id = {sql_text(parse_run_id)}; "
        f"select {sql_text(parse_run_id)} as parse_run_id;"
    )


def media_parser_config_path() -> Path:
    configured = os.environ.get("STUDY_WEB_MEDIA_QOE_CONFIG", os.environ.get("VOCERA_MEDIA_QOE_CONFIG", "config/vocera-media-qoe.yaml"))
    path = Path(configured)
    return path if path.is_absolute() else ROOT / path


def media_wlc_imports() -> tuple[Any, Any]:
    """Load the manual WLC session helpers on demand."""

    path = str(ROOT / "tools" / "vocera_media_qoe")
    if path not in sys.path:
        sys.path.insert(0, path)
    try:
        import vocera_multicast as multicast  # type: ignore[import-not-found]
        import vocera_wlc_session as wlc_session  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - depends on local checkout
        raise RuntimeError(f"Manual WLC helpers are not importable: {exc}") from exc
    return multicast, wlc_session


def media_wlc_yaml_config() -> dict[str, Any]:
    """Load the site Media QoE YAML config for non-secret WLC defaults."""

    path = media_parser_config_path()
    if not path.is_file():
        return {}
    try:
        import yaml  # type: ignore[import-not-found]

        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def media_wlc_defaults() -> dict[str, Any]:
    """Return non-secret WLC capture defaults from config plus safe fallbacks."""

    multicast, _ = media_wlc_imports()
    config = media_wlc_yaml_config()
    wlc = config.get("wlc_capture") if isinstance(config.get("wlc_capture"), dict) else {}
    vocera = config.get("vocera_multicast") if isinstance(config.get("vocera_multicast"), dict) else {}
    pool = vocera.get("ipv4_pool") if isinstance(vocera.get("ipv4_pool"), dict) else {}
    sender = wlc.get("sender") if isinstance(wlc.get("sender"), dict) else {}
    receiver = wlc.get("receiver") if isinstance(wlc.get("receiver"), dict) else {}
    return {
        "site": wlc.get("site") or config.get("site") or "unknown",
        "wlc_name": wlc.get("wlc_name") or "",
        # Blank by default so the create endpoint generates a unique, WLC-safe
        # capture name. A static prefill collides on the controller and the
        # generator fallback would almost never run if the UI sent a fixed value.
        "capture_name": wlc.get("capture_name") or "",
        "wlc_interface": wlc.get("wlc_interface") or "",
        "capture_filter_mode": wlc.get("capture_filter_mode") or "vocera_pool_control",
        "collector_host": wlc.get("collector_host") or "",
        "collector_scp_username": wlc.get("collector_scp_username") or "",
        "collector_scp_port": int(wlc.get("collector_scp_port") or 22),
        "ring_file_count": int(wlc.get("ring_file_count") or 5),
        "ring_file_size_mb": int(wlc.get("ring_file_size_mb") or 100),
        "continuous_export_enabled": bool(wlc.get("continuous_export_enabled", False)),
        "short_validation_duration_seconds": int(wlc.get("short_validation_duration_seconds") or 90),
        "expected_dscp": int((vocera.get("expected_dscp") if isinstance(vocera, dict) else None) or config.get("expected_dscp") or 46),
        "vocera_vlan": int(wlc.get("vocera_vlan") or 684),
        "vocera_multicast_pool": pool.get("cidr") or multicast.DEFAULT_VOCERA_MULTICAST_CIDR,
        "vocera_first_usable": pool.get("first_usable") or multicast.DEFAULT_FIRST_USABLE,
        "vocera_last_usable": pool.get("last_usable") or multicast.DEFAULT_LAST_USABLE,
        "sender": {
            "name": sender.get("name") or "V5000 Sender",
            "model": sender.get("model") or "V5000",
            "mac": sender.get("mac") or "",
            "ip": sender.get("ip") or "",
        },
        "receiver": {
            "name": receiver.get("name") or "C1000 Receiver",
            "model": receiver.get("model") or "C1000",
            "mac": receiver.get("mac") or "",
            "ip": receiver.get("ip") or "",
        },
    }


def media_wlc_session_root(*, create: bool = False) -> Path:
    """Return the raw-root-scoped WLC session package root."""

    raw = media_raw_dir()
    configured = os.environ.get("STUDY_WEB_MEDIA_QOE_WLC_SESSION_ROOT", "").strip()
    root = Path(configured).expanduser() if configured else raw / "wlc-sessions"
    candidate = root if root.is_absolute() else raw / root
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="WLC session root must stay under STUDY_WEB_MEDIA_QOE_RAW_DIR.") from exc
    if create:
        resolved.mkdir(parents=True, exist_ok=True)
    return resolved


WLC_MANAGED_SCAN_DIRS = ("wlc-sessions", "wlc-attempts")


def media_path_under_wlc_managed(path: Path) -> bool:
    """Return True when ``path`` resolves inside a WLC-managed package root.

    WLC capture-session (``wlc-sessions``) and capture-attempt (``wlc-attempts``)
    packages are owned by their own ingest pipelines, never by the generic
    raw-file register/scan endpoints, so the evidence pipelines cannot
    cross-contaminate: a half-uploaded session EPC must not be parsed by a
    generic operator action, and a session/attempt EPC must not be
    double-registered or mislabeled as ordinary ICAP evidence. This mirrors the
    batch publisher's DEFAULT_EXCLUDED_SCAN_DIRS so both automated paths agree.
    """

    try:
        root = media_raw_dir()
    except HTTPException:
        return False
    try:
        parts = path.resolve(strict=False).relative_to(root).parts
    except (ValueError, OSError):
        return False
    return bool(parts) and parts[0] in WLC_MANAGED_SCAN_DIRS


def media_wlc_validate_id(value: str, label: str) -> str:
    """Validate a path-safe session or attempt identifier."""

    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,96}", value or ""):
        raise HTTPException(status_code=400, detail=f"{label} must be 3-96 characters of letters, numbers, dot, dash, or underscore.")
    return value


def media_wlc_session_package_dir(study_id: str, session_id: str, *, create: bool = False) -> Path:
    """Return a safe package path for one WLC capture session."""

    root = media_wlc_session_root(create=create)
    media_wlc_validate_id(session_id, "session_id")
    target = (root / study_id / session_id).resolve(strict=False)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="WLC session package path must stay under the session root.") from exc
    if create:
        target.mkdir(parents=True, exist_ok=True)
    return target


def media_wlc_session_row(session_id: str) -> dict[str, str]:
    row = media_query_one(
        "select * from v_vocera_media_capture_sessions "
        f"where session_id = {sql_text(session_id)};"
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"No WLC capture session found for {session_id}.")
    return row


def media_wlc_command_sheets(package_dir: Path) -> dict[str, str]:
    """Return generated command-sheet text for display or download."""

    out: dict[str, str] = {}
    for path in sorted(package_dir.glob("*.cli")):
        try:
            out[path.name] = path.read_text(encoding="utf-8")
        except OSError:
            continue
    return out


def media_wlc_session_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-wlc-session-" + uuid.uuid4().hex[:6]


def media_wlc_namespace(study_id: str, payload: MediaWlcCaptureSessionCreate, target: Path) -> SimpleNamespace:
    """Merge request fields with configured WLC defaults for package creation."""

    defaults = media_wlc_defaults()
    sender = defaults["sender"]
    receiver = defaults["receiver"]
    session_id = media_wlc_validate_id(payload.session_id or media_wlc_session_id(), "session_id")
    configured_vocera_vlan = payload.vocera_vlan or defaults["vocera_vlan"]
    vlan_selection_source = "operator_override" if payload.vocera_vlan is not None and payload.vocera_vlan != defaults["vocera_vlan"] else "default"
    merged = SimpleNamespace(
        session_root=str(target.parents[1]),
        study_id=study_id,
        session_id=session_id,
        site=payload.site or defaults["site"],
        wlc_name=payload.wlc_name or defaults["wlc_name"],
        capture_name=payload.capture_name or defaults["capture_name"],
        wlc_interface=payload.wlc_interface or defaults["wlc_interface"],
        capture_filter_mode=payload.capture_filter_mode or defaults["capture_filter_mode"],
        capture_mode=payload.capture_mode,
        short_validation_duration_seconds=payload.short_validation_duration_seconds or defaults["short_validation_duration_seconds"],
        collector_host=payload.collector_host or defaults["collector_host"],
        collector_scp_username=payload.collector_scp_username or defaults["collector_scp_username"],
        collector_scp_port=payload.collector_scp_port or defaults["collector_scp_port"],
        collector_scp_path=payload.collector_scp_path,
        ring_file_count=payload.ring_file_count or defaults["ring_file_count"],
        ring_file_size_mb=payload.ring_file_size_mb or defaults["ring_file_size_mb"],
        continuous_export_enabled=defaults["continuous_export_enabled"] if payload.continuous_export_enabled is None else payload.continuous_export_enabled,
        session_state="prepared_not_started",
        sender_name=payload.sender_name or sender["name"],
        sender_model=payload.sender_model or sender["model"],
        sender_mac=payload.sender_mac or sender["mac"],
        sender_ip=payload.sender_ip or sender["ip"],
        receiver_name=payload.receiver_name or receiver["name"],
        receiver_model=payload.receiver_model or receiver["model"],
        receiver_mac=payload.receiver_mac or receiver["mac"],
        receiver_ip=payload.receiver_ip or receiver["ip"],
        expected_dscp=payload.expected_dscp or defaults["expected_dscp"],
        vocera_vlan=configured_vocera_vlan,
        resolved_group_ip=None,
        resolved_group_vlan=None,
        resolved_mgid=None,
        resolved_at=None,
        vlan_selection_source=vlan_selection_source,
        vocera_multicast_pool=payload.vocera_multicast_pool or defaults["vocera_multicast_pool"],
        vocera_first_usable=payload.vocera_first_usable or defaults["vocera_first_usable"],
        vocera_last_usable=payload.vocera_last_usable or defaults["vocera_last_usable"],
        operator=user(),
        created_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        notes=payload.notes,
        force=True,
    )
    missing = [
        name
        for name in ("wlc_name", "wlc_interface", "collector_host", "collector_scp_username", "sender_mac", "sender_ip", "receiver_mac", "receiver_ip")
        if not getattr(merged, name)
    ]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing WLC session defaults or request fields: {', '.join(missing)}")
    return merged


def media_wlc_insert_session(session: Mapping[str, Any]) -> dict[str, str]:
    """Upsert one capture-session DB row."""

    sender = session.get("sender") if isinstance(session.get("sender"), dict) else {}
    receiver = session.get("receiver") if isinstance(session.get("receiver"), dict) else {}
    expected = session.get("expected") if isinstance(session.get("expected"), dict) else {}
    return media_query_one(
        "insert into vocera_media_capture_sessions ("
        "session_id, study_id, site, wlc_name, capture_method, capture_name, wlc_interface, capture_filter_mode, "
        "capture_mode, collector_host, collector_scp_username, collector_scp_port, collector_scp_path, "
        "ring_file_count, ring_file_size_mb, ring_total_size_mb, continuous_export_enabled, session_state, "
        "sender_name, sender_model, sender_mac, sender_ip, receiver_name, receiver_model, receiver_mac, receiver_ip, "
        "expected_dscp, configured_vocera_vlan, resolved_group_ip, resolved_group_vlan, resolved_mgid, resolved_at, "
        "vlan_selection_source, vlan_context_state, vocera_multicast_pool, vocera_first_usable, vocera_last_usable, expected_mac_start, expected_mac_end, "
        "command_package_path, created_by, raw_context, updated_at"
        ") values ("
        f"{sql_text(session.get('session_id'))}, {sql_text(session.get('study_id'))}, {sql_text(session.get('site'))}, "
        f"{sql_text(session.get('wlc_name'))}, {sql_text(session.get('capture_method'))}, {sql_text(session.get('capture_name'))}, "
        f"{sql_text(session.get('wlc_interface'))}, {sql_text(session.get('capture_filter_mode'))}, {sql_text(session.get('capture_mode'))}, "
        f"{sql_text(session.get('collector_host'))}, {sql_text(session.get('collector_scp_username'))}, {sql_int(session.get('collector_scp_port'))}, "
        f"{sql_text(session.get('collector_scp_path'))}, {sql_int(session.get('ring_file_count'))}, {sql_int(session.get('ring_file_size_mb'))}, "
        f"{sql_int(session.get('ring_total_size_mb'))}, {sql_bool(bool(session.get('continuous_export_enabled')))}, {sql_text(session.get('session_state'))}, "
        f"{sql_text(sender.get('name'))}, {sql_text(sender.get('model'))}, {sql_text(sender.get('mac'))}, {sql_text(sender.get('ip'))}, "
        f"{sql_text(receiver.get('name'))}, {sql_text(receiver.get('model'))}, {sql_text(receiver.get('mac'))}, {sql_text(receiver.get('ip'))}, "
        f"{sql_int(expected.get('expected_dscp'))}, {sql_int(session.get('configured_vocera_vlan') or expected.get('configured_vocera_vlan') or expected.get('vocera_vlan') or 684)}, "
        f"{sql_text(session.get('resolved_group_ip'))}, {sql_int(session.get('resolved_group_vlan'))}, {sql_int(session.get('resolved_mgid'))}, "
        f"{sql_text(session.get('resolved_at'))}, {sql_text(session.get('vlan_selection_source') or 'default')}, {sql_text(session.get('vlan_context_state') or 'configured_only')}, "
        f"{sql_text(expected.get('vocera_multicast_pool'))}, {sql_text(expected.get('vocera_first_usable'))}, "
        f"{sql_text(expected.get('vocera_last_usable'))}, {sql_text(expected.get('expected_mac_start'))}, {sql_text(expected.get('expected_mac_end'))}, "
        f"{sql_text(session.get('package_path'))}, {sql_text(session.get('created_by'))}, {media_jsonb(session)}, now()"
        ") on conflict (session_id) do update set "
        "session_state = excluded.session_state, updated_at = now(), raw_context = excluded.raw_context "
        "returning session_id;"
    )


def media_wlc_update_session(session_id: str, payload: MediaWlcCaptureSessionPatch) -> dict[str, str]:
    """Patch state/timestamps for a capture session."""

    media_wlc_session_row(session_id)
    # Active multicast-group resolution is attempt-scoped evidence and must never be
    # written at the capture-session level. The resolved_* columns on
    # vocera_media_capture_sessions are retained only for backward compatibility with
    # legacy rows; reject writes here so they cannot become a second source of truth.
    # Resolution belongs on the broadcast attempt (media_wlc_set_active_group /
    # PATCH /api/media-qoe/wlc/attempts/{attempt_id}/active-group).
    multicast, _ = media_wlc_imports()
    try:
        multicast.reject_session_level_resolution(
            resolved_group_ip=payload.resolved_group_ip,
            resolved_group_vlan=payload.resolved_group_vlan,
            resolved_mgid=payload.resolved_mgid,
            resolved_at=payload.resolved_at,
        )
    except multicast.SessionResolutionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    assignments: list[str] = []
    if payload.session_state is not None:
        assignments.append(f"session_state = {sql_text(payload.session_state)}")
    if payload.capture_started_at is not None:
        assignments.append(f"capture_started_at = {sql_timestamp(payload.capture_started_at)}")
    if payload.capture_stopped_at is not None:
        assignments.append(f"capture_stopped_at = {sql_timestamp(payload.capture_stopped_at)}")
    if payload.vlan_selection_source is not None:
        assignments.append(f"vlan_selection_source = {sql_text(payload.vlan_selection_source)}")
    raw_context_expr = "coalesce(raw_context, '{}'::jsonb)"
    if payload.notes is not None:
        raw_context_expr = f"jsonb_set({raw_context_expr}, '{{notes}}', to_jsonb({sql_text(payload.notes)}::text), true)"
    if payload.vlan_override_reason is not None:
        raw_context_expr = (
            f"jsonb_set({raw_context_expr}, '{{vlan_override_reason}}', "
            f"to_jsonb({sql_text(payload.vlan_override_reason)}::text), true)"
        )
    if payload.notes is not None or payload.vlan_override_reason is not None:
        assignments.append(f"raw_context = {raw_context_expr}")
    if not assignments:
        return media_wlc_session_row(session_id)
    assignments.append("updated_at = now()")
    media_query_one(
        "update vocera_media_capture_sessions set "
        + ", ".join(assignments)
        + f" where session_id = {sql_text(session_id)} returning session_id;"
    )
    return media_wlc_session_row(session_id)


def media_wlc_new_attempt_id(session_id: str) -> str:
    """Return a fresh attempt identifier scoped to a capture session."""

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{session_id}-attempt-{stamp}-{uuid.uuid4().hex[:6]}"[:96]


def media_wlc_attempt_row(attempt_id: str) -> dict[str, Any]:
    """Return one broadcast attempt row or raise 404."""

    row = media_query_one(
        "select * from v_vocera_media_broadcast_attempts "
        f"where attempt_id = {sql_text(attempt_id)};"
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"No broadcast attempt found for {attempt_id}.")
    return row


def media_wlc_open_attempt(session_id: str) -> dict[str, Any] | None:
    """Return the single open attempt for a capture session, if any exists."""

    rows = media_query_rows(
        "select * from vocera_media_broadcast_attempts "
        f"where capture_session_id = {sql_text(session_id)} and attempt_state = 'open' "
        "order by attempt_started_at desc nulls last, created_at desc limit 1;"
    )
    return rows[0] if rows else None


def media_wlc_event_context(payload: BaseModel) -> dict[str, Any]:
    """Return a JSON-safe event payload for raw_context."""

    context = model_data(payload)
    for key in ("event_time", "browser_event_time", "started_at", "ended_at", "selected_at"):
        if isinstance(context.get(key), datetime):
            context[key] = context[key].isoformat()
    return context


def media_wlc_outcome_verdict(event_kind: str) -> tuple[str, str, str]:
    """Return (verdict, confidence, explanation) for an attempt outcome kind."""

    if event_kind == "heard":
        return (
            "baseline_success",
            "medium",
            "Operator marked this broadcast as heard; use it as baseline evidence for the same capture session.",
        )
    if event_kind == "alert_only":
        return ("alert_only_failure", "medium", "Operator marked alert received but audio not heard.")
    return (
        "inconclusive",
        "low",
        "Attempt outcome recorded during a long-running WLC capture session; evidence analysis is pending.",
    )


def media_wlc_insert_open_attempt(
    session: Mapping[str, Any], attempt_id: str, started_at: datetime, operator: str, notes: str | None
) -> None:
    """Insert one open broadcast attempt. The DB enforces one open per session."""

    media_query_one(
        "insert into vocera_media_broadcast_attempts ("
        "attempt_id, study_id, capture_session_id, site, wlc_name, started_at, attempt_started_at, attempt_state, "
        "sender_name, sender_model, sender_mac, sender_ip, receiver_name, receiver_model, receiver_mac, receiver_ip, "
        "configured_vocera_vlan, operator_name, capture_window_before_seconds, capture_window_after_seconds, "
        "operator_notes, verdict, verdict_confidence, verdict_explanation, raw_context, updated_at"
        ") values ("
        f"{sql_text(attempt_id)}, {sql_text(session.get('study_id'))}, {sql_text(session['session_id'])}, {sql_text(session.get('site'))}, "
        f"{sql_text(session.get('wlc_name'))}, {sql_timestamp(started_at)}, {sql_timestamp(started_at)}, 'open', "
        f"{sql_text(session.get('sender_name'))}, {sql_text(session.get('sender_model'))}, {sql_text(session.get('sender_mac'))}, {sql_text(session.get('sender_ip'))}, "
        f"{sql_text(session.get('receiver_name'))}, {sql_text(session.get('receiver_model'))}, {sql_text(session.get('receiver_mac'))}, {sql_text(session.get('receiver_ip'))}, "
        f"{sql_int(session.get('configured_vocera_vlan') or 684)}, {sql_text(operator)}, 30, 30, "
        f"{sql_text(notes)}, 'inconclusive', 'low', {sql_text('Attempt opened; awaiting outcome and active-group evidence.')}, "
        f"{media_jsonb({'lifecycle': 'open'})}, now()"
        ") on conflict (attempt_id) do nothing;"
    )


def media_wlc_close_attempt(
    session: Mapping[str, Any],
    attempt_id: str,
    *,
    event_time: datetime,
    audio_result: str | None,
    alert_received: bool | None,
    audio_received: bool | None,
    marker_type: str | None,
    operator: str,
    notes: str | None,
    raw_context: Mapping[str, Any],
) -> None:
    """Insert or update one attempt as completed, attaching the outcome.

    ``attempt_started_at``/``started_at`` are never overwritten on conflict so an
    outcome closes the existing open attempt instead of resetting its start time.
    """

    verdict, confidence, explanation = media_wlc_outcome_verdict(str(marker_type or audio_result or ""))
    media_query_one(
        "insert into vocera_media_broadcast_attempts ("
        "attempt_id, study_id, capture_session_id, site, wlc_name, started_at, ended_at, attempt_started_at, "
        "attempt_marked_at, attempt_ended_at, attempt_state, sender_name, sender_model, sender_mac, sender_ip, "
        "receiver_name, receiver_model, receiver_mac, receiver_ip, configured_vocera_vlan, operator_name, audio_result, "
        "alert_result, alert_received, audio_received, failure_marker_type, capture_window_before_seconds, "
        "capture_window_after_seconds, operator_notes, verdict, verdict_confidence, verdict_explanation, raw_context, updated_at"
        ") values ("
        f"{sql_text(attempt_id)}, {sql_text(session.get('study_id'))}, {sql_text(session['session_id'])}, {sql_text(session.get('site'))}, "
        f"{sql_text(session.get('wlc_name'))}, {sql_timestamp(event_time)}, {sql_timestamp(event_time)}, {sql_timestamp(event_time)}, "
        f"{sql_timestamp(event_time)}, {sql_timestamp(event_time)}, 'completed', {sql_text(session.get('sender_name'))}, {sql_text(session.get('sender_model'))}, "
        f"{sql_text(session.get('sender_mac'))}, {sql_text(session.get('sender_ip'))}, {sql_text(session.get('receiver_name'))}, "
        f"{sql_text(session.get('receiver_model'))}, {sql_text(session.get('receiver_mac'))}, {sql_text(session.get('receiver_ip'))}, "
        f"{sql_int(session.get('configured_vocera_vlan') or 684)}, {sql_text(operator)}, {sql_text(audio_result)}, "
        f"{sql_bool(alert_received)}, {sql_bool(alert_received)}, {sql_bool(audio_received)}, {sql_text(marker_type)}, 30, 30, "
        f"{sql_text(notes)}, {sql_text(verdict)}, {sql_text(confidence)}, {sql_text(explanation)}, {media_jsonb(raw_context)}, now()"
        ") on conflict (attempt_id) do update set "
        "attempt_marked_at = excluded.attempt_marked_at, attempt_ended_at = excluded.attempt_ended_at, "
        "attempt_state = 'completed', ended_at = excluded.ended_at, audio_result = excluded.audio_result, "
        "alert_result = excluded.alert_result, alert_received = excluded.alert_received, "
        "audio_received = excluded.audio_received, failure_marker_type = excluded.failure_marker_type, "
        "verdict = excluded.verdict, verdict_confidence = excluded.verdict_confidence, "
        "verdict_explanation = excluded.verdict_explanation, operator_notes = excluded.operator_notes, updated_at = now() "
        "returning attempt_id;"
    )


def media_wlc_write_session_event(
    session: Mapping[str, Any],
    *,
    attempt_id: str | None,
    event_kind: str,
    event_time: datetime,
    browser_event_time: datetime | None,
    operator: str,
    audio_result: str | None,
    alert_received: bool | None,
    audio_received: bool | None,
    notes: str | None,
    raw_context: Mapping[str, Any],
) -> dict[str, Any]:
    """Append one immutable capture-session event and return the stored row."""

    event_id = new_entity_id("wlc_evt")
    media_query_one(
        "insert into vocera_media_capture_session_events ("
        "event_id, capture_session_id, study_id, attempt_id, event_kind, event_time, browser_event_time, "
        "operator_name, audio_result, alert_received, audio_received, notes, raw_context"
        ") values ("
        f"{sql_text(event_id)}, {sql_text(session['session_id'])}, {sql_text(session.get('study_id'))}, {sql_text(attempt_id)}, "
        f"{sql_text(event_kind)}, {sql_timestamp(event_time)}, {sql_timestamp(browser_event_time)}, "
        f"{sql_text(operator)}, {sql_text(audio_result)}, {sql_bool(alert_received)}, {sql_bool(audio_received)}, "
        f"{sql_text(notes)}, {media_jsonb(raw_context)}"
        ") returning event_id;"
    )
    return media_query_one(
        "select * from v_vocera_media_capture_session_events "
        f"where event_id = {sql_text(event_id)};"
    )


def media_wlc_normalize_outcome(
    event_kind: str, audio_result: str | None, alert_received: bool | None, audio_received: bool | None
) -> tuple[str | None, bool | None, bool | None]:
    """Derive audio_result/alert/audio defaults for an outcome event kind."""

    if event_kind in {"heard", "missed", "partial", "choppy"}:
        audio_result = audio_result or event_kind
    elif event_kind == "alert_only":
        audio_result = audio_result or "missed"
        alert_received = True if alert_received is None else alert_received
        audio_received = False if audio_received is None else audio_received
    if event_kind == "heard":
        alert_received = True if alert_received is None else alert_received
        audio_received = True if audio_received is None else audio_received
    elif event_kind == "missed":
        audio_received = False if audio_received is None else audio_received
    return audio_result, alert_received, audio_received


def media_wlc_insert_event(session: Mapping[str, str], payload: MediaWlcSessionEventCreate) -> dict[str, Any]:
    """Record one operator event, maintaining the one-attempt-per-broadcast model.

    ``broadcast_started`` opens a single attempt (reusing any already-open one);
    an outcome event closes that same open attempt rather than forking a new row.
    """

    event_time = payload.event_time or datetime.now(timezone.utc)
    event_kind = payload.event_kind
    session_id = str(session["session_id"])
    outcome_kinds = {"heard", "missed", "partial", "choppy", "alert_only"}
    operator = payload.operator_name or user()
    attempt_id = payload.attempt_id
    audio_result = payload.audio_result
    alert_received = payload.alert_received
    audio_received = payload.audio_received
    raw_context = media_wlc_event_context(payload)

    if event_kind == "broadcast_started":
        existing = media_wlc_open_attempt(session_id)
        if attempt_id is None and existing is not None:
            attempt_id = str(existing.get("attempt_id"))
        elif attempt_id is None:
            attempt_id = media_wlc_new_attempt_id(session_id)
        if existing is None or attempt_id != str(existing.get("attempt_id")):
            media_wlc_insert_open_attempt(session, attempt_id, event_time, operator, payload.notes)
        audio_result = audio_result or "unknown"
    elif event_kind in outcome_kinds:
        audio_result, alert_received, audio_received = media_wlc_normalize_outcome(
            event_kind, audio_result, alert_received, audio_received
        )
        if attempt_id is None:
            existing = media_wlc_open_attempt(session_id)
            attempt_id = str(existing.get("attempt_id")) if existing else media_wlc_new_attempt_id(session_id)
        marker_type = event_kind if event_kind in {"missed", "partial", "choppy", "alert_only"} else None
        media_wlc_close_attempt(
            session,
            attempt_id,
            event_time=event_time,
            audio_result=audio_result,
            alert_received=alert_received,
            audio_received=audio_received,
            marker_type=marker_type,
            operator=operator,
            notes=payload.notes,
            raw_context=raw_context,
        )

    event = media_wlc_write_session_event(
        session,
        attempt_id=attempt_id,
        event_kind=event_kind,
        event_time=event_time,
        browser_event_time=payload.browser_event_time,
        operator=operator,
        audio_result=audio_result,
        alert_received=alert_received,
        audio_received=audio_received,
        notes=payload.notes,
        raw_context=raw_context,
    )
    if event_kind == "session_end":
        media_wlc_update_session(session_id, MediaWlcCaptureSessionPatch(session_state="stopped", capture_stopped_at=event_time))
    return {"event": event, "attempt_id": attempt_id}


def media_wlc_start_attempt(session: Mapping[str, Any], payload: MediaWlcAttemptStart) -> dict[str, Any]:
    """Open exactly one broadcast attempt for a capture session."""

    session_id = str(session["session_id"])
    if not payload.attempt_id:
        existing = media_wlc_open_attempt(session_id)
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Capture session {session_id} already has an open attempt "
                    f"({existing.get('attempt_id')}). Record its outcome before starting another."
                ),
            )
    started_at = payload.started_at or datetime.now(timezone.utc)
    operator = payload.operator_name or user()
    attempt_id = (
        media_wlc_validate_id(payload.attempt_id, "attempt_id")
        if payload.attempt_id
        else media_wlc_new_attempt_id(session_id)
    )
    media_wlc_insert_open_attempt(session, attempt_id, started_at, operator, payload.notes)
    media_wlc_write_session_event(
        session,
        attempt_id=attempt_id,
        event_kind="broadcast_started",
        event_time=started_at,
        browser_event_time=payload.browser_event_time,
        operator=operator,
        audio_result=None,
        alert_received=None,
        audio_received=None,
        notes=payload.notes,
        raw_context=media_wlc_event_context(payload),
    )
    return media_wlc_attempt_row(attempt_id)


def media_wlc_set_outcome(attempt_id: str, payload: MediaWlcAttemptOutcome) -> dict[str, Any]:
    """Record an audio outcome for an attempt and close it."""

    attempt = media_wlc_attempt_row(attempt_id)
    session_id = str(attempt.get("capture_session_id") or "")
    session = media_wlc_session_row(session_id) if session_id else attempt
    ended_at = payload.ended_at or datetime.now(timezone.utc)
    operator = payload.operator_name or user()
    event_kind = payload.audio_result
    audio_result, alert_received, audio_received = media_wlc_normalize_outcome(
        event_kind, payload.audio_result if event_kind != "alert_only" else None, payload.alert_received, payload.audio_received
    )
    marker_type = event_kind if event_kind in {"missed", "partial", "choppy", "alert_only"} else None
    raw_context = media_wlc_event_context(payload)
    media_wlc_close_attempt(
        session,
        attempt_id,
        event_time=ended_at,
        audio_result=audio_result,
        alert_received=alert_received,
        audio_received=audio_received,
        marker_type=marker_type,
        operator=operator,
        notes=payload.notes,
        raw_context=raw_context,
    )
    media_wlc_write_session_event(
        session,
        attempt_id=attempt_id,
        event_kind=event_kind,
        event_time=ended_at,
        browser_event_time=payload.browser_event_time,
        operator=operator,
        audio_result=audio_result,
        alert_received=alert_received,
        audio_received=audio_received,
        notes=payload.notes,
        raw_context=raw_context,
    )
    return media_wlc_attempt_row(attempt_id)


def media_wlc_selected_summary_row(group_summary_raw: str | None, group_ip: str) -> str | None:
    """Return the raw group-summary line that names the selected group, if present."""

    if not group_summary_raw:
        return None
    for line in group_summary_raw.splitlines():
        if group_ip in line:
            return line.strip()
    return None


def media_wlc_write_active_group_artifacts(
    attempt: Mapping[str, Any],
    payload: MediaWlcAttemptActiveGroup,
    *,
    selection_source: str,
    override_reason: str | None,
    selected_row: str | None,
    selected_at: datetime,
    configured_vlan: int,
) -> None:
    """Rewrite the per-attempt resolved-group command sheet and evidence files.

    Best-effort: the canonical record is in PostgreSQL, so a missing package
    directory or file error must never fail the resolution request.
    """

    _, wlc_session = media_wlc_imports()
    study_id = attempt.get("study_id")
    session_id = attempt.get("capture_session_id")
    if not (study_id and session_id):
        return
    try:
        package_dir = media_wlc_session_package_dir(str(study_id), str(session_id), create=False)
    except HTTPException:
        return
    if not package_dir.is_dir():
        return
    attempt_id = str(attempt["attempt_id"])
    capture_name = attempt.get("capture_name") or "VOCERA_BCAST"
    try:
        sheet = wlc_session.render_resolved_active_group(
            capture_name, configured_vlan, payload.group_ip, payload.group_vlan, attempt_id=attempt_id
        )
        wlc_session.write_text(package_dir / "cli" / f"attempt-{attempt_id}-resolved-group.cli", sheet, overwrite=True)
        if payload.group_summary_raw and payload.group_summary_raw.strip():
            wlc_session.write_text(
                package_dir / "cli" / f"attempt-{attempt_id}-active-group-summary.txt",
                payload.group_summary_raw,
                overwrite=True,
            )
        selection = {
            "attempt_id": attempt_id,
            "session_id": str(session_id),
            "group_ip": payload.group_ip,
            "group_vlan": payload.group_vlan,
            "mgid": payload.mgid,
            "configured_vocera_vlan": configured_vlan,
            "selection_source": selection_source,
            "vlan_override_reason": override_reason,
            "selected_row": selected_row,
            "selected_at": selected_at.isoformat(),
            "operator": payload.operator_name or user(),
        }
        wlc_session.write_json(
            package_dir / "notes" / f"attempt-{attempt_id}-group-selection.json", selection, overwrite=True
        )
    except OSError:
        return


def media_wlc_set_active_group(attempt_id: str, payload: MediaWlcAttemptActiveGroup) -> dict[str, Any]:
    """Attach the live dynamic Vocera group to one attempt with VLAN enforcement."""

    multicast, _ = media_wlc_imports()
    attempt = media_wlc_attempt_row(attempt_id)
    configured_vlan = int(attempt.get("configured_vocera_vlan") or 684)
    try:
        selection_source = multicast.enforce_vlan_selection(
            configured_vlan,
            payload.group_vlan,
            selection_source=payload.selection_source,
            override_reason=payload.vlan_override_reason,
        )
    except multicast.VlanSelectionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    selected_at = payload.selected_at or datetime.now(timezone.utc)
    reason = (payload.vlan_override_reason or "").strip() or None
    vlan_context_state = "resolved_confirmed" if int(payload.group_vlan) == configured_vlan else "configured_group_mismatch"
    selected_row = payload.selected_row or media_wlc_selected_summary_row(payload.group_summary_raw, payload.group_ip)
    media_query_one(
        "update vocera_media_broadcast_attempts set "
        f"resolved_group_ip = {sql_text(payload.group_ip)}, resolved_group_vlan = {sql_int(payload.group_vlan)}, "
        f"resolved_mgid = {sql_int(payload.mgid)}, dynamic_multicast_ip = {sql_text(payload.group_ip)}, "
        f"group_selection_source = {sql_text(selection_source)}, vlan_selection_source = {sql_text(selection_source)}, "
        f"vlan_override_reason = {sql_text(reason)}, active_group_selected_at = {sql_timestamp(selected_at)}, "
        f"multicast_group_detected_at = coalesce(multicast_group_detected_at, {sql_timestamp(selected_at)}), "
        f"vlan_context_state = {sql_text(vlan_context_state)}, active_group_summary_raw = {sql_text(payload.group_summary_raw)}, "
        f"active_group_selected_row = {sql_text(selected_row)}, updated_at = now() "
        f"where attempt_id = {sql_text(attempt_id)} returning attempt_id;"
    )
    media_wlc_write_active_group_artifacts(
        attempt,
        payload,
        selection_source=selection_source,
        override_reason=reason,
        selected_row=selected_row,
        selected_at=selected_at,
        configured_vlan=configured_vlan,
    )
    return media_wlc_attempt_row(attempt_id)


def media_dnac_imports() -> tuple[Any, Any]:
    """Load the existing DNAC ICAP helper and Catalyst Center client on demand."""

    for path in (ROOT / "tools" / "vocera_media_qoe", ROOT / "tools" / "wireless_rf"):
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)
    try:
        import vocera_dnac_icap as icap  # type: ignore[import-not-found]
        from wireless_rf.dnac_client import CatalystCenterIcapReadClient  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - depends on operator environment
        raise RuntimeError(f"Catalyst Center ICAP helpers are not importable: {exc}") from exc
    return icap, CatalystCenterIcapReadClient


def media_dnac_env_file() -> str:
    return (
        os.environ.get("STUDY_WEB_MEDIA_QOE_DNAC_ENV_FILE")
        or os.environ.get("VOCERA_MEDIA_QOE_ENV_FILE")
        or "/etc/grafana-mimir-observability/secrets/dnac-readonly.env"
    )


def media_dnac_env_value(name: str, env_file_values: Mapping[str, str]) -> str | None:
    value = os.environ.get(name)
    if value not in (None, ""):
        return value
    file_value = env_file_values.get(name)
    return file_value if file_value not in (None, "") else None


def media_dnac_env_int(name: str, env_file_values: Mapping[str, str], default: int, *, minimum: int = 0, maximum: int | None = None) -> int:
    raw = media_dnac_env_value(name, env_file_values)
    try:
        value = int(raw) if raw not in (None, "") else default
    except ValueError:
        value = default
    value = max(value, minimum)
    return min(value, maximum) if maximum is not None else value


def media_dnac_env_bool(name: str, env_file_values: Mapping[str, str], default: bool) -> bool:
    raw = media_dnac_env_value(name, env_file_values)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def media_dnac_soft_raw_dir() -> Path:
    configured = os.environ.get("STUDY_WEB_MEDIA_QOE_RAW_DIR", "/var/lib/vocera-media-qoe/raw").strip()
    path = Path(configured or "/var/lib/vocera-media-qoe/raw").expanduser()
    try:
        return path.resolve(strict=False)
    except OSError:
        return path


def media_dnac_config(query: MediaDnacCaptureQuery | None = None) -> dict[str, Any]:
    icap, client_class = media_dnac_imports()
    env_file = media_dnac_env_file()
    env_file_values = icap.load_env_file(env_file)
    base_url = media_dnac_env_value("DNAC_BASE_URL", env_file_values)
    username = media_dnac_env_value("DNAC_USERNAME", env_file_values)
    credential_name = "DNAC_" + "PASSWORD"
    credential = media_dnac_env_value(credential_name, env_file_values)
    default_client_mac = media_dnac_env_value("VOCERA_MEDIA_QOE_DNAC_CLIENT_MAC", env_file_values)
    default_ap_mac = media_dnac_env_value("VOCERA_MEDIA_QOE_DNAC_AP_MAC", env_file_values)
    default_capture_type = media_dnac_env_value("VOCERA_MEDIA_QOE_DNAC_CAPTURE_TYPE", env_file_values) or "FULL"
    verify_tls = media_dnac_env_bool("DNAC_VERIFY_TLS", env_file_values, True)
    if media_dnac_env_bool("VOCERA_MEDIA_QOE_DNAC_INSECURE", env_file_values, False):
        verify_tls = False

    raw_dir = media_dnac_soft_raw_dir()
    requested_client_mac = query.client_mac if query and query.client_mac else default_client_mac
    requested_ap_mac = query.ap_mac if query and query.ap_mac else default_ap_mac
    capture_type = (query.capture_type if query and query.capture_type else default_capture_type).strip().upper()
    lookback_minutes = query.lookback_minutes if query and query.lookback_minutes is not None else media_dnac_env_int("VOCERA_MEDIA_QOE_DNAC_LOOKBACK_MINUTES", env_file_values, 0, minimum=0)
    limit = query.limit if query and query.limit is not None else media_dnac_env_int("VOCERA_MEDIA_QOE_DNAC_LIMIT", env_file_values, 20, minimum=1, maximum=100)
    offset = query.offset if query else 1
    missing = [
        name for name, value in (
            ("DNAC_BASE_URL", base_url),
            ("DNAC_USERNAME", username),
            (credential_name, credential),
        ) if not value
    ]
    return {
        "icap": icap,
        "client_class": client_class,
        "env_file": env_file,
        "base_url": base_url,
        "username": username,
        "credential": credential,
        "configured": not missing,
        "missing_config": missing,
        "client_mac": requested_client_mac,
        "ap_mac": requested_ap_mac,
        "default_client_mac": default_client_mac,
        "default_ap_mac": default_ap_mac,
        "capture_type": capture_type or "FULL",
        "lookback_minutes": lookback_minutes,
        "limit": limit,
        "offset": offset,
        "verify_tls": verify_tls,
        "start_capture_available": False,
        "start_capture_unavailable_reason": "ICAP start-capture is intentionally unavailable",
        "download_enabled": media_dnac_env_bool("STUDY_WEB_MEDIA_QOE_DNAC_DOWNLOAD_ENABLED", env_file_values, True),
        "raw_dir": raw_dir,
        "raw_dir_exists": raw_dir.exists(),
        "raw_dir_readable": raw_dir.exists() and raw_dir.is_dir() and os.access(raw_dir, os.R_OK),
    }


def media_dnac_client(config: Mapping[str, Any]) -> Any:
    client_class = config["client_class"]
    kwargs = {
        "base_url": str(config["base_url"]),
        "username": str(config["username"]),
        "verify_tls": bool(config["verify_tls"]),
    }
    kwargs["pass" + "word"] = str(config["credential"])
    return client_class(**kwargs)


def media_dnac_error(exc: Exception) -> str:
    return str(exc)[:1200]


def media_dnac_normalize_mac(icap: Any, value: str | None, label: str) -> str | None:
    if not value:
        return None
    try:
        return icap.normalize_mac(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {label}: {value}") from exc


def media_dnac_time_filters(lookback_minutes: int) -> tuple[int | None, int | None]:
    if lookback_minutes <= 0:
        return None, None
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    return end_ms - (lookback_minutes * 60 * 1000), end_ms


def media_dnac_timestamp(capture: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = capture.get(key)
        if value in (None, ""):
            continue
        try:
            timestamp_ms = int(float(value))
        except (TypeError, ValueError):
            continue
        if timestamp_ms <= 0:
            continue
        return datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc).isoformat()
    return None


def media_dnac_capture_value(capture: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = capture.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def media_dnac_registered_by_path(study_id: str, source_paths: list[str]) -> dict[str, dict[str, str]]:
    if not source_paths:
        return {}
    rows = media_query_rows(
        "select * from v_vocera_media_qoe_study_captures "
        f"where source_path in ({', '.join(sql_text(path) for path in source_paths)});"
    )
    preferred: dict[str, dict[str, str]] = {}
    for row in rows:
        source_path = row.get("source_path") or ""
        if not source_path:
            continue
        if source_path not in preferred or row.get("study_id") == study_id:
            preferred[source_path] = row
    return preferred


def media_dnac_capture_local_path(config: Mapping[str, Any], capture: Mapping[str, Any]) -> str:
    icap = config["icap"]
    client_mac = str(config["client_mac"] or "")
    capture_type = str(config["capture_type"] or "FULL")
    raw_dir = config["raw_dir"]
    try:
        local_name = icap.capture_filename(capture, client_mac=client_mac, capture_type=capture_type)
    except Exception:
        local_name = media_dnac_capture_value(capture, "fileName", "name", "id") or "capture.pcap"
    return str(raw_dir / local_name)


def media_dnac_capture_matches(capture: Mapping[str, Any], capture_id: str | None, file_name: str | None) -> bool:
    wanted = {str(value).strip() for value in (capture_id, file_name) if value not in (None, "")}
    if not wanted:
        return False
    for key in ("id", "fileName", "name"):
        value = capture.get(key)
        if value not in (None, "") and str(value).strip() in wanted:
            return True
    return False


def media_dnac_select_capture(icap: Any, captures: list[dict[str, Any]], payload: MediaDnacCaptureDownload) -> dict[str, Any]:
    if payload.capture_id or payload.file_name:
        for capture in captures:
            if media_dnac_capture_matches(capture, payload.capture_id, payload.file_name):
                return capture
        raise HTTPException(status_code=404, detail="Selected DNAC ICAP capture was not found in the completed capture list.")
    selected = icap.select_latest_capture(captures)
    if not selected:
        raise HTTPException(status_code=404, detail="No completed DNAC ICAP captures matched this search.")
    return selected


def media_dnac_download_path(config: Mapping[str, Any], capture: Mapping[str, Any]) -> Path:
    root = media_raw_dir()
    if not os.access(root, os.W_OK):
        raise HTTPException(status_code=403, detail=f"Raw capture directory is not writable: {root}")
    scoped = dict(config)
    scoped["raw_dir"] = root
    local_path = Path(media_dnac_capture_local_path(scoped, capture)).resolve(strict=False)
    try:
        local_path.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Resolved DNAC capture path must stay under STUDY_WEB_MEDIA_QOE_RAW_DIR.") from exc
    if local_path.suffix.lower() not in media_allowed_extensions():
        raise HTTPException(status_code=400, detail=f"DNAC capture resolved to unsupported extension: {local_path.suffix or '<none>'}.")
    return local_path


def media_dnac_capture_item(config: Mapping[str, Any], capture: Mapping[str, Any], registered: Mapping[str, dict[str, str]]) -> dict[str, Any]:
    icap = config["icap"]
    capture_type = str(config["capture_type"] or "FULL")
    local_path = media_dnac_capture_local_path(config, capture)
    row = registered.get(local_path)
    study_match = row and row.get("study_id") == config.get("study_id")
    capture_status = row.get("capture_status") if row else None
    stream_count = row.get("stream_count") if row else None
    rtp_qoe_stream_count = row.get("rtp_qoe_stream_count") if row else None
    parse_success = row.get("parse_success") if row else None
    return {
        "dnac_capture_id": media_dnac_capture_value(capture, "id", "fileName", "name"),
        "file_name": media_dnac_capture_value(capture, "fileName", "name", "id") or Path(local_path).name,
        "file_size": icap.capture_file_size(capture),
        "created_at": media_dnac_timestamp(capture, "fileCreationTimestamp", "createdTime", "startTime", "timestamp"),
        "updated_at": media_dnac_timestamp(capture, "lastUpdatedTimestamp", "updatedTime", "endTime"),
        "client_mac": media_dnac_capture_value(capture, "clientMac") or config.get("client_mac"),
        "ap_mac": media_dnac_capture_value(capture, "apMac") or config.get("ap_mac"),
        "capture_type": media_dnac_capture_value(capture, "type", "captureType") or capture_type,
        "local_path": local_path,
        "already_downloaded": Path(local_path).is_file(),
        "already_registered": bool(study_match),
        "registered_in_other_study": bool(row and row.get("study_id") != config.get("study_id")),
        "already_parsed": bool(study_match and (capture_status == "complete" or int(stream_count or 0) > 0)),
        "registered_capture_id": row.get("capture_id") if row else None,
        "capture_status": capture_status,
        "parse_success": parse_success,
        "stream_count": stream_count,
        "rtp_qoe_stream_count": rtp_qoe_stream_count,
        "dscp_mismatch_stream_count": row.get("dscp_mismatch_stream_count") if row else None,
        "trusted_rtp_dscp_mismatch_stream_count": row.get("trusted_rtp_dscp_mismatch_stream_count") if row else None,
        "non_rtp_dscp_mismatch_stream_count": row.get("non_rtp_dscp_mismatch_stream_count") if row else None,
        "lossy_stream_count": row.get("lossy_stream_count") if row else None,
        "jitter_p95_ms": row.get("jitter_p95_ms") if row else None,
        "loss_p95_ratio": row.get("loss_p95_ratio") if row else None,
        "interarrival_p95_ms": row.get("interarrival_p95_ms") if row else None,
    }


def media_dnac_base_status(config: Mapping[str, Any]) -> dict[str, Any]:
    raw_dir = config["raw_dir"]
    return {
        "ok": True,
        "configured": bool(config["configured"]),
        "base_url_configured": bool(config["base_url"]),
        "username_configured": bool(config["username"]),
        "password_configured": bool(config["credential"]),
        "tls_verify": bool(config["verify_tls"]),
        "raw_dir": str(raw_dir),
        "raw_dir_exists": bool(config["raw_dir_exists"]),
        "raw_dir_readable": bool(config["raw_dir_readable"]),
        "default_client_mac": config.get("default_client_mac"),
        "default_ap_mac": config.get("default_ap_mac"),
        "default_capture_type": config.get("capture_type"),
        "lookback_minutes": config.get("lookback_minutes"),
        "limit": config.get("limit"),
        "start_capture_available": bool(config["start_capture_available"]),
        "start_capture_unavailable_reason": config["start_capture_unavailable_reason"],
        "download_enabled": bool(config["download_enabled"]),
        "missing_config": list(config["missing_config"]),
        "auth_ok": None,
        "client_detail_ok": None,
        "capture_files_api_ok": None,
        "capture_files_returned": None,
        "resolved": None,
        "error_summary": None,
    }


def media_scan_raw_files(study_id: str, *, include_registered: bool, limit: int) -> list[dict[str, Any]]:
    root = media_raw_dir()
    allowed = media_allowed_extensions()
    max_files = min(media_limit(limit, default=100, maximum=media_max_scan_files()), media_max_scan_files())
    found: list[dict[str, Any]] = []
    try:
        iterator = root.rglob("*")
        for candidate in iterator:
            if len(found) >= max_files:
                break
            if candidate.suffix.lower() not in allowed:
                continue
            try:
                resolved = candidate.resolve(strict=True)
                resolved.relative_to(root)
                if media_path_under_wlc_managed(resolved):
                    # WLC session/attempt packages are owned by their own pipelines.
                    continue
                if not resolved.is_file():
                    continue
                state = media_source_state(resolved)
            except (OSError, ValueError):
                continue
            found.append(
                {
                    "source_path": state["path"],
                    "source_name": state["name"],
                    "source_size_bytes": state["size_bytes"],
                    "source_mtime": state["mtime"].isoformat(),
                }
            )
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Raw capture directory scan failed: {exc}") from exc

    if not found:
        return []

    source_paths = ", ".join(sql_text(item["source_path"]) for item in found)
    registered_rows = media_query_rows(
        "select * from v_vocera_media_qoe_study_captures "
        f"where source_path in ({source_paths});"
    )
    rows_by_path: dict[str, list[dict[str, str]]] = {}
    for row in registered_rows:
        rows_by_path.setdefault(row.get("source_path", ""), []).append(row)

    files: list[dict[str, Any]] = []
    for item in sorted(found, key=lambda value: (value.get("source_mtime") or "", value.get("source_path") or ""), reverse=True):
        matches = rows_by_path.get(str(item["source_path"]), [])
        study_match = next((row for row in matches if row.get("study_id") == study_id), None)
        if study_match and not include_registered:
            continue
        out = dict(item)
        out["registered"] = study_match is not None
        if study_match:
            out.update(
                {
                    "capture_id": study_match.get("capture_id"),
                    "capture_status": study_match.get("capture_status"),
                    "parse_success": study_match.get("parse_success"),
                    "stream_count": study_match.get("stream_count"),
                    "rtp_qoe_stream_count": study_match.get("rtp_qoe_stream_count"),
                    "dscp_mismatch_stream_count": study_match.get("dscp_mismatch_stream_count"),
                    "trusted_rtp_dscp_mismatch_stream_count": study_match.get("trusted_rtp_dscp_mismatch_stream_count"),
                    "non_rtp_dscp_mismatch_stream_count": study_match.get("non_rtp_dscp_mismatch_stream_count"),
                    "lossy_stream_count": study_match.get("lossy_stream_count"),
                    "jitter_p95_ms": study_match.get("jitter_p95_ms"),
                    "loss_p95_ratio": study_match.get("loss_p95_ratio"),
                    "interarrival_p95_ms": study_match.get("interarrival_p95_ms"),
                }
            )
        files.append(out)
    return files


@app.get("/api/media-qoe/summary")
def get_media_qoe_summary() -> dict[str, Any]:
    project_id = default_media_project_id()
    return {
        "ok": True,
        "project": media_project_row(project_id),
        "summary": media_project_summary_row(project_id),
        "studies": media_query_rows(
            "select * from v_vocera_media_qoe_studies "
            f"where project_id = {sql_text(project_id)} "
            "and deleted_at is null "
            "order by study_name, study_id;"
        ),
    }


@app.get("/api/media-qoe/execution/status")
def get_media_qoe_execution_status() -> dict[str, Any]:
    configured = os.environ.get("STUDY_WEB_MEDIA_QOE_RAW_DIR", "/var/lib/vocera-media-qoe/raw").strip()
    raw_path = Path(configured or "/var/lib/vocera-media-qoe/raw").expanduser()
    try:
        raw_dir = raw_path.resolve(strict=False)
    except OSError:
        raw_dir = raw_path
    raw_dir_exists = raw_dir.exists()
    raw_dir_readable = raw_dir_exists and raw_dir.is_dir() and os.access(raw_dir, os.R_OK)
    active_lock = media_active_parse_lock()
    return {
        "ok": True,
        "execution_enabled": media_execution_enabled(),
        "archive_enabled": media_archive_enabled(),
        "raw_dir": str(raw_dir),
        "allowed_extensions": sorted(media_allowed_extensions()),
        "max_scan_files": media_max_scan_files(),
        "max_parse_bytes": media_max_parse_bytes(),
        "parse_timeout_seconds": media_parse_timeout_seconds(),
        "raw_dir_exists": raw_dir_exists,
        "raw_dir_readable": raw_dir_readable,
        "parse_running": bool(active_lock),
        "active_parse": active_lock or None,
    }


@app.get("/api/media-qoe/dnac/status")
def get_media_qoe_dnac_status(
    client_mac: str | None = None,
    ap_mac: str | None = None,
    capture_type: str | None = None,
    lookback_minutes: int | None = None,
    limit: int | None = None,
    offset: int = 1,
) -> dict[str, Any]:
    query = MediaDnacCaptureQuery(
        client_mac=client_mac,
        ap_mac=ap_mac,
        capture_type=capture_type,
        lookback_minutes=lookback_minutes,
        limit=limit,
        offset=offset,
    )
    try:
        config = media_dnac_config(query)
    except Exception as exc:
        raw_dir = media_dnac_soft_raw_dir()
        return {
            "ok": True,
            "configured": False,
            "dnac_client_available": False,
            "base_url_configured": False,
            "username_configured": False,
            "password_configured": False,
            "tls_verify": True,
            "raw_dir": str(raw_dir),
            "raw_dir_exists": raw_dir.exists(),
            "raw_dir_readable": raw_dir.exists() and raw_dir.is_dir() and os.access(raw_dir, os.R_OK),
            "default_client_mac": None,
            "default_ap_mac": None,
            "default_capture_type": capture_type or "FULL",
            "lookback_minutes": lookback_minutes,
            "limit": limit,
            "start_capture_available": False,
            "start_capture_unavailable_reason": "ICAP start-capture is intentionally unavailable",
            "download_enabled": False,
            "missing_config": ["DNAC_BASE_URL", "DNAC_USERNAME", "DNAC_PASSWORD"],
            "auth_ok": None,
            "client_detail_ok": None,
            "capture_files_api_ok": None,
            "capture_files_returned": None,
            "resolved": None,
            "error_summary": media_dnac_error(exc),
        }

    status = media_dnac_base_status(config)
    status["dnac_client_available"] = True
    if not config["configured"]:
        return status

    icap = config["icap"]
    try:
        normalized_client_mac = media_dnac_normalize_mac(icap, config.get("client_mac"), "client MAC")
        normalized_ap_mac = media_dnac_normalize_mac(icap, config.get("ap_mac"), "AP MAC")
    except HTTPException as exc:
        status["error_summary"] = str(exc.detail)
        return status

    client = media_dnac_client(config)
    if normalized_client_mac:
        try:
            client_detail = client.get_client_detail(normalized_client_mac)
            status["auth_ok"] = True
            status["client_detail_ok"] = True
            status["resolved"] = icap.resolve_capture_ids(client_detail)
        except Exception as exc:
            status["auth_ok"] = False
            status["client_detail_ok"] = False
            status["error_summary"] = media_dnac_error(exc)

        try:
            start_ms, end_ms = media_dnac_time_filters(int(config["lookback_minutes"]))
            payload = client.list_icap_capture_files(
                str(config["capture_type"]),
                client_mac=normalized_client_mac,
                ap_mac=normalized_ap_mac,
                start_time_ms=start_ms,
                end_time_ms=end_ms,
                limit=1,
                offset=1,
                sort_by="lastUpdatedTimestamp",
                order="desc",
            )
            status["auth_ok"] = True
            status["capture_files_api_ok"] = True
            status["capture_files_returned"] = len(icap.iter_capture_files(payload))
        except Exception as exc:
            if status["auth_ok"] is not True:
                status["auth_ok"] = False
            status["capture_files_api_ok"] = False
            status["error_summary"] = media_dnac_error(exc)

    return status


@app.get("/api/studies/{study_id}/media-qoe/dnac/captures")
def list_study_media_qoe_dnac_captures(
    study_id: str,
    client_mac: str | None = None,
    ap_mac: str | None = None,
    capture_type: str | None = None,
    lookback_minutes: int | None = None,
    limit: int | None = None,
    offset: int = 1,
) -> dict[str, Any]:
    validate_media_study_id(study_id)
    query = MediaDnacCaptureQuery(
        client_mac=client_mac,
        ap_mac=ap_mac,
        capture_type=capture_type,
        lookback_minutes=lookback_minutes,
        limit=limit,
        offset=offset,
    )
    try:
        config = media_dnac_config(query)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=media_dnac_error(exc)) from exc
    if not config["configured"]:
        raise HTTPException(status_code=400, detail=f"Missing Catalyst Center configuration: {', '.join(config['missing_config'])}")

    icap = config["icap"]
    normalized_client_mac = media_dnac_normalize_mac(icap, config.get("client_mac"), "client MAC")
    if not normalized_client_mac:
        raise HTTPException(status_code=400, detail="Client MAC is required to list completed ICAP captures.")
    normalized_ap_mac = media_dnac_normalize_mac(icap, config.get("ap_mac"), "AP MAC")
    config["client_mac"] = normalized_client_mac
    config["ap_mac"] = normalized_ap_mac
    config["study_id"] = study_id

    start_ms, end_ms = media_dnac_time_filters(int(config["lookback_minutes"]))
    client = media_dnac_client(config)
    try:
        payload = client.list_icap_capture_files(
            str(config["capture_type"]),
            client_mac=normalized_client_mac,
            ap_mac=normalized_ap_mac,
            start_time_ms=start_ms,
            end_time_ms=end_ms,
            limit=int(config["limit"]),
            offset=int(config["offset"]),
            sort_by="lastUpdatedTimestamp",
            order="desc",
        )
        captures = icap.filter_capture_files(icap.iter_capture_files(payload), client_mac=normalized_client_mac, ap_mac=normalized_ap_mac)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=media_dnac_error(exc)) from exc

    captures = sorted(captures, key=lambda item: (icap.capture_timestamp_ms(item), str(media_dnac_capture_value(item, "fileName", "id", "name") or "")), reverse=True)
    local_paths = [media_dnac_capture_local_path(config, capture) for capture in captures]
    registered = media_dnac_registered_by_path(study_id, local_paths)
    return {
        "ok": True,
        "study_id": study_id,
        "client_mac": normalized_client_mac,
        "ap_mac": normalized_ap_mac,
        "capture_type": config["capture_type"],
        "lookback_minutes": config["lookback_minutes"],
        "limit": config["limit"],
        "offset": config["offset"],
        "raw_dir": str(config["raw_dir"]),
        "captures": [media_dnac_capture_item(config, capture, registered) for capture in captures],
    }


@app.post("/api/studies/{study_id}/media-qoe/dnac/captures/download")
def download_study_media_qoe_dnac_capture(study_id: str, payload: MediaDnacCaptureDownload) -> dict[str, Any]:
    validate_media_study_id(study_id)
    query = MediaDnacCaptureQuery(
        client_mac=payload.client_mac,
        ap_mac=payload.ap_mac,
        capture_type=payload.capture_type,
        lookback_minutes=payload.lookback_minutes,
        limit=payload.limit,
        offset=payload.offset,
    )
    try:
        config = media_dnac_config(query)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=media_dnac_error(exc)) from exc
    if not config["download_enabled"]:
        raise HTTPException(status_code=403, detail="DNAC ICAP download is disabled by STUDY_WEB_MEDIA_QOE_DNAC_DOWNLOAD_ENABLED.")
    if not config["configured"]:
        raise HTTPException(status_code=400, detail=f"Missing Catalyst Center configuration: {', '.join(config['missing_config'])}")

    icap = config["icap"]
    normalized_client_mac = media_dnac_normalize_mac(icap, config.get("client_mac"), "client MAC")
    if not normalized_client_mac:
        raise HTTPException(status_code=400, detail="Client MAC is required to download an ICAP capture.")
    normalized_ap_mac = media_dnac_normalize_mac(icap, config.get("ap_mac"), "AP MAC")
    config["client_mac"] = normalized_client_mac
    config["ap_mac"] = normalized_ap_mac
    config["study_id"] = study_id

    start_ms, end_ms = media_dnac_time_filters(int(config["lookback_minutes"]))
    client = media_dnac_client(config)
    try:
        list_payload = client.list_icap_capture_files(
            str(config["capture_type"]),
            client_mac=normalized_client_mac,
            ap_mac=normalized_ap_mac,
            start_time_ms=start_ms,
            end_time_ms=end_ms,
            limit=int(config["limit"]),
            offset=int(config["offset"]),
            sort_by="lastUpdatedTimestamp",
            order="desc",
        )
        captures = icap.filter_capture_files(icap.iter_capture_files(list_payload), client_mac=normalized_client_mac, ap_mac=normalized_ap_mac)
        selected = media_dnac_select_capture(icap, captures, payload)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=media_dnac_error(exc)) from exc

    local_path = media_dnac_download_path(config, selected)
    sidecar_path = local_path.with_suffix(local_path.suffix + ".json")
    registered = media_dnac_registered_by_path(study_id, [str(local_path)])
    registered_row = registered.get(str(local_path))
    if payload.register and registered_row and registered_row.get("study_id") != study_id:
        raise HTTPException(status_code=409, detail="DNAC capture local path is already registered to another study.")

    expected_size = icap.capture_file_size(selected)
    downloaded = False
    if local_path.exists() and local_path.stat().st_size > 0:
        local_size = local_path.stat().st_size
        if expected_size is not None and local_size != expected_size:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Existing local ICAP capture size does not match Catalyst Center metadata. "
                    f"local={local_size} expected={expected_size}"
                ),
            )
    else:
        data = b""
        last_error: Exception | None = None
        for candidate_id in icap.capture_download_ids(selected):
            try:
                data = client.download_icap_capture_file(candidate_id)
                break
            except Exception as exc:
                last_error = exc
        if not data and last_error:
            raise HTTPException(status_code=502, detail=media_dnac_error(last_error)) from last_error
        if not data:
            raise HTTPException(status_code=502, detail="Catalyst Center returned an empty ICAP capture.")
        if expected_size is not None and len(data) != expected_size:
            raise HTTPException(
                status_code=502,
                detail=f"Downloaded ICAP capture size does not match Catalyst Center metadata: downloaded={len(data)} expected={expected_size}",
            )
        tmp_path = local_path.with_suffix(local_path.suffix + ".tmp")
        tmp_path.write_bytes(data)
        tmp_path.replace(local_path)
        downloaded = True

    icap.write_metadata(sidecar_path, selected, local_path, list_payload)

    capture_id: str | None = None
    registration_created = False
    if payload.register:
        response = register_study_media_qoe_capture(
            study_id,
            MediaCaptureRegister(
                source_path=str(local_path),
                source_name=local_path.name,
                capture_point="ICAP",
                notes="Downloaded from Catalyst Center ICAP completed capture list.",
            ),
        )
        capture = response.get("capture") or {}
        capture_id = capture.get("capture_id")
        registration_created = bool(response.get("registered"))

    message = "Downloaded and registered ICAP capture."
    if not downloaded and registration_created:
        message = "Using existing local ICAP capture and registered it."
    elif downloaded and not registration_created and capture_id:
        message = "Downloaded ICAP capture; registration already existed."
    elif not downloaded and capture_id:
        message = "ICAP capture was already downloaded and registered."
    elif not payload.register:
        message = "Downloaded ICAP capture."

    return {
        "ok": True,
        "downloaded": downloaded,
        "registered": bool(capture_id),
        "registration_created": registration_created,
        "local_path": str(local_path),
        "sidecar_path": str(sidecar_path),
        "capture_id": capture_id,
        "source_name": local_path.name,
        "dnac_capture_id": media_dnac_capture_value(selected, "id", "fileName", "name"),
        "file_size": local_path.stat().st_size,
        "message": message,
    }


@app.get("/api/projects/{project_id}/media-qoe/summary")
def get_project_media_qoe_summary(project_id: str) -> dict[str, Any]:
    validate_media_project_id(project_id)
    return {"ok": True, "summary": media_project_summary_row(project_id)}


@app.get("/api/projects/{project_id}/media-qoe/captures")
def list_project_media_qoe_captures(project_id: str, include_deleted: bool = False, limit: int = 500) -> dict[str, Any]:
    validate_media_project_id(project_id)
    deleted_filter = "" if include_deleted else "and deleted_at is null "
    rows = media_query_rows(
        "select * from v_vocera_media_qoe_study_captures "
        f"where project_id = {sql_text(project_id)} "
        f"{deleted_filter}"
        "order by capture_time desc nulls last, parsed_at desc nulls last, capture_id desc "
        f"limit {media_limit(limit)};"
    )
    return {"ok": True, "captures": rows}


@app.get("/api/projects/{project_id}/media-qoe/streams")
def list_project_media_qoe_streams(project_id: str, limit: int = 500) -> dict[str, Any]:
    validate_media_project_id(project_id)
    rows = media_query_rows(
        "select * from v_vocera_media_qoe_study_streams "
        f"where project_id = {sql_text(project_id)} "
        "order by sample_time desc nulls last, capture_id desc, stream_id desc "
        f"limit {media_limit(limit)};"
    )
    return {"ok": True, "streams": rows}


@app.get("/api/projects/{project_id}/media-qoe/duplicates")
def list_project_media_qoe_duplicates(project_id: str, limit: int = 500) -> dict[str, Any]:
    validate_media_project_id(project_id)
    rows = media_query_rows(
        "select * from v_vocera_media_qoe_duplicate_captures "
        f"where project_id = {sql_text(project_id)} "
        "order by duplicate_count desc, duplicate_key, duplicate_rank, capture_id "
        f"limit {media_limit(limit)};"
    )
    return {"ok": True, "duplicates": rows}


@app.get("/api/studies/{study_id}/media-qoe/summary")
def get_study_media_qoe_summary(study_id: str) -> dict[str, Any]:
    return {"ok": True, "summary": validate_media_study_id(study_id)}


@app.get("/api/studies/{study_id}/media-qoe/captures")
def list_study_media_qoe_captures(study_id: str, include_deleted: bool = False, limit: int = 500) -> dict[str, Any]:
    validate_media_study_id(study_id)
    deleted_filter = "" if include_deleted else "and deleted_at is null "
    rows = media_query_rows(
        "select * from v_vocera_media_qoe_study_captures "
        f"where study_id = {sql_text(study_id)} "
        f"{deleted_filter}"
        "order by capture_time desc nulls last, parsed_at desc nulls last, capture_id desc "
        f"limit {media_limit(limit)};"
    )
    return {"ok": True, "captures": rows}


@app.get("/api/studies/{study_id}/media-qoe/streams")
def list_study_media_qoe_streams(study_id: str, limit: int = 500) -> dict[str, Any]:
    validate_media_study_id(study_id)
    rows = media_query_rows(
        "select * from v_vocera_media_qoe_study_streams "
        f"where study_id = {sql_text(study_id)} "
        "order by sample_time desc nulls last, capture_id desc, stream_id desc "
        f"limit {media_limit(limit)};"
    )
    return {"ok": True, "streams": rows}


@app.get("/api/studies/{study_id}/media-qoe/raw-files")
def list_study_media_qoe_raw_files(study_id: str, include_registered: bool = True, limit: int = 100) -> dict[str, Any]:
    validate_media_study_id(study_id)
    raw_dir = media_raw_dir()
    return {
        "ok": True,
        "raw_dir": str(raw_dir),
        "files": media_scan_raw_files(study_id, include_registered=include_registered, limit=limit),
    }


@app.get("/api/media-qoe/wlc/defaults")
def get_media_qoe_wlc_defaults() -> dict[str, Any]:
    defaults = media_wlc_defaults()
    return {
        "ok": True,
        "defaults": defaults,
        "session_root": str(media_wlc_session_root(create=False)),
        "password_policy": {
            "collects_passwords": False,
            "message": "Manual mode does not collect WLC or SCP passwords. The WLC prompts interactively during SCP export.",
        },
    }


@app.get("/api/studies/{study_id}/media-qoe/wlc/sessions")
def list_study_media_qoe_wlc_sessions(study_id: str, limit: int = 100) -> dict[str, Any]:
    validate_media_study_id(study_id)
    rows = media_query_rows(
        "select * from v_vocera_media_capture_sessions "
        f"where study_id = {sql_text(study_id)} "
        "order by created_at desc, session_id desc "
        f"limit {media_limit(limit, default=100, maximum=500)};"
    )
    return {"ok": True, "sessions": rows}


@app.post("/api/studies/{study_id}/media-qoe/wlc/sessions")
def create_study_media_qoe_wlc_session(study_id: str, payload: MediaWlcCaptureSessionCreate) -> dict[str, Any]:
    validate_media_study_id(study_id)
    _, wlc_session = media_wlc_imports()
    session_id = media_wlc_validate_id(payload.session_id or media_wlc_session_id(), "session_id")
    payload.session_id = session_id
    # Duplicate-session protection: never silently overwrite an existing package
    # or DB row. Conflicting session IDs must be a deliberate, explicit choice.
    existing = media_query_rows(
        f"select session_id from vocera_media_capture_sessions where session_id = {sql_text(session_id)} limit 1;"
    )
    if existing:
        raise HTTPException(status_code=409, detail=f"WLC capture session {session_id} already exists.")
    if (media_wlc_session_package_dir(study_id, session_id, create=False) / "session.json").exists():
        raise HTTPException(status_code=409, detail=f"A capture-session package already exists for {session_id}.")
    # Generate a short, unique capture name when the operator did not supply one
    # so controller capture-session names cannot collide across sessions.
    if not (payload.capture_name and payload.capture_name.strip()):
        payload.capture_name = wlc_session.generate_capture_name()
    # Capture-name collision protection: the same controller capture name in
    # active use by another non-terminal session would collide on the WLC, so
    # reject reuse until that session is imported or aborted. The generator above
    # already avoids this for blank requests; this guards operator-supplied names.
    name_conflict = media_query_rows(
        "select session_id from vocera_media_capture_sessions "
        f"where capture_name = {sql_text(payload.capture_name)} "
        "and session_state not in ('imported', 'aborted') "
        "limit 1;"
    )
    if name_conflict:
        raise HTTPException(
            status_code=409,
            detail=(
                f"WLC capture name {payload.capture_name} is already in use by active session "
                f"{name_conflict[0].get('session_id')}. Choose another or leave it blank to generate one."
            ),
        )
    # Let the package creator create the path only after validating the local
    # SCP target account. A root-owned Study Web process must delegate only the
    # incoming/ staging directory to that account; creating the target here
    # would leave an empty root-owned package behind on validation failure.
    target = media_wlc_session_package_dir(study_id, session_id, create=False)
    args = media_wlc_namespace(study_id, payload, target)
    session = wlc_session.session_payload(args, target)
    try:
        wlc_session.create_session_package(session, target, force=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=500, detail=f"Unable to prepare WLC SCP staging: {exc}") from exc
    media_wlc_insert_session(session)
    row = media_wlc_session_row(session_id)
    return {
        "ok": True,
        "session": row,
        "package_path": str(target),
        "command_sheets": media_wlc_command_sheets(target),
        "message": "Created manual WLC capture-session package. No passwords were collected or written.",
    }


@app.patch("/api/media-qoe/wlc/sessions/{session_id}")
def update_media_qoe_wlc_session(session_id: str, payload: MediaWlcCaptureSessionPatch) -> dict[str, Any]:
    media_wlc_validate_id(session_id, "session_id")
    row = media_wlc_update_session(session_id, payload)
    return {"ok": True, "session": row}


@app.post("/api/media-qoe/wlc/sessions/{session_id}/events")
def create_media_qoe_wlc_session_event(session_id: str, payload: MediaWlcSessionEventCreate) -> dict[str, Any]:
    media_wlc_validate_id(session_id, "session_id")
    session = media_wlc_session_row(session_id)
    result = media_wlc_insert_event(session, payload)
    refreshed = media_wlc_session_row(session_id)
    return {"ok": True, "session": refreshed, **result}


@app.get("/api/media-qoe/wlc/sessions/{session_id}/attempts")
def list_media_qoe_wlc_session_attempts(session_id: str, limit: int = 200) -> dict[str, Any]:
    media_wlc_validate_id(session_id, "session_id")
    media_wlc_session_row(session_id)
    rows = media_query_rows(
        "select * from v_vocera_media_broadcast_attempts "
        f"where capture_session_id = {sql_text(session_id)} "
        "order by attempt_started_at desc nulls last, created_at desc "
        f"limit {media_limit(limit, default=200, maximum=1000)};"
    )
    open_attempt = media_wlc_open_attempt(session_id)
    return {"ok": True, "attempts": rows, "open_attempt_id": open_attempt.get("attempt_id") if open_attempt else None}


@app.post("/api/media-qoe/wlc/sessions/{session_id}/attempts/start")
def start_media_qoe_wlc_attempt(session_id: str, payload: MediaWlcAttemptStart) -> dict[str, Any]:
    media_wlc_validate_id(session_id, "session_id")
    session = media_wlc_session_row(session_id)
    attempt = media_wlc_start_attempt(session, payload)
    return {"ok": True, "attempt": attempt, "session": media_wlc_session_row(session_id)}


@app.patch("/api/media-qoe/wlc/attempts/{attempt_id}/outcome")
def set_media_qoe_wlc_attempt_outcome(attempt_id: str, payload: MediaWlcAttemptOutcome) -> dict[str, Any]:
    media_wlc_validate_id(attempt_id, "attempt_id")
    attempt = media_wlc_set_outcome(attempt_id, payload)
    return {"ok": True, "attempt": attempt}


@app.patch("/api/media-qoe/wlc/attempts/{attempt_id}/active-group")
def set_media_qoe_wlc_attempt_active_group(attempt_id: str, payload: MediaWlcAttemptActiveGroup) -> dict[str, Any]:
    media_wlc_validate_id(attempt_id, "attempt_id")
    attempt = media_wlc_set_active_group(attempt_id, payload)
    return {"ok": True, "attempt": attempt}


def media_register_capture_record(
    study_id: str,
    path: Path,
    *,
    capture_point: str | None,
    source_name: str | None,
    notes: str | None,
    site: str | None = None,
) -> dict[str, Any]:
    """Register (or return the existing) capture row for a validated file.

    Shared by the generic raw-file register endpoint and the WLC session-EPC
    ingest path. The caller validates ``path`` first with the appropriate
    validator (generic raw-file vs. session-package), so this only owns file
    identity, de-duplication, and the insert -- both ingestion paths register
    captures identically.
    """

    state = media_source_state(path)
    capture_id = media_capture_id_for_state(state)
    source_sha256 = media_source_sha256_for_state(state)

    existing = media_query_rows(
        "select capture_id, study_id, source_path from vocera_media_captures "
        f"where capture_id = {sql_text(capture_id)} "
        f"or source_path = {sql_text(state['path'])} "
        "order by case when capture_id = "
        f"{sql_text(capture_id)} then 0 else 1 end, capture_id;"
    )
    for row in existing:
        if row.get("study_id") != study_id:
            raise HTTPException(status_code=409, detail="Capture source is already registered to another study.")
        if row.get("capture_id") != capture_id:
            raise HTTPException(status_code=409, detail="Capture source path is already registered with a different file identity.")
        return {"capture_id": capture_id, "registered": False}

    raw_metadata = {
        "source_pcap": {
            "path": state["path"],
            "name": source_name or state["name"],
            "size_bytes": state["size_bytes"],
            "mtime_ns": state["mtime_ns"],
        },
        "registration": {
            "notes": notes,
            "registered_by": user(),
        },
    }
    media_query_one(
        "insert into vocera_media_captures ("
        "capture_id, study_id, source_path, source_name, source_size_bytes, source_sha256, "
        "source_mtime, source_mtime_ns, source_discovered_at, source_registered_at, "
        "site, capture_point, capture_status, parse_success, parse_requested_by, parse_requested_at, raw_metadata"
        ") values ("
        f"{sql_text(capture_id)}, "
        f"{sql_text(study_id)}, "
        f"{sql_text(state['path'])}, "
        f"{sql_text(source_name or state['name'])}, "
        f"{sql_int(int(state['size_bytes']))}, "
        f"{sql_text(source_sha256)}, "
        f"{sql_timestamp(state['mtime'])}, "
        f"{sql_int(int(state['mtime_ns']))}, "
        "now(), "
        "now(), "
        f"{sql_text(site or 'unknown')}, "
        f"{sql_text(capture_point or 'unknown')}, "
        "'registered', "
        "false, "
        f"{sql_text(user())}, "
        "now(), "
        f"{media_jsonb(raw_metadata)}"
        ") "
        "returning capture_id;"
    )
    return {"capture_id": capture_id, "registered": True}


@app.post("/api/studies/{study_id}/media-qoe/captures/register")
def register_study_media_qoe_capture(study_id: str, payload: MediaCaptureRegister) -> dict[str, Any]:
    validate_media_study_id(study_id)
    path = validate_media_raw_file(payload.source_path)
    result = media_register_capture_record(
        study_id,
        path,
        capture_point=payload.capture_point,
        source_name=payload.source_name,
        notes=payload.notes,
        site=payload.site,
    )
    return {"ok": True, "capture": media_study_capture_row(result["capture_id"]), "registered": result["registered"]}


@app.get("/api/media-qoe/captures/{capture_id}/parse-runs")
def list_media_qoe_capture_parse_runs(capture_id: str, limit: int = 25) -> dict[str, Any]:
    media_capture_row(capture_id)
    rows = media_query_rows(
        "select * from v_vocera_media_qoe_parse_runs "
        f"where capture_id = {sql_text(capture_id)} "
        "order by requested_at desc, parse_run_id desc "
        f"limit {media_limit(limit, default=25, maximum=100)};"
    )
    return {"ok": True, "parse_runs": rows}


@app.post("/api/media-qoe/captures/{capture_id}/execute")
def execute_media_qoe_capture(capture_id: str, payload: MediaCaptureExecute) -> dict[str, Any]:
    if not media_execution_enabled():
        raise HTTPException(status_code=403, detail="Media QoE parser execution is disabled by STUDY_WEB_MEDIA_QOE_EXECUTION_ENABLED.")
    if media_archive_enabled():
        raise HTTPException(status_code=400, detail="Archive generation is not allowed for web-triggered Media QoE parsing.")

    capture = media_capture_row(capture_id)
    study_id = capture.get("study_id") or default_media_study_id()
    validate_media_study_id(study_id)
    if capture.get("capture_status") == "complete" and not payload.reparse:
        raise HTTPException(status_code=409, detail="Capture is already complete. Set reparse=true to parse it again.")

    path = validate_media_raw_file(capture.get("source_path") or "")
    return media_run_capture_parse(
        capture_id,
        study_id,
        path,
        timeout_seconds=payload.timeout_seconds,
        requested_by=user(),
    )


def media_run_capture_parse(
    capture_id: str,
    study_id: str,
    path: Path,
    *,
    timeout_seconds: int | None = None,
    requested_by: str | None = None,
) -> dict[str, Any]:
    """Run the media QoE parser for one already-validated capture file.

    Shared executor for the generic single-capture execute endpoint and the WLC
    session-EPC ingest path: locking, parse-run bookkeeping, the
    ``vocera_media_qoe_batch`` subprocess, and result recording all live here so
    both paths behave identically. The caller validates ``path`` with the
    appropriate validator (generic raw-file vs. session-package) and registers
    ``capture_id`` first.
    """

    state = media_source_state(path)
    current_capture_id = media_capture_id_for_state(state)
    if current_capture_id != capture_id:
        raise HTTPException(status_code=409, detail="Capture file changed since registration. Register the current file identity before parsing.")
    if int(state["size_bytes"]) > media_max_parse_bytes():
        raise HTTPException(status_code=413, detail="Capture file exceeds STUDY_WEB_MEDIA_QOE_MAX_PARSE_BYTES.")

    config_path = media_parser_config_path()
    if not config_path.is_file():
        raise HTTPException(status_code=500, detail=f"Media QoE parser config file not found: {config_path}")

    parse_run_id = new_entity_id("parse")
    effective_timeout = min(timeout_seconds or media_parse_timeout_seconds(), media_parse_timeout_seconds())
    requested_by = requested_by or user()
    lock_acquired = False
    media_acquire_parse_lock(capture_id, parse_run_id, effective_timeout)
    lock_acquired = True

    try:
        media_query_one(
            "insert into vocera_media_capture_parse_runs (parse_run_id, capture_id, study_id, source_path, requested_by, requested_at, status) "
            "values ("
            f"{sql_text(parse_run_id)}, {sql_text(capture_id)}, {sql_text(study_id)}, {sql_text(state['path'])}, {sql_text(requested_by)}, now(), 'queued'"
            "); "
            "update vocera_media_captures set "
            "capture_status = 'queued', "
            "parse_requested_by = "
            f"{sql_text(requested_by)}, "
            "parse_requested_at = now(), "
            "parse_error = null "
            f"where capture_id = {sql_text(capture_id)}; "
            f"select {sql_text(parse_run_id)} as parse_run_id;"
        )

        started_at = datetime.now(timezone.utc)
        media_query_one(
            "update vocera_media_capture_parse_runs set status = 'running', started_at = now() "
            f"where parse_run_id = {sql_text(parse_run_id)}; "
            "update vocera_media_captures set "
            "capture_status = 'running', "
            "parse_started_at = now(), "
            "parse_finished_at = null, "
            "parse_duration_seconds = null, "
            "parse_exit_code = null, "
            "parse_stdout = null, "
            "parse_stderr = null, "
            "parse_error = null "
            f"where capture_id = {sql_text(capture_id)}; "
            f"select {sql_text(parse_run_id)} as parse_run_id;"
        )

        run_dir = (MEDIA_QOE_PARSE_OUTPUT_ROOT / parse_run_id).resolve(strict=False)
        parsed_dir = run_dir / "captures"
        run_dir.mkdir(parents=True, exist_ok=True)
        command = [
            "python3",
            "-m",
            "vocera_media_qoe_batch",
            "--raw-dir",
            str(media_raw_dir()),
            "--pcap",
            str(path),
            "--config",
            str(config_path),
            "--prom-out",
            str(run_dir / "vocera_media_qoe.prom"),
            "--json-out",
            str(run_dir / "vocera_media_qoe_summary.json"),
            "--parsed-dir",
            str(parsed_dir),
            "--sql-out",
            str(run_dir / "vocera_media_qoe_import.sql"),
            "--postgres-url",
            media_db().url,
            "--psql-bin",
            media_db().psql_bin,
            "--schema-sql",
            str(ROOT / "sql" / "vocera_media_qoe_schema.sql"),
            "--views-sql",
            str(ROOT / "sql" / "vocera_media_qoe_views.sql"),
            "--study-id",
            study_id,
            "--skip-install-db",
            "--no-archive",
            "--force",
        ]
        env = os.environ.copy()
        env.update(
            {
                "PYTHONPATH": str(ROOT / "tools" / "vocera_media_qoe"),
                "VOCERA_MEDIA_QOE_STUDY_ID": study_id,
                "VOCERA_MEDIA_QOE_INSTALL_DB": "0",
                "VOCERA_MEDIA_QOE_ARCHIVE_DIR": "",
            }
        )

        stdout: str | None = None
        stderr: str | None = None
        exit_code: int | None = None
        error: str | None = None
        try:
            completed = subprocess.run(
                command,
                cwd=ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=effective_timeout,
                check=False,
            )
            stdout = completed.stdout
            stderr = completed.stderr
            exit_code = completed.returncode
            if completed.returncode != 0:
                error = f"Parser exited with status {completed.returncode}."
        except subprocess.TimeoutExpired as exc:
            stdout = media_truncate_output(exc.stdout)
            stderr = media_truncate_output(exc.stderr)
            exit_code = -1
            error = f"Parser timed out after {effective_timeout} seconds."
        except Exception as exc:  # noqa: BLE001 - persist concise parser execution failures for the UI
            exit_code = -1
            error = str(exc)

        finished_at = datetime.now(timezone.utc)
        duration_seconds = max((finished_at - started_at).total_seconds(), 0.0)
        summary = {"captures": 0, "streams": 0, "rtp_qoe_streams": 0, "dscp_mismatch_streams": 0, "lossy_streams": 0}
        status = "failed"
        if error is None:
            imported = media_capture_row(capture_id)
            summary = media_parse_summary(capture_id)
            if imported.get("parse_success") in {"true", "t", "1"}:
                status = "complete"
            else:
                error = imported.get("parse_error") or "Parser completed but capture parse_success is false."

        stdout = media_truncate_output(stdout)
        stderr = media_truncate_output(stderr)
        media_query_one(
            "update vocera_media_capture_parse_runs set "
            f"status = {sql_text(status)}, "
            "finished_at = now(), "
            f"duration_seconds = {duration_seconds}, "
            f"exit_code = {sql_int(exit_code)}, "
            f"stdout = {sql_text(stdout)}, "
            f"stderr = {sql_text(stderr)}, "
            f"error = {sql_text(error)}, "
            f"captures_imported = {sql_int(summary['captures'])}, "
            f"streams_imported = {sql_int(summary['streams'])}, "
            f"rtp_qoe_streams = {sql_int(summary['rtp_qoe_streams'])}, "
            f"dscp_mismatch_streams = {sql_int(summary['dscp_mismatch_streams'])}, "
            f"lossy_streams = {sql_int(summary['lossy_streams'])} "
            f"where parse_run_id = {sql_text(parse_run_id)}; "
            "update vocera_media_captures set "
            f"capture_status = {sql_text(status)}, "
            "parse_finished_at = now(), "
            f"parse_duration_seconds = {duration_seconds}, "
            f"parse_exit_code = {sql_int(exit_code)}, "
            f"parse_stdout = {sql_text(stdout)}, "
            f"parse_stderr = {sql_text(stderr)}, "
            f"parse_error = {sql_text(error)}, "
            f"parse_success = {'true' if status == 'complete' else 'false'} "
            f"where capture_id = {sql_text(capture_id)}; "
            f"select {sql_text(parse_run_id)} as parse_run_id;"
        )
        return {
            "ok": True,
            "capture_id": capture_id,
            "parse_run_id": parse_run_id,
            "status": status,
            "duration_seconds": duration_seconds,
            "summary": summary,
            "error": error,
        }
    finally:
        if lock_acquired:
            media_release_parse_lock(parse_run_id)


# ---------------------------------------------------------------------------
# WLC capture-session EPC ingest (Phase 0: SCP session-artifact foundation)
# ---------------------------------------------------------------------------
# Study Web owns this pipeline so it can reuse the in-process parser executor
# (media_run_capture_parse) and capture registration the generic path uses.
# A thin systemd timer pokes POST /api/media-qoe/wlc/sessions/ingest-scan once a
# minute; the heavy file primitives live in vocera_wlc_session_ingest (wlc_ingest)
# and are unit tested without a database.


def _media_parse_iso(value: str | None) -> "datetime | None":
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def media_wlc_ingest_stability_seconds() -> int:
    """Minimum unchanged interval before an incoming upload is treated as final."""

    raw = os.environ.get("STUDY_WEB_MEDIA_QOE_WLC_INGEST_STABILITY_SECONDS", "15").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 15


def media_wlc_ingest_max_bytes() -> int:
    """Maximum accepted WLC EPC upload size before quarantine."""

    raw = os.environ.get("STUDY_WEB_MEDIA_QOE_WLC_INGEST_MAX_BYTES", str(wlc_ingest.DEFAULT_MAX_UPLOAD_BYTES)).strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return wlc_ingest.DEFAULT_MAX_UPLOAD_BYTES


def media_wlc_ingest_min_free_bytes() -> int:
    """Minimum free bytes that must remain after finalizing an EPC."""

    raw = os.environ.get("STUDY_WEB_MEDIA_QOE_WLC_INGEST_MIN_FREE_BYTES", str(wlc_ingest.DEFAULT_MIN_FREE_BYTES)).strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return wlc_ingest.DEFAULT_MIN_FREE_BYTES


def media_wlc_validate_session_capture(path_text: str, *, subdir: str) -> Path:
    """Validate a file inside a WLC session package's incoming/ or pcaps/ dir.

    The session-aware counterpart to validate_media_raw_file: it *requires* the
    path to live under the WLC session root (which the generic validator now
    rejects), at the four-part <root>/<study>/<session>/<subdir>/<file> depth.
    """

    if "\x00" in path_text:
        raise HTTPException(status_code=400, detail="Source path contains an invalid null byte.")
    if media_path_has_traversal(path_text):
        raise HTTPException(status_code=400, detail="Source path traversal is not allowed.")
    root = media_wlc_session_root()
    candidate = Path(path_text).expanduser()
    candidate = candidate if candidate.is_absolute() else root / candidate
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Session capture file was not found: {path_text}") from exc
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Session capture file is not accessible: {exc}") from exc
    info = wlc_ingest.parse_session_rel(root, resolved)
    if info is None or info.get("subdir") != subdir:
        raise HTTPException(
            status_code=400,
            detail=f"Session capture must live under <study>/<session>/{subdir}/ in the WLC session root.",
        )
    if resolved.suffix.lower() not in media_allowed_extensions():
        raise HTTPException(status_code=400, detail=f"Unsupported capture extension: {resolved.suffix or '<none>'}.")
    if not resolved.is_file():
        raise HTTPException(status_code=400, detail="Session capture path must be a regular file.")
    return resolved


def media_wlc_session_artifact_row(artifact_id: str) -> dict[str, str] | None:
    rows = media_query_rows(
        "select * from vocera_media_session_artifacts "
        f"where artifact_id = {sql_text(artifact_id)};"
    )
    return rows[0] if rows else None


def media_wlc_upsert_artifact(
    artifact_id: str,
    capture_session_id: str,
    artifact_kind: str,
    source_path: str,
    source_name: str,
    *,
    ingest_state: str,
    final_path: str | None = None,
    sha256: str | None = None,
    size_bytes: int | None = None,
    validated_at: bool = False,
    capture_id: str | None = None,
    parser_status: str | None = None,
    visibility_class: str | None = None,
    error_message: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Insert or update one session-artifact row, accumulating metadata."""

    media_query_one(
        "insert into vocera_media_session_artifacts ("
        "artifact_id, capture_session_id, artifact_kind, source_path, final_path, source_name, "
        "sha256, size_bytes, validated_at, ingest_state, capture_id, parser_status, "
        "visibility_class, error_message, metadata, updated_at"
        ") values ("
        f"{sql_text(artifact_id)}, {sql_text(capture_session_id)}, {sql_text(artifact_kind)}, "
        f"{sql_text(source_path)}, {sql_text(final_path)}, {sql_text(source_name)}, "
        f"{sql_text(sha256)}, {sql_int(size_bytes)}, "
        f"{'now()' if validated_at else 'null'}, {sql_text(ingest_state)}, {sql_text(capture_id)}, "
        f"{sql_text(parser_status)}, {sql_text(visibility_class)}, {sql_text(error_message)}, "
        f"{media_jsonb(metadata or {})}, now()"
        ") on conflict (artifact_id) do update set "
        "capture_session_id = excluded.capture_session_id, "
        "artifact_kind = excluded.artifact_kind, "
        "source_path = excluded.source_path, "
        "final_path = coalesce(excluded.final_path, vocera_media_session_artifacts.final_path), "
        "source_name = excluded.source_name, "
        "sha256 = coalesce(excluded.sha256, vocera_media_session_artifacts.sha256), "
        "size_bytes = coalesce(excluded.size_bytes, vocera_media_session_artifacts.size_bytes), "
        "validated_at = coalesce(excluded.validated_at, vocera_media_session_artifacts.validated_at), "
        "ingest_state = excluded.ingest_state, "
        "capture_id = coalesce(excluded.capture_id, vocera_media_session_artifacts.capture_id), "
        "parser_status = coalesce(excluded.parser_status, vocera_media_session_artifacts.parser_status), "
        "visibility_class = coalesce(excluded.visibility_class, vocera_media_session_artifacts.visibility_class), "
        "error_message = excluded.error_message, "
        "metadata = vocera_media_session_artifacts.metadata || excluded.metadata, "
        "updated_at = now();"
    )


def media_wlc_epc_visibility(path: Path, session_id: str) -> dict[str, Any]:
    """Classify what packet evidence a WLC EPC can support.

    This is intentionally a compatibility classifier, not a CAPWAP decoder. It
    inspects the existing parser's supported packet view and records the claim
    boundary so the UI does not present RTP quality conclusions for an EPC that
    only exposes outer CAPWAP or other control-plane traffic.
    """

    session_rows = media_query_rows(
        "select sender_ip, receiver_ip, vocera_multicast_pool "
        "from v_vocera_media_capture_sessions "
        f"where session_id = {sql_text(session_id)} limit 1;"
    )
    session = session_rows[0] if session_rows else {}
    sender_ip = str(session.get("sender_ip") or "").strip()
    receiver_ip = str(session.get("receiver_ip") or "").strip()
    pool_text = str(session.get("vocera_multicast_pool") or "230.230.0.0/20").strip()
    try:
        vocera_pool = ipaddress.ip_network(pool_text, strict=False)
    except ValueError:
        vocera_pool = ipaddress.ip_network("230.230.0.0/20", strict=False)

    try:
        udp_packets, packets_read = media_analyzer.iter_pcap_udp_packets(path)
    except Exception as exc:  # noqa: BLE001 - surface parser compatibility details.
        return {
            "visibility_class": "unsupported_link_or_decode",
            "container_valid": True,
            "records_seen": None,
            "ipv4_udp_seen": 0,
            "claim_limit": f"Container exists, but the supported parser could not decode meaningful packet payload: {exc}",
            "supports": ["Capture container validation and file-level provenance."],
            "cannot_prove": [
                "Receiver-side RTP arrival, RTP loss, RTP jitter, or speaker behavior.",
                "Vocera multicast delivery at the AP or client.",
            ],
            "decode_error": str(exc),
        }

    capwap_control = 0
    capwap_data = 0
    sender_seen = 0
    receiver_seen = 0
    vocera_group_seen = 0
    multicast_udp_seen = 0
    rtp_headers_visible = 0
    for packet in udp_packets:
        ports = {int(packet.src_port), int(packet.dst_port)}
        if 5246 in ports:
            capwap_control += 1
        if 5247 in ports:
            capwap_data += 1
        if sender_ip and (packet.src_ip == sender_ip or packet.dst_ip == sender_ip):
            sender_seen += 1
        if receiver_ip and (packet.src_ip == receiver_ip or packet.dst_ip == receiver_ip):
            receiver_seen += 1
        for value in (packet.src_ip, packet.dst_ip):
            try:
                ip_value = ipaddress.ip_address(value)
            except ValueError:
                continue
            if ip_value.is_multicast:
                multicast_udp_seen += 1
            if ip_value in vocera_pool:
                vocera_group_seen += 1
        if media_analyzer.parse_rtp_header(packet.payload) is not None:
            rtp_headers_visible += 1

    if packets_read <= 0:
        visibility_class = "empty_or_unusable"
        supports = ["File provenance only."]
        cannot = [
            "Packet-level multicast evidence.",
            "RTP loss, jitter, or media-arrival quality.",
        ]
    elif rtp_headers_visible > 0 and vocera_group_seen > 0:
        visibility_class = "inner_voice_visible"
        supports = ["Visible inner Vocera multicast UDP/RTP timing at this capture point."]
        cannot = ["End-user speaker output or total mouth-to-ear latency."]
    elif vocera_group_seen > 0 or multicast_udp_seen > 0:
        visibility_class = "inner_multicast_visible"
        supports = ["Visible inner multicast packet arrival and group evidence at this capture point."]
        cannot = ["RTP loss or jitter unless RTP headers are visible and pass plausibility checks."]
    elif capwap_data > 0:
        visibility_class = "outer_capwap_only"
        supports = ["Outer CAPWAP transport evidence during the capture window."]
        cannot = ["Receiver-side RTP arrival, RTP loss, RTP jitter, or media-arrival quality."]
    elif capwap_control > 0 or udp_packets:
        visibility_class = "control_plane_only"
        supports = ["Visible UDP/control-plane packet evidence at this capture point."]
        cannot = ["Native Vocera multicast delivery or RTP quality."]
    else:
        visibility_class = "unsupported_link_or_decode"
        supports = ["Capture container and record-count validation."]
        cannot = ["Packet-layer delivery or media-quality conclusions."]

    return {
        "visibility_class": visibility_class,
        "container_valid": True,
        "records_seen": packets_read,
        "ipv4_udp_seen": len(udp_packets),
        "capwap_control_seen": capwap_control > 0,
        "capwap_data_seen": capwap_data > 0,
        "capwap_control_packets": capwap_control,
        "capwap_data_packets": capwap_data,
        "sender_inner_ip_seen": sender_seen > 0,
        "receiver_inner_ip_seen": receiver_seen > 0,
        "sender_inner_ip_packets": sender_seen,
        "receiver_inner_ip_packets": receiver_seen,
        "vocera_group_seen": vocera_group_seen > 0,
        "vocera_group_packets": vocera_group_seen,
        "multicast_udp_packets": multicast_udp_seen,
        "rtp_headers_visible": rtp_headers_visible > 0,
        "rtp_header_packets": rtp_headers_visible,
        "supports": supports,
        "cannot_prove": cannot,
        "claim_limit": " ".join(cannot),
    }


def _media_wlc_prev_observation(row: dict[str, str] | None) -> tuple[dict[str, int] | None, "datetime | None"]:
    if not row:
        return None, None
    raw_meta = row.get("metadata")
    meta: Any = {}
    if isinstance(raw_meta, str):
        try:
            meta = json.loads(raw_meta)
        except json.JSONDecodeError:
            meta = {}
    elif isinstance(raw_meta, dict):
        meta = raw_meta
    observed = meta.get("observed") if isinstance(meta, dict) else None
    if not isinstance(observed, dict):
        return None, None
    signature = observed.get("signature")
    prev_sig: dict[str, int] | None = None
    if isinstance(signature, dict) and "size_bytes" in signature and "mtime_ns" in signature:
        try:
            prev_sig = {"size_bytes": int(signature["size_bytes"]), "mtime_ns": int(signature["mtime_ns"])}
        except (TypeError, ValueError):
            prev_sig = None
    return prev_sig, _media_parse_iso(observed.get("observed_at"))


def media_wlc_process_incoming(
    *,
    study_id: str,
    session_id: str,
    incoming_pcap: Path,
    session_root: Path,
    stability_seconds: int,
) -> dict[str, Any]:
    """Detect, finalize, register, and parse one incoming EPC.

    Idempotent and timer-driven: an upload still in flight is recorded as
    ``upload_detected`` and revisited on the next scan; only a file unchanged for
    ``stability_seconds`` is finalized into a service-owned ``pcaps/`` artifact,
    registered as a ``wlc_epc`` capture, and parsed by the shared executor.
    """

    name = incoming_pcap.name
    artifact_id = wlc_ingest.artifact_id_for(session_id, "wlc_epc", name)
    base = (artifact_id, session_id, "wlc_epc", str(incoming_pcap), name)
    now = wlc_ingest.utc_now()

    existing = media_wlc_session_artifact_row(artifact_id)
    if existing and existing.get("ingest_state") in {"promoted", "registered", "imported", "parsing", "parsed", "retry_pending"}:
        return {"artifact_id": artifact_id, "session_id": session_id, "name": name,
                "state": existing.get("ingest_state"), "detail": "already ingested"}

    try:
        current_sig = wlc_ingest.file_signature(incoming_pcap)
    except OSError as exc:
        return {"artifact_id": artifact_id, "session_id": session_id, "name": name,
                "state": "error", "detail": str(exc)}

    prev_sig, prev_observed_at = _media_wlc_prev_observation(existing)
    decision = wlc_ingest.plan_ingest_decision(
        prev_signature=prev_sig,
        prev_observed_at=prev_observed_at,
        current_signature=current_sig,
        now=now,
        min_gap_seconds=stability_seconds,
    )

    if decision in {wlc_ingest.DECISION_WAIT_NEW, wlc_ingest.DECISION_WAIT_CHANGED}:
        wait_state = "upload_detected" if decision == wlc_ingest.DECISION_WAIT_NEW else "waiting_for_stability"
        media_wlc_upsert_artifact(
            *base, ingest_state=wait_state, size_bytes=current_sig["size_bytes"],
            metadata={"observed": {"signature": current_sig, "observed_at": now.isoformat()},
                      "ingest_decision": decision},
        )
        return {"artifact_id": artifact_id, "session_id": session_id, "name": name,
                "state": wait_state, "decision": decision}
    if decision == wlc_ingest.DECISION_WAIT_TOO_SOON:
        # Keep the original observed_at so the stable interval keeps growing.
        media_wlc_upsert_artifact(
            *base, ingest_state="waiting_for_stability", size_bytes=current_sig["size_bytes"],
            metadata={"ingest_decision": decision},
        )
        return {"artifact_id": artifact_id, "session_id": session_id, "name": name,
                "state": "waiting_for_stability", "decision": decision}

    # decision == ready: finalize into pcaps/, register, parse. Finalization
    # copies into a service-created root-owned file instead of renaming the
    # SCP upload, because rename would preserve the upload account's ownership
    # and could leave finalized evidence writable by that account.
    media_wlc_upsert_artifact(*base, ingest_state="validating", size_bytes=current_sig["size_bytes"])
    final = wlc_ingest.promoted_path(session_root, incoming_pcap)
    if final is None:
        media_wlc_upsert_artifact(
            *base, ingest_state="failed",
            error_message="Could not resolve the pcaps/ destination for this upload.",
            metadata={"failure_category": wlc_ingest.FAIL_PROMOTION_COPY_FAILED},
        )
        return {"artifact_id": artifact_id, "session_id": session_id, "name": name, "state": "failed"}
    try:
        finalization = wlc_ingest.finalize_upload_to_pcaps(
            incoming_pcap,
            final,
            max_bytes=media_wlc_ingest_max_bytes(),
            min_free_bytes=media_wlc_ingest_min_free_bytes(),
        )
    except wlc_ingest.IngestFinalizationError as exc:
        state = "quarantined" if exc.category in wlc_ingest.SOURCE_QUARANTINE_REASONS else "failed"
        media_wlc_upsert_artifact(
            *base,
            ingest_state=state,
            size_bytes=current_sig["size_bytes"],
            error_message=exc.message,
            metadata={"failure_category": exc.category, "failure": exc.metadata},
        )
        return {
            "artifact_id": artifact_id,
            "session_id": session_id,
            "name": name,
            "state": state,
            "failure_category": exc.category,
            "detail": exc.message,
        }

    final_path = Path(str(finalization["final_path"]))
    sha = str(finalization["sha256"])
    final_size = int(finalization["size_bytes"])
    visibility = media_wlc_epc_visibility(final_path, session_id)
    media_wlc_upsert_artifact(
        *base, ingest_state="validated", final_path=str(final_path), sha256=sha, size_bytes=final_size,
        validated_at=True, visibility_class=visibility.get("visibility_class"),
        metadata={"visibility": visibility, "finalization": finalization},
    )
    dup = media_query_rows(
        "select artifact_id, capture_id from vocera_media_session_artifacts "
        f"where capture_session_id = {sql_text(session_id)} and sha256 = {sql_text(sha)} "
        f"and artifact_id <> {sql_text(artifact_id)} and ingest_state in ('imported', 'parsing', 'parsed') "
        "limit 1;"
    )
    if dup:
        media_wlc_upsert_artifact(
            *base, ingest_state="parsed", final_path=str(final_path), sha256=sha, capture_id=dup[0].get("capture_id"),
            parser_status="duplicate", validated_at=True,
            metadata={"duplicate_of": dup[0].get("artifact_id"), "finalization": finalization},
        )
        return {"artifact_id": artifact_id, "session_id": session_id, "name": name,
                "state": "parsed", "detail": "duplicate content"}

    media_wlc_upsert_artifact(
        *base, ingest_state="promoted", final_path=str(final_path), sha256=sha,
        size_bytes=final_size, validated_at=True,
        visibility_class=visibility.get("visibility_class"), metadata={"visibility": visibility, "finalization": finalization},
    )

    try:
        validated = media_wlc_validate_session_capture(str(final_path), subdir=wlc_ingest.PCAPS_SUBDIR)
        registration = media_register_capture_record(
            study_id, validated, capture_point="wlc_epc",
            source_name=name, notes="WLC capture-session EPC auto-ingest.",
        )
    except HTTPException as exc:
        media_wlc_upsert_artifact(*base, ingest_state="failed", final_path=str(final_path),
                                  error_message=str(exc.detail),
                                  metadata={"failure_category": wlc_ingest.FAIL_CAPTURE_REGISTRATION_FAILED})
        return {"artifact_id": artifact_id, "session_id": session_id, "name": name,
                "state": "failed", "detail": str(exc.detail)}
    capture_id = registration["capture_id"]
    media_wlc_upsert_artifact(
        *base, ingest_state="registered", final_path=str(final_path), capture_id=capture_id,
        visibility_class=visibility.get("visibility_class"),
    )

    if not media_execution_enabled():
        media_wlc_upsert_artifact(
            *base, ingest_state="imported", final_path=str(final_path), capture_id=capture_id,
            parser_status="execution_disabled",
        )
        return {"artifact_id": artifact_id, "session_id": session_id, "name": name,
                "state": "imported", "capture_id": capture_id, "detail": "parser execution disabled"}

    media_wlc_upsert_artifact(*base, ingest_state="parsing", final_path=str(final_path), capture_id=capture_id)
    try:
        parse = media_run_capture_parse(capture_id, study_id, validated, requested_by="wlc-session-ingest")
    except HTTPException as exc:
        media_wlc_upsert_artifact(*base, ingest_state="failed", capture_id=capture_id,
                                  parser_status="failed", error_message=str(exc.detail),
                                  metadata={"failure_category": wlc_ingest.FAIL_PARSER_FAILED})
        return {"artifact_id": artifact_id, "session_id": session_id, "name": name,
                "state": "failed", "capture_id": capture_id, "detail": str(exc.detail)}

    status = parse.get("status")
    final_state = "parsed" if status == "complete" else "failed"
    metadata = {"parse_run_id": parse.get("parse_run_id"), "summary": parse.get("summary")}
    if final_state == "failed":
        metadata["failure_category"] = wlc_ingest.FAIL_PARSER_FAILED
    media_wlc_upsert_artifact(
        *base, ingest_state=final_state, capture_id=capture_id, parser_status=status,
        error_message=parse.get("error"),
        metadata=metadata,
    )
    return {"artifact_id": artifact_id, "session_id": session_id, "name": name,
            "state": final_state, "capture_id": capture_id, "parse_run_id": parse.get("parse_run_id")}


WLC_INGEST_MAX_RETRIES = 5


def media_wlc_retry_one(row: dict[str, str]) -> dict[str, Any]:
    """Re-drive one finalized-but-unparsed WLC EPC artifact.

    Reuses the existing capture_id when present (never re-imports or duplicates),
    never moves files, and bounds runaway retries of a deterministically-failing
    EPC. A parser-lock conflict (409) is transient: the artifact is left
    retryable for the next tick without burning a retry attempt.
    """

    artifact_id = row.get("artifact_id") or ""
    session_id = row.get("capture_session_id") or ""
    name = row.get("source_name") or ""
    final_path = row.get("final_path") or ""
    capture_id = row.get("capture_id") or None
    try:
        retry_count = int(row.get("retry_count") or 0)
    except (TypeError, ValueError):
        retry_count = 0
    base = (artifact_id, session_id, "wlc_epc", final_path, name)

    if retry_count >= WLC_INGEST_MAX_RETRIES:
        media_wlc_upsert_artifact(
            *base,
            ingest_state="failed",
            error_message="Retry limit reached; manual intervention required.",
            metadata={"retry_count": retry_count, "failure_category": wlc_ingest.FAIL_RETRY_LIMIT_REACHED},
        )
        return {"artifact_id": artifact_id, "session_id": session_id, "name": name,
                "state": "failed", "detail": "retry limit reached; manual intervention required"}

    try:
        validated = media_wlc_validate_session_capture(final_path, subdir=wlc_ingest.PCAPS_SUBDIR)
    except HTTPException as exc:
        media_wlc_upsert_artifact(*base, ingest_state="failed",
                                  error_message=f"Finalized file unavailable for retry: {exc.detail}",
                                  metadata={"retry_count": retry_count + 1,
                                            "failure_category": wlc_ingest.FAIL_PROMOTION_COPY_FAILED})
        return {"artifact_id": artifact_id, "session_id": session_id, "name": name,
                "state": "failed", "detail": "finalized file unavailable"}

    session_rows = media_query_rows(
        "select study_id from v_vocera_media_capture_sessions "
        f"where session_id = {sql_text(session_id)};"
    )
    study_id = (session_rows[0].get("study_id") if session_rows else None) or default_media_study_id()

    if not capture_id:
        try:
            registration = media_register_capture_record(
                study_id, validated, capture_point="wlc_epc",
                source_name=name, notes="WLC capture-session EPC auto-ingest (retry).",
            )
            capture_id = registration["capture_id"]
        except HTTPException as exc:
            media_wlc_upsert_artifact(*base, ingest_state="failed", error_message=str(exc.detail),
                                      metadata={"retry_count": retry_count + 1,
                                                "failure_category": wlc_ingest.FAIL_CAPTURE_REGISTRATION_FAILED})
            return {"artifact_id": artifact_id, "session_id": session_id, "name": name,
                    "state": "failed", "detail": str(exc.detail)}

    # Persist the capture_id and keep the artifact retryable so a transient
    # parser-lock conflict on the parse below does not strand it.
    media_wlc_upsert_artifact(*base, ingest_state="retry_pending", capture_id=capture_id)
    try:
        media_wlc_upsert_artifact(*base, ingest_state="parsing", capture_id=capture_id)
        parse = media_run_capture_parse(capture_id, study_id, validated, requested_by="wlc-session-ingest-retry")
    except HTTPException as exc:
        if exc.status_code == 409:
            media_wlc_upsert_artifact(*base, ingest_state="retry_pending", capture_id=capture_id)
            return {"artifact_id": artifact_id, "session_id": session_id, "name": name,
                    "state": "retry_pending", "detail": "parser busy; will retry next tick"}
        media_wlc_upsert_artifact(*base, ingest_state="failed", capture_id=capture_id, parser_status="failed",
                                  error_message=str(exc.detail), metadata={"retry_count": retry_count + 1,
                                                                           "failure_category": wlc_ingest.FAIL_PARSER_FAILED})
        return {"artifact_id": artifact_id, "session_id": session_id, "name": name,
                "state": "failed", "detail": str(exc.detail)}

    status = parse.get("status")
    final_state = "parsed" if status == "complete" else "failed"
    metadata = {"parse_run_id": parse.get("parse_run_id"), "summary": parse.get("summary")}
    if final_state == "failed":
        metadata["retry_count"] = retry_count + 1
        metadata["failure_category"] = wlc_ingest.FAIL_PARSER_FAILED
    media_wlc_upsert_artifact(*base, ingest_state=final_state, capture_id=capture_id,
                              parser_status=status, error_message=parse.get("error"), metadata=metadata)
    return {"artifact_id": artifact_id, "session_id": session_id, "name": name,
            "state": final_state, "retried": True, "parse_run_id": parse.get("parse_run_id")}


def media_wlc_retry_promoted_artifacts(
    *,
    session_id: str | None = None,
    exclude_artifact_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Re-drive WLC EPC artifacts stuck after finalization (register/parse failed).

    Finalization into pcaps/ happens before registration and parsing, so a
    transient DB/parser failure leaves the service-owned file in pcaps/ -- where
    the incoming scan never revisits it -- in state imported/failed. Quarantined
    and parsed artifacts are terminal and are not retried. Artifacts already
    handled in this same scan pass (``exclude_artifact_ids``) are skipped so they
    are not retried twice per tick.
    """

    if not media_execution_enabled():
        return []
    skip = exclude_artifact_ids or set()
    clause = f"and capture_session_id = {sql_text(session_id)} " if session_id else ""
    rows = media_query_rows(
        "select artifact_id, capture_session_id, source_name, final_path, capture_id, "
        "coalesce((metadata->>'retry_count')::int, 0) as retry_count "
        "from vocera_media_session_artifacts "
        "where artifact_kind = 'wlc_epc' "
        "and ingest_state in ('promoted', 'registered', 'imported', 'failed', 'retry_pending') "
        "and final_path is not null "
        f"{clause}"
        "order by updated_at asc;"
    )
    results: list[dict[str, Any]] = []
    for row in rows:
        if row.get("artifact_id") in skip:
            continue
        results.append(media_wlc_retry_one(row))
    return results


def media_wlc_terminal_output_paths(root: Path) -> list[tuple[str, str, Path]]:
    """Return output-only terminal logs under session cli/terminal directories."""

    paths: list[tuple[str, str, Path]] = []
    if not root.is_dir():
        return paths
    for candidate in sorted(root.glob("*/*/cli/terminal/*.out")):
        if not candidate.is_file():
            continue
        try:
            rel = candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
        except ValueError:
            continue
        parts = rel.parts
        if len(parts) != 5 or parts[2] != "cli" or parts[3] != "terminal":
            continue
        paths.append((parts[0], parts[1], candidate))
    return paths


def _media_wlc_existing_attempt(session_id: str, attempt_id: str | None) -> str | None:
    if not attempt_id:
        return None
    rows = media_query_rows(
        "select attempt_id from vocera_media_broadcast_attempts "
        f"where capture_session_id = {sql_text(session_id)} "
        f"and attempt_id = {sql_text(attempt_id)} limit 1;"
    )
    return rows[0].get("attempt_id") if rows else None


def _media_wlc_snapshot_id(artifact_id: str, attempt_id: str, phase: str, block_index: int) -> str:
    raw = f"{artifact_id}\x00{block_index}\x00{attempt_id}\x00{phase}".encode("utf-8")
    return "wlcsnap_" + hashlib.sha256(raw).hexdigest()[:24]


def _media_wlc_observation_id(artifact_id: str, block_index: int, index: int) -> str:
    raw = f"{artifact_id}\x00block\x00{block_index}\x00observation\x00{index}".encode("utf-8")
    return "wlcobs_" + hashlib.sha256(raw).hexdigest()[:24]


def media_wlc_store_snapshot(
    *,
    artifact_id: str,
    session_id: str,
    attempt_id: str,
    phase: str,
    block_index: int,
    parsed: dict[str, Any],
) -> None:
    """Store one high-confidence attempt-scoped WLC snapshot."""

    snapshot_id = _media_wlc_snapshot_id(artifact_id, attempt_id, phase, block_index)
    media_query_one(
        "insert into vocera_media_wlc_snapshots ("
        "snapshot_id, attempt_id, phase, snapshot_time, receiver_ap, receiver_bssid, "
        "receiver_channel, receiver_band, receiver_rssi, receiver_snr, receiver_vlan, "
        "sender_client_vlan, sender_multicast_vlan, receiver_client_vlan, receiver_multicast_vlan, "
        "receiver_group_member, receiver_group_status, vocera_group, vocera_dynamic_group_ip, "
        "vocera_dynamic_group_mac, vocera_group_evidence_confidence, vocera_vlan, configured_vocera_vlan, "
        "resolved_group_vlan, group_vlan, vlan_context_state, mgid, multicast_enabled, "
        "capwap_multicast_mode, ap_mom_status, igmp_snooping_enabled, igmp_querier_enabled, raw_snapshot"
        ") values ("
        f"{sql_text(snapshot_id)}, {sql_text(attempt_id)}, {sql_text(phase)}, {sql_text(parsed.get('snapshot_time'))}, "
        f"{sql_text(parsed.get('receiver_ap'))}, {sql_text(parsed.get('receiver_bssid'))}, "
        f"{sql_int(parsed.get('receiver_channel'))}, {sql_text(parsed.get('receiver_band'))}, "
        f"{sql_int(parsed.get('receiver_rssi'))}, {sql_int(parsed.get('receiver_snr'))}, {sql_int(parsed.get('receiver_vlan'))}, "
        f"{sql_int(parsed.get('sender_client_vlan'))}, {sql_int(parsed.get('sender_multicast_vlan'))}, "
        f"{sql_int(parsed.get('receiver_client_vlan'))}, {sql_int(parsed.get('receiver_multicast_vlan'))}, "
        f"{sql_bool(parsed.get('c1000_group_member'))}, {sql_text(parsed.get('c1000_member_status'))}, "
        f"{sql_text(parsed.get('vocera_group'))}, {sql_text(parsed.get('vocera_dynamic_group_ip'))}, "
        f"{sql_text(parsed.get('vocera_dynamic_group_mac'))}, {sql_text(parsed.get('vocera_group_evidence_confidence'))}, "
        f"{sql_int(parsed.get('vocera_vlan'))}, {sql_int(parsed.get('configured_vocera_vlan'))}, "
        f"{sql_int(parsed.get('resolved_group_vlan'))}, {sql_int(parsed.get('group_vlan'))}, "
        f"{sql_text(parsed.get('vlan_context_state'))}, {sql_int(parsed.get('mgid'))}, "
        f"{sql_bool(parsed.get('multicast_enabled'))}, {sql_text(parsed.get('capwap_multicast_mode'))}, "
        f"{sql_text(parsed.get('ap_mom_status'))}, {sql_bool(parsed.get('igmp_snooping_enabled'))}, "
        f"{sql_bool(parsed.get('igmp_querier_enabled'))}, {sql_text(parsed.get('raw_snapshot'))}"
        ") on conflict (snapshot_id) do update set "
        "phase = excluded.phase, snapshot_time = excluded.snapshot_time, "
        "receiver_ap = excluded.receiver_ap, receiver_bssid = excluded.receiver_bssid, "
        "receiver_channel = excluded.receiver_channel, receiver_band = excluded.receiver_band, "
        "receiver_rssi = excluded.receiver_rssi, receiver_snr = excluded.receiver_snr, "
        "receiver_vlan = excluded.receiver_vlan, sender_client_vlan = excluded.sender_client_vlan, "
        "sender_multicast_vlan = excluded.sender_multicast_vlan, receiver_client_vlan = excluded.receiver_client_vlan, "
        "receiver_multicast_vlan = excluded.receiver_multicast_vlan, receiver_group_member = excluded.receiver_group_member, "
        "receiver_group_status = excluded.receiver_group_status, vocera_group = excluded.vocera_group, "
        "vocera_dynamic_group_ip = excluded.vocera_dynamic_group_ip, vocera_dynamic_group_mac = excluded.vocera_dynamic_group_mac, "
        "vocera_group_evidence_confidence = excluded.vocera_group_evidence_confidence, vocera_vlan = excluded.vocera_vlan, "
        "configured_vocera_vlan = excluded.configured_vocera_vlan, resolved_group_vlan = excluded.resolved_group_vlan, "
        "group_vlan = excluded.group_vlan, vlan_context_state = excluded.vlan_context_state, mgid = excluded.mgid, "
        "multicast_enabled = excluded.multicast_enabled, capwap_multicast_mode = excluded.capwap_multicast_mode, "
        "ap_mom_status = excluded.ap_mom_status, igmp_snooping_enabled = excluded.igmp_snooping_enabled, "
        "igmp_querier_enabled = excluded.igmp_querier_enabled, raw_snapshot = excluded.raw_snapshot;"
    )


def media_wlc_update_attempt_from_snapshot(attempt_id: str, parsed: dict[str, Any]) -> None:
    """Copy high-confidence parsed WLC evidence onto the attempt summary row."""

    media_query_one(
        "update vocera_media_broadcast_attempts set "
        f"receiver_group_member = coalesce({sql_bool(parsed.get('c1000_group_member'))}, receiver_group_member), "
        f"dynamic_multicast_ip = coalesce({sql_text(parsed.get('vocera_dynamic_group_ip'))}, dynamic_multicast_ip), "
        f"dynamic_multicast_mac = coalesce({sql_text(parsed.get('vocera_dynamic_group_mac'))}, dynamic_multicast_mac), "
        f"vocera_group = coalesce({sql_text(parsed.get('vocera_group'))}, vocera_group), "
        f"vocera_vlan = coalesce({sql_int(parsed.get('vocera_vlan'))}, vocera_vlan), "
        f"resolved_group_ip = coalesce({sql_text(parsed.get('resolved_group_ip') or parsed.get('vocera_dynamic_group_ip'))}, resolved_group_ip), "
        f"resolved_group_vlan = coalesce({sql_int(parsed.get('resolved_group_vlan'))}, resolved_group_vlan), "
        f"resolved_mgid = coalesce({sql_int(parsed.get('mgid'))}, resolved_mgid), "
        f"vlan_context_state = coalesce({sql_text(parsed.get('vlan_context_state'))}, vlan_context_state), "
        "updated_at = now() "
        f"where attempt_id = {sql_text(attempt_id)};"
    )


def media_wlc_store_observations(
    *,
    artifact_id: str,
    session_id: str,
    attempt_id: str | None,
    phase: str,
    block_index: int,
    block_id: str,
    commands: list[str],
    observations: list[dict[str, Any]],
) -> int:
    """Store parsed multicast observations, session-scoped unless safely bound."""

    count = 0
    for index, observation in enumerate(observations):
        observation_id = _media_wlc_observation_id(artifact_id, block_index, index)
        raw = dict(observation)
        raw["artifact_id"] = artifact_id
        raw["block_id"] = block_id
        raw["block_index"] = block_index
        raw["block_observation_index"] = index
        raw["commands"] = commands
        raw["phase"] = phase
        media_query_one(
            "insert into vocera_media_multicast_observations ("
            "observation_id, capture_session_id, attempt_id, observed_at, phase, evidence_source, "
            "vocera_group_ip, vocera_group_mac, vocera_vlan, source_ip, source_mac, igmp_version, "
            "mgid, receiver_mac, receiver_ip, receiver_member, receiver_blocklisted, receiver_membership_mode, "
            "wlc_capwap_group, wlc_capwap_mode, ap_name, ap_mom_status, ap_mgid, ap_delivery_mode, "
            "ap_rx_packets, ap_tx_packets, ap_slot, capture_confidence, raw_evidence"
            ") values ("
            f"{sql_text(observation_id)}, {sql_text(session_id)}, {sql_text(attempt_id)}, now(), {sql_text(phase)}, "
            f"{sql_text(observation.get('evidence_source') or 'wlc_terminal_output')}, "
            f"{sql_text(observation.get('vocera_group_ip'))}, {sql_text(observation.get('vocera_group_mac'))}, "
            f"{sql_int(observation.get('vocera_vlan'))}, {sql_text(observation.get('source_ip'))}, "
            f"{sql_text(observation.get('source_mac'))}, {sql_text(observation.get('igmp_version'))}, "
            f"{sql_int(observation.get('mgid'))}, {sql_text(observation.get('receiver_mac'))}, "
            f"{sql_text(observation.get('receiver_ip'))}, {sql_bool(observation.get('receiver_member'))}, "
            f"{sql_bool(observation.get('receiver_blocklisted'))}, {sql_text(observation.get('receiver_membership_mode'))}, "
            f"{sql_text(observation.get('wlc_capwap_group'))}, {sql_text(observation.get('wlc_capwap_mode'))}, "
            f"{sql_text(observation.get('ap_name'))}, {sql_text(observation.get('ap_mom_status'))}, "
            f"{sql_int(observation.get('ap_mgid'))}, {sql_text(observation.get('ap_delivery_mode'))}, "
            f"{sql_int(observation.get('ap_rx_packets'))}, {sql_int(observation.get('ap_tx_packets'))}, "
            f"{sql_text(observation.get('ap_slot'))}, {sql_text(observation.get('capture_confidence') or 'unknown')}, "
            f"{media_jsonb(raw)}"
            ") on conflict (observation_id) do update set "
            "attempt_id = excluded.attempt_id, observed_at = excluded.observed_at, phase = excluded.phase, "
            "evidence_source = excluded.evidence_source, vocera_group_ip = excluded.vocera_group_ip, "
            "vocera_group_mac = excluded.vocera_group_mac, vocera_vlan = excluded.vocera_vlan, "
            "source_ip = excluded.source_ip, source_mac = excluded.source_mac, igmp_version = excluded.igmp_version, "
            "mgid = excluded.mgid, receiver_mac = excluded.receiver_mac, receiver_ip = excluded.receiver_ip, "
            "receiver_member = excluded.receiver_member, receiver_blocklisted = excluded.receiver_blocklisted, "
            "receiver_membership_mode = excluded.receiver_membership_mode, wlc_capwap_group = excluded.wlc_capwap_group, "
            "wlc_capwap_mode = excluded.wlc_capwap_mode, ap_name = excluded.ap_name, ap_mom_status = excluded.ap_mom_status, "
            "ap_mgid = excluded.ap_mgid, ap_delivery_mode = excluded.ap_delivery_mode, ap_rx_packets = excluded.ap_rx_packets, "
            "ap_tx_packets = excluded.ap_tx_packets, ap_slot = excluded.ap_slot, capture_confidence = excluded.capture_confidence, "
            "raw_evidence = excluded.raw_evidence;"
        )
        count += 1
    return count


def media_wlc_process_terminal_output(*, session_id: str, output_path: Path) -> dict[str, Any]:
    """Hash, register, parse, and persist one output-only terminal transcript."""

    artifact_id = wlc_ingest.artifact_id_for(session_id, "wlc_terminal_output", output_path.name)
    existing = media_wlc_session_artifact_row(artifact_id)
    sha = wlc_ingest.sha256_file(output_path)
    existing_metadata = existing.get("metadata", "") if existing else ""
    if (
        existing
        and existing.get("sha256") == sha
        and existing.get("ingest_state") == "parsed"
        and '"transcript_block_parser_version": 2' in existing_metadata
    ):
        return {"artifact_id": artifact_id, "session_id": session_id, "name": output_path.name,
                "state": "parsed", "detail": "already parsed"}

    text = output_path.read_text(encoding="utf-8", errors="replace")
    session = media_wlc_session_row(session_id)
    metadata_path = output_path.with_suffix(".json")
    recorder_metadata: dict[str, Any] = {}
    if metadata_path.is_file():
        try:
            recorder_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            recorder_metadata = {"metadata_parse_error": "invalid JSON"}

    blocks = wlc_cli.transcript_command_blocks(text)
    block_summaries: list[dict[str, Any]] = []
    total_observations = 0
    high_confidence_attempts: list[str] = []

    for block in blocks:
        block_index = int(block.get("block_index") or 0)
        block_id = str(block.get("block_id") or f"block-{block_index:04d}")
        phase = str(block.get("phase") or "unassigned")
        commands = [str(command) for command in (block.get("commands") or [])]
        explicit_attempt_ids = [str(attempt_id) for attempt_id in (block.get("attempt_ids") or [])]
        existing_attempts = [
            attempt_id
            for attempt_id in explicit_attempt_ids
            if _media_wlc_existing_attempt(session_id, attempt_id)
        ]
        attempt_id = existing_attempts[0] if len(explicit_attempt_ids) == 1 and len(existing_attempts) == 1 else None
        association_confidence = "high" if attempt_id else ("low" if explicit_attempt_ids else "session")
        parsed = wlc_cli.parse_wlc_snapshot(
            str(block.get("text") or ""),
            phase=phase,
            receiver_mac=session.get("receiver_mac"),
            sender_mac=session.get("sender_mac"),
            expected_vlan=int(session.get("configured_vocera_vlan") or 684),
        )
        if attempt_id:
            high_confidence_attempts.append(attempt_id)
            media_wlc_store_snapshot(
                artifact_id=artifact_id,
                session_id=session_id,
                attempt_id=attempt_id,
                phase=phase,
                block_index=block_index,
                parsed=parsed,
            )
            media_wlc_update_attempt_from_snapshot(attempt_id, parsed)
        observation_count = media_wlc_store_observations(
            artifact_id=artifact_id,
            session_id=session_id,
            attempt_id=attempt_id,
            phase=phase,
            block_index=block_index,
            block_id=block_id,
            commands=commands,
            observations=parsed.get("multicast_observations") or [],
        )
        total_observations += observation_count
        block_summaries.append(
            {
                "block_id": block_id,
                "block_index": block_index,
                "phase": phase,
                "commands": commands,
                "attempt_ids": explicit_attempt_ids,
                "attempt_id": attempt_id,
                "association_confidence": association_confidence,
                "observation_count": observation_count,
                "vocera_group": parsed.get("vocera_group"),
                "resolved_group_vlan": parsed.get("resolved_group_vlan"),
                "mgid": parsed.get("mgid"),
                "receiver_group_member": parsed.get("c1000_group_member"),
            }
        )

    media_wlc_upsert_artifact(
        artifact_id,
        session_id,
        "wlc_terminal_output",
        str(output_path),
        output_path.name,
        ingest_state="parsed",
        final_path=str(output_path),
        sha256=sha,
        size_bytes=output_path.stat().st_size,
        validated_at=True,
        parser_status="parsed",
        visibility_class="wlc_cli_evidence",
        metadata={
            "transcript_block_parser_version": 2,
            "block_count": len(block_summaries),
            "blocks": block_summaries,
            "high_confidence_attempt_ids": sorted(set(high_confidence_attempts)),
            "recorder": recorder_metadata,
        },
    )
    return {
        "artifact_id": artifact_id,
        "session_id": session_id,
        "name": output_path.name,
        "state": "parsed",
        "block_count": len(block_summaries),
        "observation_count": total_observations,
    }


def media_wlc_transcript_scan(*, session_id: str | None = None) -> list[dict[str, Any]]:
    """Scan output-only terminal logs and parse WLC evidence blocks."""

    root = media_wlc_session_root()
    results: list[dict[str, Any]] = []
    for _study_id, sess_id, output_path in media_wlc_terminal_output_paths(root):
        if session_id and sess_id != session_id:
            continue
        try:
            media_wlc_validate_id(sess_id, "session_id")
            media_wlc_session_row(sess_id)
            results.append(media_wlc_process_terminal_output(session_id=sess_id, output_path=output_path))
        except HTTPException as exc:
            results.append({"session_id": sess_id, "name": output_path.name, "state": "error", "detail": str(exc.detail)})
        except Exception as exc:  # noqa: BLE001 - keep one bad transcript from blocking EPC ingest.
            results.append({"session_id": sess_id, "name": output_path.name, "state": "error", "detail": str(exc)})
    return results


def media_wlc_ingest_scan(*, session_id: str | None = None) -> dict[str, Any]:
    """Scan every session package's incoming/ once and ingest stable EPCs.

    A second pass re-drives any artifact stranded after finalization so a
    transient failure recovers automatically without an operator moving files.
    """

    root = media_wlc_session_root()
    stability_seconds = media_wlc_ingest_stability_seconds()
    results: list[dict[str, Any]] = []
    sessions_seen: dict[str, dict[str, str] | None] = {}
    for incoming_pcap in wlc_ingest.iter_incoming_pcaps(root, allowed_extensions=media_allowed_extensions()):
        info = wlc_ingest.parse_session_rel(root, incoming_pcap)
        if info is None:
            continue
        sess_id = info["session_id"]
        if session_id and sess_id != session_id:
            continue
        try:
            media_wlc_validate_id(sess_id, "session_id")
        except HTTPException:
            results.append({"session_id": sess_id, "name": info["name"], "state": "skipped",
                            "detail": "invalid session id"})
            continue
        if sess_id not in sessions_seen:
            rows = media_query_rows(
                "select session_id, study_id from v_vocera_media_capture_sessions "
                f"where session_id = {sql_text(sess_id)};"
            )
            sessions_seen[sess_id] = rows[0] if rows else None
        session_row = sessions_seen[sess_id]
        if session_row is None:
            # The artifact foreign key requires a known capture session.
            results.append({"session_id": sess_id, "name": info["name"], "state": "skipped",
                            "detail": "unknown capture session"})
            continue
        resolved_study = session_row.get("study_id") or info["study_id"]
        try:
            outcome = media_wlc_process_incoming(
                study_id=resolved_study, session_id=sess_id, incoming_pcap=incoming_pcap,
                session_root=root, stability_seconds=stability_seconds,
            )
        except HTTPException as exc:
            outcome = {"session_id": sess_id, "name": info["name"], "state": "error",
                       "detail": str(exc.detail)}
        results.append(outcome)
    handled_ids = {item.get("artifact_id") for item in results if item.get("artifact_id")}
    retried = media_wlc_retry_promoted_artifacts(session_id=session_id, exclude_artifact_ids=handled_ids)
    transcripts = media_wlc_transcript_scan(session_id=session_id)
    return {
        "ok": True,
        "scanned": len(results),
        "retried": len(retried),
        "transcripts": len(transcripts),
        "stability_seconds": stability_seconds,
        "results": results + retried + transcripts,
    }


def media_require_local_request(request: Request) -> None:
    """Reject non-loopback callers for filesystem-scanning trigger endpoints.

    Study Web listens on 0.0.0.0, but the ingest scan walks the filesystem and
    can launch long parser runs, so only the local systemd timer (127.0.0.1 /
    ::1) may trigger it. The UI never needs to POST here -- it reads artifact
    status through the GET route while the timer performs the scan.
    """

    client = request.client
    host = client.host if client else None
    if host not in {"127.0.0.1", "::1", "::ffff:127.0.0.1"}:
        raise HTTPException(status_code=403, detail="The ingest-scan trigger is restricted to local callers.")


@app.post("/api/media-qoe/wlc/sessions/ingest-scan")
def media_qoe_wlc_session_ingest_scan(request: Request, payload: MediaWlcSessionIngestScan | None = None) -> dict[str, Any]:
    media_require_local_request(request)
    session_id = payload.session_id if payload else None
    if session_id:
        media_wlc_validate_id(session_id, "session_id")
    return media_wlc_ingest_scan(session_id=session_id)


@app.get("/api/media-qoe/wlc/sessions/{session_id}/artifacts")
def list_media_qoe_wlc_session_artifacts(session_id: str) -> dict[str, Any]:
    media_wlc_validate_id(session_id, "session_id")
    media_wlc_session_row(session_id)
    rows = media_query_rows(
        "select * from vocera_media_session_artifacts "
        f"where capture_session_id = {sql_text(session_id)} "
        "order by received_at desc, artifact_id;"
    )
    return {"ok": True, "artifacts": rows}


@app.patch("/api/media-qoe/streams/{capture_id}/{stream_id}")
def update_media_qoe_stream_review(capture_id: str, stream_id: str, payload: MediaStreamReviewPatch) -> dict[str, Any]:
    media_stream_row(capture_id, stream_id)
    data = model_data(payload)
    fields = model_fields_set(payload)
    assignments: list[str] = []

    if "accepted" in fields:
        assignments.append(f"accepted = {sql_bool(data.get('accepted'))}")
    if "stream_classification" in fields:
        classification = data.get("stream_classification")
        if classification is not None and classification not in MEDIA_STREAM_CLASSIFICATIONS:
            raise HTTPException(status_code=400, detail=f"Unsupported stream_classification: {classification}.")
        assignments.append(f"stream_classification = {sql_text(classification)}")
    if "review_status" in fields:
        review_status = data.get("review_status")
        if review_status is None:
            raise HTTPException(status_code=400, detail="review_status cannot be null.")
        if review_status not in MEDIA_REVIEW_STATUSES:
            raise HTTPException(status_code=400, detail=f"Unsupported review_status: {review_status}.")
        assignments.append(f"review_status = {sql_text(review_status)}")
    if "review_notes" in fields:
        assignments.append(f"review_notes = {sql_text(data.get('review_notes'))}")

    if not assignments:
        raise HTTPException(status_code=400, detail="No stream review fields were provided.")

    assignments.extend(["reviewed_at = now()", f"reviewed_by = {sql_text(user())}"])
    row = media_query_one(
        "update vocera_media_stream_samples "
        f"set {', '.join(assignments)} "
        f"where capture_id = {sql_text(capture_id)} "
        f"and stream_id = {sql_text(stream_id)} "
        "returning capture_id, stream_id;"
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"No media QoE stream found for {capture_id}/{stream_id}.")
    return {"ok": True, "stream": media_stream_row(capture_id, stream_id)}


def grafana_external_path() -> str:
    parsed = urllib.parse.urlparse(grafana_base_path())
    path = parsed.path if parsed.scheme else grafana_base_path()
    return path.rstrip("/") or "/grafana"


def grafana_target_url(grafana_path: str, query_string: str) -> str:
    clean_path = grafana_path.lstrip("/")
    if env_bool("STUDY_WEB_GRAFANA_PROXY_STRIP_BASE_PATH", False):
        upstream_path = f"/{clean_path}" if clean_path else "/"
    else:
        base_path = grafana_external_path()
        upstream_path = f"{base_path}/{clean_path}" if clean_path else base_path
    target = f"{grafana_upstream()}{upstream_path}"
    if query_string:
        target = f"{target}?{query_string}"
    return target


def rewrite_grafana_location(value: str) -> str:
    upstream = grafana_upstream()
    base_path = grafana_external_path()
    if value.startswith(upstream):
        upstream_path = value[len(upstream):] or "/"
        if upstream_path.startswith(base_path):
            return upstream_path
        path_suffix = upstream_path if upstream_path.startswith("/") else f"/{upstream_path}"
        return f"{base_path}{path_suffix}"
    if value.startswith("/") and not value.startswith(f"{base_path}/") and value != base_path:
        return f"{base_path}{value}"
    return value


def rewrite_grafana_cookie(value: str) -> str:
    base_path = grafana_external_path()
    if re.search(r"(?i)(^|;\s*)Path=/($|;)", value):
        return re.sub(r"(?i)Path=/($|;)", f"Path={base_path}\\1", value)
    return value


def grafana_request_headers(request: Request) -> dict[str, str]:
    parsed_upstream = urllib.parse.urlparse(grafana_upstream())
    headers: dict[str, str] = {}
    for key, value in request.headers.items():
        lower = key.lower()
        if lower in HOP_BY_HOP_HEADERS or lower in {"host", "content-length", "accept-encoding"}:
            continue
        headers[key] = value
    if parsed_upstream.netloc:
        headers["Host"] = parsed_upstream.netloc
    if request.headers.get("host"):
        headers["X-Forwarded-Host"] = request.headers["host"]
    headers["X-Forwarded-Proto"] = request.url.scheme
    headers["X-Forwarded-Prefix"] = grafana_external_path()
    return headers


@app.api_route("/grafana", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"], include_in_schema=False)
@app.api_route("/grafana/{grafana_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"], include_in_schema=False)
async def grafana_proxy(request: Request, grafana_path: str = "") -> Response:
    if not env_bool("STUDY_WEB_GRAFANA_PROXY_ENABLED", True):
        raise HTTPException(status_code=404, detail="Grafana proxy is disabled.")
    upstream = grafana_upstream()
    if not upstream:
        raise HTTPException(status_code=502, detail="Grafana upstream is not configured.")

    body = b"" if request.method in {"GET", "HEAD"} else await request.body()
    target = grafana_target_url(grafana_path, request.url.query)
    upstream_request = urllib.request.Request(
        target,
        data=body if body else None,
        headers=grafana_request_headers(request),
        method=request.method,
    )
    try:
        upstream_response = urllib.request.urlopen(upstream_request, timeout=float(os.environ.get("STUDY_WEB_GRAFANA_PROXY_TIMEOUT_SECONDS", "30")))
        status_code = upstream_response.status
        upstream_headers = upstream_response.headers
        content = upstream_response.read()
    except urllib.error.HTTPError as exc:
        status_code = exc.code
        upstream_headers = exc.headers
        content = exc.read()
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=502, detail=f"Grafana upstream unavailable: {exc.reason}") from exc

    response = Response(content=b"" if request.method == "HEAD" else content, status_code=status_code)
    for header in upstream_headers.keys():
        lower = header.lower()
        if lower in HOP_BY_HOP_HEADERS or lower in {"content-length", "content-encoding"}:
            continue
        for value in upstream_headers.get_all(header, []):
            if lower == "location":
                value = rewrite_grafana_location(value)
            elif lower == "set-cookie":
                value = rewrite_grafana_cookie(value)
            response.headers.append(header, value)
    return response


if STATIC_DIR.exists():
    assets_dir = STATIC_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str) -> FileResponse:
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    raise HTTPException(
        status_code=503,
        detail=f"Study UI has not been built yet. Build web/study-ui and copy dist/ to {STATIC_DIR}.",
    )
