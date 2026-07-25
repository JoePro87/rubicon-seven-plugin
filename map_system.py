# ============================================
# RUBICON SEVEN - SPATIAL MAP SYSTEM v3
# ============================================
# 
# A referee tool for tracking exploration state,
# maintaining spatial consistency, and respecting
# secrets during dungeon/vault/city exploration.
#
# v3: Fixed renderer - south connections, wider boxes, better names
#

import json
import os
import re
import logging
from pathlib import Path
from typing import Optional, Dict, List, Any

from tool_tags import TOOL_TAGS, Safety
import site_markers as _sm  # pure leaf (json/re/pathlib); reads the SITE-marker scene token

# Status glyphs
GLYPHS = {
    'party': '◈',
    'explored': '○',
    'searched': '△',
    'noticed': '?',
    'unknown': ' ',
    'vertical_up': '↑',
    'vertical_down': '↓',
    'vertical_both': '↕',
}

VERTICAL_DIRECTIONS = ['up', 'down', 'in', 'out']

# Cardinal direction offsets
DIR_OFFSETS = {
    'n': (0, -1), 'north': (0, -1),
    's': (0, 1), 'south': (0, 1),
    'e': (1, 0), 'east': (1, 0),
    'w': (-1, 0), 'west': (-1, 0),
}

# A0 fidelity floor: every reveal_fact() call must carry a validated
# provenance stamp. This help text is the single copy of that contract —
# it's reused verbatim in every rejection message and by the reveal-gate copy.
PROVENANCE_HELP = (
    "REVEAL REJECTED — every ledger write needs provenance. Legal stamps: "
    "provenance='prep:<exact phrase from the active prep (>=8 chars)>' | "
    "'ledger:<n>' (existing entry number) | 'player' (player-originated) | "
    "'mint' (conscious new invention, stored labeled). "
    "If the fact has no source: cite it, cut it, downgrade to an in-fiction "
    "unknown, or mint it consciously. Silent invention is not a legal move."
)


class MapSystem:
    """Spatial tracking system for dungeon/vault/city exploration."""

    # Generous hard cap on a single Revealed Ledger fact. Over this, the append
    # is REFUSED loudly (never silently sliced) — see _ledger_append.
    LEDGER_FACT_MAX_CHARS = 2000

    # Map a room's `### Subsection` header (lowercased) to a reveal tier.
    # obvious = surfaced on arrival; hidden = surfaced only on a search turn;
    # dm = DM-channel note (surfaced at obvious, marked [DM]); skip = never here
    # (local statblocks surface via the encounter die). Unknown -> obvious (+log).
    _SECTION_TIER = {
        "observables": "obvious", "observable": "obvious", "description": "obvious",
        "loot": "hidden", "treasure": "hidden", "obstacles": "hidden",
        "hazards": "hidden", "hidden": "hidden",
        "dm notes": "dm", "dm note": "dm", "referee notes": "dm",
        "secret": "secret", "secrets": "secret",
        "encounters": "skip",   # local statblocks surface via the encounter die
    }

    def __init__(self, campaign_dir: Path):
        self.campaign_dir = campaign_dir
        self.maps_dir = campaign_dir / "maps"
        # parents=True so the engine can boot against a brand-new campaign folder
        # that doesn't exist yet — the MCP server starts BEFORE /vaarn-start
        # scaffolds the campaign, so this first mkdir must create the dir tree.
        self.maps_dir.mkdir(parents=True, exist_ok=True)
        # Optional callback injected by server.py to SET the Active Map pointer
        # whenever a site is entered/resumed. Layering: map_system never imports
        # server; server wires the real setter onto this attribute after init.
        self.on_active_site = None
        # Optional callback injected by server.py to READ the current campaign day
        # (int) so enter_site can stamp created_day/last_seen_day. Same layering
        # rule: server wires it after init. Returns an int day or None.
        self.get_day = None
        # Optional callback injected by server.py to refresh the spoiler-safe
        # player view after any map action. Same layering rule: server wires it
        # after init. Takes the active map_name (may be None).
        self.on_state_change = None
        # Optional callback injected by server.py (Task 3) to READ the active
        # prep file's full text, so reveal_fact can verify 'prep:<phrase>'
        # provenance stamps against it. Same layering rule: server wires it
        # after init. Returns the prep text (str) or "" if none is active.
        self.get_prep_text = None

    # ========================================
    # STATE MANAGEMENT
    # ========================================
    
    def get_map_state(self, map_name: str) -> Optional[Dict]:
        """Load map state from JSON file."""
        state_path = self.maps_dir / f"{map_name}_map.json"
        if not state_path.exists():
            return None
        with open(state_path, 'r', encoding='utf-8') as f:
            state = json.load(f)
        # B3: guarantee the map_name field for the advance_turns turn_hook
        # (older saves predate the init-time stamp).
        state.setdefault("map_name", map_name)
        # Backward-compat defaults for site-exploration fields (older saves
        # predate the two-clock + kind/discovery substrate).
        state.setdefault("kind", "vault" if state.get("rooms") else "site")
        state.setdefault("created_day", None)
        state.setdefault("last_seen_day", None)
        state.setdefault("discovery", {})
        return state

    def save_map_state(self, map_name: str, state: Dict) -> None:
        """Save map state atomically (tmp file + os.replace), retrying the
        rename on transient Windows file locks (WinError 5 / PermissionError),
        mirroring server._atomic_json_write — this persists live play-state on
        an NTFS/WSL mount that intermittently locks the destination."""
        import time
        state_path = self.maps_dir / f"{map_name}_map.json"
        tmp_path = state_path.with_suffix(".json.tmp")
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2)
        for attempt in range(5):
            try:
                os.replace(tmp_path, state_path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))

    def _ledger_append(self, state, fact, source_room, source_action, provenance: str = ""):
        """Append a party-known fact to the site's Revealed Ledger.
        Whitelist-by-construction: callers may only pass text the party has
        legitimately learned (reveal paths) or neutral markers (entered/searched).

        Facts are stored INTACT — never sliced. (Until 2026-07-24 this silently
        truncated to 300 chars mid-word, damaging 31 Thyricost entries.) A fact
        over LEDGER_FACT_MAX_CHARS is REFUSED loudly instead of being trimmed.
        Returns "" on success, or an error string the caller must surface."""
        fact = (fact or "").strip()
        if not fact:
            return ""
        if len(fact) > self.LEDGER_FACT_MAX_CHARS:
            return (f"❌ REFUSED — fact is {len(fact)} chars, over the "
                    f"{self.LEDGER_FACT_MAX_CHARS}-char ledger cap. Nothing was "
                    f"stored. Split it into two reveals rather than losing text.")
        stored = fact
        ledger = state.setdefault("revealed_ledger", [])
        # Dedup: skip a fact byte-identical (post-strip) to any of the last 10
        # entries — repeated enter/search marks and re-reveals no longer pile up.
        for e in ledger[-10:]:
            if (e.get("fact") or "") == stored:
                return ""
        day = None
        try:
            if callable(getattr(self, "get_day", None)):
                day = self.get_day()
        except Exception:
            day = None
        entry = {
            "fact": stored, "day": day,
            "source_room": source_room or "", "source_action": source_action,
        }
        if provenance:
            entry["provenance"] = provenance[:120]
        ledger.append(entry)
        return ""

    def _new_ledger_only_state(self, map_name: str) -> Dict:
        """A minimal, room-less state whose only live field is the Revealed
        Ledger. This is the reveal home for a NON-vault (social/settlement)
        scene: an Active Prep with no map, so a legitimately-learned DM-only
        fact still has somewhere to be ledgered (and stop tripping the name
        gate)."""
        return {
            "map_name": map_name, "map_type": "site", "kind": "ledger",
            "prep_file": None, "rooms": {}, "revealed_ledger": [],
            "current_turn": 0, "created_day": None, "last_seen_day": None,
            "discovery": {},
        }

    def _normalize_provenance(self, provenance: str) -> str:
        """The stored label differs from the verification input for prep:
        refs — the phrase was proof-of-source, not the thing future turns
        need to see. ledger:<n> is stored verbatim (it's already a compact,
        checkable label); player/mint are lowercased."""
        p = (provenance or "").strip()
        return "prep" if p.lower().startswith("prep:") else p.lower() if p.lower() in ("player", "mint") else p

    def _validate_provenance(self, map_name: str, provenance) -> str:
        """Fail-closed gate on reveal_fact: returns "" if the stamp is legal,
        else a REJECTED message (PROVENANCE_HELP or a specific reason +
        PROVENANCE_HELP). Callers must not write to state when this is non-empty."""
        p = (provenance or "").strip()
        if not p:
            return PROVENANCE_HELP
        low = p.lower()
        if low in ("player", "mint"):
            return ""
        if low.startswith("ledger:"):
            try:
                n = int(p.split(":", 1)[1])
            except ValueError:
                return PROVENANCE_HELP
            state = self.get_map_state(map_name)
            ledger = (state or {}).get("revealed_ledger", [])
            if not (1 <= n <= len(ledger)):
                return f"REJECTED — ledger:{n} does not exist ({len(ledger)} entries). " + PROVENANCE_HELP
            return ""
        if low.startswith("prep:"):
            ref = p.split(":", 1)[1].strip().strip('"').strip("'")
            if len(ref) < 8:
                return "REJECTED — prep: reference too short to verify (need >=8 chars). " + PROVENANCE_HELP
            text = ""
            if self.get_prep_text is not None:
                try:
                    text = self.get_prep_text() or ""
                except Exception:
                    text = ""
            if not text:
                return "REJECTED — no active prep text available to verify a prep: reference. " + PROVENANCE_HELP
            if ref.casefold() not in text.casefold():
                return f"REJECTED — prep: reference not found in the active prep: '{ref[:60]}'. " + PROVENANCE_HELP
            return ""
        return PROVENANCE_HELP

    def reveal_fact(self, map_name: str, fact: str, room_id: str = None,
                    provenance: str = None) -> str:
        """Explicit lever: the party just learned a fact (dialogue, communion,
        deduction). Ledger it so NPCs may assert it and the name tripwire unblocks.
        Fail-closed on provenance: no validated stamp, no write — see PROVENANCE_HELP."""
        err = self._validate_provenance(map_name, provenance)
        if err:
            return err
        state = self.get_map_state(map_name)
        if not state:
            # Non-vault scenes (an Active Prep with no map) still need a reveal
            # home. Mint a ledger-only state ONLY when the injected callback
            # sanctions this name as the active prep's ledger — a typo'd vault
            # name (no matching prep) still hard-errors, as before.
            _ok = getattr(self, "ledger_autocreate_ok", None)
            if callable(_ok) and _ok(map_name):
                state = self._new_ledger_only_state(map_name)
            else:
                return f"❌ Map not found: {map_name}"
        if not (fact or "").strip():
            return "❌ reveal requires a non-empty fact"
        room = (room_id or state.get("party_location") or "").lower().strip()
        err = self._ledger_append(state, fact, room, "reveal",
                                  provenance=self._normalize_provenance(provenance))
        if err:
            return err
        self.save_map_state(map_name, state)
        n = len(state["revealed_ledger"])
        # Echo the STORED value, not the input — a storage discrepancy must be
        # visible in the confirmation instead of masked by it (2026-07-24).
        want = fact.strip()
        stored = next((e.get("fact") or "" for e in reversed(state["revealed_ledger"])
                       if (e.get("fact") or "") == want),
                      (state["revealed_ledger"][-1].get("fact") or ""))
        return (f"✅ Ledgered ({n} facts known at {map_name}): {stored}\n"
                f"NPCs may now assert this fact. STATE IT PLAINLY in your prose — "
                f"an earned fact is a declarative sentence, never atmosphere.")

    # ========================================
    # EXPEDITION DOCKET — per-track state
    # ========================================
    # A track is one strand of the party's open business at a site (a petition,
    # a blocked door, a favour owed). It travels with the site map-state JSON
    # (spoiler-scoped, same file as revealed_ledger). RESOLVED tracks stay in the
    # array for history but drop out of the docket. See the 2026-07-20 spec.

    TRACK_STATUSES = {"OPEN", "BLOCKED", "WAITING", "RESOLVED"}

    def _tracks(self, state: Dict) -> List:
        """The site's track array, created on first touch."""
        return state.setdefault("tracks", [])

    def _find_track(self, state: Dict, track_id: str) -> Optional[Dict]:
        tid = (track_id or "").strip()
        for t in state.get("tracks", []):
            if t.get("id") == tid:
                return t
        return None

    def _track_day(self):
        """Current campaign day via the injected callback, or None. Never raises."""
        try:
            if callable(getattr(self, "get_day", None)):
                return self.get_day()
        except Exception:
            pass
        return None

    def _resolve_track_state(self, map_name: str):
        """Load a site's state for a track op. Honours the same ledger_autocreate_ok
        scoping as reveal_fact: a prep-scoped site with no map yet can hold tracks;
        an unknown name still hard-errors. Returns (state, error_or_None)."""
        state = self.get_map_state(map_name)
        if state is None:
            _ok = getattr(self, "ledger_autocreate_ok", None)
            if callable(_ok) and _ok(map_name):
                state = self._new_ledger_only_state(map_name)
            else:
                return None, f"❌ Map not found: {map_name}"
        return state, None

    def track_add(self, map_name: str, track_id: str, title: str, stand: str = "",
                  status: str = "OPEN", blocked_by: str = "", next_step: str = "",
                  clock: str = "") -> str:
        """Declare a new open track at a site. Duplicate id -> error (use update)."""
        state, err = self._resolve_track_state(map_name)
        if err:
            return err
        track_id = (track_id or "").strip()
        if not track_id:
            return "❌ track add requires a non-empty track_id"
        title = (title or "").strip()
        if not title:
            return "❌ track add requires a non-empty title"
        if self._find_track(state, track_id):
            return (f"❌ Track '{track_id}' already exists at {map_name} — "
                    f"use track_op=\"update\" to change it.")
        st = (status or "OPEN").strip().upper()
        if st not in self.TRACK_STATUSES:
            st = "OPEN"
        self._tracks(state).append({
            "id": track_id,
            "title": title,
            "status": st,
            "stand": (stand or "").strip()[:200],
            "blocked_by": (blocked_by or "").strip(),
            "next_step": (next_step or "").strip(),
            "clock": (clock or "").strip(),
            "updated_day": self._track_day(),
        })
        self.save_map_state(map_name, state)
        return f"✅ Track added at {map_name}: [{track_id}] {title} — {st}"

    def track_update(self, map_name: str, track_id: str, title: str = None,
                     stand: str = None, status: str = None, blocked_by: str = None,
                     next_step: str = None, clock: str = None) -> str:
        """Patch ONLY the provided fields of an existing track; always re-stamp
        updated_day. A None argument means 'leave this field alone'."""
        state, err = self._resolve_track_state(map_name)
        if err:
            return err
        t = self._find_track(state, track_id)
        if not t:
            return (f"❌ Track '{(track_id or '').strip()}' not found at {map_name} — "
                    f"track_op=\"add\" to create it.")
        if title is not None:
            ts = title.strip()
            if ts:
                t["title"] = ts
        if stand is not None:
            t["stand"] = stand.strip()[:200]
        if status is not None:
            st = status.strip().upper()
            if st in self.TRACK_STATUSES:
                t["status"] = st
        if blocked_by is not None:
            t["blocked_by"] = blocked_by.strip()
        if next_step is not None:
            t["next_step"] = next_step.strip()
        if clock is not None:
            t["clock"] = clock.strip()
        t["updated_day"] = self._track_day()
        self.save_map_state(map_name, state)
        return f"✅ Track updated at {map_name}: [{t['id']}] {t['title']} — {t['status']}"

    def track_resolve(self, map_name: str, track_id: str) -> str:
        """Mark a track RESOLVED. It stays in the array (history) but leaves the
        docket. Nudges a reveal — a resolution is usually a learned fact."""
        state, err = self._resolve_track_state(map_name)
        if err:
            return err
        t = self._find_track(state, track_id)
        if not t:
            return f"❌ Track '{(track_id or '').strip()}' not found at {map_name}."
        t["status"] = "RESOLVED"
        t["updated_day"] = self._track_day()
        self.save_map_state(map_name, state)
        return (f"✅ Track resolved at {map_name}: [{t['id']}] {t['title']}.\n"
                f"Resolution usually = a learned fact: map(action=\"reveal\", "
                f"map_name=\"{map_name}\", fact=\"...\")")

    def track_list(self, map_name: str) -> str:
        """All tracks at a site (open first, then resolved), for DM review."""
        state = self.get_map_state(map_name)
        if state is None:
            _ok = getattr(self, "ledger_autocreate_ok", None)
            if callable(_ok) and _ok(map_name):
                return f"No tracks declared at {map_name}."
            return f"❌ Map not found: {map_name}"
        tracks = state.get("tracks") or []
        if not tracks:
            return f"No tracks declared at {map_name}."
        lines = [f"TRACKS ({map_name}):"]
        for t in tracks:
            extra = []
            if t.get("blocked_by"):
                extra.append(f"BY: {t['blocked_by']}")
            if t.get("next_step"):
                extra.append(f"NEXT: {t['next_step']}")
            if t.get("clock"):
                extra.append(f"CLOCK: {t['clock']}")
            tail = (" [" + " · ".join(extra) + "]") if extra else ""
            lines.append(f"  [{t.get('id')}] {t.get('title')} — "
                         f"{(t.get('status') or 'OPEN').upper()}: {t.get('stand','')}{tail}")
        return "\n".join(lines)

    def _no_tracks_push(self, state: Dict) -> str:
        """Push the track-declaration call when a prep-backed site has no tracks
        yet. Empty string otherwise (already declared, or no prep to declare from)."""
        if not state or not state.get("prep_file"):
            return ""
        if state.get("tracks"):
            return ""
        name = state.get("map_name", "")
        return (f"\nNO TRACKS DECLARED — declare this site's open tracks from prep: "
                f"map(action=\"track\", track_op=\"add\", map_name=\"{name}\", "
                f"track_id=\"...\", title=\"...\", stand=\"...\")")

    def docket_lines(self, state: Dict, current_day: int = None) -> List[str]:
        """Injection form of the docket: one numbered line per NON-resolved track,
        capped at 12 with an overflow pointer. Empty list when no open tracks.
        `!stale` flags a track untouched for >2 days (only when both days known)."""
        tracks = [t for t in (state or {}).get("tracks", [])
                  if (t.get("status") or "").upper() != "RESOLVED"]
        if not tracks:
            return []
        cap = 12
        lines = []
        for i, t in enumerate(tracks[:cap], start=1):
            line = (f"  {i}. {t.get('title','')} — {(t.get('status') or 'OPEN').upper()}: "
                    f"{t.get('stand','')}")
            if t.get("blocked_by"):
                line += f" [BY: {t['blocked_by']}]"
            if t.get("next_step"):
                line += f" [NEXT: {t['next_step']}]"
            if t.get("clock"):
                line += f" [CLOCK: {t['clock']}]"
            ud = t.get("updated_day")
            if ud is not None and current_day is not None and (current_day - ud) > 2:
                line += " !stale"
            lines.append(line)
        if len(tracks) > cap:
            name = (state or {}).get("map_name", "")
            lines.append(f'  (+{len(tracks) - cap} more — map(action="track", '
                         f'track_op="list", map_name="{name}"))')
        return lines

    def render_docket(self, map_name: str) -> str:
        """Player-facing document form: header (from optional `docket_style`, else
        a default), a day line, every open track in full (no cap), and a short
        trailing list of settled tracks. Relayed verbatim by the DM as an in-fiction
        artifact — the party's own paperwork."""
        state = self.get_map_state(map_name)
        if state is None:
            _ok = getattr(self, "ledger_autocreate_ok", None)
            if not (callable(_ok) and _ok(map_name)):
                return f"❌ Map not found: {map_name}"
            state = self._new_ledger_only_state(map_name)
        header = (state.get("docket_style") or f"EXPEDITION LEDGER — {map_name}").strip()
        day = self._track_day()
        lines = [header, f"Day {day}" if day is not None else "Day —"]
        tracks = state.get("tracks") or []
        open_tracks = [t for t in tracks if (t.get("status") or "").upper() != "RESOLVED"]
        resolved = [t for t in tracks if (t.get("status") or "").upper() == "RESOLVED"]
        if not open_tracks:
            lines.append("")
            lines.append("(No open tracks.)")
        for i, t in enumerate(open_tracks, start=1):
            lines.append("")
            lines.append(f"{i}. {t.get('title','')} — {(t.get('status') or 'OPEN').upper()}")
            if t.get("stand"):
                lines.append(f"   Stand: {t['stand']}")
            if t.get("blocked_by"):
                lines.append(f"   Blocked by: {t['blocked_by']}")
            if t.get("next_step"):
                lines.append(f"   Next: {t['next_step']}")
            if t.get("clock"):
                lines.append(f"   Clock: {t['clock']}")
        if resolved:
            lines.append("")
            for t in resolved:
                lines.append(f"— settled: {t.get('title','')}")
        return "\n".join(lines)

    def init_or_resume_map(self, map_name: str, prep_file: str,
                           map_type: str = "vault", current_day: int = None,
                           reset: bool = False) -> str:
        """Create the site state if absent, else RESUME it (do not reset).
        Tolerates prep files with zero rooms (ambient site). The two clocks
        (current_turn within-site, last_seen_day world calendar) are stamped on
        creation and preserved on resume."""
        def _arm():
            # SET the Active Map pointer (entering OR resuming re-arms it) so the
            # nag clears and the advance_day stamp has a target. Fail-soft: a
            # callback raise must never abort site creation/resume.
            if self.on_active_site:
                try:
                    self.on_active_site(map_name)
                except Exception as exc:
                    logging.warning(f"on_active_site callback failed for {map_name}: {exc}")
        # reset=True does NOT destroy state up-front; it just forces the create
        # path below. The old file is only overwritten by save_map_state AFTER a
        # valid rebuild — so an unreadable/missing prep leaves the old site intact.
        existing = None if reset else self.get_map_state(map_name)
        if existing is not None:
            # NOTE: last_seen_day is the day the party LEFT this site; it is stamped
            # on leave (advance_day), NOT on enter. Do not advance it on resume.
            # BACKFILL created_day only when truly absent (legacy sites) — never
            # clobber a real stamped value.
            if current_day is not None and existing.get("created_day") is None:
                existing["created_day"] = current_day
            # If the caller passed a DIFFERENT prep than the state was built from,
            # do NOT silently swap content — serve stored state and tell the caller
            # to reset=True to rebuild from the new prep.
            prep_differs = bool(
                prep_file and existing.get("prep_file")
                and prep_file != existing.get("prep_file")
            )
            if prep_differs:
                logging.warning(
                    f"enter_site for {map_name} passed prep_file={prep_file} but state was "
                    f"built from {existing.get('prep_file')}; serving stored state. "
                    f"Use reset=True to rebuild from the new prep."
                )
            self.save_map_state(map_name, existing)
            last = existing.get("last_seen_day")
            _arm()
            # Roomed sites have a walkable map to draw; ambient sites do not.
            _render = (f' → map(action="render", map_name="{map_name}") to redraw the map.'
                       if existing.get("rooms") else "")
            return (f"▶ RESUMING {map_name} — turn {existing.get('current_turn', 0)}"
                    f"{', last here day ' + str(last) if last is not None else ''}."
                    f"{' (note: stored prep differs — reset=True to rebuild)' if prep_differs else ''}"
                    f"{_render}{self._social_entry_push(existing)}{self._no_tracks_push(existing)}")

        prep_path = self.campaign_dir / prep_file
        if not prep_path.exists():
            return f"❌ Prep file not found: {prep_file}"
        # Read with a small retry to ride out a transient Windows file lock,
        # mirroring save_map_state's backoff (NTFS/WSL mount intermittently locks).
        import time
        content = None
        for attempt in range(5):
            try:
                content = prep_path.read_text(encoding='utf-8')
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))
        rooms = self._parse_rooms_from_prep(content)

        if rooms:
            # reset=True forces the rebuild past init_map_from_prep's
            # "already initialized" guard; the create path's save then overwrites.
            self.init_map_from_prep(map_name, prep_file, map_type, force=reset)
            state = self.get_map_state(map_name)
            state["kind"] = "vault"
        else:
            # Ambient (no-rooms) site: still thread the SITE-marker scene so a
            # roomless social keyed site also routes the die to TEXTURE, not combat.
            _amb_marker = _sm.parse_site_marker(content)
            _amb_scene = ((_amb_marker or {}).get("scene") or "vault_exploration").strip() or "vault_exploration"
            state = {
                "map_name": map_name, "map_type": "site", "kind": "site",
                "prep_file": prep_file, "scene": _amb_scene, "party_location": "ambient",
                "party_floor": 1, "floors": {}, "rooms": {},
                "exploration_log": [f"Entered ambient site {map_name}"],
                "secrets_found": [], "notes": [], "current_turn": 0,
                "noise_level": "standard", "has_light": True, "encounters_rolled": [],
            }
            # capture top-level prose (before the first '## ' section) as the
            # ambient location's content
            _lead = re.split(r'\n##\s', "\n" + content, maxsplit=1)[0].strip()
            state["_ambient_raw"] = _lead
        state["created_day"] = current_day
        state["last_seen_day"] = current_day
        state.setdefault("discovery", {})
        # Store the parsed encounter table on the state so the encounter die can
        # roll it without re-reading the prep file. Runs for both the rooms-case
        # (state is the reloaded dict from get_map_state) and the ambient-case.
        state["encounters"] = self._parse_encounters_from_prep(content)
        self.save_map_state(map_name, state)
        _arm()
        # A roomed site has a walkable map to draw; an ambient site does not.
        _render = (f' → map(action="render", map_name="{map_name}") to draw the map.'
                   if rooms else "")
        return (f"▶ SITE: {map_name} — turn 0, encounter die armed "
                f"(d6 per turn: 1=encounter from the table, 2=omen, 3-6=quiet — "
                f"the table picks WHICH encounter on a hit, not one row per roll)."
                f"{_render}{self._social_entry_push(state)}{self._no_tracks_push(state)}")

    def init_map_from_prep(self, map_name: str, prep_file: str, map_type: str = "vault",
                           force: bool = False) -> str:
        """Initialize map state from a prep file. force=True bypasses the
        'already initialized' guard so a reset can rebuild over an existing map."""
        if not force and (self.maps_dir / f"{map_name}_map.json").exists():
            return (f"↪ {map_name} already initialized (turn "
                    f"{self.get_map_state(map_name).get('current_turn', 0)}). "
                    f"Use enter_site to resume, or reset=True to rebuild.")
        prep_path = self.campaign_dir / prep_file
        if not prep_path.exists():
            return f"❌ Prep file not found: {prep_file}"
        
        content = prep_path.read_text(encoding='utf-8')
        rooms = self._parse_rooms_from_prep(content)
        
        if not rooms:
            return f"⚠️ No ## ROOM: markers found in {prep_file}"
        
        # Determine floors
        floors = {}
        for room_id, room_data in rooms.items():
            floor = room_data.get('floor', 1)
            if floor not in floors:
                floors[floor] = {'name': f"Floor {floor}", 'rooms': []}
            floors[floor]['rooms'].append(room_id)
        
        # Find entrance
        entrance = None
        for room_id, room_data in rooms.items():
            if room_data.get('is_entrance', False):
                entrance = room_id
                break
        if not entrance:
            entrance = list(rooms.keys())[0]
        
        # Scene token from the SITE marker (default vault_exploration). A
        # "social_site" scene keeps position tracking but routes the encounter die
        # to the social TEXTURE table instead of the combat trail (see
        # _auto_encounter_check). Legacy states without a marker are unchanged.
        _marker = _sm.parse_site_marker(content)
        scene = ((_marker or {}).get("scene") or "vault_exploration").strip() or "vault_exploration"

        state = {
            "map_name": map_name,
            "map_type": map_type,
            "prep_file": prep_file,
            "scene": scene,
            "party_location": entrance,
            "party_floor": rooms[entrance].get('floor', 1),
            "floors": floors,
            "rooms": rooms,
            "exploration_log": [],
            "secrets_found": [],
            "notes": [],
            "current_turn": 0,
            "noise_level": "standard",
            "has_light": True,
            "encounters_rolled": []
        }
        
        state["rooms"][entrance]["discovery_state"] = "explored"
        state["exploration_log"].append(f"Entered {map_name} at {entrance}")
        
        self.save_map_state(map_name, state)
        
        floor_count = len(floors)
        room_count = len(rooms)
        secret_count = sum(len(r.get('secret_connections', {})) for r in rooms.values())

        # A keyed vault with rooms but no encounter table can't roll the encounter
        # die — every "something attacks" then gets improvised from scratch instead
        # of rolled (the macOS-playtest Iron-Lily failure). Surface it loudly so the
        # DM adds a `## ENCOUNTERS` table (use map(action="scaffold") to mint one).
        enc_warn = ""
        if not self._parse_encounters_from_prep(content):
            enc_warn = (f"\n\n⚠️ NO ## ENCOUNTERS TABLE — the encounter die is INERT; "
                        f"vault exploration won't auto-roll threats. Add a `## ENCOUNTERS` "
                        f"table (a `| d6 | Encounter | Context |` block) to {prep_file}, "
                        f"or scaffold a fresh prep with map(action=\"scaffold\").")

        return f"""✅ Map initialized: {map_name}

**Type:** {map_type}
**Floors:** {floor_count}
**Rooms:** {room_count}
**Secrets:** {secret_count}
**Starting Location:** {entrance}

Map state saved to maps/{map_name}_map.json{enc_warn}""" + self._no_tracks_push(state)
    
    def scaffold_prep(self, map_name: str, rooms: int = 5, prep_file: str = None,
                      encounter_die: int = 6) -> str:
        """Write a keyed-vault prep SKELETON in the exact schema map(init) parses:
        N connected `## ROOM:` blocks + a `## ENCOUNTERS` table stub. The engine
        owns the FORMAT (single source — it can't drift from the parser); the DM
        fills the room souls and the encounter rows (which creatures appear is DM
        judgment), then map(action="init") it. Creates only — never overwrites."""
        rooms = max(2, min(int(rooms), 12))
        die = int(encounter_die) if int(encounter_die) in (4, 6, 8, 10, 12, 20) else 6
        prep_file = prep_file or f"prep/{map_name.upper()}_PREP.md"
        prep_path = self.campaign_dir / prep_file
        if prep_path.exists():
            return (f"↪ {prep_file} already exists — not overwriting. Edit it, or pass a "
                    f"different prep_file. Then map(action=\"init\", map_name=\"{map_name}\", "
                    f"prep_file=\"{prep_file}\").")

        title = map_name.replace('_', ' ').title()
        lines = [f"# {title} — Vault Prep", "",
                 "<!-- DM: fill each room's soul (the prose under its block) and the",
                 "     ENCOUNTERS rows (pick creatures from the bestiary that fit this",
                 "     place). Keep the ## ROOM: / **Field:** / ## ENCOUNTERS structure",
                 "     intact — map(init) parses it. Connections use 'dir→room_id'. -->", ""]
        for i in range(1, rooms + 1):
            rid = f"room_{i}"
            conns = []
            if i > 1:
                conns.append(f"w→room_{i-1}")
            if i < rooms:
                conns.append(f"e→room_{i+1}")
            lines += [
                f"## ROOM: {rid}",
                f"**Name:** {title} — Room {i}",
                "**Floor:** 1",
                f"**Coords:** [{4 + i}, 5]",
            ]
            if i == 1:
                lines.append("**Entrance:** true")
            lines += [
                f"**Connections:** {', '.join(conns) if conns else '(none yet)'}",
                "**Hazards:** ",
                "**NPCs:** ",
                "**Loot:** ",
                "",
                "(DM: describe this room — what it is, what's broken, what it was for.)",
                "",
            ]
        lines += [f"## ENCOUNTERS",
                  f"| d{die} | Encounter | Context |",
                  "|----|-----------|---------|"]
        for r in range(1, die + 1):
            lines.append(f"| {r} | (creature/event) | (where, doing what) |")
        lines += ["",
                  "<!-- DM: each row is what the encounter die surfaces on that result.",
                  "     Empty/placeholder rows still parse; fill them for live play. -->", ""]

        prep_path.parent.mkdir(parents=True, exist_ok=True)
        prep_path.write_text("\n".join(lines), encoding="utf-8")
        return (f"✅ Scaffolded keyed-vault prep: {prep_file} "
                f"({rooms} rooms, d{die} encounter table).\n"
                f"NEXT: fill the room souls + encounter rows, then "
                f"map(action=\"init\", map_name=\"{map_name}\", prep_file=\"{prep_file}\").")

    def _parse_encounters_from_prep(self, content: str):
        """Structured encounter parse. Accepts '## ENCOUNTERS' and
        '## ENCOUNTER TABLE: <name>'. Returns {type, turn_triggers, table_entries,
        dice_size, raw} or None. Mirrors server._load_prep_file's parse so the
        encounter die can be rolled from stored state without re-reading the file."""
        m = re.search(r'^##\s*ENCOUNTERS?(?:\s+TABLE)?[^\n]*\n(.*?)(?=^##\s|\Z)',
                      content, re.MULTILINE | re.DOTALL)
        if not m:
            return None
        body = m.group(1)
        enc = {"type": None, "turn_triggers": [], "table_entries": [], "raw": body}
        if re.search(r'- \*\*Turn \d+:', body):
            enc["type"] = "turn_based"
            for mt in re.finditer(r'- \*\*Turn (\d+):\*\* (.+?)(?=\n- \*\*Turn|\n\n|\Z)',
                                  body, re.DOTALL):
                enc["turn_triggers"].append({"turn": int(mt.group(1)),
                                             "description": mt.group(2).strip()})
        elif re.search(r'\|\s*d?\d+\s*\|', body):
            enc["type"] = "random_table"
            hdr = re.search(r'\|\s*d(\d+)\s*\|', body)
            if hdr:
                enc["dice_size"] = int(hdr.group(1))
            for line in body.splitlines():
                line = line.strip()
                if not line.startswith("|"):
                    continue
                cells = [c.strip() for c in line.strip("|").split("|")]
                if not cells:
                    continue
                roll_str = cells[0].strip()
                if not re.fullmatch(r'\d+', roll_str):   # skips separator (---), header (d6), 'd8' etc.
                    continue
                enc_txt = cells[1].strip() if len(cells) > 1 else ""
                if enc_txt.lower() in ('encounter', 'description', 'context'):
                    continue
                ctx = cells[2].strip() if len(cells) > 2 else ""
                enc["table_entries"].append({"roll": int(roll_str), "encounter": enc_txt, "context": ctx})
            if not enc.get("dice_size") and enc["table_entries"]:
                enc["dice_size"] = max(e["roll"] for e in enc["table_entries"])
            if not enc["table_entries"]:
                logging.warning("Encounter table header found but 0 entries parsed.")
                return None
        else:
            return None
        return enc

    def _parse_rooms_from_prep(self, content: str) -> Dict[str, Dict]:
        """Parse room definitions from prep file content."""
        rooms = {}
        
        room_pattern = r'#{2,3}\s*ROOM:\s*(\w+)\s*\n(.*?)(?=#{2,3}\s*ROOM:|\n##\s+[A-Z]|\Z)'
        matches = re.findall(room_pattern, content, re.DOTALL | re.IGNORECASE)
        
        for room_id, block in matches:
            room_id = room_id.lower().strip()
            room = {
                'id': room_id,
                'floor': 1,
                'coords': [5, 5],
                'name': room_id.replace('_', ' ').title(),
                'connections': {},
                'secret_connections': {},
                'discovery_state': 'unknown',
                'search_state': 'unsearched',
                'is_secret': False,
                'is_entrance': False,
                'hazards': [],
                'npcs': [],
                'loot': [],
                'notes': [],
                'prep_content': block.strip()
            }
            
            lines = block.strip().split('\n')
            for line in lines:
                line = line.strip()
                line_lower = line.lower()
                
                if line_lower.startswith('**floor:**'):
                    try:
                        room['floor'] = int(re.search(r'\d+', line).group())
                    except:
                        pass
                
                elif line_lower.startswith('**coords:**'):
                    try:
                        coords = re.findall(r'\d+', line)
                        if len(coords) >= 2:
                            room['coords'] = [int(coords[0]), int(coords[1])]
                    except:
                        pass
                
                elif line_lower.startswith('**name:**'):
                    room['name'] = line.split(':', 1)[1].strip().strip('*').strip()
                
                elif line_lower.startswith('**connections:**'):
                    conn_str = line.split(':', 1)[1].strip().lstrip('*').strip()
                    room['connections'] = self._parse_connections(conn_str)
                
                elif line_lower.startswith('**secrets:**'):
                    secret_str = line.split(':', 1)[1].strip().lstrip('*').strip()
                    room['secret_connections'] = self._parse_secrets(secret_str)
                
                elif line_lower.startswith('**type:**'):
                    if 'secret' in line_lower:
                        room['is_secret'] = True
                
                elif line_lower.startswith('**entrance:**'):
                    if 'true' in line_lower or 'yes' in line_lower:
                        room['is_entrance'] = True
                
                elif line_lower.startswith('**hazards:**'):
                    hazard_str = line.split(':', 1)[1].strip().lstrip('*').strip()
                    room['hazards'] = [h.strip() for h in hazard_str.split(',') if h.strip()]
                
                elif line_lower.startswith('**npcs:**'):
                    npc_str = line.split(':', 1)[1].strip().lstrip('*').strip()
                    room['npcs'] = [n.strip() for n in npc_str.split(',') if n.strip()]
                
                elif line_lower.startswith('**loot:**'):
                    loot_str = line.split(':', 1)[1].strip().lstrip('*').strip()
                    room['loot'] = [l.strip() for l in loot_str.split(',') if l.strip()]
            
            rooms[room_id] = room

        if not rooms and re.search(r'#{2,3}\s*ROOM\b', content, re.IGNORECASE):
            logging.info("Prep has ROOM-style headers the structured parser did not match "
                         "(e.g. '### ROOM 1: NAME' with prose connections); site will be treated "
                         "as ambient. Reformat to '## ROOM: <id>' + 'dir→id' connections for room nav.")
        return rooms
    
    def _parse_connections(self, conn_str: str) -> Dict[str, Any]:
        """Parse connection string like 'n→touch, e→sight, up→vestibule@2'"""
        connections = {}
        
        for conn in conn_str.split(','):
            conn = conn.strip()
            if '→' in conn or '->' in conn:
                parts = re.split(r'→|->', conn)
                if len(parts) == 2:
                    direction = parts[0].strip().lower()
                    target = parts[1].strip().lower()
                    # Strip parenthetical annotations (flavor/conditions), e.g.
                    # "deep_conduit (scout-only)" -> "deep_conduit". Mirrors _parse_secrets.
                    target = re.sub(r'\([^)]*\)', '', target).strip()

                    if '@' in target:
                        target_parts = target.split('@')
                        connections[direction] = {
                            'room': target_parts[0].strip(),
                            'floor': int(target_parts[1].strip())
                        }
                    else:
                        connections[direction] = target
        
        return connections
    
    def _parse_secrets(self, secret_str: str) -> Dict[str, Dict]:
        """Parse secrets string like 'alcove→hidden (search + INT DC 14)'"""
        secrets = {}
        
        for secret in secret_str.split(','):
            secret = secret.strip()
            if '→' in secret or '->' in secret:
                discovery = "search"
                if '(' in secret:
                    disc_match = re.search(r'\(([^)]+)\)', secret)
                    if disc_match:
                        discovery = disc_match.group(1).strip()
                    secret = re.sub(r'\([^)]+\)', '', secret).strip()
                
                parts = re.split(r'→|->', secret)
                if len(parts) == 2:
                    secret_id = parts[0].strip().lower()
                    target = parts[1].strip().lower()
                    
                    secrets[secret_id] = {
                        'target': target,
                        'discovery': discovery,
                        'found': False
                    }
        
        return secrets
    
    # ========================================
    # EXPLORATION ACTIONS
    # ========================================
    
    def _slice_subsections(self, raw):
        """Split a room's raw prep block into {header_lower: body} by `###`
        subsections. Text before the first `###` is stored under `_lead`."""
        out = {}
        parts = re.split(r'\n###\s+', "\n" + (raw or ""))
        lead = parts[0].strip()
        if lead:
            out["_lead"] = lead
        for p in parts[1:]:
            nl = p.find("\n")
            head = (p[:nl] if nl >= 0 else p).strip().lower()
            body = (p[nl+1:] if nl >= 0 else "").strip()
            if head:
                out[head] = body
        return out

    def _section_tier(self, header):
        # PREFIX-match so titled/numbered headers tier correctly:
        # '### SECRET 3 — The Vault' / '### Secret: Hidden Door' -> secret;
        # '### Hidden Cache' -> hidden. Falls back to the exact-match table.
        h = (header or "").strip().lower()
        if re.match(r'first glance\b', h):
            return "glance"
        if re.match(r'secret(s)?\b', h):
            return "secret"
        if re.match(r'(hidden|loot|treasure|obstacles?|hazards?)\b', h):
            return "hidden"
        if re.match(r'(observables?|description)\b', h):
            return "obvious"
        if re.match(r'(dm notes?|referee notes?)\b', h):
            return "dm"
        if re.match(r'encounters?\b', h):
            return "skip"
        return self._SECTION_TIER.get(h, "obvious")  # unknown -> obvious (+log)

    def _strip_secrets(self, body):
        """Remove any secret paragraph — a blank-line-delimited block whose first
        non-blank line is a secret marker (0-2 leading asterisks OR a ## / ### prefix,
        then the word 'secret'). Paragraph-aware so multi-line secret bodies are fully
        removed; tolerant of *Secret:* / **Secret:** / bare 'Secret:' / ### Secret."""
        paras = re.split(r'\n\s*\n', body or "")
        kept = []
        for para in paras:
            first = next((ln for ln in para.splitlines() if ln.strip()), "")
            if re.match(r'\s*(?:\*{0,2}|#{2,3}\s*)secret', first, re.IGNORECASE):
                continue
            kept.append(para)
        # inline scrub: a 'Secret:'/**Secret:** clause mid-line also must not leak.
        # Cut from the inline secret marker to end-of-line (keeps the prose before it).
        scrubbed = []
        for ln in "\n\n".join(p for p in kept if p.strip()).splitlines():
            ln = re.sub(r'(?i)\*{0,2}secret\b.*$', '', ln).rstrip()
            scrubbed.append(ln)
        return "\n".join(scrubbed).strip()

    def location_content(self, state, room_id, tier):
        """Return a location's content for a reveal tier. obvious=on arrival,
        hidden=on a search turn; secrets are NEVER surfaced as bodies (only a
        count hint at the hidden tier). DM-notes surface (DM-channel) at obvious.

        Reveal pacing (2026-07-16): tier 'first_glance' returns the opening
        impression only (an explicit '### First Glance' section if authored,
        else the first paragraph of each obvious body); tier 'inspection'
        returns the rest of the obvious layer (served by map(action="look")).
        Plain 'obvious' keeps its full pre-pacing behavior for other callers."""
        room = state.get("rooms", {}).get(room_id) if room_id else None
        raw = room.get("prep_content", "") if room else state.get("_ambient_raw", "")
        secs = self._slice_subsections(raw)
        glance_mode = tier in ("first_glance", "inspection")
        eff_tier = "obvious" if glance_mode else tier
        has_explicit_glance = any(
            self._section_tier(h) == "glance" for h in secs if h != "_lead")
        lines = []
        # Structured field-lines (already parsed into room['loot']/secret_connections/
        # etc.) live in the lead text; they must NOT re-surface as obvious prose on
        # enter — loot is a hidden-tier reveal (search) and secrets are reveal-gated.
        _STRUCT_FIELDS = ('floor', 'coords', 'name', 'connections', 'secrets',
                          'type', 'entrance', 'hazards', 'npcs', 'loot')
        for head, body in secs.items():
            # Secret bodies are NEVER surfaced (only the count hint below). Strip any
            # secret paragraph nested in any tier's body before it can be appended.
            body = self._strip_secrets(body)
            if head == "_lead":
                body = "\n".join(
                    ln for ln in body.splitlines()
                    if not any(ln.strip().lower().startswith(f'**{f}:**')
                               for f in _STRUCT_FIELDS)).strip()
            h = "obvious" if head == "_lead" else self._section_tier(head)
            if h == "secret":
                continue
            if h == "dm":
                if tier in ("obvious", "first_glance") and body:
                    lines.append(f"  [DM] {body}")
                continue
            if h == "skip":
                continue
            if h == "glance":
                # explicit First Glance section: IS the glance layer; also
                # rides plain 'obvious' so non-paced callers lose nothing.
                if tier in ("first_glance", "obvious") and body:
                    lines.append(body)
                continue
            if h == eff_tier and body:
                if glance_mode and h == "obvious":
                    if has_explicit_glance:
                        # authored glance -> ALL obvious text is inspection detail
                        if tier == "first_glance":
                            continue
                    else:
                        paras = re.split(r'\n\s*\n', body)
                        if tier == "first_glance":
                            body = paras[0].strip()
                        else:  # inspection = everything after the opening paragraph
                            body = "\n\n".join(p for p in paras[1:] if p.strip()).strip()
                        if not body:
                            continue
                lines.append(body if head == "_lead" else f"**{head.title()}:** {body}")
            if (h == "obvious" and head not in self._SECTION_TIER
                    and head != "_lead" and tier == "obvious"):
                logging.info(f"Unmapped room subsection '{head}' surfaced as obvious.")
        if tier == "hidden":
            # Count secret markers in any shape (### Secret, **Secret:**, *Secret:*,
            # bare 'Secret:'), but NOT the **Secrets:** plural line that already
            # defines secret_connections (the (?!s:) lookahead skips it).
            inline = len(re.findall(r'(?im)^\s*(?:\*{0,2}|#{2,3}\s*)secret\b(?!s:)', raw))
            n = inline + len((room or {}).get("secret_connections", {}) or {})
            if n:
                lines.append(f"  ⊙ {n} SECRET feature(s) here — reveal only via the "
                             f"player's fiction (never a die/search). Use reveal_secret.")
        return "\n".join(lines)

    def enter_room(self, map_name: str, room_id: str) -> str:
        """Move party to a room and update discovery state."""
        state = self.get_map_state(map_name)
        if not state:
            return f"❌ Map not found: {map_name}"
        
        room_id = room_id.lower().strip()
        
        if room_id not in state['rooms']:
            return f"❌ Room not found: {room_id}"
        
        room = state['rooms'][room_id]
        
        if room['is_secret'] and room['discovery_state'] == 'unknown':
            return f"❌ Cannot enter {room_id} - location unknown (secret not discovered)"
        
        current = state['party_location']
        if current != room_id:
            valid_move = self._is_valid_move(state, current, room_id)
            if not valid_move:
                return f"❌ No known path from {current} to {room_id}"
        
        old_location = state['party_location']
        state['party_location'] = room_id
        state['party_floor'] = room['floor']

        if room['discovery_state'] in ['unknown', 'noticed']:
            room['discovery_state'] = 'explored'
            self._ledger_append(state, f"Entered {room['name']}", room_id, "enter", provenance="map")

        state['exploration_log'].append(f"Moved: {old_location} → {room_id}")
        state.setdefault("discovery", {}).setdefault(
            room_id, {"searched": False, "secrets_revealed": [], "taken": []})
        move_turns = 1 if state.get('has_light', True) else 3
        encounter = self.advance_turns(state, move_turns)
        self.save_map_state(map_name, state)

        body = self._format_room_content(room, for_referee=True, include_prep=False)
        # Paced delivery (2026-07-16): enter serves the first-glance layer only;
        # the player asking questions is what unlocks the rest (map action=look).
        glance = self.location_content(state, room_id, "first_glance")
        if glance:
            body += "\n\n" + glance
        body += ("\n\nServe the prep's details AS WRITTEN — render ONE finding plainly; "
                 "hold the rest for the player's "
                 f"questions. Detail: map(action=\"look\", map_name=\"{map_name}\", "
                 f"room_id=\"{room_id}\", feature=\"...\")")
        if move_turns == 3:
            body += "\n\n⚠️ Moved in darkness — 3 turns consumed."
        if encounter:
            body += f"\n\n{encounter}"
        unrendered = state.get("current_turn", 0) - state.get("last_render_turn", 0)
        if unrendered >= 5:
            body += (f"\n\nSPATIAL CHECK - {unrendered} turns since the last map render. "
                     f"Ground the player: map(action=\"render\", map_name=\"{map_name}\") "
                     "and relay the map.")
        return body + self._no_tracks_push(state)

    def _is_valid_move(self, state: Dict, from_room: str, to_room: str) -> bool:
        """Check if movement between rooms is valid."""
        if from_room not in state['rooms']:
            return False
        
        room = state['rooms'][from_room]
        
        for direction, target in room['connections'].items():
            target_id = target if isinstance(target, str) else target.get('room')
            if target_id == to_room:
                return True
        
        for secret_id, secret in room['secret_connections'].items():
            if secret['found'] and secret['target'] == to_room:
                return True
        
        return False
    
    def search_room(self, map_name: str, room_id: str = None) -> str:
        """Search current or specified room for secrets."""
        state = self.get_map_state(map_name)
        if not state:
            return f"❌ Map not found: {map_name}"
        
        if room_id is None:
            room_id = state['party_location']
        
        room_id = room_id.lower().strip()
        
        if room_id not in state['rooms']:
            return f"❌ Room not found: {room_id}"
        
        room = state['rooms'][room_id]
        if not state.get('has_light', True):
            return "❌ Cannot search without light source. Darkness conceals all secrets."
        room['search_state'] = 'searched'
        encounter = self.advance_turns(state, 1)

        secrets_to_find = []
        for secret_id, secret in room['secret_connections'].items():
            if not secret['found']:
                secrets_to_find.append({
                    'id': secret_id,
                    'target': secret['target'],
                    'discovery': secret['discovery']
                })

        state['exploration_log'].append(f"Searched: {room_id}")
        state.setdefault("discovery", {}).setdefault(
            room_id, {"searched": False, "secrets_revealed": [], "taken": []})
        state["discovery"][room_id]["searched"] = True
        self._ledger_append(
            state,
            f"Searched {room['name']}" + (
                f" — found: {', '.join(str(x) for x in room['loot'])}" if room.get('loot') else ""
            ),
            room_id, "search", provenance="map")
        self.save_map_state(map_name, state)

        result = [f"**Searched: {room['name']}**", ""]

        hidden = self.location_content(state, room_id, "hidden")
        if hidden:
            result.append(hidden)
            result.append("")

        # Structured loot is hidden-tier: it surfaces on SEARCH, not on enter
        # (the enter path suppresses it via include_prep=False in _format_room_content).
        if room.get('loot'):
            result.append("**Loot:** " + ", ".join(str(x) for x in room['loot']))
            result.append("")

        if secrets_to_find:
            # The TARGET room is a DM-gated disclosure — it surfaces only via
            # reveal_secret, never on a search listing (a search reveals THAT a
            # secret is here + its in-fiction discovery hint, not where it leads).
            result.append("**SECRETS TO DISCOVER:**")
            for secret in secrets_to_find:
                result.append(f"  • {secret['id']} → [target hidden — use reveal_secret]")
                result.append(f"    Discovery: {secret['discovery']}")
            result.append("")
            result.append("*Roll for discovery. If successful, call map_reveal_secret()*")
        else:
            result.append("No hidden passages or secrets found.")

        result.append("Serve the prep's details AS WRITTEN — render ONE finding plainly; hold the rest for the player's questions.")
        if encounter:
            result.append("")
            result.append(encounter)
        return "\n".join(result)

    def look_room(self, map_name: str, room_id: str = None, feature: str = None) -> str:
        """Inspection detail for a room (the paced-delivery second layer).
        No turn cost — looking closer is free; searching (hidden tier) costs a
        turn. feature= scopes the return to paragraphs mentioning that term."""
        state = self.get_map_state(map_name)
        if not state:
            return f"❌ Map not found: {map_name}"
        room_id = (room_id or state.get("party_location") or "").lower().strip()
        if room_id not in state.get("rooms", {}):
            return f"❌ Room not found: {room_id}"
        name = state["rooms"][room_id]["name"]
        detail = self.location_content(state, room_id, "inspection")
        if not detail:
            return f"Nothing further is apparent in {name} without a search."
        if feature:
            paras = [p for p in re.split(r'\n\s*\n', detail) if feature.lower() in p.lower()]
            if not paras:
                return (f"No further detail on '{feature}' at a glance — "
                        f"a search may reveal more.")
            detail = "\n\n".join(paras)
        return (f"**{name} — closer look**\n\n{detail}\n\n"
                "Serve the prep's details AS WRITTEN — render ONE finding plainly; hold the rest for the player's questions.")

    def reveal_secret(self, map_name: str, room_id: str, secret_id: str) -> str:
        """Mark a secret as discovered."""
        state = self.get_map_state(map_name)
        if not state:
            return f"❌ Map not found: {map_name}"
        
        room_id = room_id.lower().strip()
        secret_id = secret_id.lower().strip()
        
        if room_id not in state['rooms']:
            return f"❌ Room not found: {room_id}"
        
        room = state['rooms'][room_id]
        
        if secret_id not in room['secret_connections']:
            available = list(room['secret_connections'].keys())
            return f"❌ Secret '{secret_id}' not found in {room_id}. Available: {available}"
        
        secret = room['secret_connections'][secret_id]
        secret['found'] = True
        
        target_room_id = secret['target']
        if target_room_id in state['rooms']:
            target_room = state['rooms'][target_room_id]
            if target_room['discovery_state'] == 'unknown':
                target_room['discovery_state'] = 'noticed'
        
        state['secrets_found'].append(f"{room_id}:{secret_id}")
        state['exploration_log'].append(f"Secret found: {secret_id} in {room_id} → {target_room_id}")
        self._ledger_append(
            state,
            f"Discovered secret '{secret_id}' in {room['name']} — passage to {target_room_id}",
            room_id, "reveal_secret", provenance="map")

        self.save_map_state(map_name, state)
        
        return f"""✅ Secret revealed!

**Location:** {room['name']}
**Secret:** {secret_id}
**Leads to:** {target_room_id}

The passage is now accessible."""
    
    def set_light(self, map_name: str, has_light: bool) -> str:
        """Set whether the party has a light source (affects movement cost and search)."""
        state = self.get_map_state(map_name)
        if not state:
            return f"❌ Map not found: {map_name}"
        state['has_light'] = has_light
        self.save_map_state(map_name, state)
        return f"💡 Light {'on' if has_light else 'OFF — movement costs 3 turns, cannot search'}"

    def set_noise(self, map_name: str, noise_level: str) -> str:
        """Set party noise level: standard | noisy | loud (raises encounter odds)."""
        if noise_level not in ("standard", "noisy", "loud"):
            return "❌ noise_level must be standard, noisy, or loud"
        state = self.get_map_state(map_name)
        if not state:
            return f"❌ Map not found: {map_name}"
        state['noise_level'] = noise_level
        self.save_map_state(map_name, state)
        return f"🔊 Noise level: {noise_level}"

    def advance_turns(self, state: Dict, turns: int) -> Optional[str]:
        """Advance the turn counter on a loaded state dict and roll one encounter check.

        Operates on the passed state (caller saves). Returns encounter text or None.
        """
        old_turn = state.get('current_turn', 0)
        state['current_turn'] = old_turn + turns
        state['exploration_log'].append(f"Turn {old_turn} -> {state['current_turn']} (+{turns})")
        # B3: condition-expiry hook (server registers it as turn_hook). Fires
        # AFTER the counter advances; appended ahead of the encounter line.
        hook_lines = []
        hook = getattr(self, "turn_hook", None)
        if hook:
            try:
                hook_lines = hook(state.get("map_name", ""),
                                  state["current_turn"]) or []
            except Exception as exc:        # never let expiry kill a move
                hook_lines = [f"(condition-expiry hook error: {exc})"]
        scheduled = self._fire_turn_triggers(state)
        encounter = self._auto_encounter_check(state)
        extra = hook_lines + scheduled
        if extra:
            prefix = "\n".join(extra)
            encounter = f"{prefix}\n\n{encounter}" if encounter else prefix
        return encounter

    def _auto_encounter_check(self, state: Dict) -> Optional[str]:
        """Vaarn 2e encounter check: 1d6 (1=encounter, 2=omen, 3-6=nothing).

        noisy = 2d6 take lowest; loud = 3d6 take lowest. Reads encounter detail
        from the prep file (root canonical path) when a 1 is rolled.
        """
        import random
        noise = state.get('noise_level', 'standard')
        if noise == 'loud':
            num_dice, formula = 3, '3d6'
        elif noise == 'noisy':
            num_dice, formula = 2, '2d6'
        else:
            num_dice, formula = 1, '1d6'

        rolls = [random.SystemRandom().randint(1, 6) for _ in range(num_dice)]
        final = min(rolls)

        state['encounters_rolled'].append({
            'turn': state.get('current_turn', 0),
            'roll': final,
            'formula': formula
        })

        social = state.get("scene") == "social_site"

        if final == 1:
            if social:
                # Social scenes NEVER arm the combat trail: a hit reads TEXTURE
                # (color/tension), not reaction→lookup→combat.
                return self._read_social_texture(state)
            detail = self._read_prep_encounter(state)
            return detail or "⚔️ ENCOUNTER — roll reaction for disposition."
        elif final == 2:
            if social:
                return ("👁️ TEXTURE (social) — a quiet sign the moment is watched "
                        "(a shifted gaze, a held breath, distant murmur). Weave as "
                        "tension/color, NOT an ambush.")
            return "👁️ OMEN — a sign of what's near (tracks, sound, smell). No contact yet."
        return None

    def _read_social_texture(self, state):
        """social_site 1=hit: surface a beat of TEXTURE (color/tension), never the
        combat trail. Prefers the open parley's TEXTURE table for this site; falls
        back to the prep's parsed encounter row (reframed social) so a keyed site
        without a parley still gets flavour. NEVER calls _encounter_push_trail —
        that would inject the reaction→lookup→combat push this whole scene mode exists
        to suppress, so the fallback re-resolves the table row inline instead of
        calling _read_prep_encounter (which always appends that push)."""
        import random

        def _roll_row(entries, text_key):
            size = max(e["roll"] for e in entries)
            r = random.SystemRandom().randint(1, size)
            match = next((e for e in entries if e["roll"] == r), None)
            if not match:  # sparse table -> nearest lower entry
                lower = [e for e in entries if e["roll"] <= r]
                match = max(lower, key=lambda e: e["roll"]) if lower else entries[0]
            return f"(d{size}={r}) {match[text_key]}"

        row = None
        # 1) the open parley's own TEXTURE table for this site
        try:
            import social_system  # lazy: map_system -> social_system is one-way
            key = (state.get("map_name") or "").strip().lower()
            for _slug, p in social_system.get_open(self.campaign_dir).items():
                if (p.get("site_key") or "").strip().lower() == key and p.get("texture"):
                    row = _roll_row(p["texture"], "text")
                    break
        except Exception as exc:
            logging.debug(f"social texture lookup skipped: {exc}")

        # 2) fall back to the prep's parsed encounter row, reframed as social texture
        if row is None:
            enc = state.get("encounters")
            if enc and enc.get("type") == "random_table" and enc.get("table_entries"):
                row = _roll_row(enc["table_entries"], "encounter")

        tail = f": {row}" if row else " — improvise a beat of color from the scene"
        return (f"🎭 TEXTURE (social){tail}. Weave as tension/color, NOT an ambush "
                "(no reaction roll, no statblock — this is atmosphere).")

    def _social_entry_push(self, state: Dict) -> str:
        """On entry/resume of a social_site keyed site with no open parley for its
        site_key, push the opener so the negotiation doesn't go un-started. Mirrors
        _read_social_texture's guard: lazy `import social_system` (map_system ->
        social_system is one-way), fully exception-guarded — an import/read failure
        is silent, never a crash. Idempotent: silent once a matching parley is open.
        Silent for vault scenes (only social_site fires)."""
        if state.get("scene") != "social_site":
            return ""
        site_key = (state.get("map_name") or "").strip()
        if not site_key:
            return ""
        try:
            import social_system  # lazy: map_system -> social_system is one-way
            key = site_key.lower()
            for p in social_system.get_open(self.campaign_dir).values():
                if (p.get("site_key") or "").strip().lower() == key:
                    return ""  # a matching parley is already open
        except Exception as exc:
            logging.debug(f"social entry-push lookup skipped: {exc}")
            return ""
        import push_format as _pf
        return "\n" + _pf.next_block(
            _pf.push_call("parley", action="open", slug=f"{site_key}_parley", site=site_key),
            label="open the negotiation",
        )

    def _encounter_push_trail(self, query_hint: str = None) -> str:
        """The exact next-call trail for a fired encounter, mirroring the proven
        push wording in geography_system.py. `query_hint` is the raw table-row text
        when a table matched (passed verbatim as the fuzzy lookup query — we do NOT
        parse a creature name out of free-text rows); None (no-table / scripted)
        falls back to a placeholder the DM fills from the fiction in front of them."""
        q = query_hint.strip() if query_hint else "<the creature>"
        # Escape embedded double-quotes so the pushed call stays syntactically valid.
        q = q.replace('"', "'")
        return ("→ roll(action=\"reaction\", character=\"<highest-EGO PC>\", "
                "vs_ancestry=\"<if known>\") for its disposition.\n"
                f"→ lookup(action=\"creature\", query=\"{q}\") for its statblock.\n"
                "→ combat(action=\"init\", enemies=[...]) if it turns hostile.")

    def _read_prep_encounter(self, state):
        """Resolve a '1 = Encounter' using the parsed table stored in state."""
        enc = state.get("encounters")
        if not enc:
            return ("⚔️ ENCOUNTER — no table for this site; improvise from the area "
                    "(or generate one via content-forge).\n"
                    + self._encounter_push_trail())
        if enc.get("type") == "random_table" and enc.get("table_entries"):
            import random
            size = enc.get("dice_size") or max(e["roll"] for e in enc["table_entries"])
            r = random.SystemRandom().randint(1, size)
            match = next((e for e in enc["table_entries"] if e["roll"] == r), None)
            if not match:  # sparse table -> nearest lower entry
                lower = [e for e in enc["table_entries"] if e["roll"] <= r]
                match = max(lower, key=lambda e: e["roll"]) if lower else enc["table_entries"][0]
            row = match["encounter"]
            return (f"⚔️ ENCOUNTER (d{size}={r}): {row}"
                    f"{' — ' + match['context'] if match.get('context') else ''}.\n"
                    + self._encounter_push_trail(row))
        return ("⚔️ ENCOUNTER — scripted site; surface the active threat.\n"
                + self._encounter_push_trail())

    def _fire_turn_triggers(self, state):
        """Return any turn_based trigger descriptions whose turn is at-or-before the
        current turn, once each (tracked in state['fired_turn_triggers']). Firing
        at-or-before (not exactly ==) catches triggers jumped over by multi-turn
        moves (e.g. a 3-turn darkness move past a Turn 2 trigger) — better late
        than silently skipped, since these can spawn combat."""
        enc = state.get("encounters") or {}
        if enc.get("type") != "turn_based":
            return []
        fired = state.setdefault("fired_turn_triggers", [])
        out = []
        for trig in enc.get("turn_triggers", []):
            if trig["turn"] <= state.get("current_turn", 0) and trig["turn"] not in fired:
                fired.append(trig["turn"])
                out.append(f"⏱ SCHEDULED (turn {trig['turn']}): {trig['description']}")
        return out

    def wait(self, map_name: str) -> str:
        """Advance one dungeon turn without moving — for stationary holds (parley, search, rest at location).

        Reuses the SAME advance_turns + save_map_state machinery as enter_room/search_room so that:
          - current_turn increments (the vault-liveness gate's single mutating signal)
          - the encounter die fires (d6, standard Vaarn 2e rules)
          - any registered countdown clock decrements (handled by advance_turns → _auto_encounter_check)
        No room change occurs.
        """
        state = self.get_map_state(map_name)
        if not state:
            return f"❌ Map not found: {map_name}"

        old_turn = state.get('current_turn', 0)
        encounter = self.advance_turns(state, 1)
        state['exploration_log'].append(f"Wait/hold at {state.get('party_location', '?')}")
        self.save_map_state(map_name, state)

        new_turn = state.get('current_turn', 0)
        result = [
            f"⏳ Turn advanced: {old_turn} → {new_turn} (holding position at {state.get('party_location', '?')})",
            "Encounter die rolled.",
        ]
        if encounter:
            result.append(encounter)
        else:
            result.append("No encounter (3–6).")
        return "\n".join(result)

    def update_room(self, map_name: str, room_id: str, field: str, value: str) -> str:
        """Update a room's tracking data."""
        state = self.get_map_state(map_name)
        if not state:
            return f"❌ Map not found: {map_name}"
        
        room_id = room_id.lower().strip()
        
        if room_id not in state['rooms']:
            return f"❌ Room not found: {room_id}"
        
        room = state['rooms'][room_id]
        field = field.lower().strip()
        
        list_fields = ['notes', 'hazards', 'npcs', 'loot']
        string_fields = ['discovery_state', 'search_state', 'name']
        
        if field in list_fields:
            if value.startswith('-'):
                item = value[1:].strip()
                if item in room[field]:
                    room[field].remove(item)
                    action = f"Removed '{item}' from"
                else:
                    return f"⚠️ '{item}' not found in {field}"
            else:
                items = [v.strip() for v in value.split(',')]
                room[field].extend(items)
                action = f"Added to"
        elif field in string_fields:
            room[field] = value
            action = f"Updated"
        else:
            return f"❌ Unknown field: {field}. Use: {', '.join(list_fields + string_fields)}"
        
        state['exploration_log'].append(f"Updated {room_id}: {field}")
        self.save_map_state(map_name, state)
        
        return f"✅ {action} {field} for {room['name']}"
    
    # ========================================
    # MAP RENDERING - v3 FIXED
    # ========================================
    
    def render_map(self, map_name: str, floor: int = None, resolution: str = "compact") -> str:
        """Render ASCII map of explored areas."""
        state = self.get_map_state(map_name)
        if not state:
            return f"❌ Map not found: {map_name}"

        # Stamp for the spatial-orientation push: enter_room nags after 5+
        # unrendered turns (2026-07-20 — Thyricost "where are we?" gap).
        state["last_render_turn"] = state.get("current_turn", 0)
        self.save_map_state(map_name, state)

        if floor is None:
            floor = state['party_floor']

        # Get discovered rooms on this floor
        floor_rooms = {}
        for room_id, room in state['rooms'].items():
            if room['floor'] == floor and room['discovery_state'] != 'unknown':
                floor_rooms[room_id] = room

        if not floor_rooms:
            return f"No explored areas on floor {floor}"

        floor_name = state['floors'].get(str(floor), {}).get('name', f"Floor {floor}")

        max_box_width = 16 if resolution == "compact" else 48
        return self._render_ascii(state, floor_rooms, floor, floor_name, max_box_width=max_box_width)

    # Direction offsets for auto-layout (cardinals + diagonals; verticals
    # up/down/in/out have no xy offset and are skipped).
    _LAYOUT_OFFSETS = {
        'n': (0, -1), 'north': (0, -1),
        's': (0, 1), 'south': (0, 1),
        'e': (1, 0), 'east': (1, 0),
        'w': (-1, 0), 'west': (-1, 0),
        'ne': (1, -1), 'nw': (-1, -1),
        'se': (1, 1), 'sw': (-1, 1),
        'northeast': (1, -1), 'northwest': (-1, -1),
        'southeast': (1, 1), 'southwest': (-1, 1),
        # Same-floor vertical spines (a bore/shaft vault): descend = lower on
        # screen. Cross-floor targets never reach the BFS (floor-filtered), so
        # these only fire for rooms sharing a floor — without them a vault whose
        # spine is up/down collapses into the disconnected fallback column.
        'up': (0, -1), 'out': (0, -1),
        'down': (0, 1), 'in': (0, 1),
    }

    def _auto_layout(self, rooms: Dict[str, Dict], party_id: str = None) -> Dict[str, tuple]:
        """Compute a distinct grid cell per room from its connections.

        Used only at RENDER time (never mutates the saved map) when a floor's
        rooms all share the default [5, 5] coords, or otherwise collide. BFS
        from a deterministic start room, stepping by direction offsets; probes
        a nearby free cell on collision; appends disconnected rooms in a
        deterministic free column. Reads connection targets in both `str` and
        `{'room': ...}` shapes.
        """
        if not rooms:
            return {}

        # Deterministic start: entrance, else party room, else first id sorted.
        start = next((rid for rid in sorted(rooms) if rooms[rid].get('is_entrance')), None)
        if start is None and party_id in rooms:
            start = party_id
        if start is None:
            start = sorted(rooms)[0]

        def _target_id(target):
            if isinstance(target, str):
                return target
            if isinstance(target, dict):
                return target.get('room')
            return None

        placed: Dict[str, tuple] = {}
        used = set()

        def _probe(cell):
            """Nearest free cell to `cell` by deterministic outward ring scan."""
            if cell not in used:
                return cell
            r = 1
            while True:
                ring = []
                for dx in range(-r, r + 1):
                    for dy in range(-r, r + 1):
                        if max(abs(dx), abs(dy)) == r:
                            ring.append((cell[0] + dx, cell[1] + dy))
                for c in sorted(ring):
                    if c not in used:
                        return c
                r += 1

        # BFS from the start room.
        placed[start] = (0, 0)
        used.add((0, 0))
        queue = [start]
        while queue:
            rid = queue.pop(0)
            cx, cy = placed[rid]
            conns = rooms[rid].get('connections', {}) or {}
            for direction in sorted(conns):
                offset = self._LAYOUT_OFFSETS.get(str(direction).lower())
                if not offset:
                    continue  # vertical or unknown direction: no xy step
                tid = _target_id(conns[direction])
                if tid not in rooms or tid in placed:
                    continue
                cell = _probe((cx + offset[0], cy + offset[1]))
                placed[tid] = cell
                used.add(cell)
                queue.append(tid)

        # Any rooms not reached via connections: drop them in a free column to
        # the right, one per row, deterministically by room id.
        col = (max((c[0] for c in used), default=0)) + 2
        row = 0
        for rid in sorted(rooms):
            if rid not in placed:
                cell = _probe((col, row))
                placed[rid] = cell
                used.add(cell)
                row += 1

        return placed

    def _render_ascii(self, state: Dict, floor_rooms: Dict, floor: int, floor_name: str, max_box_width: int = 16) -> str:
        """Render floor as ASCII using coordinate-based grid - FIXED VERSION."""

        # Build coordinate lookup. If rooms collide on a cell (e.g. every room
        # defaulted to [5, 5] because the prep carried no **Coords:** lines),
        # relayout for THIS render from connections — never touching the saved
        # map. Genuinely distinct authored coords are left as-is.
        coords_map = {rid: tuple(r.get('coords', [5, 5])) for rid, r in floor_rooms.items()}
        if len(set(coords_map.values())) < len(floor_rooms):
            coords_map = self._auto_layout(floor_rooms, state.get('party_location'))

        coord_to_room = {}
        for room_id, room in floor_rooms.items():
            x, y = coords_map[room_id]
            coord_to_room[(x, y)] = room

        if not coord_to_room:
            return "No rooms to display"

        # Auto-size box to longest discovered room name, capped by max_box_width
        names = [r['name'] for r in coord_to_room.values()]
        longest = max((len(n) for n in names), default=11)
        BOX_W = max(13, min(longest + 2, max_box_width))
        CELL_W = BOX_W + 4
        BOX_H = 4    # Room box internal height
        CELL_H = 6   # Height of each cell (extra row for connections)
        
        # Find bounds
        all_x = [c[0] for c in coord_to_room.keys()]
        all_y = [c[1] for c in coord_to_room.keys()]
        min_x, max_x = min(all_x), max(all_x)
        min_y, max_y = min(all_y), max(all_y)
        
        # Grid dimensions
        cols = max_x - min_x + 1
        rows = max_y - min_y + 1
        grid_w = cols * CELL_W + 4
        grid_h = rows * CELL_H + 4
        
        # Initialize grid
        grid = [[' ' for _ in range(grid_w)] for _ in range(grid_h)]
        
        # Helper to write string to grid
        def write(gx, gy, text):
            for i, ch in enumerate(text):
                if 0 <= gy < grid_h and 0 <= gx + i < grid_w:
                    grid[gy][gx + i] = ch
        
        # Helper to write single char
        def put(gx, gy, ch):
            if 0 <= gy < grid_h and 0 <= gx < grid_w:
                grid[gy][gx] = ch
        
        # Draw each room
        for (rx, ry), room in coord_to_room.items():
            # Calculate grid position (top-left of cell)
            cx = (rx - min_x) * CELL_W + 2
            cy = (ry - min_y) * CELL_H + 2
            
            # Room box position (centered in cell)
            bx = cx + (CELL_W - BOX_W) // 2
            by = cy + 1  # Leave room for north connection
            
            # Determine glyph
            is_party = (room['id'] == state['party_location'])
            if is_party:
                glyph = GLYPHS['party']
            elif room['search_state'] == 'searched':
                glyph = GLYPHS['searched']
            elif room['discovery_state'] == 'explored':
                glyph = GLYPHS['explored']
            elif room['discovery_state'] == 'noticed':
                glyph = GLYPHS['noticed']
            else:
                glyph = ' '
            
            # Get display name - truncate smartly
            name = room['name']
            max_name_len = BOX_W - 2
            if len(name) > max_name_len:
                # Try to find a good break point
                name = name[:max_name_len]
            
            # Check for vertical connections
            has_up = any(d in ['up', 'out'] for d in room['connections'])
            has_down = any(d in ['down', 'in'] for d in room['connections'])
            if has_up and has_down:
                vert = GLYPHS['vertical_both']
            elif has_up:
                vert = GLYPHS['vertical_up']
            elif has_down:
                vert = GLYPHS['vertical_down']
            else:
                vert = ' '
            
            # Draw box (4 lines high now)
            write(bx, by, '╔' + '═' * (BOX_W - 2) + '╗')
            write(bx, by + 1, '║' + name.center(BOX_W - 2) + '║')
            write(bx, by + 2, '║' + (glyph + ' ' + vert).center(BOX_W - 2) + '║')
            write(bx, by + 3, '╚' + '═' * (BOX_W - 2) + '╝')
        
        # Second pass: draw connections AFTER all boxes
        for (rx, ry), room in coord_to_room.items():
            cx = (rx - min_x) * CELL_W + 2
            cy = (ry - min_y) * CELL_H + 2
            bx = cx + (CELL_W - BOX_W) // 2
            by = cy + 1
            
            for direction, target in room['connections'].items():
                target_id = target if isinstance(target, str) else target.get('room')

                # Check if target is discovered and on same floor
                if target_id not in floor_rooms:
                    continue

                # Draw from ACTUAL laid-out adjacency, not the direction label:
                # auto-layout may probe a neighbor to a different cell than its
                # label implies, and a same-floor up/down neighbor (vertical
                # bore spine) has no lateral label at all. Only exact N/S/E/W
                # adjacency gets a line; diagonal or probed-away neighbors are
                # left to the room-box glyphs.
                tx, ty = coords_map[target_id]
                dx, dy = tx - rx, ty - ry

                # Draw connection line
                if dx == 1 and dy == 0:  # East
                    line_y = by + 2
                    # Draw from box edge to cell edge
                    for lx in range(bx + BOX_W, cx + CELL_W):
                        put(lx, line_y, '─')
                    # Add connector on box edge
                    put(bx + BOX_W - 1, line_y, '╡')

                elif dx == -1 and dy == 0:  # West
                    line_y = by + 2
                    # Draw from cell start to box edge
                    for lx in range(cx, bx):
                        put(lx, line_y, '─')
                    # Add connector on box edge
                    put(bx, line_y, '╞')

                elif dy == 1 and dx == 0:  # South
                    line_x = bx + BOX_W // 2
                    # Draw from box bottom to cell bottom
                    for ly in range(by + BOX_H, cy + CELL_H):
                        put(line_x, ly, '│')
                    # Add connector on box edge
                    put(line_x, by + BOX_H - 1, '╧')

                elif dy == -1 and dx == 0:  # North
                    line_x = bx + BOX_W // 2
                    # Draw from cell top to box top
                    for ly in range(cy, by):
                        put(line_x, ly, '│')
                    # Add connector on box edge
                    put(line_x, by, '╤')
        
        # Convert grid to string
        lines = [''.join(row).rstrip() for row in grid]
        
        # Trim empty lines
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        
        # Build header
        header = [
            f"{state['map_name'].upper()} - {floor_name.upper()}",
            "═" * 60,
            ""
        ]
        
        # Vertical exits from current room
        party_room = state['rooms'].get(state['party_location'], {})
        vert_exits = []
        if party_room and party_room['floor'] == floor:
            for d, t in party_room.get('connections', {}).items():
                if d in VERTICAL_DIRECTIONS:
                    t_str = t if isinstance(t, str) else f"{t['room']}@{t['floor']}"
                    vert_exits.append(f"{d}→{t_str}")
        
        footer = [
            "",
            "─" * 60,
            "◈ Party  ○ Explored  △ Searched  ? Noticed  ↕ Vertical",
        ]
        if vert_exits:
            footer.append(f"Vertical: {', '.join(vert_exits)}")
        
        return '\n'.join(header + lines + footer)

    def render_fog(self, map_name: str) -> str:
        """Player-facing fog-of-war render: only rooms the party has explored
        or noticed; secret rooms and unknown rooms are absent entirely (never
        just hidden-but-present); party position marked '⊕'; noticed-but-
        unexplored rooms marked '?'. Names and known connections only — never
        room contents (hazards/npcs/loot/notes).

        Primary path delegates to `_render_ascii` over a fog-filtered deep
        copy of the state, mirroring how `render_map` calls it — real
        prep-inited rooms always carry 'coords' (`_parse_rooms_from_prep`
        defaults it), so this is the normal path for every real map. Falls
        back to a simpler room-list render only when a known room lacks
        'coords' (older/malformed saves) — a degraded path, not the default.
        """
        state = self.get_map_state(map_name)
        if not state:
            return f"(no active map — nothing to render for '{map_name}')"

        rooms = state.get('rooms', {})
        known = {rid: r for rid, r in rooms.items()
                 if r.get('discovery_state') in ('explored', 'noticed')
                 and not r.get('is_secret')}

        if not known:
            return f"{state.get('map_name', map_name).upper()} — nothing explored yet"

        known_ids = set(known)
        if all('coords' in r for r in known.values()):
            text = self._render_fog_spatial(state, known, known_ids)
        else:
            text = self._render_fog_list(state, known, known_ids)
        return text.replace(GLYPHS['party'], '⊕')

    def _filter_fog_connections(self, conns: Optional[Dict], known_ids: set) -> Dict:
        """Keep only connection targets that point at a known (fog-visible) room.
        Drops any shape `_render_ascii` can't safely draw (e.g. a list target) —
        those never occur in real prep-parsed connections, only in malformed data."""
        filtered = {}
        for direction, target in (conns or {}).items():
            if isinstance(target, str):
                if target in known_ids:
                    filtered[direction] = target
            elif isinstance(target, dict):
                if target.get('room') in known_ids:
                    filtered[direction] = target
        return filtered

    def _render_fog_spatial(self, state: Dict, known: Dict, known_ids: set) -> str:
        """Primary fog render: reuses `_render_ascii` (the same drawing engine
        as the DM's `render_map`) over a fog-filtered deep copy, so player and
        DM maps share one renderer."""
        import copy
        fog_rooms = {}
        for rid, r in known.items():
            fr = copy.deepcopy(r)
            fr['connections'] = self._filter_fog_connections(fr.get('connections'), known_ids)
            fog_rooms[rid] = fr
        fog_state = dict(state)
        fog_state['rooms'] = fog_rooms

        by_floor: Dict[Any, Dict] = {}
        for rid, r in fog_rooms.items():
            by_floor.setdefault(r.get('floor', 1), {})[rid] = r

        _FOG_BOX_W = 16  # keep in sync with the _render_ascii call below
        parts = []
        for floor in sorted(by_floor):
            floor_name = state.get('floors', {}).get(str(floor), {}).get('name', f"Floor {floor}")
            parts.append(self._render_ascii(fog_state, by_floor[floor], floor, floor_name, max_box_width=_FOG_BOX_W))

        # Grid boxes hard-truncate names to BOX_W - 2 chars; append the full
        # names of anything that got cut so the render never loses a name.
        cut = sorted({r['name'] for r in fog_rooms.values()
                      if len(r.get('name', '')) > _FOG_BOX_W - 2})
        if cut:
            parts.append("FULL NAMES (truncated on the grid):\n" +
                         "\n".join(f"  • {n}" for n in cut))
        return '\n\n'.join(parts)

    def _render_fog_list(self, state: Dict, known: Dict, known_ids: set) -> str:
        """Degraded fallback fog render, used only when a known room lacks
        'coords' and so can't go through the coordinate-grid `_render_ascii`
        renderer (real prep-inited maps always have coords; this covers
        older/malformed saves)."""
        party_location = state.get('party_location')
        map_name = state.get('map_name', 'map')

        def _known_targets(conns: Dict) -> List[str]:
            names = []
            for target in (conns or {}).values():
                candidates = target if isinstance(target, list) else [target]
                for t in candidates:
                    tid = t if isinstance(t, str) else (t or {}).get('room')
                    if tid and tid in known_ids:
                        names.append(known[tid].get('name', tid))
            return names

        by_floor: Dict[Any, List[str]] = {}
        for rid, room in known.items():
            by_floor.setdefault(room.get('floor', 1), []).append(rid)

        sections = []
        for floor in sorted(by_floor, key=lambda f: (f is None, f)):
            lines = [f"{map_name.upper()} — FLOOR {floor}", "=" * 60, ""]
            for rid in by_floor[floor]:
                room = known[rid]
                label = room.get('name', rid)
                if room.get('discovery_state') == 'noticed':
                    label = f"{label} ?"
                if rid == party_location:
                    label = f"⊕ {label}"
                lines.append(label)
                for target_name in _known_targets(room.get('connections')):
                    lines.append(f"    -> {target_name}")
                lines.append("")
            lines.append("-" * 60)
            lines.append("⊕ Party  ? Noticed, not yet explored")
            sections.append('\n'.join(lines))

        return '\n\n'.join(sections)

    # ========================================
    # ROOM CONTENT
    # ========================================

    def get_room_content(self, map_name: str, room_id: str = None) -> str:
        """Get full room content for referee use."""
        state = self.get_map_state(map_name)
        if not state:
            return f"❌ Map not found: {map_name}"
        
        if room_id is None:
            room_id = state['party_location']
        
        room_id = room_id.lower().strip()
        
        if room_id not in state['rooms']:
            return f"❌ Room not found: {room_id}"
        
        room = state['rooms'][room_id]
        
        return self._format_room_content(room, for_referee=True)
    
    def _format_room_content(self, room: Dict, for_referee: bool = True,
                             include_prep: bool = True) -> str:
        """Format room content for display. When include_prep is False, the raw
        prep_content dump is omitted (enter_room surfaces tiered content instead,
        so the secret/hidden bodies never leak on arrival)."""
        
        lines = [
            "═" * 60,
            f"  {room['name'].upper()} (Floor {room['floor']})",
            "═" * 60,
            ""
        ]
        
        # Status
        lines.append(f"**Status:** {room['discovery_state']} | Searched: {room['search_state']}")
        lines.append("")
        
        # Connections
        if room['connections']:
            lines.append("**Exits:**")
            for direction, target in room['connections'].items():
                target_str = target if isinstance(target, str) else f"{target['room']} (Floor {target['floor']})"
                lines.append(f"  {direction}: {target_str}")
            lines.append("")
        
        # Secrets (DM only). DM-gated: never auto-print on the enter/search path
        # (include_prep is False there) — the target room is a reveal_secret-only
        # disclosure. Full view (get_room, include_prep=True) still shows it.
        if include_prep and for_referee and room['secret_connections']:
            lines.append("**SECRETS (DM ONLY):**")
            for secret_id, secret in room['secret_connections'].items():
                found_str = "✓ FOUND" if secret['found'] else "hidden"
                lines.append(f"  • {secret_id} → {secret['target']} [{found_str}]")
                lines.append(f"    Requires: {secret['discovery']}")
            lines.append("")
        
        # Hazards
        if room['hazards']:
            lines.append("**Hazards:**")
            for hazard in room['hazards']:
                lines.append(f"  ☠ {hazard}")
            lines.append("")
        
        # NPCs
        if room['npcs']:
            lines.append("**NPCs:**")
            for npc in room['npcs']:
                lines.append(f"  • {npc}")
            lines.append("")
        
        # Loot — structured list. Hidden until SEARCH: suppressed on the
        # enter/search-format path (include_prep is False); search_room surfaces
        # it explicitly at the hidden tier. Full view (include_prep=True) shows it.
        if include_prep and room['loot']:
            lines.append("**Loot:**")
            for loot in room['loot']:
                lines.append(f"  $ {loot}")
            lines.append("")
        
        # Notes
        if room['notes']:
            lines.append("**Notes:**")
            for note in room['notes']:
                lines.append(f"  • {note}")
            lines.append("")
        
        # Prep content
        if include_prep and for_referee and room.get('prep_content'):
            lines.append("**FROM PREP FILE:**")
            lines.append("─" * 40)
            content = room['prep_content']
            content_lines = []
            for line in content.split('\n'):
                if not any(line.strip().lower().startswith(f'**{f}:**') 
                          for f in ['floor', 'coords', 'name', 'connections', 'secrets', 
                                   'type', 'entrance', 'hazards', 'npcs', 'loot']):
                    content_lines.append(line)
            content = '\n'.join(content_lines).strip()
            if len(content) > 1500:
                content = content[:1500] + "\n... [truncated]"
            lines.append(content)
        
        lines.append("═" * 60)
        
        return '\n'.join(lines)
    
    def query_nearby(self, map_name: str, room_id: str = None, include_vertical: bool = True) -> str:
        """Query what's nearby for quick reference."""
        state = self.get_map_state(map_name)
        if not state:
            return f"❌ Map not found: {map_name}"
        
        if room_id is None:
            room_id = state['party_location']
        
        room_id = room_id.lower().strip()
        
        if room_id not in state['rooms']:
            return f"❌ Room not found: {room_id}"
        
        room = state['rooms'][room_id]
        
        lines = [
            f"**NEARBY:** From {room['name']}",
            "═" * 40,
            ""
        ]
        
        horizontal = []
        vertical = []
        secrets = []
        
        for direction, target in room['connections'].items():
            target_id = target if isinstance(target, str) else target.get('room')
            target_floor = target.get('floor', room['floor']) if isinstance(target, dict) else room['floor']
            
            if target_id in state['rooms']:
                target_room = state['rooms'][target_id]
                status = target_room['discovery_state']
                name = target_room['name'] if status != 'unknown' else '???'
                
                entry = f"  {direction}: {name} [{status}]"
                
                if direction in VERTICAL_DIRECTIONS:
                    if target_floor != room['floor']:
                        entry += f" (Floor {target_floor})"
                    vertical.append(entry)
                else:
                    horizontal.append(entry)
        
        for secret_id, secret in room['secret_connections'].items():
            if secret['found']:
                target_id = secret['target']
                if target_id in state['rooms']:
                    target_room = state['rooms'][target_id]
                    secrets.append(f"  {secret_id}: {target_room['name']} [SECRET]")
        
        if horizontal:
            lines.append("**Same Floor:**")
            lines.extend(horizontal)
            lines.append("")
        
        if include_vertical and vertical:
            lines.append("**Vertical:**")
            lines.extend(vertical)
            lines.append("")
        
        if secrets:
            lines.append("**Secret Passages:**")
            lines.extend(secrets)
            lines.append("")
        
        if room['hazards']:
            lines.append("**Hazards Here:**")
            for hazard in room['hazards']:
                lines.append(f"  ☠ {hazard}")
        
        return '\n'.join(lines)

    def spatial_summary(self, map_name: str) -> Optional[str]:
        """Inject-ready snapshot of live vault state for check_canon (DM-facing).

        Reports: party room/floor/turn, adjacent rooms with their discovery
        state, unexplored exits, and undiscovered secrets in the current room.
        Returns None if the map does not exist.
        """
        state = self.get_map_state(map_name)
        if not state:
            return None
        if state.get("kind") == "site" and not state.get("rooms"):
            return (f"📍 Active site: {state.get('map_name')} (ambient) — turn "
                    f"{state.get('current_turn', 0)}. Encounter die active each turn.")
        rooms = state.get('rooms', {})
        party = state.get('party_location', '')
        if not party or party not in rooms:
            return (f"**ACTIVE MAP: {map_name}** — party_location missing or invalid "
                    f"({party!r}); state may need repair")
        room = rooms[party]
        lines = [
            f"**ACTIVE MAP: {map_name}** — Floor {state.get('party_floor', '?')}, "
            f"Turn {state.get('current_turn', 0)}",
            f"Party in: {room.get('name', party)} ({party})",
        ]

        adj = []
        unexplored = []
        for direction, target in room.get('connections', {}).items():
            target_id = target if isinstance(target, str) else target.get('room', '')
            if not target_id or target_id not in rooms:
                continue  # skip dangling refs (mirrors query_nearby)
            tstate = rooms[target_id].get('discovery_state', 'unknown')
            adj.append(f"{direction}→{target_id} [{tstate}]")
            if tstate in ('unknown', 'noticed'):
                unexplored.append(f"{direction}→{target_id}")
        if adj:
            lines.append("Exits: " + ", ".join(adj))
        if unexplored:
            lines.append("Unexplored exits: " + ", ".join(unexplored))

        undiscovered = [sid for sid, s in room.get('secret_connections', {}).items()
                        if not s.get('found')]
        if undiscovered:
            lines.append(f"Undiscovered secret(s) here: {', '.join(undiscovered)} "
                         "(DM-only — require search to reveal)")

        return "\n".join(lines)

    def list_floors(self, map_name: str) -> str:
        """List all floors with exploration status."""
        state = self.get_map_state(map_name)
        if not state:
            return f"❌ Map not found: {map_name}"
        
        lines = [
            f"**{state['map_name'].upper()}** - Floor Overview",
            "═" * 40,
            ""
        ]
        
        floor_stats = {}
        for room_id, room in state['rooms'].items():
            floor = room['floor']
            if floor not in floor_stats:
                floor_stats[floor] = {'total': 0, 'explored': 0, 'searched': 0, 'secrets': 0, 'secrets_found': 0}
            
            floor_stats[floor]['total'] += 1
            if room['discovery_state'] in ['explored', 'searched']:
                floor_stats[floor]['explored'] += 1
            if room['search_state'] == 'searched':
                floor_stats[floor]['searched'] += 1
            
            floor_stats[floor]['secrets'] += len(room['secret_connections'])
            floor_stats[floor]['secrets_found'] += sum(1 for s in room['secret_connections'].values() if s['found'])
        
        for floor in sorted(floor_stats.keys()):
            stats = floor_stats[floor]
            floor_name = state['floors'].get(str(floor), {}).get('name', f"Floor {floor}")
            
            party_here = " ◈" if state['party_floor'] == floor else ""
            pct = (stats['explored'] / stats['total'] * 100) if stats['total'] > 0 else 0
            
            lines.append(f"**Floor {floor}: {floor_name}**{party_here}")
            lines.append(f"  Explored: {stats['explored']}/{stats['total']} ({pct:.0f}%)")
            if stats['secrets'] > 0:
                lines.append(f"  Secrets: {stats['secrets_found']}/{stats['secrets']}")
            lines.append("")
        
        return '\n'.join(lines)


# ============================================
# TOOL REGISTRATION
# ============================================

def _get_tool_tags(tool_name: str) -> set[str]:
    """Get tags for a tool from the central mapping."""
    return TOOL_TAGS.get(tool_name, {Safety.ALWAYS})


def register_map_tools(mcp, campaign_dir: Path):
    """Register consolidated map tool with the MCP server."""

    map_sys = MapSystem(campaign_dir)

    @mcp.tool(
        annotations={"readOnlyHint": False, "idempotentHint": False},
        tags=_get_tool_tags("map")
    )
    def map(
        action: str,
        map_name: str,
        prep_file: str = None,
        map_type: str = "vault",
        floor: int = None,
        room_id: str = None,
        secret_id: str = None,
        fact: str = None,
        provenance: str = None,
        field: str = None,
        value: str = None,
        include_vertical: bool = True,
        resolution: str = "compact",
        reset: bool = False,
        rooms: int = 5,
        encounter_die: int = 6,
        feature: str = None,
        track_op: str = None,
        track_id: str = None,
        title: str = None,
        stand: str = None,
        blocked_by: str = None,
        next_step: str = None,
        clock: str = None,
        status: str = None
    ) -> str:
        """Reach for this WHEN the party enters, moves through, or searches a keyed vault or dungeon — init loads the prep file, then enter/search/wait/render drive play room by room.

        Spatial map system for vault/dungeon exploration.

        Actions:
            scaffold: Mint a keyed-vault prep SKELETON (map_name, rooms?, prep_file?, encounter_die?) — N connected rooms + an encounter-table stub in the schema init parses. Fill the souls + encounter rows, then init. Use this for a vault/ruin opening so map(init) is viable and the encounter die can roll.
            init: Initialize from prep file (map_name, prep_file, map_type?)
            render: ASCII map (map_name, floor?, resolution?)
            enter: Enter room (map_name, room_id)
            search: Search for secrets (map_name, room_id?)
            look: Inspection detail after enter (map_name, room_id?, feature?) — free, no turn cost
            wait: Hold position — advance 1 turn, roll encounter die, no room change (satisfies vault-liveness gate)
            reveal_secret: Reveal secret (map_name, room_id, secret_id)
            reveal: Ledger a fact the party just learned socially/by deduction (map_name, fact, room_id?, provenance) — provenance: required for reveal — 'prep:<exact phrase>' | 'ledger:<n>' | 'player' | 'mint'
            track: Manage the Expedition Docket — the party's open business at this site (map_name, track_op="add|update|resolve|list", track_id, title?, stand?, status?, blocked_by?, next_step?, clock?). add declares a strand; update patches only the fields you pass; resolve retires it (stays as history); list shows all.
            docket: Render the player-facing Expedition Docket document (map_name) — relay verbatim as the party's own paperwork
            get_room: Get room content (map_name, room_id?)
            update_room: Update room data (map_name, room_id, field, value)
            set_light: Toggle light source (map_name, value="false" for darkness)
            set_noise: Set noise level (map_name, value=standard|noisy|loud)
            query_nearby: Adjacent rooms (map_name, room_id?, include_vertical?)
            list_floors: Floor overview (map_name)
            enter_site: Create-or-resume a site from a prep file (map_name, prep_file, map_type?, reset?) — resumes turn count if revisited; reset=True rebuilds from the prep (only overwrites on a valid prep)

        Examples:
            map(action="init", map_name="vermillion_archive", prep_file="VERMILLION_ARCHIVE_PREP.md")
            map(action="render", map_name="vermillion_archive")
            map(action="render", map_name="vermillion_archive", resolution="large")
            map(action="enter", map_name="vermillion_archive", room_id="galleries_hub")
            map(action="search", map_name="vermillion_archive")
            map(action="wait", map_name="kept_sill")
        """
        action = action.lower().strip()

        if action == "init":
            if not prep_file:
                return "Error: init requires prep_file"
            result = map_sys.init_map_from_prep(map_name, prep_file, map_type)

        elif action == "scaffold":
            result = map_sys.scaffold_prep(map_name, rooms=rooms, prep_file=prep_file,
                                         encounter_die=encounter_die)

        elif action == "render":
            result = map_sys.render_map(map_name, floor, resolution)

        elif action == "enter":
            if not room_id:
                return "Error: enter requires room_id"
            result = map_sys.enter_room(map_name, room_id)

        elif action == "search":
            result = map_sys.search_room(map_name, room_id)

        elif action == "wait":
            result = map_sys.wait(map_name)

        elif action == "reveal_secret":
            if not room_id or not secret_id:
                return "Error: reveal_secret requires room_id, secret_id"
            result = map_sys.reveal_secret(map_name, room_id, secret_id)

        elif action == "look":
            result = map_sys.look_room(map_name, room_id, feature)

        elif action == "reveal":
            if not fact:
                return "Error: reveal requires fact"
            result = map_sys.reveal_fact(map_name, fact, room_id, provenance=provenance)

        elif action == "get_room":
            result = map_sys.get_room_content(map_name, room_id)

        elif action == "update_room":
            if not room_id or not field or not value:
                return "Error: update_room requires room_id, field, value"
            result = map_sys.update_room(map_name, room_id, field, value)

        elif action == "set_light":
            if value is None:
                return "Error: set_light requires value (true|false)"
            result = map_sys.set_light(map_name, value.lower() in ("true", "1", "yes", "on"))

        elif action == "set_noise":
            if not value:
                return "Error: set_noise requires value (standard|noisy|loud)"
            result = map_sys.set_noise(map_name, value.lower())

        elif action == "query_nearby":
            result = map_sys.query_nearby(map_name, room_id, include_vertical)

        elif action == "list_floors":
            result = map_sys.list_floors(map_name)

        elif action == "enter_site":
            if not prep_file:
                return "Error: enter_site requires prep_file"
            _day = map_sys.get_day() if callable(getattr(map_sys, "get_day", None)) else None
            result = map_sys.init_or_resume_map(map_name, prep_file, map_type,
                                              current_day=_day, reset=reset)

        elif action == "track":
            top = (track_op or "").lower().strip()
            if top == "add":
                if not track_id or not title:
                    return "Error: track add requires track_id, title"
                result = map_sys.track_add(
                    map_name, track_id, title, stand=stand or "",
                    status=status or "OPEN", blocked_by=blocked_by or "",
                    next_step=next_step or "", clock=clock or "")
            elif top == "update":
                if not track_id:
                    return "Error: track update requires track_id"
                result = map_sys.track_update(
                    map_name, track_id, title=title, stand=stand, status=status,
                    blocked_by=blocked_by, next_step=next_step, clock=clock)
            elif top == "resolve":
                if not track_id:
                    return "Error: track resolve requires track_id"
                result = map_sys.track_resolve(map_name, track_id)
            elif top == "list":
                result = map_sys.track_list(map_name)
            else:
                return "Error: track requires track_op (add|update|resolve|list)"

        elif action == "docket":
            result = map_sys.render_docket(map_name)

        else:
            return f"Unknown action: {action}. Valid actions: scaffold, init, render, enter, search, wait, reveal_secret, reveal, look, get_room, update_room, set_light, set_noise, query_nearby, list_floors, enter_site, track, docket"

        if map_sys.on_state_change:
            try:
                map_sys.on_state_change(map_name)
            except Exception as exc:
                logging.warning(f"on_state_change callback failed for {map_name}: {exc}")
        return result

    return map_sys
