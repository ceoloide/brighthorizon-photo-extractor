import React from 'react';
import versionData from '../version.json';

export const Footer: React.FC = () => {
  const { version, build, gitHash } = versionData;

  return (
    <footer className="w-full py-3 px-4 text-center text-[11px] text-slate-500 font-mono border-t border-slate-200/80 bg-white/70 backdrop-blur-xs select-none mt-auto shrink-0 shadow-2xs">
      <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-1 sm:gap-4">
        <span className="font-semibold text-slate-700">
          Bright Horizons Photo Extractor
        </span>
        <span className="inline-flex items-center gap-1.5 text-slate-500 text-[10px]">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
          <span>Version {version}-b{build}</span>
          <span className="text-slate-400">({gitHash})</span>
        </span>
      </div>
    </footer>
  );
};
