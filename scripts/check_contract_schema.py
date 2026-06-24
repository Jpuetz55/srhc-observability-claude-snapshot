#!/usr/bin/env python3
"""Check the metric contract covers every recording rule file."""

from __future__ import annotations
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / 'contracts' / 'metric_contract.yaml'
RULES = ROOT / 'prometheus' / 'rules'

METRIC_RE = re.compile(r'^[a-zA-Z_:][a-zA-Z0-9_:]*$')
RECORD_RE = re.compile(r'^\s*-\s*record:\s*([A-Za-z_:][A-Za-z0-9_:]*)\s*$', re.M)


def load_contract_metrics(path: Path) -> set[str]:
    """Load all `- name:` entries from the metric contract."""

    text = path.read_text(encoding='utf-8')
    names: set[str] = set()
    for line in text.splitlines():
        s = line.strip()
        if s.startswith('- name:'):
            name = s.split(':', 1)[1].strip().strip('"\'')
            if name:
                names.add(name)
    return names


def load_recording_rules(rules_dir: Path) -> set[str]:
    """Load recording rule names from Prometheus rule YAML files."""

    names: set[str] = set()
    for path in rules_dir.rglob('*.yml'):
        text = path.read_text(encoding='utf-8')
        for match in RECORD_RE.findall(text):
            names.add(match)
    return names


def main() -> int:
    """Validate metric names and contract/rule coverage."""

    if not CONTRACT.exists():
        print(f'ERROR: missing contract file: {CONTRACT}', file=sys.stderr)
        return 1
    if not RULES.exists():
        print(f'ERROR: missing rules directory: {RULES}', file=sys.stderr)
        return 1

    contract_metrics = load_contract_metrics(CONTRACT)
    invalid = sorted(name for name in contract_metrics if not METRIC_RE.match(name))
    if invalid:
        print('ERROR: invalid metric names in contract:', file=sys.stderr)
        for name in invalid:
            print(f'  - {name}', file=sys.stderr)
        return 1

    recording_rules = load_recording_rules(RULES)
    missing = sorted(recording_rules - contract_metrics)
    if missing:
        print('ERROR: recording rules missing from contract:', file=sys.stderr)
        for name in missing:
            print(f'  - {name}', file=sys.stderr)
        return 1

    print(f'OK: contract covers {len(recording_rules)} recording rules and {len(contract_metrics)} metrics entries.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
