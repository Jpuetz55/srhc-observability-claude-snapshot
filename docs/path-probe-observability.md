# Path Probe Observability

Path probes are optional, collector-originated synthetic canaries for RTT,
RTT variation, reachability, and loss between infrastructure endpoints. They
supplement WLC telemetry and incident evidence; they are **not** RTP, Vocera
vRTP, one-way, badge-to-badge, or badge-to-server media measurements.

The current provisioned Grafana dashboards are WLC Control Plane and Vocera
Iperf QoE. Path-probe metrics are available to Prometheus/Mimir when installed,
but no path-probe dashboard is currently provisioned. Query the metric, use a
temporary Explore view, or add a reviewed dashboard through the normal
DEV → repository → PROD promotion path.

## Metrics

`tools/path_probe/path_probe.py` emits node_exporter textfile metrics:

| Metric | Meaning |
| --- | --- |
| `wireless_path_probe_up` | `1` when the latest probe received at least one reply. |
| `wireless_path_probe_rtt_min_ms` | Minimum RTT in milliseconds. |
| `wireless_path_probe_rtt_avg_ms` | Average RTT in milliseconds. |
| `wireless_path_probe_rtt_max_ms` | Maximum RTT in milliseconds. |
| `wireless_path_probe_rtt_p95_ms` | p95 RTT in milliseconds. |
| `wireless_path_probe_rtt_mdev_ms` | Population standard deviation when individual replies are available. |
| `wireless_path_probe_rtt_pdv_p95_ms` | RTT p95 minus minimum RTT when samples are available. |
| `wireless_path_probe_rtt_pdv_range_ms` | Maximum RTT minus minimum RTT. |
| `wireless_path_probe_jitter_ms` | Deprecated compatibility alias for synthetic RTT variation; not RTP jitter. |
| `wireless_path_probe_packet_loss_pct` | Packet loss percentage. |
| `wireless_path_probe_last_success_timestamp_seconds` | Last run timestamp with at least one reply. |
| `wireless_path_probe_last_run_timestamp_seconds` | Last attempted probe timestamp. |

Labels identify the logical `segment`, `source`, stable `target`,
`target_type`, and `method`.

## Run locally

```bash
cp config/path-probe.example.yaml config/path-probe.yaml

PYTHONPATH=tools/path_probe:tools/wireless_rf python3 -m path_probe \
  --config config/path-probe.yaml \
  --prom-out data/path-probe/out/path_probe.prom

sudo install -D -m 0644 data/path-probe/out/path_probe.prom \
  /var/lib/node_exporter/textfile_collector/path_probe.prom
```

## Systemd

Install after creating a real, approved target configuration:

```bash
sudo bash ./scripts/install_path_probe_textfile.sh
sudo systemctl start wireless-path-probe.service
sudo systemctl enable --now wireless-path-probe.timer
```

Use wording such as “collector-to-server RTT” or “WLC-to-AP RTT.” Do not label
these values as media latency or media jitter.
