#!/usr/bin/env bash
# Grafana-side topology diagnostic. The data is confirmed good, so this checks
# the path Grafana ACTUALLY uses: the deployed dashboard JSON and the host
# published Postgres port 127.0.0.1:15432 (NOT the in-container 5432 port that
# `podman exec ... psql` uses).
#
# Run on the Grafana host (collectors01):
#   bash scripts/topology_diagnose_grafana.sh
#
# Uses sudo for podman/journal reads; you'll be prompted once.
set -uo pipefail

HOST="127.0.0.1"
PORT="${TOPOLOGY_POSTGRES_PORT:-15432}"
DB="${TOPOLOGY_POSTGRES_DB:-topology}"
USER_DB="${TOPOLOGY_POSTGRES_USER:-topology}"
_secrets_file="${TOPOLOGY_POSTGRES_SECRETS_FILE:-/etc/grafana-mimir-observability/secrets/topology-postgres.env}"
if [[ -z "${TOPOLOGY_POSTGRES_PASSWORD:-}" && -r "$_secrets_file" ]]; then
  # shellcheck disable=SC1090
  set -a; source "$_secrets_file"; set +a
fi
PASS="${TOPOLOGY_POSTGRES_PASSWORD:?TOPOLOGY_POSTGRES_PASSWORD not set; run 'sudo bash scripts/install_secrets.sh' first}"
CONTAINER="${TOPOLOGY_POSTGRES_CONTAINER_NAME:-network-topology-postgres}"
DASH="/var/lib/grafana/dashboards-prod/Platform - Network Topology/network-topology-enterprise__network_topology_v1.json"

echo "================ A. is the dashboard actually deployed, and what does it ask for? ================"
if [[ -f "$DASH" ]]; then
  echo "FOUND: $DASH"
  python3 - "$DASH" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
def uid(ds):
    return ds.get("uid") if isinstance(ds, dict) else ds
panels = [p for p in d.get("panels", []) if p.get("type") == "nodeGraph"]
print("nodeGraph panels:", len(panels))
for p in panels:
    print("  panel.datasource.uid =", uid(p.get("datasource")))
    print("  panel.options keys   =", list(p.get("options", {}).keys()),
          "(arcs should live under 'nodes', not top-level)")
    for t in p.get("targets", []):
        sql = t.get("rawSql", "")
        frm = "edges" if "topology_edges_v1" in sql else "nodes" if "topology_nodes_v1" in sql else "?"
        print(f"  target refId={t.get('refId')!r} ds={uid(t.get('datasource'))!r} "
              f"format={t.get('format')!r} rawQuery={t.get('rawQuery')!r} from={frm} "
              f"has_WHERE={'WHERE' in sql} has_timeFilter={'__timeFilter' in sql or '__time' in sql}")
        print("    ---- exact rawSql Grafana runs ----")
        for line in sql.splitlines():
            print("    | " + line)
print("templating vars:", [v.get("name") for v in d.get("templating", {}).get("list", [])])
PY
else
  echo "MISSING: $DASH"
  echo "--- what is actually under the provisioned prod folder? ---"
  ls -la "/var/lib/grafana/dashboards-prod/Platform - Network Topology/" 2>/dev/null \
    || sudo ls -la "/var/lib/grafana/dashboards-prod/Platform - Network Topology/" 2>/dev/null \
    || echo "  (folder missing -> promote did not sync the dashboard)"
fi

echo
echo "================ B. host port $HOST:$PORT reachable? (THE path Grafana uses) ================"
if timeout 3 bash -c "exec 3<>/dev/tcp/$HOST/$PORT" 2>/dev/null; then
  echo "OPEN: $HOST:$PORT reachable from the host -> Grafana's TCP path is fine"
else
  echo "CLOSED: $HOST:$PORT NOT reachable from the host"
  echo "  >>> This alone makes the panel blank: Grafana cannot connect even though"
  echo "  >>> the data exists inside the container. Fix the published port, then redeploy."
fi

echo
echo "================ C. how is the container publishing its port? ================"
sudo podman port "$CONTAINER" 2>/dev/null || echo "(could not read 'podman port $CONTAINER')"
echo "--- listening sockets on :$PORT ---"
{ ss -ltnp 2>/dev/null || sudo ss -ltnp 2>/dev/null; } | grep ":$PORT " || echo "(nothing listening on :$PORT)"

echo
echo "================ D. Grafana's own error for this datasource (the smoking gun) ================"
sudo journalctl -u grafana-server --no-pager -n 3000 2>/dev/null \
  | grep -iE "topology|postgres|TOPOLOGY_DS|dial tcp|connection refused|password auth|pq:|sslmode|no pg_hba" \
  | tail -40 \
  || echo "(no journal matches; trying log file)"
if [[ -f /var/log/grafana/grafana.log ]]; then
  echo "--- /var/log/grafana/grafana.log ---"
  sudo grep -iE "topology|postgres|TOPOLOGY_DS|dial tcp|connection refused|password auth|pq:|sslmode|no pg_hba" \
    /var/log/grafana/grafana.log 2>/dev/null | tail -40 || echo "(no matches in log file)"
fi

echo
echo "================ E. run the real query over the host port (exactly what Grafana does) ================"
if command -v psql >/dev/null 2>&1; then
  PGPASSWORD="$PASS" PGSSLMODE=disable \
    psql -h "$HOST" -p "$PORT" -U "$USER_DB" -d "$DB" \
      -c "select count(*) as nodes_via_host_port from topology_nodes_v1;" \
    || echo ">>> psql over $HOST:$PORT FAILED — this is the same failure Grafana hits."
else
  echo "host psql not installed (that's why the container shim exists); rely on sections B and D."
fi

echo
echo "================ done ================"
