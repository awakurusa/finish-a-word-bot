import pytest

from finish_the_word import debuglog


@pytest.fixture(autouse=True)
def _debug_log_to_tmp(tmp_path, monkeypatch):
    """Keep tests from writing ftw_debug.log into the project folder."""
    monkeypatch.setattr(debuglog, "_PATH", tmp_path / "ftw_debug.log")
    monkeypatch.setattr(debuglog, "_started", False)
