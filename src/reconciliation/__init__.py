"""
Reconciliation package for 3-way matching, discrepancy detection,
and investigation-ready case packaging.

Stages:
  1. Document Linking
  2. Header Reconciliation (Vendor, PO Ref, Currency)
  3. Line-Item Matching (Explainable hierarchy)
  4. Quantity Reconciliation (Directional checks)
  5. Price Reconciliation (Configurable tolerances)
  6. Financial Reconciliation (Semantic document-level checks)
  7. Receipt Reconciliation (3-way tabular comparison)
  8. Duplicate Detection (Multi-field fingerprinting)
  9. Discrepancy Engine (Rule-based severity)
  10. Decision Engine (Multi-state status)
"""
import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent.parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

# Pipeline entry points
from reconciliation.pipeline import reconcile_transaction, reconcile_batch

# Stage modules
from reconciliation.document_linker import evaluate_link, batch_link_documents
from reconciliation.header_reconciler import reconcile_headers
from reconciliation.line_item_matcher import match_line_items
from reconciliation.description_reconciler import reconcile_descriptions
from reconciliation.quantity_reconciler import reconcile_quantities
from reconciliation.price_reconciler import reconcile_prices
from reconciliation.financial_reconciler import reconcile_financials
from reconciliation.receipt_reconciler import reconcile_receipts
from reconciliation.duplicate_detector import DuplicateDetector
from reconciliation.discrepancy_engine import enforce_severities
from reconciliation.decision_engine import determine_status, finalize_result

__all__ = [
    # Pipeline
    "reconcile_transaction",
    "reconcile_batch",
    # Stages
    "evaluate_link",
    "batch_link_documents",
    "reconcile_headers",
    "match_line_items",
    "reconcile_descriptions",
    "reconcile_quantities",
    "reconcile_prices",
    "reconcile_financials",
    "reconcile_receipts",
    "DuplicateDetector",
    "enforce_severities",
    "determine_status",
    "finalize_result",
]
