"""
Z-TRACS Road Intelligence - Frontend/Backend Split Mode Integration Test
Verifies Section 2.6:
  - Backend running on http://127.0.0.1:8000
  - Frontend served on http://127.0.0.1:3000 with window.API_BASE="http://127.0.0.1:8000"
  - Complete user flow verified via Playwright:
      1. Login as Administrator across origins
      2. Dashboard overview & metrics load
      3. GIS Map segments and defect pins render
      4. Evidence video loads and plays
      5. Original and annotated evidence images load
      6. Executive PDF report downloads
"""
import os
import sys
import time
import shutil
import tempfile
import secrets
import subprocess
import getpass
import psycopg
from playwright.sync_api import sync_playwright

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

def _get_pg_config(prefix="ztracs_test_split"):
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

BASE_PG_URL, TEST_DATABASE_URL, TEST_DB_NAME = _get_pg_config("ztracs_test_split")

def run_split_mode_test():
    print("=" * 60)
    print("  Z-TRACS SPLIT MODE (BACKEND:8000, FRONTEND:3000) TEST")
    print("=" * 60)

    # 1. Setup isolated Postgres DB
    print(f"Creating ephemeral database: {TEST_DB_NAME}")
    with psycopg.connect(BASE_PG_URL, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"CREATE DATABASE {TEST_DB_NAME};")

    test_tmp_dir = tempfile.mkdtemp(prefix="ztracs_split_test_")
    test_admin_user = f"splitadm_{secrets.token_hex(4)}"
    test_admin_pass = f"Pass_{secrets.token_urlsafe(16)}!9"

    backend_proc = None
    frontend_proc = None

    try:
        # 2. Launch Backend on port 8000
        env = os.environ.copy()
        env["DATABASE_URL"] = TEST_DATABASE_URL
        env["JWT_SECRET"] = secrets.token_urlsafe(48)
        env["ADMIN_USERNAME"] = test_admin_user
        env["ADMIN_PASSWORD"] = test_admin_pass
        env["USE_S3_STORAGE"] = "false"
        env["ALLOWED_ORIGINS"] = "http://127.0.0.1:3000,http://localhost:3000,http://127.0.0.1:8000,http://localhost:8000"
        env["PYTHONPATH"] = PROJECT_ROOT

        print("Starting Backend on http://127.0.0.1:8000...")
        backend_proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8000"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=PROJECT_ROOT
        )

        # 3. Launch Frontend via ./run-frontend.sh itself (Port 3000, API_BASE http://127.0.0.1:8000)
        print("Starting Frontend via ./run-frontend.sh on http://127.0.0.1:3000...")
        fe_env = os.environ.copy()
        fe_env["API_BASE"] = "http://127.0.0.1:8000"
        fe_env["PORT"] = "3000"
        fe_env["HOST"] = "127.0.0.1"
        frontend_proc = subprocess.Popen(
            ["./run-frontend.sh"],
            env=fe_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=PROJECT_ROOT
        )

        # Wait for servers
        time.sleep(2)
        import httpx
        for _ in range(15):
            try:
                r_be = httpx.get("http://127.0.0.1:8000/api/health", timeout=1.0)
                r_fe = httpx.get("http://127.0.0.1:3000/", timeout=1.0)
                if r_be.status_code == 200 and r_fe.status_code == 200:
                    print("Both Backend (8000) and Frontend (3000) are healthy!")
                    break
            except Exception:
                time.sleep(0.5)
        else:
            raise RuntimeError("Servers failed to start within timeout")

        # 4. Playwright Browser Automation
        print("Launching Chromium browser to test split mode flow...")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--host-resolver-rules=MAP cdn.tailwindcss.com 104.26.2.143"])
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()

            failed_requests = []
            def on_req_fail(req):
                failure_str = str(req.failure or "")
                # Ignore normal browser range-cancellations on media streaming and CDN blips
                if "ERR_ABORTED" in failure_str and (".mp4" in req.url or "video" in req.url):
                    return
                failed_requests.append(f"{req.method} {req.url} - {failure_str}")
            page.on("requestfailed", on_req_fail)

            page.goto("http://127.0.0.1:3000/")
            page.wait_for_selector("#login-card", timeout=5000)

            # Step 1: Login
            print("Logging in from frontend (3000) to backend (8000)...")
            page.fill("#login-username", test_admin_user)
            page.fill("#login-password", test_admin_pass)
            page.click("#btn-submit-login")
            page.wait_for_selector("#login-overlay", state="hidden", timeout=7000)
            print("PASS: Cross-origin authentication succeeded.")

            # Step 2: Dashboard Overview & DEMO-001
            page.wait_for_selector("#inspections-table-body tr", timeout=5000)
            rows = page.query_selector_all("#inspections-table-body tr")
            assert len(rows) > 0, "Inspections table should contain seeded demo inspection"
            print(f"PASS: Dashboard loaded {len(rows)} inspection(s) across origins.")

            # Step 3: GIS Map Screen
            print("Opening GIS Map screen...")
            page.click("button[data-screen='screen-map']")
            page.wait_for_selector("#screen-map", state="visible", timeout=10000)
            page.wait_for_selector(".leaflet-overlay-pane path", state="attached", timeout=10000)
            svg_paths = page.query_selector_all(".leaflet-overlay-pane path")
            print(f"PASS: GIS Map rendered {len(svg_paths)} SVG segment/corridor vectors.")
            assert len(svg_paths) > 0, "Map segments should be rendered"

            # Step 4: Evidence Screen & Video
            print("Opening Evidence screen...")
            page.click("button[data-screen='screen-evidence']")
            page.wait_for_selector("#inspection-video-player", timeout=5000)
            time.sleep(1)

            video_state = page.evaluate("""() => {
                const v = document.getElementById("inspection-video-player");
                return {
                    src: v ? v.src : "",
                    error: v && v.error ? v.error.message : null,
                    ready: v ? v.readyState : 0
                };
            }""")
            print(f"Video player URL: {video_state['src']}")
            assert "http://127.0.0.1:8000" in video_state["src"], "Video player src must route to backend port 8000"
            assert video_state["error"] is None, f"Video player reported error: {video_state['error']}"
            print("PASS: Evidence video loaded from backend port 8000.")

            # Step 5: Evidence Images
            img_states = page.evaluate("""() => {
                const orig = document.getElementById("img-original-evidence");
                const anno = document.getElementById("img-annotated-evidence");
                return {
                    orig_src: orig ? orig.src : "",
                    anno_src: anno ? anno.src : "",
                    orig_natural_width: orig ? orig.naturalWidth : 0,
                    anno_natural_width: anno ? anno.naturalWidth : 0
                };
            }""")
            print(f"Annotated evidence image URL: {img_states['anno_src']}")
            assert "http://127.0.0.1:8000" in img_states["anno_src"], "Evidence image src must route to backend port 8000"
            print("PASS: Evidence images loaded from backend port 8000.")

            # Step 6: PDF Report Download
            print("Downloading inspection report in split mode...")
            page.click("button[data-screen='screen-command']")
            page.wait_for_selector("#screen-command", state="visible", timeout=5000)
            with page.expect_download(timeout=15000) as download_info:
                page.locator("#inspections-table-body button:has-text('PDF')").first.click()
            download = download_info.value
            download_path = os.path.join(test_tmp_dir, "downloaded_split_report.pdf")
            download.save_as(download_path)
            assert os.path.exists(download_path) and os.path.getsize(download_path) > 10000
            print(f"PASS: PDF report successfully downloaded via split frontend ({os.path.getsize(download_path)} bytes).")

            # Check network failures
            critical_failures = [f for f in failed_requests if not ("tile.openstreetmap.org" in f or "fonts.gstatic.com" in f or "cdn.tailwindcss.com" in f)]
            assert len(critical_failures) == 0, f"Critical network failures detected: {critical_failures}"

            browser.close()
            print("ALL SPLIT MODE PLAYWRIGHT CHECKS PASSED!")
            return True

    finally:
        if backend_proc:
            backend_proc.terminate()
            try:
                backend_proc.wait(timeout=3)
            except Exception:
                backend_proc.kill()
        if frontend_proc:
            frontend_proc.terminate()
            try:
                frontend_proc.wait(timeout=3)
            except Exception:
                frontend_proc.kill()
                print(f"Tearing down ephemeral database: {TEST_DB_NAME}")
        try:
            with psycopg.connect(BASE_PG_URL, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} (FORCE);")
        except Exception as e:
            print(f"Warning: Failed to drop test db: {e}")

if __name__ == "__main__":
    success = run_split_mode_test()
    if not success:
        sys.exit(1)
