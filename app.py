import hmac
import hashlib
import importlib
import json
import logging
import re
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, send_from_directory
from flask_cors import CORS

try:
    stripe = importlib.import_module("stripe")
except ImportError:
    stripe = None

from src.pipeline import Pipeline
from src.narrator import StrategicNarrator, hydrate_gemini_key_from_video_gen_clean
from src.startup_intel import build_sprint_context, record_approval_decision
from src.startup_presets import apply_startup_preset, list_startup_presets
from src.database import Database
from src.email_engine import EmailEngine

load_dotenv()
hydrate_gemini_key_from_video_gen_clean(override=True)

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

base_dir = os.path.dirname(os.path.abspath(__file__))
template_dir = os.path.join(base_dir, 'templates')
static_dir = os.path.join(base_dir, 'web')

# --- INSTANCE LOCKING ---
def acquire_instance_lock(lock_name="app"):
    import sys
    # Use /tmp so the service user (bizspy) can always write regardless of app dir ownership
    pid_file = os.path.join("/tmp", f"bizspy-{lock_name}.pid")
    if os.path.exists(pid_file):
        try:
            with open(pid_file, "r") as f:
                old_pid = int(f.read().strip())
            # Check if process is still running on Unix
            os.kill(old_pid, 0)
            logger.error(f"FATAL: Instance of {lock_name} is already running (PID {old_pid}). Aborting to prevent corruption.")
            sys.exit(1)
        except (OSError, ValueError):
            # Process not running or invalid PID file, we can take it
            pass

    with open(pid_file, "w") as f:
        f.write(str(os.getpid()))
    import atexit
    atexit.register(lambda: os.path.exists(pid_file) and os.remove(pid_file))

acquire_instance_lock("app")

app = Flask(__name__, static_folder=static_dir, static_url_path='/', template_folder=template_dir)
app.secret_key = os.getenv("APP_SECRET_KEY", "super_secret_for_mvp")
CORS(app)

db = Database()
email_engine = EmailEngine()

if stripe is not None:
    stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "sk_test_mock")
else:
    logger.warning("stripe is not installed. Billing features remain disabled in local demo mode.")

# --- DATABASE SETUP ---
db = Database()

# --- IN MEMORY JOBS ---
JOBS = {}
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

DEMO_UNLOCKED_COMPETITORS = 4
DEMO_MAX_SNAPSHOTS = 6
DEMO_ENABLE_NARRATIVE = True

PACKAGES = {
    "starter": {"name": "Starter Report", "price": 49, "competitors": 3, "history_months": 3},
    "pro": {"name": "Pro Report", "price": 149, "competitors": 5, "history_months": 48},
    "super": {"name": "Super Tier", "price": 499, "competitors": 5, "history_months": 48, "includes_bulk_mining": True},
}


def is_unlimited(email: str) -> bool:
    """Return True if email is in UNLIMITED_USERS env list or has tier='unlimited' in DB."""
    if not email:
        return False
    unlimited_list = [
        e.strip().lower()
        for e in os.getenv("UNLIMITED_USERS", "").split(",")
        if e.strip()
    ]
    if email.lower() in unlimited_list:
        return True
    try:
        user = db.get_user(email)
        return bool(user and user.get("tier") == "unlimited")
    except Exception:
        return False


def is_super_paid(order: dict) -> bool:
    """Return True if order is for super tier package."""
    return order.get('package') == 'super'


def _make_share_token(slug: str, expiry: int) -> str:
    secret = os.getenv("SHARE_SECRET") or app.secret_key
    msg = f"{slug}:{expiry}"
    sig = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()[:40]
    return f"{expiry}.{sig}"


def _verify_share_token(slug: str, token: str) -> bool:
    try:
        expiry_str, sig = token.split(".", 1)
        expiry = int(expiry_str)
    except (ValueError, AttributeError):
        return False
    if expiry != 0 and time.time() > expiry:
        return False
    expected = _make_share_token(slug, expiry)
    return hmac.compare_digest(token, expected)


def utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def parse_utc_timestamp(value: str):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def normalize_target_url(raw_url: str) -> str:
    target_url = (raw_url or "").strip()
    if not target_url:
        return ""

    if "://" not in target_url:
        target_url = f"https://{target_url}"

    parsed = urlparse(target_url)
    host = (parsed.netloc or parsed.path).strip().lower().strip("/")
    path = parsed.path if parsed.netloc else ""

    if path and path != "/":
        return f"{host}{path.rstrip('/')}"
    return host


def update_job(job_id: str, **fields) -> None:
    job = JOBS.get(job_id)
    if not job:
        return

    job.update(fields)
    job["updated_at"] = utc_now_iso()

    # Persistent Sync
    user_email = job.get("email")
    if user_email:
        try:
            db.upsert_job(job_id, user_email, job)
        except Exception as e:
            logger.warning(f"Failed to persist job {job_id} for {user_email}: {e}")


def humanize_domain(value: str) -> str:
    normalized = normalize_target_url(value).split("/")[0]
    label = normalized.split(".")[0].replace("-", " ").replace("_", " ").strip()
    if not label:
        return normalized
    return " ".join(word.capitalize() for word in label.split())


def build_demo_urls(target_url: str, unlocked_competitors):
    urls = [{"name": f"{humanize_domain(target_url)} (Target)", "url": target_url}]
    for competitor in unlocked_competitors:
        if isinstance(competitor, dict):
            # Preserve all fields (dates, labels, etc.)
            domain = competitor.get("domain") or competitor.get("url")
            entry = {
                "name": competitor.get("label") or humanize_domain(domain),
                "url": domain
            }
            # Copy over orchestration fields
            for key in ["from_date", "to_date"]:
                if key in competitor:
                    entry[key] = competitor[key]
            urls.append(entry)
        else:
            urls.append({"name": humanize_domain(competitor), "url": competitor})
    return urls


def compute_progress_percent(job: dict) -> int:
    status = job.get("status")
    stage = job.get("stage", "queued")
    if status == "completed" or stage == "report_ready":
        return 100

    competitors_total = max(int(job.get("competitors_total") or 0), 1)
    competitors_completed = min(int(job.get("competitors_completed") or 0), competitors_total)
    snapshots_total = int(job.get("snapshots_total") or 0)
    snapshots_completed = int(job.get("snapshots_completed") or 0)
    snapshot_fraction = 0.0
    if snapshots_total > 0:
        snapshot_fraction = min(snapshots_completed / snapshots_total, 1.0)
    analysis_fraction = min((competitors_completed + snapshot_fraction) / competitors_total, 1.0)

    if stage == "queued":
        return 2
    if stage == "discovering_competitors":
        return 8
    if stage == "starting_analysis":
        return 14
    if stage.startswith("analyzing_"):
        return min(78, round(18 + analysis_fraction * 60))
    if stage.startswith("narrating_"):
        return min(88, round(78 + (competitors_completed / competitors_total) * 8))
    if stage == "summarizing":
        return 90
    if stage == "rendering_report":
        return 95
    if stage == "report_written":
        return 98
    if stage == "failed":
        return min(int(job.get("progress_percent") or 0), 99)
    return 5


def build_stage_label(job: dict) -> str:
    stage = job.get("stage", "queued")
    current_competitor = job.get("current_competitor")
    snapshot_index = job.get("current_snapshot_index")
    snapshots_total = job.get("snapshots_total")

    if stage == "queued":
        return "Request accepted"
    if stage == "discovering_competitors":
        return "Discovering relevant competitors"
    if stage == "starting_analysis":
        return "Preparing archive analysis"
    if stage.startswith("analyzing_"):
        if current_competitor and snapshots_total:
            return f"Analyzing {current_competitor}: snapshot {snapshot_index or 0}/{snapshots_total}"
        if current_competitor:
            return f"Analyzing {current_competitor}"
        return "Analyzing archived pages"
    if stage.startswith("narrating_"):
        if current_competitor:
            return f"Generating insight for {current_competitor}"
        return "Generating competitive insight"
    if stage == "summarizing":
        return "Synthesizing market summary"
    if stage == "rendering_report":
        return "Rendering report"
    if stage == "report_written":
        return "Writing final output"
    if stage == "report_ready":
        return "Report ready"
    if stage == "brief_ready":
        return "Brief ready"
    if stage == "failed":
        return "Processing failed"
    return "Processing"


def build_status_response(job: dict) -> dict:
    payload = dict(job)
    start_time = parse_utc_timestamp(job.get("started_at") or job.get("created_at"))
    now = datetime.now(timezone.utc)
    elapsed_seconds = int((now - start_time).total_seconds()) if start_time else 0

    payload.setdefault("competitors_total", 0)
    payload.setdefault("competitors_completed", 0)
    payload.setdefault("snapshots_total", 0)
    payload.setdefault("snapshots_completed", 0)
    payload["stage_label"] = build_stage_label(job)
    payload["progress_percent"] = compute_progress_percent(job)
    payload["elapsed_seconds"] = elapsed_seconds
    payload["discovery_mode_label"] = {
        "ai": "Gemini discovery",
        "ai_blended": "Gemini + fallback discovery",
        "fallback": "Domain-aware fallback discovery",
    }.get(job.get("competitor_source"), "Initializing discovery")

    # Phase E: Add super bulk mining status
    payload["super_bulk_status"] = _get_super_bulk_status(job)

    return payload


def _get_super_bulk_status(job: dict) -> str:
    """Get super bulk mining status for jobs with super tier orders."""
    order_id = job.get("paypal_order_id")
    if not order_id:
        return "not_applicable"

    try:
        order = db.get_order(order_id)
        if not order or not is_super_paid(order):
            return "not_applicable"

        order_status = order.get("status", "")
        if order_status == "super_bulk_completed":
            return "completed"
        elif job.get("status") == "completed":
            return "in_progress"  # Main report done, bulk mining should be running
        else:
            return "pending"
    except Exception as e:
        print(f"Exception in _get_super_bulk_status: {e}")
        return "unknown"


def resolve_output_path(report_url: str) -> str:
    filename = os.path.basename(str(report_url or "").strip())
    return os.path.join(OUTPUT_DIR, filename)

# --- ROUTES ---
@app.route('/reports/<path:filename>')
def serve_reports(filename):
    return send_from_directory(OUTPUT_DIR, filename)

@app.route('/brief/<slug>')
def serve_brief(slug):
    import re
    if not re.match(r'^[a-z0-9-]+$', slug):
        return "Not found", 404
    payload_path = os.path.join(OUTPUT_DIR, slug, "render-payload.json")
    if not os.path.isfile(payload_path):
        return "Not found", 404
    with open(payload_path) as f:
        brief_data = json.load(f)
    insights = _derive_brief_insights(brief_data)
    return render_template('brief.html', brief=brief_data, insights=insights, slug=slug)


def _derive_brief_insights(brief: dict) -> dict:
    """Extract free-tier insights from raw evidence quotes (heuristic, no LLM)."""
    import re
    quotes = brief.get("evidence_quotes") or []

    def _find(section_prefix):
        for q in quotes:
            if (q.get("section") or "").startswith(section_prefix):
                return q
        return None

    positioning = _find("homepage_h1")
    value_prop = _find("homepage_meta")
    h2 = _find("homepage_h2")

    pillars = []
    seen = set()
    for q in quotes:
        text = (q.get("quote") or "").strip()
        sect = (q.get("section") or "").lower()
        if not text or len(text) > 140 or len(text) < 8:
            continue
        if sect in {"homepage_h1", "homepage_meta"}:
            continue
        key = text.lower()[:60]
        if key in seen:
            continue
        # Skip boilerplate
        if any(b in text.lower() for b in ["privacy policy", "terms of service", "cookie", "all rights reserved"]):
            continue
        seen.add(key)
        pillars.append(text)
        if len(pillars) >= 5:
            break

    combined_text = " ".join((q.get("quote") or "") for q in quotes)

    # ICP detection
    icp_patterns = [
        r"for\s+([a-z][a-z0-9,\s\-&/]+?(?:teams?|agencies|agenc[yi]|companies|businesses|brands?|professionals?|founders?|startups?|smbs?|enterprises?|msps?|operators?))",
    ]
    icp = None
    for pat in icp_patterns:
        m = re.search(pat, combined_text, re.IGNORECASE)
        if m:
            icp = m.group(1).strip().rstrip(".,")
            if len(icp) < 120:
                break
            icp = None

    # Price anchors
    price_anchors = sorted(set(re.findall(r"\$\d[\d,]*(?:\.\d+)?(?:/[a-z]+)?", combined_text)))[:3]

    # Proof points: quotes with a leading number
    proof_points = []
    for q in quotes:
        text = (q.get("quote") or "").strip()
        if re.match(r"^\s*[\d,]{2,}", text) and len(text) < 140:
            proof_points.append(text)
        if len(proof_points) >= 3:
            break

    # Locale hints
    locales = set()
    for q in quotes:
        url = (q.get("url") or "").lower()
        for code in ["/he/", "/es/", "/fr/", "/de/", "/it/", "/pt/", "/ru/", "/zh/", "/ja/", "/ar/"]:
            if code in url:
                locales.add(code.strip("/").upper())

    # Competitive wedge phrases
    wedge_phrases = []
    for phrase in ["no platform", "without the", "unlike", "replace", "alternative to", "instead of"]:
        m = re.search(r"([^.]*\b" + re.escape(phrase) + r"\b[^.]*)", combined_text, re.IGNORECASE)
        if m:
            wedge_phrases.append(m.group(1).strip()[:160])
    wedge_phrases = list(dict.fromkeys(wedge_phrases))[:2]

    return {
        "positioning": (positioning or {}).get("quote"),
        "value_prop": (value_prop or {}).get("quote"),
        "headline_hook": (h2 or {}).get("quote"),
        "messaging_pillars": pillars,
        "icp": icp,
        "price_anchors": price_anchors,
        "proof_points": proof_points,
        "locales": sorted(locales),
        "wedge_phrases": wedge_phrases,
        "evidence_count": len(quotes),
    }


@app.route('/checkout')
def checkout_page():
    return send_from_directory(app.static_folder, 'checkout.html')

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_static(path):
    # If the file exists in web/ serve it, otherwise SPA fallback
    full_path = os.path.join(app.static_folder, path) if path else ""
    if path and os.path.isfile(full_path):
        return send_from_directory(app.static_folder, path)
    return app.send_static_file('index.html')

@app.errorhandler(404)
def not_found(e):
    if request.path.startswith('/api/'):
        return jsonify({"error": "Resource not found", "path": request.path}), 404
    return app.send_static_file('index.html')

@app.errorhandler(400)
def bad_request(e):
    return jsonify({"error": "Bad request", "detail": str(e)}), 400

@app.errorhandler(500)
def server_error(e):
    logger.error("Internal Server Error: %s", e)
    return jsonify({"error": "Internal server error"}), 500


@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        "status": "ok",
        "service": "business-spy",
        "time": utc_now_iso(),
        "paypal_configured": bool(os.getenv("PAYPAL_CLIENT_ID")),
        "gemini_source": os.getenv("WAYBACK_GEMINI_SOURCE", "local"),
        "jobs_in_memory": len(JOBS),
    })


@app.route('/api/config', methods=['GET'])
def api_config():
    return jsonify({
        "brand": os.getenv("APP_BRAND_NAME", "slopradar"),
    })

@app.route('/api/demo', methods=['POST'])
def start_demo():
    data = apply_startup_preset(request.get_json(silent=True) or {})
    logger.info(f"Demo request data: {data}")
    target_url = normalize_target_url(data.get('target_url'))
    if not target_url:
        return jsonify({"error": "Target URL required"}), 400

    # Link to authenticated user if available
    email = data.get('email') or 'demo@founder.com'
    sprint_context = build_sprint_context(data, target_url)

    # Extract overrides for forensic intelligence
    from_date = data.get("from_date")
    to_date = data.get("to_date")
    video_engine_url = data.get("video_engine_url")
    paypal_order_id = data.get("paypal_order_id")  # For testing super tier
    logger.info(f"PayPal order ID extracted: {paypal_order_id}")

    # Capture acquisition signals (from frontend body or HTTP headers)
    referrer = data.get('referrer') or request.headers.get('Referer') or None
    utm_source = data.get('utm_source') or None
    utm_medium = data.get('utm_medium') or None
    utm_campaign = data.get('utm_campaign') or None
    user_agent = request.headers.get('User-Agent') or None

    job_id = str(uuid.uuid4())
    JOBS[job_id] = {
        "id": job_id,
        "email": email,
        "status": "processing",
        "stage": "queued",
        "status_detail": "Archival Initialization",
        "target_url": target_url,
        "type": "demo",
        "referrer": referrer,
        "utm_source": utm_source,
        "utm_medium": utm_medium,
        "utm_campaign": utm_campaign,
        "user_agent": user_agent,
        "competitors_total": 0,
        "competitors_completed": 0,
        "snapshots_total": 0,
        "snapshots_completed": 0,
        "created_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
        "startup_name": sprint_context.get("startup_name"),
        "preset_id": sprint_context.get("preset_id"),
        "selection_mode": sprint_context.get("selection_mode"),
        "sprint_context": sprint_context,
        "from_date": from_date,
        "to_date": to_date,
        "video_engine_url": video_engine_url,
        "paypal_order_id": paypal_order_id,  # For testing super tier
        "is_paid": is_unlimited(email),  # unlimited users get full report immediately
    }

    # Initial Sync to Database
    try:
        db.upsert_job(job_id, email, JOBS[job_id])
    except Exception as e:
        logger.warning(f"Initial job persistence failed for {job_id}: {e}")

    # Run logic in background
    thread = threading.Thread(target=run_demo_pipeline, args=(job_id,), daemon=True)
    thread.start()

    return jsonify({"url": f"/api/status?job_id={job_id}", "job_id": job_id})


@app.route('/api/signal', methods=['POST'])
def start_signal():
    data = apply_startup_preset(request.get_json(silent=True) or {})
    target_url = normalize_target_url(data.get('target_url'))
    if not target_url:
        return jsonify({"error": "Target URL required"}), 400

    # Link to authenticated user if available
    email = data.get('email') or 'demo@founder.com'
    sprint_context = build_sprint_context(data, target_url)

    # Capture acquisition signals
    referrer = data.get('referrer') or request.headers.get('Referer') or None
    utm_source = data.get('utm_source') or None
    utm_medium = data.get('utm_medium') or None
    utm_campaign = data.get('utm_campaign') or None
    user_agent = request.headers.get('User-Agent') or None

    job_id = str(uuid.uuid4())
    JOBS[job_id] = {
        "id": job_id,
        "email": email,
        "status": "processing",
        "stage": "queued",
        "status_detail": "Outreach Brief Initialization",
        "target_url": target_url,
        "type": "signal",
        "referrer": referrer,
        "utm_source": utm_source,
        "utm_medium": utm_medium,
        "utm_campaign": utm_campaign,
        "user_agent": user_agent,
        "competitors_total": 1,  # Only the target
        "competitors_completed": 0,
        "snapshots_total": 0,
        "snapshots_completed": 0,
        "created_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
        "startup_name": sprint_context.get("startup_name"),
        "preset_id": sprint_context.get("preset_id"),
        "selection_mode": sprint_context.get("selection_mode"),
        "sprint_context": sprint_context,
        "is_paid": is_unlimited(email),  # unlimited users get full brief immediately
    }

    # Initial Sync to Database
    try:
        db.upsert_job(job_id, email, JOBS[job_id])
    except Exception as e:
        logger.warning(f"Initial job persistence failed for {job_id}: {e}")

    # Run logic in background
    thread = threading.Thread(target=run_signal_pipeline, args=(job_id,), daemon=True)
    thread.start()

    return jsonify({"url": f"/api/status?job_id={job_id}", "job_id": job_id})


@app.route('/api/me', methods=['GET'])
def get_me():
    """Return tier info for an authenticated email. Used by dashboard for UI gating."""
    email = (request.args.get('email') or '').strip().lower()
    if not email:
        return jsonify({"error": "email required"}), 400
    if is_unlimited(email):
        tier = "unlimited"
    else:
        try:
            user = db.get_user(email)
            tier = "paid" if user and user.get('is_paid') else "free"
        except Exception:
            tier = "free"
    return jsonify({"email": email, "tier": tier})


@app.route('/api/user/reports', methods=['GET'])
def get_user_reports():
    email = request.args.get('email')
    if not email:
        return jsonify({"error": "Email required"}), 400

    results = db.get_user_forensics(email)

    # For unlimited users, mark all historical reports as paid so the
    # dashboard shows full-access badges without re-purchasing.
    if is_unlimited(email):
        for row in results:
            row['status'] = row.get('status') or 'captured'

    return jsonify({"reports": results})


@app.route('/api/startup-presets', methods=['GET'])
def startup_presets():
    return jsonify({
        "presets": list_startup_presets(),
    })


# --- AGENT REPORT CONTRACT (bizspy.report.agent.v1) ---
# Stable JSON endpoint any IDE agent with project access can fetch.
# Premium fields are redacted when is_paid=false (matches HTML report gating).

def _slug_for_target(target_url: str) -> str:
    norm = normalize_target_url(target_url)
    return re.sub(r"[^a-z0-9]+", "-", norm.lower()).strip("-") if norm else ""


@app.route('/api/agent/<slug>', methods=['GET'])
def get_agent_report(slug):
    """Return the report.agent.json for a given slug.

    Query params:
      mode=share|full|redacted  (default: return stored file as-is)
      format=md                 (return markdown instead of JSON)
    """
    safe_slug = re.sub(r"[^a-zA-Z0-9_-]+", "", slug)
    if not safe_slug:
        return jsonify({"error": "invalid slug"}), 400

    fmt = request.args.get('format', 'json')
    mode = request.args.get('mode', '')

    path = os.path.join(OUTPUT_DIR, safe_slug, "report.agent.json")
    if not os.path.isfile(path):
        return jsonify({
            "error": "report not found",
            "slug": safe_slug,
            "hint": "Run POST /api/demo {target_url} first, then poll /api/status_api/<job_id> until status=completed.",
        }), 404
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as exc:
        logger.error("Failed to read agent report %s: %s", path, exc)
        return jsonify({"error": "failed to load report"}), 500

    # If a specific redaction mode is requested, re-apply on the fly
    if mode in ('share', 'free') and data.get('is_paid'):
        payload_path = os.path.join(OUTPUT_DIR, safe_slug, "render-payload.json")
        if os.path.isfile(payload_path):
            try:
                with open(payload_path, 'r', encoding='utf-8') as f:
                    payload = json.load(f)
                from src.report_generator import ReportGenerator
                reporter = ReportGenerator()
                tmp_path = f"{safe_slug}/_tmp_mode_{mode}.json"
                reporter.generate_agent_report(
                    tmp_path,
                    target_url=payload.get('target_url', ''),
                    niche_name=payload.get('niche_name', ''),
                    competitors=payload.get('competitors', []),
                    is_paid=False,
                    redaction_mode=mode,
                    niche_narrative=payload.get('niche_narrative', ''),
                    key_findings=payload.get('key_findings', []),
                    roi_analysis=payload.get('roi_analysis', {}),
                    agent_tasks=payload.get('agent_tasks', []),
                    video_script=payload.get('video_script', {}),
                    competitor_source=payload.get('competitor_source', ''),
                )
                tmp_full = os.path.join(OUTPUT_DIR, tmp_path)
                if os.path.isfile(tmp_full):
                    with open(tmp_full, 'r', encoding='utf-8') as f:
                        data = json.load(f)
            except Exception as exc:
                logger.warning("Mode re-render failed for %s: %s", safe_slug, exc)

    if fmt == 'md':
        from jinja2 import Environment, FileSystemLoader
        md_env = Environment(loader=FileSystemLoader(template_dir))
        try:
            md = md_env.get_template('agent_report.md.j2').render(**data)
            return md, 200, {"Content-Type": "text/markdown; charset=utf-8"}
        except Exception as exc:
            logger.error("MD render failed for %s: %s", safe_slug, exc)
            return ("# Agent Report: " + safe_slug + "\n\nMarkdown template unavailable."), 200, {"Content-Type": "text/markdown; charset=utf-8"}

    return jsonify(data)


@app.route('/api/agent/resolve', methods=['POST'])
def resolve_agent_report():
    data = request.get_json(silent=True) or {}
    target_url = normalize_target_url(data.get('target_url'))
    if not target_url:
        return jsonify({"error": "target_url required"}), 400
    candidates = [
        f"report-{_slug_for_target(target_url)}",
        f"free-report-{_slug_for_target(target_url)}",
        _slug_for_target(target_url),
    ]
    for slug in candidates:
        if not slug:
            continue
        path = os.path.join(OUTPUT_DIR, slug, "report.agent.json")
        if os.path.isfile(path):
            return jsonify({
                "slug": slug,
                "agent_report_url": f"/reports/{slug}/report.agent.json",
                "api_url": f"/api/agent/{slug}",
            })
    return jsonify({"error": "no report found for target", "target_url": target_url, "tried": candidates}), 404


@app.route('/api/admin/unlock', methods=['POST'])
def admin_unlock():
    """Force a paid re-render for a given target_url. Requires X-Admin-Token
    header matching ADMIN_UNLOCK_TOKEN env. Used for QA and manual support."""
    expected = os.getenv("ADMIN_UNLOCK_TOKEN", "")
    provided = request.headers.get("X-Admin-Token", "")
    if not expected or provided != expected:
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    target_url = normalize_target_url(data.get('target_url'))
    order_id = data.get('order_id') or f"admin-{uuid.uuid4()}"
    if not target_url:
        return jsonify({"error": "target_url required"}), 400
    ok = fulfill_order(order_id, target_url)
    if not ok:
        return jsonify({"error": "no render-payload.json or data.json found for slug", "target_url": target_url}), 404
    slug = re.sub(r"[^a-z0-9]+", "-", target_url.lower()).strip("-")
    return jsonify({
        "ok": True,
        "report_url": f"/reports/{slug}/report.html",
        "agent_report_url": f"/reports/{slug}/report.agent.json",
    })


@app.route('/api/admin/grant_unlimited', methods=['POST'])
def grant_unlimited():
    """Grant unlimited tier to an email. Requires X-Admin-Token header."""
    expected = os.getenv("ADMIN_UNLOCK_TOKEN", "")
    provided = request.headers.get("X-Admin-Token", "")
    if not expected or provided != expected:
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    if not email:
        return jsonify({"error": "email required"}), 400
    db.upgrade_user_tier(email, "unlimited")
    logger.info("Granted unlimited tier to %s", email)
    return jsonify({"ok": True, "email": email, "tier": "unlimited"})


@app.route('/api/admin/jobs', methods=['GET'])
def admin_list_jobs():
    """Return recent forensic_jobs for ops/analytics. Requires X-Admin-Token header."""
    expected = os.getenv("ADMIN_UNLOCK_TOKEN", "")
    provided = request.headers.get("X-Admin-Token", "")
    if not expected or provided != expected:
        return jsonify({"error": "unauthorized"}), 401
    try:
        limit = min(int(request.args.get('limit', 200)), 1000)
    except (ValueError, TypeError):
        limit = 200
    jobs = db.list_jobs(limit)
    # Summary stats
    total = len(jobs)
    by_status = {}
    by_type = {}
    distinct_targets = set()
    for j in jobs:
        s = j.get('status') or 'unknown'
        by_status[s] = by_status.get(s, 0) + 1
        t = j.get('job_type') or j.get('type') or 'demo'
        by_type[t] = by_type.get(t, 0) + 1
        if j.get('target_url'):
            distinct_targets.add(j['target_url'])
    return jsonify({
        "total": total,
        "distinct_targets": len(distinct_targets),
        "by_status": by_status,
        "by_type": by_type,
        "jobs": jobs,
    })


@app.route('/api/admin/qa_set_job_state', methods=['POST'])
def admin_qa_set_job_state():
    """QA-only: Set an in-memory job state (or update DB fallback).

    Requires `X-Admin-Token` header to match `ADMIN_UNLOCK_TOKEN` env var.
    Payload: { job_id, status?, stage_label?, progress_percent?, super_bulk_status?, trigger_bulk?: bool }
    If `trigger_bulk` is true and the job has a super-tier order, this will spawn the
    `_execute_super_bulk_mining` background thread (safe for QA).
    """
    expected = os.getenv("ADMIN_UNLOCK_TOKEN", "")
    provided = request.headers.get("X-Admin-Token", "")
    if not expected or provided != expected:
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    job_id = data.get('job_id')
    if not job_id:
        return jsonify({"error": "job_id required"}), 400

    # Fields we accept
    new_status = data.get('status')
    new_stage = data.get('stage_label')
    new_progress = data.get('progress_percent')
    new_super = data.get('super_bulk_status')
    trigger_bulk = bool(data.get('trigger_bulk', False))

    job = JOBS.get(job_id)
    updated = False

    if job:
        if new_status is not None:
            job['status'] = new_status
        if new_stage is not None:
            job['stage_label'] = new_stage
        if new_progress is not None:
            try:
                job['progress_percent'] = int(new_progress)
            except Exception:
                job['progress_percent'] = 0
        if new_super is not None:
            job['super_bulk_status'] = new_super
        job['updated_at'] = utc_now_iso()
        updated = True
    else:
        # Fallback: update persistent DB row if job not present in-memory
        fields = []
        params = []
        if new_status is not None:
            fields.append('status = ?')
            params.append(new_status)
        if new_stage is not None:
            fields.append('stage_label = ?')
            params.append(new_stage)
        if new_progress is not None:
            fields.append('progress = ?')
            params.append(int(new_progress))
        if not fields:
            return jsonify({"error": "job not in memory and no update fields provided"}), 400
        params.append(utc_now_iso())
        params.append(job_id)
        set_clause = ", ".join(fields) + ", updated_at = ?"
        sql = f"UPDATE forensic_jobs SET {set_clause} WHERE id = ?"
        try:
            db.execute(sql, tuple(params))
        except Exception as e:
            logger.error("QA set job DB update failed: %s", e)
            return jsonify({"error": "db update failed", "detail": str(e)}), 500
        # pull row into memory for return
        row = db.fetch_one('SELECT * FROM forensic_jobs WHERE id = ?', (job_id,))
        if row:
            JOBS[job_id] = row
            job = JOBS[job_id]
            updated = True

    if not updated:
        return jsonify({"error": "job not found"}), 404

    # Optionally trigger super bulk mining thread (QA only)
    if job.get('status') == 'completed' and trigger_bulk:
        order_id = job.get('paypal_order_id')
        if order_id:
            order = db.get_order(order_id)
            if order and is_super_paid(order):
                try:
                    threading.Thread(
                        target=_execute_super_bulk_mining,
                        args=(job_id, order, job.get('startup_name') or job.get('target_url', ''), job.get('competitor_source', 'ai')),
                        daemon=True,
                    ).start()
                except Exception as e:
                    logger.error("Failed to spawn QA bulk thread: %s", e)

    return jsonify({"ok": True, "job": job})


@app.route('/api/public/reports', methods=['GET'])
def list_public_reports():
    """Return slugs for completed reports with a public-demo.html file.
    Used at Netlify build time to populate sitemap.xml."""
    results = []
    if os.path.isdir(OUTPUT_DIR):
        for slug in sorted(os.listdir(OUTPUT_DIR)):
            slug_dir = os.path.join(OUTPUT_DIR, slug)
            if not os.path.isdir(slug_dir):
                continue
            # Only expose slugs that have a public HTML or render-payload
            if os.path.isfile(os.path.join(slug_dir, "public-demo.html")) or \
               os.path.isfile(os.path.join(slug_dir, "render-payload.json")):
                results.append({"slug": slug})
    return jsonify(results)


@app.route('/api/share/<slug>', methods=['POST'])
def mint_share_link(slug):
    """Mint a 30-day HMAC share token for a given report slug."""
    safe_slug = re.sub(r"[^a-zA-Z0-9_-]+", "", slug)
    if not safe_slug:
        return jsonify({"error": "invalid slug"}), 400
    if not os.path.isfile(os.path.join(OUTPUT_DIR, safe_slug, "render-payload.json")):
        return jsonify({"error": "report not found"}), 404
    expiry = int(time.time()) + 30 * 86400
    token = _make_share_token(safe_slug, expiry)
    base = request.url_root.rstrip('/')
    share_url = f"{base}/api/share/{safe_slug}/view?token={token}"
    return jsonify({"share_url": share_url, "expires_in_days": 30})


@app.route('/api/share/<slug>/view', methods=['GET'])
def view_share(slug):
    """Validate a share token and render the report with share-mode (light) redaction."""
    safe_slug = re.sub(r"[^a-zA-Z0-9_-]+", "", slug)
    token = request.args.get('token', '')
    if not safe_slug or not _verify_share_token(safe_slug, token):
        return render_template('status.html',
            job_id='', initial_state=json.dumps({"status": "error", "error": "Invalid or expired share link."})
        ), 403
    payload_path = os.path.join(OUTPUT_DIR, safe_slug, "render-payload.json")
    if not os.path.isfile(payload_path):
        return "Report data not found", 404
    with open(payload_path, 'r', encoding='utf-8') as f:
        payload = json.load(f)
    from src.report_generator import ReportGenerator
    reporter = ReportGenerator()
    share_rel = f"{safe_slug}/share.html"
    reporter.generate(
        payload["niche_name"],
        payload["competitors"],
        share_rel,
        niche_narrative=payload.get("niche_narrative", ""),
        key_findings=payload.get("key_findings", []),
        roi_analysis=payload.get("roi_analysis", {}),
        agent_tasks=payload.get("agent_tasks", []),
        video_script=payload.get("video_script", {}),
        is_paid=False,
        is_share_preview=True,
    )
    share_fs_path = os.path.join(OUTPUT_DIR, share_rel)
    if not os.path.isfile(share_fs_path):
        return "Share render failed", 500
    with open(share_fs_path, 'r', encoding='utf-8') as f:
        html = f.read()
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route('/api/status', methods=['GET'])
def check_status_page():
    job_id = request.args.get('job_id')
    job = JOBS.get(job_id)
    if not job:
        return "Invalid Job", 404

    return render_template(
        'status.html',
        job_id=job_id,
        initial_state=json.dumps(build_status_response(job)),
    )

@app.route('/api/status_api/<job_id>', methods=['GET'])
def check_status_api(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "Not found"}), 404
    return jsonify(build_status_response(job))

@app.route('/api/approval/<job_id>', methods=['POST'])
def update_approval_state(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "Not found"}), 404

    # If job is still processing, allow partial status updates but block final completion
    is_processing = job.get("status") in ("processing", "analyzing")

    decision = request.get_json(silent=True) or {}

    # Handle matrix approvals
    job["approval_matrix"] = {
        "mining": decision.get("mining_approved", False),
        "narrative": decision.get("narrative_approved", False),
        "handoff": decision.get("handoff_approved", False),
        "dispatch": decision.get("dispatch_approved", False),
    }

    # Logic: Only set status to 'approved' if all matrix items are true AND job is completed
    all_matrix_approved = all(job["approval_matrix"].values())

    if all_matrix_approved:
        if is_processing:
            # We record the matrix state but don't mark as 'approved' yet
            job["approval_status"] = "pending_final_completion"
        else:
            job["approval_status"] = "approved"
    else:
        job["approval_status"] = "partially_reviewed"

    job["operator_note"] = decision.get("operator_note")
    job["updated_at"] = utc_now_iso()

    # If an approval_state artifact exists, try to sync it (best effort)
    approval_url = job.get("approval_state_url")
    if approval_url:
        try:
            approval_path = resolve_output_path(approval_url)
            if os.path.isfile(approval_path):
                with open(approval_path, 'r', encoding='utf-8') as f:
                    approval_state = json.load(f)

                # Update underlying state
                approval_state.update({
                    "matrix": job["approval_matrix"],
                    "status": job["approval_status"],
                    "updated_at": job["updated_at"]
                })

                with open(approval_path, 'w', encoding='utf-8') as f:
                    json.dump(approval_state, f, indent=2, default=str)
        except Exception as e:
            logger.warning("Failed to sync approval state artifact: %s", e)

    return jsonify({
        'job_id': job_id,
        'status': job["status"],
        'approval_status': job["approval_status"],
        'approval_matrix': job["approval_matrix"],
    })

@app.route('/api/paypal-config', methods=['GET'])
def paypal_config():
    return jsonify({
        'client_id': os.getenv('PAYPAL_CLIENT_ID', ''),
        'mode': os.getenv('PAYPAL_MODE', 'sandbox'),
        'currency': 'USD',
        'packages': PACKAGES,
    })


@app.route('/api/paypal/create-order', methods=['POST'])
def paypal_create_order():
    import requests as http_requests

    data = request.get_json(silent=True) or {}
    package_id = data.get('packageId', 'starter')
    email = (data.get('email') or '').strip()

    pkg = PACKAGES.get(package_id)
    if not pkg:
        return jsonify({'error': 'Invalid package'}), 400
    if not email:
        return jsonify({'error': 'Email required'}), 400

    client_id = os.getenv('PAYPAL_CLIENT_ID', '')
    client_secret = os.getenv('PAYPAL_CLIENT_SECRET', '')
    mode = os.getenv('PAYPAL_MODE', 'sandbox')
    api_base = 'https://api-m.paypal.com' if mode == 'live' else 'https://api-m.sandbox.paypal.com'

    if not client_id or not client_secret:
        return jsonify({'error': 'Payment not configured'}), 503

    # Get access token
    try:
        token_resp = http_requests.post(
            f'{api_base}/v1/oauth2/token',
            auth=(client_id, client_secret),
            data={'grant_type': 'client_credentials'},
            headers={'Accept': 'application/json'},
            timeout=15,
        )
        token_resp.raise_for_status()
        access_token = token_resp.json()['access_token']
    except Exception as exc:
        logger.error('PayPal token request failed: %s', exc)
        return jsonify({'error': 'Payment service unavailable'}), 503

    # Create order
    order_data = {
        'intent': 'CAPTURE',
        'application_context': {
            'shipping_preference': 'NO_SHIPPING',
            'user_action': 'PAY_NOW',
        },
        'purchase_units': [{
            'description': f'Business Spy - {pkg["name"]}',
            'amount': {
                'currency_code': 'USD',
                'value': f'{pkg["price"]:.2f}',
            },
        }],
    }

    try:
        order_resp = http_requests.post(
            f'{api_base}/v2/checkout/orders',
            headers={
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
            },
            json=order_data,
            timeout=15,
        )
        order_resp.raise_for_status()
        result = order_resp.json()
    except Exception as exc:
        logger.error('PayPal create-order failed: %s', exc)
        return jsonify({'error': 'Failed to create payment'}), 502

    paypal_order_id = result.get('id', '')

    # Record order in DB
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute(
            'INSERT OR IGNORE INTO orders (paypal_order_id, email, package, amount, status, target_url, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
            (paypal_order_id, email, package_id, pkg['price'], 'created', data.get('targetUrl', ''), utc_now_iso()),
        )

    return jsonify({
        'id': paypal_order_id,
        'amount': pkg['price'],
        'status': result.get('status', 'CREATED'),
    })


@app.route('/api/paypal/capture', methods=['POST'])
def paypal_capture():
    import requests as http_requests

    data = request.get_json(silent=True) or {}
    order_id = data.get('orderId', '')
    if not order_id:
        return jsonify({'error': 'orderId required'}), 400

    client_id = os.getenv('PAYPAL_CLIENT_ID', '')
    client_secret = os.getenv('PAYPAL_CLIENT_SECRET', '')
    mode = os.getenv('PAYPAL_MODE', 'sandbox')
    api_base = 'https://api-m.paypal.com' if mode == 'live' else 'https://api-m.sandbox.paypal.com'

    # Get access token
    try:
        token_resp = http_requests.post(
            f'{api_base}/v1/oauth2/token',
            auth=(client_id, client_secret),
            data={'grant_type': 'client_credentials'},
            headers={'Accept': 'application/json'},
            timeout=15,
        )
        token_resp.raise_for_status()
        access_token = token_resp.json()['access_token']
    except Exception as exc:
        logger.error('PayPal token for capture failed: %s', exc)
        return jsonify({'error': 'Payment service unavailable'}), 503

    # Capture payment
    try:
        capture_resp = http_requests.post(
            f'{api_base}/v2/checkout/orders/{order_id}/capture',
            headers={
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
            },
            timeout=15,
        )
        capture_resp.raise_for_status()
        result = capture_resp.json()
    except Exception as exc:
        logger.error('PayPal capture failed: %s', exc)
        return jsonify({'error': 'Payment capture failed'}), 502

    status = result.get('status', '')
    capture_id = ''
    captures = (result.get('purchase_units') or [{}])[0].get('payments', {}).get('captures', [])
    if captures:
        capture_id = captures[0].get('id', '')

    if status != 'COMPLETED':
        return jsonify({'error': f'Unexpected status: {status}', 'status': status}), 400

    # Update DB using high-level methods
    db.capture_order(order_id, status='captured', capture_id=capture_id, captured_at=utc_now_iso())

    order = db.fetch_one('SELECT email, target_url FROM orders WHERE paypal_order_id = ?', (order_id,))
    if order:
        email = order['email']
        target_url = order['target_url']
        existing_user = db.get_user(email)
        if existing_user:
            db.update_user_paid_status(email, is_paid=True)
        else:
            db.create_user(email, str(uuid.uuid4()), is_paid=True)

    # Trigger report fulfillment (unlock full version)
    fulfill_order(order_id, target_url)

    # Fetch updated report URL from DB if available
    order_updated = db.fetch_one('SELECT report_file FROM orders WHERE paypal_order_id = ?', (order_id,))
    report_url = f"/reports/{order_updated['report_file']}" if order_updated and order_updated['report_file'] else "/"

    # Send confirmation email with full report link to the buyer
    if order and email_engine.enabled:
        try:
            base_url = os.getenv('APP_PUBLIC_DOMAIN', 'https://bizspy.netlify.app')
            full_report_url = f"{base_url}{report_url}"
            email_engine.send_report_ready(order['email'], order['target_url'] or 'your scan', full_report_url)
        except Exception as email_exc:
            logger.warning('paypal_capture: buyer email failed: %s', email_exc)

    return jsonify({
        'success': True,
        'capture_id': capture_id,
        'status': 'COMPLETED',
        'report_url': report_url
    })

@app.route('/api/orders/confirm', methods=['POST'])
def confirm_order_manual():
    """Manual confirmation for E2E testing bypass."""
    data = request.get_json(silent=True) or {}
    order_id = data.get('orderId')
    target_url = data.get('targetUrl')

    if not order_id:
        return jsonify({"error": "orderId required"}), 400

    db.capture_order(order_id, status='captured', captured_at=utc_now_iso())
    fulfill_order(order_id, target_url)

    # Fetch updated report URL
    order_updated = db.fetch_one('SELECT report_file FROM orders WHERE paypal_order_id = ?', (order_id,))
    report_url = f"/reports/{order_updated['report_file']}" if order_updated and order_updated['report_file'] else "/"

    return jsonify({
        "success": True,
        "message": "Order confirmed manually (Mock)",
        "report_url": report_url
    })

def fulfill_order(paypal_order_id, target_url):
    """
    Unlock the full report for a paid order.
    Attempts to re-render the existing demo scan with full data.
    """
    logger.info(f"Fulfilling order {paypal_order_id} for {target_url}")

    # Check if we have an active job or an existing data.json for this URL
    # Slugify to find directory
    slug = re.sub(r"[^a-z0-9]+", "-", (target_url or "").lower()).strip("-")
    render_path = os.path.join(OUTPUT_DIR, slug, "render-payload.json")
    data_path = os.path.join(OUTPUT_DIR, slug, "data.json")
    source_path = render_path if os.path.exists(render_path) else data_path

    if os.path.exists(source_path):
        try:
            with open(source_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            from src.report_generator import ReportGenerator
            reporter = ReportGenerator()

            # Extract variables from stored data
            niche_name = data.get("niche_name") or f"Report: {target_url}"
            competitors = data.get("competitors") or []
            niche_narrative = data.get("niche_narrative") or ""
            key_findings = data.get("key_findings") or []
            roi_analysis = data.get("roi_analysis") or {}
            agent_tasks = data.get("agent_tasks") or []
            video_script = data.get("video_script") or {}

            # Render FULL report (overwrite or new path)
            report_rel = f"{slug}/report.html"
            reporter.generate(
                niche_name, competitors, report_rel,
                niche_narrative=niche_narrative,
                key_findings=key_findings,
                roi_analysis=roi_analysis,
                agent_tasks=agent_tasks,
                video_script=video_script,
                is_paid=True
            )

            # Re-emit the agent-readable JSON uncensored so any IDE agent
            # fetching /reports/<slug>/report.agent.json now sees full content.
            agent_rel = f"{slug}/report.agent.json"
            try:
                reporter.generate_agent_report(
                    agent_rel,
                    target_url=target_url or data.get("target_url", ""),
                    niche_name=niche_name,
                    competitors=competitors,
                    is_paid=True,
                    niche_narrative=niche_narrative,
                    key_findings=key_findings,
                    roi_analysis=roi_analysis,
                    agent_tasks=agent_tasks,
                    video_script=video_script,
                    sprint_manifest=data.get("sprint_manifest") or {},
                    leadideal_preview=data.get("leadideal_preview") or {},
                    approval_state=data.get("approval_state") or {},
                    related_links={
                        "html": f"/reports/{report_rel}",
                        "raw_data": f"/reports/{slug}/data.json",
                        "self": f"/reports/{agent_rel}",
                    },
                    competitor_source=data.get("competitor_source", ""),
                )
            except Exception as agent_exc:
                logger.warning("fulfill_order: agent JSON regen failed: %s", agent_exc)

            db.update_order_report(paypal_order_id, report_rel)

            # Also update any active job in memory
            for j in JOBS.values():
                if j.get('target_url') == target_url:
                    j['is_paid'] = True
                    j['report_url'] = f"/reports/{report_rel}"
                    j['agent_report_url'] = f"/reports/{agent_rel}"
                    j['stage_label'] = "Full Report Unlocked"

            logger.info(f"Successfully fulfilled premium report for {target_url}")
            return True
        except Exception as e:
            logger.error(f"Failed to fulfill report re-rendering: {e}")

    return False


def run_demo_pipeline(job_id, unlocked_count=None, max_snapshots=None):
    job = JOBS[job_id]
    target_url = job['target_url']
    sprint_context = job.get('sprint_context') or {}

    unlocked_limit = unlocked_count if unlocked_count is not None else DEMO_UNLOCKED_COMPETITORS
    snapshots_limit = max_snapshots if max_snapshots is not None else DEMO_MAX_SNAPSHOTS

    try:
        update_job(
            job_id,
            stage='discovering_competitors',
            status_detail=f'Finding competitors for {target_url}.',
            started_at=utc_now_iso(),
        )
        narrator = StrategicNarrator()
        seeded_competitors = sprint_context.get("seeded_competitors") or []
        wedge = sprint_context.get("wedge") or None
        if seeded_competitors:
            all_competitors = list(seeded_competitors)
            competitor_source = 'seeded'
        else:
            # 1. AI discovers competitors automatically
            all_competitors = [c for c in narrator.find_competitors(target_url, wedge=wedge) if c and c != target_url]
            if not all_competitors:
                all_competitors = narrator.get_fallback_competitors(target_url, wedge=wedge)
                competitor_source = 'fallback'
            else:
                competitor_source = narrator.discovery_source

        if not all_competitors:
            all_competitors = narrator.get_fallback_competitors(target_url, wedge=wedge)
            competitor_source = 'fallback'

        unlocked_competitors = all_competitors[:unlocked_limit]
        locked_competitors = all_competitors[unlocked_limit:]
        urls = build_demo_urls(target_url, unlocked_competitors)

        niche_name = f"Report: {target_url}" if unlocked_limit > DEMO_UNLOCKED_COMPETITORS else f"Free Report: {target_url}"
        update_job(
            job_id,
            status_detail=f"Found {len(all_competitors)} relevant competitors using {competitor_source.replace('_', ' ')} discovery.",
            competitor_source=competitor_source,
            narrator_enabled=narrator.enabled and competitor_source != 'fallback' and DEMO_ENABLE_NARRATIVE,
            narrator_backend=narrator.backend,
            gemini_source=narrator.env_source,
            discovered_competitors=all_competitors,
            competitors_total=len(urls),
            competitors_completed=0,
            unlocked_competitors=len(unlocked_competitors),
            locked_competitors_count=len(locked_competitors),
            seeded_competitors=seeded_competitors,
        )

        pipeline = Pipeline(
            max_snapshots_per_url=snapshots_limit,
            enable_narrative=DEMO_ENABLE_NARRATIVE,
            analyze_live_target=True,
        )

        # Override video engine if provided
        video_engine_url = job.get("video_engine_url") or os.getenv("VIDEO_ENGINE_URL")
        if video_engine_url:
            pipeline.reporter.video_engine_url = video_engine_url

        if competitor_source == 'fallback':
            pipeline.narrator.enabled = False
        is_paid_user = False
        email = job.get("email")
        if email:
            if is_unlimited(email):
                is_paid_user = True
            else:
                user = db.get_user(email)
                if user and user['is_paid']:
                    is_paid_user = True

        # If it's a demo run, use the job's is_paid override if available, else check DB
        final_is_paid = job.get("is_paid", is_paid_user)

        result = pipeline.process_niche(
            niche_name,
            urls,
            from_date=job.get("from_date") or "20180101",
            to_date=job.get("to_date"),
            output_path=os.path.join(OUTPUT_DIR, "placeholder.html"), # Directory arg handling fix
            status_callback=lambda payload: update_job(
                job_id,
                status='processing',
                **payload,
            ),
            is_public=False, # We use the is_paid flag for internal gating now
            is_paid=final_is_paid,
            sprint_context=sprint_context,
            locked_competitors=locked_competitors,
            competitor_source=competitor_source,
        )

        # storage.save() returns a URL like "/reports/<slug>/report.html" while
        # the file is written under OUTPUT_DIR/<slug>/report.html. Normalise both.
        def _to_fs(path):
            if not path:
                return ""
            if path.startswith("/reports/"):
                return os.path.join(OUTPUT_DIR, path[len("/reports/"):])
            if os.path.isabs(path):
                return path
            return os.path.join(OUTPUT_DIR, path)

        html_fs = _to_fs(result['html'])
        if not os.path.isfile(html_fs):
            raise FileNotFoundError(f"Report file was not written: {result['html']} (fs={html_fs})")

        def get_rel(abs_path):
            fs = _to_fs(abs_path)
            return os.path.relpath(fs, OUTPUT_DIR) if fs else ""

        report_rel = get_rel(result['html'])
        public_rel = get_rel(result.get('public_html') or result.get('public_demo'))
        json_rel = get_rel(result['json'])
        manifest_rel = get_rel(result['manifest'])
        brief_rel = get_rel(result['brief'])
        handoff_rel = get_rel(result['leadideal_handoff'])
        preview_rel = get_rel(result['leadideal_preview'])
        approval_rel = get_rel(result['approval_state'])
        agent_report_rel = get_rel(result.get('agent_report'))

        update_job(
            job_id,
            status='completed',
            stage='report_ready',
            status_detail='Report generated successfully.',
            report_url=f"/reports/{report_rel}",
            report_file=report_rel,
            data_url=f"/reports/{json_rel}",
            manifest_url=f"/reports/{manifest_rel}",
            brief_url=f"/reports/{brief_rel}",
            leadideal_handoff_url=f"/reports/{handoff_rel}",
            leadideal_preview_url=f"/reports/{preview_rel}",
            leadideal_preview_status=result.get('leadideal_preview_status'),
            approval_state_url=f"/reports/{approval_rel}",
            approval_status=result.get('approval_status'),
            agent_report_url=f"/reports/{agent_report_rel}" if agent_report_rel else "",
            competitor_source=competitor_source,
            competitors_completed=len(urls),
            finished_at=utc_now_iso(),
        )

        # Phase D: Pipeline hook - spawn super bulk mining thread for super tier
        order_id = job.get("paypal_order_id")
        if order_id:
            order = db.get_order(order_id)
            if order and is_super_paid(order):
                logger.info(f"🚀 Spawning super bulk mining thread for order {order_id}")
                threading.Thread(
                    target=_execute_super_bulk_mining,
                    args=(job_id, order, niche_name, competitor_source),
                    daemon=True
                ).start()

        # Sync back to DB if this was a paid order
        order_id = job.get("paypal_order_id")
        if order_id:
            db.update_order_report(order_id, report_rel, public_report_file=public_rel)

        # Trigger email notification if email exists
        user_email = job.get("email")
        base_url = os.getenv("APP_PUBLIC_DOMAIN", "https://slopradar.netlify.app")
        public_path = public_rel if public_rel.startswith('/') else '/' + public_rel
        outreach_url = f"{base_url}/reports{public_path}"
        if user_email and email_engine.enabled:
            email_engine.send_report_ready(user_email, niche_name, outreach_url)
        # Always notify admin (lead capture)
        email_engine.send_admin_lead(user_email or "", job.get("target_url", ""), outreach_url, mode="demo")

        logger.info("Pipeline job %s completed successfully", job_id)

    except Exception as e:
        import traceback
        logger.error(f"💥 CRITICAL: run_demo_pipeline {job_id} failed: {e}")
        traceback.print_exc()
        try:
            update_job(
                job_id,
                status='failed',
                stage='failed',
                status_detail=f'Pipeline execution failed: {str(e)}',
                error=str(e),
                finished_at=utc_now_iso(),
            )
        except Exception as update_err:
            logger.error(f"Failed to update job status to 'failed': {update_err}")


def run_signal_pipeline(job_id):
    job = JOBS[job_id]
    target_url = job['target_url']
    sprint_context = job.get('sprint_context') or {}

    try:
        update_job(
            job_id,
            stage='analyzing_target',
            status_detail=f'Crawling prospect website for {target_url}.',
            started_at=utc_now_iso(),
        )

        urls = build_demo_urls(target_url, [])  # Only target, no competitors
        niche_name = f"Outreach Brief: {target_url}"

        pipeline = Pipeline(
            max_snapshots_per_url=DEMO_MAX_SNAPSHOTS,
            enable_narrative=DEMO_ENABLE_NARRATIVE,
            analyze_live_target=True,
        )

        is_paid_user = False
        email = job.get("email")
        if email:
            if is_unlimited(email):
                is_paid_user = True
            else:
                user = db.get_user(email)
                if user and user['is_paid']:
                    is_paid_user = True

        # If it's a signal run, use the job's is_paid override if available, else check DB
        final_is_paid = job.get("is_paid", is_paid_user)

        result = pipeline.process_niche(
            niche_name,
            urls,
            from_date=job.get("from_date") or "20180101",
            to_date=job.get("to_date"),
            output_path=os.path.join(OUTPUT_DIR, "placeholder.json"),  # Directory arg handling fix
            status_callback=lambda payload: update_job(
                job_id,
                status='processing',
                **payload,
            ),
            is_public=False,
            is_paid=final_is_paid,
            sprint_context=sprint_context,
            mode="signal",  # Enable signal mode
        )

        # storage.save() returns a URL like "/reports/<slug>/report.signal.json"
        def _to_fs(path):
            if not path:
                return ""
            if path.startswith("/reports/"):
                return os.path.join(OUTPUT_DIR, path[len("/reports/"):])
            if os.path.isabs(path):
                return path
            return os.path.join(OUTPUT_DIR, path)

        signal_json_fs = _to_fs(result['signal_json'])
        if not os.path.isfile(signal_json_fs):
            raise FileNotFoundError(f"Signal report file was not written: {result['signal_json']} (fs={signal_json_fs})")

        def get_rel(abs_path):
            fs = _to_fs(abs_path)
            return os.path.relpath(fs, OUTPUT_DIR) if fs else ""

        signal_rel = get_rel(result['signal_json'])
        brief_slug = os.path.dirname(signal_rel)
        brief_url = f"/brief/{brief_slug}"

        update_job(
            job_id,
            status='completed',
            stage='brief_ready',
            status_detail='Outreach brief generated successfully.',
            signal_url=f"/reports/{signal_rel}",
            signal_file=signal_rel,
            report_url=brief_url,
            finished_at=utc_now_iso(),
        )

        # Phase D: Pipeline hook - spawn super bulk mining thread for super tier
        order_id = job.get("paypal_order_id")
        if order_id:
            order = db.get_order(order_id)
            if order and is_super_paid(order):
                logger.info(f"🚀 Spawning super bulk mining thread for order {order_id}")
                threading.Thread(
                    target=_execute_super_bulk_mining,
                    args=(job_id, order, niche_name, "signal"),
                    daemon=True
                ).start()

        # Send completion email
        job_snapshot = JOBS.get(job_id, {})
        user_email = job_snapshot.get("email", "")
        target_url = job_snapshot.get("target_url", "")
        base_url = os.getenv("APP_PUBLIC_DOMAIN", "https://slopradar.netlify.app")
        full_brief_url = f"{base_url}{brief_url}"
        if user_email and user_email != "demo@founder.com":
            email_engine.send_report_ready(user_email, target_url, full_brief_url)
        # Always notify admin (lead capture)
        email_engine.send_admin_lead(user_email, target_url, full_brief_url, mode="signal")

        logger.info("Signal pipeline job %s completed successfully", job_id)

    except Exception as e:
        import traceback
        logger.error(f"💥 CRITICAL: run_signal_pipeline {job_id} failed: {e}")
        traceback.print_exc()
        try:
            update_job(
                job_id,
                status='failed',
                stage='failed',
                status_detail=f'Pipeline execution failed: {str(e)}',
                error=str(e),
                finished_at=utc_now_iso(),
            )
        except Exception as update_err:
            logger.error(f"Failed to update job status to 'failed': {update_err}")


@app.route('/api/orders', methods=['POST'])
def confirm_order():
    data = request.get_json(silent=True) or {}
    order_id = data.get('orderId', '')
    if not order_id:
        return jsonify({'error': 'orderId required'}), 400

    # Verify order exists and is captured
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute('SELECT * FROM orders WHERE paypal_order_id = ?', (order_id,)).fetchone()

    if not row:
        return jsonify({'error': 'Order not found'}), 404
    if row['status'] != 'captured':
        return jsonify({'error': f'Order not captured (status: {row["status"]})'}), 400

    # Mark completed and link report if target_url provided
    target_url = (data.get('targetUrl') or row['target_url'] or '').strip()
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute(
            'UPDATE orders SET status = ?, target_url = ? WHERE paypal_order_id = ?',
            ('completed', target_url, order_id),
        )

    # TRIGGER FULFILLMENT if target_url exists
    job_id = None
    if target_url:
        normalized = normalize_target_url(target_url)
        pkg_id = row['package']
        pkg_config = PACKAGES.get(pkg_id, PACKAGES['starter'])

        job_id = str(uuid.uuid4())
        JOBS[job_id] = {
            "status": "processing",
            "stage": "queued",
            "target_url": normalized,
            "type": "paid",
            "package_id": pkg_id,
            "paypal_order_id": order_id,
            "created_at": utc_now_iso(),
            "updated_at": utc_now_iso(),
        }

        thread = threading.Thread(
            target=run_demo_pipeline,
            args=(job_id, pkg_config['competitors'], pkg_config.get('history_months', 6)),
            daemon=True
        )
        thread.start()

    return jsonify({
        'success': True,
        'order_id': order_id,
        'package': row['package'],
        'email': row['email'],
        'job_id': job_id,
        'status_url': f"/api/status?job_id={job_id}" if job_id else None
    })


def _execute_super_bulk_mining(job_id: str, order: dict, niche_name: str, competitor_source: str):
    """Execute bulk mining for super tier orders in background thread.

    Called after pipeline completion for super tier orders.
    Mines 20 ICP leads and sends delivery email.
    """
    try:
        logger.info(f"🔍 Starting super bulk mining for job {job_id}, order {order.get('paypal_order_id')}")

        # Extract industry from the niche name or target URL
        target_url = order.get('target_url', '')
        industry = _infer_industry_from_niche(niche_name, target_url)

        if not industry:
            logger.warning(f"Could not infer industry for super bulk mining: niche='{niche_name}', url='{target_url}'")
            return

        # Execute bulk mining via LeadIdeal bridge
        from src.leadideal_bridge import execute_leadideal_bulk

        bulk_result = execute_leadideal_bulk(
            industry=industry,
            location="United States",  # Default to US for now
            timeout=120  # Longer timeout for bulk mining
        )

        if bulk_result.get('status') == 'completed':
            leads_count = bulk_result.get('results', {}).get('leads_mined', 0)
            qa_pass_rate = bulk_result.get('results', {}).get('qa_results', {}).get('pass_rate', 0)

            logger.info(f"✅ Super bulk mining completed: {leads_count} leads, QA pass rate {qa_pass_rate:.1f}%")

            # Send delivery email with bulk results
            user_email = order.get('email')
            if user_email:
                _send_super_bulk_delivered_email(
                    user_email=user_email,
                    customer_name=order.get('customer_name', 'Customer'),
                    niche_name=niche_name,
                    bulk_results=bulk_result,
                    competitor_source=competitor_source
                )

            # Update order with bulk mining completion
            order_id = order.get('paypal_order_id')
            if order_id:
                db.capture_order(order_id, status='super_bulk_completed')

        else:
            logger.error(f"❌ Super bulk mining failed: {bulk_result.get('error')}")
            # Could send failure notification here

    except Exception as e:
        logger.error(f"💥 Super bulk mining thread failed: {e}")
        import traceback
        traceback.print_exc()


def _infer_industry_from_niche(niche_name: str, target_url: str) -> str:
    """Infer industry from niche name or target URL for bulk mining."""
    # Simple heuristics - could be enhanced with AI
    niche_lower = niche_name.lower()
    url_lower = target_url.lower()

    # Check for common industry keywords
    industries = {
        'dental': ['dental', 'dentist', 'dentistry', 'teeth', 'oral'],
        'medical': ['medical', 'healthcare', 'clinic', 'doctor', 'hospital'],
        'legal': ['law', 'legal', 'attorney', 'lawyer', 'firm'],
        'finance': ['finance', 'financial', 'bank', 'investment', 'wealth'],
        'real estate': ['real estate', 'property', 'realtor', 'homes'],
        'ecommerce': ['ecommerce', 'shop', 'store', 'retail', 'commerce'],
        'saas': ['saas', 'software', 'app', 'platform', 'tool'],
        'consulting': ['consulting', 'consultant', 'advisory', 'advisor'],
        'marketing': ['marketing', 'agency', 'advertising', 'promo'],
        'fitness': ['fitness', 'gym', 'health', 'workout', 'training'],
    }

    for industry, keywords in industries.items():
        if any(kw in niche_lower or kw in url_lower for kw in keywords):
            return industry

    # Default fallback
    return 'technology'


def _send_super_bulk_delivered_email(user_email: str, customer_name: str, niche_name: str,
                                   bulk_results: dict, competitor_source: str):
    """Send email notification that super bulk mining is complete."""
    try:
        subject = f"Your Super Tier Report + 20 ICP Prospects is Ready"

        results = bulk_results.get('results', {})
        leads_count = results.get('leads_mined', 0)
        qa_results = results.get('qa_results', {})
        pass_rate = qa_results.get('pass_rate', 0)

        body = f"""Hi {customer_name},

Your Super Tier SlopRadar report for "{niche_name}" has been enhanced with bulk prospect mining!

🎯 **Competitor Analysis Complete**
- Discovery method: {competitor_source.replace('_', ' ')}
- Analysis: Wayback Machine + AI-powered insights

⛏️ **Bulk Prospect Mining Complete**
- Industry: {bulk_results.get('request', {}).get('industry', 'N/A')}
- Leads mined: {leads_count}
- Quality pass rate: {pass_rate:.1f}%

Your report now includes:
✅ Full competitor intelligence report
✅ 20 high-quality ICP prospects
✅ QA-verified lead data
✅ Sample outreach email templates

Access your enhanced report at: [Report Link]

The prospect data is ready for your outreach campaigns!

Best,
SlopRadar Team
"""

        email_engine.send_custom_email(
            to_email=user_email,
            subject=subject,
            body=body
        )

        logger.info(f"📧 Sent super bulk delivery email to {user_email}")

    except Exception as e:
        logger.error(f"Failed to send super bulk delivery email: {e}")


if __name__ == '__main__':
    port = int(os.getenv('PORT', '8889'))
    debug = os.getenv('FLASK_DEBUG', '').lower() in {'1', 'true', 'yes'}
    app.run(port=port, debug=debug, use_reloader=debug)
