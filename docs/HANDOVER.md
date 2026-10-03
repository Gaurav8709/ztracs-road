# Z-TRACS Road Intelligence Platform — Technical Handover & Developer Onboarding Guide

**Author**: Z-TRACS Engineering Team  
**Scope**: Full-Stack Backend, Frontend, PostgreSQL/PostGIS (Local Docker / Cloud AWS RDS), Security Hardening, and Unified/Split Serving

---

## 1. Executive Summary & What Was Done

Z-TRACS Road Intelligence is an enterprise AI & geospatial platform that ingests road survey imagery and videos, runs Computer Vision (CV) pavement defect detection, anchors defects geospatially to road segments using PostGIS, calculates condition ($0–100$) and risk scores ($0–100$), and provides interactive GIS visualization, video seeking, and automated PDF engineering reports.

### Summary of What Was Implemented & Configured
1. **Local & Cloud PostgreSQL + PostGIS Database**:
   - Default local database is containerized via Docker Compose ([`docker-compose.yml`](file:///Users/ananya/Documents/ztracs-road-intelligence/docker-compose.yml)) running `postgis/postgis:16-3.4` bound strictly to loopback `127.0.0.1:5432`.
   - Spatial schema with native geometry columns (`LineString` for road segments, `Point` for defects) and GIST spatial indexes.
   - PostGIS KNN spatial operator (`<->`) for high-speed spatial nearest-segment assignment.
   - AWS RDS PostgreSQL with PostGIS remains an optional cloud target configured via `DATABASE_URL`.
2. **AWS S3 Cloud Storage Integration (Optional)**:
   - S3 client module in [`backend/s3_client.py`](file:///Users/ananya/Documents/ztracs-road-intelligence/backend/s3_client.py).
   - Set `USE_S3_STORAGE=false` for 100% offline local development (uses local disk and cryptographic HMAC-SHA256 URL signing).
   - Set `USE_S3_STORAGE=true` with valid AWS IAM credentials to stream dashcam videos via HTTP Range requests (`206 Partial Content`) and retrieve evidence directly from AWS S3.
3. **Enterprise Security Hardening**:
   - Strict Content Security Policy (CSP) with `script-src` completely free of `'unsafe-inline'`. Pinned libraries (Tailwind, Leaflet, Chart.js) are vendored locally in `frontend/vendor/`.
   - All media and report routes protected behind time-limited HMAC-SHA256 signatures or Bearer token authentication.
   - Role-Based Access Control (RBAC) with 3 tiers: `admin`, `inspector`, `viewer`, verified dynamically against the database on every request.
   - Ingest input validation, anti-path-traversal protection, rate limiting on login, and parameterized SQL queries.
4. **Flexible Running Modes (Unified vs. Split)**:
   - **Unified Mode** (Single Origin): `./run.sh` runs the FastAPI backend and static frontend from a single server on port `8000`.
   - **Split Mode** (Separate Origins): `./run.sh` runs the API on port `8000`, and `./run-frontend.sh` serves the frontend on port `3000` with dynamic `window.API_BASE` injection and CORS support.
5. **100% Passing Automated Test Verification**:
   - `tests/test_security.py`: 29/29 checks passing.
   - `tests/test_pipeline.py`: 24/24 checks passing.
   - `tests/test_browser_pipeline.py`: Full Playwright browser E2E test passing.
   - `tests/test_split_mode.py`: Full Playwright cross-origin split mode test passing.

---

## 2. Codebase Architecture: "What is What"

```
ztracs-road-intelligence/
├── docker-compose.yml            # Docker container definition for PostGIS 16-3.4 (127.0.0.1:5432)
├── run.sh                        # Unified launcher with pre-flight checks, DB init & demo seed (port 8000)
├── run-frontend.sh               # Dedicated frontend server with dynamic API_BASE injection (port 3000)
├── backend/
│   ├── main.py                   # FastAPI app, REST routing, CORS, security middleware & media streaming
│   ├── database.py               # PostgreSQL/PostGIS connection pooling, schema init & KNN queries
│   ├── auth.py                   # JWT auth, bcrypt password hashing, RBAC enforcement & rate limiting
│   ├── models.py                 # Pydantic validation schemas, defect models & status enums
│   ├── scoring_engine.py         # Road condition (0-100), risk score (0-100) & P1-P4 priority engine (PoC weights, calibrated so the demo segment matches the spec example, not an engineering standard.)
│   ├── ai_pipeline.py            # Asynchronous background video processing worker (OpenCV + CV Client)
│   ├── cv_client.py              # Computer Vision inference client (Mock CV + HTTP mode), frame annotator
│   ├── reports.py                # ReportLab PDF report generator with dynamic defect tables & evidence
│   ├── seed_data.py              # Golden Demo DEMO-001 dataset seed generator
│   ├── s3_client.py              # AWS S3 client: byte-range streaming, presigned URLs, fallback logic
│   └── migrate_sqlite_to_postgres.py # Historical migration utility from legacy SQLite to PostgreSQL
├── frontend/
│   ├── index.html                # Single Page Application HTML (CSP-compliant, external event handlers)
│   ├── css/style.css             # Glassmorphism dark-mode theme, Leaflet styling & layout
│   ├── vendor/                   # Vendored client libraries (Tailwind, Leaflet 1.9.4, Chart.js 4.4.1)
│   └── js/
│       ├── config.js             # API_BASE resolution helper
│       ├── app.js                # State management, API client, authentication, routing
│       ├── map.js                # Leaflet GIS engine, road segments, color-coded status, defect pins
│       ├── video.js              # Video player controller, time-synced defect jumping, signed URLs
│       ├── charts.js             # Chart.js analytics telemetry (severity doughnut, density bars)
│       └── events.js             # External event delegation & event listener bindings (no inline JS)
├── tests/
│   ├── test_security.py          # 29-point automated security audit & regression test suite
│   ├── test_pipeline.py          # 24-point PostGIS spatial pipeline & idempotency test suite
│   ├── test_browser_pipeline.py  # Playwright headless Chromium real-browser E2E test suite
│   └── test_split_mode.py        # Playwright cross-origin split mode (ports 8000 & 3000) test suite
├── demo_assets/                  # Sample survey videos, defect detections JSON, and fixture evidence
├── static/
│   └── media/                    # Local copy of evidence frames, video files, and PDF reports
├── docs/
│   ├── HANDOVER.md               # This technical handover documentation
│   └── PROJECT_REPORT.md         # Comprehensive project audit and engineering report
├── requirements.txt              # Production Python package requirements
├── requirements-dev.txt          # Development, testing, and linting requirements
├── .env.example                  # Environment configuration template
└── README.md                     # Project overview, setup, running modes, and quickstart guide
```

### Key Data Flow
```
1. Video Upload
   Client Browser  ──▶  POST /api/inspections/upload  ──▶  Local disk / S3

2. Processing Pipeline (backend/ai_pipeline.py)
   OpenCV Video Decode  ──▶  Sample Frames (1 fps)  ──▶  cv_client.py (Defect Bounding Boxes)
                                                                 │
                                                                 ▼
   Evidence Storage     ◀── Annotate Crops (orig + anno) ◀───────┘
                                   │
                                   ▼
   PostGIS Nearest Segment  ──▶  KNN (<->) road_segments geom  ──▶  Assign Segment ID
                                   │
                                   ▼
   scoring_engine.py        ──▶  Deductions, Condition Score (0-100), Risk Score (0-100)
                                   │
                                   ▼
   PostgreSQL DB Commit     ──▶  Status -> COMPLETED, Segment Metrics & Alerts Updated

3. Visualization & Reporting
   GIS Map (Leaflet)        ◀──  GET /api/map/defects & /api/map/segments (GeoJSON)
   Video Player             ◀──  GET /api/media/video/{filename}?expires=...&signature=... (Range 206)
   PDF Generator            ◀──  GET /api/reports/{id}/pdf (Dynamic ReportLab PDF)
```

---

## 2.1 Asynchronous Pipeline Architecture: In-Process vs Enterprise AWS SQS

### Current PoC Implementation: In-Process BackgroundTasks
- **Mechanism**: The video processing pipeline is invoked via FastAPI's `BackgroundTasks` (`asyncio` execution loop within the uvicorn worker process).
- **Execution Flow**: When an operator triggers `POST /api/inspections/{id}/start`, the HTTP request returns an immediate 200/202 status, while `process_video_pipeline(inspection_id)` runs in the background.
- **Why This Architecture for PoC & Hackathon**:
  - **Zero External Dependencies**: Does not require Redis, RabbitMQ, Celery workers, or daemon services. A reviewer or evaluator can clone the repo and launch the entire stack with a single command (`./run.sh`).
  - **Deterministic State & Crash Recovery**: If a server process is interrupted, the startup recovery hook queries the DB and marks any orphaned `PROCESSING` / `QUEUED` jobs as `FAILED` with a descriptive error message (`Processing was interrupted by a server restart.`), preventing stale zombie jobs.
  - **Fast In-Memory Pipeline Hand-off**: OpenCV frame extraction and CV bounding box annotations write directly to the local filesystem or S3 without serialization bottlenecks.

### Enterprise Production Architecture: AWS SQS + Distributed GPU Workers
For full-scale national highway deployments with concurrent survey fleets:

```
[Survey Fleet Vehicle / Client]
             │
             ▼ (Presigned S3 PUT)
     [AWS S3 Bucket]
             │ (Upload Notification / API Trigger)
             ▼
[FastAPI Ingestion Gateway]  ──▶  [Amazon SQS FIFO Queue]  ──▶  [Dead-Letter Queue]
                                             │
                       ┌─────────────────────┴─────────────────────┐
                       ▼                                           ▼
          [GPU Worker Node 1 (ECS)]                   [GPU Worker Node 2 (ECS)]
          - TensorRT / ONNX Runtime                   - TensorRT / ONNX Runtime
          - PostGIS Spatial Aggregation               - PostGIS Spatial Aggregation
                       │                                           │
                       └─────────────────────┬─────────────────────┘
                                             ▼
                                  [AWS RDS PostgreSQL + PostGIS]
```

- **Amazon SQS Queue**: Buffers ingestion jobs across regional fleet uploads, decoupling HTTP API availability from heavy GPU processing.
- **Auto-Scaling GPU Worker Pool**: AWS ECS Fargate or EC2 Spot GPU instances scale automatically with queue depth (CloudWatch metric `ApproximateNumberOfMessagesVisible`).
- **Dead-Letter Queue (DLQ)**: Isolates corrupted or unreadable video streams without stalling subsequent jobs.
- **Zero-Code Architectural Parity**: Because `backend/ai_pipeline.py` is cleanly separated into modular functions (`process_video_pipeline`, `run_detection_pass`, `assign_spatial_segments`, `aggregate_inspection_metrics`), converting from FastAPI `BackgroundTasks` to an SQS consumer worker requires only wrapping `process_video_pipeline` in an SQS message polling loop; all database, storage, scoring, and GIS logic remains identical.

---

## 3. How to Set Up & Run on Someone Else's Laptop

Follow these exact steps when cloning this repository onto any new machine (macOS or Linux):

### Prerequisites
- **Python**: Verified support on **Python 3.9.6**. (Python 3.10–3.13 are compatible by specification but marked NOT VERIFIED on host; Python >= 3.14 is unsupported).
- **Docker & Docker Compose**: Required for local PostGIS container (`docker compose up -d`).
- **Git**

---

### Step 1: Clone the Repository
```bash
git clone <repository-url> ztracs-road-intelligence
cd ztracs-road-intelligence
```

---

### Step 2: Set Up Python Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate
```

---

### Step 3: Install Required Dependencies
```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
```

---

### Step 4: Start the Local PostGIS Database
Start the PostgreSQL + PostGIS Docker container:
```bash
docker compose up -d
```
Verify the container is healthy and bound to loopback:
```bash
docker compose ps
# Expected: ztracs-postgis ... Up (healthy) 127.0.0.1:5432->5432/tcp
```

---

### Step 5: Configure Environment Variables (`.env`)
Copy `.env.example` to create your local `.env`:
```bash
cp .env.example .env
```

The default values in `.env.example` connect directly to the local Docker PostGIS database:
```ini
# ==============================================================================
# Z-TRACS Road Intelligence Platform - Environment Configuration Template
# Copy this file to .env before starting the application:
#   cp .env.example .env
# ==============================================================================

# Secret key used to sign JWT access tokens (minimum 32 characters)
JWT_SECRET=change-me-to-a-secure-random-secret-key-at-least-32-chars

# Default administrator username created on first launch
ADMIN_USERNAME=admin

# Default administrator password (minimum 8 characters)
ADMIN_PASSWORD=change-me-admin-password

# Secret key for signing temporary media URLs (defaults to JWT_SECRET if unset)
MEDIA_SIGNING_SECRET=optional-media-signing-secret-key

# PostgreSQL connection string with PostGIS (matches docker-compose.yml)
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ztracs

# Backend HTTP server listening host
HOST=127.0.0.1

# Backend HTTP server listening port
PORT=8000

# Allowed CORS origins (includes backend port 8000 and frontend port 3000)
ALLOWED_ORIGINS=http://127.0.0.1:8000,http://localhost:8000,http://127.0.0.1:3000,http://localhost:3000

# Enable interactive API documentation at /docs and /redoc (1=enabled, 0=disabled)
ENABLE_DOCS=0

# Development mode with automatic code reloading (1=enabled, 0=disabled)
DEV=0

# Computer vision analysis engine mode ('mock' for PoC pipeline, 'onnx' for model)
CV_MODE=mock

# Storage backend flag: false for local disk storage, true for AWS S3
USE_S3_STORAGE=false

# AWS Access Key ID (only used when USE_S3_STORAGE=true)
AWS_ACCESS_KEY_ID=your-aws-access-key-id

# AWS Secret Access Key (only used when USE_S3_STORAGE=true)
AWS_SECRET_ACCESS_KEY=your-aws-secret-access-key

# AWS S3 Region
AWS_REGION=us-east-1

# AWS S3 Bucket Name
S3_BUCKET_NAME=your-s3-bucket-name
```

---

### Step 6: Start the Application

You can run the application in either **Unified Mode** or **Split Mode**:

#### Option A: Unified Mode (Recommended)
Runs both the FastAPI backend and static frontend from port 8000:
```bash
./run.sh
```
`./run.sh` automatically performs pre-flight environment checks, initializes the PostGIS schema, seeds the Golden Demo inspection (`DEMO-001`), and starts the server at `http://127.0.0.1:8000/`.

#### Option B: Split Mode (Frontend & Backend Separately)
Run backend and frontend on separate ports:
1. **Terminal 1 (Backend - Port 8000)**:
   ```bash
   ./run.sh
   ```
2. **Terminal 2 (Frontend - Port 3000)**:
   ```bash
   API_BASE=http://127.0.0.1:8000 ./run-frontend.sh
   ```
Open `http://127.0.0.1:3000/` in your browser. The frontend communicates with the backend on port 8000 via CORS.

---

### Step 7: Log In to the Platform
Open `http://127.0.0.1:8000/` (or `http://127.0.0.1:3000/` in split mode) and log in with your credentials from `.env`:
- **Username**: `admin`
- **Password**: `<ADMIN_PASSWORD from your .env>`

---

### Step 8: Run the Automated Test Suites
All test suites run in isolated ephemeral test databases and clean up automatically:

```bash
# 1. Security & RBAC Audit Suite (29 checks)
./venv/bin/python3 tests/test_security.py

# 2. Pipeline & PostGIS Spatial Integration Suite (24 checks)
./venv/bin/python3 tests/test_pipeline.py

# 3. Real Browser E2E Test Suite (Playwright Chromium)
./venv/bin/python3 tests/test_browser_pipeline.py

# 4. Split Mode Cross-Origin E2E Test Suite (Ports 8000 & 3000)
./venv/bin/python3 tests/test_split_mode.py
```

---

## 4. How AWS S3 Storage Operates (When Enabled)

When `USE_S3_STORAGE=true` is set and valid AWS IAM credentials are provided:
- Videos, evidence frames, and reports are synced to the configured S3 bucket.
- Video streaming uses HTTP Range requests (`206 Partial Content`) proxied through `/api/media/video/*`.
- For local development and demonstration, keep `USE_S3_STORAGE=false` to use local storage and HMAC-SHA256 signature verification without external cloud dependencies.

---

## 5. Common Troubleshooting & FAQs

- **Q: Port 5432 is already in use by a local PostgreSQL service?**  
  *Fix*: Stop the local service (e.g. `brew services stop postgresql@18` or `sudo systemctl stop postgresql`), then run `docker compose up -d`.

- **Q: "PostGIS extension not found" error during DB initialization?**  
  *Fix*: Ensure you are using the official PostGIS Docker image (`postgis/postgis:16-3.4`) defined in `docker-compose.yml`.

- **Q: Running tests in a development environment?**  
  *Fix*: The test files dynamically create ephemeral, isolated databases (`ztracs_test_...`) on `127.0.0.1:5432` and drop them upon completion. They never modify the main `ztracs` database.
