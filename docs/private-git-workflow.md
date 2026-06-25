# Repository workflow

## Current source boundary

Treat this repository's reviewed `main` branch and tags as the source of truth
for the collectors-VM platform. Keep every implementation, documentation, and
runtime-promotion change in this repository's normal branch-and-review flow.

A change to repository hosting, remotes, or source-control infrastructure is a
separate infrastructure task. Do not bundle it with a dashboard, parser,
evidence, or service change.

## Normal workflow

```bash
# Start from the current canonical line.
git switch main
git pull --ff-only origin main

# Use a purpose-specific branch.
git switch -c docs/example-change

# Validate before commit.
make test
make validate

git add <files>
git commit -m "docs: describe the change"
git push -u origin docs/example-change
```

Open a pull request or use the repository's established review process, inspect
the changed files and validation output, then merge into `main`. Keep branch
names scoped to the work (`docs/`, `fix/`, `feature/`, or `claude/` as
appropriate) and do not force-push shared branches.

Use a direct merge to `main` only for deliberate one-operator recovery work.
Even then, run `make test` and `make validate` first and leave a clear merge or
commit message.

## Repository safety checks

Before committing or opening a review:

```bash
git status --short
make test
make validate
```

Install the repository hook in each working clone:

```bash
bash scripts/install_githooks.sh
readlink -f .git/hooks/pre-commit
bash scripts/githooks/pre-commit
```

The hook blocks likely plaintext secrets but is not a substitute for review or
server-side controls. Never bypass it merely to commit generated data or a
credential; remove the material and use the intended secret path.

## What must never be committed

Do not commit:

```text
raw PCAPs, EPC exports, terminal transcripts, badge/Ekahau exports
runtime databases or PostgreSQL volumes
node_exporter .prom output and parser output archives
laptop-uploaded iperf JSON
Catalyst Center, WLC, SCP, Grafana, or PostgreSQL credentials
private keys, certificate private material, plaintext .env files
materialized files under /etc/grafana-mimir-observability/secrets
web/study-ui/node_modules or built static output
```

The `secrets/` directory contains templates and materialization tooling. This
sanitized repository snapshot intentionally does not contain live credentials
or a deployable encrypted secret file. Provision runtime secrets by the
approved secure process, not by copying them into Git.

## Dashboard and runtime promotion

The source-control sequence is distinct from runtime promotion:

```text
editable DEV Grafana -> repository branch -> validate -> reviewed merge -> deploy local PROD runtime
```

`make release`, `make deploy`, and `make dashboard-sync-prod-to-dev` act on the
collector runtime. Read [`cicd.md`](cicd.md) before using them. A successful
source merge does not itself change WLC configuration, start PCAP capture, or
deploy a WLC certificate.
