# tests/test_filter_dm_blocks.py
import pytest
import sys
sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.dirname(__import__('os').path.abspath(__file__))))

from server import _filter_dm_only_content

def test_filter_handles_dm_blocks_with_newlines_before_marker():
    """Filter should handle DM blocks with newlines before opening marker."""
    content = """
Some visible text

⛔
DM ONLY ⛔
Secret monster stats:
HP: 50, Armor: 12
⛔ END DM ONLY ⛔

More visible text
"""

    result = _filter_dm_only_content(content)

    assert "Secret monster stats" not in result
    assert "HP: 50" not in result
    assert "Some visible text" in result
    assert "More visible text" in result

def test_filter_handles_dm_blocks_on_separate_lines():
    """Filter should handle DM block markers on separate lines."""
    content = """
⛔
DM ONLY
⛔
Secret content
⛔
END DM ONLY
⛔
"""

    result = _filter_dm_only_content(content)

    assert "Secret content" not in result

def test_filter_dm_blocks_does_not_consume_excessive_newlines():
    """Filter should not match excessive content due to greedy newline matching."""
    content = """
Visible paragraph 1

⛔ DM ONLY ⛔
Hidden content
⛔ END DM ONLY ⛔

Visible paragraph 2

Another visible paragraph
"""

    result = _filter_dm_only_content(content)

    assert "Hidden content" not in result
    assert "Visible paragraph 1" in result
    assert "Visible paragraph 2" in result
    assert "Another visible paragraph" in result
