#!/usr/bin/env bash
# Install age + sops binaries from GitHub releases into /usr/local/bin.
# RHEL / Rocky / CentOS do not ship these in default repos. Idempotent:
# re-running with the binaries already present is a no-op (unless --force).
#
# Run as root:
#   sudo bash scripts/install_sops_age.sh
#   sudo bash scripts/install_sops_age.sh --force      # reinstall even if present
set -euo pipefail

FORCE=0
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    -h|--help)
      sed -n '2,9p' "$0"; exit 0 ;;
    *) echo "Unknown arg: $arg" >&2; exit 2 ;;
  esac
done

if [[ "$EUID" -ne 0 ]]; then
  echo "Run as root: sudo bash scripts/install_sops_age.sh" >&2
  exit 1
fi

ARCH="$(uname -m)"
case "$ARCH" in
  x86_64|amd64) ARCH_AGE="linux-amd64"; ARCH_SOPS="linux.amd64" ;;
  aarch64|arm64) ARCH_AGE="linux-arm64"; ARCH_SOPS="linux.arm64" ;;
  *) echo "unsupported arch: $ARCH"; exit 1 ;;
esac

need() { command -v "$1" >/dev/null 2>&1 || { echo "missing required command: $1" >&2; exit 1; }; }
need curl
need tar
need install

# Read the latest release tag for a GitHub repo from the public API.
# No auth required for read-only metadata.
latest_tag() {
  curl -sSL "https://api.github.com/repos/$1/releases/latest" \
    | grep -oE '"tag_name":\s*"[^"]+"' \
    | head -1 \
    | sed -E 's/.*"([^"]+)"$/\1/'
}

install_age() {
  if [[ "$FORCE" -eq 0 ]] && [[ -x /usr/local/bin/age ]] && [[ -x /usr/local/bin/age-keygen ]]; then
    echo "age already installed: $(/usr/local/bin/age --version 2>&1)"
    return 0
  fi
  local tag
  tag="$(latest_tag FiloSottile/age)"
  [[ -n "$tag" ]] || { echo "ERROR: could not resolve latest age tag from GitHub API" >&2; return 1; }
  echo "Installing age $tag"
  local url="https://github.com/FiloSottile/age/releases/download/$tag/age-$tag-$ARCH_AGE.tar.gz"
  local tmp; tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  if ! curl -fsSL "$url" -o "$tmp/age.tgz"; then
    echo "ERROR: download failed (HTTP error): $url" >&2
    return 1
  fi
  if ! tar -xzf "$tmp/age.tgz" -C "$tmp"; then
    echo "ERROR: tar extract failed; saved bytes: $(stat -c%s "$tmp/age.tgz" 2>/dev/null || echo '?')" >&2
    return 1
  fi
  # Don't assume the tarball nests under an age/ dir - locate the binaries.
  local age_bin age_keygen_bin
  age_bin="$(find "$tmp" -type f -name age -perm -u+x | head -1)"
  age_keygen_bin="$(find "$tmp" -type f -name age-keygen -perm -u+x | head -1)"
  if [[ -z "$age_bin" || -z "$age_keygen_bin" ]]; then
    echo "ERROR: age binaries not found inside tarball. Contents:" >&2
    find "$tmp" -maxdepth 3 -type f >&2
    return 1
  fi
  install -m 0755 "$age_bin"        /usr/local/bin/age
  install -m 0755 "$age_keygen_bin" /usr/local/bin/age-keygen
  [[ -x /usr/local/bin/age ]] || { echo "ERROR: /usr/local/bin/age missing after install" >&2; return 1; }
  /usr/local/bin/age --version 2>&1 || true
  /usr/local/bin/age-keygen --version 2>&1 || true
}

install_sops() {
  if [[ "$FORCE" -eq 0 ]] && [[ -x /usr/local/bin/sops ]]; then
    echo "sops already installed: $(/usr/local/bin/sops --version 2>&1 | head -1)"
    return 0
  fi
  local tag
  tag="$(latest_tag getsops/sops)"
  [[ -n "$tag" ]] || { echo "ERROR: could not resolve latest sops tag from GitHub API" >&2; return 1; }
  echo "Installing sops $tag"
  local url="https://github.com/getsops/sops/releases/download/$tag/sops-$tag.$ARCH_SOPS"
  if ! curl -fsSL "$url" -o /usr/local/bin/sops; then
    echo "ERROR: sops download failed (HTTP error): $url" >&2
    rm -f /usr/local/bin/sops
    return 1
  fi
  chmod 0755 /usr/local/bin/sops
  [[ -x /usr/local/bin/sops ]] || { echo "ERROR: /usr/local/bin/sops missing after install" >&2; return 1; }
  /usr/local/bin/sops --version 2>&1 | head -1
}

install_age
install_sops

echo
echo "Both binaries installed under /usr/local/bin/. Next steps:"
echo "  mkdir -p ~/.config/sops/age"
echo "  age-keygen -o ~/.config/sops/age/keys.txt"
echo "  chmod 600 ~/.config/sops/age/keys.txt"
echo "  grep '^# public key:' ~/.config/sops/age/keys.txt    # copy this into .sops.yaml"
