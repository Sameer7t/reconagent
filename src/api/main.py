"""
ReconAgent FastAPI REST API Application.

Main entrypoint coordinating:
- Document Ingestion & Classification
- Multi-Way Reconciliation
- LangGraph Autonomous AI Investigation
- Human Review Queue & Governance
- SQLite Relational Persistence
"""
import os
import sys
import logging
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional

# Ensure project root and src/ are in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_ROOT = Path(__file__).resolve().parent.parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from datetime import datetime, timezone
from fastapi import FastAPI, Request, status, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from api.schemas import HealthResponse, SystemInfoResponse
from api.dependencies import get_db, get_review_queue_dep, get_orchestrator
from api.routes import documents, cases, investigations, review, transactions, auth
from observability.middleware import RequestIdMiddleware
from observability.metrics import get_metrics_collector
from observability.logging import get_structured_logger

logger = logging.getLogger("ReconAgentAPI")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifecycle manager:
    - Pre-warms database and runs SQLite schema migrations
    - Hydrates human review queue with pending investigations
    - Pre-warms MasterOrchestrator
    - Releases resources on shutdown
    """
    logger.info("Initializing ReconAgent API and persisting datastores...")
    db = get_db()
    
    from api.dependencies import get_user_db
    user_db = get_user_db()
    
    rq = get_review_queue_dep()
    orchestrator = get_orchestrator()

    loaded_review_items = len(rq.queue)
    logger.info(f"ReconAgent API ready. Loaded {loaded_review_items} cases into Review Queue.")

    # Seed default Admin user in PostgreSQL
    from api.routes.auth import get_password_hash
    if not user_db.get_user_by_email('admin@reconagent.local'):
        hashed = get_password_hash("admin")
        user_db.create_user("admin@reconagent.local", hashed, "Admin")
        logger.info("Created default admin user 'admin@reconagent.local' with password 'admin'")

    yield

    logger.info("Shutting down ReconAgent API and closing database connections...")
    if orchestrator:
        orchestrator.close()
    if db:
        db.close()


tags_metadata = [
    {
        "name": "Documents",
        "description": "Ingest, classify, extract structured data, and validate math from invoices, POs, and receipts.",
    },
    {
        "name": "Cases & Reconciliation",
        "description": "Execute 3-way reconciliation on single triplets, batch directories, or arbitrary mixed document uploads.",
    },
    {
        "name": "Investigations",
        "description": "Query autonomous AI agent root-cause findings, evidence audit trees, and tool traces.",
    },
    {
        "name": "Review Queue",
        "description": "Human governance layer for specialist sign-off, approvals, overrides, and escalation.",
    },
]

app = FastAPI(
    title="ReconAgent API",
    description=(
        "Autonomous AI-Powered Invoice Reconciliation & Investigation System REST API.\n\n"
        "Features:\n"
        "- Multi-format document upload (PDF, TXT, scanned images)\n"
        "- Mixed and individual (PO / Invoice / Receipt) ingestion modes\n"
        "- Deterministic 3-Way Reconciliation with tolerance checks\n"
        "- LangGraph Autonomous AI Investigation with 9-Tier Gemini router\n"
        "- Human-in-the-loop governance review queue with SQLite audit persistence"
    ),
    version="1.0.0",
    lifespan=lifespan,
    openapi_tags=tags_metadata,
    docs_url="/docs",
    redoc_url="/redoc",
)

# -----------------------------------------------------------------------------
# CORS Middleware
# -----------------------------------------------------------------------------
cors_origins_env = os.getenv("CORS_ORIGINS", "*")
if cors_origins_env.strip() == "*":
    allow_origins = ["*"]
else:
    allow_origins = [o.strip() for o in cors_origins_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestIdMiddleware)

# -----------------------------------------------------------------------------
# Global Exception Handlers
# -----------------------------------------------------------------------------
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "VALIDATION_ERROR",
            "message": "Input validation failed on requested payload.",
            "details": exc.errors(),
        },
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled server error on {request.url.path}: {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "INTERNAL_SERVER_ERROR",
            "message": str(exc),
        },
    )


# -----------------------------------------------------------------------------
# Router Inclusions (Direct routes and /api prefixed routes)
# -----------------------------------------------------------------------------
# Documents: /documents and /api/documents
app.include_router(documents.router, prefix="/api", dependencies=[Depends(auth.get_current_user)])
app.include_router(documents.router, prefix="", dependencies=[Depends(auth.get_current_user)])
 
# Transactions: /transactions and /api/transactions
app.include_router(transactions.router, prefix="/api", dependencies=[Depends(auth.get_current_user)])
app.include_router(transactions.router, prefix="", dependencies=[Depends(auth.get_current_user)])

# Cases: /cases and /api/cases
app.include_router(cases.router, prefix="/api", dependencies=[Depends(auth.get_current_user)])
app.include_router(cases.router, prefix="", dependencies=[Depends(auth.get_current_user)])

# Investigations: /investigations and /api/investigations
app.include_router(investigations.router, prefix="/api", dependencies=[Depends(auth.get_current_user)])
app.include_router(investigations.router, prefix="", dependencies=[Depends(auth.get_current_user)])

# Review Queue: /review, /api/review, /review-queue, and /api/review-queue
app.include_router(review.router, prefix="/api/review", dependencies=[Depends(auth.get_current_user)])
app.include_router(review.router, prefix="/review", dependencies=[Depends(auth.get_current_user)])
app.include_router(review.router, prefix="/api/review-queue", dependencies=[Depends(auth.get_current_user)])
app.include_router(review.router, prefix="/review-queue", dependencies=[Depends(auth.get_current_user)])

# Authentication: /auth and /api/auth
app.include_router(auth.router, prefix="/api/auth")
app.include_router(auth.router, prefix="/auth")


from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse

FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
if (FRONTEND_DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")


# -----------------------------------------------------------------------------
# Root & Health Endpoints
# -----------------------------------------------------------------------------
@app.get("/", tags=["System"])
def root(request: Request):
    """Serves compiled React frontend dashboard to web browsers, or API index to API clients."""
    accept = request.headers.get("accept", "")
    index_path = FRONTEND_DIST / "index.html"
    if "text/html" in accept and index_path.is_file():
        return FileResponse(str(index_path))
    return {
        "service": "ReconAgent API",
        "version": "1.0.0",
        "documentation": "/docs",
        "redoc": "/redoc",
        "health": "/health",
        "status": "OPERATIONAL",
    }


@app.get("/dashboard", tags=["System"])
@app.get("/app", tags=["System"])
def serve_dashboard():
    """Direct route to frontend dashboard."""
    index_path = FRONTEND_DIST / "index.html"
    if index_path.is_file():
        return FileResponse(str(index_path))
    return JSONResponse(status_code=404, content={"message": "Frontend build not found."})



@app.get("/health", tags=["System"])
@app.get("/api/health", tags=["System"])
def health_liveness():
    """Liveness probe: simply confirms the application is running."""
    return {
        "status": "healthy",
        "service": "ReconAgent API",
        "version": "1.0.0",
        "database_connected": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/health/ready", tags=["System"])
@app.get("/api/health/ready", tags=["System"])
def health_readiness():
    """Readiness probe: checks required dependencies such as PostgreSQL."""
    db = get_db()
    try:
        with db._get_connection() as conn:
            conn.execute("SELECT 1")
        is_pg = getattr(db, "is_postgres", False)
        return {
            "status": "ready",
            "dependencies": {
                "database": {
                    "status": "up",
                    "type": "postgresql" if is_pg else "sqlite",
                    "connected": True,
                }
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "not_ready",
                "dependencies": {
                    "database": {
                        "status": "down",
                        "connected": False,
                        "error": str(exc),
                    }
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )


@app.get("/metrics", tags=["System"])
@app.get("/api/metrics", tags=["System"])
def system_metrics():
    """Exposes application performance and operational metrics."""
    return get_metrics_collector().get_metrics()


@app.get("/logs", tags=["System"], dependencies=[Depends(auth.require_role(["Admin"]))])
@app.get("/api/logs", tags=["System"], dependencies=[Depends(auth.require_role(["Admin"]))])
def system_logs(
    limit: int = 100,
    stage: Optional[str] = None,
    level: Optional[str] = None,
    case_id: Optional[str] = None,
    request_id: Optional[str] = None,
    current_user: dict = Depends(auth.require_role(["Admin"])),
):
    """
    Exposes recent structured log entries with optional filtering by stage, level, case_id, or request_id.
    RESTRICTED: Requires Admin role authentication.
    """
    s_logger = get_structured_logger()
    records = s_logger.get_records()
    if stage:
        records = [r for r in records if r.get("stage") == stage]
    if level:
        records = [r for r in records if r.get("level", "").upper() == level.upper()]
    if case_id:
        records = [r for r in records if r.get("case_id") == case_id]
    if request_id:
        records = [r for r in records if r.get("request_id") == request_id]

    return {
        "status": "success",
        "total_records": len(records),
        "log_file": str(getattr(s_logger, "log_file", "logs/reconagent.jsonl")),
        "logs": records[-limit:],
    }


@app.get("/api/info", response_model=SystemInfoResponse, tags=["System"])
def system_info():
    """Returns supported AI models, document categories, and file types."""
    return SystemInfoResponse()


