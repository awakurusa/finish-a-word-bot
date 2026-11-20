"""Keyboard automation. Knows nothing about OCR or dictionaries."""
from __future__ import annotations

import time
from dataclasses import dataclass

from . import winutil
from .config import Config


@dataclass
class TypeResult:
    ok: bool
    message: str = ""


class Typer:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._gui = None

    def _backend(self):
        if self._gui is None:
            if self.cfg.typing_backend == "pydirectinput":
                import pydirectinput as gui

                gui.PAUSE = 0
            else:
                import pyautogui as gui

                gui.PAUSE = 0
                gui.FAILSAFE = True  # slam the mouse into a screen corner to abort
            self._gui = gui
        return self._gui

    def roblox_focused(self) -> bool:
        if not self.cfg.require_roblox_focus or not winutil.IS_WINDOWS:
            return True
        return self.cfg.window_title.lower() in winutil.foreground_title().lower()

    def type_word(self, word: str) -> TypeResult:
        cfg = self.cfg
        if not word or not word.isalpha():
            return TypeResult(False, "Refusing to type an invalid word")
        if cfg.dry_run:
            return TypeResult(True, f"[dry run] would type '{word}'")
        if not self.roblox_focused():
            return TypeResult(False, f"'{cfg.window_title}' is not the active window")
        try:
            gui = self._backend()
            if cfg.input_pos:
                gui.click(int(cfg.input_pos[0]), int(cfg.input_pos[1]))
            elif cfg.focus_key:
                gui.press(cfg.focus_key)
            time.sleep(cfg.pre_type_delay)
            for ch in word:
                gui.press(ch) if cfg.typing_backend == "pydirectinput" else gui.write(ch)
                if cfg.typing_delay > 0:
                    time.sleep(cfg.typing_delay)
            if cfg.press_enter:
                time.sleep(cfg.pre_type_delay)
                gui.press("enter")
        except ImportError as e:
            return TypeResult(False, f"Typing library missing: {e.name}")
        except Exception as e:  # incl. pyautogui.FailSafeException
            return TypeResult(False, f"Typing failed: {type(e).__name__}: {e}")
        return TypeResult(True, f"Typed '{word}'")
