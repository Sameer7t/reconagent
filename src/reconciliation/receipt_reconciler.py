"""
Stage 6 — Receipt Reconciliation.

Builds a three-way matching comparison view (PO Quantity vs Invoice Quantity vs Received Quantity)
and detects physical delivery shortages (RECEIPT_SHORTAGE) and unreceived billing
(INVOICE_QUANTITY_EXCEEDS_RECEIVED).
"""
import logging
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SRC_ROOT = Path(__file__).resolve().parent.parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from schemas.reconciliation import (
    Discrepancy,
    DiscrepancyType,
    LineItemMatch,
    ReceiptLineComparison,
    ReconciliationCheck,
    ReconciliationPolicy,
    Severity,
)

logger = logging.getLogger("ReceiptReconciler")


def build_receipt_comparison_table(
    matches: List[LineItemMatch],
    policy: Optional[ReconciliationPolicy] = None,
) -> List[ReceiptLineComparison]:
    """
    Build a comparison table for receipt reconciliation from line item matches,
    supporting both physical quantities and flexible financial amounts if present.
    """
    comparison_table = []
    price_tol = policy.price_tolerance if policy else Decimal("0.02")

    for match in matches:
        item_description = "Unknown Item"
        if match.po_item:
            item_description = (
                match.po_item.get("description")
                if isinstance(match.po_item, dict)
                else getattr(match.po_item, "description", "Unknown Item")
            )
        elif match.invoice_item:
            item_description = (
                match.invoice_item.get("description")
                if isinstance(match.invoice_item, dict)
                else getattr(match.invoice_item, "description", "Unknown Item")
            )

        po_quantity = match.ordered_quantity or Decimal("0")
        invoice_quantity = match.invoiced_quantity or Decimal("0")
        received_quantity = match.received_quantity

        has_receipts = bool(match.receipt_line_ids or match.receipt_items)

        if not has_receipts and (received_quantity is None or received_quantity == Decimal("0")):
            status = "MISSING"
        elif received_quantity is None:
            status = "MISSING"
        elif received_quantity < po_quantity or received_quantity < invoice_quantity:
            status = "SHORTAGE"
        elif received_quantity > po_quantity:
            status = "OVER_DELIVERY"
        else:
            status = "MATCHED"

        # Financial fields (flexible: present only when stated on the receipt)
        po_price = match.ordered_unit_price
        inv_price = match.invoiced_unit_price
        rcpt_price = match.received_unit_price
        rcpt_tot = match.received_total

        if rcpt_price is None and rcpt_tot is not None and received_quantity and received_quantity > Decimal("0"):
            rcpt_price = (rcpt_tot / received_quantity).quantize(Decimal("0.01"))
        elif rcpt_tot is None and rcpt_price is not None and received_quantity is not None:
            rcpt_tot = (rcpt_price * received_quantity).quantize(Decimal("0.01"))

        po_tot = (po_quantity * po_price).quantize(Decimal("0.01")) if (po_quantity and po_price is not None) else None
        inv_tot = (invoice_quantity * inv_price).quantize(Decimal("0.01")) if (invoice_quantity and inv_price is not None) else None

        price_status = "NOT_APPLICABLE"
        if rcpt_price is not None:
            expected_ref_price = po_price if po_price is not None else inv_price
            if expected_ref_price is not None and abs(rcpt_price - expected_ref_price) > price_tol:
                price_status = "PRICE_MISMATCH"
            else:
                price_status = "MATCHED"

        comparison_table.append(
            ReceiptLineComparison(
                item_description=item_description or "Unknown Item",
                po_quantity=po_quantity,
                invoice_quantity=invoice_quantity,
                received_quantity=received_quantity or Decimal("0"),
                status=status,
                po_unit_price=po_price,
                invoice_unit_price=inv_price,
                received_unit_price=rcpt_price,
                po_total=po_tot,
                invoice_total=inv_tot,
                received_total=rcpt_tot,
                price_status=price_status,
            )
        )

    return comparison_table


def reconcile_receipts(
    matches: List[LineItemMatch],
    policy: Optional[ReconciliationPolicy] = None,
) -> Tuple[List[ReconciliationCheck], List[Discrepancy], List[ReceiptLineComparison]]:
    """
    Reconcile receipts against PO and invoice quantities and amounts.
    Flexible handling: if receipt specifies unit amounts/prices, reconciles them
    against PO authorized and Invoice billed rates.
    """
    checks: List[ReconciliationCheck] = []
    discrepancies: List[Discrepancy] = []

    comparison_table = build_receipt_comparison_table(matches, policy)

    all_matched = all(row.status in ("MATCHED", "MISSING") for row in comparison_table) if comparison_table else True
    has_shortage = any(row.status == "SHORTAGE" for row in comparison_table)

    checks.append(
        ReconciliationCheck(
            check_name="receipt_completeness",
            stage="receipt",
            passed=not has_shortage,
            details={"total_items": len(comparison_table), "all_matched": all_matched, "has_shortage": has_shortage},
            message="All receipt items matched cleanly" if not has_shortage else "Delivery shortage detected against receipts",
        )
    )

    for row in comparison_table:
        if row.status == "SHORTAGE":
            shortage_amount = max(row.po_quantity, row.invoice_quantity) - row.received_quantity
            checks.append(
                ReconciliationCheck(
                    check_name=f"receipt_shortage_{row.item_description}",
                    stage="receipt",
                    passed=False,
                    details={
                        "status": row.status,
                        "received": float(row.received_quantity),
                        "po": float(row.po_quantity),
                        "invoice": float(row.invoice_quantity),
                        "shortage": float(shortage_amount),
                    },
                    message=f"Shortage for '{row.item_description}': received {row.received_quantity} vs expected {max(row.po_quantity, row.invoice_quantity)}.",
                )
            )
            discrepancies.append(
                Discrepancy(
                    type=DiscrepancyType.RECEIPT_SHORTAGE,
                    severity=Severity.MEDIUM,
                    expected_value=str(max(row.po_quantity, row.invoice_quantity)),
                    actual_value=str(row.received_quantity),
                    difference=shortage_amount,
                    explanation=(
                        f"Receipt delivery shortage for '{row.item_description}': "
                        f"received {row.received_quantity}, PO ordered {row.po_quantity}, "
                        f"Invoice billed {row.invoice_quantity} (shortage: {shortage_amount} units)."
                    ),
                )
            )
        elif row.status == "OVER_DELIVERY":
            checks.append(
                ReconciliationCheck(
                    check_name=f"receipt_over_delivery_{row.item_description}",
                    stage="receipt",
                    passed=False,
                    details={
                        "status": row.status,
                        "received": float(row.received_quantity),
                        "po": float(row.po_quantity),
                    },
                    message=f"Over-delivery for '{row.item_description}': received {row.received_quantity} vs PO {row.po_quantity}.",
                )
            )

    # ── Amount / Price Checks (Flexible: evaluated when amount is present) ──
    has_receipt_prices = any(row.received_unit_price is not None or row.received_total is not None for row in comparison_table)
    has_price_mismatch = any(row.price_status == "PRICE_MISMATCH" for row in comparison_table)

    if has_receipt_prices:
        checks.append(
            ReconciliationCheck(
                check_name="receipt_price_reconciliation",
                stage="receipt",
                passed=not has_price_mismatch,
                details={
                    "has_receipt_prices": True,
                    "has_price_mismatch": has_price_mismatch,
                },
                message=(
                    "Receipt amounts reconciled cleanly with authorized documents"
                    if not has_price_mismatch
                    else "Receipt amount discrepancy detected against authorized documents"
                ),
            )
        )

        for idx, row in enumerate(comparison_table):
            if row.price_status == "PRICE_MISMATCH" and row.received_unit_price is not None:
                expected_p = row.po_unit_price if row.po_unit_price is not None else row.invoice_unit_price
                diff = abs(row.received_unit_price - (expected_p or Decimal("0.00")))
                target_match = matches[idx] if idx < len(matches) else None
                doc_ids = []
                if target_match and target_match.receipt_line_ids:
                    doc_ids.extend([lid.split("-L")[0] for lid in target_match.receipt_line_ids])
                if target_match and target_match.po_line_id:
                    doc_ids.append(target_match.po_line_id.split("-L")[0])

                checks.append(
                    ReconciliationCheck(
                        check_name=f"receipt_price_mismatch_{row.item_description}",
                        stage="receipt",
                        passed=False,
                        details={
                            "item": row.item_description,
                            "received_price": float(row.received_unit_price),
                            "expected_price": float(expected_p) if expected_p else None,
                            "difference": float(diff),
                        },
                        message=(
                            f"Receipt amount discrepancy for '{row.item_description}': "
                            f"receipt shows ${row.received_unit_price} vs authorized ${expected_p}."
                        ),
                    )
                )
                pct_diff = ((diff / expected_p) * Decimal("100")).quantize(Decimal("0.01")) if (expected_p and expected_p > 0) else None
                discrepancies.append(
                    Discrepancy(
                        type=DiscrepancyType.RECEIPT_PRICE_MISMATCH,
                        severity=Severity.HIGH if (diff > (policy.high_price_difference_threshold if policy else Decimal("100.00")) or (pct_diff and pct_diff > (policy.high_price_percentage_threshold if policy else Decimal("10.0")))) else Severity.MEDIUM,
                        document_ids=doc_ids,
                        po_line_id=target_match.po_line_id if target_match else None,
                        invoice_line_id=target_match.invoice_line_id if target_match else None,
                        receipt_line_id=target_match.receipt_line_ids[0] if (target_match and target_match.receipt_line_ids) else None,
                        expected_value=str(expected_p),
                        actual_value=str(row.received_unit_price),
                        difference=diff,
                        difference_percent=pct_diff,
                        explanation=(
                            f"Receipt amount discrepancy for '{row.item_description}': "
                            f"receipt document specifies ${row.received_unit_price}, "
                            f"exceeding authorized PO price ${expected_p} (diff: ${diff}{f', {pct_diff}%' if pct_diff else ''})."
                        ),
                    )
                )

    return checks, discrepancies, comparison_table
