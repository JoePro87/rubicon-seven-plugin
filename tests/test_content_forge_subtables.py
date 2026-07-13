"""Verifies the vault / monster_lair location subtables are wired and backed.

History: a parity audit found that the location_type d20 table names rolls
4 = "Vault" and 5 = "Monster Lair", and location_type_map sends those rolls to
keys "vault"/"monster_lair" -- but neither had a backing table, so a random
location roll of 4 or 5 fell through to a degraded
"No subtable available for this type" response in ``_roll_location_subtable``.

Fix (2026-05-31): both tables were transcribed from Vaults of Vaarn 2e canon
(Vault d20, Monster Lair d100) into content_forge_tables.json. No dispatch-code
change was needed -- ``roll_on_table`` already honors each table's ``die`` and
``location_type_map`` already pointed rolls 4/5 at these keys.

Symbol notes: the dispatch lives on the ``ContentForge`` instance --
``ContentForge.tables`` (the backing-table dict) and
``ContentForge.location_type_map`` (the d20-roll -> subtable-key map). The
module-level ``LOCATION_SUBTABLES`` list inside ``register_content_forge_tools``
is the manual-mode accept-list and is not directly importable; it is covered
indirectly by the dispatch behavior here.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import content_forge

DATA_DIR = Path(__file__).parent.parent / "data"
DEGRADED = "No subtable available for this type"


def _forge():
    return content_forge.ContentForge(DATA_DIR)


def test_vault_and_monster_lair_have_backing_tables():
    """Both subtable keys now resolve to real tables (no fallthrough).

    If this FAILS, the backing tables were lost/renamed -- re-check
    content_forge_tables.json.
    """
    forge = _forge()
    assert "vault" in forge.tables
    assert "monster_lair" in forge.tables


def test_vault_table_shape():
    forge = _forge()
    vault = forge.tables["vault"]
    assert vault["die"] == "d20"
    assert len(vault["entries"]) == 20
    cols = list(vault["entries"][0]["fields"].keys())
    assert cols == ["Vault Entrance", "The Tunnels", "Original Function"]


def test_monster_lair_table_shape():
    forge = _forge()
    lair = forge.tables["monster_lair"]
    assert lair["die"] == "d100"
    assert len(lair["entries"]) == 100
    cols = list(lair["entries"][0]["fields"].keys())
    assert cols == ["Inhabitants", "Location", "Omen"]


def test_rolling_vault_returns_real_entry():
    forge = _forge()
    entry, _, err = forge.roll_on_table("vault", 1)
    assert err is None
    assert entry["fields"]["Vault Entrance"] == "Steel Blast Doors"


def test_rolling_monster_lair_returns_real_entry():
    forge = _forge()
    entry, _, err = forge.roll_on_table("monster_lair", 100)
    assert err is None
    assert entry["fields"]["Inhabitants"] == "2d10 Zoanthropes"


def test_location_dispatch_rolls_4_and_5_no_longer_degrade():
    """The reachability path that used to dead-end: a location_type roll of
    4 (Vault) or 5 (Monster Lair) now selects a key with a real backing table.
    """
    forge = _forge()
    for d20_roll, expected_loc, expected_key in (
        (4, "Vault", "vault"),
        (5, "Lair", "monster_lair"),  # certified table-region-location-type names roll 5 "Lair"
    ):
        type_entry, _, err = forge.roll_on_table("location_type", d20_roll)
        assert err is None
        assert type_entry["fields"]["Location"] == expected_loc

        subtable_key = forge.location_type_map.get(str(d20_roll))
        assert subtable_key == expected_key
        # The fallthrough guard in _roll_location_subtable is
        # `subtable_key not in forge.tables` -- assert it would NOT trigger.
        assert subtable_key in forge.tables

        # And an actual roll on the selected subtable produces a real entry.
        entry, _, sub_err = forge.roll_on_table(subtable_key)
        assert sub_err is None
        assert entry is not None
        rendered = " | ".join(f"{k}: {v}" for k, v in entry["fields"].items())
        assert DEGRADED not in rendered
