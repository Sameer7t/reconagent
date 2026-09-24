import React from 'react';
import { Search, ShieldAlert, CheckCircle, XCircle, ArrowDown, FileText, CornerDownRight } from 'lucide-react';
import { DeepEvidenceProvenance, InvestigationData } from '../types';

interface EvidenceCardProps {
  investigation: InvestigationData;
  onViewDoc?: (fileName: string, docType: string) => void;
}

export const EvidenceCard: React.FC<EvidenceCardProps> = ({ investigation, onViewDoc }) => {
  const { provenance } = investigation;
  const isAuth = provenance?.authorization_status?.is_authorized ?? false;

  return (
    <div className="bg-slate-850 rounded-xl border border-slate-700/80 p-5 shadow-lg">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 pb-3 mb-4 border-b border-slate-700/60">
        <div className="flex items-center space-x-2.5">
          <div className="p-2 rounded-lg bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 flex-shrink-0">
            <Search className="w-5 h-5" />
          </div>
          <div>
            <h3 className="font-bold text-slate-100 tracking-wide text-sm uppercase">
              AI Investigation & Evidence Provenance
            </h3>
            <p className="text-xs text-slate-400">
              Field-level citations, document verification, and authorization policy checks
            </p>
          </div>
        </div>

        <div className="self-start sm:self-auto px-2.5 py-1 rounded-full text-xs font-mono font-medium bg-slate-800 text-slate-300 border border-slate-700">
          Confidence: <span className={`font-bold ${investigation.confidence_score >= 0.9 ? 'text-emerald-400' : investigation.confidence_score >= 0.75 ? 'text-amber-400' : 'text-rose-400'}`}>
            {Math.round(investigation.confidence_score * 100)}%
          </span>
        </div>
      </div>

      {/* Audit Provenance Flow: Finding -> Evidence -> Source Doc -> Specific Field/Value */}
      <div className="mb-5 p-3 rounded-lg bg-slate-900/80 border border-slate-800">
        <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
          <span>Audit Provenance Hierarchy</span>
          <span className="text-indigo-400 font-mono text-xs">(Section 7.3 Compliance)</span>
        </div>

        <div className="flex items-center flex-wrap gap-2 text-xs font-medium text-slate-300">
          <span className="px-2 py-1 rounded bg-indigo-950/40 text-indigo-300 border border-indigo-700/40">
            1. Finding
          </span>
          <span className="text-slate-500">➔</span>
          <span className="px-2 py-1 rounded bg-sky-950/40 text-sky-300 border border-sky-700/40">
            2. Evidence
          </span>
          <span className="text-slate-500">➔</span>
          <span className="px-2 py-1 rounded bg-emerald-950/40 text-emerald-300 border border-emerald-700/40">
            3. Source Document
          </span>
          <span className="text-slate-500">➔</span>
          <span className="px-2 py-1 rounded bg-amber-950/40 text-amber-300 border border-amber-700/40">
            4. Specific Field/Value
          </span>
        </div>
      </div>

      {/* Root-Cause Synthesis Box */}
      <div className="mb-5 p-4 rounded-xl bg-slate-900/60 border border-slate-700/80">
        <div className="text-xs font-semibold text-indigo-400 mb-1 flex items-center gap-1.5">
          <CornerDownRight className="w-4 h-4 text-indigo-400" />
          <span>Agent Synthesized Root-Cause Finding:</span>
        </div>
        <p className="text-xs text-slate-200 leading-relaxed font-sans whitespace-pre-line">
          {investigation.agent_conclusion ||
            'Cross-document reconciliation evaluated against available transaction records.'}
        </p>
      </div>

      {/* Deep Comparative Field Grid (PO vs Invoice vs Difference) */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-5">
        {/* PO Field Block */}
        <div className="p-3 rounded-lg bg-slate-900/70 border border-slate-800 flex flex-col justify-between min-w-0 overflow-hidden">
          <div className="min-w-0">
            <div className="flex items-center justify-between mb-1.5 min-w-0 gap-1.5">
              <span className="text-[11px] font-semibold text-sky-400 uppercase tracking-wide flex-shrink-0">
                Purchase Order
              </span>
              {provenance?.po_field?.source_document ? (
                <button
                  onClick={() =>
                    onViewDoc &&
                    onViewDoc(provenance.po_field.source_document, 'PURCHASE_ORDER')
                  }
                  title={provenance.po_field.source_document}
                  className="text-[10px] text-sky-300 hover:text-white underline font-mono flex items-center gap-1 min-w-0 max-w-[140px] truncate"
                >
                  <FileText className="w-3 h-3 flex-shrink-0" />
                  <span className="truncate">{provenance.po_field.source_document}</span>
                </button>
              ) : null}
            </div>
            <div className="font-mono text-xs text-slate-300 space-y-1">
              <div>
                <span className="text-slate-500">field: </span>
                <span className="text-sky-300 font-semibold">
                  {provenance?.po_field?.source_document ? (provenance?.po_field?.field_name || 'unit_price') : '—'}
                </span>
              </div>
              <div>
                <span className="text-slate-500">value: </span>
                <span className="text-white text-sm font-bold">
                  {provenance?.po_field?.source_document && provenance?.po_field?.value ? provenance.po_field.value : '—'}
                </span>
              </div>
            </div>
          </div>
          <div className="mt-2 pt-2 border-t border-slate-800/80 text-[10px] text-slate-400">
            {provenance?.po_field?.source_document
              ? (provenance?.po_field?.label || 'Authorized rate on PO')
              : 'No Purchase Order on file'}
          </div>
        </div>

        {/* Invoice Field Block */}
        <div className="p-3 rounded-lg bg-slate-900/70 border border-slate-800 flex flex-col justify-between min-w-0 overflow-hidden">
          <div className="min-w-0">
            <div className="flex items-center justify-between mb-1.5 min-w-0 gap-1.5">
              <span className="text-[11px] font-semibold text-indigo-400 uppercase tracking-wide flex-shrink-0">
                Vendor Invoice
              </span>
              {provenance?.invoice_field?.source_document ? (
                <button
                  onClick={() =>
                    onViewDoc &&
                    onViewDoc(provenance.invoice_field.source_document, 'INVOICE')
                  }
                  title={provenance.invoice_field.source_document}
                  className="text-[10px] text-indigo-300 hover:text-white underline font-mono flex items-center gap-1 min-w-0 max-w-[140px] truncate"
                >
                  <FileText className="w-3 h-3 flex-shrink-0" />
                  <span className="truncate">{provenance.invoice_field.source_document}</span>
                </button>
              ) : null}
            </div>
            <div className="font-mono text-xs text-slate-300 space-y-1">
              <div>
                <span className="text-slate-500">field: </span>
                <span className="text-indigo-300 font-semibold">
                  {provenance?.invoice_field?.source_document ? (provenance?.invoice_field?.field_name || 'unit_price') : '—'}
                </span>
              </div>
              <div>
                <span className="text-slate-500">value: </span>
                <span className="text-amber-400 text-sm font-bold">
                  {provenance?.invoice_field?.source_document && provenance?.invoice_field?.value ? provenance.invoice_field.value : '—'}
                </span>
              </div>
            </div>
          </div>
          <div className="mt-2 pt-2 border-t border-slate-800/80 text-[10px] text-slate-400">
            {provenance?.invoice_field?.source_document
              ? (provenance?.invoice_field?.label || 'Billed rate on vendor invoice')
              : 'No Invoice on file'}
          </div>
        </div>

        {/* Calculated Difference Block */}
        <div className="p-3 rounded-lg bg-amber-950/20 border border-amber-800/40 flex flex-col justify-between min-w-0 overflow-hidden">
          <div>
            <span className="text-[11px] font-semibold text-amber-400 uppercase tracking-wide">
              Discrepancy Variance
            </span>
            <div className="font-mono text-xs text-amber-200 mt-2 space-y-1">
              <div>
                <span className="text-amber-400/70">type: </span>
                <span className="font-bold">
                  {provenance?.po_field?.source_document && provenance?.invoice_field?.source_document
                    ? (provenance?.variance_type || 'PRICE_MISMATCH')
                    : (provenance?.variance_type || 'MISSING_DOCUMENTS')}
                </span>
              </div>
              <div>
                <span className="text-amber-400/70">difference: </span>
                <span className="text-base font-bold text-amber-300">
                  {provenance?.po_field?.source_document && provenance?.invoice_field?.source_document
                    ? (provenance?.difference_text || '—')
                    : '—'}
                </span>
              </div>
            </div>
          </div>
          <div className="mt-2 pt-2 border-t border-amber-900/40 text-[10px] text-amber-300/80">
            {provenance?.po_field?.source_document && provenance?.invoice_field?.source_document
              ? (provenance?.variance_type === 'MATCHED' ? 'Amounts match authorized contract' : 'Billed exceeds authorized contract')
              : 'Cross-document comparison not applicable'}
          </div>
        </div>
      </div>

      {/* Authorization Policy Outcome */}
      <div
        className={`p-3.5 rounded-lg border flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 mb-4 ${
          isAuth
            ? 'bg-emerald-950/20 border-emerald-800/40 text-emerald-300'
            : 'bg-rose-950/20 border-rose-800/40 text-rose-300'
        }`}
      >
        <div className="flex items-center space-x-2.5">
          {isAuth ? (
            <CheckCircle className="w-4 h-4 text-emerald-400 flex-shrink-0" />
          ) : (
            <XCircle className="w-4 h-4 text-rose-400 flex-shrink-0" />
          )}
          <div className="text-xs">
            <span className="font-bold">
              {isAuth ? 'Authorization Verified: ' : 'Authorization Check Failed: '}
            </span>
            <span>
              {provenance?.authorization_status?.note ||
                'No approved price change, amendment, or formal escalation order found on file.'}
            </span>
          </div>
        </div>
        {provenance?.authorization_status?.approval_ref && (
          <span className="self-start sm:self-auto text-[11px] font-mono px-2 py-0.5 rounded bg-slate-900 border border-slate-700">
            {provenance.authorization_status.approval_ref}
          </span>
        )}
      </div>

      {/* Verified Provenance Checkmarks Ribbon */}
      <div className="pt-3 border-t border-slate-800 flex items-center flex-wrap gap-2 text-[11px] text-slate-400">
        <span className="text-slate-500 font-semibold">Verified Provenance:</span>
        {provenance?.verified_checks && provenance.verified_checks.length > 0 ? (
          provenance.verified_checks.map((check, idx) => (
            <span
              key={idx}
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-slate-900 border border-slate-800 text-emerald-400 font-mono text-[10px]"
            >
              <CheckCircle className="w-3 h-3 text-emerald-400" />
              {check}
            </span>
          ))
        ) : (
          <span className="text-slate-500 italic text-[10px]">No cross-matching checks applicable</span>
        )}
      </div>
    </div>
  );
};

