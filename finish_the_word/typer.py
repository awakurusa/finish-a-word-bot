"""Keyboard automation. Knows nothing about OCR or dictionaries."""
from __future__ import annotations

import time
from dataclasses import dataclass

from . import winutil
from .config import Config


ADMIN_MESSAGE = ("'{title}' is running as Administrator, so Windows blocks this tool's "
                 "keystrokes. Restart the tool as Administrator (run_as_admin.bat)")


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

    def press_backspace(self):
        self.g.press("backspace")

    def press_key(self, name):
        self.g.press(name)

    def click(self, x, y):
        self.g.click(int(x), int(y))


class Typer:
    """Backends: "sendinput" (default, hardware scan codes), "sendinput_vk"
    (virtual key + scan code), "pydirectinput", "pyautogui"."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._kb = None
        self.last_typed_len = 0     # letters typed by the latest type_word (what a retry must erase)

    def _backend(self):
        if self._kb is None:
            name = self.cfg.typing_backend
            if name in ("sendinput", "sendinput_vk") and not winutil.IS_WINDOWS:
                name = "pyautogui"          # dev machines / CI
            if name in ("sendinput", "sendinput_vk"):
                from .inputsim import ScanCodeKeyboard

                self._kb = ScanCodeKeyboard(self.cfg.key_hold, use_vk=(name == "sendinput_vk"))
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
        cfg = self.cfg
        if not winutil.IS_WINDOWS or self.roblox_focused():
            return None
        if cfg.auto_focus_roblox:
            winutil.focus_window(cfg.window_title)      # polite: ask Windows
            if self.roblox_focused():
                time.sleep(0.12)
                return None
        if cfg.click_to_focus:                          # firm: click the window
            points = ([tuple(cfg.focus_click_pos)] if cfg.focus_click_pos
                      else winutil.focus_click_points(cfg.window_title))
            try:
                kb = self._backend()
                for x, y in points:
                    kb.click(x, y)
                    for _ in range(8):
                        time.sleep(0.05)
                        if self.roblox_focused():
                            time.sleep(0.1)
                            return None
            except Exception as e:
                return f"Could not click the Roblox window: {type(e).__name__}: {e}"
        if cfg.require_roblox_focus:
            return (f"Could not switch to the '{cfg.window_title}' window "
                    f"(is it open, visible and not minimised? is the title right?)")
        return None

    def type_word(self, word: str, skip: int = 0, erase: int = 0) -> TypeResult:
        """Type `word`. The first `skip` letters are not typed because the game
        already shows them (the prompt); the rest and Enter are. `erase` presses
        Backspace that many times first, to clear a refused word the game left
        in the box."""
        cfg = self.cfg
        if not word or not word.isalpha():
            return TypeResult(False, "Refusing to type an invalid word")
        skip = max(0, min(skip, len(word) - 1))     # always type at least one letter
        to_type = word[skip:]
        shown = f"'{word}'" if not skip else f"'{word}' (only '{to_type}', '{word[:skip]}' is already there)"
        if cfg.dry_run:
            return TypeResult(True, f"[dry run] would type {shown}")
        if winutil.blocked_by_uipi(cfg.window_title):
            return TypeResult(False, ADMIN_MESSAGE.format(title=cfg.window_title))
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
            for _ in range(max(0, erase)):
                kb.press_backspace()
                if cfg.typing_delay > 0:
                    time.sleep(cfg.typing_delay)
            self.last_typed_len = 0
            for ch in to_type.lower():
                kb.press_char(ch)
                self.last_typed_len += 1
                if cfg.typing_delay > 0:
                    time.sleep(cfg.typing_delay)
            if cfg.press_enter:
                time.sleep(cfg.pre_type_delay)
                kb.press_enter()
        except ImportError as e:
            return TypeResult(False, f"Typing library missing: {e.name}")
        except Exception as e:  # incl. pyautogui.FailSafeException
            return TypeResult(False, f"Typing failed: {type(e).__name__}: {e}")
        return TypeResult(True, f"Typed {shown}")
