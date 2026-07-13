#!/usr/bin/env python3
"""UserPromptSubmit hook: Inject banned-phrase reminder before Claude writes.

Reads blacklist.json and session catch_log from hook state.
Outputs a concise system reminder of what NOT to write.

Session-adaptive (Option B):
- Always shows top blacklisted patterns (condensed)
- Highlights session repeat offenders from catch_log
- Scales urgency with catch count

SECURITY: Uses fail_closed_wrapper (fail = block, not silent pass).
But since this is UserPromptSubmit, failure just means no reminder injected.
We override to fail-open: if anything breaks, print nothing and exit 0.
"""

# PEP 563: defer annotation evaluation so PEP 604 unions (str | None) parse on
# Python 3.9 — these hooks run under the system python3, which is 3.9 on a stock macOS.
from __future__ import annotations

import os
import re
import sys
import json
from datetime import datetime
from pathlib import Path
from collections import Counter

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
import item_slots as _isl
import wounds as _wnd
import reflex_budget as _rb
import survival as _sv
import site_markers as _sm
import push_format as _pf

from hooks.hook_utils import read_hook_input, load_state, save_state, file_lock, in_maintenance
from hooks.analytics_utils import get_scene_weights, get_recent_semantic_catches

BLACKLIST_FILE = Path(__file__).parent / "blacklist.json"
SCENE_WEIGHTS_FILE = Path(__file__).parent / "scene_type_weights.json"
from rubicon_paths import campaign_dir as _campaign_dir
CAMPAIGN_DIR = _campaign_dir()

# ---------------------------------------------------------------------------
# DUNGEON header pattern — matches <!-- DUNGEON: map=<name> enforce=vault-liveness -->
# ---------------------------------------------------------------------------
_DUNGEON_HEADER_RE = re.compile(
    r'<!--\s*DUNGEON:\s*map=(\S+)\s+enforce=vault-liveness\s*-->'
)


def _read_active_prep_files() -> list[str]:
    """Parse **Active Prep:** line from CURRENT_STATUS.md.

    Returns a list of .md filenames (bare names, no paths). Handles comma/semicolon
    separated lists and entries with parenthetical notes like:
      PLANEYFOLK_CONTACT_PREP.md (forward base); CERULINE_ARCOLOGY_PREP.md
    """
    status_path = CAMPAIGN_DIR / "CURRENT_STATUS.md"
    try:
        text = status_path.read_text(encoding="utf-8")
    except Exception:
        return []

    for line in text.splitlines():
        if "**Active Prep:**" in line:
            value = line.split("**Active Prep:**", 1)[1].strip()
            if not value or value.lower() in ("none", ""):
                return []
            # Split on common separators (semicolons, commas, slashes)
            parts = re.split(r'[;,/]', value)
            filenames = []
            for part in parts:
                # Strip parenthetical notes
                part = re.sub(r'\([^)]*\)', '', part).strip()
                # Find .md filename
                m = re.search(r'(\S+\.md)', part, re.IGNORECASE)
                if m:
                    filenames.append(m.group(1))
            return filenames
    return []


def _scan_dungeon_header(prep_filename: str) -> str | None:
    """Read the first 10 lines of a prep file looking for the DUNGEON header.

    Returns the map name (e.g. 'kept_sill') if found, else None.
    """
    prep_path = CAMPAIGN_DIR / prep_filename
    try:
        with open(prep_path, encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= 10:
                    break
                m = _DUNGEON_HEADER_RE.search(line)
                if m:
                    return m.group(1)
    except Exception:
        pass
    return None


def _get_map_current_turn(map_name: str) -> int | None:
    """Read current_turn from maps/<map_name>_map.json. Returns None if not found."""
    map_path = CAMPAIGN_DIR / "maps" / f"{map_name}_map.json"
    try:
        data = json.loads(map_path.read_text(encoding="utf-8"))
        return data.get("current_turn")
    except Exception:
        return None


def _update_vault_enforce(state: dict) -> tuple[dict, str | None]:
    """Arm or disarm the vault-enforce gate based on Active Prep.

    Returns (updated_state, constraint_reminder_text | None).
    The constraint_reminder_text is non-None only when armed.
    NEVER reads or writes scene_type.
    """
    prep_files = _read_active_prep_files()

    armed_map = None
    for prep_filename in prep_files:
        map_name = _scan_dungeon_header(prep_filename)
        if map_name:
            armed_map = map_name
            break  # first DUNGEON-headered prep wins

    current_enforce = state.get("vault_enforce", {})

    # Only arm against a map whose JSON actually exists. A DUNGEON header that
    # points at an unbuilt map must NOT arm — otherwise the liveness gate would
    # demand map actions on a nonexistent map and could soft-lock a session.
    current_turn = _get_map_current_turn(armed_map) if armed_map else None

    if armed_map and current_turn is not None:

        # Only update last_turn on initial arm; preserve it across turns
        # so the liveness check can detect advancement.
        already_armed = current_enforce.get("armed") and current_enforce.get("map") == armed_map
        if already_armed:
            # Already armed for this map — preserve last_turn (liveness check owns updates)
            new_enforce = current_enforce
        else:
            # Freshly arming — seed last_turn at current turn (one-turn grace)
            new_enforce = {
                "armed": True,
                "map": armed_map,
                "last_turn": current_turn,
            }

        state["vault_enforce"] = new_enforce

        # Build constraint reminder text
        reminder = (
            f"VAULT ARMED ({armed_map}): dungeon mechanics are LIVE every turn. "
            f"Map turn: {current_turn}. "
            f"Each narrative turn MUST advance current_turn — "
            f"map(enter/search) to move, OR map(action=\"wait\", map_name=\"{armed_map}\") to hold "
            f"(ticks time, rolls encounter die). A parley is fine; a frozen dungeon is not."
        )
        return state, reminder
    else:
        # Disarm — clear vault_enforce
        if current_enforce.get("armed"):
            state["vault_enforce"] = {"armed": False}
        return state, None


def load_blacklist() -> tuple[list[str], list[str]]:
    """Load phrases from blacklist.json. Returns (blacklisted, use_sparingly)."""
    try:
        data = json.loads(BLACKLIST_FILE.read_text(encoding="utf-8"))
        return data.get("blacklisted_phrases", []), data.get("use_sparingly", [])
    except (FileNotFoundError, json.JSONDecodeError, IOError):
        return [], []


def simplify_pattern(pattern: str) -> str:
    """Convert regex pattern to readable phrase for the reminder."""
    # Strip common regex artifacts for readability
    s = pattern
    s = s.replace("\\b", "").replace("\\s+", " ").replace("\\w+", "...")
    s = s.replace("(s|ed)", "s/ed").replace("(s|ing)", "s/ing")
    s = s.replace("?", "").replace("(ly)", "ly")
    s = s.replace("(her|his|their)", "her/his/their")
    s = s.replace("(voice|eyes|face|expression)", "voice/eyes/face")
    s = s.replace("(hangs?|hung|fell|falls?)", "hangs/fell")
    s = s.replace("(stretches|follows|settles)", "stretches/follows")
    s = s.replace("(finds?|found)", "finds/found")
    s = s.replace("(drops|dropped)", "drops/dropped")
    # If still too regex-heavy, just return as-is
    return s


_EXPLORATION_SCENE_TYPES = {"vault_exploration"}   # mirrors server._is_exploration_scene (hook can't import server)


def _read_scene_type() -> str:
    """Read current scene type from CURRENT_STATUS.md."""
    try:
        status_path = CAMPAIGN_DIR / "CURRENT_STATUS.md"
        content = status_path.read_text(encoding="utf-8")
        match = re.search(r'\*\*Scene Type:\*\*\s*(\S+)', content)
        return match.group(1).strip() if match else "unknown"
    except Exception:
        return "unknown"


def _read_active_map() -> str:
    """Read the current **Active Map:** pointer from CURRENT_STATUS.md.
    Returns '' when unset/None/missing (mirrors _read_scene_type)."""
    try:
        status_path = CAMPAIGN_DIR / "CURRENT_STATUS.md"
        content = status_path.read_text(encoding="utf-8")
        match = re.search(r'\*\*Active Map:\*\*\s*(.+?)(?:\n|$)', content)
        if not match:
            return ""
        val = match.group(1).strip()
        return "" if val.lower() == "none" else val
    except Exception:
        return ""


def _load_default_weights() -> dict:
    """Load hardcoded default scene-type weights from JSON."""
    try:
        data = json.loads(SCENE_WEIGHTS_FILE.read_text(encoding="utf-8"))
        return data
    except Exception:
        return {}


def _build_scene_line(scene_type: str) -> str:
    """Build the scene-aware warning line using analytics + defaults.

    Prefers analytics data (real catches). Falls back to hardcoded defaults
    from scene_type_weights.json if no analytics exist for this scene type.
    """
    # Try analytics first
    analytics_weights = get_scene_weights(scene_type)

    if analytics_weights:
        # Use real data: top 5 phrases most caught in this scene type
        top = list(analytics_weights.items())[:5]
        parts = [f"{phrase} ({count} catches)" for phrase, count in top]
        return f"SCENE: {scene_type} — watch for: {', '.join(parts)}"

    # Fall back to hardcoded defaults
    defaults = _load_default_weights()
    scene_data = defaults.get(scene_type, {})
    if scene_data:
        patterns = scene_data.get("patterns", [])
        desc = scene_data.get("description", "")
        if patterns:
            pattern_str = ", ".join(patterns)
            return f"SCENE: {scene_type} — watch for: {pattern_str} ({desc})"

    # No data at all — generic
    return f"SCENE: {scene_type} — no scene-specific data yet"


def build_reminder(catch_count: int, catch_log: dict,
                   blacklisted: list[str], sparingly: list[str],
                   session_vocab: list[str], scene_type: str = "unknown",
                   canon_required: bool = False) -> str:
    """Build the reminder string based on session state.

    Three tiers:
    - 0 catches: one-line reminder with scene-type top patterns
    - 1-5 catches: session offenders + scene line (no full banned list)
    - 6+ catches: full output (you need the reinforcement)
    """
    # Lorebook nudge — appended to all tiers
    lorebook_nudge = "LOREBOOK: Before writing biology, history, species traits, or world facts — call lorebook(view, keyword) first. Tool Before Tale."

    # Canon-required priming — prepended when this is a required-canon turn
    canon_warning = ""
    if canon_required:
        canon_warning = "**CANON REQUIRED THIS TURN** — call check_canon(user_input) BEFORE writing narrative. "

    # === TIER 1: Clean session — minimal reminder ===
    if catch_count == 0:
        if scene_type != "unknown":
            # Compact scene hint: just top 3 pattern names, no counts
            weights = get_scene_weights(scene_type)
            if weights:
                top_3 = list(weights.keys())[:3]
                return f"{canon_warning}PHRASE DISCIPLINE: Clean session. {scene_type} — watch: {', '.join(top_3)} | {lorebook_nudge}"
        return f"{canon_warning}PHRASE DISCIPLINE: Clean session. Stay sharp. | {lorebook_nudge}"

    lines = []

    # === TIER 2: Low catches — offenders + scene, no full banned list ===
    if catch_count <= 5:
        lines.append(f"PHRASE DISCIPLINE REMINDER ({catch_count} catches this session):")

        if catch_log:
            top = sorted(catch_log.items(), key=lambda x: x[1], reverse=True)[:8]
            offenders = ", ".join(f'"{k}" (x{v})' for k, v in top)
            lines.append(f"SESSION OFFENDERS: {offenders}")
            lines.append("These phrases have ALREADY been caught. Do NOT use them again.")

        if session_vocab:
            used = ", ".join(f'"{v}"' for v in session_vocab[:10])
            lines.append(f"USED THIS SESSION (one-per-session limit reached): {used}")

        if scene_type != "unknown":
            lines.append(_build_scene_line(scene_type))

        lines.append("RULE: Affirmative statement first. State what it IS, never what it isn't.")
        lines.append(lorebook_nudge)
        return " ".join(lines)

    # === TIER 3: High catches — full reinforcement ===
    if catch_count <= 10:
        lines.append(f"PHRASE DISCIPLINE WARNING ({catch_count} catches — tighten up):")
    else:
        lines.append(f"PHRASE DISCIPLINE ALERT ({catch_count} catches — this is bad):")

    if catch_log:
        top = sorted(catch_log.items(), key=lambda x: x[1], reverse=True)[:8]
        offenders = ", ".join(f'"{k}" (x{v})' for k, v in top)
        lines.append(f"SESSION OFFENDERS: {offenders}")
        lines.append("These phrases have ALREADY been caught. Do NOT use them again.")

    if session_vocab:
        used = ", ".join(f'"{v}"' for v in session_vocab[:10])
        lines.append(f"USED THIS SESSION (one-per-session limit reached): {used}")

    if scene_type != "unknown":
        lines.append(_build_scene_line(scene_type))

    lines.append("BANNED PATTERNS: no 'the X of a Y who/that'; no 'not X — Y' negation-correction; no freeze/lock/petrification for reactions; no silence-as-actor; no vocal-adjective delivery tags; no 'something in her voice/eyes'; no 'settles over/into/between'; no 'the weight of'; no breathing-as-shock ('breath catches/hitches', 'exhales', 'breathes out').")
    lines.append("RULE: Affirmative statement first. State what it IS, never what it isn't. If a sentence starts with 'not', rewrite it.")
    # Scene-type replacement suggestions
    replacements = {
        "social": "REACH FOR INSTEAD: specific physical action (hands, posture, object interaction) | environmental detail (what the room sounds/smells like) | behavioral displacement (what they do while speaking, what they look at) | dialogue that carries its own register",
        "intimate": "REACH FOR INSTEAD: specific sensation (texture, temperature, pressure) | what the body does next (movement, grip, release) | bond texture (emotional undertow, not labels) | one precise detail over three vague ones",
        "combat": "REACH FOR INSTEAD: perception fragments (a birthmark, impact mass, scrape of metal) | what the body registers before the mind names it | chaos first, clarity only in pauses between exchanges",
    }
    if scene_type in replacements:
        lines.append(replacements[scene_type])
    lines.append(lorebook_nudge)

    return " ".join(lines)


# ===================================================================
# Load & depletables reminder (U2 Task 6)
# ===================================================================


def _build_load_block(campaign_dir) -> str:
    """Per-turn push: per-PC slot load (+ Encumbered) and every depletable on hand,
    each with the exact usage('use') call. Empty string if nobody carries a depletable."""
    cdir = Path(campaign_dir) / "characters"
    if not cdir.is_dir():
        return ""
    loads, deplete_lines = [], []
    for f in sorted(cdir.glob("*.json")):
        try:
            char = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(char, dict) or "inventory" not in char:
            continue
        name = char.get("name", f.stem)
        carried = char.get("inventory", {}).get("carried", [])
        cap = char.get("slot_capacity_total", 10)
        gifts = len(char.get("mystic_gifts", []))
        codices = len(char.get("codices", []))
        wounds = char.get("wounds_slots_used", 0)
        used = sum(it.get("slots", 0) for it in carried) + gifts + codices + wounds
        depletables = [it for it in carried if _isl.item_is_depletable(it)]
        enc = _isl.is_encumbered(used, cap)
        if not depletables and not enc:
            continue
        tag = " ENCUMBERED(STR/DEX/CON@DIS)" if enc else ""
        loads.append(f"{name} {used}/{cap}{tag}")
        for it in depletables:
            label = _isl.depletable_label(it)
            iname = it.get("name", "?")
            deplete_lines.append(f'  {name} · {label} → usage(action="use", character="{name}", item="{iname}")')
    if not loads:
        return ""
    out = ["LOAD: " + " · ".join(loads)]
    if deplete_lines:
        out.append("DEPLETABLES — when the player uses one, call its line:")
        out.extend(deplete_lines)
    return "\n".join(out)


# ===================================================================
# Wounds reminder (Wounds Task 8) — budgeted per-turn push
# ===================================================================


def _wound_parens(rec) -> str:
    """Compact parens for ONE wound record's DERIVED effects only.

    Rolled-once mutations (ability/max-HP/level damage) are already on the
    sheet's stats and are NEVER restated — a pure-mutation wound gets ''.
    """
    # NOTE: keep the rendered keys in sync with wounds.derived_effects — a new
    # derived effect added there must gain a line here or it silently drops
    # from the per-turn push (the only place derived effects live).
    eff = _wnd.derived_effects([rec])
    bits = []
    if eff["dis_saves"]:
        bits.append("DIS " + "/".join(eff["dis_saves"]))
    if eff["deprived"]:
        bits.append("DEPRIVED no-HP-regain")
    if eff["av_penalty"]:
        bits.append(f"-{eff['av_penalty']} AV")
    if eff["av_bonus"]:
        bits.append(f"+{eff['av_bonus']} AV (Gitch)")
    if eff["double_damage"]:
        bits.append("dbl dmg")
    if eff["blind"]:
        bits.append("BLIND")
    if rec.get("until_fixed_penalty"):
        bits.append("/".join(f"-{v} {k}" for k, v in
                             rec["until_fixed_penalty"].items()) + " until fixed")
    tick = eff["daily_tick"]
    if tick:
        if len(set(tick.values())) == 1:
            bits.append(f"-{next(iter(tick.values()))} {'/'.join(tick)} per day")
        else:
            bits.append("/".join(f"-{v} {k}" for k, v in tick.items()) + " per day")
    if rec.get("duration") and not rec.get("unconscious"):
        bits.append(rec["duration"])
    return f"({', '.join(bits)})" if bits else ""


def _render_wound(rec, pc_name: str) -> str:
    """One wound, budget-rendered: name + derived parens; a pending KO save
    carries its report call inline (owed — the DM must close the loop)."""
    wname = rec.get("name", "?")
    if rec.get("pending_con_save"):
        return (f'{wname}: CON save owed -> affliction(kind="wound", action="ko_save", '
                f'character="{pc_name}", result="pass"|"fail")')
    return wname + _wound_parens(rec)


def _build_wounds_block(campaign_dir) -> str:
    """Per-turn WOUNDS push under the concision budget (spec §7, Joe's constraint):
    silent when no PC has wounds; one line per wounded PC; derived/owed content
    only; high-stakes flags (UNCONSCIOUS / DEATH'S DOOR / MUST DROP N / pending
    KO save) always shown while active. Broken items are use-time only — never here."""
    cdir = Path(campaign_dir) / "characters"
    if not cdir.is_dir():
        return ""
    lines = []
    for f in sorted(cdir.glob("*.json")):
        try:
            char = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(char, dict):
            continue
        records = [r for r in char.get("wounds") or [] if isinstance(r, dict)]
        if not records:
            continue
        name = char.get("name", f.stem)
        parts = [_render_wound(r, name) for r in records]
        eff = _wnd.derived_effects(records)
        flags = []
        if eff["unconscious"]:
            # Duration lives in 'duration' (table shutdowns) OR
            # 'unconscious_rounds' (a failed KO save) — read both.
            dur = next((r["duration"] for r in records
                        if r.get("unconscious") and r.get("duration")), None)
            if dur is None:
                rounds = next((r["unconscious_rounds"] for r in records
                               if r.get("unconscious") and r.get("unconscious_rounds")),
                              None)
                dur = f"{rounds} rounds" if rounds else None
            flags.append(f"UNCONSCIOUS(attacks auto-hit, {dur})" if dur
                         else "UNCONSCIOUS(attacks auto-hit)")
        if eff["deaths_door"]:
            flags.append("DEATH'S DOOR(next damage kills)")
        # Forced drop: same fields _build_load_block reads — gear load vs the
        # room wounds leave (Joe ruling: wounds evict gear).
        carried = (char.get("inventory") or {}).get("carried") or []
        gear_load = (sum(it.get("slots", 0) for it in carried if isinstance(it, dict))
                     + len(char.get("mystic_gifts") or [])
                     + len(char.get("codices") or []))
        cap = char.get("slot_capacity_total", 10)
        wound_slots = char.get("wounds_slots_used",
                               sum(r.get("slots", 0) for r in records))
        # Zero-slot wounds (KO, Damaged Item) evict nothing: voluntary
        # over-cap gear is U2-legal Encumbrance (LOAD's business, not ours).
        drop = _wnd.forced_drop_slots(gear_load, cap, wound_slots) if wound_slots > 0 else 0
        if drop:
            flags.append(f"MUST DROP {drop}")
        line = f"{name} - " + ", ".join(parts)
        if flags:
            line += " · " + " · ".join(flags)
        lines.append(line)
    if not lines:
        return ""
    return "WOUNDS: " + lines[0] + "".join("\n  " + l for l in lines[1:])


# ===================================================================
# Supply reminder (S1 Task 8) — budgeted per-turn push
# ===================================================================


def _build_supply_block(campaign_dir) -> list:
    """Per-turn SUPPLY push under the concision budget.

    Returns a list of reflex_budget.Entry objects (one AMBIENT pool line +
    one URGENT line per Deprived PC), or [] when in abundant mode.

    Design: silent when mode != 'field' (the party is at an earned base — no
    tracking there). In the field: always emit the pool state as AMBIENT;
    each Deprived PC adds an URGENT line with the death clock. Fail-silent
    is the CALLER's responsibility (_build_reflex_block wraps in try/except).

    Days-at-burn arithmetic mirrors server._supply_status_lines:
      burn = sum of per-PC daily_needs + follower_mouths (each = 1F + 1W);
      days = min over needs-with-burn>0 of floor(pool / burn).
    """
    cdir = Path(campaign_dir) / "characters"
    if not cdir.is_dir():
        return []
    # Read _meta.json for supply record
    meta_path = cdir / "_meta.json"
    if not meta_path.exists():
        return []
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    supply = meta.get("supply") or {}
    if supply.get("mode") != "field":
        return []

    # Read all sheets: characters/ AND vehicles/ — the server's
    # _load_characters() MERGES vehicles/*.json into the dict, so the reflex
    # line must read the same data set or the burn math could silently
    # diverge from supply(action="status") (today vehicles are mechanical ->
    # zero needs; parity matters the day a vehicle gains a survival field).
    burn = {"water": 0, "food": 0}
    deprived_entries = []
    sheet_files = sorted(cdir.glob("*.json"))
    vdir = Path(campaign_dir) / "vehicles"
    if vdir.is_dir():
        sheet_files += sorted(vdir.glob("*.json"))
    for f in sheet_files:
        if f.name == "_meta.json":
            continue
        try:
            char = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(char, dict):
            continue
        # Accumulate burn from all sheets (vehicles, followers, etc. still count
        # if their wound_table says so — daily_needs handles exemptions)
        needs = _sv.daily_needs(char)
        burn["water"] += needs["water"]
        burn["food"] += needs["food"]
        # Deprived conditions -> urgent clock lines
        name = char.get("name", f.stem)
        eff = _sv.condition_effects(char.get("conditions") or [])
        for cause, death_day in eff["dying"]:
            # Garbage-tolerant: a record missing death_day still renders —
            # the condition is real even when the clock field is absent
            day_str = "unknown" if death_day is None else str(death_day)
            deprived_entries.append(
                _rb.Entry(_rb.URGENT,
                          f'DEPRIVED: {name} {cause} — no healing, dies Day {day_str}'
                          f' → supply(action="status")'))

    # Follower mouths: each counts as 1 food + 1 water per day
    follower_mouths = supply.get("follower_mouths") or 0
    burn["water"] += follower_mouths
    burn["food"] += follower_mouths

    # Build the ambient pool line
    pool = supply.get("pool")
    if isinstance(pool, dict):
        food_pool = pool.get("food", 0)
        water_pool = pool.get("water", 0)
        # Days-at-burn: min over needs that have burn > 0; if nobody burns a
        # need (all synthetics), that need contributes 999 to the min
        days = min(
            (food_pool // burn["food"]) if burn["food"] > 0 else 999,
            (water_pool // burn["water"]) if burn["water"] > 0 else 999,
        )
        pool_line = f"SUPPLY: {food_pool}F/{water_pool}W pool ≈ {days}d"
    else:
        pool_line = "SUPPLY: carried-only"
    ambient = _rb.Entry(_rb.AMBIENT, pool_line)

    return [ambient] + deprived_entries


def _build_conditions_block(campaign_dir) -> list:
    """E1: per-turn CONDITIONS push (reflex_budget entries).

    Deprived thirst/starvation stays with _build_supply_block (field-mode
    economics); everything ELSE renders here - including photosynthesis
    Deprived, which exists even in abundant mode. SILENT when no PC has
    conditions; AMBIENT otherwise; URGENT when a death clock, a round-cadence
    tick, or a Twinning death-pending mark is live. Fail-silent is the
    caller's job."""
    entries = []
    cdir = Path(campaign_dir) / "characters"
    if not cdir.is_dir():
        return []
    current_day = None
    _meta_p = cdir / "_meta.json"
    if _meta_p.exists():
        try:
            current_day = json.loads(
                _meta_p.read_text(encoding="utf-8")).get("campaign_day")
        except Exception:
            current_day = None
    for f in sorted(cdir.glob("*.json")):
        if f.name == "_meta.json":
            continue
        try:
            char = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(char, dict):
            continue
        name = char.get("name", f.stem)
        parts, urgent = [], False
        for c in (char.get("conditions") or []):
            if not isinstance(c, dict):
                continue
            if c.get("name") == "Deprived" and c.get("cause") in (
                    "thirst", "starvation"):
                continue  # supply block owns the field-mode economics
            label = str(c.get("name", "?"))
            if c.get("cause"):
                label += f" ({c['cause']})"
            dd = c.get("death_day")
            if isinstance(dd, int):
                label += f" - dies Day {dd}"
                urgent = True
            tick = c.get("tick") or {}
            if tick.get("cadence") == "round":
                label += f" - {tick.get('hp', '?')}/round"
                urgent = True
            elif tick.get("cadence") in ("day", "week") and (
                    tick.get("hp") or tick.get("max_hp") or tick.get("abilities")):
                # A disease silently grinding HP/abilities each day must NOT be
                # AMBIENT-droppable (it can erode a PC to death between the one
                # advance_day emission and a death_day finally appearing).
                _bits = []
                if tick.get("hp"):
                    _bits.append(f"{tick['hp']} HP")
                if tick.get("max_hp"):
                    _bits.append(f"{tick['max_hp']} max-HP")
                if tick.get("abilities"):
                    _bits.append("ability")
                label += f" - drains {'/'.join(_bits)} per {tick['cadence']}"
                urgent = True
            if c.get("name") == "Spirit":
                spm = char.get("spirit") or {}
                if isinstance(spm.get("faded_until"), int):
                    label += f" - FADED (sunrise Day {spm['faded_until']})"
                    urgent = True
                elif isinstance(spm.get("essence"), int):
                    label += (f" - essence {spm['essence']}"
                              f"/{spm.get('max_essence', spm['essence'])}")
            parts.append(label)
        if isinstance(char.get("twinning_pending"), dict):
            parts.append("DEATH PENDING (twin window "
                         f"{char['twinning_pending'].get('window')})")
            urgent = True
        if parts:
            entries.append(_rb.Entry(
                _rb.URGENT if urgent else _rb.AMBIENT,
                f'CONDITIONS: {name} - ' + "; ".join(parts)
                + ' → affliction(kind="condition", action="status")'))
        # Resurrection timer coming/overdue — NO per-turn surface existed before;
        # a corpse's due resurrection was announced once (advance_day) then never
        # re-raised. Mirror the advance_day tick: URGENT once due_day is reached.
        rec = char.get("resurrection")
        if isinstance(rec, dict) and not rec.get("resolved"):
            due = rec.get("due_day")
            if (isinstance(due, int) and isinstance(current_day, int)
                    and current_day >= due):
                path = rec.get("path", "?")
                call = _pf.push_call("character", action="resurrect_resolve",
                                     name=f.stem, path=path)
                entries.append(_rb.Entry(
                    _rb.URGENT,
                    f"RESURRECTION: {name}'s {path} resurrection is DUE "
                    f"(Day {due}) - " + _pf.next_block(call, label="resolve")))
    return entries


# ===================================================================
# Reflex Layer: unified per-turn block (Component 3)
# ===================================================================


REFLEX_ERROR_LOG = Path(__file__).parent / "observer_errors.log"


def _log_reflex_failure(exc) -> None:
    """Fail-silent must still leave a trace (spec rule): append the exception
    to the shared observer error log. The logger itself never raises."""
    try:
        with REFLEX_ERROR_LOG.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat()} reflex_block: {exc!r}\n")
    except Exception:
        pass


def _reflex_snapshot(campaign_dir) -> dict:
    """Current per-PC live-state fingerprint for Δ detection.

    Keys ('kind:label' — the label half carries the metric name so Δ lines
    for the same PC stay textually distinct):
      'wounds:<PC> wounds' -> str count of wound records
      'load:<PC> load'     -> 'used/cap' string (same arithmetic as _build_load_block)
      'die:<PC>|<item>'    -> usage-die string (item_usage_die) or 'xN' (item_int_uses)
      'deprived:<PC>:<cause>' -> '<death_day>' (per-cause; 'unknown' if absent)
      'supply:pool'        -> '{food}F/{water}W' (field mode with a pool only)

    Sources from the SAME helpers _build_load_block and _build_wounds_block use,
    so snapshot and rendered blocks can never disagree.
    """
    snap = {}
    cdir = Path(campaign_dir) / "characters"
    if not cdir.is_dir():
        return snap
    for f in sorted(cdir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        # Skip non-PC files — same gate as _build_load_block
        if not isinstance(data, dict) or "inventory" not in data:
            continue
        name = data.get("name", f.stem)

        # Wound count — same filter as _build_wounds_block
        records = [r for r in data.get("wounds") or [] if isinstance(r, dict)]
        if records:
            snap[f"wounds:{name} wounds"] = str(len(records))

        # Load — same arithmetic as _build_load_block
        carried = data.get("inventory", {}).get("carried", [])
        if not isinstance(carried, list):
            carried = []
        cap = data.get("slot_capacity_total", 10)
        gifts = len(data.get("mystic_gifts", []) or [])
        codices = len(data.get("codices", []) or [])
        wound_slots = data.get("wounds_slots_used", 0)
        used = (sum(it.get("slots", 0) for it in carried if isinstance(it, dict))
                + gifts + codices + wound_slots)
        snap[f"load:{name} load"] = f"{used}/{cap}"

        # Depletion state — same helpers as _build_load_block (item_slots)
        for it in carried:
            if not isinstance(it, dict):
                continue
            iname = it.get("name", "?")
            die = _isl.item_usage_die(it)
            if die:
                snap[f"die:{name}|{iname}"] = die
            else:
                u = _isl.item_int_uses(it)
                if u is not None:
                    snap[f"die:{name}|{iname}"] = f"x{u}"

        # Deprived conditions — 'deprived:{name}:{cause}' -> '{death_day}'
        # (per-cause keys: a PC Deprived by thirst AND starvation gets two
        # snapshot entries instead of one record clobbering the other)
        for c in (data.get("conditions") or []):
            if isinstance(c, dict) and c.get("name") == "Deprived":
                cause = c.get("cause", "?")
                dd = c.get("death_day")
                snap[f"deprived:{name}:{cause}"] = (
                    "unknown" if dd is None else str(dd))

        # E1 conditions - 'cond:{name}:{condition}' -> compact state string,
        # so applying/clearing/clock-advancing a condition renders a delta line
        for c in (data.get("conditions") or []):
            if isinstance(c, dict) and c.get("name") and c.get("name") != "Deprived":
                val = str(c.get("death_day", "on"))
                # A drain tick (HP/max-HP/ability) erodes the PC each day with no
                # death_day to move; fold the eroding values into the fingerprint
                # so day-over-day grind renders a Δ line instead of a flat 'on'.
                tick = c.get("tick") or {}
                if tick.get("cadence") in ("day", "week"):
                    if tick.get("hp") or tick.get("max_hp"):
                        hp = data.get("hp") or {}
                        val += f"|hp{hp.get('current')}/{hp.get('max')}"
                    if tick.get("abilities"):
                        ab = data.get("abilities") or {}
                        for _st in tick["abilities"]:
                            _cur = ab.get(_st, {})
                            _cur = _cur.get("current") if isinstance(_cur, dict) else _cur
                            val += f"|{_st}{_cur}"
                snap[f"cond:{name}:{c['name']}"] = val

    # Supply pool state — only when field mode and pool exists
    # (metric-labeled: 'supply:pool' is a unique kind prefix)
    meta_path = cdir / "_meta.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            supply = meta.get("supply") or {}
            if supply.get("mode") == "field":
                pool = supply.get("pool")
                if isinstance(pool, dict):
                    snap["supply:pool"] = f"{pool.get('food', 0)}F/{pool.get('water', 0)}W"
        except Exception:
            pass

    return snap


def _build_reflex_block(campaign_dir, state: dict, user_text: str = "") -> str:
    """Build the unified per-turn reflex block (Reflex Layer Component 3).

    Wraps _build_wounds_block and _build_load_block through reflex_budget's
    tiered composer. Builders' output is fed PER LINE so the cap trims the
    quiet tail instead of annihilating a whole oversized block (the real
    campaign's LOAD block alone exceeds the default cap).
    Writes the current snapshot back into state['reflex_snapshot'].
    Fail-silent: returns '' on ANY exception (logged) so a broken reflex
    never blocks a turn.
    """
    try:
        entries = []

        wounds = _build_wounds_block(campaign_dir)
        if wounds:
            for line in wounds.split("\n"):
                urgent = any(m in line for m in
                             ("UNCONSCIOUS(", "DEATH'S DOOR(", "MUST DROP ", "save owed"))
                entries.append(_rb.Entry(_rb.URGENT if urgent else _rb.AMBIENT, line))

        load = _build_load_block(campaign_dir)
        if load:
            llines = load.split("\n")
            entries.append(_rb.Entry(
                _rb.URGENT if "ENCUMBERED(" in llines[0] else _rb.AMBIENT, llines[0]))
            for line in llines[1:]:
                entries.append(_rb.Entry(_rb.AMBIENT, line))

        entries.extend(_build_supply_block(campaign_dir))
        entries.extend(_build_conditions_block(campaign_dir))

        # Open NPC scene nag (door gate, Task 3): one line while an NPC scene
        # is open and its continuity is unrecorded.
        open_npc = state.get("open_npc_scene", {})
        if open_npc:
            names = ", ".join(f"{v.get('name', s)} (name='{s}')" for s, v in open_npc.items())
            entries.append(_rb.Entry(
                _rb.URGENT,
                f"⊙ OPEN NPC (continuity unrecorded): {names} — capture before you leave the scene."))

        # Exploration scene, no active site nag (site-exploration gear-shift):
        # when the scene is an exploration mode but no site/map is active, the
        # turn clock isn't running — push enter_site. Conservative: fires only
        # on a clearly-exploration scene value. Reads scene type + active map
        # from CURRENT_STATUS the same way the rest of the hook does.
        try:
            scene_type = _read_scene_type()
            scene_token = scene_type.strip().lower().split()[0] if scene_type.strip() else ""
            if scene_token in _EXPLORATION_SCENE_TYPES and not _read_active_map():
                preps = _read_active_prep_files()
                prep_hint = preps[0] if preps else "<PREP>.md"
                entries.append(_rb.Entry(
                    _rb.URGENT,
                    f'⊙ EXPLORATION SCENE, no active site — call '
                    f'map(action="enter_site", prep_file="{prep_hint}") to start the turn clock.'))
        except Exception:
            pass  # nag is advisory; never break the reflex block over it

        # Site-entry detector: the player named a known site. Scan the submitted
        # prompt against the site index and push the exact enter_site call with
        # resume context. Advisory, NEVER a gate. A freshly-named site is pinned in
        # open_site_scene with a short TTL so a passing mention fades after a couple
        # of turns (a real re-mention refreshes it); entering the site (Active Map ==
        # key) clears it immediately. Active Map is compared case-insensitively
        # because the DM may type a non-lowercase map_name.
        try:
            state.setdefault("open_site_scene", {})
            active = _read_active_map().strip().lower()
            named_now = set()
            idx = {}  # must be bound even on falsy user_text: the TTL re-render
                      # fallback below reads idx.get(key) for lingering settlements
            if user_text:
                idx = _sm.build_site_index(campaign_dir)
                named_now = set(_sm.detect_named_sites(user_text, idx))
                for key in named_now:
                    if key == active:
                        continue
                    rec = idx.get(key, {})
                    state["open_site_scene"][key] = {
                        "prep_file": rec.get("prep_file"),
                        "current_turn": rec.get("current_turn"),
                        "last_seen_day": rec.get("last_seen_day"),
                        "scene": rec.get("scene", "vault_exploration"),
                        "ttl": 1,  # this turn + 1 more, then fades unless re-named
                    }
            # Resolved: the DM entered the site (Active Map == key, case-insensitive).
            for key in [k for k in state["open_site_scene"] if k == active]:
                del state["open_site_scene"][key]
            for key in list(state["open_site_scene"].keys()):
                info = state["open_site_scene"][key]
                if key not in named_now:  # not re-named this turn -> age it out
                    info["ttl"] = info.get("ttl", 1) - 1
                    if info["ttl"] < 0:
                        del state["open_site_scene"][key]
                        continue
                prep = info.get("prep_file") or f"{key.upper()}_PREP.md"
                # Branch: settlements are non-hostile — push the roster reader,
                # not the dungeon turn-clock (no enter_site for scene=settlement).
                if info.get("scene") == "settlement":
                    push_line = settlement_arrival_push(user_text)
                    if push_line:
                        entries.append(_rb.Entry(_rb.URGENT, f'⊙ {push_line}'))
                    else:
                        # Fallback if detection doesn't re-fire (e.g. TTL re-render)
                        aliases = idx.get(key, {}).get("aliases") or [key.replace("_", " ")]
                        fallback = _pf.next_block(
                            _pf.push_call("reference_location",
                                          location=aliases[0],
                                          scope=_pf.raw('"who"')),
                            label="settlement — who's here")
                        entries.append(_rb.Entry(_rb.URGENT, f'⊙ {fallback}'))
                else:
                    ct, ld = info.get("current_turn"), info.get("last_seen_day")
                    if ct is not None or ld is not None:
                        ctx = []
                        if ct is not None:
                            ctx.append(f"last left turn {ct}")
                        if ld is not None:
                            ctx.append(f"day {ld}")
                        entries.append(_rb.Entry(
                            _rb.URGENT,
                            f'⊙ Player named {key.upper()} ({", ".join(ctx)}) — call '
                            f'map(action="enter_site", map_name="{key}", prep_file="{prep}") '
                            f'to resume the turn clock.'))
                    else:
                        entries.append(_rb.Entry(
                            _rb.URGENT,
                            f'⊙ Player named a known site — call '
                            f'map(action="enter_site", map_name="{key}", prep_file="{prep}") '
                            f'to start its turn clock.'))
        except Exception:
            pass  # advisory; never break the reflex block over the detector

        snap = _reflex_snapshot(campaign_dir)
        for line in _rb.diff_lines(state.get("reflex_snapshot") or {}, snap):
            entries.append(_rb.Entry(_rb.CHANGED, line))

        state["reflex_snapshot"] = snap
        return _rb.compose(entries)
    except Exception as exc:
        _log_reflex_failure(exc)
        return ""


# ===================================================================
# Semantic catch integration (Task 6)
# ===================================================================


def top_semantic_categories(session_id: str, limit: int = 3) -> list:
    """Return top-N semantic-catch categories from this session, by frequency.

    Returns list of (category, count) tuples sorted descending.
    Empty list if no semantic data for this session.
    """
    try:
        catches = get_recent_semantic_catches(session_id=session_id)
        if not catches:
            return []
        counter = Counter(c.get("category", "Unknown") for c in catches)
        return counter.most_common(limit)
    except Exception:
        return []


def build_semantic_reminder(session_id: str) -> str:
    """Compose semantic-catch reminder string for the current session.

    Returns a 'Session semantic patterns' section with specific phrases if data exists,
    otherwise returns an empty string.
    """
    parts = []

    semantic = top_semantic_categories(session_id, limit=3)
    if semantic:
        parts.append("**Session semantic patterns** (from observer):")
        for category, count in semantic:
            parts.append(f"  - {category}: {count} catches — watch for this family")

    # Surface specific caught phrases from the most recent turn
    try:
        catches = get_recent_semantic_catches(session_id=session_id)
        if catches:
            recent = [c for c in catches if c.get("confidence") in ("high", "medium")]
            quotes = [c.get("quote", "")[:50] for c in recent[-5:] if c.get("quote")]
            if quotes:
                parts.append("  **Specific phrases caught last turn:**")
                for q in quotes:
                    parts.append(f'    - "{q}"')
    except Exception:
        pass

    return "\n".join(parts) if parts else ""


def settlement_arrival_push(user_text: str) -> str:
    """If the player's words name a scene=settlement site, return the roster push line.

    Returns a NEXT (...) push calling reference_location(location=..., scope="who"),
    or '' if no settlement site is named.
    Settlements are non-hostile — no turn clock, no enter_site.
    """
    idx = _sm.build_site_index(CAMPAIGN_DIR)
    settlements = {k: v for k, v in idx.items() if v.get("scene") == "settlement"}
    matched = _sm.detect_named_sites(user_text, settlements)
    if not matched:
        return ""
    key = matched[0]
    aliases = settlements[key].get("aliases") or [key.replace("_", " ")]
    return _pf.next_block(
        _pf.push_call("reference_location", location=aliases[0], scope=_pf.raw('"who"')),
        label="settlement — who's here")


def main():
    try:
        with file_lock():
            state = load_state()

        # Skip if not in gameplay mode
        if state.get("session_type") != "gameplay":
            sys.exit(0)

        # Skip if maintenance mode
        if in_maintenance(state):
            sys.exit(0)

        # --- Vault-liveness arming/disarming ---
        # Run BEFORE building reminder so vault_enforce is current this turn.
        vault_reminder = None
        try:
            with file_lock():
                state = load_state()  # re-read under lock
                state, vault_reminder = _update_vault_enforce(state)
                save_state(state)
        except Exception:
            pass  # fail-open: missing vault reminder < bricking the hook

        catch_count = state.get("catch_count", 0)
        catch_log = state.get("catch_log", {})
        session_vocab = state.get("session_vocabulary", [])

        blacklisted, sparingly = load_blacklist()
        scene_type = _read_scene_type()
        canon_required = state.get("canon_required", False)
        reminder = build_reminder(catch_count, catch_log, blacklisted, sparingly, session_vocab, scene_type, canon_required)

        # Bell tracking: append current in-game time
        bell = state.get("current_bell", 0)
        if bell:
            labels = (["night"]*5 + ["dawn"]*2 + ["morning"]*4 + ["noon"]
                      + ["afternoon"]*5 + ["evening"]*2 + ["night"]*4 + ["midnight"])
            label = labels[bell - 1] if 1 <= bell <= 24 else ""
            h = bell if bell <= 12 else bell - 12
            if h == 0:
                h = 12
            suffix = "AM" if bell < 12 else ("noon" if bell == 12 else ("PM" if bell < 24 else "mid"))
            reminder += f" | BELL {bell} (~{h} {suffix}, {label})"

        # Vault-liveness reminder (injected after phrase discipline block)
        if vault_reminder:
            reminder = reminder + "\n\n" + vault_reminder

        # Semantic priming: merge Sonnet observer catches from this session
        try:
            hook_input = read_hook_input()
            session_id = hook_input.get("session_id") if hook_input else None
            user_prompt = hook_input.get("prompt", "") if hook_input else ""
        except Exception:
            session_id = None
            user_prompt = ""
        semantic_reminder = build_semantic_reminder(session_id) if session_id else build_semantic_reminder("")
        if semantic_reminder:
            reminder = reminder + "\n\n" + semantic_reminder if reminder else semantic_reminder

        # Reflex Layer: one block, one budget (replaces the LOAD + WOUNDS appends)
        try:
            with file_lock():
                _st = load_state()
                reflex_block = _build_reflex_block(CAMPAIGN_DIR, _st, user_prompt)
                if reflex_block:
                    reminder = reminder + "\n" + reflex_block
                save_state(_st)
        except Exception as exc:
            # fail-open: a broken reflex must never block a turn — but log it
            _log_reflex_failure(exc)

        # Output as system reminder that Claude will see
        print(reminder)
        sys.exit(0)

    except Exception:
        # Fail-open for UserPromptSubmit — no reminder is better than a crash
        sys.exit(0)


if __name__ == "__main__":
    main()
