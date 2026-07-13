# tests/test_utf8_handling.py
import pytest
import sys
sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.dirname(__import__('os').path.abspath(__file__))))

from server import _filter_dm_only_content
from pathlib import Path
import tempfile

def test_filter_handles_utf8_content():
    """Filter should handle UTF-8 characters correctly."""
    content = """
⛔ DM ONLY ⛔
Secret: The vault contains ancient Titan runes — ⚡⚙⛔
⛔ END DM ONLY ⛔

Visible: The walls are carved with strange symbols.
"""

    result = _filter_dm_only_content(content)

    assert "Titan runes" not in result
    assert "⚡" not in result
    assert "The walls are carved" in result
