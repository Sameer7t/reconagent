"""
Unit and Integration Tests for ReconAgent Observability Layer.

Covers:
1. Request ID generation, contextvar binding, and propagation
2. Structured logging schema, required fields, and major stages
3. Sensitive data and document payload redaction
4. Stage timing context manager (success and error paths)
5. Liveness probe (GET /health and GET /api/health)
6. Readiness probe (GET /health/ready and GET /api/health/ready)
7. Metrics endpoint (GET /metrics and GET /api/metrics)
8. Request ID middleware (header propagation and latency tracking)
9. Performance and agent operational metrics tracking
10. Gemini router fallback metrics instrumentation
"""
import sys
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient

from api.main import app
from observability.context import (
    generate_request_id,
    get_request_id,
    set_request_id,
    reset_request_id,
    get_case_id,
    set_case_id,
    reset_case_id,
    bind_context,
)
from observability.logging import (
    StructuredLogger,
    get_structured_logger,
    sanitize_sensitive_data,
)
from observability.metrics import (
    SystemMetricsCollector,
    get_metrics_collector,
)
from agent.router import GeminiModelRouter


@pytest.fixture(scope="module")
def client():
    """Test client with admin authentication override."""
    from api.routes.auth import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "test-admin-id",
        "email": "admin@reconagent.local",
        "role": "Admin",
        "is_active": True,
    }
    with TestClient(app) as tc:
        yield tc
    app.dependency_overrides.clear()


# =============================================================================
# 1. REQUEST ID AND CONTEXTVAR TESTS
# =============================================================================
def test_request_id_generation():
    """Verify unique request IDs are generated with correct prefix and uniqueness."""
    req_id1 = generate_request_id()
    req_id2 = generate_request_id()
    assert req_id1.startswith("req_")
    assert req_id2.startswith("req_")
    assert req_id1 != req_id2


def test_request_id_and_case_id_context_binding():
    """Verify request_id and case_id are properly bound and isolated in contextvars."""
    assert get_request_id() is None
    assert get_case_id() is None

    token_req = set_request_id("req_test_123")
    token_case = set_case_id("CASE-999")
    assert get_request_id() == "req_test_123"
    assert get_case_id() == "CASE-999"

    reset_request_id(token_req)
    reset_case_id(token_case)
    assert get_request_id() is None
    assert get_case_id() is None


def test_bind_context_manager():
    """Verify bind_context properly binds and restores prior values."""
    assert get_request_id() is None
    assert get_case_id() is None

    with bind_context(request_id="req_scoped", case_id="CASE-SCOPED"):
        assert get_request_id() == "req_scoped"
        assert get_case_id() == "CASE-SCOPED"

    assert get_request_id() is None
    assert get_case_id() is None


# =============================================================================
# 2. SENSITIVE DATA REDACTION TESTS
# =============================================================================
def test_sensitive_data_scrubbing():
    """Never log passwords, API keys, tokens, or private secrets."""
    payload = {
        "user_email": "specialist@reconagent.local",
        "password": "SuperSecretPassword123!",
        "api_key": "AIzaSyD-fakeKeyXYZ123456789012345678",
        "auth_token": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.t-IDc",
        "nested": {
            "client_secret": "my-client-secret",
            "safe_param": "regular_value",
            "private_key": "-----BEGIN PRIVATE KEY-----",
        },
        "list_items": [
            {"access_token": "secret_token_val", "public_id": "P-100"}
        ]
    }
    sanitized = sanitize_sensitive_data(payload)

    assert sanitized["password"] == "[REDACTED]"
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["auth_token"] == "[REDACTED]"
    assert sanitized["nested"]["client_secret"] == "[REDACTED]"
    assert sanitized["nested"]["private_key"] == "[REDACTED]"
    assert sanitized["nested"]["safe_param"] == "regular_value"
    assert sanitized["list_items"][0]["access_token"] == "[REDACTED]"
    assert sanitized["list_items"][0]["public_id"] == "P-100"


def test_document_body_payload_redaction():
    """Huge raw text bodies or full documents are truncated or redacted from logs."""
    huge_text = "LINE ITEM DETAILS AND TEXT CONTENT " * 50
    payload = {
        "file_name": "INV-3001.pdf",
        "document_text": huge_text,
        "full_document": huge_text,
        "raw_content": huge_text,
        "page_count": 2,
    }
    sanitized = sanitize_sensitive_data(payload)

    assert sanitized["file_name"] == "INV-3001.pdf"
    assert sanitized["page_count"] == 2
    assert "[DOCUMENT_PAYLOAD" in sanitized["document_text"]
    assert len(sanitized["document_text"]) < len(huge_text)
    assert "[DOCUMENT_PAYLOAD" in sanitized["full_document"]


# =============================================================================
# 3. STRUCTURED LOGGING SCHEMA AND MAJOR STAGES TESTS
# =============================================================================
def test_structured_log_record_fields():
    """Verify log records include timestamp, level, event, case_id, request_id, stage, duration_ms, status."""
    logger = StructuredLogger(name="TestLogger", json_output=False)
    logger.clear_records()

    with bind_context(request_id="req_log_abc", case_id="CASE-LOG-123"):
        record = logger.info(
            event="sample_event",
            stage="classification",
            duration_ms=42.56,
            status="SUCCESS",
            extra_field="test_value",
        )

    assert record["event"] == "sample_event"
    assert record["level"] == "INFO"
    assert record["stage"] == "classification"
    assert record["case_id"] == "CASE-LOG-123"
    assert record["request_id"] == "req_log_abc"
    assert record["duration_ms"] == 42.56
    assert record["status"] == "SUCCESS"
    assert "timestamp" in record
    assert record["extra_field"] == "test_value"


def test_major_stages_logging():
    """Verify all major stages can be logged with standard stage names."""
    logger = StructuredLogger(name="TestStagesLogger", json_output=False)
    logger.clear_records()

    major_stages = [
        "classification",
        "extraction",
        "validation",
        "reconciliation",
        "agent investigation",
        "database persistence",
        "review queue",
    ]

    for stage in major_stages:
        logger.info(
            event=f"{stage.replace(' ', '_')}_verified",
            stage=stage,
            case_id="CASE-ALL-STAGES",
            status="SUCCESS",
        )

    records = logger.get_records()
    stages_recorded = [r["stage"] for r in records]
    for s in major_stages:
        assert s in stages_recorded


# =============================================================================
# 4. STAGE TIMING TESTS
# =============================================================================
def test_stage_timer_success_path():
    """Verify stage_timer measures duration and emits started/completed events."""
    logger = StructuredLogger(name="TimerLogger", json_output=False)
    logger.clear_records()

    with logger.stage_timer("reconciliation", case_id="CASE-TIME-001") as ctx:
        time.sleep(0.02)  # 20ms
        ctx["discrepancy_count"] = 3

    records = logger.get_records()
    assert len(records) == 2
    started = records[0]
    completed = records[1]

    assert started["event"] == "reconciliation_started"
    assert started["status"] == "STARTED"
    assert started["stage"] == "reconciliation"
    assert started["case_id"] == "CASE-TIME-001"

    assert completed["event"] == "reconciliation_completed"
    assert completed["status"] == "SUCCESS"
    assert completed["stage"] == "reconciliation"
    assert completed["case_id"] == "CASE-TIME-001"
    assert completed["duration_ms"] >= 15.0
    assert completed["discrepancy_count"] == 3


def test_stage_timer_error_path():
    """Verify stage_timer records error and duration when exception occurs."""
    logger = StructuredLogger(name="TimerErrorLogger", json_output=False)
    logger.clear_records()

    with pytest.raises(ValueError, match="Simulated validation error"):
        with logger.stage_timer("validation", case_id="CASE-ERR-001"):
            time.sleep(0.01)
            raise ValueError("Simulated validation error")

    records = logger.get_records()
    assert len(records) == 2
    failed = records[1]
    assert failed["event"] == "validation_failed"
    assert failed["status"] == "ERROR"
    assert failed["duration_ms"] >= 8.0
    assert "Simulated validation error" in failed["error"]


# =============================================================================
# 5. HEALTH AND READINESS ENDPOINT TESTS
# =============================================================================
def test_health_liveness_endpoint(client):
    """GET /health confirms application is running without executing expensive queries."""
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert "version" in data
    assert "timestamp" in data

    # Test alias /api/health
    res_api = client.get("/api/health")
    assert res_api.status_code == 200
    assert res_api.json()["status"] == "healthy"


def test_health_readiness_endpoint_success(client):
    """GET /health/ready checks database connection and reports ready when DB is up."""
    res = client.get("/health/ready")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ready"
    assert data["dependencies"]["database"]["connected"] is True
    assert data["dependencies"]["database"]["status"] == "up"

    # Test alias /api/health/ready
    res_api = client.get("/api/health/ready")
    assert res_api.status_code == 200
    assert res_api.json()["status"] == "ready"


def test_health_readiness_endpoint_failure(client):
    """GET /health/ready returns 503 Service Unavailable if database is unreachable."""
    with patch("api.main.get_db") as mock_get_db:
        mock_db = MagicMock()
        mock_db._get_connection.side_effect = Exception("Database connection refused: port 5432")
        mock_get_db.return_value = mock_db

        res = client.get("/health/ready")
        assert res.status_code == 503
        data = res.json()
        assert data["status"] == "not_ready"
        assert data["dependencies"]["database"]["connected"] is False
        assert "Database connection refused" in data["dependencies"]["database"]["error"]


# =============================================================================
# 6. METRICS ENDPOINT TESTS
# =============================================================================
def test_metrics_endpoint(client):
    """GET /metrics exposes durations, operations, and Gemini router metrics."""
    res = client.get("/metrics")
    assert res.status_code == 200
    data = res.json()

    assert "durations" in data
    assert "total_request_duration" in data["durations"]
    assert "reconciliation_duration" in data["durations"]
    assert "agent_duration" in data["durations"]
    assert "database_duration" in data["durations"]

    assert "operations" in data
    assert "number_of_investigations" in data["operations"]
    assert "number_of_agent_tool_calls" in data["operations"]
    assert "human_review_count" in data["operations"]
    assert "agent_failures" in data["operations"]
    assert "model_fallback_count" in data["operations"]
    assert "recommendation_counts" in data["operations"]

    assert "gemini_router" in data
    assert "model_attempts" in data["gemini_router"]
    assert "successful_model" in data["gemini_router"]
    assert "fallback_count" in data["gemini_router"]
    assert "quota_fallbacks_429" in data["gemini_router"]
    assert "retries_503" in data["gemini_router"]
    assert "timeouts" in data["gemini_router"]

    # Test alias /api/metrics
    res_api = client.get("/api/metrics")
    assert res_api.status_code == 200
    assert "durations" in res_api.json()


# =============================================================================
# 7. REQUEST ID MIDDLEWARE TESTS
# =============================================================================
def test_request_id_middleware_auto_generation(client):
    """Requests without X-Request-ID receive a generated request ID in response header."""
    res = client.get("/health")
    assert res.status_code == 200
    assert "X-Request-ID" in res.headers
    req_id = res.headers["X-Request-ID"]
    assert req_id.startswith("req_")


def test_request_id_middleware_header_preservation(client):
    """Requests with incoming X-Request-ID preserve and return the exact ID."""
    custom_id = "client-trace-uuid-999"
    res = client.get("/health", headers={"X-Request-ID": custom_id})
    assert res.status_code == 200
    assert res.headers["X-Request-ID"] == custom_id


# =============================================================================
# 8. PERFORMANCE AND OPERATIONAL METRICS COLLECTOR TESTS
# =============================================================================
def test_system_metrics_collector():
    """Verify performance metrics collection and summary statistics."""
    collector = SystemMetricsCollector()
    collector.reset()

    # Record durations
    collector.record_request_duration(100.0)
    collector.record_request_duration(200.0)
    collector.record_reconciliation_duration(50.0)
    collector.record_agent_duration(350.0)
    collector.record_database_duration(15.0)

    # Record operations
    collector.record_investigation()
    collector.record_tool_call("get_purchase_order")
    collector.record_tool_call("get_purchase_order")
    collector.record_tool_call("get_invoice")
    collector.record_human_review()
    collector.record_agent_failure()
    collector.record_recommendation("APPROVE_PAYMENT")
    collector.record_recommendation("REJECT_INVOICE")

    metrics = collector.get_metrics()

    # Verify Durations
    req_dur = metrics["durations"]["total_request_duration"]
    assert req_dur["count"] == 2
    assert req_dur["avg_ms"] == 150.0
    assert req_dur["min_ms"] == 100.0
    assert req_dur["max_ms"] == 200.0

    assert metrics["durations"]["reconciliation_duration"]["count"] == 1
    assert metrics["durations"]["agent_duration"]["count"] == 1
    assert metrics["durations"]["database_duration"]["count"] == 1

    # Verify Operations
    ops = metrics["operations"]
    assert ops["number_of_investigations"] == 1
    assert ops["number_of_agent_tool_calls"] == 3
    assert ops["agent_tool_calls_by_tool"]["get_purchase_order"] == 2
    assert ops["agent_tool_calls_by_tool"]["get_invoice"] == 1
    assert ops["human_review_count"] == 1
    assert ops["agent_failures"] == 1
    assert ops["recommendation_counts"]["APPROVE_PAYMENT"] == 1
    assert ops["recommendation_counts"]["REJECT_INVOICE"] == 1


# =============================================================================
# 9. GEMINI ROUTER METRICS INSTRUMENTATION TESTS
# =============================================================================
def test_gemini_router_metrics_recording():
    """Verify Gemini router metrics tracking for attempts, quota 429 fallbacks, and success."""
    collector = get_metrics_collector()
    collector.reset()

    router = GeminiModelRouter(model_cascade=["gemini-3.8-flash", "gemini-3.7-flash"])

    # Simulate client that throws 429 on first model, then succeeds on second
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = '{"action": "finish", "reason": "Authorized", "tool": null, "arguments": {}}'

    def side_effect(model, contents, config):
        if model == "gemini-3.8-flash":
            raise Exception("429 ResourceExhausted: rate limit exceeded")
        return mock_response

    mock_client.models.generate_content.side_effect = side_effect

    state = {
        "case_id": "CASE-ROUTER-TEST",
        "discrepancies": [],
        "tool_calls": [],
        "evidence": [],
    }

    action = router.route_generation(state, client=mock_client)
    assert action is not None
    assert action.action == "finish"

    metrics = collector.get_metrics()["gemini_router"]
    # Tier 1 was attempted, failed with 429 quota, cascaded to Tier 2 which succeeded
    assert metrics["model_attempts"]["gemini-3.8-flash"] >= 1
    assert metrics["model_attempts"]["gemini-3.7-flash"] >= 1
    assert metrics["quota_fallbacks_429"] >= 1
    assert metrics["fallback_count"] >= 1
    assert metrics["successful_model"]["gemini-3.7-flash"] == 1


# =============================================================================
# 11. PERSISTENT FILE LOGGING AND /LOGS ENDPOINT TESTS
# =============================================================================
def test_persistent_file_logging(tmp_path):
    """Verify structured logs are persistently appended to disk in JSONL format."""
    log_file = tmp_path / "test_reconagent.jsonl"
    logger = StructuredLogger(name="TestFileLogger", json_output=True, log_file=log_file, enable_file_logging=True)

    logger.info(
        event="test_file_persistence",
        stage="database persistence",
        case_id="CASE-FILE-001",
        status="SUCCESS",
        duration_ms=12.34,
    )

    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8").strip()
    assert "test_file_persistence" in content
    assert "CASE-FILE-001" in content

    import json
    parsed = json.loads(content.splitlines()[-1])
    assert parsed["event"] == "test_file_persistence"
    assert parsed["stage"] == "database persistence"
    assert parsed["case_id"] == "CASE-FILE-001"
    assert parsed["duration_ms"] == 12.34


def test_logs_endpoints(client):
    """Verify GET /logs and GET /api/logs return structured log history."""
    # Emit an event to ensure at least one log is present
    s_logger = get_structured_logger()
    s_logger.info(
        event="endpoint_log_test",
        stage="reconciliation",
        case_id="CASE-LOG-ENDPOINT",
        status="SUCCESS",
    )

    resp1 = client.get("/logs")
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["status"] == "success"
    assert "total_records" in data1
    assert "log_file" in data1
    assert any(entry.get("case_id") == "CASE-LOG-ENDPOINT" for entry in data1["logs"])

    # Test filtering by case_id
    resp2 = client.get("/api/logs?case_id=CASE-LOG-ENDPOINT")
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert len(data2["logs"]) >= 1
    assert all(entry["case_id"] == "CASE-LOG-ENDPOINT" for entry in data2["logs"])


def test_logs_endpoint_rbac_restrictions():
    """Verify logs endpoint is strictly accessible to Admin role only."""
    from api.routes.auth import get_current_user

    # 1. Non-admin user (Reviewer role) should get 403 Forbidden
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "reviewer-user-id",
        "email": "reviewer@reconagent.local",
        "role": "Reviewer",
        "is_active": True,
    }
    with TestClient(app) as reviewer_client:
        resp = reviewer_client.get("/logs")
        assert resp.status_code == 403
        assert resp.json()["detail"] == "Not enough permissions"

        resp_api = reviewer_client.get("/api/logs")
        assert resp_api.status_code == 403

    # 2. Non-admin user (Viewer role) should get 403 Forbidden
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "viewer-user-id",
        "email": "viewer@reconagent.local",
        "role": "Viewer",
        "is_active": True,
    }
    with TestClient(app) as viewer_client:
        resp = viewer_client.get("/logs")
        assert resp.status_code == 403

    # 3. Unauthenticated request (no token override) should get 401 Unauthorized
    app.dependency_overrides.clear()
    with TestClient(app) as unauth_client:
        resp = unauth_client.get("/logs")
        assert resp.status_code == 401


