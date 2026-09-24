import React, { useState, useMemo } from 'react';
import { Search, Filter, RotateCcw, ChevronRight, ChevronDown, CheckCircle2, AlertTriangle, XCircle, Calendar, Clock, FileText, ExternalLink } from 'lucide-react';
import { CaseSummary } from '../types';

interface CasesTableProps {
  cases: CaseSummary[];
  selectedCaseId: string | null;
  onSelectCase: (caseId: string) => void;
  activeQuickFilter?: string;
  onClearQuickFilter?: () => void;
  onViewDoc?: (fileName: string, docType: string, filePath?: string) => void;
  selectedCaseDetails?: {
    po_file?: string;
    invoice_file?: string;
    receipt_files?: string[];
    po_file_path?: string;
    invoice_file_path?: string;
    receipt_file_path?: string;
  } | null;
}

export const CasesTable: React.FC<CasesTableProps> = ({
  cases,
  selectedCaseId,
  onSelectCase,
  activeQuickFilter,
  onClearQuickFilter,
  onViewDoc,
  selectedCaseDetails,
}) => {
  // 4 Independent Column Filters
  const [caseSearch, setCaseSearch] = useState('');
  const [vendorFilter, setVendorFilter] = useState('ALL');
  const [statusFilter, setStatusFilter] = useState('ALL');
  const [actionFilter, setActionFilter] = useState('ALL');

  // Date Range Filters
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [startTime, setStartTime] = useState('');
  const [endTime, setEndTime] = useState('');
  const [datePreset, setDatePreset] = useState<'ALL' | 'TODAY' | '7D' | '30D' | 'CUSTOM'>('ALL');

  const handlePresetClick = (preset: 'ALL' | 'TODAY' | '7D' | '30D') => {
    setDatePreset(preset);
    if (preset === 'ALL') {
      setStartDate('');
      setEndDate('');
      return;
    }
    const now = new Date();
    const toDateStr = (d: Date) => {
      const year = d.getFullYear();
      const month = String(d.getMonth() + 1).padStart(2, '0');
      const day = String(d.getDate()).padStart(2, '0');
      return `${year}-${month}-${day}`;
    };
    const todayStr = toDateStr(now);

    if (preset === 'TODAY') {
      setStartDate(todayStr);
      setEndDate(todayStr);
    } else if (preset === '7D') {
      const d7 = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
      setStartDate(toDateStr(d7));
      setEndDate(todayStr);
    } else if (preset === '30D') {
      const d30 = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
      setStartDate(toDateStr(d30));
      setEndDate(todayStr);
    }
  };

  // Format processed timestamp cleanly as YYYY-MM-DD HH:mm
  const formatProcessedDateTime = (ts?: string) => {
    if (!ts) return null;
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

  // Extract unique vendors for dropdown
  const uniqueVendors = useMemo(() => {
    const set = new Set<string>();
    cases.forEach((c) => {
      if (c.vendor_name) set.add(c.vendor_name);
    });
    return Array.from(set).sort();
  }, [cases]);

  // Extract unique statuses
  const uniqueStatuses = useMemo(() => {
    const set = new Set<string>();
    cases.forEach((c) => {
      if (c.status) set.add(c.status);
    });
    return Array.from(set).sort();
  }, [cases]);

  // Extract unique actions
  const uniqueActions = useMemo(() => {
    const set = new Set<string>();
    cases.forEach((c) => {
      const act = c.action || (c.requires_human_review ? 'Review Required' : 'Eligible');
      set.add(act);
    });
    return Array.from(set).sort();
  }, [cases]);

  // Filtered cases combining all filters + quick filter + date range filter
  const filteredCases = useMemo(() => {
    return cases.filter((c) => {
      // Quick filter from metrics
      if (activeQuickFilter === 'MATCHED' && c.status !== 'MATCHED') return false;
      if (activeQuickFilter === 'DISCREPANCIES' && c.status === 'MATCHED') return false;
      if (activeQuickFilter === 'UNDER_REVIEW' && !c.requires_human_review) return false;

      // 1. Case ID search
      if (caseSearch.trim()) {
        const query = caseSearch.toLowerCase();
        const cid = (c.case_id || '').toLowerCase();
        const po = (c.po_number || '').toLowerCase();
        const inv = (c.invoice_number || '').toLowerCase();
        if (!cid.includes(query) && !po.includes(query) && !inv.includes(query)) {
          return false;
        }
      }

      // 2. Vendor filter
      if (vendorFilter !== 'ALL' && c.vendor_name !== vendorFilter) {
        return false;
      }

      // 3. Status filter
      if (statusFilter !== 'ALL' && c.status !== statusFilter) {
        return false;
      }

      // 4. Action filter
      if (actionFilter !== 'ALL') {
        const act = c.action || (c.requires_human_review ? 'Review Required' : 'Eligible');
        if (act !== actionFilter) return false;
      }

      // 5. Date & Time Range filter
      if (startDate || endDate || startTime || endTime) {
        if (!c.created_at) return false;
        const cDateStr = c.created_at.slice(0, 10);
        if (startDate && cDateStr < startDate) return false;
        if (endDate && cDateStr > endDate) return false;

        if (startTime || endTime) {
          let cTimeStr = '';
          try {
            const d = new Date(c.created_at);
            if (!isNaN(d.getTime())) {
              const hours = String(d.getHours()).padStart(2, '0');
              const minutes = String(d.getMinutes()).padStart(2, '0');
              cTimeStr = `${hours}:${minutes}`;
            } else if (c.created_at.includes('T')) {
              cTimeStr = c.created_at.split('T')[1].slice(0, 5);
            }
          } catch {
            if (c.created_at.includes('T')) {
              cTimeStr = c.created_at.split('T')[1].slice(0, 5);
            }
          }

          if (cTimeStr) {
            if (startTime && cTimeStr < startTime) return false;
            if (endTime && cTimeStr > endTime) return false;
          }
        }
      }

      return true;
    });
  }, [cases, activeQuickFilter, caseSearch, vendorFilter, statusFilter, actionFilter, startDate, endDate, startTime, endTime]);

  const hasActiveFilters =
    caseSearch !== '' ||
    vendorFilter !== 'ALL' ||
    statusFilter !== 'ALL' ||
    actionFilter !== 'ALL' ||
    startDate !== '' ||
    endDate !== '' ||
    startTime !== '' ||
    endTime !== '' ||
    (activeQuickFilter && activeQuickFilter !== 'ALL');

  const handleResetFilters = () => {
    setCaseSearch('');
    setVendorFilter('ALL');
    setStatusFilter('ALL');
    setActionFilter('ALL');
    setStartDate('');
    setEndDate('');
    setStartTime('');
    setEndTime('');
    setDatePreset('ALL');
    if (onClearQuickFilter) onClearQuickFilter();
  };

  // Status badge styling
  const renderStatusBadge = (status: string) => {
    const upper = (status || '').toUpperCase();
    if (upper === 'MATCHED' || upper === 'MATCHED_WITH_TOLERANCE' || upper === 'PERFECT') {
      return (
        <span className="inline-block px-1.5 py-0.5 rounded text-[10px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 truncate max-w-full text-center">
          MATCHED
        </span>
      );
    }
    if (upper.includes('REJECT') || upper === 'REJECT_INVOICE') {
      return (
        <span className="inline-block px-1.5 py-0.5 rounded text-[10px] font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/20 truncate max-w-full text-center">
          REJECTED
        </span>
      );
    }
    if (upper.includes('CALCULATION') || upper.includes('MATH')) {
      return (
        <span className="inline-block px-1.5 py-0.5 rounded text-[10px] font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/20 truncate max-w-full text-center">
          CALCULATION ERROR
        </span>
      );
    }
    if (upper.includes('REVIEW') || upper === 'REVIEW_REQUIRED') {
      return (
        <span className="inline-block px-1.5 py-0.5 rounded text-[10px] font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20 truncate max-w-full text-center">
          REVIEW REQUIRED
        </span>
      );
    }
    if (upper.includes('PRICE')) {
      return (
        <span className="inline-block px-1.5 py-0.5 rounded text-[10px] font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20 truncate max-w-full text-center">
          PRICE
        </span>
      );
    }
    if (upper.includes('QUANTITY') || upper.includes('SHORTAGE')) {
      return (
        <span className="inline-block px-1.5 py-0.5 rounded text-[10px] font-semibold bg-orange-500/10 text-orange-400 border border-orange-500/20 truncate max-w-full text-center">
          QUANTITY
        </span>
      );
    }
    if (upper.includes('MISSING')) {
      return (
        <span className="inline-block px-1.5 py-0.5 rounded text-[10px] font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/20 truncate max-w-full text-center">
          MISSING
        </span>
      );
    }
    return (
      <span className="inline-block px-1.5 py-0.5 rounded text-[10px] font-semibold bg-slate-800 text-slate-300 border border-slate-700 truncate max-w-full text-center">
        {status}
      </span>
    );
  };

  // Action badge styling
  const renderActionBadge = (actionStr?: string, requiresReview?: boolean) => {
    const act = actionStr || (requiresReview ? 'Review' : 'Eligible');
    const lower = act.toLowerCase();
    if (lower.includes('eligible')) {
      return (
        <span className="inline-block px-1.5 py-0.5 rounded text-[10px] font-medium bg-emerald-500/10 text-emerald-300 border border-emerald-500/20 truncate max-w-full">
          Eligible
        </span>
      );
    }
    if (lower.includes('review')) {
      return (
        <span className="inline-block px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-500/10 text-amber-300 border border-amber-500/20 truncate max-w-full">
          Review
        </span>
      );
    }
    if (lower.includes('approved')) {
      return (
        <span className="inline-block px-1.5 py-0.5 rounded text-[10px] font-medium bg-sky-500/10 text-sky-300 border border-sky-500/20 truncate max-w-full">
          Approved
        </span>
      );
    }
    if (lower.includes('rejected')) {
      return (
        <span className="inline-block px-1.5 py-0.5 rounded text-[10px] font-medium bg-rose-500/10 text-rose-300 border border-rose-500/20 truncate max-w-full">
          Rejected
        </span>
      );
    }
    if (lower.includes('escalat')) {
      return (
        <span className="inline-block px-1.5 py-0.5 rounded text-[10px] font-medium bg-purple-500/10 text-purple-300 border border-purple-500/20 truncate max-w-full">
          Escalated
        </span>
      );
    }
    return (
      <span className="inline-block px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-800 text-slate-300 border border-slate-700 truncate max-w-full">
        {act}
      </span>
    );
  };

  return (
    <div className="bg-slate-850 rounded-xl border border-slate-700/80 shadow-lg flex flex-col overflow-hidden h-full min-h-0">
      {/* Table Header & Controls */}
      <div className="p-2.5 sm:p-3 border-b border-slate-700/70 bg-slate-900/60 flex-shrink-0">
        <div className="flex items-center justify-between gap-2 mb-2">
          <div className="flex items-center space-x-1.5 sm:space-x-2 min-w-0">
            <Filter className="w-4 h-4 text-sky-400 flex-shrink-0" />
            <h2 className="font-bold text-slate-100 text-xs sm:text-sm tracking-wide uppercase truncate">
              Recent Cases ({filteredCases.length})
            </h2>
          </div>
          {hasActiveFilters && (
            <button
              onClick={handleResetFilters}
              className="flex items-center space-x-1 text-[10px] sm:text-[11px] font-medium text-sky-400 hover:text-sky-300 bg-sky-500/10 px-2 py-0.5 rounded border border-sky-500/20 transition flex-shrink-0"
            >
              <RotateCcw className="w-3 h-3" />
              <span>Reset</span>
            </button>
          )}
        </div>

        {/* 4 INDEPENDENT COLUMN FILTERS (2x2 Grid fits sidebar without overflow) */}
        <div className="grid grid-cols-2 gap-1.5 text-xs">
          {/* 1. Case ID filter */}
          <div className="relative min-w-0">
            <Search className="w-3 h-3 absolute left-2 top-2 text-slate-500" />
            <input
              type="text"
              placeholder="Search ID..."
              value={caseSearch}
              onChange={(e) => setCaseSearch(e.target.value)}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg pl-6 pr-2 py-1 text-[11px] text-white placeholder-slate-500 focus:outline-none focus:border-sky-500 transition"
            />
          </div>

          {/* 2. Vendor filter */}
          <div className="min-w-0">
            <select
              value={vendorFilter}
              onChange={(e) => setVendorFilter(e.target.value)}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-2 py-1 text-[11px] text-slate-200 focus:outline-none focus:border-sky-500 transition cursor-pointer truncate"
            >
              <option value="ALL">All Vendors</option>
              {uniqueVendors.map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
          </div>

          {/* 3. Status filter */}
          <div className="min-w-0">
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-2 py-1 text-[11px] text-slate-200 focus:outline-none focus:border-sky-500 transition cursor-pointer truncate"
            >
              <option value="ALL">All Statuses</option>
              {uniqueStatuses.map((st) => (
                <option key={st} value={st}>
                  {st}
                </option>
              ))}
            </select>
          </div>

          {/* 4. Action filter */}
          <div className="min-w-0">
            <select
              value={actionFilter}
              onChange={(e) => setActionFilter(e.target.value)}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-2 py-1 text-[11px] text-slate-200 focus:outline-none focus:border-sky-500 transition cursor-pointer truncate"
            >
              <option value="ALL">All Actions</option>
              {uniqueActions.map((act) => (
                <option key={act} value={act}>
                  {act}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* 5. DATE & TIME RANGE FILTER CONTROLS */}
        <div className="mt-2 pt-2 border-t border-slate-700/60 flex flex-col gap-1.5">
          {/* Date Row */}
          <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-1.5">
            <div className="flex items-center gap-1 min-w-0 flex-1">
              <Calendar className="w-3 h-3 text-sky-400 flex-shrink-0" />
              <span className="text-[10px] uppercase font-semibold text-slate-400 flex-shrink-0 w-8">Date:</span>
              <input
                type="date"
                value={startDate}
                onChange={(e) => {
                  setStartDate(e.target.value);
                  setDatePreset('CUSTOM');
                }}
                className="bg-slate-800 border border-slate-700 rounded px-1.5 py-0.5 text-[10px] text-slate-200 focus:outline-none focus:border-sky-500 w-full min-w-0"
                title="Start Date"
              />
              <span className="text-slate-500 text-[10px] flex-shrink-0">to</span>
              <input
                type="date"
                value={endDate}
                onChange={(e) => {
                  setEndDate(e.target.value);
                  setDatePreset('CUSTOM');
                }}
                className="bg-slate-800 border border-slate-700 rounded px-1.5 py-0.5 text-[10px] text-slate-200 focus:outline-none focus:border-sky-500 w-full min-w-0"
                title="End Date"
              />
            </div>

            {/* Quick Preset Buttons */}
            <div className="flex items-center gap-1 flex-shrink-0 self-end sm:self-auto">
              {(['ALL', 'TODAY', '7D', '30D'] as const).map((preset) => (
                <button
                  key={preset}
                  type="button"
                  onClick={() => handlePresetClick(preset)}
                  className={`px-1.5 py-0.5 rounded text-[9px] font-medium transition ${
                    datePreset === preset
                      ? 'bg-sky-500/20 text-sky-300 border border-sky-500/40'
                      : 'bg-slate-800 text-slate-400 hover:text-slate-200 border border-slate-700/60'
                  }`}
                >
                  {preset === 'ALL' ? 'All' : preset === 'TODAY' ? 'Today' : preset === '7D' ? '7d' : '30d'}
                </button>
              ))}
            </div>
          </div>

          {/* Time Row */}
          <div className="flex items-center gap-1 min-w-0">
            <Clock className="w-3 h-3 text-sky-400 flex-shrink-0" />
            <span className="text-[10px] uppercase font-semibold text-slate-400 flex-shrink-0 w-8">Time:</span>
            <input
              type="time"
              value={startTime}
              onChange={(e) => setStartTime(e.target.value)}
              className="bg-slate-800 border border-slate-700 rounded px-1.5 py-0.5 text-[10px] text-slate-200 focus:outline-none focus:border-sky-500 w-full min-w-0"
              title="Start Time (HH:MM)"
            />
            <span className="text-slate-500 text-[10px] flex-shrink-0">to</span>
            <input
              type="time"
              value={endTime}
              onChange={(e) => setEndTime(e.target.value)}
              className="bg-slate-800 border border-slate-700 rounded px-1.5 py-0.5 text-[10px] text-slate-200 focus:outline-none focus:border-sky-500 w-full min-w-0"
              title="End Time (HH:MM)"
            />
            {(startTime || endTime) && (
              <button
                type="button"
                onClick={() => {
                  setStartTime('');
                  setEndTime('');
                }}
                title="Clear Time Filter"
                className="px-1.5 py-0.5 rounded text-[9px] font-medium bg-slate-800 text-slate-400 hover:text-rose-400 border border-slate-700/60 flex-shrink-0"
              >
                Clear
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Table Content (Fits 100% width and height with NO outer scroll) */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden min-h-0">
        <table className="w-full text-left border-collapse table-fixed">
          <colgroup>
            <col className="w-[28%]" />
            <col className="w-[30%]" />
            <col className="w-[22%]" />
            <col className="w-[20%]" />
          </colgroup>
          <thead className="bg-slate-900/80 sticky top-0 z-10 text-[10px] uppercase tracking-wider text-slate-400 border-b border-slate-700">
            <tr>
              <th className="py-2 px-1.5 sm:px-2 font-semibold truncate">Case</th>
              <th className="py-2 px-1.5 sm:px-2 font-semibold truncate">Vendor</th>
              <th className="py-2 px-1.5 sm:px-2 font-semibold text-center truncate">Status</th>
              <th className="py-2 px-1.5 sm:px-2 font-semibold text-right truncate">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60 text-xs">
            {filteredCases.length === 0 ? (
              <tr>
                <td colSpan={4} className="py-12 text-center text-slate-500 text-xs">
                  {cases.length === 0
                    ? 'No cases processed yet. Click "Upload Documents" to begin.'
                    : 'No cases match the selected filter criteria.'}
                </td>
              </tr>
            ) : (
              filteredCases.map((c) => {
                const isSelected = c.case_id === selectedCaseId;
                const poFile = (isSelected && selectedCaseDetails?.po_file) || c.po_file || (typeof c.source_files === 'object' && !Array.isArray(c.source_files) ? c.source_files?.po : undefined);
                const invFile = (isSelected && selectedCaseDetails?.invoice_file) || c.invoice_file || (typeof c.source_files === 'object' && !Array.isArray(c.source_files) ? c.source_files?.invoice : undefined);
                const rcptFile = (isSelected && selectedCaseDetails?.receipt_files?.[0]) || c.receipt_files?.[0] || (typeof c.source_files === 'object' && !Array.isArray(c.source_files) ? c.source_files?.receipt : undefined);

                return (
                  <React.Fragment key={c.case_id}>
                    <tr
                      onClick={() => onSelectCase(c.case_id)}
                      className={`cursor-pointer transition group ${
                        isSelected
                          ? 'bg-slate-800/80 border-l-4 border-sky-400 text-white font-medium'
                          : 'hover:bg-slate-800/40 text-slate-300'
                      }`}
                    >
                      {/* Case ID and Processed Date+Time */}
                      <td className="py-2 px-1.5 sm:px-2 min-w-0">
                        <div className="flex items-center space-x-1 min-w-0">
                          {isSelected ? (
                            <ChevronDown className="w-3.5 h-3.5 text-sky-400 flex-shrink-0" />
                          ) : (
                            <ChevronRight className="w-3.5 h-3.5 text-slate-500 group-hover:text-sky-400 flex-shrink-0" />
                          )}
                          <span className="font-mono font-bold text-sky-400 group-hover:text-sky-300 text-xs truncate" title={c.case_id}>
                            {c.case_id}
                          </span>
                        </div>
                        {c.created_at ? (
                          <div className="flex items-center gap-1.5 text-[11px] text-slate-300 font-mono font-medium mt-0.5 pl-4.5" title={`Processed: ${c.created_at}`}>
                            <Clock className="w-3 h-3 text-sky-400/80 flex-shrink-0" />
                            <span className="truncate">{formatProcessedDateTime(c.created_at)}</span>
                          </div>
                        ) : c.po_number ? (
                          <div className="text-[11px] text-slate-400 font-mono mt-0.5 pl-4.5 truncate" title={c.po_number || ''}>
                            {c.po_number}
                          </div>
                        ) : null}
                      </td>

                      {/* Vendor */}
                      <td className="py-2 px-1.5 sm:px-2 min-w-0">
                        <div
                          className="truncate font-medium text-slate-200 text-[11px]"
                          title={c.vendor_name || ''}
                        >
                          {c.vendor_name || '—'}
                        </div>
                        <div className="text-[9px] text-slate-500 font-mono truncate" title={c.invoice_number || ''}>
                          {c.invoice_number || ''}
                        </div>
                      </td>

                      {/* Status */}
                      <td className="py-2 px-1.5 sm:px-2 text-center min-w-0">
                        {renderStatusBadge(c.status)}
                      </td>

                      {/* Action */}
                      <td className="py-2 px-1.5 sm:px-2 text-right min-w-0">
                        {renderActionBadge(c.action, c.requires_human_review)}
                      </td>
                    </tr>

                    {/* EXPANDABLE ACCORDION: Shows Source Files when Case is Active/Expanded */}
                    {isSelected && (
                      <tr className="bg-slate-800/80 border-l-4 border-sky-400 border-b border-slate-700/60">
                        <td colSpan={4} className="p-2 sm:p-2.5">
                          <div className="bg-slate-900/80 rounded-lg p-2.5 border border-slate-700/70 shadow-sm flex flex-col items-center justify-center text-center w-full">
                            <div className="flex items-center justify-center gap-1.5 text-[10px] font-bold text-sky-300 uppercase tracking-wider mb-2">
                              <FileText className="w-3.5 h-3.5 text-sky-400" />
                              <span>Source Documents (Click to inspect)</span>
                            </div>

                            <div className="flex flex-wrap items-center justify-center gap-2 w-full">
                              {/* PO Pill */}
                              {poFile ? (
                                <button
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    onViewDoc?.(poFile, 'PURCHASE_ORDER', isSelected ? selectedCaseDetails?.po_file_path : undefined);
                                  }}
                                  title={`Inspect ${poFile}`}
                                  className="flex items-center justify-center space-x-1.5 px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700/90 border border-slate-700 hover:border-sky-500/50 text-xs text-slate-300 hover:text-white transition group cursor-pointer shadow-sm"
                                >
                                  <span className="w-1.5 h-1.5 rounded-full bg-sky-400 flex-shrink-0" />
                                  <span className="font-bold text-sky-300 text-[10px]">PO:</span>
                                  <span className="font-mono text-[10px] text-slate-200 group-hover:underline truncate max-w-[120px]">{poFile}</span>
                                  <ExternalLink className="w-2.5 h-2.5 text-slate-500 group-hover:text-sky-300 transition flex-shrink-0" />
                                </button>
                              ) : (
                                <div className="flex items-center justify-center space-x-1.5 px-2 py-1 rounded bg-slate-900/60 border border-dashed border-slate-800 text-[10px] text-slate-500">
                                  <span className="w-1.5 h-1.5 rounded-full bg-slate-600 flex-shrink-0" />
                                  <span className="font-semibold text-slate-400">PO:</span>
                                  <span className="italic text-slate-500 text-[9px]">Not uploaded</span>
                                </div>
                              )}

                              {/* Invoice Pill */}
                              {invFile ? (
                                <button
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    onViewDoc?.(invFile, 'INVOICE', isSelected ? selectedCaseDetails?.invoice_file_path : undefined);
                                  }}
                                  title={`Inspect ${invFile}`}
                                  className="flex items-center justify-center space-x-1.5 px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700/90 border border-slate-700 hover:border-indigo-500/50 text-xs text-slate-300 hover:text-white transition group cursor-pointer shadow-sm"
                                >
                                  <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 flex-shrink-0" />
                                  <span className="font-bold text-indigo-300 text-[10px]">Invoice:</span>
                                  <span className="font-mono text-[10px] text-slate-200 group-hover:underline truncate max-w-[120px]">{invFile}</span>
                                  <ExternalLink className="w-2.5 h-2.5 text-slate-500 group-hover:text-indigo-300 transition flex-shrink-0" />
                                </button>
                              ) : (
                                <div className="flex items-center justify-center space-x-1.5 px-2 py-1 rounded bg-slate-900/60 border border-dashed border-slate-800 text-[10px] text-slate-500">
                                  <span className="w-1.5 h-1.5 rounded-full bg-slate-600 flex-shrink-0" />
                                  <span className="font-semibold text-slate-400">Invoice:</span>
                                  <span className="italic text-slate-500 text-[9px]">Not uploaded</span>
                                </div>
                              )}

                              {/* Receipt Pill */}
                              {rcptFile ? (
                                <button
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    onViewDoc?.(rcptFile, 'RECEIPT', isSelected ? selectedCaseDetails?.receipt_file_path : undefined);
                                  }}
                                  title={`Inspect ${rcptFile}`}
                                  className="flex items-center justify-center space-x-1.5 px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700/90 border border-slate-700 hover:border-emerald-500/50 text-xs text-slate-300 hover:text-white transition group cursor-pointer shadow-sm"
                                >
                                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 flex-shrink-0" />
                                  <span className="font-bold text-emerald-300 text-[10px]">Receipt:</span>
                                  <span className="font-mono text-[10px] text-slate-200 group-hover:underline truncate max-w-[120px]">{rcptFile}</span>
                                  <ExternalLink className="w-2.5 h-2.5 text-slate-500 group-hover:text-emerald-300 transition flex-shrink-0" />
                                </button>
                              ) : (
                                <div className="flex items-center justify-center space-x-1.5 px-2 py-1 rounded bg-slate-900/60 border border-dashed border-slate-800 text-[10px] text-slate-500">
                                  <span className="w-1.5 h-1.5 rounded-full bg-slate-600 flex-shrink-0" />
                                  <span className="font-semibold text-slate-400">Receipt:</span>
                                  <span className="italic text-slate-500 text-[9px]">None attached</span>
                                </div>
                              )}
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};
