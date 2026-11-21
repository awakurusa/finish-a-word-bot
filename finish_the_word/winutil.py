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


def find_hwnd(title: str):
    """Handle of the visible window whose title best matches `title`
    (exact match beats substring match), or None."""
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
    return sorted(found)[0][1] if found else None


def find_window_client_rect(title: str):
    """(left, top, width, height) of the matching window's client area, or None."""
    if not IS_WINDOWS:
        return None
    import ctypes
    from ctypes import wintypes

    hwnd = find_hwnd(title)
    if hwnd is None:
        return None
    user32 = ctypes.windll.user32
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y, rect.right - rect.left, rect.bottom - rect.top


def focus_window(title: str) -> bool:
    """Bring the matching window to the foreground. True if it ended up there."""
    if not IS_WINDOWS:
        return True
    import ctypes
    import time

    user32 = ctypes.windll.user32
    hwnd = find_hwnd(title)
    if hwnd is None:
        return False
    if user32.GetForegroundWindow() == hwnd:
        return True
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    # Windows only lets the foreground process steal focus; tapping Alt first
    # is the standard trick that makes SetForegroundWindow succeed.
    user32.keybd_event(0x12, 0, 0, 0)
    user32.keybd_event(0x12, 0, 2, 0)
    user32.SetForegroundWindow(hwnd)
    for _ in range(10):
        if user32.GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.02)
    return False


def focus_click_points(title: str) -> list[tuple[int, int]]:
    """Safe screen points to click so the Roblox window becomes active, best
    first, keeping only points where Roblox is really the window on top (not
    the control panel or another window sitting over it)."""
    if not IS_WINDOWS:
        return []
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    hwnd = find_hwnd(title)
    if hwnd is None:
        return []
    win, cl = wintypes.RECT(), wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(win))
    user32.GetClientRect(hwnd, ctypes.byref(cl))
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    cw, ch = cl.right - cl.left, cl.bottom - cl.top
    cx = pt.x + cw // 2
    candidates = []
    if pt.y - win.top > 12:                       # a real title bar exists
        candidates.append((cx, win.top + (pt.y - win.top) // 2))
    candidates += [(cx, pt.y + 6), (pt.x + cw // 2, pt.y + ch // 2)]  # in-game: top edge, centre
    ok = []
    for x, y in candidates:
        top = user32.GetAncestor(user32.WindowFromPoint(wintypes.POINT(x, y)), 2)  # GA_ROOT
        if top == hwnd:
            ok.append((x, y))
    return ok


def is_admin() -> bool:
    """True if this process is elevated (running as Administrator)."""
    if not IS_WINDOWS:
        return False
    import ctypes

    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _process_elevated(pid: int):
    """True/False if the process is/isn't elevated, None if unknown."""
    import ctypes
    from ctypes import wintypes

    k32, adv = ctypes.windll.kernel32, ctypes.windll.advapi32
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    adv.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    adv.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    ACCESS_DENIED = 5
    proc = k32.OpenProcess(0x1000, False, pid)            # PROCESS_QUERY_LIMITED_INFORMATION
    if not proc:
        return True if ctypes.GetLastError() == ACCESS_DENIED else None
    token = wintypes.HANDLE()
    try:
        if not adv.OpenProcessToken(proc, 0x0008, ctypes.byref(token)):   # TOKEN_QUERY
            return True if ctypes.GetLastError() == ACCESS_DENIED else None
        elevated, size = wintypes.DWORD(), wintypes.DWORD()
        if not adv.GetTokenInformation(token, 20, ctypes.byref(elevated),   # TokenElevation
                                       ctypes.sizeof(elevated), ctypes.byref(size)):
            return None
        return bool(elevated.value)
    finally:
        if token:
            k32.CloseHandle(token)
        k32.CloseHandle(proc)


def blocked_by_uipi(title: str) -> bool:
    """True when the target window runs as Administrator but we don't, so
    Windows silently discards our keyboard/mouse input (UIPI)."""
    if not IS_WINDOWS:
        return False
    try:
        import ctypes
        from ctypes import wintypes

        if is_admin():
            return False
        hwnd = find_hwnd(title)
        if hwnd is None:
            return False
        pid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return _process_elevated(pid.value) is True
    except Exception:
        return False


def relaunch_as_admin(args: list[str]) -> bool:
    """Start this program again elevated (shows the Windows UAC prompt).
    True if the prompt was accepted and the new process launched."""
    if not IS_WINDOWS:
        return False
    import ctypes
    import sys
    from pathlib import Path

    root = str(Path(__file__).resolve().parent.parent)
    params = " ".join(['-m', 'finish_the_word'] + [f'"{a}"' for a in args])
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, root, 1)
    return rc > 32


def key_down(name: str) -> bool:
    """True while the named key (e.g. 'F8') is physically held. Windows only."""
    if not IS_WINDOWS:
        return False
    import ctypes

    vk = VK.get(name.upper())
    if vk is None:
        return False
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
