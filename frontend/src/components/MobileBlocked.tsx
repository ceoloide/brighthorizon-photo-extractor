import React from 'react';
import { Monitor, Smartphone, ShieldCheck } from 'lucide-react';

export const MobileBlocked: React.FC = () => {
  return (
    <div className="min-h-screen bg-slate-50 text-slate-800 flex items-center justify-center p-4 font-sans">
      <div className="max-w-md w-full bg-white border border-slate-200 rounded-2xl p-6 sm:p-8 shadow-sm text-center space-y-6">
        <div className="relative inline-flex items-center justify-center w-16 h-16 bg-amber-50 border border-amber-200 rounded-2xl">
          <Smartphone className="w-8 h-8 text-amber-600" />
          <div className="absolute -top-1 -right-1 bg-amber-500 rounded-full p-1 border-2 border-white">
            <span className="block w-2 h-2 rounded-full bg-white animate-pulse" />
          </div>
        </div>

        <div className="space-y-2">
          <h2 className="text-xl font-bold text-slate-900">Desktop Computer Required</h2>
          <p className="text-xs sm:text-sm text-slate-500 leading-relaxed">
            Connecting your Bright Horizons account requires executing a 1-click address bar session snippet on the Bright Horizons login tab, which is only supported on laptop or desktop web browsers.
          </p>
        </div>

        <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 text-left space-y-2">
          <div className="flex items-center space-x-2 text-indigo-600 text-xs font-semibold uppercase tracking-wider">
            <Monitor className="w-4 h-4" />
            <span>How to connect</span>
          </div>
          <p className="text-xs text-slate-600">
            Please open <span className="font-mono text-indigo-600 font-semibold">https://bears.ceoloide.com</span> on your desktop browser.
          </p>
        </div>

        <div className="pt-2 text-xs text-slate-400 flex items-center justify-center space-x-1.5">
          <ShieldCheck className="w-4 h-4 text-slate-400" />
          <span>Multi-tenant encrypted session management</span>
        </div>
      </div>
    </div>
  );
};
