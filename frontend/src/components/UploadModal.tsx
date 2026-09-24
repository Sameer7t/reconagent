import React, { useState } from 'react';
import {
  X,
  UploadCloud,
  FileCheck,
  FileText,
  Layers,
  CheckCircle2,
  AlertCircle,
  Loader2,
  ArrowRight,
} from 'lucide-react';
import { api } from '../services/api';

interface UploadModalProps {
  isOpen: boolean;
  onClose: () => void;
  onReconciledSuccess: (caseId: string) => void;
}

export const UploadModal: React.FC<UploadModalProps> = ({
  isOpen,
  onClose,
  onReconciledSuccess,
}) => {
  const [activeTab, setActiveTab] = useState<'MIXED' | 'TRIPLET'>('MIXED');

  // Mixed mode files
  const [mixedFiles, setMixedFiles] = useState<File[]>([]);

  // Triplet mode files
  const [poFile, setPoFile] = useState<File | null>(null);
  const [invoiceFile, setInvoiceFile] = useState<File | null>(null);
  const [receiptFiles, setReceiptFiles] = useState<File[]>([]);

  // Processing state
  const [isProcessing, setIsProcessing] = useState(false);
  const [result, setResult] = useState<any | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleMixedDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    if (e.dataTransfer.files) {
      const arr = Array.from(e.dataTransfer.files);
      setMixedFiles((prev) => [...prev, ...arr]);
      setError(null);
    }
  };

  const handleMixedFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      const arr = Array.from(e.target.files);
      setMixedFiles((prev) => [...prev, ...arr]);
      setError(null);
    }
  };

  const handleProcess = async () => {
    setIsProcessing(true);
    setError(null);
    setResult(null);

    try {
      let res: any;
      if (activeTab === 'MIXED') {
        if (mixedFiles.length === 0) {
          setError('Please select at least one file to reconcile.');
          setIsProcessing(false);
          return;
        }
        res = await api.uploadMixedFiles(mixedFiles);
      } else {
        if (!poFile || !invoiceFile) {
          setError('Both Purchase Order and Invoice files are required for Triplet mode.');
          setIsProcessing(false);
          return;
        }
        res = await api.reconcileTriplet(poFile, invoiceFile, receiptFiles);
      }

      setResult(res);
      setIsProcessing(false);

      // Notify parent to refresh cases and select new case
      const createdCaseId =
        res.case_id || (res.transactions && res.transactions[0]?.case_id);
      if (createdCaseId) {
        onReconciledSuccess(createdCaseId);
      }
    } catch (err: any) {
      console.error('Reconciliation failed:', err);
      setError(
        err.response?.data?.detail ||
          'Failed to execute reconciliation. Please check document contents.'
      );
      setIsProcessing(false);
    }
  };

  const handleReset = () => {
    setMixedFiles([]);
    setPoFile(null);
    setInvoiceFile(null);
    setReceiptFiles([]);
    setResult(null);
    setError(null);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-fadeIn">
      <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-2xl overflow-hidden shadow-2xl flex flex-col">
        {/* Header */}
        <div className="px-4 sm:px-6 py-3.5 sm:py-4 border-b border-slate-800 flex items-center justify-between bg-slate-900/90">
          <div className="flex items-center space-x-2.5 min-w-0">
            <div className="p-2 rounded-lg bg-sky-500/10 text-sky-400 border border-sky-500/20 flex-shrink-0">
              <UploadCloud className="w-5 h-5" />
            </div>
            <div className="min-w-0">
              <h2 className="font-bold text-white text-sm sm:text-base">Reconcile New Documents</h2>
              <p className="text-xs text-slate-400 truncate max-w-[240px] sm:max-w-none">
                Automated batch ingestion or individual slot uploads
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition flex-shrink-0"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Tab Selector */}
        <div className="flex border-b border-slate-800 bg-slate-950/40 px-3 sm:px-6 pt-2 sm:pt-3 overflow-x-auto whitespace-nowrap">
          <button
            onClick={() => {
              setActiveTab('MIXED');
              setError(null);
            }}
            className={`pb-2.5 sm:pb-3 px-3 sm:px-4 text-xs font-semibold tracking-wide border-b-2 transition flex items-center space-x-2 flex-shrink-0 ${
              activeTab === 'MIXED'
                ? 'border-sky-500 text-sky-400'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <Layers className="w-4 h-4" />
            <span>Option A: Mixed Batch Drop</span>
          </button>
          <button
            onClick={() => {
              setActiveTab('TRIPLET');
              setError(null);
            }}
            className={`pb-2.5 sm:pb-3 px-3 sm:px-4 text-xs font-semibold tracking-wide border-b-2 transition flex items-center space-x-2 flex-shrink-0 ${
              activeTab === 'TRIPLET'
                ? 'border-sky-500 text-sky-400'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            <FileCheck className="w-4 h-4" />
            <span>Option B: Individual Triplet Slots</span>
          </button>
        </div>

        {/* Body Content */}
        <div className="p-4 sm:p-6 flex-1 overflow-y-auto max-h-[60vh]">
          {error && (
            <div
              className={`mb-4 p-3.5 rounded-xl border flex items-start space-x-3 text-xs animate-fadeIn ${
                error.toLowerCase().includes('invalid file')
                  ? 'bg-rose-950/40 border-rose-500/60 text-rose-200 shadow-lg shadow-rose-950/50'
                  : 'bg-rose-950/30 border-rose-800/50 text-rose-300'
              }`}
            >
              <AlertCircle className="w-5 h-5 flex-shrink-0 text-rose-400 mt-0.5" />
              <div className="flex-1">
                {error.toLowerCase().includes('invalid file') && (
                  <div className="flex items-center space-x-1.5 mb-1">
                    <span className="px-2 py-0.5 rounded bg-rose-500/20 text-rose-300 font-bold text-[10px] uppercase tracking-wider border border-rose-500/30">
                      Invalid File
                    </span>
                  </div>
                )}
                <p className="leading-relaxed font-medium">{error}</p>
              </div>
            </div>
          )}

          {result ? (
            <div className="p-5 rounded-xl bg-emerald-950/20 border border-emerald-800/40 text-center space-y-3">
              <CheckCircle2 className="w-10 h-10 text-emerald-400 mx-auto" />
              <h3 className="text-base font-bold text-white">Reconciliation Completed!</h3>
              <p className="text-xs text-slate-300 font-mono">
                Case ID: {result.case_id || result.transactions?.[0]?.case_id}
              </p>
              <p className="text-xs text-slate-400">
                Status: <span className="text-emerald-400 font-semibold">{result.status || 'PROCESSED'}</span> •{' '}
                Recommendation: <span className="text-sky-300 font-semibold">{result.recommendation || 'COMPLETED'}</span>
              </p>
              <div className="pt-2 flex justify-center gap-3">
                <button
                  onClick={handleReset}
                  className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs text-slate-200 transition"
                >
                  Upload Another Batch
                </button>
                <button
                  onClick={onClose}
                  className="px-4 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 text-xs text-white font-semibold transition"
                >
                  View in Dashboard
                </button>
              </div>
            </div>
          ) : activeTab === 'MIXED' ? (
            /* TAB 1: MIXED BATCH DROPZONE */
            <div className="space-y-4">
              <div
                onDragOver={(e) => e.preventDefault()}
                onDrop={handleMixedDrop}
                className="border-2 border-dashed border-slate-700 hover:border-sky-500 rounded-xl p-8 text-center bg-slate-950/30 hover:bg-slate-900/40 transition cursor-pointer"
                onClick={() => document.getElementById('mixed-file-input')?.click()}
              >
                <UploadCloud className="w-10 h-10 text-sky-400 mx-auto mb-3" />
                <p className="text-sm font-semibold text-white mb-1">
                  Drop mixed files here or click to browse
                </p>
                <p className="text-xs text-slate-400 max-w-sm mx-auto">
                  Drag & drop any combination of POs, Invoices, and Goods Receipts (.txt, .pdf, .png).
                  ReconAgent will automatically classify and link them.
                </p>
                <input
                  id="mixed-file-input"
                  type="file"
                  multiple
                  onChange={handleMixedFileSelect}
                  className="hidden"
                />
              </div>

              {mixedFiles.length > 0 && (
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between text-xs text-slate-400">
                    <span>Selected Documents ({mixedFiles.length}):</span>
                    <button
                      onClick={() => setMixedFiles([])}
                      className="text-rose-400 hover:underline text-[11px]"
                    >
                      Clear all
                    </button>
                  </div>
                  <div className="max-h-36 overflow-y-auto space-y-1">
                    {mixedFiles.map((f, i) => (
                      <div
                        key={i}
                        className="px-3 py-1.5 rounded-lg bg-slate-800/80 border border-slate-700 flex items-center justify-between text-xs"
                      >
                        <div className="flex items-center space-x-2 truncate">
                          <FileText className="w-3.5 h-3.5 text-sky-400 flex-shrink-0" />
                          <span className="text-slate-200 truncate font-mono">{f.name}</span>
                        </div>
                        <span className="text-[10px] text-slate-500 font-mono">
                          {(f.size / 1024).toFixed(1)} KB
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            /* TAB 2: TRIPLET SLOTS */
            <div className="space-y-4">
              {/* Slot 1: Purchase Order */}
              <div className="p-3.5 rounded-xl bg-slate-950/40 border border-slate-800">
                <label className="block text-xs font-semibold text-sky-400 uppercase tracking-wide mb-1.5">
                  1. Purchase Order (PO) *
                </label>
                <input
                  type="file"
                  onChange={(e) => {
                    setPoFile(e.target.files?.[0] || null);
                    setError(null);
                  }}
                  className="w-full text-xs text-slate-300 file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-sky-500/20 file:text-sky-300 hover:file:bg-sky-500/30 cursor-pointer"
                />
              </div>

              {/* Slot 2: Vendor Invoice */}
              <div className="p-3.5 rounded-xl bg-slate-950/40 border border-slate-800">
                <label className="block text-xs font-semibold text-indigo-400 uppercase tracking-wide mb-1.5">
                  2. Vendor Invoice *
                </label>
                <input
                  type="file"
                  onChange={(e) => {
                    setInvoiceFile(e.target.files?.[0] || null);
                    setError(null);
                  }}
                  className="w-full text-xs text-slate-300 file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-indigo-500/20 file:text-indigo-300 hover:file:bg-indigo-500/30 cursor-pointer"
                />
              </div>

              {/* Slot 3: Goods Receipt (Optional / Multiple) */}
              <div className="p-3.5 rounded-xl bg-slate-950/40 border border-slate-800">
                <label className="block text-xs font-semibold text-emerald-400 uppercase tracking-wide mb-1.5">
                  3. Goods Receipt Slip(s) (Optional)
                </label>
                <input
                  type="file"
                  multiple
                  onChange={(e) => {
                    setReceiptFiles(e.target.files ? Array.from(e.target.files) : []);
                    setError(null);
                  }}
                  className="w-full text-xs text-slate-300 file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-emerald-500/20 file:text-emerald-300 hover:file:bg-emerald-500/30 cursor-pointer"
                />
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        {!result && (
          <div className="px-4 sm:px-6 py-3.5 sm:py-4 bg-slate-900 border-t border-slate-800 flex flex-col-reverse sm:flex-row items-stretch sm:items-center justify-end gap-2.5 sm:gap-3">
            <button
              onClick={onClose}
              disabled={isProcessing}
              className="w-full sm:w-auto px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs text-slate-300 transition text-center"
            >
              Cancel
            </button>
            <button
              onClick={handleProcess}
              disabled={isProcessing}
              className="w-full sm:w-auto flex items-center justify-center space-x-2 px-5 py-2 rounded-lg bg-gradient-to-r from-sky-500 to-blue-600 hover:from-sky-400 hover:to-blue-500 text-white font-semibold text-xs shadow-md shadow-sky-500/20 transition transform active:scale-95 disabled:opacity-50"
            >
              {isProcessing ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Processing Reconciliation...</span>
                </>
              ) : (
                <>
                  <span>Run Autonomous Reconciliation</span>
                  <ArrowRight className="w-4 h-4" />
                </>
              )}
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

