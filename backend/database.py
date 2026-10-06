"""
Z-TRACS Road Intelligence - PostgreSQL + PostGIS Database Layer
Implements connection management, PostGIS geometry types, and schema initialization.
"""
import os
import uuid
from datetime import datetime
from typing import Optional
import bcrypt
import psycopg
from psycopg.rows import dict_row

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


from urllib.parse import urlsplit, urlunsplit


def mask_database_url(url: Optional[str]) -> str:
    """Masks credentials in a database connection URL."""
    if not url:
        return ""
    try:
        parts = urlsplit(url)
        if not parts.netloc:
            return url
        if "@" in parts.netloc:
            creds, _, hostport = parts.netloc.partition("@")
            user = creds.split(":")[0] if ":" in creds else creds
            masked_netloc = f"{user}:****@{hostport}"
        else:
            masked_netloc = parts.netloc
        return urlunsplit((parts.scheme, masked_netloc, parts.path, parts.query, parts.fragment))
    except Exception:
        return "[MASKED_DATABASE_URL]"


def get_masked_db_target(url: Optional[str]) -> str:
    """Extracts host, port, and database name with credentials masked/omitted."""
    if not url:
        return "host=unknown, port=unknown, database=unknown"
    try:
        parts = urlsplit(url)
        host = parts.hostname or "localhost"
        port = parts.port or 5432
        dbname = parts.path.lstrip("/").split("?")[0] if parts.path else "unknown"
        return f"host={host}, port={port}, database={dbname}"
    except Exception:
        return "host=unknown, port=unknown, database=unknown"


def get_connection():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("Missing required environment variable: DATABASE_URL must be configured.")
    try:
        return psycopg.connect(database_url, row_factory=dict_row)
    except Exception as e:
        target_info = get_masked_db_target(database_url)
        raise psycopg.OperationalError(
            f"Database connection error for target ({target_info}): connection failed. (Credentials masked)"
        ) from None


def hash_pw(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def record_audit_log(username: str, role: str, action: str, target_id: Optional[str] = None, details: Optional[str] = None):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            """
            INSERT INTO audit_logs (username, role, action, target_id, details, timestamp)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (username, role, action, target_id, details, now_str)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


_ALLOWED_ENSURE_COLUMNS = {
    ("inspections", "location"),
    ("users", "full_name"),
    ("detections", "geom"),
    ("detections", "is_mock"),
    ("inspections", "processing_mode"),
    ("inspections", "inspection_date"),
    ("inspections", "fps"),
    ("detections", "gps_source"),
    ("inspections", "duration_seconds"),
    ("inspections", "is_mock"),
    ("road_segments", "geom"),
}

_ALLOWED_COLUMN_DEFS = {
    "INTEGER DEFAULT 1",
    "TEXT NOT NULL DEFAULT ''",
    "TEXT DEFAULT 'interpolated from corridor geometry'",
    "TEXT DEFAULT ''",
    "REAL DEFAULT 0.0",
    "geometry(Point, 4326)",
    "geometry(LineString, 4326)",
    "TEXT DEFAULT 'Batch'",
}


def ensure_column(table_name: str, column_name: str, column_def: str):
    """Idempotently add a column, using a strict whitelist to prevent SQL injection (D15)."""
    if (table_name, column_name) not in _ALLOWED_ENSURE_COLUMNS:
        raise ValueError(f"ensure_column: table/column not in whitelist: {table_name}.{column_name}")
    if column_def not in _ALLOWED_COLUMN_DEFS:
        raise ValueError(f"ensure_column: column_def not in whitelist: {repr(column_def)}")

    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {column_name} {column_def}")
        conn.commit()
        conn.close()
    except Exception:
        pass


def find_nearest_segment_postgis(lat: float, lon: float, default_segment_id: str = "RD-001") -> str:
    """Find the nearest road segment ID using PostGIS KNN distance operator <->."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
        SELECT id
        FROM road_segments
        WHERE geom IS NOT NULL
        ORDER BY geom <-> ST_SetSRID(ST_MakePoint(%s, %s), 4326)
        LIMIT 1
        """,
            (lon, lat),
        )
        row = cursor.fetchone()
        conn.close()
        if row and row.get("id"):
            return row["id"]
    except Exception:
        pass
    return default_segment_id


def seed_users():
    admin_username = os.getenv("ADMIN_USERNAME", "admin")
    admin_password = os.getenv("ADMIN_PASSWORD", "admin123")
    if not admin_password or admin_password == "change-me-admin-password":
        admin_password = "admin123"

    conn = get_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    admin_hash = hash_pw(admin_password)

    cursor.execute("SELECT id FROM users WHERE LOWER(username) = %s", (admin_username.lower(),))
    admin_row = cursor.fetchone()
    if admin_row:
        cursor.execute(
            "UPDATE users SET password_hash = %s, full_name = %s, role = 'admin' WHERE id = %s",
            (admin_hash, admin_username, admin_row["id"]),
        )
    else:
        uid = f"USR-{uuid.uuid4().hex[:8].upper()}"
        cursor.execute(
            """
            INSERT INTO users (id, username, full_name, password_hash, role, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                username = EXCLUDED.username,
                full_name = EXCLUDED.full_name,
                password_hash = EXCLUDED.password_hash,
                role = EXCLUDED.role
            """,
            (uid, admin_username.lower(), admin_username, admin_hash, "admin", now_str),
        )

    cursor.execute("DELETE FROM users WHERE role = 'admin' AND LOWER(username) != %s", (admin_username.lower(),))
    cursor.execute("DELETE FROM users WHERE LOWER(username) IN ('inspector', 'viewer')")
    conn.commit()
    conn.close()


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis;")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            full_name TEXT NOT NULL DEFAULT '',
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_logs (
            id SERIAL PRIMARY KEY,
            username TEXT NOT NULL,
            role TEXT NOT NULL,
            action TEXT NOT NULL,
            target_id TEXT,
            details TEXT,
            timestamp TEXT NOT NULL
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS inspections (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            road_id TEXT NOT NULL,
            road_name TEXT NOT NULL,
            source_type TEXT NOT NULL,
            created_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            status TEXT NOT NULL,
            model_version TEXT NOT NULL,
            video_url TEXT NOT NULL,
            total_frames INTEGER DEFAULT 0,
            processed_frames INTEGER DEFAULT 0,
            defect_count INTEGER DEFAULT 0,
            progress_percent INTEGER DEFAULT 0,
            current_stage TEXT DEFAULT 'Initialized',
            error_message TEXT,
            inspection_date TEXT DEFAULT '',
            location TEXT DEFAULT '',
            processing_mode TEXT DEFAULT 'Batch',
            duration_seconds REAL DEFAULT 0.0,
            fps REAL DEFAULT 0.0,
            is_mock INTEGER DEFAULT 1
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS road_segments (
            id TEXT PRIMARY KEY,
            road_id TEXT NOT NULL,
            segment_name TEXT NOT NULL,
            geometry_json TEXT NOT NULL,
            geom geometry(LineString, 4326),
            length_km REAL NOT NULL,
            road_class TEXT NOT NULL,
            traffic_exposure REAL DEFAULT 0.5,
            road_importance REAL DEFAULT 0.8,
            condition_score REAL DEFAULT 85.0,
            risk_score REAL DEFAULT 20.0,
            priority TEXT DEFAULT 'P3',
            status_color TEXT DEFAULT 'GREEN'
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_road_segments_geom ON road_segments USING GIST (geom);")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS detections (
            id TEXT PRIMARY KEY,
            detection_id TEXT NOT NULL,
            inspection_id TEXT NOT NULL REFERENCES inspections(id) ON DELETE CASCADE,
            frame_id INTEGER NOT NULL,
            timestamp REAL NOT NULL,
            defect_type TEXT NOT NULL,
            confidence REAL NOT NULL,
            severity TEXT NOT NULL,
            bbox_json TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            geom geometry(Point, 4326),
            road_segment_id TEXT NOT NULL,
            evidence_orig_url TEXT NOT NULL,
            evidence_anno_url TEXT NOT NULL,
            model_version TEXT NOT NULL,
            is_mock INTEGER DEFAULT 1,
            gps_source TEXT DEFAULT 'interpolated from corridor geometry'
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_detections_geom ON detections USING GIST (geom);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_detections_inspection_id ON detections(inspection_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_detections_road_segment_id ON detections(road_segment_id);")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS segment_metrics (
            id SERIAL PRIMARY KEY,
            segment_id TEXT NOT NULL REFERENCES road_segments(id) ON DELETE CASCADE,
            inspection_id TEXT NOT NULL REFERENCES inspections(id) ON DELETE CASCADE,
            defect_count INTEGER DEFAULT 0,
            pothole_count INTEGER DEFAULT 0,
            crack_count INTEGER DEFAULT 0,
            marking_count INTEGER DEFAULT 0,
            critical_count INTEGER DEFAULT 0,
            high_count INTEGER DEFAULT 0,
            medium_count INTEGER DEFAULT 0,
            low_count INTEGER DEFAULT 0,
            defect_density REAL DEFAULT 0.0,
            condition_score REAL DEFAULT 100.0,
            risk_score REAL DEFAULT 0.0,
            CONSTRAINT uq_segment_metrics_insp_seg UNIQUE (inspection_id, segment_id)
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_segment_metrics_insp_seg ON segment_metrics(inspection_id, segment_id);")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS alerts (
            id TEXT PRIMARY KEY,
            inspection_id TEXT NOT NULL,
            segment_id TEXT NOT NULL,
            defect_id TEXT NOT NULL,
            defect_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            message TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            evidence_url TEXT NOT NULL,
            is_read INTEGER DEFAULT 0
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_alerts_inspection_id ON alerts(inspection_id);")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS assets (
            id TEXT PRIMARY KEY,
            road_id TEXT NOT NULL,
            segment_id TEXT NOT NULL REFERENCES road_segments(id) ON DELETE CASCADE,
            asset_type TEXT NOT NULL,
            asset_name TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            condition_score REAL DEFAULT 85.0,
            status TEXT DEFAULT 'OPERATIONAL',
            last_inspected TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_road_id ON assets(road_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_segment_id ON assets(segment_id);")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS model_versions (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            is_mock INTEGER DEFAULT 1
        )
        """
    )

    cursor.execute("SELECT COUNT(*) as count FROM model_versions")
    row = cursor.fetchone()
    if row["count"] == 0:
        cursor.execute(
            """
            INSERT INTO model_versions (id, name, description, is_mock) VALUES
            ('RoadDefect-v1.0', 'RoadDefect-v1.0 (Production Stable)', 'Standard mock object detector for road defects', 1),
            ('RoadDefect-v1.1', 'RoadDefect-v1.1 (High-Recall Cracks)', 'High-recall mock model for linear surface cracks', 1),
            ('RoadDefect-v1.2', 'RoadDefect-v1.2 (Multi-Modal Depth)', 'Multi-modal mock depth & segmentation model', 1)
            ON CONFLICT (id) DO NOTHING
            """
        )

    conn.commit()
    conn.close()

    ensure_column("users", "full_name", "TEXT NOT NULL DEFAULT ''")
    ensure_column("inspections", "inspection_date", "TEXT DEFAULT ''")
    ensure_column("inspections", "location", "TEXT DEFAULT ''")
    ensure_column("inspections", "processing_mode", "TEXT DEFAULT 'Batch'")
    ensure_column("inspections", "duration_seconds", "REAL DEFAULT 0.0")
    ensure_column("inspections", "fps", "REAL DEFAULT 0.0")
    ensure_column("inspections", "is_mock", "INTEGER DEFAULT 1")
    ensure_column("detections", "is_mock", "INTEGER DEFAULT 1")
    ensure_column("detections", "gps_source", "TEXT DEFAULT 'interpolated from corridor geometry'")
    ensure_column("road_segments", "geom", "geometry(LineString, 4326)")
    ensure_column("detections", "geom", "geometry(Point, 4326)")

    seed_users()


if __name__ == "__main__":
    init_db()
