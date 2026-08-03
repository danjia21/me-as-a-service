#!/bin/sh
set -eu

if [ "${MAAS_CONFIRM_RESTORE:-}" != "restore" ]; then
    echo "Set MAAS_CONFIRM_RESTORE=restore to confirm the target database may be overwritten." >&2
    exit 2
fi

if [ -z "${RESTORE_DATABASE_URL:-}" ]; then
    echo "RESTORE_DATABASE_URL is required." >&2
    exit 2
fi

restic dump latest maas.dump \
    | pg_restore \
        --clean \
        --if-exists \
        --no-owner \
        --no-privileges \
        --dbname "$RESTORE_DATABASE_URL"
