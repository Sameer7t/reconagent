# ReconAgent: Autonomous AI-Powered Invoice Reconciliation & Investigation System

[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2+-orange.svg)](https://langchain-ai.github.io/langgraph/)
[![React 18](https://img.shields.io/badge/React-18-61DAFB.svg?logo=react&logoColor=black)](https://react.dev/)
[![PostgreSQL 16](https://img.shields.io/badge/PostgreSQL-16-336791.svg?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED.svg?logo=docker&logoColor=white)](https://www.docker.com/)
[![Tests](https://img.shields.io/badge/Tests-77%20Passed-brightgreen.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

ReconAgent is an enterprise-grade, autonomous invoice reconciliation and root-cause investigation system. It bridges the gap between deterministic 3-way reconciliation (Purchase Orders, Invoices, Delivery Receipts) and agentic root-cause resolution using a stateful **LangGraph** autonomous agent equipped with a **9-tier Gemini cascade router**, **PostgreSQL** relational persistence, a **Human-in-the-Loop review queue**, and **end-to-end observability**.

---

## Architecture Overview

```text
                                  +---------------------------------------+
                                  |         Ingestion & Extraction        |
                                  |  (PDF, TXT, Scanned Images / Receipts)|
                                  +-------------------+-------------------+
                                                      |
                                                      v
                                  +---------------------------------------+
                                  |     Mathematical Validation Engine    |
                                  |    (Line totals, subtotals, taxes)    |
                                  +-------------------+-------------------+
                                                      |
                                                      v
                                  +---------------------------------------+
                                  |    Deterministic 3-Way Reconciler     |
                                  | (Unit price, quantity, fuzzy matcher) |
                                  +-------------------+-------------------+
                                                      |
                                     [Clean Match]    |    [Variance / Discrepancy]
                                     +----------------+---------------+
                                     |                                |
                                     v                                v
                        +------------------------+      +---------------------------+
                        |  Auto-Approve Payment  |      |   LangGraph Agent State   |
                        +------------------------+      |  Autonomous Investigation |
                                                        +-------------+-------------+
                                                                      |
                                                                      v
                                                        +---------------------------+
                                                        |  9-Tier Gemini Cascade    |
                                                        |  - Tool Call Reasoning    |
                                                        |  - Contract / PO Audit    |
                                                        |  - Evidence Synthesis    |
                                                        +-------------+-------------+
                                                                      |
                                                                      v
                                                        +---------------------------+
                                                        | Human-in-the-Loop Review  |
                                                        | Role-Based Signoff & DB   |
                                                        +---------------------------+
```

---

## Key Features

1. **Deterministic Multi-Way Reconciliation Engine:**
   - Full 3-way matching across Purchase Orders (PO), Invoices (INV), and Delivery Receipts (DR).
   - Tolerant price variance detection ($0.01 tolerance) and exact line-level shortage/overage tracking.
   - Semantic fuzzy description reconciliation using normalized token ratios.

2. **Autonomous LangGraph AI Investigator:**
   - Autonomous multi-step root-cause analysis agent.
   - Dynamic tool use: queries authorization registries, historical vendor profiles, arithmetic checkers, and proof-of-delivery receipts.
   - Generates audit-ready evidence citations and deterministic recommendations (`APPROVE_PAYMENT`, `REQUEST_CREDIT_MEMO`, `FLAG_SUSPECTED_FRAUD`, etc.).

3. **9-Tier Gemini Model Router:**
   - Multi-tier cascading fallback for high reliability under rate limits:
     `gemini-3.8-flash` $\rightarrow$ `gemini-3.7-flash` $\rightarrow$ `gemini-2.5-pro` $\rightarrow$ `gemini-2.5-flash` $\rightarrow$ ...
   - Automatic exponential backoff handling of HTTP 429 quota exhaustion, 503 service spikes, and network timeouts.

4. **Human-in-the-Loop Governance & Audit Logging:**
   - Tiered Role-Based Access Control (RBAC): `Admin`, `Reviewer`, and `Viewer`.
   - Durable review queue supporting manual approval, rejection, or escalation with reviewer notes.

5. **Enterprise Observability (Phase 11):**
   - High-throughput structured JSON logging across all 7 pipeline stages.
   - In-memory ring buffer and persistent rotation to `logs/reconagent.jsonl`.
   - Distinct `request_id` (per API call) and `case_id` (per business transaction).
   - Strict PII/credential sanitization (passwords, tokens, API keys, and raw documents are never logged).
   - Kubernetes-ready `/health` (liveness), `/health/ready` (readiness), and `/metrics` telemetry endpoints.

6. **Production Containerization (Phase 12):**
   - Orchestrated multi-container stack: **PostgreSQL 16** + **FastAPI Backend** + **Vite/React Frontend served via Nginx Reverse Proxy**.
   - Automatic schema initialization and database migrations on boot.
   - Persistent volume mounts ensuring data survives container restarts.

---

## Quickstart with Docker Compose

Running the entire system anywhere requires only Docker and Docker Compose.

### 1. Clone the Repository
```bash
git clone https://github.com/Sameer7t/reconagent.git
cd reconagent
```

### 2. Configure Environment
Copy the example environment template:
```bash
cp .env.example .env
```
Edit `.env` to supply your **Google Gemini API Key**:
```dotenv
GEMINI_API_KEY=your_actual_gemini_api_key_here
```

### 3. Launch Services
```bash
docker compose up -d --build
```

### 4. Verify Services
Check container health:
```bash
docker compose ps
```
All three containers (`reconagent-db`, `reconagent-backend`, `reconagent-frontend`) will report status **Up (healthy)**.

---

## Service Endpoints & Default Credentials

| Service | URL | Description |
| :--- | :--- | :--- |
| **Frontend Web App** | [http://localhost:3000](http://localhost:3000) (or port 80) | Interactive React reconciliation workspace & review console |
| **Backend REST API** | [http://localhost:8000](http://localhost:8000) | Core ASGI FastAPI server |
| **Swagger Interactive Docs** | [http://localhost:8000/docs](http://localhost:8000/docs) | OpenAPI specification and API testing playground |
| **Liveness Health Probe** | [http://localhost:8000/health](http://localhost:8000/health) | Container liveness verification |
| **Readiness Health Probe** | [http://localhost:8000/health/ready](http://localhost:8000/health/ready) | Verifies PostgreSQL connectivity and pool status |
| **Application Metrics** | [http://localhost:8000/metrics](http://localhost:8000/metrics) | Latencies, counters, router attempts, and tool traces |
| **System Audit Logs** | [http://localhost:8000/logs](http://localhost:8000/logs) | Admin-only structured audit logs |
| **PostgreSQL Database** | `localhost:5432` | Database: `reconagent`, User: `postgres`, Password: `root` |

### Default Admin Account
* **Email:** `admin@reconagent.local`
* **Password:** `admin`
* **Role:** `Admin` (Full access to reconciliation, user management, and system logs)

---

## Local Development (Without Docker)

If you prefer to run services natively on your local machine:

### 1. Backend Setup
```bash
# Create and activate virtual environment
python -m venv .venv
# On Windows:
.\.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run FastAPI with live reload
uvicorn src.api.main:app --host 127.0.0.1 --port 8000 --reload
```

### 2. Frontend Setup
```bash
cd frontend
npm install
npm run dev
```
The Vite development server will open at `http://localhost:5173` and automatically proxy API calls to `http://127.0.0.1:8000`.

---

## Running the Automated Test Suite

ReconAgent includes an extensive automated test suite covering all units, pipelines, observability metrics, role-based security, and Docker configurations.

```bash
# Run all 77 unit, integration, and deployment tests
pytest -v

# Run observability suite only
pytest tests/test_observability.py -v

# Run Docker deployment configuration tests
pytest tests/test_docker_deployment.py -v

# Test frontend production build
cd frontend
npm run build
```

---

## Project Structure

```text
.
├── docker-compose.yml          # Production Docker Compose orchestration
├── Dockerfile                  # Backend Python 3.12 container specification
├── requirements.txt            # Python dependencies (FastAPI, LangGraph, Psycopg2, etc.)
├── .env.example                # Documented configuration template
├── scripts/
│   ├── init_db.sql             # PostgreSQL schema, indexes, and initial admin seed
│   └── docker-entrypoint.sh    # Container entrypoint with wait-for-Postgres loop
├── src/
│   ├── api/                    # FastAPI routes, dependencies, and lifecycle
│   │   ├── main.py             # App entrypoint, middleware, health endpoints
│   │   ├── dependencies.py     # Database and review queue dependency providers
│   │   └── routes/             # Documents, Cases, Investigations, Review, Auth
│   ├── agent/                  # Autonomous AI investigation agent
│   │   ├── graph.py            # LangGraph state machine workflow
│   │   ├── router.py           # 9-Tier Gemini cascade fallback router
│   │   ├── db.py               # Enterprise PostgreSQL connection pool & SQLite fallback
│   │   ├── user_db.py          # User authentication and RBAC repository
│   │   ├── review_queue.py     # Human-in-the-loop review queue manager
│   │   └── tools/              # Agent tools (PO inspection, receipt verification, math)
│   ├── reconciliation/         # Deterministic multi-way reconciliation
│   │   ├── pipeline.py         # Orchestration pipeline
│   │   ├── line_item_matcher.py# Rate and quantity tolerance matcher
│   │   └── description_reconciler.py # Semantic description fuzzy matcher
│   ├── ingestion/              # Ingestion & document classification
│   ├── extraction/             # Multi-modal structured data extraction
│   └── observability/          # Enterprise observability layer
│       ├── logging.py          # Structured JSON logging and stage timers
│       ├── metrics.py          # Application latency and operational counters
│       ├── context.py          # Async-safe request_id and case_id contextvars
│       └── middleware.py       # Request ID binding and timing middleware
├── frontend/                   # React 18 + Vite + Tailwind CSS dashboard
│   ├── Dockerfile              # Multi-stage build (Node build -> Nginx serve)
│   ├── nginx.conf              # Nginx reverse proxy routing
│   └── src/                    # Components (CasesTable, CaseDetailView, SystemLogsModal)
└── tests/                      # Automated test suite (77 passing tests)
```

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
