"""
Observability Package for ReconAgent.

Exports:
- context: Request ID and Case ID management via contextvars
- logging: Structured JSON logging with stage tracking and sensitive data masking
- metrics: Performance duration and operational metrics registry
- middleware: FastAPI RequestIdMiddleware
"""
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
    metrics_collector,
)
from observability.middleware import RequestIdMiddleware

__all__ = [
    "generate_request_id",
    "get_request_id",
    "set_request_id",
    "reset_request_id",
    "get_case_id",
    "set_case_id",
    "reset_case_id",
    "bind_context",
    "StructuredLogger",
    "get_structured_logger",
    "sanitize_sensitive_data",
    "SystemMetricsCollector",
    "get_metrics_collector",
    "metrics_collector",
    "RequestIdMiddleware",
]
