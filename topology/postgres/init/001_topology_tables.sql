-- Tables consumed by grafana/dashboards/topology-node-graph.v1.json.
-- Keep columns aligned with scripts/publish_node_graph.py and grafana/sql/*.sql.

CREATE TABLE IF NOT EXISTS topology_nodes_v1 (
    id text PRIMARY KEY,
    title text NOT NULL,
    subtitle text NOT NULL,
    mainstat text NOT NULL,
    secondarystat text NOT NULL,
    color text NOT NULL,
    confidence text NOT NULL,
    arc__green integer NOT NULL,
    arc__yellow integer NOT NULL,
    arc__red integer NOT NULL,
    site_id text NOT NULL,
    environment text NOT NULL,
    source_lineage text NOT NULL,
    detail_url text NOT NULL
);

CREATE TABLE IF NOT EXISTS topology_edges_v1 (
    id text PRIMARY KEY,
    source text NOT NULL,
    target text NOT NULL,
    mainstat text NOT NULL,
    secondarystat text NOT NULL,
    color text NOT NULL,
    confidence text NOT NULL,
    site_id text NOT NULL,
    environment text NOT NULL,
    source_lineage text NOT NULL,
    detail text NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_topology_nodes_site_environment
    ON topology_nodes_v1 (site_id, environment);

CREATE INDEX IF NOT EXISTS idx_topology_nodes_confidence
    ON topology_nodes_v1 (confidence);

CREATE INDEX IF NOT EXISTS idx_topology_edges_source_target
    ON topology_edges_v1 (source, target);

CREATE INDEX IF NOT EXISTS idx_topology_edges_site_environment
    ON topology_edges_v1 (site_id, environment);

CREATE INDEX IF NOT EXISTS idx_topology_edges_confidence
    ON topology_edges_v1 (confidence);
