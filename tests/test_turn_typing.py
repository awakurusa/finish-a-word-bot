import numpy as np

from finish_the_word import winutil
from finish_the_word.config import Config
from finish_the_word.dictionary import WordDB
from finish_the_word.engine import Engine
from finish_the_word.ocr import OCRResult
from finish_the_word.turn import TurnDetector, color_matches, mean_rgb
from finish_the_word.typer import Typer


def solid(rgb, size=(20, 30)):
    img = np.zeros((*size, 3), np.uint8)
    img[:, :] = rgb[::-1]          # BGR
    return img


def test_color_detector():
    assert mean_rgb(solid((10, 200, 30))) == [10, 200, 30]
    assert color_matches(solid((12, 195, 35)), [10, 200, 30], 45)
    assert not color_matches(solid((200, 40, 40)), [10, 200, 30], 45)


def test_turn_detector_modes_and_invert():
    cfg = Config()
    td = TurnDetector(cfg, capture=None, ocr=None)
    assert td.check() is None                       # not configured
    cfg.turn_check, cfg.turn_region, cfg.turn_color = "color", [0, 0, 10, 10], [10, 200, 30]
    assert td.enabled
    assert td.check(solid((10, 200, 30))) is True
    assert td.check(solid((200, 0, 0))) is False
    cfg.turn_invert = True
    assert td.check(solid((200, 0, 0))) is True


def test_turn_detector_text_mode():
    class FakeOCR:
        def read_text(self, img):
            return OCRResult(raw="  Your  Turn! ")
    cfg = Config()
    cfg.turn_check, cfg.turn_region, cfg.turn_text = "text", [0, 0, 9, 9], "your turn"
    assert TurnDetector(cfg, None, FakeOCR()).check(solid((0, 0, 0))) is True
    cfg.turn_text = "opponent"
    assert TurnDetector(cfg, None, FakeOCR()).check(solid((0, 0, 0))) is False


class FakeOCR:
    def __init__(self):
        self.text = "st"

    def read(self, f):
        return OCRResult(text=self.text, raw=self.text, confidence=95.0, processed=f[:, :, 0])


class FakeTyper:
    def __init__(self):
        self.typed = []

    def type_word(self, w):
        from finish_the_word.typer import TypeResult
        self.typed.append(w)
        return TypeResult(True)


def test_engine_waits_for_turn_then_answers_same_prompt():
    cfg = Config(); cfg.persist_used_words = False; cfg.retry_next_word = False
    db = WordDB(); typer = FakeTyper()
    eng = Engine(cfg, capture=object(), ocr=FakeOCR(), db=db, typer=typer,
                 turn=TurnDetector(cfg, None, None))
    f = np.full((40, 120, 3), 10, np.uint8)
    for i in range(5):                      # opponent's turn: never types
        eng.step(f, now=i * 0.1, turn=False)
    assert typer.typed == [] and "turn" in eng.state.status.lower()
    for i in range(4):                      # our turn begins
        eng.step(f, now=1 + i * 0.1, turn=True)
    assert len(typer.typed) == 1
    for i in range(3):                      # opponent again, then us, same letters
        eng.step(f, now=2 + i * 0.1, turn=False)
    for i in range(4):
        eng.step(f, now=3 + i * 0.1, turn=True)
    assert len(typer.typed) == 2


class RecordingKB:
    def __init__(self):
        self.events = []
    def click(self, x, y): self.events.append(("click", x, y))
    def press_char(self, c): self.events.append(("char", c))
    def press_key(self, k): self.events.append(("key", k))
    def press_enter(self): self.events.append(("enter",))


def make_typer(**kw):
    cfg = Config(); cfg.typing_delay = 0; cfg.pre_type_delay = 0
    for k, v in kw.items():
        setattr(cfg, k, v)
    t = Typer(cfg); t._kb = RecordingKB()
    return t


def test_typer_clicks_box_types_letters_and_enter():
    t = make_typer(input_pos=[500, 600])
    assert t.type_word("Zinc").ok
    assert t._kb.events == [("click", 500, 600), ("char", "z"), ("char", "i"),
                            ("char", "n"), ("char", "c"), ("enter",)]


def test_typer_focus_key_and_no_enter():
    t = make_typer(focus_key="/", press_enter=False)
    assert t.type_word("ab").ok
    assert t._kb.events == [("char", "/"), ("char", "a"), ("char", "b")]


def test_typer_reports_failures_instead_of_crashing():
    t = make_typer()
    t._kb.press_char = lambda c: (_ for _ in ()).throw(RuntimeError("blocked"))
    r = t.type_word("ab")
    assert not r.ok and "blocked" in r.message


def test_typer_auto_focuses_roblox(monkeypatch):
    t = make_typer()
    calls, fg = [], {"t": "Claude"}
    monkeypatch.setattr(winutil, "IS_WINDOWS", True)
    monkeypatch.setattr(winutil, "foreground_title", lambda: fg["t"])
    monkeypatch.setattr(winutil, "focus_click_points", lambda title: [])

    def focus(title):
        calls.append(title)
        fg["t"] = "Roblox"
        return True
    monkeypatch.setattr(winutil, "focus_window", focus)
    assert t.type_word("ab").ok and calls == ["Roblox"]
    fg["t"] = "Claude"
    monkeypatch.setattr(winutil, "focus_window", lambda title: False)
    r = t.type_word("ab")
    assert not r.ok and "Roblox" in r.message


def test_clicks_roblox_window_when_focus_switch_fails(monkeypatch):
    t = make_typer()
    state = {"fg": "Claude"}
    monkeypatch.setattr(winutil, "IS_WINDOWS", True)
    monkeypatch.setattr(winutil, "foreground_title", lambda: state["fg"])
    monkeypatch.setattr(winutil, "focus_window", lambda title: False)   # Windows refuses
    monkeypatch.setattr(winutil, "focus_click_points", lambda title: [(100, 10), (500, 400)])

    def click(x, y):
        t._kb.events.append(("click", x, y))
        if (x, y) == (500, 400):          # first spot misses, second activates Roblox
            state["fg"] = "Roblox"
    t._kb.click = click
    assert t.type_word("ab").ok
    assert t._kb.events[:2] == [("click", 100, 10), ("click", 500, 400)]
    assert ("click", 500, 400) in t._kb.events and t._kb.events[-3:] == [
        ("char", "a"), ("char", "b"), ("enter",)]


def test_no_click_when_already_focused_or_disabled(monkeypatch):
    t = make_typer()
    monkeypatch.setattr(winutil, "IS_WINDOWS", True)
    monkeypatch.setattr(winutil, "foreground_title", lambda: "Roblox")
    assert t.type_word("ab").ok
    assert not any(e[0] == "click" for e in t._kb.events)      # no answer box, no click
    t2 = make_typer(click_to_focus=False)
    monkeypatch.setattr(winutil, "foreground_title", lambda: "Claude")
    monkeypatch.setattr(winutil, "focus_window", lambda title: False)
    r = t2.type_word("ab")
    assert not r.ok and t2._kb.events == []


def test_default_backend_is_scancode_sendinput():
    assert Config().typing_backend == "sendinput"


def test_backend_names_and_hold_default():
    c = Config()
    assert c.key_hold >= 0.04            # Roblox needs keys held across a frame
    assert c.typing_backend in ("sendinput", "sendinput_vk", "pydirectinput", "pyautogui")


def test_refuses_to_claim_success_when_roblox_is_elevated(monkeypatch):
    t = make_typer()
    monkeypatch.setattr(winutil, "blocked_by_uipi", lambda title: True)
    r = t.type_word("ab")
    assert not r.ok and "Administrator" in r.message and t._kb.events == []


def test_uipi_check_is_false_off_windows():
    assert winutil.blocked_by_uipi("Roblox") is False
    assert winutil.is_admin() is False


def test_diagnose_is_safe_off_windows(capsys):
    from finish_the_word import diagnose
    assert diagnose.run(Config()) == 0
    assert "only works on Windows" in capsys.readouterr().out


def test_config_saves_only_non_defaults_and_defaults_propagate(tmp_path):
    from finish_the_word.config import CONFIG_VERSION
    path = tmp_path / "config.json"
    c = Config(); c.press_enter = False; c.region = [1, 2, 300, 100]
    c.save(path)
    import json
    data = json.loads(path.read_text())
    assert data == {"region": [1, 2, 300, 100], "press_enter": False, "config_version": CONFIG_VERSION}
    assert Config.load(path).press_enter is False


def test_old_config_with_stale_defaults_is_migrated(tmp_path):
    import json
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"typing_backend": "pyautogui", "typing_delay": 0.03,
                                "selection": "reliable", "min_confidence": 50.0,
                                "region": [5, 5, 50, 50], "press_enter": False}))
    c = Config.load(path)
    assert c.typing_backend == "sendinput" and c.selection == "hard_ending"
    assert c.region == [5, 5, 50, 50] and c.press_enter is False   # real choices kept


def test_current_version_config_keeps_explicit_choice(tmp_path):
    import json
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"config_version": 2, "typing_backend": "pyautogui"}))
    assert Config.load(path).typing_backend == "pyautogui"
