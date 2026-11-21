"""Tile reader tests. Renders letter tiles from the bundled templates so no
screenshots need to live in the repo."""
import cv2
import numpy as np
import pytest

from finish_the_word.config import ROOT, Config
from finish_the_word.ocr import OCR
from finish_the_word.tiles import MASK, TileClassifier, find_tiles

TPL = ROOT / "data" / "letter_templates.npz"
pytestmark = pytest.mark.skipif(not TPL.exists(), reason="letter templates missing")


def make_tile(mask, size=81):
    """Draw a white rounded tile with a dark border and the letter body inside."""
    tile = np.full((size, size, 3), 255, np.uint8)
    cv2.rectangle(tile, (0, 0), (size - 1, size - 1), (0, 0, 0), 2)
    body = cv2.resize((mask * 255).astype(np.uint8), (size, size), interpolation=cv2.INTER_CUBIC)
    inset = int(size * 0.11)
    inner = np.full((size, size), 255, np.uint8)
    inner[body > 127] = 255
    edge = cv2.morphologyEx((body > 127).astype(np.uint8), cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8))
    tile[edge > 0] = (0, 0, 0)
    tile[:inset, :] = np.maximum(tile[:inset, :], 0)
    return tile


def row(letters, clf, bg=(180, 120, 60)):
    idx = {c: i for i, c in reversed(list(enumerate(clf.letters)))}
    tiles = [make_tile(clf.templates[idx[c]]) for c in letters]
    gap = 14
    w = len(tiles) * (81 + gap) + gap
    img = np.zeros((81 + 40, w, 3), np.uint8)
    img[:] = bg
    for i, t in enumerate(tiles):
        img[20:101, gap + i * (81 + gap): gap + i * (81 + gap) + 81] = t
    return img


@pytest.fixture(scope="module")
def clf():
    return TileClassifier(TPL)


def test_templates_cover_alphabet(clf):
    assert set("abcdefghijklmnopqrstuvwxyz") <= set(clf.letters)
    assert clf.templates.shape[1:] == (MASK, MASK)


def test_every_letter_matches_itself(clf):
    for ch, tpl in zip(clf.letters, clf.templates):
        got, score, _ = clf.classify(tpl)
        assert got == ch and score > 0.95


def test_reads_rendered_row_and_ignores_other_text(clf):
    img = row("string", clf)
    res = OCR(Config()).read(img)
    assert res.text == "string" and res.confidence > 80


def test_scaled_and_blurred_row(clf):
    img = cv2.GaussianBlur(cv2.resize(row("quiz", clf), None, fx=1.4, fy=1.4), (5, 5), 0)
    assert OCR(Config()).read(img).text == "quiz"


def test_no_tiles_falls_back_to_text_ocr():
    flat = np.full((100, 300, 3), 40, np.uint8)
    assert find_tiles(flat) == []
    assert OCR(Config()).read(flat).text == ""
