# BizSpy EC2 Deploy

This bundle hosts the Flask backend (`app.py`) on the existing LeadIdeal
EC2 instance under a dedicated `bizspy` user. The backend runs on
`127.0.0.1:8010` behind nginx on `api.bizspy.example.com` (TLS via certbot).

## Files

- `bizspy-api.service` — systemd unit, runs gunicorn as user `bizspy`.
- `nginx-bizspy.conf`  — reverse proxy + `/reports/` static alias + CORS.
- `deploy.sh`          — local rsync + remote venv install + systemd restart.

## One-time host setup

```bash
sudo useradd -m -s /bin/bash bizspy
sudo mkdir -p /opt/bizspy-api/output
sudo chown -R bizspy:bizspy /opt/bizspy-api
sudo apt-get install -y python3-venv nginx certbot python3-certbot-nginx
sudo cp deploy/ec2/bizspy-api.service /etc/systemd/system/
sudo cp deploy/ec2/nginx-bizspy.conf  /etc/nginx/sites-available/bizspy
sudo ln -sf /etc/nginx/sites-available/bizspy /etc/nginx/sites-enabled/bizspy
# (set up DNS A record first)
sudo certbot --nginx -d api.bizspy.example.com
sudo systemctl daemon-reload && sudo systemctl enable bizspy-api
```

Then create `/opt/bizspy-api/.env` (chown bizspy:bizspy, chmod 600) with the
production env (PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET, PAYPAL_MODE,
GEMINI_API_KEY, ADMIN_UNLOCK_TOKEN, APP_PUBLIC_DOMAIN, etc).

## Deploy from local

```bash
export BIZSPY_SSH_HOST=ubuntu@100.48.115.164
export BIZSPY_SSH_KEY=~/.ssh/leadideal-deployer.pem
bash deploy/ec2/deploy.sh
```

## Wire Netlify

In the Netlify dashboard for the `bizspy` site:

1. Site settings → Environment variables → add
   `BIZSPY_API_ORIGIN = https://api.bizspy.example.com`
2. Trigger a deploy (the `scripts/build_netlify_redirects.sh` step rewrites
   `web/_redirects` based on this var).
3. Verify:
   ```
   curl -fsS https://bizspy.netlify.app/health
   curl -fsS https://bizspy.netlify.app/api/startup-presets
   ```

## Agent access

Any IDE agent with project access can fetch a report by URL:

```
GET https://bizspy.netlify.app/reports/<slug>/report.agent.json
GET https://bizspy.netlify.app/api/agent/<slug>
```

Schema: `bizspy.report.agent.v1`. Premium fields are present but redacted
when `is_paid=false`. After a successful PayPal capture (or admin unlock),
the same JSON is regenerated with `is_paid=true` and full content.

## Manual unlock for QA

```
curl -X POST https://api.bizspy.example.com/api/admin/unlock \
  -H "Content-Type: application/json" \
  -H "X-Admin-Token: $ADMIN_UNLOCK_TOKEN" \
  -d '{"target_url":"leadideal.com"}'
```
