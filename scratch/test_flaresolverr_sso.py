import requests
import json

FLARESOLVERR_URL = "http://192.168.1.176:8191/v1"

print("1. Requesting FlareSolverr clearance for familyinfocenter...")
resp1 = requests.post(FLARESOLVERR_URL, json={
    "cmd": "request.get",
    "url": "https://familyinfocenter.brighthorizons.com/okta/login",
    "maxTimeout": 60000
}, timeout=65).json()

print("FlareSolverr status 1:", resp1.get("status"))
cookies1 = resp1.get("solution", {}).get("cookies", [])
print(f"Received {len(cookies1)} cookies from FlareSolverr step 1.")
for c in cookies1:
    print(f"  Cookie: {c['name']} = {c['value'][:15]}... domain={c['domain']}")

print("\n2. Requesting FlareSolverr clearance for bhloginsso.brighthorizons.com...")
resp2 = requests.post(FLARESOLVERR_URL, json={
    "cmd": "request.get",
    "url": "https://bhloginsso.brighthorizons.com",
    "maxTimeout": 60000
}, timeout=65).json()

print("FlareSolverr status 2:", resp2.get("status"))
cookies2 = resp2.get("solution", {}).get("cookies", [])
print(f"Received {len(cookies2)} cookies from FlareSolverr step 2.")
for c in cookies2:
    print(f"  Cookie: {c['name']} = {c['value'][:15]}... domain={c['domain']}")
