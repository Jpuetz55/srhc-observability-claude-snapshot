-- Contract query for node payload fields consumed by the Node Graph panel.
-- Dashboard-level filters are applied in panel JSON rawSql using:
--   site_filter, environment_filter, lineage_filter, confidence_focus.
-- Keep selected metadata fields in sync with those predicates.
SELECT
  id,
  title,
  subtitle,
  mainstat,
  secondarystat,
  color,
  confidence,
  arc__green,
  arc__yellow,
  arc__red,
  site_id,
  environment,
  source_lineage,
  detail_url AS "detail__url"
FROM topology_nodes_v1
ORDER BY id;
