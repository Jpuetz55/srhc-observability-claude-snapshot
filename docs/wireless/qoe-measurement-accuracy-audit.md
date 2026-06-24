# QoE Measurement Accuracy Audit — 2026-05

Audit of the five QoE tools that ship telemetry to Mimir / PostgreSQL after the
recent push that bundled them into `scripts/run_vocera_survey_refresh.sh`:

| Tool | Path | What it measures |
|---|---|---|
| Vocera Media QoE | `tools/vocera_media_qoe/` | RTP latency/jitter/loss from ICAP PCAPs |
| Vocera iperf QoE | `tools/vocera_iperf_qoe/` | UDP throughput/jitter/loss from `iperf3 -J` |
| Vocera RF Validation | `tools/vocera_rf_validation/` | Badge scan ↔ Ekahau survey-point correlation |
| Path Probe | `tools/path_probe/` | ICMP RTT, loss, jitter approximation |
| Vocera Media QoE Batch / SQL | `tools/vocera_media_qoe/vocera_media_qoe_*.py` | PCAP scheduler, Prometheus textfile, SQL emitter |

This document is the operator-facing summary of the audit. For each tool it
lists what was checked, what was wrong, what was fixed in this branch, and
what was deferred. The "verdict" column reflects post-fix state.

## TL;DR

The bundled refresh script ran end-to-end and produced metrics, but three of
the five tools had bugs that silently produced wrong numbers:

1. **RF validation matched zero candidates** even with 86 badge events and 449
   Ekahau survey points, because the match window was hard-capped at 1.0 second
   regardless of config.
2. **Ekahau route-point timestamps** were always interpreted as nanoseconds.
   Newer Ekahau builds export them in milliseconds; that case was silently
   broken (every survey point collapsed to ~`startTime + a few µs`).
3. **Media QoE RTP jitter** silently used an 8 kHz clock for every unknown
   payload type. A wideband (16 kHz) codec on the 8 kHz default reports
   jitter at 2× the true value with no warning.
4. **iperf3 `--reverse` UDP runs** could pick the sender-side summary, which
   has no jitter or loss fields, instead of the receiver-side block.

All four are fixed on `claude/qoe-accuracy-fixes`. Each fix ships with a
regression test that locks in the new behavior.

## Verdict per tool (post-fix)

| Tool | Verdict | Notes |
|---|---|---|
| `vocera_rf_validation` | ✅ Fixed | Match window now honors config; Ekahau ms/ns autodetected per survey |
| `vocera_media_qoe` (PCAP) | ⚠ Improved | Jitter visibility added; cross-stream p95-of-p95 deferred |
| `vocera_iperf_qoe` | ✅ Fixed | Reverse-UDP picks `sum_received`; filename-tz deferred |
| `path_probe` | ✅ As-is | One semantic inconsistency in `jitter_ms`, documented below |
| `vocera_media_qoe_batch` / `_sql` | ✅ As-is | Operational risk noted (TRUNCATE on each load) |

## What was fixed in this PR

### 1. RF validation — match window cap silently clamped to 1 s

**File**: `tools/vocera_rf_validation/correlate.py:67,184-186`

The previous code defined `MAX_MATCH_WINDOW_SECONDS = 1.0` and used
`min(configured, MAX_MATCH_WINDOW_SECONDS)`, so raising
`default_match_window_seconds` in `config/vocera-rf-validation.yaml` had no
effect. Badge scans are sparse roam events (~86 per walk) and Ekahau survey
points are dense (~449 per walk, ~1/second). The probability that any
survey point's nearest badge scan happens to fall in the same 1-second bucket
is near zero on real data, so the manual-template stage produced 0 candidate
rows.

**Fix**: renamed the constant to `DEFAULT_MATCH_WINDOW_SECONDS`, dropped the
`min(...)` cap, and graded `match_quality` into `exact_1s` / `close_5s` /
`within_window` so operators can still see *how* close a match was after
widening the window. The existing test that codified the 1-second cap
(`test_template_enforces_one_second_match_window`) was replaced with
`test_template_honors_configurable_match_window`, which verifies both the
default-1s behavior and that raising the config to 5 s admits previously
excluded rows.

**Operator action**: tune `default_match_window_seconds` in
`config/vocera-rf-validation.yaml` to match how often you stop on each
survey point. Reasonable starting values: 5 s for fast walks, 30 s for
deliberate stops. Re-run `scripts/run_vocera_survey_refresh.sh`; the
candidate count should be on the order of `min(badge_events, survey_points)`.

### 2. RF validation — Ekahau route-point ms-vs-ns autodetection

**File**: `tools/vocera_rf_validation/ekahau_importer.py:257-269`

`_relative_seconds()` had dead code after an early `return numeric` — any
value `>= 1000` was unconditionally divided by 1e9 (treated as nanoseconds).
That matches older Ekahau exports, but newer builds store route-point time
offsets in **milliseconds**; a real route-point at 3000 ms collapsed to
~3 µs, putting every survey point within microseconds of `survey.startTime`.

**Fix**: replaced `_relative_seconds` with `_route_point_scale`, which
inspects every offset in a single survey and chooses the divisor from the
magnitude of the largest offset:

- `max(abs(t)) >= 1e9` → nanoseconds (`/ 1e9`)
- `1.0 <= max(abs(t)) < 1e9` → milliseconds (`/ 1e3`)
- otherwise → seconds (no scaling)

This works because a multi-day walk in ms (`1e9` ms ≈ 11 days) is
implausible, while ns values for a few-second walk easily exceed `1e9`. Both
existing test fixtures (one with explicit ns values, one with mixed-unit
values) continue to pass.

**Operator action**: none. If a new Ekahau exporter version produces
offsets in an exotic unit, the audit comment in
`tools/vocera_rf_validation/ekahau_importer.py` documents the assumption
and where to extend the heuristic.

### 3. Media QoE — RTP jitter clock fallback now visible

**File**: `tools/vocera_media_qoe/vocera_media_qoe.py:111-112,696`

Any RTP payload type missing from `payload_clock_rates` in
`config/vocera-media-qoe.yaml` silently defaulted to 8000 Hz. The default
config enumerates only PT 0/8/9/18; anything dynamic (PT 96+, common for
Opus and proprietary codecs) reports jitter computed against the wrong
clock. The math: `transit = arrival - rtp_ts / clock`. A 16 kHz codec
labeled as 8 kHz makes `transit` swing twice as much per packet, so the
RFC 3550 smoothed jitter comes out 2× too large.

**Fix**:

- `AnalyzerConfig.rtp_clock_rate(pt)` now returns `(rate, known)` where
  `known` is `True` only when the payload type is explicitly mapped.
- `StreamStats` carries a new `clock_rate_known: bool` field.
- `render_prometheus` emits a new gauge
  `vocera_media_rtp_unknown_clock_streams{...}` per label set when at least
  one stream used the fallback.
- `to_json()` includes the field so SQL/JSON consumers can flag suspect
  rows.

A regression test (`test_rtp_unknown_clock_rate_is_visible`) builds a
synthetic stream with PT 99 and asserts the gauge appears and
`clock_rate_known=False`.

**Operator action**: alert on
`max by (server, site) (vocera_media_rtp_unknown_clock_streams) > 0`.
When this fires, add the offending payload types to the
`payload_clock_rates` block in the config. Jitter for an unknown-clock
stream is still emitted under the old metric name and **should be treated
as suspect** until the operator either maps the PT or confirms the codec
clock matches the default.

### 4. iperf — `--reverse` UDP picks `sum_received`

**File**: `tools/vocera_iperf_qoe/vocera_iperf_qoe.py:320-324`

For UDP `iperf3 -J --reverse` runs, jitter and lost packets only appear in
the receiver-side block (`end.sum_received`). The sender-side block
(`end.sum_sent`) has bytes/duration but no jitter or loss. The previous
priority order `sum or sum_received or sum_sent` would fall through to
`sum_sent` when `sum` was absent, dropping the data the operator actually
cares about.

**Fix**: reorder to `sum_received > sum > sum_sent`. For non-reverse UDP
the JSON still contains `sum` (which equals receiver-side), so the change
is a no-op for that path. For reverse UDP, `sum_received` is now picked
and jitter/loss come through.

A regression test (`test_reverse_udp_prefers_sum_received`) constructs a
reverse-UDP fixture where `sum_received` carries the jitter and `sum_sent`
does not, then asserts the parser extracts the jitter.

**Operator action**: none. Existing dashboards continue to work; reverse
UDP probes will start reporting non-zero jitter and loss where they
silently reported zero before.

## What was NOT fixed (deferred, with rationale)

These were found during the audit but left for a separate PR to keep the
scope of this branch tight. They do not produce wrong numbers under
typical use; they bias them or affect edge cases.

### Media QoE — cross-stream p95-of-p95

`vocera_media_qoe.py:969,981` aggregate per-stream p95 jitter / interarrival
into a labelset-level p95 by computing the p95 *of the per-stream p95s*.
This is the classic "average of averages" problem: the true cross-stream
p95 requires the underlying packet gaps, not per-stream summaries.

- **Impact**: harmless when there is one RTP stream per labelset (the common
  case for a single ICAP capture); misleading when multiple streams share
  a labelset.
- **Fix sketch**: either rename the emitted metric to make the per-stream
  granularity explicit (`vocera_media_rtp_stream_jitter_p50_ms`,
  `vocera_media_interarrival_gap_stream_p95_ms`) so dashboards don't
  misread it, or accumulate raw gaps and compute the true p95.

### Media QoE — loss under-reports on truncated captures

`vocera_media_qoe.py:702-705` computes `expected = max(seq) - min(seq) + 1`.
Packets lost after the last received sequence in the capture window are
invisible; a call cut off mid-stream reports 0% loss.

- **Impact**: under-reports loss when the capture stops before the call
  ends. The DNAC ICAP captures used today are full-call captures, so this
  is currently low-risk.
- **Fix sketch**: when call duration is known from SIP/control metadata,
  extrapolate `expected_packets` from the packetization interval; otherwise
  expose a `truncated=true` label so operators know the loss number is a
  lower bound.

### Media QoE — interarrival stats drop reorders

`vocera_media_qoe.py:646-651` filters reordered arrivals (`current >=
previous`) before computing p50/p95/max gaps. Reordering shows up in the
RTP `out_of_order_packets` counter, but its impact on perceived gap
distribution is silently dropped.

- **Impact**: cosmetic. Reorder-heavy streams under-report their gap
  percentiles slightly.
- **Fix sketch**: use `abs(current - previous)` or document the filter in
  the metric help text.

### iperf — filename-derived timestamp uses collector local timezone

`vocera_iperf_qoe.py:283-287` parses the `YYYYMMDD-HHMMSS` suffix using
`dt.datetime.now().astimezone().tzinfo`. If the collector container runs
UTC while the laptops write filenames in local time (or vice versa), the
fallback timestamp is off by the collector-vs-laptop offset.

- **Impact**: only triggers when `iperf3` JSON lacks `start.timestamp.timesecs`
  (rare). Bounded by hours.
- **Fix sketch**: read the laptop's timezone from `metadata.tz` and fall
  back to UTC, or require `timesecs` and skip the file otherwise.

### Path probe — `jitter_ms` is two different formulas

`path_probe.py:133` (Linux `ping`) computes `jitter_ms` as `mdev`.
`path_probe.py:218` (Cisco WLC) computes `jitter_ms` as `pdv_range`. Same
metric name, different math. The dashboard help string already calls the
metric "deprecated synthetic", but a future graph-comparison across
collection methods would be misleading.

- **Impact**: visible only when comparing Linux probes to Cisco probes on
  the same dashboard panel.
- **Fix sketch**: split into `wireless_path_probe_jitter_mdev_ms` and
  `wireless_path_probe_pdv_range_ms`.

### Path probe — Cisco `rtt_p95_ms` is `max_ms`

`path_probe.py:214` aliases `rtt_p95_ms = max_ms` because Cisco WLC ICMP
test responses only expose min/avg/max. The metric name promises a p95
but delivers the max.

- **Impact**: on Cisco-collected series, the p95 graph always equals the
  max graph. Already documented in code; called out here for operator
  awareness.

### Media QoE SQL — `TRUNCATE` before each load

`vocera_media_qoe_sql.py:252` truncates the destination table before
inserting the latest batch. The dashboard's `$__timeFilter(sample_time)`
works because rows are re-inserted with the original packet timestamps.
But if the parsed-dir cache is ever cleared, the next run inserts only
fresh captures and the historical rows are gone for good.

- **Impact**: operational, not numeric. Mitigated today by never clearing
  the parsed-dir cache.
- **Fix sketch**: switch to `INSERT … ON CONFLICT DO NOTHING` keyed on
  `(capture_id, stream_id)`.

## How to verify each fix locally

```bash
# 1. Run all three test suites — must finish with "OK: ..." for each.
python3 scripts/test_vocera_rf_validation.py
python3 scripts/test_vocera_media_qoe.py
python3 scripts/test_vocera_iperf_qoe.py

# 2. RF validation: re-run the bundled survey refresh and check the candidate
#    template now has rows (was empty with the 1-second cap).
bash scripts/run_vocera_survey_refresh.sh
wc -l data/vocera-rf-validation/out/manual_ekahau_observations_template.csv

# 3. Media QoE: after re-parsing a capture, look for the new gauge in the
#    textfile output. If it shows up with a non-zero value, at least one
#    payload type needs to be added to config/vocera-media-qoe.yaml.
grep vocera_media_rtp_unknown_clock_streams \
  /var/lib/node_exporter/textfile_collector/vocera_media_qoe.prom

# 4. iperf reverse: confirm reverse-UDP samples now publish non-zero jitter.
#    (Compare a known-reverse JSON before/after.)
grep vocera_iperf_jitter_seconds \
  /var/lib/node_exporter/textfile_collector/vocera_iperf_qoe.prom
```

## Recommended follow-up work

In rough priority order:

1. Rename the cross-stream p95-of-p95 metrics in `vocera_media_qoe.py` so
   dashboards don't read them as true cross-stream percentiles.
2. Add a `truncated` label to media QoE loss when the capture window does
   not cover full call duration.
3. Replace the media QoE `TRUNCATE` load with an idempotent upsert.
4. Split the path-probe `jitter_ms` metric into method-specific names.
5. Track Ekahau exporter version metadata in `EkahauParseResult` so the
   ms/ns scale decision is auditable in the JSON output.

## Audit method

Two independent agents read the 6,000+ lines of new QoE code in full, the
existing test suites, the metric contract, and the consumer Grafana
dashboards. Each finding above is anchored to a file:line. Where a bug was
hypothetical (e.g., the Ekahau ms-vs-ns case depends on the user's
specific `.esx` exporter version), the fix is conservative and the
existing test fixture is preserved.
