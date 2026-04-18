# Wayback Revenue Pipeline

Local Flask demo for generating competitive-intelligence reports from Wayback Machine snapshots.

The repo also now supports an internal Startup Intel Sprint mode for founder-controlled case studies using seeded competitors and startup metadata.

It also now includes built-in startup presets and a generated LeadIdeal handoff artifact.

It now also executes LeadIdeal preview and saves the preview response as an artifact.

## Local Run

1. Copy `.env.example` to `.env` if you want Gemini or custom app settings.
2. Start the app:

```bash
"/Users/tommykuznets/Downloads/My Projects/.venv/bin/python" app.py
```

3. Open `http://127.0.0.1:8889/`.

The default local interface is served from port `8889`. The same Flask app serves both the landing page and generated reports under `/reports/<filename>`.

## Current Artifacts

A successful run now writes up to seven artifacts in `output/`:

- `*-report.html`: primary visual report
- `*-data.json`: raw structured analysis output
- `*-manifest.json`: Startup Intel Sprint contract for downstream systems
- `*-internal-brief.md`: operator-facing startup brief
- `*-leadideal-handoff.json`: downstream LeadIdeal preview/mining handoff contract
- `*-leadideal-preview.json`: executed LeadIdeal preview response artifact
- `*-approval-state.json`: review gate artifact that blocks dispatch until approval is recorded

## Smoke Test

Run the local end-to-end smoke test after the server is up:

```bash
"/Users/tommykuznets/Downloads/My Projects/.venv/bin/python" scripts/smoke_demo.py --target-url example.com
```

The smoke test checks:

- `/health` returns successfully.
- `POST /api/demo` returns a job id.
- `/api/status_api/<job_id>` reaches `completed`.
- The returned `/reports/...` page loads and contains the core report sections.

## Startup Intel Sprint Input

`POST /api/demo` still works with only `target_url`, but it now also accepts optional internal metadata.

For repeatable internal runs, you can start from a preset with `preset_id` and then override only the fields you need.

Current presets:
- `leadideal-en`
- `leadideal-he`
- `creatorpacks`

List them through:

```bash
curl -s http://127.0.0.1:8889/api/startup-presets
```

Useful fields:

```json
{
	"preset_id": "leadideal-en",
	"publishability": {
		"public_case_study_ready": true
	}
}
```

Notes:
- If `seeded_competitors` is present, the run uses seeded mode instead of AI discovery.
- `seeded_competitors` can be a list of plain domains or richer objects.
- Seeded mode is recommended for internal studio products and case studies.
- If `preset_id` is present, preset values are applied first and then your request body overrides them.

Preset runner:

```bash
"/Users/tommykuznets/Downloads/My Projects/.venv/bin/python" scripts/run_startup_preset.py --preset-id leadideal-en
```

Optional override example:

```bash
"/Users/tommykuznets/Downloads/My Projects/.venv/bin/python" scripts/run_startup_preset.py --preset-id creatorpacks --payload-json '{"publishability":{"public_case_study_ready":false}}'
```

## Environment Notes

- `GEMINI_API_KEY` activates live Gemini-based competitor discovery and narrative generation.
- If `wayback-revenue-pipeline` does not have its own Gemini key configured, the app now imports the Gemini credential from `video-gen-clean` env files without printing or hardcoding the secret.
- If Gemini is unavailable, the app falls back to domain-aware competitor sets instead of generic placeholder domains.
- The demo currently analyzes up to `6` representative snapshots per analyzed URL and unlocks up to `4` competitors.
- The free demo uses Gemini for competitor discovery and can generate narrative output when Gemini is available.
- Snapshot sampling is now more resilient for sparse archive histories: if digest-collapsed history is too thin, the app retries sampling from a wider uncropped archive set before selecting representative checkpoints.
- The app prefers `google-genai` and still tolerates legacy `google-generativeai` if present.
- The current SQLite file is `saas.sqlite`.
- If `stripe` is not installed, the app still runs and the local auth page remains a static placeholder.

## Troubleshooting

### Bad competitor matches

For your own products, do not rely on auto-discovery first. Pass `seeded_competitors` so the run stays high quality and reproducible.

### Run completed but only the HTML report was used

Check `output/` for the matching manifest, internal brief, LeadIdeal handoff, LeadIdeal preview, and approval-state files. Completed jobs can now expose `manifest_url`, `brief_url`, `leadideal_handoff_url`, `leadideal_preview_url`, `approval_state_url`, and `approval_status` in addition to the report URL.

### Does preview execution mean dispatch is automatic?

No. LeadIdeal preview execution is now automated, but review and dispatch are still manual.

The current safe interpretation is:
- report generation can run automatically
- LeadIdeal preview can run automatically
- approval-state artifact is generated automatically in `pending_review`
- public publication, mining escalation, outreach, and customer dispatch remain blocked until explicit approval is recorded

### How do I record an approval decision?

Use the approval update API after a job completes:

```bash
curl -sS -X POST http://127.0.0.1:8889/api/approval/<job_id> \
	-H 'Content-Type: application/json' \
	-d '{"operator_review_completed":true,"mining_escalation_approved":true,"review_notes":"Approved for mining."}'
```

Supported decision fields:
- `operator_review_completed`
- `mining_escalation_approved`
- `public_case_study_approved`
- `customer_dispatch_approved`
- `rejected`
- `review_notes`

### LeadIdeal preview target override

Preview execution defaults to the base URL from the handoff or `https://leadideal.com`.

Override options:
- set `leadideal.base_url` in the Sprint payload
- or set `LEADIDEAL_BASE_URL` in the environment

### Payment flow looks complete but does not deliver a premium report

That is expected right now. Order creation, PayPal capture, and order confirmation exist, but premium fulfillment has not been connected to report generation yet.

### Docs disagree with code

Trust code first. The repo recently moved beyond the older demo assumptions, and the current runtime truth is:
- 4 unlocked competitors
- 6 snapshots per analyzed URL
- Sprint manifest and internal brief generation are live

## Recommended Next Tasks

The most efficient next implementation steps are:

1. Decide the preview-to-mining escalation rule.
2. Public proof artifact generation from the same run.
3. Premium fulfillment only after the internal workflow is stable.

## Fixture QA

Existing report fixtures live in `output/`. To run screenshot-based UI QA against those fixtures:

```bash
node take-gallery-screenshots.js
```

This validates the existing HTML report interface separately from the live `/api/demo` processing path.
