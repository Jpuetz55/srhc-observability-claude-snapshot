# Private Git Workflow

This repo should be managed from a private Git service before it is treated as
the long-term source of truth for observability runtime changes. The preferred
target for this environment is Forgejo or Gitea on a small private Alma Linux
VM, backed by PostgreSQL, with SSH clone/push and a LAN/VPN-only HTTPS web UI.

Use GitLab only if the environment later needs GitLab-specific features. For
the current repo size and workflow, Forgejo or Gitea is a better operational fit.

## Target Model

Recommended server:

```text
git-01
  Alma Linux 9
  Forgejo or Gitea
  PostgreSQL
  nginx or caddy reverse proxy
  repo storage under the app data directory
  nightly backups to a separate target
```

Recommended organization and repositories:

```text
observability/grafana-mimir-observability
observability/Network-Topology
```

Keep `Network-Topology` as a separate repository. This repo expects it as a
sibling checkout by default:

```text
../Network-Topology
```

The default remote for this repo should eventually be:

```text
origin  git@git-01:observability/grafana-mimir-observability.git
```

The default remote for the topology repo should eventually be:

```text
origin  git@git-01:observability/Network-Topology.git
```

## Before First Push

Run the normal repo validation before migrating:

```bash
cd /home/appsadmin/grafana-mimir-observability

git status
git remote -v
git branch

make test
ENFORCE_DASHBOARD_METRIC_CONTRACT=1 make validate
```

If Kubernetes overlays are in scope for the change, also run:

```bash
make kustomize-validate
```

Check for suspicious tracked paths before first push:

```bash
git ls-files | grep -Ei 'secret|password|token|key|pem|pfx|p12|crt|env'
```

Encrypted SOPS files, examples, and repo tooling are acceptable. Plaintext
secrets are not.

## Migration Commands

Create the organization and empty private repositories in Forgejo or Gitea
first, then run:

```bash
cd /home/appsadmin/grafana-mimir-observability

git remote rename origin old-origin 2>/dev/null || true
git remote add origin git@git-01:observability/grafana-mimir-observability.git

git push -u origin main
git push --tags
```

For the topology repo:

```bash
cd /home/appsadmin/Network-Topology

git remote rename origin old-origin 2>/dev/null || true
git remote add origin git@git-01:observability/Network-Topology.git

git push -u origin main
git push --tags
```

If either repo still uses `master`, rename it deliberately:

```bash
git branch -M main
git push -u origin main
```

After migration, test a fresh clone:

```bash
cd /tmp
git clone git@git-01:observability/grafana-mimir-observability.git
cd grafana-mimir-observability

make test
ENFORCE_DASHBOARD_METRIC_CONTRACT=1 make validate
```

## New Clone Hook Setup

Every working clone should install the repo-managed local Git hook before making
commits:

```bash
cd /home/appsadmin/grafana-mimir-observability

bash scripts/install_githooks.sh
readlink -f .git/hooks/pre-commit
bash scripts/githooks/pre-commit
```

Expected hook target:

```text
/home/appsadmin/grafana-mimir-observability/scripts/githooks/pre-commit
```

The hook is intentionally a fast local safety check. Verified behavior:

```text
no staged files                         allowed
fake plaintext password                 blocked
plaintext file under secrets/           blocked
encrypted *.sops.yaml with sops: block  allowed
```

This local hook is not a substitute for server-side protection. It can be
bypassed with `git commit --no-verify`, and other clones will not run it until
`scripts/install_githooks.sh` has been executed there. Add Forgejo server-side
secret scanning or required CI before giving additional users write access.

## Branch Policy

Protect `main` in the Git service:

```text
main:
  no force push
  no delete
  require pull request for normal changes
  allow direct admin push only for emergency or one-operator bootstrap work
```

Normal workflow:

```bash
cd /home/appsadmin/grafana-mimir-observability

git checkout main
git pull --ff-only
git checkout -b feature/example-change

# edit, validate, commit
make test
ENFORCE_DASHBOARD_METRIC_CONTRACT=1 make validate

git add .
git commit -m "Describe the change"
git push -u origin feature/example-change
```

Merge through the web UI or with a local fast-forward/rebase workflow after
review. Avoid force-pushing shared branches.

## Dashboard Release Flow

The canonical release flow is:

```text
DEV Grafana -> repo export -> Git commit -> PROD promotion
```

The release script implements that order:

```bash
make release MSG="promote dashboard updates"
```

Internally this runs:

```text
scripts/export_dev_db_to_repo.sh
git commit -m "$MSG" if export staged changes
scripts/promote_repo_to_prod.sh
```

For explicit operator control, use the same steps manually:

```bash
./scripts/export_dev_db_to_repo.sh
git status
git add .
git commit -m "export DEV dashboard updates"
./scripts/promote_repo_to_prod.sh
git push
```

Keep Git push manual at first. Promotion should remain deliberate, and PROD
should correspond to a committed repo state.

## Runtime Promotion Rules

`scripts/promote_repo_to_prod.sh` converges runtime config and dashboards from
the repo. Treat it as a deployment step, not a source edit step.

Before promotion:

```bash
git status
make test
ENFORCE_DASHBOARD_METRIC_CONTRACT=1 make validate
```

Use dry-run when checking a risky change:

```bash
make plan
```

Then promote:

```bash
make deploy
```

or:

```bash
./scripts/promote_repo_to_prod.sh
```

## What Must Never Be Committed

Do not commit:

```text
data/
dev-data/
logs/
*.log
*.db
raw captures or PCAP files
DNAC credentials
Grafana admin passwords
PostgreSQL passwords
private keys
TLS private material
plaintext .env files
decrypted SOPS files
local Grafana runtime ini files
local Ansible inventory or host var overrides
web/study-ui/node_modules/
web/study-ui/dist/
tools/study_web/static generated content
```

The `.gitignore` already blocks the common cases. Treat this list as the human
policy when reviewing changes.

Encrypted SOPS files and examples may be committed when they are intentionally
part of repo-managed secret delivery.

## Deploy Keys

Use read-only deploy keys for servers that only need to pull repo state.

Recommended access model:

```text
admin:
  Git service administrator

appsadmin:
  maintainer or owner for observability repositories

deployment key:
  read-only clone access

future collaborators:
  branch and pull request workflow
```

Do not reuse a personal write-capable SSH key for unattended deployment pulls.

## Backups

Back up all source-control state, not just bare Git repositories:

```text
Forgejo or Gitea config
Forgejo or Gitea app data
Git repository storage
PostgreSQL database
SSH host keys
TLS certificates and private keys
backup scripts
```

Minimum cadence:

```text
nightly:
  database dump
  app dump or app data snapshot
  repository storage archive
  config archive

weekly:
  full VM backup or Commvault backup

monthly:
  restore test to a throwaway VM
```

A backup is only proven after restore has been tested.

Restore acceptance:

```text
1. Fresh VM boots.
2. Forgejo or Gitea starts.
3. Users can log in.
4. Repository history is present.
5. SSH clone works.
6. A test branch can be pushed.
7. grafana-mimir-observability runs make test.
8. ENFORCE_DASHBOARD_METRIC_CONTRACT=1 make validate passes.
```

## Security Baseline

Minimum controls:

```text
LAN/VPN-only HTTPS access
SSH access restricted to admin networks
public registration disabled
default repository visibility private
SSH keys for Git access
read-only deploy keys where possible
SELinux enforcing
firewalld enabled
TLS for the web UI
admin MFA if available
regular OS and app patching
nightly backups
monthly restore tests
```

Do not expose the Git service publicly until patching, backup, restore, and
access controls have been exercised.

## CI Later

Do not start with a runner on day one. First prove:

```text
private Git works
main is protected
backup works
restore works
fresh clone validation works
```

Then add a separate runner host. Initial checks should mirror local validation:

```bash
make test
make kustomize-validate
ENFORCE_DASHBOARD_METRIC_CONTRACT=1 make validate
```

If Forgejo or Gitea Actions can reuse the current `.github/workflows`, keep them
in place initially. Move or duplicate workflows only when the runner behavior
requires it.

## Operational Checklist

Phase A, minimal working server:

```text
Forgejo or Gitea installed
PostgreSQL configured
HTTPS reverse proxy working
public registration disabled
observability org created
both repos pushed
fresh clone succeeds
make test passes from fresh clone
```

Phase B, operational safety:

```text
main protected
read-only deploy key created
nightly backup configured
off-host backup target working
restore test completed
branch/release workflow documented
```

Phase C, repo workflow integration:

```text
origin points at private Git
release workflow still exports DEV dashboards
promotion still requires committed repo state
Network-Topology remains a sibling checkout
operator can pull, validate, release, and push intentionally
```

Phase D, optional CI:

```text
runner host installed
repo validation jobs pass
main requires successful checks
runner secrets are scoped and minimal
```
