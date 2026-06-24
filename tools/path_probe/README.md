# Path probe collector

`tools/path_probe/path_probe.py` runs bounded RTT probes and writes Prometheus
textfile metrics for node_exporter. The metrics are intended to fill synthetic
path-health gaps that the Vocera dashboard cannot infer from WLC RF/client
telemetry:

- `collector_to_server`
- `collector_to_badge`
- `wlc_to_server`
- `wlc_to_ap`

WLC-originated probes are round-trip measurements. Label dashboards as
`WLC <-> AP RTT` or `WLC <-> server RTT`; do not present them as one-way
AP-to-WLC latency unless a true one-way counter is added later. These probes
are not RTP or Vocera vRTP media jitter measurements.

Example:

```bash
PYTHONPATH=tools/path_probe:tools/wireless_rf python3 -m path_probe \
  --config config/path-probe.example.yaml \
  --prom-out data/path-probe/out/path_probe.prom
```

The textfile can then be copied into node_exporter's textfile collector:

```bash
install -D -m 0644 data/path-probe/out/path_probe.prom \
  /var/lib/node_exporter/textfile_collector/path_probe.prom
```
