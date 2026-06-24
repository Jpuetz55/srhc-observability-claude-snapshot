# Network Topology Grafana Integration

This repo consumes the topology data owned by `/home/appsadmin/Network-Topology` and publishes the operator view into the current Grafana instance. The topology repo remains the source for canonical CSVs, NetBox publishing rules, and the CSV-to-PostgreSQL loader.

## Runtime Model

- Current Grafana provisions the dashboard `Network Topology - Enterprise` from `grafana/dashboards-prod/Platform - Network Topology/`.
- Current Grafana provisions datasource UID `TOPOLOGY_DS` from `grafana/provisioning/datasources/topology-postgres.yaml`.
- `TOPOLOGY_DS` points at `127.0.0.1:15432`, database `topology`, user `topology`.
- Grafana reads tables `topology_nodes_v1` and `topology_edges_v1`.
- The table DDL contract is stored here at `topology/postgres/init/001_topology_tables.sql`.
- The dashboard SQL target refIds use `nodes` for nodes and `topology_edges` for edges. The edge frame is identified by its `source`/`target` fields when rows exist; avoiding the magic `edges` refId prevents Grafana 12 from treating an empty edge response as a broken node frame.

Do not start the standalone Grafana service from the Network-Topology compose stack on this host. This repo already owns Grafana on port `3000`; use the topology Postgres service only.

## Publish And Load

Install and start the topology PostgreSQL listener on this Grafana host:

```bash
cd /home/appsadmin/grafana-mimir-observability
make topology-postgres-install
```

Publish from canonical topology data, then load the published tables:

```bash
cd /home/appsadmin/grafana-mimir-observability
make topology-publish TOPOLOGY_NETBOX_BASE_URL="http://netbox.example"
make topology-load
```

## DNAC-Sourced Topology

When Catalyst Center is the topology source of truth, publish directly from its
read-only topology APIs:

```bash
cd /home/appsadmin/grafana-mimir-observability
make topology-publish-dnac
sudo -v
make topology-load-dnac
```

`topology-publish-dnac` reads DNAC connection values from the existing
read-only Catalyst Center secret,
`/etc/grafana-mimir-observability/secrets/dnac-readonly.env`, by default and
calls:

- `/dna/intent/api/v1/topology/site-topology`
- `/dna/intent/api/v1/topology/physical-topology`
- `/dna/intent/api/v1/network-device`

It writes dashboard-ready CSVs to `data/network-topology/dnac/`, which is
ignored by git as operational data. The loader then replaces
`topology_nodes_v1` and `topology_edges_v1` with those DNAC-derived rows.
DNAC link speeds are normalized from Catalyst Center Kbps values into Gbps
labels for the edge main stat. Edge color is assigned from the normalized
bandwidth: sub-1G red, 1G orange, 2.5G yellow, 5G green, 10G cyan, 25G blue,
40G purple, 100G+ violet, and unknown gray.

For a dashboard proof-of-concept without depending on the current canonical topology dataset, load the repo-local mock topology:

```bash
make topology-load-poc
```

Useful overrides:

```bash
make topology-load TOPOLOGY_POSTGRES_HOST=127.0.0.1 TOPOLOGY_POSTGRES_PORT=15432
make topology-load TOPOLOGY_PSQL_BIN=psql
TOPOLOGY_POSTGRES_PASSWORD="..." make topology-load
```

The default loader path uses `scripts/topology_psql_in_container.sh`, which runs `psql` inside the local `network-topology-postgres` container. `make topology-load` prompts for sudo first because the systemd container is root-owned. Use `TOPOLOGY_PSQL_BIN=psql` when a host PostgreSQL client is installed and the database is reachable directly.

## Deploy Grafana Integration

After committing the repo changes, promote the dashboard and datasource through the existing deploy path:

```bash
make deploy
```

If this is an emergency local-VM deploy from a dirty tree:

```bash
PROM_URL="http://127.0.0.1:9090" MIMIR_URL="http://127.0.0.1:9009" GRAFANA_URL="http://127.0.0.1:3000" bash ./scripts/pipeline.sh deploy --allow-dirty
```

Run that deploy command as `appsadmin`, not through `sudo`; the script uses sudo internally for runtime writes.

## Verification

Check the database has rows:

```bash
set -a; source /etc/grafana-mimir-observability/secrets/topology-postgres.env; set +a
PGPASSWORD="$TOPOLOGY_POSTGRES_PASSWORD" psql -h 127.0.0.1 -p 15432 -U topology -d topology -c 'select (select count(*) from topology_nodes_v1) as nodes, (select count(*) from topology_edges_v1) as edges;'
```

Check Grafana is running:

```bash
curl -fsS http://127.0.0.1:3000/api/health
```

If the dashboard has no data, verify the Postgres listener on `127.0.0.1:15432`, rerun `make topology-load-dry-run`, then rerun `make topology-load`.
