import React from 'react';
import {
  FileText,
  Building2,
  Calendar,
  ExternalLink,
  Shield,
  Layers,
  ArrowLeft,
  Loader2,
} from 'lucide-react';
import { CaseSummary, ThreeWayMatchData, InvestigationData, ReviewDecisionRecord } from '../types';
import { ThreeWayMatchCard } from './ThreeWayMatchCard';
import { EvidenceCard } from './EvidenceCard';
import { HumanReviewCard } from './HumanReviewCard';

interface CaseDetailViewProps {
  caseSummary: CaseSummary;
  threeWayData: ThreeWayMatchData;
  investigation: InvestigationData;
  isLoading: boolean;
  onViewDoc: (fileName: string, docType: string, filePath?: string) => void;
  onDecisionSubmit: (
    action: 'APPROVE' | 'REJECT' | 'ESCALATE',
    reviewer: string,
    reason: string
  ) => Promise<void>;
  isSubmittingDecision: boolean;
  pastDecision?: ReviewDecisionRecord;
  onBack?: () => void;
}

export const CaseDetailView: React.FC<CaseDetailViewProps> = ({
  caseSummary,
  threeWayData,
  investigation,
  isLoading,
  onViewDoc,
  onDecisionSubmit,
  isSubmittingDecision,
  pastDecision,
  onBack,
}) => {
  if (isLoading) {
    return (
      <div className="h-full min-h-[500px] flex flex-col items-center justify-center space-y-3 bg-slate-850 rounded-xl border border-slate-700/80 p-8">
        <Loader2 className="w-10 h-10 text-sky-400 animate-spin" />
        <p className="text-slate-300 text-sm font-medium">
          Loading 3-Way Match & Investigation for {caseSummary.case_id}...
        </p>
      </div>
    );
  }

  // Source document tags with genuine filenames only - NO synthetic fallbacks
  const poFile = threeWayData.po_file_name || caseSummary.po_file || null;
  const invFile = threeWayData.invoice_file_name || caseSummary.invoice_file || null;
  const rcptFile =
    threeWayData.receipt_file_name ||
    caseSummary.receipt_files?.[0] ||
    null;

  const formatProcessedDateTime = (ts?: string) => {
    if (!ts) return 'Active Transaction';
    try {
      const d = new Date(ts);
      if (isNaN(d.getTime())) return ts.replace('T', ' ').slice(0, 16);
      const year = d.getFullYear();
      const month = String(d.getMonth() + 1).padStart(2, '0');
      const day = String(d.getDate()).padStart(2, '0');
      const hours = String(d.getHours()).padStart(2, '0');
      const minutes = String(d.getMinutes()).padStart(2, '0');
      return `${year}-${month}-${day} ${hours}:${minutes}`;
    } catch {
      return ts.replace('T', ' ').slice(0, 16);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      {/* Mobile Back Button */}
      {onBack && (
        <div className="lg:hidden">
          <button
            onClick={onBack}
            className="inline-flex items-center space-x-2 px-3.5 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-sky-400 border border-slate-700 shadow-sm transition"
          >
            <ArrowLeft className="w-4 h-4" />
            <span>← Back to Recent Cases</span>
          </button>
        </div>
      )}

      {/* Top Banner: Case Header & Source Document Links (mt-0 explicitly removes 24px margin-top) */}
      <div className="bg-slate-850 rounded-xl border border-slate-700/80 p-4 sm:p-5 shadow-lg !mt-0">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-4 border-b border-slate-700/60">
          <div>
            <div className="flex items-center space-x-3">
              <h1 className="text-xl font-bold text-white font-mono tracking-tight">
                {caseSummary.case_id}
              </h1>
              <span className="px-2.5 py-0.5 rounded text-xs font-semibold bg-sky-500/10 text-sky-400 border border-sky-500/20">
                {caseSummary.status}
              </span>
            </div>
            <div className="flex items-center flex-wrap gap-2 text-xs text-slate-400 mt-1">
              <span className="flex items-center gap-1">
                <Building2 className="w-3.5 h-3.5 text-slate-500" />
                <strong className="text-slate-200">
                  {caseSummary.vendor_name || '—'}
                </strong>
              </span>
              <span>•</span>
              <span className="flex items-center gap-1 font-mono text-[11px]">
                <Calendar className="w-3.5 h-3.5 text-slate-500" />
                <span>Processed: {formatProcessedDateTime(caseSummary.created_at || threeWayData.created_at)}</span>
              </span>
            </div>
          </div>

          <div className="sm:text-right font-mono text-xs">
            <span className="text-slate-500 block">Reconciliation Policy</span>
            <span className="text-emerald-400 font-semibold">Deterministic 3-Way Match</span>
          </div>
        </div>

        {/* CLICKABLE SOURCE DOCUMENT PILLS WITH EXACT FILENAMES */}
        <div className="pt-3">
          <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
            <FileText className="w-3.5 h-3.5 text-sky-400" />
            <span>Source Documents (Click to inspect in-browser)</span>
          </div>

          <div className="flex flex-wrap items-center gap-2 sm:gap-2.5">
            {/* Purchase Order Pill */}
            {poFile ? (
              <button
                onClick={() => onViewDoc(poFile, 'PURCHASE_ORDER', threeWayData.po_file_path)}
                className="flex items-center space-x-2 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700/80 border border-slate-700 text-xs text-slate-300 hover:text-white transition group cursor-pointer max-w-full"
              >
                <span className="w-2 h-2 rounded-full bg-sky-400 flex-shrink-0" />
                <span className="font-bold text-sky-300">PO:</span>
                <span className="font-mono text-slate-200 group-hover:underline truncate max-w-[180px] sm:max-w-none">{poFile}</span>
                {(threeWayData.po_id || caseSummary.po_number) && (
                  <span className="text-[10px] text-slate-500 font-mono hidden sm:inline">
                    ({threeWayData.po_id || caseSummary.po_number})
                  </span>
                )}
                <ExternalLink className="w-3 h-3 text-slate-500 group-hover:text-sky-300 transition flex-shrink-0" />
              </button>
            ) : (
              <div className="flex items-center space-x-2 px-3 py-1.5 rounded-lg bg-slate-900/60 border border-dashed border-slate-800 text-xs text-slate-500">
                <span className="w-2 h-2 rounded-full bg-slate-600 flex-shrink-0" />
                <span className="font-semibold text-slate-400">PO:</span>
                <span className="italic text-slate-500 text-[11px]">Not uploaded</span>
              </div>
            )}

            {/* Vendor Invoice Pill */}
            {invFile ? (
              <button
                onClick={() =>
                  onViewDoc(invFile, 'INVOICE', threeWayData.invoice_file_path)
                }
                className="flex items-center space-x-2 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700/80 border border-slate-700 text-xs text-slate-300 hover:text-white transition group cursor-pointer max-w-full"
              >
                <span className="w-2 h-2 rounded-full bg-indigo-400 flex-shrink-0" />
                <span className="font-bold text-indigo-300">Invoice:</span>
                <span className="font-mono text-slate-200 group-hover:underline truncate max-w-[180px] sm:max-w-none">{invFile}</span>
                {(threeWayData.invoice_id || caseSummary.invoice_number) && (
                  <span className="text-[10px] text-slate-500 font-mono hidden sm:inline">
                    ({threeWayData.invoice_id || caseSummary.invoice_number})
                  </span>
                )}
                <ExternalLink className="w-3 h-3 text-slate-500 group-hover:text-indigo-300 transition flex-shrink-0" />
              </button>
            ) : (
              <div className="flex items-center space-x-2 px-3 py-1.5 rounded-lg bg-slate-900/60 border border-dashed border-slate-800 text-xs text-slate-500">
                <span className="w-2 h-2 rounded-full bg-slate-600 flex-shrink-0" />
                <span className="font-semibold text-slate-400">Invoice:</span>
                <span className="italic text-slate-500 text-[11px]">Not uploaded</span>
              </div>
            )}

            {/* Goods Receipt Pill */}
            {rcptFile ? (
              <button
                onClick={() =>
                  onViewDoc(rcptFile, 'RECEIPT', threeWayData.receipt_file_path)
                }
                className="flex items-center space-x-2 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700/80 border border-slate-700 text-xs text-slate-300 hover:text-white transition group cursor-pointer max-w-full"
              >
                <span className="w-2 h-2 rounded-full bg-emerald-400 flex-shrink-0" />
                <span className="font-bold text-emerald-300">Receipt:</span>
                <span className="font-mono text-slate-200 group-hover:underline truncate max-w-[180px] sm:max-w-none">{rcptFile}</span>
                {(threeWayData.receipt_id || caseSummary.receipt_numbers?.[0]) && (
                  <span className="text-[10px] text-slate-500 font-mono hidden sm:inline">
                    ({threeWayData.receipt_id || caseSummary.receipt_numbers?.[0]})
                  </span>
                )}
                <ExternalLink className="w-3 h-3 text-slate-500 group-hover:text-emerald-300 transition flex-shrink-0" />
              </button>
            ) : (
              <div className="flex items-center space-x-2 px-3 py-1.5 rounded-lg bg-slate-900/60 border border-dashed border-slate-800 text-xs text-slate-500">
                <span className="w-2 h-2 rounded-full bg-slate-600 flex-shrink-0" />
                <span className="font-semibold text-slate-400">Receipt:</span>
                <span className="italic text-slate-500 text-[11px]">None attached</span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 1. DEDICATED THREE-WAY MATCH COMPARISON (USER DIRECTIVE 3) */}
      <ThreeWayMatchCard data={threeWayData} />

      {/* 2. DEEP EVIDENCE PROVENANCE (SECTION 7.3) */}
      <EvidenceCard
        investigation={investigation}
        onViewDoc={(fn, dt) => onViewDoc(fn, dt)}
      />

      {/* 3. HUMAN REVIEW & AUDIT TRAIL (SECTION 7.4) */}
      <HumanReviewCard
        investigation={investigation}
        onDecisionSubmit={onDecisionSubmit}
        isSubmitting={isSubmittingDecision}
        pastDecision={pastDecision}
      />
    </div>
  );
};

