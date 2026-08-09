import React, { useState, useEffect } from 'react';
import { Play, RefreshCw, LogOut, CheckCircle2, AlertTriangle, Terminal, Camera, Shield, ShieldCheck, FileSpreadsheet, FolderTree, Trash2, AlertCircle, Copy, Check, Monitor, Download } from 'lucide-react';
import { Gallery } from './Gallery';
import { ArchiveManager } from './ArchiveManager';

interface DashboardProps {
  token: string;
  email: string;
  childrenList?: any[];
  onLogout: () => void;
}

export const Dashboard: React.FC<DashboardProps> = ({ token, email, childrenList = [], onLogout }) => {
  const [syncMode, setSyncMode] = useState<'incremental' | 'full' | 'custom'>('incremental');
  const [startDate, setStartDate] = useState<string>('');
  const [targetChild, setTargetChild] = useState<string>('all');
  const [status, setStatus] = useState<any>({ state: 'idle', logs: [] });
  const [refreshTrigger, setRefreshTrigger] = useState<number>(0);
  const [showLogs, setShowLogs] = useState<boolean>(false);
  const [showDebugLogs, setShowDebugLogs] = useState<boolean>(false);
  const [copiedLogs, setCopiedLogs] = useState<boolean>(false);
  const [showDeleteModal, setShowDeleteModal] = useState<boolean>(false);
  const [showConflictModal, setShowConflictModal] = useState<boolean>(false);
  const [showLogoutConfirmModal, setShowLogoutConfirmModal] = useState<boolean>(false);
  const [showSessionWarningModal, setShowSessionWarningModal] = useState<boolean>(false);
  const [dismissedSessionWarning, setDismissedSessionWarning] = useState<boolean>(false);
  const [sessionExpiresAt, setSessionExpiresAt] = useState<number | null>(null);
  const [remainingSeconds, setRemainingSeconds] = useState<number | null>(null);
  const [deleting, setDeleting] = useState<boolean>(false);
  const [cancelling, setCancelling] = useState<boolean>(false);
  const [starting, setStarting] = useState<boolean>(false);
  const [mfaCode, setMfaCode] = useState<string>('');
  const [mfaSubmitting, setMfaSubmitting] = useState<boolean>(false);
  const [mfaError, setMfaError] = useState<string | null>(null);

  const handleSubmitMfaCode = async (e: React.FormEvent) => {
    e.preventDefault();
    if (mfaCode.length !== 6 || !/^\d+$/.test(mfaCode)) {
      setMfaError('Please enter a valid 6-digit verification code.');
      return;
    }
    setMfaSubmitting(true);
    setMfaError(null);
    try {
      const res = await fetch('/api/auth/submit-mfa-code', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, code: mfaCode })
      });
      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || 'Failed to submit verification code.');
      }
      setStatus((prev: any) => ({
        ...prev,
        state: 'running',
        current_step: 'Submitting verification code to Bright Horizons...'
      }));
      setMfaCode('');
    } catch (err: any) {
      setMfaError(err.message || 'Failed to submit code.');
      setMfaSubmitting(false);
    }
  };

  const handleSignOutClick = () => {
    if (status.state === 'running') {
      setShowLogoutConfirmModal(true);
    } else {
      onLogout();
    }
  };

  const handleCopyLogs = () => {
    if (!status.logs || status.logs.length === 0) return;
    const filtered = status.logs.filter((log: string) => showDebugLogs || !log.includes('[DEBUG]'));
    const fullLogText = filtered.join('\n');
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(fullLogText);
    } else {
      const textArea = document.createElement('textarea');
      textArea.value = fullLogText;
      document.body.appendChild(textArea);
      textArea.select();
      document.execCommand('copy');
      document.body.removeChild(textArea);
    }
    setCopiedLogs(true);
    setTimeout(() => setCopiedLogs(false), 2000);
  };

  const handleDownloadLogs = () => {
    const link = document.createElement('a');
    link.href = `/api/logs/download?token=${encodeURIComponent(token)}`;
    link.download = `extraction_log.log`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handleReauthenticateNow = async () => {
    setShowSessionWarningModal(false);
    if (status.state === 'running') {
      try {
        await fetch('/api/extraction/cancel', {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` }
        });
      } catch {}
    }
    onLogout();
  };

  const fetchSessionInfo = async () => {
    try {
      const res = await fetch('/api/auth/me', {
        headers: { Authorization: `Bearer ${token}` }
      });
      const data = await res.json();
      if (res.ok && data.session_expires_at) {
        setSessionExpiresAt(data.session_expires_at);
      }
    } catch (err) {
      console.error('Error fetching session info:', err);
    }
  };

  const fetchStatus = async () => {
    try {
      const res = await fetch('/api/extraction/status', {
        headers: { Authorization: `Bearer ${token}` }
      });
      const data = await res.json();
      if (res.ok) {
        setStatus(data);
        if (data.state !== 'running') {
          setCancelling(false);
        }
        if (data.state === 'completed') {
          setRefreshTrigger((prev) => prev + 1);
        }
      }
    } catch (err) {
      console.error('Error fetching extraction status:', err);
    }
  };

  useEffect(() => {
    fetchSessionInfo();
  }, [token]);

  // Session expiration countdown timer (1s interval)
  useEffect(() => {
    if (!sessionExpiresAt) return;

    const updateTimer = () => {
      const now = Date.now();
      const rem = Math.max(0, Math.floor((sessionExpiresAt - now) / 1000));
      setRemainingSeconds(rem);

      // Trigger 5-minute warning modal
      if (rem <= 300 && rem > 0 && !dismissedSessionWarning) {
        setShowSessionWarningModal(true);
      }
    };

    updateTimer();
    const timer = setInterval(updateTimer, 1000);
    return () => clearInterval(timer);
  }, [sessionExpiresAt, dismissedSessionWarning]);

  useEffect(() => {
    fetchStatus();

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        fetchStatus();
      }
    };

    const handleFocus = () => {
      fetchStatus();
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    window.addEventListener('focus', handleFocus);

    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      window.removeEventListener('focus', handleFocus);
    };
  }, [token]);

  // Connect to real-time SSE extraction events stream & poll while running with auto-reconnect
  useEffect(() => {
    let sse: EventSource | null = null;
    let reconnectTimer: any = null;
    let pollTimer: any = null;
    let isMounted = true;

    const connectSSE = () => {
      if (!isMounted) return;
      const url = `/api/extraction/events?token=${encodeURIComponent(token)}`;
      if (sse) {
        try {
          sse.close();
        } catch {}
      }

      sse = new EventSource(url);

      sse.onmessage = (e) => {
        if (e.data && isMounted) {
          try {
            const data = JSON.parse(e.data);
            setStatus((prev: any) => {
              if ((data.files_downloaded || 0) > (prev?.files_downloaded || 0)) {
                setRefreshTrigger((r) => r + 1);
              }
              return data;
            });
            if (data.state === 'completed') {
              setRefreshTrigger((prev) => prev + 1);
              setCancelling(false);
            } else if (data.state === 'failed' || data.state === 'cancelled') {
              setCancelling(false);
            }
          } catch {}
        }
      };

      sse.onerror = () => {
        if (!isMounted) return;
        try {
          sse?.close();
        } catch {}
        if (reconnectTimer) clearTimeout(reconnectTimer);
        reconnectTimer = setTimeout(() => {
          if (isMounted) {
            fetchStatus();
            connectSSE();
          }
        }, 3000);
      };
    };

    if (status.state === 'running') {
      connectSSE();

      // Fallback periodic poll to ensure gallery refreshes dynamically
      pollTimer = setInterval(() => {
        if (isMounted) {
          fetchStatus();
        }
      }, 4000);
    }

    return () => {
      isMounted = false;
      if (sse) {
        try {
          sse.close();
        } catch {}
      }
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (pollTimer) clearInterval(pollTimer);
    };
  }, [status.state, token]);

  const handleStartExtraction = async (force: boolean = false) => {
    setShowConflictModal(false);
    setStarting(true);
    try {
      const res = await fetch('/api/extraction/start', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({
          sync_mode: syncMode,
          start_date: startDate || undefined,
          child: targetChild,
          force: force
        })
      });
      const data = await res.json();
      if (res.status === 409 || data.status === 'running_conflict') {
        setShowConflictModal(true);
        return;
      }
      if (res.ok) {
        setStatus(data.job || data);
      }
    } catch (err) {
      console.error('Failed to start extraction:', err);
    } finally {
      setStarting(false);
    }
  };

  const handleCancelExtraction = async () => {
    setCancelling(true);
    try {
      await fetch('/api/extraction/cancel', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` }
      });
      fetchStatus();
    } catch (err) {
      console.error('Failed to cancel extraction:', err);
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

  const isInputDisabled = status.state === 'running' || starting || cancelling;

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
              <span className="truncate">Bright Horizon Photo Extractor</span>
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
            onClick={handleSignOutClick}
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
                Configure sync options and download child photos and videos.
              </p>
            </div>

            <div className="flex items-center gap-2">
              {status.state === 'running' ? (
                <button
                  onClick={handleCancelExtraction}
                  disabled={cancelling}
                  className="w-full sm:w-auto px-4 py-2.5 bg-rose-600 hover:bg-rose-700 text-white text-xs font-semibold rounded-xl transition disabled:opacity-50 flex items-center justify-center gap-1.5 shadow-sm"
                >
                  {cancelling ? (
                    <>
                      <RefreshCw className="w-4 h-4 animate-spin" />
                      <span>Cancelling Job...</span>
                    </>
                  ) : (
                    <>
                      <AlertCircle className="w-4 h-4" />
                      <span>Cancel Job</span>
                    </>
                  )}
                </button>
              ) : (
                <button
                  onClick={() => handleStartExtraction(false)}
                  disabled={starting}
                  className="w-full sm:w-auto px-5 py-2.5 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-xs font-semibold rounded-xl transition flex items-center justify-center gap-2 shadow-sm active:scale-[0.99]"
                >
                  {starting ? (
                    <>
                      <RefreshCw className="w-4 h-4 animate-spin" />
                      <span>Starting Job...</span>
                    </>
                  ) : (
                    <>
                      <Play className="w-4 h-4 fill-current" />
                      <span>Start Extraction</span>
                    </>
                  )}
                </button>
              )}
            </div>
          </div>

          {/* Live Progress Card if Job is Running */}
          {status.state === 'running' && (
            <div className="bg-indigo-50/60 border border-indigo-100 rounded-xl p-4 space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-2 text-xs font-semibold text-indigo-900">
                  <RefreshCw className="w-4 h-4 text-indigo-600 animate-spin" />
                  <span>Job Running: {status.current_step || 'Processing...'}</span>
                </div>
                <span className="text-xs font-mono font-bold text-indigo-700 bg-white border border-indigo-200 px-2.5 py-1 rounded-lg shadow-2xs">
                  {status.files_downloaded || 0} Files Downloaded
                </span>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 pt-1 text-xs">
                <div className="bg-white p-2.5 rounded-lg border border-indigo-100/80">
                  <span className="text-[10px] uppercase tracking-wider font-semibold text-slate-400 block">Target Child</span>
                  <span className="font-bold text-slate-800">{status.current_child || 'All Enrolled Children'}</span>
                </div>
                <div className="bg-white p-2.5 rounded-lg border border-indigo-100/80">
                  <span className="text-[10px] uppercase tracking-wider font-semibold text-slate-400 block">Timeline Month</span>
                  <span className="font-bold text-slate-800">{status.current_month || 'Loading...'}</span>
                </div>
                <div className="bg-white p-2.5 rounded-lg border border-indigo-100/80">
                  <span className="text-[10px] uppercase tracking-wider font-semibold text-slate-400 block">Current Post Date</span>
                  <span className="font-bold text-indigo-600 font-mono">{status.current_date || '—'}</span>
                </div>
              </div>
            </div>
          )}

          {/* Completed / Failed / Cancelled State Banners */}
          {status.state === 'completed' && (
            <div className="bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-xl p-3.5 flex items-center justify-between text-xs font-medium">
              <div className="flex items-center space-x-2">
                <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
                <span>Extraction job completed successfully! Downloaded {status.files_downloaded || 0} media items.</span>
              </div>
            </div>
          )}

          {status.state === 'failed' && (
            <div className="bg-rose-50 border border-rose-200 text-rose-800 rounded-xl p-3.5 flex items-center space-x-2 text-xs font-medium">
              <AlertCircle className="w-4 h-4 text-rose-600 shrink-0" />
              <span>Extraction failed: {status.error || 'An unexpected error occurred.'}</span>
            </div>
          )}

          {status.state === 'cancelled' && (
            <div className="bg-amber-50 border border-amber-200 text-amber-800 rounded-xl p-3.5 flex items-center space-x-2 text-xs font-medium">
              <AlertCircle className="w-4 h-4 text-amber-600 shrink-0" />
              <span>Extraction job was cancelled by user.</span>
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4 pt-1">
            {/* Target Child Selector (First) */}
            <div className="space-y-1.5">
              <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider">
                Target Child
              </label>
              <select
                value={targetChild}
                onChange={(e) => setTargetChild(e.target.value)}
                disabled={isInputDisabled}
                className="w-full bg-white border border-slate-300 rounded-xl px-3.5 py-2.5 sm:py-2 text-xs text-slate-800 focus:border-indigo-600 outline-none transition font-medium disabled:opacity-50"
              >
                <option value="all">All Enrolled Children</option>
                {childrenList && childrenList.map((c: any, i: number) => {
                  const name = typeof c === 'string' ? c : c.name;
                  return (
                    <option key={i} value={name.toLowerCase()}>
                      {name}
                    </option>
                  );
                })}
              </select>
            </div>

            {/* Sync Mode Controls (Second) */}
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider">
                  Sync Mode
                </label>
              </div>

              <div className="grid grid-cols-3 p-1 bg-slate-100 border border-slate-200 rounded-xl text-xs font-medium">
                <button
                  type="button"
                  onClick={() => setSyncMode('incremental')}
                  disabled={isInputDisabled}
                  title="Resume from last sync date, extracting only new posts."
                  className={`py-2 sm:py-1.5 rounded-lg transition ${
                    syncMode === 'incremental'
                      ? 'bg-white text-indigo-700 font-semibold border border-slate-200 shadow-sm'
                      : 'text-slate-500 hover:text-slate-800'
                  } disabled:opacity-50`}
                >
                  Incremental
                </button>
                <button
                  type="button"
                  onClick={() => setSyncMode('full')}
                  disabled={isInputDisabled}
                  title="Rescan all historical media across all history for the selected child or all enrolled children."
                  className={`py-2 sm:py-1.5 rounded-lg transition ${
                    syncMode === 'full'
                      ? 'bg-white text-indigo-700 font-semibold border border-slate-200 shadow-sm'
                      : 'text-slate-500 hover:text-slate-800'
                  } disabled:opacity-50`}
                >
                  Full
                </button>
                <button
                  type="button"
                  onClick={() => setSyncMode('custom')}
                  disabled={isInputDisabled}
                  title="Extract media published on or after a selected custom start date."
                  className={`py-2 sm:py-1.5 rounded-lg transition ${
                    syncMode === 'custom'
                      ? 'bg-white text-indigo-700 font-semibold border border-slate-200 shadow-sm'
                      : 'text-slate-500 hover:text-slate-800'
                  } disabled:opacity-50`}
                >
                  Custom
                </button>
              </div>
              <p className="text-[10px] text-slate-400 italic">
                {syncMode === 'incremental' && '• Resumes from last sync date, skipping existing downloads.'}
                {syncMode === 'full' && '• Downloads all historical pictures for selected child/children.'}
                {syncMode === 'custom' && '• Filter posts published on or after custom start date.'}
              </p>
            </div>

            {/* Custom Start Date Picker (Third, when Custom is selected) */}
            {syncMode === 'custom' && (
              <div className="space-y-1.5">
                <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider">
                  Start Date
                </label>
                <input
                  type="date"
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                  disabled={isInputDisabled}
                  className="w-full bg-white border border-slate-300 rounded-xl px-3.5 py-2 text-xs font-mono text-slate-800 focus:border-indigo-600 outline-none transition disabled:opacity-50"
                />
              </div>
            )}
          </div>

          {/* Status Alert & Progress Console */}
          {status.state !== 'idle' && (
            <div className="p-3.5 sm:p-4 bg-slate-50 border border-slate-200 rounded-xl space-y-3">
              {/* MFA Code Submission Interstitial Card */}
              {status.state === 'mfa_required' && (
                <form
                  onSubmit={handleSubmitMfaCode}
                  className="p-4 bg-amber-50 border border-amber-200 rounded-xl space-y-3 shadow-sm mb-3"
                >
                  <div className="flex items-start gap-3">
                    <div className="w-8 h-8 rounded-lg bg-amber-100 border border-amber-200 flex items-center justify-center text-amber-700 shrink-0 mt-0.5">
                      <ShieldCheck className="w-4 h-4" />
                    </div>
                    <div className="space-y-1">
                      <h4 className="text-xs font-bold text-amber-950 uppercase tracking-wider">Email Verification Code Required</h4>
                      <p className="text-xs text-amber-800 leading-relaxed">
                        Bright Horizons sent a 6-digit verification code to <span className="font-semibold">{email}</span>. Enter it below to authorize this extraction run.
                      </p>
                    </div>
                  </div>

                  {mfaError && (
                    <div className="p-2.5 bg-rose-50 border border-rose-200 rounded-lg text-xs text-rose-700 font-medium">
                      {mfaError}
                    </div>
                  )}

                  <div className="flex items-center gap-2.5 pt-1">
                    <input
                      type="text"
                      maxLength={6}
                      placeholder="123456"
                      value={mfaCode}
                      onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, ''))}
                      disabled={mfaSubmitting}
                      className="w-36 bg-white border border-amber-300 focus:border-amber-600 rounded-lg px-3 py-2 text-center text-base font-mono tracking-widest text-amber-950 font-bold outline-none shadow-inner"
                      autoFocus
                    />
                    <button
                      type="submit"
                      disabled={mfaSubmitting || mfaCode.length !== 6}
                      className="px-4 py-2 bg-amber-600 hover:bg-amber-700 active:bg-amber-800 disabled:opacity-50 text-white font-semibold text-xs rounded-lg transition shadow-sm flex items-center gap-1.5"
                    >
                      {mfaSubmitting ? (
                        <>
                          <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                          <span>Verifying...</span>
                        </>
                      ) : (
                        <span>Verify & Continue</span>
                      )}
                    </button>
                  </div>
                </form>
              )}

              <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                <div className="flex items-center gap-2">
                  {status.state === 'running' && <RefreshCw className="w-4 h-4 text-indigo-600 animate-spin shrink-0" />}
                  {status.state === 'mfa_required' && <ShieldCheck className="w-4 h-4 text-amber-600 shrink-0" />}
                  {status.state === 'completed' && <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />}
                  {status.state === 'failed' && <AlertTriangle className="w-4 h-4 text-rose-600 shrink-0" />}
                  <span className="font-semibold text-slate-900 capitalize">{status.state === 'mfa_required' ? 'MFA Verification Required' : status.state}</span>
                  <span className="text-slate-500 font-mono text-[11px] truncate max-w-[160px] sm:max-w-none">
                    • {status.current_step}
                  </span>
                </div>
                <span className="text-[11px] font-mono text-indigo-700 bg-indigo-50 border border-indigo-100 px-2.5 py-0.5 rounded-full font-semibold">
                  {status.files_downloaded || 0} downloaded
                </span>
              </div>

              {/* Console Log Drawer & Live Browser Preview */}
              <div className="pt-1">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-3">
                    <button
                      onClick={() => setShowLogs(!showLogs)}
                      className="text-[11px] text-slate-500 hover:text-slate-800 flex items-center gap-1.5 font-mono"
                    >
                      <Terminal className="w-3.5 h-3.5 text-indigo-600 shrink-0" />
                      <span>{showLogs ? 'Hide Console Logs' : 'Show Console Logs'}</span>
                    </button>

                    {showLogs && (
                      <label className="text-[11px] text-slate-500 hover:text-slate-700 flex items-center gap-1.5 font-mono cursor-pointer select-none border-l border-slate-200 pl-3">
                        <input
                          type="checkbox"
                          checked={showDebugLogs}
                          onChange={(e) => setShowDebugLogs(e.target.checked)}
                          className="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500 h-3 w-3"
                        />
                        <span>Show Debug Logs</span>
                      </label>
                    )}
                  </div>

                  {showLogs && status.logs && status.logs.length > 0 && (
                    <div className="flex items-center gap-2">
                      <button
                        onClick={handleCopyLogs}
                        className="text-[11px] text-slate-500 hover:text-indigo-600 flex items-center gap-1 font-mono bg-white hover:bg-slate-100 border border-slate-200 px-2 py-1 rounded-lg transition"
                        title="Copy visible console log content to clipboard"
                      >
                        {copiedLogs ? (
                          <>
                            <Check className="w-3 h-3 text-emerald-600" />
                            <span className="text-emerald-600 font-semibold">Copied!</span>
                          </>
                        ) : (
                          <>
                            <Copy className="w-3 h-3 text-slate-500" />
                            <span>Copy Logs</span>
                          </>
                        )}
                      </button>
                      <button
                        onClick={handleDownloadLogs}
                        className="text-[11px] text-slate-500 hover:text-indigo-600 flex items-center gap-1 font-mono bg-white hover:bg-slate-100 border border-slate-200 px-2 py-1 rounded-lg transition"
                        title="Download full un-truncated persistent log file from disk"
                      >
                        <Download className="w-3 h-3 text-slate-500" />
                        <span>Download Full Log</span>
                      </button>
                    </div>
                  )}
                </div>

                {showLogs && status.logs && (
                  <div className="bg-slate-900 rounded-xl p-3 sm:p-3.5 max-h-56 overflow-y-auto font-mono text-[11px] text-slate-200 space-y-1 border border-slate-800">
                    {status.logs.filter((log: string) => showDebugLogs || !log.includes('[DEBUG]')).length === 0 ? (
                      <div className="text-slate-500 italic py-1">
                        No non-debug logs. Check "Show Debug Logs" to view network trace events.
                      </div>
                    ) : (
                      status.logs
                        .filter((log: string) => showDebugLogs || !log.includes('[DEBUG]'))
                        .map((log: string, idx: number) => (
                          <div key={idx} className="leading-relaxed flex items-start gap-2 break-all">
                            <span className="text-slate-500 select-none">&gt;</span>
                            <span className={log.includes('[DEBUG]') ? 'text-slate-400 opacity-80' : ''}>{log}</span>
                          </div>
                        ))
                    )}
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

      {/* Job Running Conflict Confirmation Modal */}
      {showConflictModal && (
        <div className="fixed inset-0 z-50 bg-slate-900/60 flex items-center justify-center p-4">
          <div className="max-w-md w-full bg-white border border-slate-200 rounded-2xl p-5 sm:p-6 shadow-xl space-y-4">
            <div className="flex items-center gap-3 text-amber-600">
              <div className="p-2 bg-amber-50 rounded-xl border border-amber-100 shrink-0">
                <AlertTriangle className="w-6 h-6" />
              </div>
              <h3 className="font-bold text-slate-900 text-base">Extraction Job Already Running</h3>
            </div>

            <p className="text-xs text-slate-600 leading-relaxed">
              An extraction job is currently active for your account. Starting a new job will cancel the existing job in progress.
            </p>
            <p className="text-[11px] text-amber-700 font-medium">
              Only a single active background job is allowed per account.
            </p>

            <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setShowConflictModal(false)}
                className="w-full sm:w-auto px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold rounded-xl transition border border-slate-200"
              >
                Keep Current Job
              </button>
              <button
                type="button"
                onClick={() => handleStartExtraction(true)}
                className="w-full sm:w-auto px-4 py-2 bg-amber-600 hover:bg-amber-700 text-white text-xs font-semibold rounded-xl transition shadow-sm flex items-center justify-center gap-2"
              >
                <Play className="w-3.5 h-3.5 fill-current" />
                <span>Stop Old & Start New Job</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 5-Minute Session Expiration Warning Modal */}
      {showSessionWarningModal && remainingSeconds !== null && remainingSeconds > 0 && (
        <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="max-w-md w-full bg-white border border-amber-200 rounded-2xl p-5 sm:p-6 shadow-xl space-y-4">
            <div className="flex items-center gap-3 text-amber-600">
              <div className="p-2 bg-amber-50 rounded-xl border border-amber-100 shrink-0">
                <AlertTriangle className="w-6 h-6" />
              </div>
              <div>
                <h3 className="font-bold text-slate-900 text-base">Session Expiring Soon</h3>
                <p className="text-xs text-amber-700 font-medium">Bright Horizons security token expiration</p>
              </div>
            </div>

            <div className="bg-amber-50/80 rounded-xl p-4 border border-amber-200/60 text-center space-y-1">
              <span className="text-[11px] text-amber-800 uppercase font-mono tracking-wider font-semibold">Time Remaining</span>
              <div className="text-3xl font-mono font-bold text-amber-900">
                {Math.floor(remainingSeconds / 60).toString().padStart(2, '0')}:{(remainingSeconds % 60).toString().padStart(2, '0')}
              </div>
            </div>

            <p className="text-xs text-slate-600 leading-relaxed">
              Your Bright Horizons portal session will expire in <strong className="text-amber-800">{Math.floor(remainingSeconds / 60)}m {remainingSeconds % 60}s</strong>. Re-authenticating now ensures uninterrupted photo & video downloads.
            </p>

            <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => {
                  setShowSessionWarningModal(false);
                  setDismissedSessionWarning(true);
                }}
                className="w-full sm:w-auto px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold rounded-xl transition border border-slate-200"
              >
                Dismiss Warning
              </button>
              <button
                type="button"
                onClick={handleReauthenticateNow}
                className="w-full sm:w-auto px-4 py-2 bg-amber-600 hover:bg-amber-700 text-white text-xs font-semibold rounded-xl transition shadow-sm flex items-center justify-center gap-2"
              >
                <RefreshCw className="w-3.5 h-3.5" />
                <span>Re-authenticate Now</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
