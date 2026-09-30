# =============================================================================
# ReconAgent Backend Dockerfile (Python 3.12 Slim)
# Production Container for FastAPI, LangGraph Agent, and Multi-Way Reconciliation
# =============================================================================

FROM python:3.12-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src:/app \
    PORT=8000

# Install runtime system dependencies (curl for healthchecks, libpq for PostgreSQL)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq5 \
    bash \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python application dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source code and scripts
COPY src/ ./src/
COPY data/ ./data/
COPY scripts/ ./scripts/

# Ensure runtime directories exist and make entrypoint executable
RUN mkdir -p /app/data/uploads /app/logs && \
    chmod +x /app/scripts/docker-entrypoint.sh

# Expose backend REST API port
EXPOSE 8000

# Container healthcheck using liveness probe
HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

# Launch container via entrypoint
ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
