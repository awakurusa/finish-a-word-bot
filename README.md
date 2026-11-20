# Finish the Word Assistant

A Windows tool for the Roblox game **Finish the Word**. It watches a region of your screen, reads the letter prompt with OCR, finds a matching English word, and types it into the game.

```
screen region ──► capture.py ──► ocr.py ──► dictionary.py ──► typer.py ──► game
                       └────────── engine.py (loop, change detection) ──────────┘
                                         gui.py (control panel)
```

| Module | Job |
| --- | --- |
| `capture.py` | Grabs the configured region (optionally relative to the Roblox window) |
| `ocr.py` | Preprocesses the image, runs Tesseract/EasyOCR, cleans up OCR mistakes |
| `dictionary.py` | Matches letters against a ~215,000-word list, ranks, caches used words |
| `typer.py` | Focuses the answer box, types the word, presses Enter |
| `engine.py` | Ties them together; only acts when the prompt actually changes |
| `gui.py` | Control panel: start/stop, preview, readouts, manual test, region picker |

> **Heads-up:** automating gameplay can violate Roblox's Terms of Use or an individual game's rules and may get an account moderated. Use it at your own risk, ideally in private servers / for testing.

## Install (Windows 10/11)

1. **Python 3.10+** from <https://www.python.org/downloads/> (tick *Add Python to PATH*; keep the default *tcl/tk* option so the GUI works).
2. **Tesseract OCR**: install the Windows build from <https://github.com/UB-Mannheim/tesseract/wiki>. The default path `C:\Program Files\Tesseract-OCR\tesseract.exe` is auto-detected; otherwise set `tesseract_cmd` in `config.json`.
3. Clone and install:

```powershell
git clone https://github.com/<your-username>/finish-the-word-bot.git
cd finish-the-word-bot
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

4. Run: `python -m finish_the_word`

## Setup walkthrough

1. Open Roblox in **windowed or borderless-fullscreen** mode (true exclusive fullscreen can't be captured reliably) and get to a round where the letter prompt is visible.
2. In the control panel click **Select region…** and drag a box around *only* the letter prompt: no usernames, chat, or timers. A little padding is fine.
3. Click **Refresh preview**. The top image is what was captured; the bottom is what the OCR engine sees. *Detected letters* and *Confidence* update below. Adjust the box until the letters read cleanly.
4. Click **Pick (hover box, 3s)** and hover over the game's answer box. It will be clicked before each answer. If the game focuses the box automatically, or you use a chat key, leave it unset and set `focus_key` (e.g. `"/"`) in `config.json`.
5. Choose **Match mode** (see below) and tick **Dry run** for a first test: it shows the word it *would* type without pressing keys.
6. Untick Dry run, click **Start** (or press **F8** from inside the game) and press **F8** again to stop. Moving the mouse into a screen corner also aborts PyAutoGUI.

The bot refuses to type unless the Roblox window is in the foreground (`require_roblox_focus`).

### Match modes

I couldn't verify exactly how the game words its prompts, so this is configurable:

| Mode | Prompt `st` finds… |
| --- | --- |
| `prefix` (default) | words **starting** with it: *still*, *state* |
| `contains` | words containing it anywhere |
| `suffix` | words **ending** with it |
| `last_letter` | words starting with the prompt's **last** letter (chain games) |

If the prompt contains blanks (`ap__e`, `ap--e`), it is matched as a full-word pattern where every `_` is one letter, regardless of mode.

## Command line helpers

```powershell
python -m finish_the_word --solve ST              # dictionary only
python -m finish_the_word --solve ion --mode suffix
python -m finish_the_word --ocr-image prompt.png  # OCR only, on a screenshot
python -m finish_the_word --preview               # save the capture region to preview.png
python -m finish_the_word --cli --dry-run         # headless loop
```

## Configuration (`config.json`)

Created when you first save settings from the GUI. Key options:

| Key | Default | Meaning |
| --- | --- | --- |
| `region` | `[760,380,400,110]` | `[left, top, width, height]` in pixels |
| `region_relative_to_window` | `false` | Measure from the Roblox window's top-left |
| `min_confidence` | `40` | OCR confidence (0–100) required before typing |
| `stable_reads` | `2` | Identical consecutive reads required (rejects half-animated text) |
| `match_mode` | `prefix` | See above |
| `selection` | `hard_ending` | `hard_ending` (words ending in rare letters like z, x, q first; most common among equals), `reliable` (most common word), `longest`, `shortest`, `random` |
| `ending_priority` | `zxqjvkwfbygp` | Final letters ranked rarest-first for `hard_ending` |
| `min_word_len` / `max_word_len` | `3` / `18` | Answer length limits |
| `min_zipf` | `1.5` | Commonness floor (about 1 in 30M words); relaxed automatically if nothing matches |
| `typing_delay` | `0.03` | Seconds between keystrokes |
| `press_enter` | `true` | Submit with Enter |
| `typing_backend` | `pyautogui` | Use `pydirectinput` if Roblox ignores keystrokes (`pip install pydirectinput`) |
| `ocr_backend` | `tesseract` | Or `easyocr` (`pip install easyocr`, heavier) |
| `retry_after` | `3.0` | If the same prompt is still showing after this many seconds, try the next-best word |
| `hotkey` | `F8` | Global start/stop key |

## How the pieces behave

* **Performance:** each poll compares a tiny thumbnail of the region; OCR only runs when pixels change. Typing happens once per prompt, and the same prompt is not answered again until it changes (or disappears and reappears, or `retry_after` elapses).
* **Word database:** `data/words.txt` merges two large public dictionaries (web2 + GCIDE), keeps lowercase entries only (no proper nouns), drops vowel-less abbreviations and invalid two-letter strings, and ranks every word by real-world frequency (via `wordfreq`) so the most widely-known valid word is preferred. Add your own words in `custom_words.txt` (one per line) and ban words in `blocklist.txt`. Regenerate the list with `python tools/build_wordlist.py` (needs `requirements-dev.txt`).
* **Used-word cache:** answered words are remembered (`used_words.json`) so they aren't repeated; **Reset used words** clears it.
* **OCR mistakes:** letters are normalised (`5→s`, `0→o`, `|→l`…); flat frames are ignored; if no word matches, plausible misreads are tried (`rn→m`, `i↔l`, stray edge characters). Low-confidence reads are never typed.

## Troubleshooting

* *"Tesseract executable not found"*: install it and/or set `tesseract_cmd`.
* *Wrong letters / low confidence*: tighten the region, make sure no other text is inside it, and compare the two preview images. Try `tesseract_psm: 8`, a larger `ocr_scale`, or `ocr_backend: easyocr`.
* *Nothing is typed in Roblox*: set `typing_backend` to `pydirectinput`; run the terminal as Administrator if Roblox runs elevated.
* *Preview is black*: Roblox is in exclusive fullscreen; switch to windowed/borderless.
* *Region is offset on high-DPI displays*: the app enables DPI awareness itself; use **Select region…** rather than typing numbers.
* Multi-monitor: **Select region…** covers the primary monitor only; enter coordinates manually for other monitors.

## Development

```powershell
pip install -r requirements-dev.txt
python -m pytest
```

Tests cover dictionary matching, OCR on synthetic prompts (needs Tesseract; skipped if missing) and the engine loop with fake capture/OCR/typing.
