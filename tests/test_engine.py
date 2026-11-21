"""Workflow tests with fake capture/OCR/typer: change detection, no duplicate typing."""
import numpy as np
import pytest

from finish_the_word.config import Config
from finish_the_word.dictionary import WordDB
from finish_the_word.engine import Engine
from finish_the_word.ocr import OCRResult
from finish_the_word.typer import TypeResult, Typer


class FakeOCR:
    def __init__(self):
        self.text, self.conf, self.calls = "", 90.0, 0

    def read(self, frame):
        self.calls += 1
        return OCRResult(text=self.text, raw=self.text, confidence=self.conf, processed=frame[:, :, 0])


class FakeTyper:
    def __init__(self, ok=True):
        self.typed, self.skips, self.erases, self.ok = [], [], [], ok
        self.last_typed_len = 0

    def type_word(self, word, skip=0, erase=0):
        self.typed.append(word)
        self.skips.append(skip)
        self.erases.append(erase)
        self.last_typed_len = len(word) - skip
        return TypeResult(self.ok, "typed" if self.ok else "no focus")


@pytest.fixture(scope="module")
def db():
    return WordDB()


def make(db, **kw):
    cfg = Config()
    cfg.persist_used_words = False
    cfg.stable_reads = 2
    for k, v in kw.items():
        setattr(cfg, k, v)
    ocr, typer = FakeOCR(), FakeTyper()
    db.used.clear()
    eng = Engine(cfg, capture=object(), ocr=ocr, db=db, typer=typer)
    return eng, ocr, typer


def frame(v):
    return np.full((40, 120, 3), v, np.uint8)


def test_types_once_per_prompt_and_waits_for_change(db):
    eng, ocr, typer = make(db, retry_next_word=False)
    ocr.text = "st"
    for i in range(6):
        eng.step(frame(10), now=i * 0.1)
    assert len(typer.typed) == 1 and typer.typed[0].startswith("st")
    # prompt changes -> new answer
    ocr.text = "th"
    for i in range(4):
        eng.step(frame(200), now=1 + i * 0.1)
    assert len(typer.typed) == 2 and typer.typed[1].startswith("th")


def test_unchanged_frames_skip_ocr(db):
    eng, ocr, typer = make(db)
    ocr.text = "st"
    for i in range(10):
        eng.step(frame(10), now=i * 0.1)
    assert ocr.calls == 1


def test_requires_stable_reads(db):
    eng, ocr, typer = make(db, stable_reads=3)
    ocr.text = "st"
    eng.step(frame(10), now=0)
    eng.step(frame(10), now=0.1)
    assert typer.typed == []
    eng.step(frame(10), now=0.2)
    assert len(typer.typed) == 1


def test_low_confidence_never_types(db):
    eng, ocr, typer = make(db)
    ocr.text, ocr.conf = "st", 20.0
    for i in range(5):
        eng.step(frame(10), now=i)
    assert typer.typed == []
    assert "Low confidence" in eng.state.status


def test_retry_picks_a_different_word(db):
    eng, ocr, typer = make(db, retry_after=3.0)
    ocr.text = "st"
    for i in range(3):
        eng.step(frame(10), now=i * 0.1)
    for i in range(3):  # prompt still showing 3.5s later
        eng.step(frame(10), now=3.5 + i * 0.1)
    assert len(typer.typed) == 2 and typer.typed[0] != typer.typed[1]


def test_same_prompt_again_after_clear(db):
    eng, ocr, typer = make(db, retry_next_word=False)
    ocr.text = "st"
    for i in range(3):
        eng.step(frame(10), now=i * 0.1)
    ocr.text = ""
    for i in range(4):
        eng.step(frame(90), now=1 + i * 0.1)
    ocr.text = "st"
    for i in range(3):
        eng.step(frame(10), now=2 + i * 0.1)
    assert len(typer.typed) == 2 and typer.typed[0] != typer.typed[1]


def test_typing_failure_retries_next_poll(db):
    eng, ocr, typer = make(db)
    typer.ok = False
    ocr.text = "st"
    for i in range(4):
        eng.step(frame(10), now=i * 0.1)
    assert len(typer.typed) >= 2  # not marked as submitted
    assert not db.used


def test_no_match_is_graceful(db):
    eng, ocr, typer = make(db, retry_next_word=False)
    ocr.text = "qqqqqqqqq"
    for i in range(4):
        eng.step(frame(10), now=i * 0.1)
    assert typer.typed == []
    assert "No word found" in eng.state.status


def test_manual_solve_dry_run(db):
    eng, ocr, typer = make(db)
    sol = eng.solve_manual("Pre", type_it=True)
    assert sol.word and sol.word.startswith("pre") and typer.typed == [sol.word]


def test_typer_dry_run_and_validation():
    cfg = Config()
    cfg.dry_run = True
    t = Typer(cfg)
    assert t.type_word("apple").ok
    assert not t.type_word("").ok
    assert not t.type_word("ap ple").ok


def test_skips_prompt_letters_already_shown_in_prefix_mode(db):
    eng, ocr, typer = make(db, retry_next_word=False)
    ocr.text = "st"
    for i in range(4):
        eng.step(frame(10), now=i * 0.1)
    assert typer.typed[0].startswith("st") and typer.skips == [2]


def test_types_whole_word_when_skip_disabled_or_not_prefix_mode(db):
    eng, ocr, typer = make(db, retry_next_word=False, skip_prompt_letters=False)
    ocr.text = "st"
    for i in range(4):
        eng.step(frame(10), now=i * 0.1)
    assert typer.skips == [0]

    eng, ocr, typer = make(db, retry_next_word=False, match_mode="suffix")
    ocr.text = "ion"
    for i in range(4):
        eng.step(frame(10), now=i * 0.1)
    assert typer.skips == [0]


def test_blank_pattern_types_whole_word(db):
    eng, ocr, typer = make(db, retry_next_word=False)
    ocr.text = "ap__e"
    for i in range(4):
        eng.step(frame(10), now=i * 0.1)
    assert typer.typed and typer.skips == [0]


def _fresh_db(tmp_path):
    words = tmp_path / "words.txt"
    words.write_text("stand\t4.0\nstill\t5.0\nstick\t4.5\n", encoding="utf-8")
    return WordDB(path=words, blocklist=tmp_path / "blocklist.txt")


def _run(eng, ocr, text, t0, n=4):
    ocr.text = text
    for i in range(n):
        eng.step(frame(10), now=t0 + i * 0.1)


def test_ban_last_word_never_suggested_again(tmp_path):
    db = _fresh_db(tmp_path)
    eng, ocr, typer = make(db, retry_next_word=False, selection="reliable")
    _run(eng, ocr, "st", 0)
    assert typer.typed == ["still"]
    assert eng.ban_last_word().startswith("Banned 'still' and saved")
    assert "still" not in db
    eng2, ocr2, typer2 = make(db, retry_next_word=False, selection="reliable")
    _run(eng2, ocr2, "st", 0)
    assert typer2.typed == ["stick"]


def test_auto_ban_rejected_only_when_enabled(tmp_path):
    for flag, banned in ((True, True), (False, False)):
        folder = tmp_path / f"flag_{flag}"
        folder.mkdir()
        db = _fresh_db(folder)
        eng, ocr, typer = make(db, selection="reliable", auto_ban_rejected=flag, retry_after=3.0)
        _run(eng, ocr, "st", 0)               # types "still", prompt never changes
        _run(eng, ocr, "st", 5, n=1)          # 5s later: retry with the next word
        assert typer.typed[0] == "still" and typer.typed[1] != "still"
        assert (("still" not in db) is banned)


def test_ban_message_names_the_file_and_reports_failures(tmp_path):
    db = _fresh_db(tmp_path)
    eng, ocr, typer = make(db, retry_next_word=False)
    assert "No word to ban" in eng.ban_last_word()
    _run(eng, ocr, "st", 0)
    msg = eng.ban_last_word()
    assert str(tmp_path / "blocklist.txt") in msg and "saved" in msg

    (tmp_path / "x").mkdir()
    db2 = _fresh_db(tmp_path / "x")
    (tmp_path / "x" / "blocklist.txt").mkdir()
    eng2, ocr2, _ = make(db2, retry_next_word=False)
    _run(eng2, ocr2, "st", 0)
    assert "could not save" in eng2.ban_last_word()


def test_retry_clock_starts_after_typing_finishes(db):
    import time

    class SlowTyper(FakeTyper):
        def type_word(self, word, skip=0, erase=0):
            time.sleep(0.3)                      # typing itself takes 0.3 s
            return super().type_word(word, skip, erase)

    eng, ocr, _ = make(db, retry_after=0.2)
    eng.typer = typer = SlowTyper()
    _run(eng, ocr, "st", 0)                      # types once (takes 0.3 s)
    n = len(typer.typed)
    eng.step(frame(10), now=0.45)                # only 0.15 s after typing ended
    assert len(typer.typed) == n                 # too early to call it refused
    eng.step(frame(10), now=0.75)                # 0.45 s after typing ended
    assert len(typer.typed) == n + 1             # now it tries the next word


def test_retry_erases_what_the_previous_attempt_typed(db):
    eng, ocr, typer = make(db, selection="reliable", retry_after=1.0)
    _run(eng, ocr, "st", 0)                      # first word, prompt "st" skipped
    first_len = typer.last_typed_len
    assert first_len > 0 and typer.erases == [0]
    eng.step(frame(10), now=2.0)                 # prompt unchanged: refused -> retry
    assert typer.erases == [0, first_len]


def test_retry_does_not_erase_when_disabled(db):
    eng, ocr, typer = make(db, selection="reliable", retry_after=1.0, clear_before_retry=False)
    _run(eng, ocr, "st", 0)
    eng.step(frame(10), now=2.0)
    assert typer.erases == [0, 0]

    
def test_partial_typing_failure_is_cleaned_before_retry(db):
    class PartialFailureTyper(FakeTyper):
        def type_word(self, word, skip=0, erase=0):
            self.typed.append(word)
            self.skips.append(skip)
            self.erases.append(erase)
            if len(self.typed) == 1:
                self.last_typed_len = 2  # only two characters reached the game
                return TypeResult(False, "simulated mid-word failure")
            self.last_typed_len = len(word) - skip
            return TypeResult(True, "typed")

    eng, ocr, _ = make(
        db, selection="reliable", poll_interval=0.15, clear_before_retry=False
    )
    eng.typer = typer = PartialFailureTyper()
    _run(eng, ocr, "st", 0)
    assert len(typer.typed) == 1
    eng.step(frame(10), now=0.4)  # failure backoff has not elapsed
    assert len(typer.typed) == 1
    eng.step(frame(10), now=0.8)
    assert len(typer.typed) == 2
    assert typer.typed[0] == typer.typed[1]  # failed injection retries same word
    assert typer.erases == [0, 2]            # remove only the two confirmed chars
