"""
Z-TRACS Road Intelligence - FastAPI Application with hardened auth, RBAC, and Part C updates.
"""
import json
import os
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

import hashlib
import hmac
import time
from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles

from backend.ai_pipeline import pipeline_worker
from backend.auth import (
    authenticate_token_with_db,
    check_rate_limit,
    create_access_token,
    decode_access_token,
    get_current_user,
    get_media_signing_key,
    hash_password,
    require_env,
    require_role,
    security_bearer,
    verify_password,
)
from backend.database import get_connection, init_db, record_audit_log
from backend.seed_data import seed_demo_data
from backend.models import (
    CVDetectionPayload,
    InspectionCreate,
    InspectionResponse,
    InspectionStatus,
    CVAIResultsPayload,
    CVStatusUpdatePayload,
    CVFailedPayload,
)

from backend.reports import REPORTS_DIR, generate_inspection_pdf
from backend.s3_client import (
    is_s3_enabled,
    upload_file,
    get_file_bytes,
    get_file_stream,
    file_exists,
    generate_presigned_upload_url,
    test_s3_connection,
    get_s3_config,
)
from backend.scoring_engine import SCORING_CONFIG, calculate_segment_condition, calculate_segment_risk, get_scoring_config, update_scoring_config

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.getenv("DATA_DIR", os.path.join(PROJECT_ROOT, "data"))
STATIC_DIR = os.path.join(PROJECT_ROOT, "static")
FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")
VIDEO_DIR = os.getenv("VIDEO_DIR", os.path.join(STATIC_DIR, "media", "video"))
EVIDENCE_DIR = os.getenv("EVIDENCE_DIR", os.path.join(STATIC_DIR, "media", "evidence"))
try:
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(STATIC_DIR, exist_ok=True)
    os.makedirs(VIDEO_DIR, exist_ok=True)
    os.makedirs(EVIDENCE_DIR, exist_ok=True)
except OSError:
    pass
MAX_UPLOAD_BYTES = 500 * 1024 * 1024
UPLOAD_CHUNK_SIZE = 1024 * 1024


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        require_env()
    except RuntimeError as exc:
        print(f"Startup error: {exc}")
        raise
    init_db()
    # D5: On server startup, mark interrupted processing jobs as FAILED
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE inspections SET status = 'FAILED', error_message = 'Processing was interrupted by a server restart.'
        WHERE status IN ('PROCESSING', 'AI_ANALYSIS', 'GEO_REFERENCING', 'AGGREGATION', 'QUEUED')
    """)
    conn.commit()
    conn.close()

    seed_demo_data(force=False)
    yield


# F29a: /docs and /openapi.json disabled unless ENABLE_DOCS=1
_docs_enabled = os.getenv("ENABLE_DOCS", "0") == "1"
app = FastAPI(
    title="Z-TRACS Road Intelligence API",
    description="Unified AI platform converting road imagery into geospatially grounded road-condition intelligence.",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000,http://localhost:3000,http://127.0.0.1:3000").split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS", "HEAD"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Range"],
)

# F25: Security headers middleware
from starlette.middleware.base import BaseHTTPMiddleware

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        path = request.url.path
        if path.startswith("/docs") or path.startswith("/redoc") or path.startswith("/openapi"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "font-src 'self' data: https://cdn.jsdelivr.net; "
                "img-src 'self' https://cdn.jsdelivr.net data: blob:; "
                "connect-src 'self'"
            )
        else:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self'; "
                "style-src 'self' 'unsafe-inline'; "
                "font-src 'self' data:; "
                "img-src 'self' https://*.openstreetmap.org https://*.tile.openstreetmap.org data: blob:; "
                "media-src 'self' blob:; "
                "connect-src 'self'; "
                "frame-ancestors 'none'; "
                "object-src 'none'; "
                "base-uri 'self'"
            )
        return response

app.add_middleware(SecurityHeadersMiddleware)

# F27: Only serve frontend/CSS/JS publicly — evidence, reports and videos are auth-protected.
# Static assets (CSS, JS, icons): public — needed before login screen renders.
app.mount("/app", StaticFiles(directory=FRONTEND_DIR), name="frontend_app")
app.mount("/css", StaticFiles(directory=os.path.join(FRONTEND_DIR, "css")), name="frontend_css")
app.mount("/js", StaticFiles(directory=os.path.join(FRONTEND_DIR, "js")), name="frontend_js")
if os.path.isdir(os.path.join(FRONTEND_DIR, "vendor")):
    app.mount("/vendor", StaticFiles(directory=os.path.join(FRONTEND_DIR, "vendor")), name="frontend_vendor")


@app.get("/")
async def serve_index():
    index_file = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "Z-TRACS API running."}


@app.get("/api/health")
async def healthcheck():
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT PostGIS_Version()")
        row = cur.fetchone()
        postgis_ver = list(row.values())[0] if isinstance(row, dict) else row[0]
        conn.close()
        return {"status": "healthy", "database": "connected", "postgis_version": postgis_ver}
    except Exception:
        return {"status": "degraded", "database": "disconnected"}


@app.post("/api/auth/register", status_code=201)
async def register_user(request: Request, payload: Dict[str, Any]):
    ip = request.client.host if request.client else "unknown"
    check_rate_limit(ip, "register")

    username = str(payload.get("username", "")).strip()
    full_name = str(payload.get("full_name", "")).strip()
    password = str(payload.get("password", ""))
    confirm_password = str(payload.get("confirm_password", ""))

    if not re.fullmatch(r"[A-Za-z0-9_]{3,30}", username):
        raise HTTPException(status_code=422, detail="Username must be 3-30 characters using letters, numbers, and underscores only.")
    if not full_name:
        raise HTTPException(status_code=422, detail="Full name is required.")
    if len(password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters.")
    if not any(ch.isalpha() for ch in password) or not any(ch.isdigit() for ch in password):
        raise HTTPException(status_code=422, detail="Password must contain at least one letter and one number.")
    if password != confirm_password:
        raise HTTPException(status_code=422, detail="Passwords do not match.")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE LOWER(username) = %s", (username.lower(),))
    existing = cursor.fetchone()
    if existing:
        conn.close()
        record_audit_log(username.lower(), "anonymous", "register_failed", details="Username already taken")
        raise HTTPException(status_code=409, detail="Username already taken")

    user_id = f"USR-{uuid.uuid4().hex[:8].upper()}"
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute(
        """
        INSERT INTO users (id, username, full_name, password_hash, role, created_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (user_id, username.lower(), full_name, hash_password(password), "viewer", created_at),
    )
    conn.commit()
    conn.close()

    record_audit_log(username.lower(), "viewer", "register", target_id=user_id, details=f"Registered user {username.lower()} as viewer")
    return {
        "status": "success",
        "message": "Registration successful.",
        "user": {
            "id": user_id,
            "username": username.lower(),
            "full_name": full_name,
            "role": "viewer",
            "created_at": created_at,
        },
    }


@app.post("/api/auth/login")
async def login(request: Request, payload: Dict[str, Any]):
    ip = request.client.host if request.client else "unknown"
    check_rate_limit(ip, "login")

    username = str(payload.get("username", "")).strip().lower()
    password = str(payload.get("password", ""))

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE LOWER(username) = %s", (username,))
    user = cursor.fetchone()
    conn.close()

    if not user or not verify_password(password, user["password_hash"]):
        record_audit_log(username or "unknown", "unknown", "login_failed", details="Failed login attempt")
        raise HTTPException(status_code=401, detail="Wrong username or password")

    token = create_access_token({"sub": user["username"], "role": user["role"]})
    record_audit_log(user["username"], user["role"], "login_success", details=f"User {user['username']} logged in successfully")
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {"username": user["username"], "role": user["role"]},
    }


@app.get("/api/auth/me")
async def get_current_user_profile(user: Dict[str, Any] = Depends(get_current_user)):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, full_name, role, created_at FROM users WHERE LOWER(username) = %s", (user["username"].lower(),))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return user
    return dict(row)


@app.get("/api/audit-logs")
async def get_audit_logs(user: Dict[str, Any] = Depends(require_role(["admin"]))):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM audit_logs ORDER BY timestamp DESC LIMIT 200")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/users")
async def list_users(user: Dict[str, Any] = Depends(require_role(["admin"]))):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, full_name, role, created_at FROM users ORDER BY username ASC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.patch("/api/users/{id}/role")
async def change_user_role(id: str, payload: Dict[str, Any], user: Dict[str, Any] = Depends(require_role(["admin"]))):
    new_role = str(payload.get("role", "")).strip().lower()
    if new_role not in {"viewer", "inspector", "admin"}:
        raise HTTPException(status_code=422, detail="Role must be viewer, inspector, or admin.")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT username, role FROM users WHERE id = %s", (id,))
    target = cursor.fetchone()
    if not target:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found")
    if target["username"] == user["username"].lower() and target["role"] == "admin" and new_role != "admin":
        conn.close()
        raise HTTPException(status_code=403, detail="You cannot remove your own admin role.")

    cursor.execute("UPDATE users SET role = %s WHERE id = %s", (new_role, id))
    conn.commit()
    conn.close()
    record_audit_log(user["username"], user["role"], "role_change", target_id=id, details=f"Changed user {target['username']} role to {new_role}")
    return {"id": id, "role": new_role, "username": target["username"]}


@app.get("/api/models")
async def list_models(user: Dict[str, Any] = Depends(require_role(["viewer", "inspector", "admin"]))):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM model_versions ORDER BY id ASC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/inspections", response_model=InspectionResponse, status_code=status.HTTP_201_CREATED)
async def create_inspection(payload: InspectionCreate, user: Dict[str, Any] = Depends(require_role(["admin", "inspector"]))):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as count FROM inspections")
    count = cursor.fetchone()["count"] + 1
    new_id = f"INS-{count:03d}"
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if payload.rtsp_url and payload.rtsp_url.startswith("rtsp://"):
        video_url = payload.rtsp_url
        proc_mode = "RTSP"
        src_type = payload.source_type if payload.source_type != "Vehicle Camera" else "RTSP Stream"
    elif payload.video_filename and payload.video_filename.startswith("rtsp://"):
        video_url = payload.video_filename
        proc_mode = "RTSP"
        src_type = "RTSP Stream"
    else:
        video_url = f"/api/media/video/{payload.video_filename or 'demo_road.mp4'}"
        proc_mode = payload.processing_mode or "Batch"
        src_type = payload.source_type

    cursor.execute(
        """
        INSERT INTO inspections (
            id, name, road_id, road_name, source_type, created_at, status,
            model_version, video_url, total_frames, processed_frames, defect_count,
            progress_percent, current_stage, inspection_date, location, processing_mode, is_mock
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            new_id,
            payload.name,
            payload.road_id,
            payload.road_name,
            src_type,
            created_at,
            InspectionStatus.CREATED.value if not video_url.startswith("rtsp://") else InspectionStatus.UPLOADED.value,
            payload.model_version,
            video_url,
            0,
            0,
            0,
            0,
            "Initialized",
            payload.inspection_date or datetime.now().strftime("%Y-%m-%d"),
            payload.location or payload.road_name,
            proc_mode,
            1
        ),
    )
    conn.commit()
    conn.close()

    record_audit_log(user["username"], user["role"], "create_inspection", target_id=new_id, details=f"Created survey '{payload.name}'")
    record_audit_log(user["username"], user["role"], "status_transition", target_id=new_id, details="Status -> CREATED")

    return {
        "id": new_id,
        "name": payload.name,
        "road_id": payload.road_id,
        "road_name": payload.road_name,
        "source_type": src_type,
        "created_at": created_at,
        "started_at": None,
        "completed_at": None,
        "status": InspectionStatus.CREATED if not video_url.startswith("rtsp://") else InspectionStatus.UPLOADED,
        "model_version": payload.model_version,
        "video_url": video_url,
        "total_frames": 0,
        "processed_frames": 0,
        "defect_count": 0,
        "progress_percent": 0,
        "current_stage": "Initialized",
        "error_message": None,
        "inspection_date": payload.inspection_date or datetime.now().strftime("%Y-%m-%d"),
        "location": payload.location or payload.road_name,
        "processing_mode": proc_mode,
        "duration_seconds": 0.0,
        "fps": 0.0,
        "is_mock": True
    }


@app.post("/api/inspections/{id}/attach-rtsp-stream")
async def attach_rtsp_stream(id: str, payload: Dict[str, Any], user: Dict[str, Any] = Depends(require_role(["admin", "inspector"]))):
    rtsp_url = str(payload.get("rtsp_url") or "").strip()
    if not rtsp_url or not rtsp_url.startswith("rtsp://"):
        raise HTTPException(status_code=400, detail="A valid RTSP URL starting with rtsp:// is required.")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM inspections WHERE id = %s", (id,))
    insp = cursor.fetchone()
    if not insp:
        conn.close()
        raise HTTPException(status_code=404, detail="Inspection not found")

    cursor.execute(
        "UPDATE inspections SET video_url = %s, source_type = 'RTSP Stream', processing_mode = 'RTSP', status = %s WHERE id = %s",
        (rtsp_url, InspectionStatus.UPLOADED.value, id)
    )
    conn.commit()
    conn.close()

    record_audit_log(user["username"], user["role"], "attach_rtsp_stream", target_id=id, details=f"Attached RTSP Stream {rtsp_url}")
    return {"status": "success", "inspection_id": id, "video_url": rtsp_url}


@app.get("/api/inspections/{id}/pipeline-payload")
async def get_pipeline_payload(id: str, user: Dict[str, Any] = Depends(require_role(["viewer", "inspector", "admin"]))):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM inspections WHERE id = %s", (id,))
    insp = cursor.fetchone()
    conn.close()
    if not insp:
        raise HTTPException(status_code=404, detail="Inspection not found")

    v_url = insp["video_url"] or ""
    is_rtsp = v_url.startswith("rtsp://") or (insp.get("processing_mode") == "RTSP")

    presigned_s3_url = None
    if is_s3_enabled() and not is_rtsp:
        try:
            s3_key = v_url.lstrip("/")
            if s3_key.startswith("api/media/video/"):
                s3_key = s3_key.replace("api/media/video/", "media/video/")
            presigned_s3_url = generate_presigned_upload_url(s3_key, expires_in=3600)
        except Exception:
            pass

    return {
        "inspection_id": insp["id"],
        "name": insp["name"],
        "road_id": insp["road_id"],
        "road_name": insp["road_name"],
        "source_type": insp["source_type"],
        "processing_mode": insp.get("processing_mode", "Batch"),
        "status": insp["status"],
        "model_version": insp["model_version"],
        "is_rtsp": is_rtsp,
        "video_url": v_url,
        "rtsp_url": v_url if is_rtsp else None,
        "s3_presigned_download_url": presigned_s3_url,
        "ingest_detections_endpoint": f"/api/inspections/{id}/detections/batch",
        "created_at": insp["created_at"]
    }



@app.get("/api/inspections")
async def list_inspections(user: Dict[str, Any] = Depends(require_role(["viewer", "inspector", "admin"]))):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM inspections ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/inspections/{id}")
async def get_inspection(id: str, user: Dict[str, Any] = Depends(require_role(["viewer", "inspector", "admin"]))):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM inspections WHERE id = %s", (id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Inspection not found")
    item = dict(row)
    v_url = str(item.get("video_url") or "")
    for pfx in ("/static/media/video/", "static/media/video/"):
        if v_url.startswith(pfx):
            v_url = v_url[len(pfx):]
    item["video_url"] = v_url
    return item


@app.post("/api/inspections/{id}/upload")
async def upload_inspection_video(id: str, file: UploadFile = File(...), user: Dict[str, Any] = Depends(require_role(["admin", "inspector"]))):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM inspections WHERE id = %s", (id,))
    insp = cursor.fetchone()
    if not insp:
        conn.close()
        raise HTTPException(status_code=404, detail="Inspection not found")

    content_type = (file.content_type or "").lower()
    if not content_type.startswith("video/"):
        conn.close()
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Only MP4 or MOV video uploads are accepted.")

    safe_original = os.path.basename(file.filename or "uploaded.mp4")
    file_ext = os.path.splitext(safe_original)[1].lower() or ".mp4"
    saved_filename = f"{uuid.uuid4().hex}{file_ext}"
    dest_path = os.path.join(VIDEO_DIR, saved_filename)

    total_read = 0
    try:
        with open(dest_path, "wb") as f_out:
            while True:
                chunk = await file.read(UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                total_read += len(chunk)
                if total_read > MAX_UPLOAD_BYTES:
                    if os.path.exists(dest_path):
                        os.remove(dest_path)
                    conn.close()
                    raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Video exceeds 500MB maximum size limit.")
                f_out.write(chunk)
    finally:
        await file.close()
    # D16: reject zero-byte files
    if total_read == 0:
        if os.path.exists(dest_path):
            os.remove(dest_path)
        conn.close()
        raise HTTPException(status_code=400, detail="Uploaded file is empty (zero bytes).")

    video_url = f"/api/media/video/{saved_filename}"
    cursor.execute("UPDATE inspections SET video_url = %s, status = %s WHERE id = %s", (video_url, InspectionStatus.UPLOADED.value, id))
    conn.commit()
    conn.close()

    record_audit_log(user["username"], user["role"], "upload_video", target_id=id, details=f"Uploaded '{safe_original}' ({total_read} bytes)")
    record_audit_log(user["username"], user["role"], "status_transition", target_id=id, details="Status -> UPLOADED")
    if is_s3_enabled():
        try:
            upload_file(dest_path, f"media/video/{saved_filename}", content_type="video/mp4")
        except Exception as exc:
            print(f"[Upload] S3 sync error: {exc}")
    return {"status": "success", "video_url": video_url, "inspection_id": id}


@app.post("/api/inspections/{id}/gps")
async def upload_inspection_gps(id: str, file: UploadFile = File(...), user: Dict[str, Any] = Depends(require_role(["admin", "inspector"]))):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM inspections WHERE id = %s", (id,))
    insp = cursor.fetchone()
    if not insp:
        conn.close()
        raise HTTPException(status_code=404, detail="Inspection not found")

    filename = (file.filename or "").lower()
    content = await file.read()
    await file.close()

    gps_points = []
    if filename.endswith(".csv"):
        import csv
        import io
        text_csv = content.decode("utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(text_csv))
        for row_idx, r in enumerate(reader):
            try:
                ts = float(r.get("timestamp") or r.get("time") or 0.0)
                lat = float(r.get("latitude") or r.get("lat") or 0.0)
                lon = float(r.get("longitude") or r.get("lon") or r.get("lng") or 0.0)
            except Exception:
                conn.close()
                raise HTTPException(status_code=400, detail=f"Invalid numeric data in GPS CSV row {row_idx + 1}")
            if lat < -90.0 or lat > 90.0 or lon < -180.0 or lon > 180.0:
                conn.close()
                raise HTTPException(status_code=400, detail=f"Invalid coordinates at row {row_idx + 1}: latitude must be [-90, 90], longitude [-180, 180]")
            gps_points.append({"timestamp": ts, "lat": lat, "lon": lon})
    elif filename.endswith(".gpx"):
        import xml.etree.ElementTree as ET
        try:
            root = ET.fromstring(content)
            for trkpt in root.iter():
                if trkpt.tag.endswith("trkpt"):
                    lat = float(trkpt.attrib.get("lat", 0.0))
                    lon = float(trkpt.attrib.get("lon", 0.0))
                    if lat < -90.0 or lat > 90.0 or lon < -180.0 or lon > 180.0:
                        conn.close()
                        raise HTTPException(status_code=400, detail="Invalid coordinates in GPX: latitude must be [-90, 90], longitude [-180, 180]")
                    gps_points.append({"timestamp": float(len(gps_points)), "lat": lat, "lon": lon})
        except HTTPException:
            raise
        except Exception as e:
            conn.close()
            raise HTTPException(status_code=400, detail=f"Failed to parse GPX file: {str(e)}")
    else:
        conn.close()
        raise HTTPException(status_code=400, detail="GPS file must be a .csv or .gpx file.")

    if not gps_points:
        conn.close()
        raise HTTPException(status_code=400, detail="No GPS track points found in uploaded file.")

    gps_dir = os.path.join(DATA_DIR, "inspections", id)
    os.makedirs(gps_dir, exist_ok=True)
    with open(os.path.join(gps_dir, "gps_points.json"), "w") as f_gps:
        json.dump(gps_points, f_gps, indent=2)

    cursor.execute("UPDATE inspections SET gps_source = 'gps_file' WHERE id = %s", (id,))
    conn.commit()
    conn.close()

    record_audit_log(user["username"], user["role"], "upload_gps", target_id=id, details=f"Uploaded GPS track ({len(gps_points)} points)")
    return {"status": "success", "inspection_id": id, "point_count": len(gps_points), "gps_source": "gps_file"}



@app.post("/api/inspections/{id}/start")
async def start_inspection(id: str, background_tasks: BackgroundTasks, user: Dict[str, Any] = Depends(require_role(["admin", "inspector"]))):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM inspections WHERE id = %s", (id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Inspection not found")

    current_status = row["status"]
    running_states = {InspectionStatus.PROCESSING.value, InspectionStatus.AI_ANALYSIS.value, InspectionStatus.GEO_REFERENCING.value, InspectionStatus.AGGREGATION.value, InspectionStatus.QUEUED.value}
    if current_status in running_states:
        conn.close()
        raise HTTPException(status_code=409, detail=f"Inspection is already running (current stage: {row['current_stage']}).")

    cursor.execute("UPDATE inspections SET status = 'QUEUED', current_stage = 'Queued in background worker' WHERE id = %s", (id,))
    conn.commit()
    conn.close()

    background_tasks.add_task(pipeline_worker.run_pipeline_async, id)
    record_audit_log(user["username"], user["role"], "start_inspection", target_id=id, details="Triggered AI Processing Pipeline")
    record_audit_log(user["username"], user["role"], "status_transition", target_id=id, details="Status -> QUEUED")
    return {"status": "started", "inspection_id": id, "message": "AI Processing pipeline initiated"}


@app.get("/api/inspections/{id}/status")
async def get_inspection_status(id: str, user: Dict[str, Any] = Depends(require_role(["viewer", "inspector", "admin"]))):
    status_data = pipeline_worker.get_status(id)
    if not status_data:
        raise HTTPException(status_code=404, detail="Inspection not found")
    return status_data


@app.get("/api/inspections/{id}/detections")
async def get_inspection_detections(id: str, user: Dict[str, Any] = Depends(require_role(["viewer", "inspector", "admin"]))):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM detections WHERE inspection_id = %s ORDER BY timestamp ASC", (id,))
    rows = cursor.fetchall()
    conn.close()
    out = []
    for r in rows:
        item = dict(r)
        item["bbox"] = json.loads(item["bbox_json"]) if item.get("bbox_json") else []
        mins = int(item["timestamp"] // 60)
        secs = int(item["timestamp"] % 60)
        item["timestamp_formatted"] = f"{mins:02d}:{secs:02d}"
        for k in ("evidence_orig_url", "evidence_anno_url"):
            val = str(item.get(k) or "")
            for pfx in ("/static/media/evidence/", "static/media/evidence/"):
                if val.startswith(pfx):
                    val = val[len(pfx):]
            item[k] = val
        out.append(item)
    return out


@app.get("/api/detections/{id}")
async def get_detection_detail(id: str, user: Dict[str, Any] = Depends(require_role(["viewer", "inspector", "admin"]))):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM detections WHERE id = %s OR detection_id = %s", (id, id))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Detection not found")
    item = dict(row)
    item["bbox"] = json.loads(item["bbox_json"]) if item.get("bbox_json") else []
    mins = int(item["timestamp"] // 60)
    secs = int(item["timestamp"] % 60)
    item["timestamp_formatted"] = f"{mins:02d}:{secs:02d}"
    for k in ("evidence_orig_url", "evidence_anno_url"):
        val = str(item.get(k) or "")
        for pfx in ("/static/media/evidence/", "static/media/evidence/"):
            if val.startswith(pfx):
                val = val[len(pfx):]
        item[k] = val
    return item


def ingest_detections_core(id: str, payload_items: List[Dict[str, Any]], user_username: str, user_role: str, gps_source: str = "interpolated from corridor geometry"):
    """Shared ingest and validation logic adhering to CVDetectionPayload contract"""
    validated_detections = []
    for idx, item in enumerate(payload_items):
        try:
            val = CVDetectionPayload(**item)
            validated_detections.append(val)
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Validation failed at detection index {idx}: {str(e)}")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM inspections WHERE id = %s", (id,))
    insp = cursor.fetchone()
    if not insp:
        conn.close()
        raise HTTPException(status_code=404, detail="Inspection not found")

    cursor.execute("SELECT id, geometry_json, length_km, traffic_exposure, road_importance FROM road_segments")
    segments = cursor.fetchall()

    def get_nearest_segment(lat, lng):
        best_id = "RD-001"
        min_dist = float("inf")
        for s in segments:
            try:
                coords = json.loads(s["geometry_json"])
                for pt in coords:
                    dist = ((pt[0] - lat) ** 2 + (pt[1] - lng) ** 2) ** 0.5
                    if dist < min_dist:
                        min_dist = dist
                        best_id = s["id"]
            except Exception:
                continue
        return best_id

    inserted_ids = []
    affected_segments = set()

    for det in validated_detections:
        assigned_seg = det.road_segment_id or get_nearest_segment(det.latitude, det.longitude)
        affected_segments.add(assigned_seg)

        evidence_anno = det.evidence_uri or f"{id}/{det.detection_id}_anno.jpg"
        if "_anno." in evidence_anno:
            evidence_orig = evidence_anno.replace("_anno.", "_orig.")
        elif "_orig." in evidence_anno:
            evidence_orig = evidence_anno
            evidence_anno = evidence_orig.replace("_orig.", "_anno.")
        else:
            evidence_orig = evidence_anno

        cursor.execute(
            """
            INSERT INTO detections (
                id, detection_id, inspection_id, frame_id, timestamp, defect_type,
                confidence, severity, bbox_json, latitude, longitude, geom, road_segment_id,
                evidence_orig_url, evidence_anno_url, model_version, is_mock, gps_source
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                detection_id = EXCLUDED.detection_id,
                inspection_id = EXCLUDED.inspection_id,
                frame_id = EXCLUDED.frame_id,
                timestamp = EXCLUDED.timestamp,
                defect_type = EXCLUDED.defect_type,
                confidence = EXCLUDED.confidence,
                severity = EXCLUDED.severity,
                bbox_json = EXCLUDED.bbox_json,
                latitude = EXCLUDED.latitude,
                longitude = EXCLUDED.longitude,
                geom = EXCLUDED.geom,
                road_segment_id = EXCLUDED.road_segment_id,
                evidence_orig_url = EXCLUDED.evidence_orig_url,
                evidence_anno_url = EXCLUDED.evidence_anno_url,
                model_version = EXCLUDED.model_version,
                is_mock = EXCLUDED.is_mock,
                gps_source = EXCLUDED.gps_source
            """,
            (
                det.detection_id,
                det.detection_id,
                id,
                det.frame_id,
                det.timestamp,
                det.defect_class,
                det.confidence,
                det.severity,
                json.dumps(det.bbox),
                det.latitude,
                det.longitude,
                det.longitude,
                det.latitude,
                assigned_seg,
                evidence_orig,
                evidence_anno,
                det.model_version or insp["model_version"],
                1,
                gps_source
            ),
        )
        inserted_ids.append(det.detection_id)

        if det.severity.lower() == "critical":
            cursor.execute(
                """
                INSERT INTO alerts (
                    id, inspection_id, segment_id, defect_id, defect_type, severity,
                    message, timestamp, latitude, longitude, evidence_url, is_read
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    inspection_id = EXCLUDED.inspection_id,
                    segment_id = EXCLUDED.segment_id,
                    defect_id = EXCLUDED.defect_id,
                    defect_type = EXCLUDED.defect_type,
                    severity = EXCLUDED.severity,
                    message = EXCLUDED.message,
                    timestamp = EXCLUDED.timestamp,
                    latitude = EXCLUDED.latitude,
                    longitude = EXCLUDED.longitude,
                    evidence_url = EXCLUDED.evidence_url,
                    is_read = EXCLUDED.is_read
                """,
                (
                    f"ALT-{det.detection_id}",
                    id,
                    assigned_seg,
                    det.detection_id,
                    det.defect_class.capitalize(),
                    "Critical",
                    f"CRITICAL DEFECT DETECTED on {assigned_seg}: High impact {det.defect_class}. Immediate P1 intervention assessment required.",
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    det.latitude,
                    det.longitude,
                    evidence_anno,
                    0,
                ),
            )

    # Recompute metrics for affected segments
    for seg_id in affected_segments:
        cursor.execute("SELECT * FROM detections WHERE road_segment_id = %s AND inspection_id = %s", (seg_id, id))
        seg_dets = cursor.fetchall()
        det_dicts = [dict(d) for d in seg_dets]
        seg_row = next((s for s in segments if s["id"] == seg_id), None)
        seg_dict = dict(seg_row) if seg_row else {"length_km": 1.0, "traffic_exposure": 0.5, "road_importance": 0.8}

        cond_result = calculate_segment_condition(
            float(seg_dict.get("length_km", 1.0)),
            det_dicts
        )
        counts = cond_result.get("counts", {})
        has_crit = counts.get("critical", 0) > 0
        risk_result = calculate_segment_risk(
            condition_score=cond_result["condition_score"],
            traffic_exposure=float(seg_dict.get("traffic_exposure", 0.5)),
            road_importance=float(seg_dict.get("road_importance", 0.8)),
            has_critical_defects=has_crit
        )
        priority_val = risk_result["priority"].value if hasattr(risk_result["priority"], "value") else str(risk_result["priority"])

        cursor.execute(
            """
            INSERT INTO segment_metrics (
                segment_id, inspection_id, defect_count, pothole_count, crack_count, marking_count,
                critical_count, high_count, medium_count, low_count, defect_density, condition_score, risk_score
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (inspection_id, segment_id) DO UPDATE SET
                defect_count = EXCLUDED.defect_count,
                pothole_count = EXCLUDED.pothole_count,
                crack_count = EXCLUDED.crack_count,
                marking_count = EXCLUDED.marking_count,
                critical_count = EXCLUDED.critical_count,
                high_count = EXCLUDED.high_count,
                medium_count = EXCLUDED.medium_count,
                low_count = EXCLUDED.low_count,
                defect_density = EXCLUDED.defect_density,
                condition_score = EXCLUDED.condition_score,
                risk_score = EXCLUDED.risk_score
            """,
            (
                seg_id, id, counts.get("total", len(det_dicts)), counts.get("potholes", 0), counts.get("cracks", 0),
                counts.get("markings", 0), counts.get("critical", 0), counts.get("high", 0),
                counts.get("medium", 0), counts.get("low", 0), cond_result["defect_density"],
                cond_result["condition_score"], risk_result["risk_score"]
            ),
        )

        cursor.execute(
            """
            UPDATE road_segments SET
                condition_score = %s, risk_score = %s, priority = %s, status_color = %s
            WHERE id = %s
            """,
            (cond_result["condition_score"], risk_result["risk_score"], priority_val, cond_result["status_color"], seg_id),
        )

    cursor.execute("SELECT COUNT(*) as count FROM detections WHERE inspection_id = %s", (id,))
    total_dets = cursor.fetchone()["count"]
    cursor.execute("UPDATE inspections SET defect_count = %s WHERE id = %s", (total_dets, id))

    conn.commit()
    conn.close()

    record_audit_log(user_username, user_role, "ingest_detections", target_id=id, details=f"Ingested {len(inserted_ids)} detections across {len(affected_segments)} segments")
    return {"status": "success", "inspection_id": id, "ingested_count": len(inserted_ids), "detection_ids": inserted_ids, "affected_segments": sorted(list(affected_segments))}


# ==============================================================================
# CV Team Schema 1.0 Ingestion Endpoints (ai_results.json, processing_status.json)
# ==============================================================================

def normalize_cv_class(raw_class: str) -> str:
    c = str(raw_class or "").lower().strip()
    if "pothole" in c:
        return "pothole"
    elif "crack" in c:
        return "crack"
    elif "marking" in c:
        return "marking"
    elif "rutting" in c:
        return "rutting"
    elif "raveling" in c:
        return "raveling"
    return "crack"


def _ensure_inspection_exists(conn, cursor, inspection_id: Optional[str] = None):
    target_id = str(inspection_id or "DEMO-001").strip()
    cursor.execute("SELECT id, model_version, total_frames, duration_seconds FROM inspections WHERE id = %s", (target_id,))
    insp = cursor.fetchone()
    if not insp:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            """
            INSERT INTO inspections (
                id, survey_name, road_id, road_name, model_version, status,
                defect_count, total_frames, duration_seconds, created_at, completed_at
            ) VALUES (%s, %s, 'RD-001', 'NH-48 Expressway', 'ZTRACS-RoadDefect v1.0.0', 'PROCESSING', 0, 1000, 60.0, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (target_id, f"CV Survey {target_id}", now_str, now_str)
        )
        conn.commit()
        cursor.execute("SELECT id, model_version, total_frames, duration_seconds FROM inspections WHERE id = %s", (target_id,))
        insp = cursor.fetchone()
    return target_id, insp


@app.post("/api/cv/alert")
async def ingest_simple_cv_alert(payload: Dict[str, Any]):
    """
    Ultra-simplified CV Alert ingestion endpoint for CV AI Team.
    No username/password or auth token required.
    Payload structure:
    {
      "inspection_id": "DEMO-001", // optional, defaults to DEMO-001
      "video": true,
      "rtsp": false,
      "type": "damage",            // damage or asset
      "tag": "pothole",            // pothole, cracks, water filled pothole, traffic light, guardrails, etc.
      "lat": 18.985,
      "long": 73.110
    }
    """
    raw_insp_id = payload.get("inspection_id") or "DEMO-001"
    conn = get_connection()
    cursor = conn.cursor()
    target_id, _ = _ensure_inspection_exists(conn, cursor, str(raw_insp_id))

    is_video = bool(payload.get("video", True))
    is_rtsp = bool(payload.get("rtsp", False))
    alert_type = str(payload.get("type", "damage")).lower().strip()
    tag = str(payload.get("tag", "pothole")).lower().strip()

    lat_val = payload.get("lat") if "lat" in payload else payload.get("latitude")
    lng_val = payload.get("long") if "long" in payload else (payload.get("longitude") or payload.get("lng"))

    lat = float(lat_val) if (lat_val is not None and str(lat_val).strip() != "" and str(lat_val).lower() != "none") else 18.9850
    lng = float(lng_val) if (lng_val is not None and str(lng_val).strip() != "" and str(lng_val).lower() != "none") else 73.1100

    conf = float(payload.get("confidence", 0.90))
    sev = str(payload.get("severity", "high" if alert_type == "damage" else "low")).lower().strip()

    det_id = f"DEF-CV-{uuid.uuid4().hex[:6].upper()}"
    defect_class = normalize_cv_class(tag)

    # Evidence Image Handling (S3 URL, S3 Key, Base64 string, or fallback)
    raw_img = (
        payload.get("image_url") or
        payload.get("s3_url") or
        payload.get("s3_key") or
        payload.get("evidence_url") or
        payload.get("image_base64") or
        payload.get("image")
    )
    evidence_url = ""
    if raw_img and str(raw_img).strip():
        img_str = str(raw_img).strip()
        if img_str.startswith("s3://"):
            # Convert s3://bucket/key to https://bucket.s3.amazonaws.com/key
            parts = img_str[5:].split("/", 1)
            bucket = parts[0]
            key = parts[1] if len(parts) > 1 else ""
            evidence_url = f"https://{bucket}.s3.amazonaws.com/{key}"
        elif img_str.startswith("data:image/") or img_str.startswith("http://") or img_str.startswith("https://") or img_str.startswith("/"):
            evidence_url = img_str
        else:
            evidence_url = f"data:image/jpeg;base64,{img_str}"
    else:
        # Fallback evidence image if CV team omits image field
        evidence_url = "/static/media/evidence/demo_pothole_001.jpg" if defect_class == "pothole" else "/static/media/evidence/demo_crack_001.jpg"

    cursor.execute(
        """
        INSERT INTO detections (
            id, detection_id, inspection_id, frame_id, timestamp, defect_type,
            confidence, severity, bbox_json, latitude, longitude, geom, road_segment_id,
            evidence_orig_url, evidence_anno_url, model_version, is_mock, gps_source
        ) VALUES (%s, %s, %s, 1, 0.0, %s, %s, %s, '[100, 100, 300, 300]', %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), 'RD-001', %s, %s, 'RoadDefect-v1.0', 0, 'CV AI Alert')
        ON CONFLICT (id) DO NOTHING
        """,
        (det_id, det_id, target_id, defect_class, conf, sev, lat, lng, lng, lat, evidence_url, evidence_url)
    )

    alert_id = f"ALT-{det_id}"
    msg = f"CV Alert [{alert_type.upper()}]: {tag.upper()} ({'RTSP' if is_rtsp else 'Video'})"
    cursor.execute(
        """
        INSERT INTO alerts (
            id, inspection_id, segment_id, defect_id, defect_type, severity,
            message, timestamp, latitude, longitude, evidence_url, is_read
        ) VALUES (%s, %s, 'RD-001', %s, %s, %s, %s, NOW(), %s, %s, %s, 0)
        ON CONFLICT (id) DO NOTHING
        """,
        (alert_id, target_id, det_id, defect_class, sev, msg, lat, lng, evidence_url)
    )

    cursor.execute("UPDATE inspections SET defect_count = defect_count + 1 WHERE id = %s", (target_id,))
    conn.commit()
    conn.close()

    return {
        "status": "success",
        "alert_id": alert_id,
        "inspection_id": target_id,
        "received": {
            "inspection_id": target_id,
            "video": is_video,
            "rtsp": is_rtsp,
            "type": alert_type,
            "tag": tag,
            "lat": lat,
            "long": lng
        }
    }


@app.post("/api/inspections/{id}/ai-results")
@app.post("/api/cv/ai-results")
async def ingest_cv_ai_results(payload: Dict[str, Any], id: Optional[str] = None):
    inspection_id = id or payload.get("inspection_id") or "DEMO-001"
    conn = get_connection()
    cursor = conn.cursor()
    target_id, insp = _ensure_inspection_exists(conn, cursor, str(inspection_id))

    model_info = payload.get("model") or {}
    model_version = model_info.get("model_version") or insp["model_version"]
    video_info = payload.get("video") or {}
    total_frames = int(video_info.get("total_frames") or insp.get("total_frames") or 0)
    duration_sec = float(video_info.get("duration_seconds") or insp.get("duration_seconds") or 0.0)

    detections_raw = payload.get("detections") or []
    inserted_ids = []
    affected_segments = set()

    cursor.execute("SELECT id, geometry_json, length_km FROM road_segments")
    segments_db = cursor.fetchall()

    def find_segment(lat, lng):
        best_id = "RD-001"
        min_dist = float("inf")
        for s in segments_db:
            try:
                coords = json.loads(s["geometry_json"])
                for pt in coords:
                    dist = ((pt[0] - lat) ** 2 + (pt[1] - lng) ** 2) ** 0.5
                    if dist < min_dist:
                        min_dist = dist
                        best_id = s["id"]
            except Exception:
                continue
        return best_id

    for det in detections_raw:
        det_id = str(det.get("detection_id") or f"DEF-CV-{uuid.uuid4().hex[:6].upper()}")
        
        # Frame & Timestamp
        frame_obj = det.get("frame") if isinstance(det.get("frame"), dict) else {}
        frame_num = int(frame_obj.get("frame_number") or det.get("frame_id") or 0)
        ts_sec = float(frame_obj.get("timestamp_seconds") or det.get("timestamp") or 0.0)
        
        # Classification & Confidence
        classif = det.get("classification") if isinstance(det.get("classification"), dict) else {}
        raw_class = classif.get("class_name") or det.get("class") or det.get("defect_type") or "crack"
        defect_class = normalize_cv_class(raw_class)
        conf = float(classif.get("confidence") if "confidence" in classif else det.get("confidence", 0.90))
        sev = str(classif.get("severity") or det.get("severity") or "medium").lower()

        # Geometry & BBox
        geom = det.get("geometry") if isinstance(det.get("geometry"), dict) else {}
        bbox_dict = geom.get("bbox") if isinstance(geom.get("bbox"), dict) else None
        if bbox_dict:
            bbox_arr = [float(bbox_dict.get("x1", 0)), float(bbox_dict.get("y1", 0)), float(bbox_dict.get("x2", 100)), float(bbox_dict.get("y2", 100))]
        elif isinstance(det.get("bbox"), list):
            bbox_arr = det.get("bbox")
        else:
            bbox_arr = [100.0, 100.0, 300.0, 300.0]

        # Location
        loc = det.get("location") if isinstance(det.get("location"), dict) else {}
        lat = float(loc.get("latitude") if "latitude" in loc else det.get("latitude", 18.9850))
        lng = float(loc.get("longitude") if "longitude" in loc else det.get("longitude", 73.1100))

        # Road / Segment
        road_ref = det.get("road") if isinstance(det.get("road"), dict) else {}
        seg_id = road_ref.get("segment_id") or det.get("road_segment_id") or find_segment(lat, lng)
        affected_segments.add(seg_id)

        # Evidence
        ev = det.get("evidence") if isinstance(det.get("evidence"), dict) else {}
        evidence_orig = ev.get("original_frame_s3_key") or det.get("evidence_orig_url") or det.get("evidence_uri") or f"{inspection_id}/{det_id}_orig.jpg"
        evidence_anno = ev.get("annotated_frame_s3_key") or det.get("evidence_anno_url") or f"{inspection_id}/{det_id}_anno.jpg"

        cursor.execute(
            """
            INSERT INTO detections (
                id, detection_id, inspection_id, frame_id, timestamp, defect_type,
                confidence, severity, bbox_json, latitude, longitude, geom, road_segment_id,
                evidence_orig_url, evidence_anno_url, model_version, is_mock, gps_source
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                defect_type = EXCLUDED.defect_type,
                confidence = EXCLUDED.confidence,
                severity = EXCLUDED.severity,
                bbox_json = EXCLUDED.bbox_json,
                latitude = EXCLUDED.latitude,
                longitude = EXCLUDED.longitude,
                geom = EXCLUDED.geom,
                evidence_orig_url = EXCLUDED.evidence_orig_url,
                evidence_anno_url = EXCLUDED.evidence_anno_url
            """,
            (
                det_id, det_id, inspection_id, frame_num, ts_sec, defect_class,
                conf, sev, json.dumps(bbox_arr), lat, lng, lng, lat, seg_id,
                evidence_orig, evidence_anno, model_version, 0, "CV AI Pipeline (Schema 1.0)"
            )
        )
        inserted_ids.append(det_id)

        if sev == "critical":
            cursor.execute(
                """
                INSERT INTO alerts (
                    id, inspection_id, segment_id, defect_id, defect_type, severity,
                    message, timestamp, latitude, longitude, evidence_url, is_read
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    f"ALT-{det_id}", inspection_id, seg_id, det_id, defect_class, sev,
                    f"Critical {defect_class.upper()} detected at frame {frame_num}",
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"), lat, lng, evidence_anno, 0
                )
            )

    # Recompute metrics for affected segments
    for seg_id in affected_segments:
        cursor.execute("SELECT * FROM detections WHERE road_segment_id = %s AND inspection_id = %s", (seg_id, inspection_id))
        seg_dets = [dict(d) for d in cursor.fetchall()]
        seg_row = next((s for s in segments_db if s["id"] == seg_id), None)
        seg_dict = dict(seg_row) if seg_row else {"length_km": 1.0, "traffic_exposure": 0.5, "road_importance": 0.8}

        cond_result = calculate_segment_condition(float(seg_dict.get("length_km", 1.0)), seg_dets)
        counts = cond_result.get("counts", {})
        has_crit = counts.get("critical", 0) > 0
        risk_result = calculate_segment_risk(
            condition_score=cond_result["condition_score"],
            traffic_exposure=float(seg_dict.get("traffic_exposure", 0.5)),
            road_importance=float(seg_dict.get("road_importance", 0.8)),
            has_critical_defects=has_crit
        )
        priority_val = "P1" if (has_crit or cond_result["condition_score"] < 50) else ("P2" if cond_result["condition_score"] < 70 else "P3")

        cursor.execute(
            """
            INSERT INTO segment_metrics (
                segment_id, inspection_id, defect_count, pothole_count, crack_count,
                marking_count, critical_count, high_count, medium_count, low_count,
                defect_density, condition_score, risk_score
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (inspection_id, segment_id) DO UPDATE SET
                defect_count = EXCLUDED.defect_count,
                pothole_count = EXCLUDED.pothole_count,
                crack_count = EXCLUDED.crack_count,
                marking_count = EXCLUDED.marking_count,
                critical_count = EXCLUDED.critical_count,
                high_count = EXCLUDED.high_count,
                medium_count = EXCLUDED.medium_count,
                low_count = EXCLUDED.low_count,
                defect_density = EXCLUDED.defect_density,
                condition_score = EXCLUDED.condition_score,
                risk_score = EXCLUDED.risk_score
            """,
            (
                seg_id, inspection_id, counts.get("total", len(seg_dets)), counts.get("potholes", 0), counts.get("cracks", 0),
                counts.get("markings", 0), counts.get("critical", 0), counts.get("high", 0),
                counts.get("medium", 0), counts.get("low", 0), cond_result["defect_density"],
                cond_result["condition_score"], risk_result["risk_score"]
            ),
        )

        cursor.execute(
            """
            UPDATE road_segments SET
                condition_score = %s, risk_score = %s, priority = %s, status_color = %s
            WHERE id = %s
            """,
            (cond_result["condition_score"], risk_result["risk_score"], priority_val, cond_result["status_color"], seg_id),
        )

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        """
        UPDATE inspections SET
            status = 'COMPLETED', current_stage = 'Processing Completed', progress_percent = 100,
            processed_frames = %s, total_frames = %s, defect_count = %s, completed_at = %s,
            duration_seconds = %s, is_mock = 0
        WHERE id = %s
        """,
        (total_frames or len(inserted_ids) * 10, total_frames or len(inserted_ids) * 10, len(inserted_ids), now_str, duration_sec, inspection_id)
    )
    conn.commit()
    conn.close()

    record_audit_log("cv_system", "system", "ingest_cv_results", target_id=target_id, details=f"Ingested {len(inserted_ids)} defects via CV Schema 1.0")
    return {
        "status": "success",
        "inspection_id": target_id,
        "detections_ingested": len(inserted_ids),
        "affected_segments": sorted(list(affected_segments)),
        "message": "CV Schema 1.0 AI results ingested successfully."
    }


@app.post("/api/cv/status-update")
async def update_cv_status(payload: CVStatusUpdatePayload):
    conn = get_connection()
    cursor = conn.cursor()
    target_id, _ = _ensure_inspection_exists(conn, cursor, payload.inspection_id)

    cursor.execute(
        """
        UPDATE inspections SET
            status = %s, current_stage = %s, progress_percent = %s,
            processed_frames = %s, total_frames = %s, defect_count = %s
        WHERE id = %s
        """,
        (
            payload.status.upper(),
            payload.stage or "AI Inference",
            payload.progress,
            payload.frames_processed,
            payload.total_frames,
            payload.detections_found,
            target_id,
        )
    )
    conn.commit()
    conn.close()
    return {"status": "success", "inspection_id": target_id}


@app.post("/api/cv/status-failed")
async def report_cv_failed(payload: CVFailedPayload):
    conn = get_connection()
    cursor = conn.cursor()
    target_id, _ = _ensure_inspection_exists(conn, cursor, payload.inspection_id)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        """
        UPDATE inspections SET
            status = 'FAILED', current_stage = 'Processing Failed',
            error_message = %s, completed_at = %s
        WHERE id = %s
        """,
        (f"[{payload.error_code}] {payload.error_message}", now_str, target_id)
    )
    conn.commit()
    conn.close()
    return {"status": "failed_recorded", "inspection_id": target_id}


@app.get("/api/cv/export-tasks")
@app.get("/forensics/export-tasks")
@app.get("/api/v1/forensics/export-tasks")
async def get_cv_export_tasks():
    """
    Continuous Event Listener Endpoint for CV / DeepStream / YOLO GPU Nodes.
    No authentication required. Returns active/pending inspection surveys and S3 video download URLs.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM inspections ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()

    tasks = []
    active_count = 0
    for r in rows:
        item = dict(r)
        status = item.get("status", "QUEUED")
        if status in ["QUEUED", "UPLOADED", "PROCESSING", "AI_ANALYSIS", "CREATED"]:
            active_count += 1
        
        v_url = str(item.get("video_url") or "")
        direct_url = None
        if is_s3_enabled() and v_url and not v_url.startswith("rtsp://"):
            try:
                s3_key = v_url.lstrip("/")
                if s3_key.startswith("api/media/video/"):
                    s3_key = s3_key.replace("api/media/video/", "media/video/")
                direct_url = generate_presigned_upload_url(s3_key, expires_in=3600)
            except Exception:
                pass

        if not direct_url and v_url:
            if v_url.startswith("http://") or v_url.startswith("https://"):
                direct_url = v_url
            else:
                clean_name = v_url.split("/")[-1].split("?")[0]
                direct_url = f"/api/media/video/{clean_name}"

        filename = v_url.split("/")[-1].split("?")[0] if v_url else f"{item['id'].lower()}.mp4"

        task_entry = {
            "task_id": item["id"],
            "inspection_id": item["id"],
            "case_id": item.get("name") or item["id"],
            "footage_name": item.get("road_name") or filename,
            "filename": filename,
            "status": status,
            "direct_video_url": direct_url,
            "download_url": direct_url,
            "models_requested": [item.get("model_version") or "RoadDefect-v1.0", "ANPR", "POTHOLE", "CRACKS"],
            "duration_formatted": "00:05:00",
            "total_frames": 9000,
            "file_size_bytes": None,
            "created_at": str(item.get("created_at", ""))
        }
        tasks.append(task_entry)

    return {
        "status": "success",
        "total_tasks": len(tasks),
        "active_processing": active_count,
        "tasks": tasks
    }


@app.get("/api/cv/tasks/{id}/video")
@app.get("/forensics/tasks/{id}/video")
@app.get("/api/v1/forensics/tasks/{id}/video")
async def get_cv_task_video_stream(id: str):
    """
    Stream download footage for specific task ID directly to GPU listener nodes.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT video_url FROM inspections WHERE id = %s", (id,))
    row = cursor.fetchone()
    conn.close()

    v_url = str(row["video_url"]) if row and row.get("video_url") else ""
    clean_name = v_url.split("/")[-1].split("?")[0] if v_url else ""

    if clean_name:
        local_path = os.path.join(VIDEO_DIR, clean_name)
        if os.path.exists(local_path):
            return FileResponse(local_path, media_type="video/mp4")

        fallback_path = os.path.join("static", "media", "video", clean_name)
        if os.path.exists(fallback_path):
            return FileResponse(fallback_path, media_type="video/mp4")

    # Fallback to demo road inspection video if available
    demo_file = os.path.join(VIDEO_DIR, "demo_road.mp4")
    if os.path.exists(demo_file):
        return FileResponse(demo_file, media_type="video/mp4")

    raise HTTPException(status_code=404, detail=f"Local video file not found for task '{id}'")



@app.post("/api/inspections/{id}/detections/ingest")
async def ingest_detections(id: str, payload: List[Dict[str, Any]], user: Dict[str, Any] = Depends(require_role(["admin", "inspector"]))):
    # D19: cap batch size at 500 detections per request
    if len(payload) > 500:
        raise HTTPException(status_code=422, detail=f"Batch too large: {len(payload)} detections submitted, maximum is 500 per request.")
    return ingest_detections_core(id, payload, user["username"], user["role"])


@app.get("/api/road-segments")
async def get_road_segments(inspection_id: Optional[str] = "DEMO-001", user: Dict[str, Any] = Depends(require_role(["viewer", "inspector", "admin"]))):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM road_segments ORDER BY id ASC")
    rows = cursor.fetchall()
    results = []
    for r in rows:
        item = dict(r)
        item["geometry"] = json.loads(item["geometry_json"])
        cursor.execute("SELECT * FROM segment_metrics WHERE segment_id = %s AND inspection_id = %s", (item["id"], inspection_id))
        metric = cursor.fetchone()
        if metric:
            m_dict = dict(metric)
            item.update({
                "defect_count": m_dict["defect_count"],
                "pothole_count": m_dict["pothole_count"],
                "crack_count": m_dict["crack_count"],
                "marking_count": m_dict["marking_count"],
                "critical_count": m_dict["critical_count"],
                "high_count": m_dict["high_count"],
                "medium_count": m_dict["medium_count"],
                "low_count": m_dict["low_count"],
                "condition_score": m_dict["condition_score"],
                "risk_score": m_dict["risk_score"],
            })
        else:
            item.update({"defect_count": 0, "pothole_count": 0, "crack_count": 0, "marking_count": 0, "critical_count": 0, "high_count": 0, "medium_count": 0, "low_count": 0})
        results.append(item)
    conn.close()
    return results


@app.get("/api/road-segments/{id}")
async def get_road_segment_detail(id: str, inspection_id: Optional[str] = "DEMO-001", user: Dict[str, Any] = Depends(require_role(["viewer", "inspector", "admin"]))):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM road_segments WHERE id = %s", (id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Segment not found")
    item = dict(row)
    item["geometry"] = json.loads(item["geometry_json"])

    if inspection_id:
        cursor.execute("SELECT * FROM segment_metrics WHERE segment_id = %s AND inspection_id = %s", (id, inspection_id))
        sm = cursor.fetchone()
        if sm:
            sm_dict = dict(sm)
            item.update({
                "condition_score": sm_dict["condition_score"],
                "risk_score": sm_dict["risk_score"],
                "defect_count": sm_dict.get("defect_count", 0),
                "pothole_count": sm_dict.get("pothole_count", 0),
                "crack_count": sm_dict.get("crack_count", 0),
                "marking_count": sm_dict.get("marking_count", 0),
                "critical_count": sm_dict.get("critical_count", 0),
                "high_count": sm_dict.get("high_count", 0),
                "medium_count": sm_dict.get("medium_count", 0),
                "low_count": sm_dict.get("low_count", 0),
            })

    cursor.execute("SELECT * FROM detections WHERE road_segment_id = %s AND inspection_id = %s ORDER BY timestamp ASC", (id, inspection_id))
    det_rows = cursor.fetchall()
    conn.close()
    detections = []
    for det in det_rows:
        payload = dict(det)
        payload["bbox"] = json.loads(payload["bbox_json"]) if payload.get("bbox_json") else []
        mins = int(payload["timestamp"] // 60)
        secs = int(payload["timestamp"] % 60)
        payload["timestamp_formatted"] = f"{mins:02d}:{secs:02d}"
        detections.append(payload)
    item["detections"] = detections
    return item


@app.get("/api/map/segments")
async def get_map_segments(
    inspection_id: Optional[str] = "DEMO-001",
    user: Dict[str, Any] = Depends(require_role(["viewer", "inspector", "admin"])),
):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT rs.id, rs.road_id, rs.segment_name, rs.geometry_json, rs.length_km, rs.road_class,
               rs.condition_score, rs.risk_score, rs.priority, rs.status_color,
               COALESCE(sm.defect_count, 0) as defect_count
        FROM road_segments rs
        LEFT JOIN segment_metrics sm ON rs.id = sm.segment_id AND sm.inspection_id = %s
        ORDER BY rs.id ASC
    """, (inspection_id,))
    rows = cursor.fetchall()
    conn.close()

    features = []
    for r in rows:
        coords = []
        try:
            coords = json.loads(r["geometry_json"])
        except Exception:
            pass
        geojson_coords = [[pt[1], pt[0]] for pt in coords if len(pt) >= 2]
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": geojson_coords},
            "properties": {
                "id": r["id"],
                "road_id": r["road_id"],
                "segment_name": r["segment_name"],
                "length_km": r["length_km"],
                "road_class": r["road_class"],
                "condition_score": r["condition_score"],
                "risk_score": r["risk_score"],
                "priority": r["priority"],
                "status_color": r["status_color"],
                "defect_count": r["defect_count"],
            },
        })
    return {"type": "FeatureCollection", "features": features}


@app.get("/api/map/defects")
async def get_map_defects(inspection_id: Optional[str] = "DEMO-001", user: Dict[str, Any] = Depends(require_role(["viewer", "inspector", "admin"]))):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, detection_id, frame_id, timestamp, defect_type, confidence, severity, latitude, longitude, road_segment_id, evidence_anno_url FROM detections WHERE inspection_id = %s", (inspection_id,))
    rows = cursor.fetchall()
    conn.close()
    features = []
    for r in rows:
        mins = int(r["timestamp"] // 60)
        secs = int(r["timestamp"] % 60)
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [r["longitude"], r["latitude"]]},
            "properties": {
                "id": r["id"],
                "detection_id": r["detection_id"],
                "defect_type": r["defect_type"],
                "severity": r["severity"],
                "confidence": r["confidence"],
                "timestamp_formatted": f"{mins:02d}:{secs:02d}",
                "road_segment_id": r["road_segment_id"],
                "evidence_url": r["evidence_anno_url"],
            },
        })
    return {"type": "FeatureCollection", "features": features}


@app.get("/api/analytics/condition")
async def get_analytics_condition(inspection_id: Optional[str] = "DEMO-001", user: Dict[str, Any] = Depends(require_role(["viewer", "inspector", "admin"]))):
    """
    C7: Condition score per segment and summary.
    PoC workflow categories, not engineering standards.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM inspections WHERE id = %s", (inspection_id,))
    insp = cursor.fetchone()

    cursor.execute("""
        SELECT s.*,
               m.condition_score as metric_condition,
               m.risk_score as metric_risk,
               m.defect_count as metric_defects
        FROM road_segments s
        LEFT JOIN segment_metrics m ON s.id = m.segment_id AND m.inspection_id = %s
        ORDER BY s.id ASC
    """, (inspection_id,))
    segments = cursor.fetchall()

    # Dynamic distance calculation per C4
    road_id = insp["road_id"] if insp else None
    cursor.execute("""
        SELECT SUM(length_km) as dist FROM road_segments
        WHERE (road_id IS NOT NULL AND road_id = %s)
           OR id IN (SELECT DISTINCT road_segment_id FROM detections WHERE inspection_id = %s)
    """, (road_id, inspection_id))
    dist_row = cursor.fetchone()
    conn.close()

    total_dist = round(float(dist_row["dist"]), 1) if dist_row and dist_row["dist"] else round(sum(s["length_km"] for s in segments), 1)

    segment_list = []
    total_score = 0.0
    total_risk = 0.0
    high_risk_count = 0

    for s in segments:
        s_dict = dict(s)
        if s_dict.get("metric_condition") is not None:
            cond = float(s_dict["metric_condition"])
            risk = float(s_dict["metric_risk"])
        elif inspection_id == "DEMO-001":
            cond = float(s_dict["condition_score"])
            risk = float(s_dict["risk_score"])
        else:
            cond = 100.0
            risk = 0.0

        length = float(s_dict["length_km"])
        total_score += cond
        total_risk += risk
        if risk >= SCORING_CONFIG.high_risk_threshold:
            high_risk_count += 1

        priority = (
            "P1" if risk >= SCORING_CONFIG.p1_threshold
            else ("P2" if risk >= SCORING_CONFIG.p2_threshold
            else ("P3" if risk >= SCORING_CONFIG.p3_threshold else "P4"))
        )
        status_color = (
            "red" if risk >= SCORING_CONFIG.p1_threshold
            else ("orange" if risk >= SCORING_CONFIG.p2_threshold
            else ("yellow" if risk >= SCORING_CONFIG.p3_threshold else "green"))
        )

        segment_list.append({
            "segment_id": s_dict["id"],
            "segment_name": s_dict["segment_name"],
            "road_id": s_dict["road_id"],
            "road_class": s_dict["road_class"],
            "length_km": length,
            "condition_score": cond,
            "risk_score": risk,
            "priority": priority,
            "status_color": status_color
        })

    num_segs = max(len(segments), 1)
    avg_condition = round(total_score / num_segs, 1)
    avg_risk = round(total_risk / num_segs, 1)

    return {
        "inspection_id": inspection_id,
        "methodology": "PoC condition score",
        "note": "Scores and priorities are PoC workflow categories, not engineering standards.",
        "summary": {
            "average_condition_score": avg_condition,
            "average_risk_score": avg_risk,
            "total_segments": len(segments),
            "high_risk_segments": high_risk_count,
            "total_inspected_distance_km": total_dist
        },
        "segments": segment_list
    }




@app.get("/api/scoring/config")
async def get_scoring_weights(user: Dict[str, Any] = Depends(require_role(["viewer", "inspector", "admin"]))):
    cfg = get_scoring_config()
    return cfg.dict() if hasattr(cfg, "dict") else cfg.model_dump()


@app.put("/api/scoring/config")
async def update_scoring_weights(
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_role(["admin"]))
):
    updated = update_scoring_config(payload)
    record_audit_log(user["username"], user["role"], "update_scoring_config", details=f"Updated weights: {list(payload.keys())}")
    return updated.dict() if hasattr(updated, "dict") else updated.model_dump()

@app.get("/api/analytics/overview")
async def get_analytics_overview(inspection_id: Optional[str] = "DEMO-001", user: Dict[str, Any] = Depends(require_role(["viewer", "inspector", "admin"]))):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM detections WHERE inspection_id = %s", (inspection_id,))
    dets = cursor.fetchall()
    cursor.execute("""
        SELECT s.*,
               m.condition_score as metric_condition,
               m.risk_score as metric_risk
        FROM road_segments s
        LEFT JOIN segment_metrics m ON s.id = m.segment_id AND m.inspection_id = %s
    """, (inspection_id,))
    segs = cursor.fetchall()

    # C4: Compute Inspected Distance dynamically from corridor and detection segments
    cursor.execute("SELECT road_id FROM inspections WHERE id = %s", (inspection_id,))
    insp_row = cursor.fetchone()
    road_id = insp_row["road_id"] if insp_row else None
    cursor.execute("""
        SELECT SUM(length_km) as dist FROM road_segments
        WHERE (road_id IS NOT NULL AND road_id = %s)
           OR id IN (SELECT DISTINCT road_segment_id FROM detections WHERE inspection_id = %s)
    """, (road_id, inspection_id))
    dist_row = cursor.fetchone()
    conn.close()

    if dist_row and dist_row["dist"]:
        computed_dist_km = round(float(dist_row["dist"]), 1)
    else:
        computed_dist_km = round(sum(s["length_km"] for s in segs), 1)

    total_defects = len(dets)
    potholes = len([d for d in dets if d["defect_type"] == "pothole"])
    cracks = len([d for d in dets if d["defect_type"] == "crack"])
    markings = len([d for d in dets if d["defect_type"] == "marking"])
    others = total_defects - potholes - cracks - markings
    critical_defects = len([d for d in dets if d["severity"] == "critical"])
    high_defects = len([d for d in dets if d["severity"] == "high"])
    medium_defects = len([d for d in dets if d["severity"] == "medium"])
    low_defects = len([d for d in dets if d["severity"] == "low"])
    cond_scores = []
    risk_scores = []
    high_risk_segs = 0
    defects_per_km = []
    for s in segs:
        s_dict = dict(s)
        s_id = s_dict["id"]
        s_len = float(s_dict.get("length_km") or 1.0)
        seg_dets = [d for d in dets if d["road_segment_id"] == s_id]
        density = round(len(seg_dets) / max(s_len, 0.1), 1)

        if s_dict.get("metric_condition") is not None:
            c = float(s_dict["metric_condition"])
            r = float(s_dict["metric_risk"])
        elif inspection_id == "DEMO-001":
            c = float(s_dict["condition_score"])
            r = float(s_dict["risk_score"])
        else:
            c = 100.0
            r = 0.0
        cond_scores.append(c)
        risk_scores.append(r)
        if r >= SCORING_CONFIG.high_risk_threshold:
            high_risk_segs += 1
        defects_per_km.append({
            "segment_id": s_id,
            "density": density,
            "risk": round(r, 1),
        })
    avg_condition = round(sum(cond_scores) / max(len(cond_scores), 1), 1)
    avg_risk = round(sum(risk_scores) / max(len(risk_scores), 1), 1)

    return {
        "inspected_distance_km": computed_dist_km,
        "total_defects": total_defects,
        "critical_defects": critical_defects,
        "high_risk_segments": high_risk_segs,
        "average_condition_score": avg_condition,
        "average_risk_score": avg_risk,
        "defect_distribution": {"pothole": potholes, "crack": cracks, "marking": markings, "other": others},
        "severity_distribution": {"critical": critical_defects, "high": high_defects, "medium": medium_defects, "low": low_defects},
        "defects_per_km": defects_per_km,
    }




@app.get("/api/assets")
async def get_road_assets(
    road_id: Optional[str] = None,
    segment_id: Optional[str] = None,
    asset_type: Optional[str] = None,
    user: Dict[str, Any] = Depends(require_role(["viewer", "inspector", "admin"]))
):
    conn = get_connection()
    cursor = conn.cursor()
    query = "SELECT * FROM assets WHERE 1=1"
    params = []
    if road_id:
        query += " AND road_id = %s"
        params.append(road_id)
    if segment_id:
        query += " AND segment_id = %s"
        params.append(segment_id)
    if asset_type:
        query += " AND LOWER(asset_type) = %s"
        params.append(asset_type.lower())
    query += " ORDER BY id"
    cursor.execute(query, tuple(params))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/alerts")
async def get_alerts(user: Dict[str, Any] = Depends(require_role(["viewer", "inspector", "admin"]))):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM alerts ORDER BY timestamp DESC")
    rows = cursor.fetchall()
    conn.close()
    results = []
    for r in rows:
        item = dict(r)
        ev_url = str(item.get("evidence_url") or "")
        for pfx in ("/static/media/evidence/", "static/media/evidence/"):
            if ev_url.startswith(pfx):
                ev_url = ev_url[len(pfx):]
        item["evidence_url"] = ev_url
        results.append(item)
    return results


@app.post("/api/alerts/{id}/read")
async def mark_alert_read(id: str, user: Dict[str, Any] = Depends(require_role(["admin", "inspector"]))):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE alerts SET is_read = 1 WHERE id = %s", (id,))
    conn.commit()
    conn.close()
    return {"status": "success"}


@app.post("/api/reports")
async def generate_report(inspection_id: str = "DEMO-001", user: Dict[str, Any] = Depends(require_role(["admin", "inspector"]))):
    try:
        pdf_path = generate_inspection_pdf(inspection_id)
        filename = os.path.basename(pdf_path)
        record_audit_log(user["username"], user["role"], "generate_report", target_id=inspection_id, details=f"Generated PDF inspection report '{filename}'")
        return {"status": "success", "inspection_id": inspection_id, "pdf_url": f"/api/reports/{inspection_id}/pdf", "filename": filename}
    except Exception:
        raise HTTPException(status_code=500, detail="Report generation failed.")




@app.get("/api/reports/{id}")
async def get_report_metadata(
    id: str,
    user: Dict[str, Any] = Depends(require_role(["viewer", "inspector", "admin"]))
):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM inspections WHERE id = %s", (id,))
    insp = cursor.fetchone()
    if not insp:
        conn.close()
        raise HTTPException(status_code=404, detail="Inspection not found")

    cursor.execute("SELECT COUNT(*) as count FROM detections WHERE inspection_id = %s", (id,))
    det_count = cursor.fetchone()["count"]
    cursor.execute("SELECT COUNT(*) as count FROM road_segments WHERE road_id = %s", (insp["road_id"],))
    seg_count = cursor.fetchone()["count"]
    conn.close()

    pdf_filename = f"inspection_{id}_report.pdf"
    pdf_path = os.path.join(REPORTS_DIR, pdf_filename)
    is_generated = os.path.exists(pdf_path)

    return {
        "inspection_id": id,
        "road_id": insp["road_id"],
        "road_name": insp["road_name"],
        "status": insp["status"],
        "title": f"PoC Inspection Report - {id}",
        "defect_count": det_count,
        "segment_count": seg_count,
        "pdf_url": f"/api/reports/{id}/pdf",
        "pdf_filename": pdf_filename,
        "pdf_generated": is_generated,
        "created_at": insp["created_at"],
        "completed_at": insp["completed_at"],
    }

@app.get("/api/reports/{id}/pdf")
async def download_report_pdf(id: str, request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer)):
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Authentication required.")
    if request.query_params.get("token"):
        raise HTTPException(status_code=400, detail="Token query parameters are not allowed. Use the Authorization header.")
    try:
        payload = decode_access_token(credentials.credentials)
    except HTTPException:
        raise
    if not payload.get("sub") or not payload.get("role"):
        raise HTTPException(status_code=401, detail="Authentication failed.")
    pdf_filename = f"inspection_{id}_report.pdf"
    pdf_path = os.path.join(REPORTS_DIR, pdf_filename)
    if not os.path.exists(pdf_path):
        try:
            pdf_path = generate_inspection_pdf(id)
        except Exception:
            if is_s3_enabled():
                for k in (f"reports/{pdf_filename}", f"static/reports/{pdf_filename}", pdf_filename):
                    s3_bytes = get_file_bytes(k)
                    if s3_bytes is not None:
                        return Response(
                            content=s3_bytes,
                            media_type="application/pdf",
                            headers={"Content-Disposition": f'attachment; filename="ZTRACS_Report_{id}.pdf"'}
                        )
            raise HTTPException(status_code=404, detail="Report not found.")
    return FileResponse(pdf_path, media_type="application/pdf", filename=f"ZTRACS_Report_{id}.pdf")


def _make_media_sig(safe_name: str, expires: int, media_type: str = "video") -> str:
    """Generate an HMAC-SHA256 signature for a media file using the dedicated media signing key (A5)."""
    key = get_media_signing_key()
    msg = f"{media_type}:{safe_name}:{expires}".encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def _verify_media_sig(safe_name: str, expires: int, signature: str, media_type: str = "video") -> bool:
    """Constant-time HMAC verification for media URLs."""
    expected = _make_media_sig(safe_name, expires, media_type)
    return hmac.compare_digest(expected, signature)


@app.get("/api/media/sign")
async def sign_media_url(
    file: str,
    user: Dict[str, Any] = Depends(require_role(["viewer", "inspector", "admin"]))
):
    """Sign a single video filename. A5: uses MEDIA_SIGNING_SECRET / derived key, never raw JWT_SECRET."""
    safe_name = os.path.basename(file)
    if not safe_name or ".." in file or "/" in safe_name or "\\" in safe_name:
        raise HTTPException(status_code=400, detail="Invalid filename.")
    expires = int(time.time()) + 600
    sig = _make_media_sig(safe_name, expires, "video")
    signed_url = f"/api/media/video/{safe_name}?expires={expires}&signature={sig}"
    return {"status": "success", "url": signed_url, "expires": expires, "signature": sig, "file": safe_name}


@app.post("/api/media/sign-batch")
async def sign_media_urls_batch(
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_role(["viewer", "inspector", "admin"]))
):
    """Sign up to 100 evidence image filenames in one call (F27 / fix 1)."""
    files = payload.get("files", [])
    media_type = str(payload.get("type", "evidence"))
    if not isinstance(files, list):
        raise HTTPException(status_code=422, detail="`files` must be a list.")
    if len(files) > 100:
        raise HTTPException(status_code=422, detail="Cannot sign more than 100 files per request.")
    if media_type not in ("evidence", "video"):
        raise HTTPException(status_code=422, detail="`type` must be 'evidence' or 'video'.")
    expires = int(time.time()) + 600
    result = {}
    for f in files:
        raw_f = str(f).strip()
        for prefix in ("/static/media/evidence/", "/api/media/evidence/", "static/media/evidence/"):
            if raw_f.startswith(prefix):
                raw_f = raw_f[len(prefix):]
        raw_f = raw_f.lstrip("/")
        if not raw_f or ".." in raw_f or "\\" in raw_f:
            continue
        if media_type == "video":
            safe_name = os.path.basename(raw_f)
            sig = _make_media_sig(safe_name, expires, "video")
            url = f"/api/media/video/{safe_name}?expires={expires}&signature={sig}"
        else:
            sig = _make_media_sig(raw_f, expires, "evidence")
            url = f"/api/media/evidence/{raw_f}?expires={expires}&signature={sig}"
        result[f] = {"url": url, "expires": expires}
    return {"status": "success", "signed": result}
@app.get("/api/media/video/{filename}")
async def serve_video(
    filename: str,
    request: Request,
    expires: Optional[int] = Query(None),
    signature: Optional[str] = Query(None)
):
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename.")
    safe_name = os.path.basename(filename)

    # Authenticate: either via HMAC query signature or Bearer token (A5: uses media signing key)
    authenticated = False
    if expires is not None and signature is not None:
        if time.time() > expires:
            raise HTTPException(status_code=401, detail="Media signature has expired.")
        if not _verify_media_sig(safe_name, expires, signature, "video"):
            raise HTTPException(status_code=401, detail="Invalid media signature.")
        authenticated = True
    else:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            try:
                user = authenticate_token_with_db(token)
                if user.get("role") in ["viewer", "inspector", "admin"]:
                    authenticated = True
                else:
                    raise HTTPException(status_code=403, detail="Permission denied.")
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(status_code=401, detail="Authentication failed.")

    if not authenticated:
        raise HTTPException(status_code=401, detail="Authentication required: Provide a valid media signature or Bearer token.")

    path = os.path.join(VIDEO_DIR, safe_name)
    found_local = os.path.exists(path)
    if not found_local:
        static_video_path = os.path.join(STATIC_DIR, "media", "video", safe_name)
        if os.path.exists(static_video_path):
            path = static_video_path
            found_local = True

    if not found_local:
        if is_s3_enabled():
            s3_keys = [f"media/video/{safe_name}", f"videos/{safe_name}", safe_name]
            found_key = None
            for k in s3_keys:
                if file_exists(k):
                    found_key = k
                    break
            if found_key:
                range_header = request.headers.get("range")
                stream_res = get_file_stream(found_key, range_header=range_header)
                if stream_res:
                    status_code = 206 if range_header else 200
                    resp_headers = {
                        "Accept-Ranges": "bytes",
                        "Content-Type": stream_res.get("ContentType", "video/mp4"),
                        "Content-Length": str(stream_res.get("ContentLength", 0)),
                    }
                    if "ContentRange" in stream_res:
                        resp_headers["Content-Range"] = stream_res["ContentRange"]
                    return Response(content=stream_res["Body"].read(), status_code=status_code, headers=resp_headers)
        raise HTTPException(status_code=404, detail="Video not found.")

    file_size = os.path.getsize(path)
    range_header = request.headers.get("range")

    # Support HTTP Range requests (206 Partial Content)
    if range_header:
        range_match = re.match(r"bytes=(\d+)-(\d+)?", range_header.strip())
        if range_match:
            start = int(range_match.group(1))
            end = int(range_match.group(2)) if range_match.group(2) else file_size - 1
            if start >= file_size or end >= file_size or start > end:
                raise HTTPException(
                    status_code=416,
                    detail="Requested Range Not Satisfiable",
                    headers={"Content-Range": f"bytes */{file_size}"}
                )
            length = end - start + 1
            with open(path, "rb") as f:
                f.seek(start)
                data = f.read(length)
            headers = {
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(length),
                "Content-Type": "video/mp4",
            }
            return Response(content=data, status_code=206, headers=headers)

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(file_size),
        "Content-Type": "video/mp4",
    }
    with open(path, "rb") as f:
        data = f.read()
    return Response(content=data, status_code=200, headers=headers)


@app.get("/api/media/evidence/{filepath:path}")
async def serve_evidence(
    filepath: str,
    request: Request,
    expires: Optional[int] = Query(None),
    signature: Optional[str] = Query(None),
):
    """F27: Serve evidence images only to authenticated users or with a valid signed URL.
    filepath is relative to EVIDENCE_DIR, e.g. "INS-001/det_0001_orig.jpg" or "defect_00124_orig.jpg"
    """
    if ".." in filepath or filepath.startswith("/") or "\\" in filepath:
        raise HTTPException(status_code=400, detail="Invalid file path.")
    clean_path = filepath.lstrip("/")
    resolved = os.path.realpath(os.path.join(EVIDENCE_DIR, clean_path))
    evidence_root = os.path.realpath(EVIDENCE_DIR)
    if not resolved.startswith(evidence_root + os.sep) and resolved != evidence_root:
        raise HTTPException(status_code=400, detail="Invalid file path.")

    authenticated = False
    if expires is not None and signature is not None:
        if time.time() > expires:
            raise HTTPException(status_code=401, detail="Media signature has expired.")
        # Exact path signature check: MUST match clean_path exactly (no basename fallback)
        if _verify_media_sig(clean_path, expires, signature, "evidence"):
            authenticated = True
        else:
            raise HTTPException(status_code=401, detail="Invalid media signature.")
    else:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            try:
                user = authenticate_token_with_db(token)
                if user.get("role") in ["viewer", "inspector", "admin"]:
                    authenticated = True
                else:
                    raise HTTPException(status_code=403, detail="Permission denied.")
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(status_code=401, detail="Authentication failed.")

    if not authenticated:
        raise HTTPException(status_code=401, detail="Authentication required.")

    if not os.path.exists(resolved):
        if is_s3_enabled():
            for k in (f"media/evidence/{clean_path}", f"evidence/{clean_path}", clean_path):
                s3_bytes = get_file_bytes(k)
                if s3_bytes is not None:
                    ext = os.path.splitext(clean_path)[1].lower()
                    media_type = "image/jpeg" if ext in (".jpg", ".jpeg") else ("image/png" if ext == ".png" else "application/octet-stream")
                    return Response(content=s3_bytes, media_type=media_type)
        raise HTTPException(status_code=404, detail="Evidence file not found.")

    ext = os.path.splitext(resolved)[1].lower()
    media_type = "image/jpeg" if ext in (".jpg", ".jpeg") else ("image/png" if ext == ".png" else "application/octet-stream")
    return FileResponse(resolved, media_type=media_type)
@app.post("/api/demo/reset")
async def reset_demo_dataset(user: Dict[str, Any] = Depends(require_role(["admin"]))):
    seed_demo_data(force=True)
    record_audit_log(user["username"], user["role"], "reset_demo", target_id="DEMO-001", details="Restored Golden Demo DEMO-001 to pristine state")
    return {"status": "success", "message": "Demo Inspection DEMO-001 reset to pristine state!"}


@app.get("/data/{path:path}")
async def deny_data_file(path: str):
    raise HTTPException(status_code=404, detail="Not found")


# F27: /static/media is NOT publicly mounted — all media is served via authenticated endpoints.

@app.get("/api/storage/status")
@app.get("/api/media/storage-info")
async def get_storage_status(user: Dict[str, Any] = Depends(require_role(["viewer", "inspector", "admin"]))):
    s3_on = is_s3_enabled()
    cfg = get_s3_config()
    info = {
        "status": "ready",
        "storage_mode": "s3" if s3_on else "local",
        "s3_enabled": s3_on,
        "bucket": cfg["bucket"] if s3_on else None,
        "region": cfg["region"] if s3_on else None,
    }
    if s3_on:
        conn_test = test_s3_connection()
        info["s3_connection"] = conn_test.get("status")
    return info


@app.post("/api/media/presigned-upload")
async def get_presigned_upload(
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_role(["admin", "inspector"]))
):
    """Generate a presigned S3 PUT URL for uploading large video/evidence files directly to S3."""
    if not is_s3_enabled():
        raise HTTPException(status_code=400, detail="S3 storage is not enabled or credentials not configured.")
    filename = payload.get("filename", "")
    content_type = payload.get("content_type", "video/mp4")
    media_type = payload.get("type", "video")
    if not filename:
        raise HTTPException(status_code=422, detail="filename is required.")

    safe_name = os.path.basename(filename)
    ext = os.path.splitext(safe_name)[1].lower() or ".mp4"
    saved_filename = f"{uuid.uuid4().hex}{ext}"
    s3_key = f"media/video/{saved_filename}" if media_type == "video" else f"media/evidence/{saved_filename}"
    presigned = generate_presigned_upload_url(s3_key, content_type=content_type)
    if not presigned:
        raise HTTPException(status_code=500, detail="Failed to generate presigned upload URL.")
    if "url" not in presigned and "upload_url" in presigned:
        presigned["url"] = presigned["upload_url"]
    presigned["saved_filename"] = saved_filename
    presigned["video_url"] = f"/api/media/video/{saved_filename}"
    return presigned


@app.post("/api/inspections/{id}/attach-s3-video")
async def attach_s3_video(
    id: str,
    payload: Dict[str, Any],
    user: Dict[str, Any] = Depends(require_role(["admin", "inspector"]))
):
    """Attach an uploaded S3 video file to an inspection."""
    saved_filename = payload.get("saved_filename")
    if not saved_filename:
        raise HTTPException(status_code=422, detail="saved_filename is required.")
    safe_name = os.path.basename(saved_filename)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM inspections WHERE id = %s", (id,))
    insp = cursor.fetchone()
    if not insp:
        conn.close()
        raise HTTPException(status_code=404, detail="Inspection not found")

    video_url = f"/api/media/video/{safe_name}"
    cursor.execute("UPDATE inspections SET video_url = %s, status = %s WHERE id = %s", (video_url, InspectionStatus.UPLOADED.value, id))
    conn.commit()
    conn.close()
    record_audit_log(user["username"], user["role"], "upload_video", target_id=id, details=f"Attached S3 video '{safe_name}'")
    record_audit_log(user["username"], user["role"], "status_transition", target_id=id, details="Status -> UPLOADED")
    return {"status": "success", "video_url": video_url, "inspection_id": id}

if __name__ == "__main__":
    import uvicorn
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", 8000))
    reload = os.getenv("DEV", "0") == "1"
    print(f"Starting Z-TRACS server on http://{host}:{port}...")
    uvicorn.run("backend.main:app", host=host, port=port, reload=reload)
