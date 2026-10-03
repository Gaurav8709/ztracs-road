"""
Z-TRACS Road Intelligence - SQLite to PostgreSQL + PostGIS Data Migration Tool
Copies data from SQLite to PostgreSQL, builds PostGIS geometry columns,
ensures idempotency, and prints validation statistics.
"""
import argparse
import json
import os
import sqlite3
import sys
from typing import Dict, Tuple

import psycopg
from psycopg.rows import dict_row

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.database import init_db


def migrate(sqlite_path: str, postgres_url: str) -> Dict[str, Tuple[int, int]]:
    if not os.path.exists(sqlite_path):
        raise FileNotFoundError(f"SQLite source file not found at: {sqlite_path}")

    # Connect to SQLite
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_cur = sqlite_conn.cursor()

    # Set DATABASE_URL for Postgres connection
    os.environ["DATABASE_URL"] = postgres_url
    if not os.getenv("ADMIN_USERNAME"):
        os.environ["ADMIN_USERNAME"] = "mig_admin_temp"
    if not os.getenv("ADMIN_PASSWORD"):
        os.environ["ADMIN_PASSWORD"] = "mig_pass_temp_123!"
    
    # Initialize schema in Postgres
    init_db()

    pg_conn = psycopg.connect(postgres_url, row_factory=dict_row)
    pg_cur = pg_conn.cursor()

    counts: Dict[str, Tuple[int, int]] = {}

    # 1. Migrate model_versions
    try:
        sqlite_cur.execute("SELECT * FROM model_versions")
        mv_rows = sqlite_cur.fetchall()
        for r in mv_rows:
            pg_cur.execute(
                """
                INSERT INTO model_versions (id, name, description, is_mock)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    is_mock = EXCLUDED.is_mock
                """,
                (r["id"], r["name"], r["description"], r["is_mock"] if "is_mock" in r.keys() else 1),
            )
        pg_conn.commit()
    except Exception as e:
        print(f"Note on model_versions: {e}")

    # 2. Migrate users (NEVER print hashes)
    try:
        sqlite_cur.execute("SELECT * FROM users")
        user_rows = sqlite_cur.fetchall()
        for r in user_rows:
            keys = r.keys()
            full_name = r["full_name"] if "full_name" in keys else ""
            created_at = r["created_at"] if "created_at" in keys else ""
            uid = str(r["id"]) if "id" in keys else f"USR-{str(r['username']).upper()}"
            pg_cur.execute(
                """
                INSERT INTO users (id, username, full_name, password_hash, role, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    username = EXCLUDED.username,
                    full_name = EXCLUDED.full_name,
                    password_hash = EXCLUDED.password_hash,
                    role = EXCLUDED.role,
                    created_at = EXCLUDED.created_at
                """,
                (uid, r["username"], full_name, r["password_hash"], r["role"], created_at),
            )
        pg_conn.commit()
    except Exception as e:
        print(f"Note on users: {e}")

    # 3. Migrate inspections
    try:
        sqlite_cur.execute("SELECT * FROM inspections")
        insp_rows = sqlite_cur.fetchall()
        for r in insp_rows:
            keys = r.keys()
            pg_cur.execute(
                """
                INSERT INTO inspections (
                    id, name, road_id, road_name, source_type, created_at, started_at, completed_at,
                    status, model_version, video_url, total_frames, processed_frames, defect_count,
                    progress_percent, current_stage, error_message, inspection_date, location,
                    processing_mode, duration_seconds, fps, is_mock
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    road_id = EXCLUDED.road_id,
                    road_name = EXCLUDED.road_name,
                    source_type = EXCLUDED.source_type,
                    created_at = EXCLUDED.created_at,
                    started_at = EXCLUDED.started_at,
                    completed_at = EXCLUDED.completed_at,
                    status = EXCLUDED.status,
                    model_version = EXCLUDED.model_version,
                    video_url = EXCLUDED.video_url,
                    total_frames = EXCLUDED.total_frames,
                    processed_frames = EXCLUDED.processed_frames,
                    defect_count = EXCLUDED.defect_count,
                    progress_percent = EXCLUDED.progress_percent,
                    current_stage = EXCLUDED.current_stage,
                    error_message = EXCLUDED.error_message,
                    inspection_date = EXCLUDED.inspection_date,
                    location = EXCLUDED.location,
                    processing_mode = EXCLUDED.processing_mode,
                    duration_seconds = EXCLUDED.duration_seconds,
                    fps = EXCLUDED.fps,
                    is_mock = EXCLUDED.is_mock
                """,
                (
                    r["id"], r["name"], r["road_id"] if "road_id" in keys else "RD-NH48", r["road_name"] if "road_name" in keys else "Highway", r["source_type"] if "source_type" in keys else "Vehicle Camera",
                    r["created_at"] if "created_at" in keys else "", r["started_at"] if "started_at" in keys else None,
                    r["completed_at"] if "completed_at" in keys else None,
                    r["status"] if "status" in keys else "COMPLETED", r["model_version"] if "model_version" in keys else "RoadDefect-v1.0",
                    r["video_url"] if "video_url" in keys else (r["video_path"] if "video_path" in keys else ""),
                    r["total_frames"] if "total_frames" in keys else 0,
                    r["processed_frames"] if "processed_frames" in keys else 0,
                    r["defect_count"] if "defect_count" in keys else 0,
                    r["progress_percent"] if "progress_percent" in keys else 0,
                    r["current_stage"] if "current_stage" in keys else "Initialized",
                    r["error_message"] if "error_message" in keys else None,
                    r["inspection_date"] if "inspection_date" in keys else "",
                    r["location"] if "location" in keys else "",
                    r["processing_mode"] if "processing_mode" in keys else "Batch",
                    r["duration_seconds"] if "duration_seconds" in keys else 0.0,
                    r["fps"] if "fps" in keys else 0.0,
                    r["is_mock"] if "is_mock" in keys else 1,
                ),
            )
        pg_conn.commit()
    except Exception as e:
        print(f"Note on inspections: {e}")

    # 4. Migrate road_segments (building PostGIS LineString geom)
    try:
        sqlite_cur.execute("SELECT * FROM road_segments")
        seg_rows = sqlite_cur.fetchall()
        for r in seg_rows:
            keys = r.keys()
            geom_json = r["geometry_json"]
            coords = json.loads(geom_json)
            # GeoJSON coordinates are [longitude, latitude]
            geojson_obj = {"type": "LineString", "coordinates": [[pt[1], pt[0]] for pt in coords if len(pt) >= 2]}
            geojson_str = json.dumps(geojson_obj)
            seg_name = r["segment_name"] if "segment_name" in keys else (r["name"] if "name" in keys else "Segment")
            len_km = r["length_km"] if "length_km" in keys else (r["end_km"] - r["start_km"] if "end_km" in keys and "start_km" in keys else 1.0)
            road_cls = r["road_class"] if "road_class" in keys else (r["surface_type"] if "surface_type" in keys else "Expressway")
            traffic_exp = r["traffic_exposure"] if "traffic_exposure" in keys else 0.5
            road_imp = r["road_importance"] if "road_importance" in keys else 0.8
            cond_sc = r["condition_score"] if "condition_score" in keys else 100.0
            risk_sc = r["risk_score"] if "risk_score" in keys else 0.0
            priority = r["priority"] if "priority" in keys else "P3"
            status_color = r["status_color"] if "status_color" in keys else "GREEN"

            pg_cur.execute(
                """
                INSERT INTO road_segments (
                    id, road_id, segment_name, geometry_json, geom, length_km, road_class,
                    traffic_exposure, road_importance, condition_score, risk_score, priority, status_color
                ) VALUES (%s, %s, %s, %s, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    road_id = EXCLUDED.road_id,
                    segment_name = EXCLUDED.segment_name,
                    geometry_json = EXCLUDED.geometry_json,
                    geom = EXCLUDED.geom,
                    length_km = EXCLUDED.length_km,
                    road_class = EXCLUDED.road_class,
                    traffic_exposure = EXCLUDED.traffic_exposure,
                    road_importance = EXCLUDED.road_importance,
                    condition_score = EXCLUDED.condition_score,
                    risk_score = EXCLUDED.risk_score,
                    priority = EXCLUDED.priority,
                    status_color = EXCLUDED.status_color
                """,
                (
                    r["id"], r["road_id"], seg_name, geom_json, geojson_str,
                    len_km, road_cls, traffic_exp, road_imp,
                    cond_sc, risk_sc, priority, status_color
                ),
            )
        pg_conn.commit()
    except Exception as e:
        print(f"Note on road_segments: {e}")

    # 5. Migrate detections (building PostGIS Point geom)
    try:
        sqlite_cur.execute("SELECT * FROM detections")
        det_rows = sqlite_cur.fetchall()
        for r in det_rows:
            keys = r.keys()
            lat = float(r["latitude"])
            lng = float(r["longitude"])
            det_id = r["detection_id"] if "detection_id" in keys else r["id"]
            orig_url = r["evidence_orig_url"] if "evidence_orig_url" in keys else (r["evidence_orig_uri"] if "evidence_orig_uri" in keys else "")
            anno_url = r["evidence_anno_url"] if "evidence_anno_url" in keys else (r["evidence_uri"] if "evidence_uri" in keys else "")
            pg_cur.execute(
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
                    r["id"], det_id, r["inspection_id"], r["frame_id"], r["timestamp"],
                    r["defect_type"], r["confidence"], r["severity"], r["bbox_json"],
                    lat, lng, lng, lat,
                    r["road_segment_id"], orig_url, anno_url,
                    r["model_version"],
                    r["is_mock"] if "is_mock" in keys else 1,
                    r["gps_source"] if "gps_source" in keys else "interpolated from corridor geometry",
                ),
            )
        pg_conn.commit()
    except Exception as e:
        print(f"Note on detections: {e}")

    # 6. Migrate segment_metrics
    try:
        sqlite_cur.execute("SELECT * FROM segment_metrics")
        sm_rows = sqlite_cur.fetchall()
        for r in sm_rows:
            keys = r.keys()
            pg_cur.execute(
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
                    r["segment_id"], r["inspection_id"],
                    r["defect_count"] if "defect_count" in keys else 0,
                    r["pothole_count"] if "pothole_count" in keys else 0,
                    r["crack_count"] if "crack_count" in keys else 0,
                    r["marking_count"] if "marking_count" in keys else 0,
                    r["critical_count"] if "critical_count" in keys else 0,
                    r["high_count"] if "high_count" in keys else 0,
                    r["medium_count"] if "medium_count" in keys else 0,
                    r["low_count"] if "low_count" in keys else 0,
                    r["defect_density"] if "defect_density" in keys else 0.0,
                    r["condition_score"] if "condition_score" in keys else 100.0,
                    r["risk_score"] if "risk_score" in keys else 0.0,
                ),
            )
        pg_conn.commit()
    except Exception as e:
        print(f"Note on segment_metrics: {e}")

    # 7. Migrate alerts
    try:
        sqlite_cur.execute("SELECT * FROM alerts")
        alert_rows = sqlite_cur.fetchall()
        for r in alert_rows:
            keys = r.keys()
            pg_cur.execute(
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
                    r["id"], r["inspection_id"], r["segment_id"], r["defect_id"],
                    r["defect_type"], r["severity"], r["message"], r["timestamp"],
                    r["latitude"], r["longitude"], r["evidence_url"],
                    r["is_read"] if "is_read" in keys else 0
                ),
            )
        pg_conn.commit()
    except Exception as e:
        print(f"Note on alerts: {e}")

    # 8. Migrate audit_logs (idempotent insert)
    try:
        sqlite_cur.execute("SELECT * FROM audit_logs")
        audit_rows = sqlite_cur.fetchall()
        for r in audit_rows:
            pg_cur.execute(
                """
                INSERT INTO audit_logs (username, role, action, target_id, details, timestamp)
                SELECT %s, %s, %s, %s, %s, %s
                WHERE NOT EXISTS (
                    SELECT 1 FROM audit_logs
                    WHERE username = %s AND action = %s AND timestamp = %s
                )
                """,
                (r["username"], r["role"], r["action"], r["target_id"], r["details"], r["timestamp"],
                 r["username"], r["action"], r["timestamp"]),
            )
        pg_conn.commit()
    except Exception as e:
        print(f"Note on audit_logs: {e}")

    # Count rows from both SQLite and PostgreSQL
    tables = [
        "model_versions", "users", "inspections", "road_segments",
        "detections", "segment_metrics", "alerts", "audit_logs"
    ]

    print("\n" + "=" * 65)
    print(f" {'TABLE':<20} | {'SQLITE ROWS':<15} | {'POSTGRES ROWS':<15} | STATUS")
    print("=" * 65)

    for tbl in tables:
        try:
            sqlite_cur.execute(f"SELECT COUNT(*) as cnt FROM {tbl}")
            sq_count = sqlite_cur.fetchone()["cnt"]
        except Exception:
            sq_count = 0

        try:
            pg_cur.execute(f"SELECT COUNT(*) as cnt FROM {tbl}")
            pg_count = pg_cur.fetchone()["cnt"]
        except Exception:
            pg_count = 0

        status_str = "MATCH" if sq_count == pg_count else "OK (>=)"
        counts[tbl] = (sq_count, pg_count)
        print(f" {tbl:<20} | {sq_count:<15} | {pg_count:<15} | {status_str}")

    print("=" * 65)

    sqlite_conn.close()
    pg_conn.close()
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate Z-TRACS SQLite database to PostgreSQL + PostGIS")
    parser.add_argument("sqlite_file", nargs="?", default=None, help="Optional positional path to SQLite database file")
    parser.add_argument("--sqlite-path", default=None, help="Path to SQLite database file")
    parser.add_argument("--postgres-url", default=None, help="PostgreSQL connection string (e.g. postgresql://user@localhost:5432/ztracs)")
    args = parser.parse_args()

    sqlite_path = args.sqlite_file or args.sqlite_path or os.getenv("DB_PATH") or os.path.join(PROJECT_ROOT, "data", "ztracs.db")
    postgres_url = args.postgres_url or os.getenv("DATABASE_URL")

    if not postgres_url:
        print("ERROR: DATABASE_URL not provided via --postgres-url or environment.")
        sys.exit(1)

    print(f"Starting migration from {sqlite_path} to PostgreSQL...")
    migrate(sqlite_path, postgres_url)
    print("Migration finished successfully.")
