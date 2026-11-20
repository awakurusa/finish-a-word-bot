from finish_the_word.config import Config
from finish_the_word.dictionary import WordDB
import pytest


@pytest.fixture(scope="module")
def db():
    return WordDB()


def cfg(**kw):
    c = Config()
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def test_large_dictionary(db):
    assert len(db) > 150_000
    assert "quixotic" in db and "xylophone" in db


def test_no_proper_nouns_or_abbreviations(db):
    for bad in ("london", "nasa", "zzz", "qwrt"):
        assert bad not in db


def test_prefix_all_match_and_extend(db):
    hits = db.search("str", "prefix", min_len=3)
    assert hits and all(w.startswith("str") and len(w) > 3 for w in hits)


def test_suffix_contains(db):
    assert all(w.endswith("tion") for w in db.search("tion", "suffix"))
    assert all("ngr" in w for w in db.search("ngr", "contains"))


def test_pattern_blanks(db):
    hits = db.search("ap__e", "prefix")
    assert "apple" in hits and all(len(w) == 5 for w in hits)


def test_reliable_prefers_common_words(db):
    sol = db.solve("th", cfg())
    assert sol.word and sol.word.startswith("th") and sol.zipf >= 4.0


def test_selection_strategies(db):
    longest = db.rank(db.search("qu", "prefix", 3, 30), "longest")[0]
    shortest = db.rank(db.search("qu", "prefix", 3, 30), "shortest")[0]
    assert len(longest) > len(shortest)


def test_length_limits(db):
    sol = db.solve("st", cfg(min_word_len=6, max_word_len=7))
    assert sol.word and 6 <= len(sol.word) <= 7


def test_exclude_and_used_cache(tmp_path):
    db = WordDB(used_path=tmp_path / "used.json")
    first = db.solve("ab", cfg()).word
    db.mark_used(first)
    second = db.solve("ab", cfg()).word
    assert second and second != first
    # persisted across instances
    again = WordDB(used_path=tmp_path / "used.json")
    assert first in again.used
    again.reset_used()
    assert not again.used


def test_ocr_error_rescue(db):
    # 'zz' + nothing plausible -> correction machinery kicks in for impossible prefixes
    sol = db.solve("xqz", cfg())
    assert sol.word is None or sol.corrected
    sol = db.solve("rnoun", cfg())  # 'm' misread as 'rn' -> "mound"/"mount"
    assert sol.word


def test_relaxes_commonness_floor(db):
    sol = db.solve("zyg", cfg(min_zipf=7.0))
    assert sol.word and sol.relaxed


def test_junk_query(db):
    assert db.solve("", cfg()).word is None
    assert db.solve("___", cfg()).word is None
    assert db.solve("12", cfg()).word is None


def test_last_letter_mode(db):
    sol = db.solve("apple", cfg(match_mode="last_letter"))
    assert sol.word and sol.word.startswith("e")


def test_custom_words_and_blocklist(tmp_path):
    extra = tmp_path / "extra.txt"
    extra.write_text("zorbleflux\n")
    block = tmp_path / "block.txt"
    block.write_text("the\n")
    db = WordDB(extra=extra, blocklist=block)
    assert "zorbleflux" in db and "the" not in db
