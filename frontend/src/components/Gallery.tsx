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

  const fetchMedia = async () => {
    setLoading(true);
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
    fetchMedia();
  }, [refreshTrigger, token]);

  const childrenOptions = Array.from(new Set(mediaList.map((m) => m.child)));
  const filteredList = mediaList.filter(
    (m) => selectedChild === 'all' || m.child.toLowerCase() === selectedChild.toLowerCase()
  );

  return (
    <div className="space-y-4 font-sans">
      {/* Header & Filter Controls */}
      <div className="flex flex-wrap items-center justify-between gap-4 p-4 bg-slate-800 rounded-xl border border-slate-700 shadow-sm">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-blue-600/10 border border-blue-500/20 text-blue-400">
            <ImageIcon className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-base font-bold text-slate-100 flex items-center gap-2">
              <span>Extracted Media Library</span>
              <span className="text-xs bg-slate-900 text-slate-300 border border-slate-700 px-2.5 py-0.5 rounded font-mono">
                {filteredList.length} items
              </span>
            </h2>
            <p className="text-xs text-slate-400 mt-0.5">Photos and videos downloaded from portal</p>
          </div>
        </div>

        {childrenOptions.length > 0 && (
          <div className="flex items-center gap-2">
            <Filter className="w-3.5 h-3.5 text-slate-400" />
            <div className="flex items-center gap-1 bg-slate-900 border border-slate-700 rounded-lg p-1 text-xs">
              <button
                type="button"
                onClick={() => setSelectedChild('all')}
                className={`px-3 py-1 rounded transition ${
                  selectedChild === 'all'
                    ? 'bg-slate-700 text-slate-100 font-semibold border border-slate-600'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                All
              </button>
              {childrenOptions.map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={() => setSelectedChild(c)}
                  className={`px-3 py-1 rounded transition ${
                    selectedChild.toLowerCase() === c.toLowerCase()
                      ? 'bg-slate-700 text-slate-100 font-semibold border border-slate-600'
                      : 'text-slate-400 hover:text-slate-200'
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
        <div className="flex flex-col justify-center items-center py-20 text-slate-400 gap-3 bg-slate-800 rounded-xl border border-slate-700">
          <div className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
          <span className="text-xs font-mono">Loading media assets...</span>
        </div>
      ) : filteredList.length === 0 ? (
        <div className="text-center py-20 bg-slate-800 rounded-xl border border-dashed border-slate-700 text-slate-400">
          <ImageIcon className="w-10 h-10 mx-auto mb-3 text-slate-600" />
          <p className="font-semibold text-slate-200 text-sm">No media downloaded yet</p>
          <p className="text-xs text-slate-500 mt-1">Start an extraction job above to fetch photos and videos.</p>
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4">
          {filteredList.map((item) => {
            const isVideo = item.mime_type.includes('video') || item.original_filename.endsWith('.mp4') || item.original_filename.endsWith('.mov');
            const mediaUrl = `/api/media/${item.media_id}?token=${token}`;

            return (
              <div
                key={item.media_id}
                onClick={() => setActiveItem(item)}
                className="group relative bg-slate-800 rounded-lg overflow-hidden border border-slate-700 hover:border-slate-500 transition cursor-pointer shadow-sm flex flex-col"
              >
                <div className="aspect-square bg-slate-950 relative overflow-hidden flex items-center justify-center">
                  {isVideo ? (
                    <div className="w-full h-full flex flex-col items-center justify-center bg-slate-950 text-blue-400">
                      <Video className="w-10 h-10 mb-1 opacity-80" />
                      <span className="text-[10px] font-mono font-bold uppercase bg-slate-800 text-slate-300 border border-slate-700 px-2 py-0.5 rounded">
                        VIDEO
                      </span>
                    </div>
                  ) : (
                    <img
                      src={mediaUrl}
                      alt={item.original_filename}
                      loading="lazy"
                      className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-200"
                    />
                  )}
                  <div className="absolute inset-0 bg-slate-950/40 opacity-0 group-hover:opacity-100 transition-opacity duration-200 flex items-center justify-center">
                    <Eye className="w-6 h-6 text-white" />
                  </div>
                </div>

                <div className="p-2.5 text-xs space-y-1 bg-slate-800">
                  <div className="flex justify-between items-center text-slate-200 font-semibold truncate">
                    <span>{item.child}</span>
                    <span className="text-[10px] font-normal text-slate-400 flex items-center gap-1 font-mono">
                      <Calendar className="w-3 h-3 text-slate-500" />
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
        <div className="fixed inset-0 z-50 bg-slate-950/80 flex items-center justify-center p-4">
          <div className="relative max-w-4xl w-full bg-slate-900 border border-slate-700 rounded-xl overflow-hidden shadow-2xl flex flex-col max-h-[90vh]">
            <div className="flex items-center justify-between p-4 border-b border-slate-800 bg-slate-900">
              <div>
                <h3 className="font-bold text-slate-100 text-sm truncate">{activeItem.original_filename}</h3>
                <p className="text-xs text-slate-400 mt-0.5">{activeItem.child} • {activeItem.date}</p>
              </div>
              <div className="flex items-center gap-2">
                <a
                  href={`/api/media/${activeItem.media_id}?token=${token}`}
                  download={activeItem.original_filename}
                  className="p-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg transition border border-slate-700"
                  title="Download File"
                >
                  <Download className="w-4 h-4 text-blue-400" />
                </a>
                <button
                  onClick={() => setActiveItem(null)}
                  className="p-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg transition border border-slate-700"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>

            <div className="p-4 flex-1 flex items-center justify-center overflow-auto bg-black">
              {activeItem.mime_type.includes('video') || activeItem.original_filename.endsWith('.mp4') || activeItem.original_filename.endsWith('.mov') ? (
                <video
                  src={`/api/media/${activeItem.media_id}?token=${token}`}
                  controls
                  autoPlay
                  className="max-h-[70vh] w-auto rounded-lg"
                />
              ) : (
                <img
                  src={`/api/media/${activeItem.media_id}?token=${token}`}
                  alt={activeItem.original_filename}
                  className="max-h-[70vh] w-auto object-contain rounded-lg"
                />
              )}
            </div>

            {activeItem.comment && (
              <div className="p-4 bg-slate-900 border-t border-slate-800 text-xs text-slate-300">
                <p className="font-semibold text-slate-400 mb-1 uppercase tracking-wider text-[10px]">Caption / Comment</p>
                <p className="leading-relaxed">{activeItem.comment}</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
