# Local Mimir VM deployment and recovery

## Runtime model

The collectors VM runs a single filesystem-backed Mimir instance. Prometheus
remains the scraper and recording-rule evaluator; it remote-writes the curated
metric surface to Mimir for Grafana queries.

| Component | Endpoint / data path |
| --- | --- |
| Mimir read/write API | `127.0.0.1:9009` |
| Prometheus remote write | `http://127.0.0.1:9009/api/v1/push` |
| Grafana PromQL datasource | `http://127.0.0.1:9009/prometheus` |
| Mimir data | `/var/lib/prometheus/mimir/` |
| Prometheus local TSDB | `/var/lib/prometheus/local-tsdb/` |

The current Mimir config is single-node and has `multitenancy_enabled: false`.
Prometheus has its own capped local TSDB for scrape/rule diagnostics; it is not
the Mimir store.

## Install or reconcile Mimir

```bash
cd /home/appsadmin/grafana-mimir-observability
make mimir-install
make mimir-health
```

After a healthy install, bring the repo-managed configuration into alignment:

```bash
make plan
make deploy
```

Verify both APIs:

```bash
curl -fsS http://127.0.0.1:9009/ready
curl -fsSG http://127.0.0.1:9009/prometheus/api/v1/query \
  --data-urlencode 'query=up'
```

## Safe Prometheus local-TSDB recovery

Use this only when the **Prometheus local TSDB** is corrupt or needs to be
recreated. It does not repair Mimir and it must not delete Mimir data.

1. Confirm the exact two paths before stopping anything:

   ```bash
   sudo du -sh /var/lib/prometheus/local-tsdb /var/lib/prometheus/mimir
   sudo systemctl status prometheus mimir --no-pager -l
   ```

2. Stop Prometheus only:

   ```bash
   sudo systemctl stop prometheus
   ```

3. Remove the contents of **only** the local Prometheus TSDB:

   ```bash
   sudo test -d /var/lib/prometheus/local-tsdb
   sudo find /var/lib/prometheus/local-tsdb -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
   sudo chown -R prometheus:prometheus /var/lib/prometheus/local-tsdb
   ```

4. Start Prometheus and verify rules/scrapes:

   ```bash
   sudo systemctl start prometheus
   sudo systemctl status prometheus --no-pager -l
   curl -fsS http://127.0.0.1:9090/-/ready
   ```

**Never run a broad delete under `/var/lib/prometheus/`.** In particular, do
not remove `/var/lib/prometheus/mimir/`; that directory contains Mimir blocks,
TSDB state, compactor data, ruler storage, and activity logs.

If the repo-managed Prometheus command-line flags or config are suspected to
be stale, run `make plan` and `make deploy` after the local TSDB is healthy.
