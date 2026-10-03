"""
Z-TRACS Road Intelligence - Real AI Processing Pipeline & System Integrity Test Suite
Runs against a REAL live Uvicorn HTTP server over an isolated PostgreSQL + PostGIS test environment.
Validates all pipeline requirements (2.a through 2.f) plus PostGIS spatial and migration integrity.
"""
import os
import sys
import re
import time
import socket
import subprocess
import shutil
import tempfile
import secrets
import getpass
from typing import Dict

import cv2
import numpy as np
import httpx
import psycopg
from psycopg.rows import dict_row
from PIL import Image
from pypdf import PdfReader

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")

# Generate random JWT secret and dynamic test credentials
TEST_JWT_SECRET = secrets.token_urlsafe(48)
TEST_ADMIN_USERNAME = f"pipeadmin_{secrets.token_hex(4)}"
TEST_ADMIN_PASSWORD = f"P_{secrets.token_urlsafe(16)}!9"

# Ephemeral PostgreSQL database setup (supports both Docker PostGIS and local pg)
def _get_pg_config(prefix="ztracs_test_pipe"):
    db_id = secrets.token_hex(4)
    db_name = f"{prefix}_{db_id}"
    candidates = [
        ("postgresql://postgres:postgres@localhost:5432/postgres", f"postgresql://postgres:postgres@localhost:5432/{db_name}"),
        (f"postgresql://{getpass.getuser()}@localhost:5432/postgres", f"postgresql://{getpass.getuser()}@localhost:5432/{db_name}")
    ]
    for base, target in candidates:
        try:
            with psycopg.connect(base, connect_timeout=1):
                return base, target, db_name
        except Exception:
            continue
    return candidates[0][0], candidates[0][1], db_name

BASE_PG_URL, TEST_DATABASE_URL, TEST_DB_NAME = _get_pg_config("ztracs_test_pipe")

# Create separate temporary directories for files
TEST_TMP_DIR = tempfile.mkdtemp(prefix="ztracs_test_pipe_")
TEST_DATA_DIR = os.path.join(TEST_TMP_DIR, "data")
TEST_EVIDENCE_DIR = os.path.join(TEST_TMP_DIR, "evidence")
TEST_REPORTS_DIR = os.path.join(TEST_TMP_DIR, "reports")
TEST_VIDEO_DIR = os.path.join(TEST_TMP_DIR, "video")
TEST_SCRATCH_DIR = os.path.join(TEST_TMP_DIR, "scratch")

for d in (TEST_DATA_DIR, TEST_EVIDENCE_DIR, TEST_REPORTS_DIR, TEST_VIDEO_DIR, TEST_SCRATCH_DIR):
    os.makedirs(d, exist_ok=True)

# Copy demo_road.mp4 to test video directory for fallback references
demo_src = os.path.join(PROJECT_ROOT, "static", "media", "video", "demo_road.mp4")
if os.path.exists(demo_src):
    shutil.copy(demo_src, os.path.join(TEST_VIDEO_DIR, "demo_road.mp4"))

results_table = []


def record_result(check_num: int, description: str, passed: bool, details: str = ""):
    status_str = "PASS" if passed else "FAIL"
    results_table.append((check_num, description, status_str, details))
    print(f"[{status_str}] Check {check_num}: {description} {f'({details})' if details else ''}")


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def create_test_mp4(filepath: str, duration_sec: int = 10, fps: int = 10):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    total_frames = duration_sec * fps
    writer = cv2.VideoWriter(filepath, fourcc, float(fps), (640, 360))

    for i in range(total_frames):
        img = np.zeros((360, 640, 3), dtype=np.uint8)
        img[180:, :] = (50, 50, 50)
        cv2.line(img, (320, 180), (320, 360), (0, 255, 255), 4)
        cv2.putText(
            img,
            f"Z-TRACS TEST SURVEY - Frame {i:04d} / {total_frames:04d}",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 0),
            2
        )
        writer.write(img)

    writer.release()
    return total_frames, float(fps)


def start_server(port: int, env_extra: Dict[str, str] = None) -> subprocess.Popen:
    env = os.environ.copy()
    env["JWT_SECRET"] = TEST_JWT_SECRET
    env["ADMIN_USERNAME"] = TEST_ADMIN_USERNAME
    env["ADMIN_PASSWORD"] = TEST_ADMIN_PASSWORD
    env["DATABASE_URL"] = TEST_DATABASE_URL
    env["DATA_DIR"] = TEST_DATA_DIR
    env["EVIDENCE_DIR"] = TEST_EVIDENCE_DIR
    env["REPORTS_DIR"] = TEST_REPORTS_DIR
    env["VIDEO_DIR"] = TEST_VIDEO_DIR
    env["ALLOWED_ORIGINS"] = "http://localhost:8000,http://127.0.0.1"
    env["CV_MODE"] = "mock"
    env["PYTHONPATH"] = PROJECT_ROOT
    if env_extra:
        env.update(env_extra)

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--port", str(port), "--host", "127.0.0.1"],
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    return proc


def wait_for_server(base_url: str, timeout_sec: int = 15) -> bool:
    start_t = time.time()
    while time.time() - start_t < timeout_sec:
        try:
            r = httpx.get(f"{base_url}/api/health", timeout=1.0)
            if r.status_code == 200:
                return True
        except Exception:
            time.sleep(0.2)
    return False


def main():
    print("==========================================================")
    print("  Z-TRACS PostgreSQL + PostGIS Real Pipeline Test Suite")
    print("==========================================================")

    # 1. Provision Ephemeral Test Database
    print(f"Creating ephemeral PostgreSQL test database: {TEST_DB_NAME}")
    admin_conn = psycopg.connect(BASE_PG_URL, autocommit=True)
    admin_cur = admin_conn.cursor()
    admin_cur.execute(f"CREATE DATABASE {TEST_DB_NAME};")
    admin_cur.close()
    admin_conn.close()

    # Enable PostGIS in the new test database
    db_conn = psycopg.connect(TEST_DATABASE_URL, autocommit=True)
    db_cur = db_conn.cursor()
    db_cur.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
    db_cur.close()
    db_conn.close()

    test_port = find_free_port()
    base_url = f"http://127.0.0.1:{test_port}"
    server_proc = start_server(test_port)

    video_path_1 = os.path.join(TEST_SCRATCH_DIR, "real_survey_10s.mp4")
    expected_frames, expected_fps = create_test_mp4(video_path_1, duration_sec=10, fps=10)
    expected_duration = round(expected_frames / expected_fps, 2)

    try:
        ready = wait_for_server(base_url, timeout_sec=20)
        if not ready:
            print("FATAL: Uvicorn server failed to start within timeout.")
            if server_proc.poll() is not None:
                out, err = server_proc.communicate()
                print("Server stdout:", out)
                print("Server stderr:", err)
            server_proc.kill()
            sys.exit(1)

        print(f"Live test server running on {base_url} (PID: {server_proc.pid})")

        # CHECK 0.a: PostGIS is available via /api/health and direct query
        health_res = httpx.get(f"{base_url}/api/health").json()
        health_postgis = health_res.get("postgis_version")
        c0a_ok = health_res.get("status") == "healthy" and health_postgis is not None and "3." in str(health_postgis)
        record_result(0, "PostGIS is available and verified via /api/health", c0a_ok, f"PostGIS Version: {health_postgis}")

        # CHECK 0.b: Geometry columns and GIST indexes exist in schema
        with psycopg.connect(TEST_DATABASE_URL, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT f_table_name, f_geometry_column, type, srid 
                    FROM geometry_columns 
                    WHERE f_table_name IN ('road_segments', 'detections');
                """)
                geom_cols = {r["f_table_name"]: r for r in cur.fetchall()}

                cur.execute("""
                    SELECT tablename, indexname, indexdef 
                    FROM pg_indexes 
                    WHERE tablename IN ('road_segments', 'detections', 'segment_metrics');
                """)
                indexes = {r["indexname"]: r["indexdef"] for r in cur.fetchall()}

        has_seg_geom = "road_segments" in geom_cols and geom_cols["road_segments"]["type"] == "LINESTRING"
        has_det_geom = "detections" in geom_cols and geom_cols["detections"]["type"] == "POINT"
        has_seg_gist = "idx_road_segments_geom" in indexes and "USING gist" in indexes["idx_road_segments_geom"]
        has_det_gist = "idx_detections_geom" in indexes and "USING gist" in indexes["idx_detections_geom"]
        has_metrics_idx = "idx_segment_metrics_insp_seg" in indexes or "segment_metrics_inspection_id_segment_id_key" in indexes

        c0b_ok = (has_seg_geom and has_det_geom and has_seg_gist and has_det_gist and has_metrics_idx)
        record_result(100, "Geometry columns and GIST indexes exist in PostgreSQL schema", c0b_ok, f"Geoms: {list(geom_cols.keys())}, GISTs: {['idx_road_segments_geom' in indexes, 'idx_detections_geom' in indexes]}")

        login_res = httpx.post(f"{base_url}/api/auth/login", json={"username": TEST_ADMIN_USERNAME, "password": TEST_ADMIN_PASSWORD})
        if login_res.status_code != 200 or "access_token" not in login_res.json():
            raise RuntimeError(f"Failed to authenticate as admin: {login_res.text}")
        admin_token = login_res.json()["access_token"]
        auth_headers = {"Authorization": f"Bearer {admin_token}"}

        # CHECK 1: Upload MP4, start inspection, poll progress monotonically, verify audit log order (2.a)
        create_res = httpx.post(
            f"{base_url}/api/inspections",
            headers=auth_headers,
            json={
                "name": "Test Highway Survey 1",
                "road_id": "RD-NH48",
                "road_name": "NH-48 Corridor",
                "source_type": "Vehicle Camera",
                "model_version": "RoadDefect-v1.0"
            }
        )
        assert create_res.status_code == 201, f"Failed create inspection: {create_res.text}"
        insp_id_1 = create_res.json()["id"]

        with open(video_path_1, "rb") as vf:
            upload_res = httpx.post(
                f"{base_url}/api/inspections/{insp_id_1}/upload",
                headers=auth_headers,
                files={"file": ("real_survey_10s.mp4", vf, "video/mp4")}
            )
        assert upload_res.status_code == 200, f"Failed upload: {upload_res.text}"

        start_res = httpx.post(f"{base_url}/api/inspections/{insp_id_1}/start", headers=auth_headers)
        assert start_res.status_code == 200, f"Failed start: {start_res.text}"

        progress_monotonic = True
        prev_pct = 0
        prev_frames = 0
        terminal_status = None
        fast_latency_ok = True
        latency_checked = False

        for _ in range(70):
            st = httpx.get(f"{base_url}/api/inspections/{insp_id_1}/status", headers=auth_headers).json()
            curr_pct = st.get("progress_percent", 0)
            curr_frames = st.get("processed_frames", 0)

            if curr_pct < prev_pct or curr_frames < prev_frames:
                progress_monotonic = False
            prev_pct = max(prev_pct, curr_pct)
            prev_frames = max(prev_frames, curr_frames)

            # CHECK 2 (2.b): GET /api/inspections answers in under 2 seconds while processing
            if st.get("status") in ["PROCESSING", "AI_ANALYSIS"] and not latency_checked:
                t0 = time.time()
                list_resp = httpx.get(f"{base_url}/api/inspections", headers=auth_headers, timeout=5.0)
                elapsed = time.time() - t0
                fast_latency_ok = (list_resp.status_code == 200 and elapsed < 2.0)
                latency_checked = True

            if st.get("status") in ["COMPLETED", "FAILED"]:
                terminal_status = st.get("status")
                break
            time.sleep(0.3)

        # Query audit log for stage sequence via PostgreSQL
        with psycopg.connect(TEST_DATABASE_URL, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT details FROM audit_logs WHERE target_id = %s AND action = 'status_transition' ORDER BY id ASC", (insp_id_1,))
                log_rows = cur.fetchall()

        observed_stages = [r["details"].replace("Status -> ", "").strip() for r in log_rows]
        expected_stages = ["CREATED", "UPLOADED", "QUEUED", "PROCESSING", "AI_ANALYSIS", "GEO_REFERENCING", "AGGREGATION", "COMPLETED"]
        stages_match = (observed_stages == expected_stages)

        c1_ok = (terminal_status == "COMPLETED" and progress_monotonic and stages_match)
        record_result(1, "Progress never backwards, stages match in audit log: CREATED..COMPLETED (2.a)", c1_ok, f"Stages: {observed_stages}")

        # CHECK 2: GET /api/inspections answers in under 2s while video processing (2.b)
        record_result(2, "GET /api/inspections answers in under 2 seconds while processing (2.b)", fast_latency_ok, f"Checked: {latency_checked}")

        # CHECK 3: Frame count, FPS, and duration match actual video
        insp_detail = httpx.get(f"{base_url}/api/inspections/{insp_id_1}", headers=auth_headers).json()
        reported_frames = insp_detail.get("total_frames")
        reported_fps = insp_detail.get("fps")
        reported_duration = insp_detail.get("duration_seconds")
        c3_ok = (reported_frames == expected_frames and reported_fps == expected_fps and abs(reported_duration - expected_duration) < 0.2)
        record_result(3, "Frame count and FPS match actual video", c3_ok, f"Frames: {reported_frames} (exp {expected_frames}), FPS: {reported_fps} (exp {expected_fps})")

        # CHECK 4: Realistic timestamps and GPS interpolation
        dets_res = httpx.get(f"{base_url}/api/inspections/{insp_id_1}/detections", headers=auth_headers)
        dets_1 = dets_res.json()
        timestamps = [d["timestamp"] for d in dets_1]
        all_within_duration = all(0.0 <= t <= expected_duration + 0.1 for t in timestamps) if timestamps else False
        is_sorted = (timestamps == sorted(timestamps)) if timestamps else False
        c4_ok = (len(dets_1) > 0 and all_within_duration and is_sorted)
        record_result(4, "Detections generated with realistic timestamps", c4_ok, f"Found {len(dets_1)} detections across {expected_duration}s")

        # CHECK 5 (2.c): Each detection has model_version, is_mock = 1, gps_source, and valid road_segment_id
        valid_fields = 0
        for d in dets_1:
            has_mv = bool(d.get("model_version"))
            has_mock = (d.get("is_mock") == 1 or d.get("is_mock") is True)
            has_gps = bool(d.get("gps_source"))
            has_seg = bool(d.get("road_segment_id") and str(d.get("road_segment_id")).startswith("RD-"))
            if has_mv and has_mock and has_gps and has_seg:
                valid_fields += 1
        c5_ok = (valid_fields == len(dets_1) and len(dets_1) > 0)
        record_result(5, "Each detection has model_version, is_mock=1, gps_source, road_segment_id (2.c)", c5_ok, f"{valid_fields}/{len(dets_1)} complete")

        # CHECK 6 (2.d): Every original and annotated evidence file exists and opens as an image
        valid_evidence_images = 0
        for d in dets_1:
            anno_url = d.get("evidence_anno_url") or d.get("evidence_uri") or ""
            orig_url = d.get("evidence_orig_url") or anno_url.replace("_anno.", "_orig.")

            anno_path = os.path.join(TEST_EVIDENCE_DIR, insp_id_1, os.path.basename(anno_url))
            orig_path = os.path.join(TEST_EVIDENCE_DIR, insp_id_1, os.path.basename(orig_url))

            anno_ok = False
            orig_ok = False
            if os.path.exists(anno_path):
                try:
                    with Image.open(anno_path) as im_a:
                        im_a.verify()
                    anno_ok = True
                except Exception:
                    pass

            if os.path.exists(orig_path):
                try:
                    with Image.open(orig_path) as im_o:
                        im_o.verify()
                    orig_ok = True
                except Exception:
                    pass

            if anno_ok and orig_ok:
                valid_evidence_images += 1

        c6_ok = (valid_evidence_images == len(dets_1) and len(dets_1) > 0)
        record_result(6, "Every original and annotated evidence file exists and opens as an image (2.d)", c6_ok, f"{valid_evidence_images}/{len(dets_1)} verified")

        # CHECK 7 (2.e): Same video processed twice gives identical detections
        create_res_2 = httpx.post(
            f"{base_url}/api/inspections",
            headers=auth_headers,
            json={"name": "Duplicate Consistency Test", "road_id": "RD-NH48", "road_name": "NH-48", "source_type": "Vehicle Camera", "model_version": "RoadDefect-v1.0"}
        )
        insp_id_2 = create_res_2.json()["id"]
        with open(video_path_1, "rb") as vf:
            httpx.post(f"{base_url}/api/inspections/{insp_id_2}/upload", headers=auth_headers, files={"file": ("real_survey_10s.mp4", vf, "video/mp4")})
        httpx.post(f"{base_url}/api/inspections/{insp_id_2}/start", headers=auth_headers)

        for _ in range(60):
            st = httpx.get(f"{base_url}/api/inspections/{insp_id_2}/status", headers=auth_headers).json()
            if st.get("status") in ["COMPLETED", "FAILED"]:
                break
            time.sleep(0.3)

        dets_2 = httpx.get(f"{base_url}/api/inspections/{insp_id_2}/detections", headers=auth_headers).json()
        identical_dets = (len(dets_1) == len(dets_2))
        if identical_dets:
            for d1, d2 in zip(dets_1, dets_2):
                if (
                    d1["frame_id"] != d2["frame_id"] or
                    d1["defect_type"] != d2["defect_type"] or
                    d1["severity"] != d2["severity"] or
                    d1["confidence"] != d2["confidence"] or
                    d1["bbox"] != d2["bbox"] or
                    d1["latitude"] != d2["latitude"] or
                    d1["longitude"] != d2["longitude"]
                ):
                    identical_dets = False
                    break

        c7_ok = identical_dets
        record_result(7, "The same video processed twice gives identical detections (2.e)", c7_ok, f"Detections matched: {len(dets_2)} == {len(dets_1)}")

        # CHECK 8 (2.f): Corrupt file renamed .mp4 ends FAILED with readable message
        corrupt_path = os.path.join(TEST_SCRATCH_DIR, "corrupt_video.mp4")
        with open(corrupt_path, "wb") as f_corrupt:
            f_corrupt.write(b"NOT_A_VALID_MP4_CORRUPT_HEADER_BYTES_FOR_TESTING")

        create_res_3 = httpx.post(
            f"{base_url}/api/inspections",
            headers=auth_headers,
            json={"name": "Corrupt Video Test", "road_id": "RD-NH48", "road_name": "NH-48", "source_type": "Vehicle Camera", "model_version": "RoadDefect-v1.0"}
        )
        insp_id_3 = create_res_3.json()["id"]
        with open(corrupt_path, "rb") as cf:
            httpx.post(f"{base_url}/api/inspections/{insp_id_3}/upload", headers=auth_headers, files={"file": ("corrupt_video.mp4", cf, "video/mp4")})
        httpx.post(f"{base_url}/api/inspections/{insp_id_3}/start", headers=auth_headers)

        corrupt_terminal = None
        corrupt_err_msg = ""
        for _ in range(30):
            st = httpx.get(f"{base_url}/api/inspections/{insp_id_3}/status", headers=auth_headers).json()
            if st.get("status") in ["COMPLETED", "FAILED"]:
                corrupt_terminal = st.get("status")
                corrupt_err_msg = st.get("error_message", "")
                break
            time.sleep(0.2)

        c8_ok = (corrupt_terminal == "FAILED" and "could not be read" in corrupt_err_msg.lower())
        record_result(8, "Corrupt file renamed .mp4 ends FAILED with readable message (2.f)", c8_ok, f"Status: {corrupt_terminal}, Msg: '{corrupt_err_msg}'")

        # CHECK 9: Starting already-processing inspection rejected with 409
        video_path_2 = os.path.join(TEST_SCRATCH_DIR, "survey_20s.mp4")
        create_test_mp4(video_path_2, duration_sec=20, fps=10)

        conflict_insp = httpx.post(
            f"{base_url}/api/inspections",
            headers=auth_headers,
            json={"name": "Conflict Test Survey", "road_id": "RD-NH48", "road_name": "NH-48", "source_type": "Vehicle Camera", "model_version": "RoadDefect-v1.0"}
        ).json()
        with open(video_path_2, "rb") as vf2:
            httpx.post(f"{base_url}/api/inspections/{conflict_insp['id']}/upload", headers=auth_headers, files={"file": ("survey_20s.mp4", vf2, "video/mp4")})

        first_start = httpx.post(f"{base_url}/api/inspections/{conflict_insp['id']}/start", headers=auth_headers)
        assert first_start.status_code == 200

        second_start = httpx.post(f"{base_url}/api/inspections/{conflict_insp['id']}/start", headers=auth_headers)
        c9_ok = (second_start.status_code == 409)
        record_result(9, "Starting already-processing inspection rejected with 409", c9_ok, f"HTTP status: {second_start.status_code}")

        # Wait for conflict inspection to complete
        for _ in range(60):
            st = httpx.get(f"{base_url}/api/inspections/{conflict_insp['id']}/status", headers=auth_headers).json()
            if st["status"] in ["COMPLETED", "FAILED"]:
                break
            time.sleep(0.2)

        # CHECK 10: Killing and restarting server marks job FAILED with restart message
        restart_insp = httpx.post(
            f"{base_url}/api/inspections",
            headers=auth_headers,
            json={"name": "Restart Recovery Test", "road_id": "RD-NH48", "road_name": "NH-48", "source_type": "Vehicle Camera", "model_version": "RoadDefect-v1.0"}
        ).json()
        with psycopg.connect(TEST_DATABASE_URL) as db_conn:
            with db_conn.cursor() as db_cursor:
                db_cursor.execute("UPDATE inspections SET status = 'PROCESSING', current_stage = 'AI Perception Inference' WHERE id = %s", (restart_insp["id"],))
            db_conn.commit()

        server_proc.terminate()
        server_proc.wait(timeout=5)

        server_proc = start_server(test_port)
        wait_for_server(base_url, timeout_sec=20)

        restarted_status = httpx.get(f"{base_url}/api/inspections/{restart_insp['id']}/status", headers=auth_headers).json()
        expected_restart_msg = "Processing was interrupted by a server restart."
        c10_ok = (restarted_status["status"] == "FAILED" and restarted_status.get("error_message") == expected_restart_msg)
        record_result(10, "Killing and restarting server marks job FAILED with restart message", c10_ok, f"Status: {restarted_status['status']}, Message: '{restarted_status.get('error_message')}'")

        # CHECK 11: Segment metrics and alerts updated, map/analytics return data
        map_defects = httpx.get(f"{base_url}/api/map/defects?inspection_id={insp_id_1}", headers=auth_headers).json()
        analytics_cond = httpx.get(f"{base_url}/api/analytics/condition?inspection_id={insp_id_1}", headers=auth_headers).json()
        analytics_over = httpx.get(f"{base_url}/api/analytics/overview?inspection_id={insp_id_1}", headers=auth_headers).json()
        road_segs = httpx.get(f"{base_url}/api/road-segments?inspection_id={insp_id_1}", headers=auth_headers).json()

        c11_ok = (
            len(map_defects.get("features", [])) == len(dets_1) and
            analytics_cond.get("methodology") == "PoC condition score" and
            analytics_over.get("total_defects") == len(dets_1) and
            len(road_segs) > 0
        )
        record_result(11, "Segment metrics and alerts updated, map/analytics return data", c11_ok, f"{len(map_defects.get('features', []))} map defects, {len(road_segs)} segments")

        # CHECK 12: PDF contains 'PoC Inspection Report' & mock note, no 'official' or 'PCI'
        pdf_gen = httpx.post(f"{base_url}/api/reports?inspection_id={insp_id_1}", headers=auth_headers)
        assert pdf_gen.status_code == 200
        pdf_url = pdf_gen.json()["pdf_url"]
        pdf_download = httpx.get(f"{base_url}{pdf_url}", headers=auth_headers)
        assert pdf_download.status_code == 200

        pdf_temp_path = os.path.join(TEST_SCRATCH_DIR, "check12_report.pdf")
        with open(pdf_temp_path, "wb") as f_pdf:
            f_pdf.write(pdf_download.content)

        pdf_reader = PdfReader(pdf_temp_path)
        pdf_text = " ".join(page.extract_text() or "" for page in pdf_reader.pages)

        has_poc_title = "PoC Inspection Report" in pdf_text
        has_mock_note = "Scores and priorities are PoC workflow categories, not engineering standards." in pdf_text
        has_mock_model = "Mock CV" in pdf_text
        no_official = "official" not in pdf_text.lower()
        no_pci = "pci" not in pdf_text.lower()

        c12_ok = (has_poc_title and has_mock_note and has_mock_model and no_official and no_pci)
        record_result(12, "PDF contains 'PoC Inspection Report' & mock note, no 'official' or 'PCI'", c12_ok, f"PoC title: {has_poc_title}, Mock note: {has_mock_note}, No official: {no_official}, No PCI: {no_pci}")

        # CHECK 13: UI text search finds none of forbidden phrases
        forbidden = ["SQLite + PostGIS", "PCI Standard Equivalent", "official"]
        found_forbidden = []
        for root, _, files in os.walk(FRONTEND_DIR):
            for file in files:
                if file.endswith(('.html', '.js', '.css')):
                    filepath = os.path.join(root, file)
                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f_ui:
                        content_ui = f_ui.read()
                        for term in forbidden:
                            if term.lower() in content_ui.lower():
                                found_forbidden.append((file, term))

        c13_ok = (len(found_forbidden) == 0)
        record_result(13, "UI search finds none of: 'SQLite + PostGIS', 'PCI Standard Equivalent', 'official'", c13_ok, f"Matches: {found_forbidden}")

        # CHECK 14: REQUIREMENT 6 Check - DEMO-001 still has 24 defects with RD-014 at 48/100 condition and 83/100 risk AFTER processing NEW video (BEFORE any demo reset)
        demo_overview_before_reset = httpx.get(f"{base_url}/api/analytics/overview?inspection_id=DEMO-001", headers=auth_headers).json()
        rd014_before_reset = httpx.get(f"{base_url}/api/road-segments/RD-014?inspection_id=DEMO-001", headers=auth_headers).json()

        c14_ok = (
            demo_overview_before_reset.get("total_defects") == 24 and
            float(rd014_before_reset.get("condition_score", 0.0)) == 48.0 and
            float(rd014_before_reset.get("risk_score", 0.0)) == 83.0
        )
        record_result(14, "DEMO-001 still has 24 defects with RD-014 at 48 and 83 after processing NEW video (before any demo reset)", c14_ok, f"Defects: {demo_overview_before_reset.get('total_defects')}, RD-014 condition: {rd014_before_reset.get('condition_score')}, risk: {rd014_before_reset.get('risk_score')}")

        # CHECK 15: PostGIS Spatial Nearest Segment Assignment Check
        # Test near RD-014 (approx lat: 19.0760, lon: 72.8777)
        spatial_insp = httpx.post(
            f"{base_url}/api/inspections",
            headers=auth_headers,
            json={"name": "Spatial PostGIS Ingestion Test", "road_id": "RD-014", "road_name": "Western Express Highway", "source_type": "Vehicle Camera", "model_version": "RoadDefect-v1.0"}
        ).json()
        spatial_id = spatial_insp["id"]

        ingest_payload = [
            {
                "detection_id": "SPATIAL_014",
                "frame_id": 100,
                "timestamp": 10.0,
                "class": "pothole",
                "confidence": 0.95,
                "bbox": [100, 150, 200, 250],
                "severity": "high",
                "latitude": 19.0650,
                "longitude": 73.1750,
                "evidence_uri": "/static/media/evidence/mock.jpg"
            },
            {
                "detection_id": "SPATIAL_FAR",
                "frame_id": 200,
                "timestamp": 20.0,
                "class": "crack",
                "confidence": 0.88,
                "bbox": [50, 50, 150, 150],
                "severity": "low",
                "latitude": 28.6139,
                "longitude": 77.2090,
                "evidence_uri": "/static/media/evidence/mock.jpg"
            }
        ]
        ingest_res = httpx.post(f"{base_url}/api/inspections/{spatial_id}/detections/ingest", headers=auth_headers, json=ingest_payload)
        assert ingest_res.status_code == 200

        spatial_dets = httpx.get(f"{base_url}/api/inspections/{spatial_id}/detections", headers=auth_headers).json()
        det_014 = next((d for d in spatial_dets if d["detection_id"] == "SPATIAL_014"), None)
        det_far = next((d for d in spatial_dets if d["detection_id"] == "SPATIAL_FAR"), None)

        c15_ok = (
            det_014 is not None and det_014.get("road_segment_id") == "RD-014" and
            det_far is not None and bool(det_far.get("road_segment_id"))
        )
        record_result(15, "PostGIS spatial nearest segment: near RD-014 assigns to RD-014, far coordinate assigns cleanly", c15_ok, f"Near: {det_014.get('road_segment_id') if det_014 else None}, Far: {det_far.get('road_segment_id') if det_far else None}")

        # CHECK 16: GeoJSON structure verification for /api/map/defects and /api/map/segments
        geojson_defects = httpx.get(f"{base_url}/api/map/defects?inspection_id=DEMO-001", headers=auth_headers).json()
        geojson_segments = httpx.get(f"{base_url}/api/map/segments?inspection_id=DEMO-001", headers=auth_headers).json()

        valid_def_geojson = (
            geojson_defects.get("type") == "FeatureCollection" and
            isinstance(geojson_defects.get("features"), list) and
            len(geojson_defects["features"]) > 0 and
            geojson_defects["features"][0].get("geometry", {}).get("type") == "Point" and
            "properties" in geojson_defects["features"][0]
        )
        valid_seg_geojson = (
            geojson_segments.get("type") == "FeatureCollection" and
            isinstance(geojson_segments.get("features"), list) and
            len(geojson_segments["features"]) > 0 and
            geojson_segments["features"][0].get("geometry", {}).get("type") == "LineString" and
            "properties" in geojson_segments["features"][0]
        )
        c16_ok = (valid_def_geojson and valid_seg_geojson)
        record_result(16, "/api/map/defects and /api/map/segments return valid GeoJSON FeatureCollections", c16_ok, f"Defects: {len(geojson_defects.get('features', []))}, Segments: {len(geojson_segments.get('features', []))}")

        # CHECK 17: Migration Script idempotency and correctness test on temporary SQLite fixture
        import sqlite3
        fixture_sqlite = os.path.join(TEST_SCRATCH_DIR, "fixture.db")
        f_conn = sqlite3.connect(fixture_sqlite)
        f_cur = f_conn.cursor()
        f_cur.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT, role TEXT, full_name TEXT, is_active INTEGER, created_at TEXT);")
        f_cur.execute("INSERT INTO users VALUES (1, 'miguser', 'hash_secret', 'inspector', 'Migration User', 1, '2026-09-30');")
        f_cur.execute("CREATE TABLE inspections (id TEXT PRIMARY KEY, name TEXT, road_id TEXT, road_name TEXT, source_type TEXT, status TEXT, total_frames INTEGER, processed_frames INTEGER, fps REAL, duration_seconds REAL, video_path TEXT, model_version TEXT, error_message TEXT, created_by TEXT, created_at TEXT, completed_at TEXT);")
        f_cur.execute("INSERT INTO inspections VALUES ('INSP-MIG', 'Mig Insp', 'RD-014', 'WEH', 'Vehicle Camera', 'COMPLETED', 100, 100, 10.0, 10.0, '/video/m.mp4', 'RoadDefect-v1.0', NULL, 'miguser', '2026-09-30', '2026-09-30');")
        f_cur.execute("CREATE TABLE road_segments (id TEXT PRIMARY KEY, name TEXT, road_id TEXT, road_name TEXT, start_km REAL, end_km REAL, surface_type TEXT, lanes INTEGER, speed_limit INTEGER, geometry_json TEXT, created_at TEXT);")
        f_cur.execute("INSERT INTO road_segments VALUES ('RD-014', 'Segment 14', 'WEH', 'WEH', 0.0, 1.0, 'Asphalt', 6, 80, '[[19.0760, 72.8777], [19.0770, 72.8787]]', '2026-09-30');")
        f_cur.execute("CREATE TABLE detections (id TEXT PRIMARY KEY, inspection_id TEXT, frame_id INTEGER, timestamp REAL, defect_type TEXT, confidence REAL, severity TEXT, bbox_json TEXT, latitude REAL, longitude REAL, road_segment_id TEXT, chainage_km REAL, evidence_uri TEXT, evidence_orig_uri TEXT, is_mock INTEGER, gps_source TEXT, model_version TEXT, created_at TEXT);")
        f_cur.execute("INSERT INTO detections VALUES ('DET-MIG-1', 'INSP-MIG', 10, 1.0, 'pothole', 0.95, 'high', '[10,20,30,40]', 19.0760, 72.8777, 'RD-014', 0.1, '/evidence/e1.jpg', '/evidence/e1_orig.jpg', 1, 'gps_log', 'RoadDefect-v1.0', '2026-09-30');")
        f_cur.execute("CREATE TABLE segment_metrics (id SERIAL, inspection_id TEXT, segment_id TEXT, pci_score REAL, condition_score REAL, risk_score REAL, pothole_count INTEGER, crack_count INTEGER, rutting_count INTEGER, raveling_count INTEGER, total_defects INTEGER, primary_defect TEXT, priority TEXT, treatment_type TEXT, est_cost_inr REAL, calculated_at TEXT);")
        f_cur.execute("INSERT INTO segment_metrics VALUES (1, 'INSP-MIG', 'RD-014', 80.0, 80.0, 20.0, 1, 0, 0, 0, 1, 'pothole', 'low', 'Routine', 5000.0, '2026-09-30');")
        f_cur.execute("CREATE TABLE alerts (id SERIAL, inspection_id TEXT, segment_id TEXT, detection_id TEXT, alert_type TEXT, severity TEXT, title TEXT, message TEXT, is_read INTEGER, created_at TEXT);")
        f_cur.execute("CREATE TABLE audit_logs (id SERIAL, user_id TEXT, username TEXT, action TEXT, target_type TEXT, target_id TEXT, details TEXT, ip_address TEXT, timestamp TEXT);")
        f_cur.execute("CREATE TABLE model_versions (id SERIAL, version_id TEXT UNIQUE, name TEXT, framework TEXT, task TEXT, classes_json TEXT, input_resolution TEXT, weights_path TEXT, is_active INTEGER, is_mock INTEGER, created_at TEXT);")
        f_conn.commit()
        f_conn.close()

        mig_test_db = f"ztracs_test_mig_{secrets.token_hex(4)}"
        mig_test_url = BASE_PG_URL.rsplit("/", 1)[0] + f"/{mig_test_db}"
        with psycopg.connect(BASE_PG_URL, autocommit=True) as aconn:
            with aconn.cursor() as acur:
                acur.execute(f"CREATE DATABASE {mig_test_db};")
        with psycopg.connect(mig_test_url, autocommit=True) as mconn:
            with mconn.cursor() as mcur:
                mcur.execute("CREATE EXTENSION IF NOT EXISTS postgis;")

        mig_env = os.environ.copy()
        mig_env["DATABASE_URL"] = mig_test_url
        mig_env["PYTHONPATH"] = PROJECT_ROOT

        # Run 1
        mig_run1 = subprocess.run([sys.executable, "backend/migrate_sqlite_to_postgres.py", fixture_sqlite], cwd=PROJECT_ROOT, env=mig_env, capture_output=True, text=True)
        # Run 2 (idempotent verification)
        mig_run2 = subprocess.run([sys.executable, "backend/migrate_sqlite_to_postgres.py", fixture_sqlite], cwd=PROJECT_ROOT, env=mig_env, capture_output=True, text=True)

        with psycopg.connect(mig_test_url, row_factory=dict_row) as mconn:
            with mconn.cursor() as mcur:
                mcur.execute("SELECT count(*) as cnt FROM users;")
                u_cnt = mcur.fetchone()["cnt"]
                mcur.execute("SELECT count(*) as cnt FROM detections;")
                d_cnt = mcur.fetchone()["cnt"]
                mcur.execute("SELECT ST_AsText(geom) as geom_txt FROM detections WHERE id = 'DET-MIG-1';")
                det_geom_row = mcur.fetchone()
                det_geom_txt = det_geom_row["geom_txt"] if det_geom_row else ""

        with psycopg.connect(BASE_PG_URL, autocommit=True) as aconn:
            with aconn.cursor() as acur:
                acur.execute(f"DROP DATABASE {mig_test_db} (FORCE);")

        c17_ok = (
            mig_run1.returncode == 0 and
            mig_run2.returncode == 0 and
            u_cnt >= 1 and
            d_cnt == 1 and
            "POINT" in det_geom_txt and
            "hash_secret" not in mig_run1.stdout and
            "hash_secret" not in mig_run1.stderr
        )
        record_result(17, "Migration script copies SQLite fixture, is idempotent on rerun, and suppresses hashes", c17_ok, f"Run1: {mig_run1.returncode}, Run2: {mig_run2.returncode}, Geom: {det_geom_txt}")

        # CHECK 18: Demo reset check
        reset_res = httpx.post(f"{base_url}/api/demo/reset", headers=auth_headers)
        assert reset_res.status_code == 200
        demo_overview = httpx.get(f"{base_url}/api/analytics/overview?inspection_id=DEMO-001", headers=auth_headers).json()
        rd014_res = httpx.get(f"{base_url}/api/road-segments/RD-014?inspection_id=DEMO-001", headers=auth_headers).json()
        c18_ok = (
            demo_overview.get("total_defects") == 24 and
            float(rd014_res.get("condition_score", 0.0)) == 48.0 and
            float(rd014_res.get("risk_score", 0.0)) == 83.0
        )
        record_result(18, "DEMO-001 has 24 defects and RD-014 at 48/100 and 83/100 after demo reset", c18_ok, f"Defects: {demo_overview.get('total_defects')}, Condition: {rd014_res.get('condition_score')}, Risk: {rd014_res.get('risk_score')}")

        # CHECK 19: tests/test_security.py passes all checks
        sec_res = subprocess.run([sys.executable, "tests/test_security.py"], cwd=PROJECT_ROOT, capture_output=True, text=True)
        c19_ok = (sec_res.returncode == 0 and "FAIL:" not in sec_res.stdout and "Passed: 30" in sec_res.stdout)
        record_result(19, "tests/test_security.py still passes all checks (30/30)", c19_ok, f"Exit code: {sec_res.returncode}")

        # CHECK 20 (A2): PDF dynamically generated, unhardcoded, counts match DB, zero-defect handled
        insp_nondemo = "INS-TEST-A2"
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO inspections (
                        id, name, road_id, road_name, source_type, created_at, started_at, completed_at,
                        status, model_version, video_url, total_frames, processed_frames, defect_count,
                        progress_percent, current_stage, error_message, is_mock
                    ) VALUES (%s, %s, %s, %s, %s, NOW(), NOW(), NOW(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (insp_nondemo, "State Highway 55 Survey", "RD-001", "SH-55 Corridor", "Vehicle", "COMPLETED", "RoadDefect-v2.1", "sh55.mp4", 200, 200, 5, 100, "COMPLETED", None, 1))

                # Two classes (pothole, crack) with mixed severities (critical, high, medium, low)
                cur.execute("""
                    INSERT INTO detections (
                        id, detection_id, inspection_id, frame_id, timestamp, defect_type,
                        confidence, severity, bbox_json, latitude, longitude, geom,
                        road_segment_id, evidence_orig_url, evidence_anno_url, model_version, is_mock, gps_source
                    ) VALUES 
                    (%s, %s, %s, 10, 1.0, 'pothole', 0.965, 'critical', '[]', 19.1234, 73.5678, ST_SetSRID(ST_MakePoint(73.5678, 19.1234), 4326), 'RD-001', 'orig1.jpg', 'anno1.jpg', 'RoadDefect-v2.1', 1, 'GPS'),
                    (%s, %s, %s, 15, 1.5, 'pothole', 0.880, 'high', '[]', 19.1239, 73.5682, ST_SetSRID(ST_MakePoint(73.5682, 19.1239), 4326), 'RD-001', 'orig1b.jpg', 'anno1b.jpg', 'RoadDefect-v2.1', 1, 'GPS'),
                    (%s, %s, %s, 20, 2.0, 'crack', 0.840, 'medium', '[]', 19.1244, 73.5688, ST_SetSRID(ST_MakePoint(73.5688, 19.1244), 4326), 'RD-001', 'orig2.jpg', 'anno2.jpg', 'RoadDefect-v2.1', 1, 'GPS'),
                    (%s, %s, %s, 25, 2.5, 'crack', 0.780, 'medium', '[]', 19.1249, 73.5693, ST_SetSRID(ST_MakePoint(73.5693, 19.1249), 4326), 'RD-001', 'orig2b.jpg', 'anno2b.jpg', 'RoadDefect-v2.1', 1, 'GPS'),
                    (%s, %s, %s, 30, 3.0, 'crack', 0.650, 'low', '[]', 19.1254, 73.5698, ST_SetSRID(ST_MakePoint(73.5698, 19.1254), 4326), 'RD-001', 'orig3.jpg', 'anno3.jpg', 'RoadDefect-v2.1', 1, 'GPS')
                """, (
                    "DET-A2-001", "DET-A2-001", insp_nondemo,
                    "DET-A2-002", "DET-A2-002", insp_nondemo,
                    "DET-A2-003", "DET-A2-003", insp_nondemo,
                    "DET-A2-004", "DET-A2-004", insp_nondemo,
                    "DET-A2-005", "DET-A2-005", insp_nondemo
                ))

        pdf_a2_gen = httpx.post(f"{base_url}/api/reports?inspection_id={insp_nondemo}", headers=auth_headers)
        assert pdf_a2_gen.status_code == 200
        pdf_a2_url = pdf_a2_gen.json()["pdf_url"]
        pdf_a2_dl = httpx.get(f"{base_url}{pdf_a2_url}", headers=auth_headers)
        assert pdf_a2_dl.status_code == 200

        pdf_a2_path = os.path.join(TEST_SCRATCH_DIR, "check20_nondemo_report.pdf")
        with open(pdf_a2_path, "wb") as f_a2:
            f_a2.write(pdf_a2_dl.content)
        pdf_a2_reader = PdfReader(pdf_a2_path)
        pdf_a2_text = " ".join(page.extract_text() or "" for page in pdf_a2_reader.pages)

        # 1. Must not contain DEF-POT-00124 or Certified Highway
        no_hardcoded_flagship = "DEF-POT-00124" not in pdf_a2_text
        no_hardcoded_cert = "Certified Highway" not in pdf_a2_text

        # 2. Must contain own top detection ID (DET-A2-001, critical pothole)
        has_own_top_id = "DET-A2-001" in pdf_a2_text

        # 3. Compute expected per-class totals and per-severity counts directly from DB
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT defect_type,
                           COUNT(*) as total,
                           COUNT(*) FILTER (WHERE severity = 'critical') as critical,
                           COUNT(*) FILTER (WHERE severity = 'high') as high,
                           COUNT(*) FILTER (WHERE severity = 'medium') as medium,
                           COUNT(*) FILTER (WHERE severity = 'low') as low
                    FROM detections
                    WHERE inspection_id = %s
                    GROUP BY defect_type
                    ORDER BY defect_type
                """, (insp_nondemo,))
                expected_db_counts = cur.fetchall()

        # Assert each class row in the PDF table text shows exactly those DB counts
        counts_match = len(expected_db_counts) == 2
        for r_cnt in expected_db_counts:
            c_name = r_cnt["defect_type"].capitalize()
            tot, crit, hi, med, low = r_cnt["total"], r_cnt["critical"], r_cnt["high"], r_cnt["medium"], r_cnt["low"]
            pat = rf"{c_name}\s+{tot}\s+{crit}\s+{hi}\s+{med}\s+{low}"
            if not re.search(pat, pdf_a2_text):
                counts_match = False
                print(f"Check 20 count mismatch: pattern {pat} not found in PDF text")

        # 4. Zero-detection inspection must contain "No detections recorded."
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO inspections (
                        id, name, road_id, road_name, source_type, created_at, started_at, completed_at,
                        status, model_version, video_url, total_frames, processed_frames, defect_count,
                        progress_percent, current_stage, error_message, is_mock
                    ) VALUES (%s, %s, %s, %s, %s, NOW(), NOW(), NOW(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, ("INS-EMPTY-CHECK", "Empty Survey", "RD-001", "NH-48 Empty", "Video", "COMPLETED", "RoadDefect-v1.0", "empty.mp4", 100, 100, 0, 100, "COMPLETED", None, 1))

        pdf_empty_gen = httpx.post(f"{base_url}/api/reports?inspection_id=INS-EMPTY-CHECK", headers=auth_headers)
        assert pdf_empty_gen.status_code == 200
        pdf_empty_url = pdf_empty_gen.json()["pdf_url"]
        pdf_empty_dl = httpx.get(f"{base_url}{pdf_empty_url}", headers=auth_headers)
        assert pdf_empty_dl.status_code == 200

        pdf_empty_path = os.path.join(TEST_SCRATCH_DIR, "check20_empty_report.pdf")
        with open(pdf_empty_path, "wb") as f_empty:
            f_empty.write(pdf_empty_dl.content)
        pdf_empty_reader = PdfReader(pdf_empty_path)
        pdf_empty_text = " ".join(page.extract_text() or "" for page in pdf_empty_reader.pages)
        has_no_detections_msg = "No detections recorded." in pdf_empty_text

        c20_ok = (no_hardcoded_flagship and no_hardcoded_cert and has_own_top_id and counts_match and has_no_detections_msg)
        record_result(20, "Dynamic PDF: unhardcoded, top detection ID, counts match DB, zero-defect handled", c20_ok, f"No hardcoded: {no_hardcoded_flagship and no_hardcoded_cert}, Top ID: {has_own_top_id}, Counts match: {counts_match}, Zero msg: {has_no_detections_msg}")

        # -------------------------------------------------------------
        # CHECK 21: A3 & A4 - Real processed inspection embeds own evidence image,
        # and road without segments outputs "No segments recorded for this road" and 0.0 KM
        # -------------------------------------------------------------
        # A3: Test real processed inspection from Check 12 (saved at check12_report.pdf)
        pdf_proc_path = os.path.join(TEST_SCRATCH_DIR, "check12_report.pdf")
        assert os.path.exists(pdf_proc_path), "check12_report.pdf must exist"
        pdf_proc_reader = PdfReader(pdf_proc_path)
        proc_images = [img for page in pdf_proc_reader.pages for img in page.images]
        has_embedded_evidence = len(proc_images) > 0 and len(proc_images[0].data) > 1000

        # A4: Test inspection on road without segments
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO inspections (
                        id, name, road_id, road_name, source_type, created_at, started_at, completed_at,
                        status, model_version, video_url, total_frames, processed_frames, defect_count,
                        progress_percent, current_stage, error_message, is_mock
                    ) VALUES (%s, %s, %s, %s, %s, NOW(), NOW(), NOW(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, ("INS-NOSEGS-CHECK", "No Segments Survey", "RD-UNMAPPED-99", "Unmapped Rural Road", "Video", "COMPLETED", "RoadDefect-v1.0", "empty.mp4", 100, 100, 0, 100, "COMPLETED", None, 1))

        pdf_nosegs_gen = httpx.post(f"{base_url}/api/reports?inspection_id=INS-NOSEGS-CHECK", headers=auth_headers)
        assert pdf_nosegs_gen.status_code == 200
        pdf_nosegs_url = pdf_nosegs_gen.json()["pdf_url"]
        pdf_nosegs_dl = httpx.get(f"{base_url}{pdf_nosegs_url}", headers=auth_headers)
        assert pdf_nosegs_dl.status_code == 200

        pdf_nosegs_path = os.path.join(TEST_SCRATCH_DIR, "check21_nosegs_report.pdf")
        with open(pdf_nosegs_path, "wb") as f_nosegs:
            f_nosegs.write(pdf_nosegs_dl.content)
        pdf_nosegs_reader = PdfReader(pdf_nosegs_path)
        pdf_nosegs_text = " ".join(page.extract_text() or "" for page in pdf_nosegs_reader.pages)

        has_nosegs_msg = "No segments recorded for this road" in pdf_nosegs_text
        has_zero_km = "0.0 KM" in pdf_nosegs_text
        # Ensure it didn't fall back to unrelated road segments
        no_unrelated_segs = "Panvel Tollway Entry" not in pdf_nosegs_text and "RD-001" not in pdf_nosegs_text

        c21_ok = (has_embedded_evidence and has_nosegs_msg and has_zero_km and no_unrelated_segs)
        record_result(21, "Dynamic PDF: real evidence image embedded, zero-segment road handled with 0.0 KM", c21_ok, f"Images extracted: {len(proc_images)}, No-segs msg: {has_nosegs_msg}, 0.0 KM: {has_zero_km}, No unrelated fallback: {no_unrelated_segs}")

        # -------------------------------------------------------------
        # CHECK 22: B4 (2.5) Status names parity between backend enum and frontend badge cases
        # -------------------------------------------------------------
        from backend.models import InspectionStatus
        backend_statuses = set(s.value for s in InspectionStatus)
        with open("frontend/js/app.js", "r", encoding="utf-8") as f_app:
            app_js_text = f_app.read()
        badge_start = app_js_text.find("function getStatusBadge")
        badge_end = app_js_text.find("function isUrlExpiredOrExpiringSoon", badge_start)
        badge_fn_body = app_js_text[badge_start:badge_end]
        frontend_cases = set(re.findall(r"case\s+'([^']+)':", badge_fn_body))

        c22_ok = (backend_statuses == frontend_cases)
        record_result(22, "Status Enum Parity: frontend getStatusBadge matches backend InspectionStatus enum exactly", c22_ok, f"Backend: {len(backend_statuses)} statuses, Frontend: {len(frontend_cases)} cases")

        # CHECK 23: Configurable scoring weights API
        get_cfg_res = httpx.get(f"{base_url}/api/scoring/config", headers=auth_headers)
        cfg_data = get_cfg_res.json()
        orig_pothole_wt = cfg_data.get("pothole_weight", 1.5)

        # Viewer role forbidden on PUT
        httpx.post(f"{base_url}/api/auth/register", json={"username": "vieweruser_c23", "password": "Password123", "confirm_password": "Password123", "full_name": "Viewer C23"})
        v_login = httpx.post(f"{base_url}/api/auth/login", json={"username": "vieweruser_c23", "password": "Password123"})
        viewer_token = v_login.json().get("access_token") or v_login.json().get("token")
        viewer_headers = {"Authorization": f"Bearer {viewer_token}"}
        put_viewer_res = httpx.put(f"{base_url}/api/scoring/config", json={"pothole_weight": 2.5}, headers=viewer_headers)

        # Admin can update
        put_admin_res = httpx.put(f"{base_url}/api/scoring/config", json={"pothole_weight": 2.5}, headers=auth_headers)
        updated_cfg = put_admin_res.json()

        # Reset back
        httpx.put(f"{base_url}/api/scoring/config", json={"pothole_weight": orig_pothole_wt}, headers=auth_headers)

        # Assert that changing a weight changes the computed score
        from backend.scoring_engine import calculate_segment_condition
        from backend.models import ScoringConfig
        sample_defects = [{"defect_type": "pothole", "severity": "high"}]
        base_cfg = ScoringConfig(**cfg_data)
        base_score = calculate_segment_condition(1.0, sample_defects, base_cfg)["condition_score"]

        put_altered = httpx.put(f"{base_url}/api/scoring/config", json={"pothole_weight": 4.0}, headers=auth_headers)
        altered_cfg = ScoringConfig(**put_altered.json())
        new_score = calculate_segment_condition(1.0, sample_defects, altered_cfg)["condition_score"]
        httpx.put(f"{base_url}/api/scoring/config", json={"pothole_weight": orig_pothole_wt}, headers=auth_headers)

        c23_ok = (
            get_cfg_res.status_code == 200 and
            "pothole_weight" in cfg_data and
            put_viewer_res.status_code == 403 and
            put_admin_res.status_code == 200 and
            updated_cfg.get("pothole_weight") == 2.5 and
            new_score < base_score
        )
        record_result(23, "Configurable scoring weights: GET allows authenticated, PUT enforces admin RBAC and updates weights", c23_ok, f"GET: {get_cfg_res.status_code}, Viewer PUT: {put_viewer_res.status_code}, Admin PUT: {put_admin_res.status_code}, ScoreChanged: {base_score}->{new_score}")

        # CHECK 24: Highway Infrastructure Assets API
        assets_res = httpx.get(f"{base_url}/api/assets", headers=auth_headers)
        assets_data = assets_res.json()
        bridge_res = httpx.get(f"{base_url}/api/assets?asset_type=bridge", headers=auth_headers)
        bridge_data = bridge_res.json()

        c24_ok = (
            assets_res.status_code == 200 and
            len(assets_data) >= 5 and
            bridge_res.status_code == 200 and
            len(bridge_data) >= 1 and
            all(a["asset_type"] == "bridge" for a in bridge_data)
        )
        record_result(24, "Highway Infrastructure Assets: GET /api/assets returns corridor inventory and filters by type", c24_ok, f"Total: {len(assets_data)} assets, Bridges: {len(bridge_data)}")

        # CHECK 25: Report Metadata API (GET /api/reports/{id})
        rep_res = httpx.get(f"{base_url}/api/reports/DEMO-001", headers=auth_headers)
        rep_data = rep_res.json()
        rep_404 = httpx.get(f"{base_url}/api/reports/NON-EXISTING-INSP-ID", headers=auth_headers)

        c25_ok = (
            rep_res.status_code == 200 and
            rep_data.get("inspection_id") == "DEMO-001" and
            rep_data.get("pdf_url") == "/api/reports/DEMO-001/pdf" and
            rep_data.get("defect_count") == 24 and
            rep_404.status_code == 404
        )
        record_result(25, "Report Metadata: GET /api/reports/{id} returns inspection report details and 404s for invalid ID", c25_ok, f"Status: {rep_res.status_code}, Defects: {rep_data.get('defect_count')}, 404: {rep_404.status_code}")

        # -------------------------------------------------------------
        # CHECK 26: PDF High-Risk & Schematic Map Sections, Neutral PoC Wording, and Empty-Case Messages
        # -------------------------------------------------------------
        pdf_demo_gen = httpx.post(f"{base_url}/api/reports?inspection_id=DEMO-001", headers=auth_headers)
        assert pdf_demo_gen.status_code == 200
        pdf_demo_url = pdf_demo_gen.json()["pdf_url"]
        pdf_demo_dl = httpx.get(f"{base_url}{pdf_demo_url}", headers=auth_headers)
        assert pdf_demo_dl.status_code == 200
        pdf_demo_path = os.path.join(TEST_SCRATCH_DIR, "check26_demo_report.pdf")
        with open(pdf_demo_path, "wb") as f_demo:
            f_demo.write(pdf_demo_dl.content)
        pdf_demo_reader = PdfReader(pdf_demo_path)
        pdf_demo_text = " ".join(page.extract_text() or "" for page in pdf_demo_reader.pages)

        has_map_section = "Corridor segment overview (schematic)" in pdf_demo_text
        has_high_risk_section = "High-Risk Corridor Segments" in pdf_demo_text
        has_rd014_in_high_risk = "RD-014" in pdf_demo_text
        no_mandated_action = "Mandated Action" not in pdf_demo_text
        no_deadlines = "48h" not in pdf_demo_text and "30 days" not in pdf_demo_text
        has_poc_advisory = "Recommended Intervention (PoC Advisory)" in pdf_demo_text

        # Verify empty-case messages on an empty inspection (INS-NOSEGS-CHECK)
        has_empty_map_msg = "No GIS corridor geometry or segments available for this inspection" in pdf_nosegs_text
        has_empty_hr_msg = "No high-risk segments identified in this survey corridor" in pdf_nosegs_text

        c26_ok = (
            has_map_section and
            has_high_risk_section and
            has_rd014_in_high_risk and
            no_mandated_action and
            no_deadlines and
            has_poc_advisory and
            has_empty_map_msg and
            has_empty_hr_msg
        )
        record_result(
            26,
            "PDF High-Risk & Schematic Map: sections present in DEMO-001, neutral PoC wording, empty-case messages verified",
            c26_ok,
            f"Map: {has_map_section}, HighRisk: {has_high_risk_section}, NoDeadlines: {no_deadlines}, EmptyMsgs: {has_empty_map_msg and has_empty_hr_msg}"
        )

        # -------------------------------------------------------------
        # CHECK 27: Scoring Engine RD-014 (48/83) & Seeding Resilience with SCORING_* Overrides
        # -------------------------------------------------------------
        from backend.models import ScoringConfig
        from backend.scoring_engine import calculate_segment_condition, calculate_segment_risk
        from backend.seed_data import seed_demo_data

        with psycopg.connect(TEST_DATABASE_URL, row_factory=dict_row) as check_conn:
            with check_conn.cursor() as cur:
                cur.execute("""
                    SELECT defect_type, severity, confidence, latitude, longitude
                    FROM detections
                    WHERE inspection_id = 'DEMO-001' AND road_segment_id = 'RD-014'
                """)
                rd014_db_defects = cur.fetchall()

        default_cfg = ScoringConfig()
        has_crit = any(d["severity"] == "critical" for d in rd014_db_defects)
        cond_calc = calculate_segment_condition(1.0, rd014_db_defects, config=default_cfg)
        risk_calc = calculate_segment_risk(cond_calc["condition_score"], 0.95, 0.98, has_crit, config=default_cfg)

        engine_48_83 = (cond_calc["condition_score"] == 48.0 and risk_calc["risk_score"] == 83.0)

        # Test seeding resilience when SCORING_* env vars are modified
        os.environ["SCORING_TYPE_SCORE_WEIGHT"] = "0.99"
        os.environ["SCORING_SEV_PENALTY_WEIGHT"] = "0.99"
        seeding_survived = False
        try:
            seed_demo_data(force=True)
            seeding_survived = True
        except Exception as e:
            seeding_survived = False
        finally:
            os.environ.pop("SCORING_TYPE_SCORE_WEIGHT", None)
            os.environ.pop("SCORING_SEV_PENALTY_WEIGHT", None)
            # Re-seed with standard defaults
            seed_demo_data(force=True)

        c27_ok = engine_48_83 and seeding_survived
        record_result(
            27,
            "Scoring Engine RD-014 (48/83) engine calculation & seeding resilience with SCORING_* overrides",
            c27_ok,
            f"EngineRD014: cond={cond_calc.get('condition_score')}, risk={risk_calc.get('risk_score')} (48.0/83.0: {engine_48_83}), SeedingSurvivedOverrides: {seeding_survived}"
        )

    finally:
        if server_proc:
            server_proc.terminate()
            try:
                server_proc.wait(timeout=4)
            except Exception:
                server_proc.kill()
        # Clean up temporary test data directory
        shutil.rmtree(TEST_TMP_DIR, ignore_errors=True)

        # Drop ephemeral PostgreSQL database (Item 6)
        print(f"Tearing down ephemeral PostgreSQL database: {TEST_DB_NAME}")
        try:
            with psycopg.connect(BASE_PG_URL, autocommit=True) as teardown_conn:
                with teardown_conn.cursor() as teardown_cur:
                    teardown_cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} (FORCE);")
        except Exception as e:
            print(f"Warning: Failed to drop test db {TEST_DB_NAME}: {e}")

    print("\n" + "=" * 60)
    print("  PIPELINE VERIFICATION SUMMARY")
    print("=" * 60)
    passed_count = sum(1 for _, _, status, _ in results_table if status == "PASS")
    total_count = len(results_table)
    print(f"Total Checks: {total_count} | PASSED: {passed_count} | FAILED: {total_count - passed_count}")
    for num, desc, st, det in results_table:
        print(f"{num:3d}. [{st}] {desc} {f'-- {det}' if det else ''}")

    if passed_count < total_count:
        sys.exit(1)
    print("ALL PIPELINE CHECKS PASSED!")


if __name__ == "__main__":
    main()
