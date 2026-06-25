# Network topology PostgreSQL integration

This repository provides the local PostgreSQL datasource contract for topology
visualization. The canonical topology data and publishing logic remain owned by
the sibling `Network-Topology` repository, normally checked out as:

```text
/home/appsadmin/Network-Topology
```

## Current status

- The local topology PostgreSQL service and Grafana datasource definition are
  maintained here.
- The current tested Grafana dashboard inventory does **not** include a
  provisioned Network Topology dashboard. Do not claim a topology dashboard is
  live solely because the datasource has rows.
- A future topology dashboard must be added to both dashboard trees and the
  dashboard-inventory contract in the same change.

## Runtime contract

| Item | Value |
| --- | --- |
| Datasource UID | `TOPOLOGY_DS` |
| PostgreSQL listener | `127.0.0.1:15432` |
| Database / user | `topology` / `topology` |
| Tables/views | `topology_nodes_v1`, `topology_edges_v1` |
| Schema | `topology/postgres/init/001_topology_tables.sql` |
| Credentials | `/etc/grafana-mimir-observability/secrets/topology-postgres.env` |

Do not run the standalone Grafana service from a Network-Topology compose
stack on this host. Grafana on port `3000` is owned by this repository.

## Install the database service

```bash
cd /home/appsadmin/grafana-mimir-observability
make topology-postgres-install
```

The service runs a local Podman PostgreSQL container and binds it only on
`127.0.0.1:15432`.

## Publish and load canonical topology

```bash
cd /home/appsadmin/grafana-mimir-observability

# Validates source data in ../Network-Topology by default.
make topology-validate

# Publish canonical working data, then load it into local PostgreSQL.
make topology-publish TOPOLOGY_NETBOX_BASE_URL="http://netbox.example"
make topology-load
```

The loader is intentionally separated from publisher execution. Review the
published CSV output before replacing the local tables.

## Read-only Catalyst Center topology option

When Catalyst Center topology APIs are the desired source:

```bash
make topology-publish-dnac \
  TOPOLOGY_DNAC_ENV_FILE=/etc/grafana-mimir-observability/secrets/dnac-readonly.env
make topology-load-dnac
```

This uses read-only topology/device APIs and writes generated CSVs under
`data/network-topology/dnac/`, which is ignored by Git. It does not use
Catalyst Center Command Runner and does not change network-device
configuration.

`topology-publish-dnac` is the current target name. There is no
`topology-refresh-dnac` Make target.

## Verify the load

```bash
set -a
source /etc/grafana-mimir-observability/secrets/topology-postgres.env
set +a

PGPASSWORD="$TOPOLOGY_POSTGRES_PASSWORD" \
psql -h 127.0.0.1 -p 15432 -U topology -d topology \
  -c 'select (select count(*) from topology_nodes_v1) as nodes, (select count(*) from topology_edges_v1) as edges;'
```

For a source-only input validation that does not connect to PostgreSQL:

```bash
make topology-load-dry-run
```
