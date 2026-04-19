# Wayback Revenue Pipeline - Project Context

**Last Updated**: 2026-04-19
**Status**: Local Flask demo working. **New**: Automated Forensic Handoff to LeadIdeal integrated (2026-04-19).

## LeadIdeal Forensic Signal Handoff (2026-04-19)

- **Automated Intelligence Extraction**: Updated `startup_intel.py` to extract forensic outreach hooks (the "Why Now" signal) from niche-wide narratives and competitor insights.
- **Signal-Aware Handoff**: The `leadideal-handoff.json` artifact now includes `forensic_context` and a dynamic `bizspy_report_url`.
- **Transmission Bridge**: Updated the LeadIdeal bridge to proactively transmit forensic signals during the preview step, enabling high-intent outreach tagging in the recipient's CRM.

## What This Repo Is

Wayback Revenue Pipeline is a historical competitor-intelligence app that pulls archived snapshots, extracts structured signals, and renders HTML and JSON reports. It now also supports an internal Startup Intel Sprint workflow for founder-controlled case studies and startup playbooks.

Current intended uses:
- public-facing free demo and paid report scaffolding
- internal startup optimization for studio products
- public proof assets and case studies built from internal runs

## Current State

Phase 1 of Startup Intel Sprint is complete.

Phase 2 has partially started.

What exists now:
- free demo flow from landing page to async report generation
- optional Gemini-based competitor discovery with fallback discovery
- seeded competitor mode for founder-controlled case studies
- generated HTML report, raw JSON report, Sprint manifest JSON, and internal brief markdown
- generated LeadIdeal handoff JSON from the Sprint manifest
- generated LeadIdeal preview artifact from the handoff
- generated approval-state artifact that blocks dispatch until human review is recorded
- reusable preset startup runs for LeadIdeal EN, LeadIdeal HE, and CreatorPacks
- preset runner script for reproducible internal case-study execution
- PayPal checkout scaffolding for paid reports

What is not complete yet:
- paid fulfillment does not enqueue or attach a premium report after successful payment
- LeadIdeal preview now executes from this repo, but approval and any downstream dispatch remain manual
- CreatorPacks promotion handoff is not wired into the Wayback app yet
- public case-study packaging is still a curated output pattern, not a first-class generated surface
- approval recording itself is still not implemented, so HITL is enforced as a blocking state artifact but not yet resumable in-app
- approval resume is implemented through `POST /api/approval/<job_id>`, but there is still no authenticated multi-user review workflow

## Architecture

### Core Stack
- Frontend: static HTML and vanilla JS in `web/`
- Backend: Flask app in `app.py`
- Data store: SQLite in `saas.sqlite`
- Analysis pipeline: `src/pipeline.py`, `src/page_analyzer.py`, `src/live_site_analyzer.py`, `src/narrator.py`
- Rendering: Jinja report template plus JSON and markdown artifact generation in `src/report_generator.py`
- Startup Intel helpers: `src/startup_intel.py`

### Runtime Flow
1. User or operator posts to `/api/demo` with a `target_url` and optional Sprint metadata.
	- Operators can also start from a preset using `preset_id`.
2. `app.py` creates an in-memory job and launches `run_demo_pipeline()` in a background thread.
3. Competitors are selected in one of two modes:
	 - seeded mode if `seeded_competitors` were provided
	 - discovery mode through Gemini with fallback competitor sets
4. `Pipeline.process_niche()` analyzes archive snapshots, optionally crawls the current live target, and produces seven artifacts:
	 - `*-report.html`
	 - `*-data.json`
	 - `*-manifest.json`
	 - `*-internal-brief.md`
	- `*-leadideal-handoff.json`
 	- `*-leadideal-preview.json`
	 - `*-approval-state.json`
5. Job status is available through `/api/status_api/<job_id>` and the status page served at `/api/status?job_id=...`.

## Startup Presets

Current built-in presets:
- `leadideal-en`
- `leadideal-he`
- `creatorpacks`

Preset metadata is served from `/api/startup-presets` and defined in `src/startup_presets.py`.

Preset runner:
- `scripts/run_startup_preset.py --preset-id <preset>` starts a run and prints all generated artifact URLs plus approval status.

Preset intent:
- make the first three internal case studies reproducible
- default internal runs to seeded-competitor mode
- attach downstream distribution defaults without rebuilding payloads manually

## Startup Intel Sprint

### Phase 1 Implemented

The app now accepts internal strategy metadata and can run a founder-seeded intelligence sprint.

Accepted `POST /api/demo` payload fields beyond `target_url`:
- `preset_id`
- `startup_name`
- `variant_id`
- `language`
- `geo`
- `offer`
- `audience`
- `objective`
- `message_pillars`
- `recommended_experiments`
- `publishability`
- `leadideal`
- `creatorpacks`
- `seeded_competitors`

`seeded_competitors` supports either plain domain strings or objects with:
- `domain`
- `label`
- `selection_reason`
- `similarity_score`

### Sprint Artifacts

Every Sprint-capable run can now output:
- HTML report: external-facing or operator-readable full report
- JSON report: raw competitor analysis bundle
- Sprint manifest: reusable internal contract for downstream systems
- Internal brief: markdown memo for founders and future agents
- LeadIdeal handoff: JSON payload for preview and mining follow-up
- LeadIdeal preview artifact: JSON response snapshot from a preview attempt against LeadIdeal
- Approval-state artifact: JSON gate that marks review as pending and blocks downstream dispatch

### Sprint Manifest Contents

The manifest currently stores:
- startup identity and variant metadata
- competitor selection mode and source
- summary counts for competitors, snapshots, changes, and tech tools
- message pillars and recommended experiments
- distribution placeholders for LeadIdeal and CreatorPacks
- publishability flags
- competitor-level metadata such as role, selection reason, headline, CTAs, pricing, tech stack, and AI insight

### LeadIdeal Handoff Artifact

`*-leadideal-handoff.json` is now generated from the Sprint manifest.

It currently stores:
- startup identity and variant info
- segment label
- industry, roles, locations, and optional `job_title`
- suggested next step
- one or more preview request payloads matching LeadIdeal preview expectations
- selection notes and key findings for operator context

This is the execution contract for the automated preview step.

The repo now calls LeadIdeal preview automatically, but it does not continue into mining, outreach, or dispatch automatically.

### LeadIdeal Preview Artifact

`*-leadideal-preview.json` is now generated by executing the preview request against LeadIdeal.

It currently stores:
- execution status
- LeadIdeal base URL and endpoint used
- request payloads derived from the handoff
- compact response summaries such as estimated total, DB matches, match tier, note, promo, preview count, and error
- up to three preview rows per request as a compact excerpt

This does not authorize dispatch. It is an operator-facing artifact only.

### Approval-State Artifact

`*-approval-state.json` is now generated after the preview step.

It currently stores:
- `status = pending_review`
- `dispatch_blocked = true`
- preview status summary
- publishability flags
- blocked next actions for mining escalation, public publication, and customer dispatch
- human-readable blockers and the recommended next review step

This is the current code-level HITL boundary.

### Approval Update API

`POST /api/approval/<job_id>` now updates the approval-state artifact for a completed job.

Supported decision fields:
- `operator_review_completed`
- `mining_escalation_approved`
- `public_case_study_approved`
- `customer_dispatch_approved`
- `rejected`
- `review_notes`

This route rewrites the approval artifact on disk and mirrors the updated `approval_status` back into the in-memory job record.

## Demo and Monetization State

### Free Demo
- unlocked competitors: `4`
- max snapshots per analyzed URL: `6`
- narrative generation: enabled when Gemini is available and discovery is not fallback-only
- target live crawl: enabled in the pipeline

### Paid Checkout
- packages currently exposed by `/api/paypal-config`:
	- `starter`: $49, 3 competitors, 3 months
	- `pro`: $149, 5 competitors, 48 months
- current state: create-order, capture, and order-confirmation exist, but the premium fulfillment step is still missing

## Verification Snapshot

Verified on 2026-04-17:
- new Sprint helpers import successfully from the workspace venv
- Sprint manifest generation returns `schema_version = startup-intel-v1`
- seeded competitor mode resolves correctly
- internal brief generation writes a markdown file successfully
- static analysis reported no errors in `app.py`, `src/pipeline.py`, `src/report_generator.py`, and `src/startup_intel.py`

Verified on 2026-04-18:
- preset resolution still works after user edits to `src/startup_intel.py` and `src/startup_presets.py`
- LeadIdeal handoff generation still returns `leadideal-handoff-v1`
- LeadIdeal preview execution returns `leadideal-preview-artifact-v1`
- approval-state generation returns `startup-intel-approval-v1`
- preset `leadideal.base_url` now survives through Sprint context into the handoff artifact
- preview artifact generation writes successfully to disk
- runtime note: `urllib3` emits a LibreSSL warning under the current macOS Python build, but execution still succeeds

## Troubleshooting

### If the demo returns poor competitors
- Use `seeded_competitors` instead of discovery mode for founder-controlled case studies.
- CreatorPacks and likely LeadIdeal HE should default to seeded mode until discovery quality is proven.

### If Gemini is unavailable
- The app falls back to domain-aware competitor sets.
- This keeps the run alive, but quality is lower for internal case studies. Prefer seeded mode when quality matters.

### If docs and runtime disagree
- Trust code over markdown.
- Important current truths:
	- database file is `saas.sqlite`, not `saas.db`
	- demo currently unlocks 4 competitors and 6 snapshots
	- Sprint artifacts now include manifest and internal brief outputs

### If a run completes but only the HTML report is used
- Check the generated output directory for `*-manifest.json`, `*-internal-brief.md`, `*-leadideal-handoff.json`, `*-leadideal-preview.json`, and `*-approval-state.json`.
- The status payload now also includes `data_url`, `manifest_url`, `brief_url`, `leadideal_handoff_url`, `leadideal_preview_url`, `approval_state_url`, and `approval_status` in completed jobs.

### If LeadIdeal preview succeeds
- Treat the preview artifact and approval-state artifact as the review bundle.
- Preview execution is now automated, but delivery approval is still blocked until a later approval-recording step is implemented.

### If LeadIdeal preview fails
- Check `base_url` in the handoff and preview artifact first.
- Override the LeadIdeal base URL in the Sprint payload under `leadideal.base_url` or via `LEADIDEAL_BASE_URL` when local or alternate targets are needed.

### If you want reproducible internal runs
- Use `preset_id` instead of rebuilding the full payload every time.
- Current presets live in `src/startup_presets.py`.
- Use `scripts/run_startup_preset.py` when you want a repeatable operator flow that prints the artifact bundle directly.
- Override fields in the request body only when you need a run-specific change.

### If checkout succeeds but no premium report appears
- This is a known gap, not a transient failure.
- Payment confirmation currently stops at order status updates. Premium report fulfillment has not been connected yet.

### If future agents need the best internal memo example
- Reuse the structure from `output/leadideal-hybrid-competitors-working-report.md`.
- That file is still the strongest pattern for internal case-study output.

## Recommended Next Tasks

Do these in order for the current direction:

1. Implement LeadIdeal handoff from the Sprint manifest.
- Status: preview execution is now implemented.
- Next: store approval state and decide when preview should escalate to mining.

2. Decide the preview-to-mining escalation rule.
- Status: manual approval recording now exists.
- Next: define when `approved_for_mining` should be allowed or suggested automatically.

3. Generate a public proof variant from the same run.
- Goal: emit a cleaner redacted case study artifact instead of relying on manually curated output files.

4. Wire premium fulfillment only after the three internal case studies are stable.
- Goal: attach paid reports to orders after the internal workflow is producing strong, reusable outputs.

## Operational Guidance For Next Agents

- Treat this repo as the system-of-record for analysis artifacts, not for outbound execution.
- Keep seeded-competitor mode as the default for internal studio products.
- Do not spend time polishing checkout UX before preview-to-mining rules and public proof packaging exist.
- If you are choosing between discovery quality and automation, choose quality first for the next three case studies.
