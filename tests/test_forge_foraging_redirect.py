"""The pre-S2 d30 'foraging' table in content_forge is retired.

The S2 survival system runs the certified rulebook d100 forage
(table-desert-foraging) via the supply tool. The forge's stale d30 table
must be gone from data/content_forge_tables.json, and
roll(action="environment", table="foraging") must redirect the DM to
supply(action="forage", character="...") instead of rolling.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

DATA_FILE = Path(__file__).parent.parent / "data" / "content_forge_tables.json"


def _capture_roll_tool():
    """Register the forge tools against a fake MCP and return the roll function."""
    from content_forge import register_content_forge_tools
    captured = {}

    class _FakeMCP:
        def tool(self, *args, **kwargs):
            def deco(fn):
                captured[fn.__name__] = fn
                return fn
            return deco

    register_content_forge_tools(_FakeMCP(), Path(__file__).parent.parent)
    return captured["roll"]


def test_forge_json_has_no_foraging_table():
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    assert "foraging" not in data["tables"], (
        "stale pre-S2 d30 foraging table still present in content_forge_tables.json; "
        "forage is owned by the supply tool (S2 certified d100)"
    )


def test_environment_foraging_redirects_to_supply():
    roll = _capture_roll_tool()
    out = roll(action="environment", table="foraging", specific_roll=None)
    assert 'supply(action="forage"' in out, (
        "environment/foraging must push the real supply forage call, got: " + out
    )
    assert "d30" not in out, "redirect must not roll the retired d30 table"


def test_environment_unknown_table_mentions_foraging_redirect():
    roll = _capture_roll_tool()
    out = roll(action="environment", table="bogus", specific_roll=None)
    assert "foraging" in out and "supply" in out, (
        "Unknown-table message should still mention foraging as a supply redirect, got: " + out
    )
