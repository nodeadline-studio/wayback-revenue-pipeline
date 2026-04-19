import importlib
import json
import logging
import os
import sqlite3
import threading
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
}


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
    return payload


def resolve_output_path(report_url: str) -> str:
    filename = os.path.basename(str(report_url or "").strip())
    return os.path.join(OUTPUT_DIR, filename)

# --- ROUTES ---
@app.route('/reports/<path:filename>')
def serve_reports(filename):
    return send_from_directory(OUTPUT_DIR, filename)

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

@app.route('/api/demo', methods=['POST'])
def start_demo():
    data = apply_startup_preset(request.get_json(silent=True) or {})
    target_url = normalize_target_url(data.get('target_url'))
    if not target_url:
        return jsonify({"error": "Target URL required"}), 400

    sprint_context = build_sprint_context(data, target_url)
    
    # Extract overrides for forensic intelligence
    from_date = data.get("from_date")
    to_date = data.get("to_date")
    video_engine_url = data.get("video_engine_url")

    job_id = str(uuid.uuid4())
    JOBS[job_id] = {
        "status": "processing",
        "stage": "queued",
        "status_detail": "Demo request accepted.",
        "target_url": target_url,
        "type": "demo",
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
    }

    # Run logic in background
    thread = threading.Thread(target=run_demo_pipeline, args=(job_id,), daemon=True)
    thread.start()

    return jsonify({"url": f"/api/status?job_id={job_id}", "job_id": job_id})


@app.route('/api/user/reports', methods=['GET'])
def get_user_reports():
    email = request.args.get('email')
    if not email:
        return jsonify({"error": "Email required"}), 400
    
    reports = db.get_user_reports(email)
    # Filter out reports without files
    valid_reports = [r for r in reports if r.get('report_file')]
    
    return jsonify({"reports": valid_reports})


@app.route('/api/startup-presets', methods=['GET'])
def startup_presets():
    return jsonify({
        "presets": list_startup_presets(),
    })

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
    
    order = db.fetch_one('SELECT email FROM orders WHERE paypal_order_id = ?', (order_id,))
    if order and order['email']:
        email = order['email']
        existing_user = db.get_user(email)
        if existing_user:
            db.update_user_paid_status(email, is_paid=True)
        else:
            db.create_user(email, str(uuid.uuid4()), is_paid=True)

    return jsonify({
        'success': True,
        'capture_id': capture_id,
        'status': status,
    })


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
        if seeded_competitors:
            all_competitors = list(seeded_competitors)
            competitor_source = 'seeded'
        else:
            # 1. AI discovers competitors automatically
            all_competitors = [c for c in narrator.find_competitors(target_url) if c and c != target_url]
            if not all_competitors:
                all_competitors = narrator.get_fallback_competitors(target_url)
                competitor_source = 'fallback'
            else:
                competitor_source = narrator.discovery_source

        if not all_competitors:
            all_competitors = narrator.get_fallback_competitors(target_url)
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
        )

        if not os.path.isfile(result['html']):
            raise FileNotFoundError(f"Report file was not written: {result['html']}")

        # Resolve relative paths from OUTPUT_DIR for nested folders
        def get_rel(abs_path):
            return os.path.relpath(abs_path, OUTPUT_DIR) if abs_path else ""

        report_rel = get_rel(result['html'])
        json_rel = get_rel(result['json'])
        manifest_rel = get_rel(result['manifest'])
        brief_rel = get_rel(result['brief'])
        handoff_rel = get_rel(result['leadideal_handoff'])
        preview_rel = get_rel(result['leadideal_preview'])
        approval_rel = get_rel(result['approval_state'])

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
            competitor_source=competitor_source,
            competitors_completed=len(urls),
            finished_at=utc_now_iso(),
        )

        # Sync back to DB if this was a paid order
        order_id = job.get("paypal_order_id")
        if order_id:
            db.update_order_report(order_id, report_rel)
        
        # Trigger email notification if email exists
        user_email = job.get("email")
        if user_email and email_engine.enabled:
            # Construct public URL for email
            base_url = os.getenv("APP_PUBLIC_DOMAIN", "https://bizspy.netlify.app")
            full_report_url = f"{base_url}{report_rel if report_rel.startswith('/') else '/' + report_rel}"
            email_engine.send_report_ready(user_email, target_url, full_report_url)

        logger.info("Pipeline job %s completed with report %s", job_id, html_file)

    except Exception as e:
        import traceback
        update_job(
            job_id,
            status='failed',
            stage='failed',
            status_detail='Pipeline execution failed.',
            error=str(e),
            finished_at=utc_now_iso(),
        )
        logger.exception("Pipeline job %s failed", job_id)
        traceback.print_exc()

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

if __name__ == '__main__':
    port = int(os.getenv('PORT', '8889'))
    debug = os.getenv('FLASK_DEBUG', '').lower() in {'1', 'true', 'yes'}
    app.run(port=port, debug=debug, use_reloader=debug)
