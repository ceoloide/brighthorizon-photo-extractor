import requests
import json

FLARESOLVERR_URL = "http://192.168.1.176:8191/v1"

payload = {
    "cmd": "request.get",
    "url": "https://bhloginsso.brighthorizons.com/u/login/identifier",
    "maxTimeout": 60000
}

print(f"[FlareSolverr] Sending request to {FLARESOLVERR_URL}...")
try:
    resp = requests.post(FLARESOLVERR_URL, json=payload, timeout=70)
    print(f"[FlareSolverr] Status Code: {resp.status_code}")
    data = resp.json()
    print(f"[FlareSolverr] Status: {data.get('status')}")
    solution = data.get("solution", {})
    print(f"[FlareSolverr] Cookies: {len(solution.get('cookies', []))}")
    for c in solution.get('cookies', []):
        print(f"  Cookie: {c['name']} = {c['value'][:15]}... ({c['domain']})")
except Exception as e:
    print(f"[FlareSolverr Error]: {e}")
