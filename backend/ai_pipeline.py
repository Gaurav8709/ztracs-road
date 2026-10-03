"""
Z-TRACS Road Intelligence - Real AI Processing Pipeline with Mock CV Service (Part D)
Replaces simulated sleeps with real OpenCV video decoding, deterministic Mock CV inference,
geo-referencing, and state persistence.
"""
import os
import json
import time
import threading
from datetime import datetime
from typing import Optional, Dict, Any

import cv2

from backend.database import get_connection, record_audit_log
from backend.models import InspectionStatus
from backend.cv_client import get_cv_client

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(PROJECT_ROOT, "static")
DATA_DIR = os.getenv("DATA_DIR", os.path.join(PROJECT_ROOT, "data"))
VIDEO_DIR = os.getenv("VIDEO_DIR", os.path.join(STATIC_DIR, "media", "video"))
PROCESSING_TIMEOUT_SECONDS = int(os.getenv("PROCESSING_TIMEOUT_SECONDS", 1800))


class RealPipelineWorker:
    def __init__(self):
        self._lock = threading.Lock()
        self.active_jobs = set()

    def get_status(self, inspection_id: str) -> Optional[Dict[str, Any]]:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM inspections WHERE id = %s", (inspection_id,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        insp = dict(row)
        return {
            "id": insp["id"],
            "status": insp["status"],
            "current_stage": insp["current_stage"],
            "progress_percent": insp["progress_percent"],
            "processed_frames": insp["processed_frames"],
            "total_frames": insp["total_frames"],
            "defect_count": insp["defect_count"],
            "model_version": insp["model_version"],
            "video_url": insp["video_url"],
            "started_at": insp["started_at"],
            "completed_at": insp["completed_at"],
            "error_message": insp.get("error_message"),
            "is_mock": bool(insp.get("is_mock", 1)),
            "duration_seconds": insp.get("duration_seconds", 0.0),
            "fps": insp.get("fps", 0.0)
        }

    def _update_stage(
        self,
        inspection_id: str,
        status: str,
        progress: int,
        stage_desc: str,
        processed_frames: int,
        total_frames: int,
        defect_count: int,
        error_message: Optional[str] = None
    ):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE inspections SET
                status = %s, progress_percent = %s, current_stage = %s,
                processed_frames = %s, total_frames = %s, defect_count = %s,
                error_message = %s
            WHERE id = %s
            """,
            (status, progress, stage_desc, processed_frames, total_frames, defect_count, error_message, inspection_id),
        )
        conn.commit()
        conn.close()

    def _fail_job(self, inspection_id: str, message: str, username: str = "system", role: str = "system"):
        conn = get_connection()
        cursor = conn.cursor()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            """
            UPDATE inspections SET
                status = 'FAILED', current_stage = 'Processing Failed',
                error_message = %s, completed_at = %s
            WHERE id = %s
            """,
            (message, now_str, inspection_id),
        )
        conn.commit()
        conn.close()
        record_audit_log(username, role, "status_transition", target_id=inspection_id, details=f"Status -> FAILED: {message}")

    def run_pipeline_job(self, inspection_id: str, username: str = "admin", role: str = "admin"):
        with self._lock:
            if inspection_id in self.active_jobs:
                return
            self.active_jobs.add(inspection_id)

        try:
            self._execute_pipeline(inspection_id, username, role)
        finally:
            with self._lock:
                self.active_jobs.discard(inspection_id)

    def run_pipeline_async(self, inspection_id: str):
        """Backwards compatible alias for tests"""
        self.run_pipeline_job(inspection_id, username="system", role="inspector")

    def _execute_pipeline(self, inspection_id: str, username: str, role: str):
        start_time = time.time()
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM inspections WHERE id = %s", (inspection_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return
        insp = dict(row)

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            "UPDATE inspections SET status = 'PROCESSING', started_at = %s, progress_percent = 5, current_stage = 'Initializing Pipeline' WHERE id = %s",
            (now_str, inspection_id),
        )
        conn.commit()
        conn.close()
        record_audit_log(username, role, "status_transition", target_id=inspection_id, details="Status -> PROCESSING")

        # 1. Resolve video path
        video_url = insp.get("video_url") or "/api/media/video/demo_road.mp4"
        video_filename = os.path.basename(video_url)
        video_path = os.path.join(VIDEO_DIR, video_filename)

        if not os.path.exists(video_path):
            self._fail_job(inspection_id, "The video file could not be read. Please upload a valid MP4.", username, role)
            return

        # 2. Open video with OpenCV & validate
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            cap.release()
            self._fail_job(inspection_id, "The video file could not be read. Please upload a valid MP4.", username, role)
            return

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = float(cap.get(cv2.CAP_PROP_FPS))

        if total_frames <= 0 or fps <= 0.0:
            cap.release()
            self._fail_job(inspection_id, "The video file could not be read. Please upload a valid MP4.", username, role)
            return

        duration_sec = round(total_frames / fps, 2)

        # Store real duration, fps and total_frames in DB
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE inspections SET total_frames = %s, duration_seconds = %s, fps = %s WHERE id = %s",
            (total_frames, duration_sec, round(fps, 2), inspection_id),
        )
        conn.commit()
        conn.close()

        # 3. Stage 1: Frame Extraction & Sampling (default 1 fps)
        frames_out_dir = os.path.join(DATA_DIR, "inspections", inspection_id, "frames")
        os.makedirs(frames_out_dir, exist_ok=True)

        step = max(int(round(fps)), 1)
        sampled_frames = []

        frame_idx = 0
        extracted_count = 0

        self._update_stage(
            inspection_id,
            InspectionStatus.PROCESSING.value,
            15,
            "Frame Extraction & Preprocessing",
            0,
            total_frames,
            0
        )
        record_audit_log(username, role, "stage_transition", target_id=inspection_id, details="Stage -> Frame Extraction & Preprocessing")

        while True:
            if time.time() - start_time > PROCESSING_TIMEOUT_SECONDS:
                cap.release()
                self._fail_job(inspection_id, "Processing timeout exceeded.", username, role)
                return

            ret, frame = cap.read()
            if not ret:
                break
            if frame_idx % step == 0:
                t_sec = frame_idx / fps
                frame_filename = f"frame_{frame_idx:04d}.jpg"
                frame_save_path = os.path.join(frames_out_dir, frame_filename)
                cv2.imwrite(frame_save_path, frame)
                sampled_frames.append((frame_idx, t_sec, frame))
                extracted_count += 1

                # Update progress during sampling (smooth progression 15% -> 40%)
                pct = min(15 + int((frame_idx / total_frames) * 25), 40)
                self._update_stage(
                    inspection_id,
                    InspectionStatus.PROCESSING.value,
                    pct,
                    f"Extracting Frames ({extracted_count} sampled)",
                    frame_idx,
                    total_frames,
                    0
                )
                time.sleep(0.03)
            frame_idx += 1

        cap.release()

        time.sleep(0.2)

        # 4. Stage 2: AI Perception Inference (Mock CV Service)
        self._update_stage(
            inspection_id,
            InspectionStatus.AI_ANALYSIS.value,
            45,
            "AI Perception Inference (Mock CV Service)",
            total_frames,
            total_frames,
            0
        )
        record_audit_log(username, role, "status_transition", target_id=inspection_id, details="Status -> AI_ANALYSIS")

        # Check for GPS points upload
        gps_points_path = os.path.join(DATA_DIR, "inspections", inspection_id, "gps_points.json")
        gps_source_name = "interpolated from corridor geometry"
        gps_points = None
        if os.path.exists(gps_points_path):
            try:
                with open(gps_points_path, "r") as f_gps:
                    gps_points = json.load(f_gps)
                    if gps_points:
                        gps_source_name = "gps_file"
            except Exception:
                pass

        # Fetch corridor coordinates for GPS interpolation
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT geometry_json FROM road_segments ORDER BY id ASC")
        rows = cursor.fetchall()
        conn.close()

        corridor_coords = []
        for r in rows:
            try:
                coords = json.loads(r["geometry_json"])
                for pt in coords:
                    corridor_coords.append(pt)
            except Exception:
                pass

        # Run inference via CV Client (Mock or HTTP)
        try:
            cv_client = get_cv_client()
            detections = cv_client.run_inference(
                video_path=video_path,
                sampled_frames=sampled_frames,
                inspection_id=inspection_id,
                model_version=insp["model_version"],
                corridor_coords=corridor_coords,
                duration_sec=duration_sec,
                gps_points=gps_points
            )
        except Exception as e:
            self._fail_job(inspection_id, str(e), username, role)
            return

        time.sleep(0.2)

        self._update_stage(
            inspection_id,
            InspectionStatus.AI_ANALYSIS.value,
            70,
            f"AI Inference Complete ({len(detections)} defects identified)",
            total_frames,
            total_frames,
            len(detections)
        )

        time.sleep(0.2)

        # 5. Stage 3: Geo-referencing Detections to Road Segments
        self._update_stage(
            inspection_id,
            InspectionStatus.GEO_REFERENCING.value,
            80,
            "Geo-referencing Detections to Road Segments",
            total_frames,
            total_frames,
            len(detections)
        )
        record_audit_log(username, role, "status_transition", target_id=inspection_id, details="Status -> GEO_REFERENCING")

        # Ingest detections using shared ingestion logic
        try:
            from backend.main import ingest_detections_core
            ingest_detections_core(inspection_id, detections, username, role, gps_source=gps_source_name)
        except Exception as e:
            self._fail_job(inspection_id, f"Ingest/Geo-referencing failed: {str(e)}", username, role)
            return

        time.sleep(0.2)

        # 6. Stage 4: Aggregation & Risk Scoring
        self._update_stage(
            inspection_id,
            InspectionStatus.AGGREGATION.value,
            92,
            "Condition Scoring & Risk Priority Calculation",
            total_frames,
            total_frames,
            len(detections)
        )
        record_audit_log(username, role, "status_transition", target_id=inspection_id, details="Status -> AGGREGATION")

        time.sleep(0.2)

        # 7. Stage 5: Finalize and Save structured JSON output
        out_dir = os.path.join(DATA_DIR, "inspections", inspection_id, "outputs")
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "detections.json"), "w") as f_out:
            json.dump(detections, f_out, indent=2)

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE inspections SET
                status = 'COMPLETED', progress_percent = 100, current_stage = 'Completed & Geo-Referenced',
                processed_frames = %s, total_frames = %s, defect_count = %s, completed_at = %s,
                is_mock = 1
            WHERE id = %s
            """,
            (total_frames, total_frames, len(detections), now_str, inspection_id),
        )
        conn.commit()
        conn.close()
        record_audit_log(username, role, "status_transition", target_id=inspection_id, details="Status -> COMPLETED")


pipeline_worker = RealPipelineWorker()
