#!/usr/bin/env bash

set -Eeuo pipefail
SCRIPT_DIRECTORY=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
source "$SCRIPT_DIRECTORY/lib.sh"

source_dir=""
env_file=""
domain=""
observability="false"
ssh_port=22
allowed_ports=()

usage() {
  cat <<'EOF'
Usage: verify-deployment.sh --source-dir PATH --env-file PATH --domain NAME [options]

Checks service state, public HTTPS health, and non-loopback TCP listeners.

Options:
  --observability     Include compose.observability.yaml
  --ssh-port PORT     Expected restricted SSH port (default: 22)
  --allow-port PORT   Allow another intentional non-loopback TCP listener
  --help              Show this help
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
    --domain)
      domain=${2:-}
      shift 2
      ;;
    --observability)
      observability="true"
      shift
      ;;
    --ssh-port)
      ssh_port=${2:-}
      shift 2
      ;;
    --allow-port)
      allowed_ports+=("${2:-}")
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

[[ -n $source_dir && -n $env_file && -n $domain ]] ||
  die "--source-dir, --env-file, and --domain are required"
require_command curl
require_command docker
require_command ss
validate_production_inputs "$source_dir" "$env_file"
compose_files "$observability"
allowed_ports+=("$ssh_port" 80 443)

cd "$source_dir"
docker compose --env-file "$env_file" "${COMPOSE_ARGUMENTS[@]}" config --quiet
docker compose --env-file "$env_file" "${COMPOSE_ARGUMENTS[@]}" ps
curl --fail --show-error --silent --max-time 15 "https://${domain}/" >/dev/null

unexpected=()
while read -r local_address; do
  [[ -n $local_address ]] || continue
  host=${local_address%:*}
  port=${local_address##*:}
  host=${host#[}
  host=${host%]}
  case "$host" in 127.* | ::1) continue ;; esac

  permitted="false"
  for allowed_port in "${allowed_ports[@]}"; do
    if [[ $port == "$allowed_port" ]]; then
      permitted="true"
      break
    fi
  done
  [[ $permitted == "true" ]] || unexpected+=("$local_address")
done < <(ss -H -lnt | awk '{ print $4 }')

((${#unexpected[@]} == 0)) ||
  die "unexpected non-loopback TCP listeners: ${unexpected[*]}"
log "deployment health and public-port verification passed"
