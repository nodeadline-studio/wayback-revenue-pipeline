
import os
import json
import sys

# Add src to path
sys.path.append(os.getcwd())

from src.report_generator import ReportGenerator

def verify():
    print("--- MVP Monetization Verification ---")
    
    # 1. Load existing data
    data_path = "output/free-report-glossier-com-data.json"
    if not os.path.exists(data_path):
        print(f"Error: {data_path} not found")
        return

    with open(data_path, 'r') as f:
        data = json.load(f)

    generator = ReportGenerator()
    
    # 2. Render FREE (Redacted) Report
    print("Rendering FREE report...")
    free_filename = "verify-redacted-report.html"
    generator.generate(
        niche_name="Glossier (Redacted Test)",
        competitors=data['competitors'],
        output_path=free_filename,
        is_paid=False,
        agent_tasks=[{"task": "Verify funnel extraction", "owner": "CrawlAgent"}]
    )
    
    # 3. Render PAID (Unlocked) Report
    print("Rendering PAID report...")
    paid_filename = "verify-unlocked-report.html"
    generator.generate(
        niche_name="Glossier (Unlocked Test)",
        competitors=data['competitors'],
        output_path=paid_filename,
        is_paid=True,
        agent_tasks=[{"task": "Verify funnel extraction", "owner": "CrawlAgent"}]
    )

    # 4. Verification Check
    print("\nVerifying Redaction...")
    free_path = os.path.join("output", free_filename)
    with open(free_path, 'r') as f:
        free_content = f.read()
        if "[LOCKED]" in free_content:
            print("✅ SUCCESS: FREE report contains [LOCKED] tokens.")
        else:
            print("❌ FAILURE: FREE report does NOT contains [LOCKED] tokens.")

    print("Verifying Unlock...")
    paid_path = os.path.join("output", paid_filename)
    with open(paid_path, 'r') as f:
        paid_content = f.read()
        if "[LOCKED]" not in paid_content:
            print("✅ SUCCESS: PAID report does NOT contain [LOCKED] tokens.")
        else:
            print("❌ FAILURE: PAID report still contains [LOCKED] tokens.")

    # 5. Check fulfillment endpoint logic on live server
    print("\nTriggering live fulfillment via mock endpoint...")
    import requests
    try:
        resp = requests.post("http://127.0.0.1:5005/api/orders/confirm", json={
            "orderId": "VERIFY-FINAL",
            "targetUrl": "glossier.com"
        })
        if resp.status_code == 200:
            result = resp.json()
            print(f"✅ SUCCESS: Fulfillment API returned status 200. Report URL: {result.get('report_url')}")
        else:
            print(f"❌ FAILURE: Fulfillment API returned status {resp.status_code}")
    except Exception as e:
        print(f"⚠️ SKIPPED: Could not reach live server (is it running on 5000?): {e}")

if __name__ == "__main__":
    verify()
