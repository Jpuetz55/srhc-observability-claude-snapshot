#!/usr/bin/env bash
# Shared token file discovery/helpers for Grafana scripts.
# Supports both /etc/observability and /etc/onservability.

# Resolve token base dir once (env override wins).
if [[ -z "${OBS_TOKEN_BASE_DIR:-}" ]]; then
  if [[ -d "/etc/onservability" ]]; then
    OBS_TOKEN_BASE_DIR="/etc/onservability"
  elif [[ -d "/etc/observability" ]]; then
    OBS_TOKEN_BASE_DIR="/etc/observability"
  else
    # Keep deterministic default even if path doesn't exist yet.
    OBS_TOKEN_BASE_DIR="/etc/observability"
  fi
fi

OBS_DEV_TOKEN_FILE="${OBS_DEV_TOKEN_FILE:-$OBS_TOKEN_BASE_DIR/grafana_token_dev}"
OBS_PROD_TOKEN_FILE="${OBS_PROD_TOKEN_FILE:-$OBS_TOKEN_BASE_DIR/grafana_token_prod}"
OBS_LEGACY_TOKEN_FILE="${OBS_LEGACY_TOKEN_FILE:-$OBS_TOKEN_BASE_DIR/grafana_token}"

# Read and normalize a Grafana token file, using sudo when needed.
obs_read_token_file() {
  # Read root- or user-readable token files and normalize common file formats
  # into the raw bearer token string expected by curl headers.
  local path="$1"
  local raw line

  # Accept plain tokens, KEY=value files, optional export, Bearer prefixes,
  # comments, whitespace, CRLF, and one layer of quotes.
  normalize_token() {
    local in="$1"
    local out="$in"

    # Pick first non-empty, non-comment line.
    out="$(printf '%s\n' "$out" | awk 'NF && $1 !~ /^#/ { print; exit }')"
    out="$(printf '%s' "$out" | tr -d '\r\n' | sed -E 's/^[[:space:]]+|[[:space:]]+$//g')"

    # Support formats like:
    # - export GRAFANA_DEV_TOKEN=...
    # - GRAFANA_DEV_TOKEN=...
    if [[ "$out" =~ ^export[[:space:]]+[A-Za-z_][A-Za-z0-9_]*= ]]; then
      out="${out#export }"
      out="${out#*=}"
    elif [[ "$out" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; then
      out="${out#*=}"
    fi

    # Strip optional Bearer prefix.
    out="${out#Bearer }"
    out="${out#bearer }"

    # Strip one layer of surrounding quotes.
    out="${out%\"}"
    out="${out#\"}"
    out="${out%\'}"
    out="${out#\'}"

    printf '%s' "$out"
  }

  if [[ -r "$path" ]]; then
    raw="$(cat "$path")"
    line="$(normalize_token "$raw")"
    [[ -n "$line" ]] || return 1
    printf '%s' "$line"
    return 0
  fi

  if command -v sudo >/dev/null 2>&1; then
    sudo test -f "$path" || return 1
    raw="$(sudo cat "$path")"
    line="$(normalize_token "$raw")"
    [[ -n "$line" ]] || return 1
    printf '%s' "$line"
    return 0
  fi

  return 1
}
