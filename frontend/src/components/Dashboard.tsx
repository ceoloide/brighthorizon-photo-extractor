import React, { useState, useEffect } from 'react';
import { Play, RefreshCw, LogOut, CheckCircle2, AlertTriangle, Terminal, Camera, Shield, FileSpreadsheet, FolderTree, Trash2, AlertCircle } from 'lucide-react';
import { Gallery } from './Gallery';
import { ArchiveManager } from './ArchiveManager';

interface DashboardProps {
  token: string;
  email: string;
  onLogout: () => void;
}

export const Dashboard: React.FC<DashboardProps> = ({ token, email, onLogout }) => {
  const [syncMode, setSyncMode] = useState<'incremental' | 'full'>('incremental');
  const [layoutMode, setLayoutMode] = useState<'flat' | 'nested'>('flat');
  const [targetChild, setTargetChild] = useState<string>('all');
  const [status, setStatus] = useState<any>({ state: 'idle', logs: [] });
  const [refreshTrigger, setRefreshTrigger] = useState<number>(0);
  const [showLogs, setShowLogs] = useState<boolean>(true);
  const [showDeleteModal, setShowDeleteModal] = useState<boolean>(false);
  const [deleting, setDeleting] = useState<boolean>(false);

  const fetchStatus = async () => {
    try {
      const res = await fetch('/api/extraction/status', {
        headers: { Authorization: `Bearer ${token}` }
      });
      const data = await res.json();
      if (res.ok) {
        setStatus(data);
        if (data.state === 'completed') {
          setRefreshTrigger((prev) => prev + 1);
        }
      }
    } catch (err) {
      console.error('Error fetching extraction status:', err);
    }
  };

  useEffect(() => {
    fetchStatus();
  }, [token]);

  useEffect(() => {
    let interval: any;
    if (status.state === 'running') {
      interval = setInterval(fetchStatus, 2000);
    }
    return () => clearInterval(interval);
  }, [status.state]);

  const handleStartExtraction = async () => {
    try {
      const res = await fetch('/api/extraction/start', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({
          sync_mode: syncMode,
          layout_mode: layoutMode,
          child: targetChild
        })
      });
      const data = await res.json();
      if (res.ok) {
        setStatus(data.job || data);
      }
    } catch (err) {
      console.error('Failed to start extraction:', err);
    }
  };

  const handleDeleteAccount = async () => {
    setDeleting(true);
    try {
      const res = await fetch('/api/auth/delete-account', {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        onLogout();
      }
    } catch (err) {
      console.error('Account deletion failed:', err);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-800 flex flex-col font-sans">
      {/* Top Navbar */}
      <header className="bg-white border-b border-slate-200 px-4 sm:px-6 py-3 flex flex-wrap items-center justify-between gap-3 shadow-sm sticky top-0 z-40">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 sm:w-9 sm:h-9 rounded-xl bg-indigo-50 border border-indigo-100 flex items-center justify-center text-indigo-600 shrink-0">
            <Camera className="w-4 h-4 sm:w-5 sm:h-5" />
          </div>
          <div className="min-w-0">
            <h1 className="font-bold text-xs sm:text-sm text-slate-900 flex items-center gap-1.5 truncate">
              <span className="truncate">Bright Horizons</span>
              <span className="text-[10px] font-medium px-2 py-0.5 bg-indigo-50 text-indigo-700 border border-indigo-100 rounded-full shrink-0">
                Sync
              </span>
            </h1>
            <p className="text-[10px] sm:text-[11px] text-slate-500 flex items-center gap-1 font-mono truncate">
              <Shield className="w-3 h-3 text-indigo-500 shrink-0" />
              <span className="truncate max-w-[160px] sm:max-w-none">{email}</span>
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 ml-auto">
          <button
            onClick={() => setShowDeleteModal(true)}
            className="px-2.5 sm:px-3 py-1.5 bg-rose-50 hover:bg-rose-100 text-rose-700 border border-rose-200 text-xs font-medium rounded-xl transition flex items-center gap-1"
            title="Delete Account & All Data"
          >
            <Trash2 className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Delete Account</span>
          </button>
          <button
            onClick={onLogout}
            className="px-2.5 sm:px-3.5 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-medium rounded-xl transition border border-slate-200 flex items-center gap-1.5"
          >
            <LogOut className="w-3.5 h-3.5" />
            <span>Sign Out</span>
          </button>
        </div>
      </header>

      {/* Main Dashboard Container */}
      <main className="flex-1 max-w-7xl w-full mx-auto p-3 sm:p-6 space-y-4 sm:space-y-6">
        {/* Extraction Control Banner */}
        <div className="p-4 sm:p-6 bg-white rounded-2xl border border-slate-200 space-y-4 sm:space-y-5 shadow-sm">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div>
              <h2 className="text-sm sm:text-base font-bold text-slate-900 flex items-center gap-2">
                <Play className="w-4 h-4 text-indigo-600 fill-current" />
                <span>Extraction Control Panel</span>
              </h2>
              <p className="text-xs text-slate-500 mt-0.5">
                Configure sync options and download photos and videos.
              </p>
            </div>

            <button
              onClick={handleStartExtraction}
              disabled={status.state === 'running'}
              className="w-full sm:w-auto px-5 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-semibold rounded-xl transition disabled:opacity-50 flex items-center justify-center gap-2 shadow-sm active:scale-[0.99]"
            >
              {status.state === 'running' ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  <span>Extracting Photos...</span>
                </>
              ) : (
                <>
                  <Play className="w-4 h-4 fill-current" />
                  <span>Start Extraction</span>
                </>
              )}
            </button>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4 pt-1">
            {/* Sync Mode Segment Control */}
            <div className="space-y-1.5">
              <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider">
                Sync Mode
              </label>
              <div className="grid grid-cols-2 p-1 bg-slate-100 border border-slate-200 rounded-xl text-xs font-medium">
                <button
                  type="button"
                  onClick={() => setSyncMode('incremental')}
                  disabled={status.state === 'running'}
                  className={`py-2 sm:py-1.5 rounded-lg transition ${
                    syncMode === 'incremental'
                      ? 'bg-white text-indigo-700 font-semibold border border-slate-200 shadow-sm'
                      : 'text-slate-500 hover:text-slate-800'
                  }`}
                >
                  Incremental
                </button>
                <button
                  type="button"
                  onClick={() => setSyncMode('full')}
                  disabled={status.state === 'running'}
                  className={`py-2 sm:py-1.5 rounded-lg transition ${
                    syncMode === 'full'
                      ? 'bg-white text-indigo-700 font-semibold border border-slate-200 shadow-sm'
                      : 'text-slate-500 hover:text-slate-800'
                  }`}
                >
                  Full Rescan
                </button>
              </div>
            </div>

            {/* Storage Layout Segment Control */}
            <div className="space-y-1.5">
              <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider">
                Storage Layout
              </label>
              <div className="grid grid-cols-2 p-1 bg-slate-100 border border-slate-200 rounded-xl text-xs font-medium">
                <button
                  type="button"
                  onClick={() => setLayoutMode('flat')}
                  disabled={status.state === 'running'}
                  className={`py-2 sm:py-1.5 rounded-lg transition flex items-center justify-center gap-1.5 ${
                    layoutMode === 'flat'
                      ? 'bg-white text-indigo-700 font-semibold border border-slate-200 shadow-sm'
                      : 'text-slate-500 hover:text-slate-800'
                  }`}
                >
                  <FileSpreadsheet className="w-3.5 h-3.5" />
                  <span>Flat</span>
                </button>
                <button
                  type="button"
                  onClick={() => setLayoutMode('nested')}
                  disabled={status.state === 'running'}
                  className={`py-2 sm:py-1.5 rounded-lg transition flex items-center justify-center gap-1.5 ${
                    layoutMode === 'nested'
                      ? 'bg-white text-indigo-700 font-semibold border border-slate-200 shadow-sm'
                      : 'text-slate-500 hover:text-slate-800'
                  }`}
                >
                  <FolderTree className="w-3.5 h-3.5" />
                  <span>Nested</span>
                </button>
              </div>
            </div>

            {/* Target Child Selector */}
            <div className="space-y-1.5 sm:col-span-2 md:col-span-1">
              <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider">
                Target Child
              </label>
              <select
                value={targetChild}
                onChange={(e) => setTargetChild(e.target.value)}
                disabled={status.state === 'running'}
                className="w-full bg-white border border-slate-300 rounded-xl px-3.5 py-2.5 sm:py-2 text-xs text-slate-800 focus:border-indigo-600 outline-none transition"
              >
                <option value="all">All Enrolled Children</option>
              </select>
            </div>
          </div>

          {/* Status Alert & Progress Console */}
          {status.state !== 'idle' && (
            <div className="p-3.5 sm:p-4 bg-slate-50 border border-slate-200 rounded-xl space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                <div className="flex items-center gap-2">
                  {status.state === 'running' && <RefreshCw className="w-4 h-4 text-indigo-600 animate-spin shrink-0" />}
                  {status.state === 'completed' && <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />}
                  {status.state === 'failed' && <AlertTriangle className="w-4 h-4 text-rose-600 shrink-0" />}
                  <span className="font-semibold text-slate-900 capitalize">{status.state}</span>
                  <span className="text-slate-500 font-mono text-[11px] truncate max-w-[160px] sm:max-w-none">
                    • {status.current_step}
                  </span>
                </div>
                <span className="text-[11px] font-mono text-indigo-700 bg-indigo-50 border border-indigo-100 px-2.5 py-0.5 rounded-full font-semibold">
                  {status.files_downloaded || 0} downloaded
                </span>
              </div>

              {/* Console Log Drawer */}
              <div className="pt-1">
                <button
                  onClick={() => setShowLogs(!showLogs)}
                  className="text-[11px] text-slate-500 hover:text-slate-800 flex items-center gap-1.5 mb-2 font-mono"
                >
                  <Terminal className="w-3.5 h-3.5 text-indigo-600 shrink-0" />
                  <span>{showLogs ? 'Hide Console Logs' : 'Show Console Logs'}</span>
                </button>

                {showLogs && status.logs && (
                  <div className="bg-slate-900 rounded-xl p-3 sm:p-3.5 max-h-40 overflow-y-auto font-mono text-[11px] text-slate-200 space-y-1">
                    {status.logs.map((log: string, idx: number) => (
                      <div key={idx} className="leading-relaxed flex items-start gap-2 break-all">
                        <span className="text-slate-500 select-none">&gt;</span>
                        <span>{log}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Media Gallery Section */}
        <Gallery token={token} refreshTrigger={refreshTrigger} />

        {/* Archive Center Section */}
        <ArchiveManager token={token} />
      </main>

      {/* Account Deletion Confirmation Modal */}
      {showDeleteModal && (
        <div className="fixed inset-0 z-50 bg-slate-900/60 flex items-center justify-center p-4">
          <div className="max-w-md w-full bg-white border border-slate-200 rounded-2xl p-5 sm:p-6 shadow-xl space-y-4">
            <div className="flex items-center gap-3 text-rose-600">
              <div className="p-2 bg-rose-50 rounded-xl border border-rose-100 shrink-0">
                <AlertCircle className="w-6 h-6" />
              </div>
              <h3 className="font-bold text-slate-900 text-base">Permanently Delete Account?</h3>
            </div>

            <p className="text-xs text-slate-600 leading-relaxed">
              This action will permanently delete your account (<strong className="text-slate-800">{email}</strong>), all downloaded photo/video files, encrypted manifests, saved credentials, and session data.
            </p>
            <p className="text-[11px] text-rose-600 font-semibold">
              This process is immediate and cannot be undone.
            </p>

            <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setShowDeleteModal(false)}
                disabled={deleting}
                className="w-full sm:w-auto px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold rounded-xl transition border border-slate-200"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleDeleteAccount}
                disabled={deleting}
                className="w-full sm:w-auto px-4 py-2 bg-rose-600 hover:bg-rose-700 text-white text-xs font-semibold rounded-xl transition shadow-sm flex items-center justify-center gap-2"
              >
                {deleting ? (
                  <>
                    <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                    <span>Purging All Data...</span>
                  </>
                ) : (
                  <>
                    <Trash2 className="w-3.5 h-3.5" />
                    <span>Confirm Delete</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
