# tests/test_social_state_store.py
import json
import social_system as ss
from tests.test_social_parley_parser import SAMPLE

def test_load_missing_file_is_empty(tmp_path):
    assert ss.load_parleys(tmp_path) == {}

def test_open_from_parsed_block(tmp_path):
    parsed = ss.parse_parley_block(SAMPLE)
    p = ss.open_parley(tmp_path, parsed["slug"], title="Outer Reach Accord",
                       day=131, site_key="outer_reach", parsed=parsed)
    on_disk = ss.load_parleys(tmp_path)[parsed["slug"]]
    assert on_disk["status"] == "open"
    assert on_disk["current_tier"] == "contact"
    assert on_disk["tiers"][0]["reached_day"] == 131
    assert on_disk["parties"][0]["needle"] == "wary"
    assert on_disk["reveals"][0]["unlocked"] is False
    assert "brokerage" in on_disk["stakes"]
    assert on_disk["failure_state"].startswith("Combat")

def test_open_inline_uses_generic_ladder(tmp_path):
    p = ss.open_parley(tmp_path, "dock_dispute", title="Dock dispute", day=140,
                       stakes="wage terms", parties=[{"name": "Foreman Hale", "needle": "neutral"}])
    assert [t["name"] for t in p["tiers"]] == ss.GENERIC_LADDER
    assert p["parties"][0]["lever"] == ""

def test_open_duplicate_slug_raises(tmp_path):
    ss.open_parley(tmp_path, "x", title="X", day=1)
    try:
        ss.open_parley(tmp_path, "x", title="X", day=2)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "already open" in str(e)

def test_open_duplicate_slug_closed_message(tmp_path):
    ss.open_parley(tmp_path, "x", title="X", day=1)
    data = ss.load_parleys(tmp_path)
    data["x"]["status"] = "closed"
    ss.save_parleys(tmp_path, data)
    try:
        ss.open_parley(tmp_path, "x", title="X", day=2)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "closed parley" in str(e) and "history" in str(e)

def test_open_inline_invalid_needle_raises(tmp_path):
    try:
        ss.open_parley(tmp_path, "dock_dispute2", title="Dock dispute", day=140,
                       parties=[{"name": "Foreman Hale", "needle": "furious"}])
        assert False, "expected ValueError"
    except ValueError:
        pass

def test_find_by_npc_case_insensitive(tmp_path):
    parsed = ss.parse_parley_block(SAMPLE)
    ss.open_parley(tmp_path, parsed["slug"], title="OR", day=131, parsed=parsed)
    hits = ss.find_by_npc(tmp_path, "she-who-keeps")
    assert len(hits) == 1 and hits[0][2]["name"] == "She-Who-Keeps"

def test_saved_file_is_valid_utf8_json(tmp_path):
    ss.open_parley(tmp_path, "x", title="Rax'il parley — apostrophe", day=1)
    raw = (tmp_path / "parleys.json").read_text(encoding="utf-8")
    assert json.loads(raw)["x"]["title"].startswith("Rax'il")
