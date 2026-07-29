import React, { useState, useEffect } from 'react';
import { Shield, CheckCircle2, RefreshCw, AlertTriangle, ArrowLeft, Camera, Monitor, Lock } from 'lucide-react';

interface VerificationInterstitialProps {
  email: string;
  password: string;
  onSuccess: (token: string, user: any) => void;
  onCancel: () => void;
}

export const VerificationInterstitial: React.FC<VerificationInterstitialProps> = ({ email, password, onSuccess, onCancel }) => {
  const [status, setStatus] = useState<any>({
    status: 'running',
    step: 'Initializing Playwright & Cloudflare bypass...',
    step_index: 1,
    screenshot: null,
    error: null
  });

  const pollProgress = async () => {
    try {
      const res = await fetch('/api/auth/verify-progress', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password })
      });
      const data = await res.json();
      if (res.ok) {
        setStatus(data);
        if (data.status === 'success' && data.token) {
          localStorage.setItem('bh_token', data.token);
          localStorage.setItem('bh_email', email);
          setTimeout(() => {
            onSuccess(data.token, data);
          }, 1200);
        }
      }
    } catch (err: any) {
      console.error('Error polling verification progress:', err);
    }
  };

  useEffect(() => {
    pollProgress();
    const interval = setInterval(pollProgress, 1200);
    return () => clearInterval(interval);
  }, []);

  const steps = [
    { title: 'Bypass Cloudflare Turnstile', desc: 'FlareSolverr clearance cookies' },
    { title: 'Auth0 SSO Login Check', desc: 'Validating email & password' },
    { title: 'Discover Enrolled Children', desc: 'Reading portal dependent cards' }
  ];

  return (
    <div className="min-h-screen flex flex-col justify-center items-center p-4 sm:p-6 bg-slate-50 font-sans">
      <div className="max-w-2xl w-full bg-white rounded-2xl p-5 sm:p-8 border border-slate-200 shadow-sm space-y-6">
        {/* Header Banner */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-4 border-b border-slate-100">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-indigo-50 border border-indigo-100 flex items-center justify-center text-indigo-600 shrink-0">
              <Camera className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-base font-bold text-slate-900">Verifying Bright Horizons Account</h2>
              <p className="text-xs text-slate-500 font-mono truncate max-w-[240px] sm:max-w-none">{email}</p>
            </div>
          </div>

          <div className="flex items-center gap-1.5 px-3 py-1 bg-indigo-50 border border-indigo-100 rounded-full text-indigo-700 text-xs font-medium shrink-0 self-start sm:self-auto">
            <Shield className="w-3.5 h-3.5 text-indigo-600" />
            <span>FlareSolverr Cloudflare Bypass Active</span>
          </div>
        </div>

        {/* Step-by-Step Progress Tracker */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {steps.map((s, idx) => {
            const stepNum = idx + 1;
            const isDone = status.step_index > stepNum || status.status === 'success';
            const isCurrent = status.step_index === stepNum && status.status === 'running';

            return (
              <div
                key={idx}
                className={`p-3.5 rounded-xl border transition ${
                  isDone
                    ? 'bg-emerald-50 border-emerald-200 text-emerald-900'
                    : isCurrent
                    ? 'bg-indigo-50 border-indigo-200 text-indigo-900 shadow-sm'
                    : 'bg-slate-50 border-slate-200 text-slate-400'
                }`}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[10px] font-mono font-bold uppercase">Step 0{stepNum}</span>
                  {isDone && <CheckCircle2 className="w-4 h-4 text-emerald-600" />}
                  {isCurrent && <RefreshCw className="w-3.5 h-3.5 text-indigo-600 animate-spin" />}
                </div>
                <h3 className="text-xs font-bold leading-snug">{s.title}</h3>
                <p className="text-[11px] opacity-80 mt-0.5">{s.desc}</p>
              </div>
            );
          })}
        </div>

        {/* Live Headless Browser Screenshot Preview Box */}
        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs text-slate-700 font-medium">
            <span className="flex items-center gap-1.5 font-semibold text-slate-900">
              <Monitor className="w-4 h-4 text-indigo-600" />
              <span>Live Headless Browser Debug View</span>
            </span>
            {status.status === 'running' && (
              <span className="flex items-center gap-1 text-[11px] text-rose-600 font-mono">
                <span className="w-2 h-2 rounded-full bg-rose-500 animate-pulse" />
                LIVE SCREENSHOT
              </span>
            )}
          </div>

          <div className="bg-slate-950 rounded-xl border border-slate-800 p-2 overflow-hidden flex flex-col items-center justify-center min-h-[220px] max-h-[340px] relative group">
            {status.screenshot ? (
              <img
                src={status.screenshot}
                alt="Headless Browser View"
                className="w-full h-auto max-h-[320px] object-contain rounded-lg shadow-md"
              />
            ) : (
              <div className="flex flex-col items-center justify-center py-12 text-slate-500 gap-2">
                <RefreshCw className="w-6 h-6 text-indigo-500 animate-spin" />
                <span className="text-xs font-mono text-slate-400">Capturing live browser viewport...</span>
              </div>
            )}
          </div>

          <div className="p-3 bg-slate-900 rounded-xl font-mono text-[11px] text-slate-300 flex items-center justify-between">
            <span className="truncate flex-1 pr-2">&gt; {status.step}</span>
            {status.status === 'running' && <RefreshCw className="w-3.5 h-3.5 text-indigo-400 animate-spin shrink-0" />}
          </div>
        </div>

        {/* Status Outcome Banners */}
        {status.status === 'success' && (
          <div className="p-4 bg-emerald-50 border border-emerald-200 rounded-xl flex items-center gap-3 text-emerald-900 text-xs">
            <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0" />
            <div>
              <p className="font-bold">Bright Horizons Verification Successful!</p>
              <p className="text-emerald-700 mt-0.5">Discovered enrolled children profiles. Advancing to dashboard portal...</p>
            </div>
          </div>
        )}

        {status.status === 'failed' && (
          <div className="p-4 bg-rose-50 border border-rose-200 rounded-xl space-y-3">
            <div className="flex items-start gap-3 text-rose-900 text-xs">
              <AlertTriangle className="w-5 h-5 text-rose-600 shrink-0 mt-0.5" />
              <div>
                <p className="font-bold">Verification Failed</p>
                <p className="text-rose-700 leading-relaxed mt-0.5">{status.error || 'Check your credentials and try again.'}</p>
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-1 border-t border-rose-200">
              <button
                type="button"
                onClick={onCancel}
                className="px-4 py-2 bg-white hover:bg-slate-100 text-slate-700 text-xs font-semibold rounded-xl border border-slate-300 transition flex items-center gap-1.5"
              >
                <ArrowLeft className="w-3.5 h-3.5" />
                <span>Back to Login</span>
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
