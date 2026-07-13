"""Contract tests for the dashboard's data-shaping logic (dashboard/model.py).

These import plain functions ONLY -- no Textual App is instantiated here (the
TUI itself is covered by a separate smoke test). Enforces the dumb-renderer
discipline: read_artifacts must never open any campaign file other than the
two player-view artifacts.
"""
import json
from pathlib import Path

import pytest

from dashboard import model


@pytest.fixture
def view_fixture():
    return {
        "day": 132, "weather": "dust storm", "location": "Dust Pilgrim's Rest",
        "active_prep": "thyricost", "wealth_tokens": 22280,
        "supply": {"mode": "abundant"},
        "party": [
            {"name": "Kess", "hp": 29, "hp_max": 29, "av": 18, "wounds": 0,
             "slots_free": 3, "slots_total": 12, "items": ["Heavy Crossbow", "Bedroll"]},
            {"name": "Vela", "hp": 11, "hp_max": 11, "av": 14, "wounds": 1,
             "slots_free": 5, "slots_total": 10, "items": []},
        ],
        "open_parleys": [{"slug": "warden-hessa", "tier": 2}],
        "in_combat": True,
        "updated_at": "2026-07-05T10:00:00",
    }


# -- party_cards --------------------------------------------------------

def test_party_cards_shape(view_fixture):
    cards = model.party_cards(view_fixture)
    assert cards[0]["name"] == "Kess"
    assert cards[0]["hp_text"] == "29/29"
    assert cards[0]["av"] == 18
    assert cards[0]["wounds"] == 0
    assert cards[0]["slots_text"] == "3/12"
    # old-shape (plain string) items normalize — pre-2026-07-07 view files
    assert cards[0]["items"] == [
        {"name": "Heavy Crossbow", "where": None, "effect": None},
        {"name": "Bedroll", "where": None, "effect": None},
    ]
    assert cards[1]["slots_text"] == "5/10"
    assert cards[1]["items"] == []


def test_party_cards_new_item_shape_passes_through(view_fixture):
    view_fixture["party"][0]["items"] = [
        {"name": "Whisper Lens", "where": "carried", "effect": "See through fog"},
        {"name": "Reflex Splice", "where": "cybernetic", "effect": "+1 DEX"},
    ]
    cards = model.party_cards(view_fixture)
    assert cards[0]["items"] == [
        {"name": "Whisper Lens", "where": "carried", "effect": "See through fog"},
        {"name": "Reflex Splice", "where": "cybernetic", "effect": "+1 DEX"},
    ]


def test_party_cards_empty_on_no_view():
    assert model.party_cards(None) == []
    assert model.party_cards({}) == []


# -- world_summary --------------------------------------------------------

def test_world_summary_shape(view_fixture):
    w = model.world_summary(view_fixture)
    assert w["day"] == 132
    assert w["weather"] == "dust storm"
    assert w["location"] == "Dust Pilgrim's Rest"
    assert w["supply_mode"] == "abundant"
    assert w["wealth_tokens"] == 22280
    assert w["in_combat"] is True
    assert w["parley_count"] == 1


def test_world_summary_none_on_no_view():
    assert model.world_summary(None) is None


# -- parleys_list --------------------------------------------------------

def test_parleys_list_shape(view_fixture):
    assert model.parleys_list(view_fixture) == [{"slug": "warden-hessa", "tier": 2}]


def test_parleys_list_empty_state(view_fixture):
    view_fixture["open_parleys"] = []
    assert model.parleys_list(view_fixture) == []


def test_parleys_list_no_view():
    assert model.parleys_list(None) == []


# -- read_artifacts: missing / malformed -----------------------------------

def test_read_artifacts_missing_files_returns_placeholder_state(tmp_path):
    view, map_text, stale = model.read_artifacts(tmp_path)
    assert view is None
    assert map_text is None
    assert stale is False


def test_read_artifacts_malformed_json_is_stale_not_crash(tmp_path):
    (tmp_path / "player_view.json").write_text("{not valid json", encoding="utf-8")
    view, map_text, stale = model.read_artifacts(tmp_path)
    assert view is None
    assert stale is True


def test_read_artifacts_happy_path(tmp_path, view_fixture):
    (tmp_path / "player_view.json").write_text(json.dumps(view_fixture), encoding="utf-8")
    (tmp_path / "player_map.txt").write_text("###\n#@#\n###\n", encoding="utf-8")
    view, map_text, stale = model.read_artifacts(tmp_path)
    assert view["day"] == 132
    assert map_text == "###\n#@#\n###\n"
    assert stale is False


# -- read_artifacts: never opens any other file ----------------------------

def test_read_artifacts_never_opens_other_files(tmp_path, view_fixture, monkeypatch):
    """The never-opens-other-files property: a decoy secret file living in the
    same campaign dir must never be read by read_artifacts."""
    (tmp_path / "player_view.json").write_text(json.dumps(view_fixture), encoding="utf-8")
    (tmp_path / "player_map.txt").write_text("map", encoding="utf-8")
    decoy = tmp_path / "ANTAGONIST_CULTIVATION.md"
    decoy.write_text("SECRET-DECOY-SHOULD-NEVER-BE-READ-QUUX", encoding="utf-8")

    opened = []
    real_read_text = Path.read_text

    def tracking_read_text(self, *args, **kwargs):
        opened.append(str(self))
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", tracking_read_text)

    model.read_artifacts(tmp_path)

    assert str(decoy) not in opened
    assert str(tmp_path / "player_view.json") in opened
    assert str(tmp_path / "player_map.txt") in opened
