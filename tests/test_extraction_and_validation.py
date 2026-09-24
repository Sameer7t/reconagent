import sys
from decimal import Decimal
from pathlib import Path

# Add src to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from schemas import Invoice, InvoiceItem, InvoiceParty
from validation import verify_invoice_math


def test_valid_invoice_model():
    """Tests that an Invoice Pydantic model with accurate math passes verification."""
    invoice = Invoice(
        invoice_number="INV-2026-001",
        vendor=InvoiceParty(name="Apex Industrial Supplies", address="123 Industrial Way"),
        buyer=InvoiceParty(name="Global Dynamics Corp", address="789 Commerce Blvd"),
        total_quantity=Decimal("15"),
        items=[
            InvoiceItem(
                description="Heavy Duty Widget",
                quantity=Decimal("10"),
                unit_price=Decimal("15.50"),
                unit_discount=Decimal("5.00"),
                unit_tax=Decimal("0.00"),
                line_total=Decimal("150.00"),
            ),
            InvoiceItem(
                description="Stainless Steel Bolt Pack",
                quantity=Decimal("5"),
                unit_price=Decimal("4.20"),
                unit_discount=Decimal("0.00"),
                unit_tax=Decimal("2.00"),
                line_total=Decimal("23.00"),
            ),
        ],
        subtotal=Decimal("173.00"),
        total_discount=Decimal("10.00"),
        total_tax=Decimal("14.94"),
        shipping=Decimal("15.00"),
        rounding_adjustment=Decimal("-0.04"),
        total=Decimal("192.90"),
    )

    result = verify_invoice_math(invoice)
    assert result["is_valid"] is True, f"Expected valid invoice, got: {result}"
    assert result["confidence_score"] == 100.0
    assert result["checks"]["line_items_verified"] is True
    assert result["checks"]["subtotal_verified"] is True
    assert result["checks"]["grand_total_verified"] is True
    assert result["checks"]["total_quantity_verified"] is True
    print("test_valid_invoice_model passed!")


def test_math_error_invoice():
    """Tests that an invoice with deliberate math errors fails verification and lists discrepancies."""
    bad_invoice = {
        "invoice_number": "INV-ERR-2026",
        "total_quantity": 25,  # Actual is 10
        "items": [
            {
                "description": "Faulty Component",
                "quantity": 10,
                "unit_price": 50.00,
                "line_total": 600.00,  # Math error: 10 * 50 = 500
            }
        ],
        "subtotal": 600.00,
        "total": 500.00,  # Grand total error: subtotal 600 != total 500
    }

    result = verify_invoice_math(bad_invoice)
    assert result["is_valid"] is False
    assert len(result["discrepancies"]) > 0
    print("test_math_error_invoice passed with detected discrepancies:", result["discrepancies"])


def test_batch_verification_workflow():
    """Tests the simulated extraction-then-validation batch pipeline."""
    # Simulated extraction records
    mock_extracted_records = [
        {
            "file_name": "invoice_001.pdf",
            "file_path": "/path/to/invoice_001.pdf",
            "extracted_data": {
                "invoice_number": "INV-1001",
                "items": [
                    {"description": "Item A", "quantity": 2, "unit_price": 50.0, "line_total": 100.0}
                ],
                "subtotal": 100.0,
                "total": 100.0,
            },
        },
        {
            "file_name": "invoice_002.pdf",
            "file_path": "/path/to/invoice_002.pdf",
            "extracted_data": {
                "invoice_number": "INV-1002",
                "items": [
                    {"description": "Item B", "quantity": 1, "unit_price": 200.0, "line_total": 250.0}  # Line error
                ],
                "subtotal": 250.0,
                "total": 300.0,  # Grand total error
            },
        },
    ]

    audited = []
    for record in mock_extracted_records:
        val_report = verify_invoice_math(record["extracted_data"])
        rec_copy = dict(record)
        rec_copy["validation_report"] = val_report
        audited.append(rec_copy)

    assert len(audited) == 2
    assert audited[0]["validation_report"]["is_valid"] is True
    assert audited[1]["validation_report"]["is_valid"] is False
    print("test_batch_verification_workflow passed!")


def test_missing_subtotal_reconciled():
    """Tests that an invoice without an explicit subtotal row passes 100% if line items reconcile with grand total."""
    invoice_data = {
        "invoice_number": "INV-NO-SUBTOTAL-01",
        "items": [
            {"description": "Item A", "quantity": 1, "unit_price": 79.0, "line_total": 79.0},
            {"description": "Item B", "quantity": 1, "unit_price": 19.0, "line_total": 19.0},
            {"description": "Freight", "quantity": 1, "unit_price": 1.24, "line_total": 1.24},
        ],
        "subtotal": None,
        "total": 99.24,
    }

    report = verify_invoice_math(invoice_data)
    assert report["is_valid"] is True
    assert report["confidence_score"] == 100.0
    assert report["checks"]["subtotal_verified"] is True
    assert report["checks"]["grand_total_verified"] is True
    assert len(report["discrepancies"]) == 0
    print("test_missing_subtotal_reconciled passed!")


if __name__ == "__main__":
    test_valid_invoice_model()
    test_math_error_invoice()
    test_batch_verification_workflow()
    test_missing_subtotal_reconciled()
    print("\nALL VERIFICATION TESTS PASSED SUCCESSFULLY!")


