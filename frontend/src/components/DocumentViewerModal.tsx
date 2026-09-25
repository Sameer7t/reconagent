import React, { useState, useEffect } from 'react';
import { X, FileText, Copy, Check, ExternalLink, Loader2, Eye, AlignLeft } from 'lucide-react';
import { api } from '../services/api';
import { DocumentContentData } from '../types';

interface DocumentViewerModalProps {
  isOpen: boolean;
  onClose: () => void;
  fileName: string | null;
  filePath?: string | null;
  docType?: string;
}

export const DocumentViewerModal: React.FC<DocumentViewerModalProps> = ({
  isOpen,
  onClose,
  fileName,
  filePath,
  docType,
}) => {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<DocumentContentData | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const effectiveName = fileName || data?.file_name || filePath || '';
  const isPdf = effectiveName.toLowerCase().endsWith('.pdf');
  const isImage = ['.png', '.jpg', '.jpeg', '.tiff', '.tif'].some((ext) =>
    effectiveName.toLowerCase().endsWith(ext)
  );

  const [viewMode, setViewMode] = useState<'VISUAL' | 'TEXT'>(isPdf || isImage ? 'VISUAL' : 'TEXT');

  // Sync default view mode whenever target file changes
  useEffect(() => {
    if (effectiveName) {
      if (
        effectiveName.toLowerCase().endsWith('.pdf') ||
        ['.png', '.jpg', '.jpeg', '.tiff', '.tif'].some((ext) =>
          effectiveName.toLowerCase().endsWith(ext)
        )
      ) {
        setViewMode('VISUAL');
      } else {
        setViewMode('TEXT');
      }
    }
  }, [effectiveName]);

  const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null;
  const tokenQuery = token ? `&token=${encodeURIComponent(token)}` : '';

  const rawUrl = fileName
    ? `/api/documents/raw?file_name=${encodeURIComponent(fileName)}${tokenQuery}`
    : filePath
    ? `/api/documents/raw?file_path=${encodeURIComponent(filePath)}${tokenQuery}`
    : '';

  useEffect(() => {
    if (isOpen && (fileName || filePath)) {
      setLoading(true);
      setError(null);
      api
        .getDocumentContent(fileName || undefined, filePath || undefined)
        .then((res) => {
          setData(res);
          setLoading(false);
        })
        .catch((err) => {
          console.error('Failed to load document content:', err);
          setError(err.response?.data?.detail || 'Failed to load document on server.');
          setLoading(false);
        });
    } else {
      setData(null);
      setError(null);
    }
  }, [isOpen, fileName, filePath]);

  if (!isOpen) return null;

  const handleCopy = () => {
    if (data?.content) {
      navigator.clipboard.writeText(data.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const lines = data?.content ? data.content.split('\n') : [];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6 bg-slate-950/80 backdrop-blur-sm animate-fadeIn">
      <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-5xl h-[88vh] flex flex-col shadow-2xl overflow-hidden">
        {/* Modal Header */}
        <div className="px-4 sm:px-6 py-3.5 border-b border-slate-800 flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-slate-900/95 flex-shrink-0">
          <div className="flex items-center space-x-3 min-w-0">
            <div className="p-2 rounded-lg bg-sky-500/10 text-sky-400 border border-sky-500/20 flex-shrink-0">
              <FileText className="w-5 h-5" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center space-x-2">
                <span className="font-semibold text-white text-sm sm:text-base truncate max-w-[220px] sm:max-w-md">
                  {fileName || data?.file_name || 'Document Viewer'}
                </span>
                <span className="px-2 py-0.5 rounded text-[10px] font-mono font-semibold uppercase bg-slate-800 text-sky-300 border border-slate-700 flex-shrink-0">
                  {docType || data?.document_type || 'SOURCE DOC'}
                </span>
                {isPdf && (
                  <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-bold uppercase bg-rose-500/15 text-rose-300 border border-rose-500/30 flex-shrink-0">
                    PDF
                  </span>
                )}
              </div>
              <p className="text-xs text-slate-400 font-mono truncate max-w-[240px] sm:max-w-md">
                {filePath || data?.file_path || 'In-Memory Content'}
              </p>
            </div>
          </div>

          <div className="flex items-center justify-between sm:justify-end space-x-2 flex-wrap gap-y-2">
            {/* Mode Switcher Tabs for PDFs & Images */}
            {(isPdf || isImage) && (
              <div className="flex items-center bg-slate-950 p-1 rounded-lg border border-slate-800 mr-1">
                <button
                  onClick={() => setViewMode('VISUAL')}
                  className={`flex items-center space-x-1.5 px-2.5 py-1 rounded text-xs font-medium transition ${
                    viewMode === 'VISUAL'
                      ? 'bg-sky-500 text-white shadow-sm'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <Eye className="w-3.5 h-3.5" />
                  <span>{isPdf ? 'Visual PDF' : 'Image'}</span>
                </button>
                <button
                  onClick={() => setViewMode('TEXT')}
                  className={`flex items-center space-x-1.5 px-2.5 py-1 rounded text-xs font-medium transition ${
                    viewMode === 'TEXT'
                      ? 'bg-sky-500 text-white shadow-sm'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <AlignLeft className="w-3.5 h-3.5" />
                  <span>Extracted Text</span>
                </button>
              </div>
            )}

            {/* Open in full tab button */}
            {rawUrl && (
              <a
                href={rawUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs text-sky-400 hover:text-sky-300 transition flex items-center space-x-1.5"
                title="Open in new browser tab"
              >
                <ExternalLink className="w-3.5 h-3.5" />
                <span className="hidden sm:inline">Open in Tab</span>
              </a>
            )}

            {/* Copy Content (Visible in text view) */}
            {viewMode === 'TEXT' && (
              <button
                onClick={handleCopy}
                disabled={!data?.content}
                className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs text-slate-300 hover:text-white transition flex items-center space-x-1.5 disabled:opacity-40"
              >
                {copied ? (
                  <>
                    <Check className="w-3.5 h-3.5 text-emerald-400" />
                    <span className="text-emerald-400">Copied!</span>
                  </>
                ) : (
                  <>
                    <Copy className="w-3.5 h-3.5" />
                    <span>Copy Text</span>
                  </>
                )}
              </button>
            )}

            <button
              onClick={onClose}
              className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition"
              title="Close viewer"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Modal Body */}
        <div className="flex-1 overflow-hidden bg-slate-950 relative flex flex-col">
          {viewMode === 'VISUAL' && isPdf ? (
            <div className="w-full h-full flex flex-col bg-slate-950">
              <iframe
                src={rawUrl}
                title={fileName || 'PDF Document Viewer'}
                className="w-full h-full border-0 bg-slate-900"
              />
            </div>
          ) : viewMode === 'VISUAL' && isImage ? (
            <div className="w-full h-full p-4 flex items-center justify-center overflow-auto bg-slate-950">
              <img
                src={rawUrl}
                alt={fileName || 'Document Image'}
                className="max-w-full max-h-full object-contain rounded-lg shadow-xl border border-slate-800"
              />
            </div>
          ) : (
            <div className="w-full h-full overflow-y-auto p-4 font-mono text-xs text-slate-200">
              {loading ? (
                <div className="py-24 flex flex-col items-center justify-center space-y-3">
                  <Loader2 className="w-8 h-8 text-sky-400 animate-spin" />
                  <p className="text-slate-400 text-xs">Streaming source document from server...</p>
                </div>
              ) : error ? (
                <div className="py-16 px-6 text-center">
                  <p className="text-rose-400 font-sans font-semibold mb-1">Failed to read file</p>
                  <p className="text-slate-400 text-xs font-mono">{error}</p>
                </div>
              ) : (
                <div className="divide-y divide-slate-900">
                  {lines.map((line, idx) => (
                    <div key={idx} className="flex hover:bg-slate-900/50 py-0.5 leading-relaxed">
                      <span className="w-10 text-right pr-3 select-none text-slate-600 font-mono text-[11px]">
                        {idx + 1}
                      </span>
                      <span className="flex-1 pl-2 whitespace-pre-wrap break-all">{line}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Modal Footer */}
        <div className="px-6 py-2.5 bg-slate-900 border-t border-slate-800 flex items-center justify-between text-xs text-slate-400 flex-shrink-0">
          <div className="flex items-center space-x-4">
            {viewMode === 'TEXT' ? (
              <span>{lines.length} lines</span>
            ) : isPdf ? (
              <span className="text-sky-300 font-sans">
                Interactive PDF Preview (Zoom, Page Navigation & Print enabled)
              </span>
            ) : (
              <span className="text-sky-300 font-sans">Original Visual Image</span>
            )}
            <span>{data?.file_size_bytes ? `${data.file_size_bytes} bytes` : ''}</span>
          </div>
          <span className="text-[11px] text-slate-500 font-sans">
            Click outside or ESC to close
          </span>
        </div>
      </div>
    </div>
  );
};
