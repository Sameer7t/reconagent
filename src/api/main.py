"""
ReconAgent FastAPI REST API Application.

Main entrypoint coordinating:
- Document Ingestion & Classification
- Multi-Way Reconciliation
- LangGraph Autonomous AI Investigation
- Human Review Queue & Governance
- SQLite Relational Persistence
"""
import sys
import logging
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Dict, Any

# Ensure project root and src/ are in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_ROOT = Path(__file__).resolve().parent.parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI, Request, status, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from api.schemas import HealthResponse, SystemInfoResponse
from api.dependencies import get_db, get_review_queue_dep, get_orchestrator
from api.routes import documents, cases, investigations, review, transactions, auth

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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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



@app.get("/health", response_model=HealthResponse, tags=["System"])
@app.get("/api/health", response_model=HealthResponse, tags=["System"])
def health_check():
    """System health check and database connectivity probe."""
    db = get_db()
    rq = get_review_queue_dep()

    total_inv = 0
    try:
        with db._get_connection() as conn:
            cur = conn.execute("SELECT COUNT(*) FROM investigations")
            total_inv = cur.fetchone()[0]
        db_connected = True
    except Exception:
        db_connected = False

    metrics = rq.get_metrics()

    return HealthResponse(
        status="healthy" if db_connected else "degraded",
        version="1.0.0",
        database_connected=db_connected,
        total_investigations=total_inv,
        review_queue_pending=metrics.get("pending_count", 0),
    )


@app.get("/api/info", response_model=SystemInfoResponse, tags=["System"])
def system_info():
    """Returns supported AI models, document categories, and file types."""
    return SystemInfoResponse()

