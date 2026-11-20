"""Windows helpers (ctypes only). Every function degrades gracefully elsewhere."""
from __future__ import annotations

import sys

IS_WINDOWS = sys.platform == "win32"

VK = {f"F{i}": 0x6F + i for i in range(1, 13)}  # F1=0x70 ... F12=0x7B


def enable_dpi_awareness() -> None:
    """Make screen coordinates physical pixels so mss, Tk and pyautogui agree."""
    if not IS_WINDOWS:
        return
    import ctypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _window_title(hwnd) -> str:
    import ctypes

    user32 = ctypes.windll.user32
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def foreground_title() -> str:
    if not IS_WINDOWS:
        return ""
    import ctypes

    return _window_title(ctypes.windll.user32.GetForegroundWindow())


def find_window_client_rect(title: str):
    """Return (left, top, width, height) of the client area of the window whose
    title best matches `title`, or None. Exact match beats substring match."""
    if not IS_WINDOWS:
        return None
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found: list[tuple[int, int]] = []  # (rank, hwnd)
    want = title.lower()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def enum_cb(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            t = _window_title(hwnd).lower()
            if t == want:
                found.append((0, hwnd))
            elif want in t:
                found.append((1, hwnd))
        return True

    user32.EnumWindows(enum_cb, 0)
    if not found:
        return None
    hwnd = sorted(found)[0][1]
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y, rect.right - rect.left, rect.bottom - rect.top


def key_down(name: str) -> bool:
    """True while the named key (e.g. 'F8') is physically held. Windows only."""
    if not IS_WINDOWS:
        return False
    import ctypes

    vk = VK.get(name.upper())
    if vk is None:
        return False
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
