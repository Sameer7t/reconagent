import React from 'react';
import { ShieldCheck, UploadCloud, RefreshCw, LogOut, User, Users } from 'lucide-react';
import { useAuth } from '../AuthContext';

interface NavbarProps {
  onOpenUpload: () => void;
  onOpenUserMgmt?: () => void;
  onRefresh: () => void;
  isRefreshing: boolean;
  onlineStatus: boolean;
}

export const Navbar: React.FC<NavbarProps> = ({
  onOpenUpload,
  onOpenUserMgmt,
  onRefresh,
  isRefreshing,
  onlineStatus,
}) => {
  const { user, logout } = useAuth();
  const canUpload = user?.role === 'Admin' || user?.role === 'Reviewer';

  return (
    <header className="bg-slate-900/90 backdrop-blur border-b border-slate-800 sticky top-0 z-30 px-3 sm:px-6 py-2.5 sm:py-3.5">
      <div className="max-w-7xl mx-auto flex items-center justify-between gap-2">
        {/* Left: Branding */}
        <div className="flex items-center space-x-2.5 sm:space-x-3 min-w-0">
          <div className="h-8 w-8 sm:h-9 sm:w-9 rounded-lg bg-indigo-500/20 border border-indigo-400/30 flex items-center justify-center text-indigo-400 shadow-sm shadow-indigo-500/10 flex-shrink-0">
            <ShieldCheck className="w-4 h-4 sm:w-5 sm:h-5" />
          </div>
          <div className="min-w-0">
            <div className="flex items-center space-x-1.5 sm:space-x-2">
              <span className="font-extrabold text-base sm:text-lg text-white uppercase tracking-wider truncate font-['Open_Sauce_Sans','Open_Sans',sans-serif]">
                RECONAGENT
              </span>
            </div>
            <p className="hidden md:block text-[11px] text-slate-400 uppercase tracking-wider truncate font-['Open_Sauce_Sans','Open_Sans',sans-serif] font-medium">
              AUTONOMOUS INVOICE RECONCILIATION & INVESTIGATION SYSTEM
            </p>
          </div>
        </div>

        {/* Right: Actions & Status */}
        <div className="flex items-center space-x-2 sm:space-x-4 flex-shrink-0">
          {/* User Profile */}
          {user && (
            <div className="hidden lg:flex items-center space-x-2 px-3 py-1.5 rounded-full bg-slate-800/80 border border-slate-700">
              <div className="bg-indigo-500/20 p-1 rounded-full text-indigo-400">
                <User className="w-3.5 h-3.5" />
              </div>
              <div className="flex flex-col">
                <span className="text-xs font-semibold text-slate-200 leading-none">{user.email}</span>
                <span className="text-[10px] text-slate-400 leading-none mt-0.5">{user.role}</span>
              </div>
            </div>
          )}

          {/* Status badge */}
          <div className="hidden sm:flex items-center space-x-2 px-2.5 sm:px-3 py-1 rounded-full bg-slate-800/80 border border-slate-700/60 text-xs">
            <span
              className={`w-2 h-2 rounded-full ${
                onlineStatus ? 'bg-emerald-400 animate-pulse' : 'bg-rose-400'
              }`}
            />
            <span className="text-slate-300 font-medium">
              {onlineStatus ? 'API Online' : 'Connecting...'}
            </span>
          </div>

          {/* Refresh button */}
          <button
            onClick={onRefresh}
            disabled={isRefreshing}
            title="Refresh Cases & Metrics"
            className="p-1.5 sm:p-2 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 hover:text-white transition flex items-center justify-center disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 sm:w-4 sm:h-4 ${isRefreshing ? 'animate-spin text-indigo-400' : ''}`} />
          </button>

          {/* Manage Users (Admin only) */}
          {user?.role === 'Admin' && onOpenUserMgmt && (
            <button
              onClick={onOpenUserMgmt}
              className="flex items-center space-x-1.5 px-3 py-1.5 sm:py-2 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-indigo-300 hover:text-white font-medium text-xs transition"
              title="Manage Users & Permissions"
            >
              <Users className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-indigo-400" />
              <span className="hidden sm:inline">Manage Users</span>
            </button>
          )}

          {/* Upload & Reconcile button */}
          {canUpload && (
            <button
              onClick={onOpenUpload}
              className="flex items-center space-x-1.5 sm:space-x-2 px-3 sm:px-4 py-1.5 sm:py-2 rounded-lg bg-gradient-to-r from-indigo-500 to-violet-600 hover:from-indigo-400 hover:to-violet-500 text-white font-medium text-xs shadow-md shadow-indigo-500/20 hover:shadow-indigo-500/30 transition transform active:scale-95"
            >
              <UploadCloud className="w-3.5 h-3.5 sm:w-4 sm:h-4" />
              <span className="hidden xs:inline sm:inline">Upload & Reconcile</span>
              <span className="inline xs:hidden sm:hidden">Upload</span>
            </button>
          )}

          {/* Logout button */}
          <button
            onClick={logout}
            title="Logout"
            className="p-1.5 sm:p-2 rounded-lg bg-slate-800 hover:bg-rose-500/20 border border-slate-700 hover:border-rose-500/50 text-slate-400 hover:text-rose-400 transition flex items-center justify-center"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </div>
    </header>
  );
};
