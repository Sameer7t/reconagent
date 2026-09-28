"""
Performance and Operational Metrics Collector for ReconAgent.

Tracks:
1. Performance Durations:
   - Total request duration
   - Reconciliation duration
   - Agent duration
   - Database duration
2. Application Counters:
   - Number of investigations
   - Number of agent tool calls (overall and per tool)
   - Human-review count
   - Agent failures
   - Model fallback count
   - Recommendation counts (by action)
3. Gemini Router Metrics:
   - Model attempts (by model)
   - Successful model (by model)
   - Fallback count
   - 429/quota fallbacks
   - 503 retries
   - Timeouts
"""
import time
import threading
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from contextlib import contextmanager


@dataclass
class DurationMetric:
    count: int = 0
    total_ms: float = 0.0
    min_ms: float = float("inf")
    max_ms: float = 0.0
    recent_samples: List[float] = field(default_factory=list)

    def record(self, duration_ms: float):
        self.count += 1
        self.total_ms += duration_ms
        if duration_ms < self.min_ms:
            self.min_ms = duration_ms
        if duration_ms > self.max_ms:
            self.max_ms = duration_ms
        self.recent_samples.append(duration_ms)
        if len(self.recent_samples) > 200:
            self.recent_samples.pop(0)

    @property
    def avg_ms(self) -> float:
        return (self.total_ms / self.count) if self.count > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "count": self.count,
            "total_ms": round(self.total_ms, 2),
            "avg_ms": round(self.avg_ms, 2),
            "min_ms": round(self.min_ms, 2) if self.count > 0 else 0.0,
            "max_ms": round(self.max_ms, 2),
        }

    def reset(self):
        self.count = 0
        self.total_ms = 0.0
        self.min_ms = float("inf")
        self.max_ms = 0.0
        self.recent_samples.clear()


class SystemMetricsCollector:
    """Thread-safe singleton metrics registry."""
    def __init__(self):
        self._lock = threading.Lock()
        # Durations
        self._request_duration = DurationMetric()
        self._reconciliation_duration = DurationMetric()
        self._agent_duration = DurationMetric()
        self._database_duration = DurationMetric()

        # Operational counters
        self._investigations_count: int = 0
        self._agent_tool_calls_total: int = 0
        self._tool_calls_by_name: Dict[str, int] = {}
        self._human_review_count: int = 0
        self._agent_failures_count: int = 0
        self._model_fallback_count: int = 0
        self._recommendations_by_type: Dict[str, int] = {}

        # Gemini Router metrics
        self._router_model_attempts: Dict[str, int] = {}
        self._router_successful_model: Dict[str, int] = {}
        self._router_fallbacks: int = 0
        self._router_quota_fallbacks_429: int = 0
        self._router_retries_503: int = 0
        self._router_timeouts: int = 0

    # --- Duration Recorders ---
    def record_request_duration(self, duration_ms: float):
        with self._lock:
            self._request_duration.record(duration_ms)

    def record_reconciliation_duration(self, duration_ms: float):
        with self._lock:
            self._reconciliation_duration.record(duration_ms)

    def record_agent_duration(self, duration_ms: float):
        with self._lock:
            self._agent_duration.record(duration_ms)

    def record_database_duration(self, duration_ms: float):
        with self._lock:
            self._database_duration.record(duration_ms)

    @contextmanager
    def measure_stage(self, stage: str):
        start = time.perf_counter()
        try:
            yield
        finally:
            dur = (time.perf_counter() - start) * 1000.0
            if stage in ("request", "api_request"):
                self.record_request_duration(dur)
            elif stage in ("reconciliation", "recon"):
                self.record_reconciliation_duration(dur)
            elif stage in ("agent", "agent investigation"):
                self.record_agent_duration(dur)
            elif stage in ("database", "database persistence", "db"):
                self.record_database_duration(dur)

    # --- Application Counters ---
    def record_investigation(self, count: int = 1):
        with self._lock:
            self._investigations_count += count

    def record_tool_call(self, tool_name: str):
        with self._lock:
            self._agent_tool_calls_total += 1
            self._tool_calls_by_name[tool_name] = self._tool_calls_by_name.get(tool_name, 0) + 1

    def record_human_review(self, count: int = 1):
        with self._lock:
            self._human_review_count += count

    def record_agent_failure(self, count: int = 1):
        with self._lock:
            self._agent_failures_count += count

    def record_model_fallback(self, count: int = 1):
        with self._lock:
            self._model_fallback_count += count

    def record_recommendation(self, recommendation: str):
        with self._lock:
            rec_key = str(recommendation).strip().upper()
            self._recommendations_by_type[rec_key] = self._recommendations_by_type.get(rec_key, 0) + 1

    # --- Gemini Router Metrics ---
    def record_router_attempt(self, model_name: str):
        with self._lock:
            self._router_model_attempts[model_name] = self._router_model_attempts.get(model_name, 0) + 1

    def record_router_success(self, model_name: str):
        with self._lock:
            self._router_successful_model[model_name] = self._router_successful_model.get(model_name, 0) + 1

    def record_router_fallback(self, count: int = 1):
        with self._lock:
            self._router_fallbacks += count
            self._model_fallback_count += count

    def record_router_quota_429(self, count: int = 1):
        with self._lock:
            self._router_quota_fallbacks_429 += count

    def record_router_retry_503(self, count: int = 1):
        with self._lock:
            self._router_retries_503 += count

    def record_router_timeout(self, count: int = 1):
        with self._lock:
            self._router_timeouts += count

    # --- Expose Metrics ---
    def get_metrics(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "durations": {
                    "total_request_duration": self._request_duration.to_dict(),
                    "reconciliation_duration": self._reconciliation_duration.to_dict(),
                    "agent_duration": self._agent_duration.to_dict(),
                    "database_duration": self._database_duration.to_dict(),
                },
                "operations": {
                    "number_of_investigations": self._investigations_count,
                    "number_of_agent_tool_calls": self._agent_tool_calls_total,
                    "agent_tool_calls_by_tool": dict(self._tool_calls_by_name),
                    "human_review_count": self._human_review_count,
                    "agent_failures": self._agent_failures_count,
                    "model_fallback_count": self._model_fallback_count,
                    "recommendation_counts": dict(self._recommendations_by_type),
                },
                "gemini_router": {
                    "model_attempts": dict(self._router_model_attempts),
                    "successful_model": dict(self._router_successful_model),
                    "fallback_count": self._router_fallbacks,
                    "quota_fallbacks_429": self._router_quota_fallbacks_429,
                    "retries_503": self._router_retries_503,
                    "timeouts": self._router_timeouts,
                },
            }

    def reset(self):
        with self._lock:
            self._request_duration.reset()
            self._reconciliation_duration.reset()
            self._agent_duration.reset()
            self._database_duration.reset()

            self._investigations_count = 0
            self._agent_tool_calls_total = 0
            self._tool_calls_by_name.clear()
            self._human_review_count = 0
            self._agent_failures_count = 0
            self._model_fallback_count = 0
            self._recommendations_by_type.clear()

            self._router_model_attempts.clear()
            self._router_successful_model.clear()
            self._router_fallbacks = 0
            self._router_quota_fallbacks_429 = 0
            self._router_retries_503 = 0
            self._router_timeouts = 0


# Global metrics registry singleton
metrics_collector = SystemMetricsCollector()


def get_metrics_collector() -> SystemMetricsCollector:
    return metrics_collector
