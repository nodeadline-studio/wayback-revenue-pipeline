#!/usr/bin/env python3
"""Run a reproducible Startup Intel preset against the local app."""

import argparse
import json
import sys

from smoke_demo import http_json, poll_job


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a startup preset and print generated artifact URLs.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8889", help="Base URL for the local app")
    parser.add_argument("--preset-id", required=True, help="Startup preset id exposed by /api/startup-presets")
    parser.add_argument("--target-url", help="Optional target_url override")
    parser.add_argument("--timeout", type=int, default=240, help="Polling timeout in seconds")
    parser.add_argument("--interval", type=float, default=3.0, help="Polling interval in seconds")
    parser.add_argument(
        "--payload-json",
        help="Optional JSON object string merged into the /api/demo payload after preset selection",
    )
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    payload = {"preset_id": args.preset_id}
    if args.target_url:
        payload["target_url"] = args.target_url
    if args.payload_json:
        try:
            payload.update(json.loads(args.payload_json))
        except json.JSONDecodeError as exc:
            print(f"Invalid --payload-json: {exc}", file=sys.stderr)
            return 1

    try:
        _, start_payload = http_json(f"{base_url}/api/demo", method="POST", payload=payload)
        job_id = start_payload["job_id"]
        print(json.dumps({"job_id": job_id, "status_url": start_payload["url"], "preset_id": args.preset_id}, indent=2))

        final_payload = poll_job(base_url, job_id, args.timeout, args.interval)
        if final_payload.get("status") != "completed":
            print(json.dumps(final_payload, indent=2))
            return 1

        print(json.dumps({
            "job_id": job_id,
            "preset_id": args.preset_id,
            "status": final_payload.get("status"),
            "stage": final_payload.get("stage"),
            "report_url": final_payload.get("report_url"),
            "data_url": final_payload.get("data_url"),
            "manifest_url": final_payload.get("manifest_url"),
            "brief_url": final_payload.get("brief_url"),
            "leadideal_handoff_url": final_payload.get("leadideal_handoff_url"),
            "leadideal_preview_url": final_payload.get("leadideal_preview_url"),
            "leadideal_preview_status": final_payload.get("leadideal_preview_status"),
            "approval_state_url": final_payload.get("approval_state_url"),
            "approval_status": final_payload.get("approval_status"),
        }, indent=2))
        return 0
    except Exception as exc:
        print(f"Preset run failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())