"""Word database and matching. Knows nothing about OCR or keyboards."""
from __future__ import annotations

import json
import random
import re
from bisect import bisect_left
from dataclasses import dataclass, field
from pathlib import Path

from .config import WORDLIST_PATH, Config

# Single-character OCR confusions used to rescue failed matches.
CONFUSIONS = {
    "i": "lj", "l": "ij", "o": "ce", "c": "oe", "e": "co", "u": "vn", "v": "uy",
    "n": "mu", "m": "n", "h": "b", "b": "hd", "d": "b", "g": "qa", "q": "g",
    "s": "z", "z": "s", "a": "o", "r": "n", "t": "f", "f": "t", "k": "x", "x": "k",
    "w": "v", "y": "v", "p": "b",
}
MODES = ("prefix", "contains", "suffix", "last_letter")
SELECTIONS = ("hard_ending", "reliable", "longest", "shortest", "random")
# Rarest word-final letters first (used by the "hard_ending" selection).
DEFAULT_ENDING_PRIORITY = "zxqjvkwfbygp"


@dataclass
class Solution:
    word: str | None
    query: str                      # what OCR gave us
    used_query: str = ""            # what actually matched (differs if corrected)
    corrected: bool = False         # OCR-error rescue was needed
    relaxed: bool = False           # commonness floor was lowered to find a word
    zipf: float = 0.0
    alternatives: list[str] = field(default_factory=list)


class WordDB:
    def __init__(
        self,
        path: Path = WORDLIST_PATH,
        extra: Path | None = None,
        blocklist: Path | None = None,
        used_path: Path | None = None,
    ):
        self.zipf: dict[str, float] = {}
        self._load_main(path)
        if extra:
            self._load_extra(extra)
        if blocklist and blocklist.exists():
            for line in blocklist.read_text(encoding="utf-8").splitlines():
                self.zipf.pop(line.strip().lower(), None)
        if not self.zipf:
            raise RuntimeError(f"Word list is empty or missing: {path}")

        self.alpha = sorted(self.zipf)
        self.rev = sorted(w[::-1] for w in self.alpha)
        self.used: set[str] = set()
        self.used_path = used_path
        self._load_used()

    # ---- loading --------------------------------------------------------
    def _load_main(self, path: Path) -> None:
        if not path.exists():
            raise FileNotFoundError(f"Word list not found: {path}")
        with path.open(encoding="utf-8") as f:
            for line in f:
                word, _, z = line.strip().partition("\t")
                if word:
                    try:
                        self.zipf[word] = float(z) if z else 0.0
                    except ValueError:
                        self.zipf[word] = 0.0

    def _load_extra(self, path: Path) -> None:
        """custom_words.txt: one word per line (optional 'word<TAB>zipf')."""
        if not path.exists():
            return
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip().lower()
            if not line or line.startswith("#"):
                continue
            word, _, z = line.partition("\t")
            if word.isalpha():
                self.zipf[word] = float(z) if z else max(self.zipf.get(word, 0.0), 3.0)

    # ---- used-word cache ------------------------------------------------
    def _load_used(self) -> None:
        if self.used_path and self.used_path.exists():
            try:
                self.used = set(json.loads(self.used_path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError, TypeError):
                self.used = set()

    def mark_used(self, word: str) -> None:
        self.used.add(word)
        if self.used_path:
            try:
                self.used_path.write_text(json.dumps(sorted(self.used)), encoding="utf-8")
            except OSError:
                pass

    def reset_used(self) -> None:
        self.used.clear()
        if self.used_path:
            try:
                self.used_path.write_text("[]", encoding="utf-8")
            except OSError:
                pass

    def __contains__(self, word: str) -> bool:
        return word.lower() in self.zipf

    def __len__(self) -> int:
        return len(self.alpha)

    # ---- raw matching ---------------------------------------------------
    def _candidates(self, q: str, mode: str) -> list[str]:
        if "_" in q:  # incomplete word: every '_' is exactly one letter
            rx = re.compile("^" + q.replace("_", "[a-z]") + "$")
            pool = self._prefix(q.split("_", 1)[0]) if not q.startswith("_") else self.alpha
            return [w for w in pool if len(w) == len(q) and rx.match(w)]
        if mode == "prefix":
            return self._prefix(q)
        if mode == "last_letter":
            return self._prefix(q[-1])
        if mode == "suffix":
            r = q[::-1]
            i = bisect_left(self.rev, r)
            out = []
            while i < len(self.rev) and self.rev[i].startswith(r):
                out.append(self.rev[i][::-1])
                i += 1
            return out
        if mode == "contains":
            return [w for w in self.alpha if q in w]
        raise ValueError(f"Unknown match mode: {mode}")

    def _prefix(self, p: str) -> list[str]:
        i = bisect_left(self.alpha, p)
        out = []
        while i < len(self.alpha) and self.alpha[i].startswith(p):
            out.append(self.alpha[i])
            i += 1
        return out

    def search(
        self,
        query: str,
        mode: str = "prefix",
        min_len: int = 1,
        max_len: int = 99,
        min_zipf: float = 0.0,
        exclude: set[str] | None = None,
    ) -> list[str]:
        """All matching words (unranked) passing the filters."""
        q = query.lower()
        if not q or not re.fullmatch(r"[a-z_]+", q):
            return []
        exclude = exclude or set()
        pattern = "_" in q
        out = []
        for w in self._candidates(q, mode):
            if w in exclude or self.zipf[w] < min_zipf:
                continue
            if not pattern:
                # Must actually extend the prompt, and respect length limits.
                if mode != "last_letter" and len(w) <= len(q):
                    continue
                if not (min_len <= len(w) <= max_len):
                    continue
            out.append(w)
        return out

    def rank(
        self,
        words: list[str],
        selection: str = "reliable",
        ending_priority: str = DEFAULT_ENDING_PRIORITY,
    ) -> list[str]:
        z = self.zipf
        if selection == "hard_ending":
            # Words ending in the rarest letters first (earlier in
            # `ending_priority` = rarer = better); ties go to the most common word.
            n = len(ending_priority)

            def score(w: str) -> int:
                i = ending_priority.find(w[-1])
                return n - i if i >= 0 else 0

            return sorted(words, key=lambda w: (-score(w), -z[w], len(w), w))
        if selection == "longest":
            return sorted(words, key=lambda w: (-len(w), -z[w], w))
        if selection == "shortest":
            return sorted(words, key=lambda w: (len(w), -z[w], w))
        ranked = sorted(words, key=lambda w: (-z[w], len(w), w))
        if selection == "random" and ranked:
            head = ranked[:25]
            random.shuffle(head)
            return head + ranked[25:]
        return ranked

    # ---- OCR-error rescue -----------------------------------------------
    @staticmethod
    def corrections(q: str, limit: int = 80):
        """Plausible fixes for a misread prompt, most likely first."""
        seen = {q}
        n = 0

        def emit(c):
            nonlocal n
            if c and c not in seen and n < limit:
                seen.add(c)
                n += 1
                return True
            return False

        for a, b in (("rn", "m"), ("m", "rn"), ("vv", "w"), ("w", "vv"), ("cl", "d")):
            if a in q:  # two glyphs read as one (or vice versa)
                c = q.replace(a, b, 1)
                if emit(c):
                    yield c
        for i, ch in enumerate(q):  # one confusable substitution
            for alt in CONFUSIONS.get(ch, ""):
                c = q[:i] + alt + q[i + 1:]
                if emit(c):
                    yield c
        if len(q) > 1:  # stray trailing / leading character
            for c in (q[:-1], q[1:]):
                if emit(c):
                    yield c

    # ---- high level -----------------------------------------------------
    def solve(
        self,
        query: str,
        cfg: Config | None = None,
        exclude: set[str] | None = None,
        allow_correction: bool = True,
    ) -> Solution:
        cfg = cfg or Config()
        q = query.strip().lower()
        sol = Solution(word=None, query=q)
        if not q or not re.fullmatch(r"[a-z_]+", q) or set(q) == {"_"}:
            return sol
        skip = set(self.used) | (exclude or set())

        def attempt(text: str):
            # Try with the commonness floor first, then without it.
            for floor, relaxed in ((cfg.min_zipf, False), (0.0, True)):
                hits = self.search(
                    text, cfg.match_mode, cfg.min_word_len, cfg.max_word_len, floor, skip
                )
                if hits:
                    return self.rank(hits, cfg.selection, cfg.ending_priority), relaxed
                if floor == 0.0:
                    break
            return [], False

        ranked, relaxed = attempt(q)
        used_q, corrected = q, False
        if not ranked and allow_correction:
            for fix in self.corrections(q):
                ranked, relaxed = attempt(fix)
                if ranked:
                    used_q, corrected = fix, True
                    break
        if ranked:
            sol.word = ranked[0]
            sol.used_query = used_q
            sol.corrected = corrected
            sol.relaxed = relaxed
            sol.zipf = self.zipf[ranked[0]]
            sol.alternatives = ranked[1:6]
        return sol


def load_db(cfg: Config) -> WordDB:
    return WordDB(
        path=WORDLIST_PATH,
        extra=cfg.resolve(cfg.extra_words_file),
        blocklist=cfg.resolve(cfg.blocklist_file),
        used_path=cfg.resolve(cfg.used_words_file) if cfg.persist_used_words else None,
    )
