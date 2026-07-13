"""edge-cases (low, OSS) — the stop hook's NPC-fabrication check must derive the
never-flag party set from the LIVE roster, not a hardcoded personal-campaign
list (stale roster + OSS personalization leak).
"""
import json
from pathlib import Path

import hooks.consolidated_stop_check as csc


def test_reads_names_from_split_sheets(tmp_path, monkeypatch):
    monkeypatch.setattr(csc, "CAMPAIGN_DIR", tmp_path)
    cdir = tmp_path / "characters"
    cdir.mkdir()
    (cdir / "_meta.json").write_text(json.dumps({"campaign_day": 1}), encoding="utf-8")
    (cdir / "hero.json").write_text(json.dumps({"name": "Bravo"}), encoding="utf-8")
    (cdir / "ally.json").write_text(json.dumps({"name": "Charlie"}), encoding="utf-8")
    assert csc._load_party_names() == {"Bravo", "Charlie"}


def test_falls_back_to_monolithic_characters_json(tmp_path, monkeypatch):
    monkeypatch.setattr(csc, "CAMPAIGN_DIR", tmp_path)
    (tmp_path / "characters.json").write_text(
        json.dumps({"characters": {"a": {"name": "Delta"}, "b": {"name": "Echo"}}}),
        encoding="utf-8",
    )
    assert csc._load_party_names() == {"Delta", "Echo"}


def test_empty_set_when_no_roster(tmp_path, monkeypatch):
    monkeypatch.setattr(csc, "CAMPAIGN_DIR", tmp_path)
    assert csc._load_party_names() == set()


def test_no_hardcoded_owner_party_names_remain():
    """The owner's personal party literals must be gone from the hook source."""
    src = Path(csc.__file__).read_text(encoding="utf-8")
    for leaked in ("Creenash", "MNEMOSYNE", "Tesslyn", "Bugsie"):
        assert leaked not in src, f"hardcoded owner name still present: {leaked}"


def test_hook_utils_loader_matches_csc_behavior(tmp_path):
    from hooks.hook_utils import load_party_names
    cdir = tmp_path / "characters"
    cdir.mkdir()
    (cdir / "_meta.json").write_text(json.dumps({"campaign_day": 1}), encoding="utf-8")
    (cdir / "hero.json").write_text(json.dumps({"name": "Bravo"}), encoding="utf-8")
    (cdir / "bad.json").write_text("{not json", encoding="utf-8")
    assert load_party_names(tmp_path) == {"Bravo"}


def test_hook_utils_loader_monolithic_fallback(tmp_path):
    from hooks.hook_utils import load_party_names
    (tmp_path / "characters.json").write_text(
        json.dumps({"characters": {"a": {"name": "Delta"}}}), encoding="utf-8")
    assert load_party_names(tmp_path) == {"Delta"}


def test_hook_utils_loader_empty_on_missing(tmp_path):
    from hooks.hook_utils import load_party_names
    assert load_party_names(tmp_path) == set()


def test_csc_delegates_to_hook_utils(tmp_path, monkeypatch):
    """csc._load_party_names must be the shared loader, not a drifted copy."""
    monkeypatch.setattr(csc, "CAMPAIGN_DIR", tmp_path)
    cdir = tmp_path / "characters"
    cdir.mkdir()
    (cdir / "x.json").write_text(json.dumps({"name": "Foxtrot"}), encoding="utf-8")
    assert csc._load_party_names() == {"Foxtrot"}
    src = Path(csc.__file__).read_text(encoding="utf-8")
    assert "load_party_names(CAMPAIGN_DIR)" in src, "csc must delegate to hook_utils"


def test_no_hardcoded_owner_words_in_lorebook_gate():
    import hooks.lorebook_gate as lg
    src = Path(lg.__file__).read_text(encoding="utf-8").lower()
    owner_words = ("creenash", "vela", "kess", "bugsie", "saphora", "roscar",
                   "petros", "aramanthus", "mnemosyne", "patagia", "substrate",
                   "mycorrhizal", "mantid", "chattersnipe", "krypteia", "ceruline",
                   "kalaxis", "vermillion", "thyricost", "delta complex", "sandwhisper")
    for w in owner_words:
        assert w not in src, f"owner-campaign word still hardcoded in lorebook_gate: {w}"
