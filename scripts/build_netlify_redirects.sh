#!/usr/bin/env bash
# Generate web/_redirects and web/sitemap.xml from BIZSPY_API_ORIGIN at Netlify build time.
# If BIZSPY_API_ORIGIN is unset, the proxy redirects are omitted so the
# frontend's offline banner is shown instead of returning HTML for /api/*.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${ROOT}/web/_redirects"
SITEMAP="${ROOT}/web/sitemap.xml"

origin="${BIZSPY_API_ORIGIN:-}"

{
  if [[ -n "${origin}" ]]; then
    echo "/api/*      ${origin}/api/:splat       200!"
    echo "/health     ${origin}/health           200!"
    echo "/reports/*  ${origin}/reports/:splat   200!"
  else
    # Explicit JSON 503 so the frontend's catch handler shows a real message
    # instead of trying to JSON.parse the SPA shell.
    echo "/api/*      /backend-offline.json     503!"
    echo "/health     /backend-offline.json     503!"
    echo "/reports/*  /backend-offline.json     503!"
  fi
  echo "/*          /index.html               200"
} > "${OUT}"

cat > "${ROOT}/web/backend-offline.json" <<'JSON'
{
  "error": "backend_offline",
  "message": "BizSpy backend is not configured. Set BIZSPY_API_ORIGIN in Netlify and redeploy.",
  "schema_version": "bizspy.error.v1"
}
JSON

echo "Wrote ${OUT}:"
cat "${OUT}"

# --- sitemap.xml ---
SITE_URL="https://bizspy.netlify.app"
NOW="$(date -u +%Y-%m-%d)"

# Fetch list of public report slugs from backend if available
REPORT_URLS=""
if [[ -n "${origin}" ]]; then
  REPORT_JSON=$(curl -fsS --max-time 10 "${origin}/api/public/reports" 2>/dev/null || echo "[]")
  # Parse slugs with Python (available on Netlify build image)
  REPORT_URLS=$(echo "${REPORT_JSON}" | python3 -c "
import sys, json
try:
    items = json.load(sys.stdin)
    for item in items:
        slug = item.get('slug', '')
        if slug:
            print(f'  <url><loc>https://bizspy.netlify.app/reports/{slug}/</loc><changefreq>monthly</changefreq></url>')
except Exception:
    pass
" 2>/dev/null || true)
fi

cat > "${SITEMAP}" <<SITEMAP_EOF
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>${SITE_URL}/</loc>
    <lastmod>${NOW}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>
  <url>
    <loc>${SITE_URL}/dashboard.html</loc>
    <lastmod>${NOW}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.5</priority>
  </url>
  <url>
    <loc>${SITE_URL}/checkout.html</loc>
    <lastmod>${NOW}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.4</priority>
  </url>
${REPORT_URLS}
</urlset>
SITEMAP_EOF

echo "Wrote ${SITEMAP}"
