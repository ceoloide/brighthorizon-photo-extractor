import React, { useState } from 'react';
import { Lock, Mail, ShieldAlert, Heart, Camera } from 'lucide-react';
import { VerificationInterstitial } from './VerificationInterstitial';

interface LoginFormProps {
  onLoginSuccess: (token: string, user: any) => void;
}

export const LoginForm: React.FC<LoginFormProps> = ({ onLoginSuccess }) => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [verifying, setVerifying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !password) {
      setError('Please enter both email and password.');
      return;
    }
    setError(null);
    setVerifying(true);
  };

  if (verifying) {
    return (
      <VerificationInterstitial
        email={email}
        password={password}
        onSuccess={(token, data) => {
          onLoginSuccess(token, { ...data, email: data?.email || email });
        }}
        onCancel={() => {
          setVerifying(false);
        }}
      />
    );
  }

  return (
    <div className="min-h-screen flex flex-col justify-center items-center p-4 sm:p-6 bg-slate-50 font-sans">
      <div className="max-w-md w-full bg-white rounded-2xl p-5 sm:p-8 border border-slate-200 shadow-sm space-y-6">
        {/* Header */}
        <div className="text-center space-y-2">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-indigo-50 border border-indigo-100 text-indigo-600 mb-1">
            <Camera className="w-6 h-6" />
          </div>
          <h1 className="text-lg sm:text-xl font-bold text-slate-900">Bright Horizons Extractor</h1>
          <p className="text-xs text-slate-500">Download and archive your children's photos & videos</p>
        </div>

        {error && (
          <div className="p-3.5 bg-rose-50 border border-rose-200 rounded-xl flex items-start gap-3 text-rose-700 text-xs">
            <ShieldAlert className="w-4 h-4 text-rose-500 shrink-0 mt-0.5" />
            <span className="leading-relaxed">{error}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
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
          </div>

          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider">
              Password
            </label>
            <div className="relative">
              <Lock className="absolute left-3.5 top-3.5 w-4 h-4 text-slate-400" />
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••••••"
                className="w-full pl-10 pr-4 py-3 bg-white border border-slate-300 rounded-xl focus:border-indigo-600 focus:ring-1 focus:ring-indigo-600 outline-none text-slate-900 placeholder-slate-400 text-sm transition"
                required
              />
            </div>
          </div>

          <button
            type="submit"
            className="w-full py-3 bg-indigo-600 hover:bg-indigo-700 text-white font-medium rounded-xl transition flex justify-center items-center gap-2 text-sm shadow-sm active:scale-[0.99]"
          >
            <span>Sign In & Verify Account</span>
          </button>
        </form>

        <div className="pt-2 text-center border-t border-slate-100 flex items-center justify-center gap-1.5 text-[11px] text-slate-400">
          <Heart className="w-3 h-3 text-rose-400 fill-rose-400" />
          <span>Keep your child's memories safe & backed up</span>
        </div>
      </div>
    </div>
  );
};
