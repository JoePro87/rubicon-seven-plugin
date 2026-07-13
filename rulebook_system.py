# ============================================
# RUBICON SEVEN - RULEBOOK SYSTEM
# ============================================
#
# Keyword-driven mechanical rules lookup.
# Mirrors lorebook architecture for lore,
# but serves game mechanics from Vaarn 2e.
#

import json
from pathlib import Path
from typing import Dict, List, Optional

from tool_tags import TOOL_TAGS
from engine_core import RULES_DATA_DIR


class RulebookSystem:
    """Mechanical rules lookup system for Vaarn 2e."""

    # Turns before an entry can be re-injected
    COOLDOWN_TURNS = 15

    def __init__(self, campaign_dir: Path):
        self.campaign_dir = campaign_dir
        # Book data is engine-bundled rules-data (engine-always-wins), NOT play-state.
        self.rulebook_dir = RULES_DATA_DIR / "rulebook"
        self._cache = {}
        # Session-level dedup: {entry_id: turn_injected}
        self._injections: Dict[str, int] = {}
        self._turn: int = 0
        # Count of query-relevant entries hidden by cooldown on the last search()
        self._last_suppressed: int = 0
        self._load_all()

    def _load_all(self):
        """Load all rulebook JSON files into cache."""
        self._cache = {
            'rules': [],
            'tables': {'rolling': [], 'reference': []},
            'bestiary': [],
            'equipment': [],
            'gifts': [],
            'lore': []
        }

        # Load rules
        rules_path = self.rulebook_dir / "rules.json"
        if rules_path.exists():
            with open(rules_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self._cache['rules'] = data.get('entries', [])

        # Load tables
        tables_path = self.rulebook_dir / "tables.json"
        if tables_path.exists():
            with open(tables_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self._cache['tables']['rolling'] = data.get('rolling_tables', [])
                self._cache['tables']['reference'] = data.get('reference_tables', [])

        # Load bestiary
        bestiary_path = self.rulebook_dir / "bestiary.json"
        if bestiary_path.exists():
            with open(bestiary_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self._cache['bestiary'] = data.get('entries', [])

        # Load equipment
        equipment_path = self.rulebook_dir / "equipment.json"
        if equipment_path.exists():
            with open(equipment_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self._cache['equipment'] = data.get('entries', [])

        # Load gifts
        gifts_path = self.rulebook_dir / "gifts.json"
        if gifts_path.exists():
            with open(gifts_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self._cache['gifts'] = data.get('entries', [])

        # Load lore additions
        lore_path = self.rulebook_dir / "lore_additions.json"
        if lore_path.exists():
            with open(lore_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self._cache['lore'] = data.get('entries', [])

    def reload(self):
        """Reload all data from disk."""
        self._load_all()
        return f"Reloaded: {len(self._cache['rules'])} rules, " \
               f"{len(self._cache['tables']['rolling'])} rolling tables, " \
               f"{len(self._cache['tables']['reference'])} reference tables, " \
               f"{len(self._cache['bestiary'])} creatures, " \
               f"{len(self._cache['equipment'])} equipment, " \
               f"{len(self._cache['gifts'])} gifts, " \
               f"{len(self._cache['lore'])} lore"

    def reset_session(self):
        """Clear injection cache for new session."""
        self._injections = {}
        self._turn = 0
        self._last_suppressed = 0
        return "Session reset: injection cache cleared"

    def advance_turn(self):
        """Advance the dedup clock by one tick and prune expired cooldowns.

        The clock is now self-driven from search() (one tick per search call), so
        the cooldown actually expires without any external per-turn wiring. This
        action stays for back-compat but is no longer required to be called.
        """
        self._tick()
        return f"Turn {self._turn}, {len(self._injections)} entries on cooldown"

    def _tick(self):
        """Advance the dedup clock one step and drop injections past cooldown."""
        self._turn += 1
        cutoff = self._turn - self.COOLDOWN_TURNS
        self._injections = {k: v for k, v in self._injections.items() if v > cutoff}

    def _is_on_cooldown(self, entry_id: str) -> bool:
        """Check if entry was recently injected."""
        if entry_id not in self._injections:
            return False
        injected_turn = self._injections[entry_id]
        return (self._turn - injected_turn) < self.COOLDOWN_TURNS

    def _mark_injected(self, entry_id: str):
        """Mark entry as injected this turn."""
        self._injections[entry_id] = self._turn

    def _match_keywords(self, entry: Dict, query_terms: List[str]) -> int:
        """Score entry by keyword match. Higher = better match."""
        entry_keywords = [k.lower() for k in entry.get('keywords', [])]
        score = 0
        for term in query_terms:
            term_lower = term.lower()
            # Exact keyword match = 3 points
            if term_lower in entry_keywords:
                score += 3
            # Partial keyword match = 1 point
            elif any(term_lower in kw for kw in entry_keywords):
                score += 1
            # ID match = 2 points
            elif term_lower in entry.get('id', '').lower():
                score += 2
        return score

    def search(self, query: str, types: Optional[List[str]] = None, limit: int = 5,
               skip_cooldown: bool = False) -> List[Dict]:
        """Search across rulebook entries by keyword.

        Args:
            query: Space-separated search terms
            types: Filter to specific types ['rules', 'tables', 'bestiary', 'equipment', 'gifts', 'lore']
            limit: Max results per type
            skip_cooldown: If True, ignore dedup cooldown (for explicit lookups)

        Returns:
            List of matching entries with _type and _score fields
        """
        query_terms = query.lower().split()
        self._last_suppressed = 0
        if not query_terms:
            return []

        # Self-driving dedup clock: each search call is one tick, so a previously
        # returned entry's cooldown actually expires after COOLDOWN_TURNS searches
        # instead of never (no external turn/session_reset wiring needed). See C6.
        if not skip_cooldown:
            self._tick()

        types = types or ['rules', 'tables', 'bestiary', 'equipment', 'gifts', 'lore']
        results = []

        def collect(entries, type_label):
            """Score entries; keep query matches, count cooldown-hidden matches."""
            for entry in entries:
                score = self._match_keywords(entry, query_terms)
                if score <= 0:
                    continue
                entry_id = entry.get('id', '')
                if not skip_cooldown and self._is_on_cooldown(entry_id):
                    self._last_suppressed += 1
                    continue
                results.append({**entry, '_type': type_label, '_score': score})

        if 'rules' in types:
            collect(self._cache['rules'], 'rule')
        if 'tables' in types:
            collect(self._cache['tables']['rolling'] + self._cache['tables']['reference'], 'table')
        if 'bestiary' in types:
            collect(self._cache['bestiary'], 'creature')
        if 'equipment' in types:
            collect(self._cache['equipment'], 'equipment')
        if 'gifts' in types:
            collect(self._cache['gifts'], 'gift')
        if 'lore' in types:
            collect(self._cache['lore'], 'lore')

        # Sort by score descending, take top N
        results.sort(key=lambda x: x['_score'], reverse=True)
        final_results = results[:limit]

        # Mark returned entries as injected (unless skip_cooldown)
        if not skip_cooldown:
            for r in final_results:
                entry_id = r.get('id', '')
                if entry_id:
                    self._mark_injected(entry_id)

        return final_results

    def get_rule(self, rule_id: str) -> Optional[Dict]:
        """Get a specific rule by ID."""
        for entry in self._cache['rules']:
            if entry.get('id') == rule_id:
                return entry
        return None

    def get_creature(self, creature_id: str) -> Optional[Dict]:
        """Get a specific creature by ID."""
        for entry in self._cache['bestiary']:
            if entry.get('id') == creature_id:
                return entry
        return None

    def get_table(self, table_id: str) -> Optional[Dict]:
        """Get a specific table by ID."""
        for entry in self._cache['tables']['rolling'] + self._cache['tables']['reference']:
            if entry.get('id') == table_id:
                return entry
        return None

    def get_gift(self, gift_id: str) -> Optional[Dict]:
        """Get a specific gift by ID."""
        for entry in self._cache['gifts']:
            if entry.get('id') == gift_id:
                return entry
        return None

    def get_lore(self, lore_id: str) -> Optional[Dict]:
        """Get a specific lore entry by ID."""
        for entry in self._cache['lore']:
            if entry.get('id') == lore_id:
                return entry
        return None

    def format_rule(self, entry: Dict) -> str:
        """Format a rule entry for display."""
        lines = [f"**{entry.get('id', 'Unknown')}**"]
        if 'rule' in entry:
            lines.append(entry['rule'])
        if 'source' in entry:
            lines.append(f"_Source: {entry['source']}_")
        return "\n".join(lines)

    def format_creature(self, entry: Dict) -> str:
        """Format a creature entry for display."""
        stats = entry.get('stats', {})
        lines = [
            f"**{entry.get('id', 'Unknown').replace('creature-', '').replace('-', ' ').title()}**",
            f"Level {stats.get('level', '?')} | AV {stats.get('av', '?')} | Morale {stats.get('morale', '?')}"
        ]

        attacks = stats.get('attacks', [])
        if attacks:
            atk_strs = [f"{a.get('name', '?')}: {a.get('damage', '?')}" for a in attacks]
            lines.append(f"Attacks: {', '.join(atk_strs)}")

        specials = stats.get('special', [])
        if specials:
            lines.append(f"Special: {'; '.join(specials[:2])}")

        return "\n".join(lines)

    def format_table(self, entry: Dict, roll_result: int = None) -> str:
        """Format a table entry for display. If roll_result provided, show that row."""
        lines = [f"**{entry.get('id', 'Unknown')}** (d{entry.get('die', '?').replace('d', '')})"]

        entries = entry.get('entries', [])
        if roll_result and entries:
            # Find matching row — supports exact roll and range-based entries
            matched_row = None
            for row in entries:
                if row.get('roll') == roll_result:
                    matched_row = row
                    break
                if 'range' in row and '-' in str(row['range']):
                    try:
                        lo, hi = (int(x) for x in str(row['range']).split('-'))
                        if lo <= roll_result <= hi:
                            matched_row = row
                            break
                    except ValueError:
                        pass
            if matched_row:
                parts = [f"{k}: {v}" for k, v in matched_row.items() if k != 'roll']
                lines.append(f"Roll {roll_result}: {', '.join(parts)}")
        elif entries:
            # Show first 3 rows as sample
            lines.append(f"({len(entries)} entries)")

        return "\n".join(lines)

    def format_lore(self, entry: Dict) -> str:
        """Format a lore entry for display."""
        lines = [f"**{entry.get('id', 'Unknown')}**"]
        if 'text' in entry:
            lines.append(entry['text'])
        if 'source' in entry:
            lines.append(f"_Source: {entry['source']}_")
        return "\n".join(lines)

    def stats(self) -> Dict[str, int]:
        """Return counts of loaded entries."""
        return {
            'rules': len(self._cache['rules']),
            'rolling_tables': len(self._cache['tables']['rolling']),
            'reference_tables': len(self._cache['tables']['reference']),
            'bestiary': len(self._cache['bestiary']),
            'equipment': len(self._cache['equipment']),
            'gifts': len(self._cache['gifts']),
            'lore': len(self._cache['lore'])
        }


def _get_tool_tags(tool_name: str) -> dict:
    """Get tool tags in MCP-compatible format."""
    tags = TOOL_TAGS.get(tool_name, set())
    return {"tags": list(tags)} if tags else {}


def register_rulebook_tools(mcp, campaign_dir: Path):
    """Register rulebook tool with the MCP server."""

    rb_sys = RulebookSystem(campaign_dir)

    @mcp.tool(
        annotations={"readOnlyHint": True, "idempotentHint": True},
        tags=_get_tool_tags("rulebook")
    )
    def rulebook(
        action: str,
        query: str = None,
        id: str = None,
        types: str = None,
        limit: int = 5,
        roll: int = None
    ) -> str:
        """Reach for this WHEN you need to keyword-search across rules, tables, bestiary, or lore — for a direct by-name fetch of a known creature or item, use lookup() instead.

        search: Keyword search (query, types?, limit?) — a self-expiring dedup cooldown hides a just-returned entry for the next 15 searches, and any hidden matches are reported in the output | get: Fetch entry by id — bypasses cooldown | stats: Entry counts + cooldown status | reload: Reload from disk | turn: (legacy no-op; the cooldown is self-driven now) | session_reset: Clear dedup cache (auto-called at session start). Types (comma-separated): rules, tables, bestiary, equipment, gifts, lore.
        """
        action = action.lower().strip()

        if action == "session_reset":
            return rb_sys.reset_session()

        if action == "turn":
            return rb_sys.advance_turn()

        if action == "stats":
            counts = rb_sys.stats()
            return f"Rulebook loaded: {counts['rules']} rules, " \
                   f"{counts['rolling_tables']} rolling tables, " \
                   f"{counts['reference_tables']} reference tables, " \
                   f"{counts['bestiary']} creatures, " \
                   f"{counts['equipment']} equipment, " \
                   f"{counts['gifts']} gifts, " \
                   f"{counts['lore']} lore | " \
                   f"Turn {rb_sys._turn}, {len(rb_sys._injections)} on cooldown"

        if action == "reload":
            return rb_sys.reload()

        if action == "search":
            if not query:
                return "Error: search requires query parameter"

            type_list = None
            if types:
                type_list = [t.strip().lower() for t in types.split(',')]

            results = rb_sys.search(query, types=type_list, limit=limit)

            suppressed = rb_sys._last_suppressed
            suppress_note = ""
            if suppressed:
                suppress_note = (
                    f"\n({suppressed} matching entr{'y' if suppressed == 1 else 'ies'} "
                    f"suppressed by dedup cooldown — re-run to let them expire, or use "
                    f"action='get' with the entry id to bypass.)"
                )

            if not results:
                return f"No matches for '{query}'{suppress_note}"

            # Format results
            lines = [f"**{len(results)} matches for '{query}':**\n"]
            for r in results:
                rtype = r['_type']
                if rtype == 'rule':
                    lines.append(rb_sys.format_rule(r))
                elif rtype == 'gift':
                    lines.append(rb_sys.format_rule(r))
                elif rtype == 'creature':
                    lines.append(rb_sys.format_creature(r))
                elif rtype == 'table':
                    lines.append(rb_sys.format_table(r))
                elif rtype == 'lore':
                    lines.append(rb_sys.format_lore(r))
                else:
                    lines.append(f"**{r.get('id', 'Unknown')}** ({rtype})")
                lines.append("")  # blank line between entries

            return "\n".join(lines) + suppress_note

        if action == "get":
            if not id:
                return "Error: get requires id parameter"

            # Try each type
            if id.startswith('rule-'):
                entry = rb_sys.get_rule(id)
                if entry:
                    return rb_sys.format_rule(entry)
            elif id.startswith('creature-'):
                entry = rb_sys.get_creature(id)
                if entry:
                    return rb_sys.format_creature(entry)
            elif id.startswith('table-'):
                entry = rb_sys.get_table(id)
                if entry:
                    return rb_sys.format_table(entry, roll_result=roll)
            elif id.startswith('gift-'):
                entry = rb_sys.get_gift(id)
                if entry:
                    return rb_sys.format_rule(entry)
            elif id.startswith('lore-'):
                entry = rb_sys.get_lore(id)
                if entry:
                    return rb_sys.format_lore(entry)
            else:
                # Try all types
                entry = (rb_sys.get_rule(id) or rb_sys.get_creature(id) or
                         rb_sys.get_table(id) or rb_sys.get_gift(id) or
                         rb_sys.get_lore(id))
                if entry:
                    if 'rule' in entry:
                        return rb_sys.format_rule(entry)
                    elif 'stats' in entry:
                        return rb_sys.format_creature(entry)
                    elif 'text' in entry:
                        return rb_sys.format_lore(entry)
                    else:
                        return rb_sys.format_table(entry, roll_result=roll)

            return f"Entry not found: {id}"

        return f"Unknown action: {action}. Use: search, get, stats, reload, turn, session_reset"

    return rb_sys
