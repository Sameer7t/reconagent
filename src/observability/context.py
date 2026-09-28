"""
Context Management for Request ID and Case ID Propagation.

Uses Python contextvars to ensure request_id and case_id are available
across async coroutines, threads, and downstream function calls
without modifying function signatures.
"""
import uuid
import contextvars
from contextlib import contextmanager
from typing import Optional

_request_id_ctx: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("request_id", default=None)
_case_id_ctx: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("case_id", default=None)


def generate_request_id() -> str:
    """Generates a unique request identifier for an incoming API call."""
    return f"req_{uuid.uuid4().hex[:12]}"


def get_request_id() -> Optional[str]:
    """Returns the current request_id from context, or None."""
    return _request_id_ctx.get()


def set_request_id(request_id: Optional[str]) -> contextvars.Token:
    """Sets the current request_id in context."""
    return _request_id_ctx.set(request_id)


def reset_request_id(token: contextvars.Token):
    """Resets request_id to its prior value."""
    _request_id_ctx.reset(token)


def get_case_id() -> Optional[str]:
    """Returns the current case_id from context, or None."""
    return _case_id_ctx.get()


def set_case_id(case_id: Optional[str]) -> contextvars.Token:
    """Sets the current case_id in context."""
    return _case_id_ctx.set(case_id)


def reset_case_id(token: contextvars.Token):
    """Resets case_id to its prior value."""
    _case_id_ctx.reset(token)


@contextmanager
def bind_context(request_id: Optional[str] = None, case_id: Optional[str] = None):
    """Context manager to temporarily bind request_id and/or case_id."""
    req_token = None
    case_token = None
    if request_id is not None:
        req_token = set_request_id(request_id)
    if case_id is not None:
        case_token = set_case_id(case_id)
    try:
        yield
    finally:
        if req_token is not None:
            reset_request_id(req_token)
        if case_token is not None:
            reset_case_id(case_token)
