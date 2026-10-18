#!/usr/bin/env bash
# Root-level setup for the dev server (192.168.100.142) — run ON the server:
#     bash scripts/server-bootstrap.sh
# Installs: make, docker + compose plugin, python3-pip/venv, fail2ban, ufw basics.
# Everything else in DEVELOPMENT.md §7 runs without root afterwards.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "needs admin rights — re-running elevated" >&2
  exec sudo bash "$0" "$@"
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get -y upgrade
apt-get -y install make python3-pip python3-venv ca-certificates curl gnupg ufw fail2ban

# Docker engine + compose plugin (official repo)
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
docker compose version || echo "WARN: compose plugin missing"

# Optional: Python 3.12 (DEVELOPMENT.md §5 target) on Ubuntu 22.04 via deadsnakes
if ! command -v python3.12 >/dev/null 2>&1; then
  apt-get -y install software-properties-common
  add-apt-repository -y ppa:deadsnakes/ppa
  apt-get update
  apt-get -y install python3.12 python3.12-venv || echo "WARN: python3.12 unavailable — using system python3"
fi

# Firewall: SSH only from LAN (§8)
ufw --force default deny incoming
ufw --force allow OpenSSH
ufw --force allow from 192.168.100.0/24 to any port 22 proto tcp
ufw --force enable
systemctl enable --now fail2ban

echo "== done =="
docker -v; docker compose version; make -v | head -1
python3 -m pip --version || true
command -v python3.12 && python3.12 -V || true
echo "Now: docker compose -f docker-compose.dev.yml up -d db redis   (as your user)"
