"""
Full save/load game-state round-trip test.

Locks the CLAUDE.md "compact MUST preserve" contract across the
prepare_save_state -> confirm_save (-> save_state) -> read-back cycle.

The contract (from CLAUDE.md "Compact MUST preserve"):
    day + date, location (scene + overworld), active prep,
    party HP / level / XP, emotional states of present characters.

These survive the save in three different stores, so this test verifies
each store rather than assuming one function returns everything:
  - day + date, location, active prep, emotional states  -> CURRENT_STATUS.md
  - party HP                                              -> CURRENT_STATUS.md PARTY HP STATUS
                                                            (synced FROM the character files)
  - party level / XP                                      -> characters/*.json (must be untouched)
  - day                                                   -> load_last_session() + characters/_meta.json

Isolation: conftest.py's autouse `isolate_campaign_dir` fixture redirects
server.CAMPAIGN_DIR to a per-test temp directory, so this never touches the
live save. We additionally seed a realistic character/status layout INTO that
temp dir before each test.

Source of truth for behaviour: server.py prepare_save_state / confirm_save /
save_state / load_last_session (read 2026-06-07 audit remediation).
"""

import json
import re
import sys
from pathlib import Path

import pytest

# Mirror the import convention used by the rest of the suite. pytest's rootdir
# insertion makes `server` importable; the conftest env-var trick makes it load
# against a temp campaign dir.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server  # noqa: E402
from server import (  # noqa: E402
    prepare_save_state,
    confirm_save,
    load_last_session,
)


# ----------------------------------------------------------------------------
# Fixture: seed a realistic campaign layout into the isolated temp dir
# ----------------------------------------------------------------------------

# What we will save and then expect to read back unchanged.
SAVE_DAY = 51            # one above the conftest-seeded Day 50; passes the
                         # day-regression guard (>= meta_day - 2)
SCENE_LOCATION = "Ceruline Arcology — Varro's office, Tier 5"
ACTIVE_PREP = ("CERULINE_ARCOLOGY_PREP.md (forward base = Tier 5); "
               "PLANEYFOLK_CONTACT_PREP for the midnight return to the sill")
EMOTIONAL_STATES = {
    "Creenash": "resolute, quiet hatred held at bay",
    "Vela": "offensive posture, protective",
}
# Per-character ground truth that MUST survive the round-trip.
PARTY = {
    "creenash": {"name": "Creenash", "level": 4,
                 "xp": {"current": 0, "needed": 4},
                 "hp": {"current": 19, "max": 23}},
    "vela": {"name": "Vela", "level": 4,
             "xp": {"current": 2, "needed": 5},
             "hp": {"current": 24, "max": 24}},
}


@pytest.fixture
def seeded_campaign(isolate_campaign_dir):
    """
    Build a realistic campaign dir on top of the isolated temp dir.

    `isolate_campaign_dir` (autouse in conftest) has already pointed
    server.CAMPAIGN_DIR at a temp directory and dropped minimal files there.
    Here we overwrite CURRENT_STATUS.md with a full structure and create the
    split character files, so the save tooling has real HP/level/XP to sync.
    """
    campaign = Path(server.CAMPAIGN_DIR)

    # --- split character files + meta ---
    chars_dir = campaign / "characters"
    chars_dir.mkdir(exist_ok=True, parents=True)
    for key, data in PARTY.items():
        (chars_dir / f"{key}.json").write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )
    (chars_dir / "_meta.json").write_text(
        json.dumps(
            {"version": 1, "last_updated": "2026-01-01",
             "campaign_day": 50, "system": "Vaults of Vaarn"},
            indent=2,
        ),
        encoding="utf-8",
    )

    # --- a full CURRENT_STATUS.md: header, scene state, active prep,
    #     arc, an empty emotional-state placeholder is NOT pre-seeded
    #     (save_state inserts it), and a PARTY HP STATUS table to sync into ---
    status = campaign / "CURRENT_STATUS.md"
    status.write_text(
        "# CURRENT STATUS - DAY 50\n"
        "\n"
        "**Last Updated:** 2026-01-01 00:00\n"
        "\n"
        "---\n"
        "\n"
        "## SCENE STATE (check_canon reads this section)\n"
        "\n"
        "**Day:** 50\n"
        "**Location:** Old Location (should be overwritten)\n"
        "**Present:** Creenash, Vela\n"
        "\n"
        "---\n"
        "\n"
        # Active Prep lives in its OWN section in production (## ACTIVE SCENE),
        # NOT inside SCENE STATE. save_state rebuilds SCENE STATE wholesale, so
        # the only safe home for Active Prep is a separate section like this.
        "## ACTIVE SCENE (Conductor tracks this)\n"
        "\n"
        f"**Active Prep:** {ACTIVE_PREP}\n"
        "\n"
        "---\n"
        "\n"
        "## PARTY HP STATUS\n"
        "\n"
        "| Character | Current | Max | Notes |\n"
        "|-----------|---------|-----|-------|\n"
        "| Creenash | 0 | 0 | stale |\n"
        "| Vela | 0 | 0 | stale |\n"
        "\n"
        "---\n",
        encoding="utf-8",
    )

    # --- fresh continuity file (so load_last_session has a clean slate) ---
    (campaign / "MASTER_CONTINUITY_CURRENT.md").write_text(
        "# MASTER CONTINUITY - CURRENT SESSION\n\n", encoding="utf-8"
    )

    return campaign


# ----------------------------------------------------------------------------
# Helper: run the real save round-trip and return the post-save artifacts
# ----------------------------------------------------------------------------

def _do_roundtrip(narrative_log):
    """prepare_save_state -> grab token -> confirm_save. Returns confirm output."""
    preview = prepare_save_state(
        session_summary="Round-trip contract test session.",
        day=SAVE_DAY,
        narrative_log=narrative_log,
        scene_location=SCENE_LOCATION,
        characters_present="Creenash, Vela",
        last_speaker="Vela",
        last_beat="Defense is finished. Now we choose the Houses.",
        tension_mood="resolute, offensive",
        next_expected="Descend to the Chrysalis Tier",
        current_arc="Houses Offensive",
        arc_summary="Party flips from defensive to offensive toward the Houses.",
        arc_tension="Which Houses fall first.",
        emotional_states=EMOTIONAL_STATES,
    )
    # The token is printed as: CONFIRMATION TOKEN: <token>
    # It is exactly 8 hex chars (md5 hexdigest[:8]); the surrounding output may
    # glue the trailing "====" line on with no separator, so match precisely.
    m = re.search(r"CONFIRMATION TOKEN:\s*([0-9a-f]{8})", preview)
    assert m, f"No confirmation token in prepare_save_state output:\n{preview}"
    token = m.group(1)

    result = confirm_save(token=token)
    assert "ERROR" not in result, f"confirm_save returned an error:\n{result}"
    return result


# ----------------------------------------------------------------------------
# Tests — one assertion cluster per contract element
# ----------------------------------------------------------------------------

def test_confirm_save_names_distill_index_step(seeded_campaign):
    """Step 6->7 reflex push: a committed save names the distill_session INDEX
    call in-band, so a post-compaction DM is pulled into Step 7 even without the
    session-end skill's checklist."""
    result = _do_roundtrip(narrative_log="A beat for the index-push test.")
    assert 'distill_session(action="write"' in result
    assert "index step 7" in result


def test_day_and_date_survive_roundtrip(seeded_campaign):
    """day + date: header, scene state, _meta.json, and load_last_session."""
    _do_roundtrip(narrative_log="A short narrative beat for the log.")

    status = (seeded_campaign / "CURRENT_STATUS.md").read_text(encoding="utf-8")

    # Day in the header
    assert f"# CURRENT STATUS - DAY {SAVE_DAY}" in status, \
        "Day not updated in CURRENT_STATUS.md header"
    # Day in scene state
    assert re.search(rf"\*\*Day:\*\*\s*{SAVE_DAY}\b", status), \
        "Day not updated in SCENE STATE"
    # A real timestamp was stamped (date present, not the stale placeholder)
    assert re.search(r"\*\*Last Updated:\*\*\s*\d{4}-\d{2}-\d{2} \d{2}:\d{2}", status), \
        "Last Updated timestamp missing/not refreshed"
    assert "2026-01-01 00:00" not in status, "Last Updated was not refreshed"

    # Day synced to the character meta
    meta = json.loads((seeded_campaign / "characters" / "_meta.json").read_text(encoding="utf-8"))
    assert meta["campaign_day"] == SAVE_DAY, "campaign_day not synced in _meta.json"

    # load_last_session reports the same day
    loaded = load_last_session()
    assert f"**Day:** {SAVE_DAY}" in loaded, \
        f"load_last_session did not report Day {SAVE_DAY}:\n{loaded}"


def test_location_survives_roundtrip(seeded_campaign):
    """location (scene + overworld) -> SCENE STATE Location line."""
    _do_roundtrip(narrative_log="Location beat.")
    status = (seeded_campaign / "CURRENT_STATUS.md").read_text(encoding="utf-8")
    assert f"**Location:** {SCENE_LOCATION}" in status, \
        "Scene location not persisted to CURRENT_STATUS.md"
    assert "Old Location (should be overwritten)" not in status, \
        "Stale location was not overwritten"


def test_active_prep_survives_roundtrip(seeded_campaign):
    """active prep: not a save param — must survive untouched, not be clobbered."""
    _do_roundtrip(narrative_log="Prep beat.")
    status = (seeded_campaign / "CURRENT_STATUS.md").read_text(encoding="utf-8")
    assert f"**Active Prep:** {ACTIVE_PREP}" in status, \
        "Active Prep line was lost or altered by the save round-trip"


@pytest.mark.xfail(
    reason=(
        "REAL FRAGILITY (audit 2026-06-07): save_state rebuilds the entire "
        "'## SCENE STATE' section from only its 7 known fields (Day, Location, "
        "Present, Last 3 Beats, Last Speaker, Tension/Mood, Next Expected). Any "
        "OTHER field placed inside that section is silently dropped on save. "
        "Active Prep is safe in production ONLY because it lives in its own "
        "'## ACTIVE SCENE' section (see test_active_prep_survives_roundtrip). "
        "This test documents the data-loss boundary: do NOT add compact-preserve "
        "fields inside SCENE STATE."
    ),
    strict=True,
)
def test_extra_field_inside_scene_state_is_dropped(seeded_campaign):
    """Locks the known data-loss boundary: a custom field inside SCENE STATE
    is NOT carried across the save. If this ever starts passing, save_state has
    been hardened to preserve unknown SCENE STATE fields — update the contract."""
    status_path = seeded_campaign / "CURRENT_STATUS.md"
    content = status_path.read_text(encoding="utf-8")
    # Inject a custom field inside the SCENE STATE block (after Present).
    content = content.replace(
        "**Present:** Creenash, Vela\n",
        "**Present:** Creenash, Vela\n**Custom Marker:** PRESERVE-ME-42\n",
        1,
    )
    status_path.write_text(content, encoding="utf-8")

    _do_roundtrip(narrative_log="Boundary beat.")

    after = status_path.read_text(encoding="utf-8")
    # Expectation under the contract would be preservation; the bug drops it,
    # so this assertion FAILS -> xfail. (strict: if it ever survives, xpass -> fail)
    assert "PRESERVE-ME-42" in after


def test_party_hp_survives_roundtrip(seeded_campaign):
    """party HP -> synced from character files into PARTY HP STATUS table."""
    _do_roundtrip(narrative_log="HP beat.")
    status = (seeded_campaign / "CURRENT_STATUS.md").read_text(encoding="utf-8")

    # Pull the PARTY HP STATUS table rows back out and confirm the numbers
    for key, data in PARTY.items():
        name = data["name"]
        cur = data["hp"]["current"]
        mx = data["hp"]["max"]
        row = re.search(
            rf"\|\s*{re.escape(name)}\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|",
            status,
        )
        assert row, f"No PARTY HP row found for {name}\n{status}"
        assert int(row.group(1)) == cur, \
            f"{name} current HP wrong after round-trip: {row.group(1)} != {cur}"
        assert int(row.group(2)) == mx, \
            f"{name} max HP wrong after round-trip: {row.group(2)} != {mx}"
    # The stale 0/0 values must be gone
    assert "| 0 | 0 |" not in status, "HP sync left stale 0/0 rows"


def test_party_level_and_xp_survive_roundtrip(seeded_campaign):
    """party level / XP live in characters/*.json and must be untouched."""
    _do_roundtrip(narrative_log="Level/XP beat.")
    chars_dir = seeded_campaign / "characters"
    for key, expected in PARTY.items():
        on_disk = json.loads((chars_dir / f"{key}.json").read_text(encoding="utf-8"))
        assert on_disk["level"] == expected["level"], \
            f"{key} level changed across round-trip"
        assert on_disk["xp"] == expected["xp"], \
            f"{key} xp changed across round-trip"
        assert on_disk["hp"] == expected["hp"], \
            f"{key} hp dict mutated across round-trip"


def test_emotional_states_survive_roundtrip(seeded_campaign):
    """emotional states -> EMOTIONAL STATE table in CURRENT_STATUS.md."""
    _do_roundtrip(narrative_log="Emotional beat.")
    status = (seeded_campaign / "CURRENT_STATUS.md").read_text(encoding="utf-8")
    assert "## EMOTIONAL STATE" in status, "EMOTIONAL STATE section not written"
    for name, state in EMOTIONAL_STATES.items():
        # Table row form: | Name | state |
        assert re.search(rf"\|\s*{re.escape(name)}\s*\|\s*{re.escape(state)}\s*\|", status), \
            f"Emotional state for {name} not persisted ({state!r})"


def test_narrative_log_roundtrips_through_load_last_session(seeded_campaign):
    """The narrative log written by the save is what load_last_session reads back."""
    marker = "ROUNDTRIP-MARKER cross-sill communion at the kept_sill"
    _do_roundtrip(narrative_log=f"{marker}\n\nThe sill held. Thresh named ally.")
    loaded = load_last_session()
    assert marker in loaded, \
        f"load_last_session did not return the saved narrative log:\n{loaded}"
    assert f"Day {SAVE_DAY}" in loaded, "load_last_session lost the day stamp"


def test_full_contract_single_roundtrip(seeded_campaign):
    """
    One save, assert every contract element at once — the integration check
    that the stores don't fight each other in a single pass.
    """
    _do_roundtrip(narrative_log="Full-contract integration beat.")
    status = (seeded_campaign / "CURRENT_STATUS.md").read_text(encoding="utf-8")

    # day + date
    assert f"# CURRENT STATUS - DAY {SAVE_DAY}" in status
    assert re.search(rf"\*\*Day:\*\*\s*{SAVE_DAY}\b", status)
    assert re.search(r"\*\*Last Updated:\*\*\s*\d{4}-\d{2}-\d{2}", status)
    # location
    assert f"**Location:** {SCENE_LOCATION}" in status
    # active prep
    assert f"**Active Prep:** {ACTIVE_PREP}" in status
    # HP
    assert re.search(r"\|\s*Creenash\s*\|\s*19\s*\|\s*23\s*\|", status)
    assert re.search(r"\|\s*Vela\s*\|\s*24\s*\|\s*24\s*\|", status)
    # level / XP untouched on disk
    creenash = json.loads((seeded_campaign / "characters" / "creenash.json").read_text(encoding="utf-8"))
    assert creenash["level"] == 4 and creenash["xp"] == {"current": 0, "needed": 4}
    # emotional states
    assert "## EMOTIONAL STATE" in status
    assert re.search(r"\|\s*Creenash\s*\|\s*resolute, quiet hatred held at bay\s*\|", status)


def test_scene_state_managed_block_drops_stray_fields(seeded_campaign):
    """LOCK (audit 2026-06-07, ruling #5): SCENE STATE is a managed block.

    save_state rebuilds it wholesale from the known fields, so a stray field
    hand-written INSIDE the block is dropped by design, while durable data in
    its own section (## ACTIVE SCENE) survives the same save. This pins the
    boundary as known-by-design so it can't silently change unnoticed."""
    status_path = seeded_campaign / "CURRENT_STATUS.md"
    content = status_path.read_text(encoding="utf-8")
    # Inject a stray field INSIDE the SCENE STATE block.
    content = content.replace(
        "**Present:** Creenash, Vela\n",
        "**Present:** Creenash, Vela\n**Stray Note:** delete-me-on-save\n",
        1,
    )
    status_path.write_text(content, encoding="utf-8")

    _do_roundtrip(narrative_log="managed-block boundary test")

    after = status_path.read_text(encoding="utf-8")
    # Stray field inside SCENE STATE is gone (managed block, by design):
    assert "Stray Note" not in after
    assert "delete-me-on-save" not in after
    # Durable data in its OWN section survives the same save:
    assert f"**Active Prep:** {ACTIVE_PREP}" in after
