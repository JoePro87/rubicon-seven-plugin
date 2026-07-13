"""Book-lore base layer for check_canon — shipped Crimson Hound world facts.

LEAF module: never imports server (or any engine module). server.check_canon
loads data/rules/rulebook/lore_additions.json (mtime-cached) and passes the
raw dict in; this module converts entries to the campaign-lorebook shape and
keyword-matches them. Subject-coverage suppression makes campaign canon win:
a book entry sharing ANY keyword with the campaign lorebook never matches.

All output is DM-facing RAG. Fail-open by construction: any malformed input
yields no matches, and check_canon behaves as if the layer doesn't exist.
"""
import re


def book_entries(raw):
    """Convert lore_additions entries into the lorebook entry shape.

    Entries flagged "scene_inject": false (referee advice, not world facts)
    are skipped here but still served by the rulebook tool unchanged.
    """
    out = []
    try:
        entries = raw.get("entries", [])
    except Exception:
        return []
    if not isinstance(entries, list):
        return []
    for e in entries:
        try:
            if not isinstance(e, dict):
                continue
            if e.get("scene_inject", True) is False:
                continue
            kws = [k for k in e.get("keywords", [])
                   if isinstance(k, str) and k.strip()]
            text = e.get("text", "")
            if not kws or not isinstance(text, str) or not text:
                continue
            out.append({
                "keywords": kws,
                "category": "book",
                "status": "CH",
                "context": text,
                "short_context": text if len(text) <= 500 else "",
            })
        except Exception:
            continue
    return out


def match_book_entries(entries, input_lower, campaign_keywords, broad_kw):
    """Word-boundary keyword match, same semantics as the campaign scan.

    Returns [(entry, triggered_kw, is_specific), ...] — the tuple shape
    check_canon's campaign `matches` list uses, so the render pipeline
    consumes both without translation.
    """
    matches = []
    if not isinstance(entries, list):
        return []
    for entry in entries:
        try:
            kws = [k.lower().strip() for k in entry.get("keywords", [])]
            if any(k in campaign_keywords for k in kws):
                continue  # campaign owns this subject — book stays silent
            spec_kw = None
            broad = None
            for kw in kws:
                if not kw:
                    continue
                if re.search(rf'\b{re.escape(kw)}\b', input_lower):
                    if kw in broad_kw:
                        broad = broad or kw
                        continue
                    spec_kw = kw
                    break
            if spec_kw:
                matches.append((entry, spec_kw, True))
            elif broad:
                matches.append((entry, broad, False))
        except Exception:
            continue
    return matches
