"""
Stage 2 — Line-Item Matching.

Addresses out-of-order line items across documents using an explainable,
multi-tier matching hierarchy:
  1. Exact Normalized Description (confidence 1.0)
  2. SKU / Product Code (confidence 1.0)
  3. Vendor Item Code (confidence 1.0)
  4. Fuzzy Description Matching (confidence = similarity ratio >= 0.85)

Uses greedy bipartite assignment with strict numeric variant protection
(prevents 'Model 001' from matching 'Model 002') and token-set reordering.
"""
import difflib
import logging
import re
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

SRC_ROOT = Path(__file__).resolve().parent.parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from schemas.reconciliation import (
    Discrepancy,
    DiscrepancyType,
    LineItemMatch,
    MatchMethod,
    Severity,
)

logger = logging.getLogger("LineItemMatcher")


def normalize_description(text: str) -> str:
    """
    Normalize item description: lowercase, strip, collapse spaces, remove punctuation.
    """
    if not text:
        return ""
    text = text.lower()
    # Remove punctuation characters
    text = re.sub(r'[\.,\-_/\\\'"\(\)\[\]#:]', ' ', text)
    # Collapse multiple whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def normalize_code(code: Optional[str]) -> Optional[str]:
    """
    Normalize item/product codes: uppercase, strip, remove dashes and spaces.
    """
    if not code:
        return None
    code_str = str(code).upper().strip().replace('-', '').replace(' ', '')
    return code_str if code_str else None


def _extract_numbers(s: str) -> Set[str]:
    """Extract all standalone or embedded digit sequences from a string."""
    return set(re.findall(r'\d+', s))


def calculate_similarity(text1: str, text2: str) -> float:
    """
    Calculate similarity ratio between two strings using character sequence,
    token sort, and token set metrics, with strict protection against
    conflicting numbers (e.g. Model 001 vs Model 002).
    """
    if not text1 or not text2:
        return 0.0

    if text1 == text2:
        return 1.0

    # Number conflict check: if both have numbers and their number sets differ,
    # they represent different models/variants and must NOT fuzzy match.
    nums1 = _extract_numbers(text1)
    nums2 = _extract_numbers(text2)
    if nums1 and nums2 and nums1 != nums2:
        return 0.0

    tokens1 = text1.split()
    tokens2 = text2.split()
    set1 = set(tokens1)
    set2 = set(tokens2)

    # Exact token set match (identical words in different order)
    if set1 and set2 and set1 == set2:
        return 1.0

    # Token-set Jaccard similarity
    token_sim = 0.0
    if set1 and set2:
        intersection = set1.intersection(set2)
        union = set1.union(set2)
        token_sim = len(intersection) / len(union)

    # Standard SequenceMatcher
    seq_sim = difflib.SequenceMatcher(None, text1, text2).ratio()

    # Token sort ratio (words sorted alphabetically)
    sorted1 = " ".join(sorted(tokens1))
    sorted2 = " ".join(sorted(tokens2))
    sorted_sim = difflib.SequenceMatcher(None, sorted1, sorted2).ratio()

    return max(seq_sim, sorted_sim, token_sim)


def match_single_pair(
    po_item: Dict[str, Any],
    invoice_item: Dict[str, Any],
    po_index: int,
    invoice_index: int,
    po_id: str = '',
    invoice_id: str = '',
) -> Optional[LineItemMatch]:
    """
    Attempt to match a single PO item to an invoice item using the hierarchy.
    Returns a LineItemMatch if successful, otherwise None.
    """
    po_desc = normalize_description(str(po_item.get('description', '')))
    inv_desc = normalize_description(str(invoice_item.get('description', '')))

    po_code = po_item.get('product_code')
    inv_code = invoice_item.get('product_code')
    norm_po_code = normalize_code(po_code)
    norm_inv_code = normalize_code(inv_code)

    method = None
    confidence = 0.0
    rationale = ""

    if po_desc and inv_desc and po_desc == inv_desc:
        method = MatchMethod.NORMALIZED_DESCRIPTION
        confidence = 1.0
        rationale = "Exact normalized description match."
    elif po_code and inv_code and po_code == inv_code:
        method = MatchMethod.SKU
        confidence = 1.0
        rationale = f"Exact SKU/product code match ({po_code})."
    elif norm_po_code and norm_inv_code and norm_po_code == norm_inv_code:
        method = MatchMethod.VENDOR_ITEM_CODE
        confidence = 1.0
        rationale = f"Normalized product code match ({norm_po_code})."
    else:
        # If both items have explicit product codes and they disagree,
        # they represent distinct SKUs / Item Substitutions and must not be fuzzy matched.
        if po_code and inv_code and norm_po_code != norm_inv_code:
            return None

        sim = calculate_similarity(po_desc, inv_desc)
        if sim >= 0.85:
            method = MatchMethod.FUZZY_DESCRIPTION
            confidence = round(sim, 4)
            rationale = f"Fuzzy description match (similarity: {confidence:.2%})."

    if method:
        ordered_qty = Decimal(str(po_item.get('quantity', 0) or 0))
        invoiced_qty = Decimal(str(invoice_item.get('quantity', 0) or 0))
        ordered_price = Decimal(str(po_item.get('unit_price', 0) or 0))
        invoiced_price = Decimal(str(invoice_item.get('unit_price', 0) or 0))

        return LineItemMatch(
            po_line_id=f"{po_id}-L{po_index+1}",
            invoice_line_id=f"{invoice_id}-L{invoice_index+1}",
            match_method=method,
            match_confidence=confidence,
            match_rationale=rationale,
            po_item=po_item,
            invoice_item=invoice_item,
            ordered_quantity=ordered_qty,
            invoiced_quantity=invoiced_qty,
            received_quantity=Decimal('0'),
            ordered_unit_price=ordered_price,
            invoiced_unit_price=invoiced_price,
            receipt_line_ids=[],
            receipt_items=[],
        )
    return None


def match_line_items(
    po_items: List[Dict[str, Any]],
    invoice_items: List[Dict[str, Any]],
    po_id: str = '',
    invoice_id: str = '',
) -> Tuple[List[LineItemMatch], List[Discrepancy]]:
    """
    Match all PO items to Invoice items using greedy bipartite matching.
    Highest confidence candidate pairs are matched first.
    """
    matches_matrix = []
    for i, po in enumerate(po_items):
        for j, inv in enumerate(invoice_items):
            m = match_single_pair(po, inv, i, j, po_id, invoice_id)
            if m:
                matches_matrix.append((m.match_confidence, i, j, m))

    # Sort by confidence descending
    matches_matrix.sort(key=lambda x: x[0], reverse=True)

    matched_po = set()
    matched_inv = set()
    final_matches = []

    for conf, i, j, match in matches_matrix:
        if i not in matched_po and j not in matched_inv:
            matched_po.add(i)
            matched_inv.add(j)
            final_matches.append(match)

    discrepancies = []

    # Unmatched PO items
    for i, po in enumerate(po_items):
        if i not in matched_po:
            po_line_id = f"{po_id}-L{i+1}"
            desc = po.get('description', '')
            discrepancies.append(Discrepancy(
                type=DiscrepancyType.UNMATCHED_ITEM,
                severity=Severity.HIGH,
                explanation=f"PO line item '{desc}' has no matching invoice line.",
                po_line_id=po_line_id,
                expected_value=desc,
            ))

    # Unmatched Invoice items
    for j, inv in enumerate(invoice_items):
        if j not in matched_inv:
            inv_line_id = f"{invoice_id}-L{j+1}"
            desc = inv.get('description', '')
            discrepancies.append(Discrepancy(
                type=DiscrepancyType.UNMATCHED_ITEM,
                severity=Severity.HIGH,
                explanation=f"Invoice line item '{desc}' has no matching PO line.",
                invoice_line_id=inv_line_id,
                actual_value=desc,
            ))

    return final_matches, discrepancies


def match_receipt_items_to_matches(
    matches: List[LineItemMatch],
    receipt_items: List[Dict[str, Any]],
    receipt_id: str = '',
) -> List[LineItemMatch]:
    """
    Match receipt items to existing LineItemMatches using greedy bipartite matching.
    Prioritizes exact matches, avoids cross-item collisions, and supports partial deliveries.
    """
    if not matches or not receipt_items:
        return matches

    candidate_pairs = []

    for m_idx, match in enumerate(matches):
        po_item = match.po_item or {}
        inv_item = match.invoice_item or {}

        # Use either PO item or Invoice item attributes
        po_desc = normalize_description(str(po_item.get('description') or inv_item.get('description', '')))
        po_code = po_item.get('product_code') or inv_item.get('product_code')
        norm_po_code = normalize_code(po_code)

        for r_idx, r_item in enumerate(receipt_items):
            r_desc = normalize_description(str(r_item.get('description', '')))
            r_code = r_item.get('item_code') or r_item.get('product_code')
            norm_r_code = normalize_code(r_code)

            conf = 0.0
            if po_desc and r_desc and po_desc == r_desc:
                conf = 1.0
            elif po_code and r_code and po_code == r_code:
                conf = 1.0
            elif norm_po_code and norm_r_code and norm_po_code == norm_r_code:
                conf = 1.0
            else:
                if po_code and r_code and norm_po_code != norm_r_code:
                    conf = 0.0
                else:
                    sim = calculate_similarity(po_desc, r_desc)
                    if sim >= 0.85:
                        conf = sim

            if conf > 0.0:
                candidate_pairs.append((conf, m_idx, r_idx, r_item))

    # Sort candidates by confidence descending
    candidate_pairs.sort(key=lambda x: x[0], reverse=True)

    matched_matches_in_receipt = set()
    matched_receipt_indices = set()

    for conf, m_idx, r_idx, r_item in candidate_pairs:
        if m_idx not in matched_matches_in_receipt and r_idx not in matched_receipt_indices:
            matched_matches_in_receipt.add(m_idx)
            matched_receipt_indices.add(r_idx)

            target_match = matches[m_idx]
            r_line_id = f"{receipt_id}-L{r_idx+1}"

            if target_match.receipt_line_ids is None:
                target_match.receipt_line_ids = []
            if target_match.receipt_items is None:
                target_match.receipt_items = []

            target_match.receipt_line_ids.append(r_line_id)
            target_match.receipt_items.append(r_item)

            raw_rq = r_item.get('quantity') if r_item.get('quantity') is not None else (r_item.get('quantity_delivered') if r_item.get('quantity_delivered') is not None else r_item.get('qty', 0))
            rq = Decimal(str(raw_rq or 0))
            if target_match.received_quantity is None:
                target_match.received_quantity = Decimal('0')
            target_match.received_quantity += rq

            # Flexible receipt amount extraction: if present on the receipt item, capture it
            r_price = r_item.get("unit_price") or r_item.get("price")
            if r_price is not None:
                try:
                    target_match.received_unit_price = Decimal(str(r_price))
                except Exception:
                    pass

            r_tot = r_item.get("total") or r_item.get("line_total")
            if r_tot is not None:
                try:
                    target_match.received_total = Decimal(str(r_tot)).quantize(Decimal("0.01"))
                except Exception:
                    pass
            elif target_match.received_unit_price is not None and target_match.received_quantity is not None:
                target_match.received_total = (target_match.received_unit_price * target_match.received_quantity).quantize(Decimal("0.01"))

            if target_match.received_unit_price is None and target_match.received_total is not None and target_match.received_quantity and target_match.received_quantity > Decimal("0"):
                try:
                    target_match.received_unit_price = (target_match.received_total / target_match.received_quantity).quantize(Decimal("0.01"))
                except Exception:
                    pass

    return matches
