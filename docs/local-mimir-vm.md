# Local Mimir VM Deployment

This profile runs Mimir locally on the collectors VM and keeps Prometheus as the 30-day local-retention scraper and rule evaluator.

## Runtime model

- Mimir listens on `127.0.0.1:9009`.
- Prometheus remote-writes samples to `http://127.0.0.1:9009/api/v1/push`.
- Grafana queries Mimir at `http://127.0.0.1:9009/prometheus`.
- Mimir stores blocks under `/var/lib/prometheus/mimir`.
- Prometheus stores its 30-day local buffer under `/var/lib/prometheus/local-tsdb`.
- Prometheus local TSDB is capped at 300GB and remains separate from the longer-term Mimir store.

## First-time install

```bash
cd /home/appsadmin/grafana-mimir-observability
sudo bash ./scripts/install_mimir_local_vm.sh
```

The installer uses the existing `prometheus` service account, installs `/usr/local/bin/mimir` if missing, deploys `/etc/mimir/mimir.yaml`, installs `mimir.service`, and starts the service.

The default binary is pinned to Mimir `3.0.6` and verified with SHA-256 before install. Override `MIMIR_VERSION`, `MIMIR_ASSET`, `MIMIR_DOWNLOAD_URL`, and `MIMIR_SHA256` together when intentionally changing versions.

## Cutover

After Mimir is healthy, deploy the repo:

```bash
bash ./scripts/pipeline.sh deploy --allow-dirty
```

Verify local Mimir:

```bash
curl -fsS http://127.0.0.1:9009/ready
curl -fsS http://127.0.0.1:9009/prometheus/api/v1/query --data-urlencode 'query=up'
```

## Prometheus TSDB recovery

If `/var/lib/prometheus` is full, export what you need, then delete only the TSDB contents and keep the parent directory owned by Prometheus:

```bash
sudo systemctl stop prometheus
sudo find /var/lib/prometheus -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
sudo chown prometheus:prometheus /var/lib/prometheus
sudo chmod 750 /var/lib/prometheus
```

Do not start Prometheus with the old service override after clearing the TSDB. Run the repo deploy next so Prometheus starts with `/var/lib/prometheus/local-tsdb` and the 30-day/300GB retention cap.
