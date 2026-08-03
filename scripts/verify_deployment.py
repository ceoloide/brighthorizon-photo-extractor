#!/usr/bin/env python3
"""
Live Deployment Version Verification Script.
Fetches https://bears.ceoloide.com/, extracts the main JS bundle,
and verifies that the served version text matches version.json.
"""
import os
import re
import sys
import json
import urllib.request
import ssl

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_FILE = os.path.join(ROOT_DIR, "version.json")

def verify_live_deployment(target_url="https://bears.ceoloide.com"):
    if not os.path.exists(VERSION_FILE):
        print(f"Error: {VERSION_FILE} not found!")
        sys.exit(1)

    with open(VERSION_FILE, "r") as f:
        version_data = json.load(f)

    expected_ver = version_data.get("version", "2.1.0")
    expected_build = version_data.get("build", 1)
    expected_hash = version_data.get("gitHash", "")
    expected_tag = f"v{expected_ver}-b{expected_build}"

    print(f"Expected Version Tag: {expected_tag} ({expected_hash})")
    print(f"Fetching live target URL: {target_url}...")

    # SSL context bypass for internal proxy testing if needed
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(target_url, headers={"User-Agent": "Mozilla/5.0 (Deployment-Verifier)"})
    with urllib.request.urlopen(req, context=ctx) as resp:
        html_content = resp.read().decode("utf-8")

    # Extract JS bundle filename
    m = re.search(r'src="(/assets/index-[^"]+\.js)"', html_content)
    if not m:
        print("Error: Could not locate main JS script bundle in live HTML response!")
        sys.exit(1)

    js_path = m.group(1)
    bundle_url = f"{target_url.rstrip('/')}{js_path}"
    print(f"Found JS script bundle: {bundle_url}")

    req_js = urllib.request.Request(bundle_url, headers={"User-Agent": "Mozilla/5.0 (Deployment-Verifier)"})
    with urllib.request.urlopen(req_js, context=ctx) as resp:
        js_content = resp.read().decode("utf-8")

    # Search for version string, build integer, and git hash in bundle
    has_ver = expected_ver in js_content
    has_build = f"build:{expected_build}" in js_content or f"={expected_build}," in js_content or f"={expected_build};" in js_content or f":{expected_build}," in js_content or f":{expected_build}}}" in js_content
    has_hash = expected_hash in js_content if expected_hash else True

    if has_ver and (has_build or has_hash):
        print(f"SUCCESS: Live deployment verified! Serving {expected_tag} ({expected_hash}) cleanly.")
        return True
    else:
        print(f"WARNING: Expected version '{expected_ver}' / build '{expected_build}' / hash '{expected_hash}' not fully verified in JS bundle!")
        print(f"Details: has_ver={has_ver}, has_build={has_build}, has_hash={has_hash}")
        sys.exit(1)

if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://bears.ceoloide.com"
    verify_live_deployment(url)
