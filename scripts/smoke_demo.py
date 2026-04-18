#!/usr/bin/env python3
"""Local smoke test for the port 8889 demo flow."""

import argparse
import json
import sys
import time
from typing import Any, Dict, Tuple
from urllib import error, parse, request


def http_json(url: str, method: str = "GET", payload: Dict[str, Any] = None) -> Tuple[int, Dict[str, Any]]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = request.Request(url, data=data, headers=headers, method=method)
    with request.urlopen(req, timeout=20) as response:
        body = response.read().decode("utf-8")
        return response.status, json.loads(body)


def http_text(url: str) -> Tuple[int, str]:
    with request.urlopen(url, timeout=20) as response:
        return response.status, response.read().decode("utf-8")


def poll_job(base_url: str, job_id: str, timeout_seconds: int, interval_seconds: float) -> Dict[str, Any]:
    deadline = time.time() + timeout_seconds
    status_url = f"{base_url}/api/status_api/{job_id}"

    while time.time() < deadline:
        _, payload = http_json(status_url)
        status = payload.get("status")
        stage = payload.get("stage")
        detail = payload.get("status_detail")
        print(f"status={status} stage={stage} detail={detail}")

        if status in {"completed", "failed"}:
            return payload

        time.sleep(interval_seconds)

    raise TimeoutError(f"Timed out waiting for job {job_id} after {timeout_seconds} seconds")


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test the local Wayback demo flow.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8889", help="Base URL for the local app")
    parser.add_argument("--target-url", required=True, help="Domain or URL to submit to /api/demo")
    parser.add_argument("--timeout", type=int, default=180, help="Polling timeout in seconds")
    parser.add_argument("--interval", type=float, default=3.0, help="Polling interval in seconds")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")

    try:
        health_status, health_payload = http_json(f"{base_url}/health")
        print(json.dumps({"health_status": health_status, "health": health_payload}, indent=2))

        _, start_payload = http_json(
            f"{base_url}/api/demo",
            method="POST",
            payload={"target_url": args.target_url},
        )
        job_id = start_payload["job_id"]
        print(json.dumps({"job_id": job_id, "status_url": start_payload["url"]}, indent=2))

        final_payload = poll_job(base_url, job_id, args.timeout, args.interval)
        if final_payload.get("status") != "completed":
            print(json.dumps(final_payload, indent=2))
            return 1

        report_url = final_payload.get("report_url")
        if not report_url:
            print(json.dumps(final_payload, indent=2))
            raise RuntimeError("Completed job is missing report_url")

        report_status, report_html = http_text(parse.urljoin(f"{base_url}/", report_url.lstrip("/")))
        required_markers = [
            '<div class="stats-grid">',
            'Competitive Intelligence Report',
            'Competitor Evolution',
        ]
        missing_markers = [marker for marker in required_markers if marker not in report_html]
        if report_status != 200 or missing_markers:
            raise RuntimeError(
                f"Report verification failed: status={report_status}, missing_markers={missing_markers}"
            )

        print(json.dumps({
            "job_id": job_id,
            "stage": final_payload.get("stage"),
            "report_url": report_url,
            "report_file": final_payload.get("report_file"),
            "status": "passed",
        }, indent=2))
        return 0
    except error.HTTPError as exc:
        print(f"HTTP error: {exc.code} {exc.reason}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Smoke test failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())