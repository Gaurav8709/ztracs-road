"""
Z-TRACS Road Intelligence - Computer Vision Client Interface (Part D)
Implements Mock CV Service (default) and HTTP CV Service Stub.
Adheres strictly to the frozen CVDetectionPayload contract.
"""
import os
import hashlib
import random
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Tuple, Optional
import cv2
import httpx

from backend.models import CVDetectionPayload

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(PROJECT_ROOT, "static")
EVIDENCE_BASE_DIR = os.getenv("EVIDENCE_DIR", os.path.join(STATIC_DIR, "media", "evidence"))


class BaseCVClient(ABC):
    @abstractmethod
    def run_inference(
        self,
        video_path: str,
        sampled_frames: List[Tuple[int, float, Any]],
        inspection_id: str,
        model_version: str = "RoadDefect-v1.0",
        corridor_coords: Optional[List[List[float]]] = None,
        duration_sec: float = 0.0,
        gps_points: Optional[List[Dict[str, float]]] = None
    ) -> List[Dict[str, Any]]:
        """
        Runs inference on sampled frames and returns detections matching CVDetectionPayload:
        {"detection_id","frame_id","timestamp","class","confidence","bbox",
         "severity","latitude","longitude","evidence_uri"}
        """
        pass


class MockCVClient(BaseCVClient):
    """
    Deterministic Mock CV Service seeded by video file hash.
    Clearly labelled everywhere as MOCK CV.
    """
    def __init__(self):
        self.is_mock = True

    def run_inference(
        self,
        video_path: str,
        sampled_frames: List[Tuple[int, float, Any]],
        inspection_id: str,
        model_version: str = "RoadDefect-v1.0",
        corridor_coords: Optional[List[List[float]]] = None,
        duration_sec: float = 0.0,
        gps_points: Optional[List[Dict[str, float]]] = None
    ) -> List[Dict[str, Any]]:
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")

        # Compute deterministic seed from video hash
        with open(video_path, "rb") as f:
            video_bytes = f.read()
        sha256_hash = hashlib.sha256(video_bytes).hexdigest()
        seed_int = int(sha256_hash[:16], 16)
        rng = random.Random(seed_int)

        evidence_dir = os.path.join(EVIDENCE_BASE_DIR, inspection_id)
        try:
            os.makedirs(evidence_dir, exist_ok=True)
        except OSError:
            pass

        if not corridor_coords:
            corridor_coords = [
                [18.9950, 73.1150], [19.0025, 73.1215], [19.0100, 73.1280],
                [19.0175, 73.1345], [19.0250, 73.1410], [19.0325, 73.1475],
                [19.0400, 73.1540], [19.0475, 73.1605], [19.0550, 73.1670],
                [19.0625, 73.1735], [19.0700, 73.1800]
            ]

        def get_coords_at_time(t_sec: float) -> Tuple[float, float]:
            if gps_points and len(gps_points) > 0:
                if len(gps_points) == 1:
                    return gps_points[0]["lat"], gps_points[0]["lon"]
                sorted_pts = sorted(gps_points, key=lambda p: p["timestamp"])
                if t_sec <= sorted_pts[0]["timestamp"]:
                    return sorted_pts[0]["lat"], sorted_pts[0]["lon"]
                if t_sec >= sorted_pts[-1]["timestamp"]:
                    return sorted_pts[-1]["lat"], sorted_pts[-1]["lon"]
                for k in range(len(sorted_pts) - 1):
                    p1 = sorted_pts[k]
                    p2 = sorted_pts[k + 1]
                    if p1["timestamp"] <= t_sec <= p2["timestamp"]:
                        span = max(p2["timestamp"] - p1["timestamp"], 1e-6)
                        frac = (t_sec - p1["timestamp"]) / span
                        lat = round(p1["lat"] + frac * (p2["lat"] - p1["lat"]), 5)
                        lng = round(p1["lon"] + frac * (p2["lon"] - p1["lon"]), 5)
                        return lat, lng
                return sorted_pts[-1]["lat"], sorted_pts[-1]["lon"]

            if duration_sec <= 0.0 or len(corridor_coords) < 2:
                return corridor_coords[0][0], corridor_coords[0][1]
            frac = min(max(t_sec / duration_sec, 0.0), 1.0)
            idx_float = frac * (len(corridor_coords) - 1)
            idx_low = int(idx_float)
            idx_high = min(idx_low + 1, len(corridor_coords) - 1)
            sub_frac = idx_float - idx_low

            p1 = corridor_coords[idx_low]
            p2 = corridor_coords[idx_high]
            lat = round(p1[0] + sub_frac * (p2[0] - p1[0]), 5)
            lng = round(p1[1] + sub_frac * (p2[1] - p1[1]), 5)
            return lat, lng

        classes = ["pothole", "crack", "marking"]
        severities = ["critical", "high", "medium", "low"]
        color_map = {
            "critical": (0, 0, 220),   # Red
            "high": (0, 140, 255),     # Orange
            "medium": (0, 215, 255),   # Yellow
            "low": (0, 200, 0)         # Green
        }

        detections = []
        det_count = 0

        # Deterministically determine which frames emit defects
        # Ensure at least 3-6 defects per video, plus random distribution
        for i, (frame_idx, t_sec, frame_img) in enumerate(sampled_frames):
            # Deterministic trigger
            should_emit = (i % 2 == 0) or (rng.random() < 0.45)
            if not should_emit and det_count >= 3:
                continue

            det_count += 1
            det_id = f"D-{inspection_id}-{det_count:04d}"
            h, w = frame_img.shape[:2]

            d_class = rng.choice(classes)
            severity = rng.choice(severities)
            confidence = round(rng.uniform(0.82, 0.98), 2)

            # Realistic bounding box
            bw = int(w * rng.uniform(0.12, 0.35))
            bh = int(h * rng.uniform(0.12, 0.30))
            bx1 = int(w * rng.uniform(0.15, 0.60))
            by1 = int(h * rng.uniform(0.35, 0.65))
            bx2 = min(bx1 + bw, w - 1)
            by2 = min(by1 + bh, h - 1)
            bbox = [bx1, by1, bx2, by2]

            # Save original frame crop / image
            orig_filename = f"det_{det_count:04d}_orig.jpg"
            orig_path = os.path.join(evidence_dir, orig_filename)
            cv2.imwrite(orig_path, frame_img)

            # Draw annotated bounding box with label
            anno_img = frame_img.copy()
            box_col = color_map.get(severity, (0, 165, 255))
            cv2.rectangle(anno_img, (bx1, by1), (bx2, by2), box_col, 2)

            # Badge / Label text
            label_text = f"{d_class.upper()} {confidence*100:.0f}% [{severity.upper()}] (MOCK CV)"
            cv2.putText(
                anno_img,
                label_text,
                (bx1, max(by1 - 8, 18)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                box_col,
                2
            )

            anno_filename = f"det_{det_count:04d}_anno.jpg"
            anno_path = os.path.join(evidence_dir, anno_filename)
            cv2.imwrite(anno_path, anno_img)

            try:
                from backend.s3_client import is_s3_enabled, upload_file
                if is_s3_enabled():
                    upload_file(orig_path, f"media/evidence/{inspection_id}/{orig_filename}", "image/jpeg")
                    upload_file(anno_path, f"media/evidence/{inspection_id}/{anno_filename}", "image/jpeg")
            except Exception:
                pass

            lat, lng = get_coords_at_time(t_sec)

            evidence_uri = f"{inspection_id}/{anno_filename}"

            det_payload = {
                "detection_id": det_id,
                "frame_id": frame_idx,
                "timestamp": round(t_sec, 2),
                "class": d_class,
                "confidence": confidence,
                "bbox": bbox,
                "severity": severity,
                "latitude": lat,
                "longitude": lng,
                "evidence_uri": evidence_uri
            }

            # Validate each detection with existing CVDetectionPayload contract
            CVDetectionPayload(**det_payload)
            detections.append(det_payload)

        return detections


class HTTPCVClient(BaseCVClient):
    """
    HTTP CV Service Client Stub.
    Posts frames to CV_SERVICE_URL/infer and validates return contract.
    Raises clear 'AI model unavailable' error if unreachable.
    """
    def __init__(self):
        self.service_url = os.getenv("CV_SERVICE_URL", "http://localhost:9999").rstrip("/")
        self.is_mock = False

    def run_inference(
        self,
        video_path: str,
        sampled_frames: List[Tuple[int, float, Any]],
        inspection_id: str,
        model_version: str = "RoadDefect-v1.0",
        corridor_coords: Optional[List[List[float]]] = None,
        duration_sec: float = 0.0,
        gps_points: Optional[List[Dict[str, float]]] = None
    ) -> List[Dict[str, Any]]:
        endpoint = f"{self.service_url}/infer"
        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.post(
                    endpoint,
                    json={
                        "inspection_id": inspection_id,
                        "model_version": model_version,
                        "frame_count": len(sampled_frames),
                        "video_path": video_path
                    }
                )
                if res.status_code != 200:
                    raise RuntimeError(f"AI model unavailable: Service returned status {res.status_code}")
                data = res.json()
                detections = data.get("detections", [])
                for det in detections:
                    CVDetectionPayload(**det)
                return detections
        except Exception as e:
            raise RuntimeError(f"AI model unavailable: {str(e)}")


def get_cv_client() -> BaseCVClient:
    mode = os.getenv("CV_MODE", "mock").strip().lower()
    if mode == "http":
        return HTTPCVClient()
    return MockCVClient()
