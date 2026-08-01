import pytest
import io
from PIL import Image
from backend.thumbnail import generate_square_thumbnail

def test_generate_square_thumbnail_image():
    # Create an 800x600 test image in memory
    img = Image.new("RGB", (800, 600), color="blue")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    img_bytes = buf.getvalue()

    thumb_bytes = generate_square_thumbnail(img_bytes, is_video=False, size=400)
    assert thumb_bytes is not None

    # Verify generated thumbnail dimensions are 400x400
    res_img = Image.open(io.BytesIO(thumb_bytes))
    assert res_img.size == (400, 400)
    assert res_img.format == "JPEG"

def test_generate_square_thumbnail_invalid_data():
    res = generate_square_thumbnail(b"invalid data", is_video=False)
    assert res is None
