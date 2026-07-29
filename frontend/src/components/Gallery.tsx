import React, { useState, useEffect } from 'react';
import { Image as ImageIcon, Video, Calendar, User, Download, Eye, X } from 'lucide-react';

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
    <div className="space-y-6">
      {/* Header & Filter Controls */}
      <div className="flex flex-wrap items-center justify-between gap-4 p-4 bg-slate-800/80 rounded-2xl border border-slate-700/60">
        <div>
          <h2 className="text-lg font-bold text-slate-100 flex items-center gap-2">
            <ImageIcon className="w-5 h-5 text-sky-400" />
            <span>Extracted Media Library</span>
            <span className="text-xs bg-slate-700 text-slate-300 px-2 py-0.5 rounded-full font-mono">
              {filteredList.length} items
            </span>
          </h2>
        </div>

        {childrenOptions.length > 0 && (
          <div className="flex items-center gap-2">
            <User className="w-4 h-4 text-slate-400" />
            <select
              value={selectedChild}
              onChange={(e) => setSelectedChild(e.target.value)}
              className="bg-slate-900 border border-slate-700 rounded-xl px-3 py-1.5 text-sm text-slate-200 focus:ring-2 focus:ring-sky-500 outline-none"
            >
              <option value="all">All Children</option>
              {childrenOptions.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {/* Grid Display */}
      {loading ? (
        <div className="flex justify-center items-center py-20 text-slate-400 gap-3">
          <div className="w-6 h-6 border-2 border-sky-400 border-t-transparent rounded-full animate-spin" />
          <span>Loading media library...</span>
        </div>
      ) : filteredList.length === 0 ? (
        <div className="text-center py-20 bg-slate-800/40 rounded-2xl border border-dashed border-slate-700 text-slate-400">
          <ImageIcon className="w-12 h-12 mx-auto mb-3 text-slate-600" />
          <p className="font-semibold">No media downloaded yet</p>
          <p className="text-sm text-slate-500 mt-1">Start an extraction process above to populate photos and videos.</p>
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
                className="group relative bg-slate-800 rounded-xl overflow-hidden border border-slate-700/60 hover:border-sky-500/50 transition cursor-pointer shadow-md flex flex-col"
              >
                <div className="aspect-square bg-slate-900 relative overflow-hidden flex items-center justify-center">
                  {isVideo ? (
                    <div className="w-full h-full flex flex-col items-center justify-center bg-slate-950 text-sky-400">
                      <Video className="w-10 h-10 mb-1 opacity-80 group-hover:scale-110 transition" />
                      <span className="text-[10px] font-mono uppercase bg-slate-800 px-1.5 py-0.5 rounded text-slate-300">
                        VIDEO
                      </span>
                    </div>
                  ) : (
                    <img
                      src={mediaUrl}
                      alt={item.original_filename}
                      loading="lazy"
                      className="w-full h-full object-cover group-hover:scale-105 transition duration-300"
                    />
                  )}
                  <div className="absolute inset-0 bg-slate-950/40 opacity-0 group-hover:opacity-100 transition flex items-center justify-center gap-2">
                    <Eye className="w-6 h-6 text-white" />
                  </div>
                </div>

                <div className="p-2.5 text-xs space-y-1">
                  <div className="flex justify-between items-center text-slate-300 font-semibold truncate">
                    <span>{item.child}</span>
                    <span className="text-[10px] font-normal text-slate-400 flex items-center gap-1">
                      <Calendar className="w-3 h-3" />
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
        <div className="fixed inset-0 z-50 bg-slate-950/90 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="relative max-w-4xl w-full bg-slate-900 border border-slate-700 rounded-2xl overflow-hidden shadow-2xl flex flex-col max-h-[90vh]">
            <div className="flex items-center justify-between p-4 border-b border-slate-800">
              <div>
                <h3 className="font-bold text-slate-100 text-sm">{activeItem.original_filename}</h3>
                <p className="text-xs text-slate-400 mt-0.5">{activeItem.child} • {activeItem.date}</p>
              </div>
              <div className="flex items-center gap-2">
                <a
                  href={`/api/media/${activeItem.media_id}?token=${token}`}
                  download={activeItem.original_filename}
                  className="p-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg transition"
                  title="Download File"
                >
                  <Download className="w-4 h-4" />
                </a>
                <button
                  onClick={() => setActiveItem(null)}
                  className="p-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg transition"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>

            <div className="p-4 flex-1 flex items-center justify-center overflow-auto bg-black/60">
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
              <div className="p-3 bg-slate-950/80 border-t border-slate-800 text-xs text-slate-300">
                <p className="font-medium text-slate-400 mb-1">Caption / Comment:</p>
                <p>{activeItem.comment}</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
