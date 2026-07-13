"""Keyed-vault prep scaffold + encounter-table warning (Bug 8, macOS playtest 1).

vaarn-start used to emit prose prep, so map(init) was never viable: no keyed
rooms, no encounter table, no turn-tracking, no auto-encounter rolls. The engine
already parses `## ROOM:` blocks + a `## ENCOUNTERS` table — it just had no way to
EMIT that schema. map(action="scaffold") now mints the skeleton (engine owns the
format, single source), and init warns loudly when a keyed vault has no encounter
table (the inert-encounter-die failure).
"""
import sys
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from map_system import MapSystem


def _fresh():
    root = Path(tempfile.mkdtemp(prefix="map_scaffold_"))
    return MapSystem(root), root


def test_scaffold_writes_parseable_keyed_prep():
    ms, root = _fresh()
    try:
        out = ms.scaffold_prep("iron_lily", rooms=4)
        assert "Scaffolded" in out
        prep = root / "prep" / "IRON_LILY_PREP.md"
        assert prep.is_file()
        content = prep.read_text(encoding="utf-8")
        # The engine's own parsers must accept what the engine wrote.
        rooms = ms._parse_rooms_from_prep(content)
        assert len(rooms) == 4
        assert any(r.get("is_entrance") for r in rooms.values())   # room_1 is the entrance
        enc = ms._parse_encounters_from_prep(content)
        assert enc is not None
        assert enc["dice_size"] == 6
        assert len(enc["table_entries"]) == 6
    finally:
        shutil.rmtree(root)


def test_scaffold_then_init_is_viable_and_no_warning():
    ms, root = _fresh()
    try:
        ms.scaffold_prep("iron_lily", rooms=3)
        out = ms.init_map_from_prep("iron_lily", "prep/IRON_LILY_PREP.md", "vault")
        assert "Map initialized" in out
        assert "Rooms:** 3" in out
        assert "NO ## ENCOUNTERS TABLE" not in out   # scaffold included one
    finally:
        shutil.rmtree(root)


def test_scaffold_custom_encounter_die():
    ms, root = _fresh()
    try:
        ms.scaffold_prep("deep_vault", rooms=2, encounter_die=12)
        content = (root / "prep" / "DEEP_VAULT_PREP.md").read_text(encoding="utf-8")
        enc = ms._parse_encounters_from_prep(content)
        assert enc["dice_size"] == 12
        assert len(enc["table_entries"]) == 12
    finally:
        shutil.rmtree(root)


def test_scaffold_does_not_overwrite():
    ms, root = _fresh()
    try:
        ms.scaffold_prep("iron_lily", rooms=3)
        again = ms.scaffold_prep("iron_lily", rooms=9)
        assert "already exists" in again
        # original (3 rooms) untouched
        content = (root / "prep" / "IRON_LILY_PREP.md").read_text(encoding="utf-8")
        assert len(ms._parse_rooms_from_prep(content)) == 3
    finally:
        shutil.rmtree(root)


def test_init_warns_when_vault_has_rooms_but_no_encounter_table():
    ms, root = _fresh()
    try:
        prep = root / "prose_vault.md"
        prep.write_text(
            "# Prose Vault\n\n## ROOM: hall\n**Name:** Hall\n**Floor:** 1\n"
            "**Entrance:** true\n**Connections:** (none)\n\nA long hall.\n",
            encoding="utf-8")
        out = ms.init_map_from_prep("prose_vault", "prose_vault.md", "vault")
        assert "Map initialized" in out
        assert "NO ## ENCOUNTERS TABLE" in out     # the inert-encounter-die warning
    finally:
        shutil.rmtree(root)
