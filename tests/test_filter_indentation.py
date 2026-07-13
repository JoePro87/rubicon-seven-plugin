# tests/test_filter_indentation.py
import pytest
import sys
sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.dirname(__import__('os').path.abspath(__file__))))

from server import _filter_dm_only_content

def test_filter_preserves_indentation_in_nested_lists():
    """Filter should preserve indentation when removing dm_only lines."""
    content = """
- Room features:
  - Ancient machinery (dm_only: triggers trap if touched)
  - Glowing crystals
  - Stone altar
"""

    result = _filter_dm_only_content(content, preserve_structure=True)

    # dm_only line should be replaced but indentation preserved
    assert "triggers trap" not in result
    assert "  [DM note removed]" in result or "[DM note removed]\n  - Glowing" in result
    # Markdown structure should be valid
    assert "- Room features:" in result
    assert "- Glowing crystals" in result

def test_filter_preserves_indentation_in_deeply_nested_structure():
    """Filter should preserve indentation at any nesting level."""
    content = """
1. First level
   - Second level
     - Third level (dm_only: secret compartment)
     - Other third level
"""

    result = _filter_dm_only_content(content, preserve_structure=True)

    assert "secret compartment" not in result
    assert "     [DM note removed]" in result  # 5 spaces preserved
