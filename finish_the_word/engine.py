"""Glue: capture -> OCR -> dictionary -> typer, with change detection."""
from __future__ import annotations

import threading
import time
from copy import copy
from dataclasses import dataclass, field
from typing import Callable

import cv2
import numpy as np

from . import winutil
from .capture import CaptureError, ScreenCapture
from .config import Config
from .dictionary import Solution, WordDB, load_db
from .ocr import OCR, OCRResult, OCRUnavailable
from .turn import TurnDetector
from .typer import Typer


@dataclass
class State:
    running: bool = False
    raw: str = ""
    letters: str = ""
    confidence: float = 0.0
    word: str = ""
    status: str = "Idle"
    my_turn: bool | None = None   # None = turn check not configured
    corrected: bool = False
    alternatives: list = field(default_factory=list)
    frame: np.ndarray | None = field(default=None, repr=False)
    processed: np.ndarray | None = field(default=None, repr=False)


class Engine:
    def __init__(
        self,
        cfg: Config,
        capture: ScreenCapture | None = None,
        ocr: OCR | None = None,
        db: WordDB | None = None,
        typer: Typer | None = None,
        turn: TurnDetector | None = None,
        on_state: Callable[[State], None] | None = None,
    ):
        self.cfg = cfg
        self.capture = capture or ScreenCapture(cfg)
        self.ocr = ocr or OCR(cfg)
        self.db = db or load_db(cfg)
        self.typer = typer or Typer(cfg)
        self.turn = turn or TurnDetector(cfg, self.capture, self.ocr)
        self.on_state = on_state
        self.state = State()

        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._reset_tracking()

    # ---- state ----------------------------------------------------------
    def _reset_tracking(self) -> None:
        self._last_sig: np.ndarray | None = None
        self._last_read: OCRResult | None = None
        self._candidate = ""
        self._candidate_count = 0
        self._empty_reads = 0
        self._submitted_prompt: str | None = None
        self._submitted_at = 0.0
        self._attempted: set[str] = set()
        self._last_typed = ""

    def _emit(self, **changes) -> None:
        for k, v in changes.items():
            setattr(self.state, k, v)
        if self.on_state:
            self.on_state(copy(self.state))

    # ---- one iteration (pure logic, no sleeping; unit-testable) ----------
    @staticmethod
    def _signature(frame: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return cv2.resize(gray, (64, 24), interpolation=cv2.INTER_AREA).astype(np.float32)

    def step(self, frame: np.ndarray, now: float | None = None, turn: bool | None = None) -> None:
        """Process one frame. `turn`: True/False from the turn detector, None if unchecked."""
        cfg = self.cfg
        now = time.monotonic() if now is None else now

        sig = self._signature(frame)
        changed = (
            self._last_sig is None
            or self._last_read is None
            or float(np.mean(np.abs(sig - self._last_sig))) > cfg.change_threshold
        )
        if changed:  # OCR only when pixels actually changed
            read = self.ocr.read(frame)
            self._last_sig, self._last_read = sig, read
            self._emit(frame=frame, processed=read.processed)
        else:
            read = self._last_read

        text, conf = read.text, read.confidence
        letters = text.replace("_", "")
        self._emit(raw=read.raw, letters=text, confidence=conf, my_turn=turn)

        if turn is False:  # someone else's turn: keep watching, never answer
            self._candidate, self._candidate_count = "", 0
            self._submitted_prompt = None   # so we answer again when our turn comes
            self._emit(status="Waiting for your turn…")
            return

        if not letters or read.error:
            self._candidate, self._candidate_count = "", 0
            self._empty_reads += 1
            if self._empty_reads >= cfg.clear_reads:
                self._submitted_prompt = None  # prompt gone -> re-arm
            self._emit(status=read.error or "Waiting for letters…")
            return
        self._empty_reads = 0

        if not (cfg.min_letters <= len(letters) <= cfg.max_letters):
            self._emit(word="", status=f"Ignored '{text}' (unexpected length)")
            return
        if conf < cfg.min_confidence:
            self._candidate, self._candidate_count = "", 0
            self._emit(word="", status=f"Low confidence ({conf:.0f}%) for '{text}'")
            return

        if text == self._candidate:
            self._candidate_count += 1
        else:
            self._candidate, self._candidate_count = text, 1
        if self._candidate_count < cfg.stable_reads:
            self._emit(status=f"Reading '{text}'…")
            return

        if text != self._submitted_prompt:
            self._attempted = set()  # brand-new prompt
            self._submit(text, now)
        elif cfg.retry_next_word and now - self._submitted_at >= cfg.retry_after:
            if cfg.auto_ban_rejected and self._last_typed:
                self.db.ban(self._last_typed)   # prompt unchanged: game refused it
            self._emit(status=f"'{self._last_typed}' seems refused; trying another word…")
            erase = getattr(self.typer, "last_typed_len", 0) if cfg.clear_before_retry else 0
            self._submit(text, now, erase=erase)  # same prompt still up: answer was rejected?
        # else: already answered this prompt; wait for it to change

    def _submit(self, text: str, now: float, erase: int = 0) -> None:
        sol = self.db.solve(text, self.cfg, exclude=self._attempted)
        if not sol.word:
            self._submitted_prompt, self._submitted_at = text, now
            self._emit(word="", alternatives=[], status=f"No word found for '{text}'")
            return
        self._emit(word=sol.word, corrected=sol.corrected, alternatives=sol.alternatives,
                   status=f"Typing '{sol.word}'…")
        t0 = time.monotonic()
        result = self.typer.type_word(sol.word, skip=self._already_shown(sol), erase=erase)
        typing_time = time.monotonic() - t0
        if result.ok:
            self._attempted.add(sol.word)
            self._last_typed = sol.word
            self.db.mark_used(sol.word)
            # time the game's reaction from when typing FINISHED, not when it began
            self._submitted_prompt, self._submitted_at = text, now + typing_time
        # on failure leave the prompt un-submitted so the next poll retries
        self._emit(status=result.message)

    def _already_shown(self, sol: Solution) -> int:
        """How many leading letters of the answer are already on screen as the
        prompt, so the typer can skip them. Only plain prefix prompts qualify:
        blank patterns (ap__e) and the other match modes need the full word."""
        if not (self.cfg.skip_prompt_letters and self.cfg.match_mode == "prefix"):
            return 0
        q = sol.used_query
        if q and "_" not in q and sol.word and sol.word.startswith(q):
            return len(q)
        return 0

    def ban_word(self, word: str) -> str:
        """Permanently ban a word; returns a status line."""
        word = word.strip().lower()
        if not word.isalpha():
            return "No word to ban yet: the bot hasn't typed one"
        self.db.ban(word)
        self._attempted.add(word)
        path = self.db.blocklist_path
        if self.db.ban_error:
            msg = (f"Banned '{word}' for this session only; could not save it to "
                   f"{path}: {self.db.ban_error}")
        elif path:
            msg = f"Banned '{word}' and saved it to {path}"
        else:
            msg = f"Banned '{word}' for this session (no blocklist file configured)"
        self._emit(status=msg)
        return msg

    def ban_last_word(self) -> str:
        """Ban the word typed most recently (the one the game didn't accept)."""
        return self.ban_word(self._last_typed or self.state.word)

    # ---- manual testing -------------------------------------------------
    def solve_manual(self, text: str, type_it: bool = False) -> Solution:
        from .ocr import normalize

        q = normalize(text, self.cfg.allow_blanks)
        sol = self.db.solve(q, self.cfg, exclude=self._attempted)
        msg = f"Manual '{q}' -> {sol.word or 'no match'}"
        if sol.word and type_it:
            res = self.typer.type_word(sol.word, skip=self._already_shown(sol))
            msg = res.message
            if res.ok:
                self._attempted.add(sol.word)
                self.db.mark_used(sol.word)
        self._emit(raw=text, letters=q, confidence=100.0, word=sol.word or "",
                   corrected=sol.corrected, alternatives=sol.alternatives, status=msg)
        return sol

    # ---- thread control -------------------------------------------------
    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._reset_tracking()
        self._thread = threading.Thread(target=self._run, name="ftw-engine", daemon=True)
        self._thread.start()
        self._emit(running=True, status="Running")

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
        self._emit(running=False, status="Stopped")

    def toggle(self) -> None:
        self.stop() if self.running else self.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            t0 = time.monotonic()
            try:
                frame = self.capture.grab()
                self.step(frame, turn=self.turn.check())
            except OCRUnavailable as e:
                self._emit(running=False, status=str(e))
                return
            except CaptureError as e:
                self._emit(status=str(e))
            except Exception as e:
                self._emit(status=f"Error: {type(e).__name__}: {e}")
            self._stop.wait(max(0.0, self.cfg.poll_interval - (time.monotonic() - t0)))


class HotkeyWatcher:
    """Global start/stop hotkey (Windows; polls GetAsyncKeyState, no admin needed)."""

    def __init__(self, engine: Engine):
        self.engine = engine
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not winutil.IS_WINDOWS or self._thread:
            return
        self._thread = threading.Thread(target=self._run, name="ftw-hotkey", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        was_down = False
        while not self._stop.wait(0.05):
            down = winutil.key_down(self.engine.cfg.hotkey)
            if down and not was_down:
                self.engine.toggle()
            was_down = down
