"""
广告词检测模块
Advertising words detection module
"""

import re
from typing import List, Tuple, Optional, Dict, Any, Union

from manager import manager

logger = manager.logger


def load_advertising_words() -> List[str]:
    """
    从配置中加载广告词列表
    Load advertising words from configuration
    
    Returns:
        List[str]: 广告词列表 (list of advertising words)
    """
    config = manager.config
    if not config.has_section("advertising"):
        logger.warning("No advertising section in configuration")
        return []
    
    if not config["advertising"].getboolean("enabled", False):
        logger.info("Advertising detection is disabled")
        return []
    
    words = config["advertising"].get("words", "")
    if isinstance(words, str):
        # If words is a string, split it by comma
        words = [word.strip() for word in words.split(",") if word.strip()]
    
    logger.debug(f"Loaded {len(words)} advertising words from configuration")
    return words


def load_advertising_patterns() -> List[Dict[str, Any]]:
    """
    从配置中加载广告词正则表达式模式
    Load advertising regex patterns from configuration
    
    Returns:
        List[Dict[str, Any]]: 广告词正则表达式模式列表 (list of advertising regex patterns)
            Each dict contains:
            - pattern: str - The regex pattern string
            - compiled: re.Pattern - The compiled regex pattern
            - name: str - The name of the pattern (for logging)
    """
    config = manager.config
    if not config.has_section("advertising"):
        logger.warning("No advertising section in configuration")
        return []
    
    if not config["advertising"].getboolean("enabled", False):
        logger.info("Advertising detection is disabled")
        return []
    
    # Check if regex_patterns exists in config
    patterns_str = config["advertising"].get("regex_patterns", "")
    if not patterns_str:
        return []
    
    patterns = []
    
    # Split by semicolon for different patterns
    pattern_items = [p.strip() for p in patterns_str.split(";") if p.strip()]
    
    for i, pattern_str in enumerate(pattern_items):
        # Split by colon for pattern name and pattern
        parts = pattern_str.split(":", 1)
        
        if len(parts) == 2:
            name, pattern = parts[0].strip(), parts[1].strip()
        else:
            name, pattern = f"pattern_{i+1}", pattern_str.strip()
        
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
            patterns.append({
                "pattern": pattern,
                "compiled": compiled,
                "name": name
            })
            # logger.info(f"Loaded advertising regex pattern: {name}")
        except re.error as e:
            logger.error(f"Failed to compile regex pattern '{pattern}': {e}")
    
    logger.debug(f"Loaded {len(patterns)} advertising regex patterns from configuration")
    return patterns


def check_advertising(text: str) -> Tuple[bool, Optional[str]]:
    """
    检查文本是否包含广告词
    Check if text contains advertising words
    
    Args:
        text (str): 要检查的文本 (text to check)
    
    Returns:
        Tuple[bool, Optional[str]]: 
            - 是否包含广告词 (whether contains advertising words)
            - 匹配到的广告词或模式名称 (matched advertising word or pattern name, if any)
    """
    if not text:
        return False, None
    
    # Check simple word matches
    words = load_advertising_words()
    if words:
        # Convert text to lowercase for case-insensitive matching
        text_lower = text.lower()
        
        for word in words:
            if word.lower() in text_lower:
                logger.info(f"Advertising word detected: {word}")
                return True, word
    
    # Check regex patterns
    patterns = load_advertising_patterns()
    if patterns:
        for pattern_info in patterns:
            compiled_pattern = pattern_info["compiled"]
            name = pattern_info["name"]
            
            if compiled_pattern.search(text):
                logger.info(f"Advertising pattern detected: {name}")
                return True, f"pattern:{name}"
    
    return False, None
