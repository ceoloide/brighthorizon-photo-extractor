import React from 'react';
import { Share2, X, Loader2 } from 'lucide-react';

interface ShareProgressModalProps {
  isOpen: boolean;
  title: string;
  total: number;
  current: number;
  onCancel: () => void;
}

export const ShareProgressModal: React.FC<ShareProgressModalProps> = ({
  isOpen,
  title,
  total,
  current,
  onCancel,
}) => {
  if (!isOpen) return null;

  const percentage = total > 0 ? Math.min(100, Math.round((current / total) * 100)) : 0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-xs animate-in fade-in duration-200">
      <div className="bg-white rounded-2xl border border-slate-200 p-5 max-w-sm w-full shadow-2xl space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-xl bg-indigo-50 border border-indigo-100 text-indigo-600">
              <Share2 className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-bold text-slate-900 text-sm">Preparing iOS Share</h3>
              <p className="text-xs text-slate-500 truncate max-w-[200px]">{title}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onCancel}
            className="p-1.5 text-slate-400 hover:text-slate-600 rounded-lg hover:bg-slate-100 transition"
            title="Cancel Share"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="space-y-2">
          <div className="flex justify-between text-xs font-semibold">
            <span className="text-slate-600 flex items-center gap-1.5">
              <Loader2 className="w-3.5 h-3.5 text-indigo-600 animate-spin" />
              <span>Gathering files...</span>
            </span>
            <span className="font-mono text-indigo-600">
              {current} of {total} ({percentage}%)
            </span>
          </div>

          {/* Progress Bar */}
          <div className="w-full bg-slate-100 h-2.5 rounded-full overflow-hidden border border-slate-200">
            <div
              className="bg-indigo-600 h-full transition-all duration-200 rounded-full"
              style={{ width: `${percentage}%` }}
            />
          </div>
        </div>

        <p className="text-[11px] text-slate-400 text-center">
          Building image bundle for native iOS Share Sheet...
        </p>
      </div>
    </div>
  );
};
