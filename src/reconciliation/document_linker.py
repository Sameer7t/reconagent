import sys
import logging
import difflib
import re
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Any

SRC_ROOT = Path(__file__).resolve().parent.parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from schemas.reconciliation import (
    LinkingConfidence, LinkingEvidence, DocumentLinkResult, ReconciliationPolicy,
    ReconciliationStatus, ReconciliationResult, Discrepancy, DiscrepancyType, Severity
)

logger = logging.getLogger(__name__)

def normalize_vendor(name: str) -> str:
    """
    Normalize vendor name by stripping suffixes, punctuation, and whitespace.
    """
    if not name:
        return ""
    name = name.lower()
    suffixes = [
        r'\bltd\.?\b', r'\binc\.?\b', r'\bllc\.?\b', r'\bcorp\.?\b', 
        r'\bco\.?\b', r'\bcompany\b', r'\bcorporation\b', r'\blimited\b', 
        r'\bgroup\b', r'\bholdings\b', r'\bpty\.?\b', r'\bpvt\.?\b', 
        r'\bsa\b', r'\bgmbh\b', r'\bag\b'
    ]
    for suffix in suffixes:
        name = re.sub(suffix, '', name)
    name = re.sub(r'[^\w\s]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name

def normalize_currency(currency: Optional[str]) -> Optional[str]:
    """
    Map common currency symbols and variations to ISO 4217 codes.
    """
    if not currency:
        return None
    currency = currency.strip()
    if not currency:
        return None
    mapping = {
        '$': 'USD',
        'US$': 'USD',
        'USD$': 'USD',
        'CAD$': 'CAD',
        'CAN$': 'CAD',
        'CA$': 'CAD',
        'A$': 'AUD',
        'AU$': 'AUD',
        'NZ$': 'NZD',
        '€': 'EUR',
        '£': 'GBP',
        '¥': 'JPY',
        '₹': 'INR',
        'RS': 'PKR',
        'RS.': 'PKR',
        'PKR': 'PKR',
        'INR': 'INR',
        'RM': 'MYR',
        'R': 'ZAR'
    }
    upper_c = currency.upper()
    return mapping.get(currency, mapping.get(upper_c, upper_c))


def normalize_po_number(po_str: Optional[str]) -> str:
    """
    Normalize PO number by stripping common prefixes ('PO-', 'PO#', 'P.O.', etc.),
    punctuation, and leading/trailing whitespace.
    """
    if not po_str:
        return ""
    clean = str(po_str).strip()
    clean = re.sub(r'^(P\.?O\.?|PURCHASE[\s\-_]*ORDER)[\s\-_#:]*', '', clean, flags=re.IGNORECASE)
    return clean.strip().upper()


def evaluate_link(
    po_data: dict, 
    invoice_data: dict = None, 
    receipt_data_list: list[dict] = None, 
    policy: ReconciliationPolicy = None
) -> LinkingEvidence:
    """
    Evaluate linking confidence between PO, Invoice, and Receipts.
    Returns LinkingEvidence with matched_identifiers and reasons.
    """
    if policy is None:
        policy = ReconciliationPolicy()
        
    score = 0
    matched_identifiers = []
    reasons = []
    
    has_invoice = bool(invoice_data)
    invoice_data = invoice_data or {}
    receipt_data_list = receipt_data_list or []
    
    po_num = po_data.get('purchase_order_number')
    norm_po_num = normalize_po_number(po_num)
    
    # 1. Strong Identifiers: PO Number (robust to prefixes like PO-10248 vs 10248)
    inv_po = invoice_data.get('purchase_order_number')
    norm_inv_po = normalize_po_number(inv_po)
    if has_invoice and (
        (po_num and inv_po and po_num == inv_po)
        or (norm_po_num and norm_inv_po and norm_po_num == norm_inv_po)
    ):
        score += 55
        matched_identifiers.append('po_number')
        matched_identifiers.append('purchase_order_number (Invoice)')
        reasons.append('Exact PO number match with Invoice')
        
    receipt_po_matches = 0
    for i, receipt in enumerate(receipt_data_list):
        rcpt_po = receipt.get('purchase_order_number')
        norm_rcpt_po = normalize_po_number(rcpt_po)
        if (
            (po_num and rcpt_po and po_num == rcpt_po)
            or (norm_po_num and norm_rcpt_po and norm_po_num == norm_rcpt_po)
        ):
            receipt_po_matches += 1
            matched_identifiers.append(f'purchase_order_number (Receipt {i+1})')
            reasons.append(f'Exact PO number match with Receipt {i+1}')
            
    if receipt_po_matches > 0:
        if has_invoice:
            score += min(receipt_po_matches * 15, 25)
        else:
            # When invoice is absent, receipt matching PO is the primary link
            score += 70

    # 2. Vendor match
    po_vendor = normalize_vendor(po_data.get('vendor_name', ''))
    
    # Get comparison vendor from invoice or first receipt
    candidate_vendors = []
    if has_invoice:
        inv_vendor_raw = invoice_data.get('vendor_name') or invoice_data.get('vendor', {}).get('name', '')
        if inv_vendor_raw:
            candidate_vendors.append(('Invoice', normalize_vendor(inv_vendor_raw)))
    for i, r in enumerate(receipt_data_list):
        r_vendor = r.get('vendor_name', '')
        if r_vendor:
            candidate_vendors.append((f'Receipt {i+1}', normalize_vendor(r_vendor)))

    vendor_matched = False
    for doc_type, cand_vendor in candidate_vendors:
        if po_vendor and cand_vendor:
            if po_vendor == cand_vendor:
                score += 20
                matched_identifiers.append(f'vendor_name ({doc_type})')
                reasons.append(f'Exact vendor name match with {doc_type}')
                vendor_matched = True
                break
            else:
                ratio = difflib.SequenceMatcher(None, po_vendor, cand_vendor).ratio()
                if ratio >= 0.80:
                    score += 10
                    matched_identifiers.append(f'vendor_name (fuzzy {doc_type})')
                    reasons.append(f'Fuzzy vendor name match with {doc_type} (ratio {ratio:.2f})')
                    vendor_matched = True
                    break

    # 3. Currency match
    po_curr = normalize_currency(po_data.get('currency'))
    inv_curr = normalize_currency(invoice_data.get('currency'))
    if po_curr and inv_curr and po_curr == inv_curr:
        score += 5
        matched_identifiers.append('currency')
        reasons.append('Currency match')
        
    # 4. Date proximity
    po_date = po_data.get('order_date')
    inv_date = invoice_data.get('invoice_date')
    if po_date and inv_date and po_date <= inv_date:
        score += 5
        matched_identifiers.append('date_proximity')
        reasons.append('Order date is before or equal to invoice date')
        
    # 5. Total amount proximity
    try:
        po_total = float(po_data.get('total', 0))
        inv_total = float(invoice_data.get('total', 0))
        if po_total > 0 and inv_total > 0:
            diff_ratio = abs(po_total - inv_total) / max(po_total, inv_total)
            if diff_ratio <= 0.20:
                score += 5
                matched_identifiers.append('total_amount_proximity')
                reasons.append('Total amounts are within 20%')
    except (ValueError, TypeError):
        pass
        
    score_normalized = min(score / 100.0, 1.0)
    
    if score_normalized >= getattr(policy, 'min_link_confidence_auto', 0.85):
        confidence = LinkingConfidence.HIGH
    elif score_normalized >= getattr(policy, 'min_link_confidence_review', 0.50):
        confidence = LinkingConfidence.MEDIUM
    else:
        confidence = LinkingConfidence.LOW
        
    return LinkingEvidence(
        confidence=confidence,
        score=score_normalized,
        matched_identifiers=matched_identifiers,
        reasons=reasons
    )

def detect_missing_documents(
    po_data: dict = None, 
    invoice_data: dict = None, 
    receipt_data_list: list[dict] = None
) -> list[str]:
    """
    Identify which document types are missing from the case.
    """
    missing = []
    if not po_data:
        missing.append('PURCHASE_ORDER')
    if not invoice_data:
        missing.append('INVOICE')
    if not receipt_data_list:
        missing.append('RECEIPT')
    return missing

def link_transaction(
    po_data: dict = None, 
    invoice_data: dict = None, 
    receipt_data_list: list[dict] = None, 
    case_id: str = None, 
    policy: ReconciliationPolicy = None
) -> ReconciliationResult:
    """
    Link transaction documents and determine initial status.
    """
    if policy is None:
        policy = ReconciliationPolicy()
        
    missing_docs = detect_missing_documents(po_data, invoice_data, receipt_data_list)
    
    if not po_data:
        return ReconciliationResult(
            case_id=case_id or "",
            status=ReconciliationStatus.UNMATCHED,
            missing_documents=missing_docs,
            linking_evidence=None
        )
        
    evidence = evaluate_link(po_data, invoice_data, receipt_data_list, policy)
    
    status = ReconciliationStatus.MATCHED
    if evidence.confidence == LinkingConfidence.HIGH:
        status = ReconciliationStatus.MATCHED
    elif evidence.confidence == LinkingConfidence.MEDIUM:
        status = ReconciliationStatus.REVIEW_REQUIRED
    else:
        status = ReconciliationStatus.UNMATCHED
        
    if missing_docs:
        status = ReconciliationStatus.INCOMPLETE
        
    return ReconciliationResult(
        case_id=case_id or "",
        status=status,
        missing_documents=missing_docs,
        linking_evidence=evidence,
        purchase_order_id=po_data.get('purchase_order_number'),
        invoice_id=invoice_data.get('invoice_number') if invoice_data else None,
        receipt_ids=[r.get('receipt_number') for r in (receipt_data_list or []) if r.get('receipt_number')]
    )

def batch_link_documents(
    purchase_orders: list[dict], 
    invoices: list[dict], 
    receipts: list[dict], 
    policy: ReconciliationPolicy = None
) -> tuple[list[ReconciliationResult], dict]:
    """
    Process batches of documents to form linked cases.
    Groups by PO number first.
    Returns linked cases and unmatched documents dict.
    """
    if policy is None:
        policy = ReconciliationPolicy()
        
    cases = []
    unmatched = {
        'purchase_orders': [],
        'invoices': [],
        'receipts': []
    }
    
    po_map = {po.get('purchase_order_number'): po for po in purchase_orders if po.get('purchase_order_number')}
    
    # Track unmatched POs if any don't have a PO number
    for po in purchase_orders:
        if not po.get('purchase_order_number'):
            unmatched['purchase_orders'].append(po)
    
    # Group invoices
    inv_map = {}
    for inv in invoices:
        po_num = inv.get('purchase_order_number')
        if po_num in po_map:
            inv_map[po_num] = inv
        else:
            unmatched['invoices'].append(inv)
            
    # Group receipts
    rec_map = {}
    for rec in receipts:
        po_num = rec.get('purchase_order_number')
        if po_num in po_map:
            if po_num not in rec_map:
                rec_map[po_num] = []
            rec_map[po_num].append(rec)
        else:
            unmatched['receipts'].append(rec)
            
    # Process linked cases
    for po_num, po_data in po_map.items():
        case_id = f"case_{po_num}"
        inv_data = inv_map.get(po_num)
        rec_data = rec_map.get(po_num, [])
        
        result = link_transaction(po_data, inv_data, rec_data, case_id, policy)
        cases.append(result)
        
    return cases, unmatched
