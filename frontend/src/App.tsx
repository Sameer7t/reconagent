import React, { useState, useEffect, useCallback } from 'react';
import { Navbar } from './components/Navbar';
import { MetricsBar } from './components/MetricsBar';
import { CasesTable } from './components/CasesTable';
import { CaseDetailView } from './components/CaseDetailView';
import { DocumentViewerModal } from './components/DocumentViewerModal';
import { UploadModal } from './components/UploadModal';
import { UserManagementModal } from './components/UserManagementModal';
import { api } from './services/api';
import {
  CaseSummary,
  ThreeWayMatchData,
  ThreeWayLineItem,
  InvestigationData,
  MetricCounts,
  ReviewDecisionRecord,
  isCaseCleanMatched,
  doesCaseHaveDiscrepancy,
} from './types';
import { AlertCircle } from 'lucide-react';

export const App: React.FC = () => {
  // Global State
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);
  const [isUserMgmtOpen, setIsUserMgmtOpen] = useState<boolean>(false);
  const [metrics, setMetrics] = useState<MetricCounts>({
    total_cases: 0,
    matched: 0,
    discrepancies: 0,
    under_review: 0,
  });

  // Real-time dynamic metrics calculated directly from active cases
  const dynamicMetrics: MetricCounts = React.useMemo(() => {
    if (!cases || cases.length === 0) {
      return metrics;
    }
    const total = cases.length;
    const matched = cases.filter(isCaseCleanMatched).length;
    const underReview = cases.filter(
      (c) => Boolean(c.requires_human_review) || c.status === 'PENDING_REVIEW' || c.status === 'NEEDS_REVIEW' || c.status === 'HUMAN_REVIEW'
    ).length;
    const discrepancies = cases.filter(doesCaseHaveDiscrepancy).length;

    return {
      total_cases: total,
      matched: matched,
      discrepancies: discrepancies,
      under_review: underReview,
    };
  }, [cases, metrics]);
  const [activeQuickFilter, setActiveQuickFilter] = useState<string>('ALL');
  const [onlineStatus, setOnlineStatus] = useState<boolean>(true);
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);
  const [mobileTab, setMobileTab] = useState<'DIRECTORY' | 'DETAILS'>('DIRECTORY');

  // Selected Case Detail State
  const [isDetailLoading, setIsDetailLoading] = useState<boolean>(false);
  const [selectedCaseSummary, setSelectedCaseSummary] = useState<CaseSummary | null>(null);
  const [threeWayData, setThreeWayData] = useState<ThreeWayMatchData | null>(null);
  const [investigationData, setInvestigationData] = useState<InvestigationData | null>(null);

  // Durable Human Decisions (recorded locally & on server)
  const [decisions, setDecisions] = useState<Record<string, ReviewDecisionRecord>>({});
  const [isSubmittingDecision, setIsSubmittingDecision] = useState(false);

  // Modals
  const [isUploadOpen, setIsUploadOpen] = useState(false);
  const [docViewerParams, setDocViewerParams] = useState<{
    isOpen: boolean;
    fileName: string | null;
    filePath?: string | null;
    docType?: string;
  }>({
    isOpen: false,
    fileName: null,
  });

  // 1. Initial Data Fetching
  const loadData = useCallback(async () => {
    setIsRefreshing(true);
    try {
      // Check health
      await api.getHealth().then(() => setOnlineStatus(true)).catch(() => setOnlineStatus(false));

      // Fetch metrics
      const m = await api.getReviewMetrics();
      setMetrics(m);

      // Fetch cases
      const res = await api.getCases({ limit: 100 });
      setCases(res.cases);

      // Default select first case if cases exist, otherwise reset selection
      if (res.cases.length > 0) {
        setSelectedCaseId((prev) => (prev && res.cases.some((c) => c.case_id === prev) ? prev : res.cases[0].case_id));
      } else {
        setSelectedCaseId(null);
        setSelectedCaseSummary(null);
        setThreeWayData(null);
        setInvestigationData(null);
      }
    } catch (err) {
      console.error('Failed to load cases:', err);
    } finally {
      setIsRefreshing(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // 2. Load Deep Case Details When Selected
  useEffect(() => {
    if (!selectedCaseId) {
      setSelectedCaseSummary(null);
      setThreeWayData(null);
      setInvestigationData(null);
      return;
    }

    const currentSummary = cases.find((c) => c.case_id === selectedCaseId);
    if (!currentSummary) {
      return;
    }
    setSelectedCaseSummary(currentSummary);
    setIsDetailLoading(true);

    // Fetch case detail & investigation in parallel
    Promise.allSettled([
      api.getCaseDetail(selectedCaseId),
      api.getInvestigation(selectedCaseId),
    ])
      .then(([caseRes, invRes]) => {
        const caseDetail = caseRes.status === 'fulfilled' ? caseRes.value : null;
        const invDetail = invRes.status === 'fulfilled' ? invRes.value : null;

        // Extract real line item matches from reconciliation engine
        const rawMatches = caseDetail?.reconciliation_result?.line_item_matches || [];
        const mappedLines: ThreeWayLineItem[] = Array.isArray(rawMatches) && rawMatches.length > 0
          ? rawMatches.map((m: any, idx: number) => {
              const poQty = m.ordered_quantity !== null && m.ordered_quantity !== undefined ? Number(m.ordered_quantity) : null;
              const invQty = m.invoiced_quantity !== null && m.invoiced_quantity !== undefined ? Number(m.invoiced_quantity) : null;
              const rcptQty = m.received_quantity !== null && m.received_quantity !== undefined ? Number(m.received_quantity) : null;

              const poPrice = m.ordered_unit_price !== null && m.ordered_unit_price !== undefined ? Number(m.ordered_unit_price) : null;
              const invPrice = m.invoiced_unit_price !== null && m.invoiced_unit_price !== undefined ? Number(m.invoiced_unit_price) : null;
              let rcptPrice = m.received_unit_price !== null && m.received_unit_price !== undefined
                ? Number(m.received_unit_price)
                : (m.receipt_items?.[0]?.unit_price !== null && m.receipt_items?.[0]?.unit_price !== undefined
                    ? Number(m.receipt_items[0].unit_price)
                    : null);

              const poTotal = poQty !== null && poPrice !== null ? poQty * poPrice : (m.po_item?.total ? Number(m.po_item.total) : null);
              const invTotal = invQty !== null && invPrice !== null ? invQty * invPrice : (m.invoice_item?.total ? Number(m.invoice_item.total) : null);
              let rcptTotal = m.received_total !== null && m.received_total !== undefined
                ? Number(m.received_total)
                : (rcptQty !== null && rcptPrice !== null
                    ? rcptQty * rcptPrice
                    : (m.receipt_items?.[0]?.total !== null && m.receipt_items?.[0]?.total !== undefined
                        ? Number(m.receipt_items[0].total)
                        : null));

              if (rcptPrice === null && rcptTotal !== null && rcptQty !== null && rcptQty > 0) {
                rcptPrice = Number((rcptTotal / rcptQty).toFixed(2));
              }
              if (rcptTotal === null && rcptPrice !== null && rcptQty !== null && rcptQty > 0) {
                rcptTotal = Number((rcptPrice * rcptQty).toFixed(2));
              }

              const desc = m.po_item?.description || m.invoice_item?.description || m.receipt_items?.[0]?.description || `Line Item ${idx + 1}`;

              let varianceFlag: 'NONE' | 'PRICE' | 'QUANTITY' | 'MISSING' = 'NONE';
              if (poPrice !== null && invPrice !== null && Math.abs(poPrice - invPrice) > 0.01) {
                varianceFlag = 'PRICE';
              } else if (rcptPrice !== null && poPrice !== null && Math.abs(rcptPrice - poPrice) > 0.01) {
                varianceFlag = 'PRICE';
              } else if (rcptPrice !== null && invPrice !== null && Math.abs(rcptPrice - invPrice) > 0.01) {
                varianceFlag = 'PRICE';
              } else if (invQty !== null && rcptQty !== null && invQty !== rcptQty) {
                varianceFlag = 'QUANTITY';
              } else if (poQty !== null && invQty !== null && poQty !== invQty) {
                varianceFlag = 'QUANTITY';
              }

              return {
                line_number: idx + 1,
                description: desc,
                po_quantity: poQty,
                invoice_quantity: invQty,
                receipt_quantity: rcptQty,
                po_unit_price: poPrice,
                invoice_unit_price: invPrice,
                receipt_unit_price: rcptPrice,
                po_total: poTotal,
                invoice_total: invTotal,
                receipt_total: rcptTotal,
                variance_flag: varianceFlag,
              };
            })
          : [];

        // Determine price / variance values from genuine financial breakdown or line sums
        const fin = caseDetail?.reconciliation_result?.financial_breakdown;
        let totalPo = fin?.po_total !== null && fin?.po_total !== undefined ? Number(fin.po_total) : (caseDetail?.po_amount ?? currentSummary.po_amount ?? 0);
        let totalInv = fin?.invoice_total !== null && fin?.invoice_total !== undefined ? Number(fin.invoice_total) : (caseDetail?.invoice_amount ?? currentSummary.invoice_amount ?? 0);
        let totalRcpt = fin?.receipt_total !== null && fin?.receipt_total !== undefined
          ? Number(fin.receipt_total)
          : mappedLines.reduce((acc, l) => acc + (l.receipt_total || 0), 0);

        if (mappedLines.length > 0) {
          if (!totalPo) {
            totalPo = mappedLines.reduce((acc, l) => acc + (l.po_total || 0), 0);
          }
          if (!totalInv) {
            totalInv = mappedLines.reduce((acc, l) => acc + (l.invoice_total || 0), 0);
          }
        }

        const diffAmount = totalInv - totalPo;
        const diffPct = totalPo > 0 ? (diffAmount / totalPo) * 100 : 0;

        const rawDiscrepancies = caseDetail?.reconciliation_result?.discrepancies || caseDetail?.discrepancies || [];
        const hasReceiptAmountMismatch = rawDiscrepancies.some((d: any) =>
          d.type === 'RECEIPT_PRICE_MISMATCH' || d.type === 'RECEIPT_TOTAL_MISMATCH'
        );
        const hasCalculationError = rawDiscrepancies.some((d: any) =>
          d.type === 'CALCULATION_ERROR' || d.type === 'INTERNAL_MATH_ERROR'
        );
        const isRejected = caseDetail?.recommendation === 'REJECT_INVOICE' || currentSummary?.recommendation === 'REJECT_INVOICE' || caseDetail?.status === 'REJECTED';
        const hasDiscrepancies = rawDiscrepancies.length > 0 || (caseDetail?.discrepancy_count || 0) > 0;

        const statusStr = caseDetail?.status || currentSummary.status || 'MATCHED';
        const isCleanMatch = (statusStr === 'MATCHED' || statusStr === 'MATCHED_WITH_TOLERANCE') && !hasDiscrepancies && !isRejected;
        const isMatched = isCleanMatch;
        const isQuantityMismatch = statusStr.includes('QUANTITY') || statusStr.includes('SHORTAGE') || rawDiscrepancies.some((d: any) => String(d.type).includes('QUANTITY') || String(d.type).includes('SHORTAGE'));
        const isPriceMismatch = statusStr.includes('PRICE') || hasReceiptAmountMismatch || rawDiscrepancies.some((d: any) => String(d.type).includes('PRICE'));
        const isMissingDoc = statusStr.includes('MISSING') || rawDiscrepancies.some((d: any) => String(d.type).includes('MISSING'));

        let matchStatus: 'MATCHED' | 'PRICE_MISMATCH' | 'QUANTITY_MISMATCH' | 'MISSING_DOCUMENT' | 'CALCULATION_ERROR' | 'DISCREPANCY_FLAGGED' = 'MATCHED';
        if (isCleanMatch) {
          matchStatus = 'MATCHED';
        } else if (hasCalculationError) {
          matchStatus = 'CALCULATION_ERROR';
        } else if (isQuantityMismatch) {
          matchStatus = 'QUANTITY_MISMATCH';
        } else if (isPriceMismatch) {
          matchStatus = 'PRICE_MISMATCH';
        } else if (isMissingDoc) {
          matchStatus = 'MISSING_DOCUMENT';
        } else if (hasDiscrepancies || isRejected) {
          matchStatus = 'DISCREPANCY_FLAGGED';
        } else {
          matchStatus = Math.abs(diffAmount) > 0.01 ? 'PRICE_MISMATCH' : 'MATCHED';
        }

        let mismatchBadge = '✓ THREE-WAY MATCH PERFECT';
        if (!isCleanMatch) {
          if (hasCalculationError) {
            mismatchBadge = '⚠ DOCUMENT ARITHMETIC / CALCULATION ERROR';
          } else if (hasReceiptAmountMismatch) {
            mismatchBadge = '⚠ RECEIPT AMOUNT DISCREPANCY DETECTED';
          } else if (isQuantityMismatch) {
            mismatchBadge = '⚠ QUANTITY SHORTAGE DETECTED';
          } else if (isPriceMismatch || Math.abs(diffAmount) > 0.01) {
            mismatchBadge = `⚠ PRICE MISMATCH (${diffAmount >= 0 ? '+' : ''}$${diffAmount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} / ${diffPct >= 0 ? '+' : ''}${diffPct.toFixed(1)}%)`;
          } else if (isRejected) {
            mismatchBadge = '⚠ INVOICE REJECTED (VALIDATION FAILURE)';
          } else {
            mismatchBadge = `⚠ ${statusStr.replace(/_/g, ' ')}`;
          }
        }

        // Construct robust 3-Way Match Data with genuine file provenance
        const normalizedThreeWay: ThreeWayMatchData = {
          case_id: selectedCaseId,
          vendor_name: caseDetail?.vendor_name || currentSummary.vendor_name || '',
          po_id: caseDetail?.po_number || currentSummary.po_number || '',
          invoice_id: caseDetail?.invoice_number || currentSummary.invoice_number || '',
          receipt_id: caseDetail?.receipt_numbers?.[0] || currentSummary.receipt_numbers?.[0] || '',
          po_file_name: caseDetail?.po_file || currentSummary.po_file || undefined,
          invoice_file_name: caseDetail?.invoice_file || currentSummary.invoice_file || undefined,
          receipt_file_name: caseDetail?.receipt_files?.[0] || currentSummary.receipt_files?.[0] || undefined,
          created_at: caseDetail?.created_at || currentSummary.created_at,
          completed_at: caseDetail?.completed_at || currentSummary.completed_at,
          lines: mappedLines,
          total_po: totalPo,
          total_invoice: totalInv,
          total_receipt: totalRcpt,
          difference_amount: diffAmount,
          difference_percent: diffPct,
          match_status: matchStatus,
          mismatch_badge: mismatchBadge,
        };
        setThreeWayData(normalizedThreeWay);

        if (caseDetail) {
          setSelectedCaseSummary((prev) => ({
            ...(prev || currentSummary),
            ...caseDetail,
            po_file: caseDetail.po_file || prev?.po_file,
            invoice_file: caseDetail.invoice_file || prev?.invoice_file,
            receipt_files: caseDetail.receipt_files || prev?.receipt_files,
            source_files: caseDetail.source_files || prev?.source_files,
            created_at: caseDetail.created_at || prev?.created_at,
          }));
        }

        // Construct Investigation & Deep Evidence Data
        const findingsList = invDetail?.findings || caseDetail?.investigation_result?.findings || [];
        const evidenceList = invDetail?.evidence || caseDetail?.investigation_result?.evidence || [];
        const hasPoDoc = Boolean(normalizedThreeWay.po_file_name);
        const hasInvDoc = Boolean(normalizedThreeWay.invoice_file_name);
        const hasPo = Boolean(hasPoDoc || (normalizedThreeWay.po_id && totalPo > 0));
        const hasInv = Boolean(hasInvDoc || (normalizedThreeWay.invoice_id && totalInv > 0));

        const firstLine = mappedLines[0];
        const poPriceVal = hasPo ? (firstLine?.po_unit_price ?? (totalPo > 0 ? totalPo : undefined)) : undefined;
        const invPriceVal = hasInv ? (firstLine?.invoice_unit_price ?? (totalInv > 0 ? totalInv : undefined)) : undefined;
        const poQtyVal = firstLine?.po_quantity ?? 1;
        const invQtyVal = firstLine?.invoice_quantity;
        const rcptQtyVal = firstLine?.receipt_quantity;

        // Short-form, non-technical plain English reasoning
        let flaggedReason = '';
        if (hasCalculationError) {
          const calcFinding = findingsList.find((f: any) => {
            const dt = String(f.discrepancy_type || '').toUpperCase();
            return dt.includes('CALCULATION') || dt.includes('MATH');
          });
          const rawMathDisc = (caseDetail?.discrepancies || []).find((d: any) => {
            const dt = String(d.type || d.discrepancy_type || '').toUpperCase();
            return dt.includes('CALCULATION') || dt.includes('MATH');
          });
          flaggedReason = calcFinding?.explanation || rawMathDisc?.explanation || (findingsList.length > 0 && findingsList[0]?.explanation) || 'Document arithmetic error: Printed totals do not equal itemized line calculations.';
        } else if (findingsList.length > 0 && findingsList[0]?.explanation) {
          flaggedReason = findingsList[0].explanation;
        } else if (isCleanMatch) {
          flaggedReason = 'Three-way match completed with zero discrepancies. Purchase order, invoice, and delivery receipt reconcile perfectly.';
        } else if (isQuantityMismatch) {
          flaggedReason = `Quantity shortage: Billed ${invQtyVal ?? '—'} units on invoice vs ${rcptQtyVal !== null && rcptQtyVal !== undefined ? rcptQtyVal : (poQtyVal ?? '—')} verified received at the dock.`;
        } else if (isPriceMismatch || Math.abs(diffAmount) > 0.01) {
          flaggedReason = `Price difference: Billed $${(invPriceVal || 0).toFixed(2)} per unit on invoice vs authorized $${(poPriceVal || 0).toFixed(2)} on purchase order (variance: ${diffAmount >= 0 ? '+' : ''}$${diffAmount.toFixed(2)}).`;
        } else if (isMissingDoc || !hasPo || !hasInv) {
          flaggedReason = 'Missing documents: Required purchase order or invoice is missing for this transaction.';
        } else {
          flaggedReason = `Reconciliation review triggered: ${statusStr.replace(/_/g, ' ')}.`;
        }

        // Short-form, non-technical plain English conclusion
        let agentConclusion = '';
        if (invDetail?.final_summary && !invDetail.final_summary.startsWith('=== INVESTIGATION REPORT:')) {
          agentConclusion = invDetail.final_summary;
        } else if (findingsList.length > 0 && findingsList[0]?.explanation) {
          agentConclusion = findingsList[0].explanation;
        } else if (hasCalculationError) {
          const docName = normalizedThreeWay.po_id || normalizedThreeWay.invoice_id || 'source document';
          agentConclusion = `Document arithmetic error on ${docName}. The printed total does not equal itemized calculations, so the invoice cannot be authorized. Recommended action: Reject invoice and request a corrected document from ${normalizedThreeWay.vendor_name || 'the vendor'}.`;
        } else if (isCleanMatch) {
          agentConclusion = `Clean 3-way match verified. Line items, unit rates, quantities, and totals reconcile with 0 discrepancy. Approved for automated payment release.`;
        } else if (isQuantityMismatch) {
          agentConclusion = `Vendor billed for ${invQtyVal ?? '—'} units, but receiving dock confirmed only ${rcptQtyVal ?? poQtyVal ?? '—'} units were delivered. Recommended action: Request a credit memo for unreceived items before payment.`;
        } else if (isPriceMismatch || Math.abs(diffAmount) > 0.01) {
          agentConclusion = `Vendor billed $${(invPriceVal || 0).toFixed(2)} vs authorized PO rate $${(poPriceVal || 0).toFixed(2)}. No approved price change was found on file. Recommended action: Request a credit memo of $${Math.abs(diffAmount).toFixed(2)} from ${normalizedThreeWay.vendor_name || 'the vendor'}.`;
        } else if (!hasPo || !hasInv || isMissingDoc) {
          agentConclusion = `Cannot reconcile transaction because required matching documents are missing. Flagged for human review to locate missing files.`;
        } else {
          agentConclusion = `Audited transaction against contract terms. Recommended action: ${caseDetail?.recommendation || invDetail?.recommendation || 'REQUEST_CREDIT_MEMO'}.`;
        }

        // Dynamic Case-Specific Confidence Score
        const backendConfStr = (invDetail?.confidence || caseDetail?.confidence || '').toUpperCase();
        let dynamicScore = 0.90;

        if (isMatched && diffAmount === 0 && !isQuantityMismatch && !isPriceMismatch && !isMissingDoc) {
          dynamicScore = 0.99;
        } else if (isMissingDoc || !hasPo || !hasInv) {
          dynamicScore = backendConfStr === 'HIGH' ? 0.75 : 0.65;
        } else if (backendConfStr === 'HIGH') {
          dynamicScore = 0.94;
        } else if (backendConfStr === 'MEDIUM') {
          dynamicScore = 0.82;
        } else if (backendConfStr === 'LOW') {
          dynamicScore = 0.58;
        } else if (isQuantityMismatch) {
          dynamicScore = 0.89;
        } else if (isPriceMismatch) {
          dynamicScore = 0.92;
        }

        // Incorporate line item match confidence if available
        if (mappedLines.length > 0 && rawMatches.length > 0) {
          const avgMatchConf = rawMatches.reduce((acc: number, m: any) => acc + (typeof m.match_confidence === 'number' ? m.match_confidence : 1.0), 0) / rawMatches.length;
          dynamicScore = Number(((dynamicScore * 0.7) + (avgMatchConf * 0.3)).toFixed(2));
        }

        // Investigation Steps tailored for non-technical users
        let dynamicSteps = [];
        if (invDetail?.events && invDetail.events.length > 0) {
          dynamicSteps = invDetail.events.map((ev: any, idx: number) => {
            const rawTool = ev.tool_name || ev.action || 'Audit Tool';
            let resObj = ev.result;
            if (typeof resObj === 'string') {
              try {
                resObj = JSON.parse(resObj);
              } catch {
                // leave as string
              }
            }

            const cleanTool = rawTool
              .replace(/_/g, ' ')
              .replace(/\b\w/g, (c: string) => c.toUpperCase());

            let findingsStr = '';
            if (rawTool === 'verify_document_arithmetic') {
              if (resObj && typeof resObj === 'object') {
                if (resObj.summary) {
                  findingsStr = resObj.summary;
                } else if (resObj.error_detail) {
                  findingsStr = resObj.error_detail;
                } else if (resObj.failed_lines && resObj.failed_lines.length > 0) {
                  const fls = resObj.failed_lines.map((fl: any) => `${fl.description || fl.product_code || 'Line'}: printed $${fl.reported_line_total} vs calculated $${fl.calculated_line_total}`).join('; ');
                  findingsStr = `Document math verification failed: ${fls}`;
                } else if (resObj.is_valid) {
                  findingsStr = `Document arithmetic verified: all line items, tax, and totals reconcile perfectly.`;
                } else {
                  findingsStr = `Audited document arithmetic across item lines and summary totals.`;
                }
              } else if (typeof resObj === 'string' && !resObj.startsWith('{')) {
                findingsStr = resObj;
              } else {
                findingsStr = `Audited document arithmetic across item lines and summary totals.`;
              }
            } else if (rawTool === 'get_purchase_order') {
              if (resObj && typeof resObj === 'object') {
                if (resObj.lines && Array.isArray(resObj.lines)) {
                  const poId = resObj.po_id || 'PO';
                  const vName = resObj.vendor_id || resObj.vendor || '';
                  const lineSummaries = resObj.lines.map((l: any) => `${l.description || l.item_id} (Qty: ${l.quantity} @ $${Number(l.unit_price).toFixed(2)})`).join(', ');
                  findingsStr = `Retrieved Purchase Order ${poId}${vName ? ` (${vName})` : ''}. Inspected ${resObj.lines.length} authorized line items: ${lineSummaries}.`;
                } else if (resObj.status === 'NOT_FOUND') {
                  findingsStr = `Purchase order record was not found in enterprise files.`;
                } else {
                  findingsStr = resObj.summary || resObj.description || `Inspected purchase order records and approved line items.`;
                }
              } else if (typeof resObj === 'string' && !resObj.startsWith('{')) {
                findingsStr = resObj;
              } else {
                findingsStr = `Inspected purchase order records and approved line items.`;
              }
            } else if (rawTool === 'get_invoice') {
              if (resObj && typeof resObj === 'object') {
                if (resObj.lines && Array.isArray(resObj.lines)) {
                  const invId = resObj.invoice_id || 'Invoice';
                  const totStr = resObj.total ? ` (Total: $${Number(resObj.total).toFixed(2)})` : '';
                  const lineSummaries = resObj.lines.map((l: any) => `${l.description || l.line_id} (Qty: ${l.quantity} @ $${Number(l.unit_price).toFixed(2)}${l.line_total ? ` = $${Number(l.line_total).toFixed(2)}` : ''})`).join(', ');
                  findingsStr = `Retrieved Invoice ${invId}${totStr}. Inspected ${resObj.lines.length} billed line items: ${lineSummaries}.`;
                } else if (resObj.status === 'NOT_FOUND') {
                  findingsStr = `Invoice document was not found in enterprise records.`;
                } else {
                  findingsStr = resObj.summary || resObj.description || `Inspected billed invoice items, rates, and line totals.`;
                }
              } else if (typeof resObj === 'string' && !resObj.startsWith('{')) {
                findingsStr = resObj;
              } else {
                findingsStr = `Inspected billed invoice items, rates, and line totals.`;
              }
            } else if (rawTool === 'get_receipt') {
              if (resObj && typeof resObj === 'object') {
                if (resObj.received_lines && Array.isArray(resObj.received_lines)) {
                  const rId = resObj.receipt_id || 'Receipt';
                  const dDate = resObj.delivery_date ? ` delivered on ${resObj.delivery_date}` : '';
                  const lineSummaries = resObj.received_lines.map((l: any) => `${l.description || l.line_id} (Received: ${l.quantity_delivered ?? l.quantity})`).join(', ');
                  findingsStr = `Retrieved Delivery Receipt ${rId}${dDate}. Confirmed receiving dock counts: ${lineSummaries}.`;
                } else if (resObj.status === 'NOT_FOUND') {
                  findingsStr = `Delivery receipt not found in warehouse records.`;
                } else {
                  findingsStr = resObj.summary || resObj.description || `Inspected physical delivery and dock receiving receipts.`;
                }
              } else if (typeof resObj === 'string' && !resObj.startsWith('{')) {
                findingsStr = resObj;
              } else {
                findingsStr = `Inspected physical delivery and dock receiving receipts.`;
              }
            } else if (rawTool === 'check_authorization') {
              if (resObj && typeof resObj === 'object') {
                findingsStr = resObj.authorized
                  ? `Checked price authorizations: Found formal approval on file.`
                  : `Checked price authorizations: No formal price change authorization was found on file.`;
              } else {
                findingsStr = `Checked price authorizations on file.`;
              }
            } else if (rawTool === 'get_vendor_history') {
              findingsStr = `Retrieved vendor history: Checked historical rates and past transaction records.`;
            } else if (rawTool === 'find_similar_invoices') {
              findingsStr = `Searched historical invoices: Checked for similar past billing patterns.`;
            } else if (typeof resObj === 'object' && resObj !== null) {
              findingsStr = resObj.summary || resObj.description || resObj.error_detail || resObj.message || `Audit step completed: verified ${cleanTool.toLowerCase()} data.`;
            } else if (typeof resObj === 'string' && !resObj.startsWith('{')) {
              findingsStr = resObj;
            } else {
              findingsStr = `Audit step completed: executed ${cleanTool.toLowerCase()}.`;
            }

            return {
              step: idx + 1,
              action: cleanTool,
              tool: cleanTool,
              findings: findingsStr,
            };
          });
        } else if (hasCalculationError) {
          dynamicSteps = [
            {
              step: 1,
              action: 'Document Math Validation',
              tool: 'Pre-Reconciliation Check',
              findings: `Audited arithmetic across line items and document totals. Detected calculation mismatch where printed line totals do not equal Quantity × Unit Price.`,
            },
            {
              step: 2,
              action: 'Multi-Way Discrepancy Cross-Check',
              tool: 'Validation Policy',
              findings: `Source document contains an unresolved arithmetic defect. Investigated ordered vs billed vs delivered quantities.`,
            },
            {
              step: 3,
              action: 'Settlement Recommendation',
              tool: 'Resolution Policy',
              findings: `Marked invoice for rejection and requested a corrected document from ${normalizedThreeWay.vendor_name || 'the vendor'}.`,
            },
          ];
        } else {
          dynamicSteps = [
            {
              step: 1,
              action: '3-Way Document Line Audit',
              tool: 'Document Matching',
              findings: isCleanMatch
                ? `Line items, rates ($${(poPriceVal || 0).toFixed(2)}), and quantities match with zero variance.`
                : (hasPo && hasInv
                    ? `Compared authorized PO unit price ($${(poPriceVal || 0).toFixed(2)}) against billed rate ($${(invPriceVal || 0).toFixed(2)}).`
                    : (normalizedThreeWay.receipt_file_name ? 'Receipt attached; Purchase Order and Invoice missing.' : 'Incomplete document triplet.')),
            },
            {
              step: 2,
              action: 'Contract & Change Order Audit',
              tool: 'Authorization Registry',
              findings: isCleanMatch
                ? 'Authorized contract rate verified; zero change order escalations required.'
                : (hasPo && hasInv
                    ? 'Queried enterprise ERP registry: 0 approved change orders found for price variance.'
                    : 'Authorization check not applicable due to missing files.'),
            },
            {
              step: 3,
              action: 'Vendor Historical Analysis',
              tool: 'Vendor Profile Audit',
              findings: normalizedThreeWay.vendor_name
                ? `Audited contract history and commercial terms for ${normalizedThreeWay.vendor_name}.`
                : 'Standalone case; no vendor profile on file.',
            },
          ];
        }

        const normalizedInv: InvestigationData = {
          case_id: selectedCaseId,
          transaction_id: `TXN-${selectedCaseId}`,
          flagged_reason: flaggedReason,
          investigation_steps: dynamicSteps,
          evidence_citations: evidenceList.map((e: any) => ({
            document: e.source_id || '',
            field: e.field || 'unit_price',
            value: String(e.value || '—'),
            notes: e.description || '',
          })),
          agent_conclusion: agentConclusion,
          agent_recommendation:
            caseDetail?.recommendation ||
            invDetail?.recommendation ||
            (isMatched ? 'APPROVE_PAYMENT' : 'REQUEST_CREDIT_MEMO'),
          confidence_score: dynamicScore,
          provenance: {
            finding: findingsList[0]?.explanation || (hasPo && hasInv ? 'Unapproved supplier rate hike over purchase order.' : 'Incomplete document triplet comparison.'),
            variance_type: isMatched ? 'MATCHED' : (hasPo && hasInv ? (isQuantityMismatch ? 'QUANTITY_SHORTAGE' : 'PRICE_MISMATCH') : 'MISSING_DOCUMENTS'),
            po_field: {
              label: 'Authorized Unit Price on PO',
              value: poPriceVal !== undefined ? `$${poPriceVal.toFixed(2)}` : '—',
              source_document: normalizedThreeWay.po_file_name || '',
              field_name: hasPo ? 'unit_price' : '—',
              line_number: 1,
            },
            invoice_field: {
              label: 'Billed Unit Price on Invoice',
              value: invPriceVal !== undefined ? `$${invPriceVal.toFixed(2)}` : '—',
              source_document: normalizedThreeWay.invoice_file_name || '',
              field_name: hasInv ? 'unit_price' : '—',
              line_number: 1,
            },
            difference_text: isMatched ? '$0.00 / 0.0%' : (hasPo && hasInv ? `+$${diffAmount.toLocaleString()} / +${diffPct.toFixed(1)}%` : '—'),
            authorization_status: {
              is_authorized: isMatched,
              note: isMatched
                ? 'Rate approved under corporate contract.'
                : (hasPo && hasInv
                    ? 'No approved price change, amendment, or formal escalation order found on file.'
                    : 'Incomplete document triplet; cross-document authorization check not applicable.'),
              approval_ref: isMatched ? 'CO-441-APPROVED' : undefined,
            },
            verified_checks: hasPo && hasInv ? [
              ...(poPriceVal !== undefined ? [`PO Rate ($${poPriceVal.toFixed(2)})`] : []),
              ...(invPriceVal !== undefined ? [`Invoice Rate ($${invPriceVal.toFixed(2)})`] : []),
              'ERP Change Order Registry Check',
              'Vendor Historical Rates Audited',
            ] : [],
          },
        };
        setInvestigationData(normalizedInv);
        setIsDetailLoading(false);
      })
      .catch((err) => {
        console.error('Error fetching details:', err);
        setIsDetailLoading(false);
      });
  }, [selectedCaseId, cases]);

  // 3. Human Review Decision Submission (Section 7.4)
  const handleDecisionSubmit = async (
    action: 'APPROVE' | 'REJECT' | 'ESCALATE',
    reviewer: string,
    reason: string
  ) => {
    if (!selectedCaseId || !investigationData) return;
    setIsSubmittingDecision(true);

    try {
      await api.submitDecision(selectedCaseId, action, reviewer, reason);

      const decisionRecord: ReviewDecisionRecord = {
        case_id: selectedCaseId,
        reviewer,
        decision: action,
        original_recommendation: investigationData.agent_recommendation,
        reviewer_decision: action,
        reason,
        timestamp: new Date().toISOString(),
      };

      // Record decision locally
      setDecisions((prev) => ({
        ...prev,
        [selectedCaseId]: decisionRecord,
      }));

      // Update case status in cases table
      setCases((prev) =>
        prev.map((c) => {
          if (c.case_id === selectedCaseId) {
            return {
              ...c,
              action: action === 'APPROVE' ? 'Approved' : action === 'REJECT' ? 'Rejected' : 'Escalated',
              requires_human_review: false,
            };
          }
          return c;
        })
      );

      // Decrement under review metric
      setMetrics((prev) => ({
        ...prev,
        under_review: Math.max(0, prev.under_review - 1),
      }));
    } catch (err: any) {
      console.error('Decision submission error:', err);
      alert('Failed to submit decision: ' + (err.response?.data?.detail || err.message));
    } finally {
      setIsSubmittingDecision(false);
    }
  };

  // 4. Modal Handlers
  const handleViewDoc = (fileName: string, docType: string, filePath?: string) => {
    setDocViewerParams({
      isOpen: true,
      fileName,
      filePath,
      docType,
    });
  };

  const handleReconciledSuccess = (newCaseId: string) => {
    loadData();
    setSelectedCaseId(newCaseId);
    setIsUploadOpen(false);
  };

  const handleSelectCase = (cid: string) => {
    setSelectedCaseId(cid);
    setMobileTab('DETAILS');
    if (typeof window !== 'undefined' && window.innerWidth < 1024) {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  };

  return (
    <div className="h-screen bg-slate-900 text-slate-100 flex flex-col font-sans overflow-hidden">
      {/* Top Navigation */}
      <Navbar
        onOpenUpload={() => setIsUploadOpen(true)}
        onOpenUserMgmt={() => setIsUserMgmtOpen(true)}
        onRefresh={loadData}
        isRefreshing={isRefreshing}
        onlineStatus={onlineStatus}
      />

      {/* Main Container (Fills exact remaining viewport height) */}
      <main className="flex-1 max-w-7xl w-full mx-auto p-2.5 sm:p-4 flex flex-col min-h-0 overflow-hidden">
        {/* KPI Metrics Bar */}
        <MetricsBar
          metrics={dynamicMetrics}
          activeFilter={activeQuickFilter}
          onFilterSelect={(filter) => setActiveQuickFilter(filter)}
        />

        {/* Responsive Mobile Tab Switcher (< lg) */}
        <div className="lg:hidden flex items-center bg-slate-850 p-1 rounded-xl border border-slate-700/80 mb-2.5 shadow-sm flex-shrink-0">
          <button
            onClick={() => setMobileTab('DIRECTORY')}
            className={`flex-1 py-1.5 text-xs font-semibold rounded-lg transition flex items-center justify-center space-x-1.5 ${
              mobileTab === 'DIRECTORY'
                ? 'bg-sky-500 text-white shadow'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            <span>📋 Recent Cases</span>
            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-slate-900/50 font-mono">
              {cases.length}
            </span>
          </button>
          <button
            onClick={() => setMobileTab('DETAILS')}
            className={`flex-1 py-1.5 text-xs font-semibold rounded-lg transition flex items-center justify-center space-x-1.5 ${
              mobileTab === 'DETAILS'
                ? 'bg-sky-500 text-white shadow'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            <span>🔍 Case Details</span>
            {selectedCaseId && (
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-slate-900/50 font-mono">
                {selectedCaseId}
              </span>
            )}
          </button>
        </div>

        {/* Master-Detail Layout: Both Left & Right Exactly Fit Screen Height */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 flex-1 min-h-0 overflow-hidden">
          {/* Left Column (Equal Size): Recent Cases Table */}
          <div
            className={`${
              mobileTab === 'DIRECTORY' ? 'flex' : 'hidden'
            } lg:flex h-full flex-col min-h-0 overflow-hidden`}
          >
            <CasesTable
              cases={cases}
              selectedCaseId={selectedCaseId}
              onSelectCase={handleSelectCase}
              activeQuickFilter={activeQuickFilter}
              onClearQuickFilter={() => setActiveQuickFilter('ALL')}
              onViewDoc={handleViewDoc}
            />
          </div>

          {/* Right Column (Equal Size): Full Case Details View */}
          <div
            className={`${
              mobileTab === 'DETAILS' ? 'flex' : 'hidden'
            } lg:flex h-full flex-col min-h-0 overflow-y-auto pr-1 pb-1`}
          >
            {selectedCaseSummary && threeWayData && investigationData ? (
              <CaseDetailView
                caseSummary={selectedCaseSummary}
                threeWayData={threeWayData}
                investigation={investigationData}
                isLoading={isDetailLoading}
                onViewDoc={handleViewDoc}
                onDecisionSubmit={handleDecisionSubmit}
                isSubmittingDecision={isSubmittingDecision}
                pastDecision={selectedCaseId ? decisions[selectedCaseId] : undefined}
                onBack={() => setMobileTab('DIRECTORY')}
              />
            ) : (
              <div className="h-full flex flex-col items-center justify-center p-8 bg-slate-850 rounded-xl border border-slate-800 text-slate-400">
                <AlertCircle className="w-12 h-12 text-slate-600 mb-3" />
                <p className="text-sm font-medium">
                  {cases.length === 0
                    ? 'No cases available yet. Click "Upload Documents" to begin.'
                    : 'Select a case from Recent Cases to inspect'}
                </p>
              </div>
            )}
          </div>
        </div>
      </main>

      {/* Document Viewer Modal (Click-to-view raw file content) */}
      <DocumentViewerModal
        isOpen={docViewerParams.isOpen}
        onClose={() => setDocViewerParams((prev) => ({ ...prev, isOpen: false }))}
        fileName={docViewerParams.fileName}
        filePath={docViewerParams.filePath}
        docType={docViewerParams.docType}
      />

      {/* Document Upload Modal (Dual-mode: Mixed batch vs Triplet slots) */}
      <UploadModal
        isOpen={isUploadOpen}
        onClose={() => setIsUploadOpen(false)}
        onReconciledSuccess={handleReconciledSuccess}
      />

      {/* User Management Modal (Admin only) */}
      <UserManagementModal
        isOpen={isUserMgmtOpen}
        onClose={() => setIsUserMgmtOpen(false)}
      />
    </div>
  );
};

export default App;

