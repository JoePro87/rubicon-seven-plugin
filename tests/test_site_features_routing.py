import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402
import site_features as sf  # noqa: E402

ULP = server.update_location_progress


def _tmp_campaign(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    return tmp_path


def test_no_prep_routes_to_ledger(tmp_path, monkeypatch):
    camp = _tmp_campaign(tmp_path, monkeypatch)
    out = ULP(location="Pilgrims Rest", day=141,
              summary="Left a chromatic flower on the shrine stone",
              items_left=["chromatic flower"])
    assert "site-feature ledger" in out
    assert "📍 Feature stamped" in out
    feats = sf.features_for(camp, "pilgrims_rest")
    texts = [f["text"] for f in feats]
    assert "Left a chromatic flower on the shrine stone" in texts
    assert "chromatic flower left here" in texts
    # resurface footer appears ONCE
    assert out.count("Resurfaces on") == 1


def test_no_prep_status_and_consequences_become_features(tmp_path, monkeypatch):
    camp = _tmp_campaign(tmp_path, monkeypatch)
    ULP(location="Quills Camp", day=10, summary="Camp visited",
        status=["the_well: REPAIRED"], consequences="The gang knows our faces")
    texts = [f["text"] for f in sf.features_for(camp, "quills_camp")]
    assert "the_well: REPAIRED" in texts
    assert "The gang knows our faces" in texts


def test_prep_path_unchanged(tmp_path, monkeypatch):
    camp = _tmp_campaign(tmp_path, monkeypatch)
    (camp / "THE_CISTERN_PREP.md").write_text("# The Cistern\n", encoding="utf-8")
    out = ULP(location="THE_CISTERN", day=5, summary="Explored the east pump")
    assert "✓ Progress logged" in out
    assert "PROGRESS LOG" in (camp / "THE_CISTERN_PREP.md").read_text(encoding="utf-8")
    # nothing leaked into the ledger
    assert not (camp / "site_features.json").exists()


def test_mapped_site_hint(tmp_path, monkeypatch):
    camp = _tmp_campaign(tmp_path, monkeypatch)
    (camp / "maps").mkdir()
    (camp / "maps" / "quills_camp_map.json").write_text("{}", encoding="utf-8")
    out = ULP(location="Quills Camp", day=10, summary="Gates burned")
    assert 'map(action="update_room"' in out


def test_remove_routes_to_ledger(tmp_path, monkeypatch):
    camp = _tmp_campaign(tmp_path, monkeypatch)
    ULP(location="Quills Camp", day=10, summary="A flower on the stone")
    out = ULP(location="Quills Camp", day=12, summary="cleanup", remove="flower")
    assert "📍 Feature removed" in out
    assert sf.features_for(camp, "quills_camp") == []


def test_remove_on_prep_place_is_guidance_not_crash(tmp_path, monkeypatch):
    camp = _tmp_campaign(tmp_path, monkeypatch)
    (camp / "THE_CISTERN_PREP.md").write_text("# The Cistern\n", encoding="utf-8")
    out = ULP(location="THE_CISTERN", day=5, summary="x", remove="flower")
    assert "PROGRESS LOG" in out  # tells the DM prep places edit their log
