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
| `ocr.py` | Reads the prompt: letter tiles first (`tiles.py`), else Tesseract/EasyOCR text OCR; cleans up mistakes |
| `tiles.py` | Finds the game's white letter tiles and identifies each letter by template matching |
| `dictionary.py` | Matches letters against a ~215,000-word list, ranks, caches used words |
| `typer.py` | Makes Roblox the active window (clicking it if needed), types the word, presses Enter |
| `engine.py` | Ties them together; only acts when the prompt actually changes |
| `gui.py` | Control panel: start/stop, preview, readouts, manual test, region picker |

> **Heads-up:** automating gameplay can violate Roblox's Terms of Use or an individual game's rules and may get an account moderated. Use it at your own risk, ideally in private servers / for testing.

## Install (Windows 10/11)

1. **Python 3.10+** from <https://www.python.org/downloads/> (tick *Add Python to PATH*; keep the default *tcl/tk* option so the GUI works).
2. **Tesseract OCR**: install the Windows build from <https://github.com/UB-Mannheim/tesseract/wiki>. The default path `C:\Program Files\Tesseract-OCR\tesseract.exe` is auto-detected; otherwise set `tesseract_cmd` in `config.json`.
3. Clone and install:

```powershell
git clone https://github.com/awakurusa/finish-a-word-bot.git
cd finish-a-word-bot
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

4. Run: `python -m finish_the_word`

## Setup walkthrough

1. Open Roblox in **windowed or borderless-fullscreen** mode (true exclusive fullscreen can't be captured reliably) and get to a round where the letter prompt is visible.
2. In the control panel click **Select region…** and drag a box around *only* the letter prompt: no usernames, chat, or timers. A little padding is fine.
3. Click **Refresh preview**. The top image is what was captured; the bottom is what the OCR engine sees. *Detected letters* and *Confidence* update below. Adjust the box until the letters read cleanly.
4. Finish the Word has no answer box: you just type. Leave **Pick** alone (it's only for games that have a box). Before typing, the bot makes Roblox the active window by itself: it asks Windows first and, if that's refused, **clicks the Roblox window** (its title bar, or a harmless spot at the top of the game view). Set `click_to_focus` to `false` to disable the click, or `focus_click_pos` (`[x, y]`) to choose the spot.
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

## How letters are read

Finish the Word draws each letter as a separate white tile with a thin black outline. Generic text OCR is unreliable on that, so the default `reader: "auto"` does this instead:

1. find the white tiles in your capture region (works across UI scales and slight blur),
2. extract each letter's shape and compare it with `data/letter_templates.npz`, templates taken from real game screenshots (all 26 letters),
3. fall back to Tesseract/EasyOCR text reading only if no tiles are found.

In the OCR preview the second image shows the detected tiles: green box = recognised, red = unknown (treated as a blank `_`). If your game uses a different skin or font, rebuild the templates from your own screenshots of a tile row:

```powershell
python tools/build_templates.py row1.png GABCDEFGHIJKLMNOP row2.png QRSTUVWXYZ
```

(each image followed by its letters left-to-right). Set `reader` to `tiles` or `text` to force one method, and lower `tile_min_score` (default 0.75) if real letters show up red.

## Fully automatic play: knowing it's your turn

Without a turn check the bot answers whenever it can read a prompt. To make it answer **only on your turn**, point it at whatever the game shows when it's your turn (a "Your turn" label, a glowing/colored bar, your name highlighted, a prompt that only appears on your turn):

1. Wait until it is **not** your turn. Click **Select turn indicator…** and drag a box tightly around that indicator's spot.
2. When it **is** your turn, click **Learn 'my turn' color** (color mode), or set *Turn check* to `text` and type the words the game shows (e.g. `your turn`).
3. Click **Test turn check now** on both kinds of turn: it should say YES on yours and no otherwise. The "Your turn" line in the Status box shows the live result.
4. If the indicator *disappears* on your turn, tick **Act when indicator is absent**.

While it isn't your turn the bot keeps watching but never types, and it re-arms automatically so it answers again when your turn comes back with the same letters. Then just press **Start** (or F8) and leave it running.

## If Roblox is running as Administrator

The tool restarts itself as Administrator automatically when it sees Roblox running that way (accept the Windows prompt), and the control panel has a **Restart as admin** button. Windows silently discards keystrokes and clicks sent by a normal program to an Administrator program. Then everything *looks* fine (the status says "Typed") but Roblox never receives anything. Fix: run this tool as Administrator too.

* Double-click **`run_as_admin.bat`** (accept the Windows prompt), or
* open PowerShell as Administrator and run `.venv\Scripts\python -m finish_the_word`, or
* from a normal window: `.venv\Scripts\python -m finish_the_word --admin`.

The tool now detects this situation and reports it in the Status line instead of saying "Typed". If you'd rather not use admin mode, start Roblox normally (not "Run as administrator") and leave the tool as it is.

## If nothing gets typed in Roblox

Run `.venv\\Scripts\\python -m finish_the_word --diagnose` (as Administrator if Roblox is) and send the printed report: it shows whether Roblox is elevated, whether Windows accepts the keys, and whether the Roblox window is found and focused.

**Run the typing test first.** It tries every input method, each typing a different letter, so you can see which one your Roblox accepts:

```powershell
.venv\Scripts\python -m finish_the_word --test-keys
```

It waits 5 seconds, brings Roblox to the front and types `aaaa` (scan codes), `bbbb` (virtual keys + scan codes), `cccc` (pydirectinput), `dddd` (pyautogui). Put Roblox somewhere the typed letters are visible (e.g. the chat box). Whichever letters appear are the methods that work; set `typing_backend` in `config.json` to that method's name (`sendinput`, `sendinput_vk`, `pydirectinput`, `pyautogui`). To check the tool itself works, run it against Notepad: `--test-keys --window Notepad`. If it works in Notepad but not Roblox, the game is rejecting that input type or is running elevated (run PowerShell as Administrator).

If keys sometimes register and sometimes don't, raise `key_hold` (default `0.05`, seconds each key stays down) and `typing_delay` (default `0.04`) in `config.json`; Roblox only reads keys once per frame, so very short presses can be missed on low FPS.

Look at the **Status** line in the panel after a word is chosen; it says exactly what happened.

* *"Could not switch to the 'Roblox' window"*: Roblox isn't open or its window title differs; set `window_title`.
* *"SendInput was blocked"*: Roblox is running as Administrator. Run the terminal/PowerShell as Administrator too.
* *"Typed 'word'" but nothing appears*: Roblox had focus but ignored the keys. Make sure no chat box is capturing input, and if your game needs a key to start typing, set `focus_key` (e.g. `"/"`). Try **Find & type (3s)** to test typing alone.
* *"[dry run] would type"*: untick **Dry run**.
* Roblox must be windowed or borderless; screen capture and clicks don't work in exclusive fullscreen.

## Command line helpers

```powershell
python -m finish_the_word --solve ST              # dictionary only
python -m finish_the_word --solve ion --mode suffix
python -m finish_the_word --ban still stalk        # never suggest these again (saved to blocklist.txt)
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
| `reader` | `auto` | `auto` (letter tiles, else text OCR), `tiles`, or `text` |
| `min_confidence` | `40` | OCR confidence (0–100) required before typing |
| `stable_reads` | `2` | Identical consecutive reads required (rejects half-animated text) |
| `match_mode` | `prefix` | See above |
| `selection` | `hard_ending` | `hard_ending` (words ending in rare letters like z, x, q first; most common among equals), `reliable` (most common word), `longest`, `shortest`, `random` |
| `ending_priority` | `zxqjvkwfbygp` | Final letters ranked rarest-first for `hard_ending` |
| `min_word_len` / `max_word_len` | `3` / `18` | Answer length limits |
| `min_zipf` | `1.5` | Commonness floor (about 1 in 30M words); relaxed automatically if nothing matches |
| `typing_delay` | `0.04` | Seconds between keystrokes |
| `press_enter` | `true` | Submit with Enter |
| `skip_prompt_letters`| `true` | `prefix` mode: don't retype the prompt letters the game already shows (`st` → `still` types `ill`). `false` = type the whole word |
| `typing_backend` | `sendinput` | Hardware scan-code input. Alternatives: `sendinput_vk`, `pydirectinput`, `pyautogui` (find yours with `--test-keys`) |
| `key_hold` | `0.05` | Seconds each key stays pressed; raise if letters get dropped |
| `auto_focus_roblox` | `true` | Bring the Roblox window to the front before typing |
| `turn_check` | `none` | `none`, `color` or `text`: how the bot knows it's your turn (see below) |
| `turn_region` / `turn_color` / `turn_text` | | Indicator region, learned color, or keyword (e.g. `your turn`) |
| `turn_invert` | `false` | Act when the indicator is *absent* |
| `ocr_backend` | `tesseract` | Or `easyocr` (`pip install easyocr`, heavier) |
| `retry_after` | `1.5` | If the same prompt is still showing this many seconds after the word was typed, assume the game refused it (e.g. an opponent already used it) and try the next-best word |
| `auto_ban_rejected` | `false` | Also ban the refused word permanently. Only for games that refuse *invalid* words; leave off if refusals are words opponents already used |
| `clear_before_retry` | `true` | The game leaves a refused word in the box, so whenever the bot types again for the same prompt (even if the prompt flickered away and back) it presses Backspace once per letter it typed first. Set `false` if your game clears the box itself |
| `erase_delay` | `0.06` | Seconds between Backspace presses |
| `erase_pause` | `0.4` | Pause after erasing, before typing the next word, so the game registers the deletion |
| `erase_window` | `30.0` | Only erase if the leftover word was typed within this many seconds; later than that it is a new turn with an empty box |
| `hotkey` | `F8` | Global start/stop key |

## How the pieces behave

* **Performance:** each poll compares a tiny thumbnail of the region; OCR only runs when pixels change. Typing happens once per prompt, and the same prompt is not answered again until it changes (or disappears and reappears, or `retry_after` elapses).
* **Word database:** `data/words.txt` merges two large public dictionaries (web2 + GCIDE), keeps lowercase entries only (no proper nouns), drops vowel-less abbreviations and invalid two-letter strings, and ranks every word by real-world frequency (via `wordfreq`) so the most widely-known valid word is preferred. Add your own words in `custom_words.txt` (one per line) and ban words in `blocklist.txt`. If the game rejects a word, click **Ban last word** in the control panel or run `--ban WORD`; it is removed immediately and written to `blocklist.txt` (turn on `auto_ban_rejected` to do this automatically). Regenerate the list with `python tools/build_wordlist.py` (needs `requirements-dev.txt`).
* **Used-word cache:** answered words are remembered (`used_words.json`) so they aren't repeated; **Reset used words** clears it.
* **OCR mistakes:** letters are normalised (`5→s`, `0→o`, `|→l`…); flat frames are ignored; if no word matches, plausible misreads are tried (`rn→m`, `i↔l`, stray edge characters). Low-confidence reads are never typed.

## Troubleshooting

* *"Tesseract executable not found"*: install it and/or set `tesseract_cmd`.
* *Wrong letters / low confidence*: tighten the region, make sure no other text is inside it, and compare the two preview images. Try `tesseract_psm: 8`, a larger `ocr_scale`, or `ocr_backend: easyocr`.
* *Preview is black*: Roblox is in exclusive fullscreen; switch to windowed/borderless.
* *Region is offset on high-DPI displays*: the app enables DPI awareness itself; use **Select region…** rather than typing numbers.
* Multi-monitor: **Select region…** covers the primary monitor only; enter coordinates manually for other monitors.

## Development

```powershell
pip install -r requirements-dev.txt
python -m pytest
```

Tests cover dictionary matching, OCR on synthetic prompts (needs Tesseract; skipped if missing) and the engine loop with fake capture/OCR/typing.
