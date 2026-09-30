"""
Unit and Integration Tests for ReconAgent Dockerization & Production Deployment.

Validates Phase 12 specifications:
1. Backend Dockerfile structure, Python base image, runtime dependencies, entrypoint
2. Frontend multi-stage Dockerfile and Nginx reverse proxy configuration
3. PostgreSQL container definition and persistent named volumes
4. Environment variable handling and .env.example template completeness
5. Database initialization SQL schema and extensions
6. Integration with Phase 11 health probes (/health and /health/ready)
"""
import os
import sys
import yaml
import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient
from api.main import app


# =============================================================================
# 1. BACKEND DOCKERFILE VALIDATION
# =============================================================================
def test_backend_dockerfile_structure():
    """Verify backend Dockerfile exists, uses python:3.12-slim, exposes port 8000, and defines healthcheck."""
    dockerfile_path = PROJECT_ROOT / "Dockerfile"
    assert dockerfile_path.exists(), "Dockerfile must exist at project root"

    content = dockerfile_path.read_text(encoding="utf-8")
    assert "FROM python:3.12-slim" in content
    assert "EXPOSE 8000" in content
    assert "HEALTHCHECK" in content
    assert "/health" in content
    assert "requirements.txt" in content
    assert "ENTRYPOINT" in content
    assert "docker-entrypoint.sh" in content


def test_requirements_txt_production_dependencies():
    """Verify requirements.txt contains all production runtime dependencies."""
    req_path = PROJECT_ROOT / "requirements.txt"
    assert req_path.exists(), "requirements.txt must exist at project root"

    content = req_path.read_text(encoding="utf-8")
    required_packages = [
        "fastapi",
        "uvicorn",
        "psycopg2-binary",
        "bcrypt",
        "PyJWT",
        "python-dotenv",
        "google-genai",
        "langgraph",
        "langchain-core",
        "pypdf",
        "pillow",
        "httpx",
    ]
    for pkg in required_packages:
        assert any(pkg.lower() in line.lower() for line in content.splitlines()), f"Missing dependency: {pkg}"


def test_docker_entrypoint_script():
    """Verify docker-entrypoint.sh exists and contains PostgreSQL wait loop logic."""
    entrypoint_path = PROJECT_ROOT / "scripts" / "docker-entrypoint.sh"
    assert entrypoint_path.exists(), "scripts/docker-entrypoint.sh must exist"

    content = entrypoint_path.read_text(encoding="utf-8")
    assert "DATABASE_URL" in content
    assert "psycopg2" in content
    assert 'exec "$@"' in content


# =============================================================================
# 2. FRONTEND DOCKERFILE & NGINX CONFIGURATION
# =============================================================================
def test_frontend_dockerfile_multistage():
    """Verify frontend Dockerfile utilizes a multi-stage build (Node build -> Nginx serve)."""
    frontend_dockerfile = PROJECT_ROOT / "frontend" / "Dockerfile"
    assert frontend_dockerfile.exists(), "frontend/Dockerfile must exist"

    content = frontend_dockerfile.read_text(encoding="utf-8")
    assert ("FROM node:20-alpine AS build" in content or "FROM node:20-slim AS build" in content)
    assert "FROM nginx" in content
    assert "COPY --from=build" in content
    assert "EXPOSE 80" in content
    assert "HEALTHCHECK" in content


def test_nginx_reverse_proxy_configuration():
    """Verify nginx.conf properly proxies API, auth, health, metrics, and logs routes to backend."""
    nginx_conf = PROJECT_ROOT / "frontend" / "nginx.conf"
    assert nginx_conf.exists(), "frontend/nginx.conf must exist"

    content = nginx_conf.read_text(encoding="utf-8")
    assert "proxy_pass http://backend:8000" in content
    assert "try_files $uri $uri/ /index.html" in content
    assert "client_max_body_size" in content
    assert "gzip on" in content

    # Verify key proxied route prefixes
    for route in ["api", "auth", "health", "metrics", "logs", "docs"]:
        assert route in content, f"Missing route in nginx proxy configuration: {route}"


# =============================================================================
# 3. DOCKER COMPOSE ORCHESTRATION & PERSISTENCE
# =============================================================================
def test_docker_compose_validity_and_services():
    """Verify docker-compose.yml defines db, backend, and frontend with required networks and volumes."""
    compose_path = PROJECT_ROOT / "docker-compose.yml"
    assert compose_path.exists(), "docker-compose.yml must exist"

    with open(compose_path, "r", encoding="utf-8") as f:
        compose_data = yaml.safe_load(f)

    assert "services" in compose_data
    services = compose_data["services"]

    # 1. Database service (PostgreSQL 16)
    assert "db" in services
    db_service = services["db"]
    assert "postgres" in db_service["image"]
    assert "healthcheck" in db_service
    assert any("postgres_data:" in str(v) for v in db_service.get("volumes", []))
    assert any("init_db.sql" in str(v) for v in db_service.get("volumes", []))

    # 2. Backend service
    assert "backend" in services
    backend_service = services["backend"]
    assert backend_service.get("depends_on", {}).get("db", {}).get("condition") == "service_healthy"
    assert "healthcheck" in backend_service
    assert any("backend_data:" in str(v) for v in backend_service.get("volumes", []))
    assert any("backend_logs:" in str(v) for v in backend_service.get("volumes", []))

    # 3. Frontend service
    assert "frontend" in services
    frontend_service = services["frontend"]
    assert frontend_service.get("depends_on", {}).get("backend", {}).get("condition") == "service_healthy"

    # 4. Volumes persistence (must persist across down/up)
    assert "volumes" in compose_data
    volumes = compose_data["volumes"]
    assert "postgres_data" in volumes
    assert "backend_data" in volumes
    assert "backend_logs" in volumes


# =============================================================================
# 4. DATABASE INITIALIZATION SQL SCHEMA
# =============================================================================
def test_init_db_sql_schema():
    """Verify scripts/init_db.sql creates all relational tables, indexes, and extensions."""
    init_sql_path = PROJECT_ROOT / "scripts" / "init_db.sql"
    assert init_sql_path.exists(), "scripts/init_db.sql must exist"

    content = init_sql_path.read_text(encoding="utf-8")
    assert "CREATE EXTENSION IF NOT EXISTS" in content
    assert "CREATE TABLE IF NOT EXISTS users" in content
    assert "CREATE TABLE IF NOT EXISTS investigations" in content
    assert "CREATE TABLE IF NOT EXISTS investigation_events" in content
    assert "CREATE TABLE IF NOT EXISTS investigation_evidence" in content
    assert "CREATE TABLE IF NOT EXISTS investigation_findings" in content
    assert "CREATE TABLE IF NOT EXISTS review_decisions" in content
    assert "admin@reconagent.local" in content


# =============================================================================
# 5. ENVIRONMENT CONFIGURATION TEMPLATE
# =============================================================================
def test_env_example_template_completeness():
    """Verify .env.example contains all required environment variable definitions."""
    example_path = PROJECT_ROOT / ".env.example"
    assert example_path.exists(), ".env.example must exist"

    content = example_path.read_text(encoding="utf-8")
    expected_vars = [
        "GEMINI_API_KEY",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "DATABASE_URL",
        "SECRET_KEY",
        "ENVIRONMENT",
        "CORS_ORIGINS",
    ]
    for var in expected_vars:
        assert f"{var}=" in content, f"Missing variable in .env.example: {var}"


# =============================================================================
# 6. INTEGRATION WITH PHASE 11 HEALTH PROBES
# =============================================================================
def test_health_probes_for_container_lifecycle():
    """Verify /health (liveness) and /health/ready (readiness) respond as expected."""
    with TestClient(app) as client:
        # Liveness probe
        resp_live = client.get("/health")
        assert resp_live.status_code == 200
        assert resp_live.json()["status"] == "healthy"

        # Readiness probe
        resp_ready = client.get("/health/ready")
        assert resp_ready.status_code in (200, 503)
        assert "status" in resp_ready.json()
