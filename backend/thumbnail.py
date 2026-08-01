import io
import os
import tempfile
import subprocess
from typing import Optional
from PIL import Image

def generate_square_thumbnail(media_bytes: bytes, is_video: bool = False, size: int = 400) -> Optional[bytes]:
    """
    Generates a lightweight 400x400 JPEG square center crop for images or videos.
    - Images: Center cropped to 1:1 ratio and resized to 400x400.
    - Videos: Uses ffmpeg to extract frame at 0.5s, center crops 1:1, and resizes to 400x400.
    """
    if not media_bytes:
        return None

    if is_video:
        return _generate_video_thumbnail(media_bytes, size=size)

    try:
        img = Image.open(io.BytesIO(media_bytes))
        img = img.convert("RGB")
        width, height = img.size
        min_dim = min(width, height)
        left = (width - min_dim) // 2
        top = (height - min_dim) // 2
        right = left + min_dim
        bottom = top + min_dim
        img_cropped = img.crop((left, top, right, bottom))
        img_resized = img_cropped.resize((size, size), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        img_resized.save(output, format="JPEG", quality=82, optimize=True)
        return output.getvalue()
    except Exception as e:
        print(f"[Thumbnail Error] Image thumbnail generation failed: {e}")
        return None

def _generate_video_thumbnail(video_bytes: bytes, size: int = 400) -> Optional[bytes]:
    """Extracts frame from video bytes using ffmpeg and crops to 400x400 square JPEG."""
    tmp_in_path = None
    tmp_out_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_in:
            tmp_in.write(video_bytes)
            tmp_in_path = tmp_in.name
        tmp_out_path = tmp_in_path + ".jpg"

        cmd = [
            "ffmpeg", "-y",
            "-ss", "00:00:00.500",
            "-i", tmp_in_path,
            "-vframes", "1",
            "-vf", f"crop='min(iw,ih)':'min(iw,ih)',scale={size}:{size}",
            "-q:v", "4",
            tmp_out_path
        ]
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
        if res.returncode == 0 and os.path.exists(tmp_out_path) and os.path.getsize(tmp_out_path) > 0:
            with open(tmp_out_path, "rb") as f:
                return f.read()
    except Exception as e:
        print(f"[Thumbnail Error] Video thumbnail generation via ffmpeg failed: {e}")
    finally:
        for p in [tmp_in_path, tmp_out_path]:
            if p and os.path.exists(p):
                try: os.remove(p)
                except Exception: pass
    return None
