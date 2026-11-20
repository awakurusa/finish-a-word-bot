"""OCR for the letter prompt. Knows nothing about dictionaries or keyboards."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

import cv2
import numpy as np

from .config import Config

BLANK_CHARS = "_-\u2013\u2014.\u2022\u25a1\u25a2?*"
# Characters OCR commonly returns instead of letters.
DIGIT_FIXES = {"0": "o", "1": "l", "5": "s", "8": "b", "|": "l", "!": "i", "$": "s"}
LETTERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
MIN_CONTRAST = 8.0  # grayscale std-dev below which a frame is treated as blank

TESSERACT_WINDOWS_PATHS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
)


class OCRUnavailable(RuntimeError):
    """The OCR backend cannot run (binary / package missing)."""


@dataclass
class OCRResult:
    text: str = ""            # normalised: lowercase letters and '_' only
    raw: str = ""             # exactly what the backend returned
    confidence: float = 0.0   # 0-100
    processed: np.ndarray | None = field(default=None, repr=False)
    error: str = ""


def normalize(raw: str, allow_blanks: bool = True) -> str:
    """Turn raw OCR output into lowercase letters (and '_' for blanks)."""
    out = []
    for ch in raw.strip():
        if ch.isspace():
            continue
        if ch in BLANK_CHARS:
            if allow_blanks:
                out.append("_")
            continue
        ch = DIGIT_FIXES.get(ch, ch).lower()
        if "a" <= ch <= "z":
            out.append(ch)
    return "".join(out)


def preprocess(img_bgr: np.ndarray, scale: int = 3, edge_trim: int = 3) -> list[np.ndarray]:
    """Return candidate binarised images (dark text on white), best guess first.

    `edge_trim` pixels are shaved off every side first: window borders and UI
    frame lines at the edge of the capture region otherwise confuse Tesseract.
    """
    h, w = img_bgr.shape[:2]
    if edge_trim > 0 and min(h, w) > edge_trim * 8:
        img_bgr = img_bgr[edge_trim:h - edge_trim, edge_trim:w - edge_trim]
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    if scale > 1:
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)

    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # Text is the minority colour: if most pixels are black, flip so the
    # background is white (what Tesseract expects).
    if otsu.mean() < 127:
        otsu = cv2.bitwise_not(otsu)
    candidates = [otsu, cv2.bitwise_not(otsu)]

    adaptive = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 10
    )
    if adaptive.mean() < 127:
        adaptive = cv2.bitwise_not(adaptive)
    candidates.append(adaptive)

    pad = 12
    return [
        cv2.copyMakeBorder(c, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255)
        for c in candidates
    ]


class OCR:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._easy = None
        self.last_processed: np.ndarray | None = None

    # ---- backends -------------------------------------------------------
    def _tesseract(self, img: np.ndarray) -> tuple[str, float]:
        try:
            import pytesseract
        except ImportError as e:  # pragma: no cover
            raise OCRUnavailable("pytesseract is not installed (pip install pytesseract)") from e

        cmd = self.cfg.tesseract_cmd
        if not cmd and os.name == "nt":
            cmd = next((p for p in TESSERACT_WINDOWS_PATHS if os.path.exists(p)), "")
        if cmd:
            pytesseract.pytesseract.tesseract_cmd = cmd

        whitelist = LETTERS + ("_-" if self.cfg.allow_blanks else "")
        config = (
            f"--oem 3 --psm {int(self.cfg.tesseract_psm)} "
            f"-c tessedit_char_whitelist={whitelist}"
        )
        try:
            data = pytesseract.image_to_data(
                img, config=config, output_type=pytesseract.Output.DICT
            )
        except pytesseract.TesseractNotFoundError as e:
            raise OCRUnavailable(
                "Tesseract executable not found. Install it and/or set "
                "'tesseract_cmd' in config.json (see README)."
            ) from e

        words, weights = [], []
        for txt, conf in zip(data["text"], data["conf"]):
            txt = txt.strip()
            try:
                conf = float(conf)
            except (TypeError, ValueError):
                continue
            if txt and conf >= 0:
                words.append(txt)
                weights.append((conf, len(txt)))
        if not words:
            return "", 0.0
        total = sum(n for _, n in weights)
        confidence = sum(c * n for c, n in weights) / max(total, 1)
        return "".join(words), confidence

    def _easyocr(self, img: np.ndarray) -> tuple[str, float]:
        if self._easy is None:
            try:
                import easyocr
            except ImportError as e:
                raise OCRUnavailable("easyocr is not installed (pip install easyocr)") from e
            self._easy = easyocr.Reader(["en"], gpu=False, verbose=False)
        allow = LETTERS + ("_-" if self.cfg.allow_blanks else "")
        results = self._easy.readtext(img, allowlist=allow, detail=1, paragraph=False)
        if not results:
            return "", 0.0
        results.sort(key=lambda r: r[0][0][0])  # left-to-right
        text = "".join(r[1] for r in results)
        conf = sum(r[2] for r in results) / len(results) * 100.0
        return text, conf

    def _run(self, img: np.ndarray) -> tuple[str, float]:
        if self.cfg.ocr_backend == "easyocr":
            return self._easyocr(img)
        return self._tesseract(img)

    # ---- public ---------------------------------------------------------
    def read(self, img_bgr: np.ndarray) -> OCRResult:
        """OCR one frame. Tries extra preprocessing variants only when the
        first attempt is not confident, which keeps the common case fast."""
        best = OCRResult()
        # A flat frame has no text; Tesseract would hallucinate letters on it.
        if float(np.std(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY))) < MIN_CONTRAST:
            self.last_processed = None
            return best
        try:
            for variant in preprocess(img_bgr, self.cfg.ocr_scale, self.cfg.edge_trim):
                raw, conf = self._run(variant)
                text = normalize(raw, self.cfg.allow_blanks)
                cand = OCRResult(text=text, raw=raw, confidence=conf, processed=variant)
                if text and (not best.text or conf > best.confidence):
                    best = cand
                elif not best.text and best.processed is None:
                    best = cand
                if best.text and best.confidence >= self.cfg.min_confidence:
                    break
        except OCRUnavailable:
            raise
        except Exception as e:  # never let one bad frame kill the loop
            best.error = f"{type(e).__name__}: {e}"
        self.last_processed = best.processed
        return best


_LETTER_RE = re.compile(r"[a-z]")


def letter_count(text: str) -> int:
    return len(_LETTER_RE.findall(text))
