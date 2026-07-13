import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import site_features as sf  # noqa: E402


def test_slugify_matches_geography_normalization():
    assert sf.slugify("Pilgrim's Rest") == "pilgrims_rest"
    assert sf.slugify("  Salt Bones ") == "salt_bones"


def test_stamp_creates_place_and_persists(tmp_path):
    msg = sf.stamp_feature(tmp_path, "Pilgrim's Rest", "A chromatic flower rests on the shrine stone", 141)
    assert msg.startswith("📍 Feature stamped")
    data = json.loads((tmp_path / "site_features.json").read_text(encoding="utf-8"))
    entry = data["places"]["pilgrims_rest"]
    assert entry["display_name"] == "Pilgrim's Rest"
    assert entry["features"][0] == {"id": 1, "text": "A chromatic flower rests on the shrine stone", "day": 141}


def test_stamp_appends_and_increments_id(tmp_path):
    sf.stamp_feature(tmp_path, "Quills Camp", "first", 10)
    sf.stamp_feature(tmp_path, "Quills Camp", "second", 12)
    feats = sf.features_for(tmp_path, "quills_camp")
    assert [f["id"] for f in feats] == [1, 2]


def test_stamp_rejects_empty_text(tmp_path):
    assert sf.stamp_feature(tmp_path, "Quills Camp", "   ", 10).startswith("ERROR")
    assert not (tmp_path / "site_features.json").exists()


def test_cold_start_missing_file_is_empty(tmp_path):
    assert sf.load_ledger(tmp_path) == {"version": 1, "places": {}}
    assert sf.features_for(tmp_path, "anywhere") == []
    assert sf.scan_text_for_places(tmp_path, "we walk to Pilgrim's Rest") == {}


def test_corrupt_file_treated_as_empty(tmp_path):
    (tmp_path / "site_features.json").write_text("{not json", encoding="utf-8")
    assert sf.load_ledger(tmp_path)["places"] == {}


def test_remove_by_id_and_substring(tmp_path):
    sf.stamp_feature(tmp_path, "Camp", "a flower on the stone", 10)
    sf.stamp_feature(tmp_path, "Camp", "a burned tent", 11)
    assert "flower" in sf.remove_feature(tmp_path, "Camp", "1", 12)
    assert "burned" in sf.remove_feature(tmp_path, "Camp", "tent", 12)
    assert sf.features_for(tmp_path, "Camp") == []


def test_remove_ambiguous_and_missing(tmp_path):
    sf.stamp_feature(tmp_path, "Camp", "red banner", 10)
    sf.stamp_feature(tmp_path, "Camp", "red door", 10)
    msg = sf.remove_feature(tmp_path, "Camp", "red", 11)
    assert msg.startswith("ERROR") and "#1" in msg and "#2" in msg
    assert sf.remove_feature(tmp_path, "Camp", "zeppelin", 11).startswith("ERROR")
    assert sf.remove_feature(tmp_path, "Nowhere", "x", 11).startswith("ERROR")


def test_place_entry_fuzzy_two_way(tmp_path):
    sf.stamp_feature(tmp_path, "Ceruline Arcology", "gates rebuilt", 20)
    # long live-status string CONTAINS the display name
    e = sf.place_entry(tmp_path, "Ceruline Arcology — Anchor's Office corridor, Tier 5")
    assert e and e["display_name"] == "Ceruline Arcology"


def test_alias_match_and_scan(tmp_path):
    sf.stamp_feature(tmp_path, "Pilgrim's Rest", "flower", 10, aliases=["the crossroads camp"])
    hits = sf.scan_text_for_places(tmp_path, "We camp at the crossroads camp tonight.")
    assert list(hits) == ["pilgrims_rest"]
    # short names (<4 chars) never scan-match
    sf.stamp_feature(tmp_path, "Ox", "cart", 10)
    assert "ox" not in sf.scan_text_for_places(tmp_path, "an ox walks by")


def test_scan_apostrophe_insensitive(tmp_path):
    # stamped WITHOUT apostrophe (routing's underscore-derived form),
    # prose WITH apostrophe — and the reverse — must both match.
    sf.stamp_feature(tmp_path, "PILGRIMS REST", "a flower", 141)
    assert "pilgrims_rest" in sf.scan_text_for_places(tmp_path, "we ride toward Pilgrim's Rest")
    sf.stamp_feature(tmp_path, "Yam's Landing", "a rope", 141)
    assert "yams_landing" in sf.scan_text_for_places(tmp_path, "docked at Yams Landing")


def test_scan_skips_places_without_features(tmp_path):
    sf.stamp_feature(tmp_path, "Camp", "flower", 10)
    sf.remove_feature(tmp_path, "Camp", "1", 11)
    assert sf.scan_text_for_places(tmp_path, "back at Camp") == {}


def test_format_block(tmp_path):
    sf.stamp_feature(tmp_path, "Camp", "a flower", 10)
    block = sf.format_features_block(sf.place_entry(tmp_path, "Camp"))
    assert block.startswith("📍 SITE FEATURES — Camp:")
    assert "a flower (since Day 10)" in block
