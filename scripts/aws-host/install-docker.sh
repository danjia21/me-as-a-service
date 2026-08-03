#!/usr/bin/env bash

set -Eeuo pipefail
SCRIPT_DIRECTORY=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
source "$SCRIPT_DIRECTORY/lib.sh"

mode=""
deploy_user=""

usage() {
  cat <<'EOF'
Usage: install-docker.sh (--check | --apply) [--deploy-user USER]

Checks or idempotently installs Docker Engine and the Compose plugin on Ubuntu.
The apply path must run as root. Supplying --deploy-user adds that existing user
to the root-equivalent docker group.
EOF
}

while (($# > 0)); do
  case "$1" in
    --check | --apply)
      [[ -z $mode ]] || die "choose exactly one of --check or --apply"
      mode=${1#--}
      shift
      ;;
    --deploy-user)
      deploy_user=${2:-}
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

[[ -n $mode ]] || die "choose --check or --apply"
require_ubuntu

if [[ $mode == "check" ]]; then
  require_command docker
  docker version >/dev/null
  docker compose version >/dev/null
  systemctl is-enabled docker >/dev/null
  systemctl is-active docker >/dev/null
  log "Docker Engine and Compose are installed and active"
  exit 0
fi

require_root
require_command apt-get
require_command curl
require_command dpkg
export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y ca-certificates curl
apt-get remove -y \
  docker.io docker-compose docker-compose-v2 docker-doc podman-docker \
  containerd runc || true

install -m 0755 -d /etc/apt/keyrings
temporary_key=$(mktemp)
temporary_source=$(mktemp)
trap 'rm -f "$temporary_key" "$temporary_source"' EXIT

curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o "$temporary_key"
install -m 0644 "$temporary_key" /etc/apt/keyrings/docker.asc

# shellcheck disable=SC1091
source /etc/os-release
codename=${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}
[[ -n $codename ]] || die "could not determine Ubuntu codename"
architecture=$(dpkg --print-architecture)

{
  printf 'Types: deb\n'
  printf 'URIs: https://download.docker.com/linux/ubuntu\n'
  printf 'Suites: %s\n' "$codename"
  printf 'Components: stable\n'
  printf 'Architectures: %s\n' "$architecture"
  printf 'Signed-By: /etc/apt/keyrings/docker.asc\n'
} >"$temporary_source"
install -m 0644 "$temporary_source" /etc/apt/sources.list.d/docker.sources

apt-get update
apt-get install -y \
  docker-ce docker-ce-cli containerd.io docker-buildx-plugin \
  docker-compose-plugin
systemctl enable --now docker

if [[ -n $deploy_user ]]; then
  id "$deploy_user" >/dev/null 2>&1 || die "deployment user does not exist: $deploy_user"
  if ! id -nG "$deploy_user" | tr ' ' '\n' | grep -qx docker; then
    usermod -aG docker "$deploy_user"
    log "added $deploy_user to the root-equivalent docker group; reconnect before use"
  fi
fi

docker version >/dev/null
docker compose version >/dev/null
log "Docker Engine and Compose are installed"
