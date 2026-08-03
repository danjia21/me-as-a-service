#!/usr/bin/env bash

set -Eeuo pipefail
SCRIPT_DIRECTORY=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
source "$SCRIPT_DIRECTORY/lib.sh"

mode=""
ssh_port=22
ssh_cidr=""
swap_gib=2
lockout_confirmation="false"

usage() {
  cat <<'EOF'
Usage:
  harden-host.sh --check [--ssh-port PORT]
  harden-host.sh --apply --ssh-cidr CIDR [options]

Options:
  --ssh-port PORT                 SSH port (default: 22)
  --ssh-cidr CIDR                 IPv4/IPv6 source allowed to reach SSH
  --swap-gib N                    Swap-file size when no swap exists (default: 2)
  --confirm-secondary-session     Confirm a second key-based SSH session works
  --help                          Show this help

The apply path changes SSH and firewall settings and must run as root. Keep the
current SSH session open. The script refuses lockout-sensitive changes without
the explicit secondary-session confirmation.
EOF
}

while (($# > 0)); do
  case "$1" in
    --check | --apply)
      [[ -z $mode ]] || die "choose exactly one of --check or --apply"
      mode=${1#--}
      shift
      ;;
    --ssh-port)
      ssh_port=${2:-}
      shift 2
      ;;
    --ssh-cidr)
      ssh_cidr=${2:-}
      shift 2
      ;;
    --swap-gib)
      swap_gib=${2:-}
      shift 2
      ;;
    --confirm-secondary-session)
      lockout_confirmation="true"
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

[[ -n $mode ]] || die "choose --check or --apply"
if ! [[ $ssh_port =~ ^[0-9]+$ ]] ||
  ((ssh_port < 1 || ssh_port > 65535)); then
  die "invalid SSH port"
fi
[[ $swap_gib =~ ^[0-9]+$ ]] || die "swap size must be a non-negative integer"
require_ubuntu

check_hardening() {
  require_command sshd
  require_command ufw
  require_command swapon
  sshd -t
  effective_sshd=$(sshd -T)
  grep -q '^permitrootlogin no$' <<<"$effective_sshd" ||
    die "SSH root login is not disabled"
  grep -q '^passwordauthentication no$' <<<"$effective_sshd" ||
    die "SSH password authentication is not disabled"
  ufw status | grep -q '^Status: active$' || die "UFW is not active"
  systemctl is-enabled unattended-upgrades >/dev/null ||
    die "automatic security updates are not enabled"
  log "SSH, UFW, and automatic-update checks passed"
}

if [[ $mode == "check" ]]; then
  require_root
  check_hardening
  exit 0
fi

require_root
[[ -n $ssh_cidr ]] || die "--ssh-cidr is required with --apply"
[[ $lockout_confirmation == "true" ]] ||
  die "confirm a second key-based SSH session with --confirm-secondary-session"
require_command apt-get
export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get full-upgrade -y
apt-get install -y unattended-upgrades ufw
systemctl enable --now unattended-upgrades

temporary_sshd=$(mktemp)
trap 'rm -f "$temporary_sshd"' EXIT
cat >"$temporary_sshd" <<EOF
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
X11Forwarding no
MaxAuthTries 3
LoginGraceTime 30
Port ${ssh_port}
EOF
install -m 0644 "$temporary_sshd" /etc/ssh/sshd_config.d/99-maas-hardening.conf
sshd -t

ufw default deny incoming
ufw default allow outgoing
ufw allow from "$ssh_cidr" to any port "$ssh_port" proto tcp comment SSH
ufw allow 80/tcp comment HTTP
ufw allow 443/tcp comment HTTPS
ufw --force enable

systemctl reload ssh

if ((swap_gib > 0)) && [[ -z $(swapon --noheadings --show=NAME) ]]; then
  fallocate -l "${swap_gib}G" /swapfile
  chmod 0600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -qF '/swapfile none swap sw 0 0' /etc/fstab ||
    printf '/swapfile none swap sw 0 0\n' >>/etc/fstab
fi

printf 'vm.swappiness=10\n' >/etc/sysctl.d/99-maas-memory.conf
sysctl --system >/dev/null
check_hardening
log "hardening applied; keep this session open until a new SSH connection succeeds"
