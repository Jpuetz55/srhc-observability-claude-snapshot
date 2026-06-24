# Secrets

Encrypted-at-rest credentials for runtime services. Plaintext never lives in
git; the real `*.sops.yaml` files are committed encrypted with **sops + age**
per `../.sops.yaml`.

## What lives here

| File                                | Purpose                                                                 |
| ----------------------------------- | ----------------------------------------------------------------------- |
| `postgres.env.sops.yaml`            | Encrypted Postgres passwords for topology + vocera-media-qoe + vocera-rf-validation. |
| `postgres.env.sops.yaml.example`    | Plaintext template (committed). Shows the structure.                    |

## One-time bootstrap on a new host

1. Install sops and age:
   ```
   sudo dnf install age sops    # or apt install age sops
   ```
2. Generate an age key for this host:
   ```
   mkdir -p ~/.config/sops/age
   age-keygen -o ~/.config/sops/age/keys.txt
   chmod 600 ~/.config/sops/age/keys.txt
   ```
3. Copy the public key (prints from `age-keygen`, format `age1...`) into
   `../.sops.yaml` under the `age:` line, then commit.
4. Author the encrypted file from the template:
   ```
   cp secrets/postgres.env.sops.yaml.example secrets/postgres.env.sops.yaml
   $EDITOR secrets/postgres.env.sops.yaml      # put the real passwords
   sops --encrypt --in-place secrets/postgres.env.sops.yaml
   git add secrets/postgres.env.sops.yaml
   git commit -m "bootstrap encrypted postgres secrets"
   ```
5. Materialize the runtime env files on the host:
   ```
   sudo bash scripts/install_secrets.sh
   ```
   This writes one `KEY=value` file per service into
   `/etc/grafana-mimir-observability/secrets/` (root-owned, 0600). Grafana
   picks them up via the systemd drop-in
   `systemd-overrides/grafana-server.service.d/secrets.conf`.
6. For existing Postgres data directories, apply the same passwords to the
   already-created database roles:
   ```
   sudo bash scripts/sync_postgres_passwords_from_secrets.sh
   sudo systemctl restart grafana-server
   ```
   The Postgres container image only uses `POSTGRES_PASSWORD` during first
   initialization. Changing env files later does not update stored role
   passwords without this `ALTER ROLE` step.

## Migrating the existing dev defaults

The repo previously shipped `topology_dev_change_me`, `vocera_media_qoe_dev_change_me`,
and `vocera_rf_validation_dev_change_me` in plaintext. The running Postgres
containers have those values in their stored role passwords. To migrate
without disrupting the running services, use the existing values once when you
encrypt the file the first time:

```yaml
topology:
  password: topology_dev_change_me
vocera_media_qoe:
  password: vocera_media_qoe_dev_change_me
vocera_rf_validation:
  password: vocera_rf_validation_dev_change_me
```

Then rotate to real random passwords later by:
1. Updating each line in `postgres.env.sops.yaml`.
2. Re-running `sudo bash scripts/install_secrets.sh`.
3. Running `sudo bash scripts/sync_postgres_passwords_from_secrets.sh --restart-grafana`.

## Editing an encrypted file

```
sops secrets/postgres.env.sops.yaml
```

Opens `$EDITOR` with the decrypted view; saving re-encrypts in place.

## What never goes in git

- `secrets/*.plain.*` and `secrets/*.decrypted.*` — covered by `.gitignore`.
- Anything outside `secrets/` that has a real password string — caught by
  `scripts/githooks/pre-commit` (install with `bash scripts/install_githooks.sh`).
