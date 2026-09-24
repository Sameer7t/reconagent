/**
 * ReconAgent Frontend TypeScript Interfaces & Contracts
 */

export interface SourceDocumentRef {
  id?: string;
  file_name?: string;
  file_path?: string;
  doc_type: 'PURCHASE_ORDER' | 'INVOICE' | 'RECEIPT' | 'UNKNOWN';
}

export interface CaseSummary {
  case_id: string;
  vendor_name?: string;
  po_number?: string;
  invoice_number?: string;
  receipt_number?: string;
  receipt_numbers?: string[];
  po_file?: string;
  invoice_file?: string;
  receipt_files?: string[];
  source_files?: string[] | { po?: string; invoice?: string; receipt?: string };
  status: string; // MATCHED, PRICE_MISMATCH, QUANTITY_MISMATCH, MISSING_DOCUMENT
  action?: string; // Eligible for Payment, Review Required, Approved, Rejected, Escalated
  recommendation?: string;
  confidence?: string;
  requires_human_review?: boolean;
  discrepancy_count?: number;
  po_amount?: number;
  invoice_amount?: number;
  difference?: number;
  created_at?: string;
  completed_at?: string;
}

export const isCaseCleanMatched = (c: CaseSummary): boolean => {
  const status = (c.status || '').toUpperCase();
  const rec = (c.recommendation || '').toUpperCase();

  // If case is rejected, has errors, mismatches, or positive discrepancy count, it is NOT matched
  if (
    status === 'REJECTED' ||
    rec === 'REJECT_INVOICE' ||
    status.includes('MISMATCH') ||
    status.includes('ERROR') ||
    status.includes('FLAGGED') ||
    status.includes('SHORTAGE') ||
    status.includes('FAIL') ||
    (typeof c.discrepancy_count === 'number' && c.discrepancy_count > 0)
  ) {
    return false;
  }

  // A case is clean matched only if its status is clean match or completed with 0 discrepancies
  return (
    status === 'MATCHED' ||
    status === 'MATCHED_WITH_TOLERANCE' ||
    status === 'CLEAN' ||
    (status === 'COMPLETED' && (!c.discrepancy_count || c.discrepancy_count === 0))
  );
};

export const doesCaseHaveDiscrepancy = (c: CaseSummary): boolean => {
  return !isCaseCleanMatched(c);
};

export interface ThreeWayLineItem {
  line_number: number;
  description: string;
  po_quantity: number | null;
  invoice_quantity: number | null;
  receipt_quantity: number | null;
  po_unit_price: number | null;
  invoice_unit_price: number | null;
  receipt_unit_price: number | null;
  po_total: number | null;
  invoice_total: number | null;
  receipt_total: number | null;
  variance_flag?: 'NONE' | 'PRICE' | 'QUANTITY' | 'MISSING';
}

export interface ThreeWayMatchData {
  case_id: string;
  vendor_name: string;
  po_id?: string;
  invoice_id?: string;
  receipt_id?: string;
  po_file_name?: string;
  invoice_file_name?: string;
  receipt_file_name?: string;
  po_file_path?: string;
  invoice_file_path?: string;
  receipt_file_path?: string;
  created_at?: string;
  completed_at?: string;
  lines: ThreeWayLineItem[];
  total_po: number;
  total_invoice: number;
  total_receipt: number;
  difference_amount: number;
  difference_percent: number;
  match_status: 'MATCHED' | 'PRICE_MISMATCH' | 'QUANTITY_MISMATCH' | 'MISSING_DOCUMENT' | 'CALCULATION_ERROR' | 'DISCREPANCY_FLAGGED';
  mismatch_badge: string;
}

export interface ProvenanceField {
  label: string;
  value: string;
  source_document: string;
  field_name: string;
  line_number?: number;
}

export interface DeepEvidenceProvenance {
  finding: string;
  variance_type: string;
  po_field: ProvenanceField;
  invoice_field: ProvenanceField;
  receipt_field?: ProvenanceField;
  difference_text: string;
  authorization_status: {
    is_authorized: boolean;
    note: string;
    approval_ref?: string;
  };
  verified_checks: string[];
}

export interface InvestigationData {
  case_id: string;
  transaction_id: string;
  flagged_reason: string;
  investigation_steps: Array<{
    step: number;
    action: string;
    tool: string;
    findings: string;
  }>;
  evidence_citations: Array<{
    document: string;
    field: string;
    value: string;
    notes: string;
  }>;
  agent_conclusion: string;
  agent_recommendation: string; // REQUEST_CREDIT_MEMO, APPROVE_PAYMENT, REJECT_INVOICE, ESCALATE
  confidence_score: number;
  provenance: DeepEvidenceProvenance;
  last_decision?: ReviewDecisionRecord;
}

export interface ReviewDecisionRecord {
  case_id: string;
  reviewer: string;
  decision: 'APPROVE' | 'REJECT' | 'ESCALATE';
  original_recommendation: string;
  reviewer_decision: string;
  reason: string;
  timestamp: string;
}

export interface DocumentContentData {
  file_name: string;
  file_path: string;
  content: string;
  file_size_bytes: number;
  is_binary: boolean;
  document_type?: string;
}

export interface MetricCounts {
  total_cases: number;
  matched: number;
  discrepancies: number;
  under_review: number;
}

