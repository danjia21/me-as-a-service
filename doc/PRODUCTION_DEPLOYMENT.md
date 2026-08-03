# Production deployment

This runbook deploys the single-VPS production contract. The host needs Docker
Engine with Compose, a public IPv4 or IPv6 address, DNS, and outbound HTTPS
access to OpenAI and, when enabled, LangSmith. Only Traefik publishes ports 80
and 443.

The repository supplies deployment artifacts; DNS changes, provider account
limits, secret creation, external uptime monitoring, and receiver credentials
remain operator actions.

## AWS infrastructure and host automation

AWS deployments can provision the repeatable cloud-owned resources under
`infra/aws/`. The Terraform/OpenTofu configuration covers Lightsail compute,
static IPv4 and IPv4/IPv6 firewall rules, a protected S3 backup bucket, a
policy-only backup identity, optional Route 53 DNS, and optional budget
notifications. It deliberately does not automate root MFA, recovery, the first
trusted administrator, SSH private keys, IAM access keys, or application
secrets. Follow [`infra/aws/README.md`](../infra/aws/README.md) and review a
saved plan before every apply.

Repeatable Ubuntu host operations live under `scripts/aws-host/`. Every
mutating script has an explicit apply/deploy mode, and the SSH-hardening path
requires both a restricted source CIDR and confirmation that a second
key-based session works.

Run the non-destructive checks first:

```bash
scripts/aws-host/check-host.sh \
  --source-dir /opt/me-as-a-service \
  --minimum-memory-mib 1800 \
  --minimum-disk-gib 12

sudo scripts/aws-host/install-docker.sh --check
sudo scripts/aws-host/harden-host.sh --check
```

On a new host, install Docker and apply the guarded hardening once the
infrastructure firewall and a second SSH session are confirmed:

```bash
sudo scripts/aws-host/install-docker.sh \
  --apply \
  --deploy-user DEPLOY_USER

sudo scripts/aws-host/harden-host.sh \
  --apply \
  --ssh-cidr OPERATOR_ADDRESS/32 \
  --ssh-port 22 \
  --swap-gib 2 \
  --confirm-secondary-session
```

Both apply paths are safe to rerun. Docker group membership remains
root-equivalent. Keep the original SSH session open until another connection
succeeds after hardening.

## 1. Prepare the host

- Create an unprivileged deployment user with permission to run Docker.
- Use SSH keys and disable password authentication and direct root login.
- Restrict SSH by source address or VPN when practical.
- Allow inbound TCP 80 and 443. Keep PostgreSQL, API, Next.js, Prometheus,
  Alertmanager, and Docker daemon ports closed.
- Enable the distribution's automatic security updates, or record a monthly
  patch window.
- Enable both the VPS-provider firewall and the host firewall.
- Configure DNS for the production name before requesting the certificate.

Install the checkout under a stable path and create a root-readable secret
directory:

```bash
sudo install -d -m 0700 /etc/maas
sudo cp .env.production.example /etc/maas/production.env
sudo chmod 0600 /etc/maas/production.env
openssl rand -hex 32 | sudo tee /etc/maas/metrics-token >/dev/null
openssl rand -hex 32 | sudo tee /etc/maas/restic-password >/dev/null
sudo chmod 0600 /etc/maas/metrics-token /etc/maas/restic-password
```

Edit `/etc/maas/production.env` and replace every example value. Keep it and
the referenced secret files outside Git. Use independent high-entropy values
for PostgreSQL, the internal web-to-API proxy, metrics, Grafana, and restic.
URL-encode the PostgreSQL password in `DATABASE_URL`.

For OpenAI:

- create a dedicated project and restricted API key;
- set a monthly hard spend limit;
- restrict the project to the intended models;
- leave hosted web search and unrelated paid tools disabled.

The application daily token limit is a safety layer, not a substitute for the
provider hard limit.

LangSmith is optional. To enable it, set `LANGSMITH_TRACING=true`, provide a
restricted `LANGSMITH_API_KEY`, and choose `LANGSMITH_PROJECT`. Set
`LANGSMITH_ENDPOINT` for a non-default region and `LANGSMITH_WORKSPACE_ID` when
the key scope requires it. Traces include visitor messages, system prompts,
answers, and retrieved evidence; restrict project access accordingly. Leaving
tracing disabled does not affect readiness or chat.

## 2. Configure proxy trust and alerts

For a direct-to-VPS deployment, leave `MAAS_TRAEFIK_TRUSTED_IPS` at the
loopback-only default. If a CDN is added, replace it with that CDN's documented
egress CIDRs and configure the CDN to replace client forwarding headers. Never
trust all forwarding sources.

Copy the Alertmanager example outside the checkout and add one real receiver:

```bash
sudo cp deploy/alertmanager/alertmanager.example.yml /etc/maas/alertmanager.yml
sudo chmod 0600 /etc/maas/alertmanager.yml
```

Set `MAAS_ALERTMANAGER_CONFIG=/etc/maas/alertmanager.yml`. Receiver secrets
belong in that root-readable file or an external secret mechanism, never in the
checked-in example.

## 3. Validate and start

Use the same file list for every production operation:

```bash
sudo scripts/aws-host/deploy-app.sh \
  --mode verify \
  --source-dir /opt/me-as-a-service \
  --env-file /etc/maas/production.env \
  --observability

sudo scripts/aws-host/deploy-app.sh \
  --mode deploy \
  --source-dir /opt/me-as-a-service \
  --env-file /etc/maas/production.env \
  --observability \
  --run-checks
```

Omit `compose.observability.yaml` to use hosted Prometheus-compatible
monitoring. In that case, scrape Traefik on its private metrics entry point and
FastAPI `/metrics` with the configured bearer token from a private collector.
Retain an equivalent dashboard and alert set.

Check service state and the public boundary:

```bash
sudo scripts/aws-host/verify-deployment.sh \
  --source-dir /opt/me-as-a-service \
  --env-file /etc/maas/production.env \
  --domain PUBLIC_HOSTNAME \
  --observability
```

Do not publish or temporarily map private service ports for convenience.
The verification script rejects unexpected non-loopback TCP listeners; expected
ports are 80 and 443 plus the deliberately restricted SSH administration path.
Use `--allow-port` only for a reviewed additional listener. Grafana binds to
`127.0.0.1:3001` and is reached through an SSH tunnel:

```bash
ssh -L 3001:127.0.0.1:3001 deploy@your-vps
```

Then open `http://127.0.0.1:3001` locally.

## 4. Pre-launch exercise

Before pointing public DNS at the host, complete and record:

1. `docker compose config --quiet`, clean image builds, and `pnpm check`.
2. Desktop and mobile first-turn, follow-up, correction, redirection, reset,
   refresh, and stale-session recovery in a real browser.
3. NDJSON streaming through Traefik and the issued TLS certificate.
4. Edge body, rate, and 16-request in-flight bounds plus application IP,
   conversation, four-active, and eight-queued limits.
5. A modest load test below the provider spend ceiling.
6. An API restart during an active PostgreSQL-persisted conversation.
7. Dashboard panels, target health, log redaction, and Docker log rotation.
8. A real alert receiver test by temporarily changing the disabled
   `MaasDeploymentTestAlert` expression from `vector(0)` to `vector(1)`,
   reloading Prometheus, confirming delivery, and reverting it.
9. A manual backup and clean-database restore using the procedure below.
10. A port scan from a different network.
11. An external HTTPS uptime probe with independent alert delivery.

The in-VPS monitoring stack cannot report total VPS, network, or provider
failure. The external probe is a launch requirement, not an optional duplicate.

## 5. Backups and restore

The backup container runs at 02:17 UTC. It streams a custom-format `pg_dump`
into restic. Restic encrypts before upload to the configured S3-compatible
repository and retains seven daily and four weekly snapshots by default.

Run an on-demand backup:

```bash
sudo scripts/aws-host/verify-backup-restore.sh \
  --mode backup \
  --source-dir /opt/me-as-a-service \
  --env-file /etc/maas/production.env
```

Never test restore against the production database. Create an empty PostgreSQL
database, construct its connection URL, and restore into that target:

```bash
sudo scripts/aws-host/verify-backup-restore.sh \
  --mode restore \
  --source-dir /opt/me-as-a-service \
  --env-file /etc/maas/production.env \
  --restore-database-url RESTORE_DATABASE_URL \
  --confirm-clean-target
```

Validation is complete only after the restored API starts against that
database, loads a known persisted conversation, and reads the restored
`daily_model_usage` aggregate. Record the restore date, snapshot ID, and result
without recording conversation content or credentials.

Legacy `turn_traces` and `trace_evidence` tables are intentionally left in place
during upgrade. After the new usage ledger and LangSmith export have been
verified and a backup exists, remove them explicitly with:

```bash
psql "$DATABASE_URL" -f apps/api/migrations/drop_legacy_trace_tables.sql
```

The cleanup is destructive; recovery requires restoring the legacy tables from
a database backup.

For a routine update, keep the checkout clean and on a branch with a configured
upstream, then run `deploy-app.sh --mode update` with the same options. It uses
only `git pull --ff-only`, rebuilds, and reconciles Compose; it never merges,
rebases, commits, or pushes.

Use provider volume snapshots only as a second recovery layer. They do not
replace the encrypted off-host logical backup.

## 6. Routine operations

- Review Grafana and firing alerts weekly.
- Confirm `maas_backup_last_run_success` is 1 and the last-success timestamp is
  less than 26 hours old.
- Review provider spend and application token budget daily during launch week.
- Apply host and container security updates on the documented cadence.
- Rotate model, proxy, metrics, database, Grafana, restic, and alert receiver
  credentials after suspected disclosure and at least annually.
- Keep conversation retention at 24 hours unless the privacy policy is
  deliberately revised.
- Never add API workers or replicas until rate limiting, concurrency, and
  budget reservations use shared atomic state.

When the model provider quota is exhausted, the API must return its existing
bounded failure/usage response. Do not bypass the provider ceiling during an
incident.
