"""
AI Investigation Agent Model Router Layer.

Step 8: Isolates the agent loop from provider model availability by placing
the 9-tier Gemini priority cascade underneath a unified router interface:

                    Agent State Machine
                             │
                             ▼
                     GeminiModelRouter
                             │
        ┌────────────────────┼────────────────────┐
        ▼                    ▼                    ▼
     Tier 1               Tier 2               Tier 3...
 (3.8 Flash)          (3.7 Flash)          (3.6 Flash)
        │                    │                    │
        └────────────────────┼────────────────────┘
                             ▼
                 Structured AgentAction

Governance Rules:
1. Temporary Spikes (503 UNAVAILABLE, high demand, server busy, timeout):
   DO NOT change the model. Apply exponential backoff and retry on the SAME model.
2. Quota Limits (429 RESOURCE_EXHAUSTED, rate limit, quota exceeded, 404 deprecated):
   Strictly cascade to the next model in the 9-tier priority order.
"""
import time
import json
import logging
import concurrent.futures
from typing import Dict, Any, Optional, List, TypeVar, Type

from pydantic import BaseModel

from agent.state import InvestigationState
from agent.models import AgentAction
from agent.prompts import INVESTIGATION_SYSTEM_PROMPT, build_analysis_user_prompt
from agent.policies import get_allowed_tools_for_discrepancies

T = TypeVar("T", bound=BaseModel)

logger = logging.getLogger("GeminiModelRouter")

# 9-Tier Model Cascade in strict user-specified priority order
DEFAULT_MODEL_CASCADE: List[str] = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3-flash",
    "gemini-2.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash-lite",
]

MAX_SPIKE_RETRIES = 4
BASE_SPIKE_DELAY = 1.0
REQUEST_TIMEOUT_SECONDS = 15.0


def is_quota_limit_error(exc: Exception) -> bool:
    """
    Identifies quota exhaustion, rate limit caps, or model unavailability
    that explicitly requires cascading to the next tier in priority order.
    """
    msg = str(exc).lower()
    return any(k in msg for k in [
        "429", "resource_exhausted", "quota", "rate limit",
        "404", "not_found", "no longer available"
    ])


def is_temporary_spike_error(exc: Exception) -> bool:
    """
    Identifies transient demand spikes, socket timeouts, or temporary server congestion
    where the model should NOT be changed and exponential backoff should be used.
    """
    if isinstance(exc, (TimeoutError, concurrent.futures.TimeoutError)):
        return True
    msg = str(exc).lower()
    return any(k in msg for k in [
        "503", "unavailable", "high demand", "spikes in demand",
        "502", "bad gateway", "504", "gateway timeout", "timeout", "timed out"
    ])


class GeminiModelRouter:
    """
    Production-grade Model Router.
    Enforces exponential backoff on the SAME model during temporary demand spikes,
    and only cascades across the 9-tier priority order upon encountering quota limits.
    """
    def __init__(self, model_cascade: Optional[List[str]] = None):
        self.cascade = list(model_cascade) if model_cascade is not None else list(DEFAULT_MODEL_CASCADE)

    def route_generation(
        self,
        state: InvestigationState,
        client: Optional[Any] = None,
        preferred_model: Optional[str] = None,
    ) -> Optional[AgentAction]:
        """
        Attempts structured JSON generation across the cascade tiers.
        - On temporary demand spike: Exponential backoff on the SAME model.
        - On quota limit: Strictly cascades to the next tier in priority order.
        """
        if client is None:
            return None

        discrepancies = state.get("discrepancies", [])
        user_prompt = build_analysis_user_prompt(state)

        # Build tier candidate sequence starting with preferred model if specified
        candidates: List[str] = []
        if preferred_model:
            candidates.append(preferred_model)
        for m in self.cascade:
            if m not in candidates:
                candidates.append(m)

        for candidate_model in candidates:
            spike_attempt = 0
            while spike_attempt <= MAX_SPIKE_RETRIES:
                try:
                    logger.info(
                        f"[Router] Invoking model tier '{candidate_model}' (Attempt {spike_attempt+1}/{MAX_SPIKE_RETRIES+1})..."
                    )
                    def _call_gemini():
                        return client.models.generate_content(
                            model=candidate_model,
                            contents=[
                                {"role": "user", "parts": [{"text": INVESTIGATION_SYSTEM_PROMPT + "\n\n" + user_prompt}]}
                            ],
                            config={"response_mime_type": "application/json"}
                        )

                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                        future = executor.submit(_call_gemini)
                        response = future.result(timeout=REQUEST_TIMEOUT_SECONDS)

                    raw_data = json.loads(response.text)
                    action_obj = AgentAction(**raw_data)

                    # Validate tool choice against investigation policy
                    if action_obj.action == "investigate" and action_obj.tool:
                        allowed = get_allowed_tools_for_discrepancies(discrepancies)
                        if action_obj.tool not in allowed:
                            logger.warning(
                                f"[Router] Model '{candidate_model}' chose tool '{action_obj.tool}' outside policy {allowed}."
                            )
                            break
                    return action_obj

                except Exception as exc:
                    if is_quota_limit_error(exc):
                        # Quota limit: strictly cascade to next model in 9-tier priority order
                        logger.warning(
                            f"[Router] Quota limit encountered on tier '{candidate_model}' ({exc}). "
                            f"Cascading to next tier in 9-tier priority order..."
                        )
                        break  # Break out of this model's loop to cascade to next candidate

                    elif is_temporary_spike_error(exc):
                        # Temporary spike: DO NOT change model. Use exponential backoff on SAME model.
                        spike_attempt += 1
                        if spike_attempt <= MAX_SPIKE_RETRIES:
                            delay = BASE_SPIKE_DELAY * (2 ** (spike_attempt - 1))
                            logger.info(
                                f"[Router] Temporary demand spike on tier '{candidate_model}' ({exc}). "
                                f"Retrying on SAME model with exponential backoff in {delay:.1f}s (Attempt {spike_attempt}/{MAX_SPIKE_RETRIES})..."
                            )
                            time.sleep(delay)
                            continue
                        else:
                            logger.warning(
                                f"[Router] Tier '{candidate_model}' remained unavailable after {MAX_SPIKE_RETRIES} backoff retries. "
                                f"Cascading to next tier in priority order..."
                            )
                            break

                    else:
                        # Unexpected error: quick retry with backoff, then cascade if persistent
                        spike_attempt += 1
                        if spike_attempt <= 2:
                            delay = BASE_SPIKE_DELAY * (2 ** (spike_attempt - 1))
                            logger.warning(
                                f"[Router] Error on '{candidate_model}': {exc}. Retrying on same tier in {delay:.1f}s..."
                            )
                            time.sleep(delay)
                            continue
                        else:
                            logger.warning(
                                f"[Router] Tier '{candidate_model}' error persisted. Cascading to next tier..."
                            )
                            break

        logger.warning("[Router] All cascade tiers exhausted or unavailable. Triggering deterministic fallback.")
        return None

    def route_structured_extraction(
        self,
        client: Any,
        contents: list,
        response_schema: Type[T],
        preferred_model: Optional[str] = None,
        temperature: float = 0.0,
        request_timeout_seconds: Optional[float] = None,
    ) -> Optional[T]:
        """
        Attempts structured JSON extraction against response_schema across the 9-tier cascade.
        - On temporary demand spike (503, timeout, server busy): Exponential backoff on the SAME model.
        - On quota limit (429, resource exhausted, 404): Strictly cascades to the next tier in 9-tier priority order.
        """
        if client is None:
            return None

        timeout = request_timeout_seconds or REQUEST_TIMEOUT_SECONDS

        # Build tier candidate sequence starting with preferred model if specified
        candidates: List[str] = []
        if preferred_model:
            candidates.append(preferred_model)
        for m in self.cascade:
            if m not in candidates:
                candidates.append(m)

        for candidate_model in candidates:
            spike_attempt = 0
            while spike_attempt <= MAX_SPIKE_RETRIES:
                try:
                    logger.info(
                        f"[Router] Invoking extraction on tier '{candidate_model}' (Attempt {spike_attempt+1}/{MAX_SPIKE_RETRIES+1})..."
                    )
                    def _call_gemini():
                        return client.models.generate_content(
                            model=candidate_model,
                            contents=contents,
                            config={
                                "response_mime_type": "application/json",
                                "response_schema": response_schema,
                                "temperature": temperature,
                            }
                        )

                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                        future = executor.submit(_call_gemini)
                        response = future.result(timeout=timeout)

                    # SDK parsed model check
                    if hasattr(response, "parsed") and response.parsed is not None:
                        logger.info(f"[Router] Extraction succeeded and validated against schema on tier '{candidate_model}'.")
                        return response.parsed

                    # Fallback: parse raw response text if SDK failed to auto-populate response.parsed
                    if hasattr(response, "text") and response.text:
                        try:
                            raw_dict = json.loads(response.text)
                            parsed_obj = response_schema.model_validate(raw_dict)
                            logger.info(f"[Router] Extraction parsed via fallback deserializer on tier '{candidate_model}'.")
                            return parsed_obj
                        except Exception as parse_err:
                            logger.warning(f"[Router] Fallback JSON parsing failed on tier '{candidate_model}': {parse_err}")

                    # If response was empty or unparseable, cascade to next candidate
                    break

                except Exception as exc:
                    if is_quota_limit_error(exc):
                        # Quota limit: strictly cascade to next model in 9-tier priority order
                        logger.warning(
                            f"[Router] Quota limit encountered on tier '{candidate_model}' ({exc}). "
                            f"Cascading to next tier in 9-tier priority order..."
                        )
                        break

                    elif is_temporary_spike_error(exc):
                        # Temporary spike: DO NOT change model. Use exponential backoff on SAME model.
                        spike_attempt += 1
                        if spike_attempt <= MAX_SPIKE_RETRIES:
                            delay = BASE_SPIKE_DELAY * (2 ** (spike_attempt - 1))
                            logger.info(
                                f"[Router] Temporary demand spike on tier '{candidate_model}' ({exc}). "
                                f"Retrying on SAME model with exponential backoff in {delay:.1f}s (Attempt {spike_attempt}/{MAX_SPIKE_RETRIES})..."
                            )
                            time.sleep(delay)
                            continue
                        else:
                            logger.warning(
                                f"[Router] Tier '{candidate_model}' remained unavailable after {MAX_SPIKE_RETRIES} backoff retries. "
                                f"Cascading to next tier in priority order..."
                            )
                            break

                    else:
                        # Unexpected error: retry on same model once, then cascade
                        spike_attempt += 1
                        if spike_attempt <= 2:
                            delay = BASE_SPIKE_DELAY * (2 ** (spike_attempt - 1))
                            logger.warning(
                                f"[Router] Error on tier '{candidate_model}': {exc}. Retrying in {delay:.1f}s..."
                            )
                            time.sleep(delay)
                            continue
                        else:
                            logger.warning(
                                f"[Router] Tier '{candidate_model}' error persisted. Cascading to next tier..."
                            )
                            break

        logger.warning("[Router] All extraction cascade tiers exhausted or unavailable.")
        return None


_DEFAULT_ROUTER = GeminiModelRouter()


def route_extraction(
    client: Any,
    contents: list,
    response_schema: Type[T],
    preferred_model: Optional[str] = None,
    router: Optional[GeminiModelRouter] = None,
    temperature: float = 0.0,
    timeout_seconds: Optional[float] = None,
) -> Optional[T]:
    """
    Convenience function for routing structured extraction requests across the 9-tier Gemini cascade.
    """
    active_router = router if router is not None else _DEFAULT_ROUTER
    return active_router.route_structured_extraction(
        client=client,
        contents=contents,
        response_schema=response_schema,
        preferred_model=preferred_model,
        temperature=temperature,
        request_timeout_seconds=timeout_seconds,
    )

