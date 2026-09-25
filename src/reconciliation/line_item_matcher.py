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


def normalize_unit(u: str) -> str:
    """Normalize unit abbreviations to standard canonical names."""
    u = u.lower().strip()
    if u in ('"', 'in', 'inch', 'inches'):
        return 'in'
    if u in ("'", 'ft', 'feet'):
        return 'ft'
    if u in ('m', 'meter', 'meters'):
        return 'm'
    if u in ('cm', 'centimeter', 'centimeters'):
        return 'cm'
    if u in ('mm', 'millimeter', 'millimeters'):
        return 'mm'
    if u in ('g', 'gram', 'grams'):
        return 'g'
    if u in ('kg', 'kilo', 'kilos', 'kilogram', 'kilograms'):
        return 'kg'
    if u in ('lb', 'lbs', 'pound', 'pounds'):
        return 'lb'
    if u in ('oz', 'ounce', 'ounces'):
        return 'oz'
    if u in ('l', 'liter', 'liters', 'litre', 'litres'):
        return 'l'
    if u in ('ml', 'milliliter', 'milliliters'):
        return 'ml'
    if u in ('gal', 'gallon', 'gallons'):
        return 'gal'
    if u in ('v', 'volt', 'volts'):
        return 'v'
    if u in ('w', 'watt', 'watts'):
        return 'w'
    if u in ('kw', 'kilowatt', 'kilowatts'):
        return 'kw'
    if u in ('a', 'amp', 'amps'):
        return 'a'
    if u in ('hz', 'hertz'):
        return 'hz'
    if u in ('mhz', 'megahertz'):
        return 'mhz'
    if u in ('ghz', 'gigahertz'):
        return 'ghz'
    if u in ('ream', 'reams'):
        return 'ream'
    if u in ('pack', 'pk', 'packs'):
        return 'pack'
    return u


def extract_specs_and_words(text: str) -> Dict[str, Any]:
    """
    Extract specifications (dimensions, measurements, model numbers) and
    isolate real-world descriptive words from an item description.
    """
    if not text:
        return {'dimensions': [], 'measurements': {}, 'codes': set(), 'words': []}

    t = text.lower()
    dimensions = []
    measurements = {}

    # 1. Dimensions (e.g. 4x4, 4 x 8, 2x4x8, 4"x4")
    dim_pat = re.compile(
        r'\b(\d+(?:\.\d+)?)\s*[xX*]\s*(\d+(?:\.\d+)?)(?:\s*[xX*]\s*(\d+(?:\.\d+)?))?\s*(mm|cm|m|in|inch|inches|ft|feet|"|\')?\b'
    )
    for m in dim_pat.finditer(t):
        d1 = float(m.group(1))
        d2 = float(m.group(2))
        d3 = float(m.group(3)) if m.group(3) else None
        u = normalize_unit(m.group(4)) if m.group(4) else ''
        dims = (d1, d2) if d3 is None else (d1, d2, d3)
        dimensions.append((dims, u))
    t = dim_pat.sub(' ', t)

    # 2. Fractions (e.g. 1/2 in, 3/4")
    frac_pat = re.compile(
        r'\b(\d+)\s*/\s*(\d+)\s*(mm|cm|m|meter|meters|in|inch|inches|"|ft|feet|\'|lb|lbs|oz|kg|g)?\b'
    )
    for m in frac_pat.finditer(t):
        val = round(float(m.group(1)) / float(m.group(2)), 4)
        u = normalize_unit(m.group(3)) if m.group(3) else 'fraction'
        measurements[u] = val
    t = frac_pat.sub(' ', t)

    # 3. Measurements with units (e.g. 0.5 mm, 0.10 mm, 20 lb, 10-ream, 10k)
    meas_pat = re.compile(
        r'\b(\d+(?:\.\d+)?)\s*-?\s*(mm|cm|m|meter|meters|in|inch|inches|"|ft|feet|\'|yd|yard|yards|mg|g|gram|grams|kg|kilo|kilos|oz|ounce|ounces|lb|lbs|pound|pounds|ml|l|liter|liters|litre|litres|gal|gallon|gallons|qt|quart|fl\s*oz|pt|pint|v|volt|volts|kv|w|watt|watts|kw|a|amp|amps|ma|hz|khz|mhz|ghz|kb|mb|gb|tb|k|ream|reams|pack|pk|ct|count|box|bx|roll|rl|bundle|case|cs|gsm|mil|gauge|ga)\b'
    )
    for m in meas_pat.finditer(t):
        val = float(m.group(1))
        u = normalize_unit(m.group(2))
        measurements[u] = val
    t = meas_pat.sub(' ', t)

    # 4. Alphanumeric codes / model numbers (e.g. i9-13900k, 001, cat6)
    codes = set()
    num_code_pat = re.compile(r'\b[a-z0-9_-]*\d+[a-z0-9_-]*\b')
    for m in num_code_pat.finditer(t):
        clean_code = re.sub(r'[-_]', '', m.group(0))
        if clean_code:
            codes.add(clean_code)
    t = num_code_pat.sub(' ', t)

    # 5. Descriptive words
    words = re.findall(r'[a-z]{2,}', t)

    return {
        'dimensions': dimensions,
        'measurements': measurements,
        'codes': codes,
        'words': words,
    }


def word_match_score(w1: str, w2: str) -> float:
    """Fuzzy similarity between two single words with typo tolerance."""
    if w1 == w2:
        return 1.0
    if not w1 or not w2:
        return 0.0
    ratio = difflib.SequenceMatcher(None, w1, w2).ratio()
    if ratio >= 0.80:
        return ratio
    # 1 edit distance for words with 3+ letters (e.g., wud vs wood)
    if len(w1) >= 3 and len(w2) >= 3 and abs(len(w1) - len(w2)) <= 1 and ratio >= 0.70:
        return ratio
    return 0.0


def words_similarity(words1: List[str], words2: List[str]) -> float:
    """
    Calculate semantic/fuzzy similarity between two word token lists,
    accounting for typos, out-of-order words, and vendor abbreviations/subsets.
    """
    if not words1 and not words2:
        return 1.0
    if not words1 or not words2:
        return 0.0

    if words1 == words2:
        return 1.0

    # Greedy bipartite word matching with typo tolerance
    used_j = set()
    matched_scores = []

    for w1 in words1:
        best_score = 0.0
        best_j = -1
        for j, w2 in enumerate(words2):
            if j in used_j:
                continue
            score = word_match_score(w1, w2)
            if score > best_score:
                best_score = score
                best_j = j
        if best_j != -1 and best_score >= 0.70:
            used_j.add(best_j)
            matched_scores.append(best_score)
        else:
            matched_scores.append(0.0)

    matched_sum = sum(matched_scores)
    precision = matched_sum / len(words1)
    recall = matched_sum / len(words2)
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

    min_len = min(len(words1), len(words2))
    containment = matched_sum / min_len if min_len > 0 else 0.0

    str1 = " ".join(words1)
    str2 = " ".join(words2)
    seq_ratio = difflib.SequenceMatcher(None, str1, str2).ratio()

    sorted1 = " ".join(sorted(words1))
    sorted2 = " ".join(sorted(words2))
    sorted_ratio = difflib.SequenceMatcher(None, sorted1, sorted2).ratio()

    if containment >= 0.75 and f1 >= 0.60:
        return max(f1, (containment * 0.7 + f1 * 0.3), seq_ratio, sorted_ratio)

    return max(f1, seq_ratio, sorted_ratio)


def compare_item_descriptions(desc1: str, desc2: str) -> Tuple[bool, float, str, str]:
    """
    Compare two item descriptions with strict specification and measurement guards:
    - Real-world words are matched fuzzily (accommodating typos like 'marker' vs 'merker').
    - Measurements (e.g. 0.5 mm vs 0.10 mm) and dimensions (e.g. 4x4 vs 4x8) MUST NOT
      match fuzzily if they conflict.

    Returns:
        (is_match, similarity_score, discrepancy_type_code, explanation)
    """
    if not desc1 and not desc2:
        return True, 1.0, "MATCHED", "Both descriptions empty."
    if not desc1 or not desc2:
        return False, 0.0, "MISSING_DESCRIPTION", "One description is missing."

    p1 = extract_specs_and_words(desc1)
    p2 = extract_specs_and_words(desc2)

    # 1. Dimensions Check: if both specify dimensions and they differ, strict reject
    if p1['dimensions'] and p2['dimensions']:
        d1_set = set(p1['dimensions'])
        d2_set = set(p2['dimensions'])
        if d1_set != d2_set:
            return (
                False,
                0.0,
                "DIMENSION_MISMATCH",
                f"Conflicting dimensions: {p1['dimensions']} vs {p2['dimensions']}",
            )

    # 2. Measurements Check: if both have measurements on the same unit, they must match numerically
    shared_units = set(p1['measurements'].keys()).intersection(set(p2['measurements'].keys()))
    for u in shared_units:
        val1 = p1['measurements'][u]
        val2 = p2['measurements'][u]
        if abs(val1 - val2) > 0.001:
            return (
                False,
                0.0,
                "MEASUREMENT_MISMATCH",
                f"Conflicting measurement for unit '{u}': {val1} vs {val2}",
            )

    # 3. Model Code / Standalone Numbers Check
    if p1['codes'] and p2['codes']:
        if p1['codes'] != p2['codes']:
            return (
                False,
                0.0,
                "CODE_MISMATCH",
                f"Conflicting model codes/numbers: {p1['codes']} vs {p2['codes']}",
            )

    # 4. Descriptive Words Check
    # If there are no words (e.g., pure dimension like "4x4") and specs matched:
    if not p1['words'] and not p2['words']:
        return True, 1.0, "MATCHED", "Specifications matched exactly."

    sim = words_similarity(p1['words'], p2['words'])
    if sim >= 0.70:
        return True, sim, "MATCHED", f"Fuzzy description match (similarity: {sim:.2%})"
    else:
        return False, sim, "DESCRIPTION_MISMATCH", f"Word similarity too low: {sim:.2%}"


def calculate_similarity(text1: str, text2: str) -> float:
    """
    Calculate similarity ratio between two strings using domain-aware description
    comparison. Real-world words match fuzzily; conflicting measurements, dimensions,
    or model variants strictly return 0.0.
    """
    if not text1 or not text2:
        return 0.0
    if text1.strip().lower() == text2.strip().lower():
        return 1.0

    is_match, sim, code, _ = compare_item_descriptions(text1, text2)
    if not is_match:
        if code in ("DIMENSION_MISMATCH", "MEASUREMENT_MISMATCH", "CODE_MISMATCH"):
            return 0.0
        return sim if sim < 0.70 else 0.0
    return sim


def match_single_pair(
    po_item: Dict[str, Any],
    invoice_item: Dict[str, Any],
    po_index: int,
    invoice_index: int,
    po_id: str = '',
    invoice_id: str = '',
) -> Optional[LineItemMatch]:
    """
    Attempt to match a single PO item to an invoice item using the hierarchy:
      1. Exact normalized description
      2. SKU / Product code
      3. Vendor item code
      4. Fuzzy description with strict measurement/dimension guard
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

        is_match, sim, code, reason = compare_item_descriptions(po_desc, inv_desc)
        if is_match and sim >= 0.70:
            method = MatchMethod.FUZZY_DESCRIPTION
            confidence = round(sim, 4)
            rationale = f"Fuzzy description match (similarity: {confidence:.2%})."

    if method:
        ordered_qty = Decimal(str(po_item.get('quantity', 0) or 0))
        invoiced_qty = Decimal(str(invoice_item.get('quantity', 0) or 0))
        ordered_price = Decimal(str(po_item.get('unit_price', 0) or 0))
        invoiced_price = Decimal(str(invoice_item.get('unit_price', 0) or 0))

        # Check specification compatibility for provenance metadata
        is_m, s_score, d_code, _ = compare_item_descriptions(po_desc, inv_desc)
        spec_matched = (d_code not in ("DIMENSION_MISMATCH", "MEASUREMENT_MISMATCH", "CODE_MISMATCH"))

        return LineItemMatch(
            po_line_id=f"{po_id}-L{po_index+1}",
            invoice_line_id=f"{invoice_id}-L{invoice_index+1}",
            match_method=method,
            match_confidence=confidence,
            match_rationale=rationale,
            description_similarity=confidence if method == MatchMethod.FUZZY_DESCRIPTION else 1.0,
            specification_match=spec_matched,
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
                    if sim >= 0.70:
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
