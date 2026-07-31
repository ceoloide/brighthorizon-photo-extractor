import React, { useState, useEffect } from 'react';
import { ExternalLink, Copy, Check, ShieldCheck, AlertCircle, Laptop, ArrowRight, Lock, Camera, Mail } from 'lucide-react';

interface DesktopSessionStepperProps {
  onSuccess: (email: string, children?: any[], token?: string) => void;
}

export const DesktopSessionStepper: React.FC<DesktopSessionStepperProps> = ({ onSuccess }) => {
  const [step, setStep] = useState<number>(1);
  const [email, setEmail] = useState<string>('');
  const [copied, setCopied] = useState<boolean>(false);
  const [rawPayload, setRawPayload] = useState<string>('');
  const [validationError, setValidationError] = useState<string | null>(null);
  const [validationSuccess, setValidationSuccess] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [parsedPayload, setParsedPayload] = useState<any>(null);
  const [showSnippetCode, setShowSnippetCode] = useState<boolean>(false);

  const snippetCode = `javascript:(function(){var d={cookies:document.cookie,storage:JSON.stringify(localStorage)},s=JSON.stringify(d),o=document.getElementById("bh-session-overlay");if(o)o.remove();var b=document.createElement("div");b.id="bh-session-overlay";b.style.cssText="position:fixed;top:20px;right:20px;z-index:999999;width:420px;background:#1e293b;color:#fff;padding:16px;border-radius:12px;box-shadow:0 20px 25px -5px rgba(0,0,0,0.5);font-family:sans-serif;font-size:13px;";b.innerHTML='<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;"><b style="color:#818cf8;">Bright Horizons Session Payload</b><button id="bh-close-btn" style="background:none;border:none;color:#94a3b8;cursor:pointer;font-size:16px;">✕</button></div><p style="margin:0 0 10px 0;font-size:11px;color:#cbd5e1;">Click below to copy your full session payload:</p><textarea id="bh-ta-payload" style="width:100%;height:140px;background:#0f172a;color:#fde047;border:1px solid #334155;border-radius:6px;padding:8px;font-family:monospace;font-size:10px;resize:none;" readonly></textarea><button id="bh-copy-btn" style="width:100%;margin-top:10px;padding:8px;background:#4f46e5;color:#fff;border:none;border-radius:6px;font-weight:bold;cursor:pointer;">📋 Copy Session Payload</button>';document.body.appendChild(b);var t=document.getElementById("bh-ta-payload");t.value=s;t.select();document.getElementById("bh-close-btn").onclick=function(){b.remove();};document.getElementById("bh-copy-btn").onclick=function(){t.select();document.execCommand("copy");this.innerText="✓ Copied to Clipboard!";this.style.background="#10b981";};})();`;

  const handleCopySnippet = () => {
    navigator.clipboard.writeText(snippetCode);
    setCopied(true);
    setTimeout(() => setCopied(false), 3000);
  };

  const validateLocalPayload = (input: string) => {
    setRawPayload(input);
    setValidationError(null);
    setValidationSuccess(null);
    setParsedPayload(null);

    const trimmed = input.trim();
    if (!trimmed) return;

    try {
      const data = JSON.parse(trimmed);
      if (!data || typeof data !== 'object') {
        setValidationError('Invalid payload: Must be a JSON object containing cookies or storage.');
        return;
      }

      if (!data.cookies && !data.storage) {
        setValidationError('Invalid payload: Missing cookies or storage attributes.');
        return;
      }

      let cookieCount = 0;
      if (typeof data.cookies === 'string') {
        cookieCount = data.cookies.split(';').filter((c: string) => c.trim().length > 0).length;
      }

      setParsedPayload(data);
      setValidationSuccess(`✓ Valid session payload detected! Found ${cookieCount} cookies.`);
    } catch (err: any) {
      setValidationError(`JSON Syntax Error: Please ensure you pasted the exact text from the browser prompt.`);
    }
  };

  const handleSubmitSession = async () => {
    if (!email.trim() || !parsedPayload) return;

    setSubmitting(true);
    setValidationError(null);

    try {
      const resp = await fetch('/api/auth/import-session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: email.trim().toLowerCase(),
          payload: parsedPayload
        })
      });

      const resData = await resp.json();
      if (!resp.ok) {
        throw new Error(resData.detail || 'Failed to import session');
      }

      onSuccess(email.trim(), resData.children || [], resData.token);
    } catch (err: any) {
      setValidationError(err.message || 'Portal authentication failed. Please log in again in your Bright Horizons tab and paste fresh session tokens.');
      setStep(3);
    } finally {
      setSubmitting(false);
    }
  };

  if (submitting) {
    return (
      <div className="min-h-screen bg-slate-50 text-slate-800 flex items-center justify-center p-4 sm:p-6 font-sans">
        <div className="max-w-md w-full bg-white border border-slate-200 rounded-2xl p-6 sm:p-8 shadow-sm text-center space-y-6">
          <div className="flex items-center justify-center space-x-3">
            <div className="w-6 h-6 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin" />
            <h2 className="text-lg font-bold text-slate-900">Connecting Account...</h2>
          </div>
          <p className="text-xs text-slate-500 leading-relaxed">
            Authenticating session tokens with Bright Horizons portal and discovering enrolled children...
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50 text-slate-800 flex items-center justify-center p-4 sm:p-6 font-sans">
      <div className="max-w-2xl w-full bg-white border border-slate-200 rounded-2xl p-6 sm:p-8 shadow-sm space-y-8">
        
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-100 pb-6">
          <div className="flex items-center space-x-3">
            <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-indigo-50 border border-indigo-100 text-indigo-600">
              <Camera className="w-6 h-6" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-slate-900">Bright Horizons Desktop Setup</h1>
              <p className="text-xs text-slate-500">Connect your account securely using native session tokens</p>
            </div>
          </div>
        </div>

        {/* Stepper Progress */}
        <div className="grid grid-cols-3 gap-3">
          <div className={`p-3 rounded-xl border text-xs font-semibold flex items-center space-x-2 transition-all ${step === 1 ? 'bg-indigo-50 border-indigo-200 text-indigo-700 shadow-sm' : step > 1 ? 'bg-emerald-50 border-emerald-200 text-emerald-700' : 'bg-slate-50 border-slate-200 text-slate-400'}`}>
            <span className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] ${step === 1 ? 'bg-indigo-600 text-white' : step > 1 ? 'bg-emerald-600 text-white' : 'bg-slate-200 text-slate-600'}`}>1</span>
            <span>Email</span>
          </div>
          <div className={`p-3 rounded-xl border text-xs font-semibold flex items-center space-x-2 transition-all ${step === 2 ? 'bg-indigo-50 border-indigo-200 text-indigo-700 shadow-sm' : step > 2 ? 'bg-emerald-50 border-emerald-200 text-emerald-700' : 'bg-slate-50 border-slate-200 text-slate-400'}`}>
            <span className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] ${step === 2 ? 'bg-indigo-600 text-white' : step > 2 ? 'bg-emerald-600 text-white' : 'bg-slate-200 text-slate-600'}`}>2</span>
            <span>External Login</span>
          </div>
          <div className={`p-3 rounded-xl border text-xs font-semibold flex items-center space-x-2 transition-all ${step === 3 ? 'bg-indigo-50 border-indigo-200 text-indigo-700 shadow-sm' : 'bg-slate-50 border-slate-200 text-slate-400'}`}>
            <span className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] ${step === 3 ? 'bg-indigo-600 text-white' : 'bg-slate-200 text-slate-600'}`}>3</span>
            <span>Import Session</span>
          </div>
        </div>

        {/* Step 1: Email Input */}
        {step === 1 && (
          <div className="space-y-6">
            <div className="space-y-2">
              <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider">
                Bright Horizons Email
              </label>
              <div className="relative">
                <Mail className="absolute left-3.5 top-3.5 w-4 h-4 text-slate-400" />
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="parent@example.com"
                  className="w-full pl-10 pr-4 py-3 bg-white border border-slate-300 rounded-xl focus:border-indigo-600 focus:ring-1 focus:ring-indigo-600 outline-none text-slate-900 placeholder-slate-400 text-sm transition"
                  required
                />
              </div>
              <p className="text-xs text-slate-500">Enter the email associated with your Bright Horizons parent portal account.</p>
            </div>
            <button
              disabled={!email.trim() || !email.includes('@')}
              onClick={() => setStep(2)}
              className="w-full py-3.5 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 text-white font-medium rounded-xl transition flex justify-center items-center gap-2 text-sm shadow-sm active:scale-[0.99]"
            >
              <span>Continue to Login Step</span>
              <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        )}

        {/* Step 2: External Login Prompt */}
        {step === 2 && (
          <div className="space-y-6">
            <div className="bg-slate-50 border border-slate-200 rounded-xl p-6 space-y-4">
              <div className="flex items-start space-x-3">
                <div className="p-2 bg-indigo-100 text-indigo-600 rounded-lg mt-0.5">
                  <ExternalLink className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-slate-900">Log In on Bright Horizons Portal</h3>
                  <p className="text-xs text-slate-600 leading-relaxed mt-1">
                    Click the button below to open Bright Horizons in a new tab. Log in with your email, password, and security code in that tab.
                  </p>
                </div>
              </div>

              <a
                href="https://familyinfocenter.brighthorizons.com/home"
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center justify-center space-x-2 w-full bg-white hover:bg-slate-100 text-indigo-700 border border-indigo-200 font-semibold py-3 px-4 rounded-xl text-sm transition-colors shadow-sm"
              >
                <span>Open Family Information Center Portal</span>
                <ExternalLink className="w-4 h-4" />
              </a>
            </div>

            <div className="flex items-center justify-between pt-2">
              <button
                onClick={() => setStep(1)}
                className="text-xs text-slate-500 hover:text-slate-800 font-medium"
              >
                Back
              </button>
              <button
                onClick={() => setStep(3)}
                className="py-3 px-6 bg-indigo-600 hover:bg-indigo-700 text-white font-medium rounded-xl transition flex justify-center items-center gap-2 text-sm shadow-sm"
              >
                <span>I Have Logged In →</span>
              </button>
            </div>
          </div>
        )}

        {/* Step 3: Address Bar Snippet & Import */}
        {step === 3 && (
          <div className="space-y-6">
            <div className="bg-slate-50 border border-slate-200 rounded-xl p-6 space-y-4">
              <h3 className="text-sm font-semibold text-slate-900">1. Copy Session Extraction Code</h3>
              <p className="text-xs text-slate-600 leading-relaxed">
                Click <strong>Copy Code</strong> below. Switch to your open Bright Horizons tab (<code className="font-mono text-indigo-700 bg-indigo-50 px-1 py-0.5 rounded">familyinfocenter.brighthorizons.com</code>), click the address bar, type <span className="font-mono text-indigo-700 bg-indigo-50 border border-indigo-100 px-1.5 py-0.5 rounded font-semibold">javascript:</span> into the address bar, paste the code directly after it, and press <strong>Enter</strong>.
              </p>

              <div className="relative bg-slate-900 border border-slate-800 rounded-xl p-3.5 font-mono text-xs">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <span className="text-[10px] font-bold tracking-wider uppercase text-slate-400">SESSION EXTRACTION SNIPPET</span>
                    <button
                      type="button"
                      onClick={() => setShowSnippetCode(!showSnippetCode)}
                      className="text-xs text-indigo-400 hover:text-indigo-300 font-sans font-medium transition"
                    >
                      {showSnippetCode ? 'Hide Code ▲' : 'Show Code ▼'}
                    </button>
                  </div>
                  <button
                    type="button"
                    onClick={handleCopySnippet}
                    className="flex items-center space-x-1.5 text-indigo-200 hover:text-white bg-indigo-600/40 hover:bg-indigo-600/70 border border-indigo-500/40 px-3 py-1.5 rounded-lg transition-colors font-sans text-xs font-semibold shadow-2xs"
                  >
                    {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                    <span>{copied ? 'Copied to Clipboard!' : 'Copy Code'}</span>
                  </button>
                </div>

                {showSnippetCode && (
                  <div className="mt-3 pt-3 border-t border-slate-800 space-y-2">
                    <p className="text-[11px] text-slate-400 font-sans leading-relaxed">
                      💡 <strong>Why type <code className="text-amber-300 font-mono">javascript:</code> manually?</strong> Browsers automatically strip the leading <code className="text-amber-300 font-mono">javascript:</code> prefix when pasting into address bars. Typing <code className="text-amber-300 font-mono">javascript:</code> first ensures the code executes as a bookmarklet.
                    </p>
                    <p className="text-amber-300 text-[10px] break-all select-all font-mono bg-slate-950 p-3 rounded-lg border border-slate-800 max-h-36 overflow-y-auto leading-relaxed">
                      {snippetCode}
                    </p>
                  </div>
                )}
              </div>
            </div>

            <div className="space-y-2">
              <h3 className="text-sm font-semibold text-slate-900">2. Paste Output & Validate</h3>
              <textarea
                rows={4}
                value={rawPayload}
                onChange={(e) => validateLocalPayload(e.target.value)}
                placeholder='Paste the output here e.g. {"cookies":"...","storage":"..."}'
                className="w-full bg-white border border-slate-300 rounded-xl p-4 text-xs font-mono text-slate-900 placeholder-slate-400 focus:border-indigo-600 focus:ring-1 focus:ring-indigo-600 outline-none transition"
              />

              {validationError && (
                <div className="flex items-center space-x-2 text-xs text-rose-700 bg-rose-50 border border-rose-200 p-3.5 rounded-xl">
                  <AlertCircle className="w-4 h-4 shrink-0 text-rose-500" />
                  <span>{validationError}</span>
                </div>
              )}

              {validationSuccess && (
                <div className="flex items-center space-x-2 text-xs text-emerald-700 bg-emerald-50 border border-emerald-200 p-3.5 rounded-xl font-medium">
                  <ShieldCheck className="w-4 h-4 shrink-0 text-emerald-600" />
                  <span>{validationSuccess}</span>
                </div>
              )}
            </div>

            <div className="flex items-center justify-between pt-2">
              <button
                onClick={() => setStep(2)}
                className="text-xs text-slate-500 hover:text-slate-800 font-medium"
              >
                Back
              </button>
              <button
                disabled={!parsedPayload || submitting}
                onClick={handleSubmitSession}
                className="py-3 px-6 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 text-white font-medium rounded-xl transition flex justify-center items-center gap-2 text-sm shadow-sm"
              >
                <span>Connect Account</span>
                <ShieldCheck className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}

      </div>
    </div>
  );
};
