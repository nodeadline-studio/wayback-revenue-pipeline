#!/usr/bin/env bash
# BizSpy EC2 deploy script.
#
# Prerequisites on the EC2 host (one-time, run as ubuntu via sudo):
#   sudo useradd -m -s /bin/bash bizspy
#   sudo mkdir -p /opt/bizspy-api/output && sudo chown -R bizspy:bizspy /opt/bizspy-api
#   sudo apt-get install -y python3-venv nginx certbot python3-certbot-nginx
#   sudo cp deploy/ec2/bizspy-api.service /etc/systemd/system/
#   sudo cp deploy/ec2/nginx-bizspy.conf  /etc/nginx/sites-available/bizspy
#   sudo ln -sf /etc/nginx/sites-available/bizspy /etc/nginx/sites-enabled/bizspy
#   sudo certbot --nginx -d api.bizspy.example.com   # or skip and run plain HTTP for now
#   sudo systemctl daemon-reload && sudo systemctl enable bizspy-api
#
# Then locally:
#   bash deploy/ec2/deploy.sh                   # rsync code + restart service
#
# Required local env:
#   BIZSPY_SSH_HOST        (e.g. ubuntu@100.48.115.164)
#   BIZSPY_SSH_KEY         (path to .pem)
set -euo pipefail

HOST="${BIZSPY_SSH_HOST:-}"
KEY="${BIZSPY_SSH_KEY:-$HOME/.ssh/leadideal-deployer.pem}"
REMOTE_DIR="/opt/bizspy-api"

if [[ -z "$HOST" ]]; then
  echo "BIZSPY_SSH_HOST not set. Example: BIZSPY_SSH_HOST=ubuntu@100.48.115.164 bash deploy/ec2/deploy.sh" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

echo "[1/5] Rsyncing code to $HOST:$REMOTE_DIR (excluding venv, output, node_modules, .env)..."
rsync -az --delete \
  --exclude '.venv' \
  --exclude '.git' \
  --exclude 'output' \
  --exclude 'node_modules' \
  --exclude '__pycache__' \
  --exclude '*.log' \
  --exclude '.env' \
  --exclude 'saas.sqlite' \
  -e "ssh -i $KEY -o StrictHostKeyChecking=accept-new" \
  ./ "$HOST:/tmp/bizspy-stage/"

ssh -i "$KEY" "$HOST" bash -se <<EOF
set -euo pipefail
sudo rsync -a --delete /tmp/bizspy-stage/ ${REMOTE_DIR}/
sudo chown -R bizspy:bizspy ${REMOTE_DIR}
sudo -u bizspy bash -lc "
  cd ${REMOTE_DIR}
  if [[ ! -d .venv ]]; then python3 -m venv .venv; fi
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt
  .venv/bin/pip install gunicorn
  mkdir -p output
"
sudo systemctl daemon-reload
sudo systemctl restart bizspy-api
sleep 2
sudo systemctl --no-pager status bizspy-api | head -20
EOF

echo "[2/5] Probing /health..."
ssh -i "$KEY" "$HOST" "curl -fsS http://127.0.0.1:8010/health || true"

echo
echo "[OK] Deploy complete. Next steps:"
echo "  1) On Netlify, set BIZSPY_API_ORIGIN to your public backend URL"
echo "     (e.g. https://api.bizspy.example.com) and redeploy bizspy.netlify.app."
echo "  2) Test:  curl -fsS https://api.bizspy.example.com/health"
echo "  3) Test:  curl -fsS https://bizspy.netlify.app/health"
