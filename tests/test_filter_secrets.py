# tests/test_filter_secrets.py
import pytest
import sys
sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.dirname(__import__('os').path.abspath(__file__))))

from server import _filter_dm_only_content

def test_filter_removes_secrets_with_underscores():
    """Filter should remove secrets with underscores in ID."""
    content = """
### SECRET: vault_origin

**Scope:** dm_only

This vault was built by the Titans.

### SECRET: other_secret

**Scope:** party_known

The party can see this one.
"""

    result = _filter_dm_only_content(content)

    assert "vault_origin" not in result
    assert "This vault was built by the Titans" not in result
    assert "other_secret" in result
    assert "The party can see this one" in result

def test_filter_removes_secrets_with_hyphens():
    """Filter should remove secrets with hyphens in ID."""
    content = """
### SECRET: vault-origin

**Scope:** dm_only

This vault was built by the Titans.
"""

    result = _filter_dm_only_content(content)

    assert "vault-origin" not in result
    assert "This vault was built by the Titans" not in result

def test_filter_removes_secrets_with_numbers():
    """Filter should remove secrets with numbers in ID."""
    content = """
### SECRET: trap_7

**Scope:** dm_only

Pressure plate triggers spears.
"""

    result = _filter_dm_only_content(content)

    assert "trap_7" not in result
    assert "Pressure plate triggers spears" not in result
