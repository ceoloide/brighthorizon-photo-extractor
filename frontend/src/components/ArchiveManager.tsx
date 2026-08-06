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

  const formatBytes = (bytes?: number) => {
    if (!bytes || isNaN(bytes) || bytes <= 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  return (
    <div className="p-4 sm:p-6 bg-white rounded-2xl border border-slate-200 space-y-4 sm:space-y-5 shadow-sm font-sans">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-xl bg-indigo-50 border border-indigo-100 text-indigo-600 shrink-0">
            <Archive className="w-5 h-5" />
          </div>
          <div>
            <h3 className="font-bold text-slate-900 text-sm sm:text-base">ZIP Archive Download Center</h3>
            <p className="text-xs text-slate-500 mt-0.5">Create a downloadable ZIP file of all saved photos and videos</p>
          </div>
        </div>
      </div>

      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pt-1">
        <div className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-3">
          <label className="text-xs font-semibold uppercase tracking-wider text-slate-700">Layout Format:</label>
          <div className="grid grid-cols-2 p-1 bg-slate-100 border border-slate-200 rounded-xl text-xs font-medium w-full sm:w-auto">
            <button
              type="button"
              onClick={() => setLayoutMode('flat')}
              disabled={status.status === 'processing'}
              className={`px-3 py-2 sm:py-1.5 rounded-lg transition flex items-center justify-center gap-1.5 ${
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
              disabled={status.status === 'processing'}
              className={`px-3 py-2 sm:py-1.5 rounded-lg transition flex items-center justify-center gap-1.5 ${
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

        <button
          onClick={handleCreateArchive}
          disabled={loading || status.status === 'processing'}
          className="w-full sm:w-auto px-5 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-semibold rounded-xl transition disabled:opacity-50 flex items-center justify-center gap-2 shadow-sm active:scale-[0.99]"
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
          <div className="flex justify-between text-xs text-slate-500">
            <span>Compressing media files into ZIP...</span>
            <span className="font-mono font-bold text-indigo-600">{status.progress_percent}%</span>
          </div>
          <div className="w-full h-2 bg-slate-100 rounded-full overflow-hidden border border-slate-200">
            <div
              className="h-full bg-indigo-600 transition-all duration-300 rounded-full"
              style={{ width: `${status.progress_percent}%` }}
            />
          </div>
        </div>
      )}

      {/* Download Box */}
      {status.status === 'ready' && status.archive_id && (
        <div className="p-4 bg-emerald-50 border border-emerald-200 rounded-xl flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs">
          <div className="flex items-center gap-2.5">
            <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0" />
            <div>
              <p className="font-semibold text-emerald-900">Archive Ready for Download!</p>
              <p className="text-emerald-700 font-mono text-[11px]">
                {status.archive_id} • {formatBytes(status.file_size || status.size)}
              </p>
            </div>
          </div>

          <a
            href={`/api/archive/download?token=${token}`}
            className="w-full sm:w-auto px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white font-semibold rounded-xl transition flex items-center justify-center gap-2 shadow-sm shrink-0"
          >
            <Download className="w-4 h-4" />
            <span>Download ZIP Archive</span>
          </a>
        </div>
      )}

      {status.status === 'failed' && (
        <div className="p-3.5 bg-rose-50 border border-rose-200 rounded-xl flex items-center gap-2.5 text-xs text-rose-700">
          <AlertCircle className="w-4 h-4 text-rose-600 shrink-0" />
          <span>Archive creation failed: {status.error || 'Unknown error'}</span>
        </div>
      )}
    </div>
  );
};
