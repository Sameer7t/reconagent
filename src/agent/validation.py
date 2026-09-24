"""
AI Investigation Agent Validation Layer.

Implements Evidence Grounding (Step 27) and Deterministic Post-Validation (Step 28)
to guard against model hallucination, fictitious document references, and ungrounded claims.
"""
from typing import List, Set, Dict, Any, Tuple
from pydantic import BaseModel, Field

from agent.models import Finding, Evidence, InvestigationResult

ALLOWED_RECOMMENDATIONS = {
    "APPROVE_PAYMENT",
    "REQUEST_CREDIT_MEMO",
    "REJECT_INVOICE",
    "ESCALATE_TO_BUYER",
}


class ValidationReport(BaseModel):
    """
    Structured outcome of deterministic post-validation on an agent investigation.
    """
    is_valid: bool = Field(..., description="True if output passed all deterministic checks.")
    grounding_valid: bool = Field(default=True, description="True if all cited evidence IDs exist.")
    case_id_valid: bool = Field(default=True, description="True if case ID matches state.")
    recommendation_valid: bool = Field(default=True, description="True if recommendation is in allowed enum.")
    discrepancies_valid: bool = Field(default=True, description="True if findings link to actual case discrepancies.")
    document_boundaries_valid: bool = Field(default=True, description="True if all document IDs belong to the case.")
    violations: List[str] = Field(default_factory=list, description="List of specific rule violations detected.")
    cleaned_findings: List[Finding] = Field(default_factory=list, description="Sanitized findings with hallucinated IDs removed.")


def validate_evidence_grounding(
    findings: List[Finding],
    valid_evidence_ids: Set[str],
) -> Tuple[List[Finding], List[str]]:
    """
    Step 27: Evidence Grounding Validation.
    
    Verifies that every evidence ID cited in finding.supporting_evidence_ids
    actually exists in the verified evidence repository.
    If a model invents an ID (e.g. 'EVID-999'), strips it and flags the finding as ungrounded.
    """
    cleaned: List[Finding] = []
    violations: List[str] = []

    for f in findings:
        valid_refs = []
        hallucinated_refs = []

        for eid in f.supporting_evidence_ids:
            if eid in valid_evidence_ids:
                valid_refs.append(eid)
            else:
                hallucinated_refs.append(eid)

        if hallucinated_refs:
            violations.append(
                f"Evidence Grounding Violation in finding '{f.finding_id}' ({f.discrepancy_type}): "
                f"Referenced non-existent evidence IDs: {hallucinated_refs}."
            )

        # Clone finding with cleaned evidence references
        f_dict = f.model_dump()
        f_dict["supporting_evidence_ids"] = valid_refs

        # If all evidence references were hallucinated, mark ungrounded
        if hallucinated_refs and not valid_refs:
            f_dict["confidence"] = "LOW"
            f_dict["explanation"] = f"{f_dict['explanation']} [UNGROUNDED: Referenced evidence does not exist on file]"

        cleaned.append(Finding(**f_dict))

    return cleaned, violations


def validate_investigation_result(
    result: InvestigationResult,
    state: Dict[str, Any],
) -> ValidationReport:
    """
    Step 28: Deterministic Post-Validation of Agent Output.
    
    Python strictly validates the structure, case boundaries, and evidence grounding
    without trusting raw model generation:
      1. Are evidence IDs real?
      2. Does the case ID match?
      3. Are recommendations allowed?
      4. Are findings linked to actual case discrepancies?
      5. Did the agent invent document IDs?
    """
    violations: List[str] = []

    # 1. Case ID Match
    expected_case_id = state.get("case_id", "")
    case_id_valid = (result.case_id == expected_case_id)
    if not case_id_valid:
        violations.append(
            f"Case ID Mismatch: Result specifies '{result.case_id}' but active case is '{expected_case_id}'."
        )

    # 2. Permitted Recommendations Whitelist
    recommendation_valid = result.recommendation in ALLOWED_RECOMMENDATIONS
    if not recommendation_valid:
        violations.append(
            f"Disallowed Recommendation: '{result.recommendation}'. Permitted: {sorted(ALLOWED_RECOMMENDATIONS)}."
        )

    # 3. Evidence Grounding
    valid_eids = {e.evidence_id for e in result.evidence}
    # Also include any evidence existing in state
    for e in state.get("evidence", []):
        eid = e.get("evidence_id") if isinstance(e, dict) else getattr(e, "evidence_id", None)
        if eid:
            valid_eids.add(eid)

    cleaned_findings, grounding_violations = validate_evidence_grounding(result.findings, valid_eids)
    grounding_valid = len(grounding_violations) == 0
    violations.extend(grounding_violations)

    # 4. Discrepancy Alignment
    actual_discrepancies = state.get("discrepancies", [])
    actual_types = {str(d.get("type", "")).upper() for d in actual_discrepancies}
    discrepancies_valid = True

    if actual_types:
        for f in result.findings:
            f_type = f.discrepancy_type.upper()
            matched = any(at in f_type or f_type in at for at in actual_types)
            if not matched:
                discrepancies_valid = False
                violations.append(
                    f"Discrepancy Misalignment: Finding '{f.finding_id}' claims '{f.discrepancy_type}' "
                    f"which was not reported in reconciliation discrepancies {sorted(actual_types)}."
                )

    # 5. Document Boundary / Scoping Integrity
    rec_result = state.get("reconciliation_result", {})
    allowed_docs: Set[str] = set()
    for key in ("purchase_order_id", "invoice_id"):
        val = rec_result.get(key)
        if val:
            allowed_docs.add(str(val).strip().upper())
    for r_id in rec_result.get("receipt_ids", []):
        if r_id:
            allowed_docs.add(str(r_id).strip().upper())
    vendor = rec_result.get("vendor_name")
    if vendor:
        allowed_docs.add(str(vendor).strip().upper())

    doc_boundaries_valid = True
    for ev in result.evidence:
        source_id = str(ev.source_id).strip().upper()
        # Allow case_id or any known document
        if allowed_docs and source_id not in allowed_docs and source_id != expected_case_id.upper():
            doc_boundaries_valid = False
            violations.append(
                f"Document Boundary Violation: Evidence '{ev.evidence_id}' references foreign or invented document ID '{ev.source_id}'."
            )

    is_valid = (
        case_id_valid
        and recommendation_valid
        and grounding_valid
        and discrepancies_valid
        and doc_boundaries_valid
    )

    return ValidationReport(
        is_valid=is_valid,
        grounding_valid=grounding_valid,
        case_id_valid=case_id_valid,
        recommendation_valid=recommendation_valid,
        discrepancies_valid=discrepancies_valid,
        document_boundaries_valid=doc_boundaries_valid,
        violations=violations,
        cleaned_findings=cleaned_findings,
    )

