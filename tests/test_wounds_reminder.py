# tests/test_wounds_reminder.py
# Budget rules ARE the acceptance criteria (spec §7, Joe's constraint):
# silent when clean; one line per wounded PC; derived/owed only (mutations
# never restated); high-stakes always shown; broken items never pushed here.
import json
from pathlib import Path
import importlib.util

HOOK = Path(__file__).resolve().parents[1] / "hooks" / "phrase_reminder.py"
spec = importlib.util.spec_from_file_location("phrase_reminder", HOOK)
pr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pr)


def _write_char(dirpath, name, carried=None, capacity=13, wounds=None,
                gifts=0, codices=0):
    (dirpath / "characters").mkdir(exist_ok=True)
    wounds = wounds or []
    wound_slots = sum(r.get("slots", 0) for r in wounds if isinstance(r, dict))
    (dirpath / "characters" / f"{name.lower()}.json").write_text(json.dumps({
        "name": name, "slot_capacity_total": capacity,
        "wounds": wounds, "wounds_slots_used": wound_slots,
        "mystic_gifts": ["g"] * gifts, "codices": ["c"] * codices,
        "inventory": {"carried": carried or []},
    }))


# --- Budget rule 1: silent when clean (the common case = zero tokens) ---

def test_silent_when_no_wounds(tmp_path):
    _write_char(tmp_path, "Kess", carried=[{"name": "Rope", "slots": 1}])
    assert pr._build_wounds_block(tmp_path) == ""


def test_silent_when_no_characters_dir(tmp_path):
    assert pr._build_wounds_block(tmp_path) == ""


# --- Budget rule 2: one line per wounded PC, derived-only content ---

def test_one_line_per_wounded_pc_derived_only(tmp_path):
    # Crippling Wound carries a derived effect (DIS DEX); Major Fracture is a
    # pure rolled-once mutation -> NAME ONLY, its stat damage already on sheet.
    _write_char(tmp_path, "Vela", wounds=[
        {"name": "Crippling Wound", "slots": 1, "dis_saves": ["DEX"],
         "effect": "DIS on DEX saves"},
        {"name": "Major Fracture", "slots": 2, "effect": "-d6 STR and -d6 DEX"},
    ])
    block = pr._build_wounds_block(tmp_path)
    assert block.startswith("WOUNDS: ")
    assert "Crippling Wound(DIS DEX)" in block
    assert "Major Fracture" in block
    # Mutation effect text NEVER restated
    assert "-d6" not in block
    assert "STR" not in block.split("Major Fracture")[1]
    # One line for the one wounded PC
    assert len(block.splitlines()) == 1


def test_mutation_only_wound_name_only(tmp_path):
    _write_char(tmp_path, "Vela", wounds=[
        {"name": "Bloody Gash", "slots": 1, "effect": "-d8 max HP"},
    ])
    block = pr._build_wounds_block(tmp_path)
    assert "Bloody Gash" in block
    assert "Bloody Gash(" not in block      # no parens on a pure mutation
    assert "max HP" not in block            # effect text absent
    assert "d8" not in block


# --- Budget rule 3: high-stakes states always shown while active ---

def test_unconscious_shows_auto_hit(tmp_path):
    _write_char(tmp_path, "Roscar", wounds=[
        {"name": "Supercoolant Leak", "slots": 1, "deprived": True,
         "effect": "Deprived; cannot regain HP until this Wound is fixed"},
        {"name": "Cracked Skull", "slots": 2, "unconscious": True,
         "effect": "-d8 INT and -d8 PSY. Pass out."},
    ])
    block = pr._build_wounds_block(tmp_path)
    assert "Supercoolant Leak(DEPRIVED no-HP-regain)" in block
    assert "UNCONSCIOUS(attacks auto-hit)" in block
    assert "d8" not in block   # mutation magnitudes never restated


def test_unconscious_duration_shown_when_present(tmp_path):
    _write_char(tmp_path, "Roscar", wounds=[
        {"name": "Motive Drive Inhibited", "slots": 5, "unconscious": True,
         "duration": "4 hours", "effect": "-10 STR/DEX/CON; shut down d6 hours"},
    ])
    block = pr._build_wounds_block(tmp_path)
    assert "UNCONSCIOUS(attacks auto-hit, 4 hours)" in block


def test_deaths_door_shown(tmp_path):
    _write_char(tmp_path, "Vela", wounds=[
        {"name": "Death's Door", "slots": 5, "deaths_door": True,
         "unconscious": True,
         "effect": "Any further damage is LETHAL until this wound is healed."},
    ])
    block = pr._build_wounds_block(tmp_path)
    assert "DEATH'S DOOR(next damage kills)" in block
    assert "UNCONSCIOUS(attacks auto-hit)" in block


def test_must_drop_correct_number(tmp_path):
    # cap 13, wound slots 5 -> gear room 8; gear = 9 carried + 1 gift = 10 -> drop 2
    _write_char(tmp_path, "Vela", capacity=13, gifts=1,
                carried=[{"name": "Loot", "slots": 9}],
                wounds=[{"name": "Death's Door", "slots": 5,
                         "deaths_door": True, "unconscious": True,
                         "effect": "lethal"}])
    block = pr._build_wounds_block(tmp_path)
    assert "MUST DROP 2" in block


def test_no_must_drop_when_gear_fits(tmp_path):
    _write_char(tmp_path, "Vela", capacity=13,
                carried=[{"name": "Rope", "slots": 1}],
                wounds=[{"name": "Bloody Gash", "slots": 1, "effect": "-d8 max HP"}])
    block = pr._build_wounds_block(tmp_path)
    assert "MUST DROP" not in block


def test_pending_ko_save_call_line_double_quoted(tmp_path):
    _write_char(tmp_path, "Petros", wounds=[
        {"name": "Knocked Out", "slots": 0, "pending_con_save": True,
         "effect": "CON save vs unconscious d6 rounds"},
    ])
    block = pr._build_wounds_block(tmp_path)
    assert ("Knocked Out: CON save owed -> "
            'affliction(kind="wound", action="ko_save", character="Petros", result="pass"|"fail")') in block
    # double-quoted args (apostrophe-safe, U2 pattern) — no single-quoted args
    assert "character='Petros'" not in block


# --- Budget rule 4: broken items NEVER appear here (use-time only) ---

def test_broken_items_not_pushed_clean_pc(tmp_path):
    _write_char(tmp_path, "Kess",
                carried=[{"name": "Blowtorch", "slots": 1, "broken": True}])
    assert pr._build_wounds_block(tmp_path) == ""


def test_broken_items_not_pushed_wounded_pc(tmp_path):
    _write_char(tmp_path, "Vela",
                carried=[{"name": "Blowtorch", "slots": 1, "broken": True}],
                wounds=[{"name": "Bloody Gash", "slots": 1, "effect": "-d8 max HP"}])
    block = pr._build_wounds_block(tmp_path)
    assert "Blowtorch" not in block
    assert "broken" not in block.lower()


# --- Derived parens vocabulary (compact) ---

def test_av_penalty_and_double_damage_parens(tmp_path):
    _write_char(tmp_path, "Roscar", wounds=[
        {"name": "Synthskin Damaged", "slots": 2, "av_penalty": 3,
         "double_damage": True, "effect": "-d4 AV; suffer double damage"},
    ])
    block = pr._build_wounds_block(tmp_path)
    assert "Synthskin Damaged(-3 AV, dbl dmg)" in block


def test_blind_parens(tmp_path):
    _write_char(tmp_path, "Roscar", wounds=[
        {"name": "Vischip Disabled", "slots": 3, "blind": True,
         "effect": "Blind: cannot make ranged attacks; melee attacks at DIS"},
    ])
    block = pr._build_wounds_block(tmp_path)
    assert "Vischip Disabled(BLIND)" in block


def test_until_fixed_compressed(tmp_path):
    _write_char(tmp_path, "Roscar", wounds=[
        {"name": "Incompatible Motion Interface", "slots": 2,
         "until_fixed_penalty": {"STR": 4, "DEX": 2},
         "effect": "-d6 STR and -d6 DEX until fixed"},
    ])
    block = pr._build_wounds_block(tmp_path)
    assert "Incompatible Motion Interface(-4 STR/-2 DEX until fixed)" in block


def test_daily_tick_compressed(tmp_path):
    _write_char(tmp_path, "Roscar", wounds=[
        {"name": "Cascading Kinesthetics Debilitation", "slots": 3,
         "daily_tick": {"STR": 2, "DEX": 2},
         "effect": "Lose 2 STR and 2 DEX per day"},
    ])
    block = pr._build_wounds_block(tmp_path)
    assert "Cascading Kinesthetics Debilitation(-2 STR/DEX per day)" in block


# --- Multi-PC: stable ordering (sorted by filename, like the LOAD block) ---

def test_multi_pc_ordering_stable(tmp_path):
    _write_char(tmp_path, "Zed", wounds=[
        {"name": "Bloody Gash", "slots": 1, "effect": "-d8 max HP"}])
    _write_char(tmp_path, "Anna", wounds=[
        {"name": "Crippling Wound", "slots": 1, "dis_saves": ["DEX"],
         "effect": "DIS on DEX saves"}])
    block = pr._build_wounds_block(tmp_path)
    lines = block.splitlines()
    assert lines[0].startswith("WOUNDS: Anna - ")
    assert lines[1] == "  Zed - Bloody Gash"
    assert block.index("Anna") < block.index("Zed")


def test_skips_malformed_json_and_legacy_records(tmp_path):
    _write_char(tmp_path, "Vela", wounds=[
        {"name": "Bloody Gash", "slots": 1, "effect": "-d8 max HP"},
        "legacy string wound",   # non-dict record contributes nothing, no crash
    ])
    (tmp_path / "characters" / "bad.json").write_text("{ not valid json ")
    block = pr._build_wounds_block(tmp_path)
    assert "Bloody Gash" in block
    assert "legacy" not in block


# --- Review fixes: KO rounds + zero-slot drop gate ---

def test_unconscious_shows_ko_save_rounds(tmp_path):
    # A FAILED KO save stores unconscious_rounds (not duration) -- the push
    # must surface the round count, the DM ticks it down.
    _write_char(tmp_path, "Petros", wounds=[
        {"name": "Knocked Out", "slots": 0, "special": "knocked_out",
         "effect": "...", "unconscious": True, "unconscious_rounds": 3},
    ])
    block = pr._build_wounds_block(tmp_path)
    assert "UNCONSCIOUS(attacks auto-hit, 3 rounds)" in block


def test_zero_slot_wound_never_forces_drop_on_voluntary_encumbrance(tmp_path):
    # Voluntarily Encumbered (gear 15 > cap 13, U2-legal) + a ZERO-slot wound
    # (KO) -> the wound evicted nothing; MUST DROP must NOT fire (that gear
    # state is the LOAD block's Encumbered business).
    _write_char(tmp_path, "Vela", capacity=13,
                carried=[{"name": "Loot", "slots": 15}],
                wounds=[{"name": "Knocked Out", "slots": 0,
                         "special": "knocked_out", "effect": "...",
                         "pending_con_save": True}])
    block = pr._build_wounds_block(tmp_path)
    assert "MUST DROP" not in block
    assert "Knocked Out" in block                  # the wound itself still pushed
