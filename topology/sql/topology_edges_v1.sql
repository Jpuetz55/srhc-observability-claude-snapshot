-- Contract query for edge payload fields consumed by the Node Graph panel.
-- Dashboard-level filters are applied in panel JSON rawSql using:
--   site_filter, environment_filter, lineage_filter, confidence_focus.
-- Keep selected metadata fields in sync with those predicates.
SELECT
  id,
  source,
  target,
  mainstat,
  secondarystat,
  color,
  confidence,
  site_id,
  environment,
  source_lineage,
  detail AS "detail__source"
FROM topology_edges_v1
ORDER BY id;
