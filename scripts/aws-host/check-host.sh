#!/usr/bin/env bash

set -Eeuo pipefail
SCRIPT_DIRECTORY=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
source "$SCRIPT_DIRECTORY/lib.sh"

source_dir=""
env_file=""
minimum_memory_mib=1800
minimum_disk_gib=12

usage() {
  cat <<'EOF'
Usage: check-host.sh [options]

Non-destructively checks whether an Ubuntu host can run the production stack.

Options:
  --source-dir PATH       Application checkout to inspect
  --env-file PATH         Protected production environment file to inspect
  --minimum-memory-mib N  Required physical memory (default: 1800)
  --minimum-disk-gib N    Required free disk space (default: 12)
  --help                  Show this help
EOF
}

while (($# > 0)); do
  case "$1" in
    --source-dir)
      source_dir=${2:-}
      shift 2
      ;;
    --env-file)
      env_file=${2:-}
      shift 2
      ;;
    --minimum-memory-mib)
      minimum_memory_mib=${2:-}
      shift 2
      ;;
    --minimum-disk-gib)
      minimum_disk_gib=${2:-}
      shift 2
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      usage_error "$1"
      ;;
  esac
done

require_ubuntu
require_command awk
require_command df
require_command getconf
require_command systemctl

architecture=$(dpkg --print-architecture)
case "$architecture" in
  amd64 | arm64) ;;
  *) die "unsupported architecture: $architecture" ;;
esac

memory_mib=$(awk '/^MemTotal:/ { print int($2 / 1024) }' /proc/meminfo)
((memory_mib >= minimum_memory_mib)) ||
  die "physical memory is ${memory_mib} MiB; require at least ${minimum_memory_mib} MiB"

disk_kib=$(df -Pk "${source_dir:-/}" | awk 'NR == 2 { print $4 }')
minimum_disk_kib=$((minimum_disk_gib * 1024 * 1024))
((disk_kib >= minimum_disk_kib)) ||
  die "free disk is below the required ${minimum_disk_gib} GiB"

[[ $(getconf LONG_BIT) == "64" ]] || die "a 64-bit operating system is required"
[[ $(systemctl is-system-running 2>/dev/null || true) != "offline" ]] ||
  die "systemd is not running"

if [[ -n $source_dir ]]; then
  require_file "$source_dir/compose.yaml"
  require_file "$source_dir/compose.production.yaml"
  require_file "$source_dir/.env.production.example"
fi

if [[ -n $env_file ]]; then
  require_file "$env_file"
  check_secret_file_mode "$env_file"
  placeholders=$(grep -nE 'replace-me|example\.com|YOUR_' "$env_file" || true)
  [[ -z $placeholders ]] ||
    die "environment file contains unfinished placeholders"
fi

if command -v docker >/dev/null 2>&1; then
  docker compose version >/dev/null
  log "Docker Engine and Compose are available"
else
  log "Docker is not installed; run install-docker.sh --apply"
fi

log "host compatibility check passed (${architecture}, ${memory_mib} MiB RAM)"
