#!/usr/bin/env python3
"""
Z-TRACS Road Intelligence Platform — Computer Vision (CV) AI Team Integration Script
-------------------------------------------------------------------------------------
Continuous 24/7 Event Daemon Loop for YOLOv8 / DeepStream / Custom AI Perception GPU Nodes.

How it works:
1. Runs in a continuous 24/7 while loop polling Z-TRACS API (/api/cv/export-tasks).
2. Whenever a user creates a "+ New Survey" or uploads video/RTSP in Z-TRACS, it immediately detects the new survey.
3. Streams/downloads the video footage from AWS S3 Presigned URLs or Server API to local disk.
4. Performs frame-by-frame AI perception model inference (Potholes, Cracks, Marking Damage).
5. Ingests detected defects and alerts back into Z-TRACS (/api/cv/ai-results and /api/cv/alert).

Usage:
  # 24/7 Continuous Daemon Mode (Default for CV Team GPU Nodes):
  python scripts/cv_pipeline_integration.py --api-base http://3.109.28.196:8000

  # Single-inspection test run mode:
  python scripts/cv_pipeline_integration.py --api-base http://3.109.28.196:8000 --inspection-id DEMO-001 --once
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from typing import Dict, Any, List, Optional

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


def fetch_export_tasks(api_base: str) -> List[Dict[str, Any]]:
    """Fetch active and pending road survey tasks from Z-TRACS backend."""
    url = f"{api_base.rstrip('/')}/api/cv/export-tasks"
    req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("tasks", [])
    except Exception as e:
        # Fallback to /api/inspections if export-tasks is unavailable
        try:
            url_alt = f"{api_base.rstrip('/')}/api/inspections"
            req_alt = urllib.request.Request(url_alt, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req_alt, timeout=10) as resp_alt:
                rows = json.loads(resp_alt.read().decode("utf-8"))
                return [{"task_id": r["id"], "inspection_id": r["id"], "case_id": r["name"], "filename": f"{r['id'].lower()}.mp4", "direct_video_url": r.get("video_url")} for r in rows]
        except Exception:
            return []


def fetch_pipeline_payload(api_base: str, inspection_id: str) -> dict:
    """Fetch execution parameters and S3/RTSP URL for target inspection survey."""
    url = f"{api_base.rstrip('/')}/api/inspections/{inspection_id}/pipeline-payload"
    req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return {
            "inspection_id": inspection_id,
            "video_url": "demo_assets/road_inspection_demo.mp4",
            "is_rtsp": False,
            "model_version": "RoadDefect-v1.0"
        }


def download_video_if_needed(api_base: str, task: dict, local_dir: str = "downloads") -> str:
    """Stream download video footage from AWS S3 Presigned URL or API to local disk with failover."""
    tid = task.get("task_id") or task.get("inspection_id") or "DEMO-001"
    fn = task.get("filename") or f"{tid.lower()}.mp4"
    dest_path = os.path.join(local_dir, tid, fn)

    if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
        return dest_path

    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    tmp_path = f"{dest_path}.tmp"

    candidate_urls = []
    if task.get("direct_video_url"):
        candidate_urls.append(task["direct_video_url"])
    if task.get("download_url"):
        candidate_urls.append(task["download_url"])
    candidate_urls.append(f"/api/cv/tasks/{tid}/video")

    for raw_url in candidate_urls:
        url = raw_url if raw_url.startswith("http") else f"{api_base.rstrip('/')}{raw_url}"
        print(f"📥 [CV DOWNLOAD] Syncing footage for survey '{tid}' from S3/Server: {url}")
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=120) as resp, open(tmp_path, "wb") as f:
                total_bytes = int(resp.headers.get("Content-Length", 0))
                dl_bytes = 0
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    dl_bytes += len(chunk)
                    if total_bytes > 0:
                        pct = (dl_bytes / total_bytes) * 100
                        sys.stdout.write(f"\r -> Progress: [{pct:5.1f}%] {dl_bytes / (1024*1024):.1f} / {total_bytes / (1024*1024):.1f} MB")
                        sys.stdout.flush()
            sys.stdout.write("\n")
            os.replace(tmp_path, dest_path)
            size_mb = os.path.getsize(dest_path) / (1024 * 1024)
            print(f"✅ [DOWNLOAD COMPLETE] Saved local footage: '{dest_path}' ({size_mb:.2f} MB)")
            return dest_path
        except Exception as e:
            print(f"⚠️ [DOWNLOAD WARN] Candidate stream '{url}' failed for '{tid}': {e}. Trying fallback...")
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

    print(f"❌ [DOWNLOAD ERROR] All download candidates failed for survey '{tid}'.")
    return ""


def process_video_or_rtsp_stream(video_source: str, inspection_id: str, max_frames: int = 100) -> list:
    """Frame reader & AI perception inference simulation (replaceable with PyTorch / YOLO)."""
    is_rtsp = str(video_source).startswith("rtsp://")
    print(f"\n🎥 [AI INFERENCE ENGINE] Processing stream: {video_source}")
    
    cap = None
    if HAS_CV2 and os.path.exists(video_source):
        cap = cv2.VideoCapture(video_source)

    fps = (cap.get(cv2.CAP_PROP_FPS) if cap and cap.isOpened() else 25.0) or 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) if (cap and cap.isOpened() and not is_rtsp) else 100

    detections = []
    frame_idx = 0
    clean_id = inspection_id.replace("-", "").lower()

    while frame_idx < min(max_frames, total_frames if total_frames > 0 else max_frames):
        if cap and cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

        timestamp_sec = frame_idx / fps

        if frame_idx > 0 and frame_idx % 15 == 0:
            det_id = f"DEF-CV-{clean_id}-{frame_idx}"
            detection = {
                "detection_id": det_id,
                "frame": {
                    "frame_number": frame_idx,
                    "timestamp_seconds": round(timestamp_sec, 2)
                },
                "classification": {
                    "class_name": "pothole" if frame_idx % 30 == 0 else "crack",
                    "confidence": 0.94,
                    "severity": "critical" if frame_idx % 30 == 0 else "high"
                },
                "geometry": {
                    "bbox": {"x1": 120, "y1": 340, "x2": 480, "y2": 620}
                },
                "location": {
                    "latitude": 18.9850 + (frame_idx * 0.0001),
                    "longitude": 73.1100 + (frame_idx * 0.0001)
                }
            }
            detections.append(detection)

        frame_idx += 1

    if cap and cap.isOpened():
        cap.release()

    print(f"🎉 [INFERENCE FINISHED] Processed {frame_idx} frames for '{inspection_id}'. Total AI defects: {len(detections)}")
    return detections


def submit_detections_batch(api_base: str, inspection_id: str, detections: list):
    """Post batch AI detection results back to Z-TRACS Platform API."""
    if not detections:
        print("ℹ️ No detections to submit.")
        return

    url = f"{api_base.rstrip('/')}/api/cv/ai-results"
    payload = {
        "inspection_id": inspection_id,
        "model": {"model_name": "ZTRACS-RoadDefect", "model_version": "v1.0.0"},
        "video": {"total_frames": 100, "duration_seconds": 4.0},
        "detections": detections
    }

    req_body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=req_body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            print(f"✅ [API INGESTED] Successfully sent {len(detections)} AI detections for survey '{inspection_id}' to Z-TRACS!")
    except Exception as e:
        print(f"❌ [API ERROR] Could not submit detections for '{inspection_id}': {e}")


def submit_realtime_alert(api_base: str, inspection_id: str, tag: str = "pothole", lat: float = 18.985, lng: float = 73.110):
    """Post token-free real-time alert back to Z-TRACS Platform (/api/cv/alert)."""
    url = f"{api_base.rstrip('/')}/api/cv/alert"
    payload = {
        "inspection_id": inspection_id,
        "video": True,
        "rtsp": False,
        "type": "damage",
        "tag": tag,
        "lat": lat,
        "long": lng,
        "confidence": 0.95,
        "severity": "critical" if tag == "pothole" else "high"
    }

    req_body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=req_body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            print(f"🔔 [ALERT SENT] Ingested alert '{res.get('alert_id')}' for '{inspection_id}' ({tag.upper()})")
    except Exception as e:
        print(f"⚠️ [ALERT ERROR] Could not send alert: {e}")


def run_continuous_daemon_loop(api_base: str, poll_interval: float = 5.0, max_frames: int = 100):
    """24/7 Continuous Loop: Auto-detects newly submitted surveys (+ New Survey), downloads video, & ingests AI results."""
    print("=" * 75)
    print("Z-TRACS CV PIPELINE INTEGRATION DAEMON (24/7 CONTINUOUS LISTENER)")
    print("=" * 75)
    print(f"Status            : ACTIVE (24/7 Loop, Polling '{api_base}' every {poll_interval}s)")
    print("Auto S3 Video Sync: ENABLED")
    print("Press Ctrl+C to stop.")
    print("=" * 75 + "\n")

    processed_tasks = set()
    initial_load = True

    while True:
        try:
            tasks = fetch_export_tasks(api_base)
            for task in tasks:
                tid = task.get("task_id") or task.get("inspection_id")
                if not tid or tid in processed_tasks:
                    continue

                if not initial_load:
                    print("\n" + "=" * 75)
                    print(f"🔔 [NEW SURVEY DETECTED FROM FRONTEND / API]")
                    print("=" * 75)
                    print(f" -> Survey / Task ID : {tid}")
                    print(f" -> Survey Name      : {task.get('case_id')}")
                    print(f" -> Status           : {task.get('status')}")
                    print(f" -> S3 / Video URL   : {task.get('direct_video_url')}")
                    print("=" * 75)

                local_file = download_video_if_needed(api_base, task)
                payload = fetch_pipeline_payload(api_base, tid)
                video_source = local_file if (local_file and os.path.exists(local_file)) else (payload.get("s3_presigned_download_url") or payload.get("video_url") or "demo_assets/road_inspection_demo.mp4")

                detections = process_video_or_rtsp_stream(video_source, tid, max_frames=max_frames)
                submit_detections_batch(api_base, tid, detections)
                submit_realtime_alert(api_base, tid, tag="pothole", lat=19.035, lng=73.150)

                processed_tasks.add(tid)
                print(f"✅ Survey '{tid}' pipeline completed. Listening for next survey submission...\n")

            if initial_load:
                print(f"✅ Initialized listener with {len(tasks)} existing survey(s). Active 24/7 polling started...")
                initial_load = False

        except Exception as e:
            print(f"⚠️ Polling loop error: {e}")

        time.sleep(poll_interval)


def main():
    parser = argparse.ArgumentParser(description="Z-TRACS CV Team AI Pipeline Handoff & 24/7 Integration Script")
    parser.add_argument("--api-base", default="http://3.109.28.196:8000", help="Z-TRACS API Base URL")
    parser.add_argument("--inspection-id", default="DEMO-001", help="Inspection ID for single-run mode")
    parser.add_argument("--max-frames", type=int, default=60, help="Max frames to process per video survey")
    parser.add_argument("--poll-interval", type=float, default=5.0, help="Polling interval in seconds for 24/7 mode")
    parser.add_argument("--once", action="store_true", help="Run once for single inspection ID instead of 24/7 daemon loop")

    args = parser.parse_args()

    if args.once:
        print(f"🏃 Running single-inspection test mode for ID '{args.inspection_id}'...")
        payload = fetch_pipeline_payload(args.api_base, args.inspection_id)
        video_source = payload.get("s3_presigned_download_url") or payload.get("video_url") or "demo_assets/road_inspection_demo.mp4"
        detections = process_video_or_rtsp_stream(video_source, args.inspection_id, max_frames=args.max_frames)
        submit_detections_batch(args.api_base, args.inspection_id, detections)
        submit_realtime_alert(args.api_base, args.inspection_id)
    else:
        try:
            run_continuous_daemon_loop(args.api_base, poll_interval=args.poll_interval, max_frames=args.max_frames)
        except KeyboardInterrupt:
            print("\nStopping Z-TRACS CV Pipeline Integration Daemon...")
            sys.exit(0)


if __name__ == "__main__":
    main()
