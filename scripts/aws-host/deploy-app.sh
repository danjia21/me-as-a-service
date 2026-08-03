#!/usr/bin/env bash

set -Eeuo pipefail
SCRIPT_DIRECTORY=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
source "$SCRIPT_DIRECTORY/lib.sh"

mode=""
source_dir=""
env_file=""
observability="false"
run_checks="false"

usage() {
  cat <<'EOF'
Usage: deploy-app.sh --mode MODE --source-dir PATH --env-file PATH [options]

Modes:
  verify   Validate production Compose configuration without changing services
  deploy   Build current checkout and reconcile the production services
  update   Fast-forward the current branch, then build and reconcile services

Options:
  --observability   Include compose.observability.yaml
  --run-checks      Run pnpm check before deploy/update
  --help            Show this help

The update mode requires a clean checkout on a branch with an upstream and uses
git pull --ff-only. It never merges, rebases, commits, or pushes.
EOF
}

while (($# > 0)); do
  case "$1" in
    --mode)
      mode=${2:-}
      shift 2
      ;;
    --source-dir)
      source_dir=${2:-}
      shift 2
      ;;
    --env-file)
      env_file=${2:-}
      shift 2
      ;;
    --observability)
      observability="true"
      shift
      ;;
    --run-checks)
      run_checks="true"
      shift
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

case "$mode" in verify | deploy | update) ;; *) die "invalid --mode" ;; esac
[[ -n $source_dir && -n $env_file ]] ||
  die "--source-dir and --env-file are required"
require_command docker
validate_production_inputs "$source_dir" "$env_file"
compose_files "$observability"

cd "$source_dir"

if [[ $mode == "update" ]]; then
  require_command git
  [[ -z $(git status --porcelain) ]] || die "update requires a clean checkout"
  [[ -n $(git symbolic-ref --short -q HEAD) ]] || die "update requires a branch checkout"
  git rev-parse --abbrev-ref '@{upstream}' >/dev/null 2>&1 ||
    die "current branch has no upstream"
  git pull --ff-only
fi

docker compose --env-file "$env_file" "${COMPOSE_ARGUMENTS[@]}" config --quiet

if [[ $mode == "verify" ]]; then
  log "production Compose configuration is valid"
  exit 0
fi

if [[ $run_checks == "true" ]]; then
  require_command pnpm
  pnpm check
fi

docker compose --env-file "$env_file" "${COMPOSE_ARGUMENTS[@]}" build --pull
docker compose --env-file "$env_file" "${COMPOSE_ARGUMENTS[@]}" up -d --remove-orphans
docker compose --env-file "$env_file" "${COMPOSE_ARGUMENTS[@]}" ps
log "$mode completed"
