#!/usr/bin/env bash

set -Eeuo pipefail
SCRIPT_DIRECTORY=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
source "$SCRIPT_DIRECTORY/lib.sh"

mode=""
source_dir=""
env_file=""
restore_database_url=""
restore_confirmation="false"

usage() {
  cat <<'EOF'
Usage: verify-backup-restore.sh --mode MODE --source-dir PATH --env-file PATH

Modes:
  check    Validate backup configuration and protected secret files
  backup   Run an on-demand encrypted backup
  restore  Restore the latest snapshot to an explicitly separate clean database

Restore-only options:
  --restore-database-url URL
  --confirm-clean-target

Restore never targets the configured production DATABASE_URL. After restore,
the script verifies that the application conversation and trace tables exist;
the operator must still start the API against the restored database and verify
a known record without logging its content.
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
    --restore-database-url)
      restore_database_url=${2:-}
      shift 2
      ;;
    --confirm-clean-target)
      restore_confirmation="true"
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

case "$mode" in check | backup | restore) ;; *) die "invalid --mode" ;; esac
[[ -n $source_dir && -n $env_file ]] ||
  die "--source-dir and --env-file are required"
require_command docker
validate_production_inputs "$source_dir" "$env_file"
compose_files "false"

restic_password_file=$(read_env_value "$env_file" RESTIC_PASSWORD_FILE_HOST) ||
  die "RESTIC_PASSWORD_FILE_HOST is required"
check_secret_file_mode "$restic_password_file"

cd "$source_dir"
docker compose --env-file "$env_file" "${COMPOSE_ARGUMENTS[@]}" config --quiet

if [[ $mode == "check" ]]; then
  log "backup configuration and protected password file are valid"
  exit 0
fi

if [[ $mode == "backup" ]]; then
  docker compose --env-file "$env_file" "${COMPOSE_ARGUMENTS[@]}" \
    run --rm backup maas-backup
  log "on-demand backup completed"
  exit 0
fi

[[ -n $restore_database_url ]] ||
  die "--restore-database-url is required for restore"
[[ $restore_confirmation == "true" ]] ||
  die "restore requires --confirm-clean-target"
production_database_url=$(read_env_value "$env_file" DATABASE_URL) ||
  die "DATABASE_URL is required"
[[ $restore_database_url != "$production_database_url" ]] ||
  die "refusing to restore over the configured production database"

docker compose --env-file "$env_file" "${COMPOSE_ARGUMENTS[@]}" run --rm \
  -e MAAS_CONFIRM_RESTORE=restore \
  -e RESTORE_DATABASE_URL="$restore_database_url" \
  backup maas-restore

schema_result=$(docker compose --env-file "$env_file" "${COMPOSE_ARGUMENTS[@]}" run --rm \
  -e PGPASSWORD= \
  backup psql "$restore_database_url" --no-password --tuples-only --no-align \
  --field-separator=, --command \
  "SELECT to_regclass('public.conversations'), to_regclass('public.daily_model_usage');")
grep -q '^conversations,daily_model_usage$' <<<"$schema_result" ||
  die "restore completed, but required application tables were not found"
log "restore completed and required application tables were found"
