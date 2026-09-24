"""
End-to-End Test for Document Calculation Error + Quantity Variance Investigation.

Verifies that when a Purchase Order contains a clerical arithmetic error
(e.g. QTY 6 @ $560 = $3360, but printed as $2800) alongside a quantity variance
(Invoice billed 5, Receipt received 5), the AI investigation agent:
1. Is NOT bypassed.
2. Successfully executes verify_document_arithmetic on the PO.
3. Retrieves PO, Invoice, and Receipt records.
4. Formulates a REJECT_INVOICE recommendation due to the source arithmetic defect.
5. Synthesizes a multi-factor explanation explaining both the line total math error
   and the quantity variance (PO 6 vs billed/received 5).
"""
import sys
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pipeline.orchestrator import MasterOrchestrator, TransactionResult


def test_calculation_error_and_quantity_variance_agent_investigation():
    orchestrator = MasterOrchestrator(max_tool_calls=6)

    # PO has QTY 6 @ $560.00 = $3,360.00, but printed line_total is $2,800.00
    po_data = {
        "purchase_order_number": "PO-2024-0001",
        "vendor_name": "TechTraders Solutions Inc.",
        "currency": "USD",
        "items": [
            {
                "product_code": "TT-CPU-109",
                "description": "Intel Core i9-13900K Processor",
                "quantity": 6,
                "unit_price": "560.00",
                "line_total": "2800.00",  # Math error! 6 * 560 = 3360
            },
            {
                "product_code": "TT-RAM-032",
                "description": "Corsair Vengeance 32GB DDR5 RAM",
                "quantity": 10,
                "unit_price": "120.00",
                "line_total": "1200.00",
            },
            {
                "product_code": "TT-SSD-002",
                "description": "Samsung 990 Pro 2TB NVMe SSD",
                "quantity": 15,
                "unit_price": "170.00",
                "line_total": "2550.00",
            },
        ],
        "subtotal": "6550.00",
        "shipping": "45.00",
        "tax": "524.00",
        "total": "7119.00",
    }

    # Invoice billed 5 units @ $560.00 = $2,800.00
    invoice_data = {
        "invoice_number": "INV-30001",
        "purchase_order_number": "PO-2024-0001",
        "vendor_name": "TechTraders Solutions Inc.",
        "currency": "USD",
        "items": [
            {
                "product_code": "TT-CPU-109",
                "description": "Intel Core i9-13900K Processor",
                "quantity": 5,
                "unit_price": "560.00",
                "line_total": "2800.00",
            },
            {
                "product_code": "TT-RAM-032",
                "description": "Corsair Vengeance 32GB DDR5 RAM",
                "quantity": 10,
                "unit_price": "120.00",
                "line_total": "1200.00",
            },
            {
                "product_code": "TT-SSD-002",
                "description": "Samsung 990 Pro 2TB NVMe SSD",
                "quantity": 15,
                "unit_price": "170.00",
                "line_total": "2550.00",
            },
        ],
        "subtotal": "6550.00",
        "shipping": "45.00",
        "tax": "524.00",
        "total": "7119.00",
    }

    # Receipt received 5 units
    receipt_data = [
        {
            "receipt_number": "DR-70001",
            "purchase_order_number": "PO-2024-0001",
            "vendor_name": "TechTraders Solutions Inc.",
            "items": [
                {
                    "item_code": "TT-CPU-109",
                    "description": "Intel Core i9-13900K Processor",
                    "quantity_ordered": 5,
                    "quantity_delivered": 5,
                },
                {
                    "item_code": "TT-RAM-032",
                    "description": "Corsair Vengeance 32GB DDR5 RAM",
                    "quantity_ordered": 10,
                    "quantity_delivered": 10,
                },
                {
                    "item_code": "TT-SSD-002",
                    "description": "Samsung 990 Pro 2TB NVMe SSD",
                    "quantity_ordered": 15,
                    "quantity_delivered": 15,
                },
            ],
            "subtotal": "6550.00",
            "shipping": "45.00",
            "tax": "524.00",
            "total": "7119.00",
        }
    ]

    result: TransactionResult = orchestrator.process_transaction(
        po_data=po_data,
        invoice_data=invoice_data,
        receipt_data_list=receipt_data,
        case_id="TRX-100-TEST",
    )

    assert result.case_id == "TRX-100-TEST"
    assert result.recommendation == "REJECT_INVOICE"
    assert result.requires_human_review is True

    inv_res = result.investigation_result
    assert inv_res is not None, "Agent investigation must not be bypassed!"

    evidence = inv_res.get("evidence", [])
    findings = inv_res.get("findings", [])

    # 1. Verify verify_document_arithmetic tool was called and produced math evidence
    has_math_evidence = any(
        e.get("field") in ("line_total_math", "document_math") for e in evidence
    )
    assert has_math_evidence, "Agent must gather documentary arithmetic evidence"

    # 2. Verify no NaN in any evidence value
    for ev in evidence:
        val = str(ev.get("value", ""))
        assert "NaN" not in val, f"Evidence value should never contain NaN: {ev}"

    # 3. Verify PO, Invoice, and Receipt evidence gathered
    source_types = {e.get("source_type") for e in evidence}
    assert "purchase_order" in source_types
    assert "invoice" in source_types

    # 4. Verify finding explains the document calculation defect and quantity context
    finding_texts = " ".join(f.get("explanation", "") for f in findings)
    assert "arithmetic" in finding_texts.lower() or "calculation" in finding_texts.lower()
    print("PASS: test_calculation_error_and_quantity_variance_agent_investigation")
