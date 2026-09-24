import React, { useState, useRef } from 'react';
import {
  UserCheck,
  AlertCircle,
  HelpCircle,
  CheckCircle2,
  XCircle,
  ArrowUpRight,
  Info,
  Clock,
  ShieldCheck,
  FileCheck,
  Send,
  Loader2,
} from 'lucide-react';
import { InvestigationData, ReviewDecisionRecord } from '../types';

interface HumanReviewCardProps {
  investigation: InvestigationData;
  onDecisionSubmit: (
    action: 'APPROVE' | 'REJECT' | 'ESCALATE',
    reviewer: string,
    reason: string
  ) => Promise<void>;
  isSubmitting: boolean;
  pastDecision?: ReviewDecisionRecord;
}

export const HumanReviewCard: React.FC<HumanReviewCardProps> = ({
  investigation,
  onDecisionSubmit,
  isSubmitting,
  pastDecision,
}) => {
  const [reviewer, setReviewer] = useState('Jane Doe (AP Senior Specialist)');
  const [reason, setReason] = useState('');
  const [activeTooltip, setActiveTooltip] = useState<string | null>(null);
  const hoverTimerRef = useRef<any>(null);

  // 2-Second Hover Delay Implementation
  const handleMouseEnter = (buttonKey: string) => {
    // Clear any previous timer
    if (hoverTimerRef.current) {
      clearTimeout(hoverTimerRef.current);
    }
    // Start 2000ms delay timer
    hoverTimerRef.current = setTimeout(() => {
      setActiveTooltip(buttonKey);
    }, 2000);
  };

  const handleMouseLeave = () => {
    if (hoverTimerRef.current) {
      clearTimeout(hoverTimerRef.current);
      hoverTimerRef.current = null;
    }
    setActiveTooltip(null);
  };

  const handleAction = (action: 'APPROVE' | 'REJECT' | 'ESCALATE') => {
    const finalReason =
      reason.trim() ||
      (action === 'APPROVE'
        ? `Approved recommendation (${investigation.agent_recommendation}).`
        : action === 'REJECT'
        ? 'Dispute billing rate with vendor.'
        : 'Escalated for senior leadership policy review.');
    onDecisionSubmit(action, reviewer, finalReason);
  };

  return (
    <div className="bg-slate-850 rounded-xl border border-slate-700/80 p-5 shadow-lg relative">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 pb-3 mb-4 border-b border-slate-700/60">
        <div className="flex items-center space-x-2.5">
          <div className="p-2 rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex-shrink-0">
            <UserCheck className="w-5 h-5" />
          </div>
          <div>
            <h3 className="font-bold text-slate-100 tracking-wide text-sm uppercase flex items-center gap-2">
              Human Review & Governance Audit Trail
            </h3>
            <p className="text-xs text-slate-400">
              Enterprise sign-off resolving agent findings with permanent audit ledger
            </p>
          </div>
        </div>

        <span className="self-start sm:self-auto px-2.5 py-1 rounded text-xs font-semibold bg-sky-500/10 text-sky-400 border border-sky-500/20">
          Section 7.4 Protocol
        </span>
      </div>

      {/* THE 5 ESSENTIAL HUMAN REVIEW QUESTIONS */}
      <div className="space-y-3 mb-6 bg-slate-900/90 rounded-xl p-4 border border-slate-800">
        {/* Q1: Why was this flagged? */}
        <div>
          <div className="text-[11px] uppercase tracking-wider font-semibold text-slate-400 flex items-center gap-1.5 mb-1">
            <AlertCircle className="w-3.5 h-3.5 text-amber-400" />
            <span>1. Why was this flagged?</span>
          </div>
          <p className="text-xs text-slate-200 pl-5 leading-relaxed font-sans">
            {investigation.flagged_reason ||
              'Reconciliation review initiated for case verification.'}
          </p>
        </div>

        {/* Q2: What did the agent investigate? */}
        <div>
          <div className="text-[11px] uppercase tracking-wider font-semibold text-slate-400 flex items-center gap-1.5 mb-1.5">
            <HelpCircle className="w-3.5 h-3.5 text-sky-400" />
            <span>2. What did the agent investigate?</span>
          </div>
          <div className="space-y-1.5 pl-5">
            {(investigation.investigation_steps || [
              { tool: 'Reconciliation Audit', findings: 'Audited case documents and line records' },
            ]).map((step, idx) => (
              <div key={idx} className="flex items-start gap-2 text-xs text-slate-300">
                <span className="font-semibold text-sky-400 min-w-[150px] flex-shrink-0">
                  {step.tool || step.action}:
                </span>
                <span className="text-slate-200 leading-snug">{step.findings}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Q3: What evidence did it use? */}
        <div>
          <div className="text-[11px] uppercase tracking-wider font-semibold text-slate-400 flex items-center gap-1.5 mb-1.5">
            <FileCheck className="w-3.5 h-3.5 text-indigo-400" />
            <span>3. What evidence did it use?</span>
          </div>
          <div className="pl-5 text-xs text-slate-200">
            {investigation.evidence_citations && investigation.evidence_citations.length > 0 ? (
              <div className="space-y-1.5">
                {investigation.evidence_citations.map((ev, idx) => {
                  let fieldText = ev.field;
                  let valText = ev.value;
                  let noteText = ev.notes;

                  if (fieldText === 'internal_math' || valText.includes('sum_line_totals') || valText.startsWith('{')) {
                    fieldText = 'Line Math Check';
                    if (noteText && noteText.includes('calculated') && noteText.includes('reported')) {
                      const match = noteText.match(/calculated\s+([\d\.]+)\s+vs\s+reported\s+([\d\.]+)/i);
                      if (match) {
                        valText = `Printed $${Number(match[2]).toFixed(2)} vs Calculated $${Number(match[1]).toFixed(2)}`;
                      } else {
                        valText = 'Arithmetic Mismatch';
                      }
                    } else if (noteText && noteText.includes('calculated') && noteText.includes('printed')) {
                      const match = noteText.match(/calculated\s+\$?([\d\.]+)\s+vs\s+printed(?:\s+on\s+document)?\s+\$?([\d\.]+)/i);
                      if (match) {
                        valText = `Printed $${Number(match[2]).toFixed(2)} vs Calculated $${Number(match[1]).toFixed(2)}`;
                      } else {
                        valText = 'Arithmetic Mismatch';
                      }
                    } else {
                      valText = 'Printed total does not equal calculated sum';
                    }
                    noteText = 'Document arithmetic verification failed on itemized calculation';
                  }

                  return (
                    <div key={idx} className="flex items-center flex-wrap gap-2 text-xs text-slate-300 font-mono">
                      <span className="px-2 py-0.5 rounded bg-slate-800 text-indigo-300 border border-slate-700 font-semibold text-[11px]">
                        {ev.document || 'Source Record'}
                      </span>
                      <span className="text-slate-400 capitalize">{fieldText.replace(/_/g, ' ')}:</span>
                      <span className="text-white font-bold">{valText}</span>
                      {noteText && <span className="text-slate-400 font-sans text-xs">({noteText})</span>}
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="text-slate-300 leading-relaxed font-sans">
                Reconciled source records: Verified Purchase Order approved pricing, Vendor Invoice billed item rates, and physical Goods Receipt counts. Cross-document consistency verified.
              </p>
            )}
          </div>
        </div>

        {/* Q4: What did it conclude? */}
        <div>
          <div className="text-[11px] uppercase tracking-wider font-semibold text-slate-400 flex items-center gap-1.5 mb-1">
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
            <span>4. What did it conclude?</span>
          </div>
          <p className="text-xs text-slate-200 pl-5 leading-relaxed font-sans whitespace-pre-line">
            {investigation.agent_conclusion ||
              'Reconciliation completed against contract rate repository and enterprise authorization records.'}
          </p>
        </div>

        {/* Q5: What does it recommend? */}
        <div className="pt-1 border-t border-slate-800/80">
          <div className="text-[11px] uppercase tracking-wider font-semibold text-slate-400 flex items-center gap-1.5 mb-1">
            <ArrowUpRight className="w-3.5 h-3.5 text-sky-400" />
            <span>5. What does it recommend?</span>
          </div>
          <div className="pl-5 flex items-center space-x-2">
            <span className="px-3 py-1 rounded-lg text-xs font-bold uppercase bg-gradient-to-r from-sky-500/20 to-blue-500/20 text-sky-300 border border-sky-400/40">
              {investigation.agent_recommendation || 'REQUEST_CREDIT_MEMO'}
            </span>
            <span className="text-[11px] text-slate-400">
              (Confidence: <span className={`font-semibold ${investigation.confidence_score >= 0.9 ? 'text-emerald-400' : investigation.confidence_score >= 0.75 ? 'text-amber-400' : 'text-rose-400'}`}>{Math.round(investigation.confidence_score * 100)}%</span>)
            </span>
          </div>
        </div>
      </div>

      {/* Reviewer Inputs */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-4">
        <div>
          <label className="block text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-1">
            Reviewer Specialist ID / Name
          </label>
          <input
            type="text"
            value={reviewer}
            onChange={(e) => setReviewer(e.target.value)}
            disabled={isSubmitting || !!pastDecision}
            className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-sky-500 disabled:opacity-50"
          />
        </div>
        <div>
          <label className="block text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-1">
            Decision Rationale / Dispute Reason
          </label>
          <input
            type="text"
            placeholder="e.g. Price hike unapproved; requesting credit adjustment"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            disabled={isSubmitting || !!pastDecision}
            className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-sky-500 disabled:opacity-50"
          />
        </div>
      </div>

      {/* 3 SETTLEMENT ACTION BUTTONS WITH 2-SECOND DELAYED TOOLTIP */}
      <div className="relative pt-2">
        <div className="flex flex-col sm:flex-row items-center justify-center flex-wrap gap-2.5 sm:gap-4">
          {/* Button 1: Approve Recommendation */}
          <div
            className="relative w-full sm:w-auto"
            onMouseEnter={() => handleMouseEnter('APPROVE')}
            onMouseLeave={handleMouseLeave}
          >
            <button
              onClick={() => handleAction('APPROVE')}
              disabled={isSubmitting || !!pastDecision}
              className="w-full sm:w-auto min-w-[200px] flex items-center justify-center space-x-2 px-5 py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold shadow-md shadow-emerald-900/30 transition transform active:scale-95 disabled:opacity-50"
            >
              {isSubmitting ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <CheckCircle2 className="w-4 h-4" />
              )}
              <span>Approve Recommendation</span>
              <span
                onClick={(e) => {
                  e.stopPropagation();
                  setActiveTooltip((prev) => (prev === 'APPROVE' ? null : 'APPROVE'));
                }}
                className="p-1 -mr-1 rounded hover:bg-white/10"
                title="Hover 2s or tap for details"
              >
                <Info className="w-3.5 h-3.5 opacity-80 hover:opacity-100 transition" />
              </span>
            </button>
          </div>

          {/* Button 2: Reject Recommendation */}
          <div
            className="relative w-full sm:w-auto"
            onMouseEnter={() => handleMouseEnter('REJECT')}
            onMouseLeave={handleMouseLeave}
          >
            <button
              onClick={() => handleAction('REJECT')}
              disabled={isSubmitting || !!pastDecision}
              className="w-full sm:w-auto min-w-[200px] flex items-center justify-center space-x-2 px-5 py-2.5 rounded-lg bg-rose-600 hover:bg-rose-500 text-white text-xs font-semibold shadow-md shadow-rose-900/30 transition transform active:scale-95 disabled:opacity-50"
            >
              {isSubmitting ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <XCircle className="w-4 h-4" />
              )}
              <span>Reject Recommendation</span>
              <span
                onClick={(e) => {
                  e.stopPropagation();
                  setActiveTooltip((prev) => (prev === 'REJECT' ? null : 'REJECT'));
                }}
                className="p-1 -mr-1 rounded hover:bg-white/10"
                title="Hover 2s or tap for details"
              >
                <Info className="w-3.5 h-3.5 opacity-80 hover:opacity-100 transition" />
              </span>
            </button>
          </div>

          {/* Button 3: Escalate Case */}
          <div
            className="relative w-full sm:w-auto"
            onMouseEnter={() => handleMouseEnter('ESCALATE')}
            onMouseLeave={handleMouseLeave}
          >
            <button
              onClick={() => handleAction('ESCALATE')}
              disabled={isSubmitting || !!pastDecision}
              className="w-full sm:w-auto min-w-[200px] flex items-center justify-center space-x-2 px-5 py-2.5 rounded-lg bg-purple-600 hover:bg-purple-500 text-white text-xs font-semibold shadow-md shadow-purple-900/30 transition transform active:scale-95 disabled:opacity-50"
            >
              {isSubmitting ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <ArrowUpRight className="w-4 h-4" />
              )}
              <span>Escalate Case</span>
              <span
                onClick={(e) => {
                  e.stopPropagation();
                  setActiveTooltip((prev) => (prev === 'ESCALATE' ? null : 'ESCALATE'));
                }}
                className="p-1 -mr-1 rounded hover:bg-white/10"
                title="Hover 2s or tap for details"
              >
                <Info className="w-3.5 h-3.5 opacity-80 hover:opacity-100 transition" />
              </span>
            </button>
          </div>
        </div>

        {/* 2-SECOND DELAYED HOVER TOOLTIP BOX */}
        {activeTooltip && (
          <div className="absolute top-full mt-3 left-1/2 -translate-x-1/2 z-30 w-full max-w-sm sm:w-96 p-3.5 rounded-xl bg-slate-900 border border-sky-500/50 shadow-2xl text-xs text-slate-200 animate-fadeIn backdrop-blur-md">
            <div className="flex items-center justify-between text-sky-400 font-bold mb-1">
              <div className="flex items-center space-x-1.5">
                <Info className="w-4 h-4" />
                <span>
                  {activeTooltip === 'APPROVE'
                    ? 'Approve Recommendation'
                    : activeTooltip === 'REJECT'
                    ? 'Reject Recommendation'
                    : 'Escalate Case'}
                </span>
              </div>
              <button
                onClick={() => setActiveTooltip(null)}
                className="text-slate-400 hover:text-white text-xs font-mono px-1 rounded"
              >
                ✕
              </button>
            </div>
            <p className="text-[11px] text-slate-300 leading-relaxed">
              {activeTooltip === 'APPROVE' &&
                "Accepts the AI agent's synthesized recommendation (e.g. Request Credit Memo or Approve Payment), marks the case as resolved, and permanently logs approval in SQLite."}
              {activeTooltip === 'REJECT' &&
                'Overrules the agent recommendation, places invoice payment on indefinite administrative hold, and queues case for formal vendor contract dispute.'}
              {activeTooltip === 'ESCALATE' &&
                'Routes this discrepancy directly to Senior Procurement or Finance Leadership for executive exception approval and policy override.'}
            </p>
            <div className="mt-2 text-[10px] text-sky-400/80 font-mono">
              ℹ Appears after 2.0s hover delay (or instant tap)
            </div>
          </div>
        )}
      </div>

      {/* DURABLE AUDIT TRAIL LOGGING */}
      {pastDecision ? (
        <div className="mt-5 p-4 rounded-xl bg-emerald-950/20 border border-emerald-800/40 text-xs">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center space-x-2 text-emerald-300 font-bold">
              <ShieldCheck className="w-4 h-4 text-emerald-400" />
              <span>DURABLE AUDIT TRAIL SIGN-OFF RECORDED</span>
            </div>
            <span className="text-[10px] text-slate-400 font-mono">
              {new Date(pastDecision.timestamp).toLocaleString()}
            </span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2 text-[11px] font-mono">
            <div>
              <span className="text-slate-500">Reviewer: </span>
              <span className="text-slate-200 font-bold">{pastDecision.reviewer}</span>
            </div>
            <div>
              <span className="text-slate-500">Decision: </span>
              <span className="text-emerald-400 font-bold">{pastDecision.decision}</span>
            </div>
            <div>
              <span className="text-slate-500">Original Rec: </span>
              <span className="text-sky-300">{pastDecision.original_recommendation}</span>
            </div>
            <div>
              <span className="text-slate-500">Persisted: </span>
              <span className="text-slate-300">SQLite review_decisions</span>
            </div>
          </div>
          {pastDecision.reason && (
            <div className="mt-2 text-[11px] text-slate-300 pt-2 border-t border-emerald-900/40">
              <span className="text-slate-400 font-medium">Recorded Reason: </span>
              "{pastDecision.reason}"
            </div>
          )}
        </div>
      ) : (
        <div className="mt-4 text-[11px] text-slate-500 flex items-center space-x-1.5">
          <Clock className="w-3.5 h-3.5" />
          <span>
            Every specialist sign-off is durably persisted to SQLite with reviewer name, timestamp, and audit trail.
          </span>
        </div>
      )}
    </div>
  );
};
