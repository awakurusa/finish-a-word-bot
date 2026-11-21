"""Decides whether it is currently the player's turn. Knows nothing about
typing or words: it only looks at a small indicator region."""
from __future__ import annotations

import numpy as np

from .capture import ScreenCapture
from .config import Config
from .ocr import OCR


def mean_rgb(frame_bgr: np.ndarray) -> list[int]:
    b, g, r = (float(frame_bgr[:, :, i].mean()) for i in range(3))
    return [int(round(r)), int(round(g)), int(round(b))]


def color_matches(frame_bgr: np.ndarray, rgb, tolerance: float) -> bool:
    cur = np.array(mean_rgb(frame_bgr), dtype=float)
    return float(np.linalg.norm(cur - np.array(rgb, dtype=float))) <= tolerance


class TurnDetector:
    def __init__(self, cfg: Config, capture: ScreenCapture, ocr: OCR):
        self.cfg, self.capture, self.ocr = cfg, capture, ocr

    @property
    def enabled(self) -> bool:
        c = self.cfg
        if c.turn_check == "color":
            return bool(c.turn_region and c.turn_color)
        if c.turn_check == "text":
            return bool(c.turn_region and c.turn_text)
        return False

    def check(self, frame: np.ndarray | None = None) -> bool | None:
        """True = my turn, False = not my turn, None = no turn check configured.
        `frame` may be passed in (tests); otherwise the indicator is captured."""
        if not self.enabled:
            return None
        c = self.cfg
        if frame is None:
            frame = self.capture.grab(c.turn_region)
        if c.turn_check == "color":
            hit = color_matches(frame, c.turn_color, c.turn_color_tolerance)
        else:
            text = self.ocr.read_text(frame).raw.lower().replace(" ", "")
            hit = c.turn_text.lower().replace(" ", "") in text
        return (not hit) if c.turn_invert else hit
