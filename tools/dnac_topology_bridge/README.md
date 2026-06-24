# DNAC -> canonical bridge

Staging area for two files that belong in the sibling Network-Topology repo.
They fill the gap between `import_dnac_inventory.py` (which dumps raw DNAC
data to `data/raw/dnac_export_<DATE>/`) and `publish_node_graph.py` (which
only reads canonical CSVs from `data/working/*.v1.csv`).

## What the bridge does

1. **Assigns a hierarchy layer to each device** from the YAML lookup
   (`role` -> layer, `family` -> layer, `hostname_patterns` overrides).
   Layers, top to bottom in the dashboard: `0=edge/WAN`, `1=core`,
   `2=distribution`, `3=access/WLC`, `4=endpoints`, `5=other`. The layer
   is held in memory only - it is not added to the canonical schema.
2. **Normalizes link direction** so `a_device_id` always sits at a lower
   layer than `z_device_id`. DNAC's `/topology/physical-topology` returns
   endpoints without semantic direction, so before this normalization the
   dashboard's BFS hierarchy SQL collapses everything to `graph_depth = 0`.
   After normalization, "root" nodes are the layer-0 edge devices.
3. **Rewrites `evidence_ref` to `CFG-DNAC-<YYYY-MM-DD>`** so
   `publish_node_graph.py:99-108` returns `confidence = "high"` and
   `source_lineage = "config_export"`. Without this, every DNAC-observed
   link publishes as `low` confidence with `manual_or_unknown` lineage.

## Install into the sibling repo

From `/home/appsadmin/grafana-mimir-observability`:

```
install -d /home/appsadmin/Network-Topology/config
install -m 0644 tools/dnac_topology_bridge/dnac_role_layer.yaml \
    /home/appsadmin/Network-Topology/config/dnac_role_layer.yaml
install -m 0755 tools/dnac_topology_bridge/bridge_dnac_to_canonical.py \
    /home/appsadmin/Network-Topology/scripts/bridge_dnac_to_canonical.py
```

Then commit them in the Network-Topology repo.

## End-to-end run

From the Network-Topology repo:

```
# 1. Pull fresh from DNAC.
python3 scripts/import_dnac_inventory.py \
    --base-url "$DNAC_BASE_URL" --username "$DNAC_USERNAME" --password "$DNAC_PASSWORD"

# 2. Bridge DNAC raw -> canonical with layer + normalized direction.
python3 scripts/bridge_dnac_to_canonical.py

# 3. Derive the published Grafana CSVs.
python3 scripts/publish_node_graph.py
```

Then from this Grafana repo:

```
make topology-load
```

The bridge prints a per-layer device count and warns if any devices land at
layer 5 (unknown) - those need either a `role`/`family` entry or a
`hostname_patterns` override in
`Network-Topology/config/dnac_role_layer.yaml`.

## Tuning the layer assignment

If a device lands on the wrong layer (e.g. `LCH-COR-X` coming back as
layer 2 because it matched the generic "Switches and Hubs" family), add a
hostname override near the top of the YAML:

```yaml
hostname_patterns:
  - pattern: "LCH-COR-*"
    layer: 1
  ...
```

The bridge re-evaluates every run, so the fix lands on the next DNAC pull.

## Verifying the result

After `make topology-load` the dashboard's hierarchy SQL should now place
edge devices at the top and APs at the bottom. To confirm before redeploying
the dashboard:

```
sudo podman exec -i network-topology-postgres psql -U topology -d topology \
  -c "SELECT source_node.id AS src, target_node.id AS tgt
      FROM topology_edges_v1 e
      LEFT JOIN topology_nodes_v1 source_node ON source_node.id = e.source
      LEFT JOIN topology_nodes_v1 target_node ON target_node.id = e.target
      LIMIT 10;"
```

`source_node` should consistently be the layer-0 / layer-1 device on each
link; if you still see APs as the source, the bridge did not run (or the
layer YAML did not classify the device correctly).
