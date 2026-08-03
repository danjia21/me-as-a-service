FROM postgres:18.4-alpine3.22

RUN apk add --no-cache restic

COPY deploy/backup/backup.sh /usr/local/bin/maas-backup
COPY deploy/backup/restore.sh /usr/local/bin/maas-restore
COPY deploy/backup/crontab /etc/crontabs/root

RUN chmod 0555 /usr/local/bin/maas-backup /usr/local/bin/maas-restore \
    && chmod 0444 /etc/crontabs/root

HEALTHCHECK --interval=60s --timeout=3s --retries=3 \
    CMD ["pgrep", "crond"]

CMD ["crond", "-f", "-l", "2"]
