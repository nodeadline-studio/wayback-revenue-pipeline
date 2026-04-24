#!/usr/bin/env bash
# Run on the EC2 host, NOT locally.
# Idempotent one-time install of BizSpy backend.
set -euo pipefail

echo "[1/6] Ensure bizspy user"
if ! id bizspy &>/dev/null; then
  sudo useradd -m -s /bin/bash bizspy
fi

echo "[2/6] Move staged code to /opt/bizspy-api"
sudo mkdir -p /opt/bizspy-api/output
sudo rsync -a --delete /tmp/bizspy-stage/ /opt/bizspy-api/
sudo chown -R bizspy:bizspy /opt/bizspy-api

echo "[3/6] Compose /opt/bizspy-api/.env from leadideal shared keys + bizspy defaults"
sudo bash -c '
  src=/opt/leadideal-api/.env
  dst=/opt/bizspy-api/.env
  : > "$dst"
  if [[ -f "$src" ]]; then
    for k in GEMINI_API_KEY GOOGLE_API_KEY OPENAI_API_KEY SENDGRID_API_KEY FROM_EMAIL APP_SECRET_KEY; do
      v=$(grep -E "^${k}=" "$src" | head -1 | cut -d= -f2-)
      if [[ -n "${v:-}" ]]; then echo "${k}=${v}" >> "$dst"; fi
    done
  fi
  cat >> "$dst" <<EOF
APP_PUBLIC_DOMAIN=https://bizspy.netlify.app
LOG_LEVEL=INFO
PAYPAL_MODE=sandbox
PAYPAL_CLIENT_ID=
PAYPAL_CLIENT_SECRET=
ADMIN_UNLOCK_TOKEN=
EOF
  chown bizspy:bizspy "$dst"
  chmod 600 "$dst"
'

echo "[4/6] venv + pip install"
sudo -u bizspy bash -lc '
  set -e
  cd /opt/bizspy-api
  if [[ ! -d .venv ]]; then python3 -m venv .venv; fi
  .venv/bin/pip install --upgrade pip wheel >/dev/null
  .venv/bin/pip install -r requirements.txt >/tmp/bizspy-pip.log 2>&1 || { tail -50 /tmp/bizspy-pip.log; exit 1; }
  .venv/bin/pip install gunicorn >>/tmp/bizspy-pip.log 2>&1
  echo "pip install OK"
'

echo "[5/6] Install systemd unit"
sudo cp /opt/bizspy-api/deploy/ec2/bizspy-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable bizspy-api
sudo systemctl restart bizspy-api
sleep 4

echo "[6/6] Health check"
sudo systemctl --no-pager status bizspy-api | head -15
echo "---"
curl -fsS http://127.0.0.1:8010/health || { echo "HEALTH FAILED"; sudo journalctl -u bizspy-api -n 50 --no-pager; exit 1; }
echo
echo "DONE"
