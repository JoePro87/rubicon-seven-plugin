"""S2: shape/sanity contract for the annotated Desert Foraging table.

Reads the engine-bundled rules-data tables.json (read-only), resolved
repo-relatively per the judge-against-the-real-runner rule.
"""
import json
import re
from pathlib import Path

import pytest

TABLES = Path(__file__).resolve().parents[1] / "data" / "rules" / "rulebook" / "tables.json"
DICE_RX = re.compile(r"^\d*d\d+$")
CACHE_SIZES = {"Small", "Medium", "Large", "Extra-Large"}


def _foraging_table():
    if not TABLES.exists():
        pytest.skip("campaign repo not present")
    data = json.loads(TABLES.read_text(encoding="utf-8"))
    for t in data.get("rolling_tables", []):
        if t.get("id") == "table-desert-foraging":
            return t
    pytest.fail("table-desert-foraging missing from rolling_tables")


def test_every_entry_is_yield_cache_or_plain():
    t = _foraging_table()
    yields = caches = 0
    for e in t["entries"]:
        has_yield = "yield" in e
        has_cache = "cache" in e
        assert not (has_yield and has_cache), f"row {e.get('roll')}: both yield and cache"
        if has_yield:
            yields += 1
            y = e["yield"]
            assert isinstance(y, dict) and y, f"row {e.get('roll')}: empty yield"
            for kind, v in y.items():
                assert kind in ("water", "food"), f"row {e.get('roll')}: bad kind {kind}"
                assert (isinstance(v, int) and v > 0) or (
                    isinstance(v, str) and DICE_RX.match(v)), \
                    f"row {e.get('roll')}: bad value {v!r}"
        if has_cache:
            caches += 1
            assert e["cache"] in CACHE_SIZES, f"row {e.get('roll')}: bad cache {e['cache']}"
    assert yields >= 25, f"only {yields} yield rows — annotation pass incomplete?"
    assert caches == 4


def test_cache_rows_are_72_81_90_100():
    t = _foraging_table()
    expected = {72: "Small", 81: "Medium", 90: "Large", 100: "Extra-Large"}
    got = {e["roll"]: e["cache"] for e in t["entries"] if "cache" in e}
    assert got == expected
