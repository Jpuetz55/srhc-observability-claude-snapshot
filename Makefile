.PHONY: help validate plan deploy release status mimir-install mimir-health dashboard-sync-prod-to-dev test test-rf-validation test-pcap-study kustomize-validate wireless-rf-textfile-install wireless-rf-parse wireless-rf-verify-parse wireless-rf-status wireless-rf-smoke-test vocera-dashboard-audit wireless-rf-web wireless-badge-collect wireless-badge-parse wireless-badge-web wireless-rf-install-textfile wireless-rf-install-hourly path-probe-run path-probe-install vocera-survey-refresh vocera-survey-rollback ipad-rf-validation-run ipad-rf-validation-process vocera-media-qoe-parse vocera-media-qoe-dnac-download vocera-media-qoe-dnac-check-api vocera-media-qoe-wlc-attempt-init vocera-media-qoe-wlc-attempt-record vocera-media-qoe-wlc-attempt-validate vocera-media-qoe-wlc-attempt-ingest vocera-media-qoe-wlc-attempt-report vocera-media-qoe-wlc-attempt-list vocera-media-qoe-wlc-session-init vocera-media-qoe-wlc-session-smoke-init vocera-media-qoe-wlc-session-console vocera-media-qoe-wlc-session-mark vocera-media-qoe-wlc-session-report vocera-media-qoe-wlc-session-list vocera-media-qoe-publish vocera-media-qoe-install vocera-media-qoe-wlc-session-ingest-install vocera-media-qoe-postgres-install vocera-media-qoe-install-db vocera-media-qoe-emit-sql vocera-media-qoe-load-db vocera-media-qoe-data-audit vocera-iperf-qoe-parse vocera-iperf-qoe-install vocera-rf-validation-postgres-install vocera-rf-validation-install-db vocera-rf-validation-study vocera-rf-validation-study-web vocera-rf-validation-study-web-install vocera-rf-validation-parse-badge vocera-rf-validation-inspect-ekahau vocera-rf-validation-parse-ekahau vocera-rf-validation-manual-template vocera-rf-validation-correlate vocera-rf-validation-emit-sql vocera-rf-validation-load-db vocera-rf-validation-all vocera-rf-validation-test topology-postgres-install topology-validate topology-publish topology-publish-dnac topology-load topology-load-poc topology-load-dnac topology-load-dry-run topology-publish-load topology-publish-load-dnac study-web-frontend-build vocera-rf-validation-study-web-legacy

# Ensure the repository root is on PYTHONPATH so `python3 -m ...` module targets
# and the test scripts resolve the top-level `tools` package from a clean
# checkout, independent of any inherited PYTHONPATH. Target-specific overrides
# below prepend their tool directories ahead of this root.
export PYTHONPATH := .$(if $(PYTHONPATH),:$(PYTHONPATH),)

# Operator-facing defaults. Scheduled jobs and ad-hoc runs can override any of
# these with environment variables or explicit make arguments.
INPUT ?= data/wireless-rf/raw/wlc_rf_raw.txt
WLC ?= unknown
BAND ?= 5ghz
SITE_TAG_REGEX ?=
AP_NAME_REGEX ?=
RF_OUT_DIR ?= data/wireless-rf/out
RF_CSV_OUT ?= $(RF_OUT_DIR)/wlc_rf_snapshot.csv
RF_JSON_OUT ?= $(RF_OUT_DIR)/wlc_rf_summary.json
RF_PROM_OUT ?= $(RF_OUT_DIR)/wlc_rf.prom
RF_SQLITE_DB ?= data/wireless-rf/wlc_rf.sqlite
BADGE_CONFIG ?= config/badge-client-observability.yaml
BADGE_INPUT ?= data/wireless-rf/raw/badge_client_raw.json
RF_VERIFY_AP ?=
RF_VERIFY_SLOT ?=
RF_VERIFY_ACCESS_CATEGORY ?= voice
RF_VERIFY_CLIENT_GENERATION ?=
RF_VERIFY_WLC ?=
VOCERA_DASHBOARD ?= grafana/dashboards-prod/Platform - Wireless RF/vocera-badge-80211r-impact__vocera_badge_80211r_impact.json
MIMIR_PROM_URL ?= http://127.0.0.1:9009/prometheus
MIMIR_ORG_ID ?= observability
DEPLOY_PROM_URL ?= http://127.0.0.1:9090
DEPLOY_MIMIR_URL ?= http://127.0.0.1:9009
DEPLOY_GRAFANA_URL ?= http://127.0.0.1:3000
PATH_PROBE_CONFIG ?= config/path-probe.example.yaml
PATH_PROBE_PROM_OUT ?= data/path-probe/out/path_probe.prom
PATH_PROBE_JSON_OUT ?= data/path-probe/out/path_probe_summary.json
PATH_PROBE_JOB ?=
VOCERA_MEDIA_QOE_CONFIG ?= config/vocera-media-qoe.yaml
VOCERA_MEDIA_QOE_PCAP ?= data/vocera-media-qoe/raw/example.pcap
VOCERA_MEDIA_QOE_PUBLISH_PCAP ?=
VOCERA_MEDIA_QOE_RAW_DIR ?= /var/lib/vocera-media-qoe/raw
VOCERA_MEDIA_QOE_PROM_OUT ?= data/vocera-media-qoe/out/vocera_media_qoe.prom
VOCERA_MEDIA_QOE_JSON_OUT ?= data/vocera-media-qoe/out/vocera_media_qoe_summary.json
VOCERA_MEDIA_QOE_PARSED_DIR ?= data/vocera-media-qoe/out/captures
VOCERA_MEDIA_QOE_SQL_OUT ?= data/vocera-media-qoe/out/vocera_media_qoe_import.sql
VOCERA_MEDIA_QOE_ARCHIVE_DIR ?= data/vocera-media-qoe/out/archives
VOCERA_MEDIA_QOE_DATABASE_URL ?=
VOCERA_MEDIA_QOE_PSQL_BIN ?= psql
VOCERA_MEDIA_QOE_ENV_FILE ?= /etc/grafana-mimir-observability/secrets/dnac-readonly.env
VOCERA_MEDIA_QOE_DNAC_CLIENT_MAC ?=
VOCERA_MEDIA_QOE_DNAC_AP_MAC ?=
VOCERA_MEDIA_QOE_DNAC_CAPTURE_TYPE ?= FULL
VOCERA_MEDIA_QOE_DNAC_LOOKBACK_MINUTES ?= 0
VOCERA_MEDIA_QOE_DNAC_LIMIT ?= 20
VOCERA_MEDIA_QOE_DNAC_INSECURE ?= 0
VOCERA_MEDIA_QOE_WLC_ATTEMPT_ROOT ?= /var/lib/vocera-media-qoe/raw/wlc-attempts
VOCERA_MEDIA_QOE_WLC_SESSION_ROOT ?= /var/lib/vocera-media-qoe/raw/wlc-sessions
# Guard against silently overwriting an existing capture-session package. The
# session-init CLI refuses to overwrite unless --force is passed; keep that off
# by default and enable it only with an explicit WLC_SESSION_FORCE=1/yes/true.
WLC_SESSION_FORCE ?= 0
# Extra flags passed to the WLC session-ingest installer, e.g. --start-now or
# --no-enable (the installer enables and starts the one-minute timer by default).
WLC_SESSION_INGEST_INSTALL_ARGS ?=
STUDY_ID ?= study_v5000_c1000_multicast
ATTEMPT_ID ?=
ATTEMPT_DIR ?=
SESSION_ID ?=
SESSION_DIR ?=
WLC_NAME ?=
# Blank by default so the session CLI generates a unique, WLC-safe capture name
# (PREFIX_YYMMDD_HHMM_XXXX). A static default eventually collides on the
# controller and across concurrent sessions.
WLC_CAPTURE_NAME ?=
WLC_INTERFACE ?=
CAPTURE_FILTER_MODE ?= vocera_pool_control
COLLECTOR_HOST ?=
COLLECTOR_SCP_USERNAME ?=
COLLECTOR_SCP_PORT ?= 22
RING_FILE_COUNT ?= 5
RING_FILE_SIZE_MB ?= 100
WLC_CAPTURE_MODE ?= long_reproduction
WLC_SHORT_VALIDATION_DURATION_SECONDS ?= 90
WLC_SSH_HOST ?= $(WLC_NAME)
WLC_SSH_USER ?=
WLC_SSH_PORT ?= 22
VOCERA_MULTICAST_POOL ?= 230.230.0.0/20
V5000_MAC ?=
V5000_IP ?=
C1000_MAC ?=
C1000_IP ?=
VOCERA_VLAN ?= 684
EXPECTED_DSCP ?= 46
OPERATOR ?= $(USER)
AUDIO_RESULT ?= unknown
ALERT_RESULT ?= unknown
OPERATOR_NOTES ?=
TEXTFILE_COLLECTOR_DIR ?= /var/lib/node_exporter/textfile_collector
VOCERA_IPERF_QOE_CONFIG ?= config/vocera-iperf-qoe.example.yaml
VOCERA_IPERF_QOE_INCOMING_ROOT ?= /var/lib/vocera-iperf-qoe/incoming
VOCERA_IPERF_QOE_PROM_OUT ?= data/vocera-iperf-qoe/out/vocera_iperf_qoe.prom
VOCERA_IPERF_QOE_JSON_OUT ?= data/vocera-iperf-qoe/out/vocera_iperf_qoe_summary.json
VOCERA_RF_VALIDATION_CONFIG ?= config/vocera-rf-validation.yaml
VOCERA_RF_VALIDATION_TEST_RUN_ID ?= srhc_vocera_ekahau_manual
VOCERA_RF_VALIDATION_BADGE_INPUT ?= /var/lib/vocera-rf-validation/raw/client_diag/sys
VOCERA_RF_VALIDATION_BADGE_MAC ?=
VOCERA_RF_VALIDATION_BADGE_MODEL ?=
VOCERA_RF_VALIDATION_EKAHAU_JSON ?= /var/lib/vocera-rf-validation/raw/ekahau_export.json
VOCERA_RF_VALIDATION_OUT_DIR ?= data/vocera-rf-validation/out
VOCERA_RF_VALIDATION_BADGE_JSON ?= $(VOCERA_RF_VALIDATION_OUT_DIR)/badge_scan_events.json
VOCERA_RF_VALIDATION_EKAHAU_POINTS_JSON ?= $(VOCERA_RF_VALIDATION_OUT_DIR)/ekahau_survey_points.json
VOCERA_RF_VALIDATION_MANUAL_TEMPLATE ?= $(VOCERA_RF_VALIDATION_OUT_DIR)/manual_ekahau_observations_template.csv
VOCERA_RF_VALIDATION_MANUAL_CSV ?= $(VOCERA_RF_VALIDATION_MANUAL_TEMPLATE)
VOCERA_RF_VALIDATION_MATCHES_JSON ?= $(VOCERA_RF_VALIDATION_OUT_DIR)/badge_ekahau_matches.json
VOCERA_RF_VALIDATION_MATCHES_CSV ?= $(VOCERA_RF_VALIDATION_OUT_DIR)/badge_ekahau_matches.csv
VOCERA_RF_VALIDATION_SQL_OUT ?= $(VOCERA_RF_VALIDATION_OUT_DIR)/vocera_rf_validation_import.sql
VOCERA_RF_VALIDATION_ARCHIVE_DIR ?= $(VOCERA_RF_VALIDATION_OUT_DIR)/archives
VOCERA_RF_VALIDATION_POSTGRES_PASSWORD ?=
VOCERA_RF_VALIDATION_DATABASE_URL ?= $(if $(VOCERA_RF_VALIDATION_POSTGRES_PASSWORD),postgresql://vocera_rf_validation:$(VOCERA_RF_VALIDATION_POSTGRES_PASSWORD)@127.0.0.1:15433/vocera_rf_validation,)
VOCERA_RF_VALIDATION_PSQL_BIN ?= scripts/vocera_rf_validation_psql_in_container.sh
IPAD_RF_VALIDATION_CONFIG ?= config/ipad-rf-validation.yaml
IPAD_RF_VALIDATION_RUN_ID ?=
IPAD_RF_VALIDATION_CLIENT_MAC ?=
IPAD_RF_VALIDATION_CLIENT_MODEL ?= iPad
IPAD_RF_VALIDATION_EKAHAU_PROJECT ?=
IPAD_RF_VALIDATION_OUT_DIR ?=
IPAD_RF_VALIDATION_ARCHIVE_DIR ?= data/ipad-rf-validation/out/archives
IPAD_RF_VALIDATION_INSTALL_DB ?= 1
IPAD_RF_VALIDATION_LOAD_DB ?= 1
IPAD_RF_VALIDATION_DATABASE_URL ?= $(VOCERA_RF_VALIDATION_DATABASE_URL)
IPAD_RF_VALIDATION_PSQL_BIN ?= $(VOCERA_RF_VALIDATION_PSQL_BIN)
VOCERA_SURVEY_ROLLBACK_RUN_ID ?=
VOCERA_SURVEY_ROLLBACK_ARGS ?=
NETWORK_TOPOLOGY_REPO ?= ../Network-Topology
TOPOLOGY_INPUT_DIR ?= $(NETWORK_TOPOLOGY_REPO)/data/working
TOPOLOGY_PUBLISHED_DIR ?= $(NETWORK_TOPOLOGY_REPO)/data/published
TOPOLOGY_POC_DIR ?= data/network-topology/poc
TOPOLOGY_SCHEMA_SQL ?= topology/postgres/init/001_topology_tables.sql
TOPOLOGY_NETBOX_BASE_URL ?= http://localhost:8000
TOPOLOGY_NODE_CONFIDENCE_HIGH_DAYS ?= 7
TOPOLOGY_NODE_CONFIDENCE_MEDIUM_DAYS ?= 30
TOPOLOGY_AS_OF_DATE ?=
TOPOLOGY_POSTGRES_HOST ?= 127.0.0.1
TOPOLOGY_POSTGRES_PORT ?= 15432
TOPOLOGY_POSTGRES_DB ?= topology
TOPOLOGY_POSTGRES_USER ?= topology
TOPOLOGY_PSQL_BIN ?= scripts/topology_psql_in_container.sh
TOPOLOGY_DNAC_ENV_FILE ?= /etc/grafana-mimir-observability/secrets/dnac-readonly.env
TOPOLOGY_DNAC_PUBLISHED_DIR ?= data/network-topology/dnac
TOPOLOGY_DNAC_RAW_DIR ?= data/network-topology/dnac/raw
TOPOLOGY_DNAC_ENVIRONMENT ?= prod
TOPOLOGY_DNAC_SOURCE_LINEAGE ?= dnac_physical_topology
TOPOLOGY_DNAC_PAGE_LIMIT ?= 500
TOPOLOGY_DNAC_INSECURE ?= 0

# Help is intentionally explicit because several targets touch local services
# or write generated artifacts.
help:
	@echo "Targets:"
	@echo "  make validate                  Run repo preflight checks"
	@echo "  make plan                      Dry-run promotion to PROD"
	@echo "  make deploy                    Promote repo -> PROD"
	@echo "  make release MSG='...'         Export DEV dashboards, validate, and promote"
	@echo "  make status                    Show DEV / repo / PROD dashboard status"
	@echo "  make mimir-install             Install/start local VM Mimir service"
	@echo "  make mimir-health              Check local Mimir readiness"
	@echo "  make dashboard-sync-prod-to-dev Reseed editable DEV org from PROD files"
	@echo "  make test                      Run repo validation tests"
	@echo "  make kustomize-validate        Build Kubernetes base/dev/prod overlays"
	@echo "  make wireless-rf-textfile-install Install wireless RF textfile systemd timer"
	@echo "  make wireless-rf-parse INPUT=... WLC=..."
	@echo "  make wireless-rf-verify-parse Verify raw WLC CLI values match generated .prom metrics"
	@echo "  make wireless-rf-status        Inspect wireless RF collector, textfile, and query path"
	@echo "  make wireless-rf-smoke-test    Run parse/publish/query smoke test from an existing raw file"
	@echo "  make vocera-dashboard-audit    Query every Vocera dashboard panel expression from Mimir"
	@echo "  make wireless-rf-web           Run optional Streamlit RF report UI"
	@echo "  make wireless-rf-install-textfile Install parser-only systemd service/timer"
	@echo "  make wireless-rf-install-hourly Install parse+publish hourly service/timer"
	@echo "  make wireless-badge-collect    Collect explicit badge client details"
	@echo "  make wireless-badge-parse      Parse badge client raw JSON"
	@echo "  make wireless-badge-web        Run optional Streamlit badge client UI"
	@echo "  make path-probe-run            Run RTT/loss/delay-variation probes and write Prometheus textfile"
	@echo "  make path-probe-install        Install path probe systemd service/timer without enabling it"
	@echo "  make vocera-survey-refresh     Hard-coded SRHC Vocera ICAP + badge/Ekahau parse refresh"
	@echo "  make vocera-survey-rollback VOCERA_SURVEY_ROLLBACK_RUN_ID=... Roll back one survey parser run"
	@echo "  sudo make ipad-rf-validation-run IPAD_RF_VALIDATION_CLIENT_MAC=... IPAD_RF_VALIDATION_EKAHAU_PROJECT=... Process manually collected iPad WLC scan-report snapshots"
	@echo "  sudo make ipad-rf-validation-process IPAD_RF_VALIDATION_RUN_ID=... IPAD_RF_VALIDATION_EKAHAU_PROJECT=... Process/load existing iPad snapshots"
	@echo "  make vocera-media-qoe-parse    Analyze an offline Vocera media pcap"
	@echo "  make vocera-media-qoe-dnac-download VOCERA_MEDIA_QOE_DNAC_CLIENT_MAC=... Download newest DNAC ICAP pcap for client"
	@echo "  make vocera-media-qoe-dnac-check-api VOCERA_MEDIA_QOE_DNAC_CLIENT_MAC=... Check read/download DNAC ICAP API readiness"
	@echo "  make vocera-media-qoe-wlc-attempt-init ATTEMPT_ID=... V5000_MAC=... C1000_MAC=... Create manual WLC attempt package"
	@echo "  make vocera-media-qoe-wlc-attempt-ingest ATTEMPT_DIR=... Validate/manual-ingest WLC attempt evidence"
	@echo "  make vocera-media-qoe-wlc-session-init SESSION_ID=... WLC_INTERFACE=... COLLECTOR_HOST=... Create long-running manual WLC session package"
	@echo "  make vocera-media-qoe-wlc-session-smoke-init SESSION_ID=... Create 90-second WLC EPC smoke package"
	@echo "  make vocera-media-qoe-wlc-session-console SESSION_DIR=... WLC_SSH_USER=... Open output-recorded manual WLC SSH console"
	@echo "  make vocera-media-qoe-publish  Parse unprocessed media pcaps and publish latest node_exporter textfile"
	@echo "  make vocera-media-qoe-install  Install media PCAP QoE textfile systemd service/timer"
	@echo "  make vocera-media-qoe-postgres-install Install/start media QoE PostgreSQL container"
	@echo "  make vocera-media-qoe-install-db Apply media QoE PostgreSQL schema/views"
	@echo "  make vocera-media-qoe-emit-sql Emit media QoE PostgreSQL import SQL from parsed captures"
	@echo "  make vocera-media-qoe-load-db Load media QoE capture-time history into PostgreSQL"
	@echo "  make vocera-iperf-qoe-parse    Publish uploaded laptop iperf JSON as Prometheus textfile"
	@echo "  make vocera-iperf-qoe-install  Install iperf QoE textfile systemd service/timer"
	@echo "  make vocera-rf-validation-postgres-install Install/start RF validation PostgreSQL container"
	@echo "  make vocera-rf-validation-study Interactive manager for named RF validation studies"
	@echo "  make vocera-rf-validation-study-web Run FastAPI/React study workflow web UI"
	@echo "  make vocera-rf-validation-study-web-install Install/start study workflow web UI service"
	@echo "  make study-web-frontend-build Build React/Vite/Tailwind static assets"
	@echo "  make vocera-rf-validation-all  Parse badge sys + Ekahau JSON timestamps and write manual RSSI/SNR template"
	@echo "  make vocera-rf-validation-correlate Complete calibrated deltas after manual RSSI/SNR CSV entry"
	@echo "  make vocera-rf-validation-emit-sql Emit PostgreSQL import SQL for parsed RF validation artifacts"
	@echo "  make topology-postgres-install Install/start local topology PostgreSQL container service"
	@echo "  make topology-validate         Validate canonical data in ../Network-Topology"
	@echo "  make topology-publish          Publish Network-Topology data for Grafana Node Graph"
	@echo "  make topology-publish-dnac     Publish Catalyst Center physical topology for Grafana Node Graph"
	@echo "  make topology-load             Load published topology CSVs into PostgreSQL"
	@echo "  make topology-load-poc         Load repo-local POC topology CSVs into PostgreSQL"
	@echo "  make topology-load-dnac        Load Catalyst Center published topology CSVs into PostgreSQL"
	@echo "  make topology-load-dry-run     Validate topology load inputs without connecting"

validate:
	bash ./scripts/pipeline.sh validate

plan:
# Dry-run the same promotion path used by deploy.
	PROM_URL="$(DEPLOY_PROM_URL)" MIMIR_URL="$(DEPLOY_MIMIR_URL)" GRAFANA_URL="$(DEPLOY_GRAFANA_URL)" bash ./scripts/pipeline.sh plan

deploy:
# Promote repo-managed runtime config and dashboards after validation.
	PROM_URL="$(DEPLOY_PROM_URL)" MIMIR_URL="$(DEPLOY_MIMIR_URL)" GRAFANA_URL="$(DEPLOY_GRAFANA_URL)" bash ./scripts/pipeline.sh deploy

release:
	PROM_URL="$(DEPLOY_PROM_URL)" MIMIR_URL="$(DEPLOY_MIMIR_URL)" GRAFANA_URL="$(DEPLOY_GRAFANA_URL)" bash ./scripts/release.sh -m "$(MSG)"

status:
	bash ./scripts/status.sh

mimir-install:
	sudo bash ./scripts/install_mimir_local_vm.sh

mimir-health:
	curl -fsS http://127.0.0.1:9009/ready

dashboard-sync-prod-to-dev:
	bash ./scripts/sync_prod_to_dev.sh

test:
	python3 ./scripts/check_dashboards.py
	python3 ./scripts/check_dashboard_inventory.py
	python3 ./scripts/check_topology_dashboard.py
	python3 ./scripts/test_check_dashboards.py
	python3 ./scripts/test_common_config.py
	python3 ./scripts/test_common_dashboard.py
	python3 ./scripts/test_common_files.py
	python3 ./scripts/test_common_prometheus.py
	python3 ./scripts/check_contract_schema.py
	python3 ./scripts/check_dashboard_metric_contract.py
	python3 ./scripts/check_metric_name_overlap.py
	python3 ./scripts/test_dnac_readonly_contract.py
	PYTHONPATH=.:tools/wireless_rf python3 ./scripts/test_wireless_rf_parsers.py
	python3 ./scripts/test_path_probe.py
	python3 ./scripts/test_vocera_media_qoe.py
	python3 ./scripts/test_vocera_media_qoe_psql_in_container.py
	python3 ./scripts/test_vocera_multicast.py
	python3 ./scripts/test_vocera_wlc_cli.py
	python3 ./scripts/test_vocera_wlc_attempt.py
	python3 ./scripts/test_vocera_wlc_session.py
	python3 ./scripts/test_vocera_wlc_session_ingest.py
	python3 ./scripts/test_vocera_wlc_session_console.py
	python3 ./scripts/test_wlc_session_make_safety.py
	python3 ./scripts/test_wlc_session_documentation_contract.py
	python3 ./scripts/test_vocera_iperf_qoe.py
	python3 ./scripts/test_vocera_rf_validation.py
	python3 ./scripts/test_publish_dnac_topology.py

test-rf-validation:
	python3 ./scripts/test_vocera_rf_validation.py

test-pcap-study:
	python3 ./scripts/test_vocera_media_qoe.py

kustomize-validate:
	kustomize build deploy/k8s/base >/dev/null
	kustomize build deploy/k8s/overlays/dev >/dev/null
	kustomize build deploy/k8s/overlays/prod >/dev/null

wireless-rf-textfile-install:
	sudo bash ./scripts/install_wireless_rf_textfile.sh

wireless-rf-parse:
# Parse an existing raw evidence file and write CSV/JSON/Prometheus/SQLite.
	PYTHONPATH=.:tools/wireless_rf python3 -m wireless_rf.cli parse "$(INPUT)" \
		--wlc "$(WLC)" \
		--band "$(BAND)" \
		$(if $(SITE_TAG_REGEX),--site-tag-regex "$(SITE_TAG_REGEX)",) \
		$(if $(AP_NAME_REGEX),--ap-name-regex "$(AP_NAME_REGEX)",) \
		--csv-out "$(RF_CSV_OUT)" \
		--json-out "$(RF_JSON_OUT)" \
		--prom-out "$(RF_PROM_OUT)" \
		--sqlite-db "$(RF_SQLITE_DB)"

wireless-rf-verify-parse:
# Compare selected raw WLC traffic-distribution values against generated .prom.
	PYTHONPATH=.:tools/wireless_rf python3 ./scripts/verify_wireless_rf_cli_parse.py \
		--input "$(INPUT)" \
		--prom "$(RF_PROM_OUT)" \
		--band "$(BAND)" \
		$(if $(RF_VERIFY_WLC),--wlc "$(RF_VERIFY_WLC)",) \
		$(if $(RF_VERIFY_AP),--ap "$(RF_VERIFY_AP)",) \
		$(if $(RF_VERIFY_SLOT),--slot "$(RF_VERIFY_SLOT)",) \
		$(if $(RF_VERIFY_ACCESS_CATEGORY),--access-category "$(RF_VERIFY_ACCESS_CATEGORY)",) \
		$(if $(RF_VERIFY_CLIENT_GENERATION),--client-generation "$(RF_VERIFY_CLIENT_GENERATION)",)

wireless-rf-status:
	bash ./scripts/wireless_rf_status.sh

wireless-rf-smoke-test:
	bash ./scripts/wireless_rf_smoke_test.sh

vocera-dashboard-audit:
	python3 ./scripts/audit_vocera_dashboard.py \
		--dashboard "$(VOCERA_DASHBOARD)" \
		--mimir-url "$(MIMIR_PROM_URL)" \
		--org-id "$(MIMIR_ORG_ID)"

wireless-rf-web:
	cd tools/wireless_rf && PYTHONPATH=. streamlit run streamlit_app.py

wireless-rf-install-textfile:
	sudo bash ./scripts/install_wireless_rf_textfile.sh --enable --start-now

wireless-rf-install-hourly:
	sudo bash ./scripts/install_wireless_rf_hourly.sh

wireless-badge-collect:
	PYTHONPATH=.:tools/wireless_rf python3 -m wireless_rf.cli collect-badges \
		--config "$(BADGE_CONFIG)"

wireless-badge-parse:
	@test -f "$(BADGE_CONFIG)" || (echo "Missing $(BADGE_CONFIG). Copy config/badge-client-observability.example.yaml first." && exit 1)
# The badge config supplies default output paths so scheduled and manual runs
# keep writing the same artifact set.
	PYTHONPATH=.:tools/wireless_rf python3 -m wireless_rf.cli parse-badges \
		--config "$(BADGE_CONFIG)" \
		--input "$(BADGE_INPUT)"

wireless-badge-web:
	cd tools/wireless_rf && PYTHONPATH=. streamlit run badge_client_app.py

path-probe-run:
	PYTHONPATH=.:tools/path_probe:tools/wireless_rf python3 -m path_probe \
		--config "$(PATH_PROBE_CONFIG)" \
		--prom-out "$(PATH_PROBE_PROM_OUT)" \
		--json-out "$(PATH_PROBE_JSON_OUT)" \
		$(if $(PATH_PROBE_JOB),--job "$(PATH_PROBE_JOB)",)

path-probe-install:
	sudo bash ./scripts/install_path_probe_textfile.sh

vocera-survey-refresh:
	sudo VOCERA_SURVEY_OUTPUT_OWNER="$$(id -un)" bash ./scripts/run_vocera_survey_refresh.sh

vocera-survey-rollback:
	@test -n "$(VOCERA_SURVEY_ROLLBACK_RUN_ID)" || (echo "Set VOCERA_SURVEY_ROLLBACK_RUN_ID" && exit 1)
	sudo bash ./scripts/rollback_vocera_survey_refresh.sh --run-id "$(VOCERA_SURVEY_ROLLBACK_RUN_ID)" $(VOCERA_SURVEY_ROLLBACK_ARGS)

ipad-rf-validation-run:
	@test -n "$(IPAD_RF_VALIDATION_CLIENT_MAC)" || (echo "Set IPAD_RF_VALIDATION_CLIENT_MAC" && exit 1)
	@test -n "$(IPAD_RF_VALIDATION_EKAHAU_PROJECT)" || (echo "Set IPAD_RF_VALIDATION_EKAHAU_PROJECT" && exit 1)
	IPAD_RF_VALIDATION_CONFIG="$(IPAD_RF_VALIDATION_CONFIG)" \
	IPAD_RF_VALIDATION_RUN_ID="$(IPAD_RF_VALIDATION_RUN_ID)" \
	IPAD_RF_VALIDATION_CLIENT_MAC="$(IPAD_RF_VALIDATION_CLIENT_MAC)" \
	IPAD_RF_VALIDATION_CLIENT_MODEL="$(IPAD_RF_VALIDATION_CLIENT_MODEL)" \
	IPAD_RF_VALIDATION_EKAHAU_PROJECT="$(IPAD_RF_VALIDATION_EKAHAU_PROJECT)" \
	IPAD_RF_VALIDATION_OUT_DIR="$(IPAD_RF_VALIDATION_OUT_DIR)" \
	IPAD_RF_VALIDATION_ARCHIVE_DIR="$(IPAD_RF_VALIDATION_ARCHIVE_DIR)" \
	IPAD_RF_VALIDATION_INSTALL_DB="$(IPAD_RF_VALIDATION_INSTALL_DB)" \
	IPAD_RF_VALIDATION_LOAD_DB="$(IPAD_RF_VALIDATION_LOAD_DB)" \
	IPAD_RF_VALIDATION_DATABASE_URL="$(IPAD_RF_VALIDATION_DATABASE_URL)" \
	IPAD_RF_VALIDATION_PSQL_BIN="$(IPAD_RF_VALIDATION_PSQL_BIN)" \
	bash ./scripts/run_ipad_rf_validation_refresh.sh

ipad-rf-validation-process:
	@test -n "$(IPAD_RF_VALIDATION_RUN_ID)" || (echo "Set IPAD_RF_VALIDATION_RUN_ID" && exit 1)
	@test -n "$(IPAD_RF_VALIDATION_CLIENT_MAC)" || (echo "Set IPAD_RF_VALIDATION_CLIENT_MAC" && exit 1)
	@test -n "$(IPAD_RF_VALIDATION_EKAHAU_PROJECT)" || (echo "Set IPAD_RF_VALIDATION_EKAHAU_PROJECT" && exit 1)
	IPAD_RF_VALIDATION_CONFIG="$(IPAD_RF_VALIDATION_CONFIG)" \
	IPAD_RF_VALIDATION_RUN_ID="$(IPAD_RF_VALIDATION_RUN_ID)" \
	IPAD_RF_VALIDATION_CLIENT_MAC="$(IPAD_RF_VALIDATION_CLIENT_MAC)" \
	IPAD_RF_VALIDATION_CLIENT_MODEL="$(IPAD_RF_VALIDATION_CLIENT_MODEL)" \
	IPAD_RF_VALIDATION_EKAHAU_PROJECT="$(IPAD_RF_VALIDATION_EKAHAU_PROJECT)" \
	IPAD_RF_VALIDATION_OUT_DIR="$(IPAD_RF_VALIDATION_OUT_DIR)" \
	IPAD_RF_VALIDATION_ARCHIVE_DIR="$(IPAD_RF_VALIDATION_ARCHIVE_DIR)" \
	IPAD_RF_VALIDATION_INSTALL_DB="$(IPAD_RF_VALIDATION_INSTALL_DB)" \
	IPAD_RF_VALIDATION_LOAD_DB="$(IPAD_RF_VALIDATION_LOAD_DB)" \
	IPAD_RF_VALIDATION_DATABASE_URL="$(IPAD_RF_VALIDATION_DATABASE_URL)" \
	IPAD_RF_VALIDATION_PSQL_BIN="$(IPAD_RF_VALIDATION_PSQL_BIN)" \
	bash ./scripts/run_ipad_rf_validation_refresh.sh

vocera-media-qoe-parse:
	PYTHONPATH=.:tools/vocera_media_qoe python3 -m vocera_media_qoe \
		--pcap "$(VOCERA_MEDIA_QOE_PCAP)" \
		--config "$(VOCERA_MEDIA_QOE_CONFIG)" \
		--prom-out "$(VOCERA_MEDIA_QOE_PROM_OUT)" \
		--json-out "$(VOCERA_MEDIA_QOE_JSON_OUT)" \
		--archive-dir "$(VOCERA_MEDIA_QOE_ARCHIVE_DIR)"

vocera-media-qoe-dnac-download:
	PYTHONPATH=.:tools/vocera_media_qoe:tools/wireless_rf python3 -m vocera_dnac_icap \
		--env-file "$(VOCERA_MEDIA_QOE_ENV_FILE)" \
		--client-mac "$(VOCERA_MEDIA_QOE_DNAC_CLIENT_MAC)" \
		$(if $(VOCERA_MEDIA_QOE_DNAC_AP_MAC),--ap-mac "$(VOCERA_MEDIA_QOE_DNAC_AP_MAC)",) \
		--capture-type "$(VOCERA_MEDIA_QOE_DNAC_CAPTURE_TYPE)" \
		--lookback-minutes "$(VOCERA_MEDIA_QOE_DNAC_LOOKBACK_MINUTES)" \
		--limit "$(VOCERA_MEDIA_QOE_DNAC_LIMIT)" \
		$(if $(filter 1 true yes,$(VOCERA_MEDIA_QOE_DNAC_INSECURE)),--insecure,) \
		--out-dir "$(VOCERA_MEDIA_QOE_RAW_DIR)" \
		--parsed-dir "$(VOCERA_MEDIA_QOE_PARSED_DIR)"

vocera-media-qoe-dnac-check-api:
	PYTHONPATH=.:tools/vocera_media_qoe:tools/wireless_rf python3 -m vocera_dnac_icap \
		--env-file "$(VOCERA_MEDIA_QOE_ENV_FILE)" \
		--client-mac "$(VOCERA_MEDIA_QOE_DNAC_CLIENT_MAC)" \
		$(if $(VOCERA_MEDIA_QOE_DNAC_AP_MAC),--ap-mac "$(VOCERA_MEDIA_QOE_DNAC_AP_MAC)",) \
		--capture-type "$(VOCERA_MEDIA_QOE_DNAC_CAPTURE_TYPE)" \
		--lookback-minutes "$(VOCERA_MEDIA_QOE_DNAC_LOOKBACK_MINUTES)" \
		--limit "$(VOCERA_MEDIA_QOE_DNAC_LIMIT)" \
		$(if $(filter 1 true yes,$(VOCERA_MEDIA_QOE_DNAC_INSECURE)),--insecure,) \
		--check-api

vocera-media-qoe-wlc-attempt-init:
	@test -n "$(ATTEMPT_ID)" || (echo "Set ATTEMPT_ID" && exit 1)
	@test -n "$(V5000_MAC)" || (echo "Set V5000_MAC" && exit 1)
	@test -n "$(V5000_IP)" || (echo "Set V5000_IP" && exit 1)
	@test -n "$(C1000_MAC)" || (echo "Set C1000_MAC" && exit 1)
	@test -n "$(C1000_IP)" || (echo "Set C1000_IP" && exit 1)
	PYTHONPATH=.:tools/vocera_media_qoe python3 -m vocera_wlc_attempt init \
		--attempt-root "$(VOCERA_MEDIA_QOE_WLC_ATTEMPT_ROOT)" \
		--study-id "$(STUDY_ID)" \
		--attempt-id "$(ATTEMPT_ID)" \
		--wlc-name "$(WLC_NAME)" \
		--v5000-mac "$(V5000_MAC)" \
		--v5000-ip "$(V5000_IP)" \
		--c1000-mac "$(C1000_MAC)" \
		--c1000-ip "$(C1000_IP)" \
		--vocera-vlan "$(VOCERA_VLAN)" \
		--expected-dscp "$(EXPECTED_DSCP)" \
		--operator "$(OPERATOR)"

vocera-media-qoe-wlc-attempt-record:
	@test -n "$(ATTEMPT_DIR)" || (echo "Set ATTEMPT_DIR" && exit 1)
	PYTHONPATH=.:tools/vocera_media_qoe python3 -m vocera_wlc_attempt record --attempt-dir "$(ATTEMPT_DIR)" --audio-result "$(AUDIO_RESULT)" --alert-result "$(ALERT_RESULT)" --operator "$(OPERATOR)" $(if $(OPERATOR_NOTES),--notes "$(OPERATOR_NOTES)",)

vocera-media-qoe-wlc-attempt-validate:
	@test -n "$(ATTEMPT_DIR)" || (echo "Set ATTEMPT_DIR" && exit 1)
	PYTHONPATH=.:tools/vocera_media_qoe python3 -m vocera_wlc_attempt validate \
		--attempt-dir "$(ATTEMPT_DIR)"

vocera-media-qoe-wlc-attempt-ingest:
	@test -n "$(ATTEMPT_DIR)" || (echo "Set ATTEMPT_DIR" && exit 1)
	PYTHONPATH=.:tools/vocera_media_qoe python3 -m vocera_wlc_attempt ingest \
		--attempt-dir "$(ATTEMPT_DIR)" \
		$(if $(VOCERA_MEDIA_QOE_DATABASE_URL),--postgres-url "$(VOCERA_MEDIA_QOE_DATABASE_URL)",) \
		--psql-bin "$(VOCERA_MEDIA_QOE_PSQL_BIN)"

vocera-media-qoe-wlc-attempt-report:
	@test -n "$(ATTEMPT_DIR)" || (echo "Set ATTEMPT_DIR" && exit 1)
	PYTHONPATH=.:tools/vocera_media_qoe python3 -m vocera_wlc_attempt report \
		--attempt-dir "$(ATTEMPT_DIR)"

vocera-media-qoe-wlc-attempt-list:
	PYTHONPATH=.:tools/vocera_media_qoe python3 -m vocera_wlc_attempt list \
		--attempt-root "$(VOCERA_MEDIA_QOE_WLC_ATTEMPT_ROOT)" \
		--study-id "$(STUDY_ID)"

vocera-media-qoe-wlc-session-init:
	@test -n "$(SESSION_ID)" || (echo "Set SESSION_ID" && exit 1)
	@test -n "$(WLC_NAME)" || (echo "Set WLC_NAME" && exit 1)
	@test -n "$(WLC_INTERFACE)" || (echo "Set WLC_INTERFACE" && exit 1)
	@test -n "$(COLLECTOR_HOST)" || (echo "Set COLLECTOR_HOST" && exit 1)
	@test -n "$(COLLECTOR_SCP_USERNAME)" || (echo "Set COLLECTOR_SCP_USERNAME" && exit 1)
	@test -n "$(V5000_MAC)" || (echo "Set V5000_MAC" && exit 1)
	@test -n "$(V5000_IP)" || (echo "Set V5000_IP" && exit 1)
	@test -n "$(C1000_MAC)" || (echo "Set C1000_MAC" && exit 1)
	@test -n "$(C1000_IP)" || (echo "Set C1000_IP" && exit 1)
	PYTHONPATH=.:tools/vocera_media_qoe python3 -m vocera_wlc_session init \
		--session-root "$(VOCERA_MEDIA_QOE_WLC_SESSION_ROOT)" \
		--study-id "$(STUDY_ID)" \
		--session-id "$(SESSION_ID)" \
		--wlc-name "$(WLC_NAME)" \
		$(if $(strip $(WLC_CAPTURE_NAME)),--capture-name "$(WLC_CAPTURE_NAME)",) \
		--wlc-interface "$(WLC_INTERFACE)" \
		--capture-filter-mode "$(CAPTURE_FILTER_MODE)" \
		--capture-mode "$(WLC_CAPTURE_MODE)" \
		--short-validation-duration-seconds "$(WLC_SHORT_VALIDATION_DURATION_SECONDS)" \
		--collector-host "$(COLLECTOR_HOST)" \
		--collector-scp-username "$(COLLECTOR_SCP_USERNAME)" \
		--collector-scp-port "$(COLLECTOR_SCP_PORT)" \
		--ring-file-count "$(RING_FILE_COUNT)" \
		--ring-file-size-mb "$(RING_FILE_SIZE_MB)" \
		--sender-mac "$(V5000_MAC)" \
		--sender-ip "$(V5000_IP)" \
		--receiver-mac "$(C1000_MAC)" \
		--receiver-ip "$(C1000_IP)" \
		--expected-dscp "$(EXPECTED_DSCP)" \
		--vocera-vlan "$(VOCERA_VLAN)" \
		--vocera-multicast-pool "$(VOCERA_MULTICAST_POOL)" \
		--operator "$(OPERATOR)" \
		$(if $(filter 1 yes true,$(WLC_SESSION_FORCE)),--force,)

vocera-media-qoe-wlc-session-smoke-init:
	$(MAKE) vocera-media-qoe-wlc-session-init WLC_CAPTURE_MODE=short_validation WLC_SHORT_VALIDATION_DURATION_SECONDS=90

vocera-media-qoe-wlc-session-console:
	@test -n "$(SESSION_DIR)" || (echo "Set SESSION_DIR" && exit 1)
	@test -n "$(WLC_SSH_HOST)" || (echo "Set WLC_SSH_HOST or WLC_NAME" && exit 1)
	@test -n "$(WLC_SSH_USER)" || (echo "Set WLC_SSH_USER" && exit 1)
	bash ./scripts/run_vocera_wlc_session_console.sh \
		--session-dir "$(SESSION_DIR)" \
		--wlc-host "$(WLC_SSH_HOST)" \
		--wlc-user "$(WLC_SSH_USER)" \
		--wlc-port "$(WLC_SSH_PORT)" \
		--operator "$(OPERATOR)"

vocera-media-qoe-wlc-session-mark:
	@test -n "$(SESSION_DIR)" || (echo "Set SESSION_DIR" && exit 1)
	@test -n "$(EVENT_KIND)" || (echo "Set EVENT_KIND" && exit 1)
	PYTHONPATH=.:tools/vocera_media_qoe python3 -m vocera_wlc_session mark --session-dir "$(SESSION_DIR)" --event-kind "$(EVENT_KIND)" --operator "$(OPERATOR)" $(if $(OPERATOR_NOTES),--notes "$(OPERATOR_NOTES)",)

vocera-media-qoe-wlc-session-report:
	@test -n "$(SESSION_DIR)" || (echo "Set SESSION_DIR" && exit 1)
	PYTHONPATH=.:tools/vocera_media_qoe python3 -m vocera_wlc_session report \
		--session-dir "$(SESSION_DIR)"

vocera-media-qoe-wlc-session-list:
	PYTHONPATH=.:tools/vocera_media_qoe python3 -m vocera_wlc_session list \
		--session-root "$(VOCERA_MEDIA_QOE_WLC_SESSION_ROOT)" \
		--study-id "$(STUDY_ID)"

vocera-media-qoe-publish:
	@if [ -n "$(VOCERA_MEDIA_QOE_DATABASE_URL)" ]; then case "$(VOCERA_MEDIA_QOE_PSQL_BIN)" in *vocera_media_qoe_psql_in_container.sh) sudo -v ;; esac; fi
	VOCERA_MEDIA_QOE_RAW_DIR="$(VOCERA_MEDIA_QOE_RAW_DIR)" \
	VOCERA_MEDIA_QOE_PCAP="$(VOCERA_MEDIA_QOE_PUBLISH_PCAP)" \
	VOCERA_MEDIA_QOE_CONFIG="$(VOCERA_MEDIA_QOE_CONFIG)" \
	VOCERA_MEDIA_QOE_PROM_OUT="$(VOCERA_MEDIA_QOE_PROM_OUT)" \
	VOCERA_MEDIA_QOE_JSON_OUT="$(VOCERA_MEDIA_QOE_JSON_OUT)" \
	VOCERA_MEDIA_QOE_PARSED_DIR="$(VOCERA_MEDIA_QOE_PARSED_DIR)" \
	VOCERA_MEDIA_QOE_SQL_OUT="$(VOCERA_MEDIA_QOE_SQL_OUT)" \
	VOCERA_MEDIA_QOE_ARCHIVE_DIR="$(VOCERA_MEDIA_QOE_ARCHIVE_DIR)" \
	VOCERA_MEDIA_QOE_DATABASE_URL="$(VOCERA_MEDIA_QOE_DATABASE_URL)" \
	VOCERA_MEDIA_QOE_PSQL_BIN="$(VOCERA_MEDIA_QOE_PSQL_BIN)" \
	VOCERA_MEDIA_QOE_ENV_FILE="$(VOCERA_MEDIA_QOE_ENV_FILE)" \
	TEXTFILE_COLLECTOR_DIR="$(TEXTFILE_COLLECTOR_DIR)" \
	bash ./scripts/run_vocera_media_qoe_textfile.sh

vocera-media-qoe-install:
	sudo bash ./scripts/install_vocera_media_qoe_textfile.sh

vocera-media-qoe-wlc-session-ingest-install:
	sudo bash ./scripts/install_vocera_wlc_session_ingest.sh $(WLC_SESSION_INGEST_INSTALL_ARGS)

vocera-media-qoe-postgres-install:
	sudo bash ./scripts/install_vocera_media_qoe_postgres.sh --enable --start-now

vocera-media-qoe-install-db:
	@test -n "$(VOCERA_MEDIA_QOE_DATABASE_URL)" || (echo "Set VOCERA_MEDIA_QOE_DATABASE_URL" && exit 1)
	@case "$(VOCERA_MEDIA_QOE_PSQL_BIN)" in *vocera_media_qoe_psql_in_container.sh) sudo -v ;; esac
	PYTHONPATH=.:tools/vocera_media_qoe python3 -m vocera_media_qoe_sql install-db \
		--postgres-url "$(VOCERA_MEDIA_QOE_DATABASE_URL)" \
		--psql-bin "$(VOCERA_MEDIA_QOE_PSQL_BIN)"

vocera-media-qoe-emit-sql:
	PYTHONPATH=.:tools/vocera_media_qoe python3 -m vocera_media_qoe_sql emit-sql \
		--parsed-dir "$(VOCERA_MEDIA_QOE_PARSED_DIR)" \
		--sql-out "$(VOCERA_MEDIA_QOE_SQL_OUT)"

vocera-media-qoe-load-db:
	@test -n "$(VOCERA_MEDIA_QOE_DATABASE_URL)" || (echo "Set VOCERA_MEDIA_QOE_DATABASE_URL" && exit 1)
	@case "$(VOCERA_MEDIA_QOE_PSQL_BIN)" in *vocera_media_qoe_psql_in_container.sh) sudo -v ;; esac
	$(VOCERA_MEDIA_QOE_PSQL_BIN) "$(VOCERA_MEDIA_QOE_DATABASE_URL)" -v ON_ERROR_STOP=1 -f "$(VOCERA_MEDIA_QOE_SQL_OUT)"

vocera-media-qoe-data-audit:
	sudo bash ./scripts/vocera_media_qoe_data_audit.sh

vocera-iperf-qoe-parse:
	PYTHONPATH=.:tools/vocera_iperf_qoe python3 -m vocera_iperf_qoe \
		--config "$(VOCERA_IPERF_QOE_CONFIG)" \
		--incoming-root "$(VOCERA_IPERF_QOE_INCOMING_ROOT)" \
		--prom-out "$(VOCERA_IPERF_QOE_PROM_OUT)" \
		--json-out "$(VOCERA_IPERF_QOE_JSON_OUT)"

vocera-iperf-qoe-install:
	sudo bash ./scripts/install_vocera_iperf_qoe_textfile.sh

vocera-rf-validation-postgres-install:
	sudo bash ./scripts/install_vocera_rf_validation_postgres.sh --enable --start-now

vocera-rf-validation-install-db:
	@test -n "$(VOCERA_RF_VALIDATION_DATABASE_URL)" || (echo "Set VOCERA_RF_VALIDATION_DATABASE_URL" && exit 1)
	@case "$(VOCERA_RF_VALIDATION_PSQL_BIN)" in *vocera_rf_validation_psql_in_container.sh) sudo -v ;; esac
	PYTHONPATH=. python3 -m tools.vocera_rf_validation.cli --config "$(VOCERA_RF_VALIDATION_CONFIG)" install-db \
		--postgres-url "$(VOCERA_RF_VALIDATION_DATABASE_URL)" \
		--psql-bin "$(VOCERA_RF_VALIDATION_PSQL_BIN)"

vocera-rf-validation-study:
	sudo bash ./scripts/manage_vocera_rf_validation_study.sh

study-web-frontend-build:
	@test "$$(id -u)" -ne 0 -o "$(ALLOW_ROOT_FRONTEND_BUILD)" = "1" || (echo "Do not build the study web frontend as root. Run this make target as appsadmin, or set ALLOW_ROOT_FRONTEND_BUILD=1 if you really mean it." >&2; exit 1)
	cd web/study-ui && npm install && npm run build
	rm -rf tools/study_web/static
	mkdir -p tools/study_web/static
	cp -a web/study-ui/dist/. tools/study_web/static/

vocera-rf-validation-study-web:
	PYTHONPATH=tools python3 -m uvicorn study_web.main:app --host 0.0.0.0 --port 8097

vocera-rf-validation-study-web-legacy:
	PYTHONPATH=tools python3 -m vocera_rf_validation.study_web

vocera-rf-validation-study-web-install: study-web-frontend-build
	sudo bash ./scripts/install_vocera_rf_validation_study_web.sh --install-python-deps --skip-frontend-build --enable --start-now

vocera-rf-validation-parse-badge:
	PYTHONPATH=. python3 -m tools.vocera_rf_validation.cli --config "$(VOCERA_RF_VALIDATION_CONFIG)" \
		--archive-dir "$(VOCERA_RF_VALIDATION_ARCHIVE_DIR)" parse-badge \
		--test-run-id "$(VOCERA_RF_VALIDATION_TEST_RUN_ID)" \
		--input "$(VOCERA_RF_VALIDATION_BADGE_INPUT)" \
		$(if $(VOCERA_RF_VALIDATION_BADGE_MAC),--badge-mac "$(VOCERA_RF_VALIDATION_BADGE_MAC)",) \
		$(if $(VOCERA_RF_VALIDATION_BADGE_MODEL),--badge-model "$(VOCERA_RF_VALIDATION_BADGE_MODEL)",) \
		--json-out "$(VOCERA_RF_VALIDATION_BADGE_JSON)"

vocera-rf-validation-inspect-ekahau:
	PYTHONPATH=. python3 -m tools.vocera_rf_validation.cli --config "$(VOCERA_RF_VALIDATION_CONFIG)" \
		--archive-dir "$(VOCERA_RF_VALIDATION_ARCHIVE_DIR)" inspect-ekahau \
		--input "$(VOCERA_RF_VALIDATION_EKAHAU_JSON)"

vocera-rf-validation-parse-ekahau:
	PYTHONPATH=. python3 -m tools.vocera_rf_validation.cli --config "$(VOCERA_RF_VALIDATION_CONFIG)" \
		--archive-dir "$(VOCERA_RF_VALIDATION_ARCHIVE_DIR)" parse-ekahau-json \
		--test-run-id "$(VOCERA_RF_VALIDATION_TEST_RUN_ID)" \
		--input "$(VOCERA_RF_VALIDATION_EKAHAU_JSON)" \
		--json-out "$(VOCERA_RF_VALIDATION_EKAHAU_POINTS_JSON)"

vocera-rf-validation-manual-template:
	PYTHONPATH=. python3 -m tools.vocera_rf_validation.cli --config "$(VOCERA_RF_VALIDATION_CONFIG)" \
		--archive-dir "$(VOCERA_RF_VALIDATION_ARCHIVE_DIR)" manual-template \
		--badge-json "$(VOCERA_RF_VALIDATION_BADGE_JSON)" \
		--ekahau-json "$(VOCERA_RF_VALIDATION_EKAHAU_POINTS_JSON)" \
		--csv-out "$(VOCERA_RF_VALIDATION_MANUAL_TEMPLATE)"

vocera-rf-validation-correlate:
	PYTHONPATH=. python3 -m tools.vocera_rf_validation.cli --config "$(VOCERA_RF_VALIDATION_CONFIG)" \
		--archive-dir "$(VOCERA_RF_VALIDATION_ARCHIVE_DIR)" correlate \
		--template-csv "$(VOCERA_RF_VALIDATION_MANUAL_CSV)" \
		--json-out "$(VOCERA_RF_VALIDATION_MATCHES_JSON)" \
		--csv-out "$(VOCERA_RF_VALIDATION_MATCHES_CSV)"

vocera-rf-validation-emit-sql:
	PYTHONPATH=. python3 -m tools.vocera_rf_validation.cli --config "$(VOCERA_RF_VALIDATION_CONFIG)" \
		--archive-dir "$(VOCERA_RF_VALIDATION_ARCHIVE_DIR)" emit-sql \
		--badge-json "$(VOCERA_RF_VALIDATION_BADGE_JSON)" \
		--ekahau-json "$(VOCERA_RF_VALIDATION_EKAHAU_POINTS_JSON)" \
		$(if $(wildcard $(VOCERA_RF_VALIDATION_MANUAL_CSV)),--template-csv "$(VOCERA_RF_VALIDATION_MANUAL_CSV)",) \
		$(if $(wildcard $(VOCERA_RF_VALIDATION_MATCHES_JSON)),--matches-json "$(VOCERA_RF_VALIDATION_MATCHES_JSON)",) \
		--sql-out "$(VOCERA_RF_VALIDATION_SQL_OUT)"

vocera-rf-validation-load-db:
	@test -n "$(VOCERA_RF_VALIDATION_DATABASE_URL)" || (echo "Set VOCERA_RF_VALIDATION_DATABASE_URL" && exit 1)
	@case "$(VOCERA_RF_VALIDATION_PSQL_BIN)" in *vocera_rf_validation_psql_in_container.sh) sudo -v ;; esac
	$(VOCERA_RF_VALIDATION_PSQL_BIN) "$(VOCERA_RF_VALIDATION_DATABASE_URL)" -v ON_ERROR_STOP=1 -f "$(VOCERA_RF_VALIDATION_SQL_OUT)"

vocera-rf-validation-all: vocera-rf-validation-parse-badge vocera-rf-validation-parse-ekahau vocera-rf-validation-manual-template

vocera-rf-validation-test:
	python3 ./scripts/test_vocera_rf_validation.py

topology-postgres-install:
	sudo bash ./scripts/install_network_topology_postgres.sh --enable --start-now

topology-validate:
	@test -d "$(NETWORK_TOPOLOGY_REPO)" || (echo "Missing Network-Topology repo: $(NETWORK_TOPOLOGY_REPO)" && exit 1)
	cd "$(NETWORK_TOPOLOGY_REPO)" && python3 scripts/validate_topology_data.py \
		--data-dir "$(abspath $(TOPOLOGY_INPUT_DIR))"

topology-publish:
	@test -d "$(NETWORK_TOPOLOGY_REPO)" || (echo "Missing Network-Topology repo: $(NETWORK_TOPOLOGY_REPO)" && exit 1)
	cd "$(NETWORK_TOPOLOGY_REPO)" && python3 scripts/publish_node_graph.py \
		--input-dir "$(abspath $(TOPOLOGY_INPUT_DIR))" \
		--output-dir "$(abspath $(TOPOLOGY_PUBLISHED_DIR))" \
		--netbox-base-url "$(TOPOLOGY_NETBOX_BASE_URL)" \
		--node-confidence-high-days "$(TOPOLOGY_NODE_CONFIDENCE_HIGH_DAYS)" \
		--node-confidence-medium-days "$(TOPOLOGY_NODE_CONFIDENCE_MEDIUM_DAYS)" \
		$(if $(TOPOLOGY_AS_OF_DATE),--as-of-date "$(TOPOLOGY_AS_OF_DATE)",)

topology-publish-dnac:
	PYTHONPATH=.:tools/wireless_rf python3 scripts/publish_dnac_topology.py \
		--env-file "$(TOPOLOGY_DNAC_ENV_FILE)" \
		--output-dir "$(TOPOLOGY_DNAC_PUBLISHED_DIR)" \
		--raw-out-dir "$(TOPOLOGY_DNAC_RAW_DIR)" \
		--environment "$(TOPOLOGY_DNAC_ENVIRONMENT)" \
		--source-lineage "$(TOPOLOGY_DNAC_SOURCE_LINEAGE)" \
		--page-limit "$(TOPOLOGY_DNAC_PAGE_LIMIT)" \
		$(if $(filter 1 true yes,$(TOPOLOGY_DNAC_INSECURE)),--insecure,)

topology-load:
	@test -d "$(NETWORK_TOPOLOGY_REPO)" || (echo "Missing Network-Topology repo: $(NETWORK_TOPOLOGY_REPO)" && exit 1)
	@case "$(TOPOLOGY_PSQL_BIN)" in *topology_psql_in_container.sh) sudo -v ;; esac
	TOPOLOGY_PUBLISHED_DIR="$(abspath $(TOPOLOGY_PUBLISHED_DIR))" \
	python3 "$(NETWORK_TOPOLOGY_REPO)/scripts/load_published_topology_to_postgres.py" \
		--published-dir "$(abspath $(TOPOLOGY_PUBLISHED_DIR))" \
		--schema-sql "$(TOPOLOGY_SCHEMA_SQL)" \
		--host "$(TOPOLOGY_POSTGRES_HOST)" \
		--port "$(TOPOLOGY_POSTGRES_PORT)" \
		--database "$(TOPOLOGY_POSTGRES_DB)" \
		--user "$(TOPOLOGY_POSTGRES_USER)" \
		--psql-bin "$(TOPOLOGY_PSQL_BIN)"

topology-load-poc:
	$(MAKE) topology-load TOPOLOGY_PUBLISHED_DIR="$(TOPOLOGY_POC_DIR)"

topology-load-dnac:
	$(MAKE) topology-load TOPOLOGY_PUBLISHED_DIR="$(TOPOLOGY_DNAC_PUBLISHED_DIR)"

topology-load-dry-run:
	@test -d "$(NETWORK_TOPOLOGY_REPO)" || (echo "Missing Network-Topology repo: $(NETWORK_TOPOLOGY_REPO)" && exit 1)
	TOPOLOGY_PUBLISHED_DIR="$(abspath $(TOPOLOGY_PUBLISHED_DIR))" \
	python3 "$(NETWORK_TOPOLOGY_REPO)/scripts/load_published_topology_to_postgres.py" \
		--published-dir "$(abspath $(TOPOLOGY_PUBLISHED_DIR))" \
		--schema-sql "$(TOPOLOGY_SCHEMA_SQL)" \
		--host "$(TOPOLOGY_POSTGRES_HOST)" \
		--port "$(TOPOLOGY_POSTGRES_PORT)" \
		--database "$(TOPOLOGY_POSTGRES_DB)" \
		--user "$(TOPOLOGY_POSTGRES_USER)" \
		--psql-bin "$(TOPOLOGY_PSQL_BIN)" \
		--dry-run

topology-publish-load: topology-publish topology-load

topology-publish-load-dnac: topology-publish-dnac topology-load-dnac
