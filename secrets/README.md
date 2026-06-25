# Secrets and runtime credential material

This directory contains **templates and tooling**, not live service secrets. A
sanitized checkout must not be assumed to contain an encrypted secret payload,
an age private key, or materialized credential file.

## Runtime location

Services consume root-owned materialized environment files from:

```text
/etc/grafana-mimir-observability/secrets/
```

Examples include:

```text
dnac-readonly.env
topology-postgres.env
vocera-media-qoe-postgres.env
vocera-rf-validation-postgres.env
```

These files are operational secrets. Never commit them, paste them into a
terminal transcript, or add them to a documentation example.

## Repository material

| File | Meaning |
| --- | --- |
| `postgres.env.sops.yaml.example` | plaintext shape/example only; contains no live values |
| `scripts/install_secrets.py` | optional materialization helper for an approved encrypted source |
| `scripts/install_sops_age.sh` | helper for installing SOPS/age tooling where approved |
| `scripts/githooks/pre-commit` | fast local guard against accidental plaintext secret commits |

An encrypted `secrets/postgres.env.sops.yaml` may be used only when the project
owner has deliberately chosen to keep that encrypted artifact in the canonical
repository and has configured the matching SOPS policy/recipient keys.
It is not required to exist in every clone and is not a substitute for host
secret management.

## Materialize an approved encrypted source

Where an approved encrypted source and age identity exist, run the helper from
the current checkout using the documented administrative procedure. It writes
root-owned per-service files under `/etc/grafana-mimir-observability/secrets/`.
Inspect permissions after any change:

```bash
sudo find /etc/grafana-mimir-observability/secrets -maxdepth 1 -type f -printf '%M %u:%g %p\n'
```

Do not run a materialization command against a production host until the input
source, target service files, and rotation plan have been reviewed.

## Rules

- Keep passwords/tokens/private keys out of Git, Make variables, shell history,
  screenshots, and generated session packages.
- Use the dedicated read-only Catalyst Center account for completed ICAP/topology
  discovery; it is not a WLC automation credential.
- WLC EPC export uses an interactive SCP password prompt. Study Web stores only
  destination host/user/port/path metadata.
- Rotate a credential through the approved secret process, then restart only the
  services that consume it and verify their health.
