#!/usr/bin/env python3
"""
Z-TRACS Road Intelligence Platform — CV AI Team Alert Sender Script

Ultra-clean & lightweight alert sender for the Computer Vision (CV) AI team.
- ZERO external dependencies (uses standard Python urllib.request).
- NO username, NO password, NO auth token required.
- NO 404 errors (automatically uses or registers target inspection_id).
- Supports sending defect/asset EVIDENCE IMAGES (Base64 string or URL).

Usage:
  python scripts/send_cv_alert.py --tag pothole --type damage
  python scripts/send_cv_alert.py --tag "traffic light" --type asset --lat 18.9850 --long 73.1100 --image-base64 "data:image/jpeg;base64,..."
"""

import argparse
import json
import urllib.request
import urllib.error
import sys

def send_alert(
    api_base: str = "http://127.0.0.1:8000",
    tag: str = "pothole",
    alert_type: str = "damage",
    video: bool = True,
    rtsp: bool = False,
    lat: float = None,
    long: float = None,
    image_base64: str = None,
    image_url: str = None,
    inspection_id: str = "DEMO-001"
):
    url = f"{api_base.rstrip('/')}/api/cv/alert"
    payload = {
        "inspection_id": inspection_id,
        "video": video,
        "rtsp": rtsp,
        "type": alert_type,
        "tag": tag,
        "lat": lat,
        "long": long
    }
    
    if image_base64:
        payload["image_base64"] = image_base64
    elif image_url:
        payload["image_url"] = image_url

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            print(f"✅ Alert sent successfully!")
            print(json.dumps(result, indent=2))
            return result
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        print(f"❌ Error sending alert ({e.code}): {err_body}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"❌ Connection error to {url}: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Z-TRACS CV Alert Sender")
    parser.add_argument("--api-base", default="http://127.0.0.1:8000", help="Z-TRACS API Base URL")
    parser.add_argument("--tag", default="pothole", help="Alert tag (e.g. pothole, cracks, traffic light)")
    parser.add_argument("--type", default="damage", choices=["damage", "asset"], help="Alert type (damage or asset)")
    parser.add_argument("--video", action="store_true", default=True, help="Source is video file")
    parser.add_argument("--rtsp", action="store_true", default=False, help="Source is live RTSP stream")
    parser.add_argument("--lat", type=float, default=None, help="Latitude (optional)")
    parser.add_argument("--long", type=float, default=None, help="Longitude (optional)")
    parser.add_argument("--image-base64", default=None, help="Base64 encoded JPEG image frame (optional)")
    parser.add_argument("--image-url", default=None, help="Evidence image URL (optional)")
    parser.add_argument("--inspection-id", default="DEMO-001", help="Target inspection survey ID")
    
    args = parser.parse_args()
    send_alert(
        api_base=args.api_base,
        tag=args.tag,
        alert_type=args.type,
        video=args.video,
        rtsp=args.rtsp,
        lat=args.lat,
        long=args.long,
        image_base64=args.image_base64,
        image_url=args.image_url,
        inspection_id=getattr(args, "inspection_id", "DEMO-001")
    )
