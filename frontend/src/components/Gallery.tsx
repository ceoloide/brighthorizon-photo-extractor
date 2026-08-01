import React, { useState, useEffect, useMemo } from 'react';
import {
  Image as ImageIcon,
  Video,
  Calendar,
  Download,
  Eye,
  X,
  Filter,
  ChevronDown,
  ChevronRight,
  ChevronsDown,
  ChevronsUp
} from 'lucide-react';

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

const formatMonthGroupTitle = (key: string) => {
  const [yearStr, monthStr] = key.split('-');
  const year = parseInt(yearStr, 10);
  const monthIdx = parseInt(monthStr, 10) - 1;
  if (!isNaN(year) && !isNaN(monthIdx) && monthIdx >= 0 && monthIdx < 12) {
    const monthNames = [
      'January', 'February', 'March', 'April', 'May', 'June',
      'July', 'August', 'September', 'October', 'November', 'December'
    ];
    return `${monthNames[monthIdx]} ${year}`;
  }
  return key;
};

const isItemVideo = (item: MediaItem) => {
  if (!item) return false;
  const mime = (item.mime_type || '').toLowerCase();
  const fn = (item.original_filename || '').toLowerCase();
  return mime.includes('video') || /\.(mp4|mov|avi|mkv|webm|m4v)$/i.test(fn);
};

export const Gallery: React.FC<GalleryProps> = ({ token, refreshTrigger }) => {
  const [mediaList, setMediaList] = useState<MediaItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [selectedChild, setSelectedChild] = useState<string>('all');
  const [activeItem, setActiveItem] = useState<MediaItem | null>(null);
  const [openMonths, setOpenMonths] = useState<Record<string, boolean>>({});
  const [loadedMedia, setLoadedMedia] = useState<Record<string, boolean>>({});

  const handleMediaLoaded = (id: string) => {
    setLoadedMedia((prev) => ({ ...prev, [id]: true }));
  };

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

  const groupedMedia = useMemo(() => {
    const groups: { [key: string]: { key: string; title: string; items: MediaItem[] } } = {};

    filteredList.forEach((item) => {
      let key = 'Unknown Date';
      if (item.date && /^\d{4}-\d{2}-\d{2}$/.test(item.date)) {
        key = item.date.substring(0, 7); // "YYYY-MM"
      } else if (item.date) {
        const d = new Date(item.date);
        if (!isNaN(d.getTime())) {
          const y = d.getFullYear();
          const m = String(d.getMonth() + 1).padStart(2, '0');
          key = `${y}-${m}`;
        }
      }

      if (!groups[key]) {
        groups[key] = {
          key,
          title: key === 'Unknown Date' ? 'Unknown Date' : formatMonthGroupTitle(key),
          items: []
        };
      }
      groups[key].items.push(item);
    });

    const sortedKeys = Object.keys(groups).sort((a, b) => b.localeCompare(a));

    return sortedKeys.map((k) => {
      const grp = groups[k];
      grp.items.sort((a, b) => b.date.localeCompare(a.date));
      return grp;
    });
  }, [filteredList]);

  const toggleMonth = (key: string) => {
    setOpenMonths((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const handleExpandAll = () => {
    const allOpen: Record<string, boolean> = {};
    groupedMedia.forEach((g) => {
      allOpen[g.key] = true;
    });
    setOpenMonths(allOpen);
  };

  const handleCollapseAll = () => {
    setOpenMonths({});
  };

  const isAllExpanded = groupedMedia.length > 0 && groupedMedia.every((g) => openMonths[g.key]);

  return (
    <div className="space-y-4 font-sans">
      {/* Header & Filter Controls */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-4 sm:p-5 bg-white rounded-2xl border border-slate-200 shadow-xs">
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
            <p className="text-xs text-slate-500 mt-0.5">High-resolution photos & videos grouped by month</p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {groupedMedia.length > 0 && (
            <button
              type="button"
              onClick={isAllExpanded ? handleCollapseAll : handleExpandAll}
              className="px-3 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold rounded-xl transition border border-slate-200 flex items-center gap-1.5 shrink-0"
            >
              {isAllExpanded ? (
                <>
                  <ChevronsUp className="w-3.5 h-3.5 text-slate-500" />
                  <span>Collapse All</span>
                </>
              ) : (
                <>
                  <ChevronsDown className="w-3.5 h-3.5 text-slate-500" />
                  <span>Expand All</span>
                </>
              )}
            </button>
          )}

          {childrenOptions.length > 0 && (
            <div className="flex items-center gap-2 overflow-x-auto pb-1 sm:pb-0">
              <Filter className="w-3.5 h-3.5 text-slate-400 shrink-0" />
              <div className="flex items-center gap-1 bg-slate-100 border border-slate-200 rounded-xl p-1 text-xs shrink-0">
                <button
                  type="button"
                  onClick={() => setSelectedChild('all')}
                  className={`px-3 py-1.5 sm:py-1 rounded-lg transition whitespace-nowrap ${
                    selectedChild === 'all'
                      ? 'bg-white text-indigo-700 font-semibold border border-slate-200 shadow-xs'
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
                        ? 'bg-white text-indigo-700 font-semibold border border-slate-200 shadow-xs'
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
      </div>

      {/* Grouped Month Accordion Sections */}
      {loading ? (
        <div className="flex flex-col justify-center items-center py-16 sm:py-20 text-slate-500 gap-3 bg-white rounded-2xl border border-slate-200 shadow-xs">
          <div className="w-7 h-7 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin" />
          <span className="text-xs font-medium text-slate-600">Loading photo gallery...</span>
        </div>
      ) : filteredList.length === 0 ? (
        <div className="text-center py-16 sm:py-20 bg-white rounded-2xl border border-dashed border-slate-200 text-slate-400 p-4 shadow-xs">
          <ImageIcon className="w-10 h-10 mx-auto mb-3 text-slate-300" />
          <p className="font-semibold text-slate-700 text-sm">No media downloaded yet</p>
          <p className="text-xs text-slate-400 mt-1 max-w-sm mx-auto">Start an extraction job above to populate photos and videos.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {groupedMedia.map((grp) => {
            const isOpen = !!openMonths[grp.key];
            const videoCount = grp.items.filter((i) => isItemVideo(i)).length;
            const photoCount = grp.items.length - videoCount;

            return (
              <div key={grp.key} className="bg-white border border-slate-200 rounded-2xl overflow-hidden shadow-xs">
                {/* Month Group Accordion Header */}
                <div
                  onClick={() => toggleMonth(grp.key)}
                  className="w-full flex items-center justify-between p-3.5 sm:p-4 bg-white hover:bg-slate-50 cursor-pointer transition select-none"
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="p-1.5 rounded-xl bg-indigo-50 text-indigo-600 border border-indigo-100 shrink-0">
                      {isOpen ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                    </div>
                    <div className="min-w-0 flex items-center gap-2">
                      <h3 className="font-bold text-slate-900 text-sm sm:text-base truncate">{grp.title}</h3>
                      <div className="flex items-center gap-1.5 shrink-0">
                        <span className="text-[11px] font-mono font-semibold bg-slate-100 text-slate-700 border border-slate-200 px-2 py-0.5 rounded-full">
                          {grp.items.length} {grp.items.length === 1 ? 'file' : 'files'}
                        </span>
                        {(photoCount > 0 || videoCount > 0) && (
                          <span className="hidden sm:inline text-[10px] text-slate-400 font-mono">
                            ({photoCount > 0 ? `${photoCount} photo${photoCount > 1 ? 's' : ''}` : ''}
                            {photoCount > 0 && videoCount > 0 ? ', ' : ''}
                            {videoCount > 0 ? `${videoCount} video${videoCount > 1 ? 's' : ''}` : ''})
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-1 text-xs text-indigo-600 font-medium shrink-0 ml-2">
                    <span>{isOpen ? 'Collapse' : 'Expand'}</span>
                  </div>
                </div>

                {/* Grid Content - Only rendered when section is open (Lazy DOM Mounting & Lazy Loading) */}
                {isOpen && (
                  <div className="p-3.5 sm:p-4 border-t border-slate-100 bg-slate-50/50">
                    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-2.5 sm:gap-4">
                      {grp.items.map((item) => {
                        const isVideo = isItemVideo(item);
                        const mediaUrl = `/api/media/${item.media_id}?token=${token}`;
                        const isLoaded = !!loadedMedia[item.media_id];

                        return (
                          <div
                            key={item.media_id}
                            onClick={() => setActiveItem(item)}
                            className="group relative bg-white rounded-2xl overflow-hidden border border-slate-200 hover:border-indigo-400 transition-all duration-200 cursor-pointer shadow-xs hover:shadow-md flex flex-col active:scale-[0.98]"
                          >
                            <div className="aspect-square bg-slate-100 relative overflow-hidden flex items-center justify-center">
                              {/* Skeleton Animated Placeholder */}
                              {!isLoaded && (
                                <div className="absolute inset-0 bg-slate-200/90 animate-pulse flex items-center justify-center z-0">
                                  {isVideo ? (
                                    <Video className="w-6 h-6 text-indigo-400/60 animate-pulse" />
                                  ) : (
                                    <ImageIcon className="w-6 h-6 text-slate-400/50 animate-pulse" />
                                  )}
                                </div>
                              )}

                              {isVideo ? (
                                <>
                                  <video
                                    src={`${mediaUrl}#t=0.5`}
                                    preload="metadata"
                                    muted
                                    playsInline
                                    onLoadedMetadata={() => handleMediaLoaded(item.media_id)}
                                    onLoadedData={() => handleMediaLoaded(item.media_id)}
                                    onCanPlay={() => handleMediaLoaded(item.media_id)}
                                    onSeeked={() => handleMediaLoaded(item.media_id)}
                                    onError={() => handleMediaLoaded(item.media_id)}
                                    className={`w-full h-full object-cover group-hover:scale-105 transition-all duration-300 ${
                                      isLoaded ? 'opacity-100' : 'opacity-80'
                                    }`}
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
                                  decoding="async"
                                  onLoad={() => handleMediaLoaded(item.media_id)}
                                  className={`w-full h-full object-cover group-hover:scale-105 transition-all duration-300 ${
                                    isLoaded ? 'opacity-100 scale-100' : 'opacity-0 scale-95'
                                  }`}
                                />
                              )}
                              <div className="absolute inset-0 bg-slate-900/30 opacity-0 group-hover:opacity-100 transition-opacity duration-200 flex items-center justify-center z-20">
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
                  </div>
                )}
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

            <div className="p-2 sm:p-4 flex-1 flex items-center justify-center overflow-auto bg-slate-900 min-h-[250px]">
              {isItemVideo(activeItem) ? (
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
