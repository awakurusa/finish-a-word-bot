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
        self.typed, self.skips, self.ok = [], [], ok

    def type_word(self, word, skip=0):
        self.typed.append(word)
        self.skips.append(skip)
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
