"""
Unit and Integration Tests for AI Investigation Agent Tools & Registry.

Tests:
1. Tool #1: get_purchase_order
2. Tool #2: get_invoice
3. Tool #3: get_receipt
4. Tool #4: get_vendor_history
5. Tool #5: check_authorization
6. Tool #6: find_similar_invoices
7. Tool Registry whitelist enforcement
8. Tool Registry required parameter validation
9. Tool Registry case-scoping data isolation & access denial
10. State provenance tracking and tool_call_count incrementation
"""
import sys
from decimal import Decimal
from pathlib import Path

# Path setup
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent.state import InvestigationState, create_initial_state
from agent.tools import (
    AgentDataStore,
    ToolRegistry,
    get_purchase_order,
    get_invoice,
    get_receipt,
    get_vendor_history,
    check_authorization,
    find_similar_invoices,
    TOOLS,
)


def _setup_test_datastore() -> AgentDataStore:
    """Creates a populated test datastore."""
    store = AgentDataStore()

    # Add PO-8831
    store.add_purchase_order("PO-8831", {
        "purchase_order_number": "PO-8831",
        "vendor_name": "TechTraders Solutions Inc.",
        "currency": "USD",
        "items": [
            {
                "product_code": "TT-CPU-109",
                "description": "Intel Core i9-13900K Processor",
                "quantity": Decimal("10"),
                "unit_price": Decimal("1500.00"),
                "line_total": Decimal("15000.00"),
            },
            {
                "product_code": "TT-RAM-032",
                "description": "Corsair Vengeance 32GB DDR5 RAM",
                "quantity": Decimal("20"),
                "unit_price": Decimal("120.00"),
                "line_total": Decimal("2400.00"),
            }
        ]
    })

    # Add INV-4512 (Current Invoice)
    store.add_invoice("INV-4512", {
        "invoice_number": "INV-4512",
        "purchase_order_number": "PO-8831",
        "vendor_name": "TechTraders Solutions Inc.",
        "currency": "USD",
        "invoice_date": "2024-02-16",
        "items": [
            {
                "product_code": "TT-CPU-109",
                "description": "Intel Core i9-13900K Processor",
                "quantity": Decimal("10"),
                "unit_price": Decimal("1700.00"),
                "line_total": Decimal("17000.00"),
            },
            {
                "product_code": "TT-RAM-032",
                "description": "Corsair Vengeance 32GB DDR5 RAM",
                "quantity": Decimal("20"),
                "unit_price": Decimal("120.00"),
                "line_total": Decimal("2400.00"),
            }
        ],
        "subtotal": Decimal("19400.00"),
        "shipping": Decimal("50.00"),
        "total_tax": Decimal("1552.00"),
        "total": Decimal("21002.00"),
    })

    # Add historical invoices for vendor history
    store.add_invoice("INV-100", {
        "invoice_number": "INV-100",
        "vendor_name": "TechTraders Solutions Inc.",
        "invoice_date": "2024-01-10",
        "items": [
            {"description": "Intel Core i9-13900K Processor", "unit_price": Decimal("1500.00"), "quantity": Decimal("5")}
        ]
    })
    store.add_invoice("INV-101", {
        "invoice_number": "INV-101",
        "vendor_name": "TechTraders Solutions Inc.",
        "invoice_date": "2024-01-25",
        "items": [
            {"description": "Intel Core i9-13900K Processor", "unit_price": Decimal("1500.00"), "quantity": Decimal("5")}
        ]
    })

    # Add Delivery Receipt DR-8831
    store.add_receipt("DR-8831", {
        "receipt_number": "DR-8831",
        "purchase_order_number": "PO-8831",
        "vendor_name": "TechTraders Solutions Inc.",
        "date": "2024-02-15",
        "items": [
            {
                "description": "Intel Core i9-13900K Processor",
                "quantity_ordered": Decimal("10"),
                "quantity": Decimal("8"),
            },
            {
                "description": "Corsair Vengeance 32GB DDR5 RAM",
                "quantity_ordered": Decimal("20"),
                "quantity": Decimal("20"),
            }
        ]
    })

    # Add Authorization Record for PO-8831
    store.add_authorization("PO-8831", {
        "authorization_id": "AUTH-44",
        "discrepancy_type": "PRICE_MISMATCH",
        "approved_value": "1700.00",
        "approved_by_role": "purchasing_manager",
        "notes": "Emergency factory price adjustment approved by Purchasing Dept."
    })

    return store


def test_tool_get_purchase_order():
    store = _setup_test_datastore()
    res = get_purchase_order("PO-8831", store=store)

    assert "error" not in res
    assert res["po_id"] == "PO-8831"
    assert res["vendor_id"] == "TechTraders Solutions Inc."
    assert res["currency"] == "USD"
    assert len(res["lines"]) == 2
    assert res["lines"][0]["line_id"] == "PO-L1"
    assert res["lines"][0]["description"] == "Intel Core i9-13900K Processor"
    assert res["lines"][0]["unit_price"] == "1500.00"
    assert res["lines"][0]["quantity"] == "10"
    print("  PASS: test_tool_get_purchase_order")


def test_tool_get_invoice():
    store = _setup_test_datastore()
    res = get_invoice("INV-4512", store=store)

    assert "error" not in res
    assert res["invoice_id"] == "INV-4512"
    assert res["vendor"] == "TechTraders Solutions Inc."
    assert res["po_reference"] == "PO-8831"
    assert res["currency"] == "USD"
    assert res["subtotal"] == "19400.00"
    assert res["total"] == "21002.00"
    assert len(res["lines"]) == 2
    assert res["lines"][0]["line_id"] == "INV-L1"
    assert res["lines"][0]["unit_price"] == "1700.00"
    assert res["lines"][0]["line_total"] == "17000.00"
    print("  PASS: test_tool_get_invoice")


def test_tool_get_receipt():
    store = _setup_test_datastore()
    res = get_receipt("DR-8831", store=store)

    assert "error" not in res
    assert res["receipt_id"] == "DR-8831"
    assert res["po_reference"] == "PO-8831"
    assert res["delivery_date"] == "2024-02-15"
    assert len(res["received_lines"]) == 2
    assert res["received_lines"][0]["line_id"] == "REC-L1"
    assert res["received_lines"][0]["quantity_ordered"] == "10"
    assert res["received_lines"][0]["quantity_delivered"] == "8"
    print("  PASS: test_tool_get_receipt")


def test_tool_get_vendor_history():
    store = _setup_test_datastore()
    res = get_vendor_history("TechTraders Solutions Inc.", store=store)

    assert "error" not in res
    assert res["vendor_id"] == "TechTraders Solutions Inc."
    # Should find INV-4512, INV-100, INV-101
    assert len(res["transactions"]) >= 2

    # Filter by item
    filtered = get_vendor_history("TechTraders Solutions Inc.", item_id="Intel Core", store=store)
    for tx in filtered["transactions"]:
        assert "Intel Core" in tx["description"]
        assert tx["unit_price"] in ("1500.00", "1700.00")
    print("  PASS: test_tool_get_vendor_history")


def test_tool_check_authorization():
    store = _setup_test_datastore()

    # Test authorized scenario
    res_auth = check_authorization("PO-8831", discrepancy_type="PRICE_MISMATCH", store=store)
    assert res_auth["authorized"] is True
    assert len(res_auth["records"]) == 1
    assert res_auth["records"][0]["authorization_id"] == "AUTH-44"
    assert res_auth["records"][0]["approved_value"] == "1700.00"
    assert res_auth["records"][0]["approved_by_role"] == "purchasing_manager"

    # Test unauthorized scenario
    res_unauth = check_authorization("PO-8831", discrepancy_type="QUANTITY_MISMATCH", store=store)
    assert res_unauth["authorized"] is False
    assert res_unauth["records"] == []
    print("  PASS: test_tool_check_authorization")


def test_tool_find_similar_invoices():
    store = _setup_test_datastore()
    similar = find_similar_invoices(
        vendor_id="TechTraders Solutions Inc.",
        item_description="Intel Core Processor",
        limit=5,
        store=store
    )

    assert isinstance(similar, list)
    assert len(similar) > 0
    top_hit = similar[0]
    assert "invoice_id" in top_hit
    assert "unit_price" in top_hit
    assert top_hit["similarity_score"] > 0.50
    print("  PASS: test_tool_find_similar_invoices")


def test_registry_validation_and_case_scoping():
    """
    Verifies ToolRegistry security boundary:
    - Rejects unpermitted tools
    - Rejects missing arguments
    - Blocks access to documents not belonging to the case
    - Allows access to documents belonging to the case
    """
    store = _setup_test_datastore()
    registry = ToolRegistry(datastore=store)

    # Setup state for REC-1001 with PO-8831, INV-4512, DR-8831
    state = create_initial_state({
        "case_id": "REC-1001",
        "purchase_order_id": "PO-8831",
        "invoice_id": "INV-4512",
        "receipt_ids": ["DR-8831"],
        "vendor_name": "TechTraders Solutions Inc.",
        "discrepancies": []
    })

    # 1. Reject unknown tool
    err_unknown = registry.validate_and_execute("unauthorized_system_command", {}, state)
    assert "error" in err_unknown
    assert "is not allowed" in err_unknown["error"]

    # 2. Reject missing arguments
    err_missing = registry.validate_and_execute("get_invoice", {}, state)
    assert "error" in err_missing
    assert "Missing required argument 'invoice_id'" in err_missing["error"]

    # 3. Security Case Scoping: Block foreign invoice INV-999999
    err_foreign_inv = registry.validate_and_execute(
        "get_invoice",
        {"invoice_id": "INV-999999"},
        state
    )
    assert "error" in err_foreign_inv
    assert "Access denied: Invoice 'INV-999999' does not belong to case 'REC-1001'" in err_foreign_inv["error"]

    # 4. Security Case Scoping: Block foreign PO PO-9999
    err_foreign_po = registry.validate_and_execute(
        "get_purchase_order",
        {"po_id": "PO-9999"},
        state
    )
    assert "error" in err_foreign_po
    assert "Access denied: Purchase Order 'PO-9999' does not belong to case 'REC-1001'" in err_foreign_po["error"]

    # 5. Security Case Scoping: Block foreign receipt DR-0000
    err_foreign_rcpt = registry.validate_and_execute(
        "get_receipt",
        {"receipt_id": "DR-0000"},
        state
    )
    assert "error" in err_foreign_rcpt
    assert "Access denied: Receipt 'DR-0000' does not belong to case 'REC-1001'" in err_foreign_rcpt["error"]

    # 6. Valid access to matching case documents
    res_valid_inv = registry.validate_and_execute(
        "get_invoice",
        {"invoice_id": "INV-4512"},
        state
    )
    assert "error" not in res_valid_inv
    assert res_valid_inv["invoice_id"] == "INV-4512"

    res_valid_po = registry.validate_and_execute(
        "get_purchase_order",
        {"po_id": "PO-8831"},
        state
    )
    assert "error" not in res_valid_po
    assert res_valid_po["po_id"] == "PO-8831"

    # 7. Check state provenance tracking
    assert len(state["tool_calls"]) > 0
    assert state["tool_call_count"] == len(state["tool_calls"])
    last_call = state["tool_calls"][-1]
    assert last_call["tool"] == "get_purchase_order"
    assert last_call["arguments"] == {"po_id": "PO-8831"}
    print("  PASS: test_registry_validation_and_case_scoping")


def run_all_tests():
    print("\n" + "=" * 60)
    print("RUNNING AGENT INVESTIGATION TOOLS & REGISTRY TEST SUITE")
    print("=" * 60)
    test_tool_get_purchase_order()
    test_tool_get_invoice()
    test_tool_get_receipt()
    test_tool_get_vendor_history()
    test_tool_check_authorization()
    test_tool_find_similar_invoices()
    test_registry_validation_and_case_scoping()
    print("=" * 60)
    print("ALL AGENT INVESTIGATION TOOLS TESTS PASSED (7/7)!")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()

