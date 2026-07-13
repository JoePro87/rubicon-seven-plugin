"""tests/test_settlement_push.py — Task D1 + D3: Settlement arrival push + Stop reflex.

D1: Tests the branch in phrase_reminder that routes scene=settlement site detections
to reference_location(scope="who") INSTEAD of the dungeon map(enter_site,...) push.

D3: Tests the settlement_change_unstamped helper in consolidated_stop_check — the pure
function that the Stop runner calls to decide whether to append a nag advisory.
"""
import site_markers as sm


def test_settlement_index_carries_scene(tmp_path):
    """Guard: build_site_index preserves the scene field from the SITE marker."""
    (tmp_path / "FOO_PREP.md").write_text(
        '<!-- SITE: key=foo scene=settlement aliases="Foo Town" -->\n# FOO', encoding="utf-8")
    idx = sm.build_site_index(tmp_path)
    assert idx["foo"]["scene"] == "settlement"


def test_settlement_push_text(tmp_path, monkeypatch):
    """settlement_arrival_push returns a NEXT line calling reference_location
    with scope="who" when the player names a settlement site."""
    import hooks.phrase_reminder as pr
    monkeypatch.setattr(pr, "CAMPAIGN_DIR", tmp_path)
    (tmp_path / "FOO_PREP.md").write_text(
        '<!-- SITE: key=foo scene=settlement aliases="Foo Town" -->\n# FOO', encoding="utf-8")
    push = pr.settlement_arrival_push("we walk into Foo Town")
    assert 'reference_location' in push and 'scope="who"' in push


# ---------------------------------------------------------------------------
# Task D3: Stop reflex — settlement_change_unstamped helper
# ---------------------------------------------------------------------------

def test_reflex_flags_death_without_stamp():
    """Returns True when the transcript narrates a settlement change (death) but
    update_location_progress was NOT called this turn."""
    import hooks.consolidated_stop_check as csc
    transcript = "Dressik slumps against the basin, dead. The party stands in silence."
    tool_calls = []  # no update_location_progress this turn
    assert csc.settlement_change_unstamped(transcript, tool_calls) is True


def test_reflex_silent_when_stamped():
    """Returns False when update_location_progress WAS called this turn — already stamped."""
    import hooks.consolidated_stop_check as csc
    transcript = "Dressik slumps against the basin, dead."
    tool_calls = ["update_location_progress"]
    assert csc.settlement_change_unstamped(transcript, tool_calls) is False
