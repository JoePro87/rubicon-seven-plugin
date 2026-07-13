"""C31 — prep-authored ### CONSTRAINT: blocks are parsed for surfacing, and
C28 — dm_view is retired (tombstone)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import server


PREP = """# Test Vault

### CONSTRAINT: sealed_gate
**Subject:** the north gate
**Limitation:** cannot be opened while the ward is lit
**Scope:** party_known

### CONSTRAINT: dm_trap
**Subject:** the reliquary
**Limitation:** collapses if the idol is removed
**Scope:** dm_only

### SECRET: idol
**Truth:** it is a fake
"""


def test_extract_prep_constraints_parses_blocks():
    cons = server._extract_prep_constraints(PREP)
    assert len(cons) == 2
    by_id = {c["id"]: c for c in cons}
    assert by_id["sealed_gate"]["subject"] == "the north gate"
    assert by_id["sealed_gate"]["limitation"] == "cannot be opened while the ward is lit"
    assert by_id["sealed_gate"]["scope"] == "party_known"
    assert by_id["dm_trap"]["scope"] == "dm_only"


def test_extract_prep_constraints_defaults_scope_party_known():
    prep = ("### CONSTRAINT: x\n**Subject:** thing\n"
            "**Limitation:** no touch\n\n## NEXT\n")
    cons = server._extract_prep_constraints(prep)
    assert cons[0]["scope"] == "party_known"


def test_extract_prep_constraints_empty_when_none():
    assert server._extract_prep_constraints("# just a title\n\nno constraints") == []


def test_dm_view_is_retired():
    # C28 tombstone: the tool is gone, not merely disabled.
    assert not hasattr(server, "dm_view")
