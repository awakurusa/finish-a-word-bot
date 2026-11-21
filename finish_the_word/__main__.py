"""Entry point.

    python -m finish_the_word                  GUI control panel
    python -m finish_the_word --cli            headless loop (Ctrl+C to stop)
    python -m finish_the_word --preview        save the captured region to preview.png
    python -m finish_the_word --ocr-image F    test OCR alone on an image file
    python -m finish_the_word --solve ST       test dictionary matching alone
"""
from __future__ import annotations

import argparse
import sys
import time

from . import winutil
from .config import ROOT, Config


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="finish_the_word", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cli", action="store_true", help="run without the GUI")
    ap.add_argument("--preview", action="store_true", help="save the capture region to preview.png")
    ap.add_argument("--ocr-image", metavar="FILE", help="run OCR on an image file and print the result")
    ap.add_argument("--solve", metavar="LETTERS", help="find a word for these letters")
    ap.add_argument("--mode", choices=("prefix", "contains", "suffix", "last_letter"))
    ap.add_argument("--test-keys", action="store_true",
                    help="type test letters with every input method to find the one that works")
    ap.add_argument("--window", metavar="TITLE", help="window to type into for --test-keys (e.g. Notepad)")
    ap.add_argument("--backend", help="only test this typing backend")
    ap.add_argument("--admin", action="store_true",
                    help="relaunch this program as Administrator (needed if Roblox runs as admin)")
    ap.add_argument("--dry-run", action="store_true", help="never press keys")
    args = ap.parse_args(argv)

    if args.admin and winutil.IS_WINDOWS and not winutil.is_admin():
        import ctypes

        rest = " ".join(f'"{a}"' for a in (argv if argv is not None else sys.argv[1:]) if a != "--admin")
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, f"-m finish_the_word {rest}", str(ROOT), 1)
        if rc <= 32:
            print("Could not start as Administrator (was the prompt declined?)")
            return 1
        return 0

    winutil.enable_dpi_awareness()
    cfg = Config.load()
    if args.mode:
        cfg.match_mode = args.mode
    if args.dry_run:
        cfg.dry_run = True

    if args.test_keys:
        from .typer import Typer

        if args.window:
            cfg.window_title = args.window
        cfg.dry_run, cfg.press_enter, cfg.input_pos, cfg.focus_key = False, False, None, ""
        backends = [args.backend] if args.backend else [
            "sendinput", "sendinput_vk", "pydirectinput", "pyautogui"]
        admin = ""
        if winutil.IS_WINDOWS:
            admin = f"this tool is Administrator: {winutil.is_admin()}"
            if winutil.blocked_by_uipi(cfg.window_title):
                admin += (f"  *** '{cfg.window_title}' is running as Administrator, so Windows "
                          "blocks our input. Run again with --admin ***")
        print(f"Typing test into the '{cfg.window_title}' window. {admin}")
        print("Each method types a different letter: aaaa, bbbb, cccc, dddd.")
        print("Starting in 5 seconds; it will bring that window to the front.")
        time.sleep(5)
        for letter, name in zip("abcd", backends):
            cfg.typing_backend = name
            res = Typer(cfg).type_word(letter * 4)
            print(f"  {name:14} -> {res.message}")
            time.sleep(1.2)
        print("Whichever letters appeared in the game are the methods that work. "
              'Set "typing_backend" in config.json to that one.')
        return 0

    if args.solve:
        from .dictionary import load_db
        from .ocr import normalize

        db = load_db(cfg)
        q = normalize(args.solve, cfg.allow_blanks)
        sol = db.solve(q, cfg)
        print(f"query={q!r} mode={cfg.match_mode} -> {sol.word}  "
              f"(zipf {sol.zipf:.2f}, corrected={sol.corrected}, alternatives={sol.alternatives})")
        return 0 if sol.word else 1

    if args.ocr_image:
        import cv2

        from .ocr import OCR

        img = cv2.imread(args.ocr_image)
        if img is None:
            print(f"Cannot read image: {args.ocr_image}")
            return 2
        res = OCR(cfg).read(img)
        print(f"text={res.text!r} raw={res.raw!r} confidence={res.confidence:.1f} {res.error}")
        return 0 if res.text else 1

    if args.preview:
        import cv2

        from .capture import ScreenCapture

        frame = ScreenCapture(cfg).grab()
        out = ROOT / "preview.png"
        cv2.imwrite(str(out), frame)
        print(f"Saved {out}  (region={cfg.region})")
        return 0

    if args.cli:
        from .engine import Engine, HotkeyWatcher

        last = {"s": ""}

        def show(s):
            line = f"[{s.letters or '-':>10}] {s.confidence:5.1f}%  word={s.word or '-':<14} {s.status}"
            if line != last["s"]:
                print(line)
                last["s"] = line

        eng = Engine(cfg, on_state=show)
        HotkeyWatcher(eng).start()
        eng.start()
        print(f"Running. {cfg.hotkey} toggles on Windows, Ctrl+C quits.")
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            eng.stop()
        return 0

    from .gui import main as gui_main

    gui_main(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
