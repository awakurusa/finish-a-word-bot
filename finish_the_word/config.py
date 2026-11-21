"""Central configuration (stored as config.json next to the project)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
WORDLIST_PATH = ROOT / "data" / "words.txt"


@dataclass
class Config:
    # ---- screen capture -------------------------------------------------
    # [left, top, width, height] in physical screen pixels.
    region: list = field(default_factory=lambda: [760, 380, 400, 110])
    # If True, `region` is measured from the top-left of the Roblox window's
    # client area instead of the screen (survives moving the window).
    region_relative_to_window: bool = False
    window_title: str = "Roblox"

    # ---- OCR ------------------------------------------------------------
    # auto = read separate letter tiles by template matching when tiles are
    # visible, else fall back to text OCR | tiles = tiles only | text = OCR only
    reader: str = "auto"
    tile_min_score: float = 0.75        # template match (0-1) needed per tile
    ocr_backend: str = "tesseract"      # "tesseract" | "easyocr" (text reader)
    tesseract_cmd: str = ""             # auto-detected on Windows if empty
    tesseract_psm: int = 7              # 7 = single line, 8 = single word
    ocr_scale: int = 3                  # upscale factor before OCR
    edge_trim: int = 3                  # px shaved off each edge (kills border lines)
    allow_blanks: bool = True           # read "_" / "-" as wildcard letters
    min_confidence: float = 40.0        # 0-100, below this nothing is typed
    min_letters: int = 1
    max_letters: int = 12

    # ---- dictionary -----------------------------------------------------
    # prefix | contains | suffix | last_letter
    # (a prompt containing "_" is always matched as a full-word pattern)
    match_mode: str = "prefix"
    # hard_ending (words ending in rare letters first) | reliable (most common
    # first) | longest | shortest | random
    selection: str = "hard_ending"
    # Rarest word-final letters first; used by "hard_ending".
    ending_priority: str = "zxqjvkwfbygp"
    min_word_len: int = 3
    max_word_len: int = 18
    min_zipf: float = 1.5               # commonness floor; relaxed if no match
    extra_words_file: str = "custom_words.txt"
    blocklist_file: str = "blocklist.txt"
    used_words_file: str = "used_words.json"
    persist_used_words: bool = True

    # ---- keyboard automation --------------------------------------------
    typing_backend: str = "pyautogui"   # "pyautogui" | "pydirectinput"
    input_pos: list | None = None       # [x, y] of the answer box; None = skip click
    focus_key: str = ""                 # e.g. "/" to focus Roblox chat
    typing_delay: float = 0.03          # seconds between keystrokes
    pre_type_delay: float = 0.08        # seconds after focusing the box
    press_enter: bool = True
    require_roblox_focus: bool = True   # refuse to type if Roblox isn't foreground
    dry_run: bool = False               # never press keys, only report

    # ---- main loop ------------------------------------------------------
    poll_interval: float = 0.15         # seconds between captures
    change_threshold: float = 2.0       # mean pixel diff that counts as "changed"
    stable_reads: int = 2               # identical consecutive reads required
    clear_reads: int = 3                # empty reads that re-arm the same prompt
    retry_after: float = 3.0            # seconds before trying another word
    retry_next_word: bool = True        # try another word if prompt doesn't change
    hotkey: str = "F8"                  # global start/stop toggle (Windows)

    # --------------------------------------------------------------------
    def save(self, path: Path = CONFIG_PATH) -> None:
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "Config":
        cfg = cls()
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return cfg
            known = {f.name for f in fields(cls)}
            for k, v in data.items():
                if k in known:
                    setattr(cfg, k, v)
        return cfg

    def resolve(self, name: str) -> Path:
        """Resolve a config-relative file name against the project root."""
        p = Path(name)
        return p if p.is_absolute() else ROOT / p
