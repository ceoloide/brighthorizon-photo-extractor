import React, { useState, useEffect } from 'react';
import { Image as ImageIcon, Video, Calendar, Download, Eye, X, Filter } from 'lucide-react';

interface MediaItem {
  media_id: string;
  child: string;
  date: string;
  original_filename: string;
  comment: string;
  mime_type: string;
  file_size: number;
}

interface GalleryProps {
  token: string;
  refreshTrigger: number;
}

export const Gallery: React.FC<GalleryProps> = ({ token, refreshTrigger }) => {
  const [mediaList, setMediaList] = useState<MediaItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [selectedChild, setSelectedChild] = useState<string>('all');
  const [activeItem, setActiveItem] = useState<MediaItem | null>(null);

  const fetchMedia = async (isInitial: boolean = false) => {
    if (isInitial) setLoading(true);
    try {
      const res = await fetch('/api/media', {
        headers: { Authorization: `Bearer ${token}` }
      });
      const data = await res.json();
      if (res.ok && data.media) {
        setMediaList(data.media);
      }
    } catch (err) {
      console.error('Failed to fetch media:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchMedia(mediaList.length === 0);
  }, [refreshTrigger, token]);

  const childrenOptions = Array.from(new Set(mediaList.map((m) => m.child)));
  const filteredList = mediaList.filter(
    (m) => selectedChild === 'all' || m.child.toLowerCase() === selectedChild.toLowerCase()
  );

  return (
    <div className="space-y-4 font-sans">
      {/* Header & Filter Controls */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-4 sm:p-5 bg-white rounded-2xl border border-slate-200 shadow-sm">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-xl bg-indigo-50 border border-indigo-100 text-indigo-600 shrink-0">
            <ImageIcon className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-sm sm:text-base font-bold text-slate-900 flex items-center gap-2">
              <span>Extracted Media Library</span>
              <span className="text-xs bg-indigo-50 text-indigo-700 border border-indigo-100 px-2 py-0.5 rounded-full font-mono font-semibold">
                {filteredList.length}
              </span>
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">High-resolution photos & videos saved from daily updates</p>
          </div>
        </div>

        {childrenOptions.length > 0 && (
          <div className="flex items-center gap-2 overflow-x-auto pb-1 sm:pb-0 w-full sm:w-auto">
            <Filter className="w-3.5 h-3.5 text-slate-400 shrink-0" />
            <div className="flex items-center gap-1 bg-slate-100 border border-slate-200 rounded-xl p-1 text-xs shrink-0">
              <button
                type="button"
                onClick={() => setSelectedChild('all')}
                className={`px-3 py-1.5 sm:py-1 rounded-lg transition whitespace-nowrap ${
                  selectedChild === 'all'
                    ? 'bg-white text-indigo-700 font-semibold border border-slate-200 shadow-sm'
                    : 'text-slate-500 hover:text-slate-800'
                }`}
              >
                All Children
              </button>
              {childrenOptions.map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={() => setSelectedChild(c)}
                  className={`px-3 py-1.5 sm:py-1 rounded-lg transition whitespace-nowrap ${
                    selectedChild.toLowerCase() === c.toLowerCase()
                      ? 'bg-white text-indigo-700 font-semibold border border-slate-200 shadow-sm'
                      : 'text-slate-500 hover:text-slate-800'
                  }`}
                >
                  {c}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Grid Display */}
      {loading ? (
        <div className="flex flex-col justify-center items-center py-16 sm:py-20 text-slate-500 gap-3 bg-white rounded-2xl border border-slate-200 shadow-sm">
          <div className="w-7 h-7 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin" />
          <span className="text-xs font-medium text-slate-600">Loading photo gallery...</span>
        </div>
      ) : filteredList.length === 0 ? (
        <div className="text-center py-16 sm:py-20 bg-white rounded-2xl border border-dashed border-slate-200 text-slate-400 p-4 shadow-sm">
          <ImageIcon className="w-10 h-10 mx-auto mb-3 text-slate-300" />
          <p className="font-semibold text-slate-700 text-sm">No media downloaded yet</p>
          <p className="text-xs text-slate-400 mt-1 max-w-sm mx-auto">Start an extraction job above to populate photos and videos.</p>
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-2.5 sm:gap-4">
          {filteredList.map((item) => {
            const isVideo = item.mime_type.includes('video') || item.original_filename.endsWith('.mp4') || item.original_filename.endsWith('.mov');
            const mediaUrl = `/api/media/${item.media_id}?token=${token}`;

            return (
              <div
                key={item.media_id}
                onClick={() => setActiveItem(item)}
                className="group relative bg-white rounded-2xl overflow-hidden border border-slate-200 hover:border-indigo-400 transition-all duration-200 cursor-pointer shadow-sm hover:shadow-md flex flex-col active:scale-[0.98]"
              >
                <div className="aspect-square bg-slate-900 relative overflow-hidden flex items-center justify-center">
                  {isVideo ? (
                    <>
                      <video
                        src={`${mediaUrl}#t=0.5`}
                        preload="metadata"
                        muted
                        playsInline
                        className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-200"
                      />
                      <div className="absolute top-2 right-2 z-10">
                        <span className="text-[9px] sm:text-[10px] font-mono font-bold uppercase bg-slate-900/80 backdrop-blur-xs text-indigo-300 border border-indigo-500/30 px-2 py-0.5 rounded-full shadow-xs flex items-center gap-1">
                          <Video className="w-3 h-3 text-indigo-400" />
                          VIDEO
                        </span>
                      </div>
                    </>
                  ) : (
                    <img
                      src={mediaUrl}
                      alt={item.original_filename}
                      loading="lazy"
                      className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-200"
                    />
                  )}
                  <div className="absolute inset-0 bg-slate-900/30 opacity-0 group-hover:opacity-100 transition-opacity duration-200 flex items-center justify-center">
                    <Eye className="w-6 h-6 text-white" />
                  </div>
                </div>

                <div className="p-2.5 sm:p-3 text-xs space-y-0.5 sm:space-y-1 bg-white border-t border-slate-100">
                  <div className="flex justify-between items-center text-slate-800 font-semibold truncate">
                    <span className="truncate">{item.child}</span>
                    <span className="text-[10px] font-normal text-slate-500 flex items-center gap-1 font-mono shrink-0 ml-1">
                      <Calendar className="w-3 h-3 text-slate-400" />
                      {item.date}
                    </span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Fullscreen Preview Lightbox Modal */}
      {activeItem && (
        <div className="fixed inset-0 z-50 bg-slate-900/80 backdrop-blur-xs flex items-center justify-center p-2 sm:p-4">
          <div className="relative max-w-4xl w-full bg-white border border-slate-200 rounded-2xl overflow-hidden shadow-2xl flex flex-col max-h-[92vh]">
            <div className="flex items-center justify-between p-3.5 sm:p-4 border-b border-slate-100 bg-white">
              <div className="min-w-0 pr-2">
                <h3 className="font-bold text-slate-900 text-xs sm:text-sm truncate">{activeItem.original_filename}</h3>
                <p className="text-[11px] text-slate-500 mt-0.5">{activeItem.child} • {activeItem.date}</p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <a
                  href={`/api/media/${activeItem.media_id}?token=${token}`}
                  download={activeItem.original_filename}
                  className="p-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-xl transition border border-slate-200 min-w-[40px] min-h-[40px] flex items-center justify-center"
                  title="Download File"
                >
                  <Download className="w-4 h-4 text-indigo-600" />
                </a>
                <button
                  onClick={() => setActiveItem(null)}
                  className="p-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-xl transition border border-slate-200 min-w-[40px] min-h-[40px] flex items-center justify-center"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>

            <div className="p-2 sm:p-4 flex-1 flex items-center justify-center overflow-auto bg-slate-950 min-h-[250px]">
              {activeItem.mime_type.includes('video') || activeItem.original_filename.endsWith('.mp4') || activeItem.original_filename.endsWith('.mov') ? (
                <video
                  src={`/api/media/${activeItem.media_id}?token=${token}`}
                  controls
                  autoPlay
                  className="max-h-[65vh] w-full object-contain rounded-xl"
                />
              ) : (
                <img
                  src={`/api/media/${activeItem.media_id}?token=${token}`}
                  alt={activeItem.original_filename}
                  className="max-h-[65vh] w-auto max-w-full object-contain rounded-xl"
                />
              )}
            </div>

            {activeItem.comment && (
              <div className="p-3.5 sm:p-4 bg-white border-t border-slate-100 text-xs text-slate-700 max-h-32 overflow-y-auto">
                <p className="font-semibold text-slate-500 mb-1 uppercase tracking-wider text-[10px]">Caption / Comment</p>
                <p className="leading-relaxed">{activeItem.comment}</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
