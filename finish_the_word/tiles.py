"""Tile-based reader for prompts drawn as separate white letter tiles.

Finish the Word draws each letter in its own white rounded tile with a hollow,
black-outlined glyph over a busy 3D background. Reading the strip as one line
of text fails, so we (1) find the tiles, (2) fill the outlined glyph solid,
(3) OCR every tile as a single character.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

WHITE_MIN = 225        # every channel above this = tile face
MIN_TILE = 28          # px, smaller blobs are ignored
MAX_ASPECT = 1.6


@dataclass
class Tile:
    x: int
    y: int
    w: int
    h: int
    face: np.ndarray        # BGR crop of the tile
    mask: np.ndarray | None = None    # normalised letter mask (see tile_mask)


def _boxes_for(img: np.ndarray, erode: int, white_min: int):
    white = (img.min(axis=2) > white_min).astype(np.uint8) * 255
    if erode > 0:
        white = cv2.erode(white, np.ones((2 * erode + 1, 2 * erode + 1), np.uint8))
    n, _lab, st, _c = cv2.connectedComponentsWithStats(white, connectivity=8)
    out = []
    for i in range(1, n):
        x, y, w, h, area = (int(v) for v in st[i])
        x, y, w, h = x - erode, y - erode, w + 2 * erode, h + 2 * erode  # undo erosion
        ew, eh = w - 2 * erode, h - 2 * erode   # size after erosion
        if w >= MIN_TILE and h >= MIN_TILE and area >= 0.5 * ew * eh:   # tiles are solid
            out.append((max(x, 0), max(y, 0), w, h))
    return out


def _square_score(boxes) -> int:
    """How many boxes look like same-sized square tiles."""
    sq = [b for b in boxes if 0.75 <= b[2] / b[3] <= 1.3]
    if not sq:
        return 0
    med = float(np.median([b[2] for b in sq]))
    return sum(1 for b in sq if abs(b[2] - med) <= 0.2 * med)


def _boxes(img: np.ndarray) -> list[tuple[int, int, int, int]]:
    # Soft edges (blur, rescaling) can fuse neighbouring tiles into one blob;
    # try increasing erosion and keep the cleanest set of square tiles.
    best, best_score = [], 0
    for erode in (0, 1, 2, 3, 5, 8):
        raw = _boxes_for(img, erode, WHITE_MIN)
        score = _square_score(raw)
        if score > best_score:
            best, best_score = raw, score
    raw = best
    if not raw:
        return []
    square = [b for b in raw if 0.75 <= b[2] / b[3] <= 1.3] or raw
    ys = np.median([b[1] for b in square])
    hs = np.median([b[3] for b in square])
    ws = np.median([b[2] for b in square])
    boxes = []
    for x, y, w, h in raw:
        if abs(y - ys) > hs * 0.35:           # not on the tile row (e.g. chat text)
            continue
        if w / ws > 1.5:                      # touching tiles -> split evenly
            gap = max(2, 0.17 * ws)
            k = max(2, int(round((w + gap) / (ws + gap))))
            piece = (w - gap * (k - 1)) / k
            for i in range(k):
                boxes.append((int(x + i * (piece + gap)), int(ys), int(piece), int(hs)))
        elif 0.75 <= w / ws <= 1.25 and 0.75 <= h / hs <= 1.25:
            boxes.append((x, int(ys), int(ws), int(hs)))
        # else: stray blob (chat text, partial tile) -> ignore
    boxes.sort()
    return boxes


MASK = 48          # normalised mask size used for template matching
_WORK = 96         # tile is resized to this before extracting the letter


def tile_mask(face_bgr: np.ndarray) -> np.ndarray | None:
    """Return the letter's white body as a MASK x MASK float image (0..1).

    The tile is normalised by *tile size* (not by letter bounding box), so
    every letter keeps its natural proportions and the result is independent
    of the Roblox UI scale.
    """
    if face_bgr.size == 0:
        return None
    face = cv2.resize(face_bgr, (_WORK, _WORK), interpolation=cv2.INTER_CUBIC)
    inset = int(_WORK * 0.11)             # drop the tile's own rounded border
    inner = face[inset:_WORK - inset, inset:_WORK - inset]
    gray = cv2.cvtColor(inner, cv2.COLOR_BGR2GRAY)
    _, ink = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY_INV)
    cnts, hier = cv2.findContours(ink, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    if hier is None or not len(cnts):
        return None
    hier = hier[0]

    def depth(i: int) -> int:
        d = 0
        while hier[i][3] != -1:
            i = hier[i][3]
            d += 1
        return d

    def root(i: int) -> int:
        while hier[i][3] != -1:
            i = hier[i][3]
        return i

    # The glyph is a thin black outline around a white body (nested rings).
    # Level 0 = outside edge of the outline, 1 = edge of the white body,
    # 2 = outer edge of a counter's outline (A, B, D, O ...), 3 = open counter.
    area_min = 0.015 * inner.shape[0] * inner.shape[1]
    keep = {i for i in range(len(cnts))
            if hier[i][3] == -1 and cv2.contourArea(cnts[i]) >= area_min}
    if not keep:
        return None
    body = np.zeros_like(ink)
    for i in sorted(range(len(cnts)), key=depth):
        if root(i) not in keep:
            continue
        d = depth(i) % 4
        if d == 1:
            cv2.drawContours(body, [cnts[i]], -1, 255, cv2.FILLED)
        elif d == 2:
            cv2.drawContours(body, [cnts[i]], -1, 0, cv2.FILLED)
    if int(body.sum()) == 0:
        return None
    out = np.zeros((_WORK, _WORK), np.uint8)
    out[inset:_WORK - inset, inset:_WORK - inset] = body
    return cv2.resize(out, (MASK, MASK), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0


def find_tiles(img_bgr: np.ndarray) -> list[Tile]:
    tiles = []
    for x, y, w, h in _boxes(img_bgr):
        face = img_bgr[y:y + h, x:x + w]
        tiles.append(Tile(x, y, w, h, face, tile_mask(face)))
    return tiles


# ---------------------------------------------------------------------------
# Template matching
# ---------------------------------------------------------------------------
_PAD = 4


class TileClassifier:
    """Matches tile masks against real letter templates from the game's font."""

    def __init__(self, path):
        data = np.load(path)
        self.letters = [str(c) for c in data["letters"]]
        self.templates = data["masks"].astype(np.float32)      # N x MASK x MASK
        c = _PAD
        self._core = [np.ascontiguousarray(t[c:MASK - c, c:MASK - c]) for t in self.templates]

    def classify(self, mask: np.ndarray) -> tuple[str, float, float]:
        """-> (letter, score 0..1, margin to the runner-up letter)."""
        q = cv2.copyMakeBorder(mask, _PAD, _PAD, _PAD, _PAD, cv2.BORDER_CONSTANT, value=0)
        best: dict[str, float] = {}
        for ch, core in zip(self.letters, self._core):
            s = float(cv2.matchTemplate(q, core, cv2.TM_CCOEFF_NORMED).max())
            if s > best.get(ch, -1.0):
                best[ch] = s
        ranked = sorted(best.items(), key=lambda kv: -kv[1])
        top, second = ranked[0], (ranked[1][1] if len(ranked) > 1 else 0.0)
        return top[0], top[1], top[1] - second
