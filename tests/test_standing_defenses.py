"""Defenses-before-harm injection (2026-07-19, memory-eater ruling).

On vault/combat turns check_canon surfaces every standing defensive
item/augment/gift so the DM resolves them BEFORE narrating irreversible
consequence — the D134 memory-theft retcon happened because a protective
item surfaced only after the harm was written.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402


def _mk_char(tmp_path, name="Kess", items=None, augments=None, gifts=None):
    char_dir = tmp_path / "characters"
    char_dir.mkdir(exist_ok=True)
    data = {
        "name": name,
        "inventory": {"carried": items or []},
        "augmentations": augments or {},
        "mystic_gifts": gifts or [],
    }
    (char_dir / f"{name.lower()}.json").write_text(json.dumps(data), encoding="utf-8")


def _wire(tmp_path, monkeypatch, vault=True, combat=False):
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    monkeypatch.setattr(server, "_active_vault_turn",
                        lambda: ("thevault", 3) if vault else (None, None))
    monkeypatch.setitem(server.GAME_STATE, "active_combat",
                        {"round": 1} if combat else None)


def test_defensive_items_surface_on_vault_turn(tmp_path, monkeypatch):
    _mk_char(tmp_path, "Kess", items=[
        {"name": "Memetic Shielding Headset", "effect": "Advantage on PSY saves"},
        {"name": "Rope", "effect": "It is rope."},
    ])
    _wire(tmp_path, monkeypatch, vault=True)
    out = server._standing_defenses_injection()
    assert "STANDING DEFENSES" in out
    assert "Memetic Shielding Headset" in out
    assert "Rope" not in out
    assert "BEFORE narrating irreversible harm" in out


def test_augments_and_gifts_scanned(tmp_path, monkeypatch):
    _mk_char(tmp_path, "Roscar",
             augments={"CON": [{"name": "Backup Heart",
                                "effect": "survives lethal heart damage"}]},
             gifts=[{"name": "Mnemonic Aegis",
                     "effect": "Memories cannot be extracted or consumed."}])
    _wire(tmp_path, monkeypatch, vault=True)
    out = server._standing_defenses_injection()
    assert "Backup Heart" in out
    assert "Mnemonic Aegis" in out


def test_silent_outside_vault_and_combat(tmp_path, monkeypatch):
    _mk_char(tmp_path, "Kess", items=[
        {"name": "Memetic Shielding Headset", "effect": "Advantage on PSY saves"}])
    _wire(tmp_path, monkeypatch, vault=False, combat=False)
    assert server._standing_defenses_injection() == ""


def test_combat_alone_triggers(tmp_path, monkeypatch):
    _mk_char(tmp_path, "Kess", items=[
        {"name": "Memetic Shielding Headset", "effect": "Advantage on PSY saves"}])
    _wire(tmp_path, monkeypatch, vault=False, combat=True)
    assert "Memetic Shielding Headset" in server._standing_defenses_injection()


def test_no_defensive_items_yields_empty(tmp_path, monkeypatch):
    _mk_char(tmp_path, "Kess", items=[{"name": "Rope", "effect": "It is rope."}])
    _wire(tmp_path, monkeypatch, vault=True)
    assert server._standing_defenses_injection() == ""


def test_line_cap(tmp_path, monkeypatch):
    items = [{"name": f"Ward Stone {i}", "effect": "Prevents harm."}
             for i in range(20)]
    _mk_char(tmp_path, "Kess", items=items)
    _wire(tmp_path, monkeypatch, vault=True)
    out = server._standing_defenses_injection()
    bullet_lines = [ln for ln in out.splitlines() if ln.startswith("  • ")]
    assert len(bullet_lines) == server._DEFENSES_MAX_LINES
    assert "+8 more" in out


def test_live_roster_probe_counts_only(monkeypatch):
    """Against the real campaign roster (read-only): defensive markers must
    find at least the known standing defenses. Counts only, no content asserts."""
    import os
    campaign = Path(os.environ.get("RUBICON_LIVE_CAMPAIGN_DIR")
                    or Path(__file__).resolve().parent.parent.parent
                    / "rubicon-seven-campaign")
    if not (campaign / "characters").exists():
        return  # no live campaign next door (CI / fresh clone)
    monkeypatch.setattr(server, "CAMPAIGN_DIR", campaign)
    monkeypatch.setattr(server, "_active_vault_turn", lambda: ("probe", 1))
    monkeypatch.setitem(server.GAME_STATE, "active_combat", None)
    out = server._standing_defenses_injection()
    bullets = [ln for ln in out.splitlines() if ln.startswith("  • ")]
    assert len(bullets) >= 3, f"expected >=3 live defenses, got {len(bullets)}"
