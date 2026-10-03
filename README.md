# Z-TRACS Road Intelligence Platform

**Rodic InfraAI Innovation Challenge 2026**  
**Theme 02 — AI for Roads, Bridges & Tunnels**  
*Full-Stack, Cloud & Geospatial Engineering Deliverable*

> 📘 **Developer Handover Guide**: For complete onboarding, architecture walkthrough, AWS S3 / RDS configuration, and running on a new laptop, see **[HANDOVER.md](docs/HANDOVER.md)**.

---

## Prerequisites
- macOS or Linux. Windows via WSL2 or Git Bash (untested).
- Docker Desktop installed and running (provides the PostGIS database).
- Python 3.9 to 3.13 (only 3.9 has been tested).
- Free ports: 5432, 8000, and 3000 (split mode).
- Internet on first run (packages install; map tiles from OpenStreetMap).
- Use the local defaults from .env.example. AWS settings need your own credentials.

---

## 1. System Overview

Z-TRACS Road Intelligence is an enterprise AI & geospatial platform that converts road imagery (dashcam video, UAV drone footage, and corridor survey cameras) into geospatially anchored pavement condition intelligence, defect risk scoring, and actionable maintenance priorities.

```
Road / Fleet Camera  ──▶  Video Ingestion  ──▶  Frame Extraction  ──▶  AI Inference (CV Model)
                                                                               │
                                                                               ▼
PDF Reports & Alerts  ◀──  Z-TRACS Dashboard  ◀──  Scoring Engine  ◀──  PostGIS Road Segments
```

---

## 2. Core Architecture & 5 Main Screens

1. **Screen 1 — Command Center (`screen-command`)**:
   - Executive telemetry metrics: Inspected Distance (10.0 KM / 42.6 KM), Total Defects (24), Critical Defects (2 P1), High-Risk Segments (3), Average Condition Score (78.4/100).
   - Real-time Chart.js telemetry: Defect classification doughnut, Severity tier breakdown, and Defect density per kilometer.
   - Survey operations registry with live inspection status badges.

2. **Screen 2 — New Inspection (`screen-new-inspection`)**:
   - Create inspection survey, corridor selection (`NH-48 Corridor`), imagery source tagging, model version selection (`RoadDefect-v1.0`), and drag-and-drop video upload with validation (`.mp4`, `.mov`).

3. **Screen 3 — Live / Batch Processing Status (`screen-live`)**:
   - Asynchronous pipeline tracker with live progress bar and status steps (`CREATED`, `UPLOADED`, `QUEUED`, `PROCESSING`, `AI_ANALYSIS`, `GEO_REFERENCING`, `AGGREGATION`, `COMPLETED`).
   - Frame telemetry counters and live inference event log with `MOCK CV` status indicator.

4. **Screen 4 — Road Intelligence GIS Map (`screen-map`)**:
   - Interactive Leaflet GIS map with OpenStreetMap tiles and verified attribution.
   - PostGIS-driven color-coded road segment polylines:
     - **GREEN**: Good (80–100 condition)
     - **YELLOW**: Monitor (60–79 condition)
     - **ORANGE**: High Risk (40–59 condition)
     - **RED**: Critical (<40 condition)
   - Interactive Segment Flyout (**Section 17 flagship segment RD-014**): Condition Score `48/100`, Risk Score `83/100`, Total Defects `17` (8 Potholes, 6 Cracks, 3 Markings), and "View Evidence" action.
   - Severity-colored defect pin markers with interactive inspection flyouts and direct video seek synchronization.

5. **Screen 5 — Defect Evidence Viewer & Synchronized Video Player (`screen-evidence`)**:
   - **Flagship Defect Inspector (DEF-POT-00124)**: Confidence 94.2%, Severity Critical, GPS `19.0682, 73.1785`, Segment `RD-014`, Model `RoadDefect-v1.0`.
   - **Side-by-Side Comparison**: Original camera frame vs AI annotated detection frame with glowing bounding boxes and confidence HUD.
   - **Synchronized Video Player (Section 19)**: Interactive timeline markers; clicking any defect instantly seeks the video to that exact timestamp with HTTP 206 Partial Content range requests.
   - **Report Generator (Section 26)**: One-click authenticated PDF report generation with PDF injection escaping and PoC disclaimers.

### Asynchronous Processing: In-Process Tasks vs Enterprise AWS SQS
- **PoC Runtime (In-Process)**: Video inference and PostGIS spatial mapping run asynchronously using FastAPI `BackgroundTasks` on the local event loop. This enables 100% turnkey local evaluation without Redis or Celery dependencies, while incorporating automatic crash recovery on server restarts.
- **Enterprise Scaling (AWS SQS)**: For nationwide fleet deployments, the modular pipeline in `backend/ai_pipeline.py` is architected to decouple behind an **Amazon SQS FIFO Queue** feeding auto-scaled GPU worker pools (AWS ECS Fargate / EC2 Spot GPU) with Dead-Letter Queues (DLQ). See **[HANDOVER.md Section 2.1](docs/HANDOVER.md#21-asynchronous-pipeline-architecture-in-process-vs-enterprise-aws-sqs)** for architecture diagrams and specifications.

---

## 3. Section 38 Demo Mode ("Golden Demo")

To guarantee a 100% reliable live pitch without external API dependencies or GPU cold-starts:
- Click the **"⚡ Golden Demo (DEMO-001)"** button in the header.
- Loads a pre-computed 10 KM survey on the **NH-48 Mumbai–Pune Expressway corridor** with 24 defects, high-resolution original & annotated frames, and synchronized video seek points.
- Can be reset to a pristine state at any time via `POST /api/demo/reset` (admin role required).

---

## 4. Security Architecture & Hardening

- **Zero-Trust Media Access**: All static mounts for media (`/static/media/evidence`, `/static/media/video`, `/static/reports`) are removed. Images and video are served strictly via authenticated endpoints (`/api/media/evidence/...` and `/api/media/video/...`).
- **HMAC URL Pre-Signing**: Evidence images and video playback use time-limited HMAC-SHA256 signatures (`10-minute expiry`, `clean_path` binding, constant-time compare).
- **Chunked Batch Signing**: Frontend signs files in batches of 100 via `POST /api/media/sign-batch`. Expired signatures are detected client-side with automatic single-retry fallback on `<img onerror>`.
- **DB-Backed Authentication & Role Verification**: JWT tokens re-query the PostgreSQL database on every request via `authenticate_token_with_db()`. Demoted or deleted users are refused immediately (401/403) without waiting for token expiry.
- **Strict Content Security Policy (CSP)**:
  ```http
  Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self' data:; img-src 'self' https://*.openstreetmap.org https://*.tile.openstreetmap.org data: blob:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'
  ```
  `script-src` contains **NO `'unsafe-inline'`**. All JavaScript is cleanly factored into external modules with event delegation.
- **Referrer Policy**: `strict-origin-when-cross-origin` ensures cross-origin OpenStreetMap tile requests include the required referrer origin while protecting private path parameters.
- **Path Traversal & Injection Hardening**: All file endpoints strictly validate paths against canonical directory roots. PDF report generator escapes HTML entities and disables dangerous tags.
- **API Protection**: Strict origin verification via CORS, IP rate limiting on authentication routes, and disabled Swagger docs in production (`ENABLE_DOCS=0`).

---

## 5. Setup & Installation from a Fresh Clone

### Prerequisites
- macOS or Linux
- Python: Verified support: **Python 3.9.6**. Python 3.10–3.13 are marked **NOT VERIFIED** (Python 3.9+ required and validated by ./run.sh, but only 3.9.6 is installed and tested on this machine; Python >= 3.14 is unsupported).
- Database: PostgreSQL 14+ with PostGIS 3.0+ (Local Docker PostGIS: docker-compose.yml)

### 1. Clone & Set Up Virtual Environment
```bash
git clone <repository-url> ztracs-road-intelligence
cd ztracs-road-intelligence

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt   # For development and running test suites
playwright install chromium
```

### 2. Start PostgreSQL / PostGIS Database (Docker)
Start the local PostGIS container:
```bash
docker compose up -d
```
This spins up PostgreSQL 16 with PostGIS 3.4 bound to `127.0.0.1:5432`, creating the `ztracs` database and `ztracs_pgdata` volume with healthchecks.

> **Note**: Both the application runtime and all automated test suites require the Docker PostgreSQL database running.

### 3. Configure Environment
Copy the template configuration:
```bash
cp .env.example .env
```
Default credentials in `.env.example` match `docker-compose.yml`:
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

### 4. Deployment Modes: Local Mode vs AWS Mode

Z-TRACS supports two primary operational deployments:

| Component | Local Mode (Default) | AWS Mode (Cloud Production / Staging) |
|---|---|---|
| **Database** | Containerized PostgreSQL 16 + PostGIS 3.4 (`docker-compose.yml`, `127.0.0.1:5432`) | Managed AWS RDS PostgreSQL with PostGIS extension (`sslmode=require`) |
| **Media Storage** | Local filesystem (`data/video/`, `static/media/evidence/`, `static/reports/`) | AWS S3 Bucket (`USE_S3_STORAGE=true`, presigned uploads/downloads) |
| **Config File** | `cp .env.example .env` | `cp .env.aws.example .env` |
| **Credentials** | Default Docker credentials (`postgres:postgres`) | Scoped AWS IAM credentials & RDS database credentials |

#### Running in Local Mode:
1. Ensure Docker PostGIS is running: `docker compose up -d`
2. Ensure `.env` is configured for local mode (`USE_S3_STORAGE=false`, local `DATABASE_URL`)
3. Launch backend: `./run.sh`

#### Running in AWS Mode:
1. Copy AWS template: `cp .env.aws.example .env`
2. Populate `DATABASE_URL` with your RDS endpoint and URL-encoded credentials (`?sslmode=require`)
3. Set `USE_S3_STORAGE=true` and populate `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `S3_BUCKET_NAME`
4. Configure RDS Security Group IP Whitelist (see below)
5. Launch backend: `./run.sh`

#### Configuring S3 Bucket CORS for Browser Direct Uploads

When `USE_S3_STORAGE=true`, survey videos are uploaded directly from the operator's browser to Amazon S3 via presigned PUT URLs. For direct browser `PUT` requests to succeed, Cross-Origin Resource Sharing (CORS) must be configured on the S3 bucket:

1. In the **AWS Management Console**, navigate to **Amazon S3** &rarr; **Buckets** &rarr; Select your bucket (e.g. `ztracsroads`).
2. Select the **Permissions** tab and scroll to **Cross-origin resource sharing (CORS)**.
3. Click **Edit** and paste the following CORS configuration:

```json
[
  {
    "AllowedHeaders": [
      "*"
    ],
    "AllowedMethods": [
      "PUT",
      "GET",
      "HEAD"
    ],
    "AllowedOrigins": [
      "http://localhost:3000",
      "http://127.0.0.1:3000",
      "http://localhost:8000",
      "http://127.0.0.1:8000"
    ],
    "ExposeHeaders": [
      "ETag"
    ],
    "MaxAgeSeconds": 3600
  }
]
```
4. Click **Save changes**.

> **Note**: For production deployments, replace the localhost entries in `AllowedOrigins` with your production frontend domain (e.g., `https://roads.ztracs.ai`).

#### Configuring RDS Security Group Inbound Rules (IP Whitelisting)

To connect your workstation or application server to AWS RDS on port 5432, your public IP must be whitelisted in the RDS VPC Security Group:

1. **Locate your RDS Security Group**:
   - Log into the **AWS Management Console** and navigate to **Amazon RDS** &rarr; **Databases**.
   - Select your DB instance (e.g., `ztracs-db`).
   - Under the **Connectivity & security** tab, locate the **VPC security groups** section and click the security group link (e.g., `sg-xxxx`).
2. **Edit Inbound Rules**:
   - In the Security Group console, select the **Inbound rules** tab and click **Edit inbound rules**.
   - Add a rule (or edit existing PostgreSQL rule):
     - **Type**: `PostgreSQL`
     - **Protocol**: `TCP`
     - **Port Range**: `5432`
     - **Source**: Select `My IP` from the dropdown, or enter your exact workstation IP in CIDR format: `<your-ip>/32`.
     - *Security Best Practice*: **Never set source to `0.0.0.0/0` (anywhere).** Always scope the ingress rule to your specific `/32` IP address.
   - Click **Save rules**.
3. **Important Note on Dynamic Public IPs**:
   - Residential, mobile hotspot, and commercial office internet connections frequently assign dynamic public IP addresses that change on reconnect or router reboot.
   - **Whenever your external IP changes**, your database connection will hang or time out on port 5432.
   - To verify your current IP, run: `curl -s https://checkip.amazonaws.com`
   - If the connection times out, return to the RDS Security Group console and update the inbound rule to your new IP address.

### 5. Running the Application: Unified Mode vs Split Mode

#### Mode A: Unified Mode (Default)
Backend API and frontend static assets are served together by FastAPI on port 8000:
```bash
./run.sh
```
- Server URL: **`http://127.0.0.1:8000`**
- Default credentials (from `.env.example`): Username **`admin`**, Password **`change-me-admin-password`**
- All API and asset routes resolve locally on the same origin (`API_BASE=""`).

#### Mode B: Split Mode (Frontend & Backend Separated)
Start backend and frontend as separate services:
1. **Terminal 1 — Backend (Port 8000)**:
   ```bash
   ./run.sh
   ```
2. **Terminal 2 — Frontend (Port 3000)**:
   ```bash
   ./run-frontend.sh
   # Or with a custom backend target:
   API_BASE=http://127.0.0.1:8000 ./run-frontend.sh
   ```
- Frontend UI: **`http://127.0.0.1:3000`**
- Backend API: **`http://127.0.0.1:8000`**
- Default credentials (from `.env.example`): Username **`admin`**, Password **`change-me-admin-password`**
- `run-frontend.sh` automatically injects `window.API_BASE` for all fetch requests and media URLs without modifying any tracked files.
- `ALLOWED_ORIGINS` in `.env` must include `http://127.0.0.1:3000,http://localhost:3000` (included by default).

---

## 6. Running the Automated Test Suites

All tests automatically provision isolated, ephemeral PostgreSQL test databases and throwaway credentials on the running PostgreSQL server (`docker compose up -d`). They never modify the real `ztracs` database.

```bash
# 1. Security & Authentication Audit Suite (29 checks)
./venv/bin/python3 tests/test_security.py

# 2. Pipeline, PostGIS Spatial, & Ingestion Suite (24 checks)
./venv/bin/python3 tests/test_pipeline.py

# 3. Real Browser E2E Suite via Playwright (Chromium)
./venv/bin/python3 tests/test_browser_pipeline.py

# 4. Split Mode Cross-Origin E2E Suite (Ports 8000 & 3000)
./venv/bin/python3 tests/test_split_mode.py
```

---

## 7. Environment Variables Reference

| Variable | Default / Example | Description |
| :--- | :--- | :--- |
| `DATABASE_URL` | `postgresql://user@localhost:5432/ztracs` | PostgreSQL + PostGIS connection string |
| `JWT_SECRET` | *(Must be set, min 32 chars)* | Cryptographic key for JWT tokens and HMAC URL signing |
| `ADMIN_USERNAME` | `admin` | Initial seeded administrator account |
| `ADMIN_PASSWORD` | *(Must be set)* | Password for seeded administrator account |
| `HOST` | `127.0.0.1` | Server binding host address |
| `PORT` | `8000` | Server binding port |
| `ALLOWED_ORIGINS` | `http://localhost:8000,http://127.0.0.1:8000` | Whitelisted CORS origins |
| `CV_MODE` | `mock` (`mock` or `real`) | Inference pipeline execution mode |
| `ENABLE_DOCS` | `0` (`0` or `1`) | Toggle FastAPI OpenAPI docs (`/docs`) |
| `DATA_DIR` | `./data` | Inspection metadata storage |
| `EVIDENCE_DIR` | `./static/media/evidence` | Evidence frames repository |
| `VIDEO_DIR` | `./static/media/video` | Dashcam video repository |
| `REPORTS_DIR` | `./static/reports` | Generated PDF inspection reports |

---

## 8. Project Directory Layout

```
ztracs-road-intelligence/
├── docker-compose.yml            # Docker container definition for PostGIS 16-3.4 (127.0.0.1:5432)
├── run.sh                        # Unified launcher with pre-flight checks, DB init & demo seed (port 8000)
├── run-frontend.sh               # Dedicated frontend server with dynamic API_BASE injection (port 3000)
├── backend/
│   ├── main.py                   # FastAPI REST API server & middleware
│   ├── s3_client.py              # AWS S3 cloud storage client & video streaming
│   ├── auth.py                   # JWT security, RBAC & DB-backed user validation
│   ├── models.py                 # Pydantic validation schemas & CV contract
│   ├── database.py               # PostGIS schema migrations & DB pooling
│   ├── scoring_engine.py         # Condition, Risk & P1-P4 priority calculation (PoC weights, calibrated so the demo segment matches the spec example, not an engineering standard.)
│   ├── ai_pipeline.py            # Asynchronous background video inference worker
│   ├── reports.py                # ReportLab PDF report generation engine
│   ├── seed_data.py              # Golden Demo DEMO-001 dataset seed generator
│   └── migrate_sqlite_to_postgres.py # Idempotent legacy migration utility
├── frontend/
│   ├── index.html                # Single page application markup (no inline scripts)
│   ├── css/style.css             # Glassmorphic tactical styling & GIS layer styles
│   └── js/
│       ├── app.js                # Application controller, state & screen router
│       ├── map.js                # Leaflet GIS engine & defect coordinate plotting
│       ├── video.js              # Synchronized video player & seek controllers
│       ├── charts.js             # Chart.js analytics & dashboard telemetry
│       ├── events.js             # CSP-compliant external UI event delegation
│       └── tailwind.config.js    # External Tailwind theme & brand token definitions
├── tests/
│   ├── test_security.py          # Security audit test suite (28 assertions)
│   ├── test_pipeline.py          # PostGIS & processing pipeline suite (21 assertions)
│   └── test_browser_pipeline.py  # Playwright real browser E2E test suite (12 assertions)
├── static/
│   └── media/                    # Local storage for evidence & demo video

├── docs/
│   ├── HANDOVER.md               # Technical onboarding and developer guide
│   └── PROJECT_REPORT.md         # Comprehensive project audit and engineering report
├── requirements-dev.txt          # Development, testing, and linting requirements
├── requirements.txt              # Python package dependencies
├── .env.example                  # Environment configuration template
└── README.md                     # Project documentation
```

---

## 9. Known Limitations & Production Notes

1. **Tailwind CDN**:
   > **TODO**: Replace the Tailwind CDN (`<script src="https://cdn.tailwindcss.com"></script>`) with a pre-compiled Tailwind CSS bundle (via Tailwind CLI or PostCSS) prior to production deployment to eliminate browser console warnings and optimize asset loading.
2. **AI Inference Mode**: The pipeline currently operates in mock inference mode (`CV_MODE=mock`) generating realistic defect telemetry for testing. When moving to production GPU nodes, point `ai_pipeline.py` to the trained YOLO/PyTorch model weights.
3. **AWS Cloud Integrations**:
   - **AWS S3 Cloud Storage**: Implemented and operational via bucket `ztracsroads` (us-east-1). Supports byte-range video streaming, pre-signed upload URLs, and fallback to local disk.
   - **AWS RDS PostgreSQL**: Connected and operational with PostGIS spatial extension.
   - **Vercel Serverless**: Configured with `vercel.json` and `api/index.py`.
