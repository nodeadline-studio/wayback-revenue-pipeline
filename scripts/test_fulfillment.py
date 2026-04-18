import requests
import sqlite3
import time
import os

BASE_URL = "http://127.0.0.1:8889"
DB_FILE = "saas.sqlite"

def test_fulfillment():
    print("starting fulfillment test...")
    
    order_id = "test_order_" + str(int(time.time()))
    email = "test@example.com"
    target_url = "example.com"
    package = "pro"
    
    # 1. Inject mock captured order
    print(f"injecting mock order {order_id}...")
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute(
            'INSERT INTO orders (paypal_order_id, email, package, amount, status, target_url, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
            (order_id, email, package, 149.0, 'captured', target_url, "2026-01-01T00:00:00Z"),
        )
    
    # 2. Confirm order via API
    print("confirming order via API...")
    resp = requests.post(f"{BASE_URL}/api/orders", json={
        "orderId": order_id,
        "targetUrl": target_url
    })
    
    if resp.status_code != 200:
        print(f"FAILED: status {resp.status_code}")
        print(resp.text)
        return
    
    data = resp.json()
    job_id = data.get("job_id")
    print(f"SUCCESS: Order confirmed. Job ID: {job_id}")
    
    if not job_id:
        print("FAILED: No job_id returned")
        return

    # 3. Poll for job progress
    print("polling job progress...")
    for _ in range(10):
        status_resp = requests.get(f"{BASE_URL}/api/status_api/{job_id}")
        status_data = status_resp.json()
        print(f"  Stage: {status_data.get('stage')} | Progress: {status_data.get('progress_percent')}%")
        
        if status_data.get("status") == "completed":
            print("Job COMPLETED successfully!")
            return
        if status_data.get("status") == "failed":
            print("Job FAILED!")
            print(status_data.get("error"))
            return
        
        time.sleep(5)

if __name__ == "__main__":
    test_fulfillment()
