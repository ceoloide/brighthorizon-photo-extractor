import React, { useState } from 'react';
import { Lock, Mail, ShieldAlert, ShieldCheck, Sparkles, Camera } from 'lucide-react';

interface LoginFormProps {
  onLoginSuccess: (token: string, user: any) => void;
}

export const LoginForm: React.FC<LoginFormProps> = ({ onLoginSuccess }) => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !password) {
      setError('Please enter your email and password.');
      return;
    }
    setLoading(true);
    setError(null);

    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || 'Login failed. Please check your credentials.');
      }

      localStorage.setItem('bh_token', data.token);
      localStorage.setItem('bh_email', data.email);
      onLoginSuccess(data.token, data);
    } catch (err: any) {
      setError(err.message || 'An unexpected authentication error occurred.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col justify-center items-center p-4 relative overflow-hidden bg-[#0b0f17]">
      {/* Subtle Background Glow Spheres */}
      <div className="absolute top-1/4 -left-20 w-96 h-96 bg-cyan-500/10 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute bottom-1/4 -right-20 w-96 h-96 bg-blue-600/10 rounded-full blur-3xl pointer-events-none" />

      <div className="max-w-md w-full glass-panel rounded-3xl p-8 shadow-2xl border border-slate-800/80 relative z-10 space-y-6">
        {/* Header Icon & Branding */}
        <div className="text-center space-y-3">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-gradient-to-tr from-cyan-500/20 via-sky-500/20 to-blue-600/20 border border-cyan-500/30 text-cyan-400 shadow-inner mb-1">
            <Camera className="w-7 h-7" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-slate-100 tracking-tight flex items-center justify-center gap-2">
              <span>Bright Horizons</span>
              <Sparkles className="w-4 h-4 text-cyan-400" />
            </h1>
            <p className="text-xs text-slate-400 font-medium mt-1">Photo & Video Extractor</p>
          </div>
        </div>

        {/* Security Badge */}
        <div className="flex items-center justify-center gap-2 px-3 py-1.5 bg-slate-900/60 rounded-full border border-slate-800/80 text-[11px] text-slate-400 font-mono">
          <ShieldCheck className="w-3.5 h-3.5 text-cyan-400" />
          <span>AES-256 Encrypted Multi-Tenant Storage</span>
        </div>

        {error && (
          <div className="p-3.5 bg-rose-500/10 border border-rose-500/20 rounded-2xl flex items-start gap-3 text-rose-300 text-xs leading-relaxed animate-fade-in">
            <ShieldAlert className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider">
              Bright Horizons Email
            </label>
            <div className="relative group">
              <Mail className="absolute left-3.5 top-3 w-4 h-4 text-slate-500 group-focus-within:text-cyan-400 transition-colors" />
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="parent@example.com"
                className="w-full pl-10 pr-4 py-2.5 bg-slate-900/80 border border-slate-800 rounded-xl focus:ring-2 focus:ring-cyan-500/50 focus:border-cyan-500/50 outline-none text-slate-100 placeholder-slate-600 text-sm transition-all"
                required
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider">
              Password
            </label>
            <div className="relative group">
              <Lock className="absolute left-3.5 top-3 w-4 h-4 text-slate-500 group-focus-within:text-cyan-400 transition-colors" />
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••••••"
                className="w-full pl-10 pr-4 py-2.5 bg-slate-900/80 border border-slate-800 rounded-xl focus:ring-2 focus:ring-cyan-500/50 focus:border-cyan-500/50 outline-none text-slate-100 placeholder-slate-600 text-sm transition-all"
                required
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full mt-2 py-3 bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-white font-semibold rounded-xl transition-all duration-200 shadow-lg shadow-cyan-500/25 active:scale-[0.99] disabled:opacity-50 flex justify-center items-center gap-2 text-sm"
          >
            {loading ? (
              <>
                <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                <span>Authenticating Session...</span>
              </>
            ) : (
              <span>Sign In to Extractor</span>
            )}
          </button>
        </form>

        <div className="pt-2 text-center">
          <p className="text-[11px] text-slate-500">
            Headless browser session with Cloudflare FlareSolverr support.
          </p>
        </div>
      </div>
    </div>
  );
};
