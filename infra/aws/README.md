# AWS infrastructure

This directory defines the smallest repeatable AWS scope needed by the
single-host deployment:

- one Lightsail instance, a static IPv4 address for dual-stack deployments,
  and explicit IPv4/IPv6 firewall rules;
- one private S3 backup bucket with public access blocked, bucket-owner
  enforcement, server-side encryption, and cleanup of incomplete uploads;
- one least-privilege IAM backup user and inline restic policy;
- an optional Route 53 A record; and
- optional monthly budget notifications.

Terraform 1.6+ and OpenTofu-compatible HCL are supported. The AWS provider is
constrained to major version 6. Terraform state can contain infrastructure
identifiers and must use a protected backend; never commit local state or plan
files.

## Deliberate manual gates

This configuration does not automate root MFA, recovery details, the initial
trusted administrative identity, SSH private keys, IAM access keys, domain
registration, non-Route-53 DNS, or application secrets. The backup IAM user is
created without an access key so a secret is not written into Terraform state.
Create a single key separately, transfer it directly to the protected host
environment, and rotate it without committing it.

Lightsail automatic snapshots remain a console/CLI launch gate because they
are a secondary machine-recovery layer, not the authoritative encrypted
database backup. IPv6 addresses are output for review, but the module creates
no AAAA record: confirm the selected Lightsail networking behavior and public
reachability before publishing one.

## Initialize and review

Use AWS credentials for the non-root infrastructure administrator. Copy the
example to an ignored filename and replace all example values:

```bash
cd infra/aws
cp terraform.tfvars.example deployment.auto.tfvars
terraform init
terraform fmt -check
terraform validate
terraform plan -out deployment.tfplan
terraform show deployment.tfplan
```

OpenTofu users may substitute `tofu` for `terraform`. A plan can create
billable resources and may propose replacement or destruction. Review the
complete plan, especially the Lightsail instance, static IP, firewall rules,
bucket, IAM identity, DNS, and budget, before applying:

```bash
terraform apply deployment.tfplan
```

The backup bucket and IAM user use `prevent_destroy`. Retire them deliberately:
preserve or remove backup data according to the retention policy, remove the
guard in a reviewed change, inspect a new plan, and only then apply it.

## Fresh environment

1. Complete root MFA, recovery, and administrator-identity setup manually.
2. Confirm the current Lightsail Ubuntu blueprint and bundle IDs in the chosen
   region.
3. Configure a restricted operator SSH CIDR and review the plan.
4. Apply this configuration.
5. Create one access key for the generated backup user outside Terraform and
   save it directly in the protected host environment.
6. Run `scripts/aws-host/check-host.sh`, then the guarded Docker and hardening
   scripts described in `doc/PRODUCTION_DEPLOYMENT.md`.
7. Configure application secrets, deploy, test backup/restore, enable the
   secondary Lightsail snapshot, and add external uptime monitoring.
