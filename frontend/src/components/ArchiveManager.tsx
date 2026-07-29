import React, { useState, useEffect } from 'react';
import { Archive, Download, RefreshCw, CheckCircle2, AlertCircle, FileSpreadsheet, FolderTree } from 'lucide-react';

interface ArchiveManagerProps {
  token: string;
}

export const ArchiveManager: React.FC<ArchiveManagerProps> = ({ token }) => {
  const [layoutMode, setLayoutMode] = useState<string>('flat');
  const [status, setStatus] = useState<any>({ status: 'idle', progress_percent: 0 });
  const [loading, setLoading] = useState<boolean>(false);

  const fetchStatus = async () => {
    try {
      const res = await fetch('/api/archive/status', {
        headers: { Authorization: `Bearer ${token}` }
      });
      const data = await res.json();
      if (res.ok) {
        setStatus(data);
      }
    } catch (err) {
      console.error('Failed to fetch archive status:', err);
    }
  };

  useEffect(() => {
    fetchStatus();
  }, [token]);

  useEffect(() => {
    let interval: any;
    if (status.status === 'processing') {
      interval = setInterval(fetchStatus, 1500);
    }
    return () => clearInterval(interval);
  }, [status.status]);

  const handleCreateArchive = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/archive/create', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({ layout_mode: layoutMode })
      });
      const data = await res.json();
      if (res.ok) {
        setStatus(data);
      }
    } catch (err) {
      console.error('Error starting archive creation:', err);
    } finally {
      setLoading(false);
    }
  };

  const formatBytes = (bytes: number) => {
    if (!bytes) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  return (
    <div className="p-6 bg-slate-800 rounded-xl border border-slate-700 space-y-5 shadow-sm font-sans">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-blue-600/10 border border-blue-500/20 text-blue-400">
            <Archive className="w-5 h-5" />
          </div>
          <div>
            <h3 className="font-bold text-slate-100 text-base">ZIP Archive Download Center</h3>
            <p className="text-xs text-slate-400 mt-0.5">Async archive creation with HTTP Range download resume</p>
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-4 pt-1">
        <div className="flex items-center gap-3">
          <label className="text-xs font-semibold uppercase tracking-wider text-slate-300">Layout Format:</label>
          <div className="grid grid-cols-2 p-1 bg-slate-900 border border-slate-700 rounded-lg text-xs font-medium">
            <button
              type="button"
              onClick={() => setLayoutMode('flat')}
              disabled={status.status === 'processing'}
              className={`px-3 py-1.5 rounded transition flex items-center gap-1.5 ${
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
              disabled={status.status === 'processing'}
              className={`px-3 py-1.5 rounded transition flex items-center gap-1.5 ${
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

        <button
          onClick={handleCreateArchive}
          disabled={loading || status.status === 'processing'}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold rounded-lg transition disabled:opacity-50 flex items-center gap-2 shadow-sm"
        >
          {status.status === 'processing' ? (
            <>
              <RefreshCw className="w-4 h-4 animate-spin" />
              <span>Compressing ZIP ({status.progress_percent}%)...</span>
            </>
          ) : (
            <>
              <Archive className="w-4 h-4" />
              <span>Generate ZIP Archive</span>
            </>
          )}
        </button>
      </div>

      {/* Progress Bar */}
      {status.status === 'processing' && (
        <div className="space-y-1.5 pt-2">
          <div className="flex justify-between text-xs text-slate-400">
            <span>Compressing media files into ZIP...</span>
            <span className="font-mono font-bold text-blue-400">{status.progress_percent}%</span>
          </div>
          <div className="w-full h-2 bg-slate-900 rounded-full overflow-hidden border border-slate-700">
            <div
              className="h-full bg-blue-500 transition-all duration-300 rounded-full"
              style={{ width: `${status.progress_percent}%` }}
            />
          </div>
        </div>
      )}

      {/* Archive Ready State */}
      {status.status === 'ready' && (
        <div className="p-4 bg-emerald-500/10 border border-emerald-500/30 rounded-lg flex flex-wrap items-center justify-between gap-4 text-emerald-300 text-xs">
          <div className="flex items-center gap-3">
            <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
            <div>
              <p className="font-bold text-sm text-emerald-300">ZIP Archive Ready ({formatBytes(status.file_size)})</p>
              <p className="text-emerald-400/80 text-[11px] mt-0.5">Supports HTTP Range headers for download pause and resume.</p>
            </div>
          </div>
          <a
            href={`/api/archive/download?token=${token}`}
            download={status.archive_id}
            className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white font-semibold rounded-lg transition shadow-sm flex items-center gap-2 text-xs"
          >
            <Download className="w-4 h-4" />
            <span>Download Archive</span>
          </a>
        </div>
      )}

      {status.status === 'error' && (
        <div className="p-4 bg-rose-500/10 border border-rose-500/30 rounded-lg flex items-center gap-3 text-rose-300 text-xs">
          <AlertCircle className="w-5 h-5 text-rose-400 shrink-0" />
          <span>Error generating archive: {status.error}</span>
        </div>
      )}
    </div>
  );
};
