"""`python -m finish_the_word --diagnose`: one report that pins down why typing fails."""
from __future__ import annotations

import ctypes
import platform
import time
from ctypes import wintypes

from . import winutil
from .config import Config


def _line(label: str, value) -> None:
    print(f"  {label:<34} {value}")


def run(cfg: Config) -> int:
    if not winutil.IS_WINDOWS:
        print("--diagnose only works on Windows.")
        return 0

    from .inputsim import MAPVK_VK_TO_VSC, _key_event, _send

    user32 = ctypes.windll.user32
    title = cfg.window_title
    print("== Finish the Word typing diagnostic ==")
    print("Copy everything below and send it back.\n")
    print("System")
    _line("Windows", platform.platform())
    _line("Python", platform.python_version())
    _line("This tool runs as Administrator", winutil.is_admin())
    _line("Keyboard layout (hex)", hex(user32.GetKeyboardLayout(0) & 0xFFFFFFFF))
    _line("typing_backend / key_hold", f"{cfg.typing_backend} / {cfg.key_hold}")
    _line("click_to_focus / auto_focus", f"{cfg.click_to_focus} / {cfg.auto_focus_roblox}")

    print("\nRoblox window")
    hwnd = winutil.find_hwnd(title)
    _line(f"Window matching '{title}'", "FOUND" if hwnd else "NOT FOUND (open Roblox / fix window_title)")
    if hwnd:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        _line("Process id", pid.value)
        _line("Roblox runs as Administrator", winutil._process_elevated(pid.value))
        _line("Our input blocked by Windows (UIPI)", winutil.blocked_by_uipi(title))
        _line("Client area (l, t, w, h)", winutil.find_window_client_rect(title))
    _line("Foreground window right now", repr(winutil.foreground_title()))

    for ch in "az":
        vk = user32.VkKeyScanW(ord(ch)) & 0xFF
        _line(f"Key '{ch}': vk / scan code", f"{hex(vk)} / {hex(user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC))}")

    print("\nStarting key test in 5 seconds. Roblox will be brought to the front;")
    print("watch the game and note whether any letters appear.")
    time.sleep(5)
    got_focus = winutil.focus_window(title)
    time.sleep(0.4)
    _line("Roblox in front after focus attempt", f"{got_focus} (foreground: {winutil.foreground_title()!r})")

    print("\nKey test: does Windows accept the keys, and does the game react?")
    vk_a = user32.VkKeyScanW(ord("a")) & 0xFF
    scan_a = user32.MapVirtualKeyW(vk_a, MAPVK_VK_TO_VSC)
    for name, use_vk in (("scan codes (sendinput)", False), ("vk + scan (sendinput_vk)", True)):
        sent = _send(_key_event(vk_a, scan_a, False, use_vk))
        time.sleep(0.06)
        down = bool(user32.GetAsyncKeyState(vk_a) & 0x8000)
        _send(_key_event(vk_a, scan_a, True, use_vk))
        _line(name, f"events accepted: {sent}/1, Windows saw key down: {down}")
        time.sleep(0.3)
        for _ in range(3):                       # a few more so it is visible in-game
            _send(_key_event(vk_a, scan_a, False, use_vk)); time.sleep(0.08)
            _send(_key_event(vk_a, scan_a, True, use_vk)); time.sleep(0.12)
        time.sleep(0.6)

    print("\nHow to read this")
    print("  * 'Roblox runs as Administrator: True' and 'This tool runs as Administrator: False'")
    print("    -> restart with run_as_admin.bat.")
    print("  * 'Windows saw key down: False' -> Windows itself rejected the input.")
    print("  * 'Windows saw key down: True' but no letters in the game -> Roblox ignores")
    print("    injected keys; tell us what you saw in the game.")
    return 0
