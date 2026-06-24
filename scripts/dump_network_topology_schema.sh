#!/usr/bin/env bash
# Dump the schema shape of the sibling Network-Topology repo so I can design
# the DNAC topology fetcher against the *actual* canonical CSV contract instead
# of guessing it from the loader. Read-only.
#
# Run on the Grafana host (collectors01):
#   bash scripts/dump_network_topology_schema.sh | tee /tmp/nettopo-schema.txt
#
# Then paste /tmp/nettopo-schema.txt back here.
set -uo pipefail

REPO="${NETWORK_TOPOLOGY_REPO:-/home/appsadmin/Network-Topology}"

echo "================ 0. repo root ================"
ls -la "$REPO" 2>/dev/null | head -30 || echo "MISSING: $REPO"

echo
echo "================ 1. canonical (working) + published data dirs ================"
for d in "$REPO/data/working" "$REPO/data/published" "$REPO/data"; do
  echo "--- $d ---"
  ls -la "$d" 2>/dev/null || echo "  (missing)"
done

echo
echo "================ 2. CSV files anywhere under data/ ================"
find "$REPO/data" -maxdepth 5 -type f \( -name '*.csv' -o -name '*.tsv' -o -name '*.json' -o -name '*.yaml' -o -name '*.yml' \) 2>/dev/null | sort

echo
echo "================ 3. first 3 lines of every CSV (headers + 2 sample rows) ================"
while IFS= read -r f; do
  echo "==== $f ===="
  head -3 "$f" 2>/dev/null
  echo
done < <(find "$REPO/data" -maxdepth 5 -type f -name '*.csv' 2>/dev/null | sort)

echo
echo "================ 4. publish_node_graph.py (head, argparse, function names) ================"
PNG="$REPO/scripts/publish_node_graph.py"
if [[ -f "$PNG" ]]; then
  echo "--- $PNG (first 120 lines) ---"
  head -120 "$PNG"
  echo
  echo "--- argparse add_argument calls ---"
  grep -nE 'add_argument|argparse|ArgumentParser' "$PNG" || echo "(none)"
  echo
  echo "--- function defs ---"
  grep -nE '^def |^class ' "$PNG"
  echo
  echo "--- input/output column names referenced ---"
  grep -nE 'fieldnames|writer\.write|csv\.|columns|DictReader|DictWriter' "$PNG" | head -40
else
  echo "MISSING: $PNG"
fi

echo
echo "================ 5. load_published_topology_to_postgres.py (signature) ================"
LDR="$REPO/scripts/load_published_topology_to_postgres.py"
if [[ -f "$LDR" ]]; then
  echo "--- $LDR (first 80 lines) ---"
  head -80 "$LDR"
  echo
  echo "--- COPY / INSERT / table refs ---"
  grep -nE 'COPY |INSERT |topology_nodes_v1|topology_edges_v1|fieldnames|csv\.' "$LDR" | head -40
else
  echo "MISSING: $LDR"
fi

echo
echo "================ 6. validate_topology_data.py (canonical contract hints) ================"
VAL="$REPO/scripts/validate_topology_data.py"
if [[ -f "$VAL" ]]; then
  grep -nE 'required|REQUIRED|columns|fieldnames|expected|schema' "$VAL" | head -40
else
  echo "(no validate_topology_data.py)"
fi

echo
echo "================ 7. any schema/contract docs ================"
find "$REPO" -maxdepth 4 -type f -name '*.md' 2>/dev/null | head -30
echo "--- grep for 'canonical' / 'schema' / 'node graph' across docs ---"
grep -rinE 'canonical|node[- ]graph schema|required columns' "$REPO" --include='*.md' 2>/dev/null | head -20

echo
echo "================ 8. scripts/ inventory ================"
ls -la "$REPO/scripts" 2>/dev/null | head -40

echo
echo "================ done ================"
