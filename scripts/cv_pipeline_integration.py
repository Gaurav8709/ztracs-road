#!/usr/bin/env python3
"""
Z-TRACS Road Intelligence Platform — Computer Vision (CV) AI Team Integration Script

This reference script demonstrates how the CV / AI Engineering Team connects to Z-TRACS:
1. Retrieves survey parameters & video/RTSP payload from Z-TRACS API (/api/inspections/{id}/pipeline-payload).
2. Reads video stream from S3 Presigned URL, Local File, or Live RTSP Stream (cv2.VideoCapture).
3. Performs frame-by-frame AI defect detection (Potholes, Cracks, Marking Damage).
4. Posts batch detections back to Z-TRACS API (/api/inspections/{id}/detections/batch).

Usage:
  python scripts/cv_pipeline_integration.py --inspection-id INS-001 --api-base http://127.0.0.1:8000 --token YOUR_JWT_TOKEN
"""

import argparse
import json
import time
import requests
import cv2

def fetch_pipeline_payload(api_base: str, inspection_id: str, token: str) -> dict:
    """Fetch execution parameters and S3/RTSP URL for target inspection survey."""
    url = f"{api_base.rstrip('/')}/api/inspections/{inspection_id}/pipeline-payload"
    headers = {"Authorization": f"Bearer {token}"}
    res = requests.get(url, headers=headers)
    res.raise_for_status()
    payload = res.json()
    print(f"✅ Fetched pipeline payload for {inspection_id}:")
    print(json.dumps(payload, indent=2))
    return payload


def process_video_or_rtsp_stream(payload: dict, max_frames: int = 100):
    """
    OpenCV Frame Reader supporting S3 Presigned URLs, Local Disk Files, and Live RTSP Streams.
    """
    video_source = payload.get("s3_presigned_download_url") or payload.get("rtsp_url") or payload.get("video_url")
    is_rtsp = payload.get("is_rtsp", False) or str(video_source).startswith("rtsp://")

    print(f"\n🎥 Connecting to video stream ({'RTSP Live Stream' if is_rtsp else 'S3 / Video File'}): {video_source}")
    cap = cv2.VideoCapture(video_source)

    if not cap.isOpened():
        print(f"❌ Failed to open video stream: {video_source}")
        return []

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) if not is_rtsp else 0
    print(f"📺 Stream opened: FPS={fps}, Total Frames={'Live' if is_rtsp else total_frames}")

    detections = []
    frame_idx = 0

    while cap.isOpened() and frame_idx < max_frames:
        ret, frame = cap.read()
        if not ret:
            break

        timestamp_sec = frame_idx / fps

        # Simulated / Placeholder AI Model Inference (Replace with PyTorch / YOLO / ONNX model)
        # Example: Detect pothole or crack every 15 frames
        if frame_idx > 0 and frame_idx % 15 == 0:
            det_id = f"DEF-CV-{inspection_id_clean(payload['inspection_id'])}-{frame_idx}"
            detection = {
                "detection_id": det_id,
                "frame_id": frame_idx,
                "timestamp": round(timestamp_sec, 2),
                "class": "pothole" if frame_idx % 30 == 0 else "crack",
                "confidence": 0.92,
                "bbox": [120.0, 340.0, 480.0, 620.0],
                "severity": "critical" if frame_idx % 30 == 0 else "high",
                "latitude": 18.9850 + (frame_idx * 0.0001),
                "longitude": 73.1100 + (frame_idx * 0.0001),
                "evidence_uri": f"{payload['inspection_id']}/{det_id}_anno.jpg",
                "road_segment_id": "RD-001",
                "model_version": payload.get("model_version", "RoadDefect-v1.0")
            }
            detections.append(detection)

        frame_idx += 1

    cap.release()
    print(f"🎉 Processed {frame_idx} frames. Total AI defects detected: {len(detections)}")
    return detections


def inspection_id_clean(insp_id: str) -> str:
    return insp_id.replace("-", "").lower()


def submit_detections_batch(api_base: str, inspection_id: str, detections: list, token: str):
    """Post AI detection results back to Z-TRACS Platform API."""
    if not detections:
        print("ℹ️ No detections to submit.")
        return

    url = f"{api_base.rstrip('/')}/api/inspections/{inspection_id}/detections/batch"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    res = requests.post(url, headers=headers, json=detections)
    res.raise_for_status()
    print(f"✅ Successfully ingested {len(detections)} AI detections into Z-TRACS!")
    print(res.json())


def main():
    parser = argparse.ArgumentParser(description="Z-TRACS CV Team AI Pipeline Handoff Script")
    parser.add_argument("--api-base", default="http://3.109.28.196:8000", help="Z-TRACS API Base URL")

    parser.add_argument("--inspection-id", required=True, help="Inspection ID (e.g. INS-001)")
    parser.add_argument("--token", required=True, help="JWT Auth Token from Z-TRACS /api/auth/login")
    parser.add_argument("--max-frames", type=int, default=60, help="Max frames to process for test run")

    args = parser.parse_args()

    payload = fetch_pipeline_payload(args.api_base, args.inspection_id, args.token)
    detections = process_video_or_rtsp_stream(payload, max_frames=args.max_frames)
    submit_detections_batch(args.api_base, args.inspection_id, detections, args.token)


if __name__ == "__main__":
    main()
