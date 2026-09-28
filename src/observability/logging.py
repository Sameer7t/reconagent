"""
Structured Logging Module for ReconAgent.

Provides structured, context-aware logging with automatic propagation of:
- timestamp
- level
- event
- case_id
- request_id
- stage
- duration_ms
- status

Ensures sensitive data (passwords, tokens, API keys, full document contents)
is strictly redacted and never leaked into log streams.
"""
import re
import json
import time
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Union
from contextlib import contextmanager
from pathlib import Path
from logging.handlers import RotatingFileHandler

from observability.context import get_request_id, get_case_id

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_LOG_DIR = PROJECT_ROOT / "logs"
DEFAULT_LOG_FILE = DEFAULT_LOG_DIR / "reconagent.jsonl"

# Common sensitive parameter names
SENSITIVE_KEY_SUBSTRINGS = (
    "password", "secret", "token", "api_key", "apikey",
    "auth", "authorization", "bearer", "private_key",
    "credit_card", "ssn", "client_secret"
)

# Document text keys that must not be emitted in full
DOCUMENT_CONTENT_KEYS = (
    "document_text", "full_document", "raw_text", "raw_content",
    "pdf_bytes", "file_bytes", "extracted_text", "page_text", "content"
)

# Regex patterns for detecting embedded secrets in strings
SECRET_PATTERNS = [
    re.compile(r"Bearer\s+[A-Za-z0-9\-\._~\+\/]+=*", re.IGNORECASE),
    re.compile(r"AIza[0-9A-Za-z\-_]{35}"),
    re.compile(r"ey[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),  # JWT pattern
]


def sanitize_sensitive_data(val: Any, max_doc_chars: int = 120) -> Any:
    """
    Recursively scrubs sensitive keys and truncates huge document payloads.
    Never logs passwords, tokens, API keys, or raw full documents.
    """
    if isinstance(val, dict):
        sanitized = {}
        for k, v in val.items():
            k_lower = str(k).lower()
            if any(sub in k_lower for sub in SENSITIVE_KEY_SUBSTRINGS):
                sanitized[k] = "[REDACTED]"
            elif any(doc_sub == k_lower or f"_{doc_sub}" in k_lower for doc_sub in DOCUMENT_CONTENT_KEYS):
                if isinstance(v, (str, bytes)):
                    sanitized[k] = f"[DOCUMENT_PAYLOAD ({len(v)} chars redacted)]"
                else:
                    sanitized[k] = sanitize_sensitive_data(v, max_doc_chars)
            else:
                sanitized[k] = sanitize_sensitive_data(v, max_doc_chars)
        return sanitized

    elif isinstance(val, list):
        return [sanitize_sensitive_data(item, max_doc_chars) for item in val]

    elif isinstance(val, tuple):
        return tuple(sanitize_sensitive_data(item, max_doc_chars) for item in val)

    elif isinstance(val, str):
        masked_val = val
        for pat in SECRET_PATTERNS:
            masked_val = pat.sub("[REDACTED_TOKEN]", masked_val)
        return masked_val

    elif isinstance(val, (bytes, bytearray)):
        return f"[BINARY_DATA ({len(val)} bytes)]"

    return val


class StructuredLogRecord:
    """Represents a structured log entry."""
    def __init__(
        self,
        timestamp: str,
        level: str,
        event: str,
        case_id: Optional[str] = None,
        request_id: Optional[str] = None,
        stage: Optional[str] = None,
        duration_ms: Optional[float] = None,
        status: Optional[str] = None,
        message: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ):
        self.timestamp = timestamp
        self.level = level.upper()
        self.event = event
        self.case_id = case_id
        self.request_id = request_id
        self.stage = stage
        self.duration_ms = round(duration_ms, 2) if duration_ms is not None else None
        self.status = status
        self.message = message
        self.extra = extra or {}

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "timestamp": self.timestamp,
            "level": self.level,
            "event": self.event,
            "case_id": self.case_id,
            "request_id": self.request_id,
            "stage": self.stage,
            "duration_ms": self.duration_ms,
            "status": self.status,
        }
        if self.message:
            data["message"] = self.message
        if self.extra:
            data.update(sanitize_sensitive_data(self.extra))
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


class StructuredLogger:
    """
    Structured Logger providing formatted and JSON log records
    with context propagation and sensitive data protection.
    """
    def __init__(
        self,
        name: str = "ReconAgent",
        json_output: bool = True,
        log_file: Optional[Union[str, Path]] = None,
        enable_file_logging: bool = True,
    ):
        self.name = name
        self.json_output = json_output
        self.raw_logger = logging.getLogger(name)
        self.raw_logger.setLevel(logging.DEBUG)
        self._in_memory_records: List[Dict[str, Any]] = []
        self._max_history = 1000

        self.log_file = Path(log_file) if log_file else DEFAULT_LOG_FILE
        self.enable_file_logging = enable_file_logging
        if self.enable_file_logging:
            self._setup_file_handler()

    def _setup_file_handler(self):
        """Attaches a RotatingFileHandler to write JSON lines to disk."""
        try:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            abs_target = str(self.log_file.resolve())
            for h in self.raw_logger.handlers:
                if isinstance(h, (logging.FileHandler, RotatingFileHandler)):
                    if getattr(h, "baseFilename", None) == abs_target:
                        return
            fh = RotatingFileHandler(
                str(self.log_file),
                maxBytes=10 * 1024 * 1024,  # 10 MB per file
                backupCount=5,
                encoding="utf-8",
            )
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(logging.Formatter("%(message)s"))
            self.raw_logger.addHandler(fh)
        except Exception:
            pass

    def log(
        self,
        level: str,
        event: str,
        message: Optional[str] = None,
        stage: Optional[str] = None,
        case_id: Optional[str] = None,
        request_id: Optional[str] = None,
        duration_ms: Optional[float] = None,
        status: Optional[str] = None,
        **extra,
    ) -> Dict[str, Any]:
        """
        Emits a structured log record. Automatically infers request_id and case_id
        from contextvars if not explicitly passed.
        """
        req_id = request_id or get_request_id()
        c_id = case_id or get_case_id()
        ts = datetime.now(timezone.utc).isoformat()

        record = StructuredLogRecord(
            timestamp=ts,
            level=level,
            event=event,
            case_id=c_id,
            request_id=req_id,
            stage=stage,
            duration_ms=duration_ms,
            status=status,
            message=message,
            extra=extra,
        )
        data = record.to_dict()

        # Keep limited in-memory history for metrics/audit/testing
        self._in_memory_records.append(data)
        if len(self._in_memory_records) > self._max_history:
            self._in_memory_records.pop(0)

        # Emit to standard logging
        log_method = getattr(self.raw_logger, level.lower(), self.raw_logger.info)
        if self.json_output:
            log_method(record.to_json())
        else:
            meta = [f"event={event}"]
            if req_id:
                meta.append(f"req={req_id}")
            if c_id:
                meta.append(f"case={c_id}")
            if stage:
                meta.append(f"stage={stage}")
            if status:
                meta.append(f"status={status}")
            if duration_ms is not None:
                meta.append(f"{duration_ms:.1f}ms")
            log_method(f"[{' | '.join(meta)}] {message or ''}")

        # Flush file handlers
        for h in self.raw_logger.handlers:
            if hasattr(h, "flush"):
                try:
                    h.flush()
                except Exception:
                    pass

        return data

    def info(self, event: str, message: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        return self.log("INFO", event, message=message, **kwargs)

    def warning(self, event: str, message: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        return self.log("WARNING", event, message=message, **kwargs)

    def error(self, event: str, message: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        return self.log("ERROR", event, message=message, **kwargs)

    def debug(self, event: str, message: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        return self.log("DEBUG", event, message=message, **kwargs)

    @contextmanager
    def stage_timer(
        self,
        stage: str,
        event: Optional[str] = None,
        case_id: Optional[str] = None,
        request_id: Optional[str] = None,
        **extra,
    ):
        """
        Context manager for timing pipeline stages and logging start/end events.
        Logs:
        - stage start (status="STARTED")
        - stage finish (status="SUCCESS", with duration_ms)
        - stage failure (status="ERROR", with duration_ms and error message)
        """
        event_name = event or stage.replace(" ", "_")
        start_time = time.perf_counter()
        c_id = case_id or get_case_id()
        r_id = request_id or get_request_id()

        self.info(
            event=f"{event_name}_started",
            stage=stage,
            case_id=c_id,
            request_id=r_id,
            status="STARTED",
            **extra,
        )

        stage_ctx: Dict[str, Any] = {}
        try:
            yield stage_ctx
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            status_val = stage_ctx.get("status", "SUCCESS")
            extra_merged = {**extra, **{k: v for k, v in stage_ctx.items() if k != "status"}}
            self.info(
                event=f"{event_name}_completed",
                stage=stage,
                case_id=c_id,
                request_id=r_id,
                duration_ms=duration_ms,
                status=status_val,
                **extra_merged,
            )
        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            self.error(
                event=f"{event_name}_failed",
                stage=stage,
                case_id=c_id,
                request_id=r_id,
                duration_ms=duration_ms,
                status="ERROR",
                error=str(exc),
                **extra,
            )
            raise

    def get_records(self) -> List[Dict[str, Any]]:
        return list(self._in_memory_records)

    def clear_records(self):
        self._in_memory_records.clear()


# Default global structured logger singleton
_structured_logger: Optional[StructuredLogger] = None


def get_structured_logger() -> StructuredLogger:
    global _structured_logger
    if _structured_logger is None:
        _structured_logger = StructuredLogger(name="ReconAgent")
    return _structured_logger
