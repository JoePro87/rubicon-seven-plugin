"""Unit tests for mechanics_ticker — the player-relay block + rolling ledger.

Covers every event kind, block composition, the empty case, qualitative enemy
thresholds (incl. the 1.0 / 0.5 / 0.0 boundaries), and record_events rolling
cap + fail-open. Persistence tests use tmp_path (never the campaign dir).
"""
import json

import mechanics_ticker as mt


# --- per-kind rendering ------------------------------------------------------

def test_pc_damage_line():
    e = {"kind": "pc_damage", "name": "Creenash", "amount": 7, "dtype": "psychic",
         "old_hp": 25, "new_hp": 18, "hp_max": 25}
    assert mt._format_event(e) == "Creenash: -7 HP (psychic) -> 18/25"


def test_pc_damage_line_no_dtype():
    e = {"kind": "pc_damage", "name": "Creenash", "amount": 3, "dtype": None,
         "old_hp": 25, "new_hp": 22, "hp_max": 25}
    assert mt._format_event(e) == "Creenash: -3 HP -> 22/25"


def test_pc_heal_line():
    e = {"kind": "pc_heal", "name": "Creenash", "amount": 5, "old_hp": 18,
         "new_hp": 23, "hp_max": 25}
    assert mt._format_event(e) == "Creenash: +5 HP -> 23/25"


def test_enemy_damage_line_qualitative():
    e = {"kind": "enemy_damage", "name": "Desiccator (lead)", "pct": 0.3}
    assert mt._format_event(e) == "Desiccator (lead): bloodied"


def test_enemy_ability_line():
    e = {"kind": "enemy_ability", "name": "Desiccator", "stat": "STR"}
    assert mt._format_event(e) == "Desiccator: weakened (STR)"


def test_enemy_ability_line_no_stat():
    e = {"kind": "enemy_ability", "name": "Desiccator", "stat": None}
    assert mt._format_event(e) == "Desiccator: weakened"


def test_condition_gained_line():
    e = {"kind": "condition", "name": "Creenash", "condition": "poisoned",
         "applied": True}
    assert mt._format_event(e) == "Creenash: CONDITION gained - poisoned"


def test_condition_cleared_line():
    e = {"kind": "condition", "name": "Creenash", "condition": "poisoned",
         "applied": False}
    assert mt._format_event(e) == "Creenash: CONDITION cleared - poisoned"


def test_wound_line():
    e = {"kind": "wound", "name": "Creenash", "wound": "torn shoulder"}
    assert mt._format_event(e) == "Creenash: WOUND - torn shoulder"


def test_ability_damage_line():
    e = {"kind": "ability_damage", "name": "Creenash", "stat": "STR",
         "amount": 2, "new_score": 11}
    assert mt._format_event(e) == "Creenash: -2 STR -> 11"


def test_unknown_kind_is_none():
    assert mt._format_event({"kind": "mystery", "name": "X"}) is None


# --- qualitative thresholds, incl. boundaries --------------------------------

def test_enemy_word_thresholds():
    assert mt._enemy_word(1.0) == "unharmed"     # boundary: exactly full
    assert mt._enemy_word(1.5) == "unharmed"
    assert mt._enemy_word(0.75) == "hurt"
    assert mt._enemy_word(0.5) == "bloodied"     # boundary: 0.5 is NOT > 0.5
    assert mt._enemy_word(0.51) == "hurt"
    assert mt._enemy_word(0.01) == "bloodied"
    assert mt._enemy_word(0.0) == "down"         # boundary: exactly zero
    assert mt._enemy_word(-0.2) == "down"


def test_enemy_word_non_numeric_fails_safe():
    assert mt._enemy_word(None) == "hurt"
    assert mt._enemy_word("x") == "hurt"


# --- block composition -------------------------------------------------------

def test_ticker_line_empty():
    assert mt.ticker_line([]) == ""
    assert mt.ticker_line(None) == ""


def test_ticker_line_all_unknown_is_empty():
    assert mt.ticker_line([{"kind": "nope"}]) == ""


def test_ticker_line_has_header_and_indented_lines():
    events = [
        {"kind": "pc_damage", "name": "Creenash", "amount": 7, "dtype": "psychic",
         "old_hp": 25, "new_hp": 18, "hp_max": 25},
        {"kind": "wound", "name": "Creenash", "wound": "seared root"},
    ]
    block = mt.ticker_line(events)
    lines = block.split("\n")
    assert lines[0] == mt.TICKER_HEADER
    assert lines[1] == "   Creenash: -7 HP (psychic) -> 18/25"
    assert lines[2] == "   Creenash: WOUND - seared root"


def test_ticker_line_is_ascii():
    events = [{"kind": "enemy_damage", "name": "Desiccator (lead)", "pct": 0.2}]
    block = mt.ticker_line(events)
    block.encode("ascii")  # raises if any non-ASCII slipped in


# --- persistence -------------------------------------------------------------

def test_record_events_writes_and_caps(tmp_path):
    # 25 events, cap is 20 -> only the last 20 survive, newest last.
    for i in range(25):
        mt.record_events(tmp_path, [{"kind": "pc_damage", "name": f"E{i}",
                                     "amount": 1, "new_hp": 1, "hp_max": 2}])
    data = json.loads((tmp_path / mt.EVENTS_FILENAME).read_text())
    names = [e["name"] for e in data["events"]]
    assert len(names) == 20
    assert names[0] == "E5"
    assert names[-1] == "E24"


def test_record_events_stamps_day(tmp_path):
    (tmp_path / "characters").mkdir()
    (tmp_path / "characters" / "_meta.json").write_text(
        json.dumps({"campaign_day": 135}), encoding="utf-8")
    mt.record_events(tmp_path, [{"kind": "pc_heal", "name": "Creenash",
                                 "amount": 5, "new_hp": 23, "hp_max": 25}])
    data = json.loads((tmp_path / mt.EVENTS_FILENAME).read_text())
    assert data["events"][0]["day"] == 135


def test_record_events_empty_is_noop(tmp_path):
    mt.record_events(tmp_path, [])
    assert not (tmp_path / mt.EVENTS_FILENAME).exists()


def test_record_events_fail_open(tmp_path):
    # A non-serializable event must not raise (fail-open).
    mt.record_events(tmp_path, [{"kind": "pc_damage", "name": object()}])
    # no exception == pass


def test_last_events_absent_is_empty(tmp_path):
    assert mt.last_events(tmp_path) == []


def test_last_events_returns_tail(tmp_path):
    for i in range(8):
        mt.record_events(tmp_path, [{"kind": "pc_damage", "name": f"E{i}",
                                     "amount": 1, "new_hp": 1, "hp_max": 2}])
    tail = mt.last_events(tmp_path, 3)
    assert [e["name"] for e in tail] == ["E5", "E6", "E7"]


# --- append_ticker seam ------------------------------------------------------

def test_append_ticker_appends_block(tmp_path):
    events = [{"kind": "pc_damage", "name": "Creenash", "amount": 7,
               "dtype": "psychic", "old_hp": 25, "new_hp": 18, "hp_max": 25}]
    out = mt.append_ticker("PROSE", events, campaign_dir=tmp_path)
    assert out.startswith("PROSE\n\n")
    assert mt.TICKER_HEADER in out
    assert out.rstrip().endswith("Creenash: -7 HP (psychic) -> 18/25")
    # and it persisted
    assert (tmp_path / mt.EVENTS_FILENAME).exists()


def test_append_ticker_empty_unchanged(tmp_path):
    assert mt.append_ticker("PROSE", [], campaign_dir=tmp_path) == "PROSE"
    assert not (tmp_path / mt.EVENTS_FILENAME).exists()


def test_enemy_damage_quantized_at_rest(tmp_path):
    """The stored ledger feeds player_view (player-facing): enemy events must
    persist the qualitative word only, never the exact HP fraction."""
    mt.record_events(tmp_path, [{"kind": "enemy_damage", "name": "Desiccator", "pct": 0.42}])
    evs = mt.last_events(tmp_path)
    assert evs and evs[-1]["kind"] == "enemy_damage"
    assert evs[-1].get("state") == "bloodied"
    assert "pct" not in evs[-1]
