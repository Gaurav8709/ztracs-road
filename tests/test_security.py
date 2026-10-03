import os
import sys
import time
import hmac
import hashlib
import shutil
import tempfile
import secrets
import subprocess
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import getpass
import psycopg

# Create separate temporary test environment
TEST_TMP_DIR = tempfile.mkdtemp(prefix="ztracs_test_sec_")
TEST_DATA_DIR = os.path.join(TEST_TMP_DIR, "data")
TEST_EVIDENCE_DIR = os.path.join(TEST_TMP_DIR, "evidence")
TEST_REPORTS_DIR = os.path.join(TEST_TMP_DIR, "reports")
TEST_VIDEO_DIR = os.path.join(TEST_TMP_DIR, "video")

for d in (TEST_DATA_DIR, TEST_EVIDENCE_DIR, TEST_REPORTS_DIR, TEST_VIDEO_DIR):
    os.makedirs(d, exist_ok=True)

# Generate ephemeral PostgreSQL database for this test run (supports Docker PostGIS)
def _get_pg_config(prefix="ztracs_test_sec"):
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

BASE_PG_URL, TEST_DATABASE_URL, TEST_PG_DB = _get_pg_config("ztracs_test_sec")

# Create isolated test Postgres database
with psycopg.connect(BASE_PG_URL, autocommit=True) as conn:
    with conn.cursor() as cur:
        cur.execute(f"CREATE DATABASE {TEST_PG_DB};")

# Generate random JWT secret and dynamic test passwords
TEST_JWT_SECRET = secrets.token_urlsafe(48)
TEST_ADMIN_USERNAME = f"secadmin_{secrets.token_hex(4)}"
TEST_ADMIN_PASSWORD = f"A_{secrets.token_urlsafe(16)}!9"
TEST_USER_PASSWORD = f"U_{secrets.token_urlsafe(16)}!1"
TEST_WRONG_PASSWORD = f"W_{secrets.token_urlsafe(16)}?2"

os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["JWT_SECRET"] = TEST_JWT_SECRET
os.environ["ADMIN_USERNAME"] = TEST_ADMIN_USERNAME
os.environ["ADMIN_PASSWORD"] = TEST_ADMIN_PASSWORD
os.environ["DATA_DIR"] = TEST_DATA_DIR
os.environ["EVIDENCE_DIR"] = TEST_EVIDENCE_DIR
os.environ["REPORTS_DIR"] = TEST_REPORTS_DIR
os.environ["VIDEO_DIR"] = TEST_VIDEO_DIR
os.environ["ALLOWED_ORIGINS"] = "http://localhost:8000,http://127.0.0.1:8000,http://localhost:3000,http://127.0.0.1:3000"

from fastapi.testclient import TestClient
from starlette.routing import Route

from backend.auth import RATE_LIMIT_BUCKETS, create_access_token
from backend.database import init_db
from backend.seed_data import seed_demo_data
from backend.main import app

# Initialize isolated test database
init_db()
seed_demo_data(force=True)

client = TestClient(app)
checks = []
USER_PREFIX = f"user_{secrets.token_hex(4)}"


def unique_username(suffix: str) -> str:
    return f"{USER_PREFIX}_{suffix}"


def require_http_code(resp, code):
    if resp.status_code != code:
        raise AssertionError(f"expected {code}, got {resp.status_code}: {resp.text[:200]}")


def record(name, fn):
    try:
        fn()
        print(f"PASS: {name}")
        checks.append((name, True))
    except Exception as exc:
        print(f"FAIL: {name}: {exc}")
        checks.append((name, False))


def get_admin_login():
    return client.post("/api/auth/login", json={"username": TEST_ADMIN_USERNAME, "password": TEST_ADMIN_PASSWORD})


def test_html_no_demo_credentials():
    html = Path("frontend/index.html").read_text()
    forbidden_tokens = [f"admin{x}" for x in (123,)] + [f"viewer{x}" for x in (123,)] + [f"inspector{x}" for x in (123,)]
    for t in forbidden_tokens:
        assert t not in html
    assert "SQLite" not in html, "Stale SQLite badge found in frontend/index.html" 


def test_register_new_user():
    username = unique_username("01")
    res = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "full_name": "New User",
            "password": TEST_USER_PASSWORD,
            "confirm_password": TEST_USER_PASSWORD,
        },
    )
    require_http_code(res, 201)
    assert res.json()["user"]["role"] == "viewer"
    assert res.json()["user"]["username"] == username


def test_duplicate_user_rejected():
    username = unique_username("01")
    res = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "full_name": "Another",
            "password": TEST_USER_PASSWORD,
            "confirm_password": TEST_USER_PASSWORD,
        },
    )
    require_http_code(res, 409)


def test_short_password_rejected():
    username = unique_username("02")
    res = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "full_name": "Another",
            "password": "short",
            "confirm_password": "short",
        },
    )
    require_http_code(res, 422)


def test_client_role_ignored():
    username = unique_username("03")
    res = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "full_name": "Third User",
            "password": TEST_USER_PASSWORD,
            "confirm_password": TEST_USER_PASSWORD,
            "role": "admin",
        },
    )
    require_http_code(res, 201)
    assert res.json()["user"]["role"] == "viewer"


def test_wrong_password_generic_401():
    RATE_LIMIT_BUCKETS.clear()
    username = unique_username("wrongpass")
    client.post(
        "/api/auth/register",
        json={
            "username": username,
            "full_name": "New User",
            "password": TEST_USER_PASSWORD,
            "confirm_password": TEST_USER_PASSWORD,
        },
    )
    res = client.post("/api/auth/login", json={"username": username, "password": TEST_WRONG_PASSWORD})
    require_http_code(res, 401)
    assert "Wrong username or password" in res.json()["detail"]


def test_rate_limit_on_failed_logins():
    RATE_LIMIT_BUCKETS.clear()
    username = unique_username("rate")
    client.post(
        "/api/auth/register",
        json={
            "username": username,
            "full_name": "Rate Limited",
            "password": TEST_USER_PASSWORD,
            "confirm_password": TEST_USER_PASSWORD,
        },
    )
    for i in range(5):
        client.post("/api/auth/login", json={"username": username, "password": f"bad{i}"})
    res = client.post("/api/auth/login", json={"username": username, "password": "bad9"})
    require_http_code(res, 429)


def test_all_protected_routes_return_401_without_token():
    public_routes = {
        ("/", "GET"),
        ("/api/health", "GET"),
        ("/api/auth/register", "POST"),
        ("/api/auth/login", "POST"),
        ("/openapi.json", "GET"),
        ("/docs", "GET"),
        ("/docs/oauth2-redirect", "GET"),
        ("/redoc", "GET"),
        ("/data/{path:path}", "GET"),
    }
    tested_count = 0
    for route in app.routes:
        if isinstance(route, Route):
            for m in (route.methods - {"HEAD", "OPTIONS"} if route.methods else ["GET"]):
                if (route.path, m) in public_routes:
                    continue
                req_path = route.path.replace("{id}", "DEMO-001").replace("{filename}", "demo_road.mp4")
                fn = getattr(client, m.lower())
                resp = fn(req_path)
                assert resp.status_code == 401, f"Route {m} {route.path} did not require authentication (got {resp.status_code})"
                tested_count += 1
    assert tested_count >= 20, f"Expected to test at least 20 protected routes, tested {tested_count}"


def test_viewer_forbidden_on_restricted_actions():
    RATE_LIMIT_BUCKETS.clear()
    username = unique_username("viewer")
    reg = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "full_name": "Viewer User",
            "password": TEST_USER_PASSWORD,
            "confirm_password": TEST_USER_PASSWORD,
        },
    )
    require_http_code(reg, 201)
    viewer_login = client.post("/api/auth/login", json={"username": username, "password": TEST_USER_PASSWORD})
    require_http_code(viewer_login, 200)
    viewer_token = viewer_login.json()["access_token"]
    vh = {"Authorization": f"Bearer {viewer_token}"}

    # Viewer gets 403 on ingest, report generation, mark alert read, demo reset, start, upload, create inspection
    require_http_code(client.post("/api/inspections/DEMO-001/detections/ingest", headers=vh, json={"detections": []}), 403)
    require_http_code(client.post("/api/reports?inspection_id=DEMO-001", headers=vh), 403)
    require_http_code(client.post("/api/alerts/1/read", headers=vh), 403)
    require_http_code(client.post("/api/demo/reset", headers=vh), 403)
    require_http_code(client.post("/api/inspections/DEMO-001/start", headers=vh), 403)
    require_http_code(client.post("/api/inspections/DEMO-001/upload", headers=vh, files={"file": ("v.mp4", b"123", "video/mp4")}), 403)
    require_http_code(client.post("/api/inspections", headers=vh, json={"name": "x", "road_id": "R1", "road_name": "R", "source_type": "V", "model_version": "M"}), 403)
    require_http_code(client.get("/api/users", headers=vh), 403)
    require_http_code(client.get("/api/audit-logs", headers=vh), 403)


def test_inspector_can_manage_own_work_but_not_admin():
    RATE_LIMIT_BUCKETS.clear()
    admin_login = get_admin_login()
    require_http_code(admin_login, 200)
    admin_token = admin_login.json()["access_token"]

    inspector_username = unique_username("inspector")
    inspector_register = client.post(
        "/api/auth/register",
        json={
            "username": inspector_username,
            "full_name": "Inspector User",
            "password": TEST_USER_PASSWORD,
            "confirm_password": TEST_USER_PASSWORD,
        },
    )
    require_http_code(inspector_register, 201)
    user_list = client.get("/api/users", headers={"Authorization": f"Bearer {admin_token}"})
    target = next(u for u in user_list.json() if u["username"] == inspector_username)
    patch = client.patch(f"/api/users/{target['id']}/role", headers={"Authorization": f"Bearer {admin_token}"}, json={"role": "inspector"})
    require_http_code(patch, 200)

    inspector_login = client.post("/api/auth/login", json={"username": inspector_username, "password": TEST_USER_PASSWORD})
    require_http_code(inspector_login, 200)
    inspector_token = inspector_login.json()["access_token"]
    ih = {"Authorization": f"Bearer {inspector_token}"}

    # Inspector can create, upload, and start inspections
    create = client.post(
        "/api/inspections",
        headers=ih,
        json={
            "name": "Inspection A",
            "road_id": "RD-1",
            "road_name": "Road 1",
            "source_type": "Vehicle Camera",
            "model_version": "RoadDefect-v1.0",
        },
    )
    require_http_code(create, 201)
    insp_id = create.json()["id"]

    upload = client.post(
        f"/api/inspections/{insp_id}/upload",
        headers=ih,
        files={"file": ("demo.mp4", b"123", "video/mp4")},
    )
    require_http_code(upload, 200)

    start = client.post(f"/api/inspections/{insp_id}/start", headers=ih)
    require_http_code(start, 200)

    # Inspector gets 403 on demo reset, users, and audit logs
    require_http_code(client.post("/api/demo/reset", headers=ih), 403)
    require_http_code(client.get("/api/users", headers=ih), 403)
    require_http_code(client.patch(f"/api/users/{target['id']}/role", headers=ih, json={"role": "admin"}), 403)
    require_http_code(client.get("/api/audit-logs", headers=ih), 403)


def test_admin_can_list_users_and_roles():
    RATE_LIMIT_BUCKETS.clear()
    admin_login = get_admin_login()
    require_http_code(admin_login, 200)
    admin_token = admin_login.json()["access_token"]

    res = client.get("/api/users", headers={"Authorization": f"Bearer {admin_token}"})
    require_http_code(res, 200)
    target_user = unique_username("adminrole")
    reg = client.post(
        "/api/auth/register",
        json={
            "username": target_user,
            "full_name": "Role User",
            "password": TEST_USER_PASSWORD,
            "confirm_password": TEST_USER_PASSWORD,
        },
    )
    require_http_code(reg, 201)
    users = client.get("/api/users", headers={"Authorization": f"Bearer {admin_token}"}).json()
    target = next(u for u in users if u["username"] == target_user)
    patch = client.patch(f"/api/users/{target['id']}/role", headers={"Authorization": f"Bearer {admin_token}"}, json={"role": "inspector"})
    require_http_code(patch, 200)
    assert patch.json()["role"] == "inspector"


def test_bad_token_rejected():
    bad = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0.invalidsignature"
    require_http_code(client.get("/api/auth/me", headers={"Authorization": f"Bearer {bad}"}), 401)


def test_expired_token_returns_401():
    expired_token = create_access_token({"sub": TEST_ADMIN_USERNAME, "role": "admin"}, expires_delta=timedelta(seconds=-3600))
    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired_token}"})
    require_http_code(resp, 401)
    assert "expired" in resp.json().get("detail", "").lower()


def test_startup_without_jwt_secret_fails_subprocess():
    env = os.environ.copy()
    env.pop("JWT_SECRET", None)
    env["PYTHONPATH"] = str(ROOT)

    proc = subprocess.run(
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--port", "58199"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    assert proc.returncode != 0, "Expected server startup to fail without JWT_SECRET, got returncode 0"
    output = (proc.stderr + proc.stdout)
    assert "JWT_SECRET" in output, f"Expected 'JWT_SECRET' in error output, got: {output[:300]}"


def test_startup_without_database_url_fails_subprocess():
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    env["PYTHONPATH"] = str(ROOT)

    proc = subprocess.run(
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--port", "58198"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    assert proc.returncode != 0, "Expected server startup to fail without DATABASE_URL, got returncode 0"
    output = (proc.stderr + proc.stdout)
    assert "DATABASE_URL" in output, f"Expected 'DATABASE_URL' in error output, got: {output[:300]}"


def test_login_as_legacy_accounts_returns_401():
    RATE_LIMIT_BUCKETS.clear()
    dummy_pass = f"p_{secrets.token_urlsafe(8)}"
    res_i = client.post("/api/auth/login", json={"username": "inspector", "password": dummy_pass})
    require_http_code(res_i, 401)

    res_v = client.post("/api/auth/login", json={"username": "viewer", "password": dummy_pass})
    require_http_code(res_v, 401)


def test_upload_validation_rejects_bad_files():
    RATE_LIMIT_BUCKETS.clear()
    admin_login = get_admin_login()
    require_http_code(admin_login, 200)
    admin_token = admin_login.json()["access_token"]

    bad_txt = client.post(
        "/api/inspections/DEMO-001/upload",
        headers={"Authorization": f"Bearer {admin_token}"},
        files={"file": ("renamed.mp4", b"hello not video", "text/plain")},
    )
    require_http_code(bad_txt, 415)

    large = client.post(
        "/api/inspections/DEMO-001/upload",
        headers={"Authorization": f"Bearer {admin_token}"},
        files={"file": ("big.mp4", b"0" * (600 * 1024 * 1024), "video/mp4")},
    )
    require_http_code(large, 413)

    evil = client.post(
        "/api/inspections/DEMO-001/upload",
        headers={"Authorization": f"Bearer {admin_token}"},
        files={"file": ("../../evil.mp4", b"\x00\x00\x00ftyp", "video/mp4")},
    )
    require_http_code(evil, 200)
    assert "evil" not in evil.json()["video_url"]


def test_pdf_requires_authorization_header_and_disallows_token_query():
    RATE_LIMIT_BUCKETS.clear()
    admin_login = get_admin_login()
    require_http_code(admin_login, 200)
    admin_token = admin_login.json()["access_token"]

    pdf = client.post("/api/reports", headers={"Authorization": f"Bearer {admin_token}"}, params={"inspection_id": "DEMO-001"})
    require_http_code(pdf, 200)
    pdf_url = pdf.json()["pdf_url"]

    file_resp = client.get(pdf_url, headers={"Authorization": f"Bearer {admin_token}"})
    require_http_code(file_resp, 200)
    assert file_resp.headers["content-type"].startswith("application/pdf")

    noauth = client.get(pdf_url)
    require_http_code(noauth, 401)

    token_q = client.get(pdf_url + "?token=abc", headers={"Authorization": f"Bearer {admin_token}"})
    require_http_code(token_q, 400)


def test_cors_rejects_unapproved_origin():
    resp = client.options(
        "/api/auth/login",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in {k.lower(): v for k, v in resp.headers.items()}


def test_cors_accepts_approved_origin_and_preflight():
    resp = client.options(
        "/api/inspections",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization, content-type",
        },
    )
    headers_lower = {k.lower(): v for k, v in resp.headers.items()}
    assert headers_lower.get("access-control-allow-origin") == "http://localhost:3000", f"Unexpected origin header: {headers_lower}"
    assert "authorization" in headers_lower.get("access-control-allow-headers", "").lower()

    resp_ip = client.options(
        "/api/auth/login",
        headers={
            "Origin": "http://127.0.0.1:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    headers_ip = {k.lower(): v for k, v in resp_ip.headers.items()}
    assert headers_ip.get("access-control-allow-origin") == "http://127.0.0.1:3000"


def test_static_traversal_blocked_and_db_not_downloadable():
    traversal = client.get("/static/../data/ztracs.db")
    require_http_code(traversal, 404)

    db_url = client.get("/static/data/ztracs.db")
    require_http_code(db_url, 404)

    direct = client.get("/data/ztracs.db")
    require_http_code(direct, 404)


def test_demo_analytics_still_loaded():
    RATE_LIMIT_BUCKETS.clear()
    admin_login = get_admin_login()
    require_http_code(admin_login, 200)
    admin_token = admin_login.json()["access_token"]

    demo = client.get("/api/analytics/overview?inspection_id=DEMO-001", headers={"Authorization": f"Bearer {admin_token}"})
    require_http_code(demo, 200)
    payload = demo.json()
    assert payload["total_defects"] == 24
    assert payload["critical_defects"] >= 2


def test_media_signing_and_range_streaming():
    # 1. Sign without auth gives 401
    r_noauth = client.get("/api/media/sign?file=demo_road.mp4")
    require_http_code(r_noauth, 401)

    # 2. Login to get token
    login = get_admin_login()
    token = login.json()["access_token"]

    # 3. Sign with auth gives 200 and signed URL
    r_sign = client.get("/api/media/sign?file=demo_road.mp4", headers={"Authorization": f"Bearer {token}"})
    require_http_code(r_sign, 200)
    sign_data = r_sign.json()
    signed_url = sign_data["url"]
    expires = sign_data["expires"]
    signature = sign_data["signature"]

    # 4. Video without signature gives 401
    r_nosig = client.get("/api/media/video/demo_road.mp4")
    require_http_code(r_nosig, 401)

    # 5. Tampered signature gives 401
    r_tampered = client.get(f"/api/media/video/demo_road.mp4?expires={expires}&signature=tampered_{signature[:10]}")
    require_http_code(r_tampered, 401)

    # 6. Expired signature gives 401
    past_exp = int(time.time()) - 120
    past_msg = f"demo_road.mp4:{past_exp}".encode("utf-8")
    past_sig = hmac.new(TEST_JWT_SECRET.encode("utf-8"), past_msg, hashlib.sha256).hexdigest()
    r_expired = client.get(f"/api/media/video/demo_road.mp4?expires={past_exp}&signature={past_sig}")
    require_http_code(r_expired, 401)

    # 7. Valid signature gives 200
    r_valid = client.get(signed_url)
    require_http_code(r_valid, 200)
    assert len(r_valid.content) > 1000

    # 8. Range request gives 206 Partial Content
    r_range = client.get(signed_url, headers={"Range": "bytes=0-1023"})
    require_http_code(r_range, 206)
    assert len(r_range.content) == 1024
    assert "bytes 0-1023/" in r_range.headers.get("content-range", "")



def test_old_static_paths_blocked_and_signed_evidence_works():
    for path in [
        "/static/media/evidence/DEMO-001/det_0001_orig.jpg",
        "/static/media/evidence/defect_00124_orig.jpg",
        "/static/media/video/demo_road.mp4",
        "/static/reports/inspection_DEMO-001_report.pdf",
    ]:
        res = client.get(path)
        assert res.status_code in (401, 404), f"Path {path} returned {res.status_code}, expected 401 or 404"

    login = get_admin_login()
    token = login.json()["access_token"]

    dummy_insp_dir = os.path.join(TEST_EVIDENCE_DIR, "TEST-SEC")
    os.makedirs(dummy_insp_dir, exist_ok=True)
    dummy_file = os.path.join(dummy_insp_dir, "det_test_orig.jpg")
    with open(dummy_file, "wb") as f:
        f.write(b"\xff\xd8\xff\xe0test_jpeg_bytes\xff\xd9")

    r_batch = client.post(
        "/api/media/sign-batch",
        headers={"Authorization": f"Bearer {token}"},
        json={"files": ["TEST-SEC/det_test_orig.jpg"], "type": "evidence"}
    )
    require_http_code(r_batch, 200)
    signed_data = r_batch.json()["signed"]["TEST-SEC/det_test_orig.jpg"]
    valid_signed_url = signed_data["url"]

    r_ev_valid = client.get(valid_signed_url)
    require_http_code(r_ev_valid, 200)

    r_tampered = client.get(valid_signed_url + "_tampered")
    require_http_code(r_tampered, 401)

    past_exp = int(time.time()) - 100
    past_msg = f"TEST-SEC/det_test_orig.jpg:{past_exp}".encode("utf-8")
    past_sig = hmac.new(TEST_JWT_SECRET.encode("utf-8"), past_msg, hashlib.sha256).hexdigest()
    r_expired = client.get(f"/api/media/evidence/TEST-SEC/det_test_orig.jpg?expires={past_exp}&signature={past_sig}")
    require_http_code(r_expired, 401)

    # sign-batch rejects >100 files with 422 (Item 4.b)
    over_100_files = [f"file_{i}.jpg" for i in range(101)]
    r_over_100 = client.post(
        "/api/media/sign-batch",
        headers={"Authorization": f"Bearer {token}"},
        json={"files": over_100_files, "type": "evidence"}
    )
    require_http_code(r_over_100, 422)

    # Subpath signature binding test (Requirement 6): A/det_0001_orig.jpg signature must NOT work for B/det_0001_orig.jpg
    dir_a = os.path.join(TEST_EVIDENCE_DIR, "A")
    dir_b = os.path.join(TEST_EVIDENCE_DIR, "B")
    os.makedirs(dir_a, exist_ok=True)
    os.makedirs(dir_b, exist_ok=True)
    with open(os.path.join(dir_a, "det_0001_orig.jpg"), "wb") as f:
        f.write(b"file_a_content")
    with open(os.path.join(dir_b, "det_0001_orig.jpg"), "wb") as f:
        f.write(b"file_b_content")

    r_sign_a = client.post(
        "/api/media/sign-batch",
        headers={"Authorization": f"Bearer {token}"},
        json={"files": ["A/det_0001_orig.jpg"], "type": "evidence"}
    )
    require_http_code(r_sign_a, 200)
    signed_url_a = r_sign_a.json()["signed"]["A/det_0001_orig.jpg"]["url"]

    # URL for A works
    r_a = client.get(signed_url_a)
    require_http_code(r_a, 200)
    assert r_a.content == b"file_a_content"

    # Exact same signature for A must NOT work for B
    signed_url_b_with_a_sig = signed_url_a.replace("/A/", "/B/")
    r_b = client.get(signed_url_b_with_a_sig)
    require_http_code(r_b, 401)


def test_demoted_user_refused_immediately():
    uname = f"demote_user_{secrets.token_hex(4)}"
    r_reg = client.post("/api/auth/register", json={"username": uname, "password": TEST_USER_PASSWORD, "confirm_password": TEST_USER_PASSWORD, "full_name": "Demote Test"})
    require_http_code(r_reg, 201)

    from backend.database import get_connection
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("UPDATE users SET role = 'inspector' WHERE username = %s", (uname,))
    conn.commit()
    conn.close()

    RATE_LIMIT_BUCKETS.clear()
    u_login = client.post("/api/auth/login", json={"username": uname, "password": TEST_USER_PASSWORD})
    require_http_code(u_login, 200)
    user_token = u_login.json()["access_token"]

    r_ok = client.post(
        "/api/inspections",
        headers={"Authorization": f"Bearer {user_token}"},
        json={"name": "Pre-Demote Survey", "road_id": "RD-001"}
    )
    require_http_code(r_ok, 201)

    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("UPDATE users SET role = 'viewer' WHERE username = %s", (uname,))
    conn.commit()
    conn.close()

    r_demoted = client.post(
        "/api/inspections",
        headers={"Authorization": f"Bearer {user_token}"},
        json={"name": "Post-Demote Survey", "road_id": "RD-001"}
    )
    require_http_code(r_demoted, 403)

    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE username = %s", (uname,))
    conn.commit()
    conn.close()

    r_deleted = client.get("/api/inspections", headers={"Authorization": f"Bearer {user_token}"})
    require_http_code(r_deleted, 401)

    # Demoted or deleted user must also be refused on evidence and video routes (Requirement 5)
    r_ev_deleted = client.get("/api/media/evidence/TEST-SEC/det_test_orig.jpg", headers={"Authorization": f"Bearer {user_token}"})
    require_http_code(r_ev_deleted, 401)

    r_vid_deleted = client.get("/api/media/video/demo_road.mp4", headers={"Authorization": f"Bearer {user_token}"})
    require_http_code(r_vid_deleted, 401)

    # Test demoting an active user to an unauthorized role
    uname2 = f"demote_user2_{secrets.token_hex(4)}"
    r_reg2 = client.post("/api/auth/register", json={"username": uname2, "password": TEST_USER_PASSWORD, "confirm_password": TEST_USER_PASSWORD, "full_name": "Demote Test 2"})
    require_http_code(r_reg2, 201)
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("UPDATE users SET role = 'viewer' WHERE username = %s", (uname2,))
    conn.commit()
    conn.close()

    RATE_LIMIT_BUCKETS.clear()
    u2_login = client.post("/api/auth/login", json={"username": uname2, "password": TEST_USER_PASSWORD})
    user2_token = u2_login.json()["access_token"]

    # Demote in DB to unauthorized role
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("UPDATE users SET role = 'unauthorized' WHERE username = %s", (uname2,))
    conn.commit()
    conn.close()

    r_ev_demoted = client.get("/api/media/evidence/TEST-SEC/det_test_orig.jpg", headers={"Authorization": f"Bearer {user2_token}"})
    assert r_ev_demoted.status_code in (401, 403), f"Expected 401 or 403 for demoted user on evidence route, got {r_ev_demoted.status_code}"

    r_vid_demoted = client.get("/api/media/video/demo_road.mp4", headers={"Authorization": f"Bearer {user2_token}"})
    assert r_vid_demoted.status_code in (401, 403), f"Expected 401 or 403 for demoted user on video route, got {r_vid_demoted.status_code}" 


def test_security_headers_present():
    for url in ["/", "/api/health"]:
        res = client.get(url)
        headers_lower = {k.lower(): v for k, v in res.headers.items()}
        assert headers_lower.get("x-content-type-options") == "nosniff"
        assert headers_lower.get("x-frame-options") == "DENY"
        assert headers_lower.get("referrer-policy") == "strict-origin-when-cross-origin"
        csp = headers_lower.get("content-security-policy", "")
        assert "default-src 'self'" in csp
        assert "script-src" in csp
        assert "frame-ancestors 'none'" in csp


def test_pdf_injection_escaping():
    admin_token = get_admin_login().json()["access_token"]
    insp_name = "<b>Bold</b> & <script>alert(1)</script>"
    r_create = client.post(
        "/api/inspections",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": insp_name, "road_id": "RD-001", "road_name": "Road & <xml>Tag</xml>"}
    )
    require_http_code(r_create, 201)
    insp_id = r_create.json()["id"]

    r_pdf = client.get(f"/api/reports/{insp_id}/pdf", headers={"Authorization": f"Bearer {admin_token}"})
    require_http_code(r_pdf, 200)
    assert len(r_pdf.content) > 1000


def test_docs_disabled_by_default_and_enabled_with_flag():
    for endpoint in ["/docs", "/redoc", "/openapi.json"]:
        r = client.get(endpoint)
        require_http_code(r, 404)

    code = f'''
import os
os.environ["DATABASE_URL"] = "{TEST_DATABASE_URL}"
os.environ["JWT_SECRET"] = "{TEST_JWT_SECRET}"
os.environ["ADMIN_USERNAME"] = "{TEST_ADMIN_USERNAME}"
os.environ["ADMIN_PASSWORD"] = "{TEST_ADMIN_PASSWORD}"
os.environ["ENABLE_DOCS"] = "1"
from fastapi.testclient import TestClient
from backend.main import app
c = TestClient(app)
assert c.get("/docs").status_code == 200
assert c.get("/openapi.json").status_code == 200
print("DOCS_ENABLED_OK")
'''
    res = subprocess.run([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert res.returncode == 0 and "DOCS_ENABLED_OK" in res.stdout


def test_database_connection_error_never_leaks_password():
    secret_pass = "P@ssw0rd_Secret_98765_LeakCheck!"
    fake_db_url = f"postgresql://dbuser:{secret_pass}@127.0.0.1:5439/testleaksdb"

    # 1. Verify backend.database.get_connection() masks credentials and never leaks password
    from backend.database import get_connection
    orig_url = os.environ.get("DATABASE_URL")
    try:
        os.environ["DATABASE_URL"] = fake_db_url
        raised = False
        try:
            get_connection()
        except Exception as e:
            raised = True
            err_msg = str(e)
            assert secret_pass not in err_msg, f"DATABASE PASSWORD LEAKED in error message: {err_msg}"
            assert "127.0.0.1" in err_msg, f"Expected host in error message: {err_msg}"
            assert "5439" in err_msg, f"Expected port in error message: {err_msg}"
            assert "testleaksdb" in err_msg, f"Expected database name in error message: {err_msg}"
        assert raised, "Expected get_connection to raise OperationalError on unreachable port 5439"
    finally:
        if orig_url:
            os.environ["DATABASE_URL"] = orig_url

    # 2. Verify run.sh connectivity check never leaks password
    import subprocess
    run_sh_template = '''
import os, sys, psycopg
from urllib.parse import urlsplit
db_url = "__TEST_URL__"
try:
    with psycopg.connect(db_url, connect_timeout=1) as conn:
        pass
except Exception:
    try:
        parts = urlsplit(db_url)
        host = parts.hostname or "localhost"
        port = parts.port or 5432
        dbname = parts.path.lstrip("/").split("?")[0] if parts.path else "unknown"
        target_info = f"host={host}, port={port}, database={dbname}"
    except Exception:
        target_info = "host=unknown, port=unknown, database=unknown"
    print(f"ERROR: Cannot connect to database ({target_info}): Connection failed. (Credentials masked)", file=sys.stderr)
    sys.exit(1)
'''
    run_sh_snippet = run_sh_template.replace("__TEST_URL__", fake_db_url)
    proc = subprocess.run([sys.executable, "-c", run_sh_snippet], capture_output=True, text=True)
    combined = proc.stdout + proc.stderr
    assert secret_pass not in combined, f"Password leaked in run.sh check output: {combined}"
    assert "127.0.0.1" in combined and "5439" in combined and "testleaksdb" in combined


def test_input_hardening_ingest_and_upload():
    RATE_LIMIT_BUCKETS.clear()
    admin_login = get_admin_login()
    require_http_code(admin_login, 200)
    admin_token = admin_login.json()["access_token"]
    headers = {"Authorization": f"Bearer {admin_token}"}

    r_create = client.post("/api/inspections", headers=headers, json={"name": "Hardening Test", "road_id": "RD-001"})
    require_http_code(r_create, 201)
    insp_id = r_create.json()["id"]

    valid_base = {
        "detection_id": "DET-001",
        "frame_id": 1,
        "timestamp": 1.0,
        "class": "pothole",
        "confidence": 0.9,
        "bbox": [10, 10, 50, 50],
        "severity": "high",
        "latitude": 19.0,
        "longitude": 73.0,
        "evidence_uri": "mock.jpg"
    }

    bad_lon = {**valid_base, "longitude": 200.0}
    r = client.post(f"/api/inspections/{insp_id}/detections/ingest", headers=headers, json=[bad_lon])
    require_http_code(r, 422)

    bad_sev = {**valid_base, "severity": "banana"}
    r = client.post(f"/api/inspections/{insp_id}/detections/ingest", headers=headers, json=[bad_sev])
    require_http_code(r, 422)

    bad_uri = {**valid_base, "evidence_uri": "http://evil/x.jpg"}
    r = client.post(f"/api/inspections/{insp_id}/detections/ingest", headers=headers, json=[bad_uri])
    require_http_code(r, 422)

    big_batch = [{**valid_base, "detection_id": f"DET-{i}"} for i in range(501)]
    r = client.post(f"/api/inspections/{insp_id}/detections/ingest", headers=headers, json=big_batch)
    require_http_code(r, 422)

    r_zero = client.post(
        f"/api/inspections/{insp_id}/upload",
        headers=headers,
        files={"file": ("empty.mp4", b"", "video/mp4")}
    )
    require_http_code(r_zero, 400)

tests = [
    ("HTML contains no demo credentials", test_html_no_demo_credentials),
    ("Register new user succeeds and role is viewer", test_register_new_user),
    ("Register duplicate username rejected", test_duplicate_user_rejected),
    ("Short password rejected", test_short_password_rejected),
    ("Client role is ignored", test_client_role_ignored),
    ("Wrong password returns generic 401", test_wrong_password_generic_401),
    ("Rapid failed logins rate limit", test_rate_limit_on_failed_logins),
    ("All protected routes in app.routes return 401 without token", test_all_protected_routes_return_401_without_token),
    ("Viewer forbidden on restricted actions (403)", test_viewer_forbidden_on_restricted_actions),
    ("Inspector can manage work but forbidden on admin routes (403)", test_inspector_can_manage_own_work_but_not_admin),
    ("Admin can list users and roles", test_admin_can_list_users_and_roles),
    ("Bad token rejected", test_bad_token_rejected),
    ("Expired token returns 401", test_expired_token_returns_401),
    ("Startup without JWT_SECRET fails", test_startup_without_jwt_secret_fails_subprocess),
    ("Startup without DATABASE_URL fails", test_startup_without_database_url_fails_subprocess),
    ("Login as legacy accounts returns 401", test_login_as_legacy_accounts_returns_401),
    ("Upload validation rejects bad files", test_upload_validation_rejects_bad_files),
    ("PDF requires auth header and blocks token query", test_pdf_requires_authorization_header_and_disallows_token_query),
    ("CORS rejects unapproved origin", test_cors_rejects_unapproved_origin),
    ("CORS accepts approved origin & preflight auth", test_cors_accepts_approved_origin_and_preflight),
    ("Static traversal blocked and db not downloadable", test_static_traversal_blocked_and_db_not_downloadable),
    ("Demo analytics still load", test_demo_analytics_still_loaded),
    ("Media signing & Range requests 206", test_media_signing_and_range_streaming),
    ("Old static paths blocked & signed evidence works", test_old_static_paths_blocked_and_signed_evidence_works),
    ("Demoted user refused immediately with old token", test_demoted_user_refused_immediately),
    ("Security headers present on responses", test_security_headers_present),
    ("PDF injection escaping", test_pdf_injection_escaping),
    ("Docs disabled by default and enabled with ENABLE_DOCS=1", test_docs_disabled_by_default_and_enabled_with_flag),
    ("Input hardening ingest & zero-byte upload", test_input_hardening_ingest_and_upload),
    ("Database connection error never leaks password", test_database_connection_error_never_leaks_password),
]

try:
    for name, fn in tests:
        record(name, fn)
finally:
    # Clean up temporary test data directory and Postgres database
    shutil.rmtree(TEST_TMP_DIR, ignore_errors=True)
    try:
        with psycopg.connect(BASE_PG_URL, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(f"DROP DATABASE IF EXISTS {TEST_PG_DB} (FORCE);")
    except Exception:
        pass

print("\nSUMMARY")
passed_count = sum(1 for _, ok in checks if ok)
total_count = len(checks)
print(f"Total checks: {total_count} Passed: {passed_count}")
if any(not ok for _, ok in checks):
    raise SystemExit(1)
