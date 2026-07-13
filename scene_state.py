"""Pure logic for splitting check_canon scene state into volatile (always-fresh)
and foldable (keyed, delta-delivered) blocks. No I/O, no MCP imports — unit-testable.

Foldable scene families (static-ish, high reward): ARC, EMOTIONAL STATE.
NEVER foldable here: day/bell/location, last-speaker/beats/mood/next (volatile),
and classified secrets/DM-knowledge (kept always-fresh by the caller).
"""


def scene_dedup_elements(arc=None, emotional_state=None):
    """Return keyed delta-delivery elements for the foldable scene blocks.

    arc: raw ARC line text (already '**ARC:** ...') or None.
    emotional_state: raw emotional-state table body or None.
    Returns list[(section, key, content)]; empty list if both are None or
    whitespace-only.
    """
    elements = []
    if arc and arc.strip():
        elements.append(("ARC", "scene:arc", arc.strip()))
    if emotional_state and emotional_state.strip():
        content = "**EMOTIONAL STATE:**\n" + emotional_state.strip()
        elements.append(("EMOTIONAL STATE", "scene:emotional_state", content))
    return elements


def context_dedup_elements(rendered_matches):
    """Convert rendered lorebook CONTEXT matches into per-keyword keyed elements.

    rendered_matches: list[(entry_key: str, formatted_line: str)] where entry_key
      is the entry's display key (its first keyword) and formatted_line is the
      already-rendered '[CAT] **kw** (status): context' string.
    Lines that share a keyword are GROUPED into a single element (first-seen order;
    exactly-identical lines collapsed) so the downstream in-call key-dedup never
    drops a distinct bio — this stays a presentation-only fold, never content loss.
    Returns list[("CONTEXT", "lore:<keyword>", joined_lines)], one per unique keyword.
    Section "CONTEXT" triggers the self-healing recovery pointers.
    """
    grouped = {}   # key -> list[str] (distinct lines, first-seen order)
    order = []     # preserve first-seen keyword order
    for entry_key, line in rendered_matches:
        if entry_key and entry_key.strip() and line and line.strip():
            k = entry_key.strip()
            if k not in grouped:
                grouped[k] = []
                order.append(k)
            if line not in grouped[k]:   # collapse only exactly-identical lines
                grouped[k].append(line)
    return [("CONTEXT", f"lore:{k}", "\n".join(grouped[k])) for k in order]
