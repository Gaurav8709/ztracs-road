# Z-TRACS Road Intelligence — Performance Benchmarks

Performance benchmark suite executed via `scripts/benchmark.py` against PostgreSQL 16 + PostGIS 3.4.

## Raw Benchmark Output

```text
======================================================================
  Z-TRACS Road Intelligence — Performance Benchmark Suite
======================================================================
Target Database: ...@127.0.0.1:5432/ztracs
Initializing test client and database connection...

Operation / Benchmark                      | Mean (ms) | P50 (ms) | P95 (ms) | Min (ms) | Max (ms) |     RPS
---------------------------------------------------------------------------------------------------------
DB: Point Query (Inspection DEMO-001)      |     33.50 |    33.16 |    36.59 |    30.86 |    40.49 |    29.8
DB: PostGIS Spatial KNN (ST_Distance)      |     46.46 |    46.26 |    48.11 |    44.41 |    54.55 |    21.5
DB: Aggregation & Metrics Summary          |     38.88 |    38.81 |    40.93 |    36.86 |    41.43 |    25.7
API: GET /api/analytics/overview           |     96.38 |    96.61 |   100.06 |    88.35 |   114.08 |    10.4
API: GET /api/map/defects (GeoJSON)        |     72.36 |    71.88 |    77.19 |    62.44 |   121.57 |    13.8
API: GET /api/road-segments                |     89.57 |    89.45 |    93.09 |    86.44 |    95.42 |    11.2
API: GET /api/assets (Corridor Inventory)  |     72.12 |    71.55 |    75.11 |    69.32 |    78.07 |    13.9
PDF: Full Report Build (GIS Map + Images)  |    698.24 |   703.54 |   736.88 |   657.96 |   736.88 |     1.4
---------------------------------------------------------------------------------------------------------
Benchmark complete. All operations executed successfully with real latencies.
```

## Summary Table

| Operation / Benchmark | Mean (ms) | P50 (ms) | P95 (ms) | Min (ms) | Max (ms) | Throughput (RPS) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **DB: Point Query (Inspection DEMO-001)** | 33.50 | 33.16 | 36.59 | 30.86 | 40.49 | 29.8 |
| **DB: PostGIS Spatial KNN (ST_Distance)** | 46.46 | 46.26 | 48.11 | 44.41 | 54.55 | 21.5 |
| **DB: Aggregation & Metrics Summary** | 38.88 | 38.81 | 40.93 | 36.86 | 41.43 | 25.7 |
| **API: GET /api/analytics/overview** | 96.38 | 96.61 | 100.06 | 88.35 | 114.08 | 10.4 |
| **API: GET /api/map/defects (GeoJSON)** | 72.36 | 71.88 | 77.19 | 62.44 | 121.57 | 13.8 |
| **API: GET /api/road-segments** | 89.57 | 89.45 | 93.09 | 86.44 | 95.42 | 11.2 |
| **API: GET /api/assets (Corridor Inventory)** | 72.12 | 71.55 | 75.11 | 69.32 | 78.07 | 13.9 |
| **PDF: Full Report Build (GIS Map + Images)** | 698.24 | 703.54 | 736.88 | 657.96 | 736.88 | 1.4 |

*Environment: Darwin arm64, Docker PostgreSQL 16 / PostGIS 3.4, Python 3.9.6 / FastAPI.*
