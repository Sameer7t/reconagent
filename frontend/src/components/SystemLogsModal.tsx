import React, { useState, useEffect, useCallback } from 'react';
import {
  X,
  RefreshCw,
  Terminal,
  ShieldAlert,
  Search,
  ChevronDown,
  ChevronRight,
  Filter,
  Clock,
  HardDrive,
  Copy,
  Check,
} from 'lucide-react';
import { api } from '../services/api';
import { useAuth } from '../AuthContext';

interface LogRecord {
  timestamp: string;
  level: string;
  event: string;
  case_id?: string | null;
  request_id?: string | null;
  stage?: string | null;
  duration_ms?: number | null;
  status?: string | null;
  message?: string | null;
  [key: string]: any;
}

interface SystemLogsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

const STAGES = [
  'ALL',
  'classification',
  'extraction',
  'validation',
  'reconciliation',
  'agent investigation',
  'database persistence',
  'review queue',
];

const LEVELS = ['ALL', 'INFO', 'WARNING', 'ERROR'];

export const SystemLogsModal: React.FC<SystemLogsModalProps> = ({ isOpen, onClose }) => {
  const { user } = useAuth();
  const isAdmin = user?.role === 'Admin';

  const [logs, setLogs] = useState<LogRecord[]>([]);
  const [totalRecords, setTotalRecords] = useState<number>(0);
  const [logFilePath, setLogFilePath] = useState<string>('logs/reconagent.jsonl');
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [selectedStage, setSelectedStage] = useState<string>('ALL');
  const [selectedLevel, setSelectedLevel] = useState<string>('ALL');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [limit, setLimit] = useState<number>(100);
  const [expandedIndices, setExpandedIndices] = useState<Record<number, boolean>>({});
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const fetchLogs = useCallback(async () => {
    if (!isAdmin) return;
    try {
      setLoading(true);
      setError(null);
      const params: any = { limit };
      if (selectedStage !== 'ALL') params.stage = selectedStage;
      if (selectedLevel !== 'ALL') params.level = selectedLevel;

      const data = await api.getLogs(params);
      setLogs(data.logs || []);
      setTotalRecords(data.total_records || 0);
      if (data.log_file) setLogFilePath(data.log_file);
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to retrieve structured system logs');
    } finally {
      setLoading(false);
    }
  }, [isAdmin, limit, selectedStage, selectedLevel]);

  useEffect(() => {
    if (isOpen && isAdmin) {
      fetchLogs();
    }
  }, [isOpen, isAdmin, fetchLogs]);

  if (!isOpen) return null;

  // Non-admin safeguard
  if (!isAdmin) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
        <div className="bg-slate-900 border border-rose-500/40 rounded-2xl max-w-md w-full p-6 text-center shadow-2xl">
          <ShieldAlert className="w-12 h-12 text-rose-400 mx-auto mb-3" />
          <h3 className="text-lg font-bold text-white mb-2">Access Restricted</h3>
          <p className="text-sm text-slate-300 mb-6">
            System Observability and Audit Logs are strictly restricted to <strong>Admin</strong> users.
          </p>
          <button
            onClick={onClose}
            className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-white rounded-lg text-sm font-medium transition"
          >
            Close
          </button>
        </div>
      </div>
    );
  }

  // Filter logs by search query (case_id, request_id, event, message)
  const filteredLogs = logs.filter((log) => {
    if (!searchQuery.trim()) return true;
    const q = searchQuery.toLowerCase();
    return (
      log.event?.toLowerCase().includes(q) ||
      log.case_id?.toLowerCase().includes(q) ||
      log.request_id?.toLowerCase().includes(q) ||
      log.stage?.toLowerCase().includes(q) ||
      log.message?.toLowerCase().includes(q) ||
      log.status?.toLowerCase().includes(q)
    );
  });

  const toggleExpand = (index: number) => {
    setExpandedIndices((prev) => ({
      ...prev,
      [index]: !prev[index],
    }));
  };

  const copyToClipboard = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const getLevelBadgeClass = (level: string) => {
    switch (level?.toUpperCase()) {
      case 'ERROR':
        return 'bg-rose-500/20 text-rose-300 border-rose-500/30';
      case 'WARNING':
        return 'bg-amber-500/20 text-amber-300 border-amber-500/30';
      case 'INFO':
      default:
        return 'bg-sky-500/20 text-sky-300 border-sky-500/30';
    }
  };

  const getStatusBadgeClass = (status: string | null | undefined) => {
    if (!status) return 'bg-slate-800 text-slate-400 border-slate-700';
    const s = status.toUpperCase();
    if (s === 'SUCCESS' || s === 'COMPLETED' || s === '200') {
      return 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30';
    }
    if (s === 'ERROR' || s === 'FAILED' || s.startsWith('4') || s.startsWith('5')) {
      return 'bg-rose-500/20 text-rose-300 border-rose-500/30';
    }
    if (s === 'STARTED' || s === 'IN_PROGRESS') {
      return 'bg-indigo-500/20 text-indigo-300 border-indigo-500/30';
    }
    return 'bg-slate-800 text-slate-300 border-slate-700';
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md p-2 sm:p-4">
      <div className="bg-slate-900 border border-slate-700/80 rounded-2xl max-w-6xl w-full h-[90vh] flex flex-col shadow-2xl overflow-hidden font-sans">
        {/* Modal Header */}
        <div className="px-5 py-3.5 border-b border-slate-800 bg-slate-950/80 flex items-center justify-between flex-shrink-0">
          <div className="flex items-center space-x-3">
            <div className="p-2 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-400">
              <Terminal className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center space-x-2">
                <h2 className="text-base sm:text-lg font-bold text-white tracking-wide">
                  System Observability & Audit Logs
                </h2>
                <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 uppercase tracking-wider">
                  Admin Only
                </span>
              </div>
              <p className="text-xs text-slate-400 flex items-center gap-1.5 mt-0.5">
                <HardDrive className="w-3.5 h-3.5 text-slate-500" />
                <span className="font-mono text-[11px] text-slate-300 truncate max-w-sm sm:max-w-md">
                  {logFilePath}
                </span>
                <span className="text-slate-600">•</span>
                <span>{totalRecords} records</span>
              </p>
            </div>
          </div>

          <div className="flex items-center space-x-2">
            <button
              onClick={fetchLogs}
              disabled={loading}
              className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 hover:text-white text-xs font-medium transition disabled:opacity-50"
              title="Refresh Logs"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin text-emerald-400' : ''}`} />
              <span className="hidden sm:inline">Refresh</span>
            </button>
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-white transition"
              title="Close"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Filters and Search Bar */}
        <div className="px-5 py-3 border-b border-slate-800/80 bg-slate-900/60 flex flex-wrap items-center justify-between gap-2.5 flex-shrink-0">
          <div className="flex flex-wrap items-center gap-2">
            {/* Stage Selector */}
            <div className="flex items-center space-x-1.5 bg-slate-800/90 border border-slate-700/80 rounded-lg px-2.5 py-1 text-xs">
              <Filter className="w-3.5 h-3.5 text-slate-400" />
              <span className="text-slate-400 font-medium">Stage:</span>
              <select
                value={selectedStage}
                onChange={(e) => setSelectedStage(e.target.value)}
                className="bg-transparent text-slate-200 font-medium focus:outline-none cursor-pointer text-xs"
              >
                {STAGES.map((s) => (
                  <option key={s} value={s} className="bg-slate-900 text-slate-200">
                    {s === 'ALL' ? 'All Stages' : s}
                  </option>
                ))}
              </select>
            </div>

            {/* Level Selector */}
            <div className="flex items-center space-x-1.5 bg-slate-800/90 border border-slate-700/80 rounded-lg px-2.5 py-1 text-xs">
              <span className="text-slate-400 font-medium">Level:</span>
              <select
                value={selectedLevel}
                onChange={(e) => setSelectedLevel(e.target.value)}
                className="bg-transparent text-slate-200 font-medium focus:outline-none cursor-pointer text-xs"
              >
                {LEVELS.map((lvl) => (
                  <option key={lvl} value={lvl} className="bg-slate-900 text-slate-200">
                    {lvl === 'ALL' ? 'All Levels' : lvl}
                  </option>
                ))}
              </select>
            </div>

            {/* Limit Selector */}
            <div className="flex items-center space-x-1.5 bg-slate-800/90 border border-slate-700/80 rounded-lg px-2.5 py-1 text-xs">
              <span className="text-slate-400 font-medium">Limit:</span>
              <select
                value={limit}
                onChange={(e) => setLimit(Number(e.target.value))}
                className="bg-transparent text-slate-200 font-medium focus:outline-none cursor-pointer text-xs"
              >
                <option value={50} className="bg-slate-900 text-slate-200">50</option>
                <option value={100} className="bg-slate-900 text-slate-200">100</option>
                <option value={250} className="bg-slate-900 text-slate-200">250</option>
                <option value={500} className="bg-slate-900 text-slate-200">500</option>
              </select>
            </div>
          </div>

          {/* Search Box */}
          <div className="relative flex-1 sm:max-w-xs min-w-[200px]">
            <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              type="text"
              placeholder="Search case, request ID, event..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-3 py-1.5 bg-slate-800/90 border border-slate-700/80 rounded-lg text-xs text-slate-200 placeholder-slate-400 focus:outline-none focus:border-indigo-500 transition"
            />
          </div>
        </div>

        {/* Logs Table / Stream */}
        <div className="flex-1 overflow-y-auto p-4 space-y-2 font-mono text-xs">
          {error && (
            <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-sm flex items-center gap-2">
              <ShieldAlert className="w-5 h-5 flex-shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {loading && logs.length === 0 && (
            <div className="h-64 flex flex-col items-center justify-center text-slate-400 space-y-3">
              <RefreshCw className="w-7 h-7 animate-spin text-emerald-400" />
              <p className="text-sm">Streaming structured logs...</p>
            </div>
          )}

          {!loading && filteredLogs.length === 0 && (
            <div className="h-64 flex flex-col items-center justify-center text-slate-500 space-y-2">
              <Terminal className="w-10 h-10 text-slate-600" />
              <p className="text-sm font-medium">No matching logs found.</p>
              <p className="text-xs text-slate-600">Try changing the stage, level, or search query.</p>
            </div>
          )}

          {filteredLogs.map((log, idx) => {
            const isExpanded = !!expandedIndices[idx];
            const extraData = Object.keys(log).filter(
              (k) =>
                ![
                  'timestamp',
                  'level',
                  'event',
                  'case_id',
                  'request_id',
                  'stage',
                  'duration_ms',
                  'status',
                  'message',
                ].includes(k)
            );

            return (
              <div
                key={idx}
                className="bg-slate-950/70 border border-slate-800/80 rounded-xl p-3 hover:border-slate-700 transition"
              >
                {/* Log Record Summary Line */}
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2 min-w-0">
                    <button
                      onClick={() => toggleExpand(idx)}
                      className="p-0.5 hover:bg-slate-800 rounded text-slate-400 hover:text-white transition"
                    >
                      {isExpanded ? (
                        <ChevronDown className="w-3.5 h-3.5" />
                      ) : (
                        <ChevronRight className="w-3.5 h-3.5" />
                      )}
                    </button>

                    {/* Level Pill */}
                    <span
                      className={`px-1.5 py-0.5 rounded text-[10px] font-bold border uppercase ${getLevelBadgeClass(
                        log.level
                      )}`}
                    >
                      {log.level}
                    </span>

                    {/* Stage Pill */}
                    {log.stage && (
                      <span className="px-2 py-0.5 rounded bg-violet-500/10 text-violet-300 border border-violet-500/20 text-[10px] font-semibold">
                        {log.stage}
                      </span>
                    )}

                    {/* Event Name */}
                    <span className="text-slate-100 font-semibold text-xs tracking-wide">
                      {log.event}
                    </span>

                    {/* Status Badge */}
                    {log.status && (
                      <span
                        className={`px-1.5 py-0.2 rounded text-[10px] font-medium border ${getStatusBadgeClass(
                          log.status
                        )}`}
                      >
                        {log.status}
                      </span>
                    )}

                    {/* Duration Badge */}
                    {log.duration_ms !== null && log.duration_ms !== undefined && (
                      <span className="px-1.5 py-0.2 rounded bg-emerald-500/10 text-emerald-300 border border-emerald-500/20 text-[10px]">
                        {log.duration_ms.toFixed(1)}ms
                      </span>
                    )}
                  </div>

                  {/* Right side: Timestamp & IDs */}
                  <div className="flex items-center gap-2 text-[11px] text-slate-400">
                    {log.case_id && (
                      <div
                        onClick={() => copyToClipboard(log.case_id!, `case-${idx}`)}
                        className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-slate-800/80 hover:bg-slate-700/80 text-indigo-300 cursor-pointer border border-slate-700 transition"
                        title="Click to copy Case ID"
                      >
                        <span>{log.case_id}</span>
                        {copiedId === `case-${idx}` ? (
                          <Check className="w-3 h-3 text-emerald-400" />
                        ) : (
                          <Copy className="w-3 h-3 text-slate-500" />
                        )}
                      </div>
                    )}

                    {log.request_id && (
                      <div
                        onClick={() => copyToClipboard(log.request_id!, `req-${idx}`)}
                        className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-slate-800/80 hover:bg-slate-700/80 text-amber-300 cursor-pointer border border-slate-700 transition"
                        title="Click to copy Request ID"
                      >
                        <span>{log.request_id}</span>
                        {copiedId === `req-${idx}` ? (
                          <Check className="w-3 h-3 text-emerald-400" />
                        ) : (
                          <Copy className="w-3 h-3 text-slate-500" />
                        )}
                      </div>
                    )}

                    <span className="text-slate-500 flex items-center gap-1">
                      <Clock className="w-3 h-3" />
                      {new Date(log.timestamp).toLocaleTimeString()}
                    </span>
                  </div>
                </div>

                {/* Message (if any) */}
                {log.message && (
                  <p className="mt-1 text-slate-300 font-sans text-xs pl-6">{log.message}</p>
                )}

                {/* Expanded JSON Details */}
                {isExpanded && (
                  <div className="mt-2.5 pt-2 border-t border-slate-800/80 pl-6">
                    <pre className="p-2.5 rounded-lg bg-slate-950 border border-slate-800 text-[11px] text-slate-300 overflow-x-auto leading-relaxed">
                      {JSON.stringify(log, null, 2)}
                    </pre>
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Modal Footer */}
        <div className="px-5 py-2.5 border-t border-slate-800 bg-slate-950/80 flex items-center justify-between text-xs text-slate-400 flex-shrink-0">
          <span>
            Displaying {filteredLogs.length} of {logs.length} fetched logs ({totalRecords} total on server)
          </span>
          <span className="text-[11px] text-slate-500">
            Protected with role-based access control (Admin Only)
          </span>
        </div>
      </div>
    </div>
  );
};
