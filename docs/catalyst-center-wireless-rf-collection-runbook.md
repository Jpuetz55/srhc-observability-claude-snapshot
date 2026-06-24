# Retired Catalyst Center wireless RF collection workflow

Catalyst Center device-command collection is intentionally unavailable in this
repo. Do not use Catalyst Center to run WLC CLI, start RF collection, or trigger
device-originated probes from this observability project.

The supported wireless RF workflow is offline/manual:

1. Collect WLC evidence outside this repo by an approved operational process.
2. Stage the raw text file under `data/wireless-rf/raw/` or another local path.
3. Run `make wireless-rf-parse INPUT=<raw-file> WLC=<wlc-label>`.
4. Review CSV, JSON, and Prometheus output before publishing.

The parser still understands WLC CLI evidence such as AP tag summaries,
auto-RF output, and AP traffic-distribution sections. The repo no longer
contains an active path that can submit Catalyst Center device-command jobs.
