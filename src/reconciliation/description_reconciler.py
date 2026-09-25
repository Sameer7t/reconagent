"""
Stage 3.5 — Description and Specification Reconciliation.

Performs 3-way description and specification audits across matched line items:
- Uses fuzzy word matching for real-world item descriptions (accommodating typos/OCR errors,
  e.g., 'marker' vs 'merker', 'processor' vs 'procesor').
- Enforces strict non-fuzzy validation for measurements, units, dimensions, and model numbers
  (e.g., '0.5 mm' vs '0.10 mm', or '4x4' vs '4x8' must NEVER match and are flagged as
  SPECIFICATION_MISMATCH discrepancies).
"""
import logging
import sys
from pathlib import Path
from typing import List, Tuple

SRC_ROOT = Path(__file__).resolve().parent.parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from schemas.reconciliation import (
    Discrepancy,
    DiscrepancyType,
    LineItemMatch,
    ReconciliationCheck,
    ReconciliationPolicy,
    Severity,
)
from reconciliation.line_item_matcher import compare_item_descriptions

logger = logging.getLogger("DescriptionReconciler")


def reconcile_descriptions(
    matches: List[LineItemMatch],
    policy: ReconciliationPolicy,
) -> Tuple[List[ReconciliationCheck], List[Discrepancy], List[LineItemMatch]]:
    """
    Audit descriptions and physical specifications across PO, Invoice, and Receipts
    for each matched line item.

    Returns:
        checks: List[ReconciliationCheck]
        discrepancies: List[Discrepancy]
        updated_matches: List[LineItemMatch]
    """
    checks: List[ReconciliationCheck] = []
    discrepancies: List[Discrepancy] = []

    if not matches:
        return checks, discrepancies, matches

    for match in matches:
        po_item = match.po_item or {}
        inv_item = match.invoice_item or {}

        po_desc = str(po_item.get("description", "") or "").strip()
        inv_desc = str(inv_item.get("description", "") or "").strip()

        # ── 1. Audit PO vs Invoice descriptions ─────────────────────
        if po_desc and inv_desc:
            is_match, sim, disc_code, reason = compare_item_descriptions(po_desc, inv_desc)

            match.description_similarity = round(sim, 4)
            match.specification_match = (
                disc_code not in ("DIMENSION_MISMATCH", "MEASUREMENT_MISMATCH", "CODE_MISMATCH")
            )

            line_identifier = match.po_line_id or match.invoice_line_id or "LINE"

            if disc_code in ("DIMENSION_MISMATCH", "MEASUREMENT_MISMATCH", "CODE_MISMATCH"):
                explanation = (
                    f"Specification mismatch on line item: PO specifies '{po_desc}' "
                    f"but Invoice specifies '{inv_desc}' ({reason}). "
                    "Different product measurement/variant billed."
                )
                discrepancies.append(
                    Discrepancy(
                        type=DiscrepancyType.SPECIFICATION_MISMATCH,
                        severity=Severity.HIGH,
                        po_line_id=match.po_line_id,
                        invoice_line_id=match.invoice_line_id,
                        expected_value=po_desc,
                        actual_value=inv_desc,
                        explanation=explanation,
                        details={
                            "po_description": po_desc,
                            "invoice_description": inv_desc,
                            "mismatch_type": disc_code,
                            "reason": reason,
                        },
                    )
                )
                checks.append(
                    ReconciliationCheck(
                        stage="DESCRIPTION_RECONCILIATION",
                        check_name=f"spec_match_{line_identifier}",
                        passed=False,
                        message=explanation,
                        details={
                            "po_description": po_desc,
                            "invoice_description": inv_desc,
                            "mismatch_type": disc_code,
                        },
                    )
                )
            elif not is_match and sim < 0.60:
                explanation = (
                    f"Item description mismatch: PO specifies '{po_desc}' "
                    f"but Invoice specifies '{inv_desc}' ({reason})."
                )
                discrepancies.append(
                    Discrepancy(
                        type=DiscrepancyType.DESCRIPTION_MISMATCH,
                        severity=Severity.HIGH,
                        po_line_id=match.po_line_id,
                        invoice_line_id=match.invoice_line_id,
                        expected_value=po_desc,
                        actual_value=inv_desc,
                        explanation=explanation,
                        details={
                            "po_description": po_desc,
                            "invoice_description": inv_desc,
                            "similarity": sim,
                            "reason": reason,
                        },
                    )
                )
                checks.append(
                    ReconciliationCheck(
                        stage="DESCRIPTION_RECONCILIATION",
                        check_name=f"desc_match_{line_identifier}",
                        passed=False,
                        message=explanation,
                        details={
                            "po_description": po_desc,
                            "invoice_description": inv_desc,
                            "similarity": sim,
                        },
                    )
                )
            else:
                checks.append(
                    ReconciliationCheck(
                        stage="DESCRIPTION_RECONCILIATION",
                        check_name=f"desc_match_{line_identifier}",
                        passed=True,
                        message=(
                            f"Description verified: '{po_desc}' aligns with '{inv_desc}' "
                            f"(similarity: {sim:.1%})."
                        ),
                        details={
                            "po_description": po_desc,
                            "invoice_description": inv_desc,
                            "similarity": sim,
                        },
                    )
                )

        # ── 2. Audit Receipts vs PO / Invoice ────────────────────────
        receipt_items = match.receipt_items or []
        for r_idx, r_item in enumerate(receipt_items):
            r_desc = str(r_item.get("description", "") or "").strip()
            r_line_id = (
                match.receipt_line_ids[r_idx]
                if match.receipt_line_ids and r_idx < len(match.receipt_line_ids)
                else None
            )

            # Audit against PO description
            if po_desc and r_desc:
                r_match, r_sim, r_code, r_reason = compare_item_descriptions(po_desc, r_desc)
                if r_code in ("DIMENSION_MISMATCH", "MEASUREMENT_MISMATCH", "CODE_MISMATCH"):
                    match.specification_match = False
                    explanation = (
                        f"Specification mismatch on receipt item: PO ordered '{po_desc}' "
                        f"but Delivery Receipt contains '{r_desc}' ({r_reason}). "
                        "Physical goods delivered do not match ordered specification."
                    )
                    discrepancies.append(
                        Discrepancy(
                            type=DiscrepancyType.SPECIFICATION_MISMATCH,
                            severity=Severity.HIGH,
                            po_line_id=match.po_line_id,
                            receipt_line_id=r_line_id,
                            expected_value=po_desc,
                            actual_value=r_desc,
                            explanation=explanation,
                            details={
                                "po_description": po_desc,
                                "receipt_description": r_desc,
                                "mismatch_type": r_code,
                                "reason": r_reason,
                            },
                        )
                    )
                    checks.append(
                        ReconciliationCheck(
                            stage="DESCRIPTION_RECONCILIATION",
                            check_name=f"receipt_spec_match_{r_line_id or match.po_line_id}",
                            passed=False,
                            message=explanation,
                        )
                    )
                elif not r_match and r_sim < 0.60:
                    explanation = (
                        f"Receipt description mismatch: PO ordered '{po_desc}' "
                        f"but Delivery Receipt contains '{r_desc}' ({r_reason})."
                    )
                    discrepancies.append(
                        Discrepancy(
                            type=DiscrepancyType.DESCRIPTION_MISMATCH,
                            severity=Severity.HIGH,
                            po_line_id=match.po_line_id,
                            receipt_line_id=r_line_id,
                            expected_value=po_desc,
                            actual_value=r_desc,
                            explanation=explanation,
                        )
                    )
                    checks.append(
                        ReconciliationCheck(
                            stage="DESCRIPTION_RECONCILIATION",
                            check_name=f"receipt_desc_match_{r_line_id or match.po_line_id}",
                            passed=False,
                            message=explanation,
                        )
                    )
                else:
                    checks.append(
                        ReconciliationCheck(
                            stage="DESCRIPTION_RECONCILIATION",
                            check_name=f"receipt_desc_match_{r_line_id or match.po_line_id}",
                            passed=True,
                            message=(
                                f"Receipt description verified: '{po_desc}' aligns with '{r_desc}' "
                                f"(similarity: {r_sim:.1%})."
                            ),
                        )
                    )

            # Audit against Invoice description if PO description was absent
            elif inv_desc and r_desc:
                r_match, r_sim, r_code, r_reason = compare_item_descriptions(inv_desc, r_desc)
                if r_code in ("DIMENSION_MISMATCH", "MEASUREMENT_MISMATCH", "CODE_MISMATCH"):
                    match.specification_match = False
                    explanation = (
                        f"Specification mismatch between invoice and receipt: Invoice billed '{inv_desc}' "
                        f"but Delivery Receipt contains '{r_desc}' ({r_reason})."
                    )
                    discrepancies.append(
                        Discrepancy(
                            type=DiscrepancyType.SPECIFICATION_MISMATCH,
                            severity=Severity.HIGH,
                            invoice_line_id=match.invoice_line_id,
                            receipt_line_id=r_line_id,
                            expected_value=inv_desc,
                            actual_value=r_desc,
                            explanation=explanation,
                        )
                    )

    return checks, discrepancies, matches
