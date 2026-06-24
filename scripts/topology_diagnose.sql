-- Network Topology node-graph diagnostic.
-- Run on the Grafana host (collectors01) against the topology Postgres:
--   sudo podman exec -i network-topology-postgres psql -U topology -d topology < scripts/topology_diagnose.sql
--
-- Goal: explain a blank Node Graph panel when the tables are populated.
-- The Grafana Node Graph needs (1) a non-empty nodes frame and (2) every edge
-- source/target to match an existing node id. This script checks both, plus the
-- arc__ values and the dashboard-variable filter behaviour.

\pset pager off
\set ON_ERROR_STOP off

\echo '================ 1. row counts ================'
SELECT (SELECT count(*) FROM topology_nodes_v1) AS nodes,
       (SELECT count(*) FROM topology_edges_v1) AS edges;

\echo ''
\echo '================ 2. orphan edges (source/target with no matching node id) ================'
\echo 'Any rows here are the classic cause of edges (and sometimes the whole graph) not drawing.'
SELECT e.id AS edge_id, e.source, e.target,
       (e.source IN (SELECT id FROM topology_nodes_v1)) AS source_ok,
       (e.target IN (SELECT id FROM topology_nodes_v1)) AS target_ok
FROM topology_edges_v1 e
WHERE e.source NOT IN (SELECT id FROM topology_nodes_v1)
   OR e.target NOT IN (SELECT id FROM topology_nodes_v1)
ORDER BY e.id;

\echo ''
\echo '================ 3. node id hygiene (duplicates / whitespace / case) ================'
\echo 'Whitespace-padded or duplicate ids silently break source/target matching.'
SELECT id, length(id) AS len
FROM topology_nodes_v1
WHERE id <> btrim(id)
   OR id IS NULL
ORDER BY id;
SELECT id, count(*) AS dupes
FROM topology_nodes_v1
GROUP BY id
HAVING count(*) > 1;

\echo ''
\echo '================ 4. arc__ sanity (each node should sum to a positive value) ================'
\echo 'A sum of 0 (or NULLs) yields a NaN arc and can drop the node border / node.'
SELECT id, arc__green, arc__yellow, arc__red,
       (COALESCE(arc__green,0) + COALESCE(arc__yellow,0) + COALESCE(arc__red,0)) AS arc_sum
FROM topology_nodes_v1
ORDER BY arc_sum ASC, id
LIMIT 20;

\echo ''
\echo '================ 5. dashboard variable filter behaviour ================'
\echo 'Normal default: variables resolve to __all -> filter is pass-through -> expect full node count.'
SELECT count(*) AS rows_when_site_filter_is_all
FROM topology_nodes_v1
WHERE ('__all' IN ('__all', '$__all') OR site_id = '__all');
\echo 'Failure mode: if a query variable failed to populate it resolves to EMPTY -> 0 rows -> blank panel.'
SELECT count(*) AS rows_when_site_filter_is_empty
FROM topology_nodes_v1
WHERE ('' IN ('__all', '$__all') OR site_id = '');

\echo ''
\echo '================ 6. distinct filter values (these feed the dashboard dropdowns) ================'
\echo 'Empty results here mean the dropdowns cannot populate via TOPOLOGY_DS.'
SELECT 'site_id' AS variable, count(DISTINCT site_id) AS distinct_values FROM topology_nodes_v1
UNION ALL
SELECT 'environment', count(DISTINCT environment) FROM topology_nodes_v1
UNION ALL
SELECT 'source_lineage', count(DISTINCT source_lineage) FROM topology_edges_v1;

\echo ''
\echo '================ 7. sample rows ================'
\x on
SELECT * FROM topology_nodes_v1 ORDER BY id LIMIT 2;
SELECT * FROM topology_edges_v1 ORDER BY id LIMIT 2;
\x off
