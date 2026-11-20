"""Regenerate data/words.txt (word<TAB>zipf-frequency, most common first).

Sources (dev-time only, NOT needed to run the bot):
    pip install english-words wordfreq

Filters: lowercase alphabetic only, no proper nouns (entries that only exist
capitalised), no vowel-less abbreviations, 2-letter words limited to the
standard valid set.  Frequency is used purely for ranking.
"""
from pathlib import Path

from english_words import get_english_words_set
from wordfreq import zipf_frequency

OUT = Path(__file__).resolve().parent.parent / "data" / "words.txt"

VALID_2 = set(
    "aa ab ad ae ag ah ai al am an ar as at aw ax ay ba be bi bo by da de do ed "
    "ef eh el em en er es ex fa fe go ha he hi hm ho id if in is it jo ka ki la "
    "li lo ma me mi mm mo mu my na ne no nu od oe of oh oi ok om on op or os ow "
    "ox oy pa pe pi po qi re sh si so ta te ti to uh um un up us ut we wo xi xu "
    "ya ye yo za".split()
)
NO_VOWEL_OK = set("brr cwm crwth hmm mm nth pfft pht psst pst shh tsk tsktsk zzz".split())
VOWELS = set("aeiouy")


def main() -> None:
    raw = set()
    for src in (["web2"], ["gcide"]):
        raw |= get_english_words_set(src, lower=False, alpha=True)
    lower_forms = {w for w in raw if w.islower()}
    words = set()
    for w in lower_forms:  # only entries that exist lowercase => not proper nouns
        if not w.isascii() or not w.isalpha():
            continue
        if len(w) == 1:
            continue
        if len(w) == 2 and w not in VALID_2:
            continue
        if not (set(w) & VOWELS) and w not in NO_VOWEL_OK:
            continue
        if len(w) > 24:
            continue
        words.add(w)

    # Common words missing from the dictionaries but present in frequency data
    # (plurals/inflections are mostly covered; this adds frequent modern words).
    scored = []
    for w in words:
        scored.append((zipf_frequency(w, "en"), w))
    scored.sort(key=lambda t: (-t[0], t[1]))
    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="\n") as f:
        for z, w in scored:
            f.write(f"{w}\t{z:.2f}\n")
    print(f"wrote {len(scored)} words to {OUT}")


if __name__ == "__main__":
    main()
