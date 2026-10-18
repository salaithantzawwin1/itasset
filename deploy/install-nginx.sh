#!/usr/bin/env bash
# Server-side root setup for §24 phase 1 (LAN HTTP):
#   bash deploy/install-nginx.sh   (run ON the server; needs sudo)
# - installs nginx, enables the itasset site (LAN :80 → 127.0.0.1:8001)
# - allows port 80 from LAN only
# - closes LAN port 8000 (app no longer binds 0.0.0.0; gunicorn is 127.0.0.1:8001)
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "needs root — re-running with sudo" >&2
  exec sudo bash "$0" "$@"
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get -y install nginx

# enable the itasset site
cp /home/glgadmin/itasset/deploy/nginx-itasset.conf /etc/nginx/sites-available/itasset
ln -sf /etc/nginx/sites-available/itasset /etc/nginx/sites-enabled/itasset
rm -f /etc/nginx/sites-enabled/default
nginx -t

systemctl enable --now nginx
systemctl reload nginx

# firewall: LAN can reach :80; close 8000 (was opened for dev runserver)
ufw allow from 192.168.100.0/24 to any port 80 proto tcp
ufw delete allow from 192.168.100.0/24 to any port 8000 proto tcp 2>/dev/null || true
ufw status verbose | sed -n '1,10p'

echo "== nginx installed; app: http://192.168.100.142 (LAN) =="
