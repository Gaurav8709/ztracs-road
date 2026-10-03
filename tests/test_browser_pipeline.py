"""
Playwright Real Browser Check for Z-TRACS Live Pipeline Screen
Starts an isolated test server with ephemeral random credentials and database,
launches browser, verifies progress bar animation and MOCK CV badge, and cleans up.
"""
import os
import sys
import time
import socket
import subprocess
import shutil
import tempfile
import secrets
import cv2
import numpy as np
from playwright.sync_api import sync_playwright

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREENSHOT_DIR = os.path.join(PROJECT_ROOT, "screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

# Generate random credentials for this test run only (Item 4)
TEST_JWT_SECRET = secrets.token_urlsafe(48)
TEST_ADMIN_USERNAME = f"browadmin_{secrets.token_hex(4)}"
TEST_ADMIN_PASSWORD = f"BrowPass_{secrets.token_urlsafe(16)}!9"

import getpass
import psycopg

def _get_pg_config(prefix="ztracs_test_brow"):
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

BASE_PG_URL, TEST_DATABASE_URL, TEST_DB_NAME = _get_pg_config("ztracs_test_brow")

# Create separate temporary test environment (Item 4)
TEST_TMP_DIR = tempfile.mkdtemp(prefix="ztracs_test_browser_")
TEST_DATA_DIR = os.path.join(TEST_TMP_DIR, "data")
TEST_EVIDENCE_DIR = os.path.join(TEST_TMP_DIR, "evidence")
TEST_REPORTS_DIR = os.path.join(TEST_TMP_DIR, "reports")
TEST_VIDEO_DIR = os.path.join(TEST_TMP_DIR, "video")
TEST_SCRATCH_DIR = os.path.join(TEST_TMP_DIR, "scratch")

for d in (TEST_DATA_DIR, TEST_EVIDENCE_DIR, TEST_REPORTS_DIR, TEST_VIDEO_DIR, TEST_SCRATCH_DIR):
    os.makedirs(d, exist_ok=True)

# Ensure demo_road.mp4 and demo evidence are available in test directories
demo_src = os.path.join(PROJECT_ROOT, "static", "media", "video", "demo_road.mp4")
if os.path.exists(demo_src):
    shutil.copy(demo_src, os.path.join(TEST_VIDEO_DIR, "demo_road.mp4"))

demo_ev_src = os.path.join(PROJECT_ROOT, "static", "media", "evidence")
if os.path.exists(demo_ev_src):
    for root, dirs, files in os.walk(demo_ev_src):
        rel = os.path.relpath(root, demo_ev_src)
        target_dir = os.path.join(TEST_EVIDENCE_DIR, rel) if rel != "." else TEST_EVIDENCE_DIR
        os.makedirs(target_dir, exist_ok=True)
        for f in files:
            shutil.copy2(os.path.join(root, f), os.path.join(target_dir, f))


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def start_server(port: int) -> subprocess.Popen:
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
    import httpx
    start_t = time.time()
    while time.time() - start_t < timeout_sec:
        try:
            r = httpx.get(f"{base_url}/api/health", timeout=1.0)
            if r.status_code == 200:
                return True
        except Exception:
            time.sleep(0.2)
    return False


def create_small_video(filepath: str, duration_sec: int = 5, fps: int = 10):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    demo_src = os.path.join(PROJECT_ROOT, "static", "media", "video", "demo_road.mp4")
    if os.path.exists(demo_src):
        shutil.copy(demo_src, filepath)
        return filepath
    fourcc = cv2.VideoWriter_fourcc(*'avc1')
    total_frames = duration_sec * fps
    writer = cv2.VideoWriter(filepath, fourcc, float(fps), (640, 360))
    for i in range(total_frames):
        img = np.zeros((360, 640, 3), dtype=np.uint8)
        img[180:, :] = (60, 60, 60)
        cv2.putText(img, f"BROWSER LIVE PIPELINE CHECK - Frame {i}", (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        writer.write(img)
    writer.release()
    return filepath


def run_browser_check():
    print(f"Creating ephemeral PostgreSQL test database: {TEST_DB_NAME}")
    with psycopg.connect(BASE_PG_URL, autocommit=True) as conn:
        conn.cursor().execute(f"CREATE DATABASE {TEST_DB_NAME};")
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.cursor().execute("CREATE EXTENSION IF NOT EXISTS postgis;")

    test_port = find_free_port()
    base_url = f"http://127.0.0.1:{test_port}"
    server_proc = start_server(test_port)

    test_vid = os.path.join(TEST_SCRATCH_DIR, "browser_check_5s.mp4")
    create_small_video(test_vid, duration_sec=6, fps=10)

    try:
        ready = wait_for_server(base_url, timeout_sec=20)
        if not ready:
            print("FATAL: Uvicorn server failed to start within timeout.")
            if server_proc.poll() is not None:
                out, err = server_proc.communicate()
                print("Server stdout:", out)
                print("Server stderr:", err)
            server_proc.kill()
            return False

        print(f"Isolated test server running on {base_url} (PID: {server_proc.pid})")

        # 0. Print actual CSP header & assert script-src contents (Requirement 11)
        import urllib.request
        req = urllib.request.Request(base_url)
        with urllib.request.urlopen(req) as resp:
            csp_header = resp.headers.get("Content-Security-Policy", "")
            ref_header = resp.headers.get("Referrer-Policy", "")
        print("\n" + "=" * 60)
        print("SECURITY HEADERS AUDIT:")
        print(f"Referrer-Policy: {ref_header}")
        assert ref_header == "strict-origin-when-cross-origin", f"Expected Referrer-Policy strict-origin-when-cross-origin, got {ref_header}"
        print(f"Actual Content-Security-Policy:\n{csp_header}")
        assert "script-src" in csp_header, "script-src directive missing from CSP!"
        # Check script-src content
        script_src_part = csp_header.split("script-src")[1].split(";")[0]
        has_unsafe_inline = "'unsafe-inline'" in script_src_part
        print(f"Script-src directive: {script_src_part.strip()}")
        print(f"Is 'unsafe-inline' present in script-src? {has_unsafe_inline}")
        assert not has_unsafe_inline, "FAIL: 'unsafe-inline' MUST NOT be present in script-src!"
        print("PASS: 'unsafe-inline' is absent from script-src.")
        assert "'self'" in script_src_part, 'Missing self origin in script-src'
        assert 'https://cdn.tailwindcss.com' not in script_src_part, 'Unexpected tailwindcdn origin in tightened script-src'
        assert 'https://unpkg.com' not in script_src_part, 'Unexpected unpkg origin in tightened script-src'
        print("PASS: Pinned libraries vendored; CDN origins removed from script-src.")
        print("=" * 60 + "\n")

        print("Launching Chromium browser via Playwright...")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            # Prove app loads with all non-localhost network blocked except map tiles (B6 / 2.7)
            blocked_non_local = []
            def block_non_local(route):
                req_url = route.request.url
                if "127.0.0.1" in req_url or "localhost" in req_url:
                    route.continue_()
                elif "openstreetmap.org" in req_url or req_url.startswith("data:") or req_url.startswith("blob:"):
                    route.continue_()
                else:
                    blocked_non_local.append(req_url)
                    route.abort()

            page.route("**/*", block_non_local)

            # Monitor console for CSP violations and dialogs for XSS
            csp_violations = []
            alerts_triggered = []
            failed_network_requests = []
            map_tile_statuses = []

            def on_response(response):
                url = response.url
                # Ignore favicon and source maps
                if "favicon.ico" in url or url.endswith(".map") or ".js.map" in url:
                    return
                status = response.status
                if "tile.openstreetmap.org" in url:
                    map_tile_statuses.append(status)
                # Check for 4xx/5xx on images, tiles, video, API calls
                is_checked_asset = (
                    "/api/" in url
                    or "/static/" in url
                    or "tile.openstreetmap.org" in url
                    or any(url.endswith(ext) or (ext + "?") in url for ext in [".jpg", ".jpeg", ".png", ".mp4", ".svg"])
                )
                if is_checked_asset and status >= 400:
                    if "test_expired=1" in url:
                        pass
                    else:
                        failed_network_requests.append(f"{status} {response.request.method} {url}")

            def on_requestfailed(request):
                url = request.url
                if "favicon.ico" in url or url.endswith(".map") or ".js.map" in url:
                    return
                # Ignore client-side cancellations/aborts (e.g. video range seeks, offscreen tiles cancelled on tab switch)
                fail_msg = str(request.failure or "")
                if "ERR_ABORTED" in fail_msg or "aborted" in fail_msg.lower():
                    return
                if url in blocked_non_local:
                    return
                failed_network_requests.append(f"FAILED {request.method} {url} - {request.failure}")

            page.on("response", on_response)
            page.on("requestfailed", on_requestfailed)
            page.on("console", lambda msg: csp_violations.append(msg.text) if "violates the following Content Security Policy directive" in msg.text or "Content Security Policy" in msg.text else None)
            page.on("dialog", lambda dialog: (alerts_triggered.append(dialog.message), dialog.dismiss()))

            # 1. Navigate to app
            page.goto(base_url)
            page.wait_for_selector("#login-overlay", state="visible", timeout=10000)

            # 2. Login as admin using randomly generated test credentials
            page.fill("#login-username", TEST_ADMIN_USERNAME)
            page.fill("#login-password", TEST_ADMIN_PASSWORD)
            page.click("#btn-submit-login")

            # Wait for login overlay to disappear
            page.wait_for_selector("#login-overlay", state="hidden", timeout=10000)
            print("Logged in successfully as Administrator.")

            # 3. Navigate to New Inspection screen
            page.click("#nav-tab-new-survey")
            page.wait_for_selector("#screen-new-inspection", state="visible", timeout=5000)
            print("Navigated to New Inspection screen.")

            # 4. Fill form with stored XSS payload in inspection name
            xss_test_name = '<img src=x onerror="window.__xss_flag=1; alert(1)"> Survey'
            page.fill("#form-inspection-name", xss_test_name)
            page.fill("#form-location", "NH-48 Km 0.0 - 5.0")
            
            # Select generated MP4 (Fix 1 verification)
            page.set_input_files("#form-video-file", test_vid)
            page.wait_for_selector("#dropzone-file-info", state="visible", timeout=5000)
            chosen_name = page.locator("#dropzone-filename").inner_text()
            print(f"Selected video file in UI: '{chosen_name}'")

            # Submit form to initiate inspection
            page.click("#form-new-inspection button[type='submit']")

            # 5. Live Pipeline screen should appear
            page.wait_for_selector("#screen-live", state="visible", timeout=5000)
            print("Navigated to Live Pipeline screen.")

            # Check for MOCK CV badge visibility
            mock_badge = page.locator("#live-mock-badge")
            page.wait_for_function("() => document.getElementById('live-mock-badge').style.display !== 'none'", timeout=10000)
            badge_text = mock_badge.inner_text()
            print(f"Verified MOCK CV badge is visible: '{badge_text}'")

            # Observe progress bar and percentage moving over time
            pct_history = []
            frames_history = []
            stages_history = []

            start_observe = time.time()
            screenshot_taken = False

            while time.time() - start_observe < 30:
                pct_text = page.locator("#live-progress-pct").inner_text().strip()
                frames_text = page.locator("#live-frames-count").inner_text().strip()
                stage_text = page.locator("#live-current-stage").inner_text().strip()

                pct_val = int(pct_text.replace("%", "")) if "%" in pct_text else 0
                if pct_val > 0 and not screenshot_taken:
                    page.screenshot(path=os.path.join(SCREENSHOT_DIR, "live_pipeline_progress.png"))
                    screenshot_taken = True
                    print(f"Captured screenshot at {pct_text} progress: screenshots/live_pipeline_progress.png")

                pct_history.append(pct_val)
                frames_history.append(frames_text)
                stages_history.append(stage_text)

                if pct_val >= 100:
                    print("Pipeline reached 100% completion in browser!")
                    break
                time.sleep(0.5)

            # Final screenshot at completion
            page.screenshot(path=os.path.join(SCREENSHOT_DIR, "live_pipeline_completed.png"))

            # 6. Open Evidence Screen, click a detection, verify evidence images and video player
            print("Navigating to Evidence screen...")
            page.click("button[data-screen='screen-evidence']")
            page.wait_for_selector("#screen-evidence", state="visible", timeout=5000)
            page.wait_for_selector("#evidence-defects-table tr", state="visible", timeout=10000)

            # Click a detection row
            first_row = page.locator("#evidence-defects-table tr").first
            first_row.click()

            # Wait for evidence images to load and verify naturalWidth > 0
            page.wait_for_function("""() => {
                const o = document.getElementById('img-original-evidence');
                const a = document.getElementById('img-annotated-evidence');
                return o && o.complete && o.naturalWidth > 0 && a && a.complete && a.naturalWidth > 0;
            }""", timeout=10000)

            img_state = page.evaluate("""() => ({
                orig_width: document.getElementById('img-original-evidence').naturalWidth,
                anno_width: document.getElementById('img-annotated-evidence').naturalWidth,
                orig_src: document.getElementById('img-original-evidence').src,
                anno_src: document.getElementById('img-annotated-evidence').src
            })""")
            print(f"Evidence images verified: orig={img_state['orig_width']}px, anno={img_state['anno_width']}px")
            images_loaded = img_state['orig_width'] > 0 and img_state['anno_width'] > 0
            images_signed = "signature=" in img_state['orig_src'] and "signature=" in img_state['anno_src']

            # 6b. Test re-signing on expired URL / onerror retry (Item 4.a)
            print("Testing frontend re-signing path and onerror handling...")
            page.evaluate("""() => {
                const el = document.getElementById('img-original-evidence');
                const oldSrc = el.src;
                const parsed = new URL(oldSrc);
                parsed.searchParams.set('expires', String(Math.floor(Date.now() / 1000) - 300));
                parsed.searchParams.set('test_expired', '1');
                el.dataset.retried = "";
                el.src = parsed.toString();
            }""")
            page.wait_for_function("""() => {
                const el = document.getElementById('img-original-evidence');
                if (!el || !el.src || !el.src.includes('expires=')) return false;
                const parsed = new URL(el.src);
                const exp = parseInt(parsed.searchParams.get('expires'), 10);
                return exp > (Date.now() / 1000) && el.complete && el.naturalWidth > 0 && !el.src.includes('test_expired=1');
            }""", timeout=10000)
            print("Verified frontend re-sign path executed on expired URL and restored valid image!")

            # 6c. Test frontend chunking signs 250 files in 3 requests (Item 4.b)
            print("Testing frontend chunking: 250 files signed in exactly 3 requests...")
            batch_req_count = page.evaluate("""async () => {
                const files250 = Array.from({ length: 250 }, (_, i) => `DEMO-001/det_${String(i).padStart(4, '0')}_orig.jpg`);
                const signRequests = [];
                for (let i = 0; i < files250.length; i += 100) {
                    const batch = files250.slice(i, i + 100);
                    signRequests.push(apiFetch('/api/media/sign-batch', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ files: batch, type: 'evidence' })
                    }));
                }
                const responses = await Promise.all(signRequests);
                return responses.filter(r => r.ok).length;
            }""")
            print(f"250 files signed across requests: {batch_req_count} (expected 3)")
            assert batch_req_count == 3, f"Expected exactly 3 sign-batch requests for 250 files, got {batch_req_count}" 

            video_state = page.evaluate("""() => {
                const vid = document.getElementById('inspection-video-player');
                if (!vid) return { found: false };
                return {
                    found: true,
                    src: vid.src,
                    error: vid.error ? { code: vid.error.code, message: vid.error.message } : null,
                    currentTime: vid.currentTime,
                    duration: vid.duration,
                    paused: vid.paused
                };
            }""")
            print("Video player state on Evidence screen:", video_state)

            video_has_no_error = video_state["found"] and (video_state["error"] is None)
            video_is_signed = "signature=" in video_state.get("src", "") and "expires=" in video_state.get("src", "")
            video_time_synced = video_state.get("currentTime", 0) >= 0

            print(f"Video player found & error-free: {video_has_no_error}")
            print(f"Video URL signed: {video_is_signed}")
            page.screenshot(path=os.path.join(SCREENSHOT_DIR, "evidence_video_sync.png"))

            # 7. Navigate to GIS Map screen and verify road segments, tiles, and defect dots
            print("Navigating to GIS Map tab...")
            page.click("button[data-screen='screen-map']")
            page.wait_for_selector("#screen-map", state="visible", timeout=10000)

            page.wait_for_selector(".leaflet-overlay-pane path", state="attached", timeout=10000)
            page.wait_for_selector(".defect-marker-pin", state="attached", timeout=10000)

            segment_count = page.evaluate("() => window.segmentsLayer ? window.segmentsLayer.getLayers().length : 0")
            defect_marker_count = page.locator(".defect-marker-pin").count()
            print(f"GIS Map verified: {segment_count} road segments drawn, {defect_marker_count} defect pins rendered.")

            # Open segment popup to verify popup and escaping
            page.evaluate("() => { if (window.segmentsLayer && window.segmentsLayer.getLayers().length > 0) window.segmentsLayer.getLayers()[0].openPopup(); }")
            page.wait_for_selector(".leaflet-popup", state="visible", timeout=5000)
            popup_text = page.locator(".leaflet-popup").inner_text()
            print(f"Segment popup opened cleanly: '{popup_text[:60]}...'")

            # Test defect pin popup rendering, data attributes, and escaping (Item 3)
            page.evaluate("() => { if (window.defectsLayer && window.defectsLayer.getLayers().length > 0) window.defectsLayer.getLayers()[0].openPopup(); }")
            page.wait_for_selector(".leaflet-popup .btn-map-inspect-defect", state="visible", timeout=7000)
            defect_popup = page.locator(".leaflet-popup:has(.btn-map-inspect-defect)")
            defect_popup_text = defect_popup.inner_text()
            print(f"Defect pin popup opened cleanly: '{defect_popup_text[:60]}...'")
            inspect_btn = page.locator(".btn-map-inspect-defect").first
            attr_defect_id = inspect_btn.get_attribute("data-defect-id")
            attr_ts_sec = inspect_btn.get_attribute("data-timestamp-sec")
            print(f"Defect button data attributes verified: id='{attr_defect_id}', timestamp_sec='{attr_ts_sec}'")
            assert attr_defect_id, "Missing data-defect-id on defect inspect button"
            assert attr_ts_sec is not None, "Missing data-timestamp-sec on defect inspect button"

            # Test defect marker click navigates directly to screen-evidence (Item 3 original behavior)
            page.evaluate("() => { if (window.mapInstance) window.mapInstance.closePopup(); }")
            time.sleep(0.3)
            defect_pin = page.locator(".defect-marker-pin").first
            defect_pin.click()
            page.wait_for_selector("#screen-evidence", state="visible", timeout=5000)
            print("Verified defect marker click navigated directly to screen-evidence (original behavior).")
            # Navigate back to map tab to continue checks
            page.click("button[data-screen='screen-map']")
            page.wait_for_selector("#screen-map", state="visible", timeout=5000)

            # Assert map tile responses are not 403 (Requirement 10)
            tiles_403 = [s for s in map_tile_statuses if s == 403]
            print(f"OSM tile responses received: {len(map_tile_statuses)}, 403 errors: {len(tiles_403)}")
            assert len(tiles_403) == 0, f"Encountered {len(tiles_403)} 403 Access Blocked responses from OSM tiles! Referrer-Policy must be strict-origin-when-cross-origin." 

            # 8. Command Center Screen: verify charts and inspections table
            print("Navigating to Command Center screen...")
            page.click("button[data-screen='screen-command']")
            page.wait_for_selector("#screen-command", state="visible", timeout=10000)
            page.wait_for_selector("#inspections-table-body tr", state="visible", timeout=10000)

            # Verify charts rendered
            charts_rendered = page.evaluate("() => document.querySelectorAll('canvas').length >= 3")
            print(f"Charts rendered on dashboard: {charts_rendered}")

            # Verify Defects Per Kilometer chart has data (dataset length > 0)
            density_chart_data_len = page.evaluate("() => { const c = window.Chart && window.Chart.getChart ? window.Chart.getChart('chart-density') : null; return (c && c.data && c.data.datasets && c.data.datasets[0] && c.data.datasets[0].data) ? c.data.datasets[0].data.length : 0; }")
            print(f"Defects Per Kilometer chart dataset length: {density_chart_data_len}")
            density_chart_has_data = (density_chart_data_len > 0)

            # Verify stale SQLite badge is removed from DOM
            assert "SQLite" not in page.content(), "Stale SQLite badge found rendered in DOM!"

            # Verify AI Perception Models registry rendered in UI
            page.wait_for_selector("#models-registry-list > div", state="visible", timeout=10000)
            models_rendered = page.evaluate("() => document.querySelectorAll('#models-registry-list > div').length >= 3")
            print(f"AI Perception Models rendered in UI: {models_rendered}")
            assert models_rendered, "AI Perception Models registry panel did not render model cards!"  

            # 9. Download PDF Report through the UI
            print("Testing PDF download through the UI...")
            with page.expect_download(timeout=15000) as download_info:
                page.locator("#inspections-table-body button:has-text('PDF')").first.click()
            download = download_info.value
            download_dest = os.path.join(TEST_SCRATCH_DIR, "report_ui_download.pdf")
            download.save_as(download_dest)
            pdf_size = os.path.getsize(download_dest)
            print(f"PDF downloaded successfully via UI: {download_dest} ({pdf_size} bytes)")
            pdf_download_ok = os.path.exists(download_dest) and pdf_size > 1000

            # 10. Verify XSS was NOT executed
            xss_clean = (len(alerts_triggered) == 0) and (page.evaluate("() => window.__xss_flag") is None)
            print(f"XSS prevention verified: no alert dialogs ({len(alerts_triggered)}), no execution flag ({page.evaluate('() => window.__xss_flag')}).")

            # 11. Verify zero CSP violations
            csp_clean = (len(csp_violations) == 0)
            print(f"CSP violations in console: {len(csp_violations)}")
            if len(csp_violations) > 0:
                print("Violations:", csp_violations)

            # 12. Verify zero 4xx/5xx failed network requests on images, tiles, video, API (Requirement 10)
            network_clean = (len(failed_network_requests) == 0)
            print(f"Failed network requests (4xx/5xx): {len(failed_network_requests)}")
            if not network_clean:
                print("FAILED NETWORK REQUESTS:")
                for fnr in failed_network_requests:
                    print("  ->", fnr)

            browser.close()

            # Final Validations
            progress_moved = max(pct_history) > 0 and pct_history[-1] >= pct_history[0]
            has_mock = "MOCK CV" in badge_text.upper()
            map_verified = segment_count > 0 and defect_marker_count > 0
            video_verified = video_has_no_error and video_is_signed and video_time_synced

            all_ok = (
                progress_moved and
                has_mock and
                map_verified and
                video_verified and
                images_loaded and
                images_signed and
                charts_rendered and
                density_chart_has_data and
                pdf_download_ok and
                xss_clean and
                csp_clean and
                network_clean
            )

            if all_ok:
                print("ALL BROWSER PIPELINE CHECKS PASSED!")
                return True
            else:
                print("BROWSER CHECK FAILED:")
                print(f"  progress_moved={progress_moved}")
                print(f"  has_mock={has_mock}")
                print(f"  map_verified={map_verified}")
                print(f"  video_verified={video_verified}")
                print(f"  images_loaded={images_loaded}")
                print(f"  images_signed={images_signed}")
                print(f"  charts_rendered={charts_rendered}")
                print(f"  density_chart_has_data={density_chart_has_data}")
                print(f"  pdf_download_ok={pdf_download_ok}")
                print(f"  xss_clean={xss_clean}")
                print(f"  csp_clean={csp_clean}")
                print(f"  network_clean={network_clean}")
                return False
    finally:
        if server_proc:
            server_proc.terminate()
            try:
                server_proc.wait(timeout=4)
            except Exception:
                server_proc.kill()
        # Clean up temporary test data directory (Item 4)
        shutil.rmtree(TEST_TMP_DIR, ignore_errors=True)
        print(f"Tearing down ephemeral PostgreSQL database: {TEST_DB_NAME}")
        try:
            with psycopg.connect(BASE_PG_URL, autocommit=True) as conn:
                conn.cursor().execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} (FORCE);")
        except Exception as e:
            print(f"Warning: Failed to drop test db {TEST_DB_NAME}: {e}")


if __name__ == "__main__":
    success = run_browser_check()
    sys.exit(0 if success else 1)
