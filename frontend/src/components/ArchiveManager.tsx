import React, { useState, useEffect } from 'react';
import { Archive, Download, RefreshCw, CheckCircle2, AlertCircle } from 'lucide-react';

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
    <div className="p-6 bg-slate-800/80 rounded-2xl border border-slate-700/60 space-y-5">
      <div className="flex items-center justify-between">
        <h3 className="font-bold text-slate-100 flex items-center gap-2">
          <Archive className="w-5 h-5 text-sky-400" />
          <span>ZIP Archive Download Center</span>
        </h3>
        <span className="text-xs text-slate-400">Async Generation & Resumable Downloads</span>
      </div>

      <div className="flex flex-wrap items-center gap-4 pt-2">
        <div className="flex items-center gap-2 text-sm text-slate-300">
          <label className="text-xs font-semibold uppercase tracking-wider text-slate-400">Layout Format:</label>
          <select
            value={layoutMode}
            onChange={(e) => setLayoutMode(e.target.value)}
            disabled={status.status === 'processing'}
            className="bg-slate-900 border border-slate-700 rounded-xl px-3 py-1.5 text-slate-200 outline-none focus:ring-2 focus:ring-sky-500"
          >
            <option value="flat">Flat (ChildName/photo.jpg)</option>
            <option value="nested">Nested (ChildName/YYYY/MM/photo.jpg)</option>
          </select>
        </div>

        <button
          onClick={handleCreateArchive}
          disabled={loading || status.status === 'processing'}
          className="px-4 py-2 bg-sky-600 hover:bg-sky-500 text-white text-sm font-semibold rounded-xl transition disabled:opacity-50 flex items-center gap-2 shadow-md"
        >
          {status.status === 'processing' ? (
            <>
              <RefreshCw className="w-4 h-4 animate-spin" />
              <span>Building Archive ({status.progress_percent}%)...</span>
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
            <span className="font-mono font-bold text-sky-400">{status.progress_percent}%</span>
          </div>
          <div className="w-full h-2.5 bg-slate-900 rounded-full overflow-hidden">
            <div
              className="h-full bg-sky-500 transition-all duration-300 rounded-full"
              style={{ width: `${status.progress_percent}%` }}
            />
          </div>
        </div>
      )}

      {/* Archive Ready State */}
      {status.status === 'ready' && (
        <div className="p-4 bg-emerald-500/10 border border-emerald-500/30 rounded-xl flex flex-wrap items-center justify-between gap-4 text-emerald-400 text-sm">
          <div className="flex items-center gap-3">
            <CheckCircle2 className="w-5 h-5 shrink-0" />
            <div>
              <p className="font-bold">Archive Ready ({formatBytes(status.file_size)})</p>
              <p className="text-xs text-emerald-400/80">Supports HTTP Range header download resume.</p>
            </div>
          </div>
          <a
            href={`/api/archive/download?token=${token}`}
            download={status.archive_id}
            className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white font-semibold rounded-xl transition shadow-lg flex items-center gap-2 text-xs"
          >
            <Download className="w-4 h-4" />
            <span>Download ZIP</span>
          </a>
        </div>
      )}

      {status.status === 'error' && (
        <div className="p-4 bg-rose-500/10 border border-rose-500/30 rounded-xl flex items-center gap-3 text-rose-400 text-sm">
          <AlertCircle className="w-5 h-5 shrink-0" />
          <span>Error generating archive: {status.error}</span>
        </div>
      )}
    </div>
  );
};
