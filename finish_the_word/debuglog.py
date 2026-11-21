"""Tiny debug log (ftw_debug.log in the project folder), rewritten each run.

It records what the bot read, what it decided and which keys it pressed, so
"it didn't erase" can be diagnosed from the file instead of guessed at.
"""
from __future__ import annotations

import time

from .config import ROOT

enabled = True
_PATH = ROOT / "ftw_debug.log"
_started = False
_MAX_BYTES = 2_000_000


def log(msg: str) -> None:
    global _started
    if not enabled:
        return
    try:
        if _started and _PATH.exists() and _PATH.stat().st_size > _MAX_BYTES:
            return
        t = time.time()
        with _PATH.open("a" if _started else "w", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S', time.localtime(t))}.{int(t * 1000) % 1000:03d}  {msg}\n")
        _started = True
    except OSError:
        pass
