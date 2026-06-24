#!/usr/bin/env bash
# List the newest uploaded iperf JSON artifacts on the collector so operators
# can confirm both laptop probes are still sending results.
set -euo pipefail

BASE="${BASE:-/var/lib/vocera-iperf-qoe/incoming}"

find "${BASE}" -type f -printf '%TY-%Tm-%Td %TH:%TM %p\n' | sort | tail -50
