# Path Probe Observability

The Vocera dashboard separates WLC/client telemetry from AP voice
access-category latency. Path probes fill a different gap: synthetic network
RTT, RTT delay variation, and loss between infrastructure endpoints.

These probes are not RTP or Vocera vRTP media measurements. They are canaries
for reachability and path health. Use packet-capture or endpoint media reports
for badge-to-badge and badge-to-server voice jitter.

## Metrics

`tools/path_probe/path_probe.py` emits node_exporter textfile metrics:

| Metric | Meaning |
| --- | --- |
| `wireless_path_probe_up` | `1` when the latest probe received at least one reply. |
| `wireless_path_probe_rtt_min_ms` | Minimum RTT in milliseconds. |
| `wireless_path_probe_rtt_avg_ms` | Average RTT in milliseconds. |
| `wireless_path_probe_rtt_max_ms` | Maximum RTT in milliseconds. |
| `wireless_path_probe_rtt_p95_ms` | p95 RTT in milliseconds. |
| `wireless_path_probe_rtt_mdev_ms` | Population standard deviation of RTT samples when individual ping replies are available. |
| `wireless_path_probe_rtt_pdv_p95_ms` | RFC 5481-style RTT packet delay variation p95, calculated as RTT p95 minus minimum RTT when individual samples are available. |
| `wireless_path_probe_rtt_pdv_range_ms` | RTT packet delay variation range, calculated as max RTT minus min RTT. |
| `wireless_path_probe_jitter_ms` | Deprecated compatibility alias for synthetic RTT variation. Do not treat it as RTP interarrival jitter. |
| `wireless_path_probe_packet_loss_pct` | Packet loss percentage. |
| `wireless_path_probe_last_success_timestamp_seconds` | Last run timestamp with at least one reply. |
| `wireless_path_probe_last_run_timestamp_seconds` | Last attempted probe run timestamp. |

Labels:

| Label | Meaning |
| --- | --- |
| `segment` | Path segment, such as `collector_to_badge` or `collector_to_server`. |
| `source` | Logical source, such as `collectors01`. |
| `target` | Stable target name for dashboard legends. |
| `target_type` | `ap`, `server`, or `badge`. |
| `method` | Probe method, currently `system_ping`. |

## Running locally

Create a site-specific config from the example:

```bash
cp config/path-probe.example.yaml config/path-probe.yaml
```

Then run:

```bash
PYTHONPATH=tools/path_probe:tools/wireless_rf python3 -m path_probe \
  --config config/path-probe.yaml \
  --prom-out data/path-probe/out/path_probe.prom
```

Publish into node_exporter's textfile collector:

```bash
install -D -m 0644 data/path-probe/out/path_probe.prom \
  /var/lib/node_exporter/textfile_collector/path_probe.prom
```

## Systemd

Install the service and timer after creating a real site config:

```bash
sudo bash ./scripts/install_path_probe_textfile.sh
```

Enable only after `PATH_PROBE_CONFIG` points at a config with real targets:

```bash
sudo systemctl start wireless-path-probe.service
sudo systemctl enable --now wireless-path-probe.timer
```

## Dashboard wording

Path probes are collector-originated round-trip measurements and must not be
labeled as RTP jitter, mouth-to-ear latency, badge-to-badge latency, or
badge-to-server media latency.
