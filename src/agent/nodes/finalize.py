"""
AI Investigation Agent Finalize Node.

Synthesizes gathered evidence, root cause analyses, and discrepancy assessments
into strongly-typed Findings, an authoritative settlement recommendation, and final status.
"""
from typing import Dict, Any, List, Optional
from agent.state import InvestigationState
from agent.models import Finding, InvestigationResult, Evidence
from agent.validation import validate_evidence_grounding, validate_investigation_result


def finalize_node(state: InvestigationState) -> InvestigationState:
    """
    Final synthesis node of the investigation workflow.
    
    1. Evaluates all case discrepancies against the gathered evidence repository.
    2. Constructs verified Finding objects linked to explicit Evidence IDs.
    3. Formulates a final business settlement recommendation:
       - APPROVE_PAYMENT: All discrepancies verified and approved.
       - REQUEST_CREDIT_MEMO: Price variance, unauthorized charge, or delivery shortage without authorization.
       - REJECT_INVOICE: Duplicate invoice, severe vendor discrepancy, or fraudulent submission.
       - ESCALATE_TO_BUYER: Ambiguous, missing records, or unresolvable policy variance.
    4. Sets confidence and human review flags.
    5. Updates state status to 'COMPLETED'.
    """
    discrepancies = state.get("discrepancies", [])
    evidence_dicts = state.get("evidence", [])
    case_id = state.get("case_id", "UNKNOWN_CASE")

    findings: List[Finding] = []

    # Evidence indexing by source type and id
    auth_evidence = [e for e in evidence_dicts if e.get("source_type") == "authorization"]
    po_evidence = [e for e in evidence_dicts if e.get("source_type") == "purchase_order"]
    inv_evidence = [e for e in evidence_dicts if e.get("source_type") == "invoice"]
    receipt_evidence = [e for e in evidence_dicts if e.get("source_type") == "receipt"]
    vendor_evidence = [e for e in evidence_dicts if e.get("source_type") == "vendor_history"]

    has_approved_auth = any(
        e.get("value") == "True" or "approved" in str(e.get("description", "")).lower()
        for e in auth_evidence
    )

    for idx, disc in enumerate(discrepancies, start=1):
        disc_type = str(disc.get("type", "UNKNOWN_DISCREPANCY")).upper()
        expected = disc.get("expected_value")
        actual = disc.get("actual_value")
        disc_explanation = disc.get("explanation", "")

        supporting_ids: List[str] = []
        finding_confidence = "HIGH"

        # 1. Price / Unit Rate Discrepancies
        if any(pt in disc_type for pt in ("PRICE", "UNIT_PRICE", "RATE")):
            supporting_ids.extend([e["evidence_id"] for e in po_evidence])
            supporting_ids.extend([e["evidence_id"] for e in inv_evidence])
            supporting_ids.extend([e["evidence_id"] for e in auth_evidence])

            if has_approved_auth:
                explanation = (
                    f"Unit price variance (expected ${expected}, billed ${actual}) was investigated and confirmed. "
                    f"A formal price escalation amendment was found on file and verified."
                )
            else:
                explanation = (
                    f"Unit price billed (${actual}) exceeds approved purchase order rate (${expected}). "
                    f"No formal price escalation or amendment authorization was found on file."
                )

        # 2. Quantity Shortage / Delivery Receipts
        elif any(qt in disc_type for qt in ("QUANTITY", "SHORTAGE", "RECEIPT")):
            supporting_ids.extend([e["evidence_id"] for e in receipt_evidence])
            supporting_ids.extend([e["evidence_id"] for e in inv_evidence])

            shortage_receipts = [
                e for e in receipt_evidence
                if e.get("field") == "quantity_delivered"
            ]
            missing_receipts = [
                e for e in receipt_evidence
                if e.get("value") == "NOT_FOUND"
            ]

            if missing_receipts:
                explanation = (
                    f"Physical delivery confirmation could not be verified. "
                    f"No delivery receipt was found on file for this shipment."
                )
                finding_confidence = "MEDIUM"
            elif shortage_receipts:
                delivered_vals = [e.get("value") for e in shortage_receipts]
                explanation = (
                    f"Physical delivery shortage confirmed by receiving records (delivered: {', '.join(delivered_vals)}). "
                    f"Vendor invoiced for ordered quantity prior to full delivery fulfillment."
                )
            else:
                explanation = f"Quantity discrepancy detected: {disc_explanation or 'Billed quantity does not match receiving records.'}"

        # 3. Unauthorized Charges / Surcharges / Shipping
        elif any(ct in disc_type for ct in ("UNAUTHORIZED", "CHARGE", "SHIPPING", "SURCHARGE")):
            supporting_ids.extend([e["evidence_id"] for e in po_evidence])
            supporting_ids.extend([e["evidence_id"] for e in inv_evidence])
            supporting_ids.extend([e["evidence_id"] for e in auth_evidence])

            if has_approved_auth:
                explanation = f"Additional charge was verified against formal authorization on file."
            else:
                explanation = (
                    f"Unauthorized financial charge or surcharge billed without PO line authorization. "
                    f"No approval or change order was found on file."
                )

        # 4. Duplicate Invoice
        elif "DUPLICATE" in disc_type:
            supporting_ids.extend([e["evidence_id"] for e in inv_evidence])
            explanation = "Invoice fingerprint matches an existing historical record in enterprise ledger."

        # 5. Header / Vendor / Currency
        elif any(ht in disc_type for ht in ("VENDOR", "CURRENCY", "LINK")):
            supporting_ids.extend([e["evidence_id"] for e in po_evidence])
            supporting_ids.extend([e["evidence_id"] for e in inv_evidence])
            explanation = f"Document header variance: {disc_explanation or 'Vendor or currency mismatch across documents.'}"

        # 6. Default / Catch-All
        else:
            supporting_ids.extend([e["evidence_id"] for e in evidence_dicts[:2]])
            explanation = f"Discrepancy investigated: {disc_explanation or 'Variance detected between PO and billed record.'}"

        findings.append(Finding(
            finding_id=f"FIND-{idx:03d}",
            discrepancy_type=disc_type,
            explanation=explanation,
            supporting_evidence_ids=list(dict.fromkeys(supporting_ids)),  # preserve order & unique
            confidence=finding_confidence,
        ))

    # Formulate Overall Recommendation
    disc_types = [str(d.get("type", "")).upper() for d in discrepancies]

    if any("DUPLICATE" in dt for dt in disc_types):
        recommendation = "REJECT_INVOICE"
    elif any("VENDOR" in dt or "CURRENCY" in dt for dt in disc_types):
        recommendation = "REJECT_INVOICE"
    elif not discrepancies:
        recommendation = "APPROVE_PAYMENT"
    elif has_approved_auth and all("PRICE" in dt or "CHARGE" in dt for dt in disc_types):
        recommendation = "APPROVE_PAYMENT"
    elif any("PRICE" in dt or "SHORTAGE" in dt or "QUANTITY" in dt or "CHARGE" in dt or "UNAUTHORIZED" in dt for dt in disc_types):
        recommendation = "REQUEST_CREDIT_MEMO"
    else:
        recommendation = "ESCALATE_TO_BUYER"

    # Overall confidence: HIGH unless any finding has LOW/MEDIUM or missing evidence
    if any(f.confidence in ("LOW", "MEDIUM") for f in findings):
        overall_confidence = "MEDIUM"
    else:
        overall_confidence = "HIGH"

    # Human review: Required for all actions except straightforward pre-approved payment
    # Step 27: Evidence Grounding Validation
    valid_eids = {e.get("evidence_id") for e in evidence_dicts}
    cleaned_findings, grounding_violations = validate_evidence_grounding(findings, valid_eids)

    # Human review: Required for all actions except straightforward pre-approved payment
    requires_human_review = (recommendation != "APPROVE_PAYMENT")
    if grounding_violations:
        requires_human_review = True
        overall_confidence = "LOW" if not any(f.confidence == "HIGH" for f in cleaned_findings) else "MEDIUM"

    # Step 26: Create InvestigationResult model
    inv_evidence = [Evidence(**e) if isinstance(e, dict) else e for e in evidence_dicts]
    inv_result = InvestigationResult(
        case_id=case_id,
        findings=cleaned_findings,
        evidence=inv_evidence,
        recommendation=recommendation,
        confidence=overall_confidence,
        requires_human_review=requires_human_review,
    )

    # Step 28: Deterministic Post-Validation
    val_report = validate_investigation_result(inv_result, state)
    if not val_report.is_valid:
        requires_human_review = True
        inv_result.requires_human_review = True

    # Update State
    state["findings"] = [f.model_dump() for f in cleaned_findings]
    state["recommendation"] = recommendation
    state["confidence"] = overall_confidence
    state["requires_human_review"] = requires_human_review
    state["investigation_result"] = inv_result.model_dump()
    state["validation_report"] = val_report.model_dump()
    state["status"] = "REQUIRES_HUMAN_REVIEW" if requires_human_review else "COMPLETED"

    return state


def create_investigation_result(state: InvestigationState) -> InvestigationResult:
    """
    Constructs an authoritative InvestigationResult model from a finalized state.
    """
    findings = [
        Finding(**f) if isinstance(f, dict) else f
        for f in state.get("findings", [])
    ]
    evidence = [
        Evidence(**e) if isinstance(e, dict) else e
        for e in state.get("evidence", [])
    ]
    return InvestigationResult(
        case_id=state.get("case_id", "UNKNOWN_CASE"),
        findings=findings,
        evidence=evidence,
        recommendation=state.get("recommendation", "ESCALATE_TO_BUYER"),
        confidence=state.get("confidence", "HIGH"),
        requires_human_review=state.get("requires_human_review", True),
    )

