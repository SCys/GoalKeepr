"""测试 utils/advertising.py 中的广告检测功能"""
import pytest
from unittest.mock import MagicMock, patch

@pytest.fixture
def mock_config_enabled_words():
    """启用广告词的配置"""
    config = MagicMock()
    config.has_section.return_value = True
    config.__getitem__ = lambda self, section: {
        "advertising": {
            "enabled": "true",
            "words": "spam,广告,test"
        }
    }[section]
    config.getboolean = lambda self, section, key, fallback=False: True
    config.get = lambda self, section, key, fallback="": "spam,广告,test"
    return config

@pytest.fixture
def mock_config_enabled_patterns():
    """启用正则模式的配置"""
    config = MagicMock()
    config.has_section.return_value = True
    config.__getitem__ = lambda self, section: {
        "advertising": {
            "enabled": "true",
            "regex_patterns": "url:http://\\w+.com;phone:1\\d{10}"
        }
    }[section]
    config.getboolean = lambda self, section, key, fallback=False: True
    config.get = lambda self, section, key, fallback="": "url:http://\\w+.com;phone:1\\d{10}"
    return config

@pytest.fixture
def mock_config_disabled():
    """禁用广告检测的配置"""
    config = MagicMock()
    config.has_section.return_value = True
    config.__getitem__ = lambda self, section: {
        "advertising": {"enabled": "false"}
    }[section]
    return config

@pytest.fixture
def mock_logger():
    """模拟 logger"""
    return MagicMock()


class TestLoadAdvertisingWords:
    """测试 load_advertising_words 函数"""

    def test_enabled_with_words(self, mock_config_enabled_words, mock_logger):
        """测试启用且有广告词"""
        with patch("utils.advertising.manager.config", mock_config_enabled_words):
            with patch("utils.advertising.logger", mock_logger):
                from utils.advertising import load_advertising_words
                words = load_advertising_words()
                assert words == ["spam", "广告", "test"]
                mock_logger.debug.assert_called_once()

    def test_disabled(self, mock_config_disabled, mock_logger):
        """测试禁用"""
        with patch("utils.advertising.manager.config", mock_config_disabled):
            with patch("utils.advertising.logger", mock_logger):
                from utils.advertising import load_advertising_words
                words = load_advertising_words()
                assert words == []
                mock_logger.info.assert_called_once()

    def test_no_section(self, mock_logger):
        """测试没有 advertising section"""
        mock_config = MagicMock()
        mock_config.has_section.return_value = False
        with patch("utils.advertising.manager.config", mock_config):
            with patch("utils.advertising.logger", mock_logger):
                from utils.advertising import load_advertising_words
                words = load_advertising_words()
                assert words == []
                mock_logger.warning.assert_called_once()


class TestLoadAdvertisingPatterns:
    """测试 load_advertising_patterns 函数"""

    def test_valid_patterns(self, mock_config_enabled_patterns, mock_logger):
        """测试有效正则模式"""
        with patch("utils.advertising.manager.config", mock_config_enabled_patterns):
            with patch("utils.advertising.logger", mock_logger):
                from utils.advertising import load_advertising_patterns
                patterns = load_advertising_patterns()
                assert len(patterns) == 2
                assert patterns[0]["name"] == "url"
                assert "http://\\w+.com" in patterns[0]["pattern"]
                mock_logger.debug.assert_called_once()

    def test_invalid_regex(self, mock_logger):
        """测试无效正则"""
        mock_config = MagicMock()
        mock_config.has_section.return_value = True
        mock_config.__getitem__ = lambda self, section: {
            "advertising": {"enabled": "true", "regex_patterns": "invalid:["}
        }[section]
        with patch("utils.advertising.manager.config", mock_config):
            with patch("utils.advertising.logger", mock_logger):
                from utils.advertising import load_advertising_patterns
                patterns = load_advertising_patterns()
                assert patterns == []
                mock_logger.error.assert_called()

    def test_no_patterns(self, mock_config_enabled_patterns, mock_logger):
        """测试没有 patterns"""
        mock_config = MagicMock()
        mock_config.has_section.return_value = True
        mock_config.getboolean.return_value = True
        mock_config.get.return_value = ""
        with patch("utils.advertising.manager.config", mock_config):
            with patch("utils.advertising.logger", mock_logger):
                from utils.advertising import load_advertising_patterns
                patterns = load_advertising_patterns()
                assert patterns == []


class TestCheckAdvertising:
    """测试 check_advertising 函数"""

    def test_word_match_case_insensitive(self, mock_config_enabled_words, mock_logger):
        """测试词匹配（忽略大小写）"""
        with patch("utils.advertising.manager.config", mock_config_enabled_words):
            with patch("utils.advertising.logger", mock_logger):
                from utils.advertising import check_advertising
                is_ad, matched = check_advertising("Buy SPAM now!")
                assert is_ad is True
                assert matched == "spam"

    def test_pattern_match(self, mock_config_enabled_patterns, mock_logger):
        """测试正则匹配"""
        with patch("utils.advertising.manager.config", mock_config_enabled_patterns):
            with patch("utils.advertising.logger", mock_logger):
                from utils.advertising import check_advertising
                is_ad, matched = check_advertising("Visit http://example.com")
                assert is_ad is True
                assert matched == "pattern:url"

    def test_no_match(self, mock_config_enabled_words, mock_logger):
        """测试无匹配"""
        with patch("utils.advertising.manager.config", mock_config_enabled_words):
            with patch("utils.advertising.logger", mock_logger):
                from utils.advertising import check_advertising
                is_ad, matched = check_advertising("normal text")
                assert is_ad is False
                assert matched is None
                mock_logger.info.assert_not_called()

    def test_empty_text(self, mock_logger):
        """测试空文本"""
        with patch("utils.advertising.logger", mock_logger):
            from utils.advertising import check_advertising
            is_ad, matched = check_advertising("")
            assert is_ad is False
            assert matched is None

    def test_multiple_words_first_match(self, mock_logger):
        """测试多个词，匹配第一个"""
        # 使用自定义配置：test 在 广告 之前
        mock_config = MagicMock()
        mock_config.has_section.return_value = True
        mock_config.__getitem__ = lambda self, section: {
            "advertising": {"enabled": "true", "words": "test,广告"}
        }[section]
        with patch("utils.advertising.manager.config", mock_config):
            with patch("utils.advertising.logger", mock_logger):
                from utils.advertising import check_advertising
                is_ad, matched = check_advertising("test and 广告")
                assert matched == "test"  # 第一个匹配的词（列表顺序）
