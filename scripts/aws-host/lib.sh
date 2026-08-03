#!/usr/bin/env bash

set -Eeuo pipefail

log() {
  printf '[maas-host] %s\n' "$*"
}

die() {
  printf '[maas-host] error: %s\n' "$*" >&2
  exit 2
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

require_root() {
  [[ ${EUID} -eq 0 ]] || die "run this command as root"
}

require_file() {
  [[ -f $1 ]] || die "required file not found: $1"
}

require_directory() {
  [[ -d $1 ]] || die "required directory not found: $1"
}

require_ubuntu() {
  require_file /etc/os-release
  # shellcheck disable=SC1091
  source /etc/os-release
  [[ ${ID:-} == "ubuntu" ]] || die "only Ubuntu hosts are supported"
}

read_env_value() {
  local env_file=$1
  local key=$2
  local line

  line=$(grep -E "^${key}=" "$env_file" | tail -n 1 || true)
  [[ -n $line ]] || return 1
  printf '%s\n' "${line#*=}"
}

check_secret_file_mode() {
  local path=$1
  local mode

  require_file "$path"
  mode=$(stat -c '%a' "$path")
  [[ $mode == "600" || $mode == "400" ]] ||
    die "$path must have mode 0600 or 0400 (found $mode)"
}

compose_files() {
  local observability=$1
  COMPOSE_ARGUMENTS=(-f compose.yaml -f compose.production.yaml)
  if [[ $observability == "true" ]]; then
    COMPOSE_ARGUMENTS+=(-f compose.observability.yaml)
  fi
}

validate_production_inputs() {
  local source_dir=$1
  local env_file=$2
  local placeholders

  require_directory "$source_dir"
  require_file "$source_dir/compose.yaml"
  require_file "$source_dir/compose.production.yaml"
  require_file "$env_file"
  [[ -r $env_file ]] || die "environment file is not readable: $env_file"

  placeholders=$(grep -nE 'replace-me|example\.com|YOUR_' "$env_file" || true)
  [[ -z $placeholders ]] ||
    die "environment file contains unfinished placeholders (line numbers intentionally omitted)"
}

usage_error() {
  die "unknown or incomplete argument: ${1:-<missing>}; run with --help"
}
