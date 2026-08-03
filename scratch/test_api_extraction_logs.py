import os
import sys
import time
import requests
import json

def test_api_extraction_logs():
    email = "taccani.massarelli@gmail.com"
    pwd = "xxTJ8i.5J2KUkkK"
    base_url = "http://localhost:8095"

    session = requests.Session()

    print(f"\n=======================================================")
    print(f"📡 TESTING BACKEND EXTRACTION API & LOGS ({base_url})")
    print(f"=======================================================\n")

    # Step 1: Pre-verification via verify-stream SSE
    print("[1/3] Triggering verification SSE stream...")
    url = f"{base_url}/api/auth/verify-stream?email={requests.utils.quote(email)}&password={requests.utils.quote(pwd)}"
    
    token = None
    res = session.get(url, stream=True)
    for line in res.iter_lines():
        if line:
            line_str = line.decode('utf-8')
            if line_str.startswith("data: "):
                try:
                    data = json.loads(line_str[6:])
                    print(f"  [SSE Event] Step {data.get('step_index')}: {data.get('step')} | Status: {data.get('status')}")
                    if data.get("status") == "success":
                        token = data.get("token")
                        print(f"🎉 Verification SUCCESS! Token obtained: {token[:25]}...")
                        break
                except Exception as e:
                    print(f"Error parsing SSE line: {e}")

    if not token:
        print("❌ Verification stream failed to return token.")
        return

    # Set Auth header
    headers = {"Authorization": f"Bearer {token}"}

    # Step 2: Start extraction job
    print("\n[2/3] Starting background extraction job...")
    start_resp = session.post(f"{base_url}/api/extraction/start", json={"mode": "INCREMENTAL"}, headers=headers)
    print(f"Start Job Response: HTTP {start_resp.status_code} | {start_resp.text}")

    # Step 3: Poll status and stream logs for 60 seconds
    print("\n[3/3] Polling /api/extraction/status logs...")
    seen_logs = set()
    start_t = time.time()

    for _ in range(35):
        time.sleep(2.0)
        elapsed = round(time.time() - start_t, 1)

        st_resp = session.get(f"{base_url}/api/extraction/status", headers=headers)
        if st_resp.status_code == 200:
            st_data = st_resp.json()
            state = st_data.get("state")
            logs = st_data.get("logs", [])

            for log_line in logs:
                if log_line not in seen_logs:
                    seen_logs.add(log_line)
                    print(f"[{elapsed}s] {log_line}")

            if state in ["completed", "failed"]:
                print(f"\nJob reached final state: '{state}' after {elapsed}s.")
                break

if __name__ == "__main__":
    test_api_extraction_logs()
