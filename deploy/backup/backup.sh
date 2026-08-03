#!/bin/sh
set -eu

metrics_dir=/var/lib/node_exporter/textfile_collector
metrics_tmp="${metrics_dir}/maas_backup.prom.tmp"
metrics_file="${metrics_dir}/maas_backup.prom"
backup_name=maas.dump

write_result() {
    success="$1"
    completed_at="$2"
    {
        echo "# HELP maas_backup_last_run_success Whether the latest backup run succeeded."
        echo "# TYPE maas_backup_last_run_success gauge"
        echo "maas_backup_last_run_success ${success}"
        if [ "$success" = "1" ]; then
            echo "# HELP maas_backup_last_success_timestamp_seconds Unix timestamp of the last successful backup."
            echo "# TYPE maas_backup_last_success_timestamp_seconds gauge"
            echo "maas_backup_last_success_timestamp_seconds ${completed_at}"
        fi
    } > "$metrics_tmp"
    mv "$metrics_tmp" "$metrics_file"
}

trap 'write_result 0 "$(date +%s)"' EXIT

if ! restic snapshots --latest 1 >/dev/null 2>&1; then
    restic init
fi

pg_dump --format=custom --no-owner --no-privileges \
    | restic backup --stdin --stdin-filename "$backup_name" --tag maas-postgres

restic forget \
    --tag maas-postgres \
    --keep-daily "${MAAS_BACKUP_RETENTION_DAILY:-7}" \
    --keep-weekly "${MAAS_BACKUP_RETENTION_WEEKLY:-4}" \
    --prune

completed_at="$(date +%s)"
write_result 1 "$completed_at"
trap - EXIT
