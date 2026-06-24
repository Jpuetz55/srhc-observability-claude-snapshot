#!/usr/bin/env bash
# Dump the existing DNAC + publish/load code in the sibling Network-Topology
# repo so the topology fetcher can extend what already exists rather than
# parallel it. Read-only.
#
# Run on the Grafana host (collectors01):
#   bash scripts/dump_network_topology_dnac.sh | tee /tmp/nettopo-dnac.txt
#
# Then paste /tmp/nettopo-dnac.txt back here.
set -uo pipefail

REPO="${NETWORK_TOPOLOGY_REPO:-/home/appsadmin/Network-Topology}"

# Print one sibling-repo file with a stable heading and optional truncation.
dump_file() {
  local label="$1"; local path="$2"; local mode="${3:-full}"
  echo
  echo "================ $label ================"
  echo "path: $path"
  if [[ ! -f "$path" ]]; then
    echo "(missing)"
    return
  fi
  echo "size: $(stat -c%s "$path") bytes"
  echo "--- content ---"
  case "$mode" in
    full) cat "$path" ;;
    head) head -120 "$path" ;;
    tail) tail -200 "$path" ;;
    *)    cat "$path" ;;
  esac
}

dump_file "1. import_dnac_inventory.py" "$REPO/scripts/import_dnac_inventory.py" full
dump_file "2. prototype_dnac_scheduled_job.py" "$REPO/scripts/prototype_dnac_scheduled_job.py" full
dump_file "3. test_import_dnac_inventory.py" "$REPO/scripts/test_import_dnac_inventory.py" full
dump_file "4. publish_node_graph.py (full)" "$REPO/scripts/publish_node_graph.py" full

echo
echo "================ 5. ADR 0006 (federated authority NetBox+DNAC) ================"
ADR="$REPO/docs/adr/0006-federated-authority-netbox-dnac.md"
if [[ -f "$ADR" ]]; then cat "$ADR"; else echo "(missing)"; fi

echo
echo "================ 6. data dictionary ================"
DD="$REPO/docs/data-dictionary.md"
if [[ -f "$DD" ]]; then head -200 "$DD"; else echo "(missing)"; fi

echo
echo "================ 7. Makefile (Network-Topology) ================"
MK="$REPO/Makefile"
if [[ -f "$MK" ]]; then cat "$MK"; else
  echo "(no top-level Makefile)"
  find "$REPO" -maxdepth 2 -type f -iname 'Makefile*' 2>/dev/null
fi

echo
echo "================ 8. systemd / EnvironmentFile traces for dnac/topology ================"
grep -rIn -E 'EnvironmentFile|DNAC_|/etc/default/network-topology|systemd' "$REPO" 2>/dev/null | head -40
echo "--- systemd unit files in repo ---"
find "$REPO" -type f \( -name '*.service' -o -name '*.timer' \) 2>/dev/null

echo
echo "================ 9. existing /etc/default + units on this host ================"
ls -la /etc/default/ 2>/dev/null | grep -iE 'topology|netbox|dnac|grafana' || echo "(no matching /etc/default files)"
sudo systemctl list-unit-files 2>/dev/null | grep -iE 'topology|netbox|dnac' || true

echo
echo "================ 10. tests for the DNAC prototype ================"
T="$REPO/scripts/test_prototype_dnac_scheduled_job.py"
if [[ -f "$T" ]]; then
  echo "path: $T"
  echo "size: $(stat -c%s "$T") bytes"
  echo "--- head 200 ---"
  head -200 "$T"
fi

echo
echo "================ 11. raw/dnac_site_map_template.csv (DNAC->site mapping hint) ================"
DSM="$REPO/data/raw/dnac_site_map_template.csv"
[[ -f "$DSM" ]] && cat "$DSM" || echo "(missing)"

echo
echo "================ done ================"
