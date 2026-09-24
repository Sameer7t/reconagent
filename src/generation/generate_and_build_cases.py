import os
import re
import time
import json
import logging
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

# ============================================================
# CONFIGURATION & GLOBAL PATHS
# ============================================================
# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("UnifiedDataPipeline")

# Dynamically resolve one level above the script directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASE_MOCK_DIR = PROJECT_ROOT / "dataset" / "mock_reconciliation"

PO_DIR = BASE_MOCK_DIR / "purchase_orders"
RECEIPT_DIR = BASE_MOCK_DIR / "receipts"
INVOICE_DIR = BASE_MOCK_DIR / "invoices"
CASES_DIR = BASE_MOCK_DIR / "cases"
GROUND_TRUTH_FILE = BASE_MOCK_DIR / "ground_truth_labels.json"

# Generation Constants
MODEL_NAME = "gemini-3.5-flash"
MAX_RETRIES = 5
BASE_DELAY_SECONDS = 2
BACKOFF_FACTOR = 2.0

# 5 API Calls generating 20 highly detailed cases each = 100 Total Cases
API_CALLS_TO_MAKE = 5
CASES_PER_CALL = 20
REQUEST_DELAY_SECONDS = 60

# ============================================================
# PHASE 1: SYNTHETIC DATA GENERATOR
# ============================================================
EDGE_CASE_PROMPT = f"""
You are an expert financial data generation AI. Create exactly {CASES_PER_CALL} high-fidelity, realistic transaction triplets (Purchase Order, Delivery Receipt, Invoice) for a 3-way reconciliation engine test.

CRITICAL REALISM INSTRUCTIONS (MIMIC REAL OCR DOCUMENTS):
Do NOT worry about token limits. Put full effort into generating extremely detailed, lengthy, and highly realistic document layouts.
1. Include realistic company headers (fake addresses, phone numbers, tax IDs, websites).
2. Use dense ASCII tabular layouts for line items (simulate spacing and columns for SKU, Description, Qty, Unit Price, Total).
3. Include standard billing terminology ("Bill To:", "Ship To:", "Remit To:", "Date:", "Due Date:").
4. Include standard business footers (Payment Terms like "Net 30", Delivery Terms like "FOB", Bank Details, "Thank you for your business").
5. Generate complex pricing (shipping charges, tax rates, sub-totals, varied unit prices).
6. Introduce realistic, sometimes messy formatting spacing to simulate scanned OCR document text.

CRITICAL EXTRACTION RULES (Must be followed for our regex to work):
1. Purchase Order Number MUST be formatted as exactly "PO-XXXX-XXXX" (e.g., PO-1234-5678) across ALL documents.
2. Invoice Number MUST be formatted as exactly "INV-XXXX" (e.g., INV-9876).
3. Receipt Number MUST be formatted as exactly "REC-XXXX" or "DR-XXXX" (e.g., REC-5555).
4. The Vendor or Supplier name MUST be explicitly prefixed with "VENDOR: " or "SUPPLIER: " on its own line (e.g., VENDOR: Acme Global Industries) across ALL documents.

For EACH triplet, randomly select ONE of the following scenarios to generate:
1. PERFECT_MATCH: All details, quantities, items, and prices match perfectly across all 3 documents.
2. QUANTITY_SHORTAGE: The Receipt shows fewer items delivered than the PO. The Invoice incorrectly bills for the original (higher) PO amount.
3. PRICE_VARIANCE: The unit price on the Invoice is higher than the agreed unit price on the PO.
4. MISSING_PO_REF: The Invoice completely omits the Purchase Order number, making automated matching difficult.
5. MATH_ERROR: The line totals on the invoice do not mathematically add up to the subtotal or grand total.
6. ITEM_SUBSTITUTION: The Receipt shows a different SKU/Item Name than the PO. The Invoice matches the Receipt.

Return ONLY a valid JSON object with a single key "cases" that contains a list of exactly {CASES_PER_CALL} objects. 
Each object MUST have exactly these keys: 
- "scenario_type": The exact name of the scenario.
- "purchase_order": The raw textual layout of the PO.
- "receipt": The raw textual layout of the Receipt.
- "invoice": The raw textual layout of the Invoice.
"""

def _generate_with_exponential_backoff(client: genai.Client) -> Optional[dict]:
    """Executes Gemini API calls with exponential backoff for rate limiting."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=EDGE_CASE_PROMPT,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.9
                )
            )
            return json.loads(response.text)

        except Exception as exc:
            if attempt == MAX_RETRIES:
                logger.error(f"Final retry limit reached ({MAX_RETRIES}). Generation failed: {exc}", exc_info=True)
                return None

            sleep_duration = BASE_DELAY_SECONDS * (BACKOFF_FACTOR ** (attempt - 1))
            logger.warning(f"API call failed: {exc}. Retrying in {sleep_duration:.2f}s...")
            time.sleep(sleep_duration)
    return None

def generate_mock_datasets() -> bool:
    """Generates synthetic documents in large batches and saves them to disk."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.critical("GEMINI_API_KEY is not configured. Aborting pipeline.")
        return False

    try:
        for directory in [PO_DIR, RECEIPT_DIR, INVOICE_DIR, CASES_DIR]:
            directory.mkdir(parents=True, exist_ok=True)

        client = genai.Client(api_key=api_key)
        total_successful_cases = 0
        ground_truth_records = {}

        logger.info(f"Initiating {API_CALLS_TO_MAKE} API calls, generating {CASES_PER_CALL} highly detailed cases per call (Goal: {API_CALLS_TO_MAKE * CASES_PER_CALL} cases)...")

        for call_index in range(1, API_CALLS_TO_MAKE + 1):
            logger.info(f"=== DISPATCHING API CALL {call_index}/{API_CALLS_TO_MAKE} ===")
            mock_data = _generate_with_exponential_backoff(client)

            if mock_data and "cases" in mock_data:
                cases_list = mock_data["cases"]
                
                for case_obj in cases_list:
                    total_successful_cases += 1
                    transaction_id = f"TRX_{int(time.time())}_{total_successful_cases:03d}"
                    
                    try:
                        (PO_DIR / f"{transaction_id}_po.txt").write_text(case_obj.get("purchase_order", ""))
                        (RECEIPT_DIR / f"{transaction_id}_receipt.txt").write_text(case_obj.get("receipt", ""))
                        (INVOICE_DIR / f"{transaction_id}_invoice.txt").write_text(case_obj.get("invoice", ""))
                        
                        scenario = case_obj.get("scenario_type", "UNKNOWN")
                        ground_truth_records[transaction_id] = scenario
                        logger.info(f"Generated {transaction_id} -> {scenario}")
                    except Exception as write_err:
                        logger.error(f"Failed writing files for {transaction_id}: {write_err}")
            else:
                logger.error(f"API Call {call_index} did not return the expected JSON array structure.")
            
            # Enforce 1 request per minute, but skip the delay on the final iteration
            if call_index < API_CALLS_TO_MAKE:
                logger.info(f"Pausing for {REQUEST_DELAY_SECONDS} seconds to respect API rate limits...")
                time.sleep(REQUEST_DELAY_SECONDS)

        if ground_truth_records:
            GROUND_TRUTH_FILE.write_text(json.dumps(ground_truth_records, indent=4))
        
        logger.info(f"Generation Complete: {total_successful_cases}/{API_CALLS_TO_MAKE * CASES_PER_CALL} total cases created.")
        return True

    except Exception as batch_err:
        logger.critical(f"Critical failure during data generation: {batch_err}", exc_info=True)
        return False

# ============================================================
# PHASE 2: CASE BUILDER & CLASSIFICATION
# ============================================================
def extract_po_number(text: str):
    patterns = [r"\bPO[-\s:]*(?:NUMBER|NO|#)?[-\s]*(\d{4}-\d+)\b", r"\bPO[-\s]*(\d{4}-\d+)\b"]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match: return f"PO-{match.group(1)}".upper()
    return None

def extract_invoice_number(text: str):
    patterns = [r"\bINV[-\s:]*(\d+)\b", r"\bINVOICE[-\s]*(?:NUMBER|NO|#)?[-\s:]*(\d+)\b"]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match: return f"INV-{match.group(1)}".upper()
    return None

def extract_receipt_number(text: str):
    patterns = [r"\bDR[-\s:]*(\d+)\b", r"\bREC[-\s:]*(\d+)\b"]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            prefix = "DR" if "DR" in match.group(0).upper() else "REC"
            return f"{prefix}-{match.group(1)}".upper()
    return None

def extract_vendor(text: str):
    patterns = [r"(?:VENDOR|SUPPLIER)\s*(?:NAME)?\s*:\s*(.+)", r"(?:VENDOR|SUPPLIER)\s*:\s*(.+)"]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match: return match.group(1).splitlines()[0].strip()
    return None

def normalize_vendor(vendor):
    if not vendor: return None
    vendor = re.sub(r"[.,]", "", vendor.upper())
    return re.sub(r"\s+", " ", vendor).strip()

def read_document(path: Path, document_type: str):
    text = path.read_text(encoding="utf-8")
    document = {
        "file": path.name,
        "path": str(path),
        "document_type": document_type,
        "text": text,
        "po_number": extract_po_number(text),
        "invoice_number": extract_invoice_number(text),
        "receipt_number": extract_receipt_number(text),
        "vendor": extract_vendor(text),
    }
    document["vendor_normalized"] = normalize_vendor(document["vendor"])
    return document

def load_documents(directory: Path, document_type: str):
    documents = []
    if not directory.exists(): return documents
    for path in sorted(directory.glob("*.txt")):
        try: documents.append(read_document(path, document_type))
        except Exception as e: logger.error(f"Failed reading {path}: {e}")
    return documents

def calculate_match_score(po, document):
    score = 0
    if po["po_number"] and document["po_number"] and po["po_number"] == document["po_number"]: score += 50
    else: return 0
    
    if po["vendor_normalized"] and document["vendor_normalized"] and po["vendor_normalized"] == document["vendor_normalized"]:
        score += 30
        
    if document["text"]: score += 5
    return score

def find_best_match(po, documents):
    candidates = [(calculate_match_score(po, doc), doc) for doc in documents if calculate_match_score(po, doc) > 0]
    if not candidates: return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0]

def create_and_save_cases(purchase_orders, receipts, invoices):
    cases = []
    used_receipts, used_invoices = set(), set()

    for index, po in enumerate(purchase_orders, start=1):
        case_id = f"CASE-{index:04d}"
        receipt_match = find_best_match(po, receipts)
        invoice_match = find_best_match(po, invoices)

        receipt = receipt_match[1] if receipt_match else None
        invoice = invoice_match[1] if invoice_match else None

        if receipt: used_receipts.add(receipt["path"])
        if invoice: used_invoices.add(invoice["path"])

        case = {
            "case_id": case_id,
            "po_number": po["po_number"],
            "vendor": po["vendor"],
            "purchase_order": {"file": po["file"], "path": po["path"]},
            "receipt": {"file": receipt["file"], "path": receipt["path"]} if receipt else None,
            "invoice": {"file": invoice["file"], "path": invoice["path"]} if invoice else None,
            "matching": {
                "receipt_found": receipt is not None,
                "invoice_found": invoice is not None,
                "receipt_score": receipt_match[0] if receipt_match else 0,
                "invoice_score": invoice_match[0] if invoice_match else 0,
            },
        }
        cases.append(case)
        
        # Save directly to disk
        case_dir = CASES_DIR / case_id
        case_dir.mkdir(parents=True, exist_ok=True)
        with open(case_dir / "case.json", "w", encoding="utf-8") as f:
            json.dump(case, f, indent=2)

    return cases, used_receipts, used_invoices

# ============================================================
# PHASE 3: MAIN ORCHESTRATION PIPELINE
# ============================================================
def run_pipeline():
    logger.info("=== STARTING UNIFIED DATA PIPELINE ===")
    
    # Phase 1: Generate Mock Data
    success = generate_mock_datasets()
    if not success:
        logger.error("Data generation failed. Halting pipeline.")
        return

    # Phase 2: Build Cases
    logger.info("Loading generated documents into Case Builder...")
    purchase_orders = load_documents(PO_DIR, "purchase_order")
    receipts = load_documents(RECEIPT_DIR, "receipt")
    invoices = load_documents(INVOICE_DIR, "invoice")

    logger.info(f"Loaded {len(purchase_orders)} POs, {len(receipts)} Receipts, {len(invoices)} Invoices.")

    cases, used_receipts, used_invoices = create_and_save_cases(purchase_orders, receipts, invoices)

    # Calculate unmatched documents
    unmatched_receipts = [r for r in receipts if r["path"] not in used_receipts]
    unmatched_invoices = [i for i in invoices if i["path"] not in used_invoices]

    unmatched = {
        "receipts": [{"file": r["file"], "po_number": r["po_number"], "vendor": r["vendor"]} for r in unmatched_receipts],
        "invoices": [{"file": i["file"], "invoice_number": i["invoice_number"], "po_number": i["po_number"], "vendor": i["vendor"]} for i in unmatched_invoices]
    }

    try:
        with open(CASES_DIR / "unmatched.json", "w", encoding="utf-8") as f:
            json.dump(unmatched, f, indent=2)
    except Exception as err:
        logger.error(f"Failed writing unmatched.json: {err}")

    logger.info("=== PIPELINE COMPLETE ===")
    print(f"\nSuccessfully generated and classified {len(cases)} cases.")
    print(f"Unmatched Receipts: {len(unmatched_receipts)} | Unmatched Invoices: {len(unmatched_invoices)}\n")

if __name__ == "__main__":
    run_pipeline()