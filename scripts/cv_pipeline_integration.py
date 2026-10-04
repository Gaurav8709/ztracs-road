#!/usr/bin/env python3
"""
Z-TRACS Road Intelligence Platform — Computer Vision (CV) AI Team Integration Script

This reference script demonstrates how the CV / AI Engineering Team connects to Z-TRACS:
1. Retrieves survey parameters & video/RTSP payload from Z-TRACS API (/api/inspections/{id}/pipeline-payload).
2. Reads video stream from S3 Presigned URL, Local File, or Live RTSP Stream (cv2.VideoCapture).
3. Performs frame-by-frame AI defect detection (Potholes, Cracks, Marking Damage).
4. Posts batch detections back to Z-TRACS API (/api/cv/ai-results).

Usage:
  python scripts/cv_pipeline_integration.py --inspection-id DEMO-001
"""

import argparse
import json
import time
import urllib.request
import urllib.error
import cv2

def fetch_pipeline_payload(api_base: str, inspection_id: str) -> dict:
    """Fetch execution parameters and S3/RTSP URL for target inspection survey."""
    url = f"{api_base.rstrip('/')}/api/inspections/{inspection_id}/pipeline-payload"
    req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            print(f"✅ Fetched pipeline payload for '{inspection_id}':")
            print(json.dumps(payload, indent=2))
            return payload
    except Exception as e:
        print(f"⚠️ Could not fetch payload from API ({e}). Falling back to local default config.")
        return {
            "inspection_id": inspection_id,
            "video_url": "demo_assets/road_inspection_demo.mp4",
            "is_rtsp": False,
            "model_version": "RoadDefect-v1.0"
        }


def process_video_or_rtsp_stream(payload: dict, max_frames: int = 100):
    """
    OpenCV Frame Reader supporting S3 Presigned URLs, Local Disk Files, and Live RTSP Streams.
    """
    video_source = payload.get("s3_presigned_download_url") or payload.get("rtsp_url") or payload.get("video_url") or "demo_assets/road_inspection_demo.mp4"
    is_rtsp = payload.get("is_rtsp", False) or str(video_source).startswith("rtsp://")

    print(f"\n🎥 Connecting to video stream ({'RTSP Live Stream' if is_rtsp else 'S3 / Video File'}): {video_source}")
    cap = cv2.VideoCapture(video_source)

    if not cap.isOpened():
        print(f"⚠️ Cannot open video source: {video_source}. Running simulated frame loop.")
        fps = 25.0
        total_frames = 100
    else:
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) if not is_rtsp else 0
        print(f"📺 Stream opened: FPS={fps}, Total Frames={'Live' if is_rtsp else total_frames}")

    detections = []
    frame_idx = 0

    while frame_idx < max_frames:
        if cap and cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

        timestamp_sec = frame_idx / fps

        # Simulated AI Model Inference (Replace with PyTorch / YOLO model)
        if frame_idx > 0 and frame_idx % 15 == 0:
            det_id = f"DEF-CV-{inspection_id_clean(payload['inspection_id'])}-{frame_idx}"
            detection = {
                "detection_id": det_id,
                "frame": {
                    "frame_number": frame_idx,
                    "timestamp_seconds": round(timestamp_sec, 2)
                },
                "classification": {
                    "class_name": "pothole" if frame_idx % 30 == 0 else "crack",
                    "confidence": 0.92,
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

    print(f"🎉 Processed {frame_idx} frames. Total AI defects detected: {len(detections)}")
    return detections


def inspection_id_clean(insp_id: str) -> str:
    return insp_id.replace("-", "").lower()


def submit_detections_batch(api_base: str, inspection_id: str, detections: list):
    """Post AI detection results back to Z-TRACS Platform API."""
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
        with urllib.request.urlopen(req) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            print(f"✅ Successfully ingested {len(detections)} AI detections into Z-TRACS!")
            print(json.dumps(res, indent=2))
    except Exception as e:
        print(f"❌ Connection error to {url}: {e}")


def main():
    parser = argparse.ArgumentParser(description="Z-TRACS CV Team AI Pipeline Handoff Script")
    parser.add_argument("--api-base", default="http://3.109.28.196:8000", help="Z-TRACS API Base URL")
    parser.add_argument("--inspection-id", default="DEMO-001", help="Inspection ID (e.g. DEMO-001)")
    parser.add_argument("--max-frames", type=int, default=60, help="Max frames to process for test run")

    args = parser.parse_args()

    payload = fetch_pipeline_payload(args.api_base, args.inspection_id)
    detections = process_video_or_rtsp_stream(payload, max_frames=args.max_frames)
    submit_detections_batch(args.api_base, args.inspection_id, detections)


if __name__ == "__main__":
    main()
