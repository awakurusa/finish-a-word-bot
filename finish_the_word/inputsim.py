"""Low-level Windows input via SendInput using hardware *scan codes*.

Roblox (like most games using DirectInput / raw input) ignores the virtual-key
events PyAutoGUI sends by default, so typing "does nothing". Scan-code events
are what a real keyboard produces and are accepted.
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

from .winutil import IS_WINDOWS

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE = 0x0002, 0x0008
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
MAPVK_VK_TO_VSC = 0
VK_RETURN = 0x0D
SCAN_ENTER = 0x1C
ULONG_PTR = ctypes.c_size_t


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD)]


class _InputUnion(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _InputUnion)]


def _send(*inputs: INPUT) -> int:
    arr = (INPUT * len(inputs))(*inputs)
    return ctypes.windll.user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def _key_event(scan: int, up: bool) -> INPUT:
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if up else 0)
    return INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(0, scan, flags, 0, 0))


class ScanCodeKeyboard:
    """Same tiny interface as the other typing backends."""

    def __init__(self, hold: float = 0.015):
        if not IS_WINDOWS:
            raise RuntimeError("SendInput backend is Windows-only")
        self.hold = hold

    def _scan_for_char(self, ch: str) -> int:
        user32 = ctypes.windll.user32
        vk = user32.VkKeyScanW(ord(ch)) & 0xFF
        return user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)

    def _tap(self, scan: int) -> None:
        if scan == 0:
            raise RuntimeError("No scan code for key")
        if not _send(_key_event(scan, False)):
            raise RuntimeError("SendInput was blocked (is Roblox running as Administrator? "
                               "Run this tool as Administrator too)")
        time.sleep(self.hold)
        _send(_key_event(scan, True))

    def press_char(self, ch: str) -> None:
        self._tap(self._scan_for_char(ch))

    def press_enter(self) -> None:
        self._tap(SCAN_ENTER)

    def click(self, x: int, y: int) -> None:
        user32 = ctypes.windll.user32
        user32.SetCursorPos(int(x), int(y))
        time.sleep(0.05)
        down = INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, 0))
        up = INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, 0))
        _send(down)
        time.sleep(0.04)
        _send(up)
