#!/usr/bin/env python3
"""
Z-TRACS Road Intelligence Platform — Computer Vision (CV) Team Result Sender Script

This standalone Python script is designed for the CV / AI Engineering Team to send model outputs
and status updates back to the Z-TRACS Platform API. Zero external dependencies (uses standard urllib).

Supported Input Files & Payloads (Schema 1.0):
  1. ai_results.json          -> Full AI defect detections & segment metrics (POST /api/cv/ai-results)
  2. processing_status.json   -> Real-time pipeline progress updates (POST /api/cv/status-update)
  3. processing_failed.json   -> Error & failure reports (POST /api/cv/status-failed)

Usage Examples:
  # 1. Send full AI Results JSON:
  python scripts/send_cv_results.py --json ai_results.json --api-base http://127.0.0.1:8000

  # 2. Send Live Status Update:
  python scripts/send_cv_results.py --json processing_status.json --api-base http://127.0.0.1:8000

  # 3. Send Failure Report:
  python scripts/send_cv_results.py --json processing_failed.json --api-base http://127.0.0.1:8000
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error

def get_auth_token(api_base: str, username: str = "admin", password: str = "admin123") -> str:
    """Authenticate with Z-TRACS API to obtain a JWT Bearer Token."""
    login_url = f"{api_base.rstrip('/')}/api/auth/login"
    payload = json.dumps({"username": username, "password": password}).encode("utf-8")
    req = urllib.request.Request(login_url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            token = data.get("access_token")
            if not token:
                raise RuntimeError("No access_token returned in login response.")
            print(f"🔑 Authenticated as '{username}' successfully.")
            return token
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        print(f"❌ Authentication failed ({e.code}): {err_body}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"❌ Connection error to {login_url}: {e}", file=sys.stderr)
        sys.exit(1)


def send_cv_payload(api_base: str, payload: dict, token: str) -> dict:
    """
    Automatically routes and posts CV Schema 1.0 JSON payloads to Z-TRACS Backend:
    - If payload contains 'detections': routes to /api/cv/ai-results
    - If payload contains 'progress': routes to /api/cv/status-update
    - If payload contains 'error_code': routes to /api/cv/status-failed
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    inspection_id = payload.get("inspection_id")
    if not inspection_id:
        raise ValueError("Payload missing required 'inspection_id' field.")

    # Determine endpoint based on payload structure
    if "detections" in payload or "schema_version" in payload:
        endpoint = f"{api_base.rstrip('/')}/api/cv/ai-results"
        payload_type = "AI Results (Schema 1.0)"
    elif "progress" in payload or "frames_processed" in payload:
        endpoint = f"{api_base.rstrip('/')}/api/cv/status-update"
        payload_type = "Processing Status Update"
    elif "error_code" in payload or "error_message" in payload:
        endpoint = f"{api_base.rstrip('/')}/api/cv/status-failed"
        payload_type = "Processing Failure Report"
    else:
        endpoint = f"{api_base.rstrip('/')}/api/cv/ai-results"
        payload_type = "Generic AI Results"

    print(f"📤 Sending {payload_type} for Survey '{inspection_id}' -> {endpoint}...")
    req_body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(endpoint, data=req_body, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            print(f"✅ Response from Z-TRACS ({resp.status} OK):")
            print(json.dumps(result, indent=2))
            return result
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        print(f"❌ API Error ({e.code}): {err_body}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"❌ Connection error to {endpoint}: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Z-TRACS CV Team Result Sender Script")
    parser.add_argument("--json", required=True, help="Path to JSON file (ai_results.json, processing_status.json, etc.)")
    parser.add_argument("--api-base", default=os.getenv("ZTRACS_API_BASE", "http://3.109.28.196:8000"), help="Z-TRACS API Base URL (defaults to ZTRACS_API_BASE env var or http://3.109.28.196:8000)")


    parser.add_argument("--username", default="admin", help="Admin/Inspector Username")
    parser.add_argument("--password", default="admin123", help="Admin/Inspector Password")
    parser.add_argument("--token", help="JWT Token (optional, overrides username/password)")

    args = parser.parse_args()

    if not os.path.exists(args.json):
        print(f"❌ File not found: {args.json}", file=sys.stderr)
        sys.exit(1)

    with open(args.json, "r", encoding="utf-8") as f:
        payload = json.load(f)

    token = args.token or get_auth_token(args.api_base, args.username, args.password)
    send_cv_payload(args.api_base, payload, token)


if __name__ == "__main__":
    main()
