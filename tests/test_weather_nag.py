"""advance_day weather nag: field-mode push, per-day-advanced count, home silence.

The desert weather hex-walk is pull-only -- nothing advances or surfaces it. The
nag reminds the DM to roll(action="weather") once PER DAY advanced when the party
is out in the field. It NEVER auto-rolls (the DM rules which days count).
"""
import server

from tests.test_supply_tool import _seed, _vela


def _status_md(dirpath, day):
    (dirpath / "CURRENT_STATUS.md").write_text(
        f"# CURRENT STATUS - DAY {day}\n\n**Day:** {day}\n")


def _field_supply(day, pool):
    return {"mode": "field", "pool": pool, "pool_location": "wagon",
            "follower_mouths": 0, "separated": [],
            "ledger": {"day": day, "consumed": {}}}


def _abundant_supply(day):
    return {"mode": "abundant", "pool": None, "follower_mouths": 0,
            "separated": [], "ledger": {"day": day, "consumed": {}}}


def test_field_single_day_pushes_weather_roll(isolate_campaign_dir):
    _status_md(isolate_campaign_dir, 100)
    _seed(isolate_campaign_dir, supply=_field_supply(100, {"food": 10, "water": 10}),
          chars={"vela": _vela()})
    out = server.advance_day(101, "march")
    assert "WEATHER" in out
    assert 'roll(action="weather")' in out
    assert "today's weather" in out
    assert "days passed" not in out  # single-day wording, no multi-day count


def test_field_multiday_jump_reflects_days_advanced(isolate_campaign_dir):
    _status_md(isolate_campaign_dir, 100)
    _seed(isolate_campaign_dir, supply=_field_supply(100, {"food": 30, "water": 30}),
          chars={"vela": _vela()})
    out = server.advance_day(105, "five days crossing the dunes")
    assert "WEATHER" in out
    assert 'roll(action="weather")' in out
    assert "5 days passed" in out  # 5-day jump owes 5 hex-walk steps


def test_abundant_mode_no_weather_nag(isolate_campaign_dir):
    _status_md(isolate_campaign_dir, 100)
    _seed(isolate_campaign_dir, supply=_abundant_supply(100), chars={"vela": _vela()})
    out = server.advance_day(101, "quiet day at home")
    assert "WEATHER" not in out


def test_same_day_no_weather_nag(isolate_campaign_dir):
    _status_md(isolate_campaign_dir, 100)
    _seed(isolate_campaign_dir, supply=_field_supply(100, {"food": 10, "water": 10}),
          chars={"vela": _vela()})
    out = server.advance_day(100, "no time passes")  # days_advanced == 0
    assert "WEATHER" not in out


def test_never_auto_rolls_the_marker(isolate_campaign_dir):
    """The nag pushes the roll; it must not walk weather_state.json itself."""
    _status_md(isolate_campaign_dir, 100)
    _seed(isolate_campaign_dir, supply=_field_supply(100, {"food": 10, "water": 10}),
          chars={"vela": _vela()})
    server.advance_day(101, "march")
    # advance_day must never create or advance the weather marker file.
    assert not (isolate_campaign_dir / "weather_state.json").exists()
