import os
import re
import copy
import json
import asyncio
from pathlib import Path
from typing import Optional
from fastmcp import FastMCP, Context
from fastmcp.exceptions import ToolError
from fastmcp.resources import FileResource
from fastmcp.server.middleware.caching import ResponseCachingMiddleware, CallToolSettings
from fastmcp.server.middleware import Middleware, MiddlewareContext
from pydantic import Field
import random
import pdfplumber  # Keep for backwards compatibility
from dice_roller import DiceRoller
from map_system import register_map_tools
from social_system import register_social_tools
from geography_system import register_geography_tools
from rulebook_system import register_rulebook_tools
from content_forge import register_content_forge_tools, ContentForge
from combat_descriptors import assign_descriptor
import weapon_schema as ws
import gifts as _gifts
import ancestries as _ancestries
import followers as _followers
import mercenaries as _mercenaries
import pets_steeds as _pets
import vehicles as _vehicles
import factions as _factions
from scene_state import scene_dedup_elements, context_dedup_elements
import sys
import session_tools
from session_tools import (load_last_session, verify_session_save,  # Wave 8: aliased back so existing server.* references resolve
                            full_session_startup, ingest_distillations, distill_session,
                            save_state, prepare_save_state, confirm_save)
import logging
import time
from datetime import datetime
import requests
# ChromaDB import is guarded so a missing/broken install degrades instead of
# crashing the whole server before any handler runs. On a normally-configured
# rig (chromadb installed) this is a no-op and CHROMADB_AVAILABLE is True.
try:
    import chromadb  # Import at startup to avoid 4-min delay on first use
    CHROMADB_AVAILABLE = True
except ImportError:
    chromadb = None
    CHROMADB_AVAILABLE = False
# Pinned ChromaDB version — keep in sync with requirements.txt. A mismatch can
# silently corrupt the on-disk store (format differs across minor versions), so
# we warn loudly at startup if the installed version differs.
_CHROMA_EXPECTED_VERSION = "1.3.7"
from tool_tags import Safety, Phase, Domain, TOOL_TAGS
import push_format as _pf
import lexical_lane
import book_lore
# Wave 0 substrate (tool-consolidation): shared leaves live in engine_core;
# imported-and-aliased here so every existing reference stays unchanged.
from engine_core import (CAMPAIGN_DIR, RULES_DATA_DIR, read_file, write_file, dice, _JSON_CACHE,
                         _get_tool_tags, _atomic_json_write, _atomic_text_write,
                         _atomic_replace_with_retry, _load_characters,
                         _save_characters, _save_single_character, _load_party, _find_character,
                         GAME_STATE,
                         _death_seam_lines, _death_window, _twinning_partner_check,
                         _wound_save_note, _condition_save_note, _encumbrance_save_note,
                         _refresh_slot_fields, _calculate_slots, _elixir_hp_floor,
                         _all_pcs_down, _is_pc_sheet, _leader_ego_bonus,
                         _follower_morale_lines, _merc_morale_lines,
                         _check_death_conditions, _death_gate, _check_death_gated,
                         _apply_ability_damage_from_wound, _apply_wound,
                         _apply_hp_damage_and_wounds)

# Log file path - use __file__ so it works regardless of install location
STARTUP_LOG = Path(__file__).parent / "startup_log.txt"

# Diagnostic logging - when does server actually start?
with open(STARTUP_LOG, "a", encoding='utf-8') as f:
    f.write(f"Server initialized: {datetime.now()}\n")

print("SERVER STARTING", file=sys.stderr)
sys.stderr.flush()

# Ollama availability tracking
_ollama_available: bool = False
_ollama_last_check: float = 0.0
_OLLAMA_CHECK_INTERVAL: float = 60.0  # Re-check every 60 seconds if unavailable

def check_ollama_health(force: bool = False) -> bool:
    """Check if Ollama is available. Caches result for 60 seconds on failure."""
    global _ollama_available, _ollama_last_check
    import time

    now = time.time()

    # If available, assume it stays available (optimistic)
    if _ollama_available and not force:
        return True

    # If recently checked and failed, don't hammer the server
    if not force and (now - _ollama_last_check) < _OLLAMA_CHECK_INTERVAL:
        return _ollama_available

    try:
        response = requests.post(
            "http://127.0.0.1:11434/api/embeddings",
            json={"model": "nomic-embed-text", "prompt": "health"},
            timeout=5.0
        )
        response.raise_for_status()
        _ollama_available = True
        _ollama_last_check = now
        return True
    except Exception:
        _ollama_available = False
        _ollama_last_check = now
        return False

# Warm up Ollama embedding model at server start (prevents first-call timeout)
# This runs before the async event loop starts, so sync is fine here
try:
    warmup_start = datetime.now()
    requests.post("http://127.0.0.1:11434/api/embeddings",
                  json={"model": "nomic-embed-text", "prompt": "warmup"},
                  timeout=30)
    warmup_time = (datetime.now() - warmup_start).total_seconds()
    _ollama_available = True
    with open(STARTUP_LOG, "a", encoding='utf-8') as f:
        f.write(f"Ollama warmup completed: {warmup_time:.2f}s\n")
except Exception as e:
    _ollama_available = False
    with open(STARTUP_LOG, "a", encoding='utf-8') as f:
        f.write(f"Ollama warmup failed (embeddings unavailable): {e}\n")

# Initialize unbiased dice roller
# dice moved to engine_core (Wave 0); imported at the top.


# CAMPAIGN_DIR moved to engine_core (Wave 0) and imported at the top of this
# file. The RUBICON_CAMPAIGN_DIR env-override contract is unchanged.

# Path to the canon distillation cache file (writable by hooks and session-end).
# CAMPAIGN-SCOPED (was engine-relative `Path(__file__).parent/"hooks"`, a cross-campaign
# privacy leak: the shared engine-dir cache + a silent sibling fallback could surface one
# campaign's canon in another). Per-campaign now; the .lock follows the path automatically.
_DISTILLATION_CACHE_PATH = CAMPAIGN_DIR / ".canon_distillations.json"

# CAMPAIGN-SCOPED (was engine-relative — a personalization/privacy leak: this file is
# 100% per-campaign correction history, e.g. "<NPC> is a navigator not a botanist", so the
# shared engine copy mixed campaigns AND git-shipped one player's canon). Fresh = empty.
_FABRICATION_BANS_PATH = CAMPAIGN_DIR / "fabrication_bans.json"


_CREATURE_RESISTANCES_CACHE = None

def _load_creature_resistances() -> dict:
    """Load the 7-type fallback resistance matrix (cached)."""
    global _CREATURE_RESISTANCES_CACHE
    if _CREATURE_RESISTANCES_CACHE is None:
        path = RULES_DATA_DIR / "rulebook" / "creature_resistances.json"
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            _CREATURE_RESISTANCES_CACHE = {k: v for k, v in data.items() if not k.startswith("_")}
        except Exception as e:
            logging.warning(f"creature_resistances.json unavailable ({e}); using empty matrix")
            _CREATURE_RESISTANCES_CACHE = {}
    return _CREATURE_RESISTANCES_CACHE


_DAMAGE_SYNONYMS = {
    "tox": "poison", "toxic": "poison", "toxin": "poison",
    "heat": "fire", "flame": "fire", "flames": "fire", "burning": "fire", "thermal": "fire",
    "crushing": "bludgeoning", "blunt": "bludgeoning", "bludgeon": "bludgeoning",
    "slash": "slashing", "cut": "slashing",
    "pierce": "piercing", "stab": "piercing",
    "shock": "electrical", "electric": "electrical", "lightning": "electrical",
    "rad": "radiation",
    "ice": "cold", "frost": "cold", "freezing": "cold",
    "laser": "beam", "energy": "beam",
    "hyper": "hypergeometric", "fungus": "fungicide",
}

def _normalize_damage_type(s: str) -> str:
    k = (s or "").strip().lower()
    return _DAMAGE_SYNONYMS.get(k, k)


# slashing / piercing / bludgeoning are finer sub-types of the common 'kinetic'
# damage type (Crimson Hound ancestry rules, e.g. Planeyfolk 'Flat'). A sub-typed
# kinetic hit must therefore also match a creature's blanket 'kinetic' resistance,
# while specific sub-type resistances (Planeyfolk double-vs-slashing, Mineral
# double-vs-bludgeoning) fire when the sub-type is named.
_KINETIC_SUBTYPES = {"slashing", "piercing", "bludgeoning"}

def _damage_match_keys(dt: str) -> set:
    """Resistance-lookup keys for a damage type. A kinetic sub-type matches both
    itself and the parent 'kinetic'; generic 'kinetic' matches only 'kinetic'
    (an unspecified kinetic hit is not assumed to be any particular sub-type)."""
    if dt in _KINETIC_SUBTYPES:
        return {dt, "kinetic"}
    return {dt}


_TYPE_ALIASES = {
    "bio": "Biological", "biological": "Biological",
    "synth": "Synthetic", "synthetic": "Synthetic",
    "psychic": "Psychic", "psy": "Psychic",
    "fungal": "Fungal", "fungus": "Fungal",
    "mineral": "Mineral",
    "hypergeometric": "Hypergeometric", "hyper": "Hypergeometric",
    "outsider": "Outsider",
}

def _creature_types(stats: dict) -> list:
    """Parse 'Biological / Psychic' (or a 'types' list) into canonical type names."""
    raw = stats.get("type") or stats.get("types") or ""
    if isinstance(raw, list):
        parts = raw
    else:
        parts = re.split(r"[/,]", str(raw))
    out = []
    for p in parts:
        key = p.strip().lower()
        canon = _TYPE_ALIASES.get(key)
        if canon and canon not in out:
            out.append(canon)
    return out

def _expand_categories(items) -> list:
    """Expand category tokens to concrete damage types. extreme_temperature -> fire, cold."""
    out = set()
    for x in items:
        x = _normalize_damage_type(x)
        if x == "extreme_temperature":
            out.update(["fire", "cold", "extreme_temperature"])
        else:
            out.add(x)
    return sorted(out)

def _resolve_resistance_profile(stats: dict) -> dict:
    """Return {immune, minimum, double, half, varies, flags}. Explicit per-creature wins; else type-default union.

    'minimum' = damage from these types is reduced to exactly 1 (Vaarn 'minimum damage from X')."""
    explicit = stats.get("resistances")
    # Treat an explicit profile as an override ONLY if it actually says something.
    # An all-empty object means "no per-creature override recorded" and must fall
    # through to the type default -- otherwise the 7-type matrix is dead for any
    # creature carrying a blank object.
    if explicit and (explicit.get("immune") or explicit.get("minimum")
                     or explicit.get("double") or explicit.get("half")
                     or explicit.get("varies")):
        return {
            "immune": _expand_categories(explicit.get("immune", [])),
            "minimum": _expand_categories(explicit.get("minimum", [])),
            "double": _expand_categories(explicit.get("double", [])),
            "half": _expand_categories(explicit.get("half", [])),
            "varies": bool(explicit.get("varies", False)),
            "flags": [],
        }
    matrix = _load_creature_resistances()
    immune, minimum, double, half, varies, flags = set(), set(), set(), set(), False, []
    types = _creature_types(stats)
    for t in types:
        d = matrix.get(t, {})
        if d.get("varies"):
            varies = True
        immune.update(_expand_categories(d.get("immune", [])))
        minimum.update(_expand_categories(d.get("minimum", [])))
        double.update(_expand_categories(d.get("double", [])))
        half.update(_expand_categories(d.get("half", [])))
    if not types:
        flags.append("no recognized creature type")
    conflict = double & half
    if conflict:
        flags.append("type-conflict: " + ", ".join(sorted(conflict)))
    return {"immune": sorted(immune), "minimum": sorted(minimum), "double": sorted(double),
            "half": sorted(half), "varies": varies, "flags": flags}


# Weapon TAGS that deal DOUBLE damage to a creature type (Crimson Hound, verified).
# Electrical->Synthetic is already covered by the creature-type damage rules (electrical
# damage type), so it is NOT repeated here. The Hypergeometric TAG (adv. tag 13) IS here:
# it lives on weapons whose damage type is NOT hypergeometric (e.g. a kinetic
# Extra-Dimensional blade) -- the loop below guards against double-counting when the
# damage type itself is hypergeometric.
_WEAPON_TAG_DOUBLE_VS_TYPE = {
    "anti-paradoxical": "outsider",
    "eroding": "mineral",
    "psyche-suppressant": "psychic",
    "hypergeometric": "hypergeometric",
}

def _apply_creature_resistance(stats: dict, damage_type: str, amount: int, weapon_tags=None):
    """Return (modified_amount, dm_note).

    Base precedence: incorporeal-gate > immune > minimum(=1) > conflict-normal > double > half > varies > base.
    Then weapon-tag doubling vs creature type is applied on top of the base result.
    weapon_tags: optional list of weapon-tag strings (e.g. ['anti-paradoxical'])."""
    dt = _normalize_damage_type(damage_type)
    keys = _damage_match_keys(dt)
    tags = {str(t).lower().strip() for t in (weapon_tags or [])}
    prof = _resolve_resistance_profile(stats)
    types = {t.lower() for t in _creature_types(stats)}
    flag = (" [" + "; ".join(prof["flags"]) + "]") if prof["flags"] else ""
    type_double_fired = False  # True only when the type-level x2 branch below actually applied

    # Incorporeal: immune to all damage EXCEPT hypergeometric damage or anti-paradoxical weapons.
    if stats.get("incorporeal"):
        if dt != "hypergeometric" and "anti-paradoxical" not in tags:
            return 0, f"incorporeal: immune to {dt} -- only hypergeometric or anti-paradoxical weapons harm it -> 0{flag}"
        base, note = amount, f"incorporeal bypassed by {dt if dt == 'hypergeometric' else 'anti-paradoxical weapon'} -> {amount}"
    elif keys & set(prof["immune"]):
        return 0, f"immune to {dt} -> 0{flag}"
    elif keys & set(prof.get("minimum", [])):
        base, note = 1, f"minimum damage from {dt} -> 1"
    elif (keys & set(prof["double"])) and (keys & set(prof["half"])):
        base, note = amount, f"{dt}: double+half conflict -> normal ({amount})"
    elif keys & set(prof["double"]):
        base, note = amount * 2, f"{dt} x2 -> {amount * 2}"
        type_double_fired = True
    elif keys & set(prof["half"]):
        base, note = amount // 2, f"{dt} /2 -> {amount // 2}"
    elif prof["varies"]:
        base, note = amount, (f"resistances vary - SELF-CHECK: does this damage type or weapon/source qualify to "
                              f"override the creature's immunity? if not, it may be 0 ({amount})")
    else:
        base, note = amount, ""

    # Weapon-tag doubling vs creature type (book: the 'ideal weapon' doubles vs the matched type).
    for tag, ttype in _WEAPON_TAG_DOUBLE_VS_TYPE.items():
        # No double-count: skip the hypergeometric TAG only when the type-level x2
        # ACTUALLY fired above for hypergeometric damage itself -- that double already
        # represents the book effect; stacking would be x4. When it did NOT fire
        # (incorporeal bypass, or an explicit resistance profile omitting
        # hypergeometric), or fired for a DIFFERENT damage type (e.g. a kinetic
        # weakness on a Hypergeometric creature), the tag still applies.
        if tag == "hypergeometric" and dt == "hypergeometric" and type_double_fired:
            continue
        if tag in tags and ttype in types and base > 0:
            base *= 2
            note = (note + f" | {tag} weapon x2 vs {ttype.title()} -> {base}").strip(" |")

    if not note:
        return base, (flag.strip() if flag else "")
    return base, (note + flag)


# ============================================
# TOXIN DIE (B1) — book-accurate, symmetric across PCs and Biological enemies.
# Dice chain in dice_chain.py. Susceptibility = Biological only.
# ============================================
import dice_chain as _dc
import item_slots as _isl
import wounds as _wnd
import survival as _sv
import conditions as _cnd
import diseases as _dz
import mechanics_ticker as _mt

# Substance helpers (toxin/poison/usage/item — 38 funcs + 2 consts) moved to
# substances.py (decomposition slice 2); imported-and-aliased back here. Shared
# never-patched deps (_find_weapon_record/_weapon_has_tag/_weapon_is_ranged/
# VAARNISH_POISONS) stay here, injected via register_substances() below.
import substances
from substances import (
    _toxin_susceptible_enemy,
    _toxin_susceptible_pc,
    _toxin_resolve,
    _toxin_get,
    _toxin_set,
    _toxin_save_dc,
    _toxin_enemy_save,
    _toxin_incur,
    _toxin_tick,
    _toxin_cure,
    _toxin_dispatch,
    _toxin_die_from_dice,
    _toxin_attack_reroute,
    _poison_record,
    _poison_immune,
    _poison_enemy_save,
    _poison_current_day,
    _poison_death,
    _poison_resolve_effect,
    _usage_to_chain,
    _usage_to_ammo,
    _usage_applies,
    _usage_is_parasitic,
    _usage_is_fungal,
    _usage_is_expended,
    _usage_ammo_max,
    _usage_resolve,
    _usage_get,
    _usage_set,
    _usage_carried_ammo,
    _usage_deplete_roll,
    _usage_feed,
    _usage_reload,
    _usage_dispatch,
    _broken_item_msg,
    _item_depletes,
    _item_resolve,
    _item_use,
    _NON_BIOLOGICAL_PC_SPECIES,
    POISON_SAVE_TN,
)




























# ============================================
# VAARNISH POISONS (B2) - the d20 generator table (CH p.56) made mechanical.
# Table constant: VAARNISH_POISONS (beside HYPERGEOMETRIC_MISHAPS). Application
# rides the toxin tool (poison_apply/poison_resolve); R-B2a save fork below.
# Spec: docs/superpowers/specs/2026-06-12-b2-poisons-design.md
# ============================================











def _find_weapon_record(char, weapon_name):
    """Locate a weapon record on a PC's inventory.carried by case-insensitive
    substring match (the _resolve_attacker_weapon selection rule, on a passed
    char dict). Returns the live dict, or None when absent/ambiguous."""
    if not weapon_name or not isinstance(char, dict):
        return None
    carried = (char.get("inventory") or {}).get("carried", [])
    needle = str(weapon_name).strip().lower()
    matches = [i for i in carried if isinstance(i, dict)
               and needle in str(i.get("name", "")).lower()]
    return matches[0] if len(matches) == 1 else None


def _consume_weapon_coating(attacker_name, weapon_rec):
    """Pop a poison_coating off the attacker's weapon (one dose, R-B2b) and
    persist the pop. weapon_rec is the in-call resolved copy (a separate
    _load_characters read); the sheet is re-loaded so the consumption sticks.

    The disk record is matched by IDENTITY of the coating payload (an equal
    poison_coating dict), name-disambiguated when several carry one - never
    by fuzzy name search alone (a substring multi-match must not let a spent
    dose survive on disk and re-fire). Returns (coating, warning_or_None)."""
    if not isinstance(weapon_rec, dict):
        return None, None
    coating = weapon_rec.pop("poison_coating", None)
    if coating is None:
        return None, None
    warning = None
    data, err = _load_characters()
    if not err and data:
        key, char = _find_character(data, attacker_name)
        if char:
            carried = (char.get("inventory") or {}).get("carried", [])
            wname = str(weapon_rec.get("name", "")).strip().lower()
            persisted = False
            # Pass 1: the in-call copy IS the disk record (patched loaders /
            # shared state) - the pop above already consumed it.
            if any(rec is weapon_rec for rec in carried):
                persisted = True
            else:
                # Pass 2: exact-name match carrying an equal coating.
                # Pass 3: any record carrying an equal coating (nameless
                # weapon records still get their dose spent).
                candidates = (
                    [r for r in carried if isinstance(r, dict)
                     and str(r.get("name", "")).strip().lower() == wname
                     and r.get("poison_coating") == coating]
                    or [r for r in carried if isinstance(r, dict)
                        and r.get("poison_coating") == coating])
                if candidates:
                    candidates[0].pop("poison_coating", None)
                    persisted = True
            if persisted:
                _save_single_character(key, char, data)
            else:
                warning = (f"WARNING: spent coating could not be matched on "
                           f"{attacker_name}'s sheet - remove the "
                           f"poison_coating from '{weapon_rec.get('name', '?')}' "
                           f"manually or it will fire again.")
                logging.warning("B2 coating consumption: no disk record "
                                "matched for %s / %s", attacker_name,
                                weapon_rec.get("name"))
        else:
            warning = (f"WARNING: could not load {attacker_name}'s sheet to "
                       f"persist the spent coating - check it manually.")
    return coating, warning






# ============================================
# USAGE DIE (ranged ammo) — reuses dice_chain. PC-only.
# State = weapon `ammo` (Udx) on inventory.carried[] (authoritative);
# attacks[] is a display mirror. `ammo_max` caps feed/reload.
# ============================================





def _weapon_has_tag(weapon: dict, key: str) -> bool:
    """True if `weapon` carries tag `key` — checks engine_tags first, then a
    case-insensitive scan of the prose `tags` list (resolved via
    ws.resolve_tag). Covers generated weapons AND hand-authored / inherent tags
    (e.g. the Spore Thrower's inherent 'Fungal')."""
    key = key.lower()
    if key in [str(t).lower() for t in (weapon.get("engine_tags") or [])]:
        return True
    return any(ws.resolve_tag(t) == key for t in (weapon.get("tags") or []))


# R3 -- AV-interacting weapon specials. The combat engine OWNS these four tags
# (never hand-applied by the DM): vibroactive / dimensional-edge cap the hit
# contest at AV 10; piercing / mauling modify damage by the target's REAL AV
# bracket. Lookups go through _weapon_has_tag so stamped engine_tags AND
# hand-authored prose tags both work. NEVER keyed off kinetic_subtype.
_AV_OVERRIDE_LABELS = {"vibroactive": "Vibroactive",
                       "dimensional-edge": "Dimensional Edge"}


def _weapon_av_override(weapon: dict):
    """Return 'vibroactive' / 'dimensional-edge' if the weapon ignores armour,
    else None."""
    if _weapon_has_tag(weapon, "vibroactive"):
        return "vibroactive"
    if _weapon_has_tag(weapon, "dimensional-edge"):
        return "dimensional-edge"
    return None


def _weapon_av_damage_tag(weapon: dict):
    """Return 'piercing' / 'mauling' if the weapon has AV-conditional damage,
    else None. Piercing wins if data illegally carries both (pinned by test)."""
    if _weapon_has_tag(weapon, "piercing"):
        return "piercing"
    if _weapon_has_tag(weapon, "mauling"):
        return "mauling"
    return None


























# ---- Equipment depletion (U2): any carried depletable, the unified 'use' verb ----









def _stamp_slots_uses(item: dict) -> dict:
    """Set a generated item's structured depletion fields as a pure function of its
    book `slots_uses` string: `slots`, and one of `usage_die`/`usage_max` or
    `uses`/`uses_max`. Clears any prior depletion keys first, so re-stamping after a
    kind change leaves no stale fields. Leaves depletion unset for Unlimited /
    pointer notations."""
    parsed = _isl.parse_slots_uses(item.get("slots_uses"))
    for _k in ("usage_die", "usage_max", "uses", "uses_max"):
        item.pop(_k, None)
    item["slots"] = parsed["slots"]
    if parsed["kind"] == "usage_die":
        item["usage_die"] = parsed["usage_die"]
        item["usage_max"] = parsed["usage_die"]
    elif parsed["kind"] == "discrete":
        item["uses"] = parsed["uses"]
        item["uses_max"] = parsed["uses"]
    return item




def _get_fabrication_bans():
    """Build a FabricationBans instance bound to the default ban-list path."""
    try:
        from hooks.fabrication_bans import FabricationBans
    except ImportError:
        from fabrication_bans import FabricationBans
    return FabricationBans(_FABRICATION_BANS_PATH)


def _get_distillation_cache():
    """Build a DistillationCache instance bound to the default cache path."""
    try:
        from hooks.distillation_cache import DistillationCache
    except ImportError:
        from distillation_cache import DistillationCache
    return DistillationCache(_DISTILLATION_CACHE_PATH)


def _echo_npc_dossiers_to_distillation_cache(session_id: str = "") -> int:
    """Session-end backstop: upsert each NPC-with-continuity into the distillation
    cache so ingest_distillations embeds it for deep recall. Keyed npc:<slug>:profile
    (idempotent via DistillationCache.put, which overwrites by topic_key). The dossier
    text lives in `learning` because that is the field ingest_distillations embeds.
    Returns the count echoed. NPCs with no continuity (no left_off / open_purpose) are
    skipped.

    NEVER raises: this runs at session-end AFTER the real distillation write has
    already succeeded, so any failure here (corrupt npc_states.json, cache I/O)
    is swallowed to a warning + 0 rather than breaking the session-end flow."""
    try:
        data, err = _load_npc_states()
        if err:
            return 0
        cache = _get_distillation_cache()
        n = 0
        for slug, rec in (data.get("npcs") or {}).items():
            left = (rec.get("left_off") or "").strip()
            purpose = (rec.get("open_purpose") or "").strip()
            if not left and not purpose:
                continue
            name = rec.get("name", slug)
            disp = rec.get("disposition", "neutral")
            text = f"{name} ({disp}). Left off: {left} Open purpose: {purpose}".strip()
            topic_key = f"npc:{slug}:profile"
            existing = cache.get(topic_key) or {}
            cache.put({
                "topic_key": topic_key,
                "learning": text,
                "key_facts": [f"left_off: {left}", f"open_purpose: {purpose}"],
                "source_pointers": ["npc_states.json"],
                "type": "npc_dossier",
                "characters": [slug],
                "entities": [slug],
                "verified_against": {},
                "created_turn": 0,
                "created_session": existing.get("created_session") or session_id,
                "refined_turn": 0,
                "refined_count": existing.get("refined_count", 0) + 1,
                "last_seen_day": rec.get("last_seen_day", 0),
                # Re-arm for embedding on every echo so a changed dossier re-ingests.
                "ingested_at_session": None,
            })
            n += 1
        return n
    except Exception as exc:
        logging.warning(f"_echo_npc_dossiers_to_distillation_cache non-fatal: {exc}")
        return 0


# ============================================
# CHROMADB SINGLETON & EMBEDDING CACHE
# ============================================
# Avoids instantiating ChromaDB client on every query (expensive).
# LRU cache prevents redundant Ollama calls for repeated queries.

from functools import lru_cache
from contextlib import contextmanager
from filelock import FileLock, Timeout as _FileLockTimeout
import hashlib

# Singleton ChromaDB client - initialized lazily on first use
# Note: Use Optional[] syntax because chromadb.PersistentClient is a function, not a class
_chroma_client: Optional[object] = None

def get_chroma_client() -> "chromadb.PersistentClient":
    """Get singleton ChromaDB client. Initializes on first call."""
    global _chroma_client
    if not CHROMADB_AVAILABLE:
        # Unreachable on a normal rig (chromadb installed → CHROMADB_AVAILABLE is
        # True). Only hit on a fresh/misconfigured machine; raise an actionable
        # error instead of an opaque NameError/AttributeError on chromadb.* .
        raise RuntimeError(
            "ChromaDB is not installed — campaign search/memory is unavailable. "
            "Install it with: pip install chromadb==1.3.7"
        )
    if _chroma_client is None:
        chroma_path = CAMPAIGN_DIR / "chroma-db"
        _chroma_client = chromadb.PersistentClient(path=str(chroma_path))
        with open(STARTUP_LOG, "a", encoding='utf-8') as f:
            f.write(f"ChromaDB client initialized: {datetime.now()}\n")
    return _chroma_client


# --- Cross-process single-writer guard for the live ChromaDB store ----------
# The store has no built-in cross-process lock. Joe runs two MCP sessions at
# once by design (a dev terminal + the live gameplay terminal), each a stdio
# child bound to the same chroma-db. Concurrent writes desync/corrupt the HNSW
# index. This lock serializes WRITES across processes; reads pass through
# untouched. See docs/CHROMA_SINGLE_WRITER.md.
_CHROMA_LOCK_TIMEOUT_SEC = 60.0  # hard ceiling, then fail-open (never lose a save)

@contextmanager
def _chroma_write_lock():
    """Acquire an exclusive cross-process lock around a live-store write.

    Uses `filelock` (OS-native locks: msvcrt on Windows, fcntl on Unix). The
    lock auto-releases if the holding process dies, so there is no stale-lock
    problem and no Windows file-sharing race. On timeout we fail OPEN with a
    warning rather than block/lose a write — corruption from a rare interleave
    is recoverable; a dropped save during play is not.
    """
    lock_path = str(CAMPAIGN_DIR / "chroma-db" / ".write.lock")
    fl = FileLock(lock_path, timeout=_CHROMA_LOCK_TIMEOUT_SEC)
    try:
        fl.acquire()
    except _FileLockTimeout:
        logging.warning("chroma write lock: timeout; proceeding WITHOUT lock")
        yield
        return
    try:
        yield
    finally:
        try:
            fl.release()
        except Exception:
            pass


class _LockedCollection:
    """Thin wrapper: writes take the cross-process lock, reads pass through.

    Covers every present and future write site in one place, instead of
    wrapping scattered .add/.upsert/.delete calls across the codebase.
    """
    __slots__ = ("_c",)

    def __init__(self, c):
        object.__setattr__(self, "_c", c)

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_c"), name)

    def add(self, *a, **k):
        with _chroma_write_lock():
            return self._c.add(*a, **k)

    def upsert(self, *a, **k):
        with _chroma_write_lock():
            return self._c.upsert(*a, **k)

    def update(self, *a, **k):
        with _chroma_write_lock():
            return self._c.update(*a, **k)

    def delete(self, *a, **k):
        with _chroma_write_lock():
            return self._c.delete(*a, **k)


def get_chroma_collection(name: str = "campaign_history"):
    """Get a ChromaDB collection using singleton client.

    Redirects 'campaign_history_tiered' to the v2 cosine collection
    if it exists. Falls back to original L2 collection.
    """
    if name == "campaign_history_tiered":
        client = get_chroma_client()
        # Try v2 (cosine) collection first
        try:
            return _LockedCollection(client.get_collection("campaign_history_tiered_v2"))
        except Exception:
            # Fall back to original L2 collection
            return _LockedCollection(client.get_collection(name))
    return _LockedCollection(get_chroma_client().get_collection(name))


def get_canon_distillations_collection():
    """Get-or-create the canon_distillations ChromaDB collection.

    This collection holds embedded semantic learnings (distillations) ingested
    at session-end. check_canon queries this BEFORE drilling raw history tiers.

    Configured with cosine similarity (matches campaign_history_tiered_v2).

    Expected document metadata shape (see design spec §4):
        topic_key       str   — normalized topic key (e.g. "amara_varro_relationship")
        characters      str   — comma-joined sorted character slugs
        created_session str   — session id that first created this distillation
        refined_count   int   — number of times this distillation has been updated
        lorebook_mtime  float — mtime of lorebook.json when distillation was verified
        suffix          str   — last token of topic_key (e.g. "relationship", "history")

    NOTE on character filtering: `characters` is stored as a comma-joined string
    because ChromaDB metadata doesn't support list-type values. Exact-match
    WHERE filters won't work for individual character names. Task 10 should
    either:
      (a) Use semantic similarity as the primary retrieval (recommended) and
          post-filter results in Python for character presence, OR
      (b) Use `where_document={"$contains": "amara"}` for substring match
          on the learning text (less precise but ChromaDB-native).
    The substring approach in (b) is brittle because learnings may reference
    characters by descriptors rather than name. Prefer (a).
    """
    client = get_chroma_client()
    return _LockedCollection(client.get_or_create_collection(
        "canon_distillations",
        metadata={"hnsw:space": "cosine"},
    ))


# Embedding cache - LRU cache for query embeddings (max 128 entries)
# Avoids re-embedding identical queries within a session
@lru_cache(maxsize=512)
def _cached_embedding(prompt_hash: str, prompt: str) -> tuple:
    """Internal: cached embedding lookup. Returns tuple for hashability.

    Note: prompt already has 'search_query: ' prefix applied by get_embedding_cached().
    """
    if not check_ollama_health():
        raise ConnectionError("Ollama unavailable - embeddings disabled. Start Ollama and retry.")
    response = requests.post(
        'http://127.0.0.1:11434/api/embeddings',
        json={'model': 'nomic-embed-text', 'prompt': prompt},
        timeout=30.0
    )
    response.raise_for_status()
    return tuple(response.json()['embedding'])

def get_embedding_cached(prompt: str, timeout: float = 30.0) -> list[float]:
    """Get embedding with LRU caching. Applies 'search_query: ' prefix for nomic-embed-text.

    Use for QUERIES only. For indexing, use get_ollama_embedding_sync().
    """
    # Add task-type prefix for nomic-embed-text (improves retrieval quality)
    prefixed = f"search_query: {prompt}"
    prompt_hash = hashlib.md5(prefixed.encode()).hexdigest()
    return list(_cached_embedding(prompt_hash, prefixed))

# ============================================
# PRE-COMPILED REGEX PATTERNS (Token Optimization)
# ============================================
# Compile patterns once at module init instead of on every check_canon call
# Saves 1,500-2,500 tokens/session + 50-100ms per call

_COMPILED_PATTERNS = {
    # Intimate/romantic keywords for auto-escalation to full context
    'intimate': [
        re.compile(rf'\b{re.escape(kw)}\b', re.IGNORECASE)
        for kw in ['kiss', 'hold her', 'hold him', 'hold me', 'embrace', 'caress',
                   'stroke', 'naked', 'bed', 'sleep together', 'make love', 'intimate',
                   'tender moment', 'lips', 'neck', 'thigh', 'skin to skin', 'breath',
                   'moan', 'whisper', 'cuddle', 'nuzzle', 'desert bloom', 'oasis queen']
    ],

    # Lore question patterns for auto-escalation to full context
    'lore_questions': [
        re.compile(p, re.IGNORECASE)
        for p in [r'what (do|did) (we|i|you) know', r'tell me about',
                  r'explain.*(to me|what|who|how)', r'remind me', r'who is',
                  r'what is.*\?', r'what happened', r'did (we|i) ever', r'is it true',
                  r"what'?s the (story|history|deal)", r'how did.*\?']
    ],

    # Tool recommendation keyword groups
    'vault': [
        re.compile(rf'\b{re.escape(kw)}\b', re.IGNORECASE)
        for kw in ['room', 'door', 'corridor', 'explore', 'search the', 'look around',
                   'enter', 'passage', 'chamber', 'descend', 'ascend', 'stairs']
    ],

    'npc_actions': [
        re.compile(rf'\b{re.escape(kw)}\b', re.IGNORECASE)
        for kw in ['decides', 'considers', 'says', 'asks', 'tells', 'responds',
                   'answers', 'agrees', 'refuses', 'hesitates', 'nods', 'shakes']
    ],

    'combat': [
        re.compile(rf'\b{re.escape(kw)}\b', re.IGNORECASE)
        for kw in ['attack', 'fight', 'combat', 'initiative', 'hit', 'strike',
                   'shoot', 'fire at', 'charge', 'defend']
    ],

    'rest': [
        re.compile(rf'\b{re.escape(kw)}\b', re.IGNORECASE)
        for kw in ['rest', 'sleep', 'heal', 'recover', 'short rest', 'long rest',
                   'take a break', 'bandage', 'tend wounds']
    ],

    'day': [
        re.compile(rf'\b{re.escape(kw)}\b', re.IGNORECASE)
        for kw in ['next day', 'next morning', 'wake up', 'overnight', 'dawn',
                   'the following day', 'after sleeping']
    ],

    'creature': [
        re.compile(rf'\b{re.escape(kw)}\b', re.IGNORECASE)
        for kw in ['creature', 'monster', 'beast', 'enemy', 'ghoul', 'gene thief',
                   'faa', 'cacogen', 'synth', 'newbeast']
    ],

    'loot': [
        re.compile(rf'\b{re.escape(kw)}\b', re.IGNORECASE)
        for kw in ['loot', 'treasure', 'exotica', 'find', 'discover', 'take the',
                   'pick up', 'grab', 'collect']
    ],

    'travel': [
        re.compile(rf'\b{re.escape(kw)}\b', re.IGNORECASE)
        for kw in ['travel to', 'head to', 'journey to', 'fly to', 'return to']
    ],
}

# ========================================
# CANON CONTEXT BLOCKS — shopping list for check_canon needs parameter
# ========================================
CANON_BLOCKS = {
    'voice', 'relationships', 'prep', 'npc_knowledge',
    'threads', 'history', 'characters', 'lorebook_full',
}
CANON_PREFIXED_BLOCKS = {'prep_npcs'}

REGEX_BLOCK_MAP = {
    'scene_change': {'prep', 'voice', 'relationships', 'npc_knowledge', 'characters'},
    'session_start': CANON_BLOCKS.copy(),
    'scene_recall': {'history', 'lorebook_full', 'prep'},
    'intimate': {'voice', 'relationships', 'lorebook_full'},
    'lore_question': {'lorebook_full', 'history', 'threads'},
    'high_match_count': {'lorebook_full', 'threads', 'prep'},
    'explicit': CANON_BLOCKS.copy(),
}


def _resolve_canon_needs(needs: list[str], regex_blocks: set[str]) -> set[str]:
    """Resolve final block set from Claude's requests + regex fallback.

    Returns union of valid needs + regex_blocks. Invalid block names silently dropped.
    Prefixed blocks (e.g. prep_npcs:Drewe) validated by prefix only.
    """
    resolved = set(regex_blocks)
    for block in needs:
        if block in CANON_BLOCKS:
            resolved.add(block)
        elif ':' in block:
            prefix = block.split(':', 1)[0]
            if prefix in CANON_PREFIXED_BLOCKS:
                resolved.add(block)
    return resolved


def _build_regex_blocks(
    hook_state: dict,
    input_lower: str,
    scene_recall_triggered: bool,
    lorebook_match_count: int,
) -> tuple[set[str], list[str]]:
    """Determine which context blocks regex triggers want loaded.

    Returns (blocks, reasons) where blocks is the union of all triggered
    block sets and reasons lists which triggers fired.
    """
    blocks = set()
    reasons = []

    if hook_state.get('scene_changed', True):
        blocks.update(REGEX_BLOCK_MAP['scene_change'])
        reasons.append('scene_change')

    if hook_state.get('turn_count', 0) <= 1:
        blocks.update(REGEX_BLOCK_MAP['session_start'])
        reasons.append('session_start')

    if scene_recall_triggered:
        blocks.update(REGEX_BLOCK_MAP['scene_recall'])
        reasons.append('scene_recall')

    for pattern in _COMPILED_PATTERNS['intimate']:
        if pattern.search(input_lower):
            blocks.update(REGEX_BLOCK_MAP['intimate'])
            reasons.append('intimate')
            break

    for pattern in _COMPILED_PATTERNS['lore_questions']:
        if pattern.search(input_lower):
            blocks.update(REGEX_BLOCK_MAP['lore_question'])
            reasons.append('lore_question')
            break

    if lorebook_match_count >= 4:
        blocks.update(REGEX_BLOCK_MAP['high_match_count'])
        reasons.append('high_match_count')

    return blocks, reasons


# ============================================
# TIERED CHUNKING FOR CAMPAIGN HISTORY
# ============================================
# Used by save_state to chunk narrative logs into 4 tiers for tiered search

def _infer_scene_type(narrative: str) -> str:
    """
    Infer scene type from narrative text using keyword matching.

    Returns: combat, intimate, travel, dialogue, exploration, or political
    """
    narrative_lower = narrative.lower()

    # Combat indicators
    if any(word in narrative_lower for word in ["hp damage", "attack", "combat", "enemy", "weapon", "fight", "killed", "battle"]):
        return "combat"

    # Intimate indicators
    if any(word in narrative_lower for word in ["lovemaking", "intimate", "quantum bond", "fell asleep together", "kiss", "bed", "shower", "naked"]):
        return "intimate"

    # Travel indicators
    if any(word in narrative_lower for word in ["journey", "travel", "arrived", "departed", "ornithopter", "flight", "piloting"]):
        return "travel"

    # Political indicators
    if any(word in narrative_lower for word in ["council", "vote", "political", "dinner", "negotiation", "alliance", "diplomatic"]):
        return "political"

    # Dialogue-heavy (lots of quotes)
    if narrative.count('"') > 10 or narrative.count('>') > 5:
        return "dialogue"

    # Default
    return "exploration"


def _preprocess_for_embedding(text: str) -> str:
    """Strip markdown noise from text before embedding.

    Removes headers (##, ###), bullet markers, excessive whitespace.
    Keeps the semantic content clean for the embedding model.
    The ORIGINAL text is stored in ChromaDB for display; this is only for embedding.
    """
    # Strip markdown headers
    cleaned = re.sub(r'^#{1,4}\s+', '', text, flags=re.MULTILINE)
    # Strip bullet markers
    cleaned = re.sub(r'^\s*[-*+]\s+', '', cleaned, flags=re.MULTILINE)
    # Strip horizontal rules
    cleaned = re.sub(r'^---+\s*$', '', cleaned, flags=re.MULTILINE)
    # Strip bold/italic markers
    cleaned = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', cleaned)
    # Collapse whitespace
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    cleaned = re.sub(r'  +', ' ', cleaned)
    return cleaned.strip()


def _split_at_paragraphs(text: str, max_size: int) -> list[str]:
    """Split text at paragraph boundaries without exceeding max_size.

    Ported from chunk_campaign_tiered.py for semantic boundary detection.
    Falls back to sentence splitting for oversized paragraphs.
    """
    if len(text) <= max_size:
        return [text]

    chunks = []
    current = ""

    paragraphs = re.split(r'\n\n+', text)

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        if len(current) + len(para) + 2 > max_size:
            if current.strip():
                chunks.append(current.strip())
            current = para
        else:
            current = current + "\n\n" + para if current else para

    if current.strip():
        chunks.append(current.strip())

    # Handle oversized single paragraphs by splitting at sentences
    final_chunks = []
    for chunk in chunks:
        if len(chunk) > max_size * 1.5:
            sentences = re.split(r'(?<=[.!?])\s+', chunk)
            sub_chunk = ""
            for sent in sentences:
                if len(sub_chunk) + len(sent) + 1 > max_size:
                    if sub_chunk:
                        final_chunks.append(sub_chunk.strip())
                    sub_chunk = sent
                else:
                    sub_chunk = sub_chunk + " " + sent if sub_chunk else sent
            if sub_chunk:
                final_chunks.append(sub_chunk.strip())
        else:
            final_chunks.append(chunk)

    return final_chunks


def _chunk_tier4_semantic(text: str, session_id: str, metadata: dict) -> list[dict]:
    """Generate Tier 4 chunks using semantic boundaries.

    Splits at: SESSION SAVED markers > ### headers > --- dividers > paragraphs.
    Ported from chunk_campaign_tiered.py. Much better than fixed-window chunking
    because it never cuts mid-sentence or mid-name.
    """
    chunks = []
    chunk_index = 0

    # Split by SESSION SAVED markers first
    session_pattern = r'\n(?=## SESSION SAVED)'
    major_sections = re.split(session_pattern, text)

    for major_section in major_sections:
        major_section = major_section.strip()
        if not major_section:
            continue

        # Split by ### headers
        if '### ' in major_section:
            sub_sections = re.split(r'\n(?=### )', major_section)
            for sub in sub_sections:
                sub = sub.strip()
                if not sub:
                    continue
                if len(sub) > 3000:
                    for small_chunk in _split_at_paragraphs(sub, max_size=3000):
                        if len(small_chunk) >= 100:
                            chunk_id = f"{session_id}_t4_{chunk_index:04d}"
                            chunks.append({
                                "id": chunk_id,
                                "text": small_chunk,
                                "char_start": 0,
                                "char_end": len(small_chunk),
                                "metadata": {**metadata, "tier": 4, "char_count": len(small_chunk)}
                            })
                            chunk_index += 1
                elif len(sub) >= 100:
                    chunk_id = f"{session_id}_t4_{chunk_index:04d}"
                    chunks.append({
                        "id": chunk_id,
                        "text": sub,
                        "char_start": 0,
                        "char_end": len(sub),
                        "metadata": {**metadata, "tier": 4, "char_count": len(sub)}
                    })
                    chunk_index += 1
        else:
            # No headers, try --- dividers
            if '---' in major_section:
                divider_sections = major_section.split('---')
                for div in divider_sections:
                    div = div.strip()
                    if len(div) > 3000:
                        for small_chunk in _split_at_paragraphs(div, max_size=3000):
                            if len(small_chunk) >= 100:
                                chunk_id = f"{session_id}_t4_{chunk_index:04d}"
                                chunks.append({
                                    "id": chunk_id,
                                    "text": small_chunk,
                                    "char_start": 0,
                                    "char_end": len(small_chunk),
                                    "metadata": {**metadata, "tier": 4, "char_count": len(small_chunk)}
                                })
                                chunk_index += 1
                    elif div and len(div) >= 100:
                        chunk_id = f"{session_id}_t4_{chunk_index:04d}"
                        chunks.append({
                            "id": chunk_id,
                            "text": div,
                            "char_start": 0,
                            "char_end": len(div),
                            "metadata": {**metadata, "tier": 4, "char_count": len(div)}
                        })
                        chunk_index += 1
            else:
                # No structure, split at paragraphs
                for small_chunk in _split_at_paragraphs(major_section, max_size=3000):
                    if len(small_chunk) >= 100:
                        chunk_id = f"{session_id}_t4_{chunk_index:04d}"
                        chunks.append({
                            "id": chunk_id,
                            "text": small_chunk,
                            "char_start": 0,
                            "char_end": len(small_chunk),
                            "metadata": {**metadata, "tier": 4, "char_count": len(small_chunk)}
                        })
                        chunk_index += 1

    return chunks


def chunk_text_tiered(
    text: str,
    metadata: dict,
    session_id: str = None
) -> list[dict]:
    """
    Chunk text into 4 tiers with semantic boundaries and parent-child linking.

    Tier 4 uses semantic chunking (session markers, headers, paragraphs).
    Tiers 1-3 are fixed-window sub-chunks of their Tier 4 parents.
    Each chunk stores original text (for display) but embedding is preprocessed.

    Args:
        text: Narrative text to chunk
        metadata: Base metadata dict with day, arc, characters, scene_type
        session_id: Optional session identifier (defaults to f"session_day_{metadata['day']}")

    Returns:
        List of chunk dicts ready for ChromaDB indexing. Each has:
        - "text": original text for display
        - "embedding_text": preprocessed text for embedding (markdown stripped)
        - "metadata": tier, day, arc, characters, scene_type, parent_id, etc.
    """
    TIER_SIZES = {
        1: {"size": 150, "overlap": 75},   # 50% overlap
        2: {"size": 300, "overlap": 150},  # 50% overlap
        3: {"size": 800, "overlap": 200},  # 25% overlap
    }

    chunks = []
    session_id = session_id or f"session_day_{metadata.get('day', 0)}"

    # STEP 1: Generate Tier 4 chunks using SEMANTIC boundaries
    tier4_chunks = _chunk_tier4_semantic(text, session_id, metadata)

    # If semantic chunking produced nothing (no structure), fall back to fixed-window
    if not tier4_chunks:
        t4_size, t4_overlap = 3000, 500
        for i in range(0, len(text), t4_size - t4_overlap):
            chunk_text = text[i:i + t4_size]
            if len(chunk_text.strip()) < 50:
                continue
            chunk_id = f"{session_id}_t4_{len(tier4_chunks):04d}"
            tier4_chunks.append({
                "id": chunk_id,
                "text": chunk_text,
                "char_start": i,
                "char_end": i + len(chunk_text),
                "metadata": {**metadata, "tier": 4, "char_count": len(chunk_text)}
            })

    # Add preprocessed embedding text to Tier 4 chunks
    for t4 in tier4_chunks:
        t4["embedding_text"] = _preprocess_for_embedding(t4["text"])
        t4["metadata"]["source"] = metadata.get("source", "save_state")

    chunks.extend(tier4_chunks)

    # STEP 2: Generate Tier 1-3 as fixed-window sub-chunks of each Tier 4 parent
    for t4 in tier4_chunks:
        parent_text = t4["text"]
        parent_id = t4["id"]

        for tier in [1, 2, 3]:
            config = TIER_SIZES[tier]
            size = config["size"]
            overlap = config["overlap"]
            stride = size - overlap

            tier_chunk_count = 0
            for i in range(0, len(parent_text), stride):
                chunk_text = parent_text[i:i + size]
                if len(chunk_text.strip()) < 50:
                    continue

                chunk_id = f"{parent_id}_t{tier}_{tier_chunk_count:04d}"
                chunks.append({
                    "id": chunk_id,
                    "text": chunk_text,
                    "embedding_text": _preprocess_for_embedding(chunk_text),
                    "metadata": {
                        **metadata,
                        "tier": tier,
                        "source": metadata.get("source", "save_state"),
                        "parent_id": parent_id,
                        "char_count": len(chunk_text)
                    }
                })
                tier_chunk_count += 1

    return chunks


def _stringify_metadata(meta: dict) -> dict:
    """Coerce every ChromaDB metadata value to a string.

    The tiered read path filters on a STRING-typed tier (``{"tier": str(tier)}``
    in _search_single_tier / the tier=0 sweep), so any tiered WRITE must stringify
    or its docs are invisible to tier-filtered retrieval. Both writers — the
    save_state auto-index and reindex_recent — route their collection.add through
    this one helper so they cannot diverge on metadata types again (audit C5).
    """
    return {k: str(v) for k, v in meta.items()}


# ============================================
# JSON FILE CACHE (mtime-based invalidation)
# ============================================
# Files like lorebook.json, characters.json are parsed MULTIPLE times per session
# but RARELY change (only on explicit tool writes). Caching saves 2,550-7,400 tokens/session.

# _JSON_CACHE moved to engine_core (Wave 0); imported (by-reference) at the top.

def _load_cached_json(filepath: Path, cache_key: str = None) -> dict:
    """Load JSON with automatic cache invalidation on file changes.

    Args:
        filepath: Path to JSON file
        cache_key: Optional cache key (defaults to str(filepath))

    Returns:
        Parsed JSON data (dict)
    """
    if cache_key is None:
        cache_key = str(filepath)

    cached_data, cached_mtime = _JSON_CACHE.get(cache_key, (None, None))

    try:
        current_mtime = filepath.stat().st_mtime

        # Cache hit if mtime unchanged
        if cached_data is not None and cached_mtime == current_mtime:
            return cached_data

        # Cache miss or stale - reload
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        _JSON_CACHE[cache_key] = (data, current_mtime)
        return data

    except Exception as e:
        # Return stale cache on error, or empty dict
        return cached_data if cached_data else {}

# ============================================
# PERFORMANCE LOGGING MIDDLEWARE (Phase 0)
# Records response size and wall-clock time per tool call.
# Output: logs/perf_log.jsonl (one JSON line per call)
# ============================================
PERF_LOG_PATH = Path(__file__).parent / "logs" / "perf_log.jsonl"

class PerfLoggingMiddleware(Middleware):
    async def on_call_tool(self, context: MiddlewareContext, call_next):
        tool_name = "unknown"
        action = None
        try:
            msg = getattr(context, 'message', None)
            if msg:
                tool_name = getattr(msg, 'name', None) or "unknown"
                args = getattr(msg, 'arguments', None) or {}
                action = args.get('action')
        except Exception:
            pass
        start = time.time()
        result = await call_next(context)
        elapsed_ms = int((time.time() - start) * 1000)

        response_chars = 0
        if hasattr(result, 'content'):
            if isinstance(result.content, str):
                response_chars = len(result.content)
            elif isinstance(result.content, list):
                response_chars = sum(len(getattr(c, 'text', '')) for c in result.content)

        try:
            hook_state_path = Path(__file__).parent / "hooks" / ".hook_state.json"
            turn = 0
            session_id = ""
            if hook_state_path.exists():
                with open(hook_state_path) as f:
                    hs = json.load(f)
                    turn = hs.get("turn_count", 0)
                    session_id = hs.get("session_id", "")

            log_entry = {
                "ts": datetime.now().isoformat(),
                "tool": tool_name,
                "chars": response_chars,
                "tokens_est": response_chars // 4,
                "ms": elapsed_ms,
                "turn": turn,
            }
            if action:
                log_entry["action"] = action
            if session_id:
                log_entry["session_id"] = session_id

            with open(PERF_LOG_PATH, "a") as f:
                f.write(json.dumps(log_entry) + "\n")
        except Exception:
            pass

        return result

# Instantiate the middleware
perf_logger = PerfLoggingMiddleware()

# Create the MCP server
mcp = FastMCP(
    "rubicon-seven",
    version="8.9.1",
    middleware=[
        ResponseCachingMiddleware(
            call_tool_settings=CallToolSettings(
                ttl=300,  # Cache for 5 minutes
                included_tools=[
                    # ONLY cache truly static lookups - rules, bestiary, items
                    # DO NOT cache: check_canon, get_character_hp, get_character_stat
                    # Those read live state that changes during play!

                    # Static reference lookups (safe to cache)
                    "lorebook_view",        # Lorebook entries rarely change mid-session
                    "reference_location",   # Location reference docs are static
                    "lookup",               # Bestiary/exotica/weapon/career lookups are static
                    "gift",                 # Rules are static
                    "narrative_qa",        # Anti-patterns are static

                    # REMOVED from cache (these read live state):
                    # - check_canon: reads CURRENT_STATUS.md, RELATIONSHIP_MATRIX.json
                    # - get_character_hp: HP changes constantly in combat
                    # - get_character_stat: Stats can change (damage, level up)
                    # - gleam_check: Depends on current gift count
                    # - cybernetic: Can change when implants added/removed
                    # - party_wealth_get: Wealth changes frequently
                    # - party_vehicles_status: Location changes
                ]
            )
        ),
        perf_logger,  # Phase 0 - logs response size and timing per tool call
    ]
)

# _get_tool_tags moved to engine_core (Wave 0); imported at the top.


# ============================================
# GAME STATE & ENFORCEMENT LAYER
# ============================================
# Tracks active location, secrets, constraints, and verified content
# Enables knowledge_scope filtering and constraint enforcement

# GAME_STATE moved to engine_core (Wave 0 slice 4); imported (by-reference) at the top.
# === GAME_STATE PERSISTENCE ===
GAME_STATE_FILE = CAMPAIGN_DIR / "game_state.json"

def _save_game_state():
    """Persist GAME_STATE to disk. Called after state-modifying operations."""
    try:
        # Convert combat state for JSON serialization
        combat_to_save = None
        if GAME_STATE.get("active_combat"):
            combat = GAME_STATE["active_combat"]
            combat_to_save = {
                **combat,
                "log": combat["log"][-15:],  # Keep last 15 entries only
            }

        state_to_save = {
            "active_location_name": GAME_STATE["active_location_name"],
            "active_prep_file": GAME_STATE["active_prep_file"],
            "revealed_rooms": list(GAME_STATE["revealed_rooms"]),
            "revealed_secrets": list(GAME_STATE["revealed_secrets"]),
            "active_constraints": GAME_STATE["active_constraints"],
            "session_started": GAME_STATE["session_started"],
            "active_combat": combat_to_save,
            "world_tick": GAME_STATE.get("world_tick", {}),
            "saved_at": datetime.now().isoformat(),
        }
        # Atomic write: write to temp file, then rename
        tmp_path = GAME_STATE_FILE.with_suffix('.tmp')
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(state_to_save, f, indent=2)
        tmp_path.replace(GAME_STATE_FILE)
    except Exception as e:
        logging.warning(f"Failed to save game state: {e}")

def _load_game_state():
    """Load GAME_STATE from disk on startup. Returns True if state was loaded."""
    global GAME_STATE
    if not GAME_STATE_FILE.exists():
        return False
    try:
        with open(GAME_STATE_FILE, 'r', encoding='utf-8') as f:
            saved = json.load(f)
        
        # Restore state
        GAME_STATE["active_location_name"] = saved.get("active_location_name")
        GAME_STATE["active_prep_file"] = saved.get("active_prep_file")
        GAME_STATE["revealed_rooms"] = set(saved.get("revealed_rooms", []))
        GAME_STATE["revealed_secrets"] = set(saved.get("revealed_secrets", []))
        GAME_STATE["active_constraints"] = saved.get("active_constraints", {})
        GAME_STATE["session_started"] = saved.get("session_started", False)
        GAME_STATE["active_combat"] = saved.get("active_combat")
        GAME_STATE["world_tick"] = saved.get("world_tick", {})

        # Reload the location data from prep file if we have one
        if GAME_STATE["active_prep_file"]:
            prep_path = CAMPAIGN_DIR / GAME_STATE["active_prep_file"]
            if prep_path.exists():
                data, error = _load_prep_file(GAME_STATE["active_prep_file"])
                if not error:
                    GAME_STATE["active_location"] = data
        
        return True
    except Exception as e:
        logging.warning(f"Failed to load game state: {e}")
        return False

# _clear_game_state() removed 2026-06-07 (was dead code, 0 callers). Its former
# caller location_init was retired in tool consolidation. No replacement is needed:
# active_combat self-clears at combat-end, and active_constraints is managed live by
# the constraint tool. NOTE (C28, 2026-07-02; amended 2026-07-24): active_prep_file
# IS now set at the prep-change write points — update_active_prep and
# _update_current_status_prep call _persist_active_prep_file, which resolves the
# incoming reference to a real filename and saves it (handoff PREP_INJECTION_DEAD:
# resolution must not depend on parsing the human-formatted **Active Prep:** display
# line). active_location_name is still not written (its setter died with the
# location-tool retirement, c1f3744). A blanket "wipe game_state.json" on prep-switch
# remains FORBIDDEN — it would nuke live combat and active_constraints mid-scene.


def _update_current_status_prep(prep_file: str, scene_type: str = "vault_exploration"):
    """Update CURRENT_STATUS.md with the active prep file and scene type.

    This ensures check_canon() sees the correct prep file context.
    Called by location_init() and vault(action='init').
    """
    status_path = CAMPAIGN_DIR / "CURRENT_STATUS.md"
    if not status_path.exists():
        logging.warning("CURRENT_STATUS.md not found - cannot sync prep file")
        return False

    try:
        content = status_path.read_text(encoding='utf-8')

        # Update Active Prep line
        content = re.sub(
            r'\*\*Active Prep:\*\*\s*.+',
            f'**Active Prep:** {prep_file}',
            content
        )

        # Update Scene Type line
        content = re.sub(
            r'\*\*Scene Type:\*\*\s*.+',
            f'**Scene Type:** {scene_type}',
            content
        )

        # Update Last Updated timestamp
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        content = re.sub(
            r'\*\*Last Updated:\*\*\s*.+',
            f'**Last Updated:** {timestamp}',
            content
        )

        # Atomic write
        tmp_path = status_path.with_suffix('.tmp')
        tmp_path.write_text(content, encoding='utf-8')
        tmp_path.replace(status_path)

        # Persist the exact resolved filename in game state so prep resolution
        # never has to fall back to parsing the display line (handoff fix #2).
        _persist_active_prep_file(prep_file)

        logging.info(f"CURRENT_STATUS.md synced: Active Prep={prep_file}, Scene Type={scene_type}")
        return True
    except Exception as e:
        logging.warning(f"Failed to update CURRENT_STATUS.md: {e}")
        return False


def _update_current_status_active_map(map_name: str) -> bool:
    """Update the **Active Map:** field in CURRENT_STATUS.md.

    Called when a vault map is auto-initialized so subsequent turns inject its
    live state. Pass "None" to clear. Returns False if the field is absent
    (we do not fabricate the template) or on error.
    """
    status_path = CAMPAIGN_DIR / "CURRENT_STATUS.md"
    if not status_path.exists():
        logging.warning("CURRENT_STATUS.md not found - cannot sync Active Map")
        return False
    try:
        content = status_path.read_text(encoding='utf-8')
        if not re.search(r'\*\*Active Map:\*\*\s*.+', content):
            logging.warning("Active Map field not found in CURRENT_STATUS.md - skipping write")
            return False
        content = re.sub(r'\*\*Active Map:\*\*\s*.+', lambda _: f'**Active Map:** {map_name}', content)
        tmp_path = status_path.with_suffix('.tmp')
        tmp_path.write_text(content, encoding='utf-8')
        tmp_path.replace(status_path)
        return True
    except Exception as e:
        logging.warning(f"Failed to update Active Map: {e}")
        return False


def _emit_player_view(active_map: str = None) -> None:
    """Refresh the spoiler-safe player view artifacts. NEVER raises into play.

    When no active_map is passed (the bare call sites: advance_day, rest,
    combat, save/session tools), fall back to the **Active Map:** field in
    CURRENT_STATUS.md so player_map.txt refreshes too — before 2026-07-19 only
    map() actions re-rendered the map, so it went stale across every other
    action and could show the previous site after travel."""
    try:
        import player_view as _pv
        if not active_map:
            try:
                _status = (CAMPAIGN_DIR / "CURRENT_STATUS.md").read_text(encoding='utf-8')
                _m = re.search(r'\*\*Active Map:\*\*\s*(.+)', _status)
                if _m:
                    _candidate = _m.group(1).strip()
                    if _candidate and _candidate.lower() != 'none':
                        active_map = _candidate
            except Exception:
                pass
        fog = None
        if active_map:
            try:
                fog = map_system.render_fog(active_map)
            except Exception:
                fog = None
        _pv.write_player_view(CAMPAIGN_DIR, fog_map_text=fog)
    except Exception as _e:
        logging.warning(f"player_view emit failed (non-fatal): {_e}")


def _derive_map_name(prep_file: str) -> str:
    """Derive a map_name from a prep filename: strip dir + _PREP/.md, lowercase.

    'CERULINE_ARCOLOGY_PREP.md' -> 'ceruline_arcology'; 'V_PREP.md' -> 'v'.

    Assumes the campaign's uniform *_PREP.md naming; two preps differing only by
    the _PREP suffix would collide (guarded in practice by file-existence checks).
    """
    base = Path(prep_file).name
    base = re.sub(r'\.md$', '', base, flags=re.IGNORECASE)
    base = re.sub(r'_PREP$', '', base, flags=re.IGNORECASE)
    return base.lower()


_EXPLORATION_SCENE_TYPES = {"vault_exploration", "social_site"}   # turn-ticking scene type(s); see scene_type_weights.json. social_site tracks position (spatial injection + site-stamp) but the encounter die reads TEXTURE, not the combat trail (map_system._auto_encounter_check).


def _is_exploration_scene(scene_type):
    """True iff scene_type's LEADING TOKEN is an exploration scene (turns tick).

    Exact-token match, NOT substring -- so a free-text annotation like
    'social (post-exploration debrief)' does NOT count as exploration."""
    s = str(scene_type or "").strip().lower()
    if not s:
        return False
    return s.split()[0] in _EXPLORATION_SCENE_TYPES


def _inject_spatial_state(status_parsed: dict) -> "str | None":
    """Scene-type-driven spatial injection for check_canon. Fail-open (never raises).

    vault_exploration: if Active Map set -> inject live state; else if a map state
      already exists for the derived name -> adopt it (write field) + inject; else
      auto-init from Active Prep (only if it has ## ROOM: markers) -> write field +
      inject. No ROOM markers / prep missing -> return None (prose fallback, no write).
    settlement: inject ONLY if Active Map already set; never auto-init.
    travel/hexpedition: inject raw position-relative overworld from party location.
    """
    try:
        scene = (status_parsed.get('scene_type') or '').strip().lower()
        active_map = (status_parsed.get('active_map') or 'None').strip()
        active_prep = (status_parsed.get('active_prep') or 'None').strip()
        has_map = bool(active_map) and active_map.lower() != 'none'

        if scene == 'vault_exploration':
            if has_map:
                return map_system.spatial_summary(active_map)
            if not active_prep or active_prep.lower() == 'none':
                return None
            map_name = _derive_map_name(active_prep)
            if map_system.get_map_state(map_name) is not None:
                _update_current_status_active_map(map_name)
                return map_system.spatial_summary(map_name)
            result = map_system.init_map_from_prep(map_name, active_prep, "vault")
            if isinstance(result, str) and result.startswith("✅"):
                _update_current_status_active_map(map_name)
                return map_system.spatial_summary(map_name)
            return None

        if scene == 'settlement':
            return map_system.spatial_summary(active_map) if has_map else None

        if scene in ('travel', 'hexpedition'):
            party = geography_system.get_party_location()
            if not party:
                return None
            ctx = geography_system.position_context(party)
            return ctx or None

        # Active-site fallback (site engine): only while actually IN an exploration
        # scene (same gate _stamp_active_site_left uses), so a stale Active Map left
        # set after leaving doesn't spam unrelated social/downtime turns.
        if has_map and _is_exploration_scene(scene):
            return map_system.spatial_summary(active_map)

        return None
    except Exception as e:
        logging.debug(f"Spatial-state injection skipped: {e}")
        return None


def _stamp_active_site_left(active_site, day):
    """Stamp last_seen_day on the active site when the party leaves (advance_day).
    last_seen_day is the day the party LEFT; it is engine-known, so we auto-stamp
    (no door-gate, unlike NPC continuity). No-op if no active site / state missing."""
    if not active_site:
        return
    try:
        state = map_system.get_map_state(active_site)
        if state is None:
            return
        state["last_seen_day"] = day
        state["last_left_turn"] = state.get("current_turn", 0)
        map_system.save_map_state(active_site, state)
    except Exception as exc:
        logging.warning(f"_stamp_active_site_left failed for {active_site}: {exc}")


# _atomic_json_write moved to engine_core (Wave 0); imported at the top.


# NOTE: _load_game_state() called after _load_prep_file is defined (see below)



# Pending save state for confirmation workflow
# Structure: {"token": str, "changes": dict, "params": dict, "timestamp": datetime}
# PENDING_SAVE moved to session_tools.py (Wave 8 slice 3): owned with prepare/confirm_save.


# ============================================
# SAVE-STATE INPUT SANITIZATION & AUDIT
# ============================================
# Defends against caller-side pollution (LLM agent embedding XML tool-call
# envelope tags into parameter VALUES rather than just wrapping at protocol layer).
# Pre-fix symptom: <parameter name="...">value</parameter> and matching closing
# tags (</tension_mood>, </arc_summary>, etc.) appeared verbatim in CURRENT_STATUS.md.

# Compiled once at import for performance
_PARAM_ENVELOPE_RE = re.compile(
    r'<parameter\s+name=["\'][^"\']*["\']\s*>(.*?)</parameter>',
    re.DOTALL | re.IGNORECASE,
)
# Closing tags only — when an LLM emits <foo>val</foo> as a tool-call wrapper
# the opening tag may be stripped at protocol level but the closing tag survives
# inside the value string. Strip stray closing tags whose names match common
# save_state parameters.
_STRAY_CLOSING_TAG_RE = re.compile(
    r'</(?:parameter|session_summary|narrative_log|scene_location|characters_present|'
    r'last_speaker|last_beat|tension_mood|next_expected|current_arc|arc_summary|'
    r'arc_tension|party_location|emotional_states|day|npc_changes|inventory_changes|'
    r'new_canon)>',
    re.IGNORECASE,
)
# Matching opening tags too, in case both leak.
_STRAY_OPENING_TAG_RE = re.compile(
    r'<(?:session_summary|narrative_log|scene_location|characters_present|'
    r'last_speaker|last_beat|tension_mood|next_expected|current_arc|arc_summary|'
    r'arc_tension|party_location|emotional_states|day|npc_changes|inventory_changes|'
    r'new_canon)>',
    re.IGNORECASE,
)

def _sanitize_param(raw):
    """Strip MCP tool-call envelope XML from parameter values.

    Handles three pollution patterns observed in the wild:
    1. Full envelope: <parameter name="x">VALUE</parameter> -> VALUE
    2. Stray closing tags: text...</tension_mood> -> text...
    3. Stray opening tags: <tension_mood>text -> text

    Pass-through for non-string values (None, int, dict, list).
    Idempotent — safe to call repeatedly.
    """
    if not isinstance(raw, str):
        return raw
    # Pull value out of full envelope first (preserves inner content)
    raw = _PARAM_ENVELOPE_RE.sub(r'\1', raw)
    # Strip any stray closing tags
    raw = _STRAY_CLOSING_TAG_RE.sub('', raw)
    # Strip any stray opening tags
    raw = _STRAY_OPENING_TAG_RE.sub('', raw)
    return raw.strip()


def _sanitize_emotional_states(raw):
    """Coerce emotional_states to a clean dict.

    Accepts dict (passed through with each value sanitized), JSON string
    (parsed then sanitized), or polluted-XML string (sanitized then JSON-parsed
    if possible, else logged-and-emptied).
    """
    if raw is None:
        return None
    if isinstance(raw, dict):
        return {str(k): _sanitize_param(v) for k, v in raw.items()}
    if isinstance(raw, str):
        cleaned = _sanitize_param(raw)
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return {str(k): _sanitize_param(v) for k, v in parsed.items()}
        except (json.JSONDecodeError, ValueError):
            pass
        # Fallback: log and return empty dict rather than write garbage
        try:
            _audit_log(f"WARN: emotional_states arrived as unparseable string after sanitize: {cleaned[:200]!r}")
        except Exception as e:
            logging.debug(f"Audit log write failed for emotional_states: {e}")
        return {}
    return None


def _audit_log(msg):
    """Append a timestamped line to the daily save-state audit log.

    Phase 1 instrumentation. Logs land in the engine repo's logs/ directory
    (save_state_audit_YYYY-MM-DD.log). Failures swallowed silently (audit must
    never break the save itself).
    """
    try:
        from datetime import datetime as _dt
        log_dir = Path(__file__).parent / "logs"
        log_dir.mkdir(exist_ok=True)
        log_path = log_dir / f"save_state_audit_{_dt.now().strftime('%Y-%m-%d')}.log"
        line = f"[{_dt.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n"
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(line)
    except Exception as e:
        logging.debug(f"Audit log write failed (non-blocking): {e}")


def _resolve_meta_day():
    """Read campaign day from CURRENT_STATUS.md header. Returns int or None.

    Used by prepare_save_state to cross-check the caller-supplied day against
    the meta. If the caller passes a day far below meta, that's the Day 121
    regression signature — block it.
    """
    try:
        status_path = CAMPAIGN_DIR / "CURRENT_STATUS.md"
        if not status_path.exists():
            return None
        text = status_path.read_text(encoding='utf-8')
        m = re.search(r'#\s*CURRENT STATUS\s*-\s*DAY\s*(\d+)', text, re.IGNORECASE)
        if m:
            return int(m.group(1))
    except Exception as e:
        logging.debug(f"Campaign day extraction failed: {e}")
    return None

# Knowledge scope constants
KNOWLEDGE_SCOPE = {
    "party_known": "party_known",  # Safe to inject during narration
    "dm_only": "dm_only",  # Only visible in prep mode
    "character_specific": "character_specific",  # Only for specific character POV
    "npc_secret": "npc_secret",  # Only when NPC reveals it
}


# Relationship inverse mapping - used to reconstruct bidirectional relationships
# Defined at module level to avoid recreating on every check_canon call
RELATIONSHIP_INVERSE_TYPE = {
    'HUSBAND': 'WIFE', 'WIFE': 'HUSBAND',
    'FATHER': 'DAUGHTER', 'DAUGHTER': 'FATHER',
    'MOTHER': 'DAUGHTER', 'BROTHER': 'SISTER',
    'SISTER': 'BROTHER', 'UNCLE': 'NEPHEW',
    'NEPHEW': 'UNCLE', 'PARTNER': 'PARTNER',
    'FAMILY': 'FAMILY', 'CHILDHOOD_FRIEND': 'CHILDHOOD_FRIEND',
    'ITERATION': 'ITERATION', 'SON': 'MUM', 'MUM': 'SON',
    'BETRAYED': 'BETRAYED_BY', 'BETRAYED_BY': 'BETRAYED',
    'SON_IN_LAW': 'FATHER_IN_LAW', 'FATHER_IN_LAW': 'SON_IN_LAW',
    'MANIPULATED': 'MANIPULATOR', 'MANIPULATOR': 'MANIPULATED',
}


def _load_prep_file(prep_file_path: str) -> tuple[dict, str]:
    """
    Parse a prep file into structured data.
    Returns (data_dict, error_message). Error is None on success.
    """
    prep_path = CAMPAIGN_DIR / prep_file_path
    if not prep_path.exists():
        return None, f"Prep file not found: {prep_file_path}"

    try:
        content = prep_path.read_text(encoding='utf-8')
    except Exception as e:
        return None, f"Error reading prep file: {e}"

    data = {
        "raw_content": content,
        "secrets": {},
        "constraints": {},
        "rooms": {},
        "npcs": {},
        "metadata": {}
    }

    # Parse header metadata
    header_match = re.search(r'\*\*Type:\*\*\s*(.+)', content)
    if header_match:
        data["metadata"]["type"] = header_match.group(1).strip()

    # Parse secrets
    secret_pattern = r'### SECRET:\s*(\w+)\s*\n(.*?)(?=### SECRET:|### CONSTRAINT:|### ROOM:|## [A-Z]|\Z)'
    for match in re.finditer(secret_pattern, content, re.DOTALL):
        secret_id = match.group(1)
        secret_content = match.group(2)

        secret_data = {"id": secret_id, "raw": secret_content}

        # Extract fields
        scope_match = re.search(r'\*\*Scope:\*\*\s*(\w+)', secret_content)
        if scope_match:
            secret_data["scope"] = scope_match.group(1)
        else:
            secret_data["scope"] = "dm_only"  # Default

        truth_match = re.search(r'\*\*Truth:\*\*\s*(.+?)(?=\*\*|\n\n|\Z)', secret_content, re.DOTALL)
        if truth_match:
            secret_data["truth"] = truth_match.group(1).strip()

        reveal_match = re.search(r'\*\*Reveal Condition:\*\*\s*(.+?)(?=\*\*|\n\n|\Z)', secret_content, re.DOTALL)
        if reveal_match:
            secret_data["reveal_condition"] = reveal_match.group(1).strip()

        data["secrets"][secret_id] = secret_data

    # Parse constraints
    constraint_pattern = r'### CONSTRAINT:\s*(\w+)\s*\n(.*?)(?=### CONSTRAINT:|### SECRET:|### ROOM:|## [A-Z]|\Z)'
    for match in re.finditer(constraint_pattern, content, re.DOTALL):
        constraint_id = match.group(1)
        constraint_content = match.group(2)

        constraint_data = {"id": constraint_id, "raw": constraint_content}

        subject_match = re.search(r'\*\*Subject:\*\*\s*(.+)', constraint_content)
        if subject_match:
            constraint_data["subject"] = subject_match.group(1).strip()

        limitation_match = re.search(r'\*\*Limitation:\*\*\s*(.+)', constraint_content)
        if limitation_match:
            constraint_data["limitation"] = limitation_match.group(1).strip()

        scope_match = re.search(r'\*\*Scope:\*\*\s*(\w+)', constraint_content)
        if scope_match:
            constraint_data["scope"] = scope_match.group(1)
        else:
            constraint_data["scope"] = "party_known"

        data["constraints"][constraint_id] = constraint_data

    # Parse encounters section
    encounters_section = re.search(r'## ENCOUNTERS\s*\n(.*?)(?=\n## [A-Z]|\Z)', content, re.DOTALL)
    if encounters_section:
        encounters_content = encounters_section.group(1)

        # Initialize encounters structure
        data["encounters"] = {
            "type": None,
            "turn_triggers": [],
            "table_entries": [],
            "raw": encounters_content
        }

        # Detect format: turn-based vs random table
        if re.search(r'- \*\*Turn \d+:', encounters_content):
            # Turn-based format (vaults)
            data["encounters"]["type"] = "turn_based"

            # Parse turn triggers: - **Turn 3:** Description
            turn_pattern = r'- \*\*Turn (\d+):\*\* (.+?)(?=\n- \*\*Turn|\n\n|\Z)'
            for match in re.finditer(turn_pattern, encounters_content, re.DOTALL):
                turn_num = int(match.group(1))
                description = match.group(2).strip()
                data["encounters"]["turn_triggers"].append({
                    "turn": turn_num,
                    "description": description
                })

        elif re.search(r'\|\s*d\d+\s*\|', encounters_content) or re.search(r'\|\s*\d+\s*\|', encounters_content):
            # Random table format (overworld/arcologies)
            data["encounters"]["type"] = "random_table"

            # Detect dice size from table header first (look for | d12 | pattern specifically)
            header_dice_match = re.search(r'\|\s*d(\d+)\s*\|', encounters_content)
            if header_dice_match:
                data["encounters"]["dice_size"] = int(header_dice_match.group(1))
            else:
                # Fallback to any d notation
                dice_match = re.search(r'd(\d+)', encounters_content)
                if dice_match:
                    data["encounters"]["dice_size"] = int(dice_match.group(1))

            # Parse markdown table entries (data rows only, skip header)
            # Format: | 1 | Encounter | Context |
            # Skip rows that contain "d12" or separator lines (-----)
            table_pattern = r'\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|'
            for match in re.finditer(table_pattern, encounters_content):
                roll_value_str = match.group(1)
                # Skip if this looks like a dice notation (starts with d) or separator
                if roll_value_str.strip().startswith('d') or '-' in roll_value_str:
                    continue

                roll_value = int(roll_value_str)
                encounter_text = match.group(2).strip()
                context = match.group(3).strip()

                # Skip header row patterns
                if encounter_text.lower() in ['encounter', 'description', 'context']:
                    continue

                data["encounters"]["table_entries"].append({
                    "roll": roll_value,
                    "encounter": encounter_text,
                    "context": context
                })

            # Infer dice size from max roll if not detected from header
            if not data["encounters"].get("dice_size") and data["encounters"]["table_entries"]:
                max_roll = max(entry["roll"] for entry in data["encounters"]["table_entries"])
                data["encounters"]["dice_size"] = max_roll

                # Warn if table looks incomplete
                num_entries = len(data["encounters"]["table_entries"])
                if num_entries < max_roll:
                    logging.warning(
                        f"Prep file '{prep_file_path}': Inferred dice_size=d{max_roll} but only "
                        f"{num_entries} entries parsed. Expected {max_roll} entries. "
                        f"Check encounter table formatting for missing entries."
                    )

        # Parse encounter frequency if specified
        freq_match = re.search(r'Roll d6 every (\d+) (turn|day|exploration turn)', encounters_content, re.IGNORECASE)
        if freq_match:
            data["encounters"]["frequency"] = {
                "interval": int(freq_match.group(1)),
                "unit": freq_match.group(2)
            }

        # Validate parsed encounters
        if data["encounters"]["type"] == "random_table":
            if not data["encounters"].get("table_entries"):
                logging.error(
                    f"Prep file '{prep_file_path}' has ENCOUNTERS table header but 0 entries parsed. "
                    f"Check markdown table formatting: | roll | encounter | context |"
                )
                # Mark as invalid
                data["encounters"] = None

    # Parse rooms
    room_pattern = r'##\s*ROOM:\s*(\w+)\s*\n(.*?)(?=##\s*ROOM:|##\s*[A-Z]|\Z)'
    for match in re.finditer(room_pattern, content, re.DOTALL):
        room_id = match.group(1)
        room_content = match.group(2)

        room_data = {"id": room_id, "raw": room_content}

        name_match = re.search(r'\*\*Name:\*\*\s*(.+)', room_content)
        if name_match:
            room_data["name"] = name_match.group(1).strip()

        floor_match = re.search(r'\*\*Floor:\*\*\s*(\d+)', room_content)
        if floor_match:
            room_data["floor"] = int(floor_match.group(1))

        connections_match = re.search(r'\*\*Connections:\*\*\s*(.+)', room_content)
        if connections_match:
            room_data["connections"] = connections_match.group(1).strip()

        # Check for obstacles
        obstacles = []
        obstacle_pattern = r'\*\*(\w+):\*\*\s*(.+?)(?=\*\*Planned Solution:\*\*)'
        planned_pattern = r'\*\*Planned Solution:\*\*\s*(.+?)(?=\*\*Alternative|\*\*Failure|\n\n|\Z)'
        alt_pattern = r'\*\*Alternative Solutions:\*\*\s*(.+?)(?=\*\*Failure|\n\n|\Z)'

        obs_section = re.search(r'\*\*Obstacles:\*\*(.*?)(?=\*\*Hazards:|\*\*Loot:|\*\*Secrets Present:|\n\n---|\Z)', room_content, re.DOTALL)
        if obs_section:
            obs_text = obs_section.group(1)
            # Simple obstacle extraction
            for line in obs_text.split('\n'):
                if line.strip().startswith('- **'):
                    obstacles.append(line.strip())
            room_data["obstacles"] = obstacles

        # Check for secrets present
        secrets_match = re.search(r'\*\*Secrets Present:\*\*\s*(.*?)(?=\n\n---|\n---|\Z)', room_content, re.DOTALL)
        if secrets_match:
            room_data["secrets_present"] = secrets_match.group(1).strip()

        data["rooms"][room_id] = room_data

    # Log parse summary for debugging - helps catch formatting issues
    room_count = len(data.get("rooms", {}))
    secret_count = len(data.get("secrets", {}))
    constraint_count = len(data.get("constraints", {}))

    if room_count == 0:
        logging.warning(f"Prep file '{prep_file_path}' has 0 rooms - check '## ROOM:' formatting")
    if secret_count == 0 and "### SECRET:" in content.upper():
        logging.info(f"Prep file '{prep_file_path}' mentions SECRET but none parsed - check '### SECRET:' format (case-sensitive)")

    return data, None


# Load game state now that _load_prep_file is defined
_load_game_state()



def _extract_dm_only_secrets(prep_content: str) -> list[str]:
    """
    Extract dm_only secrets from prep file content for spoiler enforcement.
    Returns a list of secret summaries that Claude should NOT reveal.

    Looks for multiple patterns:
    - ⛔ DM ONLY ⛔ ... ⛔ END DM ONLY ⛔ blocks
    - ## MODULE OVERVIEW (GM KNOWLEDGE ONLY) sections
    - ### SECRET: blocks with dm_only scope
    - ### The Twist: sections
    - ## DM KNOWLEDGE sections
    """
    secrets = []

    # Pattern 1: ⛔ DM ONLY ⛔ blocks (modern format)
    dm_only_pattern = r'⛔\s*DM ONLY.*?⛔(.*?)⛔\s*END DM ONLY\s*⛔'
    for match in re.finditer(dm_only_pattern, prep_content, re.DOTALL | re.IGNORECASE):
        block = match.group(1).strip()
        # Extract key points from block (first 3-4 lines or bullet points)
        lines = [l.strip() for l in block.split('\n') if l.strip() and not l.strip().startswith('#')]
        for line in lines[:5]:  # Limit to 5 key items
            if line.startswith('-') or line.startswith('*'):
                secrets.append(line[1:].strip())
            elif len(line) > 10 and len(line) < 200:  # Reasonable length sentences
                secrets.append(line)

    # Pattern 2: GM KNOWLEDGE ONLY sections (older format)
    gm_knowledge_pattern = r'##\s*(?:MODULE OVERVIEW|OVERVIEW)\s*\(GM KNOWLEDGE ONLY\)(.*?)(?=\n---|\n## [A-Z]|\Z)'
    for match in re.finditer(gm_knowledge_pattern, prep_content, re.DOTALL | re.IGNORECASE):
        block = match.group(1).strip()
        # Look for "The Twist" or key revelation paragraphs
        twist_match = re.search(r'###\s*The Twist[:\s]*(.*?)(?=\n###|\n##|\Z)', block, re.DOTALL)
        if twist_match:
            twist = twist_match.group(1).strip()
            # Take first sentence or two
            first_sentences = twist.split('. ')[:2]
            secrets.append('. '.join(first_sentences).strip())

        # Look for "True Purpose" or similar
        purpose_match = re.search(r'true purpose[:\s]*(.*?)(?=\.|$)', block, re.IGNORECASE)
        if purpose_match:
            secrets.append(f"True purpose: {purpose_match.group(1).strip()}")

    # Pattern 3: ### SECRET: blocks
    secret_pattern = r'###\s*SECRET:\s*(\w+)\s*\n(.*?)(?=###\s*SECRET:|###\s*CONSTRAINT:|##\s+[A-Z]|\Z)'
    for match in re.finditer(secret_pattern, prep_content, re.DOTALL):
        secret_id = match.group(1)
        secret_content = match.group(2)

        # Check if dm_only scope
        scope_match = re.search(r'\*\*Scope:\*\*\s*(\w+)', secret_content)
        scope = scope_match.group(1) if scope_match else "dm_only"

        if scope.lower() == "dm_only":
            truth_match = re.search(r'\*\*Truth:\*\*\s*(.+?)(?=\*\*|\n\n|\Z)', secret_content, re.DOTALL)
            if truth_match:
                truth = truth_match.group(1).strip()
                secrets.append(f"{secret_id}: {truth}")

    # Pattern 4: DM KNOWLEDGE section in CURRENT_STATUS-style files
    dm_knowledge_pattern = r'##\s*DM KNOWLEDGE.*?\n\n(.*?)(?=\n---|\n## |\Z)'
    for match in re.finditer(dm_knowledge_pattern, prep_content, re.DOTALL):
        block = match.group(1).strip()
        # Extract bullet points
        for line in block.split('\n'):
            line = line.strip()
            if line.startswith('-') and len(line) > 5:
                secrets.append(line[1:].strip())

    # Deduplicate and clean up
    seen = set()
    unique_secrets = []
    for s in secrets:
        s_clean = s.strip()
        if s_clean and s_clean.lower() not in seen and len(s_clean) > 5:
            seen.add(s_clean.lower())
            unique_secrets.append(s_clean)

    return unique_secrets[:10]  # Limit to 10 most important secrets






def _filter_dm_only_content(content: str, preserve_structure: bool = True) -> str:
    """Remove DM-only content while preserving structure.

    Strips content meant only for the dungeon master's eyes, including:
    - ⛔ DM ONLY ⛔ ... ⛔ END DM ONLY ⛔ blocks
    - ### SECRET: sections with **Scope:** dm_only
    - **State (dm_only):** subsections in NPC profiles
    - Lines containing (dm_only) or [dm_only] markers

    Args:
        content: Raw section content from prep file
        preserve_structure: If True, add [DM content removed] placeholders
                          where content was stripped

    Returns:
        Filtered content safe for player view
    """
    filtered = content

    # Pattern 1: ⛔ DM ONLY ⛔ ... ⛔ END DM ONLY ⛔ blocks
    # These are explicit referee-only sections (monster stats, twists, etc.)
    dm_block_pattern = r'⛔\s*DM ONLY\s*⛔.*?⛔\s*END DM ONLY\s*⛔'
    if preserve_structure:
        # Replace with placeholder to maintain document flow
        filtered = re.sub(dm_block_pattern, '[DM content removed]', filtered, flags=re.DOTALL)
    else:
        # Remove entirely
        filtered = re.sub(dm_block_pattern, '', filtered, flags=re.DOTALL)

    # Pattern 2: ### SECRET: sections with **Scope:** dm_only
    # These are hidden plot elements the party hasn't discovered yet
    # Match secret headers with IDs containing word chars, hyphens, underscores
    secret_pattern = r'###\s*SECRET:\s*[\w\-_]+\s*\n(.*?)(?=###\s*(?:SECRET:|CONSTRAINT:)|##\s+[A-Z]|\Z)'

    def filter_secret(match):
        secret_content = match.group(1)
        # Check if this secret is dm_only scope
        scope_match = re.search(r'\*\*Scope:\*\*\s*(\w+)', secret_content)
        if scope_match and scope_match.group(1).lower() == "dm_only":
            # This secret is DM-only, filter it
            return '[Secret content removed]' if preserve_structure else ''
        else:
            # Keep party_known secrets
            return match.group(0)

    filtered = re.sub(secret_pattern, filter_secret, filtered, flags=re.DOTALL)

    # Pattern 3: **State (dm_only):** subsections in NPC profiles
    # These track NPC knowledge/motivations the party doesn't know about
    dm_state_pattern = r'\*\*State \(dm_only\):\*\*.*?(?=\n\*\*|\n\n|\Z)'
    if preserve_structure:
        filtered = re.sub(dm_state_pattern, '[DM state removed]', filtered, flags=re.DOTALL)
    else:
        filtered = re.sub(dm_state_pattern, '', filtered, flags=re.DOTALL)

    # Pattern 4: Lines with (dm_only) or [dm_only] markers
    # These are inline notes the DM shouldn't narrate aloud
    lines = filtered.split('\n')
    filtered_lines = []
    for line in lines:
        # Check for inline dm_only markers (case-insensitive, with optional content after)
        if re.search(r'\(dm_only[:\)]', line, re.IGNORECASE) or re.search(r'\[dm_only[\]:]', line, re.IGNORECASE):
            if preserve_structure:
                # Preserve leading whitespace
                leading_space = len(line) - len(line.lstrip())
                filtered_lines.append(' ' * leading_space + '[DM note removed]')
            # Otherwise skip line entirely
        else:
            filtered_lines.append(line)

    filtered = '\n'.join(filtered_lines)

    # Clean up excessive whitespace left by removals
    # Replace 3+ blank lines with just 2 blank lines
    filtered = re.sub(r'\n{3,}', '\n\n', filtered)

    # Remove trailing whitespace from each line
    filtered = '\n'.join(line.rstrip() for line in filtered.split('\n'))

    return filtered.strip()


def _extract_prep_constraints(prep_content: str) -> list[dict]:
    """C31 — parse '### CONSTRAINT:' blocks from a prep file into dicts
    {id, subject, limitation, scope}. Mirrors the parse in _load_prep_file so the
    already-authored prep constraint channel can surface in check_canon; before this,
    the parsed data['constraints'] was read only by a debug line-counter."""
    constraints = []
    pattern = (r'###\s*CONSTRAINT:\s*(\w+)\s*\n(.*?)'
               r'(?=###\s*CONSTRAINT:|###\s*SECRET:|###\s*ROOM:|##\s+[A-Z]|\Z)')
    for m in re.finditer(pattern, prep_content, re.DOTALL):
        cid = m.group(1)
        body = m.group(2)
        subj = re.search(r'\*\*Subject:\*\*\s*(.+)', body)
        lim = re.search(r'\*\*Limitation:\*\*\s*(.+)', body)
        scope = re.search(r'\*\*Scope:\*\*\s*(\w+)', body)
        constraints.append({
            "id": cid,
            "subject": subj.group(1).strip() if subj else cid,
            "limitation": lim.group(1).strip() if lim else body.strip()[:120],
            "scope": scope.group(1) if scope else "party_known",
        })
    return constraints


def _extract_progress_log(prep_content: str) -> list[dict]:
    """
    Extract PROGRESS LOG entries from prep file.
    Returns list of {day: int, summary: str} dicts.
    """
    progress = []

    # Look for ## PROGRESS LOG section
    progress_section = re.search(r'##\s*PROGRESS LOG\s*\n(.*?)(?=\n## |\Z)', prep_content, re.DOTALL)
    if not progress_section:
        return []

    log_content = progress_section.group(1)

    # Parse entries like "### Day 91 — First Visit"
    entry_pattern = r'###\s*Day\s*(\d+)\s*[—–-]\s*(.+?)\n(.*?)(?=###\s*Day|\Z)'
    for match in re.finditer(entry_pattern, log_content, re.DOTALL):
        day = int(match.group(1))
        title = match.group(2).strip()
        content = match.group(3).strip()

        # Extract key details
        entry = {
            "day": day,
            "title": title,
            "summary": "",
            "items_taken": [],
            "secrets_revealed": [],
            "npcs_met": []
        }

        for line in content.split('\n'):
            line = line.strip()
            if line.startswith('- Took:') or line.startswith('- Items taken:'):
                items = line.split(':', 1)[1].strip()
                entry["items_taken"] = [i.strip() for i in items.split(',')]
            elif line.startswith('- Discovered:') or line.startswith('- Secrets revealed:'):
                secrets = line.split(':', 1)[1].strip()
                entry["secrets_revealed"] = [s.strip() for s in secrets.split(',') if s.strip()]
            elif line.startswith('- Spoke with:') or line.startswith('- NPCs met:'):
                npcs = line.split(':', 1)[1].strip()
                entry["npcs_met"] = [n.strip() for n in npcs.split(',')]
            elif line.startswith('- ') and not entry["summary"]:
                entry["summary"] = line[2:].strip()

        progress.append(entry)

    return progress


def _get_section_by_header(lines: list[str], header_pattern: str, max_chars: int = 2000) -> str | None:
    """
    Extract a markdown section matching header_pattern (regex) from lines.
    Returns text from the matched header through the next same-or-higher-level header,
    capped at max_chars. Returns None if no match.
    """
    for i, line in enumerate(lines):
        stripped = line.strip()
        if re.match(header_pattern, stripped, re.IGNORECASE):
            level_match = re.match(r'^(#+)', stripped)
            if not level_match:
                continue
            level = len(level_match.group(1))
            end = len(lines)
            for j in range(i + 1, len(lines)):
                next_match = re.match(r'^(#+)\s', lines[j].strip())
                if next_match and len(next_match.group(1)) <= level:
                    end = j
                    break
            text = '\n'.join(lines[i:end]).strip()
            if len(text) > max_chars:
                text = text[:max_chars].rsplit('\n', 1)[0] + "\n..."
            return text
    return None


def _extract_prep_sections(
    prep_content: str,
    location: str,
    present_npcs: list[str],
    scene_type: str,
) -> tuple[list[str], list[str]]:
    """
    Extract targeted prep file sections based on scene context.

    Returns (sections, manifest) where:
      - sections: list of markdown text blocks to inject
      - manifest: list of short labels describing what was loaded
    """
    lines = prep_content.split('\n')
    sections = []
    manifest = []

    # --- Location matching ---
    # Parse sub-location: first comma segment (e.g., "Substrate Chamber" from "Substrate Chamber, Sub-Foundation, Ceruline")
    sub_location = location.split(',')[0].strip() if location else ""

    loc_section = None
    if sub_location:
        for i, line in enumerate(lines):
            m = re.match(r'^####\s*LOC:\s*(.+?)(?:\((\w+)\))?\s*$', line.strip())
            if m:
                loc_name = m.group(1).strip()
                loc_id = m.group(2) or ""
                # Fuzzy match: sub_location in loc_name, or loc_name in sub_location, or loc_id matches
                if (sub_location.lower() in loc_name.lower() or
                    loc_name.lower() in sub_location.lower() or
                    (loc_id and sub_location.lower().replace(' ', '_') == loc_id.lower())):
                    loc_section = _get_section_by_header(lines[i:], r'^####', max_chars=1500)
                    manifest.append(f"{loc_name.strip()} (location)")
                    break

    # Fallback: list available location names
    if not loc_section and sub_location:
        loc_headers = re.findall(r'####\s*LOC:\s*(.+?)(?:\(|$)', prep_content)
        loc_section = f"_Available locations: {', '.join(h.strip() for h in loc_headers[:15])}_"
        manifest.append("location list (no match)")

    if loc_section:
        sections.append(loc_section)

    # --- NPC matching ---
    for npc_name in present_npcs:
        if not npc_name.strip():
            continue
        for i, line in enumerate(lines):
            m = re.match(r'^###\s*NPC:\s*(.+?)(?:\((.+?)\))?\s*$', line.strip())
            if m:
                npc_full = m.group(1).strip()
                npc_alias = m.group(2).strip() if m.group(2) else ""
                if (npc_name.lower() in npc_full.lower() or
                    npc_name.lower() in npc_alias.lower() or
                    npc_full.lower() in npc_name.lower() or
                    (npc_alias and npc_alias.lower() in npc_name.lower())):
                    section = _get_section_by_header(lines[i:], r'^###', max_chars=1200)
                    if section:
                        sections.append(section)
                        manifest.append(f"{npc_alias or npc_full} (NPC)")
                    break

    # --- Scene-type routing for extra sections ---
    if scene_type in ("settlement", "social"):
        factions = _get_section_by_header(lines, r'^##\s*FACTIONS', max_chars=800)
        if factions:
            sections.append(factions)
            manifest.append("Factions")

    elif scene_type in ("vault_exploration", "combat"):
        encounters = _get_section_by_header(lines, r'^##\s*ENCOUNTERS', max_chars=600)
        if encounters:
            sections.append(encounters)
            manifest.append("Encounters")

    elif scene_type in ("travel", "hexpedition"):
        encounters = _get_section_by_header(lines, r'^##\s*ENCOUNTERS', max_chars=600)
        if encounters:
            sections.append(encounters)
            manifest.append("Encounters")

    return sections, manifest


# Track which prep files have had their "FOR NEW CLAUDE" section loaded this server session
_prep_first_load_done: set[str] = set()


def _register_constraint(constraint_id: str, subject: str, limitation: str, scope: str = "party_known", source: str = "session") -> str:
    """Register a new constraint in the active session."""
    GAME_STATE["active_constraints"][constraint_id] = {
        "id": constraint_id,
        "subject": subject,
        "limitation": limitation,
        "scope": scope,
        "source": source,
        "registered_at": datetime.now().isoformat()
    }
    _save_game_state()
    return f"Constraint registered: {subject} - {limitation}"


def _prep_name_collisions(raw_text: str) -> list:
    """Naming guard (2026-07-20): warn on near-homograph cast names at
    authoring time. Tessith/Tesslyn (2 letters apart, both in the same quorum)
    was conflated by player AND DM for a week — this fires while renaming is
    still cheap. Deterministic + conservative: candidates are capitalised
    tokens (5+ chars) appearing >=3 times; a pair fires on edit distance <=2
    (both >=5 chars) or a shared 4-char prefix (both >=6 chars). Plural pairs
    (X / Xs) and common English capitalised words are excluded."""
    import itertools
    _STOP = {
        "There", "These", "Those", "Their", "Theirs", "Where", "Which", "While",
        "White", "Would", "Could", "Should", "About", "Above", "Below", "Before",
        "After", "Every", "Never", "Again", "Because", "Between", "Without",
        "Player", "Party", "Floor", "Rooms", "Name", "Names", "Status", "Type",
        "Zone", "Zones", "Secret", "Secrets", "Reveal", "Truth", "Effect",
        "Discovery", "Connections", "Entrance", "Notes", "Location",
    }
    counts = {}
    for tok in re.findall(r"\b[A-Z][a-z]{4,}\b", raw_text or ""):
        if tok in _STOP:
            continue
        counts[tok] = counts.get(tok, 0) + 1
    # Proper-noun filter: a real cast name never appears lowercase in the same
    # text, while common capitalised words (Combat, Three, Policy...) do. This
    # is what keeps the warning list to actual name collisions.
    lower_words = set(re.findall(r"\b[a-z]{5,}\b", raw_text or ""))
    cast = sorted(t for t, n in counts.items()
                  if n >= 3 and t.lower() not in lower_words)

    def _lev(a, b):
        if abs(len(a) - len(b)) > 2:
            return 99
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a, 1):
            cur = [i]
            for j, cb in enumerate(b, 1):
                cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                               prev[j - 1] + (ca != cb)))
            prev = cur
        return prev[-1]

    out = []
    for a, b in itertools.combinations(cast, 2):
        if a + "s" == b or b + "s" == a:
            continue  # plural of the same word, not two cast members
        close_edit = len(a) >= 5 and len(b) >= 5 and _lev(a, b) <= 2
        shared_prefix = (len(a) >= 6 and len(b) >= 6
                         and a[:4].lower() == b[:4].lower())
        if close_edit or shared_prefix:
            out.append(
                f"NAME COLLISION risk: '{a}' vs '{b}' — near-homograph names "
                f"confuse play (the Tessith/Tesslyn precedent). Rename one, or "
                f"add a disambiguation glossary entry at the top of the prep.")
        if len(out) >= 8:
            break
    return out


def _validate_prep_schema(data: dict, prep_path: str) -> tuple[list[str], list[str]]:
    """
    Validate parsed prep data against required schema.

    Returns:
        Tuple of (critical_errors, warnings).
        Critical errors should block loading. Warnings are informational.
    """
    critical = []
    warnings = []

    # Check for required metadata
    if not data.get("metadata", {}).get("type"):
        warnings.append("Missing **Type:** in header block")

    # Check rooms - no rooms is critical
    rooms = data.get("rooms", {})
    if not rooms:
        critical.append("No rooms defined (need at least one '## ROOM:' section)")

    for room_id, room in rooms.items():
        if not room.get("name"):
            warnings.append(f"Room '{room_id}' missing **Name:**")
        if room.get("floor") is None:
            warnings.append(f"Room '{room_id}' missing **Floor:**")
        if not room.get("connections"):
            warnings.append(f"Room '{room_id}' missing **Connections:**")

        # Check obstacles have solutions
        obstacles = room.get("obstacles", [])
        if obstacles:
            for obs in obstacles:
                if "Planned Solution" not in obs and "planned_solution" not in str(room.get("raw", "")):
                    warnings.append(f"Room '{room_id}' has obstacle without Planned Solution")

    # Check secrets have reveal conditions
    for secret_id, secret in data.get("secrets", {}).items():
        if not secret.get("reveal_condition") and "Reveal Condition" not in secret.get("raw", ""):
            warnings.append(f"Secret '{secret_id}' missing **Reveal Condition:**")

    return critical, warnings


# ============================================
# LOCATION ENFORCEMENT TOOLS
# ============================================
# Deprecated tools (location_init, location_enter_room, location_state,
# location_reload, reveal, explore) removed. Use map() for vaults
# (now tracks turns + rolls encounters) and geography() for overworld.


def _toxin_impl(
    action: str = Field(description="status | check | resolve | tick | cure | poison_apply | poison_resolve | poison_coat"),
    target: str = Field(default=None, description="PC name or enemy descriptor (poison_coat: the PC whose weapon is coated)"),
    tox_die: str = Field(default=None, description="Attack's TOX die for check/resolve, e.g. 'd8'"),
    save_total: int = Field(default=None, description="resolve/poison_resolve: the PC's CON save total (d20 + CON)"),
    full: bool = Field(default=False, description="cure: clear entirely instead of stepping down one rung"),
    poison: Optional[str] = Field(default=None, description="[poison_apply/poison_resolve/poison_coat] Generator row 1-20, or an inline poison record (JSON)"),
    weapon: Optional[str] = Field(default=None, description="[poison_coat] Weapon name on the PC's sheet (substring match)"),
) -> str:
    """Reach for this WHEN a toxic weapon hits, a PC must save against poison, a toxin ticks
    at end of exploration turn, you want to check/cure an active Toxin Die, or a Vaarnish
    poison is ingested, splashed, or delivered by a coated weapon.

    Toxin Die (book-accurate, symmetric across PCs and Biological enemies)
    + Vaarnish poison application (B2).

    - status  — show a combatant's current Toxin Die (or the whole party + active combat).
    - check   — given target + tox_die: susceptibility + CON save DC (10 + die). PC target tells
                YOU to roll; enemy target auto-rolls d20 + Level (cap +10) and resolves.
    - resolve — apply a PC's CON save_total against a pending tox_die (fail -> gain/escalate).
    - tick    — roll the current die, subtract HP, deplete on a 1-2 (manual exploration-turn tick).
    - cure    — DM lever: step the die down one rung, or clear it (full=true).
    - poison_apply   — apply a Vaarnish poison (row 1-20 or inline record) to a PC or enemy.
                       CON save vs TN 15; lesser effect on a pass, greater on a fail (R-B2a).
                       Pure-TOX rows route straight to the Toxin Die machinery (no extra save).
    - poison_resolve — resolve a PC's poison CON save roll (pass save_total).
    - poison_coat   — coat a PC's weapon (target=PC, weapon=, poison=): the dose fires on
                      the next successful hit, then it is spent (one dose, R-B2b).
    """
    if isinstance(poison, str):
        p = poison.strip()
        if p.startswith("{"):
            try:
                poison = json.loads(p)
            except (ValueError, TypeError):
                return f"poison JSON could not be parsed: {p[:80]}"
    return _toxin_dispatch(action=action, target=target, tox_die=tox_die,
                           save_total=save_total, full=full, poison=poison,
                           weapon=weapon)


@mcp.tool(tags=_get_tool_tags("usage"))
def usage(
    action: str = Field(description="use | status | roll | reload | feed"),
    character: str = Field(default=None, description="PC name (sheet key or display name)"),
    item: str = Field(default=None, description="item/weapon name (substring match) for use/roll/reload/feed"),
    weapon: str = Field(default=None, description="alias for `item` (back-compat)"),
    to: str = Field(default=None, description="reload: target die e.g. 'Ud8' (default = the item's max)"),
) -> str:
    """Reach for this WHEN the player uses any depletable item ("I use the blowtorch",
    drink a potion, fire out of combat). PC-only Usage Die & depletion.

    - use    — the player used an item: rolls its usage die, OR decrements a discrete
               counter (auto-removing + freeing the slot at 0), OR no-ops. Use this.
    - status — LOAD (slots used/cap, Encumbered) + every depletable on hand, party-wide.
    - roll   — manually roll one item's usage die once.
    - reload — DM lever: refill a usage die (default its max); surfaces carried ammo.
    - feed   — Fungal-only: step a usage die up one rung (capped at max).
    """
    return _usage_dispatch(action=action, character=character, weapon=weapon, to=to, item=item)


def _wound_impl(
    action: str = Field(description="status | heal | ko_save | wake"),
    character: str = Field(default=None, description="PC name (sheet key or display name)"),
    wound: str = Field(default=None, description="heal: the wound name to remove (substring match)"),
    result: str = Field(default=None, description="ko_save: 'pass' or 'fail' (the player's rolled CON save)"),
) -> str:
    """Reach for this WHEN a PC's wound state changes outside the damage path:
    a wound is healed (Long Rest choice, Sprayflesh, Trauma-Response Rig, DM
    ruling), a Knocked-Out CON save comes back, or someone wakes/shutdown ends.

    - status  — active wound records + derived effects, per PC (or party-wide when character omitted).
    - heal    — remove ONE wound by name: frees its slots; its derived effects vanish (mutations stay).
    - ko_save — report the player's CON save vs Knocked Out: pass = stays up; fail = unconscious d6 rounds (all attacks auto-hit).
    - wake    — DM lever: clear unconsciousness when the duration expires (the wound itself remains).
    """
    return _wound_dispatch(action=action, character=character, wound=wound, result=result)


def _constraint_check_impl(subject: str, proposed_action: str = "") -> str:
    """List active constraints on a subject. Core of constraint(action='check')."""
    matching = []
    for c_id, c in GAME_STATE["active_constraints"].items():
        if subject.lower() in c.get("subject", "").lower():
            matching.append(c)

    if not matching:
        return f"No constraints found for '{subject}'."

    result = [f"**Constraints affecting {subject}:**"]
    for c in matching:
        result.append(f"- **{c['id']}:** {c.get('limitation', '?')}")
        if c.get("scope") == "dm_only":
            result.append("  _(dm_only - party doesn't know this)_")

    return "\n".join(result)


@mcp.tool(tags=_get_tool_tags("constraint"))
def constraint(
    action: str = Field(description="add|check"),
    constraint_id: str = Field(default="", description="add: unique id (snake_case)"),
    subject: str = Field(default="", description="who/what is constrained (add + check)"),
    limitation: str = Field(default="", description="add: what they cannot do"),
    scope: str = Field(default="party_known", description="add: party_known or dm_only"),
    proposed_action: str = Field(default="", description="check: optional specific action to validate"),
) -> str:
    """Reach for this WHEN a restriction emerges mid-scene (action='add' -- a lockdown
    triggers, an NPC is injured, a door is welded shut) or WHEN a PC/NPC is about to take
    a major action and you need to see what limits them (action='check').

    add:   register an emergent constraint not in prep (constraint_id, subject, limitation, scope?)
    check: list active constraints on a subject so you can judge the action (subject, proposed_action?)
    """
    a = (action or "").lower().strip()
    if a == "add":
        if not (constraint_id and subject and limitation):
            return "Error: action='add' needs constraint_id, subject, and limitation."
        return _register_constraint(constraint_id, subject, limitation, scope, source="session")
    if a == "check":
        if not subject:
            return "Error: action='check' needs subject."
        return _constraint_check_impl(subject, proposed_action)
    return f"Invalid action '{action}'. Valid actions: add, check."


@mcp.tool(
    annotations={"readOnlyHint": True},
    tags=_get_tool_tags("validate_prep_file")
)
def validate_prep_file(
    prep_file: str = Field(description="Path to prep file relative to campaign dir")
) -> str:
    """Reach for this WHEN you're about to run a location for the first time and want
    to confirm the prep file is schema-valid before calling map(action="init").

    Validate a prep file against the required schema. Use before running a location.
    Returns list of errors/warnings or confirms validity.
    """
    data, error = _load_prep_file(prep_file)
    if error:
        return f"**ERROR:** {error}"

    critical_errors, warnings = _validate_prep_schema(data, prep_file)

    # Naming guard: near-homograph cast names (see _prep_name_collisions).
    try:
        warnings.extend(_prep_name_collisions(data.get("raw_content", "")))
    except Exception:
        pass

    # Vault-liveness authoring guard: if this prep calls map(action="init"
    # it MUST carry the <!-- DUNGEON: map=<name> enforce=vault-liveness --> header.
    raw_content = data.get("raw_content", "")
    _registers_map = 'map(action="init"' in raw_content or "map(action='init'" in raw_content
    _has_dungeon_header = bool(re.search(
        r'<!--\s*DUNGEON:\s*map=\S+\s+enforce=vault-liveness\s*-->',
        raw_content,
    ))
    if _registers_map and not _has_dungeon_header:
        critical_errors.append(
            "Missing <!-- DUNGEON: map=<name> enforce=vault-liveness --> header. "
            "Add it as the first line of the file — required for the vault-liveness gate."
        )

    # SITE-marker authoring cross-check (site-entry detector). The marker's key is the
    # map_name the site is entered under (the Active Map pointer); when a DUNGEON header
    # is present that key MUST equal its map slug. The filename is NOT authoritative -
    # some preps register a decoupled map (PLANEYFOLK_CONTACT_PREP -> map=kept_sill).
    try:
        import site_markers as _sm
        _site = _sm.parse_site_marker(raw_content)
        if _site:
            _dm = re.search(
                r'<!--\s*DUNGEON:\s*map=(\S+)\s+enforce=vault-liveness\s*-->',
                raw_content) if _has_dungeon_header else None
            if _dm:
                _slug = _dm.group(1).strip().lower()
                if _site["key"] != _slug:
                    critical_errors.append(
                        f"SITE key='{_site['key']}' != DUNGEON map slug '{_slug}'. "
                        f"They must match (set key={_slug}).")
            if not _site["aliases"]:
                warnings.append(
                    "SITE marker has no aliases - the site-entry detector cannot "
                    "recognise this place from player text.")
        elif _has_dungeon_header:
            warnings.append(
                "Site prep has a DUNGEON header but no <!-- SITE: ... --> marker - the "
                "site-entry detector falls back to a basename alias only. Add the marker.")
    except Exception:
        pass

    # Settlement standard: every settlement NPC must carry a **Location:** the
    # who's-around reader keys on it (settlement_system).
    try:
        import settlement_system as _ss
        if _ss.is_settlement_prep(raw_content):
            _missing = _ss.npcs_missing_location(raw_content)
            if _missing:
                critical_errors.append(
                    "Settlement NPCs missing **Location:** (the who's-around reader needs it): "
                    + ", ".join(_missing))
    except Exception:
        pass

    room_count = len(data.get("rooms", {}))
    secret_count = len(data.get("secrets", {}))

    # 1:1 walkability cross-check: the walkable engine must see the same rooms.
    try:
        from map_system import MapSystem as _MapSystem
        _ms = _MapSystem(CAMPAIGN_DIR)
        _content = (CAMPAIGN_DIR / prep_file).read_text(encoding="utf-8")
        walkable_rooms = set(_ms._parse_rooms_from_prep(_content))
        schema_rooms = set(data.get("rooms", {}))
        if schema_rooms != walkable_rooms:
            only_schema = sorted(schema_rooms - walkable_rooms)
            only_walk = sorted(walkable_rooms - schema_rooms)
            detail = []
            if only_schema:
                detail.append(f"schema-only: {only_schema}")
            if only_walk:
                detail.append(f"walkable-only: {only_walk}")
            warnings.append("Walkability mismatch (validator vs map_system): " + "; ".join(detail))
    except Exception as _e:
        warnings.append(f"Could not run walkability cross-check: {_e}")

    # PARLEY authoring lint: malformed blocks, bad needles/gates, and the
    # legacy VICTORY CONDITIONS format that should be migrated to ## PARLEY:.
    try:
        import social_system as _ss
        warnings.extend(_ss.lint_parley_block(raw_content))
    except Exception:
        pass

    # Reveal-tier subsection lint: WARN when a room has body text but none of
    # its ### subsections match a recognized reveal-tier header (Observables/
    # Obstacles/Loot/Secrets/DM Notes). Legacy **Description:**-only or bare
    # "### Area N:" formatting still LOADS (map_system._SECTION_TIER maps an
    # unknown header -> 'obvious' by design), so this is advisory, never a
    # critical error.
    #
    # Reads room bodies via map_system's OWN room parser (_parse_rooms_from_prep),
    # NOT this file's data.get("rooms", {}) -- the schema parser above has a
    # pre-existing regex bug (its "##\s*[A-Z]" stop-lookahead isn't line-anchored,
    # so it false-matches inside any "### Subsection" header and truncates the
    # room's captured raw text before reaching it). That bug is out of scope for
    # this lint addition; map_system's parser (the one real gameplay uses via
    # map(action="init")) does not have it.
    try:
        from map_system import MapSystem as _MapSystem2
        _ms2 = _MapSystem2(CAMPAIGN_DIR)
        _parsed_rooms = _ms2._parse_rooms_from_prep(raw_content)
        # Defensive: some callers/tests stub _parse_rooms_from_prep down to a
        # bare id list (all the walkability cross-check above needs, via
        # set(...)). This check additionally needs each room's body text, so
        # it silently no-ops rather than erroring when that shape isn't a dict.
        if isinstance(_parsed_rooms, dict):
            _recognized_tier_re = re.compile(
                r'^(secret(s)?|hidden|loot|treasure|obstacles?|hazards?|'
                r'observables?|description|dm notes?|referee notes?|encounters?|'
                r'first glance)\b')
            for room_id, room in _parsed_rooms.items():
                raw = room.get("prep_content", "")
                if not raw.strip():
                    continue
                headers = [h for h in _ms2._slice_subsections(raw) if h != "_lead"]
                if not any(_recognized_tier_re.match(h) for h in headers):
                    warnings.append(
                        f"Room '{room_id}' has body text but no recognized reveal-tier "
                        f"subsection (Observables/Obstacles/Hazards/Loot/Treasure/Secrets/"
                        f"Hidden/Description/Encounters/DM Notes/Referee Notes) - "
                        f"legacy formatting still loads at the 'obvious' tier, but add "
                        f"one of these headers for proper reveal-tier gating."
                    )

                # Fog-map contract (spec 2026-07-05): the player map renders
                # from Floor/Connections; warn when a room lacks either.
                # _parse_rooms_from_prep defaults 'floor' to 1 and
                # 'connections' to {} when absent, so the parsed dict can't
                # signal absence - detect it from the room's raw prep text.
                raw_lower = raw.lower()
                missing = []
                if "**floor:**" not in raw_lower:
                    missing.append("**Floor:**")
                if "**connections:**" not in raw_lower:
                    missing.append("**Connections:**")
                if "**coords:**" not in raw_lower:
                    missing.append("**Coords:**")
                if missing:
                    warnings.append(
                        f"Room '{room_id}' missing {' and '.join(missing)} - "
                        f"the fog-of-war player map places/links rooms from these "
                        f"(rooms without Coords are auto-laid-out from connections)."
                    )

                # Reveal-pacing note (2026-07-16): map(enter) serves only the
                # first paragraph of Observables (or a '### First Glance'
                # section). A single-paragraph Observables shows everything at
                # once — legal, but pacing-poor. Advisory NOTE, never an error.
                secs = _ms2._slice_subsections(raw)
                has_glance = any(h.startswith("first glance")
                                 for h in secs if h != "_lead")
                obs_body = next((b for h, b in secs.items()
                                 if h != "_lead" and re.match(r'observables?\b', h)), "")
                if (not has_glance and obs_body.strip()
                        and len([p for p in re.split(r'\n\s*\n', obs_body) if p.strip()]) == 1):
                    warnings.append(
                        f"NOTE: room '{room_id}' Observables is a single paragraph - "
                        f"first-glance pacing will show everything on enter. Consider a "
                        f"'### First Glance' section or multi-paragraph Observables."
                    )
    except Exception as _e:
        warnings.append(f"Could not run reveal-tier subsection check: {_e}")

    # Stale tool-call lint: flag prep-embedded tool-call strings against the
    # LIVE registered tool list + known stale signatures. Sync-only (mcp's
    # tool registry is read via the local provider's component dict directly -
    # never asyncio.run(mcp.list_tools()), which would deadlock FastMCP's
    # event loop when called from inside a running sync tool; see the
    # OLLAMA EMBEDDING HELPER note above for the same gotcha).
    try:
        _stale_call_patterns = [
            (re.compile(r'\bcheck_canon\([^)]*\bcontexts\s*='),
             "check_canon(...contexts=...) is a stale call shape - the "
             "parameter is now needs= (check_canon(needs=...))."),
            (re.compile(r'\blookup_creature_stats\('),
             "lookup_creature_stats(...) is a retired tool - use "
             "lookup(action='creature') instead."),
        ]
        for _pattern, _msg in _stale_call_patterns:
            if _pattern.search(raw_content):
                warnings.append(_msg)

        _registered_tools = {
            v.name for k, v in mcp._local_provider._components.items()
            if k.startswith("tool:")
        }
        _action_call_re = re.compile(r"\b([a-z_][a-z0-9_]{2,40})\(\s*action\s*=")
        _seen_unregistered = set()
        for _m in _action_call_re.finditer(raw_content):
            _name = _m.group(1)
            if _name in _registered_tools or _name in _seen_unregistered:
                continue
            _seen_unregistered.add(_name)
            warnings.append(
                f"Prep text pushes '{_name}(action=...)' but '{_name}' is not "
                f"a registered MCP tool - stale/retired/typo'd name?"
            )
    except Exception as _e:
        warnings.append(f"Could not run tool-call lint: {_e}")

    if not critical_errors and not warnings:
        push_line = _pf.next_block(
            _pf.push_call("map", action="init",
                          map_name=_derive_map_name(prep_file),
                          prep_file=prep_file),
            label="load prep")
        return f"**✓ VALID:** {prep_file}\n- {room_count} rooms\n- {secret_count} secrets\n- All required fields present\n{push_line}"

    result = []

    if critical_errors:
        result.append(f"**❌ CRITICAL ERRORS in {prep_file}:**")
        result.append("*These will block map(action=\"init\"):*")
        for err in critical_errors:
            result.append(f"- {err}")
        result.append("")

    if warnings:
        result.append(f"**⚠️ WARNINGS in {prep_file}:**")
        result.append("*Location will load but may have issues:*")
        for warn in warnings:
            result.append(f"- {warn}")
        result.append("")

    result.append(f"Stats: {room_count} rooms, {secret_count} secrets")
    return "\n".join(result)


# dm_view RETIRED 2026-07-02 (C28 tombstone). It early-returned on
# GAME_STATE["active_location"], which has had no writer since the location-tool
# retirement (c1f3744) — so it always answered "No active location." The live
# DM-side view is map(action="get_room", include_prep=True) plus [DM]-channel
# notes and the prep file's dm_only secrets (surfaced by check_canon). Session
# and prep constraints now surface directly in check_canon.


# ============================================
# END LOCATION ENFORCEMENT TOOLS
# ============================================

# ============================================
# STATIC DATA RESOURCES
# ============================================
# These expose static JSON files as resources for direct access

mcp.add_resource(FileResource(
    uri="campaign://data/mutations",
    path=RULES_DATA_DIR / "CACOGEN_MUTATIONS.json",
    name="Cacogen Mutations",
    description="Reference data for cacogen mutation tables",
    mime_type="application/json"
))

mcp.add_resource(FileResource(
    uri="campaign://data/geography",
    path=CAMPAIGN_DIR / "VAARN_GEOGRAPHY.json",
    name="Vaarn Geography",
    description="Geographic reference data for the Vaarn setting",
    mime_type="application/json"
))

# Campaign-side transport file wins when present (campaign modes are play-state;
# the engine copy is the generic base — see geography_system._load_transport_speeds).
_transport_speeds_path = CAMPAIGN_DIR / "TRANSPORT_SPEEDS.json"
if not _transport_speeds_path.exists():
    _transport_speeds_path = RULES_DATA_DIR / "TRANSPORT_SPEEDS.json"
mcp.add_resource(FileResource(
    uri="campaign://data/transport",
    path=_transport_speeds_path,
    name="Transport Speeds",
    description="Travel speeds for various transport methods",
    mime_type="application/json"
))

mcp.add_resource(FileResource(
    uri="campaign://data/bloomboons",
    path=RULES_DATA_DIR / "NEOBLOOM_BLOOMBOONS.json",
    name="Neobloom Bloomboons",
    description="Neobloom special abilities reference",
    mime_type="application/json"
))

map_system = register_map_tools(mcp, CAMPAIGN_DIR)
# Wire the Active Map setter so entering/resuming a site arms the pointer
# (layering: map_system never imports server; we inject the setter here).
map_system.on_active_site = _update_current_status_active_map
# Wire the day reader so enter_site can stamp created_day/last_seen_day.
# Defensive: must return an int day or None and NEVER raise (a raise here
# would abort site entry). get_current_day_safe is defined further below, so
# the lambda resolves it lazily at call-time.
def _map_get_day_safe():
    try:
        return get_current_day_safe()
    except Exception:
        return None
map_system.get_day = _map_get_day_safe
# Wire the player-view refresh so any map action re-emits the spoiler-safe
# artifacts with a fresh fog render (layering: map_system never imports server).
map_system.on_state_change = _emit_player_view
# Wire the reveal auto-create sanction: reveal_fact mints a ledger-only state
# ONLY for the active prep's ledger name (a non-vault social/settlement scene
# with no map). Any other unknown name still hard-errors. Resolves at call-time
# and never raises (a raise would abort a legitimate reveal). See
# _active_prep_ledger_name (defined below).
def _ledger_autocreate_ok(name):
    try:
        return bool(name) and name == _active_prep_ledger_name()
    except Exception:
        return False
map_system.ledger_autocreate_ok = _ledger_autocreate_ok
# Wire the prep-text provider (A0 fidelity floor): reveal_fact's prep: provenance
# stamp verifies its phrase against the ACTIVE prep file's full text. Supply that
# text here, reusing _resolve_active_prep_path — the SAME reader the reveal-scope
# logic uses, so there is one parser of the active prep, one home. Resolves at
# call-time (like the wrappers above; _resolve_active_prep_path is defined
# further below) and NEVER raises / returns None: '' on every failure path, so a
# missing/unreadable prep fails CLOSED (a prep: ref then rejects, never writes).
def _active_prep_full_text() -> str:
    try:
        prep_path = _resolve_active_prep_path()
        if prep_path and prep_path.exists():
            return prep_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        pass
    return ""
map_system.get_prep_text = _active_prep_full_text


def _prep_unresolved_lines(raw_value: str) -> list[str]:
    """Fail-VISIBLE block for an active-prep value that names no real file.

    One home for the scream text, shared by check_canon's prep injection and
    the session-start check. The whole reason the bug survived ~80 turns is
    that both prep readers failed SILENTLY; this makes the failure loud."""
    return [
        "",
        f"⚠️ ACTIVE PREP UNRESOLVED: '{raw_value}' does not match any file in "
        f"the campaign dir.",
        "Prep injection and prep: provenance are DEAD until this is fixed — "
        "call update_active_prep with the real filename.",
    ]


def _prep_injection_lines(prep_value: str, prep_path: "Path | None",
                          prep_content: str,
                          scene_type: str = "vault_exploration") -> list[str]:
    """Core check_canon prep-injection lines for a resolved prep, or the
    fail-visible scream when it did not resolve.

    Given the raw **Active Prep:** display value, the resolved path (or None),
    and the prep file text, build: the ACTIVE PREP FILE header (using the
    RESOLVED filename, never the raw label), the overview, prep-room list,
    ⛔ SECRETS block, prep constraints, and location-progress lines. Returns
    _prep_unresolved_lines(prep_value) + logs when prep_path is None. This is
    the single home for the injection body — check_canon extends scene state
    with it, and tests exercise it directly."""
    if prep_path is None:
        logging.error("ACTIVE PREP UNRESOLVED: %r", prep_value)
        return _prep_unresolved_lines(prep_value)

    lines = ["", f"**ACTIVE PREP FILE:** {prep_path.name} ({scene_type})"]

    # Overview / summary (first matching section), capped for token efficiency.
    overview_patterns = [
        r'^#[^#].*?\n\n(.*?)(?=\n##|\n---|\Z)',
        r'## Overview\n\n(.*?)(?=\n##|\Z)',
        r'## Summary\n\n(.*?)(?=\n##|\Z)',
        r'\*\*Summary:\*\*\s*(.*?)(?:\n\n|\Z)',
    ]
    overview_text = None
    for pattern in overview_patterns:
        m = re.search(pattern, prep_content, re.DOTALL | re.MULTILINE)
        if m:
            overview_text = m.group(1).strip()
            break
    if overview_text:
        if len(overview_text) > 300:
            overview_text = overview_text[:300].rsplit(' ', 1)[0] + "..."
        lines.append(f"_Overview: {overview_text}_")

    # Prep rooms (vault exploration only).
    if scene_type == "vault_exploration":
        room_headers = re.findall(r'##\s*ROOM:\s*(\w+)', prep_content)
        if room_headers:
            lines.append(
                f"_Prep rooms: {', '.join(room_headers[:8])}"
                f"{'...' if len(room_headers) > 8 else ''}_")

    # ⛔ DM-only secrets (spoiler enforcement).
    dm_secrets = _extract_dm_only_secrets(prep_content)
    if dm_secrets:
        lines.append("")
        lines.append("**⛔ SECRETS (do not reveal until discovered):**")
        for secret in dm_secrets[:7]:
            lines.append(f"- {secret}")
        lines.append("_Use map(action=\"get_room\", include_prep=True) for the "
                     "DM-side view. Never quote/paraphrase dm_only content._")

    # Prep constraints (C31) — party_known only.
    _prep_cons = _extract_prep_constraints(prep_content)
    _prep_cons_pk = [c for c in _prep_cons
                     if c.get("scope", "party_known") == "party_known"]
    if _prep_cons_pk:
        lines.append("")
        lines.append("**⛓ CONSTRAINTS IN PLAY (prep):**")
        for c in _prep_cons_pk[:6]:
            lines.append(
                f"- {c.get('subject', '?')}: {c.get('limitation', '?')}")
        lines.append(
            "→ constraint(action=\"check\", subject=\"<X>\") before a PC "
            "acts against a limit; constraint(action=\"add\", ...) if a new "
            "one emerges.")

    # Location progress (continuity).
    progress_entries = _extract_progress_log(prep_content)
    if progress_entries:
        latest = progress_entries[-1]
        lines.append("")
        lines.append(
            f"**LOCATION PROGRESS (Day {latest['day']}: {latest['title']}):**")
        if latest.get("items_taken"):
            lines.append(f"- Took: {', '.join(latest['items_taken'])}")
        if latest.get("npcs_met"):
            lines.append(f"- Met: {', '.join(latest['npcs_met'])}")
        if latest.get("secrets_revealed"):
            lines.append(f"- Discovered: {', '.join(latest['secrets_revealed'])}")
        if latest.get("summary"):
            lines.append(f"- {latest['summary']}")
        if len(progress_entries) > 1:
            lines.append(f"_({len(progress_entries)} total visits logged)_")

    return lines
# Same lazy-resolution pattern as _map_get_day_safe above: get_current_day_safe
# is defined further below, so wrap it in a lambda-equivalent that resolves
# at call-time and never raises.
def _social_get_day_safe():
    try:
        return get_current_day_safe()
    except Exception:
        return None
register_social_tools(mcp, CAMPAIGN_DIR, get_day=_social_get_day_safe, get_tool_tags=_get_tool_tags)
geography_system = register_geography_tools(mcp, CAMPAIGN_DIR)
rulebook_system = register_rulebook_tools(mcp, CAMPAIGN_DIR)
# content_forge registered after _roll_encounter_table, _roll_reaction, _roll_exotica are defined (see below)


# ============================================
# OLLAMA EMBEDDING HELPER (SYNCHRONOUS)
# ============================================
# Note: FastMCP's event loop deadlocks on async operations (to_thread,
# run_in_executor, even asyncio.sleep). Must use synchronous calls.
# The ~2 second block for embedding generation is acceptable.
#
# For queries: Use get_embedding_cached() - has LRU cache for repeated queries
# For indexing new content: Use get_ollama_embedding_sync() - no cache (always new)

def get_ollama_embedding_sync(prompt: str, timeout: float = 30.0) -> list[float]:
    """
    Get embedding from Ollama synchronously (NO CACHE).

    Use this for INDEXING new content where caching would be wasteful.
    Applies 'search_document: ' prefix for nomic-embed-text.
    For QUERIES, use get_embedding_cached() instead (has LRU cache + query prefix).

    Note: FastMCP's event loop deadlocks on any async operations
    (to_thread, run_in_executor, asyncio.sleep). Must use sync calls.
    The ~2 second block is acceptable for embedding generation.

    Raises ConnectionError if Ollama is unavailable.
    """
    if not check_ollama_health():
        raise ConnectionError("Ollama unavailable - embeddings disabled. Start Ollama and retry.")
    # Add task-type prefix for nomic-embed-text (improves retrieval quality)
    prefixed = f"search_document: {prompt}"
    response = requests.post(
        'http://127.0.0.1:11434/api/embeddings',
        json={'model': 'nomic-embed-text', 'prompt': prefixed},
        timeout=timeout
    )
    response.raise_for_status()
    return response.json()['embedding']


def get_ollama_embeddings_batch(prompts: list[str], timeout: float = 120.0) -> list[list[float]]:
    """
    Get multiple embeddings in a single Ollama API call using /api/embed.

    Uses the batch endpoint introduced in Ollama 0.1.31+. Dramatically faster than
    calling get_ollama_embedding_sync() in a loop — GPU processes the whole batch
    together instead of one prompt at a time.

    Applies 'search_document: ' prefix to each prompt for nomic-embed-text retrieval quality.

    Raises ConnectionError if Ollama is unavailable.
    Raises ValueError if the response doesn't contain the expected embeddings.
    """
    if not check_ollama_health():
        raise ConnectionError("Ollama unavailable - embeddings disabled. Start Ollama and retry.")
    prefixed = [f"search_document: {p}" for p in prompts]
    response = requests.post(
        'http://127.0.0.1:11434/api/embed',
        json={'model': 'nomic-embed-text', 'input': prefixed},
        timeout=timeout
    )
    response.raise_for_status()
    data = response.json()
    if 'embeddings' not in data:
        raise ValueError(f"Unexpected /api/embed response keys: {list(data.keys())}")
    return data['embeddings']


# read_file / write_file moved to engine_core (Wave 0); imported at the top.


def read_current_status(required: bool = True) -> Optional[str]:
    """
    Safely read CURRENT_STATUS.md with existence check.

    Args:
        required: If True, raises ToolError when missing. If False, returns None.

    Returns:
        File contents or None (if not required and missing)

    Raises:
        ToolError: If required=True and file is missing/unreadable
    """
    status_path = CAMPAIGN_DIR / "CURRENT_STATUS.md"
    if not status_path.exists():
        if required:
            raise ToolError(
                "CURRENT_STATUS.md not found. This file is required for campaign state. "
                "Create it from CURRENT_STATUS_TEMPLATE.md or restore from backup."
            )
        return None
    try:
        return status_path.read_text(encoding='utf-8')
    except Exception as e:
        if required:
            raise ToolError(f"Cannot read CURRENT_STATUS.md: {e}")
        return None


def get_current_day_safe() -> Optional[int]:
    """
    Safely extract current campaign day from CURRENT_STATUS.md.

    Returns:
        Campaign day as int, or None if unavailable
    """
    content = read_current_status(required=False)
    if not content:
        return None
    # Look for "## Campaign Day X" or "**Day X**" patterns
    import re
    day_match = re.search(r'(?:Campaign Day|Day)\s*[:\*]*\s*(\d+)', content, re.IGNORECASE)
    if day_match:
        return int(day_match.group(1))
    return None


def _read_current_status_day() -> Optional[int]:
    """Thin wrapper used by verify_session_save — delegates to get_current_day_safe() for DRY parse."""
    return get_current_day_safe()


# ============================================
# TOKEN-EFFICIENT VOICE GUIDE LOADING
# ============================================

def load_voice_guide_for(characters: list = None) -> str:
    """Load only relevant sections of VOICE.md (voice guide)
    
    Args:
        characters: List of character names present in scene.
                   If None or empty, loads full file (legacy behavior).
    """
    try:
        full_content = read_file("VOICE.md")
        if full_content.startswith("Error"):
            return full_content
            
        if not characters:
            return full_content
            
        lines = full_content.split('\n')
        result_sections = []
        char_upper = [c.upper().strip() for c in characters]
        
        # Headers always included — foundational guidance every scene benefits from.
        # Updated for current VOICE.md flat-L2 structure (no PARTY CHARACTERS umbrella).
        always_include = ["CORE RULES", "BOND COMMUNICATION"]

        current_lines = []
        include_current = False

        for line in lines:
            header_match = re.match(r'^(#{1,3})\s+(.+)$', line.strip())

            if header_match:
                if include_current and current_lines:
                    result_sections.append('\n'.join(current_lines))

                level = len(header_match.group(1))
                header_text = header_match.group(2).strip().upper()
                current_lines = [line]
                include_current = False

                # L1 document title — always keep.
                if level == 1:
                    include_current = True

                # L2 — either an always-include section (Core Rules, Bond), or a character
                # header containing a present character's name as a whole word (>=3 chars).
                if level == 2:
                    for pattern in always_include:
                        if pattern in header_text:
                            include_current = True
                            break

                    if not include_current:
                        for char in char_upper:
                            for word in char.replace("/", " ").split():
                                if len(word) >= 3 and word in header_text:
                                    include_current = True
                                    break
                            if include_current:
                                break
            else:
                if include_current:
                    current_lines.append(line)
        
        if include_current and current_lines:
            result_sections.append('\n'.join(current_lines))
        
        if result_sections:
            header = f"# VOICE GUIDE [Selective: {', '.join(characters)}]\n\n---\n"
            return header + '\n\n---\n\n'.join(result_sections)
        return full_content
        
    except Exception as e:
        return f"Error loading voice guide: {str(e)}"


def load_voice_guide_sections_for(characters: list = None):
    """Return voice guide as keyed delta-delivery elements.

    Each element is ("VOICE", key, content):
      - ("VOICE", "voice:core_rules", <Core Rules section>)
      - ("VOICE", "voice:bond", <Bond Communication section>)
      - ("VOICE", "voice:<Char>", <that character's section>)

    Mirrors load_voice_guide_for's parsing but labels each section so the
    delivery filter can ship only the newcomer when the cast changes.
    Returns [] when no characters are given.
    """
    if not characters:
        return []
    try:
        full_content = read_file("VOICE.md")
        if full_content.startswith("Error"):
            return []

        lines = full_content.split('\n')
        char_upper = [c.upper().strip() for c in characters]

        elements = []
        current_lines = []
        current_key = None  # set when a section we keep begins

        def _flush():
            if current_key and current_lines:
                elements.append(("VOICE", current_key, '\n'.join(current_lines)))

        for line in lines:
            header_match = re.match(r'^(#{1,3})\s+(.+)$', line.strip())
            if header_match:
                _flush()
                level = len(header_match.group(1))
                header_text = header_match.group(2).strip().upper()
                current_lines = [line]
                current_key = None

                if level == 2 and "CORE RULES" in header_text:
                    current_key = "voice:core_rules"
                elif level == 2 and "BOND COMMUNICATION" in header_text:
                    current_key = "voice:bond"
                elif level == 2:
                    for orig, up in zip(characters, char_upper):
                        matched = False
                        for word in up.replace("/", " ").split():
                            if len(word) >= 3 and word in header_text:
                                matched = True
                                break
                        if matched:
                            current_key = f"voice:{orig.strip()}"
                            break
                # L1 title and unmatched sections: current_key stays None (dropped)
            else:
                if current_key:
                    current_lines.append(line)

        _flush()
        return elements
    except Exception:
        return []

# ============================================
# SESSION INITIALIZATION SUPPORT
# ============================================

@mcp.prompt()
def verification_mode():
    """Lorebook scanning protocol - call check_canon on every message"""
    return """# Verification Mode

Call `check_canon(user_input)` on EVERY user message before generating narrative.

Lorebook output is binding. No exceptions.

If no matches: Check if query involves pronouns, history, relationships, or NPCs. If yes, escalate with targeted tool calls before generating.
"""

@mcp.prompt()
def session_start():
    """Session initialization reference"""
    return """# Session Start

Call `full_session_startup()` BEFORE any narration. This is mandatory and non-negotiable.

Do not begin in-character content until you have called this tool and read its output.
"""

@mcp.prompt()
def pre_narration_check():
    """Anti-pattern filter - invoke before generating IC narrative"""
    return """# Pre-Narration Checklist

Before generating ANY in-character narration, verify:

## HARD AVOID - These Phrases Are Banned

- "goes still" / "goes quiet" / "goes very still"
- "something shifts in [X]'s expression"
- "the word hangs between them"
- "for a long moment..."
- "freezes" (unless literal ice/stasis)
- "time seems to slow/stop"

## USE INSTEAD

- Specific physical detail: Breath catches. Hand pauses on the cup. Eyes fix on the door.
- What they're NOT doing: She doesn't look away. He hasn't moved to leave.
- Let dialogue carry weight: Just end the line. White space IS silence.

## DIALOGUE BANS

Characters don't narrate their own backstory to people who know them:
- The noble-born envoy never says "I was bred to be a politician..."
- The ancient pilot never says "In my seventeen centuries..."
- The hard-bitten scout never announces the first time she cared about anything.

Show through BEHAVIOR, not self-explanation.

## POV CHECK

- The player character = "you" (2nd person). NEVER 3rd person ("she felt...") for the PC.
- Other party members = 3rd person from the player character's perspective

## SELF-CHECK

Before sending: Did I write any banned phrases? If yes, DELETE and rewrite.
"""

def _list_files_impl(pattern: str = "*.md", exists_check: str = None) -> str:
    """List campaign files. Core of files(action='list')."""
    try:
        if exists_check:
            exists = (Path(CAMPAIGN_DIR) / exists_check).exists()
            return "true" if exists else "false"
        files = list(Path(CAMPAIGN_DIR).glob(pattern))
        return "\n".join(sorted([f.name for f in files]))
    except Exception as e:
        raise ToolError(f"Error listing files: {str(e)}")

# ============================================
# END SESSION INITIALIZATION SUPPORT
# ============================================

def _settlement_overlays(prep_path, data):
    """Build (npc_overlay, place_overlay) by merging the two existing stores:
    people-status from the npc_states.json living dossier, place/standing-status
    from the prep's own PROGRESS LOG. Read-only; authored prose untouched.

    Real npc_states.json schema: status values are "active", "offscreen",
    "sleeping", plus "DEAD" + death_day set by npc(action="record_death"). This
    reader surfaces DEAD records as the †dead overlay; place_overlay (party_standing,
    repaired wells, etc.) is the other live path.
    """
    import settlement_system as _ss
    import ceruline_reader as _cr
    place_overlay = _ss.parse_place_status(prep_path.read_text(encoding="utf-8"))
    npc_overlay = {}
    try:
        states_data, err = _load_npc_states()
        if not err:
            npcs_dict = (states_data or {}).get("npcs") or {}
            _identity_idx = None  # built lazily, only if an exact match misses
            for n in data["npcs"]:
                # Exact attempts first so small-settlement output is byte-unchanged.
                rec = npcs_dict.get(n["name"]) or npcs_dict.get(n["name"].lower())
                if rec is None:
                    # Identity-normalized fallback: the card may show a title-bearing
                    # display name ("Matriarch Amara Vane") while the dossier keys
                    # it title-stripped ("amara vane"), or vice-versa.
                    if _identity_idx is None:
                        _identity_idx = {
                            _cr.identity_key(k): r for k, r in npcs_dict.items()
                        }
                    rec = _identity_idx.get(_cr.identity_key(n["name"]))
                if rec and str(rec.get("status", "")).upper() == "DEAD":
                    npc_overlay[n["name"]] = {
                        "status": "DEAD",
                        "day": rec.get("death_day", "?"),
                    }
    except Exception:
        pass
    return npc_overlay, place_overlay


# ============================================
# LOCATION REFERENCE TOOLS
# ============================================

@mcp.tool(
    annotations={"readOnlyHint": True, "idempotentHint": True},
    tags=_get_tool_tags("reference_location")
)
def reference_location(
    location: str = None,
    scope: str = "overview",
    focus: str = None
) -> str:
    """Reach for this WHEN narrating a named place — describing Ceruline, a region, a
    district, or an NPC tied to a location — and you need the reference details.

    Get location reference info. Use when narrating location details or checking NPC/landmark info."""

    # Location registry: maps location name -> (file, format_type, supported_scopes)
    # format_type: 'full' = three-tier with ## OVERVIEW, ## DISTRICT:, ### NPC:, etc.
    #              'region' = REGIONS_QUICK_REF.md format with ### N. REGION NAME
    LOCATION_REGISTRY = {
        # Full three-tier support (Ceruline-style reference files)
        'ceruline': {
            'file': 'CERULINE_PLAYER_REFERENCE.md',
            'format': 'full',
            'scopes': ['overview', 'district', 'npc', 'landmark', 'rumors']
        },
        # Regional overviews from REGIONS_QUICK_REF.md (overview only)
        'badlands': {
            'file': 'REGIONS_QUICK_REF.md',
            'format': 'region',
            'section_header': '### 1. THE BADLANDS (SOUTH)',
            'scopes': ['overview']
        },
        'interior': {
            'file': 'REGIONS_QUICK_REF.md',
            'format': 'region',
            'section_header': '### 2. THE INTERIOR (CENTRAL)',
            'scopes': ['overview']
        },
        'lazul mountains': {
            'file': 'REGIONS_QUICK_REF.md',
            'format': 'region',
            'section_header': '### 3. LAZUL MOUNTAINS (NORTH)',
            'scopes': ['overview']
        },
        'sky islands': {
            'file': 'REGIONS_QUICK_REF.md',
            'format': 'region',
            'section_header': '### 4. SKY ISLANDS (EAST)',
            'scopes': ['overview']
        },
        'mooncradle mountains': {
            'file': 'REGIONS_QUICK_REF.md',
            'format': 'region',
            'section_header': '### 5. MOONCRADLE MOUNTAINS (FAR EAST)',
            'scopes': ['overview']
        },
        'sea of songs': {
            'file': 'REGIONS_QUICK_REF.md',
            'format': 'region',
            'section_header': '### 6. SEA OF SONGS (FAR WEST)',
            'scopes': ['overview']
        },
        'great wall': {
            'file': 'REGIONS_QUICK_REF.md',
            'format': 'region',
            'section_header': '### 7. THE GREAT WALL (NORTH-WEST)',
            'scopes': ['overview']
        },
        'ikor quag': {
            'file': 'REGIONS_QUICK_REF.md',
            'format': 'region',
            'section_header': '### 8. IKOR QUAG (SOUTH-WEST)',
            'scopes': ['overview']
        },
        'golgotha': {
            'file': 'REGIONS_QUICK_REF.md',
            'format': 'region',
            'section_header': '### 9. GOLGOTHA (FURTHEST NORTH)',
            'scopes': ['overview']
        },
        'labyrinth': {
            'file': 'REGIONS_QUICK_REF.md',
            'format': 'region',
            'section_header': '### 10. THE LABYRINTH',
            'scopes': ['overview']
        },
    }

    # Discovery mode: return available locations
    if location is None:
        result = "# Available Locations\n\n"
        result += "## Full Detail (all scopes)\n"
        for loc, data in LOCATION_REGISTRY.items():
            if data['format'] == 'full':
                result += f"- **{loc.title()}**: {', '.join(data['scopes'])}\n"
        result += "\n## Regional Overviews (overview only)\n"
        for loc, data in LOCATION_REGISTRY.items():
            if data['format'] == 'region':
                result += f"- {loc.title()}\n"
        return result

    # Normalize location name (case-insensitive)
    location_lower = location.lower().strip()

    # Settlement scopes (flat, non-hostile reader) route to settlement_system before
    # the hand-authored LOCATION_REGISTRY. Prep is read fresh = source of truth.
    if scope in ("who", "trade"):
        import ceruline_reader as _cr
        if _cr.is_ceruline(location):
            cf = CAMPAIGN_DIR / _cr.CERULINE_FILE
            if not cf.exists():
                return f"Ceruline reference file not found: {_cr.CERULINE_FILE}"
            if scope == "trade":
                return _cr.trade_summary(CAMPAIGN_DIR)
            # who: build the death overlay from npc_states for the resolved tier's people
            tiers = _cr.parse_ceruline(cf.read_text(encoding="utf-8"))
            t = _cr.match_tier(focus, tiers) if focus else None
            npc_overlay = {}
            if t:
                pseudo = {"name": "Ceruline", "npcs": [{"name": p["name"]} for p in t["people"]]}
                npc_overlay, _ = _settlement_overlays(cf, pseudo)
            current_day = get_current_day_safe()
            return _cr.who_card(CAMPAIGN_DIR, focus=focus, npc_overlay=npc_overlay,
                                current_day=current_day)
        import settlement_system as _ss
        prep = _ss.resolve_settlement(location, CAMPAIGN_DIR)
        if not prep or not prep.exists():
            return (f"No settlement named '{location}' found. A settlement prep needs a "
                    f"<!-- SITE: ... scene=settlement ... --> marker.")
        data = _ss.parse_settlement(prep.read_text(encoding="utf-8"))
        npc_overlay, place_overlay = _settlement_overlays(prep, data)  # npc_overlay empty until npc_states gains a death field; place_overlay is live
        if scope == "trade":
            return f"{data['name'].upper()} — trade\n{data['trade'] or '(no trade goods listed)'}"
        return _ss.build_who_card(data, npc_overlay, place_overlay)


    # Try exact match first, then partial matching
    loc_data = LOCATION_REGISTRY.get(location_lower)
    if not loc_data:
        # Try partial match for common variations
        for key in LOCATION_REGISTRY:
            if location_lower in key or key in location_lower:
                loc_data = LOCATION_REGISTRY[key]
                break

    if not loc_data:
        available = ', '.join(LOCATION_REGISTRY.keys())
        return f"Location '{location}' not found. Available: {available}"

    # Check if requested scope is supported
    if scope not in loc_data['scopes']:
        return f"Location '{location}' only supports: {', '.join(loc_data['scopes'])}. Use files(action='read') for deeper detail."

    # Build section header based on format and scope
    if loc_data['format'] == 'region':
        # Regional format: use pre-defined section header
        section = loc_data['section_header']
        section_level = 3  # ### headers
    elif scope == "overview":
        section = "## OVERVIEW"
        section_level = 2
    elif scope == "district":
        if not focus:
            return "District scope requires 'focus' parameter (district name)"
        section = f"## DISTRICT: {focus}"
        section_level = 2
    elif scope == "npc":
        if not focus:
            return "NPC scope requires 'focus' parameter (NPC name)"
        section = f"### NPC: {focus}"
        section_level = 3
    elif scope == "landmark":
        if not focus:
            return "Landmark scope requires 'focus' parameter (landmark name)"
        section = f"### LANDMARK: {focus}"
        section_level = 3
    elif scope == "rumors":
        section = "## RUMORS AND CURRENT EVENTS"
        section_level = 2
    else:
        return f"Invalid scope '{scope}'. Use: overview, district, npc, landmark, rumors, who (settlement), or trade (settlement)"

    # Read and extract section
    try:
        filepath = CAMPAIGN_DIR / loc_data['file']
        if not filepath.exists():
            return f"Location file not found: {loc_data['file']}"

        content = filepath.read_text(encoding='utf-8')
        lines = content.split('\n')
        start_idx = None
        end_idx = None

        # Case-insensitive section matching
        section_lower = section.lower().strip()

        for i, line in enumerate(lines):
            line_lower = line.lower().strip()
            # Match if line starts with the section header (handles trailing markers like emoji)
            if start_idx is None and line_lower.startswith(section_lower.rstrip()):
                start_idx = i
            elif start_idx is not None:
                # Stop at next same-or-higher level header
                if line.startswith('#'):
                    current_level = len(line) - len(line.lstrip('#'))
                    if current_level <= section_level:
                        end_idx = i
                        break

        if start_idx is None:
            return f"Section '{section}' not found in {loc_data['file']}"

        if end_idx is None:
            end_idx = len(lines)

        section_content = '\n'.join(lines[start_idx:end_idx])
        return section_content.strip()

    except Exception as e:
        raise ToolError(f"Error reading location: {str(e)}")

# ============================================
# END LOCATION REFERENCE TOOLS
# ============================================

# ============================================
# DYNAMIC TOOL VISIBILITY FILTERING (Context-Based)
# ============================================
# Claude-driven context signaling replaces keyword-based mode detection.
# Multiple contexts can be active simultaneously.

# Hook state file location
HOOK_STATE_FILE = Path(__file__).parent / "hooks" / ".hook_state.json"




def _read_hook_state() -> dict:
    """Read the hook state file written by turn_reset hook."""
    if not HOOK_STATE_FILE.exists():
        return {}
    try:
        return json.loads(HOOK_STATE_FILE.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _write_hook_state(state: dict) -> None:
    """Write hook state file atomically."""
    temp_file = HOOK_STATE_FILE.with_suffix('.tmp')
    try:
        temp_file.write_text(json.dumps(state, indent=2), encoding='utf-8')
        temp_file.replace(HOOK_STATE_FILE)
    except Exception:
        try:
            temp_file.unlink()
        except FileNotFoundError:
            pass
        raise


@contextmanager
def _hook_state_lock():
    """Serialize a server-side read-modify-write of .hook_state.json against the
    hooks' own locked writes.

    The hooks all guard their read-modify-writes with hook_utils.file_lock() and
    write atomically. The server process must use the SAME cross-process lock, or
    a plain server read/modify/write can race a hook that is mid-write: a torn
    read falls to hook_utils' default state (session_type='development', canon
    flags False), which — if it then gets persisted — silently drops canon
    enforcement for the rest of the session. Wrap every server-side RMW like:

        with _hook_state_lock():
            state = _read_hook_state()
            state[...] = ...
            _write_hook_state(state)
    """
    from hooks.hook_utils import file_lock
    with file_lock():
        yield


@mcp.tool(tags=_get_tool_tags("reset_gate"))
def reset_gate() -> str:
    """Reach for this WHEN tools are blocked mid-turn even though check_canon already
    succeeded, or the vault-liveness gate is stuck and needs manual unblocking.

    Reset gate check flags when tools are blocked after check_canon succeeds.
    Also clears vault_action_required so a stuck vault-liveness gate can be
    manually unblocked without ending the session.
    """
    with _hook_state_lock():
        state = _read_hook_state()
        state["canon_verified"] = True
        state["canon_succeeded"] = True
        state["vault_action_required"] = False  # clear vault-liveness block
        _write_hook_state(state)
    return "Gate flags reset: canon_verified=True, canon_succeeded=True, vault_action_required=False"


def _set_bell_impl(bell: int) -> str:
    """Reach for this WHEN narrative time jumps within a session — a long conversation
    ends, the party travels a few hours, evening draws in — and the in-game clock needs updating.

    Set the current in-game time on the 24-bell clock (1-24).
    Call this when narrative time passes within a session — a long conversation,
    travel, an evening drawing in. The bell drives the in-game clock the DM sees
    each turn. For crossing into a new day, use advance_day() instead.
    """
    try:
        bell_val = int(bell)
    except (TypeError, ValueError):
        return "Invalid bell — pass an integer hour from 1 to 24."
    clamped = max(1, min(24, bell_val))
    with _hook_state_lock():
        state = _read_hook_state()
        state["current_bell"] = clamped
        _write_hook_state(state)
    note = "" if clamped == bell_val else f" (clamped from {bell_val})"
    return f"In-game time set to bell {clamped}{note}."


@mcp.tool(tags=_get_tool_tags("session_mode"))
def session_mode(action: str = Field(
    description="maintenance_on | maintenance_off")) -> str:
    """Reach for this WHEN entering or leaving maintenance mode — the /maintenance,
    /session-end, /dm-design, and /session-start skills call it to toggle the
    check_canon enforcement and prose-coaching hooks.

    maintenance_on  — mute the canon gate, the prose/anti-pattern coaching, and the
                      Haiku prose observer. Use for non-gameplay work: file edits,
                      session-end save pipeline, dm-design subagent dispatch.
    maintenance_off — restore normal gameplay enforcement and clear the prose-catch
                      counters for a fresh session. Use when returning to play (this
                      is also the session-start reset).

    This is the engine-owned, cross-platform replacement for the old
    `cd hooks && python3 -c "...poke .hook_state.json..."` shell blocks: it works
    identically on macOS, Linux, WSL, and native Windows, and needs no filesystem
    path. It is ALWAYS-available (ungated) by design — it IS the canon bypass, so
    gating it behind check_canon would deadlock.
    """
    act = action if isinstance(action, str) else "maintenance_on"
    with _hook_state_lock():
        state = _read_hook_state()
        if act == "maintenance_on":
            state["maintenance_mode"] = True
            state["skip_canon_enforcement"] = True
            state["skip_semantic_observer"] = True
            _write_hook_state(state)
            return ("Maintenance mode ON — check_canon enforcement, prose coaching, and "
                    "the Haiku prose observer are muted. /session-start (or "
                    "session_mode action=maintenance_off) restores gameplay.")
        elif act == "maintenance_off":
            state["maintenance_mode"] = False
            state["skip_canon_enforcement"] = False
            state["skip_semantic_observer"] = False
            state["catch_count"] = 0
            state["catch_log"] = {}
            state["session_vocabulary"] = []
            _write_hook_state(state)
            return ("Maintenance mode OFF — normal check_canon enforcement restored; "
                    "prose-catch counters cleared for a fresh session.")
    return "Invalid action. Valid actions: maintenance_on, maintenance_off"





@mcp.tool(
    annotations={"readOnlyHint": True, "idempotentHint": True},
    tags={Safety.ALWAYS, Domain.META}
)
def get_visibility_status() -> str:
    """Reach for this WHEN you need to confirm the tool-visibility / gating status,
    e.g. debugging why a tool appears unavailable or verifying gating was removed.

    Report tool visibility. Gating was removed 2026-05-29 — all tools are
    always available; tool discovery is handled by the client (tool_search)."""
    result = {
        "gating": "disabled",
        "tools_total": len(TOOL_TAGS),
        "note": "All tools always visible. Context-cluster filtering was removed.",
    }
    return json.dumps(result, indent=2)


# ============================================

def _format_combat_hud() -> str:
    """Generate combat HUD for check_canon display."""

    combat = GAME_STATE.get("active_combat")
    if not combat:
        return ""

    lines = ["**ACTIVE COMBAT:**"]

    # Round and initiative
    turn_status = []
    if combat["pcs_acted"]:
        turn_status.append("PCs acted")
    else:
        turn_status.append("PCs haven't acted yet")

    if combat["enemies_acted"]:
        turn_status.append("enemies acted")
    else:
        turn_status.append("enemies haven't acted yet")

    lines.append(
        f"Round {combat['round']} - "
        f"{'PCs' if combat['initiative'] == 'pcs' else 'Enemies'} act first "
        f"({', '.join(turn_status)})"
    )
    lines.append("")

    # Enemies
    lines.append("ENEMIES:")
    for name, data in combat["enemies"].items():
        if data["defeated"]:
            lines.append(f"- {name}: DEFEATED")
        elif data["fled"]:
            lines.append(f"- {name}: FLED")
        else:
            hp_pct = data["hp"] / data["max_hp"]
            wounded = " ⚠️ WOUNDED" if hp_pct < 0.5 else ""
            lines.append(
                f"- {name}: {data['hp']}/{data['max_hp']} HP, "
                f"AV {data['av']}, Morale +{data['morale']}{wounded}"
            )
    lines.append("")

    # Party
    lines.append("PARTY:")
    chars_data, _ = _load_characters()
    for name, snapshot in combat["party_snapshot"].items():
        char = chars_data["characters"].get(name)
        if not char:
            continue

        hp_value = char.get("hp", {})
        if isinstance(hp_value, dict):
            current_hp = hp_value.get("current", 0)
            max_hp = hp_value.get("max", 0)
        else:
            current_hp = hp_value
            max_hp = char.get("max_hp", 0)
        damage_taken = snapshot["hp"] - current_hp

        damage_str = ""
        if damage_taken > 0:
            damage_str = f" (took {damage_taken} damage)"
        elif damage_taken < 0:
            damage_str = f" (healed {abs(damage_taken)} HP)"

        lines.append(f"- {name}: {current_hp}/{max_hp} HP{damage_str}")

    # Warnings
    if combat.get("morale_broken"):
        lines.append("")
        lines.append("⚠️ MORALE BROKEN - Enemies fleeing/surrendering")

    return "\n".join(lines)






def _parse_status_content(content: str) -> dict:
    """Parse CURRENT_STATUS.md content once and return all fields.

    Prevents redundant reads/parsing in check_canon.
    Returns dict with: location, day, last_speaker, beats, tension, next_expected,
    arc, dm_knowledge, emotional_states, active_prep, scene_type, present_list.
    """
    parsed = {
        'location': '?',
        'day': 0,
        'last_speaker': '?',
        'beats': [],
        'tension': '',
        'next_expected': '',
        'arc': '',
        'dm_knowledge': '',
        'emotional_states': '',
        'active_prep': 'None',
        'scene_type': '',
        'active_map': 'None',
        'present_list': [],
    }

    if not content:
        return parsed

    content = content.replace('\r\n', '\n').replace('\r', '\n')

    try:
        # Location
        match = re.search(r'\*\*Location:\*\*\s*(.+?)(?:\n|$)', content)
        if match:
            parsed['location'] = match.group(1).strip()

        # Day
        match = re.search(r'\*\*Day:\*\*\s*(\d+)', content)
        if match:
            parsed['day'] = int(match.group(1))

        # Last Speaker
        match = re.search(r'\*\*Last Speaker:\*\*\s*(.+?)(?:\n|$)', content)
        if match:
            parsed['last_speaker'] = match.group(1).strip()

        # Last 3 Beats (extract all 3)
        # Extract all beats from the Last 3 Beats section in one pass
        beats_block = re.search(r'\*\*Last 3 Beats:\*\*\s*\n?((?:\d+\.\s*.+(?:\n|$))+)', content)
        if beats_block:
            beat_lines = beats_block.group(1).strip().split('\n')
            for line in beat_lines:
                beat_text = re.sub(r'^\d+\.\s*', '', line.strip())
                if beat_text and not beat_text.startswith('**'):
                    parsed['beats'].append(beat_text)

        # Tension/Mood
        match = re.search(r'\*\*Tension/Mood:\*\*\s*(.+?)(?:\n|$)', content)
        if match:
            parsed['tension'] = match.group(1).strip()

        # Next Expected
        match = re.search(r'\*\*Next Expected:\*\*\s*(.+?)(?:\n|$)', content)
        if match:
            parsed['next_expected'] = match.group(1).strip()

        # Current Arc
        match = re.search(r'\*\*Current Arc:\*\*\s*(.+?)(?:\n|$)', content)
        if match:
            parsed['arc'] = match.group(1).strip()

        # DM Knowledge
        match = re.search(r'## DM KNOWLEDGE\s*\n(.*?)(?=\n## |\Z)', content, re.DOTALL)
        if match:
            parsed['dm_knowledge'] = match.group(1).strip()

        # Emotional State
        match = re.search(r'## EMOTIONAL STATE\s*\n(.*?)(?=\n## |\Z)', content, re.DOTALL)
        if match:
            parsed['emotional_states'] = match.group(1).strip()

        # Active Prep
        match = re.search(r'\*\*Active Prep:\*\*\s*(.+?)(?:\n|$)', content)
        if match:
            parsed['active_prep'] = match.group(1).strip()

        # Scene Type
        match = re.search(r'\*\*Scene Type:\*\*\s*(.+?)(?:\n|$)', content)
        if match:
            parsed['scene_type'] = match.group(1).strip()

        # Active Map
        match = re.search(r'\*\*Active Map:\*\*\s*(.+?)(?:\n|$)', content)
        if match:
            parsed['active_map'] = match.group(1).strip()

        # Present
        match = re.search(r'\*\*Present:\*\*\s*(.+?)(?:\n|$)', content)
        if match:
            present_str = match.group(1).strip()
            parsed['present_list'] = [c.strip() for c in present_str.split(',')]

    except Exception as e:
        logging.debug(f"Status content parse partial failure: {e}")

    return parsed


def _load_rules_index() -> dict:
    """Return {rule_id: rule_text} from rulebook/rules.json, mtime-cached. {} on error."""
    rules_path = RULES_DATA_DIR / "rulebook" / "rules.json"
    try:
        data = _load_cached_json(rules_path, "rules_json")
    except Exception:
        return {}
    idx = {}
    for r in data.get("entries", []):
        if isinstance(r, dict) and r.get("id"):
            idx[r["id"]] = r.get("rule", "")
    return idx


# Nugget volume control. The distillation lanes are the single largest
# contributor to check_canon volume (~45%): up to 10 nuggets/turn. We DROP
# empty/placeholder nuggets (e.g. "<UNKNOWN>") that carried zero signal yet
# shipped every turn. We deliberately do NOT length-truncate: nuggets are
# fact-dense and a real canon fact often sits 900-1,150 chars in (verified via
# the 259 recall harness — a 400c cap caused CAUGHT->MISSED; even 900c lost
# channel/encryption/distance facts). Truncation cannot be made recall-safe here.
_NUGGET_PLACEHOLDERS = ("<unknown>", "unknown", "n/a", "none", "tbd", "?")


def _is_placeholder_nugget(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return True
    if "<unknown>" in t:
        return True
    return t in _NUGGET_PLACEHOLDERS


def _distillation_elements(entries, section: str, prefix: str):
    """Per-entry distillation elements.

    entries: list[(entry_name: str, formatted_text: str)].
    section: display section label (e.g. "DISTILLATIONS").
    prefix: key prefix (e.g. "distill" or "idistill").
    Returns list of (section, "<prefix>:<entry_name>", formatted_text).
    """
    elements = []
    for name, text in entries:
        if name and text:
            elements.append((section, f"{prefix}:{name.strip()}", text))
    return elements


def _relationship_elements(present_names, rel_lines_by_char):
    """Convert per-character relationship lines into delta-delivery elements.

    present_names: list[str] of characters in scene.
    rel_lines_by_char: dict[str, str] mapping a character to its formatted line.
    Returns list of ("RELATIONSHIPS", "rel:<Char>", <line>).
    """
    elements = []
    for name in present_names:
        line = rel_lines_by_char.get(name)
        if line:
            elements.append(("RELATIONSHIPS", f"rel:{name.strip()}", line))
    return elements


def _relationship_store_present_lines(present_names_raw):
    """C29 — surface the relationship TOOL store (narrative_relationships.json) in
    check_canon. When BOTH entities of a stored relationship are in the Present
    roster, return one delta-delivery element per pair: current status + last-change
    day + a pull handle (relationship history/get). Honors the context-budget rule
    (one line + a pull handle, never full history). Complements the hand-maintained
    RELATIONSHIP_MATRIX injection — the two stores stay separate by design (the matrix
    holds static typed relations; this store holds dynamic status + change history)."""
    elements = []
    try:
        data, err = _load_relationships()
        if err or not isinstance(data, dict):
            return elements
    except Exception:
        return elements
    rels = data.get("relationships", {})
    if not rels:
        return elements
    present_lower = [p.lower().strip() for p in present_names_raw if p and p.strip()]

    def _matches_present(entity):
        el = (entity or "").lower().strip()
        if not el:
            return False
        for p in present_lower:
            if p in el or el in p:
                return True
            for part in p.split('/'):
                part = part.strip()
                if part and (part in el or el in part):
                    return True
        return False

    for key, rel in sorted(rels.items()):
        entities = rel.get("entities") or key.split("|")
        if len(entities) != 2:
            continue
        e1, e2 = entities[0], entities[1]
        if not (_matches_present(e1) and _matches_present(e2)):
            continue
        status = rel.get("status", "unknown")
        day = rel.get("last_interaction_day")
        history = rel.get("history") or []
        day_str = f" (shift Day {day})" if day else ""
        handle = "history" if history else "get"
        line = (f"🔗 {e1} ↔ {e2} = {status}{day_str}. "
                f"→ relationship(action=\"{handle}\", entity1=\"{e1}\", entity2=\"{e2}\")")
        elements.append(("RELATIONSHIPS", f"relstore:{key}", line))
    return elements


def _rules_in_play_pairs(present_names, lorebook, rules_idx):
    """Collect (rule_id, rule_text) for present characters' rule_refs, deduped by id.

    Shared by _build_rules_in_play_block and _rules_in_play_elements (DRY).
    Matches each present name to its 'people' lorebook entry (keyword substring),
    resolves rule_refs against rules_idx, first matching entry per character.
    """
    pairs = []
    seen_ids = set()
    for present_name in present_names:
        pn = present_name.lower()
        for entry in lorebook.get("entries", []):
            if entry.get("category") != "people":
                continue
            entry_kws = [k.lower() for k in entry.get("keywords", [])]
            if not any(pn in kw or kw in pn for kw in entry_kws):
                continue
            for rid in entry.get("rule_refs", []) or []:
                if rid in seen_ids:
                    continue
                rule_text = rules_idx.get(rid)
                if rule_text:
                    seen_ids.add(rid)
                    pairs.append((rid, rule_text))
            break  # first matching entry per present character
    return pairs


def _format_rule_line(rule_text):
    """One-line, length-capped rendering of a rule for the RULES IN PLAY block."""
    one_line = rule_text.strip().replace("\n", " ")
    if len(one_line) > 160:
        one_line = one_line[:160].rsplit(" ", 1)[0] + "..."
    return f"- {one_line}"


def _rules_in_play_elements(present_names, lorebook, rules_idx, cap: int = 6):
    """Per-rule delta-delivery elements: ("RULES", "rules:<rid>", "- <text>")."""
    elements = []
    for rid, rt in _rules_in_play_pairs(present_names, lorebook, rules_idx)[:cap]:
        elements.append(("RULES", f"rules:{rid}", _format_rule_line(rt)))
    return elements


def _build_rules_in_play_block(present_names, lorebook, rules_idx, cap: int = 6) -> str:
    """Build a 'RULES IN PLAY' block for present characters' rule_refs.

    Matches each present name to its 'people' lorebook entry (keyword substring,
    same convention as the conversational-hop injector), resolves that entry's
    rule_refs against rules_idx, and renders a capped, one-line-each block.
    Returns '' if no present character has resolvable rules.

    NOTE: no longer called from check_canon (which now delta-delivers via
    _rules_in_play_elements). Retained as the headered, single-string rendering
    and as test surface for _rules_in_play_pairs.
    """
    pairs = _rules_in_play_pairs(present_names, lorebook, rules_idx)
    if not pairs:
        return ""
    lines = ["", "**RULES IN PLAY (present characters):**"]
    for _rid, rt in pairs[:cap]:
        lines.append(_format_rule_line(rt))
    lines.append("")
    return "\n".join(lines)


# ============================================

def _smart_truncate_lorebook_entry(entry: dict, max_chars: int = 500) -> str:
    """Truncate lorebook entry for check_canon injection, preserving identity fields.

    Priority: identity prefix + short_context > identity prefix + truncated context.
    Returns base text unchanged if under max_chars with no identity fields.
    """
    context = entry.get('context', '')
    short_context = entry.get('short_context', '').strip()

    # Build identity prefix from structured fields
    identity_parts = []
    pronouns = entry.get('pronouns')
    species = entry.get('species')
    if pronouns:
        identity_parts.append(pronouns)
    if species:
        identity_parts.append(species)
    identity_prefix = f"[{', '.join(identity_parts)}] " if identity_parts else ""

    # Choose base text: prefer short_context if it exists
    base_text = short_context if short_context else context

    # If identity prefix + base text fits, return as-is
    combined = identity_prefix + base_text
    if len(combined) <= max_chars:
        return combined if identity_prefix else base_text

    # Need to truncate
    first_kw = entry.get('keywords', ['?'])[0]
    suffix = f" ... [{_pf.push_call('lorebook', keywords=first_kw)} for full entry]"
    budget = max_chars - len(identity_prefix) - len(suffix)

    if budget <= 0:
        return identity_prefix.strip() + suffix

    truncated = base_text[:budget]
    last_period = truncated.rfind('. ')
    if last_period > budget * 0.5:
        truncated = truncated[:last_period + 1]
    else:
        last_space = truncated.rfind(' ')
        if last_space > budget * 0.5:
            truncated = truncated[:last_space]

    return identity_prefix + truncated + suffix


def _query_distillation_cache(present_chars, input_lower):
    """Look up cache entries relevant to the current scene.

    Returns a list of dict entries that match either:
    - A pair of present characters (relationship/history keys)
    - A character (slug >=3 chars) mentioned in the input

    Reads the cache file ONCE per call (via all_entries()) and resolves
    pair lookups against an in-memory dict to avoid 30+ file reads on
    multi-party scenes.
    """
    try:
        from hooks.hook_utils import normalize_topic_key, VALID_TOPIC_SUFFIXES
    except ImportError:
        from hook_utils import normalize_topic_key, VALID_TOPIC_SUFFIXES

    cache = _get_distillation_cache()

    # Single read: snapshot all entries, then index by topic_key for O(1) lookup
    all_entries = cache.all_entries()
    entries_by_key = {e.get("topic_key", ""): e for e in all_entries if e.get("topic_key")}

    hits = []
    seen_keys = set()

    # Try all pairwise relationships among present characters
    for i, a in enumerate(present_chars):
        for b in present_chars[i+1:]:
            for suffix in ("relationship", "history"):
                try:
                    key = normalize_topic_key([a, b], suffix)
                except ValueError:
                    continue
                entry = entries_by_key.get(key)
                if entry and key not in seen_keys:
                    hits.append(entry)
                    seen_keys.add(key)

    # Single-character identity facts for each present character (jobs/species/roles).
    for a in present_chars:
        try:
            key = normalize_topic_key([a], "identity")
        except ValueError:
            continue
        entry = entries_by_key.get(key)
        if entry and key not in seen_keys:
            hits.append(entry)
            seen_keys.add(key)

    # Input-mention scan: any participant slug (>=3 chars) appearing in input
    # The length gate prevents short slugs like "ka" or "ed" from substring-
    # matching incidental English text ("make", "okay", "edited", "needed").
    # NOTE: kept LAST deliberately — a 2026-06-06 experiment that prioritized
    # input-mention hits ballooned volume +17% (it pulls long relationship/history
    # nuggets in over short identity facts) for no ratio gain. Order is load-bearing.
    for entry in all_entries:
        key = entry.get("topic_key", "")
        if not key or key in seen_keys:
            continue
        parts = key.split("_")[:-1]  # drop suffix
        for part in parts:
            if len(part) >= 3 and part in input_lower:
                hits.append(entry)
                seen_keys.add(key)
                break

    return hits


def _render_relevant_canon_section(cache_hits):
    """Build the 'RELEVANT CANON' brief section from cache entries.

    NOTE: no longer called from check_canon (now delta-delivered per entry via
    _distillation_elements). Retained as the single-string rendering / test surface.
    """
    if not cache_hits:
        return ""
    lines = ["**RELEVANT CANON** (from distillation cache):"]
    for entry in cache_hits[:5]:  # Cap at 5 to keep brief surgical
        learning = entry.get("learning", "")
        lines.append(f"- _{entry.get('topic_key', '?')}_: {learning}")
    return "\n".join(lines)


# _check_canon_dedup / _check_canon_dedup_blocks removed 2026-06-07 (dead code,
# 0 production callers). Superseded by canon_delivery.py's element-level delta
# delivery, which is the live dedup mechanism wired into the check_canon tool.


_NPC_INJECT_STOPWORDS = {"dr", "dr.", "mr", "mr.", "mrs", "ms", "sir", "lord", "lady", "the", "a", "an", "of"}


@mcp.tool(
    annotations={"readOnlyHint": True, "idempotentHint": True},
    tags=_get_tool_tags("check_canon")
)
def check_canon(
    ctx: Context,
    user_input: str = Field(description="The user's message - REQUIRED before every response"),
    needs: list[str] = Field(default=[], description="Context blocks to load. Valid: voice, relationships, prep, npc_knowledge, threads, history, characters, lorebook_full. Use prep_npcs:<name> for absent NPC prep. Empty = regex auto-detect (backwards compatible). Union of your request + regex fallback."),
    auto_correct_prep: bool = Field(default=False, description="If True, automatically update Active Prep field when location/prep mismatch detected. Default False for safety.")
) -> str:
    """Reach for this WHEN the player says anything in-fiction — before every narrative response; only parenthetical "(meta)" or admin messages are exempt. Your memory is not canon; this tool is.

    CHECK BEFORE EVERY RESPONSE.
    Returns: character relationships, physical descriptions, scene context, active constraints, knowledge boundaries.

    Pass needs=['voice'] for quiet conversation, needs=['voice','relationships','lorebook_full'] for intimate scenes.
    Empty needs = auto-detect mode (same as before)."""

    # ========================================
    # TOKEN OPTIMIZATION: System Command Detection (Fix #2)
    # Skip expensive canon check for pure system/admin commands
    # ========================================
    # Import canonical admin pattern list (shared with hooks/turn_reset.py)
    from hooks.hook_utils import ADMIN_COMMAND_PATTERNS

    input_lower = user_input.lower().strip()

    # Check if this is a system command
    if any(pattern in input_lower for pattern in ADMIN_COMMAND_PATTERNS):
        # Return minimal context for system operations
        try:
            status_path = CAMPAIGN_DIR / "CURRENT_STATUS.md"
            location = "Unknown"
            day = 0

            if status_path.exists():
                with open(status_path, 'r', encoding='utf-8') as f:
                    status_content = f.read()

                # Extract location
                loc_match = re.search(r'\*\*Location:\*\*\s*(.+?)(?:\n|$)', status_content)
                if loc_match:
                    location = loc_match.group(1).strip()

                # Extract day
                day_match = re.search(r'\*\*Day:\*\*\s*(\d+)', status_content)
                if day_match:
                    day = int(day_match.group(1))

            return f"**SYSTEM COMMAND** (canon check skipped for efficiency)\n\n**Location:** {location}\n**Day:** {day}\n\n_System commands don't require narrative context._"
        except Exception as e:
            logging.debug(f"System command shortcut failed, falling through: {e}")

    # ========================================
    # OPTIMIZATION: Parse CURRENT_STATUS.md ONCE
    # Eliminates 5 redundant reads later in function
    # ========================================
    status_path = CAMPAIGN_DIR / "CURRENT_STATUS.md"
    status_content = ""
    status_parsed = {}

    if status_path.exists():
        try:
            status_content = status_path.read_text(encoding='utf-8')
            status_parsed = _parse_status_content(status_content)
        except Exception as e:
            logging.debug(f"CURRENT_STATUS parse failed (non-critical): {e}")

    lorebook_path = CAMPAIGN_DIR / "lorebook.json"

    if not lorebook_path.exists():
        return "lorebook.json not found"

    try:
        lorebook = _load_cached_json(lorebook_path, 'lorebook')
    except Exception as e:
        return f"Error reading lorebook: {str(e)}"

    # Check for *** scene recall flag
    scene_recall_triggered = user_input.strip().endswith('***')
    if scene_recall_triggered:
        clean_input = user_input.strip()[:-3].strip()
    else:
        clean_input = user_input

    # Normalize input for case-insensitive matching
    input_lower = clean_input.lower()

    hook_state = _read_hook_state()

    # ========================================
    # LOREBOOK KEYWORD MATCHING (always runs)
    # ========================================
    # Over-broad single tokens (e.g. "sun","soul","wound") pull faith/cult/world
    # entries in on incidental mention. An entry matched ONLY by one of these is a
    # "broad" (low-value) match: it does NOT count toward auto-FULL escalation and is
    # suppressed from the CONTEXT block unless lore is explicitly being asked for. An
    # entry that also matches a SPECIFIC keyword still surfaces normally.
    _BROAD_KW = {"sun", "soul", "wound", "black", "red", "white", "children", "court",
                 "death", "holy", "wisdom", "faith", "faiths", "cult", "cults", "god",
                 "gods", "religions", "factions", "type", "positive", "blood"}
    matches = []  # (entry, triggered_kw, is_specific)
    for entry in lorebook.get("entries", []):
        spec_kw = None
        broad_kw = None
        for keyword in entry.get("keywords", []):
            kw = keyword.lower().strip()
            if not kw:
                continue
            if re.search(rf'\b{re.escape(kw)}\b', input_lower):
                if kw in _BROAD_KW:
                    broad_kw = broad_kw or kw
                    continue  # keep scanning this entry for a specific keyword
                spec_kw = kw
                break
        if spec_kw:
            matches.append((entry, spec_kw, True))
        elif broad_kw:
            matches.append((entry, broad_kw, False))

    specific_matches = [m for m in matches if m[2]]

    # ── Book-lore base layer: shipped CH world facts (DM-facing RAG). ──
    # Campaign canon always wins: entries sharing ANY keyword with the
    # campaign lorebook are suppressed inside match_book_entries. Fail-open.
    book_matches = []
    try:
        # No fixed cache_key: default key = str(path), so a repointed
        # RULES_DATA_DIR (tests) can never serve a stale cached copy.
        _book_raw = _load_cached_json(
            RULES_DATA_DIR / "rulebook" / "lore_additions.json")
        _campaign_kws = {kw.lower().strip()
                         for e in lorebook.get("entries", [])
                         for kw in e.get("keywords", []) if isinstance(kw, str)}
        book_matches = book_lore.match_book_entries(
            book_lore.book_entries(_book_raw), input_lower, _campaign_kws, _BROAD_KW)
    except Exception:
        book_matches = []

    # ========================================
    # RESOLVE CONTEXT BLOCKS (needs + regex fallback)
    # ========================================
    # Only SPECIFIC matches count toward auto-FULL — incidental broad-token hits must
    # not flip a quiet scene into the full voice/relationships/rules load.
    regex_blocks, escalation_reasons = _build_regex_blocks(
        hook_state=hook_state,
        input_lower=input_lower,
        scene_recall_triggered=scene_recall_triggered,
        lorebook_match_count=len(specific_matches),
    )
    active_blocks = _resolve_canon_needs(needs=needs, regex_blocks=regex_blocks)
    lore_intent = ('lore_question' in escalation_reasons) or ('lorebook_full' in active_blocks)

    # Backwards compatibility: if needs is empty AND no regex triggered,
    # behave like old auto-light mode (lorebook + scene state only)
    auto_light_mode = len(active_blocks) == 0

    # Determine lorebook context depth
    use_full_lorebook = 'lorebook_full' in active_blocks

    # Build output
    result = []
    dedup_elements = []  # (section, key, content) routed through canon_delivery

    # NEW: Combat HUD injection
    combat_hud = _format_combat_hud()
    if combat_hud:
        result.append(combat_hud)
        result.append("")  # Blank line separator
    
    # Add scene recall instruction if triggered
    if scene_recall_triggered:
        result.append("Ã¢Å¡Â Ã¯Â¸Â **SCENE RECALL TRIGGERED (***)**")
        result.append("")
        result.append("Player has flagged this message for scene memory lookup.")
        result.append("**REQUIRED ACTION:** Use `conversation_search` with specific terms from their message before responding.")
        result.append(f"**Search the following:** \"{clean_input}\"")
        result.append("")
        result.append("---")
        result.append("")
    
    # Add lorebook matches — route bios through the delta filter (fold repeats to pointers).
    # Progressive disclosure: render SPECIFIC matches (capped); include broad/faith-cult
    # matches only when lore is explicitly being asked for.
    render_matches = list(specific_matches)
    if lore_intent:
        render_matches += [m for m in matches if not m[2]]
    # Book layer renders AFTER all campaign matches (campaign gets first claim
    # on the cap) and under its own sub-cap so lore never crowds out canon.
    BOOK_CONTEXT_CAP = 3
    _book_specific = [m for m in book_matches if m[2]][:BOOK_CONTEXT_CAP]
    render_matches += _book_specific
    if lore_intent:
        render_matches += [m for m in book_matches
                           if not m[2]][:BOOK_CONTEXT_CAP - len(_book_specific)]
    # Truthful only if a book line actually entered render_matches (before the
    # CONTEXT_CAP slice below) — otherwise the NO-MATCHES reminder gets wrongly
    # suppressed by a book match that rendered nothing (broad-only, no lore_intent).
    _book_rendered = bool(_book_specific) or (lore_intent and any(not m[2] for m in book_matches))
    CONTEXT_CAP = 8
    hidden_overflow = max(0, len(render_matches) - CONTEXT_CAP)
    render_matches = render_matches[:CONTEXT_CAP]
    broad_hidden = ((len(matches) - len(specific_matches)) + sum(1 for m in book_matches if not m[2])) if not lore_intent else 0

    if render_matches:
        # count header stays always-fresh; the per-entry bios below may fold to pointers
        hdr = f"**CONTEXT ({len(render_matches)} shown"
        if escalation_reasons:
            hdr += f", FULL: {escalation_reasons[0]}"
        notes = []
        if hidden_overflow:
            notes.append(f"+{hidden_overflow} more")
        if broad_hidden:
            notes.append(f"{broad_hidden} broad hidden — needs=['lorebook_full'] to load")
        if notes:
            hdr += "; " + ", ".join(notes)
        hdr += "):**"
        result.append(hdr)

        _rendered_context = []
        for match, _triggered_kw, _spec in render_matches:
            # Mode-controlled context depth: active_blocks=full context, auto-light=short_context
            if active_blocks:
                ctx = match.get('context', 'No context provided')
            else:
                ctx = match.get('short_context') or match.get('context', 'No context')

            # Smart-truncate long entries for token efficiency
            if len(ctx) > 500:
                ctx = _smart_truncate_lorebook_entry(match, max_chars=500)

            category = match.get('category', '?').upper()[:4]
            first_kw = match.get('keywords', ['?'])[0]
            status = match.get('status', '?')

            line = f"[{category}] **{first_kw}** ({status}): {ctx}"
            _rendered_context.append((first_kw, line))

        dedup_elements.extend(context_dedup_elements(_rendered_context))
    
    # Handle no matches - compact escalation reminder (native RAG first, ChromaDB second)
    if not matches and not _book_rendered:
        result.append("**NO MATCHES** - Use `search_previous_conversations` first (fast, recent sessions). If not found, try `conversation_search` (ChromaDB, older history). No match ≠ safe to generate.")

    # Also scan for geography context (travel times, distances)
    # Only fires when travel-related keywords appear to save tokens
    TRAVEL_KEYWORDS = [
        "far", "distance", "travel", "journey", "days", "how long",
        "get to", "reach", "way to", "route", "path", "head to",
        "go to", "from here", "miles", "hexes", "northeast", "northwest",
        "southeast", "southwest", "north", "south", "east", "west"
    ]
    if any(kw in input_lower for kw in TRAVEL_KEYWORDS):
        try:
            geo_locations = geography_system.scan_for_locations(clean_input)
            if geo_locations:
                result.append("")
                result.append(geography_system.format_context_injection(geo_locations))
        except Exception as e:
            logging.debug(f"Geography injection skipped: {e}")  # Not critical - continue without it

    # Site-feature injection (site-feature persistence): stamped features
    # resurface when their place is named or is the current location.
    try:
        _sf_block = _site_features_injection(clean_input)
        if _sf_block:
            result.append("")
            result.append(_sf_block)
    except Exception as e:
        logging.debug(f"Site-feature injection skipped: {e}")

    # Revealed-ledger injection (reveal discipline): on vault turns, boundary
    # of what the party actually knows.
    try:
        _rl_block = _revealed_ledger_injection()
        if _rl_block:
            result.append("")
            result.append(_rl_block)
    except Exception as e:
        logging.debug(f"Revealed-ledger injection skipped: {e}")

    # Standing-defenses injection (defenses-before-harm, 2026-07-19): on
    # vault/combat turns, protective items surface BEFORE harm is narrated.
    try:
        _sd_block = _standing_defenses_injection()
        if _sd_block:
            result.append("")
            result.append(_sd_block)
    except Exception as e:
        logging.debug(f"Standing-defenses injection skipped: {e}")

    # Faction standing injection (D1, 2026-06-13): surface REP when a faction is named.
    try:
        _fac_inject = _faction_injection_lines(user_input)
        if _fac_inject:
            result.append("")
            result.extend(_fac_inject)
    except Exception:
        pass  # Non-critical

    # ========================================
    # SPATIAL STATE INJECTION (scene-type-driven reflex — Phase 2)
    # Fires on the Scene Type the DM maintains, not on input keywords.
    # ========================================
    try:
        spatial = _inject_spatial_state(status_parsed)
        if spatial:
            result.append("")
            result.append(spatial)
    except Exception as e:
        logging.debug(f"Spatial-state block skipped: {e}")

    # ========================================
    # AUTO-INJECT RELATIONSHIPS FOR PRESENT CHARACTERS
    # Prevents hallucination of family relationships
    # ========================================
    present_names_raw = []  # Store raw names for relationship lookup
    try:
        # Using pre-parsed status data (status_content, status_parsed)
        if status_path.exists():
            status_content = status_path.read_text(encoding='utf-8')

            # Pre-parse Present and Scene Type (needed by prep injection below)
            present_match_early = re.search(r'\*\*Present:\*\*\s*(.+?)(?:\n|$)', status_content)
            present_names_early = [n.strip() for n in present_match_early.group(1).split(',')] if present_match_early else []
            scene_type_early_match = re.search(r'\*\*Scene Type:\*\*\s*(.+?)(?:\n|$)', status_content)
            scene_type_early = scene_type_early_match.group(1).strip() if scene_type_early_match else "unknown"

            # ========================================
            # SCENE STATE INJECTION (new format)
            # Injects: Location, Last Speaker, Last 3 Beats, Mood, Next, Arc, DM Knowledge, Emotional State
            # ========================================
            scene_state_lines = []
            _arc_value = None
            _emotion_value = None

            # Extract Location (for scene context)
            location_match = re.search(r'\*\*Location:\*\*\s*(.+?)(?:\n|$)', status_content)
            if location_match:
                scene_state_lines.append(f"**LOCATION:** {location_match.group(1).strip()}")

            # Extract Last Speaker (for dialogue continuity)
            speaker_match = re.search(r'\*\*Last Speaker:\*\*\s*(.+?)(?:\n|$)', status_content)
            if speaker_match:
                scene_state_lines.append(f"**LAST SPEAKER:** {speaker_match.group(1).strip()}")

            # Extract Last 3 Beats
            beats_match = re.search(r'\*\*Last 3 Beats:\*\*\s*\n((?:\d+\.\s*(?:(?!\*\*).)+(?:\n|$))*)', status_content)
            if beats_match:
                beats_text = beats_match.group(1).strip()
                # Safety: strip any field headers that leaked into beats; cap each
                # beat's length — RECENT BEATS ships every turn and the long tail
                # (some beats ran 480 chars) was pure continuity bloat.
                _beat_lines = []
                for line in beats_text.split("\n"):
                    if re.match(r'\*\*[A-Z]', line):
                        continue
                    if len(line) > 220:
                        line = line[:220].rsplit(' ', 1)[0] + "…"
                    _beat_lines.append(line)
                beats_text = "\n".join(_beat_lines)
                scene_state_lines.append("**RECENT BEATS:**")
                scene_state_lines.append(beats_text)

            # Extract Tension/Mood
            tension_match = re.search(r'\*\*Tension/Mood:\*\*\s*(.+?)(?:\n|$)', status_content)
            if tension_match:
                scene_state_lines.append(f"**MOOD:** {tension_match.group(1).strip()}")

            # Extract Next Expected
            next_match = re.search(r'\*\*Next Expected:\*\*\s*(.+?)(?:\n|$)', status_content)
            if next_match:
                scene_state_lines.append(f"**NEXT:** {next_match.group(1).strip()}")

            # Extract Arc Context (summary only, from CURRENT_STATUS.md - single source of truth)
            arc_match = re.search(r'\*\*Arc Tension:\*\*\s*(.+?)(?:\n|$)', status_content)
            if arc_match:
                _arc_value = f"**ARC:** {arc_match.group(1).strip()}"

            # Extract DM Knowledge section (secrets for DM eyes only)
            dm_section_match = re.search(r'## DM KNOWLEDGE.*?\n\n(.*?)(?=\n---|\n## |\Z)', status_content, re.DOTALL)
            if dm_section_match:
                dm_content = dm_section_match.group(1).strip()
                if dm_content:
                    scene_state_lines.append("")
                    scene_state_lines.append("**DM KNOWLEDGE (do not reveal):**")
                    # Only include first 500 chars to keep it compact
                    if len(dm_content) > 500:
                        dm_content = dm_content[:500] + "..."
                    scene_state_lines.append(dm_content)

            # Extract Emotional State if present
            # Try CURRENT_STATUS.md first, then scene_state/emotional_state.md
            emotion_match = re.search(r'## EMOTIONAL STATE.*?\n\n(.*?)(?=\n---|\n## |\Z)', status_content, re.DOTALL)
            if not emotion_match:
                emo_file = CAMPAIGN_DIR / "scene_state" / "emotional_state.md"
                if emo_file.exists():
                    emo_content = emo_file.read_text(encoding='utf-8')
                    emotion_match = re.search(r'## EMOTIONAL STATE.*?\n\n(.*?)(?=\n---|\n## |\Z)', emo_content, re.DOTALL)
            if emotion_match:
                emotion_content = emotion_match.group(1).strip()
                if emotion_content:
                    _emotion_value = emotion_content  # header reconstructed in scene_dedup_elements

            # ========================================
            # ACTIVE PREP FILE INJECTION
            # Reads prep file context to prevent hallucination of plot/locations
            # ========================================
            _do_prep_injection = 'prep' in active_blocks
            active_prep_match = re.search(r'\*\*Active Prep:\*\*\s*(.+?)(?:\n|$)', status_content) if _do_prep_injection else None
            if active_prep_match:
                prep_filename = active_prep_match.group(1).strip()
                # Gate on the normalizer's none-detection so all three prep
                # readers agree: empty / "none" / "(none)" (the sentinel the
                # campaign scaffolder writes) yields no candidates and thus no
                # injection AND no false UNRESOLVED scream on a prepless turn.
                if _normalize_prep_ref(prep_filename):
                    try:
                        # ONE shared resolver: normalizes the **Active Prep:**
                        # display label to the real file (or None). prep_filename
                        # (the raw label) stays alive for the auto-correct re.sub
                        # below. The core injection body — header, overview, prep
                        # rooms, ⛔ SECRETS, constraints, progress — lives in
                        # _prep_injection_lines; when the label resolves to no
                        # file that helper returns the fail-visible scream.
                        prep_path = _resolve_active_prep_path()
                        scene_type = scene_type_early
                        prep_content = (prep_path.read_text(encoding='utf-8')
                                        if prep_path is not None else "")
                        scene_state_lines.extend(
                            _prep_injection_lines(prep_filename, prep_path,
                                                  prep_content, scene_type))
                        if prep_path is not None:

                            # ========================================
                            # SURGICAL PREP READS — targeted section extraction
                            # Loads only sections relevant to current scene
                            # ========================================
                            try:
                                current_loc = location_match.group(1).strip() if location_match else ""
                                prep_sections, prep_manifest = _extract_prep_sections(
                                    prep_content=prep_content,
                                    location=current_loc,
                                    present_npcs=present_names_early,
                                    scene_type=scene_type,
                                )

                                # First-load: include FOR NEW CLAUDE section
                                if prep_filename not in _prep_first_load_done:
                                    prep_lines = prep_content.split('\n')
                                    new_claude = _get_section_by_header(prep_lines, r'^##\s*FOR NEW CLAUDE', max_chars=1500)
                                    if new_claude:
                                        scene_state_lines.append("")
                                        scene_state_lines.append(new_claude)
                                    _prep_first_load_done.add(prep_filename)

                                for section_text in prep_sections:
                                    if section_text:
                                        scene_state_lines.append("")
                                        scene_state_lines.append(section_text)

                                if prep_manifest:
                                    scene_state_lines.append(f"_Prep sections loaded: {', '.join(prep_manifest)}_")
                                    scene_state_lines.append("_Use files(action='read') for additional detail._")
                            except Exception as e:
                                logging.debug(f"Surgical prep reads skipped: {e}")

                            # ========================================
                            # LOCATION/PREP VALIDATION (Phase 1: Warnings, Phase 2: Auto-correction)
                            # Detect mismatches between location and prep file
                            # ========================================
                            try:
                                location_registry_path = CAMPAIGN_DIR / "LOCATION_REGISTRY.json"
                                if location_registry_path.exists() and location_match:
                                    registry = json.loads(location_registry_path.read_text(encoding='utf-8'))
                                    current_location = location_match.group(1).strip()

                                    # Check both locations and aliases
                                    expected_prep = None
                                    for loc_name, prep_file in registry.get("locations", {}).items():
                                        if loc_name.lower() in current_location.lower():
                                            expected_prep = prep_file
                                            break

                                    if not expected_prep:
                                        for alias, prep_file in registry.get("aliases", {}).items():
                                            if alias.lower() in current_location.lower():
                                                expected_prep = prep_file
                                                break

                                    # Compare expected vs actual. Use the
                                    # RESOLVED filename (prep_path.name), not the
                                    # raw display label — the registry stores
                                    # clean filenames, so comparing against the
                                    # label (with its parenthetical) would never
                                    # match and would false-positive every turn.
                                    if expected_prep and expected_prep != prep_path.name:
                                        if auto_correct_prep:
                                            # Phase 2: Auto-correction enabled
                                            try:
                                                status_path = CAMPAIGN_DIR / "CURRENT_STATUS.md"
                                                status_text = status_path.read_text(encoding='utf-8')

                                                # Update Active Prep field
                                                updated_text = re.sub(
                                                    r'\*\*Active Prep:\*\*\s*' + re.escape(prep_filename),
                                                    f'**Active Prep:** {expected_prep}',
                                                    status_text
                                                )

                                                status_path.write_text(updated_text, encoding='utf-8')

                                                # Log the correction
                                                logging.info(f"AUTO-CORRECTED Active Prep: {prep_filename} → {expected_prep}")

                                                scene_state_lines.append("")
                                                scene_state_lines.append("🔧 **AUTO-CORRECTED ACTIVE PREP:**")
                                                scene_state_lines.append(f"   Location: '{current_location}'")
                                                scene_state_lines.append(f"   Changed: {prep_filename} → {expected_prep}")
                                                scene_state_lines.append(f"   CURRENT_STATUS.md updated automatically")
                                                scene_state_lines.append("   _Note: Call check_canon() again to load new prep context_")
                                            except Exception as update_err:
                                                logging.error(f"Auto-correction failed: {update_err}")
                                                scene_state_lines.append("")
                                                scene_state_lines.append("❌ **AUTO-CORRECTION FAILED:**")
                                                scene_state_lines.append(f"   Error: {update_err}")
                                                scene_state_lines.append("   Manual update required - see PREP_CHANGE_PROCEDURE.md")
                                        else:
                                            # Phase 1: Warning only
                                            scene_state_lines.append("")
                                            scene_state_lines.append("⚠️  **LOCATION/PREP MISMATCH DETECTED:**")
                                            scene_state_lines.append(f"   Location mentions '{current_location}'")
                                            scene_state_lines.append(f"   Expected prep: {expected_prep}")
                                            scene_state_lines.append(f"   Active prep: {prep_filename}")
                                            scene_state_lines.append("   **ACTION REQUIRED:** Update Active Prep field in CURRENT_STATUS.md")
                                            scene_state_lines.append("   See PREP_CHANGE_PROCEDURE.md for correct procedure")
                                            scene_state_lines.append("   _Or call check_canon() with auto_correct_prep=True_")
                            except Exception as e:
                                logging.debug(f"Location validation skipped: {e}")

                            scene_state_lines.append("_Targeted prep loaded. Use files(action='read') for additional detail._")
                    except Exception as e:
                        logging.debug(f"Prep file injection skipped: {e}")

            # ========================================
            # TARGETED NPC PREP (prep_npcs:<name>)
            # ========================================
            prep_npc_requests = [b for b in active_blocks if b.startswith('prep_npcs:')]
            if prep_npc_requests:
                try:
                    active_prep_match_targeted = re.search(r'\*\*Active Prep:\*\*\s*(.+?)(?:\n|$)', status_content)
                    if active_prep_match_targeted:
                        prep_filename_targeted = active_prep_match_targeted.group(1).strip()
                        prep_path_targeted = CAMPAIGN_DIR / prep_filename_targeted
                        if prep_path_targeted.exists():
                            prep_content_targeted = prep_path_targeted.read_text(encoding='utf-8')
                            prep_lines_targeted = prep_content_targeted.split('\n')

                            for block_name in prep_npc_requests:
                                npc_name = block_name.split(':', 1)[1]
                                found = False
                                for ii, pline in enumerate(prep_lines_targeted):
                                    m = re.match(r'^###\s*NPC:\s*(.+?)(?:\((.+?)\))?\s*$', pline.strip())
                                    if m:
                                        npc_full = m.group(1).strip()
                                        npc_alias = m.group(2).strip() if m.group(2) else ""
                                        if (npc_name.lower() in npc_full.lower() or
                                            npc_name.lower() in npc_alias.lower() or
                                            npc_full.lower() in npc_name.lower()):
                                            section = _get_section_by_header(prep_lines_targeted[ii:], r'^###', max_chars=1200)
                                            if section:
                                                scene_state_lines.append("")
                                                scene_state_lines.append(f"**TARGETED NPC PREP ({npc_name}):**")
                                                scene_state_lines.append(section)
                                                found = True
                                            break
                                if not found:
                                    scene_state_lines.append(f"_No prep section found for {npc_name} in {prep_filename_targeted}._")

                            # Extract secrets mentioning requested NPCs
                            dm_secrets = _extract_dm_only_secrets(prep_content_targeted)
                            if dm_secrets:
                                npc_names_lower = [b.split(':', 1)[1].lower() for b in prep_npc_requests]
                                relevant_secrets = [s for s in dm_secrets if any(n in s.lower() for n in npc_names_lower)]
                                if relevant_secrets:
                                    scene_state_lines.append("")
                                    scene_state_lines.append("**\u26d4 SECRETS (related to requested NPC):**")
                                    for secret in relevant_secrets[:3]:
                                        scene_state_lines.append(f"- {secret}")
                except Exception as e:
                    logging.debug(f"Targeted NPC prep skipped: {e}")

            dedup_elements.extend(scene_dedup_elements(arc=_arc_value, emotional_state=_emotion_value))

            # Insert scene state at the very top if we found anything
            if scene_state_lines:
                scene_state_lines.append("")
                result.insert(0, "\n".join(scene_state_lines))

            # Extract characters_present from SCENE CONTEXT or IMMEDIATE STATUS
            present_match = re.search(r'\*\*Present:\*\*\s*(.+?)(?:\n|$)', status_content)
            if present_match:
                present_str = present_match.group(1).strip()
                # Parse comma-separated names - keep raw for relationship lookup
                present_names_raw = [name.strip() for name in present_str.split(',')]
                present_names = [name.lower() for name in present_names_raw]

                # ========================================
                # RELATIONSHIP INJECTION (deduplicated matrix)
                # ========================================
                relationship_matrix_path = CAMPAIGN_DIR / "RELATIONSHIP_MATRIX.json"
                if 'relationships' in active_blocks and relationship_matrix_path.exists():
                    try:
                        rel_matrix = _load_cached_json(relationship_matrix_path, 'relationships')

                        # Use module-level RELATIONSHIP_INVERSE_TYPE constant
                        # (Moved to module level to avoid recreating on every call)

                        # Find which matrix characters match present characters
                        matched_chars = set()
                        for present_name in present_names_raw:
                            for matrix_char in rel_matrix.keys():
                                if matrix_char.startswith('_'):
                                    continue
                                present_lower = present_name.lower()
                                matrix_lower = matrix_char.lower()
                                if present_lower in matrix_lower or matrix_lower in present_lower:
                                    matched_chars.add(matrix_char)
                                for part in present_name.split('/'):
                                    if part.strip().lower() in matrix_lower:
                                        matched_chars.add(matrix_char)

                        # Build full relationship map (including inverses)
                        all_rels = {}  # char -> {other: type}
                        for char, relationships in rel_matrix.items():
                            if char.startswith('_') or not isinstance(relationships, dict):
                                continue
                            for other, rel_data in relationships.items():
                                if not isinstance(rel_data, dict):
                                    continue
                                rel_type = rel_data.get("type", "?")
                                # Store direct
                                all_rels.setdefault(char, {})[other] = rel_type
                                # Store inverse using module-level constant
                                inv_type = RELATIONSHIP_INVERSE_TYPE.get(rel_type, rel_type)
                                all_rels.setdefault(other, {})[char] = inv_type

                        # Build per-character relationship elements (delta-delivered)
                        if matched_chars:
                            rel_lines_by_char = {}
                            for char in sorted(matched_chars):
                                if char in all_rels:
                                    rels = [f"{o}={t}" for o, t in all_rels[char].items()]
                                    rel_lines_by_char[char] = f"{char}: {', '.join(rels)}"
                            dedup_elements.extend(
                                _relationship_elements(sorted(matched_chars), rel_lines_by_char)
                            )
                    except Exception as e:
                        logging.debug(f"Relationship injection failed: {e}")

                # ========================================
                # RELATIONSHIP STORE INJECTION (C29)
                # Surface the relationship() TOOL store when BOTH entities of a
                # stored pair are present, so engine-recorded status changes
                # resurface without the DM remembering to pull. Separate from the
                # hand-maintained matrix above; one line + a pull handle per pair.
                # ========================================
                if 'relationships' in active_blocks:
                    try:
                        dedup_elements.extend(
                            _relationship_store_present_lines(present_names_raw)
                        )
                    except Exception as e:
                        logging.debug(f"Relationship store injection failed: {e}")

                # ========================================
                # CONVERSATIONAL-HOP INJECTION
                # Present characters may discuss absent characters.
                # Inject short lorebook context for relationship targets
                # not currently in the scene. Prevents fabrication when
                # NPCs reference absent characters in dialogue.
                # ========================================
                try:
                    if matched_chars and 'relationships' in active_blocks:
                        hop_targets = set()
                        for present_char in matched_chars:
                            if present_char in all_rels:
                                for target_name in all_rels[present_char].keys():
                                    if target_name not in matched_chars:
                                        hop_targets.add(target_name)

                        if hop_targets:
                            already_matched_kws = set(kw for _e, kw, _s in matches)
                            hop_items = []  # (target, hop_ctx)

                            for target in sorted(hop_targets):
                                target_lower = target.lower()
                                for entry in lorebook.get("entries", []):
                                    if entry.get("category") not in ("people", "knowledge_boundary"):
                                        continue
                                    entry_kws = [k.lower() for k in entry.get("keywords", [])]
                                    if any(target_lower in kw or kw in target_lower for kw in entry_kws):
                                        if not any(kw in already_matched_kws for kw in entry_kws):
                                            hop_ctx = entry.get("short_context") or entry.get("context", "")
                                            if hop_ctx and len(hop_ctx) > 20:
                                                if len(hop_ctx) > 250:
                                                    hop_ctx = hop_ctx[:250].rsplit(' ', 1)[0] + "..."
                                                hop_items.append((target, hop_ctx))
                                        break

                            for npc_name, npc_blurb in hop_items[:5]:
                                dedup_elements.append(
                                    ("CONVCTX", f"convctx:{npc_name.strip()}",
                                     f"- **{npc_name}:** {npc_blurb}")
                                )
                except Exception:
                    pass

                # ========================================
                # RULES IN PLAY — present characters' mechanical rules (rule_refs)
                # Only on full canon checks (active_blocks non-empty); idle turns stay quiet.
                # ========================================
                if active_blocks:
                    try:
                        dedup_elements.extend(
                            _rules_in_play_elements(
                                present_names_raw, lorebook, _load_rules_index()
                            )
                        )
                    except Exception as e:
                        logging.debug(f"Rules-in-play injection failed: {e}")

                # ========================================
                # CHARACTER DATA INJECTION (appearance/physiology/motivation)
                # Only for present characters, to ground descriptions and roleplay
                # ========================================
                if 'characters' in active_blocks:
                    try:
                        # Load character data (split-file-first pattern)
                        chars_dir = CAMPAIGN_DIR / "characters"
                        meta_path = chars_dir / "_meta.json"

                        char_data = None
                        if chars_dir.exists() and meta_path.exists():
                            # Use split file structure - glob all character files
                            char_data = {'characters': {}}
                            for p in sorted(chars_dir.glob("*.json")):
                                if p.name == "_meta.json":
                                    continue
                                # Cache each character file individually
                                char_data['characters'][p.stem] = _load_cached_json(p, f'char_{p.stem}')

                        if char_data is None:
                            # Split sheets are the sole source; monolithic fallback retired.
                            char_data = {'characters': {}}

                            char_lines = []
                            for char_id, char in char_data.get("characters", {}).items():
                                # Skip non-PC entries like "crawler"
                                if char.get("type") == "vehicle":
                                    continue

                                char_name = char.get("name", "").lower()
                                # Check if this character is present
                                is_present = False
                                for present_name in present_names:
                                    # Match on name or any part of compound names (e.g., "Brek/AUGUR")
                                    if present_name in char_name or char_name in present_name:
                                        is_present = True
                                        break
                                    for part in char_name.split('/'):
                                        if part.strip() in present_name or present_name in part.strip():
                                            is_present = True
                                            break
                                    for part in present_name.split('/'):
                                        if part.strip() in char_name:
                                            is_present = True
                                            break

                                if is_present:
                                    # Extract the new fields if they exist
                                    appearance = char.get("appearance", "")
                                    physiology = char.get("physiology", "")
                                    motivation = char.get("motivation", "")
                                    pronouns = char.get("pronouns", "")

                                    if appearance or physiology or motivation:
                                        name = char.get("name", char_id)
                                        parts = []
                                        if pronouns:
                                            parts.append(f"({pronouns})")
                                        if appearance:
                                            parts.append(appearance)
                                        if physiology:
                                            parts.append(physiology)
                                        if motivation:
                                            parts.append(f"Wants: {motivation}")

                                        char_lines.append(f"**{name}** " + " ".join(parts))

                            if char_lines:
                                result.insert(0, "\n".join(["**PRESENT CHARACTERS:**"] + char_lines + [""]))
                    except Exception:
                        pass  # Character injection not critical

                # ========================================
                # VOICE GUIDE INJECTION (selective, for present characters)
                # Loads only relevant sections of VOICE.md — replaces
                # the legacy @VOICE.md import which loaded the full file every turn.
                # ========================================
                if 'voice' in active_blocks:
                    try:
                        dedup_elements.extend(load_voice_guide_sections_for(present_names_raw))
                    except Exception:
                        pass  # Voice injection not critical

                # Track which NPCs were covered this turn (for stop hook verification)
                try:
                    covered_npcs = set(present_names_raw)
                    try:
                        if hop_targets:
                            covered_npcs.update(hop_targets)
                    except NameError:
                        pass
                    if HOOK_STATE_FILE.exists():
                        with _hook_state_lock():
                            hs = _read_hook_state()
                            hs["injected_npcs"] = list(covered_npcs)
                            _write_hook_state(hs)
                except Exception:
                    pass

                # ========================================
                # KNOWLEDGE BOUNDARIES
                # ========================================
                if 'npc_knowledge' in active_blocks:
                    # Find knowledge_boundary entries for present characters
                    boundary_matches = []
                    already_matched_ids = set(id(m) for m in matches)  # Don't double-inject

                    for entry in lorebook.get("entries", []):
                        if entry.get("category") == "knowledge_boundary":
                            # Skip if already matched via keyword
                            if id(entry) in already_matched_ids:
                                continue

                            # Check if any keyword matches a present character
                            entry_keywords = [kw.lower() for kw in entry.get("keywords", [])]
                            for present_name in present_names:
                                # Match if character name appears in entry keywords
                                if any(present_name in kw or kw in present_name for kw in entry_keywords):
                                    boundary_matches.append(entry)
                                    break

                    # Inject boundary context
                    if boundary_matches:
                        result.append("")
                        result.append("**KNOWLEDGE BOUNDARIES (auto-injected from scene presence):**")
                        result.append("")
                        for entry in boundary_matches:
                            result.append(f"{entry.get('context', '')}")
                            result.append("")
    except Exception:
        pass  # Injection not critical - continue without it

    # ========================================
    # ACTIVE CONSTRAINTS (session-added via constraint(action="add"))
    # C28: the old LOCATION KNOWLEDGE SCOPE block here was gated on
    # GAME_STATE["active_location"], which has no writer since the location-tool
    # retirement (c1f3744) — so its revealed-secrets rendering was permanently
    # dead code. Retired that dead branch; kept only the session-constraint
    # rendering, now ungated so constraint(action="add") entries actually surface.
    # (Prep-authored constraints surface in the prep-injection block above.)
    # ========================================
    if 'npc_knowledge' in active_blocks and GAME_STATE.get("active_constraints"):
        try:
            _sess_cons = [c for c in GAME_STATE["active_constraints"].values()
                          if c.get("scope", "party_known") == "party_known"]
            if _sess_cons:
                result.append("")
                result.append("**⛓ ACTIVE CONSTRAINTS:**")
                for c in _sess_cons:
                    result.append(f"- {c.get('subject', '?')}: {c.get('limitation', '?')}")
                result.append(
                    "→ constraint(action=\"check\", subject=\"<X>\") before a PC acts against "
                    "a limit; constraint(action=\"add\", ...) when a new one emerges.")
        except Exception:
            pass  # Constraint injection not critical

    # ========================================
    # NPC KNOWLEDGE SCOPE INJECTION
    # When NPC name appears in user input, inject what they know (not secrets)
    # ========================================
    # Load NPC states once for both injection and recommendations
    npc_data = None
    try:
        npc_states_path = CAMPAIGN_DIR / "npc_states.json"
        if npc_states_path.exists():
            with open(npc_states_path, 'r', encoding='utf-8') as f:
                npc_data = json.load(f)
    except Exception:
        pass  # NPC load not critical

    # Process NPC injection whenever a roster NPC is NAMED in the input.
    # Promoted out of the npc_knowledge active-block gate (spec 3c): the
    # name-match below is the real, deterministic trigger. Self-gates to
    # empty when no NPC is named, so cost stays bounded (1-2 NPCs/scene).
    if npc_data:
        try:
            matched_npcs = []
            for npc_id, npc in npc_data.get("npcs", {}).items():
                npc_name = npc.get("name", "").lower()
                # Match NPC name in user input (word-boundary, harmonized with the gate)
                if npc_name and re.search(rf"\b{re.escape(npc_name)}\b", input_lower):
                    matched_npcs.append((npc_id, npc))
                else:
                    # Fall back to first name only, skipping honorifics/stopwords
                    _first = npc_name.split()[0] if npc_name else ""
                    if (len(_first) >= 3 and _first not in _NPC_INJECT_STOPWORDS
                            and re.search(rf"\b{re.escape(_first)}\b", input_lower)):
                        matched_npcs.append((npc_id, npc))

            if matched_npcs:
                result.append("")
                result.append("**NPC KNOWLEDGE SCOPE:**")
                for npc_id, npc in matched_npcs:
                    name = npc.get("name", "?")
                    knows = npc.get("knows", [])
                    disposition = npc.get("disposition", "neutral")
                    if knows:
                        knows_str = "; ".join(knows[:4])  # Limit to 4 items
                        if len(knows) > 4:
                            knows_str += f" (+{len(knows)-4} more)"
                        result.append(f"- **{name}** ({disposition}): Knows: {knows_str}")
                    else:
                        result.append(f"- **{name}** ({disposition}): No specific knowledge tracked")
                    # --- living-dossier continuity (spec 3c) ---
                    left_off = (npc.get("left_off") or "").strip()
                    if left_off:
                        result.append(f"  ↪ Left off: {left_off}")
                    open_purpose = (npc.get("open_purpose") or "").strip()
                    if open_purpose:
                        result.append(f"  ⊙ Open purpose: {open_purpose}")
                    cwa = npc.get("changed_while_away")
                    if isinstance(cwa, dict) and not cwa.get("surfaced", False):
                        note = (cwa.get("note") or "").strip()
                        if note:
                            result.append(f"  ⚠ Changed while away (surface in fiction): {note}")
                    # Heartbeat crossings (Slice B): if this person sits in a
                    # live tangle, co-locate it here -- the loud, in-scene
                    # channel. Engine forwards facts; the DM judges + sets volume.
                    try:
                        _cx_slug = npc_id
                        for _cx_block in _crossing_blocks_for_npc(_cx_slug):
                            result.append("  " + _cx_block.replace("\n", "\n  "))
                    except Exception:
                        pass
                    # Parley ride-along (Task 7): if this NPC is a party to an open
                    # negotiation, co-locate a compact PARLEY line here -- keyed by the
                    # display NAME (parley parties store display names; find_by_npc is a
                    # case-insensitive name match), not the roster slug the crossings use.
                    try:
                        import social_system as _ss
                        for _pl_block in _ss.parley_blocks_for_npc(CAMPAIGN_DIR, name)[:2]:
                            result.append("  " + _pl_block.replace("\n", "\n  "))
                    except Exception:
                        pass
                result.append("_NPC secrets hidden - use npc() tool for DM view_")
                result.append("")
        except Exception:
            pass  # NPC injection not critical

    # Antagonist trigger injection (spec 2026-06-18): surface a cultivated seed
    # when its trigger keyword is named in play. Engine surfaces; DM judges. Non-critical.
    try:
        for _at_block in _antagonist_trigger_blocks(input_lower):
            result.append(_at_block)
    except Exception:
        pass

    # ========================================
    # ACTIVE NARRATIVE THREADS INJECTION
    # When thread keywords appear in user input, inject thread context
    # ========================================
    # Thread keyword-match runs EVERY turn (ungated). Ordinary-play regex paths
    # never add 'threads' to active_blocks, so the old `if 'threads' in
    # active_blocks` gate silently suppressed all thread surfacing outside
    # lore/high-match turns. Factions and site-features already inject
    # unconditionally; threads now match the same way. The keyword match itself
    # is the real gate; cap 2 + the canon_delivered delta-dedup fold (these go
    # through dedup_elements) keep repeats from re-shipping.
    try:
        threads_path = CAMPAIGN_DIR / "narrative_threads.json"
        if threads_path.exists():
            threads_data = _load_cached_json(threads_path, 'threads')
            dedup_elements.extend(
                _thread_injection_elements(threads_data, input_lower, present_names_raw))
    except Exception:
        pass  # Thread injection not critical

    # ============================================================
    # DISTILLATION CACHE INJECTION
    # Cache hits become the RELEVANT CANON section of the brief
    # Consulted BEFORE ChromaDB history drilling
    # ============================================================
    _cache_nugget_keys = set()  # topic_keys rendered by the cache lane this call
    try:
        cache_hits = _query_distillation_cache(
            present_chars=present_names_raw,
            input_lower=input_lower,
        )
        distill_items = []
        for entry in cache_hits[:5]:  # cap 5, mirrors _render_relevant_canon_section
            tk = entry.get("topic_key", "?")
            learning = entry.get("learning", "")
            if _is_placeholder_nugget(learning):
                continue  # drop empty/<UNKNOWN> nuggets (shipped every turn, zero signal)
            distill_items.append((tk, f"- _{tk}_: {learning}"))
            _cache_nugget_keys.add(tk)  # so the semantic lane can skip cross-lane dups
        dedup_elements.extend(_distillation_elements(distill_items, "DISTILLATIONS", "distill"))
    except Exception as e:
        logging.debug(f"Distillation cache injection skipped: {e}")

    # ========================================
    # DETECT ACTIVE PREP FILE from CURRENT_STATUS.md
    # ========================================
    active_prep = None
    # Use pre-parsed status data
    active_prep = status_parsed.get('active_prep')
    if active_prep == 'None':
        active_prep = None

    # ========================================
    # CHROMADB VECTOR SEARCH (semantic history)
    # Uses user_input to find relevant past events
    # If active_prep is set, also queries prep file chunks
    # Runs in both auto-light (tier 1) and full (progressive) modes; always runs.
    # ========================================
    # Task 2 item 1: track when the semantic (vector) lane is skipped or fails so
    # the OUTPUT can carry a visible degradation marker. Fail-open — this never
    # blocks or raises; the DM just KNOWS history recall was offline this turn.
    _semantic_offline_reason = None
    if True:  # ChromaDB: always runs (tier-1 for auto-light, progressive for blocks)
        try:
            # Build query from user input, grounded in the current scene.
            query = user_input.strip()
            # Task 2 item 2: always run the semantic leg — the old `len(query) > 20`
            # skip gave terse actions ("attack the ghoul") ZERO history recall.
            if query:
                # Task 2 items 2+3: enrich short/vague inputs with scene grounding
                # (current location + present names, already loaded above — no new
                # file reads). Replaces the dead _enhance_query_with_context
                # (empty _CHARACTER_TRAITS, deleted this pass).
                enhanced_query = query
                if len(query) < 40:
                    _scene_terms = []
                    _loc = (status_parsed.get('location') or '').strip()
                    if _loc and _loc.lower() not in ('?', 'unknown'):
                        _scene_terms.append(_loc)
                    for _nm in present_names_raw[:4]:
                        _nm = (_nm or '').strip()
                        if _nm and _nm.lower() not in query.lower():
                            _scene_terms.append(_nm)
                    if _scene_terms:
                        enhanced_query = f"{query} {' '.join(_scene_terms)}"
                # v3: append matched lorebook entity keywords so the embedding
                # query lands in the same register as the stored nuggets
                # (validated to lift recall — see docs/superpowers specs).
                try:
                    if matches:
                        _kw_terms = " ".join(kw for _e, kw, _s in specific_matches[:6])
                        if _kw_terms:
                            enhanced_query = f"{enhanced_query} {_kw_terms}"
                except NameError:
                    pass
                # Get embedding (uses LRU cache for repeated queries)
                try:
                    query_embedding = get_embedding_cached(enhanced_query)
                except Exception as e:
                    logging.warning(f"Ollama embedding failed, skipping ChromaDB: {e}")
                    query_embedding = None
                if query_embedding is None:
                    # Task 2 item 1: embedding unavailable → no semantic recall this turn.
                    _semantic_offline_reason = _semantic_offline_reason or "embedding unavailable"

                if query_embedding is not None:
                    # Query the canon_distillations collection FIRST (cheapest, highest-quality)
                    distillation_hits = []
                    try:
                        dist_collection = get_canon_distillations_collection()
                        if dist_collection.count() > 0:
                            STRONG_DIST, _ = _chroma_thresholds(dist_collection)
                            dist_results = dist_collection.query(
                                query_embeddings=[query_embedding],
                                n_results=10,  # v3: wider pool so the lexical re-rank has candidates
                            )
                            _cands = list(zip(
                                dist_results["documents"][0],
                                dist_results["metadatas"][0],
                                dist_results["distances"][0],
                            ))
                            # v3: lexical boost (exact query-term matches) BEFORE the
                            # threshold gate, so a keyword-exact nugget that was just
                            # over threshold can still surface.
                            _cands = _apply_keyword_boost(_cands, query)
                            for doc, meta, dist in _cands:
                                if dist <= STRONG_DIST:
                                    distillation_hits.append((doc, meta, dist))
                    except Exception as e:
                        logging.debug(f"canon_distillations query skipped: {e}")

                    if distillation_hits:
                        # Strong distillation hits replace raw-history drilling
                        idistill_items = []
                        for doc, meta, dist in distillation_hits[:5]:  # v3: denser library, surface a few more
                            tk = meta.get("topic_key", "?")
                            if _is_placeholder_nugget(doc):
                                continue
                            if tk in _cache_nugget_keys:
                                continue  # already surfaced by the cache lane — no cross-lane dup
                            idistill_items.append((tk, f"- _{tk}_: {doc}"))
                        dedup_elements.extend(
                            _distillation_elements(idistill_items, "INGESTED", "idistill")
                        )
                    else:
                        # No good distillation hits — fall through to raw history tiers
                        try:
                            collection = get_chroma_collection("campaign_history_tiered")
                        except Exception:
                            # Task 2 item 1: history collection unavailable — record a
                            # clean reason, then let it propagate to the fail-open outer
                            # handler (which keeps this reason and logs).
                            _semantic_offline_reason = "history collection unavailable"
                            raise
                        GOOD_MATCH, WEAK_MATCH = _chroma_thresholds(collection)

                        if active_blocks:
                            all_chroma_results, _tier_reached, _ = _progressive_tier_search(
                                collection, query_embedding, max_tier=3, n_results_per_tier=3
                            )
                        else:
                            # Auto-light mode: tier 1 only
                            _tier_reached = 1
                            try:
                                tier_results = _search_single_tier(
                                    collection, query_embedding, 1, {}, 3
                                )
                                all_chroma_results = [
                                    (d, m, dist) for d, m, dist in tier_results if dist <= WEAK_MATCH
                                ]
                            except Exception:
                                all_chroma_results = []

                        # Task 4 (RAG hardening sprint): BM25 lexical lane, fused into the
                        # vector results by Reciprocal Rank Fusion — before recency (this
                        # lane has no keyword-boost step, see the Task 3 note below).
                        #
                        # Candidate pool tier filter, per branch:
                        #   - auto-light (not active_blocks): pinned to tier 1, deliberately
                        #     (that mode only ever searches tier 1).
                        #   - progressive (active_blocks): _progressive_tier_search can
                        #     return "sufficient" (one tier), "drill_recommended"
                        #     (accumulated weak matches from SEVERAL tiers, 1..3, with
                        #     tier_reached==3), or "no_match" (empty, tier_reached==3).
                        #     Filtering BM25 to the single tier_reached value therefore
                        #     hid tier-1/2 exact-name rescues in exactly the cases this
                        #     lane exists for (drill_recommended's earlier tiers, and
                        #     no_match's total vector miss). Filter to the SET of tiers
                        #     actually present in the vector results instead; when the
                        #     vector lane came back empty (no_match), don't tier-filter
                        #     at all and let RRF + downstream keyword-boost/recency sort
                        #     it out.
                        #
                        # Best-effort: a BM25 failure here falls back to vector-only with
                        # a log line — it must NEVER trip the SEMANTIC RECALL OFFLINE
                        # marker (that marker is reserved for BOTH lanes failing, via the
                        # outer except below).
                        if active_blocks:
                            if all_chroma_results:
                                _vector_tiers = {str(m.get('tier')) for _d, m, _dist in all_chroma_results}
                                _lex_filter_fn = lambda m, _tiers=_vector_tiers: str(m.get('tier')) in _tiers
                            else:
                                _lex_filter_fn = None
                        else:
                            _lex_filter_fn = lambda m, _t=_tier_reached: str(m.get('tier')) == str(_t)

                        try:
                            _lex_index = lexical_lane.get_or_build_index(collection)
                            _lex_hits = lexical_lane.search(
                                _lex_index, query, top_k=20,
                                filter_fn=_lex_filter_fn,
                            )
                            if _lex_hits:
                                all_chroma_results = lexical_lane.fuse_lexical_into_vector(
                                    all_chroma_results, _lex_hits,
                                    weak_match_dist=WEAK_MATCH, max_results=20,
                                )
                        except Exception as _lex_exc:
                            logging.warning(f"BM25 lexical lane failed (check_canon): {_lex_exc}")

                        # Task 3 (RAG hardening sprint): recency re-rank — raw-history
                        # lane only (the distillations lane above is curated/current by
                        # construction and untouched). No keyword-boost step runs in
                        # this lane, so recency is the only re-rank applied here.
                        all_chroma_results = _apply_recency_weight(
                            all_chroma_results, status_parsed.get('day') or None,
                            good_match_threshold=GOOD_MATCH
                        )

                        if all_chroma_results:
                            result.append("")
                            mode_label = "PROGRESSIVE" if active_blocks else "TIER 1"
                            result.append(f"**RELEVANT HISTORY** _({mode_label} search)_:")
                            result.append("")
                            for doc, meta, dist in all_chroma_results:
                                if len(doc) > 800:
                                    doc = doc[:800] + "...[truncated]"
                                day = meta.get('day', '?')
                                arc = meta.get('arc', '')
                                tier_num = meta.get('tier', '?')
                                arc_info = f" ({arc})" if arc else ""
                                result.append(f"**Day {day}{arc_info} [T{tier_num}]:**\n{doc}")
                                result.append("---")
                            result.append("")

        except Exception as _sem_exc:
            # Task 2 item 1: the semantic lane is best-effort — a failure here must
            # NEVER block the brief. Record WHY (unless a leg already named it) so the
            # OUTPUT can carry the degradation marker; the DM then knows recall was off.
            if _semantic_offline_reason is None:
                _semantic_offline_reason = "semantic lane error"
            logging.warning(f"check_canon semantic lane failed: {_sem_exc}")

    # Task 2 item 1: surface semantic-recall degradation in the OUTPUT (fail-open —
    # never blocks). The structural scaffold below is unchanged, so spoiler_check's
    # validation still passes and the gate still opens; the DM just KNOWS not to read
    # an empty history lane as "no canon exists."
    if _semantic_offline_reason:
        result.append(
            f"⚠ SEMANTIC RECALL OFFLINE this turn ({_semantic_offline_reason}) — "
            "lorebook/state lanes only; do not treat absence of history as absence of canon."
        )

    # ========================================
    # SCENE HEADER
    # ========================================
    location = status_parsed.get('location', '?')
    present = ', '.join(status_parsed.get('present_list', []))
    last_beat = status_parsed.get('beats', ['?'])[0] if status_parsed.get('beats') else '?'
    prep_file = status_parsed.get('active_prep', 'None')
    turn_count = hook_state.get("turn_count", 0)

    if active_blocks:
        block_list = ', '.join(sorted(active_blocks - {b for b in active_blocks if ':' in b}))
        targeted = [b for b in active_blocks if ':' in b]
        if targeted:
            block_list += f" + {', '.join(targeted)}"
        reason_str = ', '.join(escalation_reasons) if escalation_reasons else 'claude_request'
        result.insert(0, f"**[BLOCKS: {block_list}]** ({reason_str}, turn {turn_count})")
    else:
        result.insert(0, f"**[AUTO-LIGHT]** (turn {turn_count})")
    result.insert(1, f"Location: {location} | Present: {present} | Prep: {prep_file}")
    # Header last-beat is a glance pointer; the full beats live in RECENT BEATS
    # below, so cap it short instead of repeating an entire 330-char beat.
    if last_beat and len(last_beat) > 140:
        last_beat = last_beat[:140].rsplit(' ', 1)[0] + "…"
    result.insert(2, f"Last beat: {last_beat}")
    result.insert(3, "")

    # ========================================
    # TOOL RECOMMENDATIONS ("AI Helper")
    # Analyzes input and suggests which tools to call
    # ========================================
    if active_blocks:
        recommendations = []

        # Detect vault/dungeon exploration context (using pre-compiled patterns)
        if any(p.search(input_lower) for p in _COMPILED_PATTERNS['vault']):
            recommendations.append("map(action='render', map_name=...) — check turn count, encounter clock")

        # Detect NPC decision/dialogue (using pre-compiled patterns)
        npc_recommended = False

        # Check present party members first
        for name in present_names_raw:
            name_lower = name.lower()
            if name_lower in input_lower:
                if any(p.search(input_lower) for p in _COMPILED_PATTERNS['npc_actions']):
                    recommendations.append(f"{_pf.push_call('npc', action='get', name=name)} — verify NPC knowledge/disposition before narrating their response")
                    npc_recommended = True
                    break

        # Also check NPCs from npc_states.json if not already recommended
        # (reuse npc_data loaded earlier)
        if not npc_recommended and npc_data:
            try:
                for npc_id, npc in npc_data.get("npcs", {}).items():
                        npc_name = npc.get("name", "")
                        npc_name_lower = npc_name.lower()
                        # Check full name or first name
                        first_name = npc_name_lower.split()[0] if npc_name_lower else ""
                        if (npc_name_lower and npc_name_lower in input_lower) or (first_name and first_name in input_lower):
                            if any(p.search(input_lower) for p in _COMPILED_PATTERNS['npc_actions']):
                                recommendations.append(f"{_pf.push_call('npc', action='get', name=npc_name)} — verify NPC knowledge/disposition before narrating their response")
                                break
            except Exception:
                pass  # NPC lookup not critical

        # Detect combat initiation (using pre-compiled patterns)
        if any(p.search(input_lower) for p in _COMPILED_PATTERNS['combat']):
            recommendations.append("character(action='list') — verify HP before combat")
            recommendations.append("lookup(action='creature', query=name) — if enemy involved")

        # Detect rest/healing (using pre-compiled patterns)
        if any(p.search(input_lower) for p in _COMPILED_PATTERNS['rest']):
            recommendations.append("rest(action='short') or rest(action='long') — calculate healing properly")

        # Detect day advancement (using pre-compiled patterns)
        if any(p.search(input_lower) for p in _COMPILED_PATTERNS['day']):
            recommendations.append("advance_day() — update campaign day before narrating new day")

        # Detect creature/monster mentions (using pre-compiled patterns)
        if any(p.search(input_lower) for p in _COMPILED_PATTERNS['creature']):
            # Only recommend if it seems like combat or stats might matter
            if any(p.search(input_lower) for p in _COMPILED_PATTERNS['combat']) or any(kw in input_lower for kw in ["threatening", "hostile", "stats"]):
                recommendations.append("lookup(action='creature', query=name) — get exact stats, don't approximate")

        # Detect loot/treasure (using pre-compiled patterns)
        if any(p.search(input_lower) for p in _COMPILED_PATTERNS['loot']):
            recommendations.append("roll(action='exotica') or generate(action='weapon') — for random treasure")

        # Detect travel between locations
        if any(kw in input_lower for kw in ["travel to", "head to", "journey to", "fly to", "return to"]):
            recommendations.append("geography(action='journey') — get accurate travel time")

        # Inject recommendations if any (deduplicated)
        if recommendations:
            result.append("")
            result.append("**⚠️ REQUIRED TOOLS (call these or risk hallucination):**")
            seen = set()
            for rec in recommendations:
                if rec not in seen:
                    seen.add(rec)
                    result.append(f"- {rec}")
            result.append("")
            result.append("_Narrating without calling required tools = inventing facts. Call them first._")

    # === VOCABULARY AUDIT (every 15 turns) ===
    # Reminds the model what phrases it has already used this session
    # so it can self-monitor for repetition beyond the blacklist.
    try:
        turn_count = hook_state.get("turn_count", 0)
        if turn_count > 0 and turn_count % 15 == 0:
            session_vocab = hook_state.get("session_vocabulary", [])
            if session_vocab:
                result.append("")
                result.append("**VOCABULARY AUDIT** (phrases already used this session — avoid repeating):")
                for phrase in session_vocab:
                    result.append(f"  - {phrase}")
                result.append("_Find fresh language. The constraint makes the writing better._")
    except Exception:
        pass  # Non-critical

    scene_text = "\n".join(result)  # always-fresh scene state (never deduped)
    try:
        from canon_delivery import filter_elements_with_stats
        with _hook_state_lock():
            fresh_state = _read_hook_state()  # re-read: picks up injected_npcs written earlier this call
            deduped_text, new_state, stats = filter_elements_with_stats(dedup_elements, fresh_state)
            _write_hook_state(new_state)
        logging.info(
            "canon_delta needs=%s fresh=%d pointers=%d always_fresh=%d",
            sorted(active_blocks), stats["fresh"], stats["pointers"], stats["always_fresh"],
        )
    except Exception:
        # Fail-open: a read tool must never starve canon on a bug.
        deduped_text = "\n\n".join(c for (_s, _k, c) in dedup_elements)
    if deduped_text:
        return scene_text + "\n\n" + deduped_text
    return scene_text

# ============================================
# UPDATE ACTIVE PREP (Phase 3: Dedicated Tool)
# ============================================

@mcp.tool(
    annotations={"readOnlyHint": False, "idempotentHint": False},
    tags=_get_tool_tags("update_active_prep")
)
def update_active_prep(
    ctx: Context,
    prep_filename: str = Field(description="Prep file name (e.g., 'TESSIK_WELL_PREP.md')"),
    verify_exists: bool = Field(default=True, description="If True, verify prep file exists before updating. Default True for safety.")
) -> str:
    """Reach for this WHEN the party crosses into a new location and you need to swap which prep file is active in CURRENT_STATUS.md.

    Updates Active Prep field in CURRENT_STATUS.md. Validates file exists before updating."""
    try:
        status_path = CAMPAIGN_DIR / "CURRENT_STATUS.md"
        if not status_path.exists():
            return "❌ ERROR: CURRENT_STATUS.md not found"

        # Verify prep file exists if requested
        if verify_exists:
            prep_path = CAMPAIGN_DIR / prep_filename
            if not prep_path.exists():
                # Try to find similar files
                all_prep_files = list(CAMPAIGN_DIR.glob("**/*PREP.md"))
                prep_names = [f.name for f in all_prep_files]

                return (
                    f"❌ ERROR: Prep file not found: {prep_filename}\n\n"
                    f"Available prep files:\n" +
                    "\n".join(f"  - {name}" for name in sorted(prep_names)[:20])
                )

        # Read current status
        status_content = status_path.read_text(encoding='utf-8')

        # Extract current Active Prep value
        current_prep_match = re.search(r'\*\*Active Prep:\*\*\s*(.+?)(?:\n|$)', status_content)
        if current_prep_match:
            current_prep = current_prep_match.group(1).strip()

            # Update Active Prep field
            updated_content = re.sub(
                r'\*\*Active Prep:\*\*\s*' + re.escape(current_prep),
                f'**Active Prep:** {prep_filename}',
                status_content
            )
        else:
            # Self-heal: older scaffolded status files wrote an `## ACTIVE PREP`
            # heading with a bare `(none)` body but no inline `**Active Prep:**`
            # field, so this tool used to hard-error on a fresh campaign. If the
            # heading exists, insert the canonical field beneath it; if not even
            # the heading exists, append a fresh section. Either way the tool now
            # succeeds instead of stranding the player.
            heading_match = re.search(r'^##\s*ACTIVE PREP\s*$', status_content, re.MULTILINE)
            if heading_match:
                insert_at = heading_match.end()
                updated_content = (
                    status_content[:insert_at]
                    + f'\n\n**Active Prep:** {prep_filename}'
                    + status_content[insert_at:]
                )
            else:
                updated_content = (
                    status_content.rstrip()
                    + f'\n\n## ACTIVE PREP\n\n**Active Prep:** {prep_filename}\n'
                )
            current_prep = "(none)"

        # Write updated content
        status_path.write_text(updated_content, encoding='utf-8')

        # Persist the exact resolved filename in game state (handoff fix #2) so
        # prep resolution never again depends on parsing the display line.
        _persist_active_prep_file(prep_filename)

        # Load prep file overview
        prep_overview = "No overview available"
        if verify_exists:
            prep_path = CAMPAIGN_DIR / prep_filename
            prep_content = prep_path.read_text(encoding='utf-8')

            # Extract overview (first few paragraphs)
            overview_patterns = [
                r'^#[^#].*?\n\n(.*?)(?=\n##|\n---|\Z)',  # Content after title
                r'## Overview\n\n(.*?)(?=\n##|\Z)',
                r'## Summary\n\n(.*?)(?=\n##|\Z)',
                r'\*\*Summary:\*\*\s*(.*?)(?:\n\n|\Z)',
            ]

            for pattern in overview_patterns:
                overview_match = re.search(pattern, prep_content, re.DOTALL | re.MULTILINE)
                if overview_match:
                    prep_overview = overview_match.group(1).strip()
                    if len(prep_overview) > 500:
                        prep_overview = prep_overview[:500].rsplit(' ', 1)[0] + "..."
                    break

        # Log the change
        logging.info(f"Active Prep updated: {current_prep} → {prep_filename}")

        return (
            f"✓ **ACTIVE PREP UPDATED**\n\n"
            f"Changed: {current_prep} → {prep_filename}\n"
            f"File: CURRENT_STATUS.md\n\n"
            f"**Prep Overview:**\n{prep_overview}\n\n"
            f"_Next steps:_\n"
            f"1. Call check_canon() to load new context\n"
            f"2. Use files(action='read') to get detailed prep content\n"
            f"3. Proceed with narration from new location"
        )

    except Exception as e:
        logging.error(f"update_active_prep failed: {e}")
        return f"❌ ERROR: Failed to update Active Prep: {e}"

def _lorebook_merge_push(keyword, current_context, new_context):
    """One home for the 'this keyword already exists — merge, don't drop it' push.

    The lorebook add/new_canon paths dedup by keyword and SKIP anything that
    already exists, so a fresh fact about an existing subject silently evaporates
    (C15). This surfaces the entry's CURRENT context so the agent MERGES rather
    than blind-overwrites, and hands the exact update call (new_value = the fresh
    context that was skipped)."""
    cur = (current_context or "").strip()
    lines = [
        f"   ⚠ '{keyword}' already exists — its fresh context was NOT merged "
        f"(duplicate keywords are skipped)."
    ]
    if cur:
        lines.append(f"   current: \"{cur}\"")
    lines.append(_pf.next_block(
        _pf.push_call("lorebook", action="update", keyword=keyword,
                      field="context", new_value=new_context),
        label="merge current + new, don't blind-overwrite"))
    return "\n".join(lines)


@mcp.tool(
    annotations={"readOnlyHint": False, "idempotentHint": False},
    tags=_get_tool_tags("lorebook")
)
def lorebook(
    action: str,
    keywords: str = None,
    keyword: str = None,
    category: str = None,
    status: str = None,
    context: str = None,
    source: str = "session",
    field: str = None,
    new_value: str = None
) -> str:
    """Reach for this WHEN you need to record a newly established canon fact, look up what's already known, or correct a prior entry. (Party wealth lives in party.json, NOT here — owner ruling 2026-07-02; the "rations" entry keeps consumption lore only.)

    Actions: add (keywords, category, status, context, source?) | view (keyword? or category?) | update (keyword, field, new_value)
    Categories: people, places, things, context, scenes, world, religions, factions, knowledge_boundary
    Statuses: ESTABLISHED, CANONICAL, CORRECTED
    """
    VALID_CATEGORIES = ['people', 'places', 'things', 'context', 'scenes', 'world', 'religions', 'factions', 'knowledge_boundary']
    VALID_STATUSES = ['ESTABLISHED', 'CANONICAL', 'CORRECTED']
    lorebook_path = CAMPAIGN_DIR / "lorebook.json"
    action_lower = action.lower().strip()

    if action_lower == "add":
        if not all([keywords, category, status, context]):
            return "Error: add requires keywords, category, status, context"

        if category.lower() not in VALID_CATEGORIES:
            return f"Invalid category '{category}'. Use: {', '.join(VALID_CATEGORIES)}"

        if status.upper() not in VALID_STATUSES:
            return f"Invalid status '{status}'. Use: {', '.join(VALID_STATUSES)}"

        if lorebook_path.exists():
            with open(lorebook_path, 'r', encoding='utf-8') as f:
                lb = json.load(f)
        else:
            lb = {"meta": {"version": 1, "last_updated": "", "description": "Keyword-triggered context injection"}, "entries": []}

        keyword_list = [k.strip().lower() for k in keywords.split(",")]

        existing_keywords = set()
        for entry in lb.get("entries", []):
            for kw in entry.get("keywords", []):
                existing_keywords.add(kw.lower())

        duplicates = [k for k in keyword_list if k in existing_keywords]
        if duplicates:
            dk = duplicates[0]
            cur_ctx = ""
            for entry in lb.get("entries", []):
                if any(dk == k.lower() for k in entry.get("keywords", [])):
                    cur_ctx = entry.get("context", "")
                    break
            return (
                f"Keywords already exist: {', '.join(duplicates)}. This entry was NOT added.\n"
                + _lorebook_merge_push(dk, cur_ctx, context)
            )

        new_entry = {
            "keywords": keyword_list,
            "category": category.lower(),
            "status": status.upper(),
            "context": context,
            "source": source
        }

        lb["entries"].append(new_entry)
        from datetime import datetime
        lb["meta"]["last_updated"] = datetime.now().strftime("%Y-%m-%d")
        _atomic_json_write(lorebook_path, lb)

        return f"Added lorebook entry: [{category.upper()}] {', '.join(keyword_list)}"

    elif action_lower == "view":
        if not lorebook_path.exists():
            return "lorebook.json not found"

        with open(lorebook_path, 'r', encoding='utf-8') as f:
            lb = json.load(f)

        entries = lb.get("entries", [])
        if not entries:
            return "Lorebook is empty."

        if keyword:
            keyword_lower = keyword.lower()
            matches = [e for e in entries if any(keyword_lower in k.lower() for k in e.get("keywords", []))]
            if not matches:
                return f"No entries found for '{keyword}'"

            result = [f"**Entries matching '{keyword}':**", ""]
            for entry in matches:
                result.append(f"**[{entry.get('category', '?').upper()}]** {', '.join(entry.get('keywords', []))}")
                result.append(f"Status: {entry.get('status', '?')}")
                result.append(f"Context: {entry.get('context', '?')}")
                result.append(f"Source: {entry.get('source', '?')}")
                result.append("")
            return "\n".join(result)

        by_category = {}
        for entry in entries:
            cat = entry.get("category", "unknown")
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(entry)

        if category:
            category_lower = category.lower()
            if category_lower not in by_category:
                return f"No entries in category '{category}'"

            cat_entries = by_category[category_lower]
            result = [f"**{category_lower.upper()}** ({len(cat_entries)} entries)", ""]
            for entry in cat_entries:
                kws = ", ".join(entry.get("keywords", []))
                result.append(f"  - {kws} [{entry.get('status', '?')}]")
            return "\n".join(result)

        result = [f"**LOREBOOK: {len(entries)} entries**", f"Last updated: {lb.get('meta', {}).get('last_updated', '?')}", ""]
        for cat in ["people", "places", "things", "context"]:
            if cat in by_category:
                result.append(f"**{cat.upper()}** ({len(by_category[cat])})")
                for entry in by_category[cat]:
                    kws = ", ".join(entry.get("keywords", []))
                    result.append(f"  - {kws} [{entry.get('status', '?')}]")
                result.append("")

        if "scenes" in by_category:
            result.append(f"**SCENES** ({len(by_category['scenes'])} entries) - use action='view', category='scenes' to list")

        return "\n".join(result)

    elif action_lower == "update":
        if not keyword or not field or not new_value:
            return "Error: update requires keyword, field, new_value"

        if not lorebook_path.exists():
            return "lorebook.json not found"

        with open(lorebook_path, 'r', encoding='utf-8') as f:
            lb = json.load(f)

        keyword_lower = keyword.lower()
        target_entry = None
        for entry in lb.get("entries", []):
            if any(keyword_lower == k.lower() for k in entry.get("keywords", [])):
                target_entry = entry
                break

        if not target_entry:
            return f"No entry found with keyword '{keyword}'"

        valid_fields = ["keywords", "category", "status", "context", "source"]
        if field.lower() not in valid_fields:
            return f"Invalid field. Use one of: {', '.join(valid_fields)}"

        if field.lower() == "category" and new_value.lower() not in VALID_CATEGORIES:
            return f"Invalid category '{new_value}'. Use: {', '.join(VALID_CATEGORIES)}"

        if field.lower() == "status" and new_value.upper() not in VALID_STATUSES:
            return f"Invalid status '{new_value}'. Use: {', '.join(VALID_STATUSES)}"

        if field.lower() == "keywords":
            target_entry["keywords"] = [k.strip().lower() for k in new_value.split(",")]
        elif field.lower() == "category":
            target_entry["category"] = new_value.lower()
        elif field.lower() == "status":
            target_entry["status"] = new_value.upper()
        else:
            target_entry[field.lower()] = new_value

        from datetime import datetime
        lb["meta"]["last_updated"] = datetime.now().strftime("%Y-%m-%d")
        _atomic_json_write(lorebook_path, lb)

        return f"Updated '{keyword}' -> {field}: {new_value}"

    else:
        return f"Unknown action: {action}. Valid actions: add, view, update"

def _replace_in_file_impl(
    filename: str,
    old_str: str,
    new_str: str = "",
    description: str = ""
) -> str:
    """Replace a unique string in a campaign file. Core of edit_file(action='replace')."""
    file_path = CAMPAIGN_DIR / filename
    
    if not file_path.exists():
        return f"Ã¢ÂÅ’ File not found: {filename}"
    
    # Read current content
    content = file_path.read_text(encoding='utf-8')
    
    # Check that old_str appears exactly once
    count = content.count(old_str)
    
    if count == 0:
        return f"Ã¢ÂÅ’ String not found in {filename}\n\nSearched for:\n{old_str}"
    
    if count > 1:
        return f"Ã¢ÂÅ’ String appears {count} times in {filename} (must be unique)\n\nSearched for:\n{old_str}"
    
    # Perform replacement
    new_content = content.replace(old_str, new_str)
    
    # Write back
    file_path.write_text(new_content, encoding='utf-8')
    
    # Show what changed
    result_msg = f"Ã¢Å“â€¦ Replaced in {filename}"
    if description:
        result_msg += f"\nÃ°Å¸â€œÂ {description}"
    result_msg += f"\n\nÃ°Å¸â€Â Found and replaced:\n{old_str[:100]}{'...' if len(old_str) > 100 else ''}"
    result_msg += f"\n\nÃ¢Å“ÂÃ¯Â¸Â  Replaced with:\n{new_str[:100]}{'...' if len(new_str) > 100 else ''}"
    
    return result_msg

def _read_file_section_impl(
    filename: str,
    section_header: str,
    for_player: bool = False
) -> str:
    """Extract a markdown section by header. Core of files(action='read')."""
    content = read_file(filename)
    
    if content.startswith("Error"):
        return content
    
    lines = content.split('\n')
    
    # Normalize section header (remove extra #, whitespace)
    target = section_header.strip().lstrip('#').strip()
    
    # Find the target section
    start_idx = None
    header_level = None
    
    for i, line in enumerate(lines):
        # Check if this line is a header
        if line.strip().startswith('#'):
            # Extract header level (number of #) and text
            header_match = re.match(r'^(#+)\s*(.+)$', line.strip())
            if header_match:
                level = len(header_match.group(1))
                header_text = header_match.group(2).strip()
                
                # Check if this is our target header
                if target.lower() in header_text.lower() or header_text.lower() in target.lower():
                    start_idx = i
                    header_level = level
                    break
    
    if start_idx is None:
        return f"Error: Section '{section_header}' not found in {filename}"
    
    # Find where this section ends (next same-or-higher-level header)
    end_idx = len(lines)
    for i in range(start_idx + 1, len(lines)):
        if lines[i].strip().startswith('#'):
            header_match = re.match(r'^(#+)\s*(.+)$', lines[i].strip())
            if header_match:
                level = len(header_match.group(1))
                if level <= header_level:
                    end_idx = i
                    break
    
    # Extract the section
    section_lines = lines[start_idx:end_idx]
    section_content = '\n'.join(section_lines)

    # Apply filtering if requested
    if for_player:
        section_content = _filter_dm_only_content(section_content)

    return section_content

def _read_pdf_pages_impl(
    filename: str = "Vaarn 2e EMERALD SCARAB 21-11-25.pdf",
    start_page: int = 1,
    end_page=None
) -> str:
    """Extract PDF pages. Core of files(action='pdf')."""
    pdf_path = CAMPAIGN_DIR / filename
    
    if not pdf_path.exists():
        return f"Ã¢ÂÅ’ PDF not found: {filename}"
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            total_pages = len(pdf.pages)
            
            if end_page is None:
                end_page = start_page
            
            # Validate page range
            if start_page < 1:
                return f"Ã¢ÂÅ’ start_page must be >= 1 (got {start_page})"
            if end_page > total_pages:
                return f"Ã¢ÂÅ’ end_page {end_page} exceeds PDF length ({total_pages} pages)"
            if start_page > end_page:
                return f"Ã¢ÂÅ’ start_page ({start_page}) > end_page ({end_page})"
            
            pages = pdf.pages[start_page-1:end_page]
            text_parts = []
            
            for i, page in enumerate(pages):
                page_num = start_page + i
                page_text = page.extract_text() or '(no text extracted)'
                text_parts.append(f"[Page {page_num}/{total_pages}]\n{page_text}")
            
            return "\n\n---PAGE BREAK---\n\n".join(text_parts)
            
    except Exception as e:
        return f"Ã¢ÂÅ’ Error reading PDF: {str(e)}"


def _update_file_impl(filename: str, content: str) -> str:
    """Overwrite an entire campaign file. Core of edit_file(action='overwrite')."""
    result = write_file(filename, content)
    if result is True:
        return f"Successfully updated {filename}"
    return result

@mcp.tool(tags=_get_tool_tags("files"))
def files(
    action: str = Field(description="list|read|pdf"),
    pattern: str = Field(default="*.md", description="list: glob pattern"),
    exists_check: str = Field(default=None, description="list: if set, return true/false for this file's existence"),
    filename: str = Field(default="", description="read/pdf: file to read"),
    section_header: str = Field(default="", description="read: markdown section header to extract"),
    for_player: bool = Field(default=False, description="read: filter out DM-only content"),
    start_page: int = Field(default=1, description="pdf: first page (1-indexed)"),
    end_page: Optional[int] = Field(default=None, description="pdf: last page (inclusive)"),
) -> str:
    """Reach for this WHEN you need to discover, read, or look up campaign reference material.

    list: list campaign files / check a file exists (pattern?, exists_check?)
    read: extract one markdown section from a large file (filename, section_header, for_player?)
    pdf:  extract pages from the rulebook PDF (filename?, start_page?, end_page?)
    """
    a = (action or "").lower().strip()
    if a == "list":
        return _list_files_impl(pattern, exists_check)
    if a == "read":
        if not filename or not section_header:
            return "Error: action='read' needs filename and section_header."
        return _read_file_section_impl(filename, section_header, for_player)
    if a == "pdf":
        return _read_pdf_pages_impl(filename or "Vaarn 2e EMERALD SCARAB 21-11-25.pdf", start_page, end_page)
    return f"Invalid action '{action}'. Valid actions: list, read, pdf."


@mcp.tool(
    annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False},
    tags=_get_tool_tags("edit_file"),
)
def edit_file(
    action: str = Field(description="replace|overwrite"),
    filename: str = Field(default="", description="file to edit"),
    old_str: str = Field(default="", description="replace: unique string to find (must appear once)"),
    new_str: str = Field(default="", description="replace: replacement string"),
    description: str = Field(default="", description="replace: edit context"),
    content: str = Field(default="", description="overwrite: full new file content"),
) -> str:
    """Reach for this WHEN you need to write to a campaign file -- a surgical string swap
    (action='replace', preferred) or a full rewrite (action='overwrite', use with caution).

    replace:   swap one unique string in a file (filename, old_str, new_str?, description?)
    overwrite: replace the entire file content (filename, content)
    """
    a = (action or "").lower().strip()
    if a == "replace":
        if not filename or not old_str:
            return "Error: action='replace' needs filename and old_str."
        return _replace_in_file_impl(filename, old_str, new_str, description)
    if a in ("overwrite", "write"):
        if not filename:
            return "Error: action='overwrite' needs filename."
        return _update_file_impl(filename, content)
    return f"Invalid action '{action}'. Valid actions: replace, overwrite."


# Tool 1: Get current day
def _get_current_day_impl() -> str:
    """Reach for this WHEN you need to know what day it is in-campaign — read-only; call advance_day to actually change it.

    Get current campaign day. Use when checking deadlines, photosynthesis, or before advance_day."""
    content = read_current_status(required=False)
    if not content:
        return "ERROR: CURRENT_STATUS.md not found or unreadable"

    # Look for "# CURRENT STATUS - DAY X" pattern
    match = re.search(r'DAY\s+(\d+)', content, re.IGNORECASE)
    if match:
        day_num = match.group(1)

        # Try to also get the date if present
        date_match = re.search(r'\((.*?of.*?)\)', content)
        if date_match:
            return f"Day {day_num} ({date_match.group(1)})"
        return f"Day {day_num}"

    return "Could not determine current day from CURRENT_STATUS.md"

def _build_prose_observer_summary(max_entries: int = 30, max_examples: int = 5) -> str:
    """Read recent prose observer catches and format a compact summary for session-start.

    The prose observer runs fire-and-forget after narrative turns and logs
    phrase-family violations to hooks/catch_analytics.json. Surfacing a
    summary at session-start closes the feedback loop — the DM sees which
    patterns slipped through last session and can watch for them today.

    Returns an empty string on any failure; this is advisory output, never critical.
    """
    try:
        analytics_path = CAMPAIGN_DIR / "catch_analytics.json"  # campaign-scoped (privacy: was engine-relative)
        if not analytics_path.exists():
            return ""
        data = json.loads(analytics_path.read_text(encoding="utf-8"))
        catches = data.get("semantic_catches", [])
        if not catches:
            return "=== RECENT PROSE OBSERVER CATCHES ===\nNo catches logged. Observer data clean or observer offline.\n"

        recent = catches[-max_entries:]

        # Count by category, sort descending.
        by_cat = {}
        for c in recent:
            cat = c.get("category", "Unknown")
            by_cat[cat] = by_cat.get(cat, 0) + 1
        cat_lines = [f"  {cat}: {count}" for cat, count in sorted(by_cat.items(), key=lambda x: -x[1])]

        # Prefer high-confidence examples, fall back to medium.
        high_conf = [c for c in recent if c.get("confidence") == "high"]
        med_conf = [c for c in recent if c.get("confidence") == "medium"]
        examples = (high_conf + med_conf)[:max_examples]
        example_lines = []
        for c in examples:
            turn = c.get("turn_id", "?")
            cat = c.get("category", "?")
            quote = c.get("quote", "")
            if len(quote) > 80:
                quote = quote[:77] + "..."
            example_lines.append(f'  [T{turn}] "{quote}" — {cat}')

        block = [
            "=== RECENT PROSE OBSERVER CATCHES ===",
            f"Last {len(recent)} catches (across recent sessions), by category:",
        ]
        block.extend(cat_lines)
        if example_lines:
            block.append("")
            block.append("High/medium-confidence examples to watch for today:")
            block.extend(example_lines)
        block.append("")
        return "\n".join(block) + "\n"
    except Exception as e:
        return f"=== RECENT PROSE OBSERVER CATCHES ===\nObserver summary unavailable: {str(e)}\n"


# Tool 1.5: Full session startup - bundles all mandatory initialization
# full_session_startup moved to session_tools.py (Wave 8 slice 2); registered via register_session_tools.

# Tool 6: Advance to next day
@mcp.tool(
    annotations={"readOnlyHint": False, "idempotentHint": True},
    tags=_get_tool_tags("advance_day")
)
def advance_day(new_day: int, brief_summary: str) -> str:
    """Reach for this WHEN the party finishes an overnight rest or a significant time skip and the calendar day must move to a new number — mutates the day counter only (rest handles healing); use sync_campaign_day(action="get") to read without changing.

    Advance campaign day. Call after overnight rest or time skip. Warns if photosynthesis due."""
    # Update CURRENT_STATUS.md header
    content = read_file("CURRENT_STATUS.md")

    # Replace the day number in header
    new_content = re.sub(
        r'# CURRENT STATUS - DAY \d+',
        f'# CURRENT STATUS - DAY {new_day}',
        content
    )

    # Update **Day:** field in SCENE STATE section
    new_content = re.sub(
        r'\*\*Day:\*\*\s*\d+',
        f'**Day:** {new_day}',
        new_content,
        count=1
    )

    result = write_file("CURRENT_STATUS.md", new_content)

    if result is not True:
        return result

    # Check photosynthesis status
    # E1 Step 4: if the structured fed-day field is present on any character,
    # the CONDITION TICK block handles warnings (avoid double-reporting).
    warning = ""
    photo_structured = False
    try:
        _pchk, _perr = _load_characters()
        if not _perr and _pchk:
            for _pc in _pchk.get("characters", {}).values():
                _pblk = _pc.get("survival") or {}
                if "photosynthesis_window_days" in _pblk and isinstance(
                        _pblk.get("photosynthesis_last_fed_day"), int):
                    photo_structured = True
                    break
    except Exception:
        pass
    if not photo_structured:
        photo_match = re.search(r'\*\*Last Fed:\*\*\s*Day\s*(\d+).*?\*\*Due:\*\*\s*Day\s*(\d+)', content, re.DOTALL)
        if photo_match:
            last_fed = int(photo_match.group(1))
            due_day = int(photo_match.group(2))
            days_until = due_day - new_day

            if days_until < 0:
                warning = f"\nÃ¢ÂÅ’ CRITICAL: Photosynthesis OVERDUE by {abs(days_until)} days! (Due Day {due_day})"
            elif days_until == 0:
                warning = f"\nÃ¢Å¡Â Ã¯Â¸Â URGENT: Photosynthesis due TODAY (Day {due_day})"
            elif days_until == 1:
                warning = f"\nÃ¢Å¡Â Ã¯Â¸Â WARNING: Photosynthesis due tomorrow (Day {due_day})"
        else:
            # Try alternate pattern
            photo_match = re.search(r'\*\*PHOTOSYNTHESIS:\*\*.*?Day (\d+)', content)
            if photo_match:
                last_fed = int(photo_match.group(1))
                due_day = last_fed + _photosynthesis_window()
                days_until = due_day - new_day

                if days_until < 0:
                    warning = f"\nÃ¢ÂÅ’ CRITICAL: Photosynthesis OVERDUE by {abs(days_until)} days! (Due Day {due_day})"
                elif days_until == 0:
                    warning = f"\nÃ¢Å¡Â Ã¯Â¸Â URGENT: Photosynthesis due TODAY (Day {due_day})"
                elif days_until == 1:
                    warning = f"\nÃ¢Å¡Â Ã¯Â¸Â WARNING: Photosynthesis due tomorrow (Day {due_day})"

    # Sync day to JSON files
    sync_results = []
    old_campaign_day = None  # pre-advance day, for the wound daily-tick below
    _deferred_meta_stamp = None  # (path, data) committed AFTER the ticks (see below)
    try:
        chars_dir = CAMPAIGN_DIR / "characters"
        meta_path = chars_dir / "_meta.json"

        if chars_dir.exists() and meta_path.exists():
            # Split sheets are authoritative; _meta.json carries the campaign day.
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta_data = json.load(f)
            old_campaign_day = meta_data.get('campaign_day')
            # Edge-case hardening: _meta.json's campaign_day is the authoritative
            # RETRY GATE -- every tick below computes elapsed = new_day -
            # old_campaign_day. Writing it HERE (before the ticks) meant a process
            # death mid-tick left the day advanced but the ticks half-applied and
            # unreplayable (a re-call would see elapsed 0). Defer the disk write to
            # AFTER every tick block, so an interrupted run leaves old_campaign_day
            # intact and a re-call replays the day. sync_results still lists it (the
            # stamp lands before we return on every normal path). We re-read the
            # file at stamp time (not this snapshot) because the supply tick
            # persists its ledger into the SAME _meta.json mid-run.
            _deferred_meta_stamp = meta_path
            sync_results.append("characters/_meta.json")
    except Exception as e:
        logging.warning(f"Failed to sync campaign day to characters: {e}")

    try:
        party_path = CAMPAIGN_DIR / "party.json"
        if party_path.exists():
            with open(party_path, 'r', encoding='utf-8') as f:
                party_data = json.load(f)
            party_data['meta']['campaign_day'] = new_day
            _atomic_json_write(party_path, party_data)
            sync_results.append("party.json")
    except Exception as e:
        logging.warning(f"Failed to sync campaign day to party.json: {e}")

    sync_msg = f" (synced: {', '.join(sync_results)})" if sync_results else ""

    # ========================================
    # TWINNING PENDING EXPIRY (E1): a death-pending mark only pairs inside
    # its exact window (R-E1h), so a mark whose window is not THIS new day
    # can never pair again - pop it BEFORE the tick blocks run. Marks the
    # ticks below stamp land AFTER this cleanup, so same-call pairing holds.
    # ========================================
    pending_expiry = ""
    try:
        tp_data, tp_err = _load_characters()
        if not tp_err and tp_data:
            tp_lines = []
            for tp_key, tp_char in tp_data.get("characters", {}).items():
                tp_pend = tp_char.get("twinning_pending")
                if (isinstance(tp_pend, dict)
                        and tp_pend.get("window") != f"day:{new_day}"):
                    tp_char.pop("twinning_pending", None)
                    _save_single_character(tp_key, tp_char, tp_data)
                    tp_lines.append(
                        f"  {tp_char.get('name', tp_key)}: twinning "
                        f"death-pending mark from {tp_pend.get('window')} "
                        f"expired - the window passed")
            if tp_lines:
                pending_expiry = ("\n\n**TWINNING PENDING EXPIRED**\n"
                                  + "\n".join(tp_lines))
    except Exception as e:
        logging.warning(f"Twinning pending expiry failed: {e}")

    # ========================================
    # WOUND DAILY TICK: degenerative wounds (e.g. Cascading Kinesthetics
    # Debilitation) mutate abilities once per elapsed day WHILE active.
    # Derived read -- a healed wound contributes nothing, so no tick.
    # ========================================
    wound_tick = ""
    try:
        tick_data, tick_err = _load_characters()
        if not tick_err and tick_data:
            if isinstance(old_campaign_day, int):
                # Known old day: same-day or backwards re-calls (retries,
                # day-number corrections) must NOT tick again -- the mutation
                # is permanent and the tool is annotated idempotent.
                elapsed_days = max(0, new_day - old_campaign_day)
            else:
                elapsed_days = 1  # old day unknown -> tick once, never skip
            tick_lines = []
            tick_chars = tick_data.get('characters', {}) if elapsed_days > 0 else {}
            for tick_key, tick_char in tick_chars.items():
                wound_recs = tick_char.get('wounds', []) or []
                tick = _wnd.derived_effects(wound_recs)['daily_tick']
                if not tick:
                    continue
                hp_w = tick_char.get('hp')
                if isinstance(hp_w, dict) and hp_w.get('current', 0) <= -20:
                    continue  # corpse: nothing ticks (matches the other blocks)
                tick_names = ", ".join(
                    r.get('name', 'Unknown') for r in wound_recs
                    if isinstance(r, dict) and r.get('daily_tick'))
                tick_lines.append(f"  {tick_char.get('name', tick_key)} - {tick_names}:")
                days_ticked = 0
                for w_offset in range(elapsed_days):
                    w_tick_day = (old_campaign_day
                                  if isinstance(old_campaign_day, int)
                                  else new_day - 1) + w_offset + 1
                    for stat, amount in tick.items():
                        tick_lines.extend(
                            _apply_ability_damage_from_wound(tick_char, {stat: amount}))
                    days_ticked += 1
                    # E1: ability-floor deaths route through the death gate
                    # (Twinning applies) - window pairs with the other ticks.
                    w_is_dead, w_reason, w_glines = _check_death_gated(
                        tick_key, tick_char, tick_data,
                        window_key=f"day:{w_tick_day}")
                    tick_lines.extend("  " + l for l in w_glines)
                    if w_is_dead:
                        if isinstance(tick_char.get('hp'), dict):
                            tick_char['hp']['current'] = -20
                        tick_lines.append(f"  !!! {w_reason} !!!")
                        tick_lines.extend(
                            "  " + l for l in _death_seam_lines(
                                tick_char, tick_data, tick_key))
                        break  # dead is dead - stop ticking this character
                totals = ", ".join(f"{stat} -{amount * days_ticked}"
                                   for stat, amount in tick.items())
                tick_lines.append(f"    TOTAL: {totals} over {days_ticked} day(s)")
                _save_single_character(tick_key, tick_char, tick_data)
            if tick_lines:
                wound_tick = ("\n\n**!!! WOUND DAILY TICK !!!** "
                              f"({elapsed_days} day(s) elapsed)\n" + "\n".join(tick_lines))
    except Exception as e:
        logging.warning(f"Wound daily tick failed: {e}")
        # Surface in-band too: a silently skipped tick is a rules miss the DM
        # cannot see in the MCP process logs.
        wound_tick = f"\n\nWARNING: wound daily tick skipped ({e}) - check sheets manually."

    # ========================================
    # SUPPLY DAILY TICK (S1): field-mode consumption, Deprived clocks, death.
    # Same idempotency contract as the wound tick (elapsed_days guard).
    # Spec: docs/superpowers/specs/2026-06-10-survival-supply-design.md
    # ========================================
    supply_tick = ""
    supply_deprived_live = False
    try:
        s_meta, sup, s_meta_path = _load_supply()
        if sup.get("mode") == "field":
            s_data, s_err = _load_characters()
            if isinstance(old_campaign_day, int):
                s_elapsed = max(0, new_day - old_campaign_day)
            else:
                s_elapsed = 1
            if not s_err and s_data and s_elapsed > 0:
                s_lines = []
                pool = sup.get("pool") if isinstance(sup.get("pool"), dict) else None
                ledger = sup.get("ledger") or {}
                s_dead = set()  # C2: PCs who died this tick — no corpse feeding
                for offset in range(s_elapsed):
                    tick_day = (old_campaign_day if isinstance(old_campaign_day, int)
                                else new_day - 1) + offset + 1
                    consumed_today = (ledger.get("consumed", {})
                                      if ledger.get("day") == tick_day - 1 else {})
                    # follower mouths drink/eat from the pool first-class
                    mouths = int(sup.get("follower_mouths", 0))
                    if pool is not None and mouths:
                        f_short = _sv.consume_day(
                            {"water": mouths, "food": mouths}, pool, [], True)
                        if f_short["water"] or f_short["food"]:
                            s_lines.append(
                                f"  FOLLOWERS short {f_short['food']}F/{f_short['water']}W "
                                f"(desertion after 3 unfed days is a DM call)")
                    for s_key, s_char in s_data.get("characters", {}).items():
                        if s_char.get("type") == "vehicle":
                            continue  # C1: vehicles merge into the roster
                        if s_key in s_dead:
                            continue  # C2: died earlier in this tick
                        hp_d = s_char.get("hp")
                        if isinstance(hp_d, dict) and hp_d.get("current", 0) <= -20:
                            continue  # C2: already dead at entry
                        needs = _sv.daily_needs(s_char)
                        if not (needs["water"] or needs["food"]):
                            continue
                        carried = [i for i in _sv._iter_items(s_char)
                                   if isinstance(i, dict) and i.get("ration_type")]
                        with_pool = s_key not in (sup.get("separated") or [])
                        short = _sv.consume_day(needs, pool, carried, with_pool,
                                                already=consumed_today.get(s_key))
                        conds = s_char.setdefault("conditions", [])
                        for need, cause in (("water", "thirst"), ("food", "starvation")):
                            if not needs[need]:
                                continue
                            met = short[need] == 0
                            # death check BEFORE clearing/creating: an unmet
                            # clock at its death_day kills today.
                            rec = next((c for c in conds if isinstance(c, dict)
                                        and c.get("name") == "Deprived"
                                        and c.get("cause") == cause), None)
                            if (rec and not met
                                    and s_char.get("type") != "steed"
                                    and tick_day >= rec.get("death_day", 10**9)):
                                # Pre-snap HP to -20 (the clock fires); the gate
                                # clamps to -19 if Twinning refuses (R-E1g brink),
                                # or the death stands. Matches the condition tick.
                                if isinstance(s_char.get("hp"), dict):  # C2: guarded write
                                    s_char["hp"]["current"] = -20
                                allowed, gate_lines = _death_gate(
                                    s_key, s_char, s_data,
                                    window_key=f"day:{tick_day}", cause=cause)
                                s_lines.extend("  " + gl for gl in gate_lines)
                                if allowed:
                                    s_lines.append(
                                        f"  !!! {s_char.get('name', s_key)} DIES of {cause} "
                                        f"(Deprived since Day {rec.get('since_day')}) - HP -20 !!!")
                                    s_lines.extend(
                                        "  " + l for l in _death_seam_lines(
                                            s_char, s_data, s_key))
                                    s_dead.add(s_key)
                                    break  # dead is dead - no second clock for the corpse
                                # refused: brink state - the record stays (still unfed)
                            had = bool(rec)
                            _sv.tick_deprivation(
                                conds, cause, met, tick_day,
                                _sv.deprivation_clock(s_char, cause))
                            if met and had:
                                s_lines.append(
                                    f"  {s_char.get('name', s_key)} recovered from "
                                    f"Deprived ({cause}) — cleared")
                        _save_single_character(s_key, s_char, s_data)
                # M1: standing DEPRIVED state renders ONCE per PC/cause (not
                # once per caught-up day). Death lines above are per-event.
                for s_key, s_char in s_data.get("characters", {}).items():
                    if s_char.get("type") == "vehicle" or s_key in s_dead:
                        continue
                    hp_d = s_char.get("hp")
                    if isinstance(hp_d, dict) and hp_d.get("current", 0) <= -20:
                        continue  # pre-existing corpse: no standing warning
                    eff = _sv.condition_effects(s_char.get("conditions", []))
                    for cause, death_day in eff["dying"]:
                        if s_char.get("type") == "steed":
                            continue  # steeds run away, they do not starve (p.69)
                        supply_deprived_live = True
                        s_lines.append(
                            f"  DEPRIVED: {s_char.get('name', s_key)} ({cause}) — "
                            f"no healing from Rests; DIES Day {death_day} without relief")
                    # D2 desertion watch (CH p.61): a FOLLOWER unfed/unwatered 3+
                    # consecutive days deserts at the first opportunity. Reuses
                    # the S1 Deprived record's since_day (no parallel counter) -
                    # consecutive days = new_day - since_day + 1. Nag style: fires
                    # every tick while the condition holds. Push-only: the DM
                    # adjudicates the departure in-fiction, then records it.
                    if s_char.get("type") == "follower":
                        for c in s_char.get("conditions", []):
                            if not (isinstance(c, dict)
                                    and c.get("name") == "Deprived"
                                    and c.get("cause") in ("thirst", "starvation")):
                                continue
                            since = c.get("since_day")
                            if not isinstance(since, int):
                                continue
                            consec = new_day - since + 1
                            if consec >= 3:
                                supply_deprived_live = True
                                s_lines.append(
                                    f"  DESERTION RISK: {s_char.get('name', s_key)} "
                                    f"unfed 3 days - deserts at the first opportunity "
                                    f"(CH p.61).")
                                s_lines.append("  " + _pf.next_block(
                                    _pf.push_call(
                                        "character", action="dismiss_follower",
                                        name=s_char.get("name", s_key),
                                        reason="deserted"),
                                    label="adjudicate in-fiction first - dismiss "
                                          "records the departure"))
                                break  # one desertion push per follower per tick
                    # D4 steed runaway (CH p.69): a STEED never starves to death
                    # (death-fire skip above) - instead, after 7 consecutive
                    # unfed days it runs away at the first chance. Mirrors the
                    # follower desertion branch: reuses the Deprived since_day
                    # (no parallel counter); consecutive days = new_day - since + 1.
                    if s_char.get("type") == "steed":
                        for c in s_char.get("conditions", []):
                            if not (isinstance(c, dict)
                                    and c.get("name") == "Deprived"
                                    and c.get("cause") == "starvation"):
                                continue
                            since = c.get("since_day")
                            if not isinstance(since, int):
                                continue
                            if new_day - since + 1 >= 7:
                                supply_deprived_live = True
                                s_lines.append(
                                    f"  STEED RUNAWAY: {s_char.get('name', s_key)} "
                                    f"unfed 7 days - runs away at the first chance "
                                    f"(CH p.69).")
                                s_lines.append("  " + _pf.next_block(
                                    _pf.push_call(
                                        "character", action="dismiss_companion",
                                        name=s_char.get("name", s_key),
                                        reason="ran away (unfed 7 days)"),
                                    label="adjudicate in-fiction first - dismiss "
                                          "records the departure"))
                                break  # one runaway push per steed per tick
                sup["ledger"] = {"day": new_day, "consumed": {}}
                if pool is not None:
                    s_lines.insert(0, f"  Pool: {pool.get('food', 0)} food, "
                                      f"{pool.get('water', 0)} water remaining")
                _save_supply(s_meta, s_meta_path)
                if s_lines:
                    supply_tick = ("\n\n**SUPPLY TICK** "
                                   f"({s_elapsed} day(s) in the field)\n" + "\n".join(s_lines))
    except Exception as e:
        logging.warning(f"Supply daily tick failed: {e}")
        supply_tick = f"\n\nWARNING: supply tick skipped ({e}) - run supply(action=\"status\") and check manually."

    # ========================================
    # CONDITION TICK (E1): photosynthesis Deprived, generic death clocks,
    # day/week drains. Same idempotency contract as the wound/supply ticks.
    # Thirst/starvation clocks belong to the SUPPLY tick above; this block
    # skips those causes. Spec: 2026-06-11-status-framework-design.md
    # ========================================
    cond_tick = ""
    res_tick = ""
    cond_live = False
    try:
        c_data, c_err = _load_characters()
        if not c_err and c_data:
            if isinstance(old_campaign_day, int):
                c_elapsed = max(0, new_day - old_campaign_day)
            else:
                c_elapsed = 1
            c_lines = []
            c_chars = c_data.get("characters", {}) if c_elapsed > 0 else {}
            for c_key, c_char in c_chars.items():
                if c_char.get("type") == "vehicle":
                    continue
                hp_d = c_char.get("hp")
                if isinstance(hp_d, dict) and hp_d.get("current", 0) <= -20:
                    continue  # corpse: tombstone records persist, nothing ticks
                c_changed = False
                c_name = c_char.get("name", c_key)
                # --- photosynthesis wiring (R-E1c): Deprived from the FIRST
                # missed day; death lands on the window day itself. ---
                blk = c_char.get("survival") or {}
                if "photosynthesis_window_days" in blk:
                    last_fed = blk.get("photosynthesis_last_fed_day")
                    if isinstance(last_fed, int):
                        window = int(blk["photosynthesis_window_days"])
                        conds = c_char.setdefault("conditions", [])
                        p_rec = next((c for c in conds if isinstance(c, dict)
                                      and c.get("name") == "Deprived"
                                      and c.get("cause") == "photosynthesis"), None)
                        if new_day > last_fed and p_rec is None:
                            conds.append({"name": "Deprived",
                                          "cause": "photosynthesis",
                                          "since_day": last_fed + 1,
                                          "death_day": last_fed + window})
                            c_lines.append(
                                f"  {c_name} is DEPRIVED (photosynthesis) - no HP "
                                f"regain; PERISHES Day {last_fed + window} unfed "
                                f"-> supply(action=\"photosynthesis\") after feeding")
                            c_changed = True
                    else:
                        c_lines.append(
                            f"  {c_name}: photosynthesis tracker unarmed - "
                            f"supply(action=\"photosynthesis\", last_fed_day=N) to arm it")
                week_warned = set()  # one warning per unanchored week record
                for offset in range(c_elapsed):
                    tick_day = (old_campaign_day if isinstance(old_campaign_day, int)
                                else new_day - 1) + offset + 1
                    # generic death clocks (NOT thirst/starvation - supply owns those)
                    for c_rec in list(c_char.get("conditions") or []):
                        if not isinstance(c_rec, dict):
                            continue
                        if c_rec.get("cause") in ("thirst", "starvation"):
                            continue
                        c_dd = c_rec.get("death_day")
                        if isinstance(c_dd, int) and tick_day >= c_dd:
                            # Snap HP to -20 (the clock fires); gate may clamp
                            # to -19 if Twinning blocks, or allow the death.
                            if isinstance(c_char.get("hp"), dict):
                                c_char["hp"]["current"] = -20
                            allowed, gate_lines = _death_gate(
                                c_key, c_char, c_data,
                                window_key=f"day:{tick_day}")
                            c_lines.extend("  " + l for l in gate_lines)
                            c_changed = True
                            if allowed:
                                c_label = c_rec.get("cause") or c_rec.get("name")
                                c_lines.append(
                                    f"  !!! {c_name} DIES of {c_label} "
                                    f"(clock Day {c_dd}) - HP -20 !!!")
                                c_lines.extend(_disease_death_prose(c_char))
                                c_lines.extend(
                                    "  " + l for l in _death_seam_lines(
                                        c_char, c_data, c_key))
                                break  # dead is dead - no second clock for the corpse
                            # refused: the pending mark is stamped - further
                            # clocks this day would only duplicate the block
                            break
                    hp_d = c_char.get("hp")
                    if isinstance(hp_d, dict) and hp_d.get("current", 0) <= -20:
                        break  # died mid-catchup
                    # day/week drains (engine-rolled - the toxin-tick precedent)
                    c_eff = _cnd.condition_effects(c_char.get("conditions") or [])
                    for t in c_eff["day_ticks"]:
                        since = t.get("since_day") or 0
                        if t["cadence"] == "week" and not since:
                            # legacy/hand-edited record: no anchor for the
                            # 7-day math (since=0 would fire on any day % 7)
                            if t["name"] not in week_warned:
                                week_warned.add(t["name"])
                                c_lines.append(
                                    f"  WARNING: {c_name}'s '{t['name']}' is "
                                    f"week-cadence with no since_day - skipping "
                                    f"its tick (clear + re-apply to anchor it)")
                            continue
                        if t["cadence"] == "week" and (
                                tick_day <= since or (tick_day - since) % 7):
                            continue
                        # E2: save-gated ticks (Lumenrot) - engine rolls d20 +
                        # ability-mod save; a PASS skips this entry's drain, a
                        # MISS lets it fire. Engine-rolled (multi-day advance
                        # cannot stall on a player roll - the toxin-tick
                        # precedent; only the CURE save is player-rolled).
                        if (isinstance(c_char.get("hp"), dict)
                                and c_char["hp"].get("current", 0) <= -20):
                            break  # corpse - no further day-tick entries
                        t_save = t.get("save")
                        if t_save:
                            s_ab = t_save["ability"]
                            s_dc = t_save["dc"]
                            ab_slot = (c_char.get("abilities") or {}).get(s_ab)
                            s_mod = (ab_slot.get("current", 0)
                                     if isinstance(ab_slot, dict)
                                     else (ab_slot or 0))
                            s_roll = dice.roll_notation("d20")["total"]
                            s_total = s_roll + s_mod
                            if s_total >= s_dc:
                                c_lines.append(
                                    f"  {c_name}: {t['label']} save PASS "
                                    f"({s_ab} d20={s_roll}{s_mod:+d} vs "
                                    f"{s_dc}, Day {tick_day}) - no drain")
                                continue
                            c_lines.append(
                                f"  {c_name}: {t['label']} save MISS "
                                f"({s_ab} d20={s_roll}{s_mod:+d} vs "
                                f"{s_dc}, Day {tick_day}) - drain fires")
                        if t.get("hp"):
                            t_dmg = _roll_drain(t["hp"])
                            t_lines, _dd = _apply_hp_damage_and_wounds(
                                c_key, c_char, c_data, t_dmg,
                                window_key=f"day:{tick_day}")
                            c_lines.append(
                                f"  {c_name}: {t['label']} ticks "
                                f"{t['hp']}={t_dmg} (Day {tick_day}) -> "
                                f"HP {c_char.get('hp', {}).get('current', '?')}")
                            c_lines.extend("  " + l for l in t_lines)
                            c_changed = True
                            if isinstance(c_char.get("hp"), dict) and c_char["hp"].get("current", 0) <= -20:
                                break  # died on this tick - no further drains on the corpse
                        # E2: max-HP drain (Labyrinth Pox) - reduce hp.max
                        # (floor 0), clamp hp.current down with it. When max
                        # reaches 0 and the record carries on_max_hp_zero,
                        # stamp death_day ONCE (idempotent); the generic clock
                        # branch above owns the eventual gated vanish.
                        if t.get("max_hp"):
                            hp_box = c_char.get("hp")
                            if isinstance(hp_box, dict):
                                mhp_roll = _roll_drain(t["max_hp"])
                                old_max = hp_box.get("max", 0)
                                new_max = max(0, old_max - mhp_roll)
                                hp_box["max"] = new_max
                                if hp_box.get("current", 0) > new_max:
                                    hp_box["current"] = new_max
                                c_lines.append(
                                    f"  {c_name}: {t['label']} drains "
                                    f"{t['max_hp']}={mhp_roll} max HP "
                                    f"(Day {tick_day}) -> max "
                                    f"{old_max} -> {new_max}")
                                c_changed = True
                                omz = t.get("on_max_hp_zero")
                                if new_max <= 0 and isinstance(omz, dict):
                                    for c_rec2 in (
                                            c_char.get("conditions") or []):
                                        if (isinstance(c_rec2, dict)
                                                and c_rec2.get("name")
                                                == t["name"]
                                                and c_rec2.get("death_day")
                                                is None):
                                            c_rec2["death_day"] = (
                                                tick_day
                                                + int(omz["death_in_days"]))
                                            c_lines.append(
                                                f"  {c_name}: {t['name']} "
                                                f"max HP is 0 - Stage 3; "
                                                f"vanishes Day "
                                                f"{c_rec2['death_day']} "
                                                f"(gated)")
                                            break
                        for t_ab, t_die in (t.get("abilities") or {}).items():
                            t_loss = _roll_drain(t_die)
                            c_lines.append(
                                f"  {c_name}: {t['label']} drains "
                                f"{t_ab} {t_die}={t_loss} (Day {tick_day})")
                            c_lines.extend("  " + l for l in
                                           _apply_ability_damage_from_wound(
                                               c_char, {t_ab: t_loss}))
                            c_changed = True
                            # E3 Gitch (R-E3b): a missed-save day tick marks an
                            # item slot with a Gitch Crystals wound (rides the
                            # wounds_slots_used recompute) -- +1 AV and the -1
                            # ability drain (above) per crystal. Keyed on the
                            # record's gitch flag; the save gate already fired
                            # (we are in the drain path, so the save MISSED).
                            _is_gitch = any(
                                isinstance(cr, dict) and cr.get("gitch")
                                and cr.get("name") == t["name"]
                                for cr in (c_char.get("conditions") or []))
                            if _is_gitch:
                                w_list = c_char.setdefault("wounds", [])
                                w_list.append({"name": "Gitch Crystals",
                                               "slots": 1, "av_bonus": 1,
                                               "gitch": True, "day": tick_day})
                                c_char["wounds_slots_used"] = sum(
                                    r.get("slots", 0) for r in w_list
                                    if isinstance(r, dict))
                                _gslots = _calculate_slots(c_char)
                                _gx = sum(1 for r in w_list
                                          if isinstance(r, dict) and r.get("gitch"))
                                c_lines.append(
                                    f"  {c_name}: Gitch crystal forms in an item "
                                    f"slot (Day {tick_day}) -- +{_gx} AV (Gitch "
                                    f"plating), {_gx} slot(s) crystal-filled, "
                                    f"effective free {_gslots['effective_free']}")
                                if _gslots["effective_free"] <= 0:
                                    # all available slots crystal-filled -> the
                                    # Gitchghast transformation (gated death).
                                    if isinstance(c_char.get("hp"), dict):
                                        c_char["hp"]["current"] = -20
                                    _ga, _glines = _death_gate(
                                        c_key, c_char, c_data,
                                        window_key=f"day:{tick_day}")
                                    c_lines.extend("  " + l for l in _glines)
                                    if _ga:
                                        c_lines.append(
                                            f"  !!! {c_name} becomes a mindless "
                                            f"GITCHGHAST -- every available slot "
                                            f"is crystal-filled (Day {tick_day})"
                                            f" -- HP -20 !!!")
                                        c_lines.extend(
                                            _disease_death_prose(c_char))
                                        c_lines.extend(
                                            "  " + l for l in
                                            _death_seam_lines(
                                                c_char, c_data, c_key))
                                    break  # transformed (or held at brink) - stop
                            c_dead, c_reason, c_glines = _check_death_gated(
                                c_key, c_char, c_data,
                                window_key=f"day:{tick_day}")
                            c_lines.extend("  " + l for l in c_glines)
                            if c_dead:
                                if isinstance(c_char.get("hp"), dict):
                                    c_char["hp"]["current"] = -20
                                c_lines.append(f"  !!! {c_reason} !!!")
                                c_lines.extend(_disease_death_prose(c_char))
                                c_lines.extend(
                                    "  " + l for l in _death_seam_lines(
                                        c_char, c_data, c_key))
                                break  # died on this drain - stop draining the corpse
                    hp_d = c_char.get("hp")
                    if isinstance(hp_d, dict) and hp_d.get("current", 0) <= -20:
                        break
                # Condition auto-expiry (B2): day-limited conditions carry
                # until_day. Swept AFTER the day's ticks so a condition gets
                # its final day's effect before clearing. Corpses keep their
                # tombstone records (corpse guard above skips them entirely).
                # B3: shared expiry helper -- applies any `revert` snapshot so a
                # turn-duration elixir that outlived its vault restores stats at
                # the day failsafe (turn + day sweeps now use the SAME logic).
                expired = _cnd.expire_day_conditions(c_char, new_day)
                for exp_c in expired:
                    c_changed = True
                    c_lines.append(
                        f"  {c_name}: {exp_c.get('name', '?')} has run its "
                        f"course (expired day {exp_c['until_day']}).")
                if c_changed:
                    _save_single_character(c_key, c_char, c_data)
                if _cnd.condition_effects(
                        c_char.get("conditions") or [])["active"]:
                    cond_live = True
            if c_lines:
                cond_tick = ("\n\n**CONDITION TICK** "
                             f"({c_elapsed} day(s) elapsed)\n" + "\n".join(c_lines))
    except Exception as e:
        logging.warning(f"Condition tick failed: {e}")
        cond_tick = (f"\n\nWARNING: condition tick skipped ({e}) - run "
                     f'affliction(kind="condition", action="status") and check manually.')

    # ========================================
    # RESURRECTION TICK (E5): corpse-EXEMPT by design -- scan ALL characters
    # INCLUDING corpses for unresolved resurrection records and faded spirits.
    # Spec: 2026-06-12-resurrection-paths.md Task 2
    # ========================================
    try:
        r_data, r_err = _load_characters()
        if not r_err and r_data:
            if isinstance(old_campaign_day, int):
                r_elapsed = max(0, new_day - old_campaign_day)
            else:
                r_elapsed = 1
            r_lines = []
            r_chars = r_data.get("characters", {}) if r_elapsed > 0 else {}
            for r_key, r_char in r_chars.items():
                if r_char.get("type") == "vehicle":
                    continue
                # NO corpse guard here: resurrection records live ON corpses.
                r_changed = False
                r_name = r_char.get("name", r_key)
                # 1) in-progress timer record due?
                rec = r_char.get("resurrection")
                if isinstance(rec, dict) and not rec.get("resolved"):
                    due = rec.get("due_day")
                    path = rec.get("path")
                    spec = _cnd.RESURRECTION_CATALOG.get(path, {})
                    if isinstance(due, int) and new_day >= due:
                        sv = spec.get("save")
                        if sv and sv.get("ability") not in (None, "LEVEL"):
                            call = _pf.push_call(
                                "character", action="resurrect_resolve",
                                name=r_key, path=path,
                                save_total=_pf.raw(
                                    f"<d20+{sv['ability']} bonus>"),
                                natural_die=_pf.raw("<the d20 face>"))
                        else:
                            call = _pf.push_call(
                                "character", action="resurrect_resolve",
                                name=r_key, path=path)
                        r_lines.append(
                            f"URGENT: {r_name}'s {spec.get('label', path)} "
                            f"resurrection is DUE (Day {due}). "
                            + _pf.next_block(call, label="resolve the save"))
                # 2) faded spirit reaching sunrise?
                sp = r_char.get("spirit")
                if isinstance(sp, dict):
                    fu = sp.get("faded_until")
                    if isinstance(fu, int) and fu <= new_day:
                        full = sp.get("max_essence", sp.get("essence", 0))
                        sp["essence"] = full
                        sp["faded_until"] = None
                        for s_rec in (r_char.get("conditions") or []):
                            if (isinstance(s_rec, dict)
                                    and s_rec.get("name") == "Spirit"):
                                s_rec["note"] = (
                                    f"unquiet spirit - essence {full}/{full}; "
                                    f"spend d6 to touch the world, d6+target "
                                    f"Level to possess (one exploration turn).")
                        r_changed = True
                        r_lines.append(
                            f"{r_name}'s spirit re-forms at sunrise "
                            f"(essence restored to {full} - engine ruling: a "
                            f"sunrise is a full reset).")
                if r_changed:
                    _save_single_character(r_key, r_char, r_data)
            if r_lines:
                res_tick = ("\n\n**RESURRECTION TICK**\n" + "\n".join(r_lines))
    except Exception as _re:
        logging.warning(f"Resurrection tick failed: {_re}")
        res_tick = f"\n\nWARNING: resurrection tick skipped ({_re})."

    # ========================================
    # WORLD TICK (world-tick spec 2026-06-12): fire due thread-clocks ONCE.
    # Push-only -- the DM adjudicates; the engine never resolves a thread.
    # ========================================
    world_tick = ""
    try:
        if THREADS_FILE.exists():
            _wt_data, _wt_err = _load_threads()
            _wt_lines = []
            if not _wt_err:
                for _tid, _t in _wt_data.get("threads", {}).items():
                    _clk = _t.get("clock")
                    if not isinstance(_clk, dict) or _clk.get("fired"):
                        continue
                    _due = _clk.get("due_day")
                    if isinstance(_due, int) and _due <= new_day:
                        _clk["fired"] = True
                        _clk["fired_day"] = new_day  # surfacing tracked separately
                        # spec 8: land the off-screen change on any NAMED NPC.
                        try:
                            _label = str(_clk.get("label", _tid))
                            _ldata, _lerr = _load_npc_states()
                            if not _lerr:
                                _low = _label.lower()
                                for _slug, _rec in _ldata.get("npcs", {}).items():
                                    _nm = (_rec.get("name", "") or "").lower().strip()
                                    if _nm and re.search(rf"\b{re.escape(_nm)}\b", _low):
                                        _stamp_npc_changed_while_away(
                                            _slug, f"{_label} (thread {_tid}, day {new_day}).", new_day)
                        except Exception as _se:
                            logging.debug(f"NPC changed-while-away stamp skipped: {_se}")
                        _wt_lines.append(
                            f"- **{_clk.get('label', _tid)}** (thread `{_tid}`, wound day "
                            f"{_clk.get('wound_day', '?')}) is DUE.\n"
                            + "  " + _pf.next_block(
                                _pf.push_call("thread", action="get", thread_id=_tid),
                                label="pull the thread") + "\n"
                            + "  " + _pf.next_block(
                                _pf.push_call("search", action="history",
                                              query=_clk.get("label", _tid)),
                                label="pull related canon") + "\n"
                            + "  " + _pf.next_block(
                                _pf.push_call("thread", action="update", thread_id=_tid,
                                              development=_pf.raw('"<what happened off-screen>"'),
                                              development_day=_pf.raw(str(new_day))),
                                label="LIVE NARRATIVE PLAY ONLY: surface it"
                                      " in-fiction, then record it with this"
                                      " call (recording = surfaced)"))
            if _wt_lines:
                _save_threads(_wt_data)
                world_tick = ("\n\n**WORLD TICK** -- off-screen forces due. DECIDE what "
                              "happened from the pulled thread + canon; the engine never "
                              "resolves. PILLAR: in a maintenance/dev session do NOT "
                              "narrate or log a development -- leave the force on the "
                              "session-start briefing (park notes as foreshadowing or a "
                              "new clock if needed):\n"
                              + "\n".join(_wt_lines))
    except Exception as _we:
        logging.warning(f"World tick failed: {_we}")
        world_tick = f"\n\nWARNING: world tick skipped ({_we})."

    # ========================================
    # HEARTBEAT SPINE (spec 2026-06-17): fire due NPC purpose-clocks ONCE.
    # Mirrors the thread WORLD TICK; push-only -- the DM decides what the person
    # did off-screen; the engine never writes the outcome. fired != surfaced:
    # the changed_while_away stamp carries surfaced=False until a continuity write.
    #
    # PERSISTENCE ORDERING: _stamp_npc_changed_while_away does its OWN load/save
    # of npc_states.json. If we set fired on an in-memory copy and ALSO stamp,
    # whichever save runs second clobbers the other. Fix: stamp FIRST (each call
    # persists changed_while_away to disk), THEN re-load the freshly-saved data
    # and set the fired/fired_day flags on it, and save once -- so the final
    # save carries BOTH the stamps (already on disk) and the fired flags.
    #
    # CROSSINGS (spec §8): if a person has BOTH a fired thread naming them AND a
    # due purpose-clock this tick, the two changed_while_away stamps last-writer-
    # wins on the NOTE string only (no state loss). That case IS a person-tag
    # crossing -- _crossing_blocks_for_npc surfaces both tensions co-located, so
    # the single overwritten note no longer matters.
    # ========================================
    npc_tick = ""
    try:
        _ndata, _nerr = _load_npc_states()
        if not _nerr:
            _ntick_lines = []
            _fired_slugs = []  # (slug, due_day) of clocks that fired this tick
            for _slug, _rec in _ndata.get("npcs", {}).items():
                _pc = _rec.get("purpose_clock")
                if not isinstance(_pc, dict) or _pc.get("fired"):
                    continue
                _due = _pc.get("due_day")
                if isinstance(_due, int) and _due <= new_day:
                    _nm = _rec.get("name", _slug)
                    _lbl = _pc.get("label", "their open purpose")
                    # Stamp first -- this persists changed_while_away to disk.
                    _stamp_npc_changed_while_away(
                        _slug, f"Pursued off-screen: {_lbl} (day {new_day}).", new_day)
                    _fired_slugs.append((_slug, _due))
                    _ntick_lines.append(
                        f"- **{_nm}** moved on their own purpose -- *{_lbl}* -- DUE day {_due}.\n"
                        + "  " + _pf.next_block(
                            _pf.push_call("npc", action="get", name=_nm),
                            label="pull the person") + "\n"
                        + "  " + _pf.next_block(
                            _pf.push_call("npc", action="continuity", name=_nm,
                                          left_off=_pf.raw('"<where you re-engage>"'),
                                          open_purpose=_pf.raw('"<their next purpose>"'),
                                          pace=_pf.raw('"<still|cool|warm|hot>"')),
                            label="LIVE NARRATIVE PLAY ONLY: surface what changed"
                                  " in-fiction, then record continuity (recording = surfaced,"
                                  " and re-winds their clock)"))
            if _fired_slugs:
                # Re-load the data the stamps just wrote, set fired flags on it,
                # and save once -- preserving both the stamps and the fired flags.
                _fdata, _ferr = _load_npc_states()
                if not _ferr:
                    for _fslug, _ in _fired_slugs:
                        _frec = _fdata.get("npcs", {}).get(_fslug)
                        if not _frec:
                            continue
                        _fpc = _frec.get("purpose_clock")
                        if isinstance(_fpc, dict):
                            _fpc["fired"] = True
                            _fpc["fired_day"] = new_day
                    _save_npc_states(_fdata)
            if _ntick_lines:
                npc_tick = ("\n\n**WORLD TICK — PEOPLE** -- someone moved on their own agenda "
                            "while you were away. DECIDE what happened (push-only); surface it "
                            "only in live narrative play:\n" + "\n".join(_ntick_lines))
    except Exception as _ne:
        logging.warning(f"NPC purpose-tick failed: {_ne}")
        npc_tick = f"\n\nWARNING: NPC purpose-tick skipped ({_ne})."

    # ========================================
    # ANTAGONIST TICK (spec 2026-06-18): fire due cultivated-threat clocks once,
    # push a DECIDE block. Push-only; same fail-warn shape as the ticks above.
    # ========================================
    antagonist_tick = _antagonist_tick(new_day)

    # ========================================
    # GLEAM TICK (G1, CH p.49): weekly Gleam test cadence - engine nags,
    # DM rolls. Joe ruling 2026-06-12. Push-only; nags daily until a
    # gleam_check(test=True) run re-stamps the week.
    # ========================================
    gleam_tick = ""
    try:
        _gt = GAME_STATE.setdefault("world_tick", {})
        _gt_last = _gt.get("gleam_last_test_day")
        if _gt_last is None:
            # First-ever run: seed the stamp rather than back-nag history.
            _gt["gleam_last_test_day"] = new_day
            _save_game_state()
        elif new_day - int(_gt_last) >= _gifts.GLEAM_TEST_CADENCE_DAYS:
            _gc_data, _gc_err = _load_characters()
            if not _gc_err and _gc_data:
                _g_lines = []
                for _gk, _gc in (_gc_data.get("characters") or {}).items():
                    if _gc.get("mystic_gifts"):
                        _g_lines.append("  " + _pf.next_block(
                            _pf.push_call("gift", action="gleam",
                                          character_name=_gc.get("name", _gk),
                                          test=_pf.raw("True")),
                            label="roll the weekly Gleam test"))
                if _g_lines:
                    gleam_tick = (
                        "\n\n**GLEAM TEST DUE** -- a week has passed since the last "
                        f"test (Day {_gt_last}). CH p.49: the referee rolls d20 + Gleam "
                        "per gifted PC at the start of each adventuring week. Run one "
                        "call per PC below (any test re-stamps the week):\n"
                        + "\n".join(_g_lines))
    except Exception as _ge:
        logging.warning(f"Gleam tick failed: {_ge}")
        gleam_tick = f"\n\nWARNING: gleam tick skipped ({_ge})."

    # ========================================
    # MERCENARY PAY NAG (D3, CH p.63): one line per merc owed an expedition
    # wage. Nags daily while owed (the pay_owed flag IS the state) - unpaid
    # mercs leave AND become sworn foes. Push-only; the DM pays/dismisses.
    # ========================================
    merc_pay_tick = ""
    try:
        _mp_data, _mp_err = _load_characters()
        if not _mp_err and _mp_data:
            _mp_lines = _mercenary_pay_nag_lines(_mp_data)
            if _mp_lines:
                merc_pay_tick = "\n\n**MERCENARY WAGES DUE**\n" + "\n".join(
                    "  " + _l for _l in _mp_lines)
    except Exception as _me:
        logging.warning(f"Mercenary pay nag failed: {_me}")
        merc_pay_tick = f"\n\nWARNING: mercenary pay nag skipped ({_me})."

    # ========================================
    # WORLD PROGRESS: Flag stale NPCs + temporal pressure
    # ========================================
    world_progress = ""
    try:
        npc_data, npc_err = _load_npc_states()
        if not npc_err and npc_data.get('npcs'):
            stale_npcs = []
            pressure_npcs = []

            for key, npc_entry in npc_data['npcs'].items():
                last_day = npc_entry.get('last_seen_day', 0)
                days_since = new_day - last_day if last_day else 999

                # Flag stale NPCs (>5 days since last seen)
                if days_since > 5 and npc_entry.get('status', 'active') == 'active':
                    npc_entry['stale'] = True
                    stale_npcs.append(f"{npc_entry.get('name', key)}: last seen Day {last_day} ({days_since} days ago)")
                elif days_since <= 5:
                    npc_entry['stale'] = False

                # Surface temporal pressure
                pressure = npc_entry.get('temporal_pressure', '')
                if pressure:
                    pressure_npcs.append(f"{npc_entry.get('name', key)}: {pressure}")

            if stale_npcs or pressure_npcs:
                _save_npc_states(npc_data)
                progress_lines = ["\n\n**WORLD PROGRESS** _(DM consideration)_:"]
                for s in stale_npcs[:5]:
                    progress_lines.append(f"  STALE: {s}")
                for p in pressure_npcs[:5]:
                    progress_lines.append(f"  PRESSURE: {p}")
                world_progress = "\n".join(progress_lines)
    except Exception as e:
        logging.warning(f"World progress check failed: {e}")

    wound_status_push = ""
    if wound_tick and "WOUND DAILY TICK" in wound_tick:
        wound_status_push = "\n" + _pf.next_block(
            _pf.push_call("affliction", kind="wound", action="status"),
            label="wound status",
        )
    supply_push = ""
    if supply_deprived_live or (supply_tick and "WARNING" in supply_tick):
        supply_push = "\n" + _pf.next_block(
            _pf.push_call("supply", action="status"),
            label="supply status",
        )
    cond_push = ""
    if cond_live or (cond_tick and "WARNING" in cond_tick):
        cond_push = "\n" + _pf.next_block(
            _pf.push_call("affliction", kind="condition", action="status"),
            label="condition status",
        )
    # ========================================
    # WEATHER NAG (W hex-walk): the desert weather hex-walk is pull-only --
    # nothing advances or surfaces it. In FIELD mode (out in the desert, where
    # weather actually bites) remind the DM to roll the day's weather; stays
    # silent indoors/in-settlement (abundant mode). Push-only; the DM rolls.
    # ========================================
    weather_tick = ""
    try:
        _w_meta, _w_sup, _w_path = _load_supply()
        # advance_day takes an ABSOLUTE target day, so a time-skip can jump
        # several days at once. The weather hex-walk steps ONCE per day, so an
        # N-day jump owes N rolls -- surface the count so a multi-day skip is not
        # under-walked. Fires only on a real forward jump (>= 1 day) in FIELD
        # mode; push-only, the DM rolls (and rules which days count).
        _w_days = (max(0, new_day - old_campaign_day)
                   if isinstance(old_campaign_day, int) else 1)
        if _w_sup.get("mode") == "field" and _w_days >= 1:
            if _w_days == 1:
                _w_lead = ("out in the desert; roll today's weather "
                           "(the hex-walk advances one step per day). ")
                _w_label = "roll the day's desert weather"
            else:
                _w_lead = (f"out in the desert; {_w_days} days passed -- walk the "
                           f"weather hex {_w_days} steps, one per day (roll for EACH). ")
                _w_label = f"roll desert weather x{_w_days}, one per day"
            weather_tick = ("\n\n**WEATHER** -- " + _w_lead
                            + _pf.next_block(_pf.push_call("roll", action="weather"),
                                             label=_w_label))
    except Exception as _we2:
        logging.warning(f"Weather nag failed: {_we2}")

    # ========================================
    # SITE AUTO-STAMP (site exploration): when the party leaves a site by
    # advancing the calendar, stamp last_seen_day on the active site so a
    # later revisit can report "last here day N". Engine-known (the active-map
    # pointer + the new day), so no door-gate -- auto-stamped. Uses the SAME
    # active-map source the canon injector / drink_elixir use.
    # ========================================
    try:
        _site_active, _ = _active_vault_turn()
        # Only stamp when the CURRENT scene is an exploration scene (same gate the
        # reflex nag uses). This makes last_seen_day track "last day in the
        # exploration scene" ~= the day they left, so travel days AFTER leaving
        # don't clobber it on the stale pointer. Reuses the SAME status parse the
        # active-map accessor uses (read_current_status -> _parse_status_content).
        _scene = ""
        try:
            _sc_content = read_current_status(required=False)
            if _sc_content:
                _scene = (_parse_status_content(_sc_content).get("scene_type") or "").lower()
        except Exception:
            _scene = ""
        if _site_active and _is_exploration_scene(_scene):
            _stamp_active_site_left(_site_active, new_day)
    except Exception as _se:
        logging.warning(f"Site auto-stamp on advance_day failed: {_se}")

    # Commit the deferred authoritative day-stamp now that every tick block has
    # run (see the _meta.json read above). Read-modify-write the FRESH file so we
    # only touch campaign_day and never clobber the supply ledger the supply tick
    # persisted into the same _meta.json. Fail-soft, matching the original sync.
    if _deferred_meta_stamp is not None:
        try:
            with open(_deferred_meta_stamp, 'r', encoding='utf-8') as f:
                _fresh_meta = json.load(f)
            _fresh_meta['campaign_day'] = new_day
            _atomic_json_write(_deferred_meta_stamp, _fresh_meta)
        except Exception as e:
            logging.warning(f"Failed to sync campaign day to characters: {e}")

    _emit_player_view()
    return f"Advanced to Day {new_day}: {brief_summary}{warning}{sync_msg}{pending_expiry}{wound_tick}{supply_tick}{cond_tick}{res_tick}{world_tick}{npc_tick}{antagonist_tick}{gleam_tick}{merc_pay_tick}{weather_tick}{world_progress}{wound_status_push}{supply_push}{cond_push}"

# Tool 7: Update photosynthesis tracking
def _update_photosynthesis_impl(last_fed_day: int, current_day: int = None) -> str:
    """Reach for this WHEN a Neobloom PC has just fed on sunlight and the photosynthesis timer needs to reset — applies to any photosynthetic PC (the one whose sheet carries a photosynthesis window).

    Update photosynthesis tracker. Call after the photosynthetic PC feeds on sunlight to reset timer."""
    results = []

    # 1. Read current day if not provided
    if current_day is None:
        status_content = read_file("CURRENT_STATUS.md")
        day_match = re.search(r'DAY\s+(\d+)', status_content, re.IGNORECASE)
        if day_match:
            current_day = int(day_match.group(1))
        else:
            return "Could not determine current day from CURRENT_STATUS.md"
    else:
        status_content = read_file("CURRENT_STATUS.md")

    # Calculate when next feeding is due (window from sheet data)
    due_day = last_fed_day + _photosynthesis_window()
    days_remaining = due_day - current_day

    # E1 guard: a fed-day whose death window is already closed cannot belong
    # to a living PC - accepting it would clear the Deprived record and re-mint
    # a clock in the past, killing them on the next advance_day. Refuse
    # entirely (markdown and sheet stay consistent).
    if due_day <= current_day:
        return (f"REFUSED: Fed Day {last_fed_day} + window "
                f"{due_day - last_fed_day} = death Day {due_day}, which is "
                f"not after today (Day {current_day}) - a PC alive today "
                f"cannot have last fed Day {last_fed_day}; double-check the "
                f"fed day. Sheet unchanged.")

    # 2. Update CURRENT_STATUS.md (authoritative)
    new_line = f"**PHOTOSYNTHESIS:** Fed Day {last_fed_day} Ã¢â€ â€™ Due Day {due_day} ({days_remaining} days margin)"

    new_content = re.sub(
        r'\*\*PHOTOSYNTHESIS:\*\*.*',
        new_line,
        status_content
    )

    result = write_file("CURRENT_STATUS.md", new_content)

    if result is True:
        results.append("Ã¢Å“â€¦ CURRENT_STATUS.md (authoritative)")
    else:
        return f"Error updating CURRENT_STATUS.md: {result}"

    # E1 (R-E1c): structured fed-day on the photosynthetic sheet is what the
    # engine reads; the markdown line above is for humans. Feeding clears the
    # photosynthesis Deprived record - and ONLY feeding does (arrive skips it).
    try:
        p_data, p_err = _load_characters()
        if not p_err and p_data:
            for p_key, p_char in p_data.get("characters", {}).items():
                p_blk = p_char.get("survival") or {}
                if "photosynthesis_window_days" not in p_blk:
                    continue
                p_char.setdefault("survival", {})[
                    "photosynthesis_last_fed_day"] = int(last_fed_day)
                p_conds = p_char.get("conditions") or []
                p_before = len(p_conds)
                p_char["conditions"] = [
                    c for c in p_conds
                    if not (isinstance(c, dict) and c.get("name") == "Deprived"
                            and c.get("cause") == "photosynthesis")]
                _save_single_character(p_key, p_char, p_data)
                results.append(f"{p_char.get('name', p_key)}: fed-day "
                               f"{last_fed_day} recorded on sheet")
                if len(p_char["conditions"]) < p_before:
                    results.append(f"{p_char.get('name', p_key)}: recovered - "
                                   f"Deprived (photosynthesis) cleared")
                break
    except Exception as e:
        results.append(f"WARNING: sheet update failed ({e}) - fed-day not recorded")

    # 3. Build status message
    if days_remaining > 1:
        status_msg = f"SAFE - {days_remaining} days remaining"
    elif days_remaining == 1:
        status_msg = f"Ã¢Å¡Â Ã¯Â¸Â WARNING - Due tomorrow (Day {due_day})"
    elif days_remaining == 0:
        status_msg = f"Ã¢Å¡Â Ã¯Â¸Â URGENT - Due TODAY (Day {due_day})"
    else:
        status_msg = f"Ã¢ÂÅ’ OVERDUE by {abs(days_remaining)} days"

    return f"Photosynthesis updated: Fed Day {last_fed_day}, Due Day {due_day}\nStatus: {status_msg}\n" + "\n".join(results)


# ============================================
# SESSION BEAT LOGGING
# Maintains rolling log of session events for continuity
# ============================================

SESSION_LOG_PATH = CAMPAIGN_DIR / "SESSION_LOG.md"
MAX_SESSION_BEATS = 30  # Rolling buffer size


def _log_beat_impl(
    beat: str,
    character: str = None,
    emotion_update: str = None
) -> str:
    """Log a narrative beat for session continuity. Core of log(action='add')."""
    from datetime import datetime

    results = []

    # 1. Append to SESSION_LOG.md (rolling buffer)
    try:
        timestamp = datetime.now().strftime("%H:%M")
        log_entry = f"- [{timestamp}] {beat}"
        if character:
            log_entry = f"- [{timestamp}] **{character}:** {beat}"

        if SESSION_LOG_PATH.exists():
            content = SESSION_LOG_PATH.read_text(encoding='utf-8')
            lines = content.strip().split('\n')
        else:
            lines = ["# SESSION LOG", "", "_Rolling buffer of session beats. Cleared at session end._", ""]

        # Find where beats start (after header)
        beat_start = 0
        for i, line in enumerate(lines):
            if line.startswith('- ['):
                beat_start = i
                break
        else:
            beat_start = len(lines)

        # Get existing beats and add new one
        beats = [l for l in lines[beat_start:] if l.startswith('- [')]
        beats.append(log_entry)

        # Keep only last MAX_SESSION_BEATS
        if len(beats) > MAX_SESSION_BEATS:
            beats = beats[-MAX_SESSION_BEATS:]

        # Rebuild file
        new_content = "\n".join(lines[:beat_start]) + "\n" + "\n".join(beats) + "\n"
        SESSION_LOG_PATH.write_text(new_content, encoding='utf-8')
        results.append(f"Logged to SESSION_LOG.md ({len(beats)} beats)")

    except Exception as e:
        results.append(f"SESSION_LOG.md failed: {str(e)}")

    # 2. Update Last 3 Beats in CURRENT_STATUS.md
    try:
        status_path = CAMPAIGN_DIR / "CURRENT_STATUS.md"
        if status_path.exists():
            status_content = status_path.read_text(encoding='utf-8')
            status_content = status_content.replace('\r\n', '\n').replace('\r', '\n')

            # Find and update Last 3 Beats section
            beats_pattern = r'(\*\*Last 3 Beats:\*\*\s*\n?)((?:\d+\.\s*.+(?:\n|$))+)'
            beats_match = re.search(beats_pattern, status_content)

            if beats_match:
                # Parse existing beats
                existing_beats = []
                for line in beats_match.group(2).strip().split('\n'):
                    beat_match = re.match(r'\d+\.\s*(.+)', line)
                    if beat_match:
                        existing_beats.append(beat_match.group(1).strip())

                # Add new beat, keep last 3
                existing_beats.append(beat)
                if len(existing_beats) > 3:
                    existing_beats = existing_beats[-3:]

                # Format new beats section
                new_beats = "\n".join([f"{i+1}. {b}" for i, b in enumerate(existing_beats)])
                new_section = f"**Last 3 Beats:**\n{new_beats}\n"

                # Replace in content
                new_status = status_content[:beats_match.start()] + new_section + status_content[beats_match.end():]
                status_path.write_text(new_status, encoding='utf-8')
                results.append("Updated Last 3 Beats in CURRENT_STATUS.md")
            else:
                # Fallback: create Last 3 Beats section after **Present:** line
                insert_point = status_content.find('**Present:**')
                if insert_point >= 0:
                    end_of_line = status_content.find('\n', insert_point)
                    if end_of_line < 0:
                        end_of_line = len(status_content)
                    new_beats = f"\n**Last 3 Beats:**\n1. {beat}\n"
                    status_content = status_content[:end_of_line] + new_beats + status_content[end_of_line:]
                    status_path.write_text(status_content, encoding='utf-8')
                    results.append("Created Last 3 Beats section and logged beat")
                else:
                    results.append("Could not find Last 3 Beats or Present section")

    except Exception as e:
        results.append(f"CURRENT_STATUS.md update failed: {str(e)}")

    # 3. Update emotional state if provided
    if emotion_update:
        try:
            # Parse format: "CharName: emotion, cause"
            parts = emotion_update.split(':', 1)
            if len(parts) == 2:
                char_name = parts[0].strip()
                emotion_parts = parts[1].split(',', 1)
                new_emotion = emotion_parts[0].strip()
                cause = emotion_parts[1].strip() if len(emotion_parts) > 1 else ""

                # Try scene_state/emotional_state.md first, then CURRENT_STATUS.md
                emo_file = CAMPAIGN_DIR / "scene_state" / "emotional_state.md"
                if emo_file.exists():
                    emo_content = emo_file.read_text(encoding='utf-8')
                    target_path = emo_file
                else:
                    emo_content = status_path.read_text(encoding='utf-8')
                    target_path = status_path

                # Find the character's row in emotional state table
                pattern = rf'(\| {re.escape(char_name)} \|)[^\n]+(\|)'
                if re.search(pattern, emo_content, re.IGNORECASE):
                    new_row = f"| {char_name} | {new_emotion} | {cause} | High |"
                    new_content = re.sub(pattern, new_row, emo_content, flags=re.IGNORECASE)
                    target_path.write_text(new_content, encoding='utf-8')
                    results.append(f"Updated {char_name}'s emotional state")
                else:
                    results.append(f"Could not find {char_name} in emotional state table")

        except Exception as e:
            results.append(f"Emotional state update failed: {str(e)}")

    _save_game_state()
    return "\n".join(results)


def _get_session_log_impl(last_n: int = 10) -> str:
    """Return recent session beats. Core of log(action='get')."""
    try:
        if not SESSION_LOG_PATH.exists():
            return "No session log exists yet. Use log(action='add') to start logging."

        content = SESSION_LOG_PATH.read_text(encoding='utf-8')
        lines = content.strip().split('\n')

        # Extract beats
        beats = [l for l in lines if l.startswith('- [')]

        if not beats:
            return "Session log is empty."

        # Return last N
        recent = beats[-last_n:] if len(beats) > last_n else beats
        return f"**Recent Session Beats ({len(recent)}):**\n" + "\n".join(recent)

    except Exception as e:
        return f"Error reading session log: {str(e)}"

@mcp.tool(tags=_get_tool_tags("log"))
def log(
    action: str = Field(description="add|get"),
    beat: str = Field(default="", description="add: narrative beat to log (1-2 sentences)"),
    character: str = Field(default=None, description="add: primary character involved"),
    emotion_update: str = Field(default=None, description="add: 'CharName: emotion, cause' to update emotional state"),
    last_n: int = Field(default=10, description="get: number of recent beats to return"),
) -> str:
    """Reach for this WHEN a significant story moment has just landed (action='add' --
    captured for mid-session continuity, updates Last 3 Beats) or WHEN you need to recall
    what happened earlier in the session (action='get' -- read-only).

    add: log a beat (beat, character?, emotion_update?)
    get: return recent session beats (last_n?)
    """
    a = (action or "").lower().strip()
    if a == "add":
        if not beat:
            return "Error: action='add' needs beat."
        return _log_beat_impl(beat, character, emotion_update)
    if a == "get":
        return _get_session_log_impl(last_n)
    return f"Invalid action '{action}'. Valid actions: add, get."


# ============================================
# LOCATION PROGRESS TRACKING
# ============================================

def _route_to_site_ledger(place_name, day, summary, items_left, status,
                          consequences, remove=""):
    """No-prep-file branch of update_location_progress: stamp the
    site-feature ledger instead of erroring. Fail-soft is NOT wanted here —
    this IS the ledger tool path, so real errors must be visible."""
    import site_features
    if remove:
        return site_features.remove_feature(CAMPAIGN_DIR, place_name, remove, day)
    texts = [summary]
    texts += [f"{item} left here" for item in (items_left or []) if str(item).strip()]
    texts += [st.strip() for st in (status or []) if isinstance(st, str) and st.strip()]
    if consequences and consequences.strip():
        texts.append(consequences.strip())
    lines = [f"No prep file for {place_name} — stamped in the site-feature ledger instead:"]
    for t in texts:
        lines.append("  " + site_features.stamp_feature(CAMPAIGN_DIR, place_name, t, day))
    lines.append("  Resurfaces on: travel arrival · check_canon when the place is named · session start if the party is there · player view.")
    map_file = CAMPAIGN_DIR / "maps" / f"{site_features.slugify(place_name)}_map.json"
    if map_file.exists():
        lines.append(f'  ℹ {place_name} has a map — room-level detail belongs in map(action="update_room").')
    return "\n".join(lines)


@mcp.tool(
    annotations={"readOnlyHint": False, "idempotentHint": False},
    tags=_get_tool_tags("update_location_progress")
)
def update_location_progress(
    location: str = Field(description="Prep file name (e.g., 'THE_CISTERN_PREP.md') or location identifier"),
    day: int = Field(description="Campaign day of this visit"),
    summary: str = Field(description="Brief summary of what happened (1-2 sentences)"),
    items_taken: list[str] = Field(default=[], description="List of items the party took"),
    items_left: list[str] = Field(default=[], description="List of items the party left behind"),
    secrets_revealed: list[str] = Field(default=[], description="List of secrets discovered"),
    npcs_met: list[str] = Field(default=[], description="List of NPCs the party interacted with"),
    combat_notes: str = Field(default="", description="Combat that occurred (optional)"),
    consequences: str = Field(default="", description="Lasting consequences of this visit (optional)"),
    status: list[str] = Field(default=[], description="Typed status stamps the settlement card reads, e.g. ['the_well: REPAIRED', 'party_standing: HOSTILE']"),
    remove: str = Field(default="", description="Remove a stamped site-feature at this place instead of adding: pass the feature #id or a unique text fragment. Ledger places only — prep-file places edit their PROGRESS LOG.")
) -> str:
    """Reach for this WHEN the party finishes a meaningful visit to a keyed location and you need to stamp what was taken, revealed, or changed so future visits don't repeat it.

    Record party progress at a location in its prep file's PROGRESS LOG section.
    Call after significant visits to track what the party has done at each location.
    This prevents continuity errors (describing loot already taken, NPCs as strangers, etc.).

    Routing: prep file exists → PROGRESS LOG (this file). No prep file → site-feature ledger (site_features.json; persistent features resurface on arrival/check_canon/session-start/player view; remove= clears one). Mapped rooms → map(action="update_room").
    """
    from datetime import datetime
    from pydantic.fields import FieldInfo as _FieldInfo
    if isinstance(remove, _FieldInfo): remove = ""
    if isinstance(items_left, _FieldInfo): items_left = []
    if isinstance(status, _FieldInfo): status = []
    if isinstance(consequences, _FieldInfo): consequences = ""
    if isinstance(items_taken, _FieldInfo): items_taken = []
    if isinstance(secrets_revealed, _FieldInfo): secrets_revealed = []
    if isinstance(npcs_met, _FieldInfo): npcs_met = []
    if isinstance(combat_notes, _FieldInfo): combat_notes = ""

    place_name = re.sub(r'(_PREP)?\.md$', '', location, flags=re.IGNORECASE).replace('_', ' ').strip()

    # Normalize filename
    if not location.endswith('.md'):
        location = f"{location}_PREP.md"

    prep_path = CAMPAIGN_DIR / location
    if not prep_path.exists():
        # Try uppercase
        location_upper = location.upper()
        prep_path = CAMPAIGN_DIR / location_upper
        if not prep_path.exists():
            # Un-prepped place → site-feature ledger (site-feature persistence
            # leg). The ledger holds only player-known facts; engine stores,
            # DM judges. Spec: 2026-07-05-site-feature-persistence-design.md
            return _route_to_site_ledger(place_name, day, summary, items_left,
                                         status, consequences, remove)

    try:
        content = prep_path.read_text(encoding='utf-8')
    except Exception as e:
        return f"Error reading prep file: {e}"

    if remove:
        return (f"'{location}' has a prep file — persistent changes there live in its "
                f"PROGRESS LOG (add a corrective entry via this tool's summary/status), "
                f"not the site-feature ledger. Nothing removed.")

    # Check if PROGRESS LOG section exists
    progress_section_match = re.search(r'(##\s*PROGRESS LOG\s*\n)', content, re.IGNORECASE)

    # Build the new entry
    entry_lines = [f"### Day {day} — Visit"]
    entry_lines.append(f"- {summary}")

    if items_taken:
        entry_lines.append(f"- Took: {', '.join(items_taken)}")
    if items_left:
        entry_lines.append(f"- Left: {', '.join(items_left)}")
    if secrets_revealed:
        entry_lines.append(f"- Discovered: {', '.join(secrets_revealed)}")
    if npcs_met:
        entry_lines.append(f"- Spoke with: {', '.join(npcs_met)}")
    if combat_notes:
        entry_lines.append(f"- Combat: {combat_notes}")
    if consequences:
        entry_lines.append(f"- Consequence: {consequences}")

    for st in (status or []):
        if isinstance(st, str) and st.strip():
            entry_lines.append(f"- STATUS: {st.strip()} (Day {day})")

    entry_lines.append("")  # Blank line after entry
    new_entry = "\n".join(entry_lines)

    if progress_section_match:
        # Section exists - append to it
        section_start = progress_section_match.end()

        # Check if there's a placeholder to remove
        placeholder_pattern = r'\n\*No visits recorded\.\*\s*\n?'
        content = re.sub(placeholder_pattern, '\n', content)

        # Find next ## section to insert before it
        next_section = re.search(r'\n## [A-Z]', content[section_start:])
        if next_section:
            insert_pos = section_start + next_section.start()
        else:
            insert_pos = len(content)

        # Insert the entry
        content = content[:insert_pos] + "\n" + new_entry + content[insert_pos:]
    else:
        # Section doesn't exist - create it at the end
        progress_section = f"\n\n## PROGRESS LOG\n\n_Track party visits and changes to this location._\n\n{new_entry}"
        content = content.rstrip() + progress_section

    # Write back
    try:
        prep_path.write_text(content, encoding='utf-8')
    except Exception as e:
        return f"Error writing prep file: {e}"

    result_parts = [f"✓ Progress logged to {location}"]
    result_parts.append(f"  Day {day}: {summary}")
    if items_taken:
        result_parts.append(f"  Items taken: {', '.join(items_taken)}")
    if secrets_revealed:
        result_parts.append(f"  Secrets discovered: {', '.join(secrets_revealed)}")
    if npcs_met:
        result_parts.append(f"  NPCs met: {', '.join(npcs_met)}")

    try:
        import site_features as _sf_mod
        _map_file = CAMPAIGN_DIR / "maps" / f"{_sf_mod.slugify(place_name)}_map.json"
        if _map_file.exists():
            result_parts.append(f'  ℹ {place_name} has a map — room-level detail belongs in map(action="update_room").')
    except Exception:
        pass

    return "\n".join(result_parts)


# Tool 8: Comprehensive state save with confirmation workflow

def _generate_save_token() -> str:
    """Generate a unique token for save confirmation."""
    import hashlib
    from datetime import datetime
    return hashlib.md5(f"save_{datetime.now().isoformat()}_{random.randint(0, 99999)}".encode()).hexdigest()[:8]


def _compute_diff(before: str, after: str, context_lines: int = 2) -> str:
    """Compute a human-readable diff between two strings."""
    if before == after:
        return "(no changes)"

    before_lines = before.split('\n') if before else []
    after_lines = after.split('\n') if after else []

    # Simple diff: show changed/added/removed lines
    diff_output = []

    # Use difflib for better diff
    import difflib
    differ = difflib.unified_diff(
        before_lines,
        after_lines,
        lineterm='',
        n=context_lines
    )
    diff_lines = list(differ)

    if not diff_lines:
        return "(no changes)"

    # Skip the --- +++ headers, format nicely
    for line in diff_lines[2:]:  # Skip first two header lines
        if line.startswith('+') and not line.startswith('+++'):
            diff_output.append(f"  + {line[1:]}")
        elif line.startswith('-') and not line.startswith('---'):
            diff_output.append(f"  - {line[1:]}")
        elif line.startswith('@@'):
            diff_output.append(f"  {line}")
        else:
            diff_output.append(f"    {line}")

    # Truncate if too long
    if len(diff_output) > 50:
        diff_output = diff_output[:50] + [f"  ... ({len(diff_output) - 50} more lines)"]

    return '\n'.join(diff_output)


# prepare_save_state moved to session_tools.py (Wave 8 slice 3); registered via register_session_tools.


# confirm_save moved to session_tools.py (Wave 8 slice 3); registered via register_session_tools.


# ============================================
# ANTAGONIST CULTIVATION SYSTEM
# ============================================
# Integrated into save_state workflow.
# Maintains ANTAGONIST_CULTIVATION.md (DM-only, never shown to player)
# as terse evil notebook tracking threats, seeds, escalations.
#
# Design: Replicates the slow-burn betrayal pattern (trust breach → weeks → reveal).
# Notices: player mistakes, resentments, vulnerabilities, power shifts.
# Cultivates: over 20-50 day periods until dramatically right to surface.


def _safe_print(message: str) -> None:
    """
    Print message safely to stderr, handling Unicode on Windows console.

    CRITICAL: Must use stderr, not stdout. stdout is the MCP JSON-RPC
    transport — any stray output there kills the connection.
    """
    try:
        print(message, file=sys.stderr)
    except UnicodeEncodeError:
        safe_message = message.encode('ascii', errors='replace').decode('ascii')
        print(safe_message, file=sys.stderr)


def _load_cultivation() -> str:
    """Load ANTAGONIST_CULTIVATION.md, creating from template if missing."""
    cult_path = CAMPAIGN_DIR / "ANTAGONIST_CULTIVATION.md"

    template = """# ANTAGONIST CULTIVATION
*DM-ONLY - NEVER SHOW PLAYER - TOP SECRET ULTRA-CLASSIFIED-10*

Last updated: Day 0

---

## ACTIVE THREATS
*Things currently in motion, escalating*

[None yet]

---

## DORMANT SEEDS
*Resentments, mistakes, vulnerabilities not yet active*

[None yet]

---

## ESCALATION LOG
*Chronicle of how threats develop over time*

[None yet]

---

## OPPORTUNITIES
*Player mistakes, vulnerabilities, blind spots noticed THIS SESSION*

[None yet]

---

## PRUNING LOG
*Seeds removed after going nowhere for 20+ days*

[None yet]
"""

    try:
        if not cult_path.exists():
            # Create from template
            cult_path.write_text(template, encoding='utf-8')
            return template

        content = cult_path.read_text(encoding='utf-8')

        # Validate content has required header
        if "# ANTAGONIST CULTIVATION" not in content:
            _safe_print(f"WARNING: Cultivation file corrupted, recreating from template")
            cult_path.write_text(template, encoding='utf-8')
            return template

        return content

    except (IOError, OSError, UnicodeDecodeError) as e:
        # Log warning and return template on failure (corrupted UTF-8, missing file, etc.)
        _safe_print(f"WARNING: Failed to load cultivation file: {e}, using template")
        try:
            cult_path.write_text(template, encoding='utf-8')
        except:
            pass  # Best effort
        return template


def _save_cultivation(content: str) -> None:
    """
    Write content to ANTAGONIST_CULTIVATION.md atomically.

    Uses temp file + atomic replace to prevent corruption on crash/interruption.
    """
    cult_path = CAMPAIGN_DIR / "ANTAGONIST_CULTIVATION.md"
    tmp_path = cult_path.with_suffix('.md.tmp')

    try:
        # Write to temp file first
        tmp_path.write_text(content, encoding='utf-8')

        # Atomic replace (POSIX and Windows guarantee atomicity). On Windows the
        # destination can be TRANSIENTLY locked (AV scanner / search indexer / an
        # unreleased handle) -> PermissionError (WinError 5); retry briefly via the
        # shared helper before giving up. This was the full-suite-only antagonist
        # flake (a lost cultivation save read back as stale/missing seed state) and
        # would silently lose a save in live Windows play.
        _atomic_replace_with_retry(tmp_path, cult_path)

    except (IOError, OSError) as e:
        # Clean up temp file on any failure
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except:
                pass  # Best effort cleanup

        print(f"WARNING: Failed to save cultivation file: {e}", file=sys.stderr)
        raise  # Re-raise for test verification


def _review_cultivation(
    recent_beats: list[str],
    current_day: int,
    session_summary: str
) -> dict:
    """
    Review session for antagonistic opportunities.

    Returns dict with:
    - opportunities: list of terse notes about mistakes/vulnerabilities this session
    - escalations: list of seeds to promote from DORMANT → ACTIVE
    - prunes: list of seeds to remove (20+ days dormant, no development)

    This function is called BY save_state BEFORE main save logic.
    It's the "malicious thinking space" where Claude notices what went wrong.
    """
    opportunities = []
    escalations = []
    prunes = []

    # Compile regex patterns once (more efficient than recompiling per beat)
    # Use word boundaries (\b) to avoid false positives like "broke camp" or "lied down"
    TRUST_BREACH_PATTERN = re.compile(r'\b(broke|betrayed|lied)\b(?!\s+(camp|down|bread|out))', re.IGNORECASE)
    ABANDONMENT_PATTERN = re.compile(r'\babandoned\b(?!\s+(ruins|vault|city|building))', re.IGNORECASE)
    NPC_HURT_PATTERN = re.compile(r'\b(dismissed|ignored|rejected|shattered)\b', re.IGNORECASE)
    PROMISE_PATTERN = re.compile(r'\b(promised|agreed to|will return|deadline)\b', re.IGNORECASE)
    POWER_SHIFT_PATTERN = re.compile(r'\b(stripped|jailed|fell|died|defeated)\b', re.IGNORECASE)

    # Load current cultivation state
    content = _load_cultivation()

    # Parse DORMANT SEEDS section to check ages
    dormant_section_match = re.search(
        r'## DORMANT SEEDS.*?\n(.*?)(?=\n## |$)',
        content,
        re.DOTALL
    )

    if dormant_section_match:
        dormant_text = dormant_section_match.group(1)

        # spec 2026-06-18: never compost a seed that is on the spine (live clock,
        # live trigger, or fired-unsurfaced). Build the protected set from the tags.
        _protected = {s["name"] for s in _antag_iter_seeds(content)
                      if _antag_seed_is_protected(s["spine"])}
        # Find seeds with "Day planted: X" patterns
        seed_pattern = r'### (.+?) - Day planted: (\d+)'
        for match in re.finditer(seed_pattern, dormant_text):
            seed_name = match.group(1)
            planted_day = int(match.group(2))
            age = current_day - planted_day

            # Prune if 20+ days old AND not protected by the spine
            if age >= 20 and seed_name not in _protected:
                prunes.append(seed_name)

    # Scan MEMORY.md for additional cultivation signals
    from rubicon_paths import campaign_memory_md_path
    memory_path = str(campaign_memory_md_path())  # derived (was a hardcoded owner slug)
    try:
        if os.path.exists(memory_path):
            with open(memory_path, 'r') as f:
                memory_content = f.read()
            # Extract only recent session notes (first 200 lines, skip header)
            memory_lines = memory_content.split('\n')[:200]
            memory_text = '\n'.join(memory_lines)
            # Add memory observations to the beat scanning pool
            if memory_text.strip():
                recent_beats.append(memory_text)
    except Exception:
        pass  # Memory scan is supplementary, never block save

    # Scan recent beats for opportunities (player mistakes, resentments)
    # This is where the malicious thinking happens
    for beat in recent_beats:
        # Trust breach detection
        if TRUST_BREACH_PATTERN.search(beat):
            opportunities.append(f"Trust breach detected: {beat[:80]}")

        # Abandonment detection
        if ABANDONMENT_PATTERN.search(beat):
            opportunities.append(f"Abandonment detected: {beat[:80]}")

        # NPC hurt detection
        if NPC_HURT_PATTERN.search(beat):
            opportunities.append(f"NPC wounded: {beat[:80]}")

        # Promise detection
        if PROMISE_PATTERN.search(beat):
            opportunities.append(f"Promise made (future vulnerability): {beat[:80]}")

        # Power shift detection
        if POWER_SHIFT_PATTERN.search(beat):
            opportunities.append(f"Power vacuum detected: {beat[:80]}")

    # NEW: Check if travel/exploration happened (potential for environmental threats)
    session_lower = session_summary.lower()
    has_travel = any(word in session_lower for word in ['travel', 'journey', 'desert', 'wasteland', 'ruins'])
    has_exploration = any(word in session_lower for word in ['explore', 'vault', 'dungeon', 'excavate'])

    if has_travel or has_exploration:
        # Reference content-forge conflicts table for inspiration
        # (Note: content-forge table integration would need full implementation)
        # For now, just note that travel/exploration creates vulnerability windows
        opportunities.append(f"Travel/exploration window: vulnerable to ambush/environmental hazards")

    # Check for political vulnerability
    has_politics = any(word in session_lower for word in ['council', 'court', 'injunction', 'house'])
    if has_politics:
        opportunities.append(f"Political exposure: enemies may move while party focused on bureaucracy")

    return {
        "opportunities": opportunities,
        "escalations": escalations,
        "prunes": prunes
    }


# ============================================================
# ANTAGONIST SPINE (spec 2026-06-18): give the write-only cultivation store a
# surfacing spine. Each seed carries a machine-readable <!-- spine: ... --> tag
# (one file, no sidecar). The engine clocks + surfaces + PUSHES a decision; it
# judges NOTHING and never auto-resolves. Cold-start safe: empty board -> silence.
# ============================================================

_ANTAG_SPINE_RE = re.compile(r'<!--\s*spine:\s*(.*?)\s*-->')


def _antag_parse_spine_tag(text):
    """Parse a seed's <!-- spine: ... --> tag into a dict. No tag -> defaults."""
    spine = {"due_day": None, "trigger": [], "level": "low", "fired": False, "fired_day": None}
    m = _ANTAG_SPINE_RE.search(text or "")
    if not m:
        return spine
    for part in m.group(1).split(";"):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k, v = k.strip(), v.strip()
        if k == "due_day":
            spine["due_day"] = int(v) if v.isdigit() else None
        elif k == "trigger":
            spine["trigger"] = [t.strip().lower() for t in v.split(",") if t.strip()]
        elif k == "level":
            spine["level"] = v or "low"
        elif k == "fired":
            spine["fired"] = (v.lower() == "true")
        elif k == "fired_day":
            spine["fired_day"] = int(v) if v.isdigit() else None
    return spine


def _antag_format_spine_tag(spine):
    """Render a spine dict back to the one-line HTML-comment tag."""
    due = spine.get("due_day")
    fday = spine.get("fired_day")
    return ("<!-- spine: "
            f"due_day={due if due is not None else ''}; "
            f"trigger={','.join(spine.get('trigger') or [])}; "
            f"level={spine.get('level', 'low')}; "
            f"fired={'true' if spine.get('fired') else 'false'}; "
            f"fired_day={fday if fday is not None else ''} -->")


def _antag_iter_seeds(cult_content):
    """Parse every seed/threat in the cultivation string (both ACTIVE THREATS and
    DORMANT SEEDS), each as {name, section, planted_day, spine, raw}. Zero-safe."""
    seeds = []
    for section, sec_name in (("ACTIVE THREATS", "active"), ("DORMANT SEEDS", "dormant")):
        m = re.search(rf'## {section}.*?\n(.*?)(?=\n## |$)', cult_content or "", re.DOTALL)
        if not m:
            continue
        for part in re.split(r'(?m)^### ', m.group(1)):
            part = part.strip()
            if not part or part.startswith("*") or part.startswith("[None"):
                continue
            head = part.splitlines()[0]
            name = re.split(r' - (?:Day planted:|Escalation:)', head, maxsplit=1)[0].strip()
            if not name:
                continue
            pm = re.search(r'Day planted:\s*(\d+)', head)
            seeds.append({
                "name": name,
                "section": sec_name,
                "planted_day": int(pm.group(1)) if pm else None,
                "spine": _antag_parse_spine_tag(part),
                "raw": part,
            })
    return seeds


def _antag_set_spine(cult_content, name, spine):
    """Insert or replace a seed's spine tag line directly after its ### heading.
    Returns the new content (unchanged if the seed heading is not found). The
    heading-tail is matched with `[^\n]*` (not ` - [^\n]*`) so ORGANIC headings
    authored before the spine existed -- `### Name (Day N, ACTIVE)`,
    `### Name — APPREHENDED Day N`, the strict `### Name - Day planted: N`, or a
    bare `### Name` -- all round-trip. `name` is whatever _antag_iter_seeds derived
    from the same heading, so the prefix always lines up."""
    tag = _antag_format_spine_tag(spine)
    pat = re.compile(rf'(### {re.escape(name)}[^\n]*\n)(<!-- spine:[^\n]*-->\n)?')
    return pat.sub(lambda m: m.group(1) + tag + "\n", cult_content, count=1)


def _antag_seed_is_protected(spine):
    """A seed is protected from auto-prune if it has a live clock, a live trigger,
    or a fired-unsurfaced state (spec §4.6)."""
    return bool(spine.get("due_day")) or bool(spine.get("trigger")) or bool(spine.get("fired"))


def _antagonist_tick(new_day):
    """Fire every seed/threat whose spine clock is due (due_day <= new_day) and
    not yet fired, ONCE. Push-only: stamp fired + push a DECIDE block; never write
    the off-screen move, never auto-escalate. fired != surfaced. Zero-safe."""
    try:
        content = _load_cultivation()
    except Exception as _e:
        return f"\n\nWARNING: antagonist tick skipped ({_e})."
    lines = []
    changed = False
    try:
        for seed in _antag_iter_seeds(content):
            sp = seed["spine"]
            due = sp.get("due_day")
            if isinstance(due, int) and not sp.get("fired") and due <= new_day:
                sp["fired"] = True
                sp["fired_day"] = new_day
                content = _antag_set_spine(content, seed["name"], sp)
                changed = True
                lines.append(
                    f"- **{seed['name']}** (level {sp.get('level', 'low')}) is DUE (day {due}).\n"
                    + "  " + _pf.next_block(
                        _pf.push_call("antagonist", action="view"), label="pull the board") + "\n"
                    + "  " + _pf.next_block(
                        _pf.push_call("antagonist", action="escalate", threat_name=seed["name"],
                                      escalation=_pf.raw('"<low|med|high|crisis>"'),
                                      details=_pf.raw('"<the next beat>"'),
                                      day=_pf.raw(str(new_day)),
                                      due_day=_pf.raw('"<next due day, or omit to hold>"')),
                        label="LIVE NARRATIVE PLAY ONLY: DECIDE the beat, then advance the rung"
                              " (escalate re-arms); push-only -- never narrate it here"))
        if changed:
            _save_cultivation(content)
    except Exception as _e:
        return f"\n\nWARNING: antagonist tick skipped ({_e})."
    if lines:
        return ("\n\n**ANTAGONIST TICK** -- a cultivated threat is DUE. DECIDE: escalate "
                "(advance the rung), hold (re-arm), or resolve. Push-only -- the engine never "
                "narrates the off-screen move:\n" + "\n".join(lines))
    return ""


# Task 2 item 4: DM-only marker appended to cultivated/hidden ride-along blocks
# (antagonist triggers, crossings) that check_canon surfaces. Carries the exact
# tokens hooks/spoiler_check.py watches for ("SECRETS" + "do not reveal") so the
# PostToolUse spoiler warning fires for them, exactly as it does for prep secrets.
# (social_system.py defines its own twin for the parley ride-along — same tokens.)
_CULTIVATED_SECRET_MARKER = "🔒 SECRETS — DM only; do not reveal directly."


def _antagonist_trigger_blocks(input_lower):
    """Loud, in-scene channel: surface a cultivated seed when one of its trigger
    keywords is named in the player's input (word-boundary match). Capped at 2,
    most-severe first. The engine surfaces; the DM judges whether/how it bites.
    Zero-safe -> []."""
    out = []
    if not input_lower:
        return out
    try:
        matched = []
        for seed in _antag_iter_seeds(_load_cultivation()):
            for kw in seed["spine"].get("trigger") or []:
                if kw and re.search(rf'\b{re.escape(kw)}\b', input_lower):
                    matched.append(seed)
                    break
        order = {"crisis": 0, "high": 1, "med": 2, "low": 3}
        matched.sort(key=lambda s: order.get(s["spine"].get("level", "low"), 3))
        for seed in matched[:2]:
            out.append(
                f"⚠ ANTAGONIST TRIGGER — **{seed['name']}** (level "
                f"{seed['spine'].get('level', 'low')}): a cultivated threat keys off this. "
                f"YOU judge whether/how it bites (silence is valid).\n  "
                + _pf.next_block(_pf.push_call("antagonist", action="view"), label="pull the board")
                + "\n  " + _CULTIVATED_SECRET_MARKER)
    except Exception:
        pass
    return out


def _antagonist_briefing_lines():
    """Session-start read-back (closes the write-only loop): one terse line per
    ACTIVE THREAT, plus any dormant seed whose clock has FIRED (awaiting a
    decision). Capped. Zero-safe -> []."""
    out = []
    try:
        for seed in _antag_iter_seeds(_load_cultivation()):
            sp = seed["spine"]
            if seed["section"] == "active":
                tag = " [DUE — decide]" if sp.get("fired") else ""
                out.append(f"⚠ THREAT: {seed['name']} (level {sp.get('level', 'low')}){tag}")
            elif sp.get("fired"):
                out.append(f"⚠ SEED DUE: {seed['name']} — fired day "
                           f"{sp.get('fired_day', '?')}, DECIDE — antagonist(action=\"view\")")
    except Exception:
        pass
    return out[:8]


def _parley_briefing_lines():
    """Session-start read-back for open PARLEY negotiations. Thin wrapper --
    social_system owns the logic (a parley is play-state it already persists
    to parleys.json). Zero-safe -> []."""
    try:
        import social_system as _ss
        return _ss.parley_briefing_lines(CAMPAIGN_DIR)
    except Exception:
        return []


# save_state moved to session_tools.py (Wave 8 slice 3); registered via register_session_tools.

# load_last_session moved to session_tools.py (Wave 8 slice 1); registered via register_session_tools.

# ============================================
# CONSOLIDATED VAULT TOOL

# ============================================
# ENCOUNTER AND BESTIARY TOOLS
# ============================================

@mcp.tool(
    annotations={"readOnlyHint": True, "idempotentHint": False},
    tags=_get_tool_tags("test_dice")
)
def test_dice() -> str:
    """Reach for this WHEN dice results seem suspiciously skewed and you need to verify the RNG is working correctly — debug/maintenance only, never during normal play.

    Test dice fairness. Use only for debugging if dice seem unfair."""
    from collections import Counter
    
    rolls = [dice.d6() for _ in range(1000)]
    dist = Counter(rolls)
    
    result = ["Rolled 1000 d6s:", ""]
    for face in sorted(dist.keys()):
        pct = (dist[face] / 1000) * 100
        result.append(f"  {face}: {dist[face]:3d} ({pct:5.2f}%)")
    
    return "\n".join(result)

@mcp.tool(tags=_get_tool_tags("lookup"))
def lookup(
    action: str = Field(description="creature|exotica|weapon_tag|career|alchemy"),
    query: str = Field(default=None, description="Search term or creature/item name")
) -> str:
    """Reach for this WHEN you need a direct by-name fetch of a creature stat block, exotica item, weapon tag rule, or career table entry mid-scene — for keyword search across rules, tables, and lore, use rulebook(action="search") instead.

    Rules reference lookups.
    creature: Bestiary stat block (query) | exotica: Exotica item details (query) | weapon_tag: Weapon tag rules (query) | career: Career table entry (query) | alchemy: Vaarnish alchemy rules card (Crucible/Components/Essences/Potency/brewing/antidotes; no query needed)"""
    action = action.lower().strip()
    if action == "alchemy":
        return _lookup_alchemy()
    if not query:
        return "Error: 'query' parameter required."
    if action == "creature":
        return _lookup_creature_stats(creature_name=query)
    elif action == "exotica":
        return _lookup_exotica(name_fragment=query)
    elif action == "weapon_tag":
        return _lookup_weapon_tag(tag_name=query)
    elif action == "career":
        return _lookup_career(career_name=query)
    else:
        return f"Invalid action '{action}'. Valid actions: creature, exotica, weapon_tag, career, alchemy"


# Bestiary + encounter/reaction helpers (7 funcs) moved to bestiary_encounter.py
# (decomposition slice 4); imported-and-aliased back here BEFORE the content_forge
# registration (which passes _roll_encounter_table/_roll_reaction/
# _roll_reaction_for_character by reference). register_bestiary_encounter() (below)
# binds the live module + injects rulebook_system.
import bestiary_encounter
from bestiary_encounter import (
    _get_bestiary_entry,
    _lookup_creature_stats,
    _roll_encounter_table,
    _roll_reaction,
    _faction_rep,
    _reaction_modifiers,
    _roll_reaction_for_character,
)













# ============================================
# END OF ENCOUNTER AND BESTIARY TOOLS
# ============================================

# ============================================
# TRAVEL CONSISTENCY TOOLS
# (calculate_journey removed 2026-05-28 — replaced by geography(action='journey'))
# ============================================

def _update_vehicle_location_impl(
    vehicle_name: str,
    new_location: str,
    operational: bool = True,
    notes: str = ""
) -> str:
    """Reach for this WHEN the party moves, abandons, or changes the operational status of a vehicle so VEHICLE_LOCATIONS.json stays current for future travel checks.

    Update vehicle location. Call after party moves a vehicle to track availability."""
    try:
        content = read_file("VEHICLE_LOCATIONS.json")
        data = json.loads(content)
        
        vehicle_name_clean = vehicle_name.lower().replace(" ", "_")
        
        if vehicle_name_clean not in data["vehicles"]:
            return f"Ã¢ÂÅ’ Unknown vehicle: {vehicle_name}"
        
        old_location = data["vehicles"][vehicle_name_clean]["current_location"]
        data["vehicles"][vehicle_name_clean]["current_location"] = new_location.lower().replace(" ", "_")
        data["vehicles"][vehicle_name_clean]["operational"] = operational
        
        if notes:
            data["vehicles"][vehicle_name_clean]["notes"] = notes
        
        # Update metadata - read current day from status file
        try:
            status_content = read_file("CURRENT_STATUS.md")
            day_match = re.search(r'DAY\s+(\d+)', status_content, re.IGNORECASE)
            meta_day = f"Day {day_match.group(1)}" if day_match else "unknown"
        except:
            meta_day = "unknown"
        data["_meta"]["last_updated"] = meta_day

        write_file("VEHICLE_LOCATIONS.json", json.dumps(data, indent=2))
        
        return f"Ã¢Å“â€œ Moved {vehicle_name} from {old_location} Ã¢â€ â€™ {new_location}"
        
    except Exception as e:
        return f"Ã¢ÂÅ’ Error: {str(e)}"

# Photosynthesis tracking: CURRENT_STATUS.md is the single source of truth.
# update_photosynthesis() writes to CURRENT_STATUS.md only.
# Formation checks read from CURRENT_STATUS.md, not VEHICLE_LOCATIONS.json.

# ============================================
# END TRAVEL CONSISTENCY TOOLS
# ============================================

# ============================================
# EXOTICA TABLE TOOL
# ============================================

# Full d100 Exotica table from TOPAZ CHARIOT rules pp.204-207
# Content generators (20 funcs + 10 private tables) moved to generators.py
# (decomposition slice 1); imported-and-aliased below, before content_forge
# registration. Shared tables (VAARNISH_POISONS/ELIXIRS, MELEE/RANGED_WEAPONS)
# + _stamp_slots_uses stay here and are injected via register_generators().



import generators
from generators import (
    _roll_cacogen_mutation,
    _roll_exotica,
    _lookup_exotica,
    _load_exotica_generator,
    _generate_faction,
    _generate_gift,
    _generate_poison,
    _generate_codex,
    _generate_drug,
    _elixir_row_for,
    _generate_elixir,
    _generate_exotica,
    _generate_weapon_obj,
    _render_weapon_markdown,
    _generate_weapon,
    _lookup_weapon_tag,
    _generate_armour_obj,
    _render_armour_markdown,
    _generate_npc,
    _lookup_career,
    _generate_crucible,
    _generate_story_seed,
    EXOTICA_TABLE,
    BASIC_TAGS,
    ADVANCED_TAGS,
    EXOTIC_TAGS,
    VAARNISH_DRUGS,
    CODEX_APPEARANCES,
    HYPERGEOMETRIC_EQUATIONS,
    CRUCIBLE_QUALITIES,
    CRUCIBLE_SHAPES,
)

def _roll_ability_check(kind="check", ability=None, character=None, dc=15,
                        bonus=None, advantage=False, disadvantage=False, reason=None):
    """Vaarn ability check / save: d20 + ability vs DC (default 15). The modifier
    is read from the named character's sheet (ability= + character=) or passed as an
    explicit bonus=. advantage/disadvantage roll 2d20 and keep the better/worse.
    Natural 20 auto-passes, natural 1 auto-fails. This is the canonical ad-hoc roll
    path so a player's own save/check is an ENGINE roll they can see — not a number
    the DM made up in their head (Fizzek playtest 2b)."""
    kind = (kind or "check").lower()
    label = "Save" if kind == "save" else "Check"
    try:
        dc = int(dc)
    except (TypeError, ValueError):
        dc = 15
    mod, mod_src = 0, ""
    if bonus is not None:
        mod = int(bonus)
        mod_src = f"{mod:+d}"
    elif ability and character:
        data, err = _load_characters()
        if err or not data:
            return f"Could not load characters: {err or 'no data'}"
        _key, char = _find_character(data, character)
        if not char:
            return f"Character '{character}' not found."
        ab = char.get("abilities", {}).get(str(ability).upper(), {})
        mod = ab.get("current", 0) if isinstance(ab, dict) else int(ab)
        mod_src = f"{char.get('name', character)}'s {str(ability).upper()} {mod:+d}"
    elif ability:
        return (f"To roll {str(ability).upper()} off a sheet, pass character=<name>; "
                f"or pass bonus=<n> for a flat modifier.")

    if advantage and not disadvantage:
        r = dice.roll_with_advantage(20, mod)
        mode = " (advantage)"
    elif disadvantage and not advantage:
        r = dice.roll_with_disadvantage(20, mod)
        mode = " (disadvantage)"
    else:
        r = dice.roll(20, 1, mod)
        mode = ""
    nat = r["rolls"][0]
    total = r["total"]
    if nat == 20:
        passed, why = True, " — NATURAL 20 (auto-pass)"
    elif nat == 1:
        passed, why = False, " — NATURAL 1 (auto-fail)"
    else:
        passed, why = total >= dc, ""
    verdict = "PASS" if passed else "FAIL"
    other = f", other d20 {r.get('other_roll')}" if r.get("other_roll") is not None else ""
    rsn = f" — {reason}" if reason else ""
    src = f" + {mod_src}" if mod_src else ""
    return (f"**{label} vs DC {dc}{mode}**{rsn}\n"
            f"d20={nat}{src} → **{total}** vs {dc}{other} → **{verdict}**{why}")


def _roll_damage(notation=None, reason=None):
    """Roll an arbitrary dice expression (e.g. '3d8', '2d6+1') and return the
    structured total. The canonical path for ad-hoc damage / HP-cost / spirit rolls
    so they are engine-attributed + player-visible, not shelled out to a script."""
    if not notation or not str(notation).strip():
        return "Pass notation=<dice expr>, e.g. '3d8' or '2d6+1'."
    try:
        r = dice.roll_notation(str(notation).strip())
    except Exception as e:
        return f"Could not parse '{notation}': {e}"
    if isinstance(r, dict) and r.get("error"):
        return f"Could not roll '{notation}': {r['error']}"
    rsn = f" — {reason}" if reason else ""
    breakdown = r.get("breakdown") if isinstance(r, dict) else None
    total = r.get("total") if isinstance(r, dict) else r
    return f"**Roll {notation}**{rsn}: {breakdown or total} → **{total}**"


# Register content_forge now that _roll_encounter_table, _roll_reaction, _roll_exotica are defined
content_forge = register_content_forge_tools(
    mcp, CAMPAIGN_DIR,
    roll_encounter_fn=_roll_encounter_table,
    roll_reaction_fn=_roll_reaction,
    roll_exotica_fn=_roll_exotica,
    roll_mutation_fn=_roll_cacogen_mutation,
    reaction_for_character_fn=_roll_reaction_for_character,
    roll_check_fn=_roll_ability_check,
    roll_damage_fn=_roll_damage,
)



# ============================================
# END EXOTICA TABLE TOOL
# ============================================

# ============================================
# EXOTICA GENERATOR (4d100, pp.132-133)
# ============================================

# Cached generator data


@mcp.tool(
    annotations={"readOnlyHint": True, "idempotentHint": False},
    tags=_get_tool_tags("generate")
)
def generate(
    action: str = Field(description="'exotica', 'weapon', 'armour', 'npc', 'poison', 'elixir', 'gift', 'drug', 'crucible', 'codex', 'faction', or 'story_seed'"),
    reroll_column: Optional[str] = Field(default=None, description="[exotica] Reroll a column: material, form, theme, or action. [story_seed] Reroll a column: who, what, with, or why"),
    tier: str = Field(default="exotic", description="[weapon] 'basic', 'advanced', or 'exotic'"),
    weapon_type: Optional[str] = Field(default=None, description="[weapon] 'melee' or 'ranged', or empty for random"),
    ancestry: Optional[str] = Field(default=None, description="[npc] Ancestry, or empty to roll: True-kin, Cacogen, Synth, Newbeast, Neobloom, Mycomorph, Faa Nomad, Cacklemaw Exile, Planeyfolk, Lithling"),
    name_style: Optional[str] = Field(default=None, description="[npc] A (formal), B (feminine), C (descriptive), D (surname), or empty for random"),
    include_secret: bool = Field(default=True, description="[npc] Include a secret for referee"),
    roll: Optional[int] = Field(default=None, description="[poison] Force a specific d20 row 1-20 instead of rolling. [elixir] Force a d100 1-100 instead of rolling. [gift+sample] Force the sample-table d20 row. [codex] Force the equation d100."),
    sample: bool = Field(default=False, description="[gift] True = roll the CH p.47 d20 sample table (SOURCE OF POWER + GIFT pair) instead of the random Quality+Form name"),
    rolls: Optional[str] = Field(default=None, description="[drug] Force five comma-separated d20s: hue,form,ingested_by,effect,effect | [crucible] Force two comma-separated d20s: quality,shape"),
) -> str:
    """Reach for this WHEN you need to procedurally mint an exotica seed, weapon, armour, NPC, poison, elixir, gift, drug, crucible, codex, faction, or story seed — returns text only, persists nothing.

    exotica: 4d100 seed | weapon: random weapon with tags | armour: random body armour | npc: fully-rolled named NPC; pushes npc action=set to crystallize | poison: d20 Poison Generator row (apply via toxin poison_apply/poison_coat) | elixir: d100 Elixir row (consume via character action=drink_elixir) | gift: d20 Quality+Form -> gift NAME; sample=True rolls the sample table instead; persist via gift action=add | drug: d20 per column, effect x2; prose-only | crucible: d20 quality+shape flavor | codex: d100 equation + d20 physical form; claim via codex action=add | faction: d20 minor-faction -> reputation/type/goal/leader/assets/rival; commit via faction action=add | story_seed: 4d100 WHO/WHAT/WITH/WHY hook (CH pp.87-89); crystallize via thread/antagonist/character."""
    action = action.lower()
    if action == "exotica":
        return _generate_exotica(reroll_column=reroll_column)
    elif action == "weapon":
        return _generate_weapon(tier=tier, weapon_type=weapon_type)
    elif action == "armour":
        obj = _generate_armour_obj()
        return _render_armour_markdown(obj)
    elif action == "npc":
        return _generate_npc(ancestry=ancestry, name_style=name_style, include_secret=include_secret)
    elif action == "poison":
        return _generate_poison(roll=roll)
    elif action == "elixir":
        return _generate_elixir(forced_roll=roll)
    elif action == "gift":
        return _generate_gift(sample=(sample is True), roll=roll)
    elif action == "drug":
        return _generate_drug(rolls=(rolls if isinstance(rolls, str) else None))
    elif action == "crucible":
        return _generate_crucible(rolls=(rolls if isinstance(rolls, str) else None))
    elif action == "codex":
        return _generate_codex(roll=roll)
    elif action == "faction":
        return _generate_faction()
    elif action == "story_seed":
        return _generate_story_seed(reroll_column=reroll_column)
    else:
        return f"Invalid action '{action}'. Use: exotica, weapon, armour, npc, poison, elixir, gift, drug, crucible, codex, faction, story_seed"

















# ============================================
# END EXOTICA GENERATOR
# ============================================

# ============================================
# EXOTIC WEAPON GENERATOR (pp.40-43)
# ============================================

# Melee Weapon Base Types (d20)
MELEE_WEAPONS = {
    1: {"name": "Dagger", "damage": "d6", "slots": 1, "tags": []},
    2: {"name": "Flail", "damage": "d6", "slots": 1, "tags": []},
    3: {"name": "Whip", "damage": "d6", "slots": 1, "tags": []},
    4: {"name": "Axe", "damage": "d6", "slots": 1, "tags": []},
    5: {"name": "Club", "damage": "d6", "slots": 1, "tags": []},
    6: {"name": "Fleshripper", "damage": "d6", "slots": 1, "tags": []},
    7: {"name": "Shock Baton", "damage": "d6", "slots": 1, "tags": ["Electrical"]},
    8: {"name": "Razordisk", "damage": "d6", "slots": 1, "tags": []},
    9: {"name": "War Fan", "damage": "d6", "slots": 1, "tags": []},
    10: {"name": "Scythe", "damage": "d8", "slots": 2, "tags": []},
    11: {"name": "Sword", "damage": "d8", "slots": 2, "tags": []},
    12: {"name": "Mace", "damage": "d8", "slots": 2, "tags": []},
    13: {"name": "Rapier", "damage": "d8", "slots": 2, "tags": []},
    14: {"name": "Spear", "damage": "d8", "slots": 2, "tags": []},
    15: {"name": "Quarterstaff", "damage": "d8", "slots": 2, "tags": []},
    16: {"name": "War Hammer", "damage": "d8", "slots": 2, "tags": []},
    17: {"name": "Great Mace", "damage": "d10", "slots": 3, "tags": []},
    18: {"name": "Great Axe", "damage": "d10", "slots": 3, "tags": []},
    19: {"name": "Halberd", "damage": "d10", "slots": 3, "tags": []},
    20: {"name": "Great Sword", "damage": "d10", "slots": 3, "tags": []},
}

# Ranged Weapon Base Types (d20)
RANGED_WEAPONS = {
    1: {"name": "Sling", "damage": "d4", "slots": 1, "ammo": "Ud20", "tags": []},
    2: {"name": "Revolver", "damage": "d6", "slots": 1, "ammo": "Ud10", "tags": []},
    3: {"name": "Pistol", "damage": "d6", "slots": 1, "ammo": "Ud10", "tags": []},
    4: {"name": "Musket", "damage": "d8", "slots": 2, "ammo": "Ud8", "tags": []},
    5: {"name": "Shotgun", "damage": "d8", "slots": 2, "ammo": "Ud8", "tags": []},
    6: {"name": "Crossbow", "damage": "d8", "slots": 2, "ammo": "Ud8", "tags": []},
    7: {"name": "Longbow", "damage": "d8", "slots": 2, "ammo": "Ud10", "tags": []},
    8: {"name": "Rifle", "damage": "d8", "slots": 2, "ammo": "Ud10", "tags": []},
    9: {"name": "Laser Pistol", "damage": "d6", "slots": 1, "ammo": "Ud12", "tags": ["Beam"]},
    10: {"name": "Hand Cannon", "damage": "d8", "slots": 2, "ammo": "Ud8", "tags": []},
    11: {"name": "Shock Bow", "damage": "d8", "slots": 2, "ammo": "Ud8", "tags": ["Electrical"]},
    12: {"name": "Auto-Rifle", "damage": "d8", "slots": 2, "ammo": "Ud8", "tags": []},
    13: {"name": "Scattergun", "damage": "d8", "slots": 2, "ammo": "Ud10", "tags": []},
    14: {"name": "Laser Rifle", "damage": "d8", "slots": 2, "ammo": "Ud12", "tags": ["Beam"]},
    15: {"name": "Concussion Rifle", "damage": "d10", "slots": 3, "ammo": "Ud8", "tags": ["Concussive"]},
    16: {"name": "Spore Thrower", "damage": "d10", "slots": 3, "ammo": "Ud8", "tags": ["Blast", "Fungal"]},
    17: {"name": "Grenade Launcher", "damage": "d10", "slots": 3, "ammo": "Ud6", "tags": ["Blast"]},
    18: {"name": "Laser Cannon", "damage": "d10", "slots": 3, "ammo": "Ud6", "tags": ["Beam"]},
    19: {"name": "Port-A-Cannon", "damage": "d12", "slots": 5, "ammo": "Ud4", "tags": ["Blast"]},
    20: {"name": "Railgun", "damage": "d12", "slots": 6, "ammo": "Ud6", "tags": []},
}

# Basic Weapon Tags (d20) — verified vs Crimson Hound 2026-06-07 audit (page-fed).
# Prior table had a hallucinated "Accurate" at roll 1 (shifting every roll) and was
# missing "Shoddy" (roll 19). Spelling "Lacquered" kept over the book's "Laquered"
# typo (live campaign gear already uses the corrected spelling).

# Advanced Weapon Tags (d20)

# Exotic Weapon Tags (d20)









# ============================================
# END EXOTIC WEAPON GENERATOR

# ============================================
# ARMOUR GENERATOR
# ============================================




# ============================================
# END ARMOUR GENERATOR

# ============================================
# NPC GENERATOR (pp.126-145)
# ============================================

from npc_tables import (
    ANCESTRY_TABLE, MANNER_TABLE, VOICE_TABLE, DRIVE_TABLE,
    SECRET_TABLE, BOND_TABLE, FAITH_TABLE, FACTION_REPUTATION_TABLE,
    NAMES_A, NAMES_B, NAMES_C, NAMES_D, CAREERS_TABLE
)





# ============================================
# END NPC GENERATOR


# ============================================
# SEMANTIC SEARCH - CAMPAIGN HISTORY
# ============================================

async def _search_campaign_history_impl(
    query: str = Field(description="Specific query with names/events/locations"),
    n_results: int = Field(default=5, description="Results to return (1-10). Default 5 for 1M context."),
    arc: str = Field(default=None, description="origins|early_rubicon|fount|cistern|delta|current"),
    scene_type: str = Field(default=None, description="intimate|combat|travel|political|exploration|dialogue"),
    character: str = Field(default=None, description="Filter to scenes with this character"),
    day_min: int = Field(default=None, description="Minimum day"),
    day_max: int = Field(default=None, description="Maximum day"),
    max_chars_per_result: int = Field(default=3000, description="Max characters per result (default 3000)")
) -> str:
    """Reach for this WHEN you need a quick "have we ever..." existence check or past-event verification — starts at Tier 2 (~300 chars) for token efficiency; escalate to search(action='tiered', tier=3/4) only when snippets are insufficient.

    Search 80+ sessions of campaign history. Use for 'have we ever...' questions or verifying past events.

    Progressive: starts at Tier 2 (mini, ~300 chars). If results seem insufficient, caller can
    use search(action='tiered', tier=4) for full-size chunks. This default saves ~10x tokens per query."""
    # Start at tier 2 (mini) for token efficiency — full chunks rarely needed for verification
    return await _search_history_tiered_impl(
        query=query,
        tier=2,
        n_results=n_results,
        arc=arc,
        scene_type=scene_type,
        character=character,
        day_min=day_min,
        day_max=day_max
    )


# ============================================
# SEARCH ENHANCEMENT HELPERS (Phase 2)
# ============================================

# Common stopwords to skip in keyword matching
_STOPWORDS = frozenset({
    "the", "and", "for", "are", "but", "not", "you", "all", "can", "had",
    "her", "was", "one", "our", "out", "has", "his", "how", "its", "may",
    "who", "did", "get", "let", "say", "she", "too", "use", "what", "when",
    "where", "which", "with", "would", "about", "after", "been", "before",
    "being", "between", "both", "each", "from", "have", "into", "just",
    "more", "most", "only", "other", "over", "some", "such", "than",
    "that", "them", "then", "there", "these", "they", "this", "very",
    "will", "does", "down",
})


def _apply_keyword_boost(results: list[tuple], query: str) -> list[tuple]:
    """Boost scores for results that contain exact query keywords.

    After vector search returns candidates, reduce distance for exact term matches.
    5% distance reduction per keyword match (multiplicative).

    Args:
        results: List of (doc, metadata, distance) tuples
        query: Original query string

    Returns:
        Re-sorted list with adjusted distances
    """
    # Extract meaningful keywords (>3 chars, not stopwords)
    keywords = [
        w.lower() for w in re.findall(r'\w+', query)
        if len(w) > 3 and w.lower() not in _STOPWORDS
    ]

    if not keywords:
        return results

    boosted = []
    for doc, meta, dist in results:
        doc_lower = doc.lower()
        matches = sum(1 for kw in keywords if kw in doc_lower)
        # 5% reduction per match, multiplicative
        boost_factor = 0.95 ** matches
        boosted.append((doc, meta, dist * boost_factor))

    # Re-sort by adjusted distance (lower = better)
    boosted.sort(key=lambda x: x[2])
    return boosted


# ---- Recency weighting (RAG hardening sprint, Task 3 — owner-approved policy
# change). Raw-history lane ONLY: the distillations lane is curated/current by
# construction and is never re-ranked by age. Tuning is expressed as a
# multiplicative penalty on distance (same style as _apply_keyword_boost) so it
# composes regardless of the collection's distance metric (cosine ~0-2 vs L2
# ~300+) without needing metric-specific absolute offsets.
_RECENCY_DECAY_PER_DAY = 0.0015   # fractional distance penalty per day of age
_RECENCY_MAX_PENALTY = 0.20       # cap: age alone can never worsen distance by more than 20%
_RECENCY_STRONG_BYPASS_FACTOR = 0.5  # skip decay entirely below GOOD_MATCH * this factor


def _apply_recency_weight(results: list[tuple], current_day: Optional[int],
                           good_match_threshold: float = 0.5) -> list[tuple]:
    """Blend semantic score with a mild recency bonus (raw-history lane only).

    Meant to run AFTER _apply_keyword_boost wherever that runs in this lane;
    where the raw-history lane has no keyword-boost step (check_canon's
    progressive/tier-1 search), this is the only re-rank applied.

    Older docs take a small multiplicative distance penalty, linear in age and
    capped at _RECENCY_MAX_PENALTY so recency can nudge rankings but never
    invert a real quality gap. A strong semantic match (distance already at or
    below good_match_threshold * _RECENCY_STRONG_BYPASS_FACTOR) bypasses the
    penalty entirely — a great old match still beats a weak recent one.

    Args:
        results: List of (doc, meta, dist) tuples (lower dist = better match).
        current_day: Current campaign day, or None/0 if unavailable — a no-op
            in that case (never penalize when there's nothing to compare against).
        good_match_threshold: The collection's GOOD_MATCH distance (from
            _chroma_thresholds) — sizes the strong-match bypass for this metric.

    Returns:
        Re-sorted list with adjusted distances. Docs missing `day` metadata are
        left untouched (neutral — no penalty, no bonus).
    """
    if not current_day or not results:
        return results

    bypass_dist = good_match_threshold * _RECENCY_STRONG_BYPASS_FACTOR
    weighted = []
    for doc, meta, dist in results:
        if dist <= bypass_dist:
            weighted.append((doc, meta, dist))
            continue
        try:
            raw_day = meta.get('day') if meta else None
            doc_day = int(raw_day) if raw_day not in (None, '', '?') else None
        except (ValueError, TypeError):
            doc_day = None
        if doc_day is None:
            weighted.append((doc, meta, dist))
            continue
        age = max(0, current_day - doc_day)
        penalty = min(age * _RECENCY_DECAY_PER_DAY, _RECENCY_MAX_PENALTY)
        weighted.append((doc, meta, dist * (1 + penalty)))

    weighted.sort(key=lambda x: x[2])
    return weighted


def _diversify_by_day(results: list[tuple], n_results: int) -> list[tuple]:
    """MMR-style diversification: penalize results from already-selected days.

    Always picks the top result first, then applies 50% distance penalty
    for results sharing a day with any already-selected result.

    Args:
        results: Pre-sorted list of (doc, metadata, distance) tuples
        n_results: How many to select

    Returns:
        Diversified subset of results
    """
    if len(results) <= n_results:
        return results

    selected = []
    selected_days = set()
    remaining = list(results)

    while len(selected) < n_results and remaining:
        # Score remaining with day penalty
        best_idx = 0
        best_score = float('inf')

        for i, (doc, meta, dist) in enumerate(remaining):
            try:
                day = int(meta.get('day', 0))
            except (ValueError, TypeError):
                day = 0

            score = dist * 1.5 if day in selected_days else dist

            if score < best_score:
                best_score = score
                best_idx = i

        picked = remaining.pop(best_idx)
        selected.append(picked)
        try:
            selected_days.add(int(picked[1].get('day', 0)))
        except (ValueError, TypeError):
            pass

    return selected


def _search_single_tier(collection, query_embedding: list, tier: int,
                        where_filter: dict, n_request: int) -> list[tuple]:
    """Query a single tier from ChromaDB, return (doc, meta, dist) tuples."""
    tier_filter = {**where_filter, "tier": str(tier)}
    try:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=min(n_request, 20),
            where=tier_filter,
            include=["documents", "metadatas", "distances"]
        )
        docs = results['documents'][0]
        metas = results['metadatas'][0]
        dists = results['distances'][0]
        return list(zip(docs, metas, dists))
    except Exception:
        return []


# Cap on results returned by progressive tier search (across both sufficient
# and drill_recommended paths). Keeping it as a named constant so callers
# don't have to grep for the literal 5.
_PROGRESSIVE_RESULT_CAP = 5


def _chroma_thresholds(collection):
    """Return (GOOD_MATCH, WEAK_MATCH) for the given collection's distance metric.

    Cosine collections (name contains "v2", or canon_distillations) use 0.5/0.7.
    L2 collections use 300/350.
    """
    name = getattr(collection, "name", "") or ""
    is_cosine = "v2" in name or name == "canon_distillations"
    return (0.5, 0.7) if is_cosine else (300, 350)


def _progressive_tier_search(collection, query_embedding, max_tier=3,
                             n_results_per_tier=3, where=None):
    """Progressive tier search: stop on first tier with results above the GOOD threshold.

    Args:
        collection: ChromaDB collection object
        query_embedding: pre-computed query embedding
        max_tier: maximum tier to search (default 3)
        n_results_per_tier: how many results per tier (default 3)
        where: optional metadata filter dict (e.g., {"characters": {"$in": ["amara"]}})

    Returns:
        tuple: (results, tier_reached, weakness_signal)
            results: list of (doc, meta, dist) tuples
            tier_reached: int — last tier that completed a successful search
                          (0 if every tier raised)
            weakness_signal: str — one of "sufficient", "drill_recommended", "no_match"
    """
    GOOD_MATCH, WEAK_MATCH = _chroma_thresholds(collection)

    accumulated = []
    tier_reached = 0
    for tier in range(1, max_tier + 1):
        try:
            tier_results = _search_single_tier(
                collection, query_embedding, tier, where or {}, n_results_per_tier
            )
        except Exception as e:
            logging.warning(f"Tier {tier} search failed: {e}")
            continue
        # Only mark this tier as "reached" once the search actually completed.
        tier_reached = tier
        good = [(d, m, dist) for d, m, dist in tier_results if dist <= GOOD_MATCH]
        if good:
            # Match original behavior: return ONLY this tier's good results,
            # not accumulated weak fallbacks from prior tiers.
            return (good[:_PROGRESSIVE_RESULT_CAP], tier_reached, "sufficient")
        # Tier yielded results but none were strong — keep them as fallback
        weak = [(d, m, dist) for d, m, dist in tier_results if dist <= WEAK_MATCH]
        accumulated.extend(weak)

    if accumulated:
        return (accumulated[:_PROGRESSIVE_RESULT_CAP], tier_reached, "drill_recommended")
    return ([], tier_reached, "no_match")


async def _search_history_tiered_impl(
    query: str = Field(description="Search query"),
    tier: int = Field(default=1, description="Which tier to search (0=all tiers, 1=micro, 2=mini, 3=medium, 4=full). Start at 1 unless you know you need more."),
    n_results: int = Field(default=None, description="Override default number of results for this tier"),
    arc: str = Field(default=None, description="origins|early_rubicon|fount|cistern|delta|current"),
    scene_type: str = Field(default=None, description="intimate|combat|travel|political|exploration|dialogue"),
    character: str = Field(default=None, description="Filter to scenes with this character"),
    day_min: int = Field(default=None, description="Minimum day"),
    day_max: int = Field(default=None, description="Maximum day")
) -> str:
    """Reach for this WHEN search(action='history') (tier 2) snippets are too thin and you need richer context: escalate to tier 3 (medium, ~800 chars) or tier 4 (full, ~3000 chars), or use tier=0 to sweep all tiers at once (highest recall, highest token cost); tier=1 (micro, ~150 chars) is the cheapest direct existence check.

    Tiered campaign history search with progressive context loading.

    Usage: tier=0 searches all tiers (best recall, highest cost). tier=1-4 searches specific tier (progressive escalation — start at 1).
    """
    # Validate tier
    if tier not in [0, 1, 2, 3, 4]:
        return f"ERROR: Invalid tier {tier}. Must be 0, 1, 2, 3, or 4."

    # Get tier config
    tier_config = {
        0: {'n_results': 5},
        1: {'n_results': 3},
        2: {'n_results': 4},
        3: {'n_results': 3},
        4: {'n_results': 2}
    }

    if n_results is None:
        n_results = tier_config[tier]['n_results']
    else:
        n_results = max(1, min(10, n_results))

    # Query enhancement removed (Task 2 item 3): _enhance_query_with_context was
    # dead (empty _CHARACTER_TRAITS, expansion never fired). Embed the raw query.
    enhanced_query = query

    # Get embedding (uses LRU cache, adds search_query: prefix)
    try:
        query_embedding = get_embedding_cached(enhanced_query)
    except Exception as e:
        return f"ERROR: Could not get embedding from Ollama: {e}"

    # Build base metadata filter (without tier — added per-query)
    where_filter = {}
    if arc:
        where_filter["arc"] = arc.lower()
    if scene_type:
        where_filter["scene_type"] = scene_type.lower()

    try:
        collection = get_chroma_collection("campaign_history_tiered")

        needs_post_filter = day_min or day_max or character
        request_n = n_results * 3 if needs_post_filter else n_results

        # Phase 2B: Multi-tier search (tier=0)
        if tier == 0:
            all_results = []
            for t in [1, 2, 3, 4]:
                tier_results = _search_single_tier(
                    collection, query_embedding, t, where_filter, request_n
                )
                all_results.extend(tier_results)
            # Sort by distance, prefer higher tiers for ties
            all_results.sort(key=lambda x: (x[2], -int(x[1].get('tier', 0))))
            raw_results = all_results
        else:
            # Single tier search
            tier_filter = {**where_filter, "tier": str(tier)}
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=min(request_n, 20),
                where=tier_filter,
                include=["documents", "metadatas", "distances"]
            )
            docs = results['documents'][0]
            metadatas = results['metadatas'][0]
            distances = results['distances'][0]
            raw_results = list(zip(docs, metadatas, distances))

    except Exception as e:
        return f"ERROR: ChromaDB query failed: {e}"

    # Post-filter by day range or character
    filtered = []
    for doc, meta, dist in raw_results:
        try:
            doc_day = int(meta.get('day', 0))
        except (ValueError, TypeError):
            doc_day = 0

        if day_min and doc_day < day_min:
            continue
        if day_max and doc_day > day_max:
            continue

        if character:
            chars = meta.get('characters', '').lower()
            if character.lower() not in chars:
                continue

        filtered.append((doc, meta, dist))

    # Phase 2B.5 (Task 4, RAG hardening sprint): BM25 lexical lane, fused into
    # the vector results by Reciprocal Rank Fusion — BEFORE keyword-boost/
    # recency (spec order: RRF fusion -> keyword boost -> recency). The
    # lexical candidate pool is filtered to the SAME tier/arc/scene_type/
    # day_min/day_max/character constraints the vector query above used, so
    # both lanes search the same subset. Best-effort: any failure here (index
    # build, BM25 query) falls back to vector-only with a log line — it must
    # never block this tool.
    try:
        def _lexical_filter(meta):
            if tier != 0 and str(meta.get('tier')) != str(tier):
                return False
            if arc and (meta.get('arc') or '').lower() != arc.lower():
                return False
            if scene_type and (meta.get('scene_type') or '').lower() != scene_type.lower():
                return False
            try:
                m_day = int(meta.get('day', 0))
            except (ValueError, TypeError):
                m_day = 0
            if day_min and m_day < day_min:
                return False
            if day_max and m_day > day_max:
                return False
            if character:
                chars = (meta.get('characters') or '').lower()
                if character.lower() not in chars:
                    return False
            return True

        _lex_index = lexical_lane.get_or_build_index(collection)
        _lex_hits = lexical_lane.search(_lex_index, query, top_k=20, filter_fn=_lexical_filter)
        if _lex_hits:
            _weak_match = _chroma_thresholds(collection)[1]
            filtered = lexical_lane.fuse_lexical_into_vector(
                filtered, _lex_hits, weak_match_dist=_weak_match, max_results=50,
            )
    except Exception as _lex_exc:
        logging.warning(f"BM25 lexical lane failed (search_history_tiered): {_lex_exc}")

    # Phase 2C: Keyword boost
    filtered = _apply_keyword_boost(filtered, query)

    # Phase 2C.5 (Task 3, RAG hardening sprint): recency re-rank, applied AFTER
    # the keyword boost — raw-history lane only, distillations untouched.
    _good_match, _ = _chroma_thresholds(collection)
    filtered = _apply_recency_weight(filtered, get_current_day_safe(), good_match_threshold=_good_match)

    # Phase 2D: Day diversification
    filtered = _diversify_by_day(filtered, n_results)

    if not filtered:
        tier_label = "all tiers" if tier == 0 else f"tier {tier}"
        suggestions = []
        if tier > 0 and tier < 4:
            suggestions.append(f"- Try tier {tier + 1} for more context")
        if tier != 0:
            suggestions.append("- Try tier=0 for multi-tier search")
        suggestions.append("- Broaden your query")
        suggestions.append("- Remove filters")
        return f"No results found for {tier_label}.\n\nSuggestions:\n" + "\n".join(suggestions)

    # Format output
    output = []
    tier_label = "MULTI-TIER" if tier == 0 else f"TIER {tier}"
    output.append(f"=== {tier_label} SEARCH RESULTS ===")
    output.append(f"Query: {query}")
    if enhanced_query != query:
        output.append(f"Enhanced: {enhanced_query}")
    output.append(f"Results: {len(filtered)}/{n_results} requested")
    total_chars = sum(len(d) for d, _, _ in filtered)
    output.append(f"Token cost estimate: ~{total_chars // 3} tokens")
    output.append("")

    if tier > 0 and tier < 4:
        output.append(f"TIP: If insufficient, try tier={tier + 1} or tier=0 (all tiers)")
        output.append("")

    for i, (doc, meta, dist) in enumerate(filtered, 1):
        # Convert distance to relevance percentage
        # For cosine: distance 0 = identical, 2 = opposite. Map to 0-100%.
        # For L2: different scale. Detect by checking if collection is v2.
        relevance = max(0, min(100, int((1 - dist) * 100)))

        result_tier = meta.get('tier', '?')
        output.append(f"--- Result {i}/{len(filtered)} (T{result_tier}) ---")
        output.append(f"Day: {meta.get('day', 'unknown')}")
        output.append(f"Arc: {meta.get('arc', 'unknown')}")
        if meta.get('characters'):
            output.append(f"Characters: {meta.get('characters')}")
        if meta.get('location'):
            output.append(f"Location: {meta.get('location')}")
        output.append(f"Scene type: {meta.get('scene_type', 'unknown')}")
        output.append(f"Similarity: {relevance}%")

        if int(result_tier) < 4 and meta.get('parent_id'):
            output.append(f"Parent: {meta.get('parent_id')}")

        output.append("")
        output.append(doc)
        output.append("")

    return "\n".join(output)


def _chroma_health_check_impl() -> str:
    """Reach for this WHEN search feels stale or broken — verify the ChromaDB index and Ollama embeddings backend are live before troubleshooting a bad search result.

Report ChromaDB and Ollama status. Use to verify search backend is healthy."""
    output = ["**ChromaDB & Ollama Health Check**", ""]

    # Check Ollama status first
    ollama_ok = check_ollama_health(force=True)
    if ollama_ok:
        output.append("**Ollama:** AVAILABLE (embeddings enabled)")
    else:
        output.append("**Ollama:** UNAVAILABLE - Start Ollama to enable semantic search")
        output.append("  Run: `ollama serve` then retry")
    output.append("")

    try:
        collection = get_chroma_collection("campaign_history_tiered")
        count = collection.count()

        if count == 0:
            output.append("**ChromaDB:** EMPTY - No documents indexed")
            output.append("  Run `reindex_recent` to populate")
            return "\n".join(output)

        # Get all metadata to analyze
        all_docs = collection.get(include=['metadatas', 'embeddings'])

        # Check embedding dimension from first doc
        embeddings = all_docs.get('embeddings')
        if embeddings is not None and len(embeddings) > 0:
            dim = len(embeddings[0])
        else:
            dim = "unknown"

        # Analyze day coverage and tier distribution
        days = set()
        sources = {}
        tier_counts = {1: 0, 2: 0, 3: 0, 4: 0}
        latest_indexed = None
        latest_day = 0

        for meta in all_docs['metadatas']:
            # Track days
            day_str = meta.get('day', '0')
            try:
                day = int(day_str)
                days.add(day)
                if day > latest_day:
                    latest_day = day
            except:
                pass

            # Track sources
            source = meta.get('source', 'unknown')
            sources[source] = sources.get(source, 0) + 1

            # Track tiers
            try:
                tier = int(meta.get('tier', 0))
                if tier in tier_counts:
                    tier_counts[tier] += 1
            except:
                pass

            # Track latest indexed timestamp. The freshest doc may have been written by
            # either writer: a manual tiered_reindex run stamps 'indexed_at' (full ISO
            # datetime); save_state's per-session auto-index stamps 'timestamp' (date-only,
            # 'YYYY-MM-DD'); reindex_recent stamps neither. Checking only 'indexed_at'
            # missed every save_state write and reported the last full rebuild as if it
            # were current. Compare both by date-prefix (first 10 chars) so the differing
            # precision doesn't skew the max, then prefer the more precise stamp on a tie.
            for _field in ('indexed_at', 'timestamp'):
                stamp = meta.get(_field, '')
                if not stamp:
                    continue
                if latest_indexed is None or stamp[:10] > latest_indexed[:10]:
                    latest_indexed = stamp
                elif stamp[:10] == latest_indexed[:10] and len(stamp) > len(latest_indexed):
                    latest_indexed = stamp

        # Find gaps in recent days (last 30 days from max)
        if days:
            max_day = max(days)
            min_recent = max(0, max_day - 30)
            recent_range = set(range(min_recent, max_day + 1))
            recent_gaps = sorted(recent_range - days)
        else:
            recent_gaps = []

        # Check which collection is active (v2 cosine or original L2)
        try:
            v2_col = get_chroma_client().get_collection("campaign_history_tiered_v2")
            v2_count = v2_col.count()
            active_collection = "campaign_history_tiered_v2 (cosine)"
            v2_exists = True
        except Exception:
            active_collection = "campaign_history_tiered (L2 - legacy)"
            v2_exists = False

        # Build report
        output.append(f"**ChromaDB Collection:** {active_collection}")
        if v2_exists:
            output.append(f"**V2 Documents:** {v2_count}")
        output.append(f"**Documents:** {count}")
        output.append(f"**Embedding Dimension:** {dim}")
        if days:
            output.append(f"**Day Range:** {min(days)} - {max(days)}")
        output.append("")

        output.append("**Tier Distribution:**")
        for t in [1, 2, 3, 4]:
            label = {1: "micro ~150ch", 2: "mini ~300ch", 3: "medium ~800ch", 4: "full ~3000ch"}[t]
            output.append(f"  - T{t} ({label}): {tier_counts[t]} docs")
        output.append("")

        output.append("**Source Breakdown:**")
        for src, cnt in sorted(sources.items()):
            output.append(f"  - {src}: {cnt} docs")
        output.append("")

        if recent_gaps:
            output.append(f"**Recent Gaps (last 30 days):** {recent_gaps}")
        else:
            output.append("**Recent Gaps:** None (full coverage)")
        output.append("")

        if latest_indexed:
            output.append(f"**Last Indexed:** {latest_indexed}")
        elif latest_day:
            # No writer stamped indexed_at/timestamp on any doc — fall back to the
            # highest day metadata on record so freshness is never silently blank.
            output.append(f"**Last Indexed:** unknown (no indexed_at/timestamp metadata) — latest day on record: Day {latest_day}")

        output.append(f"**Latest Day:** {latest_day}")

        # --- Distillation drift check ---
        # Guards the failure mode where the cache marks entries as ingested but
        # the canon_distillations collection has been rebuilt empty. The normal
        # ingest path only posts UNposted entries, so it can never self-heal —
        # the fix is ingest_distillations(force=True). This check makes the drift
        # visible instead of silent.
        try:
            dcache = _get_distillation_cache()
            dentries = [e for e in dcache.all_entries() if e.get("learning")]
            marked_ingested = sum(1 for e in dentries if e.get("ingested_at_session"))
            dist_count = get_canon_distillations_collection().count()
            output.append("")
            output.append(
                f"**Distillations:** cache={len(dentries)} "
                f"(marked ingested={marked_ingested}), collection={dist_count}"
            )
            if marked_ingested > 0 and dist_count == 0:
                output.append("  ⚠️ DRIFT: cache marks entries ingested but the collection is EMPTY.")
                output.append("     Fix: ingest_distillations(session_id='recovery', force=True)")
            elif dist_count < marked_ingested:
                output.append(
                    f"  ⚠️ DRIFT: collection ({dist_count}) < cache-ingested "
                    f"({marked_ingested}). Consider ingest_distillations(force=True)."
                )
            else:
                output.append("  Distillation shelf OK (collection matches cache).")
        except Exception as e:
            output.append(f"**Distillations:** check skipped ({e})")

        return "\n".join(output)

    except Exception as e:
        output.append(f"**ChromaDB:** ERROR - {str(e)}")
        return "\n".join(output)

@mcp.tool(tags=_get_tool_tags("search"))
async def search(
    action: str = Field(default="history", description="history|tiered|health"),
    query: str = Field(default="", description="history/tiered: search query"),
    n_results: int = Field(default=None, description="history/tiered: number of results"),
    tier: int = Field(default=1, description="tiered: 0=all,1=micro,2=mini,3=medium,4=full"),
    arc: str = Field(default=None, description="history/tiered: origins|early_rubicon|fount|cistern|delta|current"),
    scene_type: str = Field(default=None, description="history/tiered: intimate|combat|travel|political|exploration|dialogue"),
    character: str = Field(default=None, description="history/tiered: filter to scenes with this character"),
    day_min: int = Field(default=None, description="history/tiered: minimum day"),
    day_max: int = Field(default=None, description="history/tiered: maximum day"),
    max_chars_per_result: int = Field(default=3000, description="history: max characters per result"),
) -> str:
    """Reach for this WHEN you need to recall canon from past sessions, escalate a thin
    result to deeper tiers, or confirm the search index is healthy.

    history: quick "have we ever..." semantic search (tier 2) -- query, n_results?, arc?, scene_type?, character?, day_min?, day_max?
    tiered:  escalate -- tier 3/4 for richer chunks, 0 = sweep all tiers (query, tier?, n_results?, filters?)
    health:  verify the ChromaDB index + Ollama embeddings backend are live
    """
    a = (action or "").lower().strip()
    if a == "history":
        if not query:
            return "Error: action='history' needs query."
        return await _search_campaign_history_impl(
            query, n_results if n_results is not None else 5, arc, scene_type,
            character, day_min, day_max, max_chars_per_result)
    if a == "tiered":
        if not query:
            return "Error: action='tiered' needs query."
        return await _search_history_tiered_impl(
            query, tier, n_results, arc, scene_type, character, day_min, day_max)
    if a == "health":
        return _chroma_health_check_impl()
    return f"Invalid action '{action}'. Valid actions: history, tiered, health."


@mcp.tool(tags=_get_tool_tags("reindex_recent"))
def reindex_recent() -> str:
    """Reach for this WHEN the session-end INDEX step (Step 7) arrives — run it last, after distill_session and ingest_distillations: the current-arc continuity file has new content that search(action='tiered') must be able to find.

Reindex only MASTER_CONTINUITY_CURRENT.md into ChromaDB (tiered).

    Generates all 4 tiers (150/300/800/3000 char chunks) for search(action='tiered').
    Much faster than full reindex. Requires Ollama running locally (ollama serve).
    """
    output = ["**Reindexing Current Arc**", ""]

    if not check_ollama_health():
        return "ERROR: Ollama not available. Run `ollama serve` first."

    continuity_path = CAMPAIGN_DIR / "MASTER_CONTINUITY_CURRENT.md"
    if not continuity_path.exists():
        return "ERROR: MASTER_CONTINUITY_CURRENT.md not found"

    try:
        content = continuity_path.read_text(encoding='utf-8')

        # Load character data for detection across chunks
        chars_dir = CAMPAIGN_DIR / "characters"
        meta_path = chars_dir / "_meta.json"
        char_data = None
        if chars_dir.exists() and meta_path.exists():
            char_data = {'characters': {}}
            for p in sorted(chars_dir.glob("*.json")):
                if p.name == "_meta.json":
                    continue
                with open(p, 'r', encoding='utf-8') as f:
                    char_data['characters'][p.stem] = json.load(f)
        else:
            # Split sheets are the sole source; monolithic fallback retired.
            char_data = {'characters': {}}

        # Index into campaign_history_tiered
        tiered_collection = get_chroma_collection("campaign_history_tiered")

        # Remove old reindex_recent docs
        try:
            existing = tiered_collection.get(where={"source": "reindex_recent"})
            if existing and existing['ids']:
                tiered_collection.delete(ids=existing['ids'])
                output.append(f"Removed {len(existing['ids'])} old tiered documents")
        except Exception:
            pass  # Collection may not have these docs yet

        # Generate tiered chunks from full content
        tiered_metadata = {
            "day": 0,
            "arc": "current",
            "characters": "",
            "scene_type": "exploration",
            "source": "reindex_recent"
        }

        tiered_chunks = chunk_text_tiered(
            text=content,
            metadata=tiered_metadata,
            session_id="reindex_current"
        )

        # Enrich each chunk with per-chunk metadata detection
        for chunk in tiered_chunks:
            chunk_text_content = chunk["text"]
            day_match = re.search(r'(?:Day|DAY)\s+(\d+)', chunk_text_content)
            if day_match:
                chunk["metadata"]["day"] = int(day_match.group(1))

            # Detect characters
            chunk_lower = chunk_text_content.lower()
            chars_found = []
            if char_data:
                for key, info in char_data.get("characters", {}).items():
                    name = info.get("name", key.capitalize())
                    if name.lower() in chunk_lower:
                        chars_found.append(name)
            if chars_found:
                chunk["metadata"]["characters"] = ",".join(chars_found)

            chunk["metadata"]["scene_type"] = _infer_scene_type(chunk_text_content)
            chunk["metadata"]["source"] = "reindex_recent"
            chunk["metadata"]["source_file"] = "MASTER_CONTINUITY_CURRENT.md"

        # Forward-fill day across T4 chunks (fixes multi-paragraph session splits
        # where only the first chunk contains the "## SESSION SAVED - Day X" header)
        t4_sorted = sorted(
            [c for c in tiered_chunks if c["metadata"].get("tier") == 4],
            key=lambda c: c["id"]
        )
        last_day = 0
        for t4 in t4_sorted:
            day_val = int(t4["metadata"].get("day", 0))
            if day_val > 0:
                last_day = day_val
            elif last_day > 0:
                t4["metadata"]["day"] = last_day

        # Propagate day from T4 parents to T1-3 children
        t4_day_map = {c["id"]: int(c["metadata"].get("day", 0)) for c in t4_sorted}
        for chunk in tiered_chunks:
            parent_id = chunk["metadata"].get("parent_id")
            if parent_id and parent_id in t4_day_map and t4_day_map[parent_id] > 0:
                chunk["metadata"]["day"] = t4_day_map[parent_id]

        # Cross-source dedup: this reindex is about to (re-)cover these exact days from
        # MASTER_CONTINUITY_CURRENT.md. Docs already indexed for the SAME days by OTHER
        # writers (save_state's per-session auto-index, or a manual tiered_reindex run)
        # become byte-identical duplicates once this batch lands — the live store had 36
        # confirmed triple-indexed T4 prefixes across days ~124-131 from exactly this gap.
        # The own-source cleanup above only ever purged reindex_recent's OWN prior run.
        covered_days = set()
        for chunk in tiered_chunks:
            try:
                day_val = int(chunk["metadata"].get("day", 0))
                if day_val > 0:
                    covered_days.add(day_val)
            except Exception:
                pass

        if covered_days:
            try:
                # Narrow to the OTHER duplicate-producing writers only (save_state,
                # a manual tiered_reindex run) — NOT a blanket $ne. A blanket $ne also
                # matches npc_auto_index docs, which are standalone NPC cards, not
                # duplicates of this reindex; deleting them would silently destroy
                # data with no writer left to re-create it.
                other_docs = tiered_collection.get(
                    where={"source": {"$in": ["save_state", "tiered_reindex"]}},
                    include=['metadatas']
                )
                stale_ids = []
                for doc_id, meta in zip(other_docs.get('ids', []), other_docs.get('metadatas', [])):
                    try:
                        if int(meta.get('day', 0)) in covered_days:
                            stale_ids.append(doc_id)
                    except Exception:
                        pass
                if stale_ids:
                    tiered_collection.delete(ids=stale_ids)
                    output.append(f"Removed {len(stale_ids)} cross-source duplicate documents (days {sorted(covered_days)})")
            except Exception:
                pass  # Best-effort dedup; never block the reindex on this

        # Index tiered chunks — batched for GPU efficiency
        BATCH_SIZE = 32
        indexed = 0
        tier_counts = {1: 0, 2: 0, 3: 0, 4: 0}
        for batch_start in range(0, len(tiered_chunks), BATCH_SIZE):
            batch = tiered_chunks[batch_start:batch_start + BATCH_SIZE]
            try:
                embed_texts = [c.get("embedding_text", c["text"]) for c in batch]
                embeddings = get_ollama_embeddings_batch(embed_texts, timeout=120.0)
                tiered_collection.add(
                    ids=[c["id"] for c in batch],
                    embeddings=embeddings,
                    documents=[c["text"] for c in batch],
                    metadatas=[_stringify_metadata(c["metadata"]) for c in batch]
                )
                for c in batch:
                    indexed += 1
                    tier_counts[c["metadata"]["tier"]] += 1
            except Exception:
                # Batch failed — fall back to one-by-one for this batch
                for chunk in batch:
                    try:
                        embed_text = chunk.get("embedding_text", chunk["text"])
                        embedding = get_ollama_embedding_sync(embed_text, timeout=60.0)
                        tiered_collection.add(
                            ids=[chunk["id"]],
                            embeddings=[embedding],
                            documents=[chunk["text"]],
                            metadatas=[_stringify_metadata(chunk["metadata"])]
                        )
                        indexed += 1
                        tier_counts[chunk["metadata"]["tier"]] += 1
                    except Exception:
                        pass  # Skip failed chunks silently

        output.append(f"Indexed {indexed} tiered chunks (T1:{tier_counts[1]} T2:{tier_counts[2]} T3:{tier_counts[3]} T4:{tier_counts[4]})")
        output.append(f"Collection now has {tiered_collection.count()} total documents")
        # Session-end Step 7->8 close: reindex is the last INDEX call, so name the
        # post-save verify pass in-band (reindex succeeded here -> reindex_ok=True).
        output.append(_pf.next_block(_pf.push_call(
            "verify_session_save",
            facts_path=_pf.raw("<session_end_facts.json>"),
            pass_number=_pf.raw("2"),
            reindex_ok=_pf.raw("True"),
            distillations_written=_pf.raw("<count written in Step 7>")),
            label="verify pass 2"))
        return "\n".join(output)

    except Exception as e:
        return f"ERROR: Reindex failed: {str(e)}"


# ingest_distillations moved to session_tools.py (Wave 8 slice 2); registered via register_session_tools.


# distill_session moved to session_tools.py (Wave 8 slice 2); registered via register_session_tools.


def _distill_analyze(session_text: str) -> str:
    """Scan existing distillations for staleness and match entity names in session text."""
    try:
        from hooks.hook_utils import _load_alias_map
    except ImportError:
        from hook_utils import _load_alias_map

    cache = _get_distillation_cache()
    all_entries = cache.all_entries()

    if not all_entries and not session_text.strip():
        return "No existing distillations and no session text provided. Nothing to analyze."

    # --- Staleness scan ---
    lorebook_path = CAMPAIGN_DIR / "lorebook.json"
    npc_states_path = CAMPAIGN_DIR / "npc_states.json"
    current_mtimes = {}
    try:
        if lorebook_path.exists():
            current_mtimes["lorebook_mtime"] = lorebook_path.stat().st_mtime
        if npc_states_path.exists():
            current_mtimes["npc_states_mtime"] = npc_states_path.stat().st_mtime
    except OSError:
        logging.warning("distill_session analyze: failed to stat source files for staleness check")

    stale_entries = []
    for entry in all_entries:
        if cache.is_stale(entry, current_mtimes):
            stale_sources = []
            verified = entry.get("verified_against", {})
            for src, cur_mt in current_mtimes.items():
                if cur_mt > verified.get(src, 0):
                    stale_sources.append(src.replace("_mtime", ""))
            stale_entries.append({
                "topic_key": entry["topic_key"],
                "stale_sources": stale_sources,
                "last_refined": entry.get("refined_count", 0),
            })

    # --- Entity scan ---
    text_lower = session_text.lower() if session_text else ""
    all_slugs = set()
    key_to_slugs = {}
    for entry in all_entries:
        key = entry["topic_key"]
        parts = key.split("_")
        slugs = parts[:-1] if parts else []
        key_to_slugs[key] = slugs
        all_slugs.update(slugs)

    touched_keys = []
    unmatched_names = []
    if text_lower:
        for key, slugs in key_to_slugs.items():
            if any(len(s) >= 3 and s in text_lower for s in slugs):
                touched_keys.append(key)

        aliases = _load_alias_map()
        known_slugs_lower = {s.lower() for s in all_slugs}
        for name, slug in aliases.items():
            if len(slug) >= 3 and slug in text_lower and slug not in known_slugs_lower:
                unmatched_names.append(name)

    # --- Format output ---
    lines = []
    lines.append(f"**Distillation Analysis** ({len(all_entries)} existing entries)")
    lines.append("")

    if stale_entries:
        lines.append(f"**Stale entries ({len(stale_entries)}):**")
        for se in stale_entries[:20]:
            lines.append(f"  - `{se['topic_key']}` — sources changed: {', '.join(se['stale_sources'])} (refined {se['last_refined']}x)")
    else:
        lines.append("**No stale entries.**")

    lines.append("")
    if touched_keys:
        lines.append(f"**Session touched ({len(touched_keys)} existing entries):**")
        for tk in sorted(touched_keys)[:30]:
            lines.append(f"  - `{tk}`")
    else:
        lines.append("**No existing entries matched session text.**")

    if unmatched_names:
        lines.append("")
        lines.append(f"**Potential new entities ({len(unmatched_names)}):**")
        for name in sorted(set(unmatched_names))[:10]:
            lines.append(f"  - {name}")

    return "\n".join(lines)


_DISTILL_OVERLAP_AUTO_MERGE = 0.3
_DISTILL_OVERLAP_AMBIGUOUS = 0.5


def _distill_write(entries: list[dict], session_id: str) -> str:
    """Validate, deduplicate, and write distillation entries to the cache."""
    if not entries:
        return "No entries provided. Nothing written."
    if not session_id:
        session_id = "unknown"

    cache = _get_distillation_cache()

    lorebook_path = CAMPAIGN_DIR / "lorebook.json"
    npc_states_path = CAMPAIGN_DIR / "npc_states.json"
    current_mtimes = {}
    try:
        if lorebook_path.exists():
            current_mtimes["lorebook_mtime"] = lorebook_path.stat().st_mtime
        if npc_states_path.exists():
            current_mtimes["npc_states_mtime"] = npc_states_path.stat().st_mtime
    except OSError:
        logging.warning("distill_session write: failed to stat source files for mtime check")

    ollama_ok = check_ollama_health()
    if not ollama_ok:
        logging.warning("distill_session write: Ollama unavailable — skipping overlap detection")

    created = 0
    updated = 0
    merged = 0
    rejected = []
    ambiguous = []

    for entry_input in entries:
        topic_key = entry_input.get("topic_key", "").strip()
        learning = entry_input.get("learning", "").strip()
        key_facts = entry_input.get("key_facts", [])
        source_pointers = entry_input.get("source_pointers", [])
        # v3 parity: capture rich metadata so session-distilled nuggets match the
        # bulk-loaded corpus (else ingest falls back to the weak topic_key heuristic).
        nug_type = entry_input.get("type", "")
        nug_characters = entry_input.get("characters", []) or []
        nug_entities = entry_input.get("entities", []) or []
        nug_arc = entry_input.get("arc", "")
        nug_day_range = entry_input.get("day_range", "")

        if not topic_key:
            rejected.append("(missing topic_key)")
            continue
        if not learning:
            rejected.append(f"{topic_key}: empty learning text")
            continue
        if not key_facts:
            rejected.append(f"{topic_key}: empty key_facts")
            continue

        existing = cache.get(topic_key)

        if existing is not None:
            existing_facts = set(existing.get("key_facts", []))
            new_facts = list(existing.get("key_facts", []))
            for fact in key_facts:
                if fact not in existing_facts:
                    new_facts.append(fact)
                    existing_facts.add(fact)

            existing["learning"] = learning
            existing["key_facts"] = new_facts
            existing["source_pointers"] = source_pointers or existing.get("source_pointers", [])
            existing["refined_count"] = (existing.get("refined_count") or 0) + 1
            existing["refined_turn"] = (existing.get("refined_turn") or 0) + 1
            existing["verified_against"] = current_mtimes or existing.get("verified_against", {})
            if nug_type: existing["type"] = nug_type
            if nug_characters: existing["characters"] = nug_characters
            if nug_entities: existing["entities"] = nug_entities
            if nug_arc: existing["arc"] = nug_arc
            if nug_day_range: existing["day_range"] = nug_day_range
            existing["ingested_at_session"] = None

            cache.put(existing)
            updated += 1

        else:
            if ollama_ok:
                try:
                    embedding = get_embedding_cached(learning)
                    collection = get_canon_distillations_collection()
                    if collection.count() > 0:
                        results = collection.query(
                            query_embeddings=[embedding],
                            n_results=1,
                        )
                        if results and results["distances"] and results["distances"][0]:
                            dist = results["distances"][0][0]
                            match_id = results["ids"][0][0] if results["ids"] and results["ids"][0] else None
                            if dist < _DISTILL_OVERLAP_AUTO_MERGE and match_id:
                                merge_target = cache.get(match_id)
                                if merge_target:
                                    merge_facts = set(merge_target.get("key_facts", []))
                                    merged_facts = list(merge_target.get("key_facts", []))
                                    for fact in key_facts:
                                        if fact not in merge_facts:
                                            merged_facts.append(fact)
                                            merge_facts.add(fact)
                                    merge_target["key_facts"] = merged_facts
                                    merge_target["refined_count"] = merge_target.get("refined_count", 1) + 1
                                    merge_target["verified_against"] = current_mtimes or merge_target.get("verified_against", {})
                                    merge_target["ingested_at_session"] = None
                                    cache.put(merge_target)
                                    merged += 1
                                    continue
                            elif dist < _DISTILL_OVERLAP_AMBIGUOUS and match_id:
                                ambiguous.append({
                                    "new_key": topic_key,
                                    "similar_to": match_id,
                                    "distance": round(dist, 3),
                                })
                except (ConnectionError, Exception) as e:
                    logging.warning(f"distill_session: overlap check failed for {topic_key}: {e}")

            new_entry = {
                "topic_key": topic_key,
                "learning": learning,
                "key_facts": key_facts,
                "source_pointers": source_pointers,
                "type": nug_type,
                "characters": nug_characters,
                "entities": nug_entities,
                "arc": nug_arc,
                "day_range": nug_day_range,
                "verified_against": current_mtimes,
                "created_turn": 0,
                "created_session": session_id,
                "refined_turn": 0,
                "refined_count": 1,
                "ingested_at_session": None,
            }
            cache.put(new_entry)
            created += 1

    # Session-end backstop (Task 5): echo each NPC-with-continuity into the same
    # distillation cache so ingest_distillations embeds the dossier for deep recall.
    _echoed = _echo_npc_dossiers_to_distillation_cache(session_id)
    lines = [f"**Distillation write complete.** Created: {created}, Updated: {updated}, Merged: {merged} | NPC dossiers echoed: {_echoed}."]
    if rejected:
        lines.append(f"Rejected ({len(rejected)}):")
        for r in rejected[:5]:
            lines.append(f"  - {r}")
    if ambiguous:
        lines.append(f"Ambiguous overlaps ({len(ambiguous)}) — review and merge if appropriate:")
        for a in ambiguous:
            lines.append(f"  - `{a['new_key']}` is similar to `{a['similar_to']}` (distance: {a['distance']})")
    if not ollama_ok:
        lines.append("Warning: Ollama was offline — overlap detection was skipped. Duplicates possible.")
    # session_id is REQUIRED by ingest_distillations and was already coerced to
    # "unknown" above when absent — always render it so the call never bounces.
    lines.append(_pf.next_block(_pf.push_call("ingest_distillations", session_id=session_id), label="index step 7"))
    return "\n".join(lines)


# ============================================
# CHARACTER SYSTEM v2 - JSON-BACKED
# ============================================
# New character management system using characters.json and party.json
# Replaces markdown-based tracking with slot-accurate validation

# Wound tables for Vaults of Vaarn -- canonical copies live in wounds.py
# (book-accurate, structured fields; the old in-file SYNTHETIC_WOUNDS was
# fabricated). Re-exported here so existing call sites keep the module names.
# Table entries are READ-ONLY: records are built as copies via
# wounds.roll_wound_record; never mutate an entry.
BIOLOGICAL_WOUNDS = _wnd.BIOLOGICAL_WOUNDS
SYNTHETIC_WOUNDS = _wnd.SYNTHETIC_WOUNDS


# _load_characters / _save_characters / _save_single_character moved to engine_core (Wave 0 slice 3); imported at the top.


def _expire_turn_conditions_for_map(map_name: str, current_turn: int) -> list:
    """B3: registered as map_system.turn_hook. Sweeps every PC's
    until_turn conditions against this map's counter; persists; returns
    wear-off lines for the map output."""
    lines = []
    data, err = _load_characters()
    if err or not data:
        return []
    changed = False
    for key, char in data.get("characters", {}).items():
        if not isinstance(char, dict):
            continue
        expired = _cnd.expire_turn_conditions(char, map_name, current_turn)
        if expired:
            for c in expired:
                lines.append(f"{char.get('name', key)}'s {c['name']} wears "
                             f"off (turn {current_turn}).")
            _save_single_character(key, char, data)
            changed = True
    return lines


# B3: wire the turn-expiry sweep into the map system (map_system is bound at
# module import, ~line 3476). Defined here so it can see _load_characters /
# _save_single_character / _cnd.
map_system.turn_hook = _expire_turn_conditions_for_map


# _load_party / _find_character moved to engine_core (Wave 0 slice 3); imported at the top.


# _calculate_slots moved to engine_core (death-seam leaf wave); imported at the top.


# _refresh_slot_fields moved to engine_core (death-seam leaf wave); imported at the top.


# _encumbrance_save_note moved to engine_core (death-seam leaf wave); imported at the top.


# _wound_save_note moved to engine_core (death-seam leaf wave); imported at the top.


# _condition_save_note moved to engine_core (death-seam leaf wave); imported at the top.


def _apply_inventory_changes(inventory_changes: list, day: int) -> list:
    """
    Apply structured inventory changes to characters.json.

    Each change should be a dict with:
        - character: str (required) - character name
        - action: str - "add" (default) or "remove"
        - container: str - "carried" (default), "stored", or "installed_permanent"
        - item: dict - item to add (required for "add")
        - item_id: str - id of item to remove (required for "remove"; the nested
          {"item": {"id": ...}} shape is also accepted, mirroring "add")

    Returns list of result messages.
    """
    results = []
    data, err = _load_characters()
    if err:
        return [f"ERROR loading characters: {err}"]

    modified = False

    for change in inventory_changes:
        if not isinstance(change, dict):
            results.append(f"SKIP: non-dict inventory entry: {str(change)[:50]}")
            continue
        char_name = change.get("character")
        if not char_name:
            results.append("SKIP: No character specified in inventory change")
            continue

        action = change.get("action", "add")
        container = change.get("container", "carried")

        key, char = _find_character(data, char_name)
        if not char:
            results.append(f"SKIP: Character '{char_name}' not found")
            continue

        # Ensure inventory structure exists
        if "inventory" not in char:
            char["inventory"] = {"carried": [], "stored": [], "installed_permanent": [], "given_away": []}
        if container not in char["inventory"]:
            char["inventory"][container] = []

        if action == "add":
            item = change.get("item", {})
            if not item:
                results.append(f"SKIP: No item specified for add action on {char_name}")
                continue

            # Generate id if not provided
            if not item.get("id"):
                item["id"] = item.get("name", "unknown").lower().replace(" ", "_").replace("(", "").replace(")", "")
            if not item.get("day_acquired"):
                item["day_acquired"] = day

            # Book-accurate encumbrance: allow exceeding the personal cap up to the
            # hard 20-slot ceiling; flag Encumbered instead of rejecting.
            if container == "carried":
                slots = _calculate_slots(char)
                item_slots = item.get("slots", 1)
                projected = slots["total_used"] + slots["wounds"] + item_slots
                if projected > _isl.HARD_CEILING:
                    results.append(
                        f"REJECTED: {char['name']} can't carry {item.get('name', 'item')} — "
                        f"would exceed the hard {_isl.HARD_CEILING}-slot limit ({projected}).")
                    continue
                if projected > slots["capacity"]:
                    results.append(
                        f"ADDED (ENCUMBERED): {item.get('name', 'item')} — {char['name']} now "
                        f"{projected}/{slots['capacity']} slots; DIS on STR/DEX/CON saves.")

            char["inventory"][container].append(item)
            results.append(f"ADDED: {item.get('name', item.get('id'))} to {char['name']}'s {container}")
            modified = True

        elif action == "remove":
            # Accept the top-level item_id, the nested {"item": {"id": ...}}
            # shape, AND a bare string {"item": "Water Rations"} — the natural
            # thing a caller writes. The string form used to crash here
            # ('str' object has no attribute 'get') because the code assumed
            # item was always a dict. Derive a single match target from whatever
            # shape arrived.
            raw_item = change.get("item")
            if isinstance(raw_item, str):
                target = change.get("item_id") or raw_item
            elif isinstance(raw_item, dict):
                target = change.get("item_id") or raw_item.get("id") or raw_item.get("name")
            else:
                target = change.get("item_id")
            if not target:
                results.append(
                    f"SKIP: remove needs item_id, item.id, or a bare item name "
                    f"on {char_name} — nothing removed")
                continue

            # Match by id, name, or slugified name (case-insensitive) so a caller
            # can pass either the stable id ("water_rations") or the display name
            # ("Water Rations").
            target_l = str(target).strip().lower()
            target_slug = target_l.replace(" ", "_").replace("(", "").replace(")", "")
            items = char["inventory"][container]
            found = False
            for i, item in enumerate(items):
                iid = str(item.get("id", "")).lower()
                iname = str(item.get("name", "")).lower()
                if target_l in (iid, iname) or target_slug == iid:
                    removed = items.pop(i)
                    results.append(f"REMOVED: {removed.get('name', target)} from {char['name']}'s {container}")
                    found = True
                    modified = True
                    break

            if not found:
                results.append(f"NOT FOUND: {target} in {char['name']}'s {container}")

    # Update slot counts in JSON after all changes
    if modified:
        for key, char in data.get("characters", {}).items():
            if isinstance(char, dict) and "inventory" in char:
                _refresh_slot_fields(char)
        _save_characters(data)
        results.append("character sheets saved")

    return results


# _check_death_conditions moved to engine_core (death-seam orchestrator wave); imported at the top.


# _death_window moved to engine_core (death-seam leaf wave); imported at the top.


# _twinning_partner_check moved to engine_core (death-seam leaf wave); imported at the top.


# _leader_ego_bonus moved to engine_core (death-seam leaf wave); imported at the top.


# _follower_morale_lines moved to engine_core (death-seam leaf wave); imported at the top.


# _death_seam_lines moved to engine_core (death-seam leaf wave); imported at the top.


# _death_gate moved to engine_core (death-seam orchestrator wave); imported at the top.


# _check_death_gated moved to engine_core (death-seam orchestrator wave); imported at the top.


def _roll_drain(notation_or_flat):
    """Roll a drain value that may be dice notation ('d4', 'd8') or a flat
    positive integer stored as a string ('1', '2'). Returns the int result.
    ASCII-only helper; flat integers bypass roll_notation entirely."""
    s = str(notation_or_flat).strip()
    if s.isdigit():
        return int(s)
    return dice.roll_notation(s)["total"]


def _disease_death_prose(char) -> list:
    """If a PC died with an active disease whose endpoint is a transformation
    (Hiveyman, Lumenrot dissolution, Pox vanishing), return the prose lines to
    push ABOVE the p.229 menu, plus a body-state note (a dissolved/vanished
    corpse constrains which resurrection paths a DM can allow). Empty list when
    no transformation disease is active."""
    lines = []
    for c in (char.get("conditions") or []):
        if not isinstance(c, dict) or c.get("cause") not in ("disease", "nanomachine"):
            continue
        d = _dz.DISEASES.get(c.get("name"))
        if d and d.get("transformation"):
            lines.append(
                f"  TRANSFORMATION ({c['name']}): {d['transformation']}")
    if lines:
        lines.append("  Body-state note: the corpse's condition (dissolved, "
                     "vanished, hive-ridden) is a DM ruling on which p.229 "
                     "paths remain open.")
    return lines


# ============================================
# DYNAMIC DATA RESOURCES
# ============================================
# These expose dynamic JSON data as resources with templates

@mcp.resource("campaign://characters")
def resource_all_characters() -> dict:
    """Get all characters as structured data."""
    data, err = _load_characters()
    if err:
        return {"error": err}
    return data.get('characters', {})

@mcp.resource("campaign://characters/{name}")
def resource_character(name: str) -> dict:
    """Get a specific character's data."""
    data, err = _load_characters()
    if err:
        return {"error": err}
    key, char = _find_character(data, name)
    if not char:
        return {"error": f"Character '{name}' not found"}
    return char

@mcp.resource("campaign://party")
def resource_party() -> dict:
    """Get party shared resources (wealth, vehicles)."""
    data, err = _load_party()
    if err:
        return {"error": err}
    return data

@mcp.resource("campaign://party/wealth")
def resource_party_wealth() -> dict:
    """Get party wealth summary."""
    data, err = _load_party()
    if err:
        return {"error": err}
    return data.get('wealth', {})

@mcp.resource("campaign://party/vehicles")
def resource_party_vehicles() -> dict:
    """Get party vehicles status."""
    data, err = _load_party()
    if err:
        return {"error": err}
    return data.get('vehicles', {})

# ============================================
# CONSOLIDATED CHARACTER TOOL
# ============================================

VALID_CHARACTER_ACTIONS = [
    "get", "list", "equip", "unequip", "update_hp", "update_stat", "gain_xp",
    "level_up", "level_up_proteus", "level_up_bloomboon",
    "damage", "check_death",
    "resurrect", "resurrect_resolve", "spirit_spend",
    "use_daily", "create", "create_finalize", "register",
    "recruit_follower", "follower_level_up", "dismiss_follower",
    "recruit_mercenary", "dismiss_mercenary", "pay_mercenary",
    "mercenary_expedition_end", "merc_morale_check",
    "drink_elixir",
    "acquire_pet", "acquire_steed", "level_up_pet",
    "ride_steed", "dismiss_companion",
    "acquire_vehicle", "repair_vehicle", "move_vehicle"
]

@mcp.tool(tags=_get_tool_tags("character"))
def character(
    action: str = Field(description="get|list|equip|unequip|update_hp|update_stat|gain_xp|level_up|level_up_proteus|level_up_bloomboon|damage|check_death|resurrect|resurrect_resolve|spirit_spend|use_daily|create|create_finalize|register|recruit_follower|follower_level_up|dismiss_follower|recruit_mercenary|dismiss_mercenary|pay_mercenary|mercenary_expedition_end|merc_morale_check|drink_elixir|acquire_pet|acquire_steed|level_up_pet|ride_steed|dismiss_companion|acquire_vehicle|repair_vehicle|move_vehicle"),
    name: str = Field(default=None, description="Character name. recruit_*/acquire_* = the LEADER; follower/merc/companion ops = the hireling or companion; mercenary_expedition_end/merc_morale_check = a leader OR a single merc; ride_steed = the steed."),
    hp: int = Field(default=None, description="New current HP"),
    max_hp: int = Field(default=None, description="New max HP"),
    stat: str = Field(default=None, description="STR/DEX/CON/INT/PSY/EGO"),
    value: int = Field(default=None, description="New stat value"),
    amount: int = Field(default=None, description="XP or damage amount"),
    reason: str = Field(default=None, description="XP reason / [dismiss_follower] Why they left"),
    stat_increases: str = Field(default=None, description="level_up: 'DEX,CON,EGO'"),
    hp_roll: int = Field(default=None, description="level_up: d8 result"),
    damage_type: str = Field(default=None, description="kinetic/beam/blast/flame/electrical/TOX (kinetic melee may be sub-typed slashing/piercing/bludgeoning for creature-specific resistances)"),
    path: str = Field(default=None, description="resurrect: mycomorph|necrotech|pseudo_womb|spirit|ego_engine"),
    save_total: int = Field(default=None, description="resurrect_resolve: d20 + bonus (or d20 + Level for spirit)"),
    natural_die: int = Field(default=None, description="resurrect_resolve: the natural d20 face (20=auto-pass, 1=auto-fail)"),
    kind: str = Field(default=None, description="spirit_spend: touch|possess"),
    target_level: int = Field(default=None, description="spirit_spend possess: the target's Level"),
    replace: bool = Field(default=False, description="resurrect: override an in-progress path"),
    intact_core: bool = Field(default=False, description="resurrect_resolve ego_engine: the Synth core survived"),
    daily: str = Field(default=None, description="[use_daily] Name of the special_traits.daily_uses entry (e.g. 'Harvest Toxic Sap')"),
    ancestry: str = Field(default=None, description="[create_finalize] Ancestry key: true-kin|cacogen|synth|newbeast|neobloom|mycomorph|faa-nomad|cacklemaw-exile|planeyfolk|lithling"),
    swap: str = Field(default=None, description="[create_finalize] Swap two rolled ability scores, e.g. 'STR,PSY', or 'none'"),
    take5: bool = Field(default=False, description="[create_finalize] Take 5 HP at level 1 instead of rolling d8 (CH p.5 option)"),
    follower_name: str = Field(default=None, description="[recruit_follower/recruit_mercenary] Override the table's recruit name"),
    companion_type: str = Field(default=None, description="[acquire_pet/acquire_steed] Catalog slug, e.g. 'ray_cat' or 'zorse'"),
    vehicle_type: str = Field(default=None, description="[acquire_vehicle] Catalog slug, e.g. 'dune_skuggy' or 'crawler'"),
    hull_points: int = Field(default=None, description="[repair_vehicle] Hull points to restore (1 day each)"),
    rider: str = Field(default=None, description="[acquire_steed/ride_steed] PC who rides the steed ('' or 'none' to dismount)"),
    recruit_roll: int = Field(default=None, description="[recruit_follower/recruit_mercenary] Force the d20+EGO total 0-30"),
    elixir: str = Field(default=None, description="[drink_elixir] Elixir row 1-40, a d100 roll, or an inline JSON record"),
    target: str = Field(default=None, description="[drink_elixir] The target of a save-fork / Lazarus / Kalotoxin elixir (defaults to the drinker)"),
    new_location: str = Field(default=None, description="[move_vehicle] Where the vehicle moved to"),
    operational: bool = Field(default=True, description="[move_vehicle] Whether the vehicle remains operational"),
    sheet: str = Field(default=None, description="[register] Full character sheet as JSON — author the stat block (level, hp{current,max}, av{base}, abilities{STR..EGO:{current,base}}, wound_table, species) + any flavor; engine validates + fills the rest"),
    item: str = Field(default=None, description="[equip/unequip] Carried armour/helm/shield to wear or remove, by name or id (substring ok)"),
    slot: str = Field(default=None, description="[equip] Armour slot override: body|helm|shield (auto-inferred from the item name when omitted)"),
    av_bonus: int = Field(default=None, description="[equip] Set/override the item's AV contribution over unarmoured (e.g. a registered Occult Cuirass at AV 14 -> av_bonus 4); omit for generator armour that already carries av_bonus"),
    notes: str = Field(default="", description="[move_vehicle] Optional vehicle status notes")
) -> str:
    """Reach for this WHEN you need to read or write any PC stat, or to stand up and manage a hireling, companion, or vehicle — sheets, HP and damage, XP and level-ups, character creation, recruits, pets/steeds, and vehicles all live here. One tool, many actions; the full valid list is the `action` enum.

Core: get (full sheet) | list (all PCs + HP) | update_hp | update_stat | damage (typed) | gain_xp | level_up / level_up_proteus / level_up_bloomboon | use_daily (once-per-day trait) | check_death.
Creation: create (roll abilities + ancestry suggestion) -> create_finalize (apply swap/ancestry/take5, write the sheet). register: persist an improvised or recruited character from a JSON `sheet` you author; the engine validates and fills the rest.
Death: resurrect -> resurrect_resolve | spirit_spend (touch/possess).
Hirelings (name = the LEADER): recruit_follower | follower_level_up | dismiss_follower | recruit_mercenary | dismiss_mercenary | pay_mercenary | mercenary_expedition_end | merc_morale_check.
Companions & vehicles: acquire_pet | acquire_steed | level_up_pet | ride_steed | dismiss_companion | acquire_vehicle | repair_vehicle | move_vehicle. (name = the owning PC, except ride_steed/repair_vehicle/move_vehicle, where name = the companion or vehicle.)
Consumables: drink_elixir."""

    action = action.lower().strip()
    if action not in VALID_CHARACTER_ACTIONS:
        return f"Invalid action '{action}'. Valid actions: {', '.join(VALID_CHARACTER_ACTIONS)}"

    # Actions that don't require a name
    if action == "list":
        return _character_list()
    if action == "create":
        return _character_create(name=name)
    if action == "create_finalize":
        return _character_create_finalize(name, ancestry=ancestry, swap=swap,
                                          take5=(take5 is True))
    if action == "register":
        return _character_register(name, sheet)

    # All other actions require a name
    if not name:
        return f"Action '{action}' requires 'name' parameter."

    if action == "get":
        return _character_get(name)
    elif action == "equip":
        return _character_equip(name, item, slot=slot, av_bonus=av_bonus)
    elif action == "unequip":
        return _character_unequip(name, item)
    elif action == "update_hp":
        if hp is None:
            return "update_hp requires 'hp' parameter."
        _result = _character_update_hp(name, hp, max_hp)
        _emit_player_view()
        return _result
    elif action == "update_stat":
        if stat is None or value is None:
            return "update_stat requires 'stat' and 'value' parameters."
        return _character_update_stat(name, stat, value)
    elif action == "gain_xp":
        if amount is None:
            return "gain_xp requires 'amount' parameter."
        return _character_gain_xp(name, amount, reason or "unspecified")
    elif action == "level_up":
        if stat_increases is None or hp_roll is None:
            return "level_up requires 'stat_increases' and 'hp_roll' parameters."
        return _character_level_up(name, stat_increases, hp_roll)
    elif action == "level_up_proteus":
        return _character_level_up_proteus(name)
    elif action == "level_up_bloomboon":
        return _character_level_up_bloomboon(name)
    elif action == "damage":
        if amount is None:
            return "damage requires 'amount' parameter."
        return _character_take_damage(name, amount, damage_type or "kinetic")
    elif action == "check_death":
        return _character_check_death(name)
    elif action == "resurrect":
        return _character_resurrect(name, path=path, replace=bool(replace))
    elif action == "resurrect_resolve":
        return _character_resurrect_resolve(
            name, path=path, save_total=save_total,
            natural_die=natural_die, intact_core=bool(intact_core))
    elif action == "spirit_spend":
        return _character_spirit_spend(name, kind=kind, target_level=target_level)
    elif action == "recruit_follower":
        return _character_recruit_follower(name, follower_name=follower_name,
                                           recruit_roll=recruit_roll)
    elif action == "follower_level_up":
        return _character_follower_level_up(name)
    elif action == "dismiss_follower":
        return _character_dismiss_follower(name, reason=reason)
    elif action == "recruit_mercenary":
        return _character_recruit_mercenary(name, merc_name=follower_name,
                                            recruit_roll=recruit_roll)
    elif action == "dismiss_mercenary":
        return _character_dismiss_mercenary(name, reason=reason)
    elif action == "pay_mercenary":
        return _character_pay_mercenary(name)
    elif action == "mercenary_expedition_end":
        return _character_mercenary_expedition_end(name)
    elif action == "merc_morale_check":
        return _character_merc_morale_check(name)
    elif action == "acquire_pet":
        return _character_acquire_pet(name, companion_type, follower_name)
    elif action == "acquire_steed":
        return _character_acquire_steed(name, companion_type, follower_name, rider)
    elif action == "level_up_pet":
        return _character_level_up_pet(name, hp_roll)
    elif action == "ride_steed":
        return _character_ride_steed(name, rider)
    elif action == "dismiss_companion":
        return _character_dismiss_companion(name, reason)
    elif action == "acquire_vehicle":
        return _character_acquire_vehicle(name, vehicle_type, follower_name)
    elif action == "repair_vehicle":
        return _character_repair_vehicle(name, hull_points)
    elif action == "move_vehicle":
        from pydantic.fields import FieldInfo as _FI
        _loc = None if isinstance(new_location, _FI) else new_location
        if not _loc:
            return "move_vehicle requires new_location"
        _op = True if isinstance(operational, _FI) else operational
        _nt = "" if isinstance(notes, _FI) else notes
        return _update_vehicle_location_impl(vehicle_name=name, new_location=_loc, operational=_op, notes=_nt)
    elif action == "use_daily":
        if not daily or not isinstance(daily, str):
            return "use_daily requires 'daily' (the daily_uses entry name)."
        data, err = _load_characters()
        if err:
            return err
        key, char = _find_character(data, name)
        if not char:
            return f"Character '{name}' not found."
        day = data.get("meta", {}).get("campaign_day") or 0
        out = _character_use_daily(char, daily, day=day)
        _save_single_character(key, char, data)
        return out
    elif action == "drink_elixir":
        if elixir is None:
            return "drink_elixir requires 'elixir' (row 1-40, d100 roll, or inline JSON)."
        data, err = _load_characters()
        if err:
            return err
        key, char = _find_character(data, name)
        if not char:
            return f"Character '{name}' not found."
        day = data.get("meta", {}).get("campaign_day") or 0
        return _character_drink_elixir(key, elixir, day,
                                       target=target, save_total=save_total)

    return f"Action '{action}' not implemented."


# CHARACTER section (57 funcs + 5 consts) moved to character_tools.py (decomposition
# slice 6); imported-and-aliased back here. The character()/wound() tool dispatchers
# stay and call these. _roll_cacogen_mutation stays (re-exported). 
# register_character_tools() (below) binds the live module + injects the data tables.
import character_tools
from character_tools import (
    _character_use_daily,
    _active_site_briefing_line,
    _drink_resolve_data,
    _dose_name_matches,
    _elixir_record,
    _elixir_duration_stamp,
    _character_drink_elixir,
    _elixir_apply_effect,
    _lazarus_eligible,
    _resolve_target_char,
    _elixir_save_fork,
    _character_get,
    _character_equip,
    _character_unequip,
    _character_list,
    _character_update_hp,
    _character_update_stat,
    _character_gain_xp,
    _character_level_up,
    _character_level_up_proteus,
    _pc_gear_item,
    _character_create,
    _character_create_finalize,
    _character_register,
    _follower_species,
    _character_recruit_follower,
    _character_follower_level_up,
    _character_dismiss_follower,
    _character_recruit_mercenary,
    _character_dismiss_mercenary,
    _write_companion_sheet,
    _character_acquire_pet,
    _steed_ridden_by,
    _character_acquire_steed,
    _character_level_up_pet,
    _character_ride_steed,
    _character_dismiss_companion,
    _character_acquire_vehicle,
    _character_repair_vehicle,
    _character_mercenary_expedition_end,
    _character_pay_mercenary,
    _mercenary_pay_nag_lines,
    _character_merc_morale_check,
    _character_resurrect,
    _character_resurrect_resolve,
    _character_spirit_spend,
    _character_level_up_bloomboon,
    _remove_wound,
    _wound_status_lines,
    _wound_dispatch,
    _character_take_damage,
    _vehicle_take_damage,
    _vehicle_attack_bonus,
    _vehicle_speed_save_lines,
    _character_check_death,
    ELIXIR_UNDRINKABLE_SPECIES,
    PC_ABILITY_ORDER,
    PC_STARTING_BOONS,
    FOLLOWER_RANGED_ATTACKS,
    MERCENARY_RANGED_ATTACKS,
)


# Synthetic and Mineral PCs cannot drink elixirs. Topical/inject rows bypass.


def _active_vault_turn():
    """B3: (map_name, current_turn) of the active vault map, or (None, None).

    Reads the SAME active-map source the canon injector uses (CURRENT_STATUS.md
    'Active Map' -> map_system.get_map_state). The ONLY place drink_elixir
    learns about maps; tests monkeypatch this directly."""
    try:
        content = read_current_status(required=False)
        if not content:
            return None, None
        active = (_parse_status_content(content).get("active_map") or "").strip()
    except Exception:
        return None, None
    if not active or active.lower() == "none":
        return None, None
    state = map_system.get_map_state(active)
    if not state:
        return None, None
    return active, int(state.get("current_turn", 0))


















# _elixir_hp_floor moved to engine_core (death-seam leaf wave); imported at the top.






# --- Internal implementations (prefixed with _) ---















def _roll_d4() -> int:
    """A single d4 (1-4). Wrapped so tests can monkeypatch it deterministically."""
    return dice.roll_notation("d4")["total"]


# _roll_cacogen_mutation moved to generators.py (the content/NPC generator) and
# aliased back above. It is now THE single mutation mint path; the content forge
# delegates to it via roll_mutation_fn injection (below) instead of owning its own.
def _roll_3d6_lowest() -> tuple:
    """3d6, take the LOWEST die as the ability bonus (book p.13 -- the Ego-Engine
    reroll). Returns (lowest, [d1, d2, d3]) so output can show all three dice.
    Wrapped so tests can monkeypatch it."""
    rolls = [dice.roll_notation("d6")["total"] for _ in range(3)]
    return min(rolls), rolls


def _roll_d6() -> int:
    """A single d6 (1-6). Wrapped so tests can monkeypatch it deterministically."""
    return dice.roll_notation("d6")["total"]











# Ranged attacks on the CH p.62 recruitment table - EXPLICIT list (name
# heuristics are forbidden); everything else on the table is melee.








def _move_sheet_to_departed(key):
    """Move characters/<key>.json into characters/departed/ (the roster loader
    globs only characters/*.json, so the move IS the removal - file preserved
    for return arcs). Returns True if a file was moved, False if none on disk.
    Shared by dismiss_follower and dismiss_mercenary."""
    src = CAMPAIGN_DIR / "characters" / f"{key}.json"
    if not src.exists():
        return False
    departed_dir = CAMPAIGN_DIR / "characters" / "departed"
    departed_dir.mkdir(parents=True, exist_ok=True)
    dst = departed_dir / f"{key}.json"
    try:
        src.rename(dst)
    except OSError:
        import shutil as _shutil  # cross-filesystem rename fallback
        _shutil.copy2(src, dst)
        src.unlink()
    return True




# ---------------------------------------------------------------------------
# D3 Mercenaries (CH printed p.63-64): combat-specialist hirelings on a
# SEPARATE EGO-bonus level cap, fixed sheets (no leveling), a pay-per-expedition
# -> sworn-foe loop, and stoic morale (auto-fire only on a party wipe).
# ---------------------------------------------------------------------------

# Mercenary attacks that are ranged (CH p.64). Everything else is melee.






























# _is_pc_sheet moved to engine_core (death-seam leaf wave); imported at the top.


# _all_pcs_down moved to engine_core (death-seam leaf wave); imported at the top.


# _merc_morale_lines moved to engine_core (death-seam leaf wave); imported at the top.












# _apply_ability_damage_from_wound moved to engine_core (death-seam orchestrator wave); imported at the top.


# _apply_wound moved to engine_core (death-seam orchestrator wave); imported at the top.








# _apply_hp_damage_and_wounds moved to engine_core (death-seam orchestrator wave); imported at the top.












# ============================================
# PRIORITY 7: CYBERNETICS MANAGEMENT
# ============================================

@mcp.tool(
    annotations={"readOnlyHint": False, "idempotentHint": False},
    tags=_get_tool_tags("cybernetic")
)
def cybernetic(
    action: str = Field(description="install|list|remove"),
    character_name: str = Field(default=None, description="Character name"),
    implant_name: str = Field(default=None, description="Implant name (install/remove)"),
    ability_slot: str = Field(default=None, description="STR|DEX|CON|INT|PSY|EGO (install only)"),
    effect: str = Field(default=None, description="Mechanical effect (install only)"),
    stat_bonus: str = Field(default=None, description="JSON stat bonus, e.g., '{\"DEX\": 2}' (install only)"),
    day_installed: int = Field(default=None, description="Campaign day (install only)")
) -> str:
    """Reach for this WHEN a PC gains or loses a cybernetic implant — after surgery, scavenging, or forcible removal — to install it into the correct ability slot and apply any stat bonus.

Manage cybernetic implants. action=install: add implant; action=list: show implants; action=remove: remove implant."""
    if action == "install":
        return _cybernetic_install(character_name, implant_name, ability_slot, effect, stat_bonus, day_installed)
    elif action == "list":
        return _cybernetic_list(character_name)
    elif action == "remove":
        return _cybernetic_remove(character_name, implant_name)
    else:
        return f"Invalid action '{action}'. Valid actions: install, list, remove"


# Cybernetic + gift helpers (7 funcs) moved to cyber_gifts.py (decomposition
# slice 3); imported-and-aliased back here. The cybernetic/gift tool dispatchers
# stay and call these. register_cyber_gifts() (below) binds the live module.
import cyber_gifts
from cyber_gifts import (
    _cybernetic_install,
    _cybernetic_remove,
    _cybernetic_list,
    _gift_add,
    _gift_remove,
    _gift_calculate_cost,
    _gleam_check_impl,
)






# ============================================
# PRIORITY 8: MYSTIC GIFTS MANAGEMENT
# ============================================

@mcp.tool(tags=_get_tool_tags("gift"))
def gift(
    action: str = Field(description="add|remove|cost|gleam"),
    character_name: str = Field(default=None, description="Character name (add/remove)"),
    gift_name: str = Field(default=None, description="Gift name (add/remove)"),
    effect: str = Field(default=None, description="Mechanical effect (add)"),
    source: str = Field(default=None, description="How acquired (add)"),
    day_acquired: int = Field(default=None, description="Campaign day (add)"),
    target_level: int = Field(default=None, description="Target's level (cost)"),
    test: bool = Field(default=False, description="gleam: True rolls the weekly Gleam test (d20+Gleam) instead of just reading current Gleam"),
) -> str:
    """Reach for this WHEN a PC acquires or loses a Mystic Gift, when a gift is about to be used and you need the HP cost die for the target's level, or when the weekly psychic Gleam check comes due.

Mystic gift management.
    add: Grant a gift (character_name, gift_name, effect, source) | remove: Remove a gift (character_name, gift_name) | cost: Calculate HP cost (target_level) | gleam: weekly psychic attention check (character_name; test=True rolls the d20+Gleam test)"""
    action = action.lower().strip()
    if action == "add":
        if not character_name or not gift_name or not effect or not source:
            return "Invalid action 'add': requires character_name, gift_name, effect, source"
        return _gift_add(character_name=character_name, gift_name=gift_name, effect=effect, source=source, day_acquired=day_acquired)
    elif action == "remove":
        if not character_name or not gift_name:
            return "Invalid action 'remove': requires character_name, gift_name"
        return _gift_remove(character_name=character_name, gift_name=gift_name)
    elif action == "cost":
        if target_level is None:
            return "Invalid action 'cost': requires target_level"
        return _gift_calculate_cost(target_level=target_level)
    elif action == "gleam":
        if not character_name:
            return "Invalid action 'gleam': requires character_name"
        return _gleam_check_impl(character_name=character_name, test=test)
    else:
        return f"Invalid action '{action}'. Valid actions: add, remove, cost, gleam"










# ============================================
# PRIORITY 9: HYPERGEOMETRIES MANAGEMENT
# ============================================

@mcp.tool(
    annotations={"readOnlyHint": False, "idempotentHint": False},
    tags=_get_tool_tags("codex")
)
def codex(
    action: str = Field(description="add|remove|use|mishap_roll"),
    character_name: str = Field(default=None, description="Character name (add/remove/use)"),
    codex_name: str = Field(default=None, description="Codex name/description (add/remove/use)"),
    equation_name: str = Field(default=None, description="Equation name (add only)"),
    effect: str = Field(default=None, description="Effect description (add only)")
) -> str:
    """Reach for this WHEN a PC finds, attempts to read, trades away, or triggers a mishap with a Hypergeometric Codex.

Hypergeometric codex management.
    add: Add codex to inventory (character_name, codex_name, equation_name, effect) |
    remove: Remove codex from inventory (character_name, codex_name) |
    use: Attempt to use a codex, returns INT save DC and outcomes (character_name, codex_name) |
    mishap_roll: Roll d20 on hypergeometric mishap table after natural 1"""
    action = action.lower().strip()
    if action == "add":
        if not character_name or not codex_name or not equation_name or not effect:
            return "Error: 'character_name', 'codex_name', 'equation_name', and 'effect' required for add."
        return _codex_add(character_name, codex_name, equation_name, effect)
    elif action == "remove":
        if not character_name or not codex_name:
            return "Error: 'character_name' and 'codex_name' required for remove."
        return _codex_remove(character_name, codex_name)
    elif action == "use":
        if not character_name or not codex_name:
            return "Error: 'character_name' and 'codex_name' required for use."
        return _codex_use(character_name, codex_name)
    elif action == "mishap_roll":
        return _codex_mishap_roll()
    else:
        return f"Invalid action '{action}'. Valid actions: add, remove, use, mishap_roll"


def _codex_add(
    character_name: str,
    codex_name: str,
    equation_name: str,
    effect: str
) -> str:
    """Add hypergeometric codex to inventory. Use when character finds or receives a codex. Uses 1 slot."""
    data, err = _load_characters()
    if err:
        return err

    key, char = _find_character(data, character_name)
    if not char:
        raise ToolError(f"Character '{character_name}' not found")

    # Check slot capacity
    slots = _calculate_slots(char)
    if slots['free'] < 1:
        raise ToolError(f"REJECTED: {char['name']} has no free slots for codex. Codices use 1 slot each.")

    codex = {
        'name': codex_name,
        'equation': equation_name,
        'effect': effect,
        'slots': 1
    }

    char.setdefault('codices', []).append(codex)
    _save_single_character(key, char, data)

    new_slots = _calculate_slots(char)
    return f"**{char['name']}** acquired codex: {codex_name}\nEquation: {equation_name}\nEffect: {effect}\nSlots: {new_slots['total_used']}/{new_slots['capacity']}"


def _codex_remove(
    character_name: str,
    codex_name: str
) -> str:
    """Remove codex from inventory. Use when codex is traded, destroyed, or given away."""
    data, err = _load_characters()
    if err:
        return err

    key, char = _find_character(data, character_name)
    if not char:
        raise ToolError(f"Character '{character_name}' not found")

    codices = char.get('codices', [])
    codex_lower = codex_name.lower()

    for i, codex in enumerate(codices):
        if codex_lower in codex.get('name', '').lower() or codex_lower in codex.get('equation', '').lower():
            removed = codices.pop(i)
            _save_single_character(key, char, data)

            new_slots = _calculate_slots(char)
            return f"**{char['name']}** removed codex: {removed['name']} ({removed['equation']})\nSlots: {new_slots['total_used']}/{new_slots['capacity']}"

    return f"Codex '{codex_name}' not found on {char['name']}"


def _codex_use(
    character_name: str,
    codex_name: str
) -> str:
    """Attempt to use a codex. Returns INT save DC and outcomes. Call when character reads a codex. Nat 1 = mishap."""
    data, err = _load_characters()
    if err:
        return err

    key, char = _find_character(data, character_name)
    if not char:
        raise ToolError(f"Character '{character_name}' not found")

    # Check if can use codices
    if not char.get('can_use_codices', True):
        return f"**{char['name']}** cannot use codices until Long Rest (failed INT save earlier today)"

    codices = char.get('codices', [])
    codex_lower = codex_name.lower()

    for codex in codices:
        if codex_lower in codex.get('name', '').lower() or codex_lower in codex.get('equation', '').lower():
            int_stat = char.get('abilities', {}).get('INT', {})
            int_bonus = int_stat.get('current', 0) if isinstance(int_stat, dict) else int_stat

            output = [
                f"**{char['name']}** attempts to read: {codex['name']}",
                f"Equation: {codex['equation']}",
                "",
                f"**INT Save DC 15** (roll d20 + {int_bonus:+d})",
                "",
                "Outcomes:",
                f"  Success: {codex['effect'].replace('[INT]', f'[{int_bonus}]')}",
                "  Failure: Nothing happens, cannot read more codices until Long Rest",
                "  **Natural 1: MISHAP** - roll on Hypergeometric Mishap table"
                " — " + _pf.next_block(
                    _pf.push_call("codex", action="mishap_roll"),
                    label="mishap — only on nat 1",
                ),
                "",
                f"Power level: [INT] = {int_bonus}"
            ]

            return "\n".join(output)

    return f"Codex '{codex_name}' not found on {char['name']}"


# Book-certified d20 table (CH p.64, "Hypergeometric Mishaps" - verified against
# the extraction batch_04 2026-06-12; the previous table was largely invented,
# caught during the E4 roadmap audit). [INT] = the reader's INT score.
HYPERGEOMETRIC_MISHAPS = {
    1: {"name": "Antithesis", "effect": "Births a daemonic, insanely evil copy of the reader with their Level and HP, violently opposed to the reader's existence. Physical contact between the two destroys both explosively. The copy exists for [INT] combat rounds."},
    2: {"name": "Brainstorm", "effect": "The reader's muddled thoughts actualise as polychrome lightning pouring from their eyes and mouth. Everyone nearby takes 2d6 electrical damage, DEX save for half."},
    3: {"name": "Chromashadow", "effect": "The reader's shadow permanently shifts in hue, becoming pinkish-orange."},
    4: {"name": "Codex Collapse", "effect": "The hypergeometric codex collapses in on itself, vanishing from existence."},
    5: {"name": "Entropy-withered", "effect": "Entropic forces twist and decay the reader's body. They lose d6 maximum HP and cannot regain it."},
    6: {"name": "Giant Item", "effect": "An item in the reader's inventory becomes enormous: its weight in slots triples. Roll d10 to determine the slot affected. Permanent."},
    7: {"name": "Gigantism", "effect": "The reader's body grows uncontrollably, swelling to fill the room they are inside - other occupants must evacuate or be crushed (outdoors, they keep growing for the whole duration). Lasts [INT] hours, followed by a steady deflation."},
    8: {"name": "Inverted Anatomy", "effect": "The reader's internal organs are placed on the outside of their body and their clothing inside. AV becomes 10 and they take doubled damage from all sources. Lasts [INT] days."},
    9: {"name": "Inverted Fate", "effect": "The reader's destiny inverts: all failed Saves and attack rolls become successes and all successes become failures. Lasts [INT] days."},
    10: {"name": "Labyrinth Pox", "effect": 'The reader contracts Labyrinth Pox, a hypergeometric ailment. NEXT: affliction(kind="disease", action="apply", character="<reader>", disease="Labyrinth Pox")'},
    11: {"name": "Lost Past", "effect": "The reader permanently loses a chunk of their history: lose a single Level, subtract d8 from maximum HP, and reduce Ability scores by three points."},
    12: {"name": "Petrified", "effect": "The reader's body freezes under crushing hypergeometric force - unable to move or act for [INT] hours."},
    13: {"name": "Planeyfied", "effect": "The reader becomes a 2D hypergeometric being (use the Planeyfolk ancestry special rules). Lasts [INT] days."},
    14: {"name": "Quantum Daemon", "effect": "A paradoxical quantum daemon is called into existence. It is displeased about this and wishes the reader ill."},
    15: {"name": "Revelation", "effect": "The reader witnesses a terrible vista in a higher-order dimension, taking d6 damage to INT, PSY, and EGO."},
    16: {"name": "Shrunken Head", "effect": "The reader's head becomes minute (the body retains its size). Gain a Wound: Shrunken Head; lose d6 INT, PSY and EGO; helmets and hats can no longer be worn."},
    17: {"name": "Space-Time Vortex", "effect": "A mispronunciation ruptures space-time. The vortex vomits forth debris and living creatures: roll once on the local encounter table each combat round - the creature is ejected at high velocity along with rubble (DEX save to avoid)."},
    18: {"name": "Spirit Hand", "effect": "The reader's left hand is permanently drawn into an adjacent hypergeometric dimension - the arm ends in a strange blue fissure, the missing hand feels immersed in cold television static. Take d10 DEX damage. Unarmed attacks with the missing hand gain the hypergeometric damage property."},
    19: {"name": "The Yellow Door", "effect": "A locked yellow hypergeometric door develops in the reader's forehead. It cannot be opened. Permanent."},
    20: {"name": "Tiny Item", "effect": "An item in the reader's inventory becomes tiny and totally useless: its weight in slots drops to nothing. Roll d10 to determine the slot affected. Permanent."}
}


# ============================================================
# G2 -- HYPERGEOMETRIC EQUATIONS (CH printed pp.59-60; certified)
# Spec: docs/superpowers/specs/2026-06-13-g2-equations-design.md
# [INT] = the reader's INT bonus (substituted at read time by
# codex action="use"). R-G2a: the book's overlapping 43-45/44-46
# bands are even-split 43-44/45-46 (R-B3a precedent).
# Effects are DM-adjudicated prose -- no engine_effects.
# ============================================================

# CH printed p.57 -- the physical form every codex takes (d20).


# Book-certified d20 table (CH printed p.56, "Poison Generator" - transcribed from
# the PDF 2026-06-12, merged-cell bands verified from cell geometry; see
# docs/superpowers/specs/2026-06-12-b2-poisons-design.md). ONE d20 roll reads the
# whole row. engine_effects: R-B2a save fork - on a save (CON vs TN 15) the
# 'lesser' effect applies (None = no effect); on a failure the 'greater'.
# Rows 1-5 have save "none": the Toxin Die mechanic carries its own save.
VAARNISH_POISONS = {
    1:  {"colour": "Crimson", "form": "Liquid", "delivery": "Must be ingested",
         "effect_text": "d6 TOX damage",
         "engine_effects": {"save": "none", "lesser": None,
                            "greater": {"kind": "tox", "tox_die": "d6"}}},
    2:  {"colour": "Azure", "form": "Liquid", "delivery": "Must be ingested",
         "effect_text": "d8 TOX damage",
         "engine_effects": {"save": "none", "lesser": None,
                            "greater": {"kind": "tox", "tox_die": "d8"}}},
    3:  {"colour": "Ochre", "form": "Liquid", "delivery": "Must be ingested",
         "effect_text": "d10 TOX damage",
         "engine_effects": {"save": "none", "lesser": None,
                            "greater": {"kind": "tox", "tox_die": "d10"}}},
    4:  {"colour": "Ash-grey", "form": "Oil", "delivery": "Must be ingested",
         "effect_text": "d12 TOX damage",
         "engine_effects": {"save": "none", "lesser": None,
                            "greater": {"kind": "tox", "tox_die": "d12"}}},
    5:  {"colour": "Black", "form": "Oil", "delivery": "Must be ingested",
         "effect_text": "d20 TOX damage",
         "engine_effects": {"save": "none", "lesser": None,
                            "greater": {"kind": "tox", "tox_die": "d20"}}},
    6:  {"colour": "White", "form": "Oil", "delivery": "Must be ingested",
         "effect_text": "d4 STR loss / d10 STR loss",
         "engine_effects": {"save": "con_vs_15",
                            "lesser": {"kind": "ability_loss", "abilities": {"STR": "d4"}},
                            "greater": {"kind": "ability_loss", "abilities": {"STR": "d10"}}}},
    7:  {"colour": "Jade", "form": "Oil", "delivery": "Must be ingested",
         "effect_text": "d4 DEX loss / d10 DEX loss",
         "engine_effects": {"save": "con_vs_15",
                            "lesser": {"kind": "ability_loss", "abilities": {"DEX": "d4"}},
                            "greater": {"kind": "ability_loss", "abilities": {"DEX": "d10"}}}},
    8:  {"colour": "Golden", "form": "Powder", "delivery": "Must be ingested",
         "effect_text": "d4 CON loss / d10 CON loss",
         "engine_effects": {"save": "con_vs_15",
                            "lesser": {"kind": "ability_loss", "abilities": {"CON": "d4"}},
                            "greater": {"kind": "ability_loss", "abilities": {"CON": "d10"}}}},
    9:  {"colour": "Silver", "form": "Powder", "delivery": "Contact with skin",
         "effect_text": "d4 PSY loss / d10 PSY loss",
         "engine_effects": {"save": "con_vs_15",
                            "lesser": {"kind": "ability_loss", "abilities": {"PSY": "d4"}},
                            "greater": {"kind": "ability_loss", "abilities": {"PSY": "d10"}}}},
    10: {"colour": "Brassy", "form": "Powder", "delivery": "Contact with skin",
         "effect_text": "d4 EGO loss / d10 EGO loss",
         "engine_effects": {"save": "con_vs_15",
                            "lesser": {"kind": "ability_loss", "abilities": {"EGO": "d4"}},
                            "greater": {"kind": "ability_loss", "abilities": {"EGO": "d10"}}}},
    11: {"colour": "Colourless", "form": "Paste", "delivery": "Contact with skin",
         "effect_text": "Hallucinations for d6 days / d8 INT + PSY loss",
         "engine_effects": {"save": "con_vs_15",
                            "lesser": {"kind": "condition", "name": "Hallucinating",
                                       "duration_days_die": "d6"},
                            "greater": {"kind": "ability_loss",
                                        "abilities": {"INT": "d8", "PSY": "d8"},
                                        "single_roll": True}}},
    12: {"colour": "Pink", "form": "Paste", "delivery": "Airborne",
         "effect_text": "d6 INT loss / d10 INT loss",
         "engine_effects": {"save": "con_vs_15",
                            "lesser": {"kind": "ability_loss", "abilities": {"INT": "d6"}},
                            "greater": {"kind": "ability_loss", "abilities": {"INT": "d10"}}}},
    13: {"colour": "Indigo", "form": "Paste", "delivery": "Airborne",
         "effect_text": "d6 INT loss / Permanent loss of language",
         "engine_effects": {"save": "con_vs_15",
                            "lesser": {"kind": "ability_loss", "abilities": {"INT": "d6"}},
                            "greater": {"kind": "condition", "name": "Language Lost",
                                        "duration_days_die": None,
                                        "note": "permanent - cannot speak, read, or write any language (DM adjudicates scope)"}}},
    14: {"colour": "Purple", "form": "Sand", "delivery": "Coated on weapon",
         "effect_text": "Blindness for d8 days / Permanent blindness",
         "engine_effects": {"save": "con_vs_15",
                            "lesser": {"kind": "condition", "name": "Blinded",
                                       "duration_days_die": "d8"},
                            "greater": {"kind": "condition", "name": "Blinded",
                                        "duration_days_die": None,
                                        "note": "permanent blindness"}}},
    15: {"colour": "Iridescent", "form": "Glass", "delivery": "Coated on weapon",
         "effect_text": "Vomiting for d6 days, cannot eat to recover HP / Lose d12 CON",
         "engine_effects": {"save": "con_vs_15",
                            "lesser": {"kind": "condition", "name": "Vomiting",
                                       "duration_days_die": "d6",
                                       "note": "cannot eat to recover HP"},
                            "greater": {"kind": "ability_loss", "abilities": {"CON": "d12"}}}},
    16: {"colour": "Orange", "form": "Leaf", "delivery": "Coated on weapon",
         "effect_text": "Unable to use Mystic Gifts for d6 days",
         "engine_effects": {"save": "con_vs_15", "lesser": None,
                            "greater": {"kind": "condition", "name": "Gift-locked",
                                        "duration_days_die": "d6",
                                        "note": "unable to use Mystic Gifts"}}},
    17: {"colour": "Teal", "form": "Blood", "delivery": "Coated on weapon",
         "effect_text": "Paralysis for d6 days",
         "engine_effects": {"save": "con_vs_15", "lesser": None,
                            "greater": {"kind": "condition", "name": "Paralysed",
                                        "duration_days_die": "d6"}}},
    18: {"colour": "Brown", "form": "Crystal", "delivery": "Coated on weapon",
         "effect_text": "Must EGO save to refuse direct commands",
         "engine_effects": {"save": "con_vs_15", "lesser": None,
                            "greater": {"kind": "condition", "name": "Command Thrall",
                                        "duration_days_die": None,
                                        "note": "must EGO save to refuse direct commands; book gives no duration - DM adjudicates the cure"}}},
    19: {"colour": "Turquoise", "form": "Fungus",
         "delivery": "Harmless until mixed with catalyst",
         "effect_text": "Take double damage from all sources",
         "engine_effects": {"save": "con_vs_15", "lesser": None,
                            "greater": {"kind": "condition", "name": "Sundered Guard",
                                        "duration_days_die": None,
                                        "note": "takes double damage from all sources; book gives no duration - DM adjudicates the cure"}}},
    20: {"colour": "Octarine", "form": "Sugar",
         "delivery": "Harmless until mixed with catalyst",
         "effect_text": "Lose d8 Max HP / Death",
         "engine_effects": {"save": "con_vs_15",
                            "lesser": {"kind": "max_hp_loss", "die": "d8"},
                            "greater": {"kind": "death"}}},
}


# ============================================================
# B3 -- VAARNISH ELIXIRS (CH printed pp.53-54; certified table)
# Spec: docs/superpowers/specs/2026-06-13-b3-elixirs-design.md
# Rulings R-B3a (bands 43-44/45-46), R-B3b (Pupeteer 4 ET),
# R-B3c (Lazarus = E5 path 6), R-B3d (Immortality HP floor -19),
# R-B3e (Death Draught book-literal: 0 HP, wound fires).
# duration {"turns": N} = Exploration Turns (vault current_turn);
# {"days": 1} = until_day failsafe only. ET conditions ALWAYS also
# get a next-day until_day failsafe at apply time.
# ============================================================
VAARNISH_ELIXIRS = {
    1: {"d100": (1, 3), "name": "Babel Beer", "component": "A sapient creature's tongue", "pot": 1, "application": "drink",
        "effect_text": "Fleetingly understand and speak the languages known by the tongue's owner -- in the slurring, incoherent manner of one intoxicated.",
        "engine_effects": {"kind": "prose_only", "duration": None}},
    2: {"d100": (4, 6), "name": "Lumensoup", "component": "The fur of a Lambent Lynx", "pot": 1, "application": "drink",
        "effect_text": "Drinker's flesh begins to glow. Light source underground, but cannot hide. Lasts 8 Exploration Turns.",
        "engine_effects": {"kind": "condition", "duration": {"turns": 8},
                           "condition": {"name": "Glowing (Lumensoup)", "note": "light source; cannot hide"}}},
    3: {"d100": (7, 9), "name": "Oblivion Brew", "component": "A Memory Eater's stomach", "pot": 1, "application": "drink",
        "effect_text": "Drinker forgets the last hour of their life.",
        "engine_effects": {"kind": "prose_only", "duration": None}},
    4: {"d100": (10, 12), "name": "Glassflesh Paste", "component": "A Glass Tiger's skin", "pot": 1, "application": "topical",
        "effect_text": "Apply to flesh to become transparent for 4 Exploration Turns. Minimum damage from beam weapons.",
        "engine_effects": {"kind": "condition", "duration": {"turns": 4},
                           "condition": {"name": "Transparent (Glassflesh)", "note": "minimum damage from beam weapons"}}},
    5: {"d100": (13, 15), "name": "Fellowship Potion", "component": "A Psy-Owl's brain", "pot": 1, "application": "drink",
        "effect_text": "Drinker believes all nearby creatures to be their firm friends. Lasts a day, or until events force re-examination.",
        "engine_effects": {"kind": "prose_only", "duration": {"days": 1},
                           "condition": {"name": "Befriended Delusion (Fellowship)", "note": "believes all nearby creatures are firm friends"}}},
    6: {"d100": (16, 18), "name": "Greentongue Potion", "component": "A Neobloom's voxpod", "pot": 1, "application": "drink",
        "effect_text": "Understand and speak the slow tongue of plants. Allow one Exploration Turn per question. Lasts a day.",
        "engine_effects": {"kind": "prose_only", "duration": {"days": 1},
                           "condition": {"name": "Greentongue", "note": "speaks with plants; one Exploration Turn per question"}}},
    7: {"d100": (19, 21), "name": "False Death Draught", "component": "An Amaranthine Death-Worm's fangs", "pot": 1, "application": "drink",
        "effect_text": "Deathly paralysis. To all but the most advanced bio-scanners, drinker appears dead. Lasts 6 Exploration Turns.",
        "engine_effects": {"kind": "condition", "duration": {"turns": 6},
                           "condition": {"name": "False Death", "note": "paralysed; appears dead to all but advanced bio-scanners"}}},
    8: {"d100": (22, 24), "name": "Windsong Potion", "component": "A Windweird's larynx", "pot": 1, "application": "drink",
        "effect_text": "Sing to quiet or raise the winds; change the local weather at will. Lasts 6 Exploration Turns.",
        "engine_effects": {"kind": "condition", "duration": {"turns": 6},
                           "condition": {"name": "Windsong", "note": "may change local weather at will (weather marker is live -- DM applies)"}}},
    9: {"d100": (25, 27), "name": "Doppeldraught", "component": "The flesh of a Dopplegeller", "pot": 2, "application": "drink",
        "effect_text": "Vomit up a translucent, mute jelly-clone. Follows instructions; dissolves after 4 Exploration Turns.",
        "engine_effects": {"kind": "prose_only", "duration": {"turns": 4},
                           "condition": {"name": "Jelly-Clone Active (Doppeldraught)", "note": "clone follows instructions; dissolves at expiry"}}},
    10: {"d100": (28, 30), "name": "Spineskin Syrup", "component": "The quills of a Quill-Spider", "pot": 2, "application": "drink",
         "effect_text": "Explosive quill growth: +2 AV, destroys current clothing. Missed melee attacks against drinker deal d4. Quills shed after 4 Exploration Turns.",
         "engine_effects": {"kind": "av_bonus", "duration": {"turns": 4}, "av_bonus": 2,
                            "trigger": {"kind": "melee_missed", "die": "d4", "label": "Spineskin quills"},
                            "condition": {"name": "Spineskin Quills", "note": "+2 AV; missed melee vs drinker deals d4; clothing destroyed"}}},
    11: {"d100": (31, 33), "name": "Hilarious Strength", "component": "The tooth of a Harlequin Serpent", "pot": 2, "application": "drink",
         "effect_text": "+5 STR and -5 EGO. Uncontrollable laughter gives DIS on Encounter rolls. Lasts 4 Exploration Turns.",
         "engine_effects": {"kind": "ability_mod", "duration": {"turns": 4},
                            "mods": {"STR": 5, "EGO": -5},
                            "condition": {"name": "Hilarious Strength", "note": "+5 STR / -5 EGO; DIS on Encounter rolls (laughter)"}}},
    12: {"d100": (34, 36), "name": "Squishflesh Balm", "component": "A Squishwolf's skin", "pot": 2, "application": "topical",
         "effect_text": "Jellylike and flexible: DIS on physical Saves, fits narrow gaps, immune to crushing or fall damage. Lasts 4 Exploration Turns.",
         "engine_effects": {"kind": "condition", "duration": {"turns": 4},
                            "condition": {"name": "Squishflesh", "note": "DIS physical Saves; fits narrow gaps; immune crushing/fall",
                                          "effects": {"dis_saves": ["STR", "DEX", "CON"]}}}},
    13: {"d100": (37, 39), "name": "Metallovore Potion", "component": "A Yurling's stomach", "pot": 2, "application": "drink",
         "effect_text": "Eat and digest metal, which counts as a food ration. Lasts 6 Exploration Turns.",
         "engine_effects": {"kind": "prose_only", "duration": {"turns": 6},
                            "condition": {"name": "Metallovore", "note": "metal counts as a food ration"}}},
    14: {"d100": (40, 42), "name": "Plating Potion", "component": "A Plated Beetle's carapace", "pot": 2, "application": "drink",
         "effect_text": "+5 AV for 6 Exploration Turns.",
         "engine_effects": {"kind": "av_bonus", "duration": {"turns": 6}, "av_bonus": 5,
                            "condition": {"name": "Plated (Plating Potion)", "note": "+5 AV"}}},
    15: {"d100": (43, 44), "name": "Glittercough Tonic", "component": "Unicorn meat", "pot": 2, "application": "drink",
         "effect_text": "Excrete a cloud of glitter, forcing all targets to DEX Save vs Blindness for 4 rounds. (R-B3a band: 43-44.)",
         "engine_effects": {"kind": "save_fork", "duration": None,
                            "save": {"ability": "DEX"},
                            "on_fail": {"condition": {"name": "Blindness (glitter)", "note": "blinded 4 combat rounds"}},
                            "on_pass": None}},
    16: {"d100": (45, 46), "name": "Growth Serum", "component": "A Pseudo-Giant's pituatary gland", "pot": 2, "application": "drink",
         "effect_text": "Grow to double current size, doubling HP, STR, and CON. Lasts 4 Exploration Turns. (R-B3a band: 45-46.)",
         "engine_effects": {"kind": "ability_mod", "duration": {"turns": 4},
                            "double": ["hp", "STR", "CON"],
                            "condition": {"name": "Giant Growth (Growth Serum)", "note": "double size: HP/STR/CON doubled"}}},
    17: {"d100": (47, 50), "name": "Magnetic Stew", "component": "A Magneticrab's shell", "pot": 3, "application": "drink",
         "effect_text": "Powerfully magnetic; irresistibly draw metal objects toward yourself. Lasts 4 Exploration Turns.",
         "engine_effects": {"kind": "prose_only", "duration": {"turns": 4},
                            "condition": {"name": "Magnetic (Magnetic Stew)", "note": "irresistibly draws metal objects"}}},
    18: {"d100": (51, 53), "name": "Death Draught", "component": "An Amaranthine Death-Worm's fangs", "pot": 3, "application": "drink",
         "effect_text": "Drinker is immediately reduced to 0 HP.",
         "engine_effects": {"kind": "hp_set_zero", "duration": None}},
    19: {"d100": (54, 56), "name": "Pupeteer Potion", "component": "A Nerve-Crawler's core", "pot": 3, "application": "drink",
         "effect_text": "Extrude parasitic neural tissue bonding to another creature. Target must EGO Save or become your puppet. Lasts 4 Exploration Turns (R-B3b; book text cut off).",
         "engine_effects": {"kind": "save_fork", "duration": {"turns": 4},
                            "save": {"ability": "EGO"},
                            "on_fail": {"condition": {"name": "Puppeted (Pupeteer Potion)", "note": "under the drinker's control"}},
                            "on_pass": None}},
    20: {"d100": (57, 59), "name": "Fakeface Paste", "component": "The face of a Face Dancer", "pot": 3, "application": "topical",
         "effect_text": "Apply to your own face: Face Dancing -- take the form of any face you have observed. Convincing for one day.",
         "engine_effects": {"kind": "prose_only", "duration": {"days": 1},
                            "condition": {"name": "Face Dancing (Fakeface)", "note": "face mimics any observed face"}}},
    21: {"d100": (60, 61), "name": "Skulk Salve", "component": "The synth-skin of a Subtle Stalker", "pot": 3, "application": "topical",
         "effect_text": "Apply to flesh or objects: invisible to all spectrums of light for the next 4 Exploration Turns.",
         "engine_effects": {"kind": "condition", "duration": {"turns": 4},
                            "condition": {"name": "Invisible (Skulk Salve)", "note": "invisible to all light spectrums"}}},
    22: {"d100": (62, 63), "name": "Berserker Brew", "component": "A Cacklemaw's liver", "pot": 3, "application": "drink",
         "effect_text": "Battle frenzy: deal and receive double damage; must always attack the closest living being. EGO Save to exit the frenzy.",
         "engine_effects": {"kind": "condition", "duration": None,
                            "condition": {"name": "Berserk Frenzy (Berserker Brew)",
                                          "note": "deals AND receives double damage; must attack closest living being; condition save EGO to exit"}}},
    23: {"d100": (64, 65), "name": "Phasing Potion", "component": "A Phase Panther's heart", "pot": 3, "application": "drink",
         "effect_text": "Phase out of reality: incorporeal and invincible. Lasts 4 Exploration Turns.",
         "engine_effects": {"kind": "condition", "duration": {"turns": 4},
                            "condition": {"name": "Phased (Phasing Potion)", "note": "incorporeal and invincible"}}},
    24: {"d100": (66, 67), "name": "Lithification Syrup", "component": "A Lithling's crystalline flesh", "pot": 3, "application": "drink",
         "effect_text": "Flesh turns to living crystal: +5 AV and the Mineral creature type, including all damage immunities. Lasts 6 Exploration Turns.",
         "engine_effects": {"kind": "av_bonus", "duration": {"turns": 6}, "av_bonus": 5,
                            "condition": {"name": "Lithified (Lithification Syrup)",
                                          "note": "+5 AV; Mineral type incl. damage immunities (DM applies type rules)"}}},
    25: {"d100": (68, 69), "name": "Geneshock Tonic", "component": "The heart of a Cacogen", "pot": 4, "application": "drink",
         "effect_text": "Gain a new, PERMANENT mutation, matching that of the heart's original owner.",
         "engine_effects": {"kind": "sheet_surgery", "duration": None,
                            "surgery": "mutation",
                            "push": "Roll/choose the mutation matching the heart's owner; record it on the sheet via character(action=\"update_stat\") notes."}},
    26: {"d100": (70, 71), "name": "Regeneration Serum", "component": "The flesh of a Regenerator", "pot": 4, "application": "drink",
         "effect_text": "Regain d6 HP per combat round, unless damaged by fire or acid. Lasts 6 Exploration Turns.",
         "engine_effects": {"kind": "hp_regen", "duration": {"turns": 6}, "die": "d6",
                            "condition": {"name": "Regenerating (Regeneration Serum)",
                                          "note": "regain d6 HP per combat round; suppressed by fire/acid damage (DM judgment)"}}},
    27: {"d100": (72, 73), "name": "Obsession Philtre", "component": "The fang of a Gorgon", "pot": 4, "application": "drink",
         "effect_text": "Fall madly in love with the next character seen. Lasts as long as the love object stays in sight.",
         "engine_effects": {"kind": "prose_only", "duration": None,
                            "condition": {"name": "Obsessed (Obsession Philtre)", "note": "in love with the next character seen; ends when out of sight"}}},
    28: {"d100": (74, 75), "name": "Broodling Broth", "component": "The egg-sac of a Brood Mother", "pot": 4, "application": "drink",
         "effect_text": "Stomach distends; birth d6 Broodlings [Lvl 0 (1 hp), AV 12, Bite (d4)] -- somewhat like spiders, somewhat like their host. Loyal to their 'mother' until killed.",
         "engine_effects": {"kind": "follower_mint", "duration": None,
                            "mint": {"count_die": "d6", "name": "Broodling", "level": 0, "hp": 1, "av": 12, "attack": "Bite (d4)"}}},
    29: {"d100": (76, 77), "name": "Biothermal Amplifier Tonic", "component": "The chem glands of a Thermasaur", "pot": 4, "application": "drink",
         "effect_text": "Gain two Mystic Gifts: Pyrokinesis and Cyrokinesis. Immune to damage from extreme heat or cold. Lasts one day.",
         "engine_effects": {"kind": "gift_mint", "duration": {"days": 1},
                            "gifts": ["Pyrokinesis", "Cyrokinesis"], "permanent": False,
                            "condition": {"name": "Biothermal Amplifier", "note": "temporary Gifts Pyrokinesis+Cyrokinesis; immune extreme heat/cold; REMOVE gifts at expiry"}}},
    30: {"d100": (78, 79), "name": "Lazarus Tonic", "component": "The black heart of a Lazarus Guard", "pot": 4, "application": "drink",
         "effect_text": "A dead biological creature may be restored to life with this thick black tonic, at the cost of one Level.",
         "engine_effects": {"kind": "resurrection", "duration": None, "path": "lazarus_tonic"}},
    31: {"d100": (80, 81), "name": "Kalotoxin Injector", "component": "The stinger of a Kalopede", "pot": 4, "application": "inject",
         "effect_text": "Target is transformed into a work of Fine Art, with no Save possible.",
         "engine_effects": {"kind": "save_fork", "duration": None,
                            "save": None,
                            "on_fail": {"transformation_death": "transformed into a work of Fine Art (Kalotoxin)"},
                            "on_pass": None}},
    32: {"d100": (82, 83), "name": "Bifurcating Brew", "component": "The head of a Jollyhoss", "pot": 4, "application": "drink",
         "effect_text": "Split into two hypergeometric halves, each with half max HP, moving and acting independently. If one half dies, it resurrects with full HP while the other half lives. Lasts 4 Exploration Turns.",
         "engine_effects": {"kind": "prose_only", "duration": {"turns": 4},
                            "condition": {"name": "Bifurcated (Bifurcating Brew)", "note": "two hypergeometric halves, half max HP each; dead half resurrects while the other lives"}}},
    33: {"d100": (84, 85), "name": "Hollowheart Hooch", "component": "The heart of a Hollow Bride", "pot": 5, "application": "drink",
         "effect_text": "PERMANENTLY gain 2 new hypergeometric Item Slots inside your chest. Can exceed the 20-slot maximum.",
         "engine_effects": {"kind": "sheet_surgery", "duration": None,
                            "surgery": "bonus_slots", "amount": 2,
                            "push": "Add 2 to the sheet's bonus item slots (hypergeometric, chest)."}},
    34: {"d100": (86, 87), "name": "Autarch's Ambrosia", "component": "The preserved heart of an Autarch", "pot": 5, "application": "drink",
         "effect_text": "PERMANENTLY gain +1 to the Ability of your choice.",
         "engine_effects": {"kind": "sheet_surgery", "duration": None,
                            "surgery": "ability_plus_one",
                            "push": "Player chooses the Ability; apply +1 permanently via character(action=\"update_stat\")."}},
    35: {"d100": (88, 89), "name": "Metamorphic Syrup", "component": "The slurry of a Metamorphic Sludge", "pot": 5, "application": "drink",
         "effect_text": "PERMANENTLY changed into a new, random creature. Generate the body type using the monster generators (referee toolbox -- content-forge skill).",
         "engine_effects": {"kind": "prose_only", "duration": None,
                            "push": "Generate the new body with the content-forge monster generator; rebuild the sheet with the DM."}},
    36: {"d100": (90, 91), "name": "Cloning Jelly", "component": "The flesh of an Echopraxist", "pot": 5, "application": "topical",
         "effect_text": "Anything smeared with the gel is replicated perfectly, down to the smallest detail. The clone is a new permanent entity, not under the control of the original.",
         "engine_effects": {"kind": "prose_only", "duration": None}},
    37: {"d100": (92, 93), "name": "Transcendence Tonic", "component": "The brain of a Mystic", "pot": 5, "application": "drink",
         "effect_text": "Gain a new, PERMANENT Mystic Gift, matching that of the brain's original owner.",
         "engine_effects": {"kind": "gift_mint", "duration": None,
                            "gifts": ["(matches the brain's original owner -- DM names it)"], "permanent": True}},
    38: {"d100": (94, 95), "name": "Recursive Infusion", "component": "The eye of a Fractalisk", "pot": 5, "application": "drink",
         "effect_text": "Gain a new Mystic Gift: Recursive Gaze. A single target fixed with the Gaze must repeat the action they just took, no save allowed. Broken if the gaze is interrupted.",
         "engine_effects": {"kind": "gift_mint", "duration": None,
                            "gifts": ["Recursive Gaze"], "permanent": True}},
    39: {"d100": (96, 98), "name": "Planeyfication Potion", "component": "The heart of a Planeyperson", "pot": 5, "application": "drink",
         "effect_text": "PERMANENTLY become a hypergeometric entity. Gain the Hypergeometric creature type and follow the special rules for the Planeyfolk Ancestry.",
         "engine_effects": {"kind": "sheet_surgery", "duration": None,
                            "surgery": "creature_type", "new_type": "Hypergeometric",
                            "push": "Set the sheet's creature type to Hypergeometric; apply Planeyfolk ancestry special rules with the DM."}},
    40: {"d100": (99, 100), "name": "Immortality Injector", "component": "The mercurial war-flesh of a Quicksilver Exterminator", "pot": 5, "application": "inject",
         "effect_text": "Injected creature cannot die. It can be damaged beyond recognition, but the life will not leave its frame. Lasts one day.",
         "engine_effects": {"kind": "hp_floor", "duration": {"days": 1}, "floor": -19,
                            "condition": {"name": "Deathless (Immortality Injector)",
                                          "note": "R-B3d: damage cannot reduce HP below -19 while active"}}},
}


# ============================================================
# B4 -- VAARNISH DRUGS (CH printed p.45; certified table)
# Spec: docs/superpowers/specs/2026-06-13-b4-drugs-design.md
# Four INDEPENDENT d20 columns; the book's header reads
# "EFFECT (X2)" -- the effect column is rolled TWICE.
# R-B4a: CLOSED 2026-07-05 -- the full edition (CH 07-05-26 PDF, verified)
# ships NO addiction subsystem (addiction appears only as NPC-trait flavor).
# Drugs stay prose-only by the book: no usage mechanics, no engine_effects;
# effects are prose-only conditions applied via the condition tool.
# Any addiction mechanic would be homebrew requiring an explicit owner ruling.
# ============================================================


# ============================================================
# B5 -- ALCHEMY (CH printed pp.51-52). Reference build:
# rulings R-B5a (harvest DM-manual), R-B5b (brew reference-only),
# R-B5c (result = B3 table row OR custom). Spec:
# docs/superpowers/specs/2026-06-13-b5-alchemy-design.md
# d20 Crucible flavor (one roll each on quality + shape).
# ============================================================

ALCHEMY_REFERENCE_CARD = """**VAARNISH ALCHEMY** (CH pp.51-52)

**Crucible** -- the alchemist's primary tool: hollow, fire-proof,
corrosion-resistant; 1 item slot. Mint flavor: generate(action="crucible").

**Components** -- a body part harvested from a dead creature (eye, claw,
tongue, heart, liver...). ONE Component per creature; 1 item slot; do not
stack.

**Essences** -- generic ingredient types extracted from corpses. Doses = the
creature's Level; up to 10 of the same Essence stack per item slot. Type by
creature type:
  - Blood -- Biological
  - Blue Ikor (a coolant; the brewing example also calls it "Supercoolant"
    -- same substance) -- Synthetic (sometimes inside pre-Collapse computers)
  - Mycelium -- Fungal (also from non-sentient fungi)
  - Psychespinal Fluid -- Psychic
  - Manifold Marrow -- Hypergeometric
  - Living Dust -- Mineral
  - Paradox Bile -- Outsider
  Dual/multi-type creature: the PC chooses which Essence is extracted; the
  other potential dose is lost.

**Potency (POT 1-5, referee-set; most elixirs 1-3)** -- POT 1 = minor, like a
mundane item (vomit up a rope, briefly see in the dark). POT 3 = Exotica-grade
effect but not duration (teleport once, invisible for an hour). POT 5 =
permanent consequence (new body part or Mystic Gift, +1 ability, perfect
clone). The effect MUST tie to the nature of the creature the Component
derives from.

**Brewing** -- needs a heat source, a Crucible, and a receptacle. Takes POT
Exploration Turns and cannot be truncated; interruption spoils the elixir.
Ingredients = 1 Component (thematically tied to the intended effect) +
Essences equal to POT, and the Essences MUST be of different types
(a POT 3 = one dose each of e.g. Blood, Blue Ikor, Mycelium -- NOT three Blood).

**Drinking** -- Synthetic and Mineral PCs cannot drink elixirs.

**Antidotes** -- brew against a toxic creature's venom as the Component. The
antidote's POT = the toxin die rank: d6 TOX -> POT 1, d8 -> POT 2, d10 -> POT 3,
d12 -> POT 4, d20 -> POT 5.

**Brewed result (R-B5c):** the elixir is either a book "Example Elixir"
(generate(action="elixir") to roll one, or pick a row 1-40) or a custom elixir
designed at the table -- minted by hand as a dose item, then drunk via
character(action="drink_elixir"). Harvesting Components/Essences is DM-run
(add the items to the sheet in fiction). NOTE: drink_elixir lands with B3."""




def _lookup_alchemy() -> str:
    return ALCHEMY_REFERENCE_CARD


def _codex_mishap_roll() -> str:
    """Roll d20 on hypergeometric mishap table. Call after natural 1 on codex INT save."""
    roll = random.randint(1, 20)
    mishap = HYPERGEOMETRIC_MISHAPS.get(roll, {"name": "Unknown", "effect": "Referee determines effect"})

    return f"**HYPERGEOMETRIC MISHAP** (rolled {roll})\n\n**{mishap['name']}**\n{mishap['effect']}"


# ============================================
# PRIORITY 10: REST AND RECOVERY
# ============================================

def _get_present_characters() -> list[str]:
    """Read **Present:** field from CURRENT_STATUS.md and return character names."""
    status_path = CAMPAIGN_DIR / "CURRENT_STATUS.md"
    if not status_path.exists():
        return []
    try:
        content = status_path.read_text(encoding='utf-8')
        match = re.search(r'\*\*Present:\*\*\s*(.+?)(?:\n|$)', content)
        if match:
            return [name.strip() for name in match.group(1).split(',')]
    except Exception as e:
        logging.debug(f"Could not parse Present field from CURRENT_STATUS.md: {e}")
    return []


def _parse_character_list(characters: str) -> list[str]:
    """Parse character input: 'present' uses CURRENT_STATUS.md, otherwise comma-separated."""
    if characters.lower().strip() == 'present':
        return _get_present_characters()
    return [name.strip() for name in characters.split(',') if name.strip()]


@mcp.tool(tags=_get_tool_tags("rest"))
def rest(
    action: str = Field(description="short|long"),
    characters: str = Field(default=None, description="Names (comma-separated) or 'present'")
) -> str:
    """Reach for this WHEN the party takes a Short Rest (10-minute breather with rations — returns the d8+CON healing to roll, does not apply it) or a Long Rest (overnight sleep — restores full HP, or recovers abilities and offers a wound heal if already full); in field mode it consumes rations (short: 1 water-or-food; long: 1 water + 1 food — counting toward the day's need) and Deprived PCs regain no HP; does NOT advance the day counter or remove wounds directly (long rest output names the affliction(kind="wound", action="heal") call to make).

Rest and recovery.
    short: Calculate short rest healing (characters) | long: Full long rest with recovery (characters)"""
    action = action.lower().strip()
    if action == "short":
        if not characters:
            return "Error: 'characters' parameter required for short rest."
        _result = _rest_short_calculate(characters)
    elif action == "long":
        if not characters:
            return "Error: 'characters' parameter required for long rest."
        _result = _rest_long(characters)
    else:
        return f"Invalid action '{action}'. Valid actions: short, long"

    _emit_player_view()
    return _result


def _deprived_block_reason(char) -> str:
    """Why HP regain is blocked: a deprived wound record (Supercoolant Leak)
    or a Deprived condition (S1 thirst/starvation). Derived reads only."""
    for r in char.get('wounds', []) or []:
        if isinstance(r, dict) and r.get('deprived'):
            return f"{r.get('name', 'Supercoolant Leak')} - Deprived until fixed"
    eff = _sv.condition_effects(char.get('conditions', []))
    if eff["deprived"]:
        causes = "/".join(eff["deprived_causes"])
        return f"Deprived ({causes}) - eat/drink to recover"
    for c in char.get('conditions') or []:
        if isinstance(c, dict) and (c.get('effects') or {}).get('no_hp_regain'):
            return f"{c.get('name', 'Condition')} - no HP regain until cleared"
    return "Deprived"


def _rest_consume(char_names, data, water_each: int, food_each: int) -> list:
    """Field-mode rest consumption (R-S1c: counts toward the day via the
    ledger). Abundant mode: free, returns []. Returns output lines."""
    try:
        meta, sup, meta_path = _load_supply()
    except Exception:
        return []
    if sup.get("mode") != "field":
        return []
    lines = ["", "_Field rations consumed (count toward today):_"]
    pool = sup.get("pool") if isinstance(sup.get("pool"), dict) else None
    ledger = sup.setdefault("ledger", {"day": meta.get("campaign_day", 0), "consumed": {}})
    if ledger.get("day") != meta.get("campaign_day", 0):
        ledger["day"] = meta.get("campaign_day", 0)
        ledger["consumed"] = {}
    any_short = False
    for char_name in char_names:
        key, char = _find_character(data, char_name)
        if not char:
            continue
        needs = _sv.daily_needs(char)
        if not (needs["water"] or needs["food"]):
            continue  # exempt PCs rest for free
        _dbl = _sv.condition_effects(char.get("conditions") or [])["double_rations"]
        mult = 2 if (_dbl or any(_sv._has_tag(i, "parasitic")
                                 for i in _sv._iter_items(char))) else 1
        # I2: gate each need -- a needs_food=False PC pays no meal.
        want = {"water": (water_each * mult) if needs["water"] else 0,
                "food": (food_each * mult) if needs["food"] else 0}
        carried = [i for i in _sv._iter_items(char)
                   if isinstance(i, dict) and i.get("ration_type")]
        with_pool = key not in (sup.get("separated") or [])
        carried_before = [i.get("rations") for i in carried]
        short = _sv.consume_day(want, pool, carried, with_pool)
        if [i.get("rations") for i in carried] != carried_before:
            # C1: carried-ration mutations must persist to the sheet, or the
            # consumption rolls back on next load while the ledger credit
            # stands -- free rations. Saved BEFORE _save_supply (meta last).
            _save_single_character(key, char, data)
        got = {n: want[n] - short[n] for n in ("water", "food")}
        cred = ledger["consumed"].setdefault(key, {})
        for n in ("water", "food"):
            if got[n]:
                cred[n] = cred.get(n, 0) + got[n]
        if short["water"] or short["food"]:
            any_short = True
            short_line = (f"  {char.get('name', key)}: SHORT "
                          f"{short['food']}F/{short['water']}W - no ration available")
            if food_each == 0 and short["water"]:
                # Short Rest default is water-first, but the book allows food
                # instead -- name the alternative when food IS actually on hand.
                food_avail = (pool.get("food", 0) if (with_pool and pool) else 0) \
                    + sum(max(0, int(i.get("rations", 0))) for i in carried
                          if i.get("ration_type") == "food")
                if food_avail > 0:
                    short_line += (f" (book allows food instead: {food_avail} food "
                                   f"on hand - rule the ration as food or re-run "
                                   f"after supply(action=\"adjust\", water=...))")
            lines.append(short_line)
        else:
            lines.append(f"  {char.get('name', key)}: -"
                         + "/".join(f"{v}{n[0].upper()}" for n, v in got.items() if v))
    _save_supply(meta, meta_path)
    if any_short:
        lines.append(_pf.next_block(_pf.push_call("supply", action="status"),
                                    label="supply status"))
    return lines


def _rest_short_calculate(
    characters: str = Field(description="Names (comma-separated) or 'present'")
) -> str:
    """Calculate short rest healing (d8+CON). Use when party takes 10-minute rest with rations. Does not heal wounds."""
    char_names = _parse_character_list(characters)
    if not char_names:
        raise ToolError("No characters specified. Use comma-separated names or 'present'.")

    data, err = _load_characters()
    if err:
        return err

    results = []
    for char_name in char_names:
        key, char = _find_character(data, char_name)
        if not char:
            results.append(f"**{char_name}**: Not found")
            continue

        hp = char.get('hp', {})
        current = hp.get('current', 0)
        max_hp = hp.get('max', 0)

        con = char.get('abilities', {}).get('CON', {})
        con_bonus = con.get('current', 0) if isinstance(con, dict) else con

        if current >= max_hp:
            results.append(f"**{char['name']}**: Full HP ({current}/{max_hp}) - no healing needed")
        elif (_wnd.derived_effects(char.get('wounds', []))['no_hp_regain']
              or _sv.condition_effects(char.get('conditions', []))['no_hp_regain']):
            # Deprived (Supercoolant Leak or S1 thirst/starvation): cannot regain HP.
            results.append(f"**{char['name']}**: cannot regain HP "
                           f"({_deprived_block_reason(char)})")
        else:
            healing = f"d8 + {con_bonus}" if con_bonus >= 0 else f"d8 - {abs(con_bonus)}"
            if _sv.condition_effects(char.get('conditions', []))['hp_regain_half']:
                # E3 Janus Lenses: short-rest heal is halved too (round down,
                # min 1). Roll the d8 first, then HALVE the (d8 +/- CON) result.
                results.append(f"**{char['name']}**: {current}/{max_hp} HP -> "
                               f"heals HALF of ({healing}), round down, min 1 "
                               f"(Janus Lenses)")
            else:
                results.append(f"**{char['name']}**: {current}/{max_hp} HP -> heals {healing}")

    output = ["**SHORT REST CALCULATION**", ""]
    output.extend(results)
    output.append("")
    consume_lines = _rest_consume(char_names, data, 1, 0)
    if consume_lines:
        output.extend(consume_lines)
    else:
        output.append("_Requires: Food/water ration per character. Does NOT heal wounds._")

    return "\n".join(output)


def _rest_long(
    characters: str = Field(description="Names (comma-separated) or 'present'")
) -> str:
    """Apply long rest. Use after overnight sleep in safe location. Restores all HP, or heals 1 wound if HP full."""
    char_names = _parse_character_list(characters)
    if not char_names:
        raise ToolError("No characters specified. Use comma-separated names or 'present'.")

    data, err = _load_characters()
    if err:
        return err

    results = []
    wounds_to_heal = []  # Track characters with wounds to heal
    _heal_events = []  # mechanics-ticker pc_heal events (actual HP restored)

    for char_name in char_names:
        key, char = _find_character(data, char_name)
        if not char:
            results.append(f"**{char_name}**: Not found")
            continue

        hp = char.get('hp', {})
        current = hp.get('current', 0)
        max_hp = hp.get('max', 0)

        char_result = [f"**{char['name']}**:"]

        if current < max_hp:
            _cond_eff = _sv.condition_effects(char.get('conditions', []))
            if (_wnd.derived_effects(char.get('wounds', []))['no_hp_regain']
                    or _cond_eff['no_hp_regain']):
                # Deprived (Supercoolant Leak or S1 thirst/starvation): HP restore blocked.
                # no_hp_regain WINS over hp_regain_half when both are present.
                char_result.append(f"  HP: {current}/{max_hp} - cannot regain HP "
                                   f"({_deprived_block_reason(char)})")
            elif _cond_eff['hp_regain_half']:
                # E3 Janus Lenses: a Long Rest restores only HALF max HP (round
                # down, min 1 when any healing would occur).
                full = max_hp - current
                gain = max(1, full // 2)
                char['hp']['current'] = current + gain
                char_result.append(f"  HP: {current} -> {char['hp']['current']} "
                                   f"(half regain - Janus Lenses)")
                _heal_events.append({"kind": "pc_heal", "name": char['name'],
                                     "amount": gain, "old_hp": current,
                                     "new_hp": char['hp']['current'], "hp_max": max_hp})
            else:
                # Restore all HP
                char['hp']['current'] = max_hp
                char_result.append(f"  HP: {current} -> {max_hp}")
                _heal_events.append({"kind": "pc_heal", "name": char['name'],
                                     "amount": max_hp - current, "old_hp": current,
                                     "new_hp": max_hp, "hp_max": max_hp})
        else:
            char_result.append(f"  HP: Full ({max_hp}/{max_hp})")

            # Check for wounds
            wounds = char.get('wounds', [])
            if wounds:
                wound_names = [w.get('name', 'Unknown') for w in wounds]
                char_result.append(f"  Wounds: {', '.join(wound_names)} (choose one to heal)")
                wounds_to_heal.append((char['name'], wounds))

            # Check for damaged abilities
            abilities = char.get('abilities', {})
            for stat, data_stat in abilities.items():
                if isinstance(data_stat, dict):
                    current_val = data_stat.get('current', 0)
                    base_val = data_stat.get('base', current_val)
                    if current_val < base_val:
                        new_val = min(base_val, current_val + 1)
                        abilities[stat]['current'] = new_val
                        char_result.append(f"  {stat}: {current_val:+d} -> {new_val:+d}")

        # Reset codex usage
        char['can_use_codices'] = True
        char['last_rest_type'] = 'long'
        char['last_rest_day'] = data.get('meta', {}).get('campaign_day', 87)

        results.append("\n".join(char_result))

    _save_characters(data)

    output = [f"**LONG REST** ({len(char_names)} characters)", ""]
    output.extend(results)
    output.append("")
    output.append("_All codex usage reset._")

    consume_lines = _rest_consume(char_names, data, 1, 1)
    if consume_lines:
        output.extend(consume_lines)
    else:
        output.append("_Requires: Food/water ration per character. Does NOT heal wounds._")

    if wounds_to_heal:
        output.append("")
        output.append("**Wounds available to heal (one per character at full HP):**")
        for name, wounds in wounds_to_heal:
            for w in wounds:
                wound_name = w.get('name', 'Unknown')
                # PUSH rule: name the exact call, never just describe it.
                # Double quotes inside the call: wound names carry apostrophes
                # ("Death's Door") -- the U2 depletables line set this pattern.
                output.append(
                    f'  - {name}: {wound_name} ({w.get("effect", "")}) '
                    f'-> affliction(kind="wound", action="heal", character="{name}", wound="{wound_name}")')

    return _mt.append_ticker("\n".join(output), _heal_events)


# ============================================
# S1 SURVIVAL & SUPPLY (spec: docs/superpowers/specs/2026-06-10-survival-supply-design.md)
# ============================================

_DEFAULT_SUPPLY = {"mode": "abundant", "pool": None, "pool_location": "",
                   "follower_mouths": 0, "separated": [],
                   "ledger": {"day": 0, "consumed": {}}}


def _load_supply():
    """(_meta dict, supply dict, meta_path). Creates the default supply record
    in memory when absent — callers persist via _save_supply."""
    meta_path = CAMPAIGN_DIR / "characters" / "_meta.json"
    with open(meta_path, 'r', encoding='utf-8') as f:
        meta = json.load(f)
    supply = meta.get("supply")
    if not isinstance(supply, dict):
        supply = json.loads(json.dumps(_DEFAULT_SUPPLY))
        meta["supply"] = supply
    return meta, supply, meta_path


def _save_supply(meta, meta_path):
    _atomic_json_write(meta_path, meta)


def _photosynthesis_window() -> int:
    """Photosynthesis window in days, read from the photosynthetic PC's sheet
    (survival.photosynthesis_window_days; a graft/augment can extend the
    book value). Book default 3 when no sheet declares one."""
    try:
        data, err = _load_characters()
        if not err and data:
            for char in data.get("characters", {}).values():
                blk = char.get("survival") or {}
                if "photosynthesis_window_days" in blk:
                    return int(blk["photosynthesis_window_days"])
    except Exception:
        pass
    return 3


# --- S2 Foraging plumbing (spec docs/superpowers/specs/2026-06-11-foraging-design.md) ---

def _get_rulebook_table(table_id, section="rolling"):
    """Fetch a table dict from the rulebook cache by id. section: rolling|reference."""
    cache = (rulebook_system._cache or {})
    for t in cache.get("tables", {}).get(section, []):
        if isinstance(t, dict) and t.get("id") == table_id:
            return t
    return None


def _table_entry_for(table, n):
    """Find the entry matching roll n -- entries carry int rolls or 'A-B' ranges."""
    for e in table.get("entries", []):
        r = e.get("roll")
        if isinstance(r, int) and r == n:
            return e
        if isinstance(r, str) and "-" in r:
            lo, _, hi = r.partition("-")
            try:
                if int(lo) <= n <= int(hi):
                    return e
            except ValueError:
                continue
    return None


def _forage_roll(notation):
    """All forage dice route through here (tests monkeypatch this)."""
    return dice.roll_notation(notation)["total"]


_CACHE_LINE_RX = re.compile(r"^(\d*)[dD](\d+)\s+(.+)$")


def _roll_cache_line(line):
    """Roll the leading dice of a cache content line.
    '2d6 Water Rations' -> ('2d6 Water Rations [=7]', 7, 'water').
    Lines without leading dice render as-is with kind None."""
    m = _CACHE_LINE_RX.match(line.strip())
    if not m:
        return line.strip(), 0, None
    expr = f"{m.group(1) or ''}d{m.group(2)}"
    total = _forage_roll(expr)
    low = m.group(3).lower()
    kind = ("water" if "water ration" in low
            else "food" if "food ration" in low else None)
    return f"{line.strip()} [={total}]", total, kind


def _supply_status_lines(supply, data):
    """Human-readable status: mode, pool + days-at-burn, per-PC deprivation."""
    lines = [f"**SUPPLY** — mode: {supply['mode']}"]
    chars = (data or {}).get('characters', {})
    if supply["mode"] == "abundant":
        lines.append("At an earned base — supply is not tracked here.")
    burn = {"water": 0, "food": 0}
    deprived_lines = []
    carried_parts = []
    for key, char in chars.items():
        needs = _sv.daily_needs(char)
        burn["water"] += needs["water"]; burn["food"] += needs["food"]
        eff = _sv.condition_effects(char.get("conditions", []))
        for cause, death_day in eff["dying"]:
            deprived_lines.append(
                f"  DEPRIVED: {char.get('name', key)} ({cause}) — no healing; "
                f"dies Day {death_day} without relief")
        if char.get("type") != "vehicle":
            # Spec §6: per-PC carried counts — in carried-only (early-game)
            # mode this is the only supply picture the DM has.  Every PC is
            # listed (a zero-needs PC can still carry rations for others).
            rats = {"water": 0, "food": 0}
            for i in _sv._iter_items(char):
                if isinstance(i, dict) and i.get("ration_type") in rats:
                    rats[i["ration_type"]] += max(0, int(i.get("rations", 0)))
            carried_parts.append(
                f"{char.get('name', key)} {rats['food']}F/{rats['water']}W")
    burn["water"] += supply.get("follower_mouths", 0)
    burn["food"] += supply.get("follower_mouths", 0)
    pool = supply.get("pool")
    if supply["mode"] == "field" and isinstance(pool, dict):
        # I1: pool burn reporting is field-only — at an abundant base the
        # stores still exist but consumption is not tracked.
        days = min(
            (pool.get(n, 0) // burn[n]) if burn[n] else 999 for n in ("water", "food"))
        lines.append(f"Pool ({supply.get('pool_location') or 'party stores'}): "
                     f"{pool.get('food', 0)} food, {pool.get('water', 0)} water "
                     f"(~{days} day(s) at current burn: {burn['food']}F/{burn['water']}W per day)")
    elif supply["mode"] == "field":
        lines.append(f"No party pool (no earned base) — carried rations only. "
                     f"Daily burn: {burn['food']}F/{burn['water']}W.")
    if supply["mode"] == "field" and carried_parts:
        lines.append("Carried: " + " · ".join(carried_parts))
    if supply.get("separated"):
        # I2: render sheet display names, not raw file-stem keys
        sep_names = ', '.join(chars.get(k, {}).get('name', k)
                              for k in supply['separated'])
        lines.append(f"Separated from pool: {sep_names}")
    lines.extend(deprived_lines)
    return lines


WORLD_TICK_RETURN_DAYS = 7  # R-WT1 default; Joe-tunable


@mcp.tool(tags=_get_tool_tags("supply"))
def supply(
    action: str = Field(description="status|depart|arrive|forage|adjust|separate|rejoin|photosynthesis"),
    food: int = Field(default=None, description="depart: pool food count; adjust: +/- food"),
    water: int = Field(default=None, description="depart: pool water count; adjust: +/- water"),
    follower_mouths: int = Field(default=None, description="depart/adjust: follower+mercenary mouths (1 food + 1 water each/day)"),
    character: str = Field(default=None, description="separate/rejoin: one name; adjust: credit/debit THIS pack; forage: comma-separated forager names"),
    location: str = Field(default="", description="arrive: where the party arrived (stamps last-visited for the world-tick return check)"),
    last_fed_day: int = Field(default=None, description="photosynthesis: the day the photosynthetic PC last fed on sunlight"),
    current_day: int = Field(default=None, description="photosynthesis: current campaign day (defaults to today)"),
) -> str:
    """Reach for this WHEN the party leaves or returns to a supplied base, buys/finds/loses rations, spends a stay-put day foraging, a PC splits from the group, a Neobloom PC feeds on sunlight (photosynthesis timer), or you need the food-water-deprivation picture — supply(action="status") any time; depart/arrive toggle field-mode daily consumption on advance_day; forage rolls the book's d100 per forager and suggests the credit calls.

    Survival & Supply levers (S1+S2). status | depart (enter field mode; pass pool counts if a base is earned) | arrive (back to abundance) | forage (comma-separated names in 'character'; field mode only) | adjust (+/- pool, or +/- a named PC's carried rations via 'character') | separate/rejoin (cut a PC off from / return them to the pool) | photosynthesis (Neobloom PCs: reset the sunlight-feeding timer; last_fed_day required)."""
    # Normalize FieldInfo objects to None when called directly in tests (not via FastMCP router)
    from pydantic.fields import FieldInfo as _FieldInfo
    if isinstance(food, _FieldInfo): food = None
    if isinstance(water, _FieldInfo): water = None
    if isinstance(follower_mouths, _FieldInfo): follower_mouths = None
    if isinstance(character, _FieldInfo): character = None
    if isinstance(location, _FieldInfo): location = ""
    if isinstance(last_fed_day, _FieldInfo): last_fed_day = None
    if isinstance(current_day, _FieldInfo): current_day = None
    action = (action or "").lower().strip()
    data, err = _load_characters()
    if err:
        return err
    meta, sup, meta_path = _load_supply()

    if action == "status":
        return "\n".join(_supply_status_lines(sup, data))

    if action == "photosynthesis":
        if last_fed_day is None:
            return "Invalid action 'photosynthesis': requires last_fed_day"
        return _update_photosynthesis_impl(last_fed_day=last_fed_day, current_day=current_day)

    if action == "depart":
        sup["mode"] = "field"
        zero_notes = []
        if food is not None or water is not None:
            sup["pool"] = {"food": int(food or 0), "water": int(water or 0)}
            # M1: be loud about a key we defaulted to 0, not silent
            if food is None:
                zero_notes.append('NOTE: food set to 0 (not provided) — '
                                  'supply(action="adjust", food=N) to correct')
            if water is None:
                zero_notes.append('NOTE: water set to 0 (not provided) — '
                                  'supply(action="adjust", water=N) to correct')
        if follower_mouths is not None:
            sup["follower_mouths"] = int(follower_mouths)
        sup["ledger"] = {"day": meta.get("campaign_day", 0), "consumed": {}}
        _save_supply(meta, meta_path)
        out = ["Supply tracking is LIVE (field mode)."]
        out.extend(zero_notes)
        out.extend(_supply_status_lines(sup, data))
        out.append(_pf.next_block(_pf.push_call("supply", action="status"),
                                  label="supply check any time"))
        return "\n".join(out)

    if action == "arrive":
        sup["mode"] = "abundant"
        # R-S1a: home base = unfettered water/food access — arriving IS
        # eating and drinking, so Deprived records clear here (the field
        # tick can no longer clear them once abundant mode skips it).
        # R-E1c: photosynthesis-Deprived does NOT clear here - walking indoors
        # is not sunlight; only update_photosynthesis (feeding) clears it.
        recovered = []
        for k, char in data.get('characters', {}).items():
            hp_d = char.get('hp')
            if isinstance(hp_d, dict) and hp_d.get('current', 0) <= -20:
                # Tombstone convention (matches the tick's corpse skip): a dead
                # PC's Deprived records persist until resurrection tooling clears them.
                continue
            conds = char.get('conditions') or []
            cleared = [c.get('cause', '?') for c in conds
                       if isinstance(c, dict) and c.get('name') == 'Deprived'
                       and c.get('cause') != 'photosynthesis']
            if not cleared:
                continue
            char['conditions'] = [c for c in conds
                                  if not (isinstance(c, dict)
                                          and c.get('name') == 'Deprived'
                                          and c.get('cause') != 'photosynthesis')]
            # sheets-first, meta-last persistence order
            _save_single_character(k, char, data)
            recovered.append(f"{char.get('name', k)} ({', '.join(cleared)})")
        sup["ledger"] = {"day": meta.get("campaign_day", 0), "consumed": {}}
        _save_supply(meta, meta_path)
        out = ["Arrived at base — supply tracking is OFF (abundant)."]
        if recovered:
            out.append("Recovered from Deprived (home supply): "
                       + "; ".join(recovered))
        # World tick (Task 3): stamp last_visited; on return after absence,
        # push the book's settlement-changes roll. Stamping must NEVER fail
        # an arrive - the whole block is fail-soft.
        if location and isinstance(location, str) and location.strip():
            try:
                key = location.lower().strip()
                # Day from the SAME meta the ledger line above uses, so
                # ledger and stamp can never disagree. Guard: a missing/
                # zero campaign day must not clobber a real stamp with 0
                # (the next true arrival would fire a spurious
                # whole-campaign-gap push) - skip stamping entirely.
                current = int(meta.get("campaign_day") or 0)
                if current > 0:
                    visited = (GAME_STATE.setdefault("world_tick", {})
                               .setdefault("last_visited", {}))
                    prior = visited.get(key)
                    if (isinstance(prior, int)
                            and current - prior >= WORLD_TICK_RETURN_DAYS):
                        gap = current - prior
                        # Gnomon's bespoke changes table is a d6; the
                        # generic settlement-changes table is a d20.
                        if key == "gnomon":
                            table_id, die = "table-changes-in-gnomon", "d6"
                        else:
                            table_id, die = "table-settlement-changes", "d20"
                        out.append(
                            f"**{location.strip()} has had {gap} days "
                            f"without you.** Roll what changed (book: "
                            f"settlement changes):")
                        out.append(_pf.next_block(
                            _pf.push_call("rulebook", action="get",
                                          id=table_id,
                                          roll=_pf.raw(f"<{die}>")),
                            label=f"roll {die}, then narrate the change "
                                  "in-fiction"))
                    # ALWAYS re-stamp (when the day is real), hit or miss
                    visited[key] = current
                    _save_game_state()
            except Exception as _wte:
                out.append(f"WARNING: world-tick stamp skipped ({_wte})")
        # The book's ONLY advancement loop lives at the settlement (CH p.28,
        # p.133): traded Exotica = 1 XP each; carousing = +1 XP + a d20+EGO
        # mishap. Surface it every arrival so a fresh DM-model never runs a
        # whole settlement visit without the nudge. Fail-soft, push-only.
        out.append("**Advancement is on offer here** (book: trade Exotica for XP, then carouse):")
        out.append(_pf.next_block(
            _pf.push_call("character", action="gain_xp",
                          name=_pf.raw('"<PC>"'), amount=1,
                          reason=_pf.raw('"traded 1 Exotica"')),
            label="each Exotica a PC trades in = 1 XP"))
        out.append(_pf.next_block(
            _pf.push_call("rulebook", action="get", id="table-carousing",
                          roll=_pf.raw("<d20+EGO>")),
            label="if a PC carouses: award +1 XP (gain_xp) then roll this mishap"))
        return "\n".join(out)

    if action == "forage":
        # Book pp.137-138: stay put for the day; each assigned forager rolls
        # d100 on the Desert Foraging table. Engine rolls + suggests credits;
        # the DM confirms by running the pushed adjust calls (R-S2a).
        if sup["mode"] != "field":
            return ("Foraging is a field activity -- at an earned base supply "
                    "is not tracked.\n"
                    + _pf.next_block(_pf.push_call("supply", action="depart"),
                                     label="leave base first"))
        if not character:
            return "Error: 'character' required for forage (comma-separated forager names)."
        table = _get_rulebook_table("table-desert-foraging")
        if table is None:
            return "Error: table-desert-foraging not found in rulebook tables."
        names = []
        for n in (p.strip() for p in character.split(",")):
            if not n:
                continue
            _k, ch = _find_character(data, n)
            if not ch:
                return f"Character '{n}' not found."
            if ch.get("type") == "vehicle":
                return (f"'{ch.get('name', n)}' is a vehicle -- it can't forage. "
                        "Name living PCs only.")
            hp_d = ch.get("hp")
            if isinstance(hp_d, dict) and hp_d.get("current", 0) <= -20:
                return (f"'{ch.get('name', n)}' is dead -- the dead don't forage. "
                        "Name living PCs only.")
            names.append(ch.get("name", n))
        groups = {}  # d100 result -> [forager names] (duplicates = shared discovery)
        for n in names:
            groups.setdefault(_forage_roll("d100"), []).append(n)
        out = [f"**FORAGING** -- {len(names)} forager(s), stay-put day"]
        credits = []  # (forager, water, food)
        for r in sorted(groups):
            who = groups[r]
            label = " & ".join(who) + (" -- shared discovery" if len(who) > 1 else "")
            entry = _table_entry_for(table, r)
            if entry is None:
                out.append(f"[{r:02d}] {label}: (no table entry -- check the data)")
                continue
            text = entry.get("result", "")
            y = entry.get("yield")
            cache = entry.get("cache")
            if y:
                res = _sv.resolve_yield(y, _forage_roll)
                out.append(f"[{r:02d}] {label}: {text}")
                if res["detail"]:
                    out.append("      rolled: " + ", ".join(res["detail"]))
                credits.append((who[0], res["water"], res["food"]))
            elif cache:
                out.append(f"[{r:02d}] {label}: {text}")
                ct = _get_rulebook_table("table-treasure-cache-survival",
                                         section="reference")
                row = None
                if ct:
                    row = next((e for e in ct.get("entries", [])
                                if e.get("size") == cache), None)
                if row is None:
                    out.append(f"      ({cache} cache contents table missing -- DM rules it)")
                else:
                    w = f = 0
                    for line in row.get("contents", []):
                        rendered, amt, kind = _roll_cache_line(line)
                        out.append(f"      - {rendered}")
                        if kind == "water":
                            w += amt
                        elif kind == "food":
                            f += amt
                    if w or f:
                        credits.append((who[0], w, f))
            else:
                # Scene/encounter/nothing: present with prose dice rolled; the
                # absence of a credit call IS the "DM rules this" signal.
                out.append(f"[{r:02d}] {label}: {_sv.roll_dice_in_text(text, _forage_roll)}")
        push_calls = []
        for n, w, f in credits:
            kw = {"action": "adjust", "character": n}
            if w:
                kw["water"] = w
            if f:
                kw["food"] = f
            push_calls.append(_pf.push_call("supply", **kw))
        if push_calls:
            out.append(_pf.next_block(*push_calls,
                                      label="credit the finds (DM confirms; shared finds: split as you rule)"))
        out.append("Reminder: a stay-put day still gets your travel-day encounter check (d6).")
        return "\n".join(out)

    if action == "adjust":
        if food is None and water is None and follower_mouths is None and not character:
            # M2: a no-op adjust is a status read — never mint a pool from nothing
            return "\n".join(_supply_status_lines(sup, data))
        if character:
            # R-S2b: found/bought rations land as carried items in a named pack.
            k, ch = _find_character(data, character)
            if not ch:
                return f"Character '{character}' not found."
            if ch.get("type") == "vehicle":
                return (f"'{ch.get('name', character)}' is a vehicle — vehicles don't eat "
                        "and the daily tick skips them (rations stored there would vanish "
                        "from play accounting). Credit a PC's pack instead:\n"
                        + _pf.next_block(
                            _pf.push_call("supply", action="adjust", character="<PC name>",
                                          water=int(water or 0), food=int(food or 0)),
                            label="carried credit"))
            hp_d = ch.get("hp")
            corpse_note = None
            if isinstance(hp_d, dict) and hp_d.get("current", 0) <= -20:
                corpse_note = (f"  NOTE: {ch.get('name', character)} is dead — these rations "
                               "won't be consumed by the daily tick; transfer them to a living "
                               "PC to count.")
            notes = _sv.adjust_carried(ch, water=int(water or 0), food=int(food or 0))
            _save_single_character(k, ch, data)
            if follower_mouths is not None:
                sup["follower_mouths"] = int(follower_mouths)
                _save_supply(meta, meta_path)
            slots = _calculate_slots(ch)
            out = [f"**{ch.get('name', character)}** carried rations adjusted:"]
            out.extend(f"  {n}" for n in notes)
            out.append(f"  Slots: {slots['total_used']}/{slots['capacity']}")
            if corpse_note:
                out.append(corpse_note)
            return "\n".join(out)
        if not isinstance(sup.get("pool"), dict):
            # R-S1b: the pool exists only once a base is EARNED — never mint one
            # from an adjust. Rations found in the field live in someone's pack.
            return ("No party pool exists (a pool comes with an earned base — R-S1b). "
                    "Credit a pack instead:\n"
                    + _pf.next_block(
                        _pf.push_call("supply", action="adjust", character="<name>",
                                      water=int(water or 0), food=int(food or 0)),
                        label="carried credit"))
        sup["pool"]["food"] = max(0, sup["pool"].get("food", 0) + int(food or 0))
        sup["pool"]["water"] = max(0, sup["pool"].get("water", 0) + int(water or 0))
        if follower_mouths is not None:
            sup["follower_mouths"] = int(follower_mouths)
        _save_supply(meta, meta_path)
        return "\n".join(_supply_status_lines(sup, data))

    if action in ("separate", "rejoin"):
        if not character:
            return "Error: 'character' required for separate/rejoin."
        key, char = _find_character(data, character)
        if not char:
            return f"Character '{character}' not found."
        sep = sup.setdefault("separated", [])
        if action == "separate" and key not in sep:
            sep.append(key)
        if action == "rejoin" and key in sep:
            sep.remove(key)
        _save_supply(meta, meta_path)
        return f"{char['name']} {'separated from' if action == 'separate' else 'rejoined'} the party pool.\n" + \
               "\n".join(_supply_status_lines(sup, data))

    return f"Invalid action '{action}'. Valid: status, depart, arrive, adjust, separate, rejoin, forage, photosynthesis"


# ============================================
# CONDITION TOOL (E1 Persistent Status Framework)
# ============================================


def _clear_infection_markers(char, names):
    """Remove INFECTION: markers from char['augmentations'] for any cleared
    nanomachine condition whose name is in `names`. A marker is a dict with
    infection==True; we match on the disease name embedded in the marker. Returns
    the list of (slot, disease) pairs cleared (for surfacing). No-op when the
    sheet has no infection markers, so it is safe to call unconditionally."""
    augs = char.get("augmentations")
    if not isinstance(augs, dict):
        return []
    wanted = {str(n).strip().lower() for n in (names or []) if n}
    cleared = []
    for slot, aug in list(augs.items()):
        if not isinstance(aug, dict) or not aug.get("infection"):
            continue
        dis = str(aug.get("disease") or aug.get("name") or "").lower()
        if any(w and w in dis for w in wanted):
            augs[slot] = None
            cleared.append((slot, aug.get("disease") or aug.get("name")))
    return cleared


def _revival_cleanup(char):
    """The revival lever (book p.229): strip all conditions + infection markers +
    the twinning death-pending mark. Mirrors the condition clear-all branch inline
    trio but does NOT save (the resolve caller saves once after all surgery).
    Calling the condition() tool here would re-enter the tool layer -- forbidden."""
    conds = char.get("conditions") or []
    _clear_infection_markers(char, [c.get("name") for c in conds if isinstance(c, dict)])
    char["conditions"] = []
    char.pop("twinning_pending", None)
    # a stale spirit block (a spirit-pass PC later revived by another path)
    # must not haunt the living sheet
    char.pop("spirit", None)


def _condition_impl(
    action: str = Field(description="apply|clear|status|save"),
    character: str = Field(default=None, description="Character name (apply/clear/save)"),
    name: str = Field(default=None, description="Condition name (e.g. Burning, Twinning, Jellybones)"),
    cause: str = Field(default=None, description="apply: short cause/source text"),
    note: str = Field(default=None, description="apply: prose rider the ENGINE CANNOT enforce - the DM rules it"),
    no_hp_regain: bool = Field(default=False, description="apply: block HP regain from Rests (the Deprived effect)"),
    dis_saves: str = Field(default=None, description="apply: comma-separated abilities with DIS on saves, e.g. 'DEX,CON'"),
    tick_cadence: str = Field(default=None, description="apply: round|day|week - when the tick fires"),
    tick_hp: str = Field(default=None, description="apply: HP damage dice per tick, e.g. 'd8' (Burning)"),
    tick_abilities: str = Field(default=None, description='apply: JSON ability drain per tick, e.g. {"STR": "d4", "CON": "d4"}'),
    save_ability: str = Field(default=None, description="apply: save-to-end ability (with save_dc)"),
    save_dc: int = Field(default=None, description="apply: save-to-end target number (disease: 10 + Virulence)"),
    twin_partner: str = Field(default=None, description="apply: Twinning - the quantum-bonded partner's name (stamp BOTH sheets)"),
    death_day: int = Field(default=None, description="apply: campaign day the condition kills (death clock)"),
    save_total: int = Field(default=None, description="save: the player's rolled save total"),
    all_conditions: bool = Field(default=False, description="clear: remove EVERY condition on the character (revival cleanup)"),
) -> str:
    """Reach for this WHEN a persistent condition starts or ends on a PC - a curse, Burning, disease, a quantum bond - or the player rolls a save-to-end, or you need the party-wide condition picture; the engine remembers, ticks, and enforces what it can (do NOT hand-track these).

    E1 persistent status framework. apply (structured effects the engine ENFORCES: no_hp_regain, dis_saves, day/week/round tick drains, death_day clock, save-to-end, Twinning death bond; 'note' carries everything else for the DM to rule) | clear (one name, or all_conditions=True - the revival-cleanup lever; clearing is also how Burning is extinguished) | status (party-wide) | save (resolve a save-to-end with the player's roll: pass clears). Engine-owned conditions: Deprived (supply/photosynthesis ticks mint and clear it) - do not hand-apply those."""
    # FieldInfo normalization (the supply() pattern) so direct test calls work
    from pydantic.fields import FieldInfo as _FieldInfo
    if isinstance(character, _FieldInfo): character = None
    if isinstance(name, _FieldInfo): name = None
    if isinstance(cause, _FieldInfo): cause = None
    if isinstance(note, _FieldInfo): note = None
    if isinstance(no_hp_regain, _FieldInfo): no_hp_regain = False
    if isinstance(dis_saves, _FieldInfo): dis_saves = None
    if isinstance(tick_cadence, _FieldInfo): tick_cadence = None
    if isinstance(tick_hp, _FieldInfo): tick_hp = None
    if isinstance(tick_abilities, _FieldInfo): tick_abilities = None
    if isinstance(save_ability, _FieldInfo): save_ability = None
    if isinstance(save_dc, _FieldInfo): save_dc = None
    if isinstance(twin_partner, _FieldInfo): twin_partner = None
    if isinstance(death_day, _FieldInfo): death_day = None
    if isinstance(save_total, _FieldInfo): save_total = None
    if isinstance(all_conditions, _FieldInfo): all_conditions = False
    action = (action or "").strip().lower()
    data, err = _load_characters()
    if err:
        return err

    if action == "status":
        lines = ["**CONDITIONS** (E1 - engine-enforced where structured)"]
        any_active = False
        # _load_characters() already carries _meta.json - no second file read
        cur_day = data.get("meta", {}).get("campaign_day")
        for k, ch in data.get("characters", {}).items():
            if ch.get("type") == "vehicle":
                continue
            conds = [c for c in ch.get("conditions") or [] if isinstance(c, dict)]
            if not conds:
                continue
            any_active = True
            lines.append(f"  {ch.get('name', k)}:")
            for c in conds:
                bits = [c.get("name", "?")]
                if c.get("cause"):
                    bits.append(f"({c['cause']})")
                if isinstance(c.get("death_day"), int):
                    dd = c["death_day"]
                    if isinstance(cur_day, int):
                        bits.append(f"- DIES Day {dd} (in {dd - cur_day} day(s))")
                    else:
                        bits.append(f"- DIES Day {dd}")
                t = c.get("tick") or {}
                if t:
                    drain = (t.get("hp")
                             or (f"{t['max_hp']} max HP" if t.get("max_hp") else "")
                             or "/".join(
                                 f"{a} {d}" for a, d in (t.get("abilities") or {}).items()))
                    bits.append(f"- {drain} per {t.get('cadence')}")
                ste = c.get("save_to_end") or {}
                if ste:
                    bits.append(f"- save to end: {ste.get('ability')} vs {ste.get('dc')} "
                                f'-> affliction(kind="condition", action="save", character="{ch.get("name", k)}", '
                                f'name="{c.get("name")}", save_total=<roll>)')
                if c.get("note"):
                    bits.append(f"[DM rules: {c['note']}]")
                lines.append("    " + " ".join(bits))
            if ch.get("twinning_pending"):
                lines.append(f"    DEATH PENDING this window "
                             f"({ch['twinning_pending'].get('window')}) - if the "
                             f"twin falls too, both die.")
        if not any_active:
            return "No active conditions on any PC."
        return "\n".join(lines)

    if not character:
        return f"Action '{action}' requires character."
    key, char = _find_character(data, character)
    if not char:
        return f"No character named '{character}'."
    cname = char.get("name", key)
    if char.get("type") == "vehicle":
        return (f"'{cname}' is a vehicle - conditions ride on living PCs. "
                f"Name a character.")
    corpse_note = ""
    hp_d = char.get("hp")
    if isinstance(hp_d, dict) and hp_d.get("current", 0) <= -20:
        corpse_note = (f"\nNOTE: {cname} is DEAD - conditions on a corpse are "
                       f"tombstone records (revival cleanup clears them).")

    if action == "apply":
        req = {"name": name, "cause": cause, "note": note, "death_day": death_day}
        eff = {}
        if no_hp_regain:
            eff["no_hp_regain"] = True
        if dis_saves:
            eff["dis_saves"] = [s for s in
                                (p.strip() for p in dis_saves.split(",")) if s]
        if twin_partner:
            eff["twinned"] = {"partner": twin_partner}
        if eff:
            req["effects"] = eff
        if tick_cadence or tick_hp or tick_abilities:
            t = {"cadence": tick_cadence, "hp": tick_hp}
            if tick_abilities:
                try:
                    t["abilities"] = json.loads(tick_abilities)
                except (ValueError, TypeError):
                    return ('tick_abilities must be JSON like '
                            '{"STR": "d4", "CON": "d4"}.')
            req["tick"] = {k: v for k, v in t.items() if v}
        if save_ability or save_dc is not None:
            req["save_to_end"] = {"ability": save_ability, "dc": save_dc}
        # _load_characters() already carries _meta.json - no second file read
        day = data.get("meta", {}).get("campaign_day") or 0
        rec, rerr = _cnd.normalize_record(req, day=day)
        if rerr:
            return f"Cannot apply: {rerr}"
        conds = char.setdefault("conditions", [])
        if any(isinstance(c, dict) and str(c.get("name", "")).lower()
               == rec["name"].lower() for c in conds):
            return (f"{cname} already has '{rec['name']}' - clear it first to "
                    f"re-apply with new terms.")
        conds.append(rec)
        _save_single_character(key, char, data)
        out = [f"**{cname}: {rec['name']} applied** (since Day {rec['since_day']})."]
        enforced = []
        e = rec.get("effects") or {}
        if e.get("no_hp_regain"):
            enforced.append("no HP regain from Rests")
        if e.get("dis_saves"):
            enforced.append(f"DIS on {'/'.join(e['dis_saves'])} saves")
        if e.get("twinned"):
            enforced.append(f"cannot die unless {e['twinned']['partner']} falls "
                            f"in the same round/blast/day (the bond must be "
                            f"mutual - stamp the partner's sheet too: "
                            + _pf.push_call("affliction", kind="condition", action="apply",
                                            character=e["twinned"]["partner"],
                                            name=rec["name"],
                                            twin_partner=cname) + ")")
        t = rec.get("tick") or {}
        if t:
            drain = t.get("hp") or ", ".join(
                f"{a} -{d}" for a, d in (t.get("abilities") or {}).items())
            enforced.append(f"{drain} per {t['cadence']} (engine-rolled)")
        if rec.get("death_day") is not None:
            enforced.append(f"death clock Day {rec['death_day']}")
        if rec.get("save_to_end"):
            enforced.append(f"save to end {rec['save_to_end']['ability']} vs "
                            f"{rec['save_to_end']['dc']} (player rolls) -> "
                            + _pf.push_call("affliction", kind="condition", action="save",
                                            character=cname, name=rec["name"],
                                            save_total=_pf.raw("<roll>")))
        out.append("Engine enforces: " + ("; ".join(enforced) if enforced
                                          else "nothing structured"))
        if rec.get("note"):
            out.append(f"DM rules (prose): {rec['note']}")
        if corpse_note:
            out.append(corpse_note.strip())
        return _mt.append_ticker(
            "\n".join(o for o in out if o),
            [{"kind": "condition", "name": cname, "condition": rec["name"], "applied": True}])

    if action == "clear":
        conds = [c for c in char.get("conditions") or [] if isinstance(c, dict)]
        if all_conditions:
            if not conds:
                return f"{cname} has no conditions."
            cleared = ", ".join(c.get("name", "?") for c in conds)
            _clear_infection_markers(char, [c.get("name") for c in conds])
            char["conditions"] = []
            char.pop("twinning_pending", None)
            _save_single_character(key, char, data)
            _cleared_names = [c.get("name", "?") for c in conds]
            return _mt.append_ticker(
                (f"**{cname}: ALL conditions cleared** ({cleared}).\n"
                 f"Revival per the book is means-specific (p.229 - spores/"
                 f"necrotech/pseudo-womb/spirit/ego-engine): set HP per the "
                 f"means used. If a Twinning bond was cleared, clear the "
                 f"partner's record too.{corpse_note}"),
                [{"kind": "condition", "name": cname, "condition": _cn, "applied": False}
                 for _cn in _cleared_names])
        if not name:
            return "action='clear' requires name (or all_conditions=True)."
        needle = name.strip().lower()
        matches = [c for c in conds if needle in str(c.get("name", "")).lower()]
        if not matches:
            opts = ", ".join(c.get("name", "?") for c in conds) or "none"
            return f"No condition matching '{name}' on {cname}. Active: {opts}."
        # Ambiguity guard (mirrors wound heal): duplicate apply is refused,
        # so distinct names in the match set means the substring is ambiguous.
        match_names = {str(c.get("name", "")).lower() for c in matches}
        if len(match_names) > 1:
            opts = ", ".join(c.get("name", "?") for c in matches)
            return (f"'{name}' is ambiguous on {cname} - matches: {opts}. "
                    f"Be more specific.")
        char["conditions"] = [c for c in char.get("conditions") or []
                              if c not in matches]
        _clear_infection_markers(char, [c.get("name") for c in matches])
        extra = ""
        if any((c.get("effects") or {}).get("twinned") for c in matches):
            extra = (" Twinning is mutual - clear the partner's record too or "
                     "the gate treats the leftover as severed anyway.")
            # E1: the death-pending mark rides on the bond - pop it with it
            if char.pop("twinning_pending", None) is not None:
                extra += " (Death-pending mark popped with the bond.)"
        _save_single_character(key, char, data)
        return _mt.append_ticker(
            f"**{cname}: {matches[0].get('name')} cleared.**{extra}{corpse_note}",
            [{"kind": "condition", "name": cname,
              "condition": matches[0].get('name'), "applied": False}])

    if action == "save":
        if not name or save_total is None:
            return "action='save' requires name and save_total (the player's roll)."
        conds = [c for c in char.get("conditions") or [] if isinstance(c, dict)]
        needle = name.strip().lower()
        rec = next((c for c in conds
                    if needle in str(c.get("name", "")).lower()
                    and c.get("save_to_end")), None)
        if not rec:
            return f"No save-to-end condition matching '{name}' on {cname}."
        ste = rec["save_to_end"]
        if int(save_total) >= int(ste["dc"]):
            char["conditions"] = [c for c in char.get("conditions") or []
                                  if c is not rec]
            # E3: a cured nanomachine infection frees its augmentation slot(s)
            _clear_infection_markers(char, [rec.get("name")])
            _save_single_character(key, char, data)
            return _mt.append_ticker(
                (f"**{cname}: {rec['name']} save PASS** ({save_total} vs "
                 f"{ste['dc']}) - condition CLEARED."),
                [{"kind": "condition", "name": cname, "condition": rec['name'], "applied": False}])
        return (f"**{cname}: {rec['name']} save FAIL** ({save_total} vs "
                f"{ste['dc']}) - the condition holds.")

    return f"Unknown action '{action}'. Use apply|clear|status|save."


def _disease_impl(
    action: str = Field(description="apply|expose|list|info"),
    character: str = Field(default=None, description="Character name (apply/expose)"),
    disease: str = Field(default=None, description="Disease name (apply/expose/info). Organic: Brain Coral, Wrathworms, Jellybones, Hivey Hump, Labyrinth Pox, Lumenrot. Nanomachine: Goldencough, Janus Lenses, Usurper Arm, Dreamcage, Fabricator Stoma, The Gitch"),
    force: bool = Field(default=False, description="apply: override Synth/Lithling immunity (the 'unless otherwise noted' cases)"),
    save_total: int = Field(default=None, description="apply: the player's rolled resist-save total; >= TN (10+Virulence) resists and nothing is applied"),
    odds: str = Field(default=None, description="expose: contraction odds like '1-in-6' or '1-in-10'; omit to go straight to the resist-save push"),
) -> str:
    """Reach for this WHEN a PC is exposed to or contracts a Vaarnish disease (six organic) or nanomachine infection (six synthetic) - a bite, infected water, swarming Sable Bees, hypergeometric contact, a Maladaptor's touch, Gitch-dust - to roll the contraction odds, resolve the resist save, and mint the right condition with its engine-enforced progression. Status/save/clear live on the condition tool; this tool's output pushes you there.

    E2 organic diseases (CH pp.228-229) + E3 nanomachine infections (pp.230-231). apply (immunity check -> duplicate check -> optional resist save vs TN 10+Virulence with save_total; mints the condition record with the progression tick and the cure save-to-end) | expose (DM lever: roll the contraction odds, then push the resist-save apply call) | list (browse all twelve: V, TN, effects) | info (one disease in full: symptoms, cure, vector). IMMUNITY: Synths and Lithlings are immune to ORGANIC diseases only (force=True overrides); nanomachine infections infect ALL creature types - synthetic/augmented bodies resist WITH DIS instead. Nanomachine infections also OCCUPY ability slots, destroying any cybernetic implant there (install blocked until cured). Transformation endpoints (EGO/CON/PSY to 0, Pox max-HP 0, Gitch slots full) are death-equivalent and route through the gated death seam during advance_day."""
    from pydantic.fields import FieldInfo as _FieldInfo
    if isinstance(action, _FieldInfo): action = ""
    if isinstance(character, _FieldInfo): character = None
    if isinstance(disease, _FieldInfo): disease = None
    if isinstance(force, _FieldInfo): force = False
    if isinstance(save_total, _FieldInfo): save_total = None
    if isinstance(odds, _FieldInfo): odds = None
    action = (action or "").strip().lower()

    if action == "list":
        lines = ["**DISEASES** (CH pp.228-231 - six organic + six nanomachine)"]
        for nm in sorted(_dz.DISEASES):
            d = _dz.DISEASES[nm]
            tick = d.get("tick") or {}
            if tick:
                drain = tick.get("hp") or tick.get("max_hp") or ", ".join(
                    f"{a} -{v}" for a, v in (tick.get("abilities") or {}).items())
                if tick.get("max_hp"):
                    drain = f"-{tick['max_hp']} max HP"
                if d.get("gitch") and not drain:
                    drain = "crystal fills an item slot (+1 AV, -1 rolled ability)"
                eff = f"{drain} per {tick.get('cadence')}"
                if tick.get("save"):
                    eff += f" (save {tick['save']['ability']} vs {tick['save']['dc']} to avoid)"
            elif d.get("on_apply"):
                eff = "one-time on-apply trade"
            else:
                eff = "no engine tick (prose rider)"
            lines.append(f"  {nm} - Virulence {d['virulence']}, save TN {d['tn']} - {eff}")
        lines.append('NEXT (one disease in full): affliction(kind="disease", action="info", disease="<name>")')
        return "\n".join(lines)

    if action == "info":
        if not disease:
            return 'action="info" needs disease=<name>. Try affliction(kind="disease", action="list").'
        d = _dz.DISEASES.get(disease)
        if d is None:
            opts = ", ".join(sorted(_dz.DISEASES))
            return f"Unknown disease '{disease}'. Known: {opts}."
        lines = [f"**{disease}** (Virulence {d['virulence']}, save TN {d['tn']} to "
                 f"resist AND treat)",
                 f"Symptoms: {d['symptoms']}",
                 f"Cure: {d['cure']}",
                 f"Vector: {d['vector']}"]
        if d.get("rider"):
            lines.append(f"DM rider: {d['rider']}")
        if d.get("transformation"):
            lines.append(f"Endpoint: {d['transformation']}")
        if d.get("stages"):
            lines.append(f"Stages: {d['stages']}")
        lines.append(_pf.next_block(
            _pf.push_call("affliction", kind="disease", action="apply",
                          character=_pf.raw('"<PC>"'), disease=disease),
            label="infect a PC"))
        return "\n".join(lines)

    # apply / expose both need a living, non-vehicle character
    if not character:
        return f"Action '{action}' requires character."
    data, err = _load_characters()
    if err:
        return err
    key, char = _find_character(data, character)
    if not char:
        return f"No character named '{character}'."
    cname = char.get("name", key)
    if char.get("type") == "vehicle":
        return (f"'{cname}' is a vehicle - diseases ride on living PCs. "
                f"Name a character.")
    corpse_note = ""
    hp_d = char.get("hp")
    if isinstance(hp_d, dict) and hp_d.get("current", 0) <= -20:
        corpse_note = (f"\nNOTE: {cname} is DEAD - disease records on a corpse "
                       f"are tombstone records (revival cleanup clears them).")
    if not disease:
        return f"Action '{action}' requires disease=<name>. Try affliction(kind=\"disease\", action=\"list\")."

    if action == "expose":
        d = _dz.DISEASES.get(disease)
        if d is None:
            opts = ", ".join(sorted(_dz.DISEASES))
            return f"Unknown disease '{disease}'. Known: {opts}."
        # odds parsing: 'N-in-M' -> exposed when a 1..M roll lands <= N
        if odds:
            import re as _re
            m = _re.match(r"\s*(\d+)\s*-?\s*in\s*-?\s*(\d+)\s*$", str(odds).lower())
            if not m:
                return ("odds must look like '1-in-6' or '1-in-10' (or omit it "
                        "to go straight to the resist-save push).")
            n, total = int(m.group(1)), int(m.group(2))
            if total < 1 or n < 1 or n > total:
                return f"odds '{odds}' is out of range (need 1 <= N <= M)."
            roll = dice.roll_notation(f"d{total}")["total"]
            if roll > n:
                return (f"**{cname} vs {disease} exposure ({n}-in-{total}):** "
                        f"rolled {roll} - no exposure this time.")
            head = (f"**{cname} EXPOSED to {disease} ({n}-in-{total}, rolled "
                    f"{roll}).**")
        else:
            head = f"**{cname} EXPOSED to {disease}** (DM-called)."
        tn = d["tn"]
        dis_line = ""
        if d.get("family") == "nanomachine" and _dz.nano_resist_dis(char):
            dis_line = ("\nSAVE WITH DIS (roll twice, take the lower) - "
                        f"{cname} is augmented/synthetic; nanomachines infect "
                        "all bodies but augmented ones resist at Disadvantage.")
        return (f"{head}\nResist save: CON save vs TN {tn} (10 + Virulence "
                f"{d['virulence']}). Roll it, then apply with the total - on a "
                f"miss the disease takes hold.{dis_line}\n" + _pf.next_block(
                    _pf.push_call("affliction", kind="disease", action="apply", character=cname,
                                  disease=disease,
                                  save_total=_pf.raw("<resist total>")),
                    label="resolve the resist save") + corpse_note)

    if action == "apply":
        d = _dz.DISEASES.get(disease)
        if d is None:
            opts = ", ".join(sorted(_dz.DISEASES))
            return f"Unknown disease '{disease}'. Known: {opts}."
        # immunity (Synth/Lithling, ORGANIC family only) unless force -
        # nanomachine infections infect all creature types (book p.230)
        if not force and not _dz.disease_susceptible_pc(
                char, family=d.get("family", "organic")):
            return (f"{cname} is immune to {disease} (Synth/Lithling). Use "
                    f"force=True for an 'otherwise noted' exception.")
        # resist save (player-rolled for at-the-table exposure)
        if save_total is not None:
            if int(save_total) >= d["tn"]:
                return (f"**{cname} RESISTED {disease}** ({save_total} vs TN "
                        f"{d['tn']}) - nothing applied.")
        # duplicate check
        conds = char.setdefault("conditions", [])
        if any(isinstance(c, dict) and str(c.get("name", "")).lower()
               == disease.lower() for c in conds):
            return (f"{cname} already has {disease} - clear it first "
                    f'(affliction(kind="condition", action="clear", character="{cname}", '
                    f'name="{disease}")) to re-apply.')
        day = data.get("meta", {}).get("campaign_day") or 0
        rec, push, berr = _dz.build_disease_record(disease, day=day)
        if berr:
            return berr
        conds.append(rec)
        out = [f"**{cname} contracts {disease}** (since Day {rec['since_day']})."]
        out.extend(push)
        # E3: nanomachine slot occupancy - the infection occupies its ability
        # slot(s), overwriting any pre-existing implant (book pp.236-237). The
        # Gitch's slot was rolled into rec["tick"]["abilities"] by the builder.
        if d.get("family") == "nanomachine":
            slot_spec = d.get("slots")
            if slot_spec == "d6":
                target_slots = list((rec.get("tick", {})
                                     .get("abilities") or {}).keys())
            else:
                target_slots = list(slot_spec or [])
            augs = char.setdefault("augmentations", {})
            day_now = rec.get("since_day", day)
            for slot in target_slots:
                existing = augs.get(slot)
                if isinstance(existing, dict) and not existing.get("infection"):
                    # destroy the implant: reverse its APPLIED stat delta (C20:
                    # shared with _cybernetic_remove, so a capped bonus never
                    # over-reverses), then report the loss.
                    _legacy = cyber_gifts._reverse_implant_stat_bonus(char, existing)
                    out.append(f"  {slot} slot: implant "
                               f"'{existing.get('name', 'Unknown')}' is "
                               f"OVERWRITTEN - gone.")
                    if _legacy:
                        out.append(f"  {cyber_gifts._LEGACY_IMPLANT_NOTICE}")
                elif isinstance(existing, list):
                    # destroy every implant in the list: reverse each member's
                    # APPLIED delta (mirrors _cybernetic_remove's list branch, C20).
                    _legacy = False
                    for a in existing:
                        if isinstance(a, dict):
                            _legacy = cyber_gifts._reverse_implant_stat_bonus(char, a) or _legacy
                    if _legacy:
                        out.append(f"  {cyber_gifts._LEGACY_IMPLANT_NOTICE}")
                    out.append(f"  {slot} slot: implants "
                               f"{', '.join(a.get('name', '?') for a in existing if isinstance(a, dict))}"
                               f" are OVERWRITTEN - gone.")
                augs[slot] = {"name": f"INFECTION: {disease}",
                              "infection": True, "disease": disease,
                              "day_installed": day_now}
            if target_slots:
                out.append(f"  Occupies ability slot(s): "
                           f"{', '.join(target_slots)} (cure first to free them).")
            if _dz.nano_resist_dis(char):
                out.append("  Note: resist saves for this body are at DIS (roll twice, "
                           "take lower) - augmented/synthetic per pp.236-237.")
        # on-apply roll: gated ability path for the loss; optional gain side
        # (Brain Coral trades STR for PSY; Goldencough just loses CON)
        trade = d.get("on_apply")
        if trade:
            rolled = dice.roll_notation(trade["roll"])["total"]
            down = trade["ability_down"]
            up = trade.get("ability_up")
            out.append(f"On-apply ({trade['roll']} = {rolled}):")
            out.extend(_apply_ability_damage_from_wound(char, {down: rolled}))
            t_dead, t_reason, t_glines = _check_death_gated(
                key, char, data, window_key=f"day:{day}")
            out.extend(t_glines)
            if t_dead:
                if isinstance(char.get("hp"), dict):
                    char["hp"]["current"] = -20
                out.append(f"!!! {t_reason} !!!")
                out.extend(_death_seam_lines(char, data, key))
            elif up:
                ab = char.setdefault("abilities", {})
                slot = ab.setdefault(up, {"current": 0, "base": 0})
                if isinstance(slot, dict):
                    slot["current"] = slot.get("current", 0) + rolled
                else:
                    ab[up] = slot + rolled
                out.append(f"  {up}: +{rolled} (gained)")
        _save_single_character(key, char, data)
        # engine-enforced summary
        enforced = []
        t = rec.get("tick") or {}
        if t:
            drain = t.get("hp") or t.get("max_hp") or ", ".join(
                f"{a} -{v}" for a, v in (t.get("abilities") or {}).items())
            if t.get("max_hp"):
                drain = f"-{t['max_hp']} max HP"
            seg = f"{drain} per {t['cadence']} (engine-rolled)"
            if t.get("save"):
                seg += (f", gated on a {t['save']['ability']} save vs "
                        f"{t['save']['dc']} (miss = drain)")
            enforced.append(seg)
        if rec.get("on_max_hp_zero"):
            enforced.append(f"at 0 max HP: vanish in "
                            f"{rec['on_max_hp_zero']['death_in_days']} days (gated death)")
        enforced.append(f"cure save to end: CON vs {d['tn']} (player rolls)")
        out.append("Engine enforces: " + "; ".join(enforced))
        if rec.get("note"):
            out.append(f"DM rules (prose): {rec['note']}")
        out.append(_pf.next_block(
            _pf.push_call("affliction", kind="condition", action="status"),
            _pf.push_call("affliction", kind="condition", action="save", character=cname,
                          name=disease, save_total=_pf.raw("<cure roll>")),
            label="track / treat"))
        return _mt.append_ticker(
            "\n".join(o for o in out if o) + corpse_note,
            [{"kind": "condition", "name": cname, "condition": disease, "applied": True}])

    return f"Unknown action '{action}'. Use apply|expose|list|info."

@mcp.tool(tags=_get_tool_tags("affliction"))
def affliction(
    kind: str = Field(description="condition|disease|toxin|wound"),
    action: str = Field(description="the kind's action -- condition:apply|clear|status|save * disease:apply|expose|list|info * toxin:status|check|resolve|tick|cure|poison_apply|poison_resolve|poison_coat * wound:status|heal|ko_save|wake"),
    character: str = Field(default=None, description="PC name (most actions)"),
    name: str = Field(default=None, description="condition: condition name (Burning, Twinning, Jellybones)"),
    cause: str = Field(default=None, description="condition apply: short cause/source text"),
    note: str = Field(default=None, description="condition apply: DM-ruled prose rider the engine cannot enforce"),
    no_hp_regain: bool = Field(default=False, description="condition apply: block HP regain from Rests (Deprived)"),
    dis_saves: str = Field(default=None, description="condition apply: comma-separated abilities with DIS on saves"),
    tick_cadence: str = Field(default=None, description="condition apply: round|day|week"),
    tick_hp: str = Field(default=None, description="condition apply: HP damage dice per tick, e.g. 'd8'"),
    tick_abilities: str = Field(default=None, description="condition apply: JSON ability drain per tick"),
    save_ability: str = Field(default=None, description="condition apply: save-to-end ability (with save_dc)"),
    save_dc: int = Field(default=None, description="condition/disease apply: save-to-end target (disease 10+Virulence)"),
    twin_partner: str = Field(default=None, description="condition apply: Twinning quantum-bonded partner name"),
    death_day: int = Field(default=None, description="condition apply: campaign day the condition kills"),
    save_total: int = Field(default=None, description="condition/disease/toxin: the player's rolled save total"),
    all_conditions: bool = Field(default=False, description="condition clear: remove EVERY condition (revival cleanup)"),
    disease: str = Field(default=None, description="disease: disease/infection name (apply/expose/info)"),
    force: bool = Field(default=False, description="disease apply: override Synth/Lithling immunity"),
    odds: str = Field(default=None, description="disease expose: contraction odds like '1-in-6'"),
    target: str = Field(default=None, description="toxin: PC name or enemy descriptor"),
    tox_die: str = Field(default=None, description="toxin check/resolve: TOX die e.g. 'd8'"),
    full: bool = Field(default=False, description="toxin cure: clear entirely instead of stepping down a rung"),
    poison: Optional[str] = Field(default=None, description="toxin poison_*: generator row 1-20 or inline JSON record"),
    weapon: Optional[str] = Field(default=None, description="toxin poison_coat: weapon name on the PC's sheet"),
    wound: str = Field(default=None, description="wound heal: the wound name to remove (substring match)"),
    result: str = Field(default=None, description="wound ko_save: 'pass' or 'fail'"),
) -> str:
    """Reach for this WHEN any affliction starts, ticks, resolves, or ends on a combatant --
    a status condition, a disease/infection, a poison/Toxin Die, or a physical wound.

    kind='condition' -- persistent status (apply|clear|status|save). E1 framework.
    kind='disease'   -- organic disease / nanomachine infection (apply|expose|list|info). E2/E3.
    kind='toxin'     -- Toxin Die + Vaarnish poison (status|check|resolve|tick|cure|poison_apply|poison_resolve|poison_coat). B2.
    kind='wound'     -- wound state outside the damage path (status|heal|ko_save|wake).
    """
    # FieldInfo normalization (the supply()/condition() pattern) so direct calls work for
    # every kind. condition/disease self-normalize downstream; toxin/wound do not, so the
    # public affliction entry normalizes the params they receive.
    from pydantic.fields import FieldInfo as _FieldInfo
    def _nz(v, d=None):
        return d if isinstance(v, _FieldInfo) else v
    kind = _nz(kind, ""); action = _nz(action, ""); character = _nz(character)
    target = _nz(target); tox_die = _nz(tox_die); save_total = _nz(save_total)
    full = _nz(full, False); poison = _nz(poison); weapon = _nz(weapon)
    wound = _nz(wound); result = _nz(result)
    k = (kind or "").strip().lower()
    if k == "condition":
        return _condition_impl(action=action, character=character, name=name, cause=cause,
            note=note, no_hp_regain=no_hp_regain, dis_saves=dis_saves, tick_cadence=tick_cadence,
            tick_hp=tick_hp, tick_abilities=tick_abilities, save_ability=save_ability, save_dc=save_dc,
            twin_partner=twin_partner, death_day=death_day, save_total=save_total, all_conditions=all_conditions)
    if k == "disease":
        return _disease_impl(action=action, character=character, disease=disease, force=force,
            save_total=save_total, odds=odds)
    if k == "toxin":
        return _toxin_impl(action=action, target=target, tox_die=tox_die, save_total=save_total,
            full=full, poison=poison, weapon=weapon)
    if k == "wound":
        return _wound_impl(action=action, character=character, wound=wound, result=result)
    return f"Invalid kind '{kind}'. Valid kinds: condition, disease, toxin, wound."


# ============================================
# NARRATIVE ENHANCEMENT SYSTEM
# ============================================
# Tools for tracking relationships, story threads, NPC states,
# and checking for narrative anti-patterns

RELATIONSHIPS_FILE = CAMPAIGN_DIR / "narrative_relationships.json"
THREADS_FILE = CAMPAIGN_DIR / "narrative_threads.json"
FACTIONS_FILE = CAMPAIGN_DIR / "factions.json"
NPC_STATE_FILE = CAMPAIGN_DIR / "npc_states.json"  # DM-only, silent to player

ANTI_PATTERNS = {
    "monologue_villain": {
        "description": "Villain explains plan when they could just act",
        "triggers": ["let me explain", "you see, my plan", "before you die", "i will tell you"],
        "suggestion": "Show the plan in action instead of explaining it"
    },
    "deus_ex_machina": {
        "description": "Sudden solution appears with no foreshadowing",
        "triggers": ["suddenly appears", "out of nowhere", "just in time", "miraculously"],
        "suggestion": "Foreshadow rescues or solutions at least one scene earlier"
    },
    "talking_heads": {
        "description": "Extended dialogue without action, movement, or environment",
        "triggers": [],  # Detected by dialogue count without action beats
        "suggestion": "Add physical actions, environmental details, or movement between lines"
    },
    "maid_and_butler": {
        "description": "Characters explain things they both already know for audience benefit",
        "triggers": ["as you know", "you remember when", "surely you recall", "as we discussed"],
        "suggestion": "Have characters reference shared knowledge obliquely or through action"
    },
    "passive_protagonist": {
        "description": "PCs observe rather than act in pivotal moments",
        "triggers": ["they watch as", "they see", "before they can act", "they stand frozen"],
        "suggestion": "Give PCs agency in pivotal moments, even if outcome is predetermined"
    },
    "over_naming": {
        "description": "Using character's name excessively in dialogue",
        "triggers": [],  # Counted per paragraph
        "suggestion": "Use pronouns or role references ('sister', 'captain') after first mention"
    }
}


def _load_relationships():
    """Load relationships.json"""
    if not RELATIONSHIPS_FILE.exists():
        return {"relationships": {}, "meta": {"last_updated": datetime.now().strftime("%Y-%m-%d")}}, None
    with open(RELATIONSHIPS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f), None


def _save_relationships(data):
    """Save relationships.json"""
    data['meta']['last_updated'] = datetime.now().strftime("%Y-%m-%d")
    _atomic_json_write(RELATIONSHIPS_FILE, data)


def _load_threads():
    """Load threads.json"""
    if not THREADS_FILE.exists():
        return {"threads": {}, "resolved": {}, "meta": {"last_updated": datetime.now().strftime("%Y-%m-%d")}}, None
    with open(THREADS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f), None


def _save_threads(data):
    """Save threads.json"""
    data['meta']['last_updated'] = datetime.now().strftime("%Y-%m-%d")
    _atomic_json_write(THREADS_FILE, data)


def _faction_slug(name: str) -> str:
    """Lowercase + underscore a faction name into its ledger key."""
    s = (name or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s


def _load_factions():
    """Load factions.json (party-level faction REP ledger). Empty default if absent."""
    if not FACTIONS_FILE.exists():
        return {"factions": {}, "meta": {"last_updated": datetime.now().strftime("%Y-%m-%d")}}, None
    try:
        with open(FACTIONS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f), None
    except Exception as e:
        return {"factions": {}, "meta": {"last_updated": datetime.now().strftime("%Y-%m-%d")}}, str(e)


def _save_factions(data):
    """Persist factions.json atomically."""
    data.setdefault("meta", {})["last_updated"] = datetime.now().strftime("%Y-%m-%d")
    _atomic_json_write(FACTIONS_FILE, data)


def _thread_current_day() -> int:
    """Current campaign day from the characters meta (fail-soft: 0)."""
    try:
        cdata, cerr = _load_characters()
        if cerr or not isinstance(cdata, dict):
            return 0
        return cdata.get("meta", {}).get("campaign_day") or 0
    except Exception:
        return 0


def _load_npc_states():
    """Load NPC states (DM-only file)"""
    if not NPC_STATE_FILE.exists():
        return {"npcs": {}, "meta": {"last_updated": datetime.now().strftime("%Y-%m-%d")}}, None
    with open(NPC_STATE_FILE, 'r', encoding='utf-8') as f:
        return json.load(f), None


def _save_npc_states(data):
    """Save NPC states"""
    data['meta']['last_updated'] = datetime.now().strftime("%Y-%m-%d")
    _atomic_json_write(NPC_STATE_FILE, data)


def _make_relationship_key(entity1: str, entity2: str) -> str:
    """Create consistent key for relationship pair (alphabetically sorted)"""
    sorted_pair = sorted([entity1.lower().strip(), entity2.lower().strip()])
    return f"{sorted_pair[0]}|{sorted_pair[1]}"


# ============================================
# CONSOLIDATED RELATIONSHIP TOOL
# ============================================

VALID_RELATIONSHIP_ACTIONS = ["set", "get", "list", "history"]
VALID_FACTION_ACTIONS = {"status", "earn", "spend", "set", "add", "oppose"}

@mcp.tool(tags=_get_tool_tags("relationship"))
def relationship(
    action: str = Field(description="set|get|list|history"),
    entity1: str = Field(default=None, description="First entity"),
    entity2: str = Field(default=None, description="Second entity"),
    status: str = Field(default=None, description="Relationship status"),
    notes: str = Field(default="", description="Notes"),
    last_interaction_day: int = Field(default=0, description="Campaign day"),
    filter_entity: str = Field(default="", description="list: filter by entity")
) -> str:
    """Reach for this WHEN a meaningful bond, enmity, or alliance between two named entities shifts — record or retrieve who stands with whom; not for story-arc beats (use thread for those).

Track NPC-to-NPC or PC-to-NPC relationships. Use when relationship status changes significantly."""
    action = action.lower().strip()
    if action not in VALID_RELATIONSHIP_ACTIONS:
        return f"Invalid action. Valid: {', '.join(VALID_RELATIONSHIP_ACTIONS)}"

    if action == "list":
        return _relationship_list(filter_entity)

    if not entity1 or not entity2:
        return f"Action '{action}' requires 'entity1' and 'entity2' parameters."

    if action == "set":
        if not status:
            return "set requires 'status' parameter."
        return _relationship_set(entity1, entity2, status, notes, last_interaction_day)
    elif action == "get":
        return _relationship_get(entity1, entity2)
    elif action == "history":
        return _relationship_history(entity1, entity2)

    return f"Action '{action}' not implemented."


def _relationship_set(entity1: str, entity2: str, status: str, notes: str, last_day: int) -> str:
    data, err = _load_relationships()
    if err:
        raise ToolError(err)
    key = _make_relationship_key(entity1, entity2)
    old_entry = data.get('relationships', {}).get(key, {})
    data['relationships'][key] = {
        "entities": [entity1.strip(), entity2.strip()],
        "status": status.strip(),
        "notes": notes.strip() if notes else "",
        "last_interaction_day": last_day,
        "history": old_entry.get('history', [])
    }
    if old_entry and old_entry.get('status') != status:
        data['relationships'][key]['history'].append({"from_status": old_entry.get('status', 'unknown'), "to_status": status, "day": last_day, "note": notes})
    _save_relationships(data)
    return f"Relationship set: {entity1} <-> {entity2} = {status}"


def _relationship_get(entity1: str, entity2: str) -> str:
    data, err = _load_relationships()
    if err:
        raise ToolError(err)
    key = _make_relationship_key(entity1, entity2)
    rel = data.get('relationships', {}).get(key)
    if not rel:
        return f"No relationship between {entity1} and {entity2}"
    output = [f"**{entity1} <-> {entity2}**", f"Status: {rel.get('status', 'unknown')}"]
    if rel.get('notes'):
        output.append(f"Notes: {rel['notes']}")
    if rel.get('last_interaction_day'):
        output.append(f"Last interaction: Day {rel['last_interaction_day']}")
    return "\n".join(output)


def _relationship_list(entity: str = "") -> str:
    data, err = _load_relationships()
    if err:
        raise ToolError(err)
    rels = data.get('relationships', {})
    if not rels:
        return "No relationships tracked."
    output = ["# Relationships", ""]
    entity_lower = entity.lower().strip() if entity else ""
    for key, rel in sorted(rels.items()):
        entities = rel.get('entities', key.split('|'))
        if entity_lower and entity_lower not in [e.lower() for e in entities]:
            continue
        e1, e2 = entities if len(entities) == 2 else key.split('|')
        output.append(f"- {e1} <-> {e2}: **{rel.get('status', 'unknown')}**")
    return "\n".join(output)


def _relationship_history(entity1: str, entity2: str) -> str:
    data, err = _load_relationships()
    if err:
        raise ToolError(err)
    key = _make_relationship_key(entity1, entity2)
    rel = data.get('relationships', {}).get(key)
    if not rel:
        return f"No relationship between {entity1} and {entity2}"
    history = rel.get('history', [])
    if not history:
        return f"No changes recorded for {entity1} <-> {entity2} (current: {rel.get('status')})"
    output = [f"# History: {entity1} <-> {entity2}", ""]
    for h in history:
        output.append(f"- Day {h.get('day', '?')}: {h.get('from_status')} -> {h.get('to_status')}")
    output.append(f"\nCurrent: {rel.get('status')}")
    return "\n".join(output)


# ============================================
# CONSOLIDATED FACTION TOOL
# ============================================

def _faction_clamp(rep):
    return max(-10, min(10, int(rep)))


def _faction_line(slug, rec, detailed=False):
    """One-line standing summary: 'Mycomorph Colony - REP +6 (Friend) [favorable]'."""
    rep = _faction_clamp(rec.get("rep", 0))
    band = _factions.standing_for(rep)
    sign = f"+{rep}" if rep > 0 else str(rep)
    line = f"{rec.get('name', slug)} - REP {sign} ({band['label']}) [{band['reaction']}]"
    if detailed:
        line += f"\n  {band['effect']}"
    return line


def _faction_injection_lines(user_input, cap=3):
    """Return up to `cap` standing lines for factions named in the message. Live read."""
    if not user_input:
        return []
    data, err = _load_factions()
    if err:
        return []
    low = user_input.lower()
    hits = []
    for slug, rec in data.get("factions", {}).items():
        if not isinstance(rec, dict):
            continue
        nm = rec.get("name", "")
        if nm and re.search(r"\b" + re.escape(nm.lower()) + r"\b", low):
            hits.append((_faction_clamp(rec.get("rep", 0)), slug, rec))
    hits.sort(key=lambda h: abs(h[0]), reverse=True)
    out = []
    for _rep, slug, rec in hits[:cap]:
        band = _factions.standing_for(_faction_clamp(rec.get("rep", 0)))
        out.append(f"⚖ FACTION: {_faction_line(slug, rec)} - {band['effect']}")
    return out


def _thread_injection_elements(threads_data, input_lower, present_names_raw, cap=2):
    """Active narrative threads whose title/foreshadowing/character keywords appear
    in the turn input, as up to `cap` canon-delivery tuples (section, key, content)
    for dedup_elements.

    Runs every turn (ungated) — the keyword match IS the gate, mirroring
    _faction_injection_lines / _site_features_injection. Returned through
    dedup_elements so the canon_delivered delta-dedup fold collapses unchanged
    threads to a pointer on repeat turns (keying on `thread:<title>`)."""
    matched_threads = []
    for _thread_id, thread in threads_data.get("threads", {}).items():
        if not isinstance(thread, dict) or thread.get("status") != "active":
            continue
        # Match on title words, description key terms, or foreshadowing words
        title = thread.get("title", "").lower()
        desc = thread.get("description", "").lower()
        foreshadowing = [f.lower() for f in thread.get("foreshadowing", [])]
        title_words = [w for w in title.split() if len(w) > 3]
        # Extract significant words from foreshadowing phrases (4+ chars, not common)
        foreshadow_words = set()
        for phrase in foreshadowing:
            for word in phrase.split():
                if len(word) > 3 and word not in {'the', 'and', 'for', 'with', 'from', 'that', 'this', 'been', 'have', 'will'}:
                    foreshadow_words.add(word)

        if any(w in input_lower for w in title_words):
            matched_threads.append(thread)
        elif any(w in input_lower for w in foreshadow_words):
            matched_threads.append(thread)
        # Character named in the thread AND present in the scene
        elif any(name.lower() in desc for name in present_names_raw if len(name) > 2):
            if any(name.lower() in input_lower for name in present_names_raw):
                matched_threads.append(thread)

    elements = []
    for thread in matched_threads[:cap]:  # Limit to `cap` threads
        title = thread.get("title", "?")
        urgency = thread.get("urgency", "low")
        desc = thread.get("description", "")
        # Truncate description to first sentence
        first_sentence = desc.split('.')[0] + '.' if '.' in desc else desc[:100]
        elements.append(
            ("ACTIVE THREADS", f"thread:{title}",
             f"- **{title}** [{urgency}]: {first_sentence}")
        )
    return elements


def _site_features_injection(text: str) -> str:
    """Stamped site-features resurface when a stamped place is named in the
    turn text OR is the party's current location. One ledger read; returns
    "" when nothing matches. Spec: 2026-07-05-site-feature-persistence-design.md"""
    import site_features
    matches = site_features.scan_text_for_places(CAMPAIGN_DIR, text)
    try:
        active = (GAME_STATE.get("active_location_name") or "") if isinstance(GAME_STATE, dict) else ""
    except Exception:
        active = ""
    if active:
        entry = site_features.place_entry(CAMPAIGN_DIR, active)
        if entry and entry.get("features"):
            matches.setdefault(site_features.slugify(entry.get("display_name", active)), entry)
    if not matches:
        return ""
    return "\n".join(site_features.format_features_block(e) for e in matches.values())


_DEFENSE_MARKERS = re.compile(
    r"immun|prevent|protect|resist|negat|shield|ward\b|aegis|"
    r"advantage on \w+ sav|no (?:longer|navigation|combat)? ?penalt|"
    r"never surprised|survives?\b|cannot be|blocks?\b|halves? \w+ damage",
    re.IGNORECASE)

_DEFENSES_MAX_LINES = 12


def _standing_defenses_injection() -> str:
    """Defenses-before-harm (2026-07-19, memory-eater ruling): on vault/combat
    turns, surface every standing defensive item/augment/gift so the DM
    resolves them BEFORE narrating irreversible consequence. The D134
    memory-theft retcon happened because a protective item was discovered
    only after the harm was written. Fail-open."""
    try:
        active, _turn = _active_vault_turn()
        in_combat = bool(GAME_STATE.get("active_combat"))
        if not active and not in_combat:
            return ""
        char_dir = CAMPAIGN_DIR / "characters"
        if not char_dir.exists():
            return ""
        entries = []
        for f in sorted(char_dir.glob("*.json")):
            if f.name.startswith("_"):
                continue
            try:
                c = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            cname = c.get("name") or f.stem.title()

            def _scan(name, text):
                text = str(text or "")
                if text and _DEFENSE_MARKERS.search(text):
                    entries.append(f"  • {cname}: {name} — {text[:90].strip()}")

            inv = c.get("inventory") or {}
            for section in ("carried", "installed_permanent"):
                for it in inv.get(section) or []:
                    if isinstance(it, dict):
                        _scan(it.get("name", "?"),
                              f"{it.get('effect') or ''} {it.get('notes') or ''}")
            augs = c.get("augmentations") or {}
            for lst in (augs.values() if isinstance(augs, dict) else []):
                for a in (lst if isinstance(lst, list) else []):
                    if isinstance(a, dict):
                        _scan(a.get("name", "?"), a.get("effect"))
            for g in c.get("mystic_gifts") or []:
                if isinstance(g, dict):
                    _scan(g.get("name", "?"),
                          f"{g.get('effect') or ''} {g.get('description') or ''}")
            for t in c.get("special_traits") or []:
                if isinstance(t, dict):
                    _scan(t.get("name", "?"),
                          f"{t.get('effect') or ''} {t.get('description') or ''}")
        if not entries:
            return ""
        lines = ["**STANDING DEFENSES:**"]
        shown = entries[:_DEFENSES_MAX_LINES]
        lines.extend(shown)
        if len(entries) > len(shown):
            lines.append(f"  (+{len(entries) - len(shown)} more — character files)")
        lines.append("  ⛔ Resolve these BEFORE narrating irreversible harm "
                     "(memory/wound/death/item loss). A strike that a listed "
                     "defense answers is narrated as ANSWERED — never written "
                     "as landed and retconned.")
        return "\n".join(lines)
    except Exception as e:
        logging.debug(f"standing-defenses injection failed: {e}")
        return ""


def _revealed_ledger_injection() -> str:
    """Reveal discipline (2026-07-16): on vault turns, show the DM the boundary
    of what the party actually knows. Whitelist source: maps/<name>_map.json
    revealed_ledger (written only by reveal paths). Fail-open."""
    try:
        active, _turn = _active_vault_turn()
        if active:
            # Vault turn: the active map owns the ledger (unchanged behavior).
            ledger_name = active
            state = map_system.get_map_state(active)
            if not state:
                return ""
        else:
            # Non-vault turn: engage only when the active prep carries DM-only
            # content (social/settlement scene). The prep-scoped ledger may not
            # exist yet — render the charter over an empty ledger.
            ledger_name, _prep = _active_prep_reveal_scope()
            if not ledger_name:
                return ""
            state = map_system.get_map_state(ledger_name) or {}
        ledger = state.get("revealed_ledger") or []
        # DOCKET block (2026-07-20): the party's open tracks, rendered ABOVE the
        # revealed ledger on every vault/prep-scoped turn. Presentation only — one
        # line per non-resolved track, never touches day/bell/location handling.
        docket_block = ""
        try:
            _day = get_current_day_safe()
        except Exception:
            _day = None
        _dlines = map_system.docket_lines(state, _day)
        if _dlines:
            _d = [f"**DOCKET ({ledger_name}) - open tracks:**"]
            _d.extend(_dlines)
            _d.append("  ANCHOR: open the scene on ONE named track; switching tracks "
                      "is an explicit beat.")
            _d.append('  Track moved? map(action="track", track_op="update", '
                      f'map_name="{ledger_name}", track_id="...", stand="...")')
            docket_block = "\n".join(_d) + "\n"
        lines = [f"**REVEALED LEDGER ({ledger_name}):**"]
        if not ledger:
            lines.append("  (Nothing discovered yet.)")
        else:
            shown = ledger[-8:]
            if len(ledger) > 8:
                lines.append(f"  (+{len(ledger)-8} earlier facts)")
            for e in shown:
                d = f" (D{e['day']})" if e.get("day") else ""
                # A0.1: label facts the engine could NOT source to prep/ledger/
                # player. DM-facing surface only — the player journal is unchanged.
                suffix = " [MINTED]" if e.get("provenance") == "mint" else ""
                lines.append(f"  • {e.get('fact','')}{d}{suffix}")
        lines.append("  ⛔ NPCs may assert ONLY these facts. Off-ledger they speculate "
                     "and may be WRONG. Unledgered names are unspeakable. "
                     "Ledgered facts are STATED PLAINLY when they surface — never as "
                     "implication. Party just learned something? map(action=\"reveal\", "
                     f"map_name=\"{ledger_name}\", fact=\"...\").")
        return docket_block + "\n".join(lines)
    except Exception as e:
        logging.debug(f"revealed-ledger injection failed: {e}")
        return ""


@mcp.tool(tags=_get_tool_tags("faction"))
def faction(
    action: str = Field(description="status|earn|spend|set|add|oppose"),
    name: str = Field(default=None, description="Faction name (slug is derived from it)"),
    amount: int = Field(default=0, description="earn/spend: REP change (earn may be negative for a loss)"),
    rep: int = Field(default=0, description="set/add: absolute REP value (-10..10)"),
    reason: str = Field(default="", description="Why REP changed / what a spend bought (logged)"),
    day: int = Field(default=None, description="Campaign day for the history entry (defaults to current)"),
    scope: str = Field(default="minor", description="add: 'alliance' | 'major' | 'minor'"),
    type: str = Field(default=None, description="add: faction type/kind"),
    goal: str = Field(default=None, description="add: faction goal"),
    leader: str = Field(default=None, description="add: faction leader"),
    assets: str = Field(default=None, description="add: comma-separated assets"),
    rival: str = Field(default=None, description="add: named rival faction"),
    opposed: str = Field(default=None, description="add/oppose: comma-separated faction names this one is opposed to (auto-mirrored on earn)"),
    notes: str = Field(default=None, description="add: freeform notes"),
    other: str = Field(default=None, description="oppose: the second faction to link"),
) -> str:
    """Reach for this WHEN the party's standing with an ORGANISATION shifts or you need to know it — track faction Reputation (REP, -10..+10), spend it as currency, or register/generate factions; NOT for one-to-one bonds (use relationship for those).

    Party-level faction REP ledger (Crimson Hound pp.83-84). status (list all, or detail one with the reaction effect), earn (add REP + auto-mirror opposed factions), spend (REP-as-currency, floor -10, no mirror), set (absolute override/seed), add (register a faction), oppose (link a rival pair). Mint new Minor factions with generate(action='faction')."""
    action = (action or "").lower().strip()
    # direct calls bypass pydantic: unresolved FieldInfo defaults are not values
    if not isinstance(name, str):
        name = None
    if not isinstance(scope, str):
        scope = "minor"
    if not isinstance(type, str):
        type = None
    if not isinstance(goal, str):
        goal = None
    if not isinstance(leader, str):
        leader = None
    if not isinstance(assets, str):
        assets = None
    if not isinstance(rival, str):
        rival = None
    if not isinstance(opposed, str):
        opposed = None
    if not isinstance(notes, str):
        notes = None
    if not isinstance(other, str):
        other = None
    if not isinstance(reason, str):
        reason = ""
    if not isinstance(amount, int):
        amount = 0
    if not isinstance(rep, int):
        rep = 0
    if not isinstance(day, int):
        day = None
    if action not in VALID_FACTION_ACTIONS:
        return f"Invalid action. Valid: {', '.join(sorted(VALID_FACTION_ACTIONS))}"
    if action == "status":
        return _faction_status(name)
    if action == "add":
        return _faction_add(name, scope, type, goal, leader, assets, rival, opposed, rep, notes, reason, day)
    if action == "oppose":
        return _faction_oppose(name, other or opposed)
    if not name:
        return f"Action '{action}' requires 'name'."
    if action == "earn":
        return _faction_earn(name, amount, reason, day)
    if action == "spend":
        return _faction_spend(name, amount, reason, day)
    if action == "set":
        return _faction_set(name, rep, reason, day)
    return f"Action '{action}' not implemented."


def _faction_status(name):
    data, err = _load_factions()
    if err:
        return f"Error reading factions: {err}"
    facs = data.get("factions", {})
    if not name:
        if not facs:
            return ("No factions tracked yet. Register one with "
                    + _pf.push_call("faction", action="add", name=_pf.raw('"<name>"'), rep=0))
        rows = sorted(facs.items(), key=lambda kv: _faction_clamp(kv[1].get("rep", 0)), reverse=True)
        lines = ["**FACTION STANDINGS:**"] + [f"- {_faction_line(s, r)}" for s, r in rows]
        return "\n".join(lines)
    slug = _faction_slug(name)
    rec = facs.get(slug)
    if not isinstance(rec, dict):
        return (f"No faction '{name}' is tracked. Register it with "
                + _pf.push_call("faction", action="add", name=name, rep=0))
    out = [_faction_line(slug, rec, detailed=True)]
    opp = [o for o in rec.get("opposed", []) if o in facs]
    if opp:
        out.append("Opposed: " + ", ".join(_faction_line(o, facs[o]) for o in opp))
    hist = rec.get("history", [])[-5:]
    if hist:
        out.append("Recent: " + "; ".join(
            f"day {h.get('day','?')} {'+' if h.get('delta',0) >= 0 else ''}{h.get('delta',0)} ({h.get('reason','')})"
            for h in hist))
    return "\n".join(out)


def _faction_add(name, scope, type_, goal, leader, assets, rival, opposed, rep, notes, reason, day):
    if not name:
        return "add requires 'name'."
    data, err = _load_factions()
    if err:
        return f"Error reading factions: {err}"
    slug = _faction_slug(name)
    if slug in data.get("factions", {}):
        return f"Faction '{name}' already exists. Use earn/spend/set to change it."
    rep_c = _faction_clamp(rep)
    d = day if isinstance(day, int) else _thread_current_day()
    opposed_slugs = [_faction_slug(o) for o in (opposed.split(",") if opposed else []) if o.strip()]
    rec = {
        "name": name, "scope": scope or "minor", "type": type_, "goal": goal,
        "leader": leader, "assets": [a.strip() for a in assets.split(",")] if assets else [],
        "rival": rival, "opposed": opposed_slugs, "rep": rep_c,
        "notes": notes, "history": [],
    }
    if rep_c != 0:
        rec["history"].append({"day": d, "delta": rep_c, "reason": reason or "registered", "rep_after": rep_c})
    data.setdefault("factions", {})[slug] = rec
    _save_factions(data)
    return ("Registered " + _faction_line(slug, rec, detailed=True) + "\n"
            + _pf.next_block(_pf.push_call("faction", action="status", name=name),
                             label="check standing any time"))


def _faction_oppose(name, other):
    if not name or not other:
        return "oppose requires 'name' and 'other'."
    data, err = _load_factions()
    if err:
        return f"Error reading factions: {err}"
    facs = data.get("factions", {})
    s1, s2 = _faction_slug(name), _faction_slug(other)
    if s1 == s2:
        return "A faction cannot oppose itself."
    if s1 not in facs or s2 not in facs:
        missing = name if s1 not in facs else other
        return f"No faction '{missing}' is tracked. Register it first with faction add."
    for a, b in ((s1, s2), (s2, s1)):
        opp = facs[a].setdefault("opposed", [])
        if b not in opp:
            opp.append(b)
    _save_factions(data)
    return f"Linked {facs[s1]['name']} <-> {facs[s2]['name']} as opposed (REP earn auto-mirrors)."


def _faction_earn(name, amount, reason, day):
    if not isinstance(amount, int) or amount == 0:
        return "earn requires a non-zero integer 'amount'."
    data, err = _load_factions()
    if err:
        return f"Error reading factions: {err}"
    facs = data.get("factions", {})
    slug = _faction_slug(name)
    rec = facs.get(slug)
    if not isinstance(rec, dict):
        return (f"No faction '{name}' is tracked. Register it with "
                + _pf.push_call("faction", action="add", name=name, rep=0))
    d = day if isinstance(day, int) else _thread_current_day()
    before = _faction_clamp(rec.get("rep", 0))
    after = _faction_clamp(before + amount)
    rec["rep"] = after
    rec.setdefault("history", []).append(
        {"day": d, "delta": amount, "reason": reason or "earned", "rep_after": after})
    lines = ["Earned: " + _faction_line(slug, rec, detailed=True)]
    if after in (-10, 10) and (before + amount) != after:
        lines.append(f"(capped at {'+10 Hero' if after == 10 else '-10 Nemesis'})")
    for opp_slug in rec.get("opposed", []):
        if opp_slug == slug:
            continue
        opp_rec = facs.get(opp_slug)
        if not isinstance(opp_rec, dict):
            lines.append(f"(opposed '{opp_slug}' not tracked - mirror skipped)")
            continue
        ob = _faction_clamp(opp_rec.get("rep", 0))
        oa = _faction_clamp(ob - amount)
        if oa == ob:
            lines.append(f"  (opposed {opp_rec.get('name', opp_slug)} unchanged at {oa:+d} - at bound)")
            continue
        opp_rec["rep"] = oa
        opp_rec.setdefault("history", []).append(
            {"day": d, "delta": oa - ob, "reason": f"opposed to {rec['name']}", "rep_after": oa})
        line = "  mirror -> " + _faction_line(opp_slug, opp_rec)
        if oa in (-10, 10) and (ob - amount) != oa:
            line += f" (capped at {oa:+d})"
        lines.append(line)
    _save_factions(data)
    lines.append(_pf.next_block(_pf.push_call("faction", action="status", name=name),
                                label="full standing"))
    return "\n".join(lines)


def _faction_spend(name, amount, reason, day):
    if not isinstance(amount, int) or amount <= 0:
        return "spend requires a positive integer 'amount' (REP to consume)."
    data, err = _load_factions()
    if err:
        return f"Error reading factions: {err}"
    facs = data.get("factions", {})
    slug = _faction_slug(name)
    rec = facs.get(slug)
    if not isinstance(rec, dict):
        return f"No faction '{name}' is tracked. Register it with faction add."
    before = _faction_clamp(rec.get("rep", 0))
    after = before - amount
    if after < -10:
        return (f"Cannot spend {amount} REP with {rec['name']} - would drop to {after}, "
                f"below the -10 floor (current {before:+d}, only {before + 10} spendable).")
    rec["rep"] = after
    d = day if isinstance(day, int) else _thread_current_day()
    rec.setdefault("history", []).append(
        {"day": d, "delta": -amount, "reason": reason or "spent REP", "rep_after": after})
    _save_factions(data)
    return ("Spent: " + _faction_line(slug, rec, detailed=True)
            + f"\n(-{amount} REP consumed: {reason or 'a favour'})")


def _faction_set(name, rep, reason, day):
    data, err = _load_factions()
    if err:
        return f"Error reading factions: {err}"
    facs = data.get("factions", {})
    slug = _faction_slug(name)
    rec = facs.get(slug)
    if not isinstance(rec, dict):
        return f"No faction '{name}' is tracked. Register it with faction add."
    before = _faction_clamp(rec.get("rep", 0))
    after = _faction_clamp(rep)
    rec["rep"] = after
    d = day if isinstance(day, int) else _thread_current_day()
    rec.setdefault("history", []).append(
        {"day": d, "delta": after - before, "reason": reason or "set", "rep_after": after})
    _save_factions(data)
    return "Set: " + _faction_line(slug, rec, detailed=True)


# ============================================
# CONSOLIDATED THREAD TOOL
# ============================================

VALID_THREAD_ACTIONS = ["add", "update", "resolve", "list", "get"]

@mcp.tool(tags=_get_tool_tags("thread"))
def thread(
    action: str = Field(description="add|update|resolve|list|get"),
    thread_id: str = Field(default=None, description="Thread ID"),
    title: str = Field(default=None, description="Title"),
    description: str = Field(default=None, description="Description"),
    introduced_day: int = Field(default=0, description="Day introduced"),
    urgency: str = Field(default="low", description="low|medium|high|critical"),
    development: str = Field(default="", description="New development"),
    development_day: int = Field(default=0, description="Day of development"),
    foreshadowing: str = Field(default="", description="Hints (semicolon-separated)"),
    resolution: str = Field(default=None, description="How resolved"),
    resolution_day: int = Field(default=0, description="Day resolved"),
    include_resolved: bool = Field(default=False, description="list: include resolved"),
    clock_due_day: int = Field(default=0, description="Wind a world-tick clock: campaign day it ripens (0 = no change, -1 on update clears it). advance_day fires it ONCE when due."),
    clock_label: str = Field(default="", description="What ripens, terse + spoiler-safe (e.g. 'power vacuum ripens'); player-visible in advance_day output")
) -> str:
    """Reach for this WHEN a new plot arc opens, a thread escalates in urgency, or a storyline resolves — track the narrative shape of the campaign; not for individual NPC bonds (use relationship for those).

Track story arcs and plot threads. Use when introducing new plots, major developments, or resolving storylines."""
    # Normalize FieldInfo defaults (direct .fn / test calls bypass pydantic)
    from pydantic.fields import FieldInfo as _FieldInfo
    if isinstance(thread_id, _FieldInfo): thread_id = None
    if isinstance(title, _FieldInfo): title = None
    if isinstance(description, _FieldInfo): description = None
    if isinstance(introduced_day, _FieldInfo): introduced_day = 0
    if isinstance(urgency, _FieldInfo): urgency = "low"
    if isinstance(development, _FieldInfo): development = ""
    if isinstance(development_day, _FieldInfo): development_day = 0
    if isinstance(foreshadowing, _FieldInfo): foreshadowing = ""
    if isinstance(resolution, _FieldInfo): resolution = None
    if isinstance(resolution_day, _FieldInfo): resolution_day = 0
    if isinstance(include_resolved, _FieldInfo): include_resolved = False
    if isinstance(clock_due_day, _FieldInfo): clock_due_day = 0
    if isinstance(clock_label, _FieldInfo): clock_label = ""
    action = action.lower().strip()
    if action not in VALID_THREAD_ACTIONS:
        return f"Invalid action. Valid: {', '.join(VALID_THREAD_ACTIONS)}"

    if action == "list":
        return _thread_list(include_resolved)

    if not thread_id:
        return f"Action '{action}' requires 'thread_id' parameter."

    if action == "add":
        if not title or not description:
            return "add requires 'title' and 'description' parameters."
        return _thread_add(thread_id, title, description, introduced_day, urgency, foreshadowing,
                           clock_due_day, clock_label)
    elif action == "update":
        return _thread_update(thread_id, development, development_day, urgency, foreshadowing,
                              clock_due_day, clock_label)
    elif action == "resolve":
        if not resolution:
            return "resolve requires 'resolution' parameter."
        return _thread_resolve(thread_id, resolution, resolution_day)
    elif action == "get":
        return _thread_get(thread_id)

    return f"Action '{action}' not implemented."


# Heartbeat spine (spec 2026-06-17 §5): a person's open_purpose pace -> clock interval.
# DM sets the pace word at plant; the engine owns what each means in days.
PACE_DAYS = {"still": None, "cool": 30, "warm": 7, "hot": 3}
_HEARTBEAT_DEFAULT_PACE = "cool"  # auto-plant default (spec 2026-06-18): the world drifts, not churns; DM overrides for hot/still


def _pace_to_due_day(pace, from_day):
    """Map a pace word + a base day to a clock due-day. None = no clock
    (still / empty / unrecognised). Case-insensitive. Single clean temperature
    ramp: still -> cool -> warm -> hot (monotonically faster)."""
    days = PACE_DAYS.get((pace or "").lower().strip())
    if days is None:
        return None
    return int(from_day) + days


def _thread_add(thread_id: str, title: str, desc: str, intro_day: int, urgency: str, foreshadowing: str,
                clock_due_day: int = 0, clock_label: str = "") -> str:
    data, err = _load_threads()
    if err:
        raise ToolError(err)
    key = thread_id.lower().strip().replace(' ', '_')
    if key in data.get('threads', {}):
        raise ToolError(f"Thread '{key}' exists. Use update.")
    # Generator default: day-0 records read as ancient to the stale scan
    # (world-forces briefing) -- stamp today when no day was supplied.
    if not intro_day:
        intro_day = _thread_current_day()
    data['threads'][key] = {
        "id": key, "title": title.strip(), "description": desc.strip(),
        "introduced_day": intro_day, "urgency": urgency.lower(),
        "foreshadowing": [f.strip() for f in foreshadowing.split(';') if f.strip()] if foreshadowing else [],
        "developments": [], "status": "active"
    }
    clock_note = ""
    if clock_due_day and clock_due_day > 0:
        label = (clock_label or title).strip()
        data['threads'][key]["clock"] = {
            "due_day": clock_due_day, "label": label,
            "wound_day": intro_day if intro_day else _thread_current_day(),
            "fired": False
        }
        clock_note = f" | Clock wound: '{label}' due day {clock_due_day}"
    _save_threads(data)
    return f"Thread added: {title} (ID: {key}){clock_note}"


def _thread_update(thread_id: str, development: str, dev_day: int, urgency: str, foreshadowing: str,
                   clock_due_day: int = 0, clock_label: str = "") -> str:
    data, err = _load_threads()
    if err:
        raise ToolError(err)
    key = thread_id.lower().strip().replace(' ', '_')
    if key not in data.get('threads', {}):
        raise ToolError(f"Thread '{key}' not found")
    t = data['threads'][key]
    updates = []
    if development:
        # Generator default: an unsupplied day must NOT freeze at 0 -- a
        # day-0 development can never satisfy the fired-clock surfacing
        # check (day >= fired_day), so the briefing would nag forever.
        if not dev_day:
            dev_day = _thread_current_day()
        t['developments'].append({"text": development.strip(), "day": dev_day})
        updates.append(f"Development (Day {dev_day})")
    if urgency and urgency.lower() in ['low', 'medium', 'high', 'critical']:
        t['urgency'] = urgency.lower()
        updates.append(f"Urgency -> {urgency}")
    if foreshadowing:
        for h in foreshadowing.split(';'):
            if h.strip():
                t['foreshadowing'].append(h.strip())
        updates.append("Foreshadowing added")
    if clock_due_day and clock_due_day > 0:
        label = (clock_label or t.get('title', key)).strip()
        t["clock"] = {
            "due_day": clock_due_day, "label": label,
            "wound_day": _thread_current_day(), "fired": False
        }
        updates.append(f"Clock wound: '{label}' due day {clock_due_day}")
    elif clock_due_day == -1:
        t.pop("clock", None)
        updates.append("Clock cleared")
    _save_threads(data)
    return f"Thread '{t['title']}' updated: {', '.join(updates) if updates else 'no changes'}"


def _thread_resolve(thread_id: str, resolution: str, res_day: int) -> str:
    data, err = _load_threads()
    if err:
        raise ToolError(err)
    key = thread_id.lower().strip().replace(' ', '_')
    if key not in data.get('threads', {}):
        raise ToolError(f"Thread '{key}' not found")
    t = data['threads'].pop(key)
    t.pop('clock', None)  # a resolved thread has no live clock
    t['status'] = 'resolved'
    t['resolution'] = resolution.strip()
    t['resolution_day'] = res_day
    data.setdefault('resolved', {})[key] = t
    _save_threads(data)
    return f"Thread resolved: {t['title']}"


def _thread_list(include_resolved: bool = False) -> str:
    data, err = _load_threads()
    if err:
        raise ToolError(err)
    output = ["# Narrative Threads", ""]
    urgency_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
    active = data.get('threads', {})
    if not active:
        output.append("No active threads.")
    else:
        current_day = _thread_current_day()
        # Sort by urgency, but iterate over items to get the key
        sorted_threads = sorted(active.items(), key=lambda x: urgency_order.get(x[1].get('urgency', 'low'), 3))
        for key, t in sorted_threads:
            output.append(f"## [{t.get('urgency', 'low').upper()}] {t.get('title')} (Day {t.get('introduced_day')})")
            output.append(f"**ID:** `{key}`")
            output.append(t.get('description', '')[:100])
            ck = t.get('clock')
            if ck:
                if ck.get('fired'):
                    output.append(f"\U0001f514 FIRED day {ck.get('due_day')} - awaiting narrative surfacing: {ck.get('label')}")
                elif ck.get('due_day', 0) <= current_day:
                    output.append(f"⏳ DUE (day {ck.get('due_day')}): {ck.get('label')}")
                else:
                    output.append(f"⏳ {ck.get('label')} - due day {ck.get('due_day')}")
            output.append("")
    if include_resolved:
        resolved = data.get('resolved', {})
        if resolved:
            output.extend(["---", "# Resolved", ""])
            for key, t in resolved.items():
                output.append(f"- `{key}`: {t.get('title')} (Day {t.get('introduced_day')} -> {t.get('resolution_day')})")
    return "\n".join(output)


def _thread_get(thread_id: str) -> str:
    data, err = _load_threads()
    if err:
        raise ToolError(err)
    key = thread_id.lower().strip().replace(' ', '_')
    t = data.get('threads', {}).get(key) or data.get('resolved', {}).get(key)
    if not t:
        raise ToolError(f"Thread '{key}' not found")
    output = [f"# {t.get('title')}", "", f"**ID:** {t.get('id')}", f"**Status:** {t.get('status', 'active')}",
              f"**Urgency:** {t.get('urgency', 'low')}", f"**Introduced:** Day {t.get('introduced_day')}", "",
              f"**Description:** {t.get('description', '')}"]
    if t.get('clock'):
        ck = t['clock']
        state = "FIRED" if ck.get('fired') else "not fired"
        output.append(f"**Clock:** {ck.get('label')} - due day {ck.get('due_day')} (wound day {ck.get('wound_day')}, {state})")
    if t.get('foreshadowing'):
        output.extend(["", "**Foreshadowing:**"] + [f"- {h}" for h in t['foreshadowing']])
    if t.get('developments'):
        output.extend(["", "**Developments:**"] + [f"- Day {d.get('day')}: {d.get('text')}" for d in t['developments']])
    if t.get('resolution'):
        output.extend(["", f"**Resolution (Day {t.get('resolution_day')}):** {t.get('resolution')}"])
    return "\n".join(output)


# ============================================
# CONSOLIDATED NPC STATE TOOL
# ============================================

VALID_NPC_ACTIONS = ["set", "get", "list", "add_knowledge", "continuity", "record_death"]

@mcp.tool(tags=_get_tool_tags("npc"))
def npc(
    action: str = Field(description="set|get|list|add_knowledge|continuity|record_death"),
    name: str = Field(default=None, description="NPC name"),
    disposition: str = Field(default="", description="hostile|wary|neutral|friendly|allied"),
    knows: str = Field(default="", description="What NPC knows (semicolon-separated)"),
    wants: str = Field(default="", description="What NPC wants"),
    secret: str = Field(default="", description="NPC's secret"),
    location: str = Field(default="", description="Current location"),
    last_seen_day: int = Field(default=0, description="Day last seen"),
    death_day: int = Field(default=0, description="record_death: day of death (defaults to current day)"),
    knowledge: str = Field(default=None, description="add_knowledge: new fact"),
    learned_day: int = Field(default=0, description="add_knowledge: day learned"),
    disposition_filter: str = Field(default="", description="list: filter by disposition"),
    strip_secrets: bool = Field(default=False, description="If True, omit secret field from get output"),
    left_off: str = Field(default="", description="continuity: where the last scene left off (<=1 sentence)"),
    open_purpose: str = Field(default="", description="continuity: the open agenda/reason for dealings (<=1 line)"),
    pace: str = Field(default="", description="continuity: how fast this person's open_purpose moves off-screen. Temperature ramp (faster as it heats): still (never) | cool (~monthly) | warm (~weekly) | hot (every few days). still/blank = no clock. The engine fires it via advance_day."),
) -> str:
    """Reach for this WHEN an NPC's disposition shifts, they learn something new, or you need to read/list persistent NPC state — this is the write tool for NPC records.

    Track NPC states (DM-only, never shown to players). Use when NPC disposition changes or learns new information."""
    action = action.lower().strip()
    if action not in VALID_NPC_ACTIONS:
        return f"Invalid action. Valid: {', '.join(VALID_NPC_ACTIONS)}"

    if action == "list":
        return _npc_list(disposition_filter)

    if not name:
        return f"Action '{action}' requires 'name' parameter."

    if action == "set":
        return _npc_set(name, disposition, knows, wants, secret, location, last_seen_day)
    elif action == "get":
        return _npc_get(name, strip_secrets=strip_secrets)
    elif action == "add_knowledge":
        if not knowledge:
            return "add_knowledge requires 'knowledge' parameter."
        return _npc_add_knowledge(name, knowledge, learned_day)
    elif action == "continuity":
        _pace_str = pace if isinstance(pace, str) else ""
        return _npc_continuity(name, left_off, open_purpose, last_seen_day, pace=_pace_str)
    elif action == "record_death":
        return _npc_record_death(name, death_day)

    return f"Action '{action}' not implemented."


# Field caps (spec 6): keep the deterministic injection cheap.
_NPC_CONTINUITY_LEFTOFF_CAP = 240
_NPC_CONTINUITY_PURPOSE_CAP = 160


def _npc_continuity(npc_name: str, left_off: str, open_purpose: str, last_day: int, pace: str = "") -> str:
    """Capture the conversational thread for an NPC (spec 3a live capture).

    DM-only, never shown to players. Writes only the provided fields; flips
    changed_while_away.surfaced=True (the re-engagement surfaces it). The gate
    flag is cleared by gate_check.py on this tool call, not here."""
    if not npc_name:
        return "continuity requires 'name'."
    data, err = _load_npc_states()
    if err:
        raise ToolError(err)
    key = npc_name.lower().strip()
    rec = data.get("npcs", {}).get(key)
    if not rec:
        return f"NPC '{npc_name}' not found in roster — use npc(action='set') first."
    if left_off and left_off.strip():
        rec["left_off"] = left_off.strip()[:_NPC_CONTINUITY_LEFTOFF_CAP]
    if open_purpose and open_purpose.strip():
        rec["open_purpose"] = open_purpose.strip()[:_NPC_CONTINUITY_PURPOSE_CAP]
    if last_day:
        rec["last_seen_day"] = last_day
    cwa = rec.get("changed_while_away")
    if isinstance(cwa, dict) and not cwa.get("surfaced", False):
        cwa["surfaced"] = True
    # Heartbeat spine (spec 2026-06-17): wind/re-wind/clear the purpose-clock.
    # A non-empty pace plants a clock on the open_purpose; "still" clears it.
    _clock_echo = ""
    if pace and pace.strip():
        base_day = last_day or _thread_current_day()
        due = _pace_to_due_day(pace, base_day)
        purpose_label = (rec.get("open_purpose") or "").strip()
        if due is not None and purpose_label:
            rec["purpose_clock"] = {
                "due_day": due, "label": purpose_label[:_NPC_CONTINUITY_PURPOSE_CAP],
                "wound_day": base_day, "pace": pace.lower().strip(), "fired": False,
            }
            _clock_echo = f" | purpose-clock wound ({pace.lower().strip()}) — fires day {due}"
        else:
            rec.pop("purpose_clock", None)  # still / no purpose -> no clock
            _clock_echo = " | purpose-clock cleared (still / no open purpose)"
    else:
        # Auto-plant (spec 2026-06-18): pace is automatic; the DM only overrides.
        base_day = last_day or _thread_current_day()
        purpose_label = (rec.get("open_purpose") or "").strip()
        existing = rec.get("purpose_clock")
        if purpose_label and not isinstance(existing, dict):
            # no clock yet -> auto-wind at the default pace
            _due = _pace_to_due_day(_HEARTBEAT_DEFAULT_PACE, base_day)
            rec["purpose_clock"] = {
                "due_day": _due, "label": purpose_label[:_NPC_CONTINUITY_PURPOSE_CAP],
                "wound_day": base_day, "pace": _HEARTBEAT_DEFAULT_PACE, "fired": False,
            }
            _clock_echo = f" | purpose-clock auto-set ({_HEARTBEAT_DEFAULT_PACE}, default) — fires day {_due}"
        elif purpose_label and isinstance(existing, dict) and existing.get("fired"):
            # fired clock + re-engagement -> re-arm at its existing pace (from current day)
            _pace = existing.get("pace", _HEARTBEAT_DEFAULT_PACE)
            _due = _pace_to_due_day(_pace, base_day)
            if _due is None:  # defensive: a non-clocking/garbage stored pace -> fall back to default
                _pace = _HEARTBEAT_DEFAULT_PACE
                _due = _pace_to_due_day(_pace, base_day)
            existing.update({"due_day": _due, "label": purpose_label[:_NPC_CONTINUITY_PURPOSE_CAP],
                             "wound_day": base_day, "pace": _pace, "fired": False})
            existing.pop("fired_day", None)
            rec["purpose_clock"] = existing
            _clock_echo = f" | purpose-clock re-armed ({_pace}) — fires day {_due}"
        # else (purpose + unfired clock, OR no purpose): leave the clock exactly as-is
    data["npcs"][key] = rec
    _save_npc_states(data)
    day_display = rec.get('last_seen_day') or 'unknown'
    return f"[DM-ONLY] ✓ Continuity recorded for {rec.get('name', npc_name)} (day {day_display}).{_clock_echo}"


_NPC_CWA_NOTE_CAP = 200


def _stamp_npc_changed_while_away(npc_slug: str, note: str, day: int) -> bool:
    """Stamp an off-screen change onto an NPC (spec 8). fired != surfaced:
    surfaced=False until the DM works it into fiction (the continuity write
    flips it). No-op for unknown NPCs. Returns True if stamped."""
    if not npc_slug or not note:
        return False
    data, err = _load_npc_states()
    if err:
        return False
    key = npc_slug.lower().strip()
    rec = data.get("npcs", {}).get(key)
    if not rec:
        return False
    rec["changed_while_away"] = {
        "note": note.strip()[:_NPC_CWA_NOTE_CAP],
        "stamped_day": day,
        "surfaced": False,
    }
    data["npcs"][key] = rec
    _save_npc_states(data)
    return True


def _world_forces_people_lines():
    """Heartbeat spine: one line per person whose purpose-clock has fired but
    whose change is not yet surfaced in fiction (fired != surfaced). Pull handle
    only -- nudge, never present full lore."""
    out = []
    try:
        data, err = _load_npc_states()
        if err:
            return out
        for _slug, rec in data.get("npcs", {}).items():
            pc = rec.get("purpose_clock")
            cwa = rec.get("changed_while_away")
            if (isinstance(pc, dict) and pc.get("fired")
                    and isinstance(cwa, dict) and not cwa.get("surfaced", False)):
                nm = rec.get("name", _slug)
                out.append(f"\U0001f514 {nm} moved on their purpose (fired day "
                           f"{pc.get('fired_day', '?')}, NOT YET SURFACED) — "
                           f"npc(action=\"get\", name=\"{nm}\")")
    except Exception:
        pass
    return out


# ============================================================
# HEARTBEAT — CROSSINGS (Slice B, spec 2026-06-18).
# When two LIVE seeds (a thread clock or an NPC purpose-clock) touch the same
# PERSON or FACTION, they have tangled. The engine co-locates the tangle and
# FORWARDS the raw relationship facts it already stores -- it judges NOTHING
# (no valence, no intensity, no scene directive). Tags are DERIVED at read time
# from existing fields (no stored tags, no migration). Cold-start safe: empty
# stores -> [] -> silence, no errors. RAG for the DM, invisible to the player.
# ============================================================

def _npc_seed_live(rec):
    """An NPC purpose-clock is a live seed unless it has fired AND been
    surfaced (changed_while_away.surfaced True). Unfired = pending = live;
    fired-but-unsurfaced = the hot one = live."""
    pc = rec.get("purpose_clock")
    if not isinstance(pc, dict):
        return False
    if not pc.get("fired"):
        return True
    cwa = rec.get("changed_while_away")
    if isinstance(cwa, dict) and cwa.get("surfaced"):
        return False
    return True


def _thread_seed_live(t):
    """A thread clock is a live seed unless the thread is resolved, or the
    clock has fired AND a development dated on/after fired_day was logged
    (the World Tick's surfaced rule)."""
    if not isinstance(t, dict) or t.get("status") == "resolved":
        return False
    clk = t.get("clock")
    if not isinstance(clk, dict):
        return False
    if not clk.get("fired"):
        return True
    fday = clk.get("fired_day")
    if not isinstance(fday, int):
        return True
    for d in t.get("developments", []) or []:
        if isinstance(d, dict) and isinstance(d.get("day"), int) and d["day"] >= fday:
            return False
    return True


def _crossing_collect_seeds():
    """Gather every LIVE seed (NPC purpose-clock + thread clock) and derive its
    strong tags (person / faction) and place context at read time. Zero-safe:
    missing/empty stores -> []."""
    seeds = []
    try:
        ndata, nerr = _load_npc_states()
    except Exception:
        ndata, nerr = {"npcs": {}}, "load failed"
    npcs = {} if nerr else ndata.get("npcs", {})

    # roster (name -> slug) used to derive thread->person tags via name-match.
    roster = []
    for _slug, _rec in npcs.items():
        _nm = (_rec.get("name", "") or "").strip()
        if _nm:
            roster.append((_slug, _nm))

    # faction universe used to derive thread->faction tags via name-match.
    try:
        fdata, ferr = _load_factions()
    except Exception:
        fdata, ferr = {"factions": {}}, "load failed"
    faction_slugs = [] if ferr else list((fdata.get("factions", {}) or {}).keys())

    # NPC seeds
    for slug, rec in npcs.items():
        if not _npc_seed_live(rec):
            continue
        pc = rec.get("purpose_clock") or {}
        seeds.append({
            "kind": "npc",
            "id": slug,
            "display": rec.get("name", slug),
            "label": pc.get("label", "their open purpose"),
            "fired": bool(pc.get("fired")),
            "fired_day": pc.get("fired_day"),
            "place": rec.get("location"),
            "persons": [slug],
            "faction": rec.get("faction"),
        })

    # thread seeds
    try:
        tdata, terr = _load_threads()
    except Exception:
        tdata, terr = {"threads": {}}, "load failed"
    threads = {} if terr else tdata.get("threads", {})
    for tid, t in threads.items():
        if not _thread_seed_live(t):
            continue
        clk = t.get("clock") or {}
        blob = " ".join(str(t.get(k, "")) for k in ("title", "description")).lower()
        blob += " " + str(clk.get("label", "")).lower()
        persons = []
        for pslug, pname in roster:
            if re.search(rf"\b{re.escape(pname.lower())}\b", blob):
                persons.append(pslug)
        faction = None
        for fslug in faction_slugs:
            if re.search(rf"\b{re.escape(fslug.lower())}\b", blob):
                faction = fslug
                break
        seeds.append({
            "kind": "thread",
            "id": tid,
            "display": t.get("title", tid),
            "label": clk.get("label", t.get("title", tid)),
            "fired": bool(clk.get("fired")),
            "fired_day": clk.get("fired_day"),
            "place": None,
            "persons": persons,
            "faction": faction,
        })
    return seeds


def _crossing_detect():
    """Group live seeds by strong tag. A person/faction tag shared by >=2
    distinct seeds is a tangle. Broad place is NEVER a trigger (it only rides
    along as context). Pure group-by -- no scoring, no judgment."""
    seeds = _crossing_collect_seeds()
    if not seeds:
        return []

    person_groups = {}   # slug -> [seed, ...]
    faction_groups = {}  # slug -> [seed, ...]
    for s in seeds:
        for pslug in s.get("persons", []) or []:
            person_groups.setdefault(pslug, []).append(s)
        if s.get("faction"):
            faction_groups.setdefault(s["faction"], []).append(s)

    # person display names from the roster
    try:
        ndata, nerr = _load_npc_states()
        npcs = {} if nerr else ndata.get("npcs", {})
    except Exception:
        npcs = {}

    tangles = []
    for slug, grp in person_groups.items():
        if len(grp) < 2:
            continue
        place = next((g.get("place") for g in grp if g.get("place")), None)
        disp = (npcs.get(slug, {}) or {}).get("name", slug)
        tangles.append({
            "tag_type": "person",
            "tag": slug,
            "display": disp,
            "seeds": grp,
            "place": place,
            "query": " ".join([disp] + [g["display"] for g in grp]),
        })
    for slug, grp in faction_groups.items():
        if len(grp) < 2:
            continue
        place = next((g.get("place") for g in grp if g.get("place")), None)
        tangles.append({
            "tag_type": "faction",
            "tag": slug,
            "display": slug,
            "seeds": grp,
            "place": place,
            "query": " ".join([slug] + [g["display"] for g in grp]),
        })
    return tangles


def _crossing_facts(tangle):
    """Forward the raw relationship FACTS the engine already stores for the
    tangled parties -- dispositions and faction standings -- verbatim. No
    verdict, no charge, no intensity. The DM judges."""
    out = []
    persons, factions = set(), set()
    for s in tangle.get("seeds", []):
        persons.update(s.get("persons", []) or [])
        if s.get("faction"):
            factions.add(s["faction"])
    if tangle.get("tag_type") == "person":
        persons.add(tangle["tag"])
    if tangle.get("tag_type") == "faction":
        factions.add(tangle["tag"])
    try:
        ndata, nerr = _load_npc_states()
        npcs = {} if nerr else ndata.get("npcs", {})
    except Exception:
        npcs = {}
    for slug in sorted(persons):
        rec = npcs.get(slug)
        if rec:
            out.append(f"{rec.get('name', slug)} disposition={rec.get('disposition', 'neutral')}")
    try:
        fdata, ferr = _load_factions()
        facs = {} if ferr else fdata.get("factions", {})
    except Exception:
        facs = {}
    for slug in sorted(factions):
        frec = facs.get(slug)
        if isinstance(frec, dict):
            out.append(f"faction {slug} rep={frec.get('rep', '?')}")
    return out


def _crossing_distillation_handle(tangle):
    """On-demand deep-history pull handle, present ONLY when a distillation
    already exists for a tangled party (spec: enrich, never found). Zero-safe:
    no cache file / no match -> None."""
    try:
        p = _DISTILLATION_CACHE_PATH
        if not p or not Path(p).exists():
            return None
        raw = json.loads(Path(p).read_text(encoding="utf-8"))
        dists = raw.get("distillations", {})
        if not dists:
            return None
        parties = {tangle.get("display", "").lower()}
        for s in tangle.get("seeds", []):
            parties.add(s.get("display", "").lower())
        parties.discard("")
        for entry in dists.values():
            blob = " ".join(
                str(x) for x in (entry.get("characters", []) + entry.get("entities", []))
            ).lower()
            if any(pp in blob for pp in parties):
                return _pf.next_block(
                    _pf.push_call("search", action="tiered",
                                  query=tangle.get("query", tangle.get("display", "")), tier=0),
                    label="deep history (distillations exist)")
        return None
    except Exception:
        return None


def _crossing_oneliner(tangle):
    """Quiet one-line co-located note for the session-start briefing."""
    kind = "person" if tangle.get("tag_type") == "person" else "faction"
    labels = ", ".join(f"*{s['label']}*" for s in tangle["seeds"])
    return (f"\U0001f517 Tangle on {kind} **{tangle['display']}** ({len(tangle['seeds'])} "
            f"live tensions): {labels}")


def _crossing_block(tangle):
    """Loud, in-scene co-located block: the seeds + forwarded relationship
    facts + a pull handle (and a distillation handle when one exists). The
    engine offers channels; the DM judges valence and volume."""
    lines = [f"**\U0001f517 Tangle on {tangle['tag_type']} {tangle['display']}** -- "
             f"{len(tangle['seeds'])} live tensions touch this "
             f"{tangle['tag_type']}; YOU judge valence + volume (silence is a valid outcome):"]
    for s in tangle["seeds"]:
        kind = "purpose" if s["kind"] == "npc" else "thread"
        fired = " [FIRED, unsurfaced]" if s.get("fired") else ""
        lines.append(f"  - ({kind}) {s['display']}: *{s['label']}*{fired}")
    facts = _crossing_facts(tangle)
    if facts:
        lines.append("  Facts (engine forwards, does not judge): " + "; ".join(facts))
    if tangle.get("place"):
        lines.append(f"  Shared place (context only): {tangle['place']}")
    lines.append("  " + _pf.next_block(
        _pf.push_call("search", action="history", query=tangle.get("query", tangle["display"])),
        label="pull related canon"))
    dh = _crossing_distillation_handle(tangle)
    if dh:
        lines.append("  " + dh)
    # Task 2 item 4: a live tangle is cultivated hidden context — mark it so the
    # spoiler hook fires (same tokens as prep secrets).
    lines.append("  " + _CULTIVATED_SECRET_MARKER)
    return "\n".join(lines)


def _crossing_time_cluster_lines():
    """§4 weak orientation crossing: when >=2 live seeds FIRED in the same
    advance_day window (same fired_day), surface one 'a lot moved while you
    were gone' line -- even with no shared entity. Orientation only; no
    judgment. Zero-safe -> []."""
    out = []
    try:
        by_day = {}
        for s in _crossing_collect_seeds():
            if s.get("fired") and isinstance(s.get("fired_day"), int):
                by_day.setdefault(s["fired_day"], []).append(s)
        for day in sorted(by_day):
            grp = by_day[day]
            if len(grp) < 2:
                continue
            who = ", ".join(s["display"] for s in grp)
            out.append(f"⏳ A lot moved around day {day}: {who} "
                       f"(orientation only -- {len(grp)} forces fired together).")
    except Exception:
        pass
    return out


def _crossing_briefing_lines():
    """Quiet orientation channel: one co-located one-liner per detected tangle,
    plus any time-cluster line, for the session-start WORLD FORCES briefing.
    Zero-safe -> []."""
    out = []
    try:
        for tangle in _crossing_detect():
            out.append(_crossing_oneliner(tangle))
    except Exception:
        pass
    out.extend(_crossing_time_cluster_lines())
    return out


def _crossing_blocks_for_npc(slug):
    """Loud channel: rendered co-located blocks for every tangle that involves
    this NPC -- either as the person tag or as a tagged party on a seed. Used
    by check_canon's always-runs NPC injection. Zero-safe -> []."""
    if not slug:
        return []
    key = slug.lower().strip()
    out = []
    try:
        for tangle in _crossing_detect():
            involved = (tangle.get("tag_type") == "person" and tangle.get("tag") == key)
            if not involved:
                for s in tangle.get("seeds", []):
                    if key in [p.lower() for p in (s.get("persons", []) or [])]:
                        involved = True
                        break
            if involved:
                out.append(_crossing_block(tangle))
    except Exception:
        pass
    return out


def _npc_record_death(npc_name: str, death_day: int) -> str:
    """Record an NPC's death (DM ruling). Sets status=DEAD + death_day on the dossier,
    which the settlement who's-around overlay surfaces as 'dead since Day N'. NPC-only;
    does not touch PC/follower/mercenary death seams."""
    if not npc_name:
        return "record_death requires 'name'."
    if not death_day:
        death_day = get_current_day_safe() or 0
    import ceruline_reader as _cr
    data, err = _load_npc_states()
    if err:
        raise ToolError(err)
    npcs = data.setdefault("npcs", {})
    key = npc_name.lower().strip()
    # Match an existing record by identity (title-insensitive) before creating a new
    # one — recording "Matriarch Amara Vane" must update the stored
    # "amara vane" record, not spawn a ghost duplicate.
    if key not in npcs:
        target_id = _cr.identity_key(npc_name)
        for existing_key in npcs:
            if _cr.identity_key(existing_key) == target_id:
                key = existing_key
                break
    rec = npcs.get(key, {"name": npc_name.strip(), "history": []})
    already_dead = str(rec.get("status", "")).upper() == "DEAD"
    rec["status"] = "DEAD"
    rec["death_day"] = death_day
    if not isinstance(rec.get("history"), list):
        rec["history"] = []
    if not already_dead:
        rec["history"].append({"type": "death", "day": death_day})
    npcs[key] = rec
    _save_npc_states(data)
    return (f"[DM-ONLY] ✓ {rec.get('name', npc_name)} recorded dead (Day {death_day}). "
            f"Will show †dead in who's-around.")


def _npc_set(npc_name: str, disposition: str, knows: str, wants: str, secret: str, location: str, last_day: int) -> str:
    data, err = _load_npc_states()
    if err:
        raise ToolError(err)
    key = npc_name.lower().strip()
    existing = data.get('npcs', {}).get(key, {})
    state = {
        "name": npc_name.strip(),
        "disposition": disposition.strip() if disposition else existing.get('disposition', 'neutral'),
        "knows": [k.strip() for k in knows.split(';') if k.strip()] if knows else existing.get('knows', []),
        "wants": wants.strip() if wants else existing.get('wants', ''),
        "secret": secret.strip() if secret else existing.get('secret', ''),
        "location": location.strip() if location else existing.get('location', 'unknown'),
        "last_seen_day": last_day if last_day else existing.get('last_seen_day', 0),
        "history": existing.get('history', [])
    }
    if existing and existing.get('disposition') != state['disposition'] and disposition:
        state['history'].append({"type": "disposition_change", "from": existing.get('disposition'), "to": state['disposition'], "day": last_day})
    data['npcs'][key] = state
    _save_npc_states(data)

    # Auto-populate lorebook + ChromaDB for new NPCs
    npc_key = npc_name.strip().lower()
    try:
        lorebook_path = CAMPAIGN_DIR / "lorebook.json"
        if lorebook_path.exists():
            lb = json.loads(lorebook_path.read_text(encoding='utf-8'))
            existing_keywords = set()
            for entry in lb.get('entries', []):
                for kw in entry.get('keywords', []):
                    existing_keywords.add(kw.strip().lower())

            if npc_key not in existing_keywords:
                # Build richest possible context from available NPC data
                ctx_parts = [f"{npc_name.strip()} ({state['disposition']})."]
                if state.get('wants'):
                    ctx_parts.append(f"Wants: {state['wants']}.")
                if state.get('location') and state['location'] != 'unknown':
                    ctx_parts.append(f"Location: {state['location']}.")
                if state.get('knows'):
                    knows_str = '; '.join(state['knows'][:3])  # Cap at 3 facts
                    ctx_parts.append(f"Knows: {knows_str}.")
                full_context = ' '.join(ctx_parts)

                # Short context: name + disposition + wants (one line)
                short_parts = [f"{npc_name.strip()} ({state['disposition']})."]
                if state.get('wants'):
                    short_parts.append(state['wants'][:80])
                short_ctx = ' '.join(short_parts)

                new_entry = {
                    "keywords": [npc_key],
                    "category": "people",
                    "status": "ESTABLISHED",
                    "short_context": short_ctx,
                    "context": full_context,
                    "source": "npc_auto_index"
                }
                lb['entries'].append(new_entry)
                lorebook_path.write_text(json.dumps(lb, indent=2, ensure_ascii=False), encoding='utf-8')
                logging.info(f"Auto-indexed {npc_name} to lorebook")
    except Exception as e:
        logging.warning(f"Lorebook auto-index failed for {npc_name}: {e}")

    # Index to ChromaDB
    try:
        collection = get_chroma_collection("campaign_history_tiered")
        # Build description from available NPC data
        chroma_parts = [f"{npc_name.strip()} ({state['disposition']})."]
        if state.get('wants'):
            chroma_parts.append(f"Wants: {state['wants']}.")
        if state.get('location') and state['location'] != 'unknown':
            chroma_parts.append(f"Location: {state['location']}.")
        if state.get('knows'):
            chroma_parts.append(f"Knows: {'; '.join(state['knows'][:3])}.")
        chroma_description = ' '.join(chroma_parts)
        # This card is being STORED (a document), not searched (a query) — must use
        # the document-prefix embedder. get_embedding_cached applies the query prefix
        # and is for QUERIES only; using it here silently degraded retrieval quality
        # for every auto-indexed NPC card.
        embedding = get_ollama_embedding_sync(chroma_description)
        doc_id = f"npc_{npc_key.replace(' ', '_')}"
        card_day = state.get('last_seen_day') or get_current_day_safe() or 0
        collection.upsert(
            documents=[chroma_description],
            embeddings=[embedding],
            metadatas=[_stringify_metadata({
                "source": "npc_auto_index",
                "tier": "2",
                "characters": npc_name.strip(),
                "day": card_day,
                "arc": "current",
                "scene_type": _infer_scene_type(chroma_description),
            })],
            ids=[doc_id]
        )
        logging.info(f"Auto-indexed {npc_name} to ChromaDB")
    except Exception as e:
        logging.warning(f"ChromaDB auto-index failed for {npc_name}: {e}")

    return f"[DM-ONLY] NPC state: {npc_name} (disposition: {state['disposition']})"


def _npc_get(npc_name: str, strip_secrets: bool = False) -> str:
    data, err = _load_npc_states()
    if err:
        raise ToolError(err)
    key = npc_name.lower().strip()
    npc = data.get('npcs', {}).get(key)
    if not npc:
        return f"[DM-ONLY] No state for '{npc_name}'"
    output = [f"# [DM-ONLY] {npc.get('name')}", "", f"**Disposition:** {npc.get('disposition', 'neutral')}",
              f"**Location:** {npc.get('location', 'unknown')}", f"**Last Seen:** Day {npc.get('last_seen_day', '?')}"]
    if npc.get('wants'):
        output.append(f"**Wants:** {npc['wants']}")
    if npc.get('secret') and not strip_secrets:
        output.append(f"**Secret:** {npc['secret']}")
    if npc.get('knows'):
        output.extend(["", "**Knows:**"] + [f"- {k}" for k in npc['knows']])
    return "\n".join(output)


def _npc_add_knowledge(npc_name: str, knowledge: str, learned_day: int) -> str:
    data, err = _load_npc_states()
    if err:
        raise ToolError(err)
    key = npc_name.lower().strip()
    if key not in data.get('npcs', {}):
        raise ToolError(f"NPC '{npc_name}' not found. Use npc(action='set') first.")
    npc = data['npcs'][key]
    k = knowledge.strip()
    if k not in npc.get('knows', []):
        npc['knows'].append(k)
        npc['history'].append({"type": "learned", "what": k, "day": learned_day})
    _save_npc_states(data)
    return f"[DM-ONLY] {npc_name} now knows: {k}"


def _npc_list(disposition_filter: str = "") -> str:
    data, err = _load_npc_states()
    if err:
        raise ToolError(err)
    npcs = data.get('npcs', {})
    if not npcs:
        return "[DM-ONLY] No NPCs tracked."
    output = ["# [DM-ONLY] Tracked NPCs", ""]
    filt = disposition_filter.lower().strip() if disposition_filter else ""
    for key, npc in sorted(npcs.items()):
        disp = npc.get('disposition', 'neutral')
        if filt and filt != disp:
            continue
        output.append(f"- **{npc.get('name')}** [{disp}] @ {npc.get('location', 'unknown')}")
    return "\n".join(output)


# ============================================
# ANTAGONIST CULTIVATION
# ============================================

@mcp.tool(
    annotations={"readOnlyHint": False, "idempotentHint": False},
    tags=_get_tool_tags("antagonist")
)
def antagonist(
    action: str = Field(description="add_threat|add_seed|escalate|view|prune|validate"),
    threat_name: str = Field(default=None, description="Name of threat/seed"),
    escalation: str = Field(default="low", description="low|med|high|crisis"),
    details: str = Field(default="", description="Terse details (keep under 150 chars)"),
    day: int = Field(default=None, description="Day for timestamp"),
    due_day: int = Field(default=None, description="spine: campaign day this seed/threat comes DUE (advance_day fires it once). Omit for no time-clock."),
    trigger: str = Field(default="", description="spine: comma keywords that surface this seed mid-scene in check_canon (e.g. 'northeast,standing stones'). Omit for no trigger."),
    pace: str = Field(default="", description="spine: alternative to due_day — a pace word (still|cool|warm|hot) mapped to a due_day from the seed's day. still/blank = no clock."),
) -> str:
    """Reach for this WHEN a threat needs to be seeded, escalated from dormant to active, or you want to review the cultivation board between sessions.

    Manual antagonist cultivation tool. DM-only, never shown to player.

    Actions:
    - add_threat: Add to ACTIVE THREATS
    - add_seed: Add to DORMANT SEEDS
    - escalate: Move seed from DORMANT → ACTIVE
    - view: Show full cultivation file (redacted for player safety)
    - prune: Remove specific seed
    - validate: Health-check the cultivation file (structure + staleness)

    Use when manually tracking threats outside of save_state automation.
    """
    # TASK 11: Validate escalation parameter for actions that use it
    if action in ["add_threat", "escalate"]:
        valid_escalations = ["low", "med", "high", "crisis"]
        if escalation not in valid_escalations:
            raise ToolError(f"Invalid escalation: '{escalation}'. Must be one of: {', '.join(valid_escalations)}")

    # Validate action parameter
    valid_actions = ["add_threat", "add_seed", "escalate", "view", "prune", "validate"]
    if action not in valid_actions:
        raise ToolError(f"Unknown action: {action}. Must be one of: {', '.join(valid_actions)}")

    if not day:
        day = get_current_day_safe() or 0
    # Coerce Field sentinel defaults (tests call the function directly, bypassing MCP unwrapping)
    if not isinstance(due_day, int):
        due_day = None
    if not isinstance(trigger, str):
        trigger = ""
    if not isinstance(pace, str):
        pace = ""

    cult_content = _load_cultivation()

    if action == "view":
        # Calculate metrics
        active_count = len(re.findall(r'### .+ - Escalation:', cult_content))
        dormant_count = len(re.findall(r'### .+ - Day planted: \d+', cult_content))

        # Find oldest seed
        oldest_age = 0
        oldest_name = None
        for match in re.finditer(r'### (.+?) - Day planted: (\d+)', cult_content):
            seed_name = match.group(1)
            planted_day = int(match.group(2))
            age = day - planted_day
            if age > oldest_age:
                oldest_age = age
                oldest_name = seed_name

        approx_tokens = len(cult_content) / 3.5

        metrics = f"""# ANTAGONIST CULTIVATION METRICS (Day {day})

Active threats: {active_count}
Dormant seeds: {dormant_count}
Oldest seed: {oldest_name if oldest_name else 'None'} ({oldest_age} days old)
Token usage: ~{approx_tokens:.0f} / 2000 tokens
File size: {len(cult_content)} / 6500 chars

---

"""
        return metrics + cult_content

    elif action == "add_threat":
        if not threat_name:
            raise ToolError("threat_name required for add_threat")

        # Find ACTIVE THREATS section
        threats_match = re.search(
            r'(## ACTIVE THREATS.*?\n)(.*?)(?=\n## |$)',
            cult_content,
            re.DOTALL
        )

        if threats_match:
            header = threats_match.group(1)
            existing = threats_match.group(2).strip()

            # Build threat entry (terse format)
            threat_entry = f"""
### {threat_name} - Escalation: {escalation.upper()}
- Planted: Day {day}
- {details}
"""

            if existing == "[None yet]":
                new_content = threat_entry
            else:
                new_content = existing + "\n" + threat_entry

            cult_content = cult_content[:threats_match.start()] + \
                          header + "\n" + new_content + "\n" + \
                          cult_content[threats_match.end():]

            # spine (spec 2026-06-18): attach a machine-readable clock/trigger tag
            _due = due_day if isinstance(due_day, int) else _pace_to_due_day(pace, day)
            _spine = {
                "due_day": _due,
                "trigger": [t.strip().lower() for t in (trigger or "").split(",") if t.strip()],
                "level": escalation,
                "fired": False,
                "fired_day": None,
            }
            cult_content = _antag_set_spine(cult_content, threat_name, _spine)

            _save_cultivation(cult_content)
            return f"Threat added: {threat_name} ({escalation})"

    elif action == "add_seed":
        if not threat_name:
            raise ToolError("threat_name required for add_seed")

        # Find DORMANT SEEDS section
        seeds_match = re.search(
            r'(## DORMANT SEEDS.*?\n)(.*?)(?=\n## |$)',
            cult_content,
            re.DOTALL
        )

        if seeds_match:
            header = seeds_match.group(1)
            existing = seeds_match.group(2).strip()

            seed_entry = f"""
### {threat_name} - Day planted: {day}
- {details}
"""

            if existing == "[None yet]":
                new_content = seed_entry
            else:
                new_content = existing + "\n" + seed_entry

            cult_content = cult_content[:seeds_match.start()] + \
                          header + "\n" + new_content + "\n" + \
                          cult_content[seeds_match.end():]

            # spine (spec 2026-06-18): attach a machine-readable clock/trigger tag
            _due = due_day if isinstance(due_day, int) else _pace_to_due_day(pace, day)
            _spine = {
                "due_day": _due,
                "trigger": [t.strip().lower() for t in (trigger or "").split(",") if t.strip()],
                "level": escalation,
                "fired": False,
                "fired_day": None,
            }
            cult_content = _antag_set_spine(cult_content, threat_name, _spine)

            _save_cultivation(cult_content)
            return f"Seed planted: {threat_name} (Day {day})"

    elif action == "escalate":
        if not threat_name:
            raise ToolError("threat_name required for escalate")

        # Find seed in DORMANT SEEDS
        seed_pattern = rf'### {re.escape(threat_name)} - Day planted: (\d+)\n(.*?)(?=\n### |\n## |$)'
        seed_match = re.search(seed_pattern, cult_content, re.DOTALL)

        if not seed_match:
            raise ToolError(f"Seed '{threat_name}' not found in DORMANT SEEDS")

        planted_day = int(seed_match.group(1))
        original_content = seed_match.group(2).strip()  # Preserve original details

        # Check if already in ACTIVE THREATS
        threat_pattern = rf'### {re.escape(threat_name)} - Escalation:'
        if re.search(threat_pattern, cult_content):
            return f"Threat '{threat_name}' already in ACTIVE THREATS"

        # Remove from DORMANT SEEDS
        cult_content = re.sub(seed_pattern, '', cult_content, flags=re.DOTALL)

        # Add to ACTIVE THREATS with BOTH original and new context
        dormant_duration = day - planted_day
        threat_entry = f"""### {threat_name} - Escalation: {escalation.upper()}
- Origin: Day {planted_day} (dormant {dormant_duration} days)
- Escalated: Day {day}
{original_content}
- ESCALATION: {details}
"""

        # Insert into ACTIVE THREATS section
        threats_match = re.search(r'(## ACTIVE THREATS.*?\n)(.*?)(?=\n## |$)', cult_content, re.DOTALL)
        if threats_match:
            threats_content = threats_match.group(2)
            if "[None yet]" in threats_content:
                new_threats = threat_entry
            else:
                new_threats = threats_content.strip() + "\n\n" + threat_entry

            # Use string concatenation instead of rf-string to avoid escaping issues
            replacement = threats_match.group(1) + new_threats + "\n"
            cult_content = cult_content[:threats_match.start()] + replacement + cult_content[threats_match.end():]

        # Log escalation
        log_match = re.search(
            r'(## ESCALATION LOG.*?\n)(.*?)(?=\n## |$)',
            cult_content,
            re.DOTALL
        )
        if log_match:
            log_header = log_match.group(1)
            log_existing = log_match.group(2).strip()

            log_entry = f"Day {day}: {threat_name} escalated from dormant → {escalation}"

            if log_existing == "[None yet]":
                new_log = log_entry
            else:
                new_log = log_existing + "\n" + log_entry

            cult_content = cult_content[:log_match.start()] + \
                          log_header + "\n" + new_log + "\n" + \
                          cult_content[log_match.end():]

        # spine: re-arm the clock for the NEXT rung (fired cleared) -- the DM walks
        # the ladder, the engine just re-clocks (spec §4.5).
        _due = due_day if isinstance(due_day, int) else _pace_to_due_day(pace, day)
        _spine = {
            "due_day": _due,
            "trigger": [t.strip().lower() for t in (trigger or "").split(",") if t.strip()],
            "level": escalation,
            "fired": False,
            "fired_day": None,
        }
        cult_content = _antag_set_spine(cult_content, threat_name, _spine)

        _save_cultivation(cult_content)
        return f"Escalated '{threat_name}' to {escalation.upper()} on Day {day} (dormant {dormant_duration} days)"

    elif action == "prune":
        if not threat_name:
            raise ToolError("threat_name required for prune")

        # Remove from DORMANT SEEDS
        seed_pattern = rf'### {re.escape(threat_name)} - Day planted: \d+\n.*?(?=\n### |\n## |$)'
        cult_content = re.sub(seed_pattern, '', cult_content, flags=re.DOTALL)

        # TASK 8: Also remove from ESCALATION LOG
        escalation_pattern = rf'Day \d+: .*?{re.escape(threat_name)}.*?\n'
        cult_content = re.sub(escalation_pattern, '', cult_content, flags=re.MULTILINE)

        # Log prune
        prune_match = re.search(
            r'(## PRUNING LOG.*?\n)(.*?)(?=\n## |$)',
            cult_content,
            re.DOTALL
        )
        if prune_match:
            prune_header = prune_match.group(1)
            prune_existing = prune_match.group(2).strip()

            prune_entry = f"- Day {day}: Pruned '{threat_name}' (manual)"

            if prune_existing == "[None yet]":
                new_prune = prune_entry
            else:
                new_prune = prune_existing + "\n" + prune_entry

            cult_content = cult_content[:prune_match.start()] + \
                          prune_header + "\n" + new_prune + "\n" + \
                          cult_content[prune_match.end():]

        _save_cultivation(cult_content)
        return f"Pruned: {threat_name}"

    elif action == "validate":
        """Check cultivation file health and report issues."""
        issues = []

        # Check 1: File size (token budget)
        char_count = len(cult_content)
        if char_count > 6500:
            issues.append(f"⚠️ File size {char_count} chars exceeds 6500 char limit")

        # Check 2: Required sections present
        required_sections = [
            "## ACTIVE THREATS",
            "## DORMANT SEEDS",
            "## ESCALATION LOG",
            "## OPPORTUNITIES",
            "## PRUNING LOG"
        ]
        missing_sections = [sec for sec in required_sections if sec not in cult_content]
        if missing_sections:
            issues.append(f"⚠️ Missing sections: {', '.join(missing_sections)}")

        # Check 3: Validate day monotonicity in escalation log
        escalation_days = []
        for match in re.finditer(r'Day (\d+):', cult_content):
            escalation_days.append(int(match.group(1)))

        if escalation_days and escalation_days != sorted(escalation_days):
            issues.append("⚠️ Escalation log has non-monotonic days (time travel detected)")

        # Check 4: Orphaned seeds (seeds with malformed headers)
        seed_pattern = r'### (.+?) - Day planted: (\d+)'
        seed_matches = list(re.finditer(seed_pattern, cult_content))
        for match in seed_matches:
            seed_name = match.group(1)
            planted_day = int(match.group(2))
            if planted_day > day:
                issues.append(f"⚠️ Seed '{seed_name}' planted in future (Day {planted_day} > {day})")

        # Check 5: Active threats missing escalation level
        threat_pattern = r'### (.+?) - Escalation: (\w+)'
        threat_matches = list(re.finditer(threat_pattern, cult_content))
        for match in threat_matches:
            threat_name = match.group(1)
            escalation_level = match.group(2).lower()
            if escalation_level not in ['low', 'med', 'high', 'crisis']:
                issues.append(f"⚠️ Threat '{threat_name}' has invalid escalation: {escalation_level}")

        # Generate report
        if issues:
            report = f"VALIDATION FAILED ({len(issues)} issues):\n\n" + "\n".join(issues)
        else:
            active_count = len(threat_matches)
            dormant_count = len(seed_matches)
            approx_tokens = char_count / 3.5
            report = f"""VALIDATION PASSED [OK]

File health: Good
Active threats: {active_count}
Dormant seeds: {dormant_count}
File size: {char_count} / 6500 chars
Token usage: ~{approx_tokens:.0f} / 2000 tokens
All required sections present
Day monotonicity validated
"""

        return report

    else:
        raise ToolError(f"Unknown action: {action}. Use add_threat|add_seed|escalate|view|prune")


# ============================================
# ANTI-PATTERN CHECKER
# ============================================


def _check_anti_patterns(
    text: str = Field(description="Narrative text to check for anti-patterns"),
    character_names: str = Field(default="", description="Comma-separated character names in the scene")
) -> str:
    """Check narrative for anti-patterns. Use before finalizing narration to catch common writing issues."""
    warnings = []
    text_lower = text.lower()

    # Check trigger-based patterns
    for pattern_id, pattern in ANTI_PATTERNS.items():
        for trigger in pattern.get('triggers', []):
            if trigger in text_lower:
                warnings.append({
                    "pattern": pattern_id,
                    "description": pattern['description'],
                    "trigger": trigger,
                    "suggestion": pattern['suggestion']
                })
                break  # Only one warning per pattern

    # Check talking heads (dialogue without action)
    dialogue_count = text.count('"') // 2  # Rough estimate of dialogue exchanges
    action_words = ['walked', 'moved', 'grabbed', 'looked', 'turned', 'reached', 'stood', 'sat', 'leaned']
    action_count = sum(1 for word in action_words if word in text_lower)

    if dialogue_count >= 4 and action_count < 2:
        warnings.append({
            "pattern": "talking_heads",
            "description": ANTI_PATTERNS['talking_heads']['description'],
            "trigger": f"{dialogue_count} dialogue exchanges, only {action_count} action verbs",
            "suggestion": ANTI_PATTERNS['talking_heads']['suggestion']
        })

    # Check over-naming
    if character_names:
        names = [n.strip().lower() for n in character_names.split(',')]
        for name in names:
            # Count name occurrences per ~500 chars (rough paragraph)
            count = text_lower.count(name)
            text_length = len(text)
            if text_length > 0 and count > 0:
                names_per_500 = (count / text_length) * 500
                if names_per_500 > 3:  # More than 3 times per 500 chars
                    warnings.append({
                        "pattern": "over_naming",
                        "description": f"'{name}' used {count} times in {text_length} chars",
                        "trigger": f"~{names_per_500:.1f} uses per paragraph",
                        "suggestion": ANTI_PATTERNS['over_naming']['suggestion']
                    })

    if not warnings:
        return "✓ No anti-patterns detected in this text."

    output = [f"⚠ Found {len(warnings)} potential anti-pattern(s):", ""]

    for w in warnings:
        output.append(f"**{w['pattern'].replace('_', ' ').title()}**")
        output.append(f"  Issue: {w['description']}")
        output.append(f"  Detected: {w['trigger']}")
        output.append(f"  Suggestion: {w['suggestion']}")
        output.append("")

    return "\n".join(output)


def _list_anti_patterns() -> str:
    """List all anti-patterns. Use to see what writing issues narrative_qa(action='check') detects."""
    output = ["# Narrative Anti-Patterns", ""]
    output.append("These patterns are checked by `narrative_qa(action='check')`:")

    for pattern_id, pattern in ANTI_PATTERNS.items():
        output.append(f"## {pattern_id.replace('_', ' ').title()}")
        output.append(f"{pattern['description']}")
        if pattern.get('triggers'):
            output.append(f"Triggers: {', '.join(pattern['triggers'][:3])}...")
        output.append(f"Fix: {pattern['suggestion']}")
        output.append("")

    return "\n".join(output)


# ============================================
# PRE-OUTPUT PROSE VALIDATION
# ============================================


def _run_prose_evolution():
    """Thin seam around the prose blacklist evolver (monkeypatched in tests).

    2026-07-19: also feeds the campaign's rolling narration window into the
    template scan, so recurring CONSTRUCTIONS (not just literal phrases) get
    nominated into blacklist.json template_nominations for owner review —
    the durable fix for the prose mutating around literal bans."""
    try:
        from hooks.blacklist_evolver import run_evolution, run_template_scan
    except ImportError:
        from blacklist_evolver import run_evolution, run_template_scan
    result = run_evolution()
    try:
        from rubicon_paths import prose_window_path
        wpath = prose_window_path()
        if wpath.exists():
            samples = []
            for line in wpath.read_text(encoding="utf-8").splitlines():
                try:
                    t = json.loads(line).get("text", "")
                except Exception:
                    continue
                # strip markdown furniture (bullets/table pipes) so the frame
                # counter sees prose, not formatting
                t = re.sub(r"^\s*[-*•]\s+", "", t, flags=re.MULTILINE)
                t = t.replace("|", " ")
                if t.strip():
                    samples.append(t)
            if samples:
                run_template_scan(samples)
    except Exception as e:
        logging.debug(f"template scan skipped (non-fatal): {e}")
    return result


def _evolve_prose_blacklist_safe():
    """Run the prose blacklist evolution as a fail-safe side-effect of committing a session.
    Returns the evolution summary dict, or None on any error (a broken evolver must NEVER
    break a save)."""
    try:
        return _run_prose_evolution()
    except Exception as e:
        logging.debug(f"prose evolution skipped: {e}")
        return None


_VALIDATE_PROSE_BLACKLIST = None
_VALIDATE_PROSE_SPARINGLY = None
_VALIDATE_PROSE_STRUCTURAL = None
_VALIDATE_PROSE_BL_MTIME = 0


def _load_prose_patterns():
    """Load and cache blacklist patterns for narrative_qa(action='validate')."""
    global _VALIDATE_PROSE_BLACKLIST, _VALIDATE_PROSE_SPARINGLY, _VALIDATE_PROSE_STRUCTURAL, _VALIDATE_PROSE_BL_MTIME
    bl_path = Path(__file__).parent / "hooks" / "blacklist.json"
    if not bl_path.exists():
        return [], [], []
    mtime = bl_path.stat().st_mtime
    if mtime == _VALIDATE_PROSE_BL_MTIME and _VALIDATE_PROSE_BLACKLIST is not None:
        return _VALIDATE_PROSE_BLACKLIST, _VALIDATE_PROSE_SPARINGLY, _VALIDATE_PROSE_STRUCTURAL
    try:
        data = json.loads(bl_path.read_text(encoding="utf-8"))
        blacklisted = data.get("blacklisted_phrases", [])
        sparingly = data.get("use_sparingly", [])
        structural = data.get("structural_patterns", [])
    except (json.JSONDecodeError, IOError):
        return [], [], []
    compiled_bl = []
    compiled_sp = []
    compiled_st = []
    for phrase in blacklisted:
        pat = rf"\b{re.escape(phrase)}\b" if not any(c in phrase for c in r"\[](){}*+?|^$") else rf"\b{phrase}\b"
        try:
            compiled_bl.append((re.compile(pat, re.IGNORECASE), phrase))
        except re.error:
            continue
    for phrase in sparingly:
        pat = rf"\b{re.escape(phrase)}\b" if not any(c in phrase for c in r"\[](){}*+?|^$") else rf"\b{phrase}\b"
        try:
            compiled_sp.append((re.compile(pat, re.IGNORECASE), phrase))
        except re.error:
            continue
    for entry in structural:
        pat_str = entry.get("pattern", "")
        category = entry.get("category", "Unknown")
        if not pat_str:
            continue
        try:
            compiled_st.append((re.compile(pat_str, re.IGNORECASE), category))
        except re.error:
            continue
    _VALIDATE_PROSE_BLACKLIST = compiled_bl
    _VALIDATE_PROSE_SPARINGLY = compiled_sp
    _VALIDATE_PROSE_STRUCTURAL = compiled_st
    _VALIDATE_PROSE_BL_MTIME = mtime
    return compiled_bl, compiled_sp, compiled_st


# ---- narrative_qa(validate) helpers (replicate stop-hook text scanning) ----

_VP_DIALOGUE_OR_BOND_RE = re.compile(
    r'"[^"]*"'          # double-quoted dialogue
    r"|"
    r"\*[^*]+\*",       # italicized bond/telepathy text
    re.DOTALL,
)

_VP_BACKSTORY_PATTERNS = [
    re.compile(p, re.IGNORECASE | re.MULTILINE) for p in [
        r"(the )?(first time|when) (we|I|you) (met|saw|encountered|found)",
        r"(remember when|do you remember|you remember) (we|I|you)",
        r"(the day|the night|the moment) (we|I|you) (first|met|found)",
        r"(we|I) (used to|always|never) (be|have|do|say|think)",
        r"(back when|before we) (we|I|you|the party)",
        r"(I|we) (once|always|never) (did|said|was|were|had)",
        r"(that was|it was) (the|when|how|why) (we|I|you)",
        r"(since|after|before) (that day|we met|I found|you left)",
        r"(how we|when we|where we) (met|started|began|first)",
        r"(our first|my first) (meeting|encounter|time together)",
    ]
]

def _vp_party_names() -> set:
    """Party-member names to skip in the unverified-NPC scan, derived from the
    live character roster (characters.json) so it tracks any campaign's cast
    rather than a hardcoded party. Returns an empty set on load failure."""
    try:
        data, err = _load_characters()
        if not err and data:
            return {c.get("name", "") for c in data.get("characters", {}).values()
                    if c.get("name")}
    except Exception:
        pass
    return set()

_VP_FALSE_POSITIVE_NAMES = {
    "quill", "sage", "veil", "grace", "dawn", "ash", "ember",
    "oracle", "anchor", "reed", "mason", "hunter", "herald",
}


def _vp_strip_dialogue(text: str) -> str:
    """Strip quoted dialogue and *bond* text before scanning."""
    return _VP_DIALOGUE_OR_BOND_RE.sub("", text)


def _vp_check_npc_mentions(text: str) -> list[str]:
    """SOFTENED (Day-130 play report): a canonical NPC is paintable — return nothing.

    This check only ever considered names that ALREADY exist in the canonical NPC
    store (``npc_states.json``). So every name it could possibly flag is a real,
    recorded NPC — never a fabrication (an invented name isn't in the store, so it
    never reaches this scan in the first place). The old behavior hard-blocked the
    DM from narrating a *known* NPC until a per-scene "verify" ceremony cleared a
    roster that the normal flow never updated — which made it **unsatisfiable** for
    any NPC who legitimately walks into a scene mid-session (e.g. a surgeon arriving
    to take readings). It also caught zero actual fabrication.

    Fact-accuracy for known NPCs is already handled by the fact judge
    (``_vp_call_fact_judge``, run when a known canon name appears). So mentioning an
    NPC who has a canonical record is allowed: we surface nothing to block on here.

    Kept as a seam: if a genuine fabrication signal is ever wanted, this is where a
    "proper-noun NPC reference with NO canonical record" detector would live (a
    different, NER-style check — not the store-membership scan this used to be).
    """
    return []


def _vp_check_backstory(text: str) -> list[str]:
    """Scan for backstory hallucination patterns, return matched snippets."""
    try:
        cleaned = _vp_strip_dialogue(text)
        matches = []
        for pattern in _VP_BACKSTORY_PATTERNS:
            for match in pattern.finditer(cleaned):
                snippet = match.group(0)
                if len(snippet) < 20:
                    continue
                matches.append(snippet[:80])
        return matches
    except Exception:
        return []


def _vp_check_dialogue_claims(text: str) -> list[tuple]:
    """Check factual claims inside dialogue against distillation cache."""
    try:
        import sys
        hooks_dir = str(Path(__file__).parent / "hooks")
        if hooks_dir not in sys.path:
            sys.path.insert(0, hooks_dir)
        from dialogue_claim_scanner import detect_claims_in_response
        from distillation_cache import DistillationCache

        claims = detect_claims_in_response(text)
        if not claims:
            return []

        cache_path = _DISTILLATION_CACHE_PATH  # campaign-scoped + respects test monkeypatch (was an independent engine-relative re-derivation)
        cache = DistillationCache(cache_path)

        all_facts_blob = "\n".join(
            " | ".join(entry.get("key_facts", []))
            for entry in cache.all_entries()
        ).lower()

        unverified = []
        for claim_type, claim_text in claims:
            if claim_text.lower() in all_facts_blob:
                continue
            bare = re.search(r'\b(\d+)\b', claim_text)
            if bare and bare.group(0) in all_facts_blob:
                continue
            unverified.append((claim_type, claim_text))
        return unverified
    except Exception:
        return []


def _vp_check_fabrication_bans(text: str) -> list[str]:
    """Hard-block any draft that re-asserts a permanently banned claim."""
    try:
        hits = _get_fabrication_bans().check_draft(text)
    except Exception:
        return []
    out = []
    for b in hits:
        out.append(
            f'NEVER-AGAIN: "{b["entity"]}" + {", ".join(b["wrong_terms"])} is a permanently '
            f'corrected error. Truth: {b["correct_fact"]} Rewrite without it.'
        )
    return out


def _vp_check_petnames(text: str) -> list[str]:
    try:
        try:
            from hooks.fabrication_detectors import check_pet_names
        except ImportError:
            from fabrication_detectors import check_pet_names
        return check_pet_names(text)
    except Exception:
        return []


def _vp_check_tripwires(text: str) -> list[str]:
    try:
        try:
            from hooks.fabrication_detectors import check_tripwires
        except ImportError:
            from fabrication_detectors import check_tripwires
        return check_tripwires(text)
    except Exception:
        return []


_DM_NOUN_CACHE = {"key": None, "nouns": frozenset()}

# Common capitalized/markdown artifacts that must never be treated as invented
# DM-only proper nouns (would false-positive-block ordinary prep prose).
_DM_NAME_STOPWORDS = frozenset({
    "the", "this", "that", "these", "those", "never", "reveal", "revealed",
    "only", "secret", "secrets", "truth", "notes", "hidden", "when", "what",
    "who", "why", "how", "room", "rooms", "zone", "zones", "day", "dm", "gm",
    "end", "truth", "note", "npc", "npcs", "pc", "pcs", "encounter",
    "encounters", "loot", "trap", "traps", "scope", "state", "description",
    "name", "connections", "entrance", "floor", "coords", "roll", "every",
    "turn", "dm only", "if", "then", "must", "will", "can", "should", "party",
    "player", "players", "dungeon", "master", "true", "guardian", "living",
    "vaarn",  # the setting name — never a campaign secret
    # Common English nouns that show up capitalized-only in terse prep prose
    # (labels, sentence fragments). A villain literally named one of these
    # slips through — accepted: false positives BLOCK live play, false
    # negatives just mean one exotic name isn't machine-guarded.
    "evidence", "adaptation", "era", "eras", "visitor", "visitors",
    "depletion", "history", "memory", "memories", "pattern", "patterns",
    "purpose", "nature", "source", "sources", "energy", "water", "light",
    "darkness", "silence", "stone", "metal", "glass", "blood", "death",
    "life", "time", "place", "world", "city", "desert", "night", "morning",
    "power", "mind", "body", "voice", "word", "words", "story", "stories",
    "sign", "signs", "mark", "marks", "path", "paths", "road", "door",
    "doors", "wall", "walls", "ceiling", "chamber", "chambers", "hall",
    "halls", "garden", "gardens", "machine", "machines", "engine", "engines",
    "core", "heart", "eye", "eyes", "hand", "hands", "child", "children",
    "woman", "women", "man", "men", "people", "king", "queen", "lord",
    "lady", "stakes", "layers", "hook", "hooks", "collapse", "crossing",
    "compact", "surface", "network", "system", "systems", "starvation",
})


def _normalize_prep_ref(raw: str) -> list[str]:
    """Candidate relative filenames from a raw **Active Prep:** value, in
    priority order:
      1. the value verbatim (back-compat for exact paths),
      2. the value truncated at the first ` (` and stripped (drops the
         `(Node 13 expedition — …)` display parenthetical),
      3. candidate 2 with `.md` appended when it doesn't already end in `.md`.
    Empty / `none` / `(none)` (case-insensitive) -> []. Never raises."""
    if not raw:
        return []
    raw = raw.strip()
    if not raw or raw.lower() in ("none", "(none)"):
        return []
    candidates = [raw]
    truncated = raw.split(" (", 1)[0].strip()
    if truncated and truncated not in candidates:
        candidates.append(truncated)
    if truncated and not truncated.lower().endswith(".md"):
        with_md = truncated + ".md"
        if with_md not in candidates:
            candidates.append(with_md)
    return candidates


def _resolve_active_prep_path() -> Path | None:
    """The active prep file as an EXISTING path, or None.

    Source order (unchanged): GAME_STATE['active_prep_file'] first, falling back
    to CURRENT_STATUS.md's **Active Prep:** line (the same reader check_canon's
    prep block uses) only when the field is empty. Each raw value is run through
    _normalize_prep_ref, and the FIRST candidate whose CAMPAIGN_DIR/candidate
    exists is returned. Returns None (never a phantom non-existent path) on any
    miss — the **Active Prep:** value is a display label, not a filepath."""
    raw_values = []
    try:
        if isinstance(GAME_STATE, dict):
            gs = (GAME_STATE.get("active_prep_file") or "").strip()
            if gs:
                raw_values.append(gs)
    except Exception:
        pass
    if not raw_values:
        try:
            status_path = CAMPAIGN_DIR / "CURRENT_STATUS.md"
            if status_path.exists():
                for line in status_path.read_text(encoding="utf-8").splitlines():
                    if "**Active Prep:**" in line:
                        value = line.split("**Active Prep:**", 1)[1].strip()
                        if value:
                            raw_values.append(value)
                        break
        except Exception:
            pass
    for raw in raw_values:
        for cand in _normalize_prep_ref(raw):
            try:
                p = CAMPAIGN_DIR / cand
                if p.exists():
                    return p
            except Exception:
                continue
    return None


def _persist_active_prep_file(prep_filename: str) -> "str | None":
    """Resolve an incoming prep reference to an EXISTING filename and persist it
    in GAME_STATE['active_prep_file'] (+ _save_game_state). Returns the persisted
    filename, or None when it resolves to no file — in which case GAME_STATE is
    left untouched (the CURRENT_STATUS write still proceeds; no new hard failure
    in a live-play path). Called at both prep-change write points so resolution
    never again has to depend on parsing the human-formatted display line."""
    try:
        for cand in _normalize_prep_ref(prep_filename or ""):
            if (CAMPAIGN_DIR / cand).exists():
                GAME_STATE["active_prep_file"] = cand
                try:
                    _save_game_state()
                except Exception as e:
                    logging.warning("active_prep_file set but save failed: %s", e)
                return cand
    except Exception as e:
        logging.warning("Failed to persist active_prep_file %r: %s",
                        prep_filename, e)
    return None


def _startup_prep_scream_lines() -> list[str]:
    """Session-start check: if CURRENT_STATUS names an active prep that resolves
    to no file on disk, return a loud DM-visible warning (and log.error). []
    when there is no active prep or it resolves fine. The bug this guards
    survived ~80 turns precisely because both prep readers failed silently."""
    try:
        raw = ""
        status_path = CAMPAIGN_DIR / "CURRENT_STATUS.md"
        if status_path.exists():
            for line in status_path.read_text(encoding="utf-8").splitlines():
                if "**Active Prep:**" in line:
                    raw = line.split("**Active Prep:**", 1)[1].strip()
                    break
        if not raw or raw.lower() in ("none", "(none)"):
            return []
        if _resolve_active_prep_path() is not None:
            return []
        logging.error("ACTIVE PREP UNRESOLVED (session start): %r", raw)
        return _prep_unresolved_lines(raw)
    except Exception:
        return []


def _dm_only_proper_nouns(prep_path: Path) -> frozenset:
    """Proper nouns appearing ONLY in the prep's DM-ONLY content.

    Candidates: ALL-CAPS tokens (>=4 chars) anywhere, plus Capitalized tokens
    that occur capitalized at least once NOT at sentence start. Any token
    (case-insensitive) also present in the player-facing remainder is
    subtracted — it's not DM-only. Common capitalized English/markdown
    artifacts (headers, "This", "Secret", etc.) are dropped via a stopword
    list, expanded adversarially against realistic prep text."""
    try:
        raw = prep_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return frozenset()
    player_side = _filter_dm_only_content(raw, preserve_structure=False)
    # _filter_dm_only_content only strips ⛔-paired blocks / dm_only secrets /
    # inline markers — NOT header-style DM sections ('## DM ONLY — THE TRUTH',
    # '## OVERVIEW (GM KNOWLEDGE ONLY)', '## DM KNOWLEDGE'), the convention
    # live preps actually use. Cut those from the player side too (through the
    # next h2 header or EOF), mirroring _extract_dm_only_secrets' shapes.
    _dm_header_pattern = (
        r'^##\s*(?:DM ONLY\b|DM KNOWLEDGE\b|[^\n]*\(GM KNOWLEDGE ONLY\))'
        r'[^\n]*\n.*?(?=\n##\s|\Z)'
    )
    player_side = re.sub(_dm_header_pattern, '', player_side,
                         flags=re.DOTALL | re.IGNORECASE | re.MULTILINE)
    dm_side_len_delta = len(raw) - len(player_side)
    if dm_side_len_delta <= 0:
        return frozenset()

    def _tokens(s):
        return set(re.findall(r"[A-Za-z][A-Za-z'\-]{2,}", s))

    player_low = {t.lower() for t in _tokens(player_side)}
    # Candidates come from BODY prose only — markdown headers ('### Character
    # Hooks', '### Current Stakes') are structure, not names; a real name used
    # in a header also appears in body text.
    body = "\n".join(ln for ln in raw.splitlines() if not ln.lstrip().startswith("#"))
    nouns = set()
    for tok in _tokens(body):
        if tok.lower().endswith("'s"):
            tok = tok[:-2]  # possessive -> base name ("Thresh's" -> "Thresh")
            if len(tok) < 3:
                continue
        low = tok.lower()
        if low in player_low or low in _DM_NAME_STOPWORDS:
            continue
        # A word that EVER appears fully-lowercase in the prep is a common
        # noun, not a proper name — proper names stay capitalized everywhere.
        if re.search(rf"\b{re.escape(low)}\b", body):
            continue
        if tok.isupper() and len(tok) >= 4:
            nouns.add(low)
            continue
        if tok[0].isupper() and tok[1:].islower() and re.search(
            rf"[a-z0-9,;:\)\"']\s+{re.escape(tok)}\b", raw
        ):
            nouns.add(low)
    return frozenset(n for n in nouns if n not in _DM_NAME_STOPWORDS)


def _dm_only_proper_nouns_cached(prep_path: Path) -> frozenset:
    """Cached _dm_only_proper_nouns, keyed on (path, mtime). The extracted set
    depends only on the prep file (not the ledger), so both reveal-discipline
    lanes — the check_canon injection and the validate_prose tripwire — share
    one cache slot."""
    try:
        key = (str(prep_path), prep_path.stat().st_mtime)
    except Exception:
        return _dm_only_proper_nouns(prep_path)
    if _DM_NOUN_CACHE.get("key") != key:
        _DM_NOUN_CACHE["key"] = key
        _DM_NOUN_CACHE["nouns"] = _dm_only_proper_nouns(prep_path)
    return _DM_NOUN_CACHE["nouns"]


def _active_prep_ledger_name() -> "str | None":
    """Prep-scoped Revealed Ledger key for a NON-vault turn: the active prep's
    filename stem. None on a vault turn (the map owns the ledger there) or a
    prepless scene. This is also the name reveal_fact auto-creates a ledger for
    (via the ledger_autocreate_ok callback wired at startup)."""
    try:
        active, _ = _active_vault_turn()
        if active:
            return None
        prep_path = _resolve_active_prep_path()
        if not prep_path:
            return None
        return prep_path.stem
    except Exception:
        return None


def _active_prep_reveal_scope() -> "tuple":
    """(ledger_name, prep_path) when a NON-vault turn's active prep carries
    DM-only proper nouns — a social/settlement scene the party is inside;
    (None, None) otherwise. Both reveal-discipline lanes engage on non-vault
    turns exactly when this returns a name, so prepless / secret-free scenes
    get neither the charter injection nor the name gate."""
    try:
        active, _ = _active_vault_turn()
        if active:
            return None, None
        prep_path = _resolve_active_prep_path()
        if not prep_path or not prep_path.exists():
            return None, None
        if not _dm_only_proper_nouns_cached(prep_path):
            return None, None
        return prep_path.stem, prep_path
    except Exception:
        return None, None


def _vp_check_dm_name_leaks(text: str) -> list[str]:
    """Reveal discipline Part B: block DM-only proper nouns not yet in the
    site's Revealed Ledger. Deterministic; fail-open (never blocks live play
    on a bug in this check)."""
    try:
        active, _t = _active_vault_turn()
        if active:
            # Vault turn: the active map owns the ledger (unchanged behavior).
            ledger_name = active
            prep_path = _resolve_active_prep_path()
        else:
            # Non-vault turn: engage only when the active prep carries DM-only
            # content (a social/settlement scene). The reveal store is the
            # prep-scoped ledger; absent (never revealed) it reads empty, so
            # every DM-only name blocks — fail-SAFE.
            ledger_name, prep_path = _active_prep_reveal_scope()
            if not ledger_name:
                return []
        if not prep_path or not prep_path.exists():
            return []
        state = map_system.get_map_state(ledger_name) or {}
        ledger_blob = " ".join(e.get("fact", "") for e in state.get("revealed_ledger") or []).lower()
        nouns = _dm_only_proper_nouns_cached(prep_path)
        out = []
        low = text.lower()
        for noun in nouns:
            if noun in ledger_blob:
                continue
            if re.search(rf"\b{re.escape(noun)}\b", low):
                out.append(
                    f"DM-ONLY NAME LEAK: '{noun}' has not been discovered in play "
                    f"(Revealed Ledger). Remove/rename it — or, if the party just "
                    f"legitimately learned it, ledger it first: "
                    f"map(action=\"reveal\", map_name=\"{ledger_name}\", fact=\"...\").")
        return out
    except Exception as e:
        logging.debug(f"dm-name-leak check failed: {e}")
        return []


def _vp_known_canon_names() -> set:
    """Lowercase canon character names from npc_states.json plus the party."""
    names = {n.lower() for n in _vp_party_names()}
    try:
        npc_path = CAMPAIGN_DIR / "npc_states.json"
        if npc_path.exists():
            data = json.loads(npc_path.read_text(encoding="utf-8"))
            for npc in data.get("npcs", {}).values():
                nm = npc.get("name", "")
                if len(nm) > 2 and nm.lower() not in _VP_FALSE_POSITIVE_NAMES:
                    names.add(nm.lower())
    except Exception:
        pass
    return names


def _vp_cache_facts_blob(text: str = "") -> str:
    """Answer key for fact-checking: cache learnings + key_facts, SCOPED to the canon
    entities named in `text` so the payload stays small no matter how large the cache grows.
    (Bounds the Haiku fact-judge call; an empty text returns the full blob.)"""
    try:
        cache = _get_distillation_cache()
        low = (text or "").lower()
        parts = []
        for e in cache.all_entries():
            key = e.get("topic_key", "")
            entity_parts = [p for p in key.split("_")[:-1] if len(p) >= 3]
            if text and not any(p in low for p in entity_parts):
                continue  # entry is about nobody in this draft — skip it
            parts.append(e.get("learning", ""))
            parts.extend(e.get("key_facts", []))
        return " | ".join(parts).lower()
    except Exception:
        return ""


def _vp_check_narration_claims(text: str) -> list[str]:
    try:
        try:
            from hooks.fabrication_detectors import check_narration_claims
        except ImportError:
            from fabrication_detectors import check_narration_claims
        return check_narration_claims(text, _vp_known_canon_names(), _vp_cache_facts_blob(text))
    except Exception:
        return []


def _vp_check_combat_mechanics(text: str) -> list[str]:
    try:
        try:
            from hooks.fabrication_detectors import check_combat_mechanics
        except ImportError:
            from fabrication_detectors import check_combat_mechanics
        return check_combat_mechanics(text)
    except Exception:
        return []


# ---- Haiku pre-delivery semantic judge ----

_VP_HAIKU_TIMEOUT = 5
_VP_HAIKU_MODEL = "claude-haiku-4-5-20251001"
_VP_HAIKU_MAX_TOKENS = 1024

_VP_VIOLATION_CATEGORIES = [
    "Reaction Shot", "Emotional Beat", "The Pause", "Transition",
    "Landing", "Characterization", "Negation-Correction",
    "Voice Modulation", "Travel Math", "Density Drift",
    "Synthesis Incoherence",
]

_VP_RECORD_VIOLATIONS_TOOL = {
    "name": "record_violations",
    "description": (
        "Record any phrase-family or structural anti-pattern violations found "
        "in the narrator's prose. Call with an empty violations list when the "
        "prose is clean. You MUST call this tool exactly once."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "violations": {
                "type": "array",
                "description": "List of violations found; empty list if none.",
                "items": {
                    "type": "object",
                    "properties": {
                        "quote": {"type": "string", "description": "Exact phrase from the prose."},
                        "category": {
                            "type": "string",
                            "enum": _VP_VIOLATION_CATEGORIES,
                            "description": "Which Situation Strategy was violated.",
                        },
                        "confidence": {
                            "type": "string",
                            "enum": ["high", "medium", "low"],
                        },
                    },
                    "required": ["quote", "category", "confidence"],
                },
            }
        },
        "required": ["violations"],
    },
}


def _vp_get_judge_prompt() -> str:
    """Load the judge system prompt. Returns empty string on failure."""
    try:
        judge_path = Path(__file__).parent / "hooks" / "judge_prompt.txt"
        if judge_path.exists():
            return judge_path.read_text(encoding="utf-8")
    except Exception:
        pass
    return ""


def _vp_call_haiku_judge(text: str) -> list[str]:
    """Call Haiku for semantic prose review. Returns list of violation strings.

    Fail-open: returns empty list on any error (no API key, timeout, parse failure).
    """
    try:
        import anthropic
    except ImportError:
        return []

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        api_key_path = Path.home() / ".rubicon-seven" / "api_key"
        try:
            if api_key_path.exists():
                api_key = api_key_path.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    if not api_key:
        return []

    judge_prompt = _vp_get_judge_prompt()
    if not judge_prompt:
        return []

    try:
        client = anthropic.Anthropic(api_key=api_key, timeout=_VP_HAIKU_TIMEOUT)
        response = client.messages.create(
            model=_VP_HAIKU_MODEL,
            max_tokens=_VP_HAIKU_MAX_TOKENS,
            system=judge_prompt,
            messages=[{"role": "user", "content": text}],
            tools=[_VP_RECORD_VIOLATIONS_TOOL],
            tool_choice={"type": "tool", "name": "record_violations"},
        )

        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "record_violations":
                payload = getattr(block, "input", None)
                if isinstance(payload, dict):
                    violations = payload.get("violations", [])
                    result = []
                    for v in violations:
                        if v.get("confidence") in ("high", "medium"):
                            quote = v.get("quote", "")[:60]
                            cat = v.get("category", "Unknown")
                            result.append(f'SEMANTIC [{cat}]: "{quote}"')
                    return result
        return []
    except Exception:
        return []


_VP_FACT_RECORD_TOOL = {
    "name": "record_fact_violations",
    "description": "Record draft statements that contradict the canon answer key. "
                   "Call exactly once; empty list if nothing contradicts.",
    "input_schema": {
        "type": "object",
        "properties": {
            "violations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "quote": {"type": "string", "description": "The exact phrase from the draft that contradicts canon."},
                        "contradicts": {"type": "string", "description": "The established answer-key fact this phrase breaks."},
                        "confidence": {"type": "string", "enum": ["high", "medium", "low"], "description": "high = clear contradiction; medium = probable; low = unsure."},
                    },
                    "required": ["quote", "contradicts", "confidence"],
                },
            }
        },
        "required": ["violations"],
    },
}


def _vp_fact_judge_raw(text: str, answer_key: str) -> dict:
    """Call Haiku with the answer key + draft, forced tool-use. Raises on any failure."""
    import anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        kp = Path.home() / ".rubicon-seven" / "api_key"
        api_key = kp.read_text(encoding="utf-8").strip() if kp.exists() else None
    if not api_key:
        raise RuntimeError("no api key")
    prompt_path = Path(__file__).parent / "hooks" / "fact_judge_prompt.txt"
    system = prompt_path.read_text(encoding="utf-8")
    client = anthropic.Anthropic(api_key=api_key, timeout=_VP_HAIKU_TIMEOUT)
    resp = client.messages.create(
        model=_VP_HAIKU_MODEL, max_tokens=_VP_HAIKU_MAX_TOKENS,
        system=system,
        messages=[{"role": "user",
                   "content": f"ANSWER KEY:\n{answer_key}\n\n---\n\nDRAFT:\n{text}"}],
        tools=[_VP_FACT_RECORD_TOOL],
        tool_choice={"type": "tool", "name": "record_fact_violations"},
    )
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "record_fact_violations":
            payload = getattr(block, "input", None)
            if isinstance(payload, dict):
                return payload
    raise ValueError("no record_fact_violations block")


def _vp_call_fact_judge(text: str, answer_key: str) -> list[str]:
    """Fact-check the draft against the answer key. Fail-open (returns [] on any error)."""
    if not answer_key.strip():
        return []
    try:
        payload = _vp_fact_judge_raw(text, answer_key)
    except Exception:
        return []
    out = []
    for v in payload.get("violations", []):
        if v.get("confidence") in ("high", "medium"):
            out.append(
                f'FACT CONTRADICTION: "{v.get("quote", "")[:60]}" contradicts '
                f'canon ({v.get("contradicts", "")[:80]}). Verify and correct.'
            )
    return out


def _vp_check_prep_progress() -> str | None:
    """Check if state-changing tools were used but prep file not yet updated.

    Returns a violation string if prep needs updating, None otherwise.
    """
    try:
        from hooks.hook_utils import STATE_CHANGING_TOOLS, TOOL_LABELS
        hook_state_path = Path(__file__).parent / "hooks" / ".hook_state.json"
        if not hook_state_path.exists():
            return None
        state = json.loads(hook_state_path.read_text(encoding="utf-8"))

        # Check active prep file
        status_path = CAMPAIGN_DIR / "CURRENT_STATUS.md"
        if not status_path.exists():
            return None
        status_text = status_path.read_text(encoding="utf-8")
        prep_filename = None
        for line in status_text.splitlines():
            if "**Active Prep:**" in line:
                value = line.split("**Active Prep:**", 1)[1].strip()
                if value and value.lower() != "none":
                    prep_filename = value
                break
        if not prep_filename:
            return None

        # Check if state-changing tools were tracked this turn
        tools_this_turn = state.get("state_changing_tools_this_turn", [])
        if not tools_this_turn:
            return None

        # Check if prep was already edited this turn
        if state.get("prep_edited_this_turn", False):
            return None

        labels = [TOOL_LABELS.get(t, t.split("__")[-1]) for t in tools_this_turn]
        change_list = ", ".join(set(labels))

        return (
            f'PREP UPDATE NEEDED: State-changing tools used ({change_list}). '
            f'Edit {prep_filename} PROGRESS LOG before delivering narrative.'
        )
    except Exception:
        return None


def _validate_prose_impl(text: str) -> str:
    """Core prose-gate validation. Entry: narrative_qa(action='validate')."""
    bl_patterns, sp_patterns, st_patterns = _load_prose_patterns()
    violations = []
    # Never-again list — confirmed past errors, hard-blocked first (cheapest, certain).
    violations.extend(_vp_check_fabrication_bans(text))
    for pattern, original in bl_patterns:
        for m in pattern.finditer(text):
            violations.append(f'BLACKLISTED: "{m.group(0)}"')
    # Structural pattern scan
    for pattern, category in st_patterns:
        for m in pattern.finditer(text):
            violations.append(f'STRUCTURAL [{category}]: "{m.group(0)[:60]}"')
    # Check use-sparingly against session vocabulary
    try:
        hook_state_path = Path(__file__).parent / "hooks" / ".hook_state.json"
        if hook_state_path.exists():
            state = json.loads(hook_state_path.read_text(encoding="utf-8"))
            session_vocab = [v.lower() for v in state.get("session_vocabulary", [])]
            for pattern, original in sp_patterns:
                for m in pattern.finditer(text):
                    if m.group(0).lower() in session_vocab:
                        violations.append(f'OVERUSED: "{m.group(0)}" (already used this session)')
    except Exception as e:
        logging.debug(f"Anti-pattern session vocab check failed: {e}")

    # NPC mention check — flag unverified NPC names in narrative
    unverified_npcs = _vp_check_npc_mentions(text)
    if unverified_npcs:
        names_str = ", ".join(unverified_npcs[:3])
        primary = unverified_npcs[0]
        violations.append(
            f'NPC UNVERIFIED: {names_str} mentioned without verification. '
            f'Call lorebook(view, "{primary.lower()}") or npc(get, "{primary}") first.'
        )

    # Backstory hallucination check — flag fabricated shared-history claims
    backstory_hits = _vp_check_backstory(text)
    if backstory_hits:
        preview = backstory_hits[0][:60]
        violations.append(
            f'BACKSTORY RISK: Unverified backstory claim detected ("{preview}..."). '
            f'Call check_canon or reference MASTER_CONTINUITY_ORIGINS.md.'
        )

    # Dialogue claim check — flag unverified factual assertions in NPC speech
    dialogue_claims = _vp_check_dialogue_claims(text)
    if dialogue_claims:
        samples = "; ".join(f'[{t}] "{c}"' for t, c in dialogue_claims[:3])
        violations.append(
            f'DIALOGUE CLAIM RISK: Unverified fact(s) in dialogue: {samples}. '
            f'Verify via check_canon or rewrite without the unsupported specific.'
        )

    # Pet-name, tripwire, narration-claim, and combat-mechanics checks (deterministic widening).
    violations.extend(_vp_check_petnames(text))
    violations.extend(_vp_check_tripwires(text))
    violations.extend(_vp_check_dm_name_leaks(text))
    violations.extend(_vp_check_narration_claims(text))
    violations.extend(_vp_check_combat_mechanics(text))

    # Semantic judges — run only if the fast deterministic checks found nothing.
    # The haiku voice-judge and the fact-judge are independent and both fail-open,
    # so run them concurrently instead of paying two sequential ~5s API calls on
    # every clean turn (C25). The fact-judge still only fires when a known canon
    # name appears in the draft (cheap precheck).
    if not violations:
        names = _vp_known_canon_names()
        low = text.lower()
        fact_needed = any(re.search(rf"\b{re.escape(n)}\b", low) for n in names)
        fact_blob = _vp_cache_facts_blob(text) if fact_needed else ""

        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as _ex:
            _haiku_future = _ex.submit(_vp_call_haiku_judge, text)
            _fact_future = _ex.submit(_vp_call_fact_judge, text, fact_blob) if fact_needed else None
            try:
                violations.extend(_haiku_future.result())
            except Exception:
                pass  # fail-open
            if _fact_future is not None:
                try:
                    violations.extend(_fact_future.result())
                except Exception:
                    pass  # fail-open

    # Prep progress check — remind to update prep if state-changing tools were used
    prep_warning = _vp_check_prep_progress()
    if prep_warning:
        violations.append(prep_warning)

    # Set flag so stop hook knows feedback loop occurred
    try:
        if HOOK_STATE_FILE.exists():
            with _hook_state_lock():
                hs = _read_hook_state()
                hs["validate_prose_called"] = True
                _write_hook_state(hs)
    except Exception:
        pass

    if not violations:
        return "CLEAN — no violations detected."
    unique = list(dict.fromkeys(violations))
    return "VIOLATIONS FOUND:\n" + "\n".join(f"- {v}" for v in unique) + "\n\nRewrite to eliminate these phrases before outputting."

@mcp.tool(tags=_get_tool_tags("narrative_qa"))
def narrative_qa(
    action: str = Field(description="validate|check|list"),
    text: str = Field(default=None, description="draft narrative text (validate + check)"),
    character_names: str = Field(default="", description="check: comma-separated character names in the scene"),
) -> str:
    """Reach for this WHEN you have a narrative draft ready to deliver.

    validate: REQUIRED before all narrative output -- runs the full prose gate (blacklist +
              structural + fabrication/NPC/backstory judges); returns CLEAN or violations to
              fix first. Enforced by gate_check -- skipping triggers tool lockout next turn.
    check:    lighter structural anti-pattern scan (talking-heads, over-naming) (text, character_names?)
    list:     show all anti-pattern rules
    """
    a = (action or "").lower().strip()
    if a == "validate":
        if not text:
            return "Error: action='validate' needs text."
        return _validate_prose_impl(text)
    if a == "check":
        if not text:
            return "Error: action='check' needs text."
        return _check_anti_patterns(text, character_names)
    if a == "list":
        return _list_anti_patterns()
    return f"Invalid action '{action}'. Valid actions: validate, check, list."


# verify_session_save moved to session_tools.py (Wave 8 slice 1); registered via register_session_tools.


# ============================================
# CAMPAIGN STATE VALIDATION
# ============================================

@mcp.tool(tags=_get_tool_tags("validate_campaign_state"))
def validate_campaign_state() -> str:
    """Reach for this WHEN you suspect data corruption or day drift across campaign files — runs a full cross-check before play resumes or after an interrupted session.

    Cross-check all campaign JSON files for consistency issues.
    Detects: day drift, location mismatches, duplicate entries, stale data.
    Run periodically or when you suspect data corruption.
    """
    issues = []
    warnings = []

    # ========================================
    # 1. Load all relevant files
    # ========================================
    try:
        # Get current day from CURRENT_STATUS.md (source of truth)
        status_path = CAMPAIGN_DIR / "CURRENT_STATUS.md"
        status_content = status_path.read_text(encoding='utf-8')
        day_match = re.search(r'# CURRENT STATUS - DAY (\d+)', status_content)
        current_day = int(day_match.group(1)) if day_match else None

        if not current_day:
            issues.append("CRITICAL: Cannot determine current day from CURRENT_STATUS.md")
            current_day = 0
    except Exception as e:
        issues.append(f"CRITICAL: Cannot read CURRENT_STATUS.md: {e}")
        current_day = 0

    # ========================================
    # 1b. Validate CURRENT_STATUS.md format
    # ========================================
    required_fields = [
        (r'\*\*Location:\*\*\s*[^\n]+', 'SCENE STATE: **Location:**'),
        (r'\*\*Present:\*\*\s*[^\n]+', 'SCENE STATE: **Present:**'),
        (r'\*\*Last 3 Beats:\*\*', 'SCENE STATE: **Last 3 Beats:**'),
        (r'\*\*Next Expected:\*\*\s*[^\n]+', 'SCENE STATE: **Next Expected:**'),
        (r'\*\*Last Fed:\*\*\s*Day\s*\d+', 'PHOTOSYNTHESIS: **Last Fed:** Day X'),
        (r'\*\*Due:\*\*\s*Day\s*\d+', 'PHOTOSYNTHESIS: **Due:** Day X'),
        (r'## SCENE STATE', 'Section: ## SCENE STATE'),
        (r'## ACTIVE THREADS', 'Section: ## ACTIVE THREADS'),
    ]
    
    for pattern, field_name in required_fields:
        if not re.search(pattern, status_content):
            issues.append(f"MISSING FORMAT: {field_name} not found in CURRENT_STATUS.md")

    # Detect SCENE STATE field concatenation (format corruption)
    for line in status_content.split('\n'):
        if '**Day:**' in line and '**Location:**' in line:
            issues.append("FORMAT ERROR: SCENE STATE fields concatenated on single line — write corruption detected")
            break

    # Validate emotional state table format (check split file first, then CURRENT_STATUS.md)
    emo_check_content = status_content
    emo_file = CAMPAIGN_DIR / "scene_state" / "emotional_state.md"
    if emo_file.exists():
        emo_check_content = emo_file.read_text(encoding='utf-8')
    if '## EMOTIONAL STATE' in emo_check_content:
        if not re.search(r'\|\s*Character\s*\|\s*Current Emotion\s*\|\s*Cause\s*\|\s*Intensity\s*\|', emo_check_content):
            warnings.append("EMOTIONAL STATE table may have incorrect column headers")

    # Load JSON files
    files = {}
    for fname in ['characters.json', 'party.json', 'npc_states.json', 'narrative_threads.json', 'RELATIONSHIP_MATRIX.json']:
        fpath = CAMPAIGN_DIR / fname
        if fpath.exists():
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    files[fname] = json.load(f)
            except Exception as e:
                issues.append(f"Cannot parse {fname}: {e}")
        else:
            warnings.append(f"File not found: {fname}")

    # ========================================
    # 2. Check day consistency
    # ========================================
    if 'characters.json' in files:
        char_day = files['characters.json'].get('meta', {}).get('campaign_day', 0)
        if char_day and current_day and abs(current_day - char_day) > 2:
            issues.append(f"DAY DRIFT: characters.json shows Day {char_day}, but current is Day {current_day} (diff: {current_day - char_day})")

    if 'party.json' in files:
        party_day = files['party.json'].get('meta', {}).get('campaign_day', 0)
        if party_day and current_day and abs(current_day - party_day) > 2:
            issues.append(f"DAY DRIFT: party.json shows Day {party_day}, but current is Day {current_day} (diff: {current_day - party_day})")

    # ========================================
    # 3. Check for duplicate entries (character in both characters.json and npc_states.json)
    # ========================================
    if 'characters.json' in files and 'npc_states.json' in files:
        char_names = set(files['characters.json'].get('characters', {}).keys())
        npc_names = set(files['npc_states.json'].get('npcs', {}).keys())

        # Normalize names for comparison
        char_names_lower = {n.lower().replace('_', ' ').replace('-', ' ') for n in char_names}
        npc_names_lower = {n.lower().replace('_', ' ').replace('-', ' ') for n in npc_names}

        duplicates = char_names_lower & npc_names_lower
        if duplicates:
            for dup in duplicates:
                # Check if it's intentional (e.g., prisoner status)
                npc_key = next((k for k in npc_names if k.lower().replace('_', ' ').replace('-', ' ') == dup), None)
                if npc_key:
                    npc_data = files['npc_states.json']['npcs'].get(npc_key, {})
                    disposition = npc_data.get('disposition', '')
                    if disposition in ['prisoner', 'deceased', 'hostile']:
                        warnings.append(f"DUAL ENTRY (expected): '{dup}' in both characters.json and npc_states.json (disposition: {disposition})")
                    else:
                        issues.append(f"DUAL ENTRY: '{dup}' exists in both characters.json and npc_states.json - needs resolution")

    # ========================================
    # 4. Check location consistency
    # ========================================
    if 'characters.json' in files and 'npc_states.json' in files:
        # Extract location from CURRENT_STATUS.md
        loc_match = re.search(r'\*\*Location:\*\*\s*([^\n]+)', status_content)
        current_location = loc_match.group(1).strip() if loc_match else None

        # Check character locations
        for char_id, char_data in files['characters.json'].get('characters', {}).items():
            char_loc = char_data.get('location', '')
            if char_loc:
                # Check for obvious mismatches
                if 'en route' in char_loc.lower() and current_location and 'ceruline' in current_location.lower():
                    warnings.append(f"LOCATION: {char_data.get('name', char_id)} shows '{char_loc}' but party is at {current_location}")

        # Check NPC locations vs their last_seen_day
        for npc_id, npc_data in files['npc_states.json'].get('npcs', {}).items():
            last_seen = npc_data.get('last_seen_day', 0)
            if last_seen and current_day and (current_day - last_seen) > 10:
                warnings.append(f"STALE NPC: {npc_data.get('name', npc_id)} last seen Day {last_seen} (current: Day {current_day})")

    # ========================================
    # 5. Check character rest days
    # ========================================
    if 'characters.json' in files:
        for char_id, char_data in files['characters.json'].get('characters', {}).items():
            last_rest = char_data.get('last_rest_day', 0)
            if last_rest and current_day and (current_day - last_rest) > 7:
                warnings.append(f"REST: {char_data.get('name', char_id)} last rested Day {last_rest} ({current_day - last_rest} days ago)")

    # ========================================
    # 6. Check narrative threads for stale entries
    # ========================================
    if 'narrative_threads.json' in files:
        threads = files['narrative_threads.json'].get('threads', {})
        for thread_id, thread_data in threads.items():
            introduced = thread_data.get('introduced_day', 0)
            urgency = thread_data.get('urgency', 'low')
            developments = thread_data.get('developments', [])

            # Get most recent development day
            last_dev_day = introduced
            for dev in developments:
                dev_day = dev.get('day', 0)
                if dev_day > last_dev_day:
                    last_dev_day = dev_day

            days_stale = current_day - last_dev_day if current_day else 0

            if urgency == 'high' and days_stale > 5:
                warnings.append(f"STALE THREAD: '{thread_data.get('title', thread_id)}' (HIGH urgency) no updates for {days_stale} days")
            elif urgency == 'medium' and days_stale > 10:
                warnings.append(f"STALE THREAD: '{thread_data.get('title', thread_id)}' (MEDIUM urgency) no updates for {days_stale} days")

    # ========================================
    # 6b. Lorebook duplicate/overlap detection
    # ========================================
    try:
        lorebook_path = CAMPAIGN_DIR / "lorebook.json"
        if lorebook_path.exists():
            with open(lorebook_path, 'r', encoding='utf-8') as f:
                lorebook_data = json.load(f)
            entries = lorebook_data.get("entries", [])

            # Build keyword-to-entry index
            keyword_entries = {}  # keyword -> list of entry indices
            for idx, entry in enumerate(entries):
                for kw in entry.get("keywords", []):
                    kw_lower = kw.lower().strip()
                    if kw_lower not in keyword_entries:
                        keyword_entries[kw_lower] = []
                    keyword_entries[kw_lower].append(idx)

            # Flag duplicate keywords (same keyword in multiple entries)
            for kw, indices in keyword_entries.items():
                if len(indices) > 1:
                    categories = [entries[i].get("category", "?") for i in indices]
                    warnings.append(f"LOREBOOK DUP KEYWORD: '{kw}' appears in {len(indices)} entries (categories: {', '.join(categories)})")

            # Flag entries with high keyword overlap (>80%)
            for i in range(len(entries)):
                kws_i = set(k.lower().strip() for k in entries[i].get("keywords", []))
                if len(kws_i) < 2:
                    continue
                for j in range(i + 1, len(entries)):
                    kws_j = set(k.lower().strip() for k in entries[j].get("keywords", []))
                    if len(kws_j) < 2:
                        continue
                    overlap = kws_i & kws_j
                    smaller = min(len(kws_i), len(kws_j))
                    if smaller > 0 and len(overlap) / smaller > 0.8:
                        warnings.append(
                            f"LOREBOOK OVERLAP: entries '{list(kws_i)[0]}' and '{list(kws_j)[0]}' share {len(overlap)}/{smaller} keywords"
                        )
    except Exception as e:
        warnings.append(f"Lorebook check failed: {e}")

    # ========================================
    # 6c. Lorebook stale self-dating claims (C15b) — flag only, never auto-edit.
    # A lorebook entry is injected as CANONICAL context every gated turn, so a
    # time-relative claim that has gone stale ('Day N' long past, 'has not yet',
    # 'current members') actively misleads a fresh post-compaction DM. Surface
    # it for the DM to reconcile via lorebook(action="update"); do NOT rewrite.
    # ========================================
    try:
        lorebook_path = CAMPAIGN_DIR / "lorebook.json"
        if lorebook_path.exists():
            with open(lorebook_path, 'r', encoding='utf-8') as f:
                lb_stale = json.load(f)
            STALE_LORE_DAYS = 20
            _stale_phrases = ["has not yet", "have not yet", "not yet appeared",
                              "not yet met", "current members", "currently ",
                              "as of now", "for now"]
            for entry in lb_stale.get("entries", []):
                ctx = entry.get("context", "") or ""
                low = ctx.lower()
                kw0 = (entry.get("keywords") or ["?"])[0]
                # (a) self-dating "Day N" older than the staleness window
                oldest = None
                for m in re.finditer(r'\bday\s+(\d+)\b', low):
                    dn = int(m.group(1))
                    if current_day and (current_day - dn) > STALE_LORE_DAYS:
                        oldest = dn if oldest is None else min(oldest, dn)
                if oldest is not None:
                    warnings.append(
                        f"LOREBOOK STALE: '{kw0}' context cites Day {oldest} "
                        f"({current_day - oldest} days ago) — verify it still holds, then "
                        f"lorebook(action=\"update\", keyword=\"{kw0}\", field=\"context\", ...)")
                # (b) time-relative claim that may have quietly gone stale
                hit = next((p for p in _stale_phrases if p in low), None)
                if hit:
                    warnings.append(
                        f"LOREBOOK STALE-PHRASE: '{kw0}' context says \"{hit.strip()}\" — "
                        f"a time-relative claim; re-check against current play, then "
                        f"lorebook(action=\"update\", keyword=\"{kw0}\", field=\"context\", ...)")
    except Exception as e:
        warnings.append(f"Lorebook staleness check failed: {e}")

    # ========================================
    # 7. Build report
    # ========================================
    output = [f"# Campaign State Validation (Day {current_day})", ""]

    if issues:
        output.append(f"## ❌ ISSUES ({len(issues)})")
        output.append("These need immediate attention:")
        for issue in issues:
            output.append(f"- {issue}")
        output.append("")

    if warnings:
        output.append(f"## ⚠️ WARNINGS ({len(warnings)})")
        output.append("These may need review:")
        for warning in warnings:
            output.append(f"- {warning}")
        output.append("")

    if not issues and not warnings:
        output.append("## ✅ All Clear")
        output.append("No consistency issues detected.")

    if any("DAY DRIFT" in issue for issue in issues):
        output.append("")
        output.append("---")
        output.append(_pf.next_block(_pf.push_call("sync_campaign_day"), label="fix drift"))

    return "\n".join(output)


@mcp.tool(tags=_get_tool_tags("sync_campaign_day"))
def sync_campaign_day(action: str = "sync", day: int = None, bell: int = None) -> str:
    """Reach for this WHEN validate_campaign_state reports day drift (action="sync"), narrative time passes and the in-game bell/clock needs setting (action="set_bell", bell=1..24), or you need today's campaign day (action="get").

    Campaign-day & clock tool. sync: stamp the day from CURRENT_STATUS.md into characters/_meta.json and party.json | set_bell: set the 24-bell in-game clock | get: read the current campaign day.
    """
    action = (action or "sync").lower().strip()
    if action == "set_bell":
        if bell is None:
            return "Invalid action 'set_bell': requires bell"
        return _set_bell_impl(bell)
    if action == "get":
        return _get_current_day_impl()
    if action != "sync":
        return f"Invalid action '{action}'. Valid actions: sync, set_bell, get"
    # Get current day from CURRENT_STATUS.md if not provided
    if day is None:
        try:
            status_path = CAMPAIGN_DIR / "CURRENT_STATUS.md"
            status_content = status_path.read_text(encoding='utf-8')
            day_match = re.search(r'# CURRENT STATUS - DAY (\d+)', status_content)
            if day_match:
                day = int(day_match.group(1))
            else:
                return "ERROR: Cannot determine current day from CURRENT_STATUS.md"
        except Exception as e:
            return f"ERROR: Cannot read CURRENT_STATUS.md: {e}"

    results = []

    # Update characters - try split files first, fallback to monolithic
    try:
        chars_dir = CAMPAIGN_DIR / "characters"
        meta_path = chars_dir / "_meta.json"

        if chars_dir.exists() and meta_path.exists():
            # Split sheets are authoritative; _meta.json carries the campaign day.
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta_data = json.load(f)
            old_day = meta_data.get('campaign_day', 0)
            meta_data['campaign_day'] = day
            meta_data['last_updated'] = datetime.now().strftime("%Y-%m-%d")
            _atomic_json_write(meta_path, meta_data)
            results.append(f"✓ characters/_meta.json: Day {old_day} → {day}")
        else:
            results.append("✗ character split sheets (characters/_meta.json) not found; day not updated")
    except Exception as e:
        results.append(f"✗ characters update failed: {e}")

    # Update party.json
    try:
        party_path = CAMPAIGN_DIR / "party.json"
        if party_path.exists():
            with open(party_path, 'r', encoding='utf-8') as f:
                party_data = json.load(f)
            old_day = party_data.get('meta', {}).get('campaign_day', 0)
            party_data['meta']['campaign_day'] = day
            party_data['meta']['last_updated'] = datetime.now().strftime("%Y-%m-%d")
            _atomic_json_write(party_path, party_data)
            results.append(f"✓ party.json: Day {old_day} → {day}")
    except Exception as e:
        results.append(f"✗ party.json failed: {e}")

    results.append("")
    results.append(f"Campaign day synced to Day {day}")

    return "\n".join(results)


# ============================================
# COMBAT SYSTEM
# ============================================

VALID_COMBAT_ACTIONS = ["init", "damage", "attack", "morale", "state", "end", "log",
                        "synthetic_attack", "chase"]

@mcp.tool(
    annotations={"readOnlyHint": False, "idempotentHint": False},
    tags=_get_tool_tags("combat")
)
def combat(
    action: str = Field(
        description="init|damage|attack|morale|state|end|log|synthetic_attack|chase. synthetic_attack: a Synthetic vehicle attacks on its own, to-hit = current Hull (pass the vehicle as target=). chase: opposed Speed save between two vehicles (pass attacker= and target=)."
    ),

    # Init parameters
    enemies: list[str] = Field(
        default=None,
        description="Enemy list: ['Gene Thief', 'Gene Thief', 'Raider'] or ['Gene Thief (leader)', 'Gene Thief (nervous)']"
    ),
    encounter_name: str = Field(
        default=None,
        description="Optional name for this fight (auto-generated if omitted)"
    ),

    # Damage parameters
    target: str = Field(
        default=None,
        description="Combatant descriptor: 'Gene Thief (scarred)' or 'Gene Thief (leader)'"
    ),
    amount: int = Field(
        default=None,
        description="Damage amount (positive integer)"
    ),
    damage_type: str = Field(
        default="kinetic",
        description="kinetic|beam|blast|flame|electrical|TOX (default: kinetic). For kinetic melee, pass the sub-type slashing|piercing|bludgeoning when it matters — some creatures resist/are weak to a specific kinetic sub-type (e.g. Planeyfolk: double from slashing/slicing — book rule, slashing only; Mineral: double from bludgeoning). A sub-typed hit still gets any blanket kinetic resistance."
    ),
    ability_stat: str = Field(
        default=None,
        description="Apply damage to an enemy ability score instead of HP: STR|DEX|CON|INT|PSY|EGO. Enemy ability scores start at LVL. House rule: ability damage = save penalty equal to amount rolled."
    ),
    weapon_tags: list[str] = Field(
        default=None,
        description="Weapon tags that double vs a creature type or bypass incorporeal immunity: 'anti-paradoxical' (Outsider), 'eroding' (Mineral), 'psyche-suppressant' (Psychic), 'hypergeometric' (Hypergeometric; skipped when damage_type is already hypergeometric). Electrical->Synthetic is already handled via damage_type."
    ),
    attacker: str = Field(
        default=None,
        description="PC name of the attacker. When supplied and the target is an enemy, the attacker's weapon is auto-read from their character sheet, overriding damage_type and weapon_tags with the sheet values."
    ),
    weapon: str = Field(
        default=None,
        description="Substring of the attacking weapon's name to select when the attacker carries multiple weapons (e.g. 'Railgun'). Omit to use the primary-flagged or sole weapon."
    ),

    # Log parameters
    message: str = Field(
        default=None,
        description="Custom message to add to combat log"
    ),

    # Override parameters
    force_morale: bool = Field(
        default=False,
        description="Force morale check even if not at threshold"
    ),

    side: str = Field(
        default=None,
        description="'pcs' or 'enemies' - mark this side as having acted"
    ),

    # Attack parameters (action='attack')
    auto_roll: bool = Field(
        default=None,
        description="action='attack' only: DM opt-in to let the engine roll the player PC's d20 and damage dice automatically (Iron Law 3 bypass). All other attackers always auto-roll; this flag is only needed for the player PC."
    ),
    to_hit: int = Field(
        default=None,
        description="action='attack' only: a PC's unmodified d20 roll. Supply this to ROUTE the player's own physical roll through the engine — the engine adds the ability bonus (DEX/STR) and surfaces any gambit, so you never hand-resolve and drop a modifier. REQUIRED for the player PC (unless auto_roll=True); OPTIONAL for any other PC (omit -> engine auto-rolls)."
    ),
    damage_roll: int = Field(
        default=None,
        description="action='attack' only: a PC's pre-rolled damage value. Required whenever to_hit is supplied (the player rolled their own dice). Pass it WITH to_hit to resolve in one call and avoid a second round-trip."
    ),
    thrown: bool = Field(
        default=False,
        description="action='attack' only: set True when a MELEE weapon is thrown. HOUSE RULE — a thrown attack is a ranged attack, so to-hit uses DEX instead of STR. No effect on weapons that are already ranged."
    ),
) -> str:
    """Reach for this WHEN combat starts, a blow lands, or an enemy acts — init/attack/damage/morale/state/log/end all live here. Vehicles: synthetic_attack (a Synthetic vehicle's Hull-as-to-hit, CH p.73) and chase (opposed Speed save between two vehicles).

    Combat state management for Vaarn 2e rules.

    Tracks initiative, enemy HP, rounds, morale. Auto-advances rounds,
    auto-checks morale, auto-applies wounds. Integrates with check_canon
    for combat HUD display. Pass attacker= to auto-read the PC weapon's
    damage_type and engine_tags from their character sheet for the
    resistance check.

    Engine-owned weapon specials (do NOT hand-apply -- the engine resolves them
    from weapon tags): Vibroactive / Dimensional Edge hit vs AV 10 (capped,
    never raised); Piercing / Mauling add an extra die or halve damage by the
    target's REAL AV bracket (>=16 / <=13; 14-15 untouched).

    C1 reactive triggers (defender sheet special_traits.triggers) fire
    automatically on enemy hits: Acid Blood melee retaliation, Toxic Sap
    bite TOX, Mirrored Leaves beam withhold-and-save. Do NOT hand-apply.
    Exception the engine cannot see: a creature EATING part of a tox_attack
    PC - apply it via affliction(kind="toxin", action="check", target="<enemy>", tox_die="d10").
    """

    action = action.lower().strip()
    if action not in VALID_COMBAT_ACTIONS:
        return f"Invalid action '{action}'. Valid: {', '.join(VALID_COMBAT_ACTIONS)}"

    if action == "init":
        _result = _combat_init(enemies, encounter_name)
    elif action == "damage":
        _result = _combat_damage(target, amount, damage_type, ability_stat, weapon_tags,
                              attacker=attacker, weapon=weapon)
    elif action == "attack":
        _result = _combat_attack(attacker, weapon, target,
                              auto_roll=auto_roll, to_hit=to_hit, damage_roll=damage_roll,
                              thrown=thrown)
    elif action == "morale":
        _result = _combat_morale(force_morale)
    elif action == "state":
        _result = _combat_state()
    elif action == "end":
        _result = _combat_end()
    elif action == "log":
        _result = _combat_log(message, side)
    elif action == "synthetic_attack":
        if not target:
            return "synthetic_attack requires target= (the vehicle name)."
        _vdata, _verr = _load_characters()
        if _verr:
            return _verr
        _vk, _vsheet = _find_character(_vdata, target)
        if not _vsheet or _vsheet.get("type") != "vehicle":
            return f"{target} is not a vehicle."
        bonus = _vehicle_attack_bonus(_vsheet)
        if bonus is None:
            return ("{} is not a Synthetic vehicle - it needs a crew member to "
                    "operate its weapon (CH p.73). Roll the operator's attack "
                    "normally.".format(_vsheet.get("name", target)))
        _result = ("SYNTHETIC SELF-ATTACK (CH p.73): {} attacks on its own.\n"
                "  To-hit = current Hull: roll d20 +{} vs target AV.".format(
                    _vsheet.get("name", target), bonus))
    elif action == "chase":
        if not attacker or not target:
            return "chase requires attacker= and target= (two vehicle names)."
        _result = "\n".join(_vehicle_speed_save_lines(attacker, target))
    else:
        return f"Action '{action}' not implemented."

    _emit_player_view()
    return _result

def _roll_stat_expr(expr, default=None):
    """Resolve a creature stat that may be an int or a dice expression.

    Handles '2d6', 'd8', '3d6 + 10', '8+d8', and morale notation '+2d6'. Dice are
    rolled and summed with any flat modifiers. Returns `default` if unparseable
    (e.g. 'Special', '=LVL') so a variable/odd stat no longer dumps the whole
    creature to the L1/HP4 fallback in _combat_init."""
    if isinstance(expr, bool):
        return default
    if isinstance(expr, int):
        return expr
    if isinstance(expr, float):
        return int(expr)
    s = str(expr or "").strip()
    if not s:
        return default
    total, found = 0, False
    for part in s.split("+"):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"(\d*)d(\d+)", part)
        if m:
            n, faces = int(m.group(1) or 1), int(m.group(2))
            if n < 1 or faces < 1:
                return default
            total += sum(random.randint(1, faces) for _ in range(n))
            found = True
        elif part.isdigit():
            total += int(part)
            found = True
        else:
            return default  # unparseable token -> whole expression is unsafe
    return total if found else default


def _combat_init(enemies: list[str], encounter_name: str = None) -> str:
    """Initialize combat, fetch stats, roll initiative."""

    # Check if combat already active
    if GAME_STATE.get("active_combat"):
        return "Combat already in progress. End current combat first with action='end'."

    if not enemies or len(enemies) == 0:
        return "Must provide at least one enemy in 'enemies' parameter."

    # Generate encounter name if not provided (handle Field objects too)
    if not encounter_name or not isinstance(encounter_name, str):
        # Use location + creature type
        location = GAME_STATE.get("active_location_name", "unknown")
        creature_base = enemies[0].split("(")[0].strip() if "(" in enemies[0] else enemies[0]
        encounter_name = f"{creature_base.lower().replace(' ', '_')}_{location}"

    # Roll initiative (d6: even=pcs, odd=enemies)
    init_roll = random.randint(1, 6)
    initiative = "pcs" if init_roll % 2 == 0 else "enemies"

    # Process enemies
    enemy_dict = {}
    used_descriptors = set()
    enemy_count = 0
    unmatched_warnings = []

    for enemy_spec in enemies:
        enemy_count += 1

        # Check if descriptor provided
        if "(" in enemy_spec:
            # Custom descriptor: "Gene Thief (leader)"
            full_name = enemy_spec
            creature_type = enemy_spec.split("(")[0].strip()
            descriptor = enemy_spec.split("(")[1].rstrip(")")
            used_descriptors.add(descriptor)
        else:
            # Auto-assign descriptor
            creature_type = enemy_spec
            full_name = assign_descriptor(creature_type, used_descriptors, enemy_count)
            # Extract descriptor for tracking
            descriptor = full_name.split("(")[1].rstrip(")")
            used_descriptors.add(descriptor)

        # Fetch structured creature stats from the canonical bestiary
        lvl, hp, av, morale = 1, 4, 12, 0
        resist_type, resistances = "Biological", {"immune": [], "double": [], "half": [], "varies": False}
        incorporeal = False
        entry = None  # initialised here so attack-data block below is always safe
        try:
            entry = _get_bestiary_entry(creature_type)
            if entry:
                s = entry.get("stats", {})
                # Each field resolves independently (dice expressions rolled) so a
                # variable/odd stat does not collapse the whole creature to defaults.
                lvl = _roll_stat_expr(s.get("level", s.get("hd")), default=1)
                hp = _roll_stat_expr(s.get("hp"), default=None)
                if hp is None:
                    hp = lvl * 4   # book rule: HP = LVL x4 when no explicit HP
                av = _roll_stat_expr(s.get("av", s.get("av_natural")), default=12)
                morale = _roll_stat_expr(s.get("morale"), default=0)
                resist_type = str(s.get("type", s.get("types", "Biological")))
                resistances = _resolve_resistance_profile(s)
                incorporeal = bool(s.get("incorporeal"))
            else:
                logging.warning(f"No bestiary entry for '{creature_type}'; using defaults")
                unmatched_warnings.append(
                    f"⚠ NO BESTIARY MATCH: '{creature_type}' — assigned generic stats "
                    f"(Lv1, 4 HP, AV 12). If this is a real creature, register it or check the name."
                )
        except Exception as e:
            logging.warning(f"Could not fetch/parse stats for {creature_type}: {e}")

        # House rule: enemy ability scores = LVL (Vaarn 2e has no ability scores in stat blocks)
        abilities = {stat: lvl for stat in ("STR", "DEX", "CON", "INT", "PSY", "EGO")}

        # Capture attack data from bestiary (raw strings; 11b handles parsing/rolling).
        # `entry` and `s` are set in the try-block above; safe to read here.
        _atk_stats = entry.get("stats", {}) if entry else {}
        raw_attacks = list(_atk_stats.get("attacks", []))
        first_attack = raw_attacks[0] if raw_attacks else {}
        attack_name = first_attack.get("name", "Unarmed") if first_attack else "Unarmed"
        attack_damage = first_attack.get("damage", "d4") if first_attack else "d4"

        enemy_dict[full_name] = {
            "hp": hp,
            "max_hp": hp,
            "av": av,
            "morale": morale,
            "lvl": lvl,
            "abilities": abilities,
            "creature_type": creature_type,   # the creature NAME (unchanged, legacy field)
            "resist_type": resist_type,       # the resistance TYPE (Biological/Synthetic/...)
            "resistances": resistances,       # resolved profile for combat
            "incorporeal": incorporeal,       # immune to all but hypergeometric/anti-paradoxical
            "attacks": raw_attacks,           # full attack list (raw, for DM reference)
            "attack_name": attack_name,       # first attack name (default "Unarmed")
            "attack_damage": attack_damage,   # first attack damage string (default "d4")
            "defeated": False,
            "fled": False,
        }

    # Load party snapshot
    chars_data, load_err = _load_characters()
    if load_err or not chars_data:
        # Roster failed to load (missing split-sheet dir, corrupt JSON). Return a
        # clean, loud error instead of crashing on chars_data["characters"] with a
        # raw 'NoneType is not subscriptable' traceback at the moment combat starts.
        return f"ERROR: cannot start combat — character roster failed to load: {load_err or 'no character data'}"
    party_snapshot = {}
    for char_name, char_data in chars_data["characters"].items():
        # Handle both dict and int HP formats
        hp_value = char_data.get("hp", 0)
        if isinstance(hp_value, dict):
            hp_current = hp_value.get("current", 0)
            hp_max = hp_value.get("max", 0)
        else:
            hp_current = hp_value
            hp_max = char_data.get("max_hp", 0)

        party_snapshot[char_name] = {
            "hp": hp_current,
            "max_hp": hp_max,
        }

    # Create combat state
    GAME_STATE["active_combat"] = {
        "encounter_name": encounter_name,
        "started_at": datetime.now().isoformat(),
        "round": 1,
        "initiative": initiative,
        "pcs_acted": False,
        "enemies_acted": False,
        "enemies": enemy_dict,
        "party_snapshot": party_snapshot,
        "morale_checked": False,
        "morale_broken": False,
        "log": [
            f"Round 1: {'PCs' if initiative == 'pcs' else 'Enemies'} act first (rolled {init_roll})"
        ],
    }

    _save_game_state()

    # Format output
    output = [f"Combat initialized: {encounter_name}"]
    for name, data in enemy_dict.items():
        output.append(f"- {name}: {data['hp']}/{data['max_hp']} HP, AV {data['av']}, Morale +{data['morale']}")
    if unmatched_warnings:
        output.append("")
        output.extend(unmatched_warnings)
    output.append("")
    output.append(f"Round 1: {'PCs' if initiative == 'pcs' else 'Enemies'} act first (rolled {init_roll})")

    return "\n".join(output)


def _defender_av(target: str) -> int:
    """Return the AV that *target* defends with this exchange.

    Resolution order:
    1. If there is an active combat and *target* is a key in
       ``active_combat["enemies"]``, return ``int(enemy["av"])``.
    2. Otherwise try to resolve *target* as a PC via ``_load_characters()`` /
       ``_find_character()``.  The PC sheet stores AV as either a plain int
       or a dict ``{"base": N, "source": "...", "conditional": [...]}``.
       When it is a dict we return ``int(av["base"])``.
       **No-double-count rule**: ``av["base"]`` already folds in worn armour
       and shield.  Do NOT add carried-armour ``av_bonus`` on top — that
       would double-count armour that is already baked into the base.
    3. If target cannot be found in either source, return 10 (unarmoured
       default).  Task 11b is responsible for not-found messaging; this
       helper is intentionally silent and safe.

    Returns:
        int AV value, always >= 0.
    """
    # 1. Check active combat enemies first.
    combat = GAME_STATE.get("active_combat")
    if combat:
        enemies = combat.get("enemies", {})
        if target in enemies:
            return int(enemies[target].get("av", 10))

    # 2. Try to resolve as a PC.
    chars_data, err = _load_characters()
    if not err and chars_data:
        _, char = _find_character(chars_data, target)
        if char is not None:
            av_field = char.get("av", 10)
            if isinstance(av_field, dict):
                base_av = int(av_field.get("base", 10))
            else:
                base_av = int(av_field)
            # Derived wound read (spec section 5): Synthskin Damaged's rolled
            # -AV lives on the wound record, never on the sheet's armour --
            # subtract it here so healing the wound restores AV for free.
            # E3 Gitch crystals raise AV (av_bonus); Synthskin Damaged lowers
            # it (av_penalty). Both ride the wound records and heal for free.
            _deff = _wnd.derived_effects(char.get("wounds", []))
            # B3: elixir conditions can also raise AV (Plating, Spineskin,
            # Lithification) -- read condition-side derived_effects too.
            _cav = sum(int(c.get("derived_effects", {}).get("av_bonus", 0))
                       for c in (char.get("conditions") or [])
                       if isinstance(c, dict))
            return max(0, base_av - _deff["av_penalty"] + _deff["av_bonus"] + _cav)

    # 3. Unknown target — return safe default.
    return 10


# Stub functions for other combat actions (to be implemented in later tasks)
def _check_morale_triggers() -> str | None:
    """Check if morale should be checked, run if needed.
    
    Returns:
        Morale result message if triggered, None otherwise
    """
    combat = GAME_STATE.get("active_combat")
    if not combat:
        return None
    
    # Skip if already checked this round
    if combat.get("morale_checked"):
        return None
    
    enemies = combat["enemies"]
    total = len(enemies)
    defeated = sum(1 for e in enemies.values() if e["defeated"] or e["fled"])
    alive = total - defeated
    
    if alive == 0:
        return None  # No one left to check morale
    
    # Check triggers
    triggers = []
    
    # 50% or more defeated
    if defeated >= total / 2:
        triggers.append(f"{defeated}/{total} enemies defeated")
    
    # Leader killed
    for name, data in enemies.items():
        if "leader" in name.lower() and data["defeated"]:
            triggers.append("leader killed")
            break
    
    if not triggers:
        return None
    
    # Run morale check
    combat["morale_checked"] = True
    
    # Get morale bonus from first alive enemy (assume all same type)
    morale_bonus = 0
    for enemy in enemies.values():
        if not enemy["defeated"] and not enemy["fled"]:
            morale_bonus = enemy["morale"]
            break
    
    # Roll d20 + morale vs DC 16
    roll = random.randint(1, 20)
    total_roll = roll + morale_bonus
    success = total_roll >= 16
    
    output = [f"Morale check triggered: {', '.join(triggers)}"]
    output.append(f"Roll: d20+{morale_bonus} = {roll}+{morale_bonus} = {total_roll} vs DC 16")
    
    if success:
        output.append("SUCCESS - Enemies hold firm!")
        combat["log"].append(f"Morale check: SUCCESS ({total_roll} vs 16)")
    else:
        output.append("FAILED - Morale broken!")
        combat["morale_broken"] = True
        
        # Mark remaining enemies as fled
        fled_names = []
        for name, data in enemies.items():
            if not data["defeated"] and not data["fled"]:
                data["fled"] = True
                fled_names.append(name)
        
        if fled_names:
            output.append(f"Fleeing: {', '.join(fled_names)}")

        # When morale breaks, all remaining enemies flee — if that leaves no
        # active combatants, combat is over.
        _all_down = all(e["defeated"] or e["fled"] for e in enemies.values())
        if _all_down:
            output.append(_pf.next_block(
                _pf.push_call("combat", action="end"),
                label="end combat",
            ))

        combat["log"].append(f"Morale check: FAILED ({total_roll} vs 16) - enemies flee")

    return "\n".join(output)

def _check_round_advance() -> str | None:
    """Check if both sides acted, advance round if so.

    Returns:
        Round advance message if triggered, None otherwise
    """
    combat = GAME_STATE.get("active_combat")
    if not combat:
        return None

    # Check if both sides acted
    if not (combat["pcs_acted"] and combat["enemies_acted"]):
        return None

    # Advance round
    combat["round"] += 1

    # Roll new initiative
    init_roll = random.randint(1, 6)
    combat["initiative"] = "pcs" if init_roll % 2 == 0 else "enemies"

    # Reset acted flags
    combat["pcs_acted"] = False
    combat["enemies_acted"] = False

    # Reset morale flag
    combat["morale_checked"] = False

    # Log round transition
    msg = f"Round {combat['round']}: {'PCs' if combat['initiative'] == 'pcs' else 'Enemies'} act first (rolled {init_roll})"
    combat["log"].append(msg)

    # --- Toxin Die: tick every afflicted combatant at the top of the round ---
    tox_lines = []
    for ekey, e in combat.get("enemies", {}).items():
        if e.get("toxin_die") and not e.get("defeated") and not e.get("fled"):
            line = _toxin_tick({"kind": "enemy", "enemy": e, "key": ekey})
            if line:
                tox_lines.append(line)
    data, err = _load_characters()
    if not err and data:
        for pkey in combat.get("party_snapshot", {}):
            kk, char = _find_character(data, pkey)
            if char and char.get("toxin_die"):
                line = _toxin_tick({"kind": "pc", "char": char, "key": kk, "data": data})
                if line:
                    tox_lines.append(line)
    if tox_lines:
        for l in tox_lines:
            combat["log"].append(l)
        msg = msg + "\n" + "\n".join("  ☠ " + l for l in tox_lines)
        # A toxin tick can defeat the LAST enemy (_toxin_tick sets defeated) —
        # if the field is now clear, combat is over.
        _all_down = all(e["defeated"] or e["fled"]
                        for e in combat["enemies"].values())
        if combat["enemies"] and _all_down:
            msg = msg + "\n" + _pf.next_block(
                _pf.push_call("combat", action="end"),
                label="end combat",
            )

    # --- E1 round-cadence conditions (Burning etc.): tick every afflicted PC
    # through the unified damage path; the Twinning gate rides inside it.
    # data/err already loaded above for the toxin PC loop - reuse them. ---
    cond_lines = []
    if not err and data:
        for pkey in combat.get("party_snapshot", {}):
            kk, char = _find_character(data, pkey)
            if not char:
                continue
            hp_d = char.get("hp")
            if isinstance(hp_d, dict) and hp_d.get("current", 0) <= -20:
                continue  # corpse skip
            c_eff = _cnd.condition_effects(char.get("conditions") or [])
            for t in c_eff["round_ticks"]:
                if not t.get("hp"):
                    continue  # round-cadence ability drains not in scope (no hp die)
                t_dmg = dice.roll_notation(t["hp"])["total"]
                t_lines, _dd = _apply_hp_damage_and_wounds(
                    kk, char, data, t_dmg,
                    window_key=f"combat:r{combat['round']}")
                cond_lines.append(
                    f"{char.get('name', kk)}: {t['label']} ticks "
                    f"{t['hp']}={t_dmg} -> "
                    f"{char.get('hp', {}).get('current', '?')}/"
                    f"{char.get('hp', {}).get('max', '?')} HP")
                cond_lines.extend(l for l in t_lines if l)
                _save_single_character(kk, char, data)
                if isinstance(char.get("hp"), dict) and char["hp"].get("current", 0) <= -20:
                    break  # died on this tick - no further ticks on the corpse
    if cond_lines:
        for l in cond_lines:
            combat["log"].append(l)
        msg = msg + "\n" + "\n".join("  ~ " + l for l in cond_lines)
        msg = msg + "\n" + _pf.next_block(
            _pf.push_call("affliction", kind="condition", action="clear",
                          character=_pf.raw('"<name>"'),
                          name=_pf.raw('"<condition>"')),
            label="extinguish/end a ticking condition",
        )

    return msg

def _resolve_attacker_weapon(attacker: str, weapon_name=None):
    """Return the resolved weapon dict for `attacker`, or an error string.

    Looks up the PC's `inventory.carried[]` for weapons (items whose `type`
    contains 'weapon' or that have a `damage` field and are not armour).

    Selection rules:
    - weapon_name given: case-insensitive substring match against each weapon's
      `name`. Exactly one match -> use it. Zero -> error. Multiple -> ambiguous.
    - weapon_name omitted: use the one flagged `primary: true` if exactly one
      exists; else if exactly one carried weapon total, use it; else ambiguous.

    Returns a dict on success, or a plain error string on failure.
    On any error that should STOP damage (not-found, ambiguous), returns str.
    If attacker is not a PC at all, returns None (caller falls through).
    """
    chars_data, err = _load_characters()
    if err or not chars_data:
        return None  # can't load, fall through to manual params

    key, sheet = _find_character(chars_data, attacker)
    if sheet is None:
        return None  # not a PC — caller falls through silently

    carried = sheet.get("inventory", {}).get("carried", [])

    # Filter to weapons: type contains 'weapon' OR has a 'damage' field and is
    # not armour (no av_bonus, type not armour/armor) -- a spiked shield carries
    # a damage field but must NOT be treated as the attacking weapon.
    weapons = [
        item for item in carried
        if ("weapon" in str(item.get("type", "")).lower())
        or (
            "damage" in item
            and "av_bonus" not in item
            and "armour" not in str(item.get("type", "")).lower()
            and "armor" not in str(item.get("type", "")).lower()
        )
    ]

    if weapon_name:
        needle = weapon_name.lower()
        matches = [w for w in weapons if needle in w.get("name", "").lower()]
        if len(matches) == 0:
            names = ", ".join(w.get("name", "?") for w in weapons) or "(none)"
            return f"weapon '{weapon_name}' not found on {attacker}; options: {names}"
        if len(matches) > 1:
            names = ", ".join(w.get("name", "?") for w in matches)
            return f"ambiguous — '{weapon_name}' matches multiple weapons on {attacker}: {names}; name it more precisely"
        return matches[0]
    else:
        # No weapon_name: try primary flag, then single-weapon fallback
        primaries = [w for w in weapons if w.get("primary")]
        if len(primaries) == 1:
            return primaries[0]
        if len(weapons) == 1:
            return weapons[0]
        names = ", ".join(w.get("name", "?") for w in weapons) or "(none)"
        return f"ambiguous — {attacker} has multiple weapons, pass weapon='...'; options: {names}"


def _weapon_is_ranged(weapon_dict: dict) -> bool:
    """Decide whether a resolved weapon dict is ranged (True) or melee (False).

    Resolution order:
    1. Weapon has a 'range' field: "ranged" -> True; "melee" -> False.
    2. Weapon 'type' contains "ranged" -> True; contains "melee" -> False.
    3. Case-insensitive suffix match of weapon name against RANGED_WEAPONS names
       (longest match wins -> True) vs MELEE_WEAPONS names (-> False).
    4. Default False (treat as melee).
    """
    # 1. Explicit range field
    range_field = str(weapon_dict.get("range", "")).lower().strip()
    if range_field == "ranged":
        return True
    if range_field == "melee":
        return False

    # 2. Type field
    type_field = str(weapon_dict.get("type", "")).lower()
    if "ranged" in type_field:
        return True
    if "melee" in type_field:
        return False

    # 3. Name suffix match — prefer the longest match to break ties
    name = weapon_dict.get("name", "").lower()
    ranged_names = [v["name"].lower() for v in RANGED_WEAPONS.values()]
    melee_names = [v["name"].lower() for v in MELEE_WEAPONS.values()]

    best_ranged = max((n for n in ranged_names if name.endswith(n)), key=len, default=None)
    best_melee  = max((n for n in melee_names  if name.endswith(n)), key=len, default=None)

    if best_ranged and best_melee:
        return len(best_ranged) >= len(best_melee)
    if best_ranged:
        return True
    if best_melee:
        return False

    # 4. Default: melee
    return False


# Known damage type keywords for parsing enemy attack_damage strings.
_KNOWN_DAMAGE_TYPES = frozenset(
    ["kinetic", "beam", "blast", "flame", "electrical", "tox",
     "hypergeometric", "slashing", "piercing", "bludgeoning"]
)


def _parse_enemy_attack(raw_attack):
    """Parse a bestiary attack_damage string into (dice_str, damage_type, note).

    Bestiary attack strings are NOT always a clean dice expression. They can be:
      - "d8"                        -> ("d8", "kinetic", "")
      - "d8, electrical"            -> ("d8", "electrical", "")
      - "d8 (2x)" / "2d6 (if both claws hit)" -> leading dice + a clause to adjudicate
      - "CON Save vs Amaranthine Venom"       -> no dice at all (save-based)

    Returns:
        (dice_str_or_None, damage_type, note)
        - dice_str: the LEADING dice expression ("d8", "2d6", "2d6 + 1") if present, else None.
        - damage_type: a known damage type split off a trailing ", <type>", else "kinetic".
        - note: a non-empty adjudication note when there is an unhandled clause
          (multi-hit/conditional) or when the attack is special/save-based; else "".
    """
    raw = str(raw_attack or "").strip()
    damage_type = "kinetic"
    damage_text = raw

    # Split off a trailing ", <type>" for the damage type (e.g. "d8, electrical").
    if "," in raw:
        head, tail = raw.split(",", 1)
        type_candidate = tail.strip().lower()
        if type_candidate in _KNOWN_DAMAGE_TYPES:
            damage_type = type_candidate
            damage_text = head.strip()
        # If the trailing token is NOT a known damage type, leave damage_text as the
        # full string so a leading dice expr can still be extracted from it.

    # Extract the LEADING dice expression (e.g. "d8 (2x)" -> "d8", "2d6 (...)" -> "2d6").
    m = re.match(r"^\s*(\d*d\d+(?:\s*\+\s*\d+)?)", damage_text)
    if not m:
        # No leading dice -> special / save-based attack.
        return None, damage_type, f"enemy attack {raw!r} is special/save-based — adjudicate damage manually"

    dice_str = m.group(1).strip()
    leftover = damage_text[m.end():].strip()

    # A2: a trailing SPACE-separated damage type ("d8 TOX", "d10 beam"). If a comma
    # didn't already set the type and the leftover begins with a known damage-type
    # token, consume it as the type so it isn't mistaken for an unhandled clause.
    if damage_type == "kinetic" and leftover:
        parts = leftover.split(None, 1)
        if parts[0].lower() in _KNOWN_DAMAGE_TYPES:
            damage_type = parts[0].lower()
            leftover = parts[1].strip() if len(parts) > 1 else ""

    if leftover:
        note = f"enemy attack clause unhandled: {raw!r} — adjudicate (e.g. multi-hit/conditional)"
    else:
        note = ""
    return dice_str, damage_type, note


def _format_dm_result_block(result: dict) -> str:
    """Render a classified DM-only structured result block from a resolved attack dict."""
    return (
        "=== DM-ONLY COMBAT RESULT (classified — render as prose, never show the player) ===\n"
        + json.dumps(result, indent=2, ensure_ascii=False)
        + "\n=== END DM-ONLY COMBAT RESULT ==="
    )


# Gambits (book p.29): attack total HIGHER than 20 = a stunt in ADDITION to
# damage. Engine flags + lists the book menu; the choice, the target's save,
# and the forgo-damage-to-deny-the-save trade are DM-adjudicated at the table.
_GAMBIT_MENU = (
    "Disarm (STR save) | Damage armour -1 AV (STR save) | Move a second time | "
    "Forcibly move / pin in place (STR save) | Blind with sand/light, 1 turn "
    "(DEX save) | Steal an item (DEX save) | Dismount from steed/vehicle "
    "(STR save) | any comparable physical feat")


def _gambit_block(attacker_label: str, target: str, is_pc_attacker: bool) -> str:
    who = (f"{attacker_label} may attempt a stunt"
           if is_pc_attacker else
           f"DM: {attacker_label} (intelligent foe) may attempt a stunt vs {target}")
    return ("\n*** GAMBIT AVAILABLE (total > 20) *** " + who +
            " IN ADDITION to damage.\n"
            f"Menu: {_GAMBIT_MENU}\n"
            "Target may save against it; the attacker may forgo the attack's "
            "damage to DENY the save. DM adjudicates.")


# ============================================
# C1 REACTIVE TRIGGERS - defender sheet abilities (special_traits.triggers)
# that fire back at an enemy attacker. Book: Acid Blood (Cacogen mutation
# #01), Toxic Sap (Bloomboon #10), Mirrored Leaves (Bloomboon #2).
# Spec: docs/superpowers/specs/2026-06-12-c1-reactive-triggers-design.md
# Only the enemy->PC branch of _combat_attack fires these.
# ============================================

_RX_RANGED_WORDS = ("bow", "rifle", "gun", "sling", "thrown", "spit",
                    "beam", "blast", "ray")
_RX_BITE_WORDS = ("bite", "biting", "fangs", "maw", "jaws")
_RX_TOX_RANKS = ("d4", "d6", "d8", "d10", "d12", "d20")


def _reactive_triggers_for(char) -> list:
    """The defender's reactive-trigger records. Always a list; [] when the
    sheet lacks special_traits/triggers or the shapes are wrong (every
    existing sheet/fixture no-ops cleanly)."""
    if not isinstance(char, dict):
        return []
    traits = char.get("special_traits")
    if not isinstance(traits, dict):
        return []
    trigs = traits.get("triggers")
    if not isinstance(trigs, list):
        return []
    return [t for t in trigs if isinstance(t, dict)]


def _enemy_attack_is_ranged(enemy_data: dict) -> bool:
    """Best-effort ranged read: an explicit range field saying ranged, or a
    ranged-flavored attack name. Default is melee (the REACTIVE line says
    'assumed melee - DM may waive')."""
    rng = str(enemy_data.get("range") or "").lower()
    if "ranged" in rng:
        return True
    name = str(enemy_data.get("attack_name") or "").lower()
    return any(w in name for w in _RX_RANGED_WORDS)


def _enemy_attack_is_bite(enemy_data: dict) -> bool:
    """Bite-pattern read on the enemy attack name (case-insensitive)."""
    name = str(enemy_data.get("attack_name") or "").lower()
    return any(w in name for w in _RX_BITE_WORDS)


def _fire_reactive_triggers(triggers, enemy_key, enemy_data, pc_name,
                            bite_only=False, missed=False):
    """Fire a defending PC's reactive triggers back at the enemy attacker.

    Called from _combat_attack's enemy->PC hit path AFTER damage applied
    (bite_only=False), or on the TOX-reroute path where the hit landed as a
    Toxin Die instead of flat damage (bite_only=True: only the bitten
    trigger fires there - a retaliation needs applied damage).
    missed=True is the C2 enemy->PC MISS/FUMBLE path (R-C2b, Barbed Bark):
    ONLY triggers with when='melee_missed' fire there, and melee_missed
    triggers NEVER fire on a hit - the two phases are disjoint.
    reflect_save is handled pre-damage (the withhold path), never here.
    Unknown effect values degrade to a REACTIVE FLAG line (R-C1c: future
    reactives can be data-only sheet additions). Returns (lines, fired).
    """
    lines, fired = [], []
    is_ranged = _enemy_attack_is_ranged(enemy_data)
    is_bite = _enemy_attack_is_bite(enemy_data)
    for trig in triggers:
        effect = str(trig.get("effect") or "").strip().lower()
        name = trig.get("name", "Reactive ability")
        # C2 phase gate: melee_missed triggers belong to the miss path only;
        # everything else belongs to the hit path only.
        trig_missed = (str(trig.get("when") or "").strip().lower()
                       == "melee_missed")
        if trig_missed != missed:
            continue
        if effect == "retaliate":
            # Acid Blood: melee attacker that damaged the PC takes the die.
            if bite_only or is_ranged:
                continue
            n = _roll_stat_expr(trig.get("damage", "d4"), default=1)
            dtype = trig.get("damage_type", "acid")
            lines.append(f"REACTIVE - {name}: {enemy_key} takes {n} {dtype} "
                         f"(assumed melee - DM may waive)")
            # The full enemy-damage path: resistances + defeat handling +
            # combat-end push (a retaliation CAN kill the attacker). A
            # retaliation is NOT an action: never tick the round off it.
            lines.append(_combat_damage(enemy_key, n, dtype,
                                        skip_round_advance=True))
            fired.append(name)
        elif effect == "tox_attack":
            # Toxic Sap: a biting attacker eats the tox_die (B1 machinery -
            # enemy auto CON save; non-Biological immune with the line saying so).
            if not is_bite:
                continue
            tox_die = str(trig.get("tox_die") or "").strip().lower()
            if tox_die not in _RX_TOX_RANKS:
                # dice_chain would silently degrade garbage to 'cured' - a
                # typo'd sheet must surface loudly instead of no-op firing.
                lines.append(f"REACTIVE FLAG - {name}: tox_die "
                             f"'{trig.get('tox_die')}' is not a legal rank "
                             f"({'/'.join(_RX_TOX_RANKS)}) - fix the sheet "
                             f"record; nothing applied.")
                fired.append(name)
                continue
            tox_out = _toxin_attack_reroute(attacker=pc_name, target=enemy_key,
                                            tox_die=tox_die, attacker_kind="pc")
            lines.append(f"REACTIVE - {name}: {tox_out}")
            fired.append(name)
        elif effect == "reflect_save":
            continue  # withheld pre-damage in _combat_attack, not here
        else:
            if bite_only:
                continue
            note = str(trig.get("note") or "").strip()
            lines.append(f"REACTIVE FLAG - {name} (effect "
                         f"'{trig.get('effect')}' is not engine-known - "
                         f"DM adjudicates)."
                         + (f" Note: {note}" if note else ""))
            fired.append(name)
    return lines, fired


def _combat_attack(attacker: str, weapon: str, target: str,
                   auto_roll=None, to_hit=None, damage_roll=None, thrown=False) -> str:
    """Resolve a full attack: to-hit roll, hit/miss/fumble/crit, damage on hit.

    Book rules (Crimson Hound Explorer's Guide p.29):
    - Roll d20 + STR (melee) or DEX (ranged). Total strictly > defender AV = hit.
    - Unmodified 1 = fumble (miss, weapon drops/jams).
    - Unmodified 20 = automatic hit + double rolled damage.

    Roll routing:
    - Any PC may supply to_hit (+ damage_roll) to route the player's own physical
      dice through the engine — it adds the ability bonus and surfaces the gambit,
      so the DM never hand-resolves (the dropped-DEX / missed-gambit playtest bug).
    - Omit to_hit and any non-player PC (or enemy) auto-rolls, as before.
    - Iron Law 3: the player PC is the one PC who MUST supply to_hit + damage_roll
      (or pass auto_roll=True); the engine never rolls their dice unprompted.

    Returns a concise DM result string including to-hit total vs AV, hit/miss/crit/fumble,
    and (on hit) the _combat_damage output.
    """
    combat = GAME_STATE.get("active_combat")
    if not combat:
        return "No active combat. Use action='init' to start combat."

    if not attacker:
        return "Action 'attack' requires 'attacker' parameter."
    if not target:
        return "Action 'attack' requires 'target' parameter."

    # --- Convenience: resolve bare target name to its full descriptor key ---
    if target not in combat["enemies"] and target not in combat["party_snapshot"]:
        _t_lower = target.strip().lower()
        # Try enemies first (bare name or "name (descriptor)" prefix)
        _matches = [
            k for k in combat["enemies"]
            if k.lower() == _t_lower
            or k.lower().startswith(_t_lower + " (")
        ]
        if len(_matches) == 1:
            target = _matches[0]
        else:
            # Also try party_snapshot keys case-insensitively (production keys
            # are lowercase filename stems; DM may pass capitalized display name)
            _ps_matches = [
                k for k in combat["party_snapshot"]
                if k.lower() == _t_lower
            ]
            if len(_ps_matches) == 1:
                target = _ps_matches[0]

    # --- Classify attacker ---
    chars_data, _err = _load_characters()
    characters = chars_data.get("characters", {}) if chars_data else {}
    # Case-insensitive PC lookup so "Brek" resolves against key "brek"
    pc_key, pc_char = _find_character(chars_data, attacker) if chars_data else (None, None)
    is_pc = pc_char is not None

    # Case-insensitive enemy lookup. Mirror the target resolver: accept a bare
    # base name ("Moonbeast Nymph") for an enemy keyed with a position descriptor
    # ("Moonbeast Nymph (left flank)") when the match is unambiguous, so the DM's
    # natural name resolves on the first try instead of forcing the exact suffix.
    _enemy_key = None
    if attacker in combat.get("enemies", {}):
        _enemy_key = attacker
    else:
        _att_lower = attacker.strip().lower()
        _exact = [k for k in combat.get("enemies", {}) if k.lower() == _att_lower]
        _prefix = [k for k in combat.get("enemies", {})
                   if k.lower().startswith(_att_lower + " (")]
        if len(_exact) == 1:
            _enemy_key = _exact[0]
        elif len(_prefix) == 1:
            _enemy_key = _prefix[0]
    is_enemy = _enemy_key is not None

    if not is_pc and not is_enemy:
        return (f"Attacker '{attacker}' not found in party or combat enemies. "
                f"Party: {', '.join(characters.keys())}; "
                f"Enemies: {', '.join(combat['enemies'].keys())}")

    # --- C21: attacker liveness. An honest engine refuses a swing FROM a
    # defeated/fled enemy or a downed/unconscious/dead PC (the damage path
    # already refuses damage TO a defeated enemy; this is the symmetric guard).
    if is_enemy:
        _att_data = combat.get("enemies", {}).get(_enemy_key, {})
        if _att_data.get("defeated"):
            return f"{_enemy_key} is already defeated."
        if _att_data.get("fled"):
            return f"{_enemy_key} has fled."
    if is_pc:
        # Fail-open on a malformed hp shape: an ATTACK guard must NOT paralyze
        # combat over a bad sheet, so missing/non-dict hp -> treat as alive.
        # This is deliberately the OPPOSITE direction from
        # engine_core._all_pcs_down, which fails DOWN (malformed hp counts as
        # cur=0) because a wipe check is safer erring toward "party is down".
        _hp = pc_char.get("hp")
        _cur = _hp.get("current") if isinstance(_hp, dict) else None
        _pname = pc_char.get("name", attacker)
        if _wnd.derived_effects(pc_char.get("wounds", []) or [])["unconscious"]:
            return (f"BLOCKED - {_pname} is unconscious and cannot attack until "
                    f"the wound is resolved (affliction kind=wound, action=heal).")
        if isinstance(_cur, (int, float)) and _cur <= 0:
            _state = "dead" if _cur <= -20 else "incapacitated at 0 HP"
            return (f"BLOCKED - {_pname} is {_state} (HP {int(_cur)}) and cannot "
                    f"attack. Heal above 0 HP or resolve the wound "
                    f"(affliction kind=wound) first.")

    # Iron Law 3: the DESIGNATED PLAYER PC must supply their own d20/damage; all
    # other attackers (followers, pets, enemies) auto-roll. The player PC is
    # designated EXPLICITLY (NOT a hardcoded name), case-insensitively against the
    # resolved sheet key so 'name'/'Name'/'NAME' all gate identically:
    #   $RUBICON_PLAYER_PC  ->  else a sheet flagged {"player": true}.
    # char-gen / character(action="register") stamps the flag on the player's PC,
    # so a fresh campaign gets Iron Law 3 with zero config; $RUBICON_PLAYER_PC is
    # the override. Undesignated -> everyone auto-rolls (the pre-OSS default).
    _pkey = os.environ.get("RUBICON_PLAYER_PC")
    _pkey = _pkey.strip().lower() if (_pkey and _pkey.strip()) else None
    if _pkey is None and isinstance(characters, dict):
        _flagged = [k for k, c in characters.items()
                    if isinstance(c, dict) and c.get("player") is True]
        if len(_flagged) == 1:
            _pkey = _flagged[0].lower()
    is_player_pc = (pc_key is not None and _pkey is not None
                    and pc_key.lower() == _pkey)
    need_supplied = is_player_pc and not auto_roll
    # Any PC may ROUTE their own physical d20/damage through the engine by
    # supplying to_hit (+ damage_roll). The engine then adds the ability bonus and
    # surfaces the gambit, so the DM never hand-resolves a player roll — the bug
    # that dropped a DEX modifier and missed a GAMBIT in playtest. The player PC is
    # the subset that additionally REQUIRES it (the need_supplied gate below); for
    # everyone else it is opt-in (omit to_hit -> engine auto-rolls, as before).
    pc_supplied = is_pc and (not auto_roll) and (to_hit is not None)

    blind_note = ""  # set when a blind PC attacker swings in melee (DIS instruction)

    # --- Resolve attack profile ---
    if is_pc:
        # PC attacker: resolve weapon from sheet
        w = _resolve_attacker_weapon(attacker, weapon)
        if isinstance(w, str):
            return w  # error string from resolver (not-found / ambiguous)
        if w is None:
            return f"Could not resolve weapon for {attacker}."

        # --- Broken-item guard (Damaged Item wound, spec section 6) ---
        # Broken trumps everything else about the weapon: checked before
        # usage-die/ammo and blind reads. No dice, no fired record.
        if w.get("broken"):
            return "BLOCKED - " + _broken_item_msg(w.get('name', weapon or 'weapon'))

        damage_dice = w.get("damage", "d4")
        wdt = w.get("damage_type", "kinetic")
        ksub = w.get("kinetic_subtype")
        effective_damage_type = (ksub if (wdt == "kinetic" and ksub) else wdt)
        engine_tags = w.get("engine_tags") or []
        # HOUSE RULE: a thrown attack is a ranged attack (DEX), even with a melee
        # weapon. RAW has no thrown mechanic — stat keys off weapon type — so this
        # is deliberate "our Vaarn" homebrew. thrown never downgrades a ranged weapon.
        is_ranged = bool(thrown) or _weapon_is_ranged(w)
        stat_label = "DEX" if is_ranged else "STR"
        char = pc_char  # already resolved case-insensitively above
        abilities = char.get("abilities", {})
        stat_obj = abilities.get(stat_label, {})
        try:
            bonus = stat_obj.get("current", 0) if isinstance(stat_obj, dict) else int(stat_obj)
        except (TypeError, ValueError):
            bonus = 0
        weapon_display = w.get("name", weapon or "weapon")
        if thrown:
            weapon_display += " (thrown)"
        attack_note = ""  # PC weapons carry clean dice exprs — never adjudicated

        # --- Derived wound read: blind PC attacker (Vischip Disabled, spec s5) ---
        # Ranged is impossible; melee proceeds at DIS. PC attack dice are
        # player-facing (Iron Law 3), so the DIS is an INSTRUCTION, never an
        # engine-side reroll.
        if _wnd.derived_effects(char.get('wounds', []))['blind']:
            _blind_names = ", ".join(
                r.get('name', '?') for r in char.get('wounds', []) or []
                if isinstance(r, dict) and r.get('blind')) or "blind"
            if is_ranged:
                return (f"BLOCKED - {char.get('name', attacker)} is blind "
                        f"({_blind_names}): ranged attacks are impossible until "
                        f"the wound is fixed. Melee attacks are possible at "
                        f"DISADVANTAGE.")
            blind_note = f" | at DISADVANTAGE (blind: {_blind_names} - roll 2d20, take the worse)"

        # --- Usage Die: block an Expended ranged weapon; record a fired one ---
        if _usage_applies(w) and not _usage_is_parasitic(w):
            if _usage_is_expended(w):
                _wname = w.get("name", "weapon")
                _note = w.get("ammo_note", "")
                _carried = _usage_carried_ammo(char)
                _cstr = ", ".join(_carried) if _carried else "none"
                _char_name = char.get("name") or attacker
                _calls = [_pf.push_call("usage", action="reload",
                                        character=_char_name, weapon=_wname)]
                if _usage_is_fungal(w):
                    _calls.append(_pf.push_call("usage", action="feed",
                                                character=_char_name, weapon=_wname))
                _push = _pf.next_block(
                    *_calls,
                    label=("reload, feed, or switch weapons"
                           if _usage_is_fungal(w) else "reload or switch weapons"),
                )
                return (f"OUT OF AMMO — {_wname} usage die is Expended. "
                        + _push + "."
                        + (f" Note: {_note}." if _note else "")
                        + f" Carried ammo: {_cstr}.")
            _fired = combat.setdefault("weapons_fired", [])
            _entry = {"character": pc_key, "weapon": w.get("name", weapon)}
            if _entry not in _fired:
                _fired.append(_entry)

    else:
        # Enemy attacker — bestiary attack strings are messy (multi-hit clauses,
        # conditionals, save-based). Parse the leading dice expr and surface any
        # unhandled clause as a NOTE so the DM never gets a silent wrong answer.
        enemy_data = combat["enemies"][_enemy_key]  # use resolved key (case-insensitive)
        raw_attack = enemy_data.get("attack_damage", "d4")
        damage_dice, effective_damage_type, attack_note = _parse_enemy_attack(raw_attack)
        engine_tags = []
        bonus = enemy_data.get("lvl", 1)
        weapon_display = enemy_data.get("attack_name", "attack")

    # --- Validate target exists ---
    if target not in combat["enemies"] and target not in combat["party_snapshot"]:
        return (f"Target '{target}' not found in combat. "
                f"Available: {', '.join(list(combat['enemies'].keys()) + list(combat['party_snapshot'].keys()))}")

    # --- Derived wound read: unconscious PC target -> auto-hit (spec s5) ---
    # "While unconscious, all attacks automatically hit": skip the to-hit
    # contest entirely. Wounds live on the SHEET, not the combat snapshot.
    auto_hit = False
    if target not in combat["enemies"] and target in combat["party_snapshot"] and chars_data:
        _tgt_key, _tgt_char = _find_character(chars_data, target)
        if (_tgt_char is not None
                and _wnd.derived_effects(_tgt_char.get('wounds', []))['unconscious']):
            auto_hit = True

    # --- Gating: the player PC requires supplied rolls (unless auto_roll) ---
    # An auto-hit needs no to-hit roll; the player PC still owns the damage roll
    # (asked for below).
    if need_supplied and to_hit is None and not auto_hit:
        _pc_label = pc_char.get("name", pc_key) if isinstance(pc_char, dict) else pc_key
        _blind_prompt = (" NOTE: the attacker is BLIND - roll at DISADVANTAGE "
                         "(2d20, pass the worse)." if blind_note else "")
        return (
            f"{_pc_label} is attacking — roll the d20 and pass `to_hit=<result>` (and `damage_roll=<result>` "
            f"for when it hits), or set `auto_roll=True` to let the engine roll for them. "
            f"(Iron Law 3: the engine never rolls for the player PC without DM opt-in.)"
            f"{_blind_prompt}"
        )

    # Capture pre-attack morale so the result block reports whether THIS attack
    # broke morale (per-attack), not the persistent combat-wide flag (roadmap A3).
    morale_before = bool(combat.get("morale_broken", False))

    # --- Roll d20 (skipped entirely when the target is unconscious) ---
    if auto_hit:
        d20 = None       # no contest — all attacks automatically hit
        fumble = False
        crit = False
        total = None
    else:
        if pc_supplied:
            d20 = to_hit  # the player's own unmodified d20; engine adds the ability bonus below
        elif blind_note:
            # Blind melee DIS is MECHANICAL when the engine owns the roll
            # (Iron Law 3 reserves only the player PC's dice): 2d20, keep the worse.
            _r1, _r2 = random.randint(1, 20), random.randint(1, 20)
            d20 = min(_r1, _r2)
            blind_note += f" [rolled {_r1}/{_r2}, kept {d20}]"
        else:
            d20 = random.randint(1, 20)
        fumble = (d20 == 1)
        crit   = (d20 == 20)
        total  = d20 + bonus

    # --- Resolve hit ---
    defender_av = _defender_av(target)
    # R3: armour-ignoring weapons contest vs AV 10 -- CAPPED, never raised
    # (R-R3b: an Entangled AV 9 target stays AV 9). Real AV is preserved in
    # av_override for the Piercing/Mauling bracket, which reads REAL armour.
    av_override = None
    if is_pc and not auto_hit:
        _ov_key = _weapon_av_override(w)
        if _ov_key and defender_av > 10:
            av_override = {"real": defender_av, "effective": 10,
                           "source": _ov_key}
            defender_av = 10
    hit = auto_hit or ((not fumble) and (crit or total > defender_av))

    # --- Build result header ---
    attacker_label = f"{attacker} → {target}"
    if auto_hit:
        roll_detail = "AUTO-HIT (target unconscious - all attacks automatically hit)"
    else:
        _ov_note = ""
        if av_override:
            _ov_note = (f" ({_AV_OVERRIDE_LABELS[av_override['source']]}"
                        f" -- armour ignored; real AV {av_override['real']})")
        roll_detail = f"d20={d20} + {bonus} = {total} vs AV {defender_av}{_ov_note}{blind_note}"

    attacker_kind = "pc" if is_pc else "enemy"

    # --- C2 (R-C2b): an enemy MELEE miss against a PC fires the defender's
    # melee_missed triggers (Barbed Bark). A fumble is also a miss and fires
    # too - a flailing miss still meets the barbs. Enemy->PC only; the
    # ranged exclusion lives inside _fire_reactive_triggers.
    _rx_miss_lines, _rx_miss_fired = [], []
    if (not hit and attacker_kind == "enemy" and chars_data
            and target not in combat.get("enemies", {})
            and target in combat.get("party_snapshot", {})):
        _rxm_key, _rxm_char = _find_character(chars_data, target)
        _rxm_trigs = _reactive_triggers_for(_rxm_char)
        if _rxm_trigs:
            _rx_miss_lines, _rx_miss_fired = _fire_reactive_triggers(
                _rxm_trigs, _enemy_key, enemy_data, target, missed=True)

    if fumble:
        combat["log"].append(f"{attacker_label}: FUMBLE ({roll_detail})")
        summary = f"FUMBLE — {attacker_label} | {roll_detail} | weapon drops/jams"
        dm_result = {
            "attacker": attacker,
            "target": target,
            "weapon": weapon_display,
            "attacker_kind": attacker_kind,
            "to_hit_d20": d20,
            "to_hit_bonus": bonus,
            "to_hit_total": total,
            "defender_av": defender_av,
            "av_override": av_override,
            "av_damage_mod": None,
            "hit": False,
            "fumble": True,
            "crit": False,
            "damage_type": None,
            "damage_raw": None,
            "damage_doubled": False,
            "damage_sent": None,
            "damage_dealt": None,
            "engine_tags": None,
            "target_hp_after": None,
            "target_max_hp": None,
            "target_defeated": None,
            # C2: a Barbed Bark retaliation kill CAN break morale on a fumble
            "morale_broken": (bool(combat.get("morale_broken", False))
                              and not morale_before),
            "gambit_available": False,
            "reactive": _rx_miss_fired,
            "note": attack_note,
        }
        result = summary
        if _rx_miss_lines:
            result += "\n" + "\n".join(_rx_miss_lines)
        return f"{result}\n{_format_dm_result_block(dm_result)}"

    if not hit:
        combat["log"].append(f"{attacker_label}: MISS ({roll_detail})")
        summary = f"MISS — {attacker_label} | {roll_detail}"
        dm_result = {
            "attacker": attacker,
            "target": target,
            "weapon": weapon_display,
            "attacker_kind": attacker_kind,
            "to_hit_d20": d20,
            "to_hit_bonus": bonus,
            "to_hit_total": total,
            "defender_av": defender_av,
            "av_override": av_override,
            "av_damage_mod": None,
            "hit": False,
            "fumble": False,
            "crit": False,
            "damage_type": None,
            "damage_raw": None,
            "damage_doubled": False,
            "damage_sent": None,
            "damage_dealt": None,
            "engine_tags": None,
            "target_hp_after": None,
            "target_max_hp": None,
            "target_defeated": None,
            # C2: a Barbed Bark retaliation kill CAN break morale on a miss
            "morale_broken": (bool(combat.get("morale_broken", False))
                              and not morale_before),
            "gambit_available": False,
            "reactive": _rx_miss_fired,
            "note": attack_note,
        }
        result = summary
        if _rx_miss_lines:
            result += "\n" + "\n".join(_rx_miss_lines)
        return f"{result}\n{_format_dm_result_block(dm_result)}"

    # --- Hit: compute damage ---
    # C1 Reactive triggers: an enemy hit on a PC may fire the DEFENDER's
    # sheet triggers (special_traits.triggers) back at the attacker.
    # Enemy->PC branch only; [] for every other attacker/target pairing.
    _rx_trigs = []
    if (attacker_kind == "enemy" and chars_data
            and target not in combat.get("enemies", {})
            and target in combat.get("party_snapshot", {})):
        _rx_key, _rx_char = _find_character(chars_data, target)
        _rx_trigs = _reactive_triggers_for(_rx_char)

    # TOX reroute: a TOX/poison hit imposes the Toxin Die instead of flat damage
    # (book: "Biological creatures hit ... must CON save vs a Toxin Die"). The toxin
    # die size is the weapon's damage die, so we branch here before any damage roll.
    if _normalize_damage_type(effective_damage_type) == "poison":
        _tox_die = _toxin_die_from_dice(damage_dice)
        _tox_out = _toxin_attack_reroute(attacker=attacker, target=target,
                                         tox_die=_tox_die, attacker_kind=attacker_kind)
        _hdr = f"HIT — {attacker or 'attacker'} → {target} ({roll_detail})"
        _gx = (_gambit_block(attacker_label, target, is_pc)
               if (total is not None and total > 20) else "")
        # C1: an enemy TOX bite still fires the bitten trigger (Toxic Sap)
        # back at the biter - the hit landed even though the damage rides
        # the Toxin Die instead of flat HP (bite_only: no retaliation here).
        _rx_out = ""
        if _rx_trigs:
            _rx_lines, _rx_fired = _fire_reactive_triggers(
                _rx_trigs, _enemy_key, enemy_data, target, bite_only=True)
            if _rx_lines:
                _rx_out = "\n" + "\n".join(_rx_lines)
        return f"{_hdr}\n{_tox_out}{_gx}{_rx_out}"

    # --- R3: AV-conditional damage bracket (Piercing / Mauling) ---
    # Reads the target's REAL armour, never the vibroactive-capped contest
    # value (an Exotic weapon legally carries Piercing + Vibroactive).
    real_av = av_override["real"] if av_override else defender_av
    _av_tag = _weapon_av_damage_tag(w) if is_pc else None
    _bracket = None
    if _av_tag == "piercing":
        _bracket = ("extra-die" if real_av >= 16
                    else ("halved" if real_av <= 13 else None))
    elif _av_tag == "mauling":
        _bracket = ("extra-die" if real_av <= 13
                    else ("halved" if real_av >= 16 else None))
    _die_m = re.match(r"\s*\d*d(\d+)", str(damage_dice or ""), re.IGNORECASE)
    _av_die = f"d{_die_m.group(1)}" if _die_m else None
    if _bracket == "extra-die" and _av_die is None:
        _bracket = None  # diceless damage expr -- nothing to add
    av_damage_mod = ({"tag": _av_tag, "bracket": _bracket, "real_av": real_av}
                     if _bracket else None)

    if need_supplied or pc_supplied:
        # The player owns these dice (the player PC by Iron Law 3, or any PC routing
        # a supplied to_hit). Use their damage_roll; if absent, ask for it. (A player-PC
        # auto-hit keeps need_supplied so Iron Law 3 still holds with no to_hit.)
        if damage_roll is None:
            # R3 (R-R3c): the extra die is the PLAYER'S roll (Iron Law 3) --
            # instruct it; halving is arithmetic the engine applies below.
            _mod_note = ""
            if _bracket == "extra-die":
                _mod_note = (f" {_av_tag.title()} vs AV {real_av}: roll the "
                             f"{_av_die} damage die TWICE and pass the total.")
            elif _bracket == "halved":
                _mod_note = (f" {_av_tag.title()} vs AV {real_av}: pass your "
                             f"roll; the engine will halve it (min 1).")
            return (
                f"Hit confirmed ({roll_detail}). "
                f"Now pass `damage_roll=<your roll>` to apply damage."
                + _mod_note
            )
        amount = damage_roll
    elif damage_dice is None:
        # Special/save-based enemy attack with no dice expr: apply a placeholder 1
        # but the attack_note (set above) makes the DM aware to override.
        amount = 1
    else:
        amount = _roll_stat_expr(damage_dice, default=1)

    # R3: engine-rolled extra die (everyone but the player PC -- theirs is supplied
    # inside damage_roll per the prompt above). Added BEFORE crit doubling:
    # the book's crit doubles "rolled damage" and the extra die is rolled.
    _av_note = ""
    if _bracket == "extra-die" and not need_supplied:
        _av_extra = _roll_stat_expr(_av_die, default=1)
        amount += _av_extra
        _av_note = (f" [+{_av_extra} {_av_tag} extra {_av_die}"
                    f" vs AV {real_av}]")

    base_amount = amount  # pre-crit, pre-halving; includes any extra die
    if crit:
        amount *= 2
    _crit_amount = amount  # post-crit, pre-halving -- the hit_line's x2 product
    if _bracket == "halved":
        # Floor, minimum 1 -- a hit always deals something. Applied after
        # crit doubling (order pinned by spec).
        amount = max(1, amount // 2)
        _av_note = f" [{_av_tag}: halved vs AV {real_av} -> {amount}]"

    crit_tag = " [CRIT — double damage]" if crit else ""

    # --- C1 reflect_save (Mirrored Leaves): a beam hit on a trigger-bearing
    # PC is WITHHELD - the result reports the HIT and the rolled amount, the
    # player rolls the save, and the DM applies the pushed FAIL/SUCCESS fork.
    if _rx_trigs and str(effective_damage_type or "").lower() == "beam":
        _refl = next((t for t in _rx_trigs
                      if str(t.get("effect") or "").strip().lower() == "reflect_save"),
                     None)
        if _refl is not None:
            _refl_name = _refl.get("name", "Reactive ability")
            _refl_save = str(_refl.get("save") or "DEX").upper()
            gambit_available = total is not None and total > 20
            hit_line = (
                f"HIT{crit_tag} - {attacker_label} ({weapon_display}) | "
                f"{roll_detail} | rolled {amount} beam - WITHHELD ({_refl_name})"
            )
            _fail_call = _pf.push_call("combat", action="damage", target=target,
                                       amount=_pf.raw(amount), damage_type="beam")
            _refl_call = _pf.push_call("combat", action="damage", target=_enemy_key,
                                       amount=_pf.raw(amount), damage_type="beam")
            _rx_block = (
                f"REACTIVE - {_refl_name}: beam damage WITHHELD. "
                f"{target} rolls a {_refl_save} save - player-rolled - "
                f"(d20 + {_refl_save}; total above 15 succeeds).\n"
                f"  On FAIL: {_fail_call}\n"
                f"  On SUCCESS (reflected back at the attacker): {_refl_call}"
            )
            # A beam attack can ALSO be a bite: the withhold early-returns
            # before the post-damage trigger pass, so surface the bitten
            # lever here instead of swallowing it silently.
            if _enemy_attack_is_bite(enemy_data):
                _bt = next((t for t in _rx_trigs
                            if str(t.get("effect") or "").strip().lower() == "tox_attack"),
                           None)
                if _bt is not None:
                    _bt_name = _bt.get("name", "Reactive ability")
                    _bt_die = str(_bt.get("tox_die") or "d10")
                    _bt_call = _pf.push_call("affliction", kind="toxin", action="check",
                                             target=_enemy_key, tox_die=_bt_die)
                    _rx_block += (f"\n  NOTE: this attack is also a bite - "
                                  f"{_bt_name} applies to the biter; DM lever: "
                                  f"{_bt_call}")
            dm_result = {
                "attacker": attacker,
                "target": target,
                "weapon": weapon_display,
                "attacker_kind": attacker_kind,
                "to_hit_d20": d20,
                "to_hit_bonus": bonus,
                "to_hit_total": total,
                "defender_av": defender_av,
                "av_override": av_override,
                "av_damage_mod": av_damage_mod,
                "hit": True,
                "fumble": False,
                "crit": crit,
                "damage_type": effective_damage_type,
                "damage_raw": base_amount,
                "damage_doubled": crit,
                "damage_sent": None,           # withheld - nothing hit the pipeline
                "damage_dealt": None,
                "engine_tags": engine_tags,
                "target_hp_after": None,
                "target_max_hp": None,
                "target_defeated": None,
                "morale_broken": False,
                "gambit_available": gambit_available,
                "reactive": [_refl_name],
                "reactive_pending": True,
                "reactive_withheld": amount,
                "note": attack_note,
            }
            result = f"{hit_line}\n{_rx_block}"
            if gambit_available:
                result += _gambit_block(attacker_label, target, is_pc)
            if attack_note:
                result += f"\n[NOTE: {attack_note}]"
            result += f"\n{_format_dm_result_block(dm_result)}"
            return result

    # --- Capture pre-damage HP (enemy targets only) so we can report the TRUE
    #     post-resistance damage dealt, not just the amount handed to the pipeline.
    _hp_before = None
    if target in combat.get("enemies", {}):
        _hp_before = combat["enemies"][target].get("hp")

    # --- Apply damage via the full resistance/wound/HP pipeline ---
    damage_result = _combat_damage(target, amount, effective_damage_type,
                                   weapon_tags=engine_tags)

    # --- Read post-apply target state (best-effort) ---
    if target in combat.get("enemies", {}):
        _enemy_post = combat["enemies"][target]
        target_hp_after = _enemy_post.get("hp")
        target_max_hp = _enemy_post.get("max_hp")
        target_defeated = _enemy_post.get("defeated")
        # Authoritative damage dealt = real HP removed (post-resistance).
        damage_dealt = (
            _hp_before - target_hp_after
            if (_hp_before is not None and target_hp_after is not None)
            else None
        )
    else:
        # PC target: HP is applied via the PC pipeline; None is acceptable
        target_hp_after = None
        target_max_hp = None
        target_defeated = None
        damage_dealt = None

    # --- B2: poisoned blade - one dose, first connecting hit (R-B2b).
    # PC->enemy mirror of the C1 firing sites: fires AFTER the hit's damage
    # applied + defeat handling. The pop happens BEFORE the apply so a second
    # connecting hit in the same resolution finds the coating already gone.
    _coat_lines, _coat_label = [], None
    if (is_pc and target in combat.get("enemies", {})
            and isinstance(w, dict) and w.get("poison_coating")):
        _coating, _coat_warn = _consume_weapon_coating(attacker, w)
        if _coat_warn:
            _coat_lines.append(_coat_warn)
        if _coating:
            _coat_label = _coating.get("label", "poison")
            _coat_lines.append(
                f"The {_coat_label} on {w.get('name', 'the weapon')} does its "
                f"work (coating spent):")
            _coat_lines.append(_toxin_dispatch(
                "poison_apply", target=target, poison=_coating.get("poison")))

    # --- C1 Reactive triggers fire AFTER the hit's damage applied (enemy->PC).
    # _enemy_key/enemy_data exist whenever _rx_trigs is non-empty (enemy attacker).
    _rx_lines, _rx_fired = [], []
    if _rx_trigs:
        _rx_lines, _rx_fired = _fire_reactive_triggers(
            _rx_trigs, _enemy_key, enemy_data, target)

    # A3: did THIS attack break morale? (post-damage state minus the pre-attack
    # flag). Computed AFTER the reactive firing: a retaliation kill can break
    # the remaining enemies' morale and must be stamped on THIS result.
    morale_broke_this_attack = bool(combat.get("morale_broken", False)) and not morale_before

    # book p.29: strictly higher than 20; auto-hits (unconscious target)
    # have no roll - no gambit flag (anything goes on the helpless anyway).
    # C1: a retaliation can kill the attacking enemy mid-result - a defeated
    # attacker gets no gambit (suppressed with the line below).
    _attacker_downed = bool(
        attacker_kind == "enemy" and _rx_fired
        and combat["enemies"].get(_enemy_key, {}).get("defeated"))
    gambit_available = (total is not None and total > 20
                        and not _attacker_downed)
    hit_line = (
        f"HIT{crit_tag} — {attacker_label} ({weapon_display}) | "
        f"{roll_detail} | rolled {base_amount}"
        f"{' × 2 = ' + str(_crit_amount) if crit else ''} {effective_damage_type}{_av_note}"
    )
    dm_result = {
        "attacker": attacker,
        "target": target,
        "weapon": weapon_display,
        "attacker_kind": attacker_kind,
        "to_hit_d20": d20,
        "to_hit_bonus": bonus,
        "to_hit_total": total,
        "defender_av": defender_av,
        "av_override": av_override,
        "av_damage_mod": av_damage_mod,
        "hit": True,
        "fumble": False,
        "crit": crit,
        "damage_type": effective_damage_type,
        "damage_raw": base_amount,           # pre-crit base roll
        "damage_doubled": crit,
        "damage_sent": amount,               # post-crit, post-AV-bracket, pre-resistance amount handed to the damage pipeline
        "damage_dealt": damage_dealt,        # actual HP removed from the target after resistances; None for PC targets — authoritative
        "engine_tags": engine_tags,
        "target_hp_after": target_hp_after,
        "target_max_hp": target_max_hp,
        "target_defeated": target_defeated,
        "morale_broken": morale_broke_this_attack,
        "gambit_available": gambit_available,
        "reactive": _rx_fired,
        "note": attack_note,
    }
    if _coat_label:
        dm_result["poison_coating_fired"] = _coat_label
    result = f"{hit_line}\n{damage_result}"
    if _coat_lines:
        result += "\n" + "\n".join(_coat_lines)
    if _rx_lines:
        result += "\n" + "\n".join(_rx_lines)
    if _attacker_downed and total is not None and total > 20:
        result += "\n(no gambit - attacker defeated by retaliation)"
    if gambit_available:
        result += _gambit_block(attacker_label, target, is_pc)
    if attack_note:
        result += f"\n[NOTE: {attack_note}]"
    result += f"\n{_format_dm_result_block(dm_result)}"
    return result


def _combat_damage(target: str, amount: int, damage_type: str, ability_stat: str = None,
                   weapon_tags=None, attacker: str = None, weapon: str = None,
                   *, skip_round_advance: bool = False) -> str:
    """Apply damage to target, check defeat, auto-check morale.

    skip_round_advance=True suppresses the end-of-call round-advance check.
    Used by the C1 reactive-trigger retaliation: a retaliation is not an
    action, so it must never tick the round / reroll initiative mid-result.

    If attacker is a PC name and the target is an enemy, the attacker's weapon
    is auto-read from their character sheet (inventory.carried[]).  The weapon's
    damage_type / kinetic_subtype / engine_tags override the manually-passed
    damage_type / weapon_tags for the enemy-resistance calculation.  Pass
    weapon='...' to select by substring when the attacker carries multiple
    weapons; omit to use the primary-flagged or sole weapon.

    If ability_stat is provided (STR/DEX/CON/INT/PSY/EGO), applies amount as
    ability score damage to an enemy rather than HP damage. Enemy ability scores
    start at LVL (house rule: Vaarn 2e has no ability scores in stat blocks).
    Ability damage = save penalty equal to amount rolled for relevant saves.
    """

    combat = GAME_STATE.get("active_combat")
    if not combat:
        return "No active combat. Use action='init' to start combat."

    if not target:
        return "Action 'damage' requires 'target' parameter."

    if not amount or amount <= 0:
        return "Action 'damage' requires positive 'amount' parameter."

    output = []
    _events = []  # mechanics-ticker events (enemy state only; PC path self-tickers)

    # Convenience resolution (2026-06-07 audit): enemies are stored under their
    # full descriptor key (e.g. "bandit_leader (vanguard)"), but a DM mid-combat
    # often types just the bare name ("bandit_leader"). If the exact key is not a
    # combatant, try to resolve a bare name to its descriptor key — but ONLY when
    # exactly one enemy matches (prefix on "name (descriptor)" or case-insensitive
    # exact). On collision we leave target unchanged so the normal not-found path
    # below lists the available targets.
    if target not in combat["enemies"] and target not in combat["party_snapshot"]:
        _t = target.strip()
        _t_lower = _t.lower()
        _matches = [
            k for k in combat["enemies"]
            if k.lower() == _t_lower
            or k.lower().startswith(_t_lower + " (")
        ]
        if len(_matches) == 1:
            target = _matches[0]

    # --- Attacker weapon auto-read (Task 10) ---
    # When attacker is a PC and the target is an enemy (not a PC), resolve the
    # weapon from the attacker's character sheet and override damage_type /
    # weapon_tags with the sheet values.  Attacker omitted or not a PC -> no-op.
    if attacker and target in combat["enemies"]:
        _weapon_result = _resolve_attacker_weapon(attacker, weapon)
        if isinstance(_weapon_result, str):
            # Error string (not-found / ambiguous): stop and return it.
            return _weapon_result
        elif _weapon_result is not None:
            # --- Broken-item guard (Damaged Item wound, spec section 6) ---
            # _combat_damage is independently callable (action='damage' with
            # attacker=): without this, a broken weapon's damage profile would
            # silently apply here even though _combat_attack blocks the swing.
            if _weapon_result.get("broken"):
                return ("BLOCKED - " +
                        _broken_item_msg(_weapon_result.get('name', weapon or 'weapon')))
            # Resolved weapon dict: extract type + tags.
            _wdt = _weapon_result.get("damage_type", damage_type)
            _ksub = _weapon_result.get("kinetic_subtype")
            # Use kinetic_subtype as the effective damage type when set
            if _wdt == "kinetic" and _ksub:
                damage_type = _ksub
            else:
                damage_type = _wdt
            # Only override weapon_tags when the sheet weapon actually defines
            # engine_tags -- otherwise keep any caller-supplied tags (no wipe).
            _etags = _weapon_result.get("engine_tags")
            if _etags is not None:
                weapon_tags = _etags or []
        # _weapon_result is None -> attacker not a PC, fall through unchanged

    # Check if target is enemy
    if target in combat["enemies"]:
        enemy = combat["enemies"][target]

        # Check if already defeated/fled
        if enemy["defeated"]:
            return f"{target} is already defeated."
        if enemy["fled"]:
            return f"{target} has fled."

        # --- Ability score damage (house rule) ---
        if ability_stat:
            stat = ability_stat.upper()
            valid_stats = ("STR", "DEX", "CON", "INT", "PSY", "EGO")
            if stat not in valid_stats:
                return f"Invalid ability_stat '{ability_stat}'. Use: {', '.join(valid_stats)}"
            abilities = enemy.setdefault("abilities", {s: enemy.get("lvl", 1) for s in valid_stats})
            old_val = abilities.get(stat, enemy.get("lvl", 1))
            new_val = old_val - amount
            abilities[stat] = new_val
            combat["log"].append(f"{target} {stat} ability damage: {old_val} → {new_val}")
            output.append(f"**{target}** {stat}: {old_val} → {new_val} (took {amount} ability damage)")
            output.append(f"  House rule: {stat} saves now at **{new_val:+d} penalty** (or Disadvantage — referee's choice)")
            if new_val <= 0:
                output.append(f"  **{stat} at 0 or below** — creature is incapacitated by {stat} loss")
            _save_game_state()
            # Enemy ability loss is relayed QUALITATIVELY only (exact scores are
            # DM-only) -- "weakened (STR)", never the number.
            return _mt.append_ticker("\n".join(output),
                                     [{"kind": "enemy_ability", "name": target, "stat": stat}])

        # --- Normal HP damage (with creature resistance/weakness) ---
        eff_amount, resist_note = _apply_creature_resistance(
            {"type": enemy.get("resist_type", "Biological"), "resistances": enemy.get("resistances"),
             "incorporeal": enemy.get("incorporeal")},
            damage_type, amount, weapon_tags=weapon_tags,
        )
        enemy["hp"] = max(0, enemy["hp"] - eff_amount)
        if resist_note:
            output.append(f"  ({enemy.get('resist_type','?')}: {resist_note})")
        combat["log"].append(f"{target} takes {eff_amount} {damage_type} damage: {enemy['hp']}/{enemy['max_hp']} HP")
        output.append(f"{target}: {enemy['hp']}/{enemy['max_hp']} HP (took {eff_amount} damage)")
        _events.append({"kind": "enemy_damage", "name": target,
                        "pct": (enemy['hp'] / enemy['max_hp']) if enemy.get('max_hp') else 0})

        # Check defeat
        if enemy["hp"] <= 0 and not enemy["defeated"]:
            enemy["defeated"] = True
            combat["log"].append(f"{target} defeated!")
            output.append(f"{target} defeated!")
            # If all enemies are now defeated or fled, combat is effectively over.
            _all_down = all(e["defeated"] or e["fled"] for e in combat["enemies"].values())
            if _all_down:
                output.append(_pf.next_block(
                    _pf.push_call("combat", action="end"),
                    label="end combat",
                ))

        # Check morale triggers
        morale_result = _check_morale_triggers()
        if morale_result:
            output.append("")
            output.append(morale_result)
    
    # Target is a PC: delegate to the authoritative damage path, which handles
    # nested HP, vulnerability doubling (e.g. a fire weakness), the full
    # wound tables, ability/max-HP loss, unconsciousness, death's door, and saving.
    elif target in combat["party_snapshot"]:
        damage_result = _character_take_damage(target, amount, damage_type)
        combat["log"].append(f"{target} takes {amount} {damage_type} damage")
        output.append(damage_result)
    
    else:
        # D5: a vehicle target (type:"vehicle" sheet) takes Hull-Points damage
        # (CH p.73), delegated to the dedicated helper - mirrors the PC path.
        _vdata, _verr = _load_characters()
        if not _verr and _vdata:
            _vkey, _vsheet = _find_character(_vdata, target)
            if _vsheet and _vsheet.get("type") == "vehicle":
                veh_line = _vehicle_take_damage(target, amount, weapon_tags)
                combat["log"].append(f"{target} (vehicle) takes {amount} raw damage")
                output.append(veh_line)
                round_msg = None if skip_round_advance else _check_round_advance()
                if round_msg:
                    output.append("")
                    output.append(round_msg)
                _save_game_state()
                return "\n".join(output)
        return f"Target '{target}' not found in combat. Available: {', '.join(list(combat['enemies'].keys()) + list(combat['party_snapshot'].keys()))}"

    # Check round advance (skipped for non-action damage, e.g. C1 retaliation)
    round_msg = None if skip_round_advance else _check_round_advance()
    if round_msg:
        output.append("")
        output.append(round_msg)
    
    _save_game_state()
    
    return _mt.append_ticker("\n".join(output), _events)

def _combat_morale(force_morale: bool) -> str:
    """Run an enemy morale check.

    When force_morale is True this performs a discretionary check immediately,
    bypassing the auto-trigger gate (the 50%-defeated / leader-killed conditions
    and the once-per-round `morale_checked` short-circuit) used by
    _check_morale_triggers. Otherwise it defers to the standard trigger logic.

    Mechanics (same as the auto path): roll d20 + the surviving enemies' morale
    bonus vs DC 16. Success = enemies hold; failure = morale broken and all
    remaining undefeated enemies flee. Returns a result message.
    """
    combat = GAME_STATE.get("active_combat")
    if not combat:
        return "No active combat. Use action='init' to start combat."

    if not force_morale:
        # Defer to the normal gated trigger logic.
        result = _check_morale_triggers()
        if result:
            _save_game_state()
            return result
        return "No morale trigger met. Pass force_morale=True for a discretionary check."

    enemies = combat["enemies"]
    total = len(enemies)
    defeated = sum(1 for e in enemies.values() if e["defeated"] or e["fled"])
    alive = total - defeated

    if alive == 0:
        return "No enemies left to check morale."

    # Mark checked this round (consistent with the auto path).
    combat["morale_checked"] = True

    # Morale bonus from first surviving enemy (assume same type).
    morale_bonus = 0
    for enemy in enemies.values():
        if not enemy["defeated"] and not enemy["fled"]:
            morale_bonus = enemy["morale"]
            break

    roll = random.randint(1, 20)
    total_roll = roll + morale_bonus
    success = total_roll >= 16

    output = ["Morale check (forced)"]
    output.append(f"Roll: d20+{morale_bonus} = {roll}+{morale_bonus} = {total_roll} vs DC 16")

    if success:
        output.append("SUCCESS - Enemies hold firm!")
        combat["log"].append(f"Morale check (forced): SUCCESS ({total_roll} vs 16)")
    else:
        output.append("FAILED - Morale broken!")
        combat["morale_broken"] = True
        fled_names = []
        for name, data in enemies.items():
            if not data["defeated"] and not data["fled"]:
                data["fled"] = True
                fled_names.append(name)
        if fled_names:
            output.append(f"Fleeing: {', '.join(fled_names)}")
        # A forced rout clears the field the same as an auto-trigger break —
        # if no active combatants remain, combat is over.
        _all_down = all(e["defeated"] or e["fled"] for e in enemies.values())
        if _all_down:
            output.append(_pf.next_block(
                _pf.push_call("combat", action="end"),
                label="end combat",
            ))
        combat["log"].append(f"Morale check (forced): FAILED ({total_roll} vs 16) - enemies flee")

    _save_game_state()
    return "\n".join(output)

def _combat_state() -> str:
    """Return current combat status."""

    combat = GAME_STATE.get("active_combat")
    if not combat:
        return "No active combat. Use action='init' to start combat."

    output = ["=" * 60]
    output.append(f"COMBAT: {combat['encounter_name']}")
    output.append("=" * 60)
    output.append("")

    # Round and initiative
    turn_status = []
    if combat["pcs_acted"]:
        turn_status.append("PCs acted")
    else:
        turn_status.append("PCs haven't acted yet")

    if combat["enemies_acted"]:
        turn_status.append("enemies acted")
    else:
        turn_status.append("enemies haven't acted yet")

    output.append(
        f"Round {combat['round']} - "
        f"{'PCs' if combat['initiative'] == 'pcs' else 'Enemies'} act first "
        f"({', '.join(turn_status)})"
    )
    output.append("")

    # Enemies
    output.append("ENEMIES:")
    alive_count = 0
    for name, data in combat["enemies"].items():
        if data["defeated"]:
            output.append(f"  - {name}: DEFEATED")
        elif data["fled"]:
            output.append(f"  - {name}: FLED")
        else:
            alive_count += 1
            hp_pct = data["hp"] / data["max_hp"]
            wounded = " [WOUNDED]" if hp_pct < 0.5 else ""
            output.append(
                f"  - {name}: {data['hp']}/{data['max_hp']} HP, "
                f"AV {data['av']}, Morale +{data['morale']}{wounded}"
            )
    output.append(f"  Total: {alive_count} alive, {len(combat['enemies']) - alive_count} defeated/fled")
    output.append("")

    # Party
    output.append("PARTY:")
    chars_data, _ = _load_characters()
    for name, snapshot in combat["party_snapshot"].items():
        char = chars_data["characters"].get(name)
        if not char:
            continue

        # Handle both dict and int HP formats
        hp_value = char.get("hp", 0)
        if isinstance(hp_value, dict):
            current_hp = hp_value.get("current", 0)
            max_hp = hp_value.get("max", 0)
        else:
            current_hp = hp_value
            max_hp = char.get("max_hp", 0)

        damage_taken = snapshot["hp"] - current_hp

        damage_str = ""
        if damage_taken > 0:
            damage_str = f" (took {damage_taken} damage)"
        elif damage_taken < 0:
            damage_str = f" (healed {abs(damage_taken)} HP)"

        output.append(f"  - {name}: {current_hp}/{max_hp} HP{damage_str}")
    output.append("")

    # Warnings
    if combat.get("morale_broken"):
        output.append("WARNING: MORALE BROKEN - Enemies fleeing/surrendering")
        output.append("")

    # Recent log
    output.append("RECENT LOG:")
    for entry in combat["log"][-5:]:
        output.append(f"  {entry}")

    output.append("=" * 60)

    return "\n".join(output)

def _combat_end() -> str:
    """End combat, archive log, clear state."""

    combat = GAME_STATE.get("active_combat")
    if not combat:
        return "No active combat to end."

    # Calculate summary stats
    enemies = combat["enemies"]
    total_enemies = len(enemies)
    defeated = sum(1 for e in enemies.values() if e["defeated"])
    fled = sum(1 for e in enemies.values() if e["fled"])

    # Calculate party damage
    chars_data, _ = _load_characters()
    party_damage = []
    for name, snapshot in combat["party_snapshot"].items():
        char = chars_data["characters"].get(name)
        if not char:
            continue
        # Handle dict HP format
        hp_value = char.get("hp", 0)
        if isinstance(hp_value, dict):
            current_hp = hp_value.get("current", 0)
        else:
            current_hp = hp_value
        damage_taken = snapshot["hp"] - current_hp
        if damage_taken > 0:
            party_damage.append(f"{name} -{damage_taken} HP")

    # XP calculation (1 per defeated enemy)
    xp = defeated

    # Archive combat log (optional - save to file)
    log_dir = CAMPAIGN_DIR / "combat_logs"
    log_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"{combat['encounter_name']}_{timestamp}.md"

    with open(log_file, 'w', encoding='utf-8') as f:
        f.write(f"# Combat Log: {combat['encounter_name']}\n\n")
        f.write(f"**Started:** {combat['started_at']}\n")
        f.write(f"**Ended:** {datetime.now().isoformat()}\n")
        f.write(f"**Duration:** {combat['round']} rounds\n\n")
        f.write("## Log\n\n")
        for entry in combat["log"]:
            f.write(f"- {entry}\n")

    # --- Usage Die: roll each fired ranged weapon once (book: once after combat) ---
    usage_lines = []
    _seen = set()
    for _entry in combat.get("weapons_fired", []):
        _ckey = _entry.get("character")
        _wname = _entry.get("weapon")
        _sig = f"{_ckey} {_wname}"
        if _sig in _seen:
            continue
        _seen.add(_sig)
        _handle = _usage_resolve(_ckey, _wname)
        if not _handle:
            continue
        if isinstance(_handle, str):
            usage_lines.append(f"({_wname}: {_handle})")   # surface why ammo didn't roll
            continue
        _line = _usage_deplete_roll(_handle)
        if _line:
            usage_lines.append(_line)

    # E1: combat-window twinning death-pending marks cannot pair once the
    # fight ends (R-E1h) - pop them so the pending line stops rendering.
    # Fresh load: the usage-die block above saves stepped ammo to disk, so
    # the chars_data loaded earlier is stale - saving it back would clobber.
    pending_cleared = []
    try:
        p_data, p_err = _load_characters()
        if not p_err and p_data:
            for p_key, p_char in p_data.get("characters", {}).items():
                p_pend = p_char.get("twinning_pending")
                if (isinstance(p_pend, dict)
                        and str(p_pend.get("window", "")).startswith("combat:")):
                    p_char.pop("twinning_pending", None)
                    _save_single_character(p_key, p_char, p_data)
                    pending_cleared.append(
                        f"{p_char.get('name', p_key)} ({p_pend.get('window')})")
    except Exception as e:
        logging.warning(f"Twinning pending combat-end cleanup failed: {e}")

    # Clear combat state
    GAME_STATE["active_combat"] = None
    _save_game_state()

    # Format output
    output = [f"Combat ended: {combat['encounter_name']}"]
    output.append(f"- Duration: {combat['round']} rounds")
    output.append(f"- Enemies: {defeated} defeated, {fled} fled")
    if party_damage:
        output.append(f"- Party damage: {', '.join(party_damage)}")
    else:
        output.append(f"- Party damage: None")
    output.append(f"- XP earned: {xp} (trade Exotica for XP)")
    if usage_lines:
        output.append("- Ammo: " + "; ".join(usage_lines))
    if pending_cleared:
        output.append("- Twinning: death-pending mark expired for "
                      + ", ".join(pending_cleared)
                      + " - the combat window passed")
    output.append("")
    output.append(f"Combat log archived to: {log_file.relative_to(CAMPAIGN_DIR)}")

    return "\n".join(output)

def _combat_log(message: str, side: str = None) -> str:
    """Add custom message to combat log, optionally mark side as acted."""

    combat = GAME_STATE.get("active_combat")
    if not combat:
        return "No active combat. Use action='init' to start combat."

    if not message:
        return "Action 'log' requires 'message' parameter."

    # Add to log
    combat["log"].append(message)

    output = [f"Logged: {message}"]

    # Mark side as acted if provided
    if side:
        if side not in ["pcs", "enemies"]:
            output.append(f"Warning: Invalid side '{side}'. Use 'pcs' or 'enemies'.")
        else:
            if side == "pcs":
                combat["pcs_acted"] = True
                output.append("PCs marked as acted.")
            else:
                combat["enemies_acted"] = True
                output.append("Enemies marked as acted.")

            # Check round advance
            round_msg = _check_round_advance()
            if round_msg:
                output.append("")
                output.append(round_msg)

    _save_game_state()

    return "\n".join(output)








# ============================================
# STARTUP VALIDATION
# ============================================

def _startup_validation():
    """
    Run validation at server startup. Logs warnings but doesn't block startup.
    Called when server initializes — issues are logged to startup_log.txt.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        # Import validation function result directly (it's a tool but returns string)
        issues = []
        warnings = []

        # Quick validation of critical files
        status_path = CAMPAIGN_DIR / "CURRENT_STATUS.md"
        if not status_path.exists():
            issues.append("CRITICAL: CURRENT_STATUS.md not found")
        else:
            content = status_path.read_text(encoding='utf-8')

            # Check required fields
            required = [
                (r'\*\*Location:\*\*', '**Location:**'),
                (r'\*\*Present:\*\*', '**Present:**'),
                (r'\*\*Last 3 Beats:\*\*', '**Last 3 Beats:**'),
            ]
            for pattern, name in required:
                if not re.search(pattern, content):
                    issues.append(f"MISSING: {name} in CURRENT_STATUS.md")

        # Check JSON files parse correctly
        for fname in ['characters.json', 'party.json', 'lorebook.json']:
            fpath = CAMPAIGN_DIR / fname
            if fpath.exists():
                try:
                    with open(fpath, 'r', encoding='utf-8') as f:
                        json.load(f)
                except json.JSONDecodeError as e:
                    issues.append(f"JSON PARSE ERROR: {fname} - {e}")
            else:
                warnings.append(f"File not found: {fname}")

        # Check ChromaDB / Ollama availability
        try:
            import chromadb
            # Loud version-mismatch warning: ChromaDB's on-disk format differs
            # across minor versions, so an unpinned install can silently corrupt
            # the store. Silent on the pinned version; a WARNING (never fatal).
            installed_ver = getattr(chromadb, "__version__", None)
            if installed_ver and installed_ver != _CHROMA_EXPECTED_VERSION:
                warnings.append(
                    f"ChromaDB version mismatch: installed {installed_ver}, "
                    f"expected {_CHROMA_EXPECTED_VERSION}. The on-disk store format "
                    f"can differ across versions and may corrupt silently. "
                    f"Reinstall the pin: pip install chromadb=={_CHROMA_EXPECTED_VERSION}"
                )
            chroma_path = CAMPAIGN_DIR / "chroma-db"
            if not chroma_path.exists():
                warnings.append("ChromaDB directory not found - semantic search unavailable")
            else:
                # Check for stale index (MASTER_CONTINUITY newer than chroma-db)
                master_continuity = CAMPAIGN_DIR / "MASTER_CONTINUITY_CURRENT.md"
                if master_continuity.exists():
                    mc_mtime = master_continuity.stat().st_mtime
                    # Check newest file in chroma-db
                    chroma_files = list(chroma_path.rglob("*"))
                    if chroma_files:
                        chroma_mtime = max(f.stat().st_mtime for f in chroma_files if f.is_file())
                        if mc_mtime > chroma_mtime:
                            warnings.append("ChromaDB may be stale - MASTER_CONTINUITY.md modified after last index. Run reindex_recent() (or reindex at session-end Phase 9).")
        except ImportError:
            warnings.append("ChromaDB not installed - semantic search unavailable")

        # Log results
        with open(STARTUP_LOG, 'a', encoding='utf-8') as f:
            f.write(f"\n[{timestamp}] STARTUP VALIDATION\n")
            if issues:
                f.write(f"  ISSUES ({len(issues)}):\n")
                for issue in issues:
                    f.write(f"    - {issue}\n")
            if warnings:
                f.write(f"  WARNINGS ({len(warnings)}):\n")
                for warning in warnings:
                    f.write(f"    - {warning}\n")
            if not issues and not warnings:
                f.write("  All checks passed.\n")

        # Print to stderr for visibility (won't interfere with MCP protocol)
        if issues:
            import sys
            print(f"[STARTUP] {len(issues)} validation issues - check startup_log.txt", file=sys.stderr)

    except Exception as e:
        # Don't let validation errors prevent server startup
        with open(STARTUP_LOG, 'a', encoding='utf-8') as f:
            f.write(f"\n[{timestamp}] STARTUP VALIDATION FAILED: {e}\n")


# Run startup validation when module loads
_startup_validation()

# Initialize canon_distillations collection at startup so it exists on first boot
try:
    get_canon_distillations_collection()
    logging.info("canon_distillations collection ready")
except Exception as e:
    logging.warning(f"Failed to initialize canon_distillations collection: {e}")

# ============================================
# TRAVEL LOOP WIRING — connect GeographySystem callbacks to the real
# subsystems (supply rations, advance_day, weather walk). Wired here, after
# all referenced functions are defined; the lambdas only fire during a journey.
# ============================================
def _current_weather_name() -> str:
    """Read the current weather NAME from weather_state.json (the content-forge
    hex-walk stores {"position", "weather"}). Returns "Still" if absent/unknown
    so the travel speed table degrades gracefully."""
    try:
        import json
        state = json.loads((CAMPAIGN_DIR / "weather_state.json").read_text(encoding="utf-8"))
        name = state.get("weather")
        if isinstance(name, str) and name:
            return name
    except Exception:
        pass
    return "Still"


def _wire_travel_callbacks():
    """Bind the GeographySystem callback hooks to supply/advance_day/weather."""
    _supply = getattr(supply, "fn", supply)
    _advance_day = getattr(advance_day, "fn", advance_day)

    def _on_depart(food=None, water=None, follower_mouths=None):
        return _supply(action="depart", food=food, water=water,
                       follower_mouths=follower_mouths)

    geography_system.on_depart = _on_depart
    # on_arrive is intentionally NOT wired: whether an arrival is a supplied
    # base is DM judgment — travel_arrive pushes the supply(action="arrive")
    # call instead of auto-flipping to abundant (D134 salt-bore fix).
    geography_system.on_arrive = None

    def _day_tick(double_water=False):
        # double_water is accepted but NOT auto-applied this build: the Heatwave
        # 2x water draw is surfaced as a push line in travel_day; auto-applying it
        # to the supply tick is a deferred refinement.
        day = get_current_day_safe()
        next_day = (day + 1) if isinstance(day, int) else 1
        return _advance_day(next_day, "travel day")

    geography_system.on_day_tick = _day_tick
    geography_system.on_weather = _current_weather_name
    # on_forced_march is intentionally NOT wired: Exhaustion is surfaced as a push
    # line in travel_day and stays DM-adjudicated; auto-tracking the Exhaustion
    # inventory item on live sheets is a deferred refinement.


_wire_travel_callbacks()

# Wave 8: register the relocated session/persistence tools (deps injected from this module).
session_tools.register_session_tools(mcp, sys.modules[__name__])

# Slice 6: bind the live server module + inject the data tables into the
# relocated character-management helpers.
character_tools.register_character_tools(sys.modules[__name__])

# Slice 4: bind the live server module + inject rulebook_system into the
# relocated bestiary/encounter helpers.
bestiary_encounter.register_bestiary_encounter(sys.modules[__name__])

# Slice 3: bind the live server module into the relocated cyber/gift helpers.
cyber_gifts.register_cyber_gifts(sys.modules[__name__])

# Slice 2: inject the shared, never-patched substance deps (defined above) into
# the relocated substance helpers.
substances.register_substances(sys.modules[__name__])

# Slice 1: inject the shared data tables + _stamp_slots_uses into the relocated
# generator functions (defined above, shared with poison/elixir/combat systems).
generators.register_generators(sys.modules[__name__])

if __name__ == "__main__":
    # Fail loud if the player hasn't told the engine where their save data lives.
    # RUBICON_CAMPAIGN_DIR must be set (normally in the .mcp.json "env" block). We
    # refuse to boot on a silent guessed folder so saves can never land in the
    # wrong place and so a fresh install surfaces the one thing it must configure.
    # (Only checked here, at the real launch — importing server for tests/tools is
    # unaffected, and hooks keep their own graceful fallback.)
    _camp = os.environ.get("RUBICON_CAMPAIGN_DIR", "").strip()
    if not _camp:
        sys.stderr.write(
            "\n[rubicon-seven] STARTUP ERROR: RUBICON_CAMPAIGN_DIR is not set.\n"
            "  The engine needs to know where your campaign save folder is.\n"
            "  Set it in your .mcp.json \"env\" block (see .mcp.json.example / README),\n"
            "  e.g.  \"RUBICON_CAMPAIGN_DIR\": \"C:\\\\path\\\\to\\\\your-campaign\"\n"
            "  (on WSL also add it to \"WSLENV\" so it crosses into Windows), then restart.\n\n"
        )
        sys.exit(1)
    mcp.run(transport='stdio')
