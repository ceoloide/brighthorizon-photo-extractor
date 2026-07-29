import React, { useState, useEffect } from 'react';
import { Play, RefreshCw, LogOut, CheckCircle, AlertTriangle, Terminal, Layers, RefreshCcw } from 'lucide-react';
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
    <div className="min-h-screen bg-slate-900 text-slate-100 flex flex-col">
      {/* Top Navbar */}
      <header className="bg-slate-800 border-b border-slate-700 px-6 py-4 flex items-center justify-between shadow-lg">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-xl bg-sky-500/20 border border-sky-400 flex items-center justify-center font-bold text-sky-400">
            BH
          </div>
          <div>
            <h1 className="font-bold text-base text-slate-100">Bright Horizons Photo Extractor</h1>
            <p className="text-xs text-slate-400 font-mono">{email}</p>
          </div>
        </div>

        <button
          onClick={onLogout}
          className="px-3.5 py-1.5 bg-slate-700 hover:bg-slate-600 text-slate-200 text-xs font-semibold rounded-xl transition flex items-center gap-2"
        >
          <LogOut className="w-4 h-4" />
          <span>Sign Out</span>
        </button>
      </header>

      {/* Main Dashboard Container */}
      <main className="flex-1 max-w-7xl w-full mx-auto p-6 space-y-8">
        {/* Extraction Control Banner */}
        <div className="p-6 bg-slate-800 rounded-2xl border border-slate-700 space-y-5 shadow-xl">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h2 className="text-lg font-bold text-slate-100 flex items-center gap-2">
                <Play className="w-5 h-5 text-sky-400" />
                <span>Extraction Control Panel</span>
              </h2>
              <p className="text-xs text-slate-400 mt-0.5">
                Configure headless sync mode and parameters for Bright Horizons parent portal.
              </p>
            </div>

            <button
              onClick={handleStartExtraction}
              disabled={status.state === 'running'}
              className="px-5 py-2.5 bg-sky-600 hover:bg-sky-500 text-white font-semibold rounded-xl transition disabled:opacity-50 flex items-center gap-2 shadow-lg shadow-sky-600/20"
            >
              {status.state === 'running' ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  <span>Extracting...</span>
                </>
              ) : (
                <>
                  <Play className="w-4 h-4 fill-current" />
                  <span>Start Extraction</span>
                </>
              )}
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-2">
            <div>
              <label className="block text-xs font-semibold text-slate-400 uppercase mb-1.5">
                Sync Mode
              </label>
              <select
                value={syncMode}
                onChange={(e: any) => setSyncMode(e.target.value)}
                disabled={status.state === 'running'}
                className="w-full bg-slate-900 border border-slate-700 rounded-xl px-3 py-2 text-sm text-slate-200 focus:ring-2 focus:ring-sky-500 outline-none"
              >
                <option value="incremental">Incremental (Stop on existing)</option>
                <option value="full">Full Verification (Check all dates)</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-400 uppercase mb-1.5">
                Storage Layout
              </label>
              <select
                value={layoutMode}
                onChange={(e: any) => setLayoutMode(e.target.value)}
                disabled={status.state === 'running'}
                className="w-full bg-slate-900 border border-slate-700 rounded-xl px-3 py-2 text-sm text-slate-200 focus:ring-2 focus:ring-sky-500 outline-none"
              >
                <option value="flat">Flat (ChildName/filename)</option>
                <option value="nested">Nested (ChildName/YYYY/MM/filename)</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-400 uppercase mb-1.5">
                Target Child
              </label>
              <select
                value={targetChild}
                onChange={(e) => setTargetChild(e.target.value)}
                disabled={status.state === 'running'}
                className="w-full bg-slate-900 border border-slate-700 rounded-xl px-3 py-2 text-sm text-slate-200 focus:ring-2 focus:ring-sky-500 outline-none"
              >
                <option value="all">All Enrolled Children</option>
              </select>
            </div>
          </div>

          {/* Status Alert & Progress */}
          {status.state !== 'idle' && (
            <div className="mt-4 p-4 bg-slate-900/90 border border-slate-700 rounded-xl space-y-3">
              <div className="flex items-center justify-between text-sm">
                <div className="flex items-center gap-2">
                  {status.state === 'running' && <RefreshCw className="w-4 h-4 text-sky-400 animate-spin" />}
                  {status.state === 'completed' && <CheckCircle className="w-4 h-4 text-emerald-400" />}
                  {status.state === 'failed' && <AlertTriangle className="w-4 h-4 text-rose-400" />}
                  <span className="font-semibold text-slate-200 capitalize">{status.state}</span>
                  <span className="text-slate-400">• {status.current_step}</span>
                </div>
                <span className="text-xs font-mono text-slate-400">
                  {status.files_downloaded || 0} files downloaded
                </span>
              </div>

              {/* Console Log Drawer */}
              <div className="pt-2">
                <button
                  onClick={() => setShowLogs(!showLogs)}
                  className="text-xs text-slate-400 hover:text-slate-200 flex items-center gap-1 mb-2 font-mono"
                >
                  <Terminal className="w-3.5 h-3.5" />
                  <span>{showLogs ? 'Hide Live Logs' : 'Show Live Logs'}</span>
                </button>

                {showLogs && status.logs && (
                  <div className="bg-black/80 rounded-xl p-3 max-h-40 overflow-y-auto font-mono text-[11px] text-slate-300 space-y-1">
                    {status.logs.map((log: string, idx: number) => (
                      <div key={idx} className="leading-relaxed">
                        {log}
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
