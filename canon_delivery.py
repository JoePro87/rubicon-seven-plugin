"""Element-level delta delivery for check_canon.

Pure logic (no I/O, no MCP imports) so it can be unit-tested in isolation.
Given a list of keyed context elements and the current hook_state, returns the
text to actually deliver (full content for new/changed/stale elements, compact
pointers for elements already delivered this session) plus the updated state.

Element tuple: (section: str, key: str | None, content: str)
  - key is None  -> always fresh (never deduplicated; e.g. live scene state)
  - key is a str -> tracked across the session under hook_state['canon_delivered']
"""

import hashlib

# Sections whose folded pointers carry a self-healing recovery call. These are
# ground-truth canon facts: if a compaction reset is ever missed and the full
# text scrolls away, the pointer still gives the DM a one-call recovery path.
RECOVERABLE_SECTIONS = frozenset({"CONTEXT"})


def _hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def filter_elements_with_stats(elements, hook_state, backstop_turns: int = 30):
    """Filter context elements for delta delivery, returning delivery stats.

    Returns (output_str, new_hook_state, stats). new/changed/stale keyed
    elements and all None-key elements ship full; unchanged keyed elements
    collapse into per-section pointer lines. A key repeated within one call
    keeps its first occurrence (dedupe-in-call; duplicates are not counted).

    stats = {"fresh": <keyed shipped full>, "pointers": <keyed deduped>,
             "always_fresh": <None-key elements>}.
    """
    # Coerce missing/None to 0: state files can carry an explicit null
    # last_canon_turn (e.g. left by tests or older code). Comparing int < None
    # raises, which would fail-open to full delivery forever — defend here.
    current_turn = hook_state.get("turn_count", 0) or 0
    last_turn = hook_state.get("last_canon_turn", 0) or 0
    compacted = current_turn < last_turn
    delivered = {} if compacted else dict(hook_state.get("canon_delivered", {}))

    fresh_parts = []
    pointers = {}  # section -> list[(display_key, delivered_turn)]
    processed = set()  # keys seen THIS call (dedupe within a single call)
    stats = {"fresh": 0, "pointers": 0, "always_fresh": 0}

    for section, key, content in elements:
        if key is None:
            fresh_parts.append(content)
            stats["always_fresh"] += 1
            continue
        if key in processed:
            continue  # duplicate within this call -> keep the first occurrence
        processed.add(key)
        h = _hash(content)
        rec = delivered.get(key)
        stale = rec is not None and (current_turn - rec.get("t", 0)) >= backstop_turns
        if rec is None or rec.get("h") != h or stale:
            fresh_parts.append(content)
            delivered[key] = {"h": h, "t": current_turn}
            stats["fresh"] += 1
        else:
            display = key.split(":", 1)[1] if ":" in key else key
            pointers.setdefault(section, []).append((display, rec.get("t", 0)))
            stats["pointers"] += 1

    out = [p for p in fresh_parts if p]
    if pointers:
        out.append("**[IN CONTEXT — already delivered this session]**")
        for section, items in pointers.items():
            if section in RECOVERABLE_SECTIONS:
                # display keys are lorebook first-keywords (clean tokens — no commas/parens), so inlining raw is safe
                joined = ", ".join(f"{d} ✓T{t} ↻ lorebook(view, {d})" for d, t in items)
            else:
                joined = ", ".join(f"{d} ✓T{t}" for d, t in items)
            out.append(f"{section}: {joined}")

    new_state = dict(hook_state)
    new_state["canon_delivered"] = delivered
    new_state["last_canon_turn"] = current_turn
    return "\n\n".join(out), new_state, stats


def filter_elements(elements, hook_state, backstop_turns: int = 30):
    """Return (output_str, new_hook_state). Thin wrapper over
    filter_elements_with_stats; discards the stats dict."""
    out, state, _stats = filter_elements_with_stats(elements, hook_state, backstop_turns)
    return out, state
