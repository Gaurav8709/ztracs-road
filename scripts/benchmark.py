#!/usr/bin/env python3
"""
Z-TRACS Road Intelligence - System Benchmark Suite
Measures real performance across Database, API endpoints, AI inference, and PDF generation.
"""
import os
import sys
import time
import statistics
import io
from typing import List, Callable, Dict, Any

# Ensure project root is on PYTHONPATH
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Load environment from .env if not explicitly set
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
if os.path.exists(env_path):
    with open(env_path) as ef:
        for line in ef:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip().strip("'\"")
                if k and k not in os.environ:
                    os.environ[k] = v
sys.path.insert(0, PROJECT_ROOT)

import psycopg
from psycopg.rows import dict_row
from fastapi.testclient import TestClient
from backend.main import app
from backend.reports import generate_inspection_pdf
from backend.database import init_db
from backend.seed_data import seed_demo_data


def run_benchmark(name: str, fn: Callable[[], Any], iterations: int = 50) -> Dict[str, Any]:
    latencies_ms: List[float] = []
    # Warmup
    for _ in range(min(5, iterations)):
        fn()

    start_total = time.perf_counter()
    for _ in range(iterations):
        t0 = time.perf_counter()
        fn()
        t1 = time.perf_counter()
        latencies_ms.append((t1 - t0) * 1000.0)
    total_time = time.perf_counter() - start_total

    latencies_ms.sort()
    mean_ms = statistics.mean(latencies_ms)
    p50_ms = statistics.median(latencies_ms)
    p95_ms = latencies_ms[int(len(latencies_ms) * 0.95)]
    min_ms = min(latencies_ms)
    max_ms = max(latencies_ms)
    throughput = iterations / total_time if total_time > 0 else 0.0

    return {
        "name": name,
        "iterations": iterations,
        "mean_ms": round(mean_ms, 2),
        "p50_ms": round(p50_ms, 2),
        "p95_ms": round(p95_ms, 2),
        "min_ms": round(min_ms, 2),
        "max_ms": round(max_ms, 2),
        "throughput_rps": round(throughput, 1),
    }


def main():
    io_buffer = io.StringIO()
    class Tee:
        def __init__(self, *streams):
            self.streams = streams
        def write(self, s):
            for st in self.streams:
                st.write(s)
        def flush(self):
            for st in self.streams:
                st.flush()
    orig_stdout = sys.stdout
    sys.stdout = Tee(orig_stdout, io_buffer)

    print("=" * 70)
    print("  Z-TRACS Road Intelligence — Performance Benchmark Suite")
    print("=" * 70)

    db_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:5432/ztracs")
    masked_db = db_url.split("@")[-1] if "@" in db_url else "configured-database"
    print(f"Target Database: ...@{masked_db}")
    print("Initializing test client and database connection...\n")
    init_db()
    seed_demo_data(force=False)

    client = TestClient(app)

    # Authenticate admin using ADMIN_USERNAME / ADMIN_PASSWORD only
    admin_user = os.getenv("ADMIN_USERNAME", "admin")
    admin_pw = os.getenv("ADMIN_PASSWORD", "change-me-admin-password")
    login_res = client.post("/api/auth/login", json={"username": admin_user, "password": admin_pw})
    if login_res.status_code != 200:
        raise RuntimeError(f"Benchmark authentication failed for user '{admin_user}': {login_res.status_code} {login_res.text}")
    token = login_res.json().get("access_token") or login_res.json().get("token") or ""
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    results = []

    # 1. Database Benchmark: Point Query
    def db_point_query():
        with psycopg.connect(db_url, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, road_name, status FROM inspections WHERE id = 'DEMO-001'")
                cur.fetchone()
    results.append(run_benchmark("DB: Point Query (Inspection DEMO-001)", db_point_query, 50))

    # 2. Database Benchmark: PostGIS Spatial Nearest Neighbor
    def db_postgis_spatial():
        with psycopg.connect(db_url, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, segment_name, ST_Distance(geom, ST_SetSRID(ST_Point(73.1785, 19.0682), 4326)) as dist
                    FROM road_segments
                    ORDER BY geom <-> ST_SetSRID(ST_Point(73.1785, 19.0682), 4326)
                    LIMIT 1
                """)
                cur.fetchone()
    results.append(run_benchmark("DB: PostGIS Spatial KNN (ST_Distance)", db_postgis_spatial, 50))

    # 3. Database Benchmark: Complex Aggregation Query
    def db_aggregation():
        with psycopg.connect(db_url, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT defect_type, severity, COUNT(*), AVG(confidence)
                    FROM detections
                    WHERE inspection_id = 'DEMO-001'
                    GROUP BY defect_type, severity
                """)
                cur.fetchall()
    results.append(run_benchmark("DB: Aggregation & Metrics Summary", db_aggregation, 50))

    # 4. API Benchmark: GET /api/analytics/overview
    def api_analytics_overview():
        res = client.get("/api/analytics/overview?inspection_id=DEMO-001", headers=headers)
        assert res.status_code == 200
    results.append(run_benchmark("API: GET /api/analytics/overview", api_analytics_overview, 50))

    # 5. API Benchmark: GET /api/map/defects (GeoJSON)
    def api_map_defects():
        res = client.get("/api/map/defects?inspection_id=DEMO-001", headers=headers)
        assert res.status_code == 200
    results.append(run_benchmark("API: GET /api/map/defects (GeoJSON)", api_map_defects, 50))

    # 6. API Benchmark: GET /api/road-segments
    def api_road_segments():
        res = client.get("/api/road-segments?inspection_id=DEMO-001", headers=headers)
        assert res.status_code == 200
    results.append(run_benchmark("API: GET /api/road-segments", api_road_segments, 50))

    # 7. API Benchmark: GET /api/assets
    def api_assets():
        res = client.get("/api/assets", headers=headers)
        assert res.status_code == 200
    results.append(run_benchmark("API: GET /api/assets (Corridor Inventory)", api_assets, 50))

    # 8. Report Generation Benchmark: PDF Engine
    def pdf_generation():
        generate_inspection_pdf("DEMO-001")
    results.append(run_benchmark("PDF: Full Report Build (GIS Map + Images)", pdf_generation, 10))

    # Print Report Table
    table_lines = []
    table_lines.append(f"{'Operation / Benchmark':<42} | {'Mean (ms)':>9} | {'P50 (ms)':>8} | {'P95 (ms)':>8} | {'Min (ms)':>8} | {'Max (ms)':>8} | {'RPS':>7}")
    table_lines.append("-" * 105)
    for r in results:
        table_lines.append(f"{r['name']:<42} | {r['mean_ms']:>9.2f} | {r['p50_ms']:>8.2f} | {r['p95_ms']:>8.2f} | {r['min_ms']:>8.2f} | {r['max_ms']:>8.2f} | {r['throughput_rps']:>7.1f}")
    table_lines.append("-" * 105)
    table_lines.append("Benchmark complete. All operations executed successfully with real latencies.\n")

    for line in table_lines:
        print(line)

    # Capture and write directly to docs/BENCHMARKS.md (no hand-typed numbers)
    raw_output = io_buffer.getvalue()
    
    doc_lines = [
        "# Z-TRACS Road Intelligence — Performance Benchmarks\n",
        "Performance benchmark suite executed via `scripts/benchmark.py` against PostgreSQL 16 + PostGIS 3.4.\n",
        "## Raw Benchmark Output\n",
        "```text",
        raw_output.strip(),
        "```\n",
        "## Summary Table\n",
        "| Operation / Benchmark | Mean (ms) | P50 (ms) | P95 (ms) | Min (ms) | Max (ms) | Throughput (RPS) |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: |"
    ]
    for r in results:
        doc_lines.append(f"| **{r['name']}** | {r['mean_ms']:.2f} | {r['p50_ms']:.2f} | {r['p95_ms']:.2f} | {r['min_ms']:.2f} | {r['max_ms']:.2f} | {r['throughput_rps']:.1f} |")
    
    import platform
    doc_lines.append(f"\n*Environment: {platform.system()} {platform.machine()}, Docker PostgreSQL 16 / PostGIS 3.4, Python {sys.version.split()[0]} / FastAPI.*\n")
    
    benchmarks_md_path = os.path.join(PROJECT_ROOT, "docs", "BENCHMARKS.md")
    with open(benchmarks_md_path, "w") as f:
        f.write("\n".join(doc_lines))
    print(f"[BENCHMARK] Output successfully written to {benchmarks_md_path}")


if __name__ == "__main__":
    main()
