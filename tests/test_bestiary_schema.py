import json
from pathlib import Path

BESTIARY = Path(__file__).resolve().parents[1] / "data" / "rules" / "rulebook" / "bestiary.json"
VALID_TYPES = {"Biological", "Synthetic", "Psychic", "Fungal", "Mineral", "Hypergeometric", "Outsider"}


def _entries():
    return json.loads(BESTIARY.read_text(encoding="utf-8"))["entries"]


def test_every_entry_has_recognized_type():
    bad = []
    for e in _entries():
        if "combat_active" not in e.get("contexts", []):
            continue  # type is a combat concern; non-combat lore entries are exempt
        raw = e.get("stats", {}).get("type") or e.get("stats", {}).get("types") or ""
        parts = [p.strip() for p in str(raw).replace(",", "/").split("/") if p.strip()]
        if not parts or any(p not in VALID_TYPES for p in parts):
            bad.append((e.get("id"), raw))
    assert not bad, f"{len(bad)} entries with missing/unknown type: {bad[:10]}"


def test_every_combat_entry_has_resistances_object():
    missing = []
    for e in _entries():
        if "combat_active" in e.get("contexts", []):
            r = e.get("stats", {}).get("resistances")
            if not isinstance(r, dict):
                missing.append(e.get("id"))
    assert not missing, f"{len(missing)} combat creatures lack a resistances object: {missing[:10]}"
