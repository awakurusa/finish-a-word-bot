"""Tkinter control panel."""
from __future__ import annotations

import queue
import tkinter as tk
from tkinter import messagebox, ttk

import cv2
import numpy as np
from PIL import Image, ImageTk

from . import winutil
from .capture import CaptureError
from .config import Config
from .dictionary import MODES, SELECTIONS
from .engine import Engine, HotkeyWatcher, State
from .turn import mean_rgb

PREVIEW_W, PREVIEW_H = 420, 120


def _to_photo(img: np.ndarray | None, w: int = PREVIEW_W, h: int = PREVIEW_H):
    if img is None:
        return None
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
    else:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    ih, iw = img.shape[:2]
    s = min(w / iw, h / ih, 4.0)
    img = cv2.resize(img, (max(1, int(iw * s)), max(1, int(ih * s))), interpolation=cv2.INTER_AREA)
    return ImageTk.PhotoImage(Image.fromarray(img))


class App:
    def __init__(self, cfg: Config):
        winutil.enable_dpi_awareness()
        self.cfg = cfg
        self.root = tk.Tk()
        self.root.title("Finish the Word Assistant")
        self.root.attributes("-topmost", True)
        self.q: queue.Queue[State] = queue.Queue()

        self.engine = Engine(cfg, on_state=self.q.put)
        self.hotkeys = HotkeyWatcher(self.engine)
        self.hotkeys.start()

        self._photos = {}
        self._shown_frame = None
        self._asked_admin = False
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.after(80, self._poll)

    # ---- layout ---------------------------------------------------------
    def _build(self) -> None:
        r = self.root
        pad = {"padx": 6, "pady": 3}

        top = ttk.Frame(r)
        top.pack(fill="x", **pad)
        self.btn = ttk.Button(top, text=f"Start ({self.cfg.hotkey})", command=self._toggle)
        self.btn.pack(side="left")
        ttk.Button(top, text="Refresh preview", command=self._refresh_preview).pack(side="left", padx=6)
        ttk.Button(top, text="Reset used words", command=self._reset_used).pack(side="left")
        if winutil.IS_WINDOWS and not winutil.is_admin():
            ttk.Button(top, text="Restart as admin", command=self._restart_admin).pack(side="left", padx=6)

        # preview
        pv = ttk.LabelFrame(r, text="OCR preview (captured region / what OCR sees)")
        pv.pack(fill="x", **pad)
        self.lbl_frame = ttk.Label(pv)
        self.lbl_frame.pack(padx=4, pady=2)
        self.lbl_proc = ttk.Label(pv)
        self.lbl_proc.pack(padx=4, pady=2)

        # readout
        ro = ttk.LabelFrame(r, text="Status")
        ro.pack(fill="x", **pad)
        self.v_letters = tk.StringVar(value="-")
        self.v_word = tk.StringVar(value="-")
        self.v_conf = tk.StringVar(value="-")
        self.v_alt = tk.StringVar(value="")
        self.v_status = tk.StringVar(value="Idle")
        self.v_turn_state = tk.StringVar(value="not checked")
        for i, (name, var) in enumerate(
            (("Detected letters", self.v_letters), ("Selected word", self.v_word),
             ("Confidence", self.v_conf), ("Alternatives", self.v_alt), ("Your turn", self.v_turn_state), ("Status", self.v_status))
        ):
            ttk.Label(ro, text=name + ":").grid(row=i, column=0, sticky="w", **pad)
            ttk.Label(ro, textvariable=var, font=("Segoe UI", 10, "bold"),
                      wraplength=300).grid(row=i, column=1, sticky="w", **pad)

        # manual
        mf = ttk.LabelFrame(r, text="Manual test")
        mf.pack(fill="x", **pad)
        self.e_manual = ttk.Entry(mf, width=16)
        self.e_manual.pack(side="left", **pad)
        self.e_manual.bind("<Return>", lambda _e: self._manual(False))
        ttk.Button(mf, text="Find word", command=lambda: self._manual(False)).pack(side="left", **pad)
        ttk.Button(mf, text="Find & type (3s)", command=lambda: self._manual(True)).pack(side="left", **pad)

        # settings
        sf = ttk.LabelFrame(r, text="Settings")
        sf.pack(fill="x", **pad)
        self.v_region = [tk.IntVar(value=int(v)) for v in self.cfg.region]
        ttk.Label(sf, text="Region L / T / W / H").grid(row=0, column=0, sticky="w", **pad)
        rf = ttk.Frame(sf)
        rf.grid(row=0, column=1, columnspan=2, sticky="w")
        for v in self.v_region:
            ttk.Spinbox(rf, from_=0, to=10000, width=6, textvariable=v).pack(side="left", padx=2)
        ttk.Button(sf, text="Select region…", command=self._select_region).grid(row=1, column=1, sticky="w", **pad)
        self.v_rel = tk.BooleanVar(value=self.cfg.region_relative_to_window)
        ttk.Checkbutton(sf, text="Relative to Roblox window", variable=self.v_rel).grid(row=1, column=2, sticky="w")

        self.v_input = tk.StringVar(value=self._pos_text())
        ttk.Label(sf, text="Answer box click").grid(row=2, column=0, sticky="w", **pad)
        ttk.Label(sf, textvariable=self.v_input).grid(row=2, column=1, sticky="w", **pad)
        self.btn_pick = ttk.Button(sf, text="Pick (hover box, 3s)", command=self._pick_input)
        self.btn_pick.grid(row=2, column=2, sticky="w", **pad)

        self.v_mode = tk.StringVar(value=self.cfg.match_mode)
        self.v_sel = tk.StringVar(value=self.cfg.selection)
        ttk.Label(sf, text="Match mode").grid(row=3, column=0, sticky="w", **pad)
        ttk.Combobox(sf, values=MODES, textvariable=self.v_mode, width=12, state="readonly").grid(row=3, column=1, sticky="w", **pad)
        ttk.Label(sf, text="Word choice").grid(row=4, column=0, sticky="w", **pad)
        ttk.Combobox(sf, values=SELECTIONS, textvariable=self.v_sel, width=12, state="readonly").grid(row=4, column=1, sticky="w", **pad)

        self.v_delay = tk.DoubleVar(value=self.cfg.typing_delay)
        ttk.Label(sf, text="Typing delay (s)").grid(row=5, column=0, sticky="w", **pad)
        ttk.Spinbox(sf, from_=0, to=1, increment=0.01, width=6, textvariable=self.v_delay).grid(row=5, column=1, sticky="w", **pad)
        self.v_enter = tk.BooleanVar(value=self.cfg.press_enter)
        self.v_dry = tk.BooleanVar(value=self.cfg.dry_run)
        ttk.Checkbutton(sf, text="Press Enter", variable=self.v_enter).grid(row=5, column=2, sticky="w")
        ttk.Checkbutton(sf, text="Dry run (don't type)", variable=self.v_dry).grid(row=6, column=1, sticky="w", **pad)
        ttk.Button(sf, text="Save settings", command=self._apply).grid(row=6, column=2, sticky="w", **pad)

        # turn detection
        self.v_turn = tk.StringVar(value=self.cfg.turn_check)
        ttk.Label(sf, text="Turn check").grid(row=7, column=0, sticky="w", **pad)
        ttk.Combobox(sf, values=("none", "color", "text"), textvariable=self.v_turn,
                     width=12, state="readonly").grid(row=7, column=1, sticky="w", **pad)
        self.v_turn_info = tk.StringVar(value=self._turn_info())
        ttk.Label(sf, textvariable=self.v_turn_info, wraplength=240).grid(row=7, column=2, sticky="w", **pad)
        ttk.Button(sf, text="Select turn indicator…", command=self._select_turn_region).grid(row=8, column=1, sticky="w", **pad)
        ttk.Button(sf, text="Learn 'my turn' color", command=self._learn_turn_color).grid(row=8, column=2, sticky="w", **pad)
        self.v_turn_text = tk.StringVar(value=self.cfg.turn_text)
        ttk.Label(sf, text="Turn text").grid(row=9, column=0, sticky="w", **pad)
        ttk.Entry(sf, textvariable=self.v_turn_text, width=16).grid(row=9, column=1, sticky="w", **pad)
        self.v_turn_inv = tk.BooleanVar(value=self.cfg.turn_invert)
        ttk.Checkbutton(sf, text="Act when indicator is absent", variable=self.v_turn_inv).grid(row=9, column=2, sticky="w")
        ttk.Button(sf, text="Test turn check now", command=self._test_turn).grid(row=10, column=1, sticky="w", **pad)

    # ---- settings -------------------------------------------------------
    def _pos_text(self) -> str:
        p = self.cfg.input_pos
        return f"{p[0]}, {p[1]}" if p else "not set (assumes box is focused)"

    def _apply(self, save: bool = True) -> bool:
        c = self.cfg
        try:
            c.region = [max(0, v.get()) for v in self.v_region]
            c.typing_delay = max(0.0, float(self.v_delay.get()))
        except tk.TclError:
            self.v_status.set("Invalid number in settings")
            return False
        c.region_relative_to_window = self.v_rel.get()
        c.match_mode = self.v_mode.get()
        c.selection = self.v_sel.get()
        c.press_enter = self.v_enter.get()
        c.dry_run = self.v_dry.get()
        c.turn_check = self.v_turn.get()
        c.turn_text = self.v_turn_text.get().strip()
        c.turn_invert = self.v_turn_inv.get()
        if save:
            c.save()
            self.v_status.set("Settings saved")
        return True

    def _select_region(self, on_done=None) -> None:
        self.root.withdraw()
        self.root.after(250, lambda: self._region_overlay(on_done))

    def _to_cfg_coords(self, left: int, top: int) -> tuple[int, int]:
        """Screen coords -> what the config stores (window-relative if enabled)."""
        if self.cfg.region_relative_to_window:
            rect = winutil.find_window_client_rect(self.cfg.window_title)
            if rect:
                return left - rect[0], top - rect[1]
        return left, top

    def _region_overlay(self, on_done=None) -> None:
        ov = tk.Toplevel()
        ov.attributes("-fullscreen", True)
        ov.attributes("-topmost", True)
        ov.attributes("-alpha", 0.3)
        ov.configure(bg="black")
        cv = tk.Canvas(ov, cursor="cross", bg="black", highlightthickness=0)
        cv.pack(fill="both", expand=True)
        cv.create_text(20, 20, anchor="nw", fill="white", font=("Segoe UI", 16),
                       text="Drag a box around the letter prompt (Esc to cancel)")
        start, rect = {}, {}

        def press(e):
            start["p"] = (e.x_root, e.y_root, e.x, e.y)

        def drag(e):
            if "p" in start:
                if rect.get("id"):
                    cv.delete(rect["id"])
                rect["id"] = cv.create_rectangle(start["p"][2], start["p"][3], e.x, e.y,
                                                 outline="red", width=3)

        def release(e):
            if "p" not in start:
                return
            x0, y0 = start["p"][0], start["p"][1]
            l, t = min(x0, e.x_root), min(y0, e.y_root)
            w, h = abs(e.x_root - x0), abs(e.y_root - y0)
            ov.destroy()
            self.root.deiconify()
            if w >= 8 and h >= 8 and on_done:
                on_done(*self._to_cfg_coords(l, t), w, h)
            elif w >= 8 and h >= 8:
                l, t = self._to_cfg_coords(l, t)
                for var, val in zip(self.v_region, (l, t, w, h)):
                    var.set(val)
                self._apply(save=True)
                self._refresh_preview()

        def cancel(_e=None):
            ov.destroy()
            self.root.deiconify()

        cv.bind("<ButtonPress-1>", press)
        cv.bind("<B1-Motion>", drag)
        cv.bind("<ButtonRelease-1>", release)
        ov.bind("<Escape>", cancel)
        ov.focus_force()

    def _pick_input(self, n: int = 3) -> None:
        if n > 0:
            self.btn_pick.config(text=f"Hover over the box… {n}")
            self.root.after(1000, lambda: self._pick_input(n - 1))
            return
        x, y = self.root.winfo_pointerxy()
        self.cfg.input_pos = [x, y]
        self.v_input.set(self._pos_text())
        self.btn_pick.config(text="Pick (hover box, 3s)")
        self.cfg.save()

    # ---- turn detection -------------------------------------------------
    def _turn_info(self) -> str:
        c = self.cfg
        reg = f"region {c.turn_region}" if c.turn_region else "no region"
        col = f", color {c.turn_color}" if c.turn_color else ""
        return reg + col

    def _select_turn_region(self) -> None:
        def done(l, t, w, h):
            self.cfg.turn_region = [l, t, w, h]
            self.cfg.save()
            self.v_turn_info.set(self._turn_info())
            self.v_status.set("Turn indicator region saved. If it is YOUR turn now, "
                              "click 'Learn my turn color'.")
        self._select_region(done)

    def _learn_turn_color(self) -> None:
        if not self.cfg.turn_region:
            self.v_status.set("Select the turn indicator region first")
            return
        try:
            frame = self.engine.capture.grab(self.cfg.turn_region)
        except CaptureError as e:
            self.v_status.set(str(e))
            return
        self.cfg.turn_color = mean_rgb(frame)
        self.v_turn.set("color")
        self._apply(save=True)
        self.v_turn_info.set(self._turn_info())
        self.v_status.set(f"Learned 'my turn' color {self.cfg.turn_color}")

    def _test_turn(self) -> None:
        self._apply(save=False)
        try:
            r = self.engine.turn.check()
        except Exception as e:
            self.v_status.set(f"Turn check failed: {e}")
            return
        self.v_turn_state.set({True: "YES", False: "no", None: "not checked"}[r])
        self.v_status.set("Turn check: " + {True: "it IS your turn", False: "NOT your turn",
                                            None: "not configured (needs region + color/text)"}[r])

    # ---- actions --------------------------------------------------------
    def _toggle(self) -> None:
        if self._apply(save=True):
            self.engine.toggle()

    def _restart_admin(self) -> None:
        if winutil.relaunch_as_admin([]):
            self._close()
        else:
            self.v_status.set("Could not restart as Administrator (prompt declined?)")

    def _reset_used(self) -> None:
        self.engine.db.reset_used()
        self.v_status.set("Used-word cache cleared")

    def _refresh_preview(self) -> None:
        self._apply(save=False)
        try:
            frame = self.engine.capture.grab()
        except CaptureError as e:
            self.v_status.set(str(e))
            return
        self._set_img(self.lbl_frame, "frame", frame)
        try:
            res = self.engine.ocr.read(frame)
            self._set_img(self.lbl_proc, "proc", res.processed)
            self._show_read(res.text, res.confidence)
            self.v_status.set(f"Preview OCR: '{res.text}'" if res.text else "Preview: no letters found")
        except Exception as e:
            self.v_status.set(str(e))

    def _manual(self, type_it: bool) -> None:
        self._apply(save=False)
        text = self.e_manual.get().strip()
        if not text:
            return
        if type_it:
            self.v_status.set("Click the game's answer box now… typing in 3s")
            self.root.after(3000, lambda: self.engine.solve_manual(text, True))
        else:
            self.engine.solve_manual(text, False)

    # ---- state updates --------------------------------------------------
    def _set_img(self, label, key, img) -> None:
        photo = _to_photo(img)
        if photo is not None:
            self._photos[key] = photo
            label.config(image=photo)

    def _show_read(self, text: str, conf: float) -> None:
        self.v_letters.set(text or "-")
        self.v_conf.set(f"{conf:.0f}%" if text else "-")

    def _poll(self) -> None:
        latest = None
        try:
            while True:
                latest = self.q.get_nowait()
        except queue.Empty:
            pass
        if latest:
            s = latest
            self._show_read(s.letters, s.confidence)
            self.v_word.set((s.word + (" (corrected)" if s.corrected else "")) if s.word else "-")
            self.v_alt.set(", ".join(s.alternatives))
            self.v_status.set(s.status)
            if "Administrator" in s.status and not self._asked_admin:
                self._asked_admin = True
                if messagebox.askyesno(
                        "Administrator needed",
                        "Roblox is running as Administrator, so Windows blocks this tool's "
                        "keystrokes.\n\nRestart this tool as Administrator now?"):
                    self._restart_admin()
            self.v_turn_state.set({True: "YES", False: "no", None: "not checked"}[s.my_turn])
            self.btn.config(text=(f"Stop ({self.cfg.hotkey})" if self.engine.running
                                  else f"Start ({self.cfg.hotkey})"))
            if s.frame is not None and s.frame is not self._shown_frame:
                self._shown_frame = s.frame  # only redraw when OCR saw a new frame
                self._set_img(self.lbl_frame, "frame", s.frame)
                self._set_img(self.lbl_proc, "proc", s.processed)
        self.root.after(80, self._poll)

    def _close(self) -> None:
        self.hotkeys.stop()
        self.engine.stop()
        self._apply(save=True)
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main(cfg: Config | None = None) -> None:
    try:
        App(cfg or Config.load()).run()
    except Exception as e:  # pragma: no cover
        messagebox.showerror("Finish the Word Assistant", str(e))
        raise
