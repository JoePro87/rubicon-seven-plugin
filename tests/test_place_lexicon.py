"""Canon place lexicon (canon gate hardening spec §F.1, 2026-07-24)."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hooks import place_lexicon  # noqa: E402
from hooks.place_lexicon import load_place_lexicon  # noqa: E402
from conftest import REAL_CAMPAIGN_DIR  # noqa: E402

# Read-only: conftest isolates RUBICON_CAMPAIGN_DIR to a temp dir, so the live
# lexicon must be read from the real repo pointer conftest exposes.
CAMPAIGN = REAL_CAMPAIGN_DIR
_live = pytest.mark.skipif(
    not (CAMPAIGN / "VAARN_GEOGRAPHY.json").exists(),
    reason="live campaign geography not present")


@_live
def test_builds_non_empty_overworld_and_site():
    lex = load_place_lexicon(CAMPAIGN)
    assert lex["overworld"], "no overworld names built from VAARN_GEOGRAPHY.json"
    assert lex["site"], "no site names built from maps/*.json"
    assert "ceruline" in lex["overworld"]


@_live
def test_backup_map_files_excluded():
    """A room name that exists ONLY in a .bak/.pre- map must not be indexed."""
    live_names, backup_names = set(), set()
    for mp in (CAMPAIGN / "maps").glob("*.json"):
        data = json.loads(mp.read_text(encoding="utf-8"))
        names = {(r.get("name") or "").lower()
                 for r in (data.get("rooms") or {}).values() if isinstance(r, dict)}
        if ".bak" in mp.name or ".pre-" in mp.name:
            backup_names |= names
        else:
            live_names |= names
    orphans = {n for n in backup_names - live_names if len(n) >= 4}
    lex = load_place_lexicon(CAMPAIGN)
    assert not (orphans & lex["site"]), f"stale backup room names leaked: {orphans & lex['site']}"


def test_short_names_dropped(tmp_path):
    (tmp_path / "VAARN_GEOGRAPHY.json").write_text(json.dumps(
        {"locations": {"sea": {}, "ceruline": {}}, "regions": {}}), encoding="utf-8")
    lex = load_place_lexicon(tmp_path)
    assert "ceruline" in lex["overworld"]
    assert "sea" not in lex["overworld"]


def test_missing_campaign_dir_returns_empty_not_exception():
    lex = load_place_lexicon("/nonexistent/campaign/dir/xyz")
    assert lex["overworld"] == frozenset()
    assert lex["site"] == frozenset()


def test_malformed_geography_fails_open(tmp_path):
    (tmp_path / "VAARN_GEOGRAPHY.json").write_text("{not json", encoding="utf-8")
    lex = load_place_lexicon(tmp_path)
    assert lex["overworld"] == frozenset()


def test_cache_invalidates_on_mtime_change(tmp_path):
    geo = tmp_path / "VAARN_GEOGRAPHY.json"
    geo.write_text(json.dumps({"locations": {"ceruline": {}}, "regions": {}}),
                   encoding="utf-8")
    place_lexicon._LEXICON_CACHE["key"] = None
    first = load_place_lexicon(tmp_path)
    assert "thyricost" not in first["overworld"]

    import os
    import time
    geo.write_text(json.dumps(
        {"locations": {"ceruline": {}, "thyricost": {}}, "regions": {}}),
        encoding="utf-8")
    # Force a distinct mtime even on coarse-grained filesystems.
    future = time.time() + 10
    os.utime(geo, (future, future))

    second = load_place_lexicon(tmp_path)
    assert "thyricost" in second["overworld"], "lexicon cache did not invalidate"


def test_exempt_place_names_removes_a_noisy_name(tmp_path):
    (tmp_path / "VAARN_GEOGRAPHY.json").write_text(json.dumps(
        {"locations": {"ceruline": {}, "thyricost": {}}, "regions": {}}),
        encoding="utf-8")
    (tmp_path / "spatial_gate_config.json").write_text(
        json.dumps({"exempt_place_names": ["thyricost"]}), encoding="utf-8")
    lex = load_place_lexicon(tmp_path)
    assert "ceruline" in lex["overworld"]
    assert "thyricost" not in lex["overworld"]
