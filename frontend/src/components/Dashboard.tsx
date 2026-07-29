import React, { useState, useEffect } from 'react';
import { Play, RefreshCw, LogOut, CheckCircle2, AlertTriangle, Terminal, Camera, Shield, FileSpreadsheet, FolderTree } from 'lucide-react';
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

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 flex flex-col font-sans">
      {/* Top Navbar */}
      <header className="bg-slate-800 border-b border-slate-700 px-6 py-3.5 flex items-center justify-between shadow-sm">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-blue-600/10 border border-blue-500/20 flex items-center justify-center text-blue-400">
            <Camera className="w-4 h-4" />
          </div>
          <div>
            <h1 className="font-bold text-sm text-slate-100 flex items-center gap-2">
              <span>Bright Horizons Extractor</span>
              <span className="text-[10px] font-mono px-2 py-0.5 bg-slate-700 text-slate-300 rounded font-normal">
                Headless
              </span>
            </h1>
            <p className="text-[11px] text-slate-400 font-mono flex items-center gap-1">
              <Shield className="w-3 h-3 text-blue-400" />
              <span>{email}</span>
            </p>
          </div>
        </div>

        <button
          onClick={onLogout}
          className="px-3 py-1.5 bg-slate-700 hover:bg-slate-600 text-slate-200 text-xs font-semibold rounded-lg transition flex items-center gap-2"
        >
          <LogOut className="w-3.5 h-3.5" />
          <span>Sign Out</span>
        </button>
      </header>

      {/* Main Dashboard Container */}
      <main className="flex-1 max-w-7xl w-full mx-auto p-4 sm:p-6 space-y-6">
        {/* Extraction Control Banner */}
        <div className="p-6 bg-slate-800 rounded-xl border border-slate-700 space-y-5 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h2 className="text-base font-bold text-slate-100 flex items-center gap-2">
                <Play className="w-4 h-4 text-blue-400 fill-current" />
                <span>Extraction Control Panel</span>
              </h2>
              <p className="text-xs text-slate-400 mt-0.5">
                Configure headless sync options and start extraction job.
              </p>
            </div>

            <button
              onClick={handleStartExtraction}
              disabled={status.state === 'running'}
              className="px-5 py-2 bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold rounded-lg transition disabled:opacity-50 flex items-center gap-2 shadow-sm"
            >
              {status.state === 'running' ? (
                <>
                  <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                  <span>Extracting Feed...</span>
                </>
              ) : (
                <>
                  <Play className="w-3.5 h-3.5 fill-current" />
                  <span>Start Extraction</span>
                </>
              )}
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-5 pt-1">
            {/* Sync Mode Segment Control */}
            <div className="space-y-1.5">
              <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider">
                Sync Mode
              </label>
              <div className="grid grid-cols-2 p-1 bg-slate-900 border border-slate-700 rounded-lg text-xs font-medium">
                <button
                  type="button"
                  onClick={() => setSyncMode('incremental')}
                  disabled={status.state === 'running'}
                  className={`py-1.5 rounded transition ${
                    syncMode === 'incremental'
                      ? 'bg-slate-700 text-slate-100 font-semibold border border-slate-600'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  Incremental
                </button>
                <button
                  type="button"
                  onClick={() => setSyncMode('full')}
                  disabled={status.state === 'running'}
                  className={`py-1.5 rounded transition ${
                    syncMode === 'full'
                      ? 'bg-slate-700 text-slate-100 font-semibold border border-slate-600'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  Full Rescan
                </button>
              </div>
            </div>

            {/* Storage Layout Segment Control */}
            <div className="space-y-1.5">
              <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider">
                Storage Layout
              </label>
              <div className="grid grid-cols-2 p-1 bg-slate-900 border border-slate-700 rounded-lg text-xs font-medium">
                <button
                  type="button"
                  onClick={() => setLayoutMode('flat')}
                  disabled={status.state === 'running'}
                  className={`py-1.5 rounded transition flex items-center justify-center gap-1.5 ${
                    layoutMode === 'flat'
                      ? 'bg-slate-700 text-slate-100 font-semibold border border-slate-600'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <FileSpreadsheet className="w-3.5 h-3.5" />
                  <span>Flat</span>
                </button>
                <button
                  type="button"
                  onClick={() => setLayoutMode('nested')}
                  disabled={status.state === 'running'}
                  className={`py-1.5 rounded transition flex items-center justify-center gap-1.5 ${
                    layoutMode === 'nested'
                      ? 'bg-slate-700 text-slate-100 font-semibold border border-slate-600'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <FolderTree className="w-3.5 h-3.5" />
                  <span>Nested</span>
                </button>
              </div>
            </div>

            {/* Target Child Selector */}
            <div className="space-y-1.5">
              <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider">
                Target Child
              </label>
              <select
                value={targetChild}
                onChange={(e) => setTargetChild(e.target.value)}
                disabled={status.state === 'running'}
                className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200 focus:border-blue-500 outline-none"
              >
                <option value="all">All Enrolled Children</option>
              </select>
            </div>
          </div>

          {/* Status Alert & Progress Console */}
          {status.state !== 'idle' && (
            <div className="p-4 bg-slate-900 border border-slate-700 rounded-lg space-y-3">
              <div className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-2">
                  {status.state === 'running' && <RefreshCw className="w-4 h-4 text-blue-400 animate-spin" />}
                  {status.state === 'completed' && <CheckCircle2 className="w-4 h-4 text-emerald-400" />}
                  {status.state === 'failed' && <AlertTriangle className="w-4 h-4 text-rose-400" />}
                  <span className="font-semibold text-slate-200 capitalize">{status.state}</span>
                  <span className="text-slate-400 font-mono">• {status.current_step}</span>
                </div>
                <span className="text-xs font-mono text-slate-300 bg-slate-800 px-2 py-0.5 rounded border border-slate-700">
                  {status.files_downloaded || 0} files downloaded
                </span>
              </div>

              {/* Console Log Drawer */}
              <div className="pt-1">
                <button
                  onClick={() => setShowLogs(!showLogs)}
                  className="text-[11px] text-slate-400 hover:text-slate-200 flex items-center gap-1.5 mb-2 font-mono"
                >
                  <Terminal className="w-3.5 h-3.5 text-blue-400" />
                  <span>{showLogs ? 'Hide Console Logs' : 'Show Console Logs'}</span>
                </button>

                {showLogs && status.logs && (
                  <div className="bg-slate-950 rounded-lg p-3 max-h-40 overflow-y-auto font-mono text-[11px] text-slate-300 space-y-1 border border-slate-800">
                    {status.logs.map((log: string, idx: number) => (
                      <div key={idx} className="leading-relaxed flex items-start gap-2">
                        <span className="text-slate-600 select-none">&gt;</span>
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
    </div>
  );
};
