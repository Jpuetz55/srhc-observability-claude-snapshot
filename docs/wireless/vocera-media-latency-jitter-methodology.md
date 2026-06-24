# Vocera Media Latency And Jitter Methodology

This dashboard must not treat WLC RF counters as badge-to-badge or badge-to-server
voice quality measurements. The most accurate media measurements come from the
actual packet stream, observed at the receiver or at a tap that can identify the
stream.

## Authoritative Model

For RTP media, use RFC 3550 receiver-side interarrival jitter. It is based on
the smoothed absolute difference between sender packet spacing and receiver
arrival spacing. Packet loss comes from RTP sequence gaps. If Vocera vRTP can be
decoded into packet sequence and timestamp fields, use the same model.

For generic IP path delay variation, use RFC 3393/RFC 5481 terminology:
one-way packet delay variation requires packet timing at two measurement points.
For jitter-buffer sizing, RFC 5481 favors packet delay variation relative to the
minimum observed delay in the interval, for example `delay_p95 - delay_min` or
`delay_max - delay_min`.

For voice planning, ITU-T G.114 is the latency reference. Vocera-specific
documents call out a 108 ms badge jitter buffer and warn that around 150 ms of
delay may affect spoken-word flow. Cisco's Vocera deployment guide recommends
latency below 100 ms, jitter below 100 ms, and packet loss below 1 percent for a
Vocera/Cisco wireless network.

## Current Metrics

`wireless_ap_voice_latency_*` is Cisco AP traffic-distribution latency. Cisco
defines that as the time, in microseconds, for a packet to be successfully
transmitted from the AP to the client for a given access category. It is useful
RF and airtime context for AC_VO traffic, but it is not badge-to-badge latency,
badge-to-server latency, RTP jitter, or mouth-to-ear delay.

`wireless_badge_client_run_state_latency_us` is WLC client mobility history time
until RUN state. It is onboarding state timing, not media latency.

`wireless_path_probe_*` is synthetic RTT/loss/delay-variation probing. It is a
path canary. It is not RTP interarrival jitter because ICMP probe samples do not
carry RTP timestamps or media sequence numbers and usually do not originate from
the badge.

## Recommended Measurements

Use these tiers, in order of accuracy:

1. Passive media capture at the Vocera Voice Server or a SPAN/TAP point that
   sees badge media. Calculate per direction and per stream:
   `packets_total`, `lost_packets_total`, `loss_pct`, `rtp_interarrival_jitter_ms`,
   `interarrival_gap_p95_ms`, and `late_packets_over_buffer_total`.
2. If packet timestamps and synchronized clocks are available at source and
   receiver, calculate one-way latency per packet as receive time minus send
   time, then report median, p95, and PDV p95.
3. If only one capture point is available, calculate receiver-side jitter,
   packet loss, interarrival gaps, and reorder/late-packet behavior. Do not label
   this one-way latency.
4. If no media stream is available, use DSCP/port-sized UDP probes from the same
   VLAN and QoS class as the badge. Label those as synthetic path probes, not
   media QoE.
5. Use AP traffic-distribution latency, retries, RSSI, SNR, channel utilization,
   and neighbor/DFS context to explain RF causes after media QoE has been
   measured.

## Badge-To-Badge Vs Badge-To-Server

Treat each media leg separately:

- Badge to server: capture packets sent from badge IPs to Vocera server audio
  ports and compute receiver-side media stats at the server side.
- Server to badge: capture packets sent from Vocera server audio ports to badge
  IPs and compute receiver-side stats as close to the badge side as possible.
- Badge to badge: if media is server-relayed, report it as two legs:
  badge A to server and server to badge B. If media is direct peer-to-peer,
  capture near at least one receiving badge or at a network point that sees both
  directions and can identify both badge IPs.

## Dashboard Rule

Dashboards should have a separate `Vocera Media QoE` section only after media
stream metrics exist. Until then, existing AP voice latency panels should stay
labeled as AP traffic-distribution or AP-to-client AC_VO latency context.

## First Collector Implementation

The initial repo implementation is `tools/vocera_media_qoe/vocera_media_qoe.py`.
It analyzes offline pcaps, writes a low-cardinality Prometheus textfile, and
writes exact stream identities only to JSON.

Catalyst Center / DNAC Intelligent Capture pcaps are valid input to this offline
analyzer when the capture contains IP/UDP media packets. Use
`vocera-media-dnac-icap-runbook.md` for the manual capture workflow. Full Packet
Capture is the first media-path choice; OTA Sniffer Capture is mainly RF/WMM
evidence unless decrypted RTP headers are visible.

Prometheus labels are limited to:

- `server`
- `site`
- `capture_point`
- `direction`
- `src_role`
- `dst_role`
- `payload_type`
- `dscp`
- `measurement_mode`

JSON carries high-cardinality fields such as source/destination IPs, ports,
SSRC, stream ID, first/last seen timestamps, packet count, loss ratio, jitter,
and interarrival p95.

For the first version, Prometheus metrics are snapshot gauges over the analyzed
capture window. They are not cumulative counters.

## Sources

- RFC 3550, RTP interarrival jitter:
  https://www.rfc-editor.org/rfc/rfc3550.html
- RFC 3393, IP Packet Delay Variation:
  https://www.rfc-editor.org/rfc/rfc3393.html
- RFC 5481, Packet Delay Variation Applicability:
  https://www.rfc-editor.org/rfc/rfc5481.html
- ITU-T G.114, one-way transmission time:
  https://www.itu.int/itu-t/recommendations/rec.aspx?lang=en&rec=6254
- Cisco Catalyst 9800 Wi-Fi 6 dashboard traffic-distribution latency:
  https://www.cisco.com/c/en/us/td/docs/wireless/controller/9800/17-5/config-guide/b_wl_17_5_cg/m_stormbreaker_ewlc.html
- Cisco Wireless Vocera Deployment Guide:
  https://www.cisco.com/c/en/us/products/collateral/wireless-mobility/wireless-lan-wlan/wireless-vocera-dep-guide-og.html
- Vocera Infrastructure Planning Guide:
  https://pubs.vocera.com/vs_infrastructure/Production/docs/InfrastructureGuide.pdf
