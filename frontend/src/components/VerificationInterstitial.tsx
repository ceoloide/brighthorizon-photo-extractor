import React, { useState, useEffect } from 'react';
import { CheckCircle2, RefreshCw, AlertTriangle, ArrowLeft, Camera, Monitor, ShieldCheck, Lock, Unlock, ChevronRight } from 'lucide-react';

interface VerificationInterstitialProps {
  email: string;
  password: string;
  onSuccess: (token: string, user: any) => void;
  onCancel: () => void;
}

const formatRelativeTime = (timestampMs: number | null): string => {
  if (!timestampMs) return 'Waiting for update...';
  const diffSec = Math.max(0, Math.floor((Date.now() - timestampMs) / 1000));
  if (diffSec < 3) return 'Just now';
  if (diffSec < 60) return `${diffSec} seconds ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin === 1) return 'A minute ago';
  if (diffMin < 60) {
    const numberWords: { [k: number]: string } = {
      2: 'Two', 3: 'Three', 4: 'Four', 5: 'Five', 6: 'Six', 7: 'Seven', 8: 'Eight', 9: 'Nine', 10: 'Ten'
    };
    const minStr = numberWords[diffMin] || `${diffMin}`;
    return `${minStr} minutes ago`;
  }
  const diffHours = Math.floor(diffMin / 60);
  if (diffHours === 1) return 'An hour ago';
  return `${diffHours} hours ago`;
};

export const VerificationInterstitial: React.FC<VerificationInterstitialProps> = ({ email, password, onSuccess, onCancel }) => {
  const [status, setStatus] = useState<any>({
    status: 'running',
    step: 'Initializing Playwright & Cloudflare bypass...',
    step_index: 1,
    screenshot: null,
    error: null
  });
  const [lastSseTime, setLastSseTime] = useState<number | null>(null);
  const [, setNowTick] = useState<number>(Date.now());
  const [mfaCode, setMfaCode] = useState<string>('');
  const [mfaSubmitting, setMfaSubmitting] = useState<boolean>(false);
  const [mfaError, setMfaError] = useState<string | null>(null);

  // Live preview interactivity state (Default: Locked)
  const [isUnlocked, setIsUnlocked] = useState<boolean>(false);
  const [clickRipple, setClickRipple] = useState<{ x: number; y: number; id: number } | null>(null);

  // 1-second ticker to smoothly increment smart relative timestamp
  useEffect(() => {
    const timer = setInterval(() => {
      setNowTick(Date.now());
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  // Connect to SSE event stream
  useEffect(() => {
    let isMounted = true;
    let eventSource: EventSource | null = null;

    const connectSSE = () => {
      const url = `/api/auth/verify-stream?email=${encodeURIComponent(email)}&password=${encodeURIComponent(password)}`;
      eventSource = new EventSource(url);

      eventSource.onmessage = (event) => {
        if (!isMounted) return;
        try {
          const data = JSON.parse(event.data);
          setStatus(data);
          setLastSseTime(Date.now());
          if (data.status === 'success' && data.token) {
            localStorage.setItem('bh_token', data.token);
            localStorage.setItem('bh_email', email);
            setTimeout(() => {
              if (isMounted) onSuccess(data.token, data);
            }, 1200);
          }
        } catch (e) {
          console.error('Error parsing SSE payload:', e);
        }
      };

      eventSource.onerror = () => {
        if (eventSource) {
          eventSource.close();
        }
      };
    };

    connectSSE();

    return () => {
      isMounted = false;
      if (eventSource) {
        eventSource.close();
      }
    };
  }, [email, password]);

  const steps = [
    {
      title: 'Initialize Browser Engine',
      desc: 'Solving Cloudflare clearance & launching headful browser'
    },
    {
      title: 'Authenticate & Verify Identity',
      desc: status.step_index === 2 && status.step ? status.step : 'Validating email, password & security challenge'
    },
    {
      title: 'Discover Enrolled Children',
      desc: 'Reading Angular CDK portal child cards'
    }
  ];

  const handlePreviewClick = async (e: React.MouseEvent<HTMLImageElement>) => {
    if (!isUnlocked) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const x_percent = (e.clientX - rect.left) / rect.width;
    const y_percent = (e.clientY - rect.top) / rect.height;

    const rippleId = Date.now();
    setClickRipple({ x: e.clientX - rect.left, y: e.clientY - rect.top, id: rippleId });
    setTimeout(() => {
      setClickRipple((prev) => (prev?.id === rippleId ? null : prev));
    }, 900);

    try {
      await fetch('/api/auth/interact-preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, x_percent, y_percent })
      });
    } catch (err) {
      console.error('Failed to replicate click:', err);
    }
  };

  const handleNextStep = async () => {
    try {
      await fetch('/api/auth/next-step', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email })
      });
    } catch (err) {
      console.error('Failed to trigger next step:', err);
    }
  };

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
                className={`p-3.5 rounded-xl border transition flex flex-col justify-between ${
                  isDone
                    ? 'bg-emerald-50 border-emerald-200 text-emerald-900'
                    : isCurrent
                    ? 'bg-indigo-50 border-indigo-200 text-indigo-900 shadow-sm'
                    : 'bg-slate-50 border-slate-200 text-slate-400'
                }`}
              >
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[10px] font-mono font-bold uppercase">Step 0{stepNum}</span>
                    {isDone && <CheckCircle2 className="w-4 h-4 text-emerald-600" />}
                    {isCurrent && <RefreshCw className="w-3.5 h-3.5 text-indigo-600 animate-spin" />}
                  </div>
                  <h3 className="text-xs font-bold leading-snug">{s.title}</h3>
                  <p className="text-[11px] opacity-80 mt-0.5 leading-tight">{s.desc}</p>
                </div>

                {/* Step 2 Manual Next Step Button */}
                {idx === 1 && isCurrent && (
                  <button
                    type="button"
                    onClick={handleNextStep}
                    className="mt-3 w-full py-1.5 px-3 bg-indigo-600 hover:bg-indigo-700 text-white text-[11px] font-bold rounded-lg transition flex items-center justify-center gap-1 shadow-sm"
                  >
                    <span>Next Step</span>
                    <ChevronRight className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
            );
          })}
        </div>

        {/* Live Headless Browser Screenshot Preview Box */}
        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs text-slate-700 font-medium">
            <span className="flex items-center gap-1.5 font-semibold text-slate-900">
              <Monitor className="w-4 h-4 text-indigo-600" />
              <span>Live Preview</span>
            </span>

            {/* Lock / Unlock Toggle Switch */}
            <button
              type="button"
              onClick={() => setIsUnlocked(!isUnlocked)}
              className={`px-2.5 py-1 rounded-lg text-[11px] font-bold flex items-center gap-1.5 transition ${
                isUnlocked
                  ? 'bg-amber-100 text-amber-900 border border-amber-300 shadow-sm'
                  : 'bg-slate-100 text-slate-600 border border-slate-200 hover:bg-slate-200'
              }`}
            >
              {isUnlocked ? <Unlock className="w-3.5 h-3.5 text-amber-600" /> : <Lock className="w-3.5 h-3.5 text-slate-500" />}
              <span>{isUnlocked ? 'Unlocked (Interactive)' : 'Locked'}</span>
            </button>
          </div>

          <div className="bg-slate-950 rounded-xl border border-slate-800 p-2 overflow-hidden flex flex-col items-center justify-center min-h-[320px] max-w-[340px] mx-auto relative group">
            {status.frame_url || status.screenshot ? (
              <div className="relative w-full aspect-[360/640] flex items-center justify-center">
                <img
                  src={status.frame_url || status.screenshot}
                  alt="Live Preview"
                  onClick={handlePreviewClick}
                  className={`w-full h-full object-contain rounded-lg shadow-md ${
                    isUnlocked ? 'cursor-crosshair ring-2 ring-amber-400/50' : 'cursor-default'
                  }`}
                />
                {/* Visual Click Indicator Ripple */}
                {clickRipple && (
                  <span
                    key={clickRipple.id}
                    style={{ left: clickRipple.x - 12, top: clickRipple.y - 12 }}
                    className="absolute w-6 h-6 rounded-full bg-amber-400/80 animate-ping pointer-events-none"
                  />
                )}
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center py-16 text-slate-500 gap-2">
                <RefreshCw className="w-6 h-6 text-indigo-500 animate-spin" />
                <span className="text-xs font-mono text-slate-400">Capturing live preview...</span>
              </div>
            )}
          </div>

          <p className="text-[11px] text-slate-400 font-normal text-center mt-1.5">
            Last update received: {formatRelativeTime(lastSseTime)}
          </p>
        </div>

        {/* MFA Verification Code Form */}
        {status.status === 'mfa_required' && (
          <form
            onSubmit={async (e) => {
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
              } catch (err: any) {
                setMfaError(err.message || 'Failed to submit code.');
              } finally {
                setMfaSubmitting(false);
              }
            }}
            className="p-5 bg-amber-50 border border-amber-200 rounded-2xl space-y-4 shadow-sm"
          >
            <div className="flex items-start gap-3">
              <div className="w-9 h-9 rounded-xl bg-amber-100 border border-amber-200 flex items-center justify-center text-amber-700 shrink-0 mt-0.5">
                <ShieldCheck className="w-5 h-5" />
              </div>
              <div className="space-y-1">
                <h4 className="text-sm font-bold text-amber-950">Email Verification Code Required</h4>
                <p className="text-xs text-amber-800 leading-relaxed">
                  Bright Horizons sent a 6-digit security verification code to <span className="font-semibold">{email}</span>. Please enter it below to complete authentication.
                </p>
              </div>
            </div>

            <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3 pt-1">
              <input
                type="text"
                inputMode="numeric"
                pattern="[0-9]*"
                maxLength={6}
                autoFocus
                placeholder="123456"
                value={mfaCode}
                onChange={(e) => {
                  const val = e.target.value.replace(/\D/g, '').slice(0, 6);
                  setMfaCode(val);
                  setMfaError(null);
                }}
                className="px-4 py-2.5 bg-white border border-amber-300 rounded-xl text-center text-lg font-mono tracking-widest text-slate-900 focus:outline-none focus:ring-2 focus:ring-amber-500 font-bold sm:w-48"
              />

              <button
                type="submit"
                disabled={mfaSubmitting || mfaCode.length !== 6}
                className="px-5 py-2.5 bg-amber-600 hover:bg-amber-700 disabled:opacity-50 text-white text-xs font-bold rounded-xl transition shadow-sm flex items-center justify-center gap-2"
              >
                {mfaSubmitting ? <RefreshCw className="w-4 h-4 animate-spin" /> : null}
                <span>Verify & Continue</span>
              </button>
            </div>

            {mfaError && <p className="text-xs font-semibold text-rose-600 mt-1">{mfaError}</p>}
          </form>
        )}

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
