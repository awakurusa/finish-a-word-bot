"""Screen capture of the configurable detection region."""
from __future__ import annotations

import threading

import numpy as np

from . import winutil
from .config import Config


class CaptureError(RuntimeError):
    pass


class ScreenCapture:
    """Grabs the configured region as a BGR numpy array (OpenCV convention)."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._local = threading.local()  # mss handles are thread-bound

    def _sct(self):
        sct = getattr(self._local, "sct", None)
        if sct is None:
            import mss

            sct = self._local.sct = mss.mss()
        return sct

    def absolute_region(self) -> tuple[int, int, int, int]:
        left, top, width, height = (int(v) for v in self.cfg.region)
        if self.cfg.region_relative_to_window:
            rect = winutil.find_window_client_rect(self.cfg.window_title)
            if rect is None:
                raise CaptureError(f"Window '{self.cfg.window_title}' not found")
            left += rect[0]
            top += rect[1]
        if width < 4 or height < 4:
            raise CaptureError("Capture region is too small")
        return left, top, width, height

    def grab(self) -> np.ndarray:
        left, top, width, height = self.absolute_region()
        shot = self._sct().grab(
            {"left": left, "top": top, "width": width, "height": height}
        )
        # mss returns BGRA; drop alpha -> BGR
        return np.ascontiguousarray(np.asarray(shot)[:, :, :3])
