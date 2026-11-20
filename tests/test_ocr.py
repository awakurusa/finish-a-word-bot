import shutil

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from finish_the_word.config import Config
from finish_the_word.ocr import OCR, normalize, preprocess

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:\\Windows\\Fonts\\arialbd.ttf",
    "/Library/Fonts/Arial Bold.ttf",
]


def font(size=64):
    for p in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render(text, fg=(255, 255, 255), bg=(40, 40, 60), size=64, noise=False):
    img = Image.new("RGB", (420, 120), bg)
    d = ImageDraw.Draw(img)
    f = font(size)
    box = d.textbbox((0, 0), text, font=f)
    d.text(((420 - box[2]) / 2, (120 - box[3]) / 2 - 4), text, font=f, fill=fg,
           stroke_width=2, stroke_fill=(0, 0, 0))
    arr = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)
    if noise:
        rng = np.random.default_rng(1)
        arr = np.clip(arr.astype(int) + rng.integers(-18, 18, arr.shape), 0, 255).astype(np.uint8)
    return arr


def test_normalize():
    assert normalize("S T") == "st"
    assert normalize("5T") == "st"
    assert normalize("ap__le") == "ap__le"
    assert normalize("ap--le") == "ap__le"
    assert normalize("ap--le", allow_blanks=False) == "aple"
    assert normalize("  Th! ") == "thi"
    assert normalize("") == ""


def test_preprocess_shapes():
    out = preprocess(render("ST"), 3)
    assert len(out) == 3 and all(o.ndim == 2 for o in out)


needs_tesseract = pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed")


@needs_tesseract
@pytest.mark.parametrize("text", ["ST", "TH", "QU", "BRA", "CHAR", "SPR"])
def test_ocr_light_on_dark(text):
    res = OCR(Config()).read(render(text))
    assert res.text == text.lower(), res


@needs_tesseract
@pytest.mark.parametrize("text", ["ST", "PRE", "TION"])
def test_ocr_dark_on_light_with_noise(text):
    res = OCR(Config()).read(render(text, fg=(20, 20, 20), bg=(230, 230, 210), noise=True))
    assert res.text == text.lower(), res


@needs_tesseract
def test_ocr_ignores_border_lines_at_region_edge():
    frame = render("ST")
    frame[:, :2] = 222   # 2px light lines like a window/UI frame edge
    frame[:2, :] = 222
    res = OCR(Config()).read(frame)
    assert res.text == "st" and res.confidence > 80, res


@needs_tesseract
def test_ocr_blank_image_is_empty_not_error():
    res = OCR(Config()).read(np.full((100, 300, 3), 30, np.uint8))
    assert res.text == "" and not res.error
