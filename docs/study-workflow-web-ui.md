# Study Workflow Web UI

This web UI moves RF validation, ICAP QoE, and Vocera multicast investigation workflows out of raw Grafana forms and into a collector-hosted application.

ICAP QoE and Vocera multicast are intentionally separate top-level pages. ICAP QoE handles completed Catalyst Center ICAP downloads, imported PCAP registration, parsing, stream review, and ICAP-related Grafana context. Vocera multicast handles manual WLC EPC capture sessions, heard/missed/partial/choppy event markers, and multicast delivery evidence for V5000 to C1000 troubleshooting.

Manual WLC capture sessions are managed under Vocera multicast -> Vocera Multicast Capture Sessions.
The web app generates command sheets, records heard/missed/partial/choppy event
markers, and stores session rows without collecting WLC or SCP passwords.
The configured Vocera multicast VLAN defaults to 684 and is tracked separately
from observed badge-side VLANs and the resolved active group VLAN.
Attempt-only package ingest remains available for older evidence bundles.

## Layout

```text
tools/study_web/                 FastAPI backend and static build output
tools/vocera_rf_validation/      Existing RF parser, correlation, and SQL helpers
web/study-ui/                    React + TypeScript + Vite + Tailwind frontend
systemd/vocera-rf-validation-study-web.service
scripts/install_vocera_rf_validation_study_web.sh
```

The old standard-library RF study web app remains available as:

```bash
make vocera-rf-validation-study-web-legacy
```

## Build frontend

```bash
cd /home/appsadmin/grafana-mimir-observability
make study-web-frontend-build
```

This runs `npm install`, builds the Vite app, and copies `web/study-ui/dist/` into `tools/study_web/static/`.

## Run locally on the collector

```bash
cd /home/appsadmin/grafana-mimir-observability
PYTHONPATH=tools python3 -m uvicorn study_web.main:app --host 0.0.0.0 --port 8097
```

## Install as a service

```bash
cd /home/appsadmin/grafana-mimir-observability
sudo bash scripts/install_vocera_rf_validation_study_web.sh --install-python-deps --enable --start-now
```

The installer creates `.venv-study-web`, installs FastAPI/Uvicorn there, builds the frontend when `npm` is available, copies the systemd unit, and restarts the service.

## API endpoints

```text
GET  /api/health
GET  /api/config
GET  /api/backend-status
GET  /api/rf/summary
GET  /api/rf/current-study
GET  /api/rf/live-runs
GET  /api/rf/archives
GET  /api/rf/archive-selection
POST /api/rf/current-study
POST /api/rf/current-study/action
POST /api/rf/archive/update
POST /api/rf/archive/delete
POST /api/rf/archive-selection/clear
POST /api/rf/archive-selection/combine
GET  /api/media-qoe/summary
```

The RF summary endpoint intentionally skips archive-selection queries unless backend status is `ready`. This avoids the previous first-run behavior where the page queried missing tables/views and displayed noisy relation errors.

## Grafana embedding

The React app can embed Grafana `d-solo` panels. The systemd unit exposes these optional environment variables:

```ini
Environment=STUDY_WEB_GRAFANA_BASE_PATH=/grafana
Environment=STUDY_WEB_GRAFANA_ORG_ID=1
Environment=STUDY_WEB_GRAFANA_THEME=dark
Environment=STUDY_WEB_GRAFANA_AP_VOICE_LATENCY_UID=platform-wireless-rf
Environment=STUDY_WEB_GRAFANA_AP_VOICE_LATENCY_SLUG=platform-wireless-rf-dashboard
Environment=STUDY_WEB_GRAFANA_AP_VOICE_LATENCY_PANEL_ID=12
Environment=STUDY_WEB_GRAFANA_TX_RETRY_UID=platform-wireless-rf
Environment=STUDY_WEB_GRAFANA_TX_RETRY_SLUG=platform-wireless-rf-dashboard
Environment=STUDY_WEB_GRAFANA_TX_RETRY_PANEL_ID=18
Environment=STUDY_WEB_GRAFANA_MEDIA_QOE_UID=vocera-media-qoe
Environment=STUDY_WEB_GRAFANA_MEDIA_QOE_SLUG=vocera-media-qoe
Environment=STUDY_WEB_GRAFANA_MEDIA_QOE_PANEL_ID=1
```

For iframe embedding, Grafana must allow embedding and the browser must have a valid Grafana session or the Grafana path must be published read-only behind your internal reverse proxy.
