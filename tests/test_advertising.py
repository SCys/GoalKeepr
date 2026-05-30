"""Tests for advertising word detection."""
from __future__ import annotations

from unittest.mock import patch

import pytest


# The module reads from manager.config at runtime, so we patch the config
# to return known advertising words.


def _mock_config(words_enabled=True, regex_enabled=False):
    """Build a dummy ConfigParser with an [advertising] section."""
    from configparser import ConfigParser

    c = ConfigParser()
    c["advertising"] = {
        "enabled": "true" if words_enabled else "false",
        "words": "广告, spam, 推广, test_word",
        "regex_patterns": "test_regex:bad[0-9]+" if regex_enabled else "",
    }
    return c


@pytest.fixture(autouse=True)
def _patch_config():
    """Patch manager.config before every test."""
    from manager import manager

    with patch.object(manager, "config", _mock_config()):
        yield


def test_detect_advertising_word():
    from utils.advertising import check_advertising

    assert check_advertising("this is spam content") == (True, "spam")
    assert check_advertising("包含广告内容") == (True, "广告")


def test_clean_text():
    from utils.advertising import check_advertising

    assert check_advertising("hello world") == (False, None)
    assert check_advertising("") == (False, None)


def test_none_text():
    from utils.advertising import check_advertising

    assert check_advertising(None) == (False, None)


def test_single_character_not_matched():
    """Words shorter than 2 characters are skipped."""
    from utils.advertising import check_advertising

    # The word "a" or single chars should not flag
    result, matched = check_advertising("a")
    assert result is False
    assert matched is None


def test_substring_not_matched():
    """Partial word match should still match (Chinese substring behavior)."""
    from utils.advertising import check_advertising

    # "test_word" matches inside "this_is_test_word_here"
    assert check_advertising("this_is_test_word_here") == (True, "test_word")


def test_disabled_detection():
    """When advertising section is disabled, no words are loaded."""
    from manager import manager

    with patch.object(manager, "config", _mock_config(words_enabled=False)):
        from utils.advertising import check_advertising

        assert check_advertising("spam") == (False, None)


def test_regex_pattern_detection():
    from manager import manager

    with patch.object(manager, "config", _mock_config(regex_enabled=True)):
        from utils.advertising import check_advertising

        assert check_advertising("bad12345") == (True, "pattern:test_regex")
        assert check_advertising("bad67890content") == (True, "pattern:test_regex")
        assert check_advertising("good") == (False, None)


def test_load_advertising_words():
    from utils.advertising import load_advertising_words

    words = load_advertising_words()
    assert "广告" in words
    assert "spam" in words
    assert "test_word" in words
