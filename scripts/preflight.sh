#!/usr/bin/env bash
set -euo pipefail
# Read-only repository validation used before release and promotion.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Assert that a command required by preflight exists.
need_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "❌ Missing command: $1" >&2; exit 1; }; }
# Assert that a repository file required by deploy/test flows exists.
need_file() { [[ -f "$1" ]] || { echo "❌ Missing file: $1" >&2; exit 1; }; }
# Validate every repo rule file before deploy copies Prometheus config.
check_repo_prometheus_rules() {
  # promtool wants explicit files; collecting them also catches empty rule dirs.
  local rules_dir="$1"
  local -a rule_files=()
  mapfile -t rule_files < <(find "$rules_dir" -type f -name '*.yml' | sort)
  if [[ "${#rule_files[@]}" -eq 0 ]]; then
    echo "❌ No Prometheus rule files found under: $rules_dir" >&2
    exit 1
  fi
  promtool check rules "${rule_files[@]}" >/dev/null
}

need_cmd bash
need_cmd python3
need_file scripts/check_dashboards.py
need_file scripts/check_topology_dashboard.py
need_file scripts/install_network_topology_postgres.sh
need_file scripts/topology_psql_in_container.sh
need_file scripts/check_contract_schema.py
need_file scripts/check_dashboard_metric_contract.py
need_file scripts/check_metric_name_overlap.py
need_file scripts/run_vocera_media_qoe_textfile.sh
need_file scripts/run_vocera_survey_refresh.sh
need_file scripts/install_vocera_media_qoe_textfile.sh
need_file scripts/install_vocera_media_qoe_postgres.sh
need_file scripts/vocera_media_qoe_psql_in_container.sh
need_file systemd/vocera-media-qoe-textfile.service
need_file systemd/vocera-media-qoe-textfile.timer
need_file systemd/vocera-media-qoe-postgres.service
need_file sql/vocera_media_qoe_schema.sql
need_file sql/vocera_media_qoe_views.sql
need_file systemd/network-topology-postgres.service
need_file topology/postgres/init/001_topology_tables.sql
need_file grafana/provisioning/dashboards/prod.yaml
need_file grafana/provisioning/datasources/mimir.yaml
need_file grafana/provisioning/datasources/topology-postgres.yaml
need_file grafana/provisioning/datasources/vocera-media-qoe-postgres.yaml
need_file prometheus/prometheus.yml
need_file mimir/mimir-local.yaml
need_file mimir/systemd/mimir.service

echo "[*] Dashboard structure check"
python3 scripts/check_dashboards.py

echo "[*] Network topology dashboard contract check"
python3 scripts/check_topology_dashboard.py

echo "[*] Dashboard metric contract check"
python3 scripts/check_dashboard_metric_contract.py

echo "[*] Prometheus contract check"
python3 scripts/check_contract_schema.py

echo "[*] Metric name overlap check"
python3 scripts/check_metric_name_overlap.py

if command -v promtool >/dev/null 2>&1; then
  # promtool is optional for lightweight dev shells, but used when available.
  echo "[*] Prometheus config syntax check"
  promtool check config prometheus/prometheus.yml >/dev/null
  echo "[*] Prometheus repo rule syntax check"
  check_repo_prometheus_rules prometheus/rules
fi

echo "✅ Preflight passed"
