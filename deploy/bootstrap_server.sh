#!/usr/bin/env bash
# One-time server preparation for Ubuntu 24.04 (run as root on a NEW droplet only).
# Installs Docker Engine + Compose plugin from Docker's apt repo, enables a firewall
# (SSH/HTTP/HTTPS only), adds 2 GB swap for image builds, and clones the repository.
set -euo pipefail
apt-get update
apt-get install -y ca-certificates curl git ufw python3
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
[ -d /opt/marketops ] || git clone https://github.com/gaurannggg7/MarketOps.git /opt/marketops
echo "bootstrap done; next: see docs/deployment.md 'Deploy'"
