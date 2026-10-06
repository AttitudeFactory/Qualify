#!/usr/bin/env bash
# One-time preparation of a FRESH Hetzner Cloud server (Ubuntu 24.04), run as root from the
# founder's Mac:
#
#   ssh root@<IP> 'bash -s' < deploy/bootstrap-server.sh
#
# Idempotent: safe to re-run. What it does:
#   1. OS updates + unattended security upgrades.
#   2. Docker Engine + Compose plugin from Docker's official apt repository.
#   3. A 2 GB swapfile (a CX22 has 4 GB RAM; the frontend build peaks during `docker build`).
#   4. Non-root `deploy` user (member of `docker`), with root's authorized SSH keys.
#   5. /opt/qualify/{releases,backups} owned by `deploy`.
#   6. ufw: deny incoming except 22/tcp, 80/tcp, 443/tcp, 443/udp.
#   7. sshd: key-only logins (password auth off), root only with a key.
#   8. Nightly Postgres backup at 03:15 UTC (deploy/backup-db.sh, as `deploy`).
#
# Note: Docker publishes container ports through its own iptables chain, which bypasses ufw.
# That is safe here only because the prod compose publishes NOTHING but Caddy's 80/443 —
# never add `ports:` to postgres or redis.
set -euo pipefail

DEPLOY_USER=deploy
ROOT_DIR=/opt/qualify

[[ $EUID -eq 0 ]] || { echo "run as root" >&2; exit 1; }
# shellcheck source=/dev/null
. /etc/os-release
[[ "$ID" == "ubuntu" ]] || echo "warning: tested on Ubuntu 24.04, this is $PRETTY_NAME" >&2

export DEBIAN_FRONTEND=noninteractive

echo "==> 1. OS packages"
apt-get update -q
apt-get upgrade -y -q
apt-get install -y -q ca-certificates curl gnupg ufw unattended-upgrades
dpkg-reconfigure -f noninteractive unattended-upgrades

echo "==> 2. Docker Engine + Compose plugin"
if ! command -v docker >/dev/null 2>&1; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    >/etc/apt/sources.list.d/docker.list
  apt-get update -q
  apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-buildx-plugin \
    docker-compose-plugin
fi
systemctl enable --now docker

echo "==> 3. Swap"
if ! swapon --show | grep -q /swapfile; then
  if [[ ! -f /swapfile ]]; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
  fi
  swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >>/etc/fstab
fi
sysctl -q -w vm.swappiness=10
echo 'vm.swappiness=10' >/etc/sysctl.d/99-qualify-swap.conf

echo "==> 4. User $DEPLOY_USER"
if ! id "$DEPLOY_USER" >/dev/null 2>&1; then
  adduser --disabled-password --gecos "" "$DEPLOY_USER"
fi
usermod -aG docker "$DEPLOY_USER"
install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "/home/$DEPLOY_USER/.ssh"
if [[ -s /root/.ssh/authorized_keys ]]; then
  install -m 600 -o "$DEPLOY_USER" -g "$DEPLOY_USER" /root/.ssh/authorized_keys \
    "/home/$DEPLOY_USER/.ssh/authorized_keys"
else
  echo "warning: /root/.ssh/authorized_keys is empty — add a key for $DEPLOY_USER by hand" >&2
fi

echo "==> 5. $ROOT_DIR"
install -d -m 750 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$ROOT_DIR" "$ROOT_DIR/releases"
install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$ROOT_DIR/backups"

echo "==> 6. Firewall (ufw)"
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable

echo "==> 7. sshd: keys only"
if [[ -s "/home/$DEPLOY_USER/.ssh/authorized_keys" ]]; then
  cat >/etc/ssh/sshd_config.d/99-qualify.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
EOF
  sshd -t && systemctl reload ssh
else
  echo "warning: skipped sshd hardening — $DEPLOY_USER has no key yet (would risk a lockout)" >&2
fi

echo "==> 8. Nightly backup cron"
cat >/etc/cron.d/qualify-backup <<EOF
# Postgres dump of the Qualify stack (deploy/backup-db.sh). Output: $ROOT_DIR/backups
15 3 * * * $DEPLOY_USER [ -x $ROOT_DIR/current/deploy/backup-db.sh ] && $ROOT_DIR/current/deploy/backup-db.sh >>$ROOT_DIR/backups/backup.log 2>&1
EOF
chmod 644 /etc/cron.d/qualify-backup

echo
echo "Done. Next, from the Mac:"
echo "  1. scp deploy/.env.prod.example $DEPLOY_USER@<IP>:$ROOT_DIR/.env.prod   (then fill it in, chmod 600)"
echo "  2. just deploy $DEPLOY_USER@<IP>"
docker --version
docker compose version
