# Vocera Iperf QoE Textfile Pipeline

Laptop probes upload completed iperf3 JSON files to:

```text
/var/lib/vocera-iperf-qoe/incoming/<DEVICE>/raw/*.json
```

The exporter scans those uploads, ignores temporary `*.iperf.json` files, keeps
the newest completed result for each device/direction/target series, and writes:

```text
data/vocera-iperf-qoe/out/vocera_iperf_qoe.prom
/var/lib/node_exporter/textfile_collector/vocera_iperf_qoe.prom
```

Node exporter then exposes the `vocera_iperf_*` gauges for Prometheus, Mimir,
and Grafana.

## Manual Run

```bash
make vocera-iperf-qoe-parse
sudo install -D -m 0644 \
  data/vocera-iperf-qoe/out/vocera_iperf_qoe.prom \
  /var/lib/node_exporter/textfile_collector/vocera_iperf_qoe.prom
```

Check the exported metrics:

```bash
curl -fsS http://127.0.0.1:9100/metrics | grep '^vocera_iperf_'
```

## Systemd Install

```bash
sudo bash ./scripts/install_vocera_iperf_qoe_textfile.sh --enable --start-now
```

Host-specific overrides live in:

```text
/etc/default/vocera-iperf-qoe-textfile
```

The optional config file is:

```text
config/vocera-iperf-qoe.example.yaml
```

Newer laptop uploads carry labels in their `metadata` object. The config file is
mainly for older raw iperf JSON and friendly target names.

## Raw Latency

Standard iperf3 JSON does not include true latency. The exporter publishes
`vocera_iperf_raw_latency_seconds` only when the laptop wrapper adds a companion
latency/RTT value to the uploaded JSON metadata.

Accepted metadata keys:

```json
{
  "metadata": {
    "raw_latency_ms": 12.5
  }
}
```

The exporter also accepts `latency_ms`, `rtt_ms`, `ping_rtt_ms`,
`ping_avg_ms`, `ping_rtt_avg_ms`, or the same names with `_seconds`.
