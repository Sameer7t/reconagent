"""
AI Investigation Agent Finalize Node.

Synthesizes gathered evidence, root cause analyses, and discrepancy assessments
into strongly-typed Findings, an authoritative settlement recommendation, and final status.
"""
import re
from typing import Dict, Any, List, Optional
from agent.state import InvestigationState
from agent.models import Finding, InvestigationResult, Evidence
from agent.validation import validate_evidence_grounding, validate_investigation_result


def _build_line_audit_context(
    po_evidence: List[Dict[str, Any]],
    inv_evidence: List[Dict[str, Any]],
    receipt_evidence: List[Dict[str, Any]],
    math_evidence: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Cross-references line-level evidence across PO, Invoice, Receipt, and Math checks.
    Identifies specific items that have arithmetic errors, quantity variances, or both.
    """
    item_map: Dict[str, Dict[str, Any]] = {}

    def to_flt(s: Any) -> Optional[float]:
        try:
            return float(str(s).strip().rstrip(".").replace(",", ""))
        except Exception:
            return None

    for e in po_evidence:
        desc = e.get("description", "")
        m = re.search(r"line '([^']+)' approved unit price is \$?([0-9.]+)\s*\(authorized qty:\s*([0-9.]+)\)", desc, re.I)
        if m:
            name, price, qty = m.group(1), to_flt(m.group(2)), to_flt(m.group(3))
            k = name.strip().lower()
            if k not in item_map:
                item_map[k] = {"name": name}
            item_map[k]["po_qty"] = qty
            item_map[k]["po_price"] = price
            item_map[k]["po_id"] = e.get("source_id")

    for e in inv_evidence:
        desc = e.get("description", "")
        m = re.search(r"line '([^']+)' billed unit price is \$?([0-9.]+)\s*\(billed qty:\s*([0-9.]+),\s*line total:\s*\$?([0-9.]+)\)", desc, re.I)
        if m:
            name, price, qty, total = m.group(1), to_flt(m.group(2)), to_flt(m.group(3)), to_flt(m.group(4))
            k = name.strip().lower()
            if k not in item_map:
                item_map[k] = {"name": name}
            item_map[k]["inv_qty"] = qty
            item_map[k]["inv_price"] = price
            item_map[k]["inv_total"] = total
            item_map[k]["inv_id"] = e.get("source_id")

    for e in receipt_evidence:
        desc = e.get("description", "")
        m = re.search(r"confirms physical delivery of ([0-9.]+)\s*units for '([^']+)'", desc, re.I)
        if m:
            qty, name = to_flt(m.group(1)), m.group(2)
            k = name.strip().lower()
            if k not in item_map:
                item_map[k] = {"name": name}
            item_map[k]["rcpt_qty"] = qty
            item_map[k]["rcpt_id"] = e.get("source_id")

    for e in math_evidence:
        desc = e.get("description", "")
        m = re.search(r"line '([^']+)' math mismatch:\s*calculated \$?([0-9.]+)\s*vs printed \$?([0-9.]+)", desc, re.I)
        if m:
            name, calc_val, print_val = m.group(1), to_flt(m.group(2)), to_flt(m.group(3))
            k = name.strip().lower()
            if k not in item_map:
                item_map[k] = {"name": name}
            item_map[k]["math_calc"] = calc_val
            item_map[k]["math_printed"] = print_val
            item_map[k]["math_doc_id"] = e.get("source_id")

    lines_summary = []
    has_math_and_qty_variance = False

    for k, item in item_map.items():
        name = item.get("name", "Item")
        po_q = item.get("po_qty")
        inv_q = item.get("inv_qty")
        rcpt_q = item.get("rcpt_qty")
        math_c = item.get("math_calc")
        math_p = item.get("math_printed")
        rate = item.get("po_price") or item.get("inv_price") or 0.0
        po_doc = item.get("math_doc_id") or item.get("po_id") or "Purchase Order"
        inv_doc = item.get("inv_id") or "Invoice"
        rcpt_doc = item.get("rcpt_id") or "Receipt"

        if math_c is not None and math_p is not None:
            has_math_and_qty_variance = True
            po_q_str = f"{int(po_q)}" if po_q is not None and po_q == int(po_q) else str(po_q or "")
            detail = (
                f"Line item '{name}' arithmetic mismatch on {po_doc}: "
                f"authorized quantity {po_q_str} @ ${rate:.2f} "
                f"(calculated: ${math_c:,.2f}), but printed total is ${math_p:,.2f}."
            )
            if inv_q is not None or rcpt_q is not None:
                q_deliv = rcpt_q if rcpt_q is not None else inv_q
                q_billed = inv_q if inv_q is not None else rcpt_q
                q_deliv_str = f"{int(q_deliv)}" if q_deliv is not None and q_deliv == int(q_deliv) else str(q_deliv or "")
                q_billed_str = f"{int(q_billed)}" if q_billed is not None and q_billed == int(q_billed) else str(q_billed or "")

                calc_at_actual = (q_deliv or 0) * rate
                if abs(calc_at_actual - math_p) < 0.01:
                    detail += (
                        f" Cross-document audit confirms {inv_doc} billed {q_billed_str} units (${math_p:,.2f}) "
                        f"and {rcpt_doc} confirmed physical delivery of {q_deliv_str} units ({q_deliv_str} x ${rate:.2f} = ${math_p:,.2f}). "
                        f"The printed {po_doc} total matches the delivered count ({q_deliv_str} units) rather than the authorized count ({po_q_str} units), "
                        f"indicating a clerical quantity typo on the purchase order."
                    )
                else:
                    detail += (
                        f" Cross-document audit reveals quantity variance: {inv_doc} billed {q_billed_str} units, "
                        f"{rcpt_doc} delivered {q_deliv_str} units, vs {po_q_str} authorized on {po_doc}."
                    )
            lines_summary.append(detail)

        elif po_q is not None and (inv_q is not None or rcpt_q is not None):
            q_deliv = rcpt_q if rcpt_q is not None else inv_q
            q_billed = inv_q if inv_q is not None else rcpt_q
            if (q_deliv is not None and q_deliv != po_q) or (q_billed is not None and q_billed != po_q):
                has_math_and_qty_variance = True
                po_q_str = f"{int(po_q)}" if po_q == int(po_q) else str(po_q)
                q_deliv_str = f"{int(q_deliv)}" if q_deliv is not None and q_deliv == int(q_deliv) else str(q_deliv)
                q_billed_str = f"{int(q_billed)}" if q_billed is not None and q_billed == int(q_billed) else str(q_billed)
                lines_summary.append(
                    f"Line item '{name}' quantity variance: PO authorized {po_q_str} units, "
                    f"Invoice billed {q_billed_str} units, and Receipt confirmed {q_deliv_str} units."
                )

    return {
        "item_map": item_map,
        "lines_summary": lines_summary,
        "has_multi_factor_defect": has_math_and_qty_variance,
    }


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
    math_evidence = [
        e for e in evidence_dicts
        if e.get("field") in ("line_total_math", "document_math", "internal_math")
    ]

    has_approved_auth = any(
        e.get("value") == "True" or "approved" in str(e.get("description", "")).lower()
        for e in auth_evidence
    )

    line_ctx = _build_line_audit_context(po_evidence, inv_evidence, receipt_evidence, math_evidence)
    lines_summary = line_ctx["lines_summary"]

    for idx, disc in enumerate(discrepancies, start=1):
        raw_type = disc.get("type", "UNKNOWN_DISCREPANCY")
        if hasattr(raw_type, "value"):
            disc_type = str(raw_type.value).upper()
        else:
            disc_type = str(raw_type).replace("DiscrepancyType.", "").strip().upper()

        expected = disc.get("expected_value")
        actual = disc.get("actual_value")
        disc_explanation = disc.get("explanation", "")

        supporting_ids: List[str] = []
        finding_confidence = "HIGH"

        # 0. Document Calculation / Internal Arithmetic Error
        if any(mt in disc_type for mt in ("CALCULATION", "MATH")):
            supporting_ids.extend([e["evidence_id"] for e in math_evidence])
            supporting_ids.extend([e["evidence_id"] for e in po_evidence])
            supporting_ids.extend([e["evidence_id"] for e in inv_evidence])
            supporting_ids.extend([e["evidence_id"] for e in receipt_evidence])
            if not supporting_ids:
                supporting_ids.extend([e["evidence_id"] for e in evidence_dicts[:3]])

            if lines_summary:
                explanation = (
                    f"Document arithmetic validation failed on source document. {lines_summary[0]} "
                    f"Corporate AP policy requires rejecting documents with internal arithmetic defects until a corrected version is reissued."
                )
            else:
                math_desc = math_evidence[0].get("description") if math_evidence else disc_explanation
                math_val = math_evidence[0].get("value") if math_evidence else ""
                explanation = (
                    f"Document arithmetic validation failed on source document. {math_desc or math_val}. "
                    f"Corporate AP policy requires rejecting documents with internal arithmetic defects until a corrected version is reissued."
                )

        # 1. Price / Unit Rate Discrepancies
        elif any(pt in disc_type for pt in ("PRICE", "UNIT_PRICE", "RATE")):
            supporting_ids.extend([e["evidence_id"] for e in po_evidence])
            supporting_ids.extend([e["evidence_id"] for e in inv_evidence])
            supporting_ids.extend([e["evidence_id"] for e in auth_evidence])

            if has_approved_auth:
                explanation = (
                    f"Unit price variance (expected ${expected}, billed ${actual}) was investigated. "
                    f"A formal price escalation amendment was found on file. "
                    f"Left to human review for final decision."
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
            supporting_ids.extend([e["evidence_id"] for e in po_evidence])
            if math_evidence:
                supporting_ids.extend([e["evidence_id"] for e in math_evidence])

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
            elif lines_summary:
                explanation = (
                    f"Quantity variance and cross-document discrepancy confirmed: {lines_summary[0]} "
                    f"Billed/delivered units do not match authorized purchase order counts."
                )
            elif math_evidence:
                math_val = math_evidence[0].get("value", "")
                explanation = (
                    f"Quantity variance detected between Purchase Order and receiving/billing records. "
                    f"PO contains a clerical arithmetic error ({math_val}). The vendor billed and delivered according to receipt records, but the PO line items do not match final delivered counts."
                )
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
    disc_types = []
    for d in discrepancies:
        raw_t = d.get("type", "")
        if hasattr(raw_t, "value"):
            disc_types.append(str(raw_t.value).upper())
        else:
            disc_types.append(str(raw_t).replace("DiscrepancyType.", "").strip().upper())

    if any("CALCULATION" in dt or "MATH" in dt for dt in disc_types):
        recommendation = "REJECT_INVOICE"
    elif any("DUPLICATE" in dt for dt in disc_types):
        recommendation = "REJECT_INVOICE"
    elif any("VENDOR" in dt or "CURRENCY" in dt for dt in disc_types):
        recommendation = "REJECT_INVOICE"
    elif not discrepancies:
        recommendation = "APPROVE_PAYMENT"
    elif has_approved_auth and all("PRICE" in dt or "CHARGE" in dt for dt in disc_types):
        recommendation = "HUMAN_REVIEW"
    elif any("PRICE" in dt or "SHORTAGE" in dt or "QUANTITY" in dt or "CHARGE" in dt or "UNAUTHORIZED" in dt for dt in disc_types):
        recommendation = "REQUEST_CREDIT_MEMO"
    else:
        recommendation = "HUMAN_REVIEW"

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

    final_summary_text = None
    if lines_summary:
        synth_text = " ".join(lines_summary)
        final_summary_text = (
            f"Document arithmetic validation and cross-document audit completed: {synth_text} "
            f"Action: Reject invoice and request a corrected document from the vendor."
        )
    elif any("CALCULATION" in dt or "MATH" in dt for dt in disc_types):
        math_detail = math_evidence[0].get("description") if math_evidence else "Printed totals do not equal line item calculations."
        final_summary_text = (
            f"Document arithmetic validation failed. {math_detail} "
            f"Action: Reject invoice and request a corrected document from the vendor."
        )
    elif recommendation == "APPROVE_PAYMENT":
        final_summary_text = "Reconciliation audit verified: all items, unit rates, and quantities match corporate authorization records."
    elif recommendation == "REQUEST_CREDIT_MEMO":
        final_summary_text = "Reconciliation identified unapproved variances. Recommended action: Request a credit memo from the vendor."
    else:
        final_summary_text = f"Investigation concluded with recommendation: {recommendation}."

    # Step 26: Create InvestigationResult model
    inv_evidence = [Evidence(**e) if isinstance(e, dict) else e for e in evidence_dicts]
    inv_result = InvestigationResult(
        case_id=case_id,
        findings=cleaned_findings,
        evidence=inv_evidence,
        recommendation=recommendation,
        confidence=overall_confidence,
        requires_human_review=requires_human_review,
        final_summary=final_summary_text,
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
    state["final_summary"] = final_summary_text
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
        recommendation=state.get("recommendation", "HUMAN_REVIEW"),
        confidence=state.get("confidence", "HIGH"),
        requires_human_review=state.get("requires_human_review", True),
        final_summary=state.get("final_summary"),
    )

