# Z-TRACS Road Intelligence — Computer Vision (CV) AI Team Integration & Handoff Guide

This document defines the official API integration and JSON payload schemas (Schema Version 1.0) for the **Computer Vision & AI Engineering Team** to connect model pipelines to the **Z-TRACS Road Intelligence Platform**.

---

## 1. Architectural Overview

```
 ┌──────────────────────┐          ┌──────────────────────┐          ┌─────────────────────────┐
 │ Z-TRACS Platform API │ ───────> │ Fetch Survey Payload │ ───────> │  CV AI Pipeline Engine  │
 │ (FastAPI + PostGIS)  │          │ (GET /pipeline-payload)         │ (YOLO/PyTorch Inference)│
 └──────────────────────┘          └──────────────────────┘          └─────────────────────────┘
            ▲                                                                     │
            │                         Send Model Results                          │
            └─────────────────────────────────────────────────────────────────────┘
                             (python scripts/send_cv_results.py)
```

---

## 2. API Endpoints Summary

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `POST /api/cv/alert` | `POST` | **Simplified Alert**: Token-free, auto-creates inspection, accepts `{video, rtsp, type, tag, lat, long}` |
| `POST /api/cv/ai-results` | `POST` | Ingest full `ai_results.json` (Schema 1.0) defect & segment metrics |
| `POST /api/cv/status-update` | `POST` | Ingest real-time `processing_status.json` progress updates |
| `POST /api/cv/status-failed` | `POST` | Ingest pipeline failure report `processing_failed.json` |

---

## 3. Official JSON Schemas (Schema 1.0)

### 3.1 `ai_results.json` (Full Defect & Segment Results)
```json
{
  "schema_version": "1.0",
  "inspection_id": "INS-2026-000001",
  "model": {
    "model_name": "ZTRACS-RoadDefect",
    "model_version": "v1.0.0",
    "processing_version": "cv-pipeline-v1.0.0"
  },
  "video": {
    "type": "vehicle_camera",
    "filename": "road_inspection_demo.mp4",
    "duration_seconds": 132.5,
    "fps": 30,
    "width": 1920,
    "height": 1080,
    "codec": "H.264",
    "total_frames": 3975
  },
  "detections": [
    {
      "detection_id": "DEF-POT-000001",
      "track_id": "TRK-00017",
      "frame": {
        "frame_number": 1821,
        "timestamp_seconds": 60.7
      },
      "classification": {
        "class_name": "pothole",
        "confidence": 0.94,
        "severity": "critical"
      },
      "geometry": {
        "bbox": {
          "x1": 420,
          "y1": 510,
          "x2": 690,
          "y2": 720
        }
      },
      "location": {
        "latitude": 19.123456,
        "longitude": 73.123456,
        "accuracy_meters": 3.5,
        "quality": "good"
      },
      "road": {
        "road_id": "RD-NH48",
        "segment_id": "RD-001"
      },
      "evidence": {
        "original_frame_s3_key": "inspections/INS-2026-000001/evidence/DEF-POT-000001_original.jpg",
        "annotated_frame_s3_key": "inspections/INS-2026-000001/evidence/DEF-POT-000001_annotated.jpg",
        "crop_s3_key": "inspections/INS-2026-000001/evidence/DEF-POT-000001_crop.jpg"
      }
    }
  ]
}
```

---

### 3.2 `processing_status.json` (Real-Time Progress Update)
```json
{
  "inspection_id": "INS-2026-000001",
  "status": "processing",
  "stage": "ai_inference",
  "progress": 72,
  "frames_processed": 2862,
  "total_frames": 3975,
  "detections_found": 128
}
```

---

### 3.3 `processing_failed.json` (Error Report)
```json
{
  "inspection_id": "INS-2026-000002",
  "status": "failed",
  "stage": "ai_inference",
  "error_code": "MODEL_LOAD_ERROR",
  "error_message": "Unable to load model",
  "retryable": true
}
```

---

## 4. How the CV Team Sends Results Using Python

The CV Team can directly use the provided Python script `scripts/send_cv_results.py` (which has **zero external dependencies** and uses standard Python `urllib`):

### 1. Send `ai_results.json`:
```bash
python scripts/send_cv_results.py \
  --json ai_results.json \
  --api-base http://127.0.0.1:8000 \
  --username admin \
  --password change-me-admin-password
```

### 2. Send `processing_status.json`:
```bash
python scripts/send_cv_results.py \
  --json processing_status.json \
  --api-base http://127.0.0.1:8000
```

### 3. Integrate in CV Python Code directly:
```python
from scripts.send_cv_results import get_auth_token, send_cv_payload

token = get_auth_token("http://127.0.0.1:8000", "admin", "change-me-admin-password")

# Send status update
send_cv_payload("http://127.0.0.1:8000", {
    "inspection_id": "INS-001",
    "status": "processing",
    "progress": 50,
    "frames_processed": 1000,
    "total_frames": 2000,
    "detections_found": 15
}, token)

# Send final results
with open("ai_results.json") as f:
    results_data = json.load(f)

send_cv_payload("http://127.0.0.1:8000", results_data, token)
```
