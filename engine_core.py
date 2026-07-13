"""engine_core.py - shared substrate for the Rubicon Seven MCP engine.

Wave 0 of the tool-consolidation / server.py-decomposition program: the bottom
layer that family modules import so they never reach back into server.py (the
circular-import wall). server.py imports these names and re-aliases them, so
nothing else in the codebase changes -- zero behavior delta; the test suite is
the proof.

LAYERING (binding): pure leaf rules-modules (conditions.py / diseases.py /
dice_roller.py / push_format.py / tool_tags.py / ...) stay LEAVES and must NEVER
import engine_core. The dependency arrows point one way:

    leaf rules-modules  <-  engine_core  <-  family modules  <-  server.py

Grow this module one verified slice at a time (each slice: verbatim move ->
re-import in server.py -> py_compile both -> mojibake grep 0 -> full suite).
"""
import json
import logging
import os
import random
from datetime import datetime
from pathlib import Path

from fastmcp.exceptions import ToolError
from dice_roller import DiceRoller
from tool_tags import TOOL_TAGS, Safety
import conditions as _cnd
import wounds as _wnd
import diseases as _dz

# Path to the campaign files. Resolved via rubicon_paths.campaign_dir(): the
# RUBICON_CAMPAIGN_DIR env var still wins (the test suite sets it BEFORE importing
# server -- conftest.py -- for isolation), otherwise it DERIVES the sibling
# "rubicon-seven-campaign" of the engine dir instead of hardcoding a machine path.
# On a sibling-layout install this is byte-identical to the old hardcoded default
# (the engine repo and the campaign repo sit side by side), but it is now portable
# to any machine. Read at import time -- identical
# contract to the old module-level constant. Nothing reassigns this after import;
# server.py re-exports it so `server.CAMPAIGN_DIR` (read widely by tests) keeps
# resolving to the same value.
from rubicon_paths import campaign_dir as _campaign_dir
CAMPAIGN_DIR = _campaign_dir()


def read_file(filename):
    """Read a file from the campaign directory"""
    filepath = os.path.join(CAMPAIGN_DIR, filename)
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        raise ToolError(f"Error reading {filename}: {str(e)}")


def write_file(filename, content):
    """Write content to a file in the campaign directory (atomic, crash-safe).

    Routes through _atomic_text_write so an interrupted write (crash / power
    loss / disk-full) can never destroy the existing file — the target is only
    replaced once the full new bytes have landed in a temp file. advance_day and
    others write CURRENT_STATUS.md through here, so this protects an accumulating
    play-state file, not just this session's bytes.
    """
    filepath = os.path.join(CAMPAIGN_DIR, filename)
    try:
        _atomic_text_write(filepath, content)
        return True
    except Exception as e:
        raise ToolError(f"Error writing {filename}: {str(e)}")


# Engine-bundled rules-data (book content: mutation + bloomboon tables, transport
# speeds, ...). ENGINE-ALWAYS-WINS: these are read ONLY from the engine's own
# folder, never the campaign dir, so book data has exactly one home and the
# "two sources disagree" problem can't recur. Campaign play-state stays in
# CAMPAIGN_DIR. RULES_DATA_DIR is resolved at call time inside read_rules_data,
# so tests can redirect it via monkeypatch.
RULES_DATA_DIR = Path(__file__).resolve().parent / "data" / "rules"


def read_rules_data(relpath):
    """Read a bundled engine rules-data file (resolved under RULES_DATA_DIR)."""
    filepath = RULES_DATA_DIR / relpath
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        raise ToolError(f"Error reading rules-data {relpath}: {str(e)}")


# Shared dice instance (one per process). The dice_roller module is a pure leaf.
dice = DiceRoller(use_crypto_random=False, log_rolls=False)


# In-memory JSON cache: {cache_key: (data, mtime)}. A MUTABLE dict shared
# by-reference -- server.py imports this exact object, so pops/sets from either
# side hit the same cache.
_JSON_CACHE = {}  # {cache_key: (data, mtime)}


def _get_tool_tags(tool_name: str) -> set[str]:
    """Get tags for a tool from the central mapping."""
    return TOOL_TAGS.get(tool_name, {Safety.ALWAYS})


def _atomic_replace_with_retry(tmp_path, path, attempts=5):
    """os.replace(tmp -> path) with a short retry on Windows transient locks.

    On Windows the destination can be TRANSIENTLY locked (AV scanner / search
    indexer / a not-yet-released handle), surfacing as PermissionError
    (WinError 5). Retry briefly before giving up -- this fixes the full-suite-only
    test flake AND hardens live Windows play, where the same lock would otherwise
    lose a save. Shared by _atomic_json_write and _atomic_text_write.
    """
    import time as _time
    for _attempt in range(attempts):
        try:
            tmp_path.replace(path)
            return
        except PermissionError:
            if _attempt == attempts - 1:
                raise
            _time.sleep(0.05 * (_attempt + 1))


def _atomic_text_write(path, content, encoding='utf-8'):
    """Atomically write text to a file (write to .tmp, then atomic replace).

    The crash-safe counterpart to _atomic_json_write for prose play-state files
    (MASTER_CONTINUITY_CURRENT.md, CURRENT_STATUS.md). A plain write_text/open('w')
    truncates the existing file BEFORE the new bytes land, so a crash mid-write
    loses the ENTIRE accumulated file — devastating for the append-of-record
    continuity log. Here the original stays intact until the atomic replace; the
    temp file is cleaned up on failure. Shares the Windows retry loop with
    _atomic_json_write.
    """
    from pathlib import Path
    path = Path(path)
    tmp_path = path.with_suffix(path.suffix + '.tmp')
    try:
        with open(tmp_path, 'w', encoding=encoding) as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        _atomic_replace_with_retry(tmp_path, path)
    except Exception:
        # Never leave a stray temp file behind on failure.
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise
    _JSON_CACHE.pop(str(path), None)


def _atomic_json_write(path, data, indent=2, ensure_ascii=False):
    """Atomically write JSON data to a file (write to .tmp, then rename).

    Also invalidates the JSON cache for this file.
    """
    from pathlib import Path
    path = Path(path)
    tmp_path = path.with_suffix('.tmp')
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=indent, ensure_ascii=ensure_ascii)
        # fsync before the rename: without it a hard OS stop can persist the
        # rename while the data blocks never flush, leaving a blank file with
        # valid metadata (2026-07-06: characters/_meta.json found whitespace-only).
        f.flush()
        os.fsync(f.fileno())
    _atomic_replace_with_retry(tmp_path, path)

    # Invalidate cache for this file
    # Check common cache keys based on filename
    filename = path.name
    if filename == "lorebook.json":
        _JSON_CACHE.pop('lorebook', None)
    elif filename == "characters.json":
        _JSON_CACHE.pop('characters', None)
    elif filename == "RELATIONSHIP_MATRIX.json":
        _JSON_CACHE.pop('relationships', None)
    elif filename == "narrative_threads.json":
        _JSON_CACHE.pop('threads', None)
    elif filename == "npc_states.json":
        _JSON_CACHE.pop('npc_states', None)
    elif filename == "_meta.json" and "characters" in str(path.parent):
        # Character metadata changed - invalidate all character caches
        keys_to_remove = [k for k in _JSON_CACHE.keys() if k.startswith('char_')]
        for k in keys_to_remove:
            _JSON_CACHE.pop(k, None)
    elif filename.endswith(".json") and ("characters" in str(path.parent) or "vehicles" in str(path.parent)):
        # Individual character/vehicle file - invalidate its cache
        char_id = path.stem
        _JSON_CACHE.pop(f'char_{char_id}', None)
    # Also invalidate by full path
    _JSON_CACHE.pop(str(path), None)


# ============================================
# CHARACTER I/O (Wave 0 slice 3)
# ============================================
# Split sheets (characters/*.json + _meta.json) are the sole source of truth.
# Moved verbatim from server.py. Tests monkeypatch server._load_characters /
# server._save_single_character; that still works because server.py re-imports
# these names and the tools-under-test resolve them via server's namespace.

def _load_characters():
    """Load character data from the split sheets (characters/*.json + _meta.json).

    Split sheets are the SOLE source of truth. The legacy monolithic characters.json
    fallback was retired (it silently drifted — missing weapons/range markers), so on
    any failure we return a clear error rather than serving stale combat stats.
    """
    chars_dir = CAMPAIGN_DIR / "characters"
    vehicles_dir = CAMPAIGN_DIR / "vehicles"

    if not (chars_dir.exists() and (chars_dir / "_meta.json").exists()):
        return None, f"Character split sheets not found at {chars_dir} (monolithic characters.json fallback retired)"

    try:
        with open(chars_dir / "_meta.json", 'r', encoding='utf-8') as f:
            meta = json.load(f)
        characters = {}
        for p in sorted(chars_dir.glob("*.json")):
            if p.name == "_meta.json":
                continue
            with open(p, 'r', encoding='utf-8') as f:
                characters[p.stem] = json.load(f)
        if vehicles_dir.exists():
            for p in sorted(vehicles_dir.glob("*.json")):
                with open(p, 'r', encoding='utf-8') as f:
                    characters[p.stem] = json.load(f)
        return {"meta": meta, "characters": characters}, None
    except Exception as e:
        return None, f"Failed to load character split sheets: {e}"


def _save_characters(data):
    """Save all character data to the split sheets (the sole source of truth).

    The monolithic characters.json fallback is retired; create the split dir on a
    fresh campaign so a save can never resurrect the deprecated monolithic file.
    """
    data['meta']['last_updated'] = datetime.now().strftime("%Y-%m-%d")
    chars_dir = CAMPAIGN_DIR / "characters"
    vehicles_dir = CAMPAIGN_DIR / "vehicles"

    chars_dir.mkdir(parents=True, exist_ok=True)
    _atomic_json_write(chars_dir / "_meta.json", data['meta'])
    for key, char in data.get('characters', {}).items():
        if char.get('type') == 'vehicle':
            vehicles_dir.mkdir(parents=True, exist_ok=True)
            _atomic_json_write(vehicles_dir / f"{key}.json", char)
        else:
            _atomic_json_write(chars_dir / f"{key}.json", char)


def _save_single_character(char_id, char_data, data=None):
    """Save a single character file. Falls back to full save if split dir doesn't exist."""
    chars_dir = CAMPAIGN_DIR / "characters"
    vehicles_dir = CAMPAIGN_DIR / "vehicles"

    if chars_dir.exists():
        if char_data.get('type') == 'vehicle':
            vehicles_dir.mkdir(parents=True, exist_ok=True)
            _atomic_json_write(vehicles_dir / f"{char_id}.json", char_data)
        else:
            _atomic_json_write(chars_dir / f"{char_id}.json", char_data)
        # Update meta timestamp
        meta_path = chars_dir / "_meta.json"
        if meta_path.exists():
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            meta['last_updated'] = datetime.now().strftime("%Y-%m-%d")
            _atomic_json_write(meta_path, meta)
    elif data is not None:
        _save_characters(data)
    else:
        logging.warning("_save_single_character: no split dir and no full data provided")


def _load_party():
    """Load party.json"""
    party_path = CAMPAIGN_DIR / "party.json"
    if not party_path.exists():
        return None, "party.json not found"
    with open(party_path, 'r', encoding='utf-8') as f:
        return json.load(f), None


def _find_character(data, name):
    """Find character by name (case-insensitive)"""
    name_lower = name.lower().strip()
    for key, char in data.get('characters', {}).items():
        if key.lower() == name_lower or char.get('name', '').lower() == name_lower:
            return key, char
    return None, None


# ============================================
# GAME STATE (Wave 0 slice 4)
# ============================================
# In-memory session state - resets when server restarts. A MUTABLE dict shared
# by-reference: server.py imports this exact object and tests mutate it in place
# (monkeypatch.setitem / GAME_STATE[key]=), never reassign -- so every side sees
# one session-state dict.
GAME_STATE = {
    "active_location": None,  # Current location prep data
    "active_location_name": None,  # Location identifier
    "active_prep_file": None,  # Path to prep file
    "revealed_rooms": set(),  # Room IDs the party has entered
    "revealed_secrets": set(),  # Secret IDs that have been revealed
    "active_constraints": {},  # constraint_id -> constraint data
    "verified_characters": set(),  # Characters whose stats were fetched this session
    "session_started": False,  # Whether full_session_startup was called
    "active_combat": None,  # Combat state (initiative, enemies, rounds, morale)
    "world_tick": {},  # World-tick state (last_visited stamps for the return-after-absence check)
}


# ============================================
# DEATH-SEAM LEAF HELPERS (death-seam wave, leaf subset)
# ============================================
# Pure/leaf computations of the death subsystem (save-note builders, slot math,
# elixir floor, PC-sheet predicates, morale builders, twinning check, death-seam
# lines/window). The 6 monkeypatched orchestrators (_apply_wound, _death_gate,
# _apply_hp_damage_and_wounds, _check_death_gated, _check_death_conditions,
# _apply_ability_damage_from_wound) STAY in server.py and call these via import
# bindings (server -> engine_core, one-directional). They migrate in the family wave.

def _calculate_slots(char):
    """Calculate slot usage for a character"""
    _inv = char.get('inventory', {})
    # Inventory is normally a dict {carried: [...]}; tolerate a bare list or
    # missing value so a malformed/legacy sheet never crashes a death check.
    _carried_list = _inv.get('carried', []) if isinstance(_inv, dict) else (
        _inv if isinstance(_inv, list) else [])
    carried = sum(item.get('slots', 0) for item in _carried_list
                  if isinstance(item, dict))
    gifts = len(char.get('mystic_gifts', []))  # 1 slot each
    codices = len(char.get('codices', []))  # 1 slot each
    wounds = char.get('wounds_slots_used', 0)

    total_used = carried + gifts + codices
    capacity = char.get('slot_capacity_total', 10)

    return {
        "carried": carried,
        "gifts": gifts,
        "codices": codices,
        "wounds": wounds,
        "total_used": total_used,
        "capacity": capacity,
        "free": capacity - total_used,
        "effective_free": capacity - total_used - wounds,
        "encumbered": (total_used + wounds) > capacity,
    }

def _refresh_slot_fields(char) -> dict:
    """Recompute and persist-in-memory the stored slot fields on a single char.
    Returns the _calculate_slots dict. Call after any inventory/wound change."""
    slots = _calculate_slots(char)
    char["slots_used"] = slots["total_used"]
    char["slots_free"] = slots["free"]
    char["slots_from_gifts"] = slots["gifts"]
    char["slots_from_codices"] = slots["codices"]
    char["slots_from_wounds"] = slots["wounds"]
    char["effective_slots_free"] = slots["effective_free"]
    char["encumbered"] = slots["encumbered"]
    return slots

def _encumbrance_save_note(char, stat: str) -> str:
    """Surfacing suffix for a save prompt: DIS on STR/DEX/CON saves while Encumbered.
    PC saves are player-rolled, so we instruct rather than auto-roll."""
    if str(stat).upper() not in ("STR", "DEX", "CON"):
        return ""
    if not _calculate_slots(char)["encumbered"]:
        return ""
    return " — at **DISADVANTAGE** (Encumbered: roll 2d20, take the worse)"

def _wound_save_note(char, stat: str) -> str:
    """Surfacing suffix for a save prompt: DIS on <stat> saves from active wounds.

    Reach for this WHEN prompting a PC save — the wound DIS is derived (spec
    section 5), so it must be surfaced at the moment of the roll. PC saves are
    player-rolled (Iron Law 3): we INSTRUCT, never auto-roll. Stacks after
    _encumbrance_save_note (a PC can be both Encumbered and wounded)."""
    stat = str(stat).upper()
    records = char.get('wounds', []) or []
    if stat not in _wnd.derived_effects(records).get('dis_saves', []):
        return ""
    names = ", ".join(r.get('name', '?') for r in records
                      if isinstance(r, dict) and stat in (r.get('dis_saves') or []))
    return (f" - at **DISADVANTAGE** ({names or 'wound'}: "
            f"roll 2d20, take the worse)")

def _condition_save_note(char, stat: str) -> str:
    """Surfacing suffix for a save prompt: DIS on <stat> saves from active
    CONDITIONS (E1), plus the E3 Goldencough coughing-fit reminder on CON saves.
    Same contract as _wound_save_note: PC saves are player-rolled, we INSTRUCT.
    Stacks after the wound note."""
    stat = str(stat).upper()
    conds = char.get('conditions') or []
    suffix = ""
    if stat in _cnd.condition_effects(conds).get('dis_saves', []):
        names = ", ".join(c.get('name', '?') for c in conds
                          if isinstance(c, dict)
                          and stat in ((c.get('effects') or {}).get('dis_saves') or []))
        suffix += (f" - at **DISADVANTAGE** ({names or 'condition'}: "
                   f"roll 2d20, take the worse)")
    if stat == "CON":
        for c in conds:
            if not isinstance(c, dict):
                continue
            cd = _dz.DISEASES.get(c.get("name"))
            if cd and cd.get("coughing_fit"):
                suffix += (" - on a FAILED CON save, Goldencough triggers a "
                           "coughing fit: d4 damage + an infectious golden-thread "
                           "cloud (DM runs the fit)")
                break
    return suffix

def _death_window() -> str:
    """The simultaneity window for the Twinning gate (R-E1h): the combat
    round when fighting, otherwise the campaign day."""
    combat = GAME_STATE.get("active_combat")
    if combat:
        return f"combat:r{combat.get('round', 0)}"
    try:
        meta_path = CAMPAIGN_DIR / "characters" / "_meta.json"
        with open(meta_path, 'r', encoding='utf-8') as f:
            day = json.load(f).get('campaign_day')
        if day is not None:
            return f"day:{day}"
    except Exception:
        pass
    return "day:unknown"

def _twinning_partner_check(char, data):
    """Resolve a MUTUAL Twinning bond. Returns (pkey, partner, note).
    (None, None, note) when unprotected - a one-sided record is a severed
    bond (spec: the gate stays open and warns about the mismatch)."""
    eff = _cnd.condition_effects(char.get('conditions') or [])
    pname = eff.get('twinned_partner')
    if not pname:
        return None, None, ""
    pkey, partner = _find_character(data or {}, pname)
    if not partner:
        return None, None, (f"TWINNING mismatch: partner '{pname}' not found - "
                            f"bond treated as severed; death stands.")
    peff = _cnd.condition_effects(partner.get('conditions') or [])
    back = str(peff.get('twinned_partner') or '').strip().lower()
    if back != str(char.get('name', '')).strip().lower():
        return None, None, (f"TWINNING mismatch: bond is one-sided "
                            f"({char.get('name')} -> {pname}, not back) - "
                            f"treated as severed; death stands. Re-stamp both "
                            f"sheets or clear the orphan record.")
    return pkey, partner, ""

def _leader_ego_bonus(data, leader_key):
    """A leader's EGO bonus (dict-or-int shape), mirroring
    _followers.follower_level_cap. 0 when the leader is missing."""
    leader = (data or {}).get("characters", {}).get(leader_key, {})
    ego = leader.get("abilities", {}).get("EGO", {})
    if isinstance(ego, dict):
        return int(ego.get("current", 0) or 0)
    return int(ego or 0)

def _follower_morale_lines(data, dying_key):
    """D2 morale seam (CH p.61): when a rostered character dies, every LIVING
    follower must save Morale on witnessing an allied death. Returns one plain
    push line per such follower (the DM rolls the d20 - this is not a tool
    call). Engine prefills max(own ML, leader EGO bonus). The dying sheet is
    excluded; corpses (hp.current <= -20) are excluded.

    Push-only: the engine NEVER resolves the save; it computes and pushes."""
    lines = []
    for fkey, fchar in (data or {}).get("characters", {}).items():
        if fkey == dying_key or not isinstance(fchar, dict):
            continue
        if fchar.get("type") != "follower":
            continue
        hp = fchar.get("hp")
        if isinstance(hp, dict) and hp.get("current", 0) <= -20:
            continue  # a corpse does not save Morale
        ml = int(fchar.get("ml", 0) or 0)
        ego = _leader_ego_bonus(data, fchar.get("leader"))
        bonus = max(ml, ego)
        lines.append(
            f"MORALE: {fchar.get('name', fkey)} witnessed an allied death - "
            f"roll d20 + {bonus} vs 15 (X = max(own ML {ml}, leader EGO {ego})); "
            f"fail = flees/hides for the rest of this combat (CH p.61)")
    return lines

def _death_seam_lines(char, data, dying_key):
    """The push block emitted at every rostered-death site. PCs get the p.229
    five-path resurrection menu; hirelings (followers AND mercenaries) do NOT
    (resurrection paths are for PCs only - book p.229). Then every living
    follower gets a MORALE line. Built ONCE so the death seams cannot drift
    apart."""
    out = []
    # Resurrection is PC-only (book p.229). Exclude ALL hireling types:
    # follower, mercenary, pet AND steed. NOTE: live PC sheets store their
    # ANCESTRY in `type` (e.g. "True-kin"), so we cannot gate on type=="pc" -
    # we gate on "not a hireling" (the follower-only check, extended over time).
    if not (isinstance(char, dict)
            and char.get("type") in ("follower", "mercenary", "pet", "steed")):
        out.extend(_cnd.resurrection_push())
    out.extend(_follower_morale_lines(data, dying_key))
    # D3 stoic merc morale (CH p.63): mercs sit OUT the per-death follower push
    # entirely; they only check morale when the party WIPES. If this death is a
    # PC's and it leaves no living PC, fire the merc-morale lines (additive).
    if _is_pc_sheet(char) and _all_pcs_down(data):
        out.extend(_merc_morale_lines(data))
    return out

def _elixir_hp_floor(char):
    """B3 R-B3d: active Immortality floor, or None. Consulted by damage
    writers."""
    for c in (char.get("conditions") or []):
        if isinstance(c, dict) and c.get("hp_floor") is not None:
            return int(c["hp_floor"])
    return None

def _is_pc_sheet(char):
    """A roster sheet is a PC when it is NOT a hireling (hireling types are
    'follower'/'mercenary'/'pet'/'steed'). PCs carry their ancestry in
    'species', not 'type' - live PC sheets have type None, but some sheets/
    fixtures put an ancestry in 'type', so exclude-the-hireling is the robust
    test. This MATCHES the resurrection-gate classification at the death seam
    (both must agree)."""
    if not isinstance(char, dict):
        return False
    return char.get("type") not in ("follower", "mercenary", "pet", "steed")

def _all_pcs_down(data):
    """True iff the roster has at least one PC and NO living PC remains (a wipe).
    A PC is 'down' when hp.current <= 0 (book: 0 HP = incapacitated). Uses the
    SAME PC-vs-hireling classification the death seam uses."""
    pcs = [c for c in (data or {}).get("characters", {}).values()
           if _is_pc_sheet(c)]
    if not pcs:
        return False
    for c in pcs:
        hp = c.get("hp")
        cur = hp.get("current", 0) if isinstance(hp, dict) else 0
        if cur > 0:
            return False
    return True

def _merc_morale_lines(data):
    """Stoic merc morale (CH p.63): one push line per LIVING (hp.current > 0)
    mercenary when the party is down. Mercs use their OWN ML (the book gives no
    leader-EGO morale substitution for mercs). Push-only; the DM rolls."""
    lines = []
    for k, c in (data or {}).get("characters", {}).items():
        if not isinstance(c, dict) or c.get("type") != "mercenary":
            continue
        hp = c.get("hp")
        cur = hp.get("current", 0) if isinstance(hp, dict) else 0
        if cur <= 0:
            continue
        ml = int(c.get("ml", 0) or 0)
        lines.append(
            "MERC MORALE: {} - the party is down - d20 + ML +{} vs 15; "
            "fail = withdraws/flees (CH p.63, extreme circumstances).".format(
                c.get("name", k), ml))
    return lines

# Death-seam orchestrator wave: wound-table aliases (mirror server.py 12787-88 so the moved _apply_hp_damage_and_wounds resolves them).
BIOLOGICAL_WOUNDS = _wnd.BIOLOGICAL_WOUNDS
SYNTHETIC_WOUNDS = _wnd.SYNTHETIC_WOUNDS


# ===== Death-seam orchestrators (moved from server.py, verbatim) =====


def _check_death_conditions(char):
    """Check all three death conditions. Returns (is_dead, reason) tuple."""
    # B3 R-B3d belt-and-braces: while the Immortality Injector floor is active,
    # the creature cannot die from HP (even a direct update_hp to -20). The
    # damage clamp normally keeps HP above the floor; this catches manual sets.
    if _elixir_hp_floor(char) is not None:
        return (False, None)
    # Condition 1: HP <= -20
    hp_current = char.get('hp', {}).get('current', 0)
    if hp_current <= -20:
        return (True, "FATALITY: HP dropped to -20 or below")

    # Condition 2: All item slots filled with wounds
    slots = _calculate_slots(char)
    if slots['wounds'] >= slots['capacity']:
        return (True, "DEATH: All item slots filled with wounds")

    # Condition 3: Any ability below -10
    for ability, data in char.get('abilities', {}).items():
        current = data.get('current', 0) if isinstance(data, dict) else data
        if current < -10:
            return (True, f"DEATH: {ability} dropped below -10")

    return (False, None)


def _death_gate(key, char, data, window_key=None, cause="damage"):
    """E1 Twinning (R-E1f/g/h): consult before letting a PC death stand.
    Returns (allowed, lines). On refusal MUTATES char to the brink (HP -19
    floor, abilities -10 floor) and stamps twinning_pending - the caller
    persists char. On a same-window pair the PARTNER dies too (mutated AND
    saved here). Stale pending marks are inert: only an exact window match
    pairs."""
    # B3 R-B3d (adversarial CRITICAL): the Immortality Injector floor beats the
    # death seam itself. Four writers (poison/toxin greater, starvation/thirst,
    # disease/condition clock, Gitchghast transform) snap hp.current=-20 then
    # call here directly, bypassing the _check_death_conditions short-circuit
    # and the combat clamp. Honour the floor BEFORE any Twinning/death logic:
    # clamp HP up to the floor and refuse the death. The creature CANNOT die
    # for the duration (book p.54).
    floor = _elixir_hp_floor(char)
    if floor is not None:
        hp_box = char.get('hp')
        if isinstance(hp_box, dict):
            hp_box['current'] = max(hp_box.get('current', floor), floor)
        return False, [f"**DEATHLESS:** {char.get('name', key)} cannot die -- "
                       f"HP held at {floor} (Immortality Injector, R-B3d)."]
    window_key = window_key or _death_window()
    pkey, partner, note = _twinning_partner_check(char, data)
    lines = [note] if note else []
    if not partner:
        return True, lines
    php = partner.get('hp', {})
    if isinstance(php, dict) and php.get('current', 0) <= -20:
        lines.append(f"TWINNING: {partner.get('name', pkey)} is already dead - "
                     f"the bond is broken; death stands.")
        return True, lines
    pending = partner.get('twinning_pending')
    if isinstance(pending, dict) and pending.get('window') == window_key:
        if isinstance(partner.get('hp'), dict):
            partner['hp']['current'] = -20
        else:
            lines.append(f"WARNING: {partner.get('name', pkey)}'s hp field is "
                         f"not a dict - could not snap HP to -20; fix the sheet "
                         f"and set it manually.")
        partner.pop('twinning_pending', None)
        if data is not None:
            # TEST-ISOLATION NOTE (death-seam orchestrator wave): this call
            # resolves _save_single_character in engine_core's namespace, so a
            # `monkeypatch.setattr(server, "_save_single_character", noop)` does
            # NOT intercept it. Only the twinning-SUNDER path reaches here; a
            # future test that noops the server copy AND drives a sunder must
            # also patch engine_core._save_single_character.
            _save_single_character(pkey, partner, data)
        lines.append(f"**!!! TWINNING SUNDERED: {char.get('name', key)} and "
                     f"{partner.get('name', pkey)} fall in the same window "
                     f"({window_key}) - the Array cannot split the load. "
                     f"BOTH ARE DEAD. !!!**")
        lines.append("Two deaths, two rulings: the p.229 paths below apply to "
                     "EACH of them separately.")
        return True, lines
    hp_box = char.get('hp')
    if isinstance(hp_box, dict):
        if hp_box.get('current', 0) <= -20:
            hp_box['current'] = -19
        brink_hp = hp_box.get('current', '?')
    else:
        lines.append(f"WARNING: {char.get('name', key)}'s hp field is not a "
                     f"dict - could not clamp HP to the brink (-19); fix the "
                     f"sheet and set it manually.")
        brink_hp = '?'
    for ab, v in (char.get('abilities') or {}).items():
        cur = v.get('current', 0) if isinstance(v, dict) else v
        if isinstance(cur, (int, float)) and cur < -10:
            if isinstance(v, dict):
                v['current'] = -10
            else:
                char['abilities'][ab] = -10
    char['twinning_pending'] = {"window": window_key}
    lines.append(f"**TWINNING: death prevented - the Array holds; "
                 f"{partner.get('name', pkey)} lives.** "
                 f"{char.get('name', key)} hangs at the brink "
                 f"(HP {brink_hp}); consequences stand. "
                 f"If {partner.get('name', pkey)} also falls this window "
                 f"({window_key}), BOTH die.")
    return False, lines


def _check_death_gated(key, char, data, window_key=None):
    """Gated replacement for acting on _check_death_conditions.
    Returns (is_dead, reason, lines)."""
    is_dead, reason = _check_death_conditions(char)
    if not is_dead:
        return False, None, []
    allowed, lines = _death_gate(key, char, data, window_key)
    if allowed:
        return True, reason, lines
    return False, None, lines


def _apply_ability_damage_from_wound(char: dict, ability_damage: dict) -> list:
    """Roll and apply ability damage from a wound entry.

    ability_damage values may be dice notation strings ('d6', 'd8') or flat ints (10).
    Reduces char['abilities'][stat]['current'] by the rolled/flat amount.
    Returns a list of description lines for the output.
    """
    output = []
    abilities = char.setdefault('abilities', {})

    for stat, dice_or_value in ability_damage.items():
        stat = stat.upper()

        # Roll or use flat value
        if isinstance(dice_or_value, str):
            roll_result = dice.roll_notation(dice_or_value)
            amount = roll_result['total']
            roll_desc = f"{dice_or_value} = {amount}"
        else:
            amount = int(dice_or_value)
            roll_desc = str(amount)

        # Ensure stat entry exists
        if stat not in abilities:
            abilities[stat] = {'current': 0, 'base': 0}

        if isinstance(abilities[stat], dict):
            old_val = abilities[stat].get('current', 0)
            new_val = old_val - amount
            abilities[stat]['current'] = new_val
        else:
            old_val = abilities[stat]
            new_val = old_val - amount
            abilities[stat] = {'current': new_val, 'base': old_val}

        output.append(f"  {stat}: {old_val:+d} -> {new_val:+d} (rolled {roll_desc})")

        # CON affects slot capacity
        if stat == 'CON':
            char['slot_capacity_bonus'] = new_val
            char['slot_capacity_total'] = 10 + new_val

        # Death check (matches _check_death_conditions: < -10)
        if new_val < -10:
            output.append(f"  **!!! DEATH: {stat} has reached {new_val:+d} (below -10) !!!**")

    return output


def _apply_wound(key, char, data, wound_hp: int, table: dict, _child: bool = False) -> list:
    """Apply the wound at wound_hp (already clamped to -20) from table.

    Returns output lines; the CALLER persists via _save_single_character.
    Derived ('until fixed'/state) effects live on the wound record and are read
    by wounds.derived_effects -- healing the record makes them vanish for free.
    Rolled-once mutations (ability/max-HP/level damage) go through the existing
    appliers here and are never re-applied or reversed by heal.
    _child marks a Bloody Mess child recursion: it skips the forced-drop line so
    only the parent's final (authoritative) number is surfaced.
    """
    entry = _wnd.wound_for_hp(wound_hp, table)
    record = _wnd.roll_wound_record(wound_hp, entry, rng=random.randint)
    wound_list = char.setdefault('wounds', [])
    wound_list.append(record)
    # Recompute as the SUM of record slots (never increment) so removal in
    # _remove_wound stays consistent with what is actually on the list.
    char['wounds_slots_used'] = sum(
        r.get('slots', 0) for r in wound_list if isinstance(r, dict))

    output = [
        "",
        f"**WOUND:** {record['name']} (HP {wound_hp})",
        f"  Effect: {record['effect']}",
        f"  Slots: {record['slots']}",
    ]

    # --- Rolled-once mutations (existing appliers) ---
    if entry.get('ability_damage'):
        output.append("  **Ability Damage Applied:**")
        output.extend(_apply_ability_damage_from_wound(char, entry['ability_damage']))
    if entry.get('max_hp_damage'):
        dice_or_val = entry['max_hp_damage']
        if isinstance(dice_or_val, str):
            roll_result = dice.roll_notation(dice_or_val)
            reduction = roll_result['total']
            roll_desc = f"{dice_or_val} = {reduction}"
        else:
            reduction = int(dice_or_val)
            roll_desc = str(reduction)
        old_max = char.get('hp', {}).get('max', 1)
        new_max = max(1, old_max - reduction)
        char.setdefault('hp', {})['max'] = new_max
        output.append(f"  **Max HP Reduced:** {old_max} -> {new_max} (rolled {roll_desc})")
    if entry.get('level_loss'):
        old_level = char.get('level', 1)
        char['level'] = max(1, old_level - 1)
        if isinstance(char.get('xp'), dict):
            char['xp']['current'] = 0
        else:
            char['xp'] = {'current': 0}
        output.append(f"  **LEVEL LOST:** {old_level} -> {char['level']}; all XP gone "
                      f"(permanent even when this Wound is fixed)")
    if entry.get('reroll_abilities'):
        # Chargen method verified vs extraction batch_02_character_creation.md:
        # roll 3d6 per ability; the LOWEST of the three dice is the bonus.
        output.append("  **Abilities Rerolled (3d6, lowest die = new bonus):**")
        abilities = char.setdefault('abilities', {})
        for stat in entry['reroll_abilities']:
            stat = str(stat).upper()
            rolls = [random.randint(1, 6) for _ in range(3)]
            new_val = min(rolls)
            if isinstance(abilities.get(stat), dict):
                old_val = abilities[stat].get('current', 0)
                abilities[stat]['current'] = new_val
                # The reroll IS the new score: reset base too, or the Long Rest
                # restore path (current -> base) silently un-rerolls it.
                abilities[stat]['base'] = new_val
            else:
                old_val = abilities.get(stat, 0)
                abilities[stat] = {'current': new_val, 'base': new_val}
            output.append(f"  {stat}: {old_val:+d} -> {new_val:+d} (rolled {rolls})")
            if stat == 'CON':
                char['slot_capacity_bonus'] = new_val
                char['slot_capacity_total'] = 10 + new_val
        output.append("  Voice and personality are altered (narrate the change).")

    # --- State callouts (derived; read back via wounds.derived_effects) ---
    # Emitted BEFORE the specials so a Bloody Mess parent's PASSES OUT line
    # reads inside the parent's block, not trailing the last child's.
    if record.get('unconscious'):
        output.append("  **CHARACTER PASSES OUT** (while unconscious, all attacks "
                      "automatically hit) - when they come round (DM-adjudicated): "
                      f'affliction(kind="wound", action="wake", character="{char["name"]}")')
    if record.get('duration'):
        output.append(f"  Duration: {record['duration']} (expiry is DM-adjudicated)")
    if record.get('deaths_door'):
        output.append("  **AT DEATH'S DOOR - ANY FURTHER DAMAGE IS LETHAL until this wound is healed**")
    if record.get('ego_engine_salvageable'):
        output.append("  Note: the Ego Engine is salvageable - it can be installed in a new shell.")
    if record.get('dead'):
        output.append("  **CHARACTER IS DEAD**")

    # --- Specials (KO prompt here; Damaged Item / Bloody Mess land in Task 3) ---
    special = entry.get('special')
    if special == 'knocked_out':
        output.append(
            f"**{char['name']}**: roll CON save vs unconscious (d6 rounds)"
            f"{_encumbrance_save_note(char, 'CON')}{_wound_save_note(char, 'CON')}"
            f"{_condition_save_note(char, 'CON')} - report: "
            f'affliction(kind="wound", action="ko_save", character="{char["name"]}", result="pass"|"fail")')
    elif special == 'damaged_item':
        # d20 vs the carried list expanded IN ORDER: each item occupies
        # item['slots'] consecutive positions (1..N). Past N = empty slot,
        # lucky miss. Only carried gear can break (never gifts/codices/wounds).
        # Zero-slot items occupy no position (same geometry as _calculate_slots,
        # where missing 'slots' defaults to 0) so they can't be struck and
        # don't shift later items' positions.
        slot_roll = random.randint(1, 20)
        carried = (char.get('inventory') or {}).get('carried') or []
        struck = None
        pos = 0  # highest occupied position so far
        for item in carried:
            span = int(item.get('slots', 0) or 0) if isinstance(item, dict) else 0
            if span <= 0:
                continue
            if pos < slot_roll <= pos + span:
                struck = item
                break
            pos += span
        if struck is not None:
            struck['broken'] = True
            output.append(f"  **Damaged Item (d20={slot_roll}):** "
                          f"{struck.get('name', 'item')} is broken - "
                          f"unusable until fixed.")
        else:
            output.append(f"  **Damaged Item (d20={slot_roll}):** struck an empty "
                          f"slot - nothing breaks.")
    elif special == 'bloody_mess':
        # Parent record (slots 0, unconscious) is already on the wound list.
        # Roll the 3 child wounds NOW, before the parent's forced-drop math
        # below, so the final recompute is the authoritative one. Each child:
        # 3d6, rerolling 18 (another Bloody Mess) - so the recursion can
        # never nest.
        output.append("  **Bloody Mess:** rolling 3 random Wounds (3d6 each, 18 rerolls)")
        for _ in range(3):
            s = sum(random.randint(1, 6) for _ in range(3))
            while s == 18:
                s = sum(random.randint(1, 6) for _ in range(3))
            output.extend(_apply_wound(key, char, data, -s, table, _child=True))

    # --- Forced drop (Joe ruling: wounds evict gear; player chooses what) ---
    slots = _refresh_slot_fields(char)
    if not _child and slots['wounds'] > 0:
        # Zero-slot wounds (KO, Damaged Item) evict nothing -- voluntary
        # over-cap gear stays U2-legal Encumbrance, never a forced drop.
        drop = _wnd.forced_drop_slots(slots['total_used'], slots['capacity'], slots['wounds'])
        if drop > 0:
            output.append(f"**MUST DROP {drop} SLOT(S) OF GEAR** - wounds displace items "
                          f"(player chooses what falls).")

    return output


def _apply_hp_damage_and_wounds(key, char, data, damage, window_key=None) -> tuple[list[str], bool]:
    """Unified HP<=0 trigger on an in-memory char dict (wounds spec sections 4-5).
    Mutates char; NEVER saves -- the caller persists (_character_take_damage saves
    directly; the toxin tick saves via _toxin_set). Returns (lines, lethal_dd).

    Sequence: derived-effects pre-read -> Synthskin doubling -> Death's Door
    lethality (snap HP to -20) -> HP subtraction -> wound at <=0 -> death check.
    Type-based vulnerability checks stay in _character_take_damage: toxin ticks
    carry no damage_type, so vulnerabilities deliberately don't fire on ticks.
    """
    lines = []
    # Derived pre-reads from active wounds (spec section 5): Synthskin doubles
    # incoming damage; Death's Door makes any further damage lethal.
    pre = _wnd.derived_effects(char.get('wounds', []))
    if pre["double_damage"] and damage > 0:
        damage *= 2
        lines.append(f"**Damage DOUBLED to {damage} - Synthskin Damaged**")
    if pre["deaths_door"] and damage > 0:
        # Lethality must be self-representing in state, not just narrated:
        # snap HP to -20 so _check_death_conditions (and every later reader)
        # reports the death from the sheet itself.
        hp_box = char.setdefault('hp', {})
        old_hp = hp_box.get('current', 0)
        floor = _elixir_hp_floor(char)
        if floor is not None:
            # B3 R-B3d: Deathless beats Death's Door -- HP cannot fall below
            # the floor, so the lethal snap never reaches -20.
            hp_box['current'] = max(old_hp - damage, floor)
            lines.append(f"**DEATHLESS:** the killing blow is denied -- HP held "
                         f"at {hp_box['current']} (Immortality Injector).")
            return lines, False
        hp_box['current'] = min(old_hp - damage, -20)
        allowed, gate_lines = _death_gate(key, char, data, window_key)
        lines.extend(gate_lines)
        if not allowed:
            return lines, False
        lines.append(f"at DEATH'S DOOR - **any further damage is LETHAL. "
                     f"{char.get('name', key)} IS DEAD.**")
        lines.extend(_death_seam_lines(char, data, key))
        lines.append("Pause and discuss with player.")
        return lines, True

    old_hp = char.get('hp', {}).get('current', 0)
    new_hp = old_hp - damage
    # B3 R-B3d: the Immortality Injector floors HP -- damage cannot reduce a
    # Deathless PC below -19 (so HP <= -20 death is unreachable while active).
    floor = _elixir_hp_floor(char)
    if floor is not None and new_hp < floor:
        new_hp = floor
        lines.append(f"**DEATHLESS:** damage clamped at {floor} HP "
                     f"(Immortality Injector).")
    char.setdefault('hp', {})['current'] = new_hp

    # Unified wound trigger (spec section 4, replacing the two buggy branches):
    # every damage landing at HP <= 0 applies the wound at that HP -- landing
    # exactly at 0, dropping from above, or taking more damage while already
    # down all use the same rule. Clamped at the -20 row (death).
    if damage > 0 and new_hp <= 0:
        wound_table = BIOLOGICAL_WOUNDS if char.get('wound_table', 'biological') == 'biological' else SYNTHETIC_WOUNDS
        lines.extend(_apply_wound(key, char, data, max(new_hp, -20), wound_table))

    is_dead, reason, gate_lines = _check_death_gated(key, char, data, window_key)
    lines.extend(gate_lines)
    if is_dead:
        lines.append("")
        lines.append(f"**!!! {reason} !!!**")
        lines.extend(_death_seam_lines(char, data, key))
        lines.append("Pause and discuss with player.")
    return lines, False
