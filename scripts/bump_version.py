#!/usr/bin/env python3
"""
Automated Version & Build Increment Script for Bright Horizons Photo Extractor.
Follows Semantic Versioning: v<MAJOR>.<MINOR>.<PATCH>-b<BUILD_NUM>
"""
import os
import json
import subprocess
from datetime import datetime, timezone

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_FILE = os.path.join(ROOT_DIR, "version.json")
FRONTEND_VERSION_FILE = os.path.join(ROOT_DIR, "frontend", "src", "version.json")
PACKAGE_JSON_FILE = os.path.join(ROOT_DIR, "frontend", "package.json")

def get_git_hash():
    try:
        res = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT_DIR)
        if res.returncode == 0:
            return res.stdout.strip()
    except Exception:
        pass
    return "dev"

def bump_version(part="build"):
    if os.path.exists(VERSION_FILE):
        with open(VERSION_FILE, "r") as f:
            data = json.load(f)
    else:
        data = {"version": "2.1.0", "build": 0, "gitHash": "dev"}

    version_str = data.get("version", "2.1.0")
    build_num = data.get("build", 0) + 1
    git_hash = get_git_hash()
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if part in ["major", "minor", "patch"]:
        parts = [int(x) for x in version_str.split(".")]
        if part == "major":
            parts[0] += 1
            parts[1] = 0
            parts[2] = 0
        elif part == "minor":
            parts[1] += 1
            parts[2] = 0
        elif part == "patch":
            parts[2] += 1
        version_str = f"{parts[0]}.{parts[1]}.{parts[2]}"

    updated_data = {
        "version": version_str,
        "build": build_num,
        "gitHash": git_hash,
        "buildTime": now_iso
    }

    # Write root version.json
    with open(VERSION_FILE, "w") as f:
        json.dump(updated_data, f, indent=2)

    # Write frontend/src/version.json
    with open(FRONTEND_VERSION_FILE, "w") as f:
        json.dump(updated_data, f, indent=2)

    # Update frontend/package.json version field
    if os.path.exists(PACKAGE_JSON_FILE):
        try:
            with open(PACKAGE_JSON_FILE, "r") as f:
                pkg_data = json.load(f)
            pkg_data["version"] = version_str
            with open(PACKAGE_JSON_FILE, "w") as f:
                json.dump(pkg_data, f, indent=2)
        except Exception as e:
            print(f"Notice updating package.json: {e}")

    print(f"Successfully bumped version: v{version_str}-b{build_num} ({git_hash})")
    return updated_data

if __name__ == "__main__":
    import sys
    part = sys.argv[1] if len(sys.argv) > 1 else "build"
    bump_version(part)
