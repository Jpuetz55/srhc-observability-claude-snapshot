# Path probe collector

`tools/path_probe/path_probe.py` runs bounded RTT probes and writes
node_exporter textfile metrics. It fills optional synthetic path-health gaps
that WLC telemetry and packet evidence cannot directly establish, for example:

- `collector_to_server`
- `collector_to_badge`
- `wlc_to_server`
- `wlc_to_ap`

These are round-trip reachability measurements. Present them as `WLC <-> AP
RTT`, `collector <-> server RTT`, and similar labels. They are not one-way
AP-to-WLC latency, RTP jitter, or Vocera media quality. The current provisioned
dashboard inventory does not include a path-probe dashboard.

```bash
PYTHONPATH=tools/path_probe:tools/wireless_rf python3 -m path_probe \
  --config config/path-probe.example.yaml \
  --prom-out data/path-probe/out/path_probe.prom

sudo install -D -m 0644 data/path-probe/out/path_probe.prom \
  /var/lib/node_exporter/textfile_collector/path_probe.prom
```

See [`docs/path-probe-observability.md`](../../docs/path-probe-observability.md)
for installation, metric definitions, and operational boundaries.
