import sys
import json
import hashlib
import logging
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional, List, Dict, Any

SRC_ROOT = Path(__file__).resolve().parent.parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from schemas.reconciliation import Discrepancy, DiscrepancyType, Severity

logger = logging.getLogger(__name__)

def build_invoice_fingerprint(invoice_data: Dict[str, Any]) -> str:
    """
    Build a unique fingerprint for an invoice to detect exact duplicates.
    
    Normalizes and combines key invoice fields, then returns a SHA-256 hash.
    
    Args:
        invoice_data (Dict[str, Any]): The invoice data dictionary.
        
    Returns:
        str: A SHA-256 hex digest of the normalized combined fields.
    """
    vendor_data = invoice_data.get('vendor', '')
    vendor_name = vendor_data.get('name', '') if isinstance(vendor_data, dict) else vendor_data
    
    # Normalize vendor name: lowercase, strip suffixes, strip whitespace
    vendor_name = vendor_name.lower().strip()
    vendor_name = re.sub(r'\b(ltd|inc|llc|corp|co)\b\.?$', '', vendor_name).strip()
    vendor_name = vendor_name.strip(',').strip()
    
    invoice_number = str(invoice_data.get('invoice_number', '')).upper().strip()
    invoice_date = str(invoice_data.get('invoice_date', '')).strip()
    currency = str(invoice_data.get('currency', '')).upper().strip()
    
    try:
        total_val = invoice_data.get('total', 0)
        total = str(Decimal(str(total_val)))
    except Exception:
        total = '0'
        
    po_number = invoice_data.get('purchase_order_number')
    if po_number:
        po_number = str(po_number).upper().strip()
    else:
        po_number = 'NONE'
        
    combined = f"{vendor_name}|{invoice_number}|{invoice_date}|{currency}|{total}|{po_number}"
    return hashlib.sha256(combined.encode('utf-8')).hexdigest()

class DuplicateDetector:
    """
    Detects duplicate invoices by maintaining a ledger of previously seen invoices.
    """
    def __init__(self, ledger_path: Optional[Path] = None):
        """
        Initialize the DuplicateDetector.
        
        Args:
            ledger_path (Optional[Path]): Path to the JSON ledger file.
                Defaults to src/dataset/ledger/invoice_ledger.json.
        """
        if ledger_path is None:
            self.ledger_path = SRC_ROOT / 'dataset' / 'ledger' / 'invoice_ledger.json'
        else:
            self.ledger_path = Path(ledger_path)
            
        self._ledger: Dict[str, Dict[str, Any]] = {}
        self.load_ledger()
        
    def load_ledger(self) -> None:
        """
        Load the ledger from the JSON file if it exists.
        """
        if self.ledger_path.exists():
            try:
                with open(self.ledger_path, 'r', encoding='utf-8') as f:
                    self._ledger = json.load(f)
                logger.info(f"Loaded {len(self._ledger)} entries from ledger.")
            except Exception as e:
                logger.error(f"Failed to load ledger from {self.ledger_path}: {e}")
                self._ledger = {}
        else:
            logger.info("No existing ledger found. Starting fresh.")
            self._ledger = {}
            
    def save_ledger(self) -> None:
        """
        Persist the current ledger to the JSON file. Creates parent directories if needed.
        """
        try:
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.ledger_path, 'w', encoding='utf-8') as f:
                json.dump(self._ledger, f, indent=4)
            logger.info(f"Saved {len(self._ledger)} entries to ledger.")
        except Exception as e:
            logger.error(f"Failed to save ledger to {self.ledger_path}: {e}")
            
    def check_duplicate(self, invoice_data: Dict[str, Any]) -> Optional[Discrepancy]:
        """
        Check if an invoice is a duplicate. If not, register it in the ledger.
        
        Args:
            invoice_data (Dict[str, Any]): The invoice data to check.
            
        Returns:
            Optional[Discrepancy]: A Discrepancy if a duplicate is found, otherwise None.
        """
        fingerprint = build_invoice_fingerprint(invoice_data)
        
        if fingerprint in self._ledger:
            existing_entry = self._ledger[fingerprint]
            existing_id = existing_entry.get('invoice_id', 'UNKNOWN')
            invoice_num = invoice_data.get('invoice_number', 'UNKNOWN')
            
            logger.warning(f"Duplicate invoice detected: {invoice_num} matches {existing_id}")
            return Discrepancy(
                type=DiscrepancyType.DUPLICATE_INVOICE,
                severity=Severity.CRITICAL,
                explanation=f"Duplicate of previously seen invoice {existing_id}",
                document_ids=[str(invoice_num), str(existing_id)],
                details=existing_entry
            )
        else:
            self.register_invoice(invoice_data, fingerprint=fingerprint)
            return None
            
    def register_invoice(self, invoice_data: Dict[str, Any], fingerprint: Optional[str] = None) -> None:
        """
        Add an invoice to the ledger without checking for duplicates.
        
        Args:
            invoice_data (Dict[str, Any]): The invoice data to register.
            fingerprint (Optional[str]): Pre-calculated fingerprint, if available.
        """
        if not fingerprint:
            fingerprint = build_invoice_fingerprint(invoice_data)
            
        invoice_id = invoice_data.get('id', invoice_data.get('invoice_number', 'UNKNOWN'))
        vendor_data = invoice_data.get('vendor', '')
        vendor_name = vendor_data.get('name', '') if isinstance(vendor_data, dict) else vendor_data
        
        try:
            total_val = invoice_data.get('total', 0)
            total = str(Decimal(str(total_val)))
        except Exception:
            total = '0'
            
        self._ledger[fingerprint] = {
            'invoice_id': invoice_id,
            'vendor': vendor_name,
            'date': str(invoice_data.get('invoice_date', '')),
            'total': total,
            'first_seen': datetime.now().isoformat()
        }
        self.save_ledger()
        
    def check_batch(self, invoices: List[Dict[str, Any]]) -> List[Discrepancy]:
        """
        Check multiple invoices for duplicates.
        
        Args:
            invoices (List[Dict[str, Any]]): A list of invoice data dictionaries.
            
        Returns:
            List[Discrepancy]: A list of discrepancies for any found duplicates.
        """
        discrepancies = []
        for invoice in invoices:
            discrep = self.check_duplicate(invoice)
            if discrep:
                discrepancies.append(discrep)
        return discrepancies
