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


class _PyAutoGuiKeyboard:
    def __init__(self, module):
        self.g = module
        module.PAUSE = 0

    def press_char(self, ch):
        self.g.press(ch)

    def press_enter(self):
        self.g.press("enter")

    def press_key(self, name):
        self.g.press(name)

    def click(self, x, y):
        self.g.click(int(x), int(y))


class Typer:
    """Backends: "sendinput" (default on Windows, scan codes), "pydirectinput",
    "pyautogui"."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._kb = None

    def _backend(self):
        if self._kb is None:
            name = self.cfg.typing_backend
            if name == "sendinput" and not winutil.IS_WINDOWS:
                name = "pyautogui"          # dev machines / CI
            if name == "sendinput":
                from .inputsim import ScanCodeKeyboard

                self._kb = ScanCodeKeyboard()
            elif name == "pydirectinput":
                import pydirectinput

                self._kb = _PyAutoGuiKeyboard(pydirectinput)
            else:
                import pyautogui

                pyautogui.FAILSAFE = True  # slam the mouse into a corner to abort
                self._kb = _PyAutoGuiKeyboard(pyautogui)
        return self._kb

    def roblox_focused(self) -> bool:
        if not winutil.IS_WINDOWS:
            return True
        return self.cfg.window_title.lower() in winutil.foreground_title().lower()

    def _ensure_focus(self) -> str | None:
        """Make Roblox the active window. Returns an error message or None."""
        if not winutil.IS_WINDOWS or self.roblox_focused():
            return None
        if self.cfg.auto_focus_roblox and winutil.focus_window(self.cfg.window_title):
            time.sleep(0.12)
            return None
        if self.cfg.require_roblox_focus:
            return (f"Could not switch to the '{self.cfg.window_title}' window "
                    f"(is it open? is the title right?)")
        return None

    def type_word(self, word: str) -> TypeResult:
        cfg = self.cfg
        if not word or not word.isalpha():
            return TypeResult(False, "Refusing to type an invalid word")
        if cfg.dry_run:
            return TypeResult(True, f"[dry run] would type '{word}'")
        problem = self._ensure_focus()
        if problem:
            return TypeResult(False, problem)
        try:
            kb = self._backend()
            if cfg.input_pos:
                kb.click(cfg.input_pos[0], cfg.input_pos[1])
            elif cfg.focus_key:
                if len(cfg.focus_key) == 1:
                    kb.press_char(cfg.focus_key)
                else:
                    kb.press_key(cfg.focus_key)
            time.sleep(cfg.pre_type_delay)
            for ch in word.lower():
                kb.press_char(ch)
                if cfg.typing_delay > 0:
                    time.sleep(cfg.typing_delay)
            if cfg.press_enter:
                time.sleep(cfg.pre_type_delay)
                kb.press_enter()
        except ImportError as e:
            return TypeResult(False, f"Typing library missing: {e.name}")
        except Exception as e:  # incl. pyautogui.FailSafeException
            return TypeResult(False, f"Typing failed: {type(e).__name__}: {e}")
        return TypeResult(True, f"Typed '{word}'")
