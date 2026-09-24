import React from 'react';
import {
  Building2,
  Calendar,
  ArrowLeft,
  Loader2,
} from 'lucide-react';
import { CaseSummary, ThreeWayMatchData, InvestigationData, ReviewDecisionRecord } from '../types';
import { ThreeWayMatchCard } from './ThreeWayMatchCard';
import { HumanReviewCard } from './HumanReviewCard';

interface CaseDetailViewProps {
  caseSummary: CaseSummary;
  threeWayData: ThreeWayMatchData;
  investigation: InvestigationData;
  isLoading: boolean;
  onViewDoc?: (fileName: string, docType: string, filePath?: string) => void;
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

      {/* Top Banner: Case Header (mt-0 explicitly removes margin-top) */}
      <div className="bg-slate-850 rounded-xl border border-slate-700/80 p-4 sm:p-5 shadow-lg !mt-0">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
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
      </div>

      {/* 1. DEDICATED THREE-WAY MATCH COMPARISON */}
      <ThreeWayMatchCard data={threeWayData} />

      {/* 2. HUMAN REVIEW & AUDIT TRAIL */}
      <HumanReviewCard
        investigation={investigation}
        onDecisionSubmit={onDecisionSubmit}
        isSubmitting={isSubmittingDecision}
        pastDecision={pastDecision}
      />
    </div>
  );
};
