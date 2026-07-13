"""Social play-loop: PARLEY parser, negotiation state, parley tool. Leaf module — NEVER imports server."""

import json
import re
import time
from pathlib import Path
from typing import Optional

import push_format as _pf
import site_markers as _sm

NEEDLE_BANDS = ["hostile", "wary", "neutral", "warm", "allied"]
GENERIC_LADDER = ["contact", "assessment", "exchange", "trust", "accord"]

# Task 2 item 4: DM-only marker appended to the parley ride-along block that
# check_canon surfaces. An open parley (with gated reveals) is DM-only meta the
# player must not see, so it carries the exact tokens hooks/spoiler_check.py
# watches for ("SECRETS" + "do not reveal") — twin of server._CULTIVATED_SECRET_MARKER.
_CULTIVATED_SECRET_MARKER = "🔒 SECRETS — DM only; do not reveal directly."

_CHECK_RE = re.compile(r"([A-Z]+)\s+DC\s+(\d+)")
# The em-dash "—" (not a hyphen) is load-bearing here: the machine-authored PARLEY
# format contract uses "N. name — description", never "-". Don't loosen this.
_TIER_LINE_RE = re.compile(
    r"^\d+\.\s*(?P<name>[^—]+?)\s*—\s*(?P<desc>[^|]+?)(?:\|\s*check:\s*(?P<check>.+))?$"
)
_BEAT_LINE_RE = re.compile(r"^-\s*(?P<label>[^|]+?)(?:\|\s*check:\s*(?P<check>.+))?$")
_REVEAL_LINE_RE = re.compile(r"^-\s*(?P<label>[^|]+?)\s*\|\s*gate:\s*(?P<gate>.+)$")
_TEXTURE_ROW_RE = re.compile(r"^\|\s*(?P<roll>\d+)\s*\|\s*(?P<text>.+?)\s*\|$")


def _parse_check(text: str) -> Optional[dict]:
    """Parse a 'STAT DC n' clause into {"stat": str, "dc": int}, or None if it doesn't match."""
    m = _CHECK_RE.search(text.strip())
    if not m:
        return None
    return {"stat": m.group(1), "dc": int(m.group(2))}


def _bold_field(line: str) -> str:
    """Extract the value from a '**Label:** value' line.

    Strips the bold markers left behind by splitting on the first ':' (the closing
    '**' lands on the value side) and any trailing inline HTML comment, e.g.
    '**Needle:** wary            <!-- hostile | wary | neutral | warm | allied -->'
    -> 'wary'.
    """
    value = line.split(":", 1)[1].strip().lstrip("*").strip()
    return re.sub(r"<!--.*?-->\s*$", "", value).strip()


def parse_gate(expr: str) -> dict:
    """Parse a gate expression like 'tier>=trust OR EGO DC 18' into {"tier": ..., "check": ...}."""
    tier = None
    check = None
    for clause in expr.split(" OR "):
        clause = clause.strip()
        tier_match = re.match(r"tier\s*>=\s*(\w+)", clause)
        if tier_match:
            tier = tier_match.group(1)
            continue
        check_match = _parse_check(clause)
        if check_match:
            check = check_match
    return {"tier": tier, "check": check}


def parse_parley_block(text: str) -> Optional[dict]:
    """Parse a '## PARLEY: <slug>' block (through the next level-2 heading or EOF)."""
    block_match = re.search(
        r"^##\s*PARLEY:\s*(?P<slug>\S+)\s*\n(?P<body>.*?)(?=\n##\s+|\Z)",
        text,
        re.DOTALL | re.MULTILINE,
    )
    if not block_match:
        return None

    slug = block_match.group("slug")
    body = block_match.group("body")

    stakes = ""
    failure_state = ""
    tiers: list = []
    parties: list = []
    reveals: list = []
    texture: list = []

    section = None
    current_tier = None
    current_npc = None

    for raw_line in body.split("\n"):
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("### "):
            section = line[4:].strip()
            # New section closes any in-progress tier/NPC block.
            current_tier = None
            current_npc = None
            continue

        if line.startswith("#### NPC:"):
            current_npc = {
                "name": line.split(":", 1)[1].strip(),
                "needle": "",
                "lever": "",
                "pressure": "",
                "victory": "",
            }
            parties.append(current_npc)
            continue

        if line.startswith("**Stakes:**"):
            stakes = _bold_field(line)
            continue
        if line.startswith("**Failure state:**"):
            failure_state = _bold_field(line)
            continue

        if section == "TIERS":
            tier_match = _TIER_LINE_RE.match(line)
            if tier_match:
                check = _parse_check(tier_match.group("check")) if tier_match.group("check") else None
                current_tier = {
                    "name": tier_match.group("name").strip(),
                    "desc": tier_match.group("desc").strip(),
                    "check": check,
                    "beats": [],
                }
                tiers.append(current_tier)
                continue
            beat_match = _BEAT_LINE_RE.match(line)
            if beat_match and current_tier is not None:
                check = _parse_check(beat_match.group("check")) if beat_match.group("check") else None
                beat_id = f"{current_tier['name']}_b{len(current_tier['beats']) + 1}"
                current_tier["beats"].append(
                    {"id": beat_id, "label": beat_match.group("label").strip(), "check": check}
                )
                continue

        if section == "PARTIES" and current_npc is not None:
            if line.startswith("**Needle:**"):
                current_npc["needle"] = _bold_field(line)
            elif line.startswith("**Lever:**"):
                current_npc["lever"] = _bold_field(line)
            elif line.startswith("**Pressure:**"):
                current_npc["pressure"] = _bold_field(line)
            elif line.startswith("**Victory:**"):
                current_npc["victory"] = _bold_field(line)
            continue

        if section == "REVEALS":
            reveal_match = _REVEAL_LINE_RE.match(line)
            if reveal_match:
                reveals.append(
                    {
                        "label": reveal_match.group("label").strip(),
                        "gate": parse_gate(reveal_match.group("gate").strip()),
                    }
                )
                continue

        if section is not None and section.startswith("TEXTURE"):
            texture_match = _TEXTURE_ROW_RE.match(line)
            if texture_match:
                texture.append(
                    {"roll": int(texture_match.group("roll")), "text": texture_match.group("text").strip()}
                )
                continue

    return {
        "slug": slug,
        "stakes": stakes,
        "failure_state": failure_state,
        "tiers": tiers,
        "parties": parties,
        "reveals": reveals,
        "texture": texture,
    }


_PARLEY_HEADING_RE = re.compile(r"^##\s*PARLEY:", re.MULTILINE)
_LEGACY_VICTORY_RE = re.compile(
    r"^##\s*VICTORY CONDITIONS?\b|\*\*VICTORY CONDITION:\*\*", re.MULTILINE
)


def lint_parley_block(text: str) -> list:
    """Author-time lint for a '## PARLEY:' block. Pure, never raises.

    Silent (returns []) when neither a PARLEY heading nor a legacy
    VICTORY CONDITIONS/CONDITION section is present - most preps have
    neither and shouldn't be flagged.
    """
    warnings: list = []
    has_heading = bool(_PARLEY_HEADING_RE.search(text))
    has_legacy = bool(_LEGACY_VICTORY_RE.search(text))

    if not has_heading:
        if has_legacy:
            warnings.append(
                "PARLEY: legacy negotiation section (VICTORY CONDITIONS/VICTORY "
                "CONDITION) with no ## PARLEY: block — author one"
            )
        return warnings

    try:
        parsed = parse_parley_block(text)
    except Exception:
        parsed = None

    if not parsed or not parsed.get("tiers"):
        warnings.append("PARLEY: malformed block")
        return warnings

    tier_names = [t["name"] for t in parsed["tiers"]]
    seen_tiers = set()
    for name in tier_names:
        if name in seen_tiers:
            warnings.append(f"PARLEY: duplicate tier name {name}")
        seen_tiers.add(name)

    for party in parsed.get("parties", []):
        needle = party.get("needle", "")
        if needle not in NEEDLE_BANDS:
            warnings.append(
                f"PARLEY: invalid needle '{needle}' (use {'|'.join(NEEDLE_BANDS)})"
            )

    tier_set = set(tier_names)
    for reveal in parsed.get("reveals", []):
        gate = reveal.get("gate") or {}
        tier = gate.get("tier")
        if tier and tier not in tier_set:
            warnings.append(f"PARLEY: gate references unknown tier '{tier}'")

    return warnings


# ---------------------------------------------------------------------------
# State store: parleys.json (campaign dir)
# ---------------------------------------------------------------------------

PARLEYS_FILENAME = "parleys.json"


def _parleys_path(campaign_dir) -> Path:
    return Path(campaign_dir) / PARLEYS_FILENAME


def _save_json_atomic(path: Path, data: dict) -> None:
    """Write JSON atomically: full write to a .tmp file, then an atomic replace.

    On Windows the destination can be TRANSIENTLY locked (AV scanner / search
    indexer / an unreleased handle) -> PermissionError. Retry briefly before
    giving up rather than silently losing the save (the `_save_cultivation`
    lesson).
    """
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    for attempt in range(10):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.05)


def load_parleys(campaign_dir) -> dict:
    """Load parleys.json from campaign_dir. Missing file -> {}."""
    path = _parleys_path(campaign_dir)
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_parleys(campaign_dir, data: dict) -> None:
    """Persist the full parleys dict back to campaign_dir/parleys.json (atomic)."""
    _save_json_atomic(_parleys_path(campaign_dir), data)


def _stamp_beats(beats: list) -> list:
    return [{**beat, "satisfied": False, "day": None, "note": None} for beat in beats]


def _tiers_from_parsed(tiers: list, day: int) -> list:
    built = []
    for i, tier in enumerate(tiers):
        new_tier = dict(tier)
        new_tier["reached_day"] = day if i == 0 else None
        new_tier["beats"] = _stamp_beats(tier.get("beats", []))
        built.append(new_tier)
    return built


def _parties_from_parsed(parties: list) -> list:
    built = []
    for party in parties:
        needle = party.get("needle", "")
        if needle not in NEEDLE_BANDS:
            raise ValueError(
                f"invalid needle '{needle}' for party '{party.get('name', '?')}' "
                f"(must be one of {NEEDLE_BANDS})"
            )
        built.append(
            {
                "name": party.get("name", ""),
                "needle": needle,
                "lever": party.get("lever") or "",
                "pressure": party.get("pressure") or "",
                "victory": party.get("victory") or "",
                "history": [],
            }
        )
    return built


def _reveals_from_parsed(reveals: list) -> list:
    return [{**reveal, "unlocked": False, "unlocked_day": None} for reveal in reveals]


def _tiers_inline(day: int) -> list:
    return [
        {"name": name, "desc": "", "check": None, "beats": [], "reached_day": day if i == 0 else None}
        for i, name in enumerate(GENERIC_LADDER)
    ]


def _parties_inline(parties: Optional[list]) -> list:
    built = []
    for party in parties or []:
        needle = party.get("needle", "")
        if needle and needle not in NEEDLE_BANDS:
            raise ValueError(
                f"invalid needle '{needle}' for party '{party.get('name', '?')}' "
                f"(must be one of {NEEDLE_BANDS})"
            )
        built.append(
            {
                "name": party.get("name", ""),
                "needle": needle,
                "lever": party.get("lever", ""),
                "pressure": party.get("pressure", ""),
                "victory": party.get("victory", ""),
                "history": [],
            }
        )
    return built


def open_parley(
    campaign_dir,
    slug: str,
    *,
    title: str,
    day: int,
    site_key: Optional[str] = None,
    parsed: Optional[dict] = None,
    stakes: str = "",
    parties: Optional[list] = None,
) -> dict:
    """Open a new parley into parleys.json, from a parsed PARLEY block or inline.

    Slugs are never reused: closed parleys are kept as permanent history, so a
    collision with either an open or a closed record raises ValueError.
    """
    data = load_parleys(campaign_dir)
    if slug in data:
        if data[slug].get("status") == "closed":
            raise ValueError(
                f"slug '{slug}' belongs to a closed parley (kept as history) — choose a new slug"
            )
        raise ValueError(f"parley '{slug}' is already open")

    if parsed is not None:
        tiers = _tiers_from_parsed(parsed.get("tiers", []), day)
        built_parties = _parties_from_parsed(parsed.get("parties", []))
        reveals = _reveals_from_parsed(parsed.get("reveals", []))
        record_stakes = parsed.get("stakes") or stakes
        record_failure_state = parsed.get("failure_state") or ""
        texture = parsed.get("texture", []) or []
    else:
        tiers = _tiers_inline(day)
        built_parties = _parties_inline(parties)
        reveals = []
        record_stakes = stakes
        record_failure_state = ""
        texture = []

    record = {
        "site_key": site_key,
        "title": title,
        "status": "open",
        "opened_day": day,
        "closed_day": None,
        "outcome": None,
        "stakes": record_stakes,
        "failure_state": record_failure_state,
        "tiers": tiers,
        "current_tier": tiers[0]["name"] if tiers else None,
        "parties": built_parties,
        "reveals": reveals,
        # TEXTURE table (parsed by parse_parley_block) — persisted so a social_site
        # map's encounter die can roll it (map_system._read_social_texture). Was
        # parsed-then-dropped before Task 6; empty for inline/textureless parleys.
        "texture": texture,
        "log": [],
    }

    data[slug] = record
    save_parleys(campaign_dir, data)
    return record


def get_open(campaign_dir) -> dict:
    """Return {slug: parley} for every parley with status == 'open'."""
    data = load_parleys(campaign_dir)
    return {slug: p for slug, p in data.items() if p.get("status") == "open"}


def find_by_npc(campaign_dir, name: str) -> list:
    """Case-insensitive NPC name match across open parleys.

    Returns a list of (slug, parley, party_entry) tuples.
    """
    needle_name = name.strip().lower()
    hits = []
    for slug, parley in get_open(campaign_dir).items():
        for party in parley.get("parties", []):
            if party.get("name", "").strip().lower() == needle_name:
                hits.append((slug, parley, party))
    return hits


def parley_blocks_for_npc(campaign_dir, name: str) -> list:
    """Ride-along blocks for check_canon: one compact PARLEY line per OPEN parley
    that names this NPC, ending with a pushed status call so the DM follows the
    trail instead of knowing the procedure.

    Labels/counts ONLY — the block carries the current tier, the named NPC's
    needle band, the next unsatisfied beat's label at that tier (or '—'), and the
    COUNT of still-gated reveals. It never leaks reveal content (there is none in
    state; keep it that way). Zero-safe -> [].
    """
    out = []
    for slug, parley, party in find_by_npc(campaign_dir, name):
        current_tier_name = parley.get("current_tier")
        current_tier = next(
            (t for t in parley.get("tiers", []) if t.get("name") == current_tier_name),
            None,
        )
        next_beat = "—"
        if current_tier is not None:
            for beat in current_tier.get("beats", []):
                if not beat.get("satisfied"):
                    next_beat = beat.get("label", "—")
                    break
        gated = sum(1 for r in parley.get("reveals", []) if not r.get("unlocked"))
        block = (
            f"🤝 PARLEY {parley.get('title', slug)} — tier: {current_tier_name}; "
            f"{party.get('name', name)} needle: {party.get('needle', '?')}; "
            f"next beat: {next_beat}; gated reveals: {gated}"
        )
        block += "\n" + _pf.next_block(
            _pf.push_call("parley", action="status", slug=slug),
            label="orient",
        )
        block += "\n" + _CULTIVATED_SECRET_MARKER
        out.append(block)
    return out


def parley_briefing_lines(campaign_dir) -> list:
    """Session-start read-back: a '🤝 OPEN PARLEYS' header + one line per OPEN
    parley (title, current tier, party needles, opened day), plus a final
    pushed `parley(action="status", slug=...)` line for the OLDEST open parley
    (lowest opened_day) so the DM follows the trail. Zero-safe -> []."""
    open_parleys = get_open(campaign_dir)
    if not open_parleys:
        return []
    items = sorted(open_parleys.items(), key=lambda kv: kv[1].get("opened_day", 0))
    out = ["🤝 OPEN PARLEYS"]
    for slug, parley in items:
        parties = ", ".join(
            f"{p.get('name', '?')}:{p.get('needle', '?')}"
            for p in parley.get("parties", [])
        )
        out.append(
            f"{parley.get('title', slug)} — tier: {parley.get('current_tier')}; "
            f"parties: {parties}; opened day {parley.get('opened_day', '?')}"
        )
    oldest_slug = items[0][0]
    out.append(
        _pf.next_block(
            _pf.push_call("parley", action="status", slug=oldest_slug),
            label="orient",
        )
    )
    return out


# ---------------------------------------------------------------------------
# Tool: parley
# ---------------------------------------------------------------------------

_ACTIONS = ("open", "status", "list", "move", "tier", "needle", "reveal", "close")


def _err(msg: str) -> str:
    """Every error/ambiguity path ends with a pushed orientation call (owner ruling) —
    there's always an open-parleys list to reorient from, even when the specific slug/site/
    action given was bad."""
    return msg + "\n" + _pf.next_block(_pf.push_call("parley", action="list"), label="orient")


def _resolve_prep_path(campaign_dir: Path, prep: Optional[str], site: Optional[str]):
    """Resolve prep=/site= to a concrete file path. prep is a literal path; site is a key
    looked up via site_markers.build_site_index. Returns (path_or_None, error_message).
    """
    if prep:
        path = Path(prep)
        if not path.is_absolute():
            path = Path(campaign_dir) / path
        return path, None
    if site:
        rec = _sm.build_site_index(campaign_dir).get(site)
        if not rec or not rec.get("prep_file"):
            return None, f"Error: unknown site key '{site}'"
        return Path(campaign_dir) / rec["prep_file"], None
    return None, None


def _find_open_slug(campaign_dir, slug: Optional[str]) -> tuple:
    """Resolve the slug to operate on: explicit slug wins; else infer a single open parley.

    Returns (resolved_slug, error_message). error_message is None on success.
    """
    if slug:
        return slug, None
    open_parleys = get_open(campaign_dir)
    if len(open_parleys) == 1:
        return next(iter(open_parleys)), None
    if not open_parleys:
        return None, "No open parleys."
    return None, "Error: slug required (multiple open parleys: " + ", ".join(sorted(open_parleys)) + ")"


def _do_open(campaign_dir, get_day, *, slug, prep, site, title, stakes, parties) -> str:
    if not slug:
        return _err("Error: open requires slug")

    prep_path, error = _resolve_prep_path(campaign_dir, prep, site)
    if error:
        return _err(error)

    parsed = None
    if prep_path is not None:
        if not prep_path.exists():
            return _err(f"Error: prep file not found: {prep_path}")
        with open(prep_path, "r", encoding="utf-8") as f:
            text = f.read()
        parsed = parse_parley_block(text)
        if parsed is None:
            return _err(f"Error: no '## PARLEY: <slug>' block found in {prep_path}")
    elif not title:
        return _err("Error: open requires prep=/site= (a PARLEY block to parse) or title= (inline parley)")

    record_title = title or (parsed.get("slug") if parsed else slug)

    try:
        record = open_parley(
            campaign_dir,
            slug,
            title=record_title,
            day=get_day(),
            site_key=site,
            parsed=parsed,
            stakes=stakes or "",
            parties=parties,
        )
    except ValueError as exc:
        return _err(f"Error: {exc}")

    tier_names = " -> ".join(t["name"] for t in record["tiers"])
    lines = [
        f"Opened parley '{slug}' ({record['title']}) at tier '{record['current_tier']}'.",
        "Ladder: " + tier_names if tier_names else "Ladder: (inline, no tiers parsed)",
    ]
    body = "\n".join(lines)
    return body + "\n" + _pf.next_block(_pf.push_call("parley", action="status", slug=slug), label="orient")


def _do_status(campaign_dir, *, slug) -> str:
    resolved_slug, error = _find_open_slug(campaign_dir, slug)
    if error:
        return _err(error)

    data = load_parleys(campaign_dir)
    record = data.get(resolved_slug)
    if not record or record.get("status") != "open":
        return _err(f"Error: no open parley '{resolved_slug}'")

    current_tier_name = record.get("current_tier")
    current_tier = next((t for t in record["tiers"] if t["name"] == current_tier_name), None)

    lines = [f"Parley '{resolved_slug}' ({record['title']}) — tier: {current_tier_name}"]

    if current_tier is not None:
        unsatisfied = [b["label"] for b in current_tier.get("beats", []) if not b.get("satisfied")]
        lines.append("Unsatisfied beats: " + ("; ".join(unsatisfied) if unsatisfied else "none"))

    for party in record.get("parties", []):
        lines.append(f"  {party['name']}: needle={party['needle']}")

    for reveal in record.get("reveals", []):
        status_word = "UNLOCKED" if reveal.get("unlocked") else "GATED"
        lines.append(f"  reveal '{reveal['label']}': {status_word}")

    body = "\n".join(lines)
    return body + "\n" + _pf.next_block(
        _pf.push_call("parley", action="move", slug=resolved_slug, note="<what happened>"),
        label="advance",
    )


def _shift_needle(record: dict, *, npc: str, to: str, reason: Optional[str], day: int) -> Optional[str]:
    """Apply a needle shift to `record` in place. Returns an error message, or None on success.

    Shared by the standalone `needle` action and `move`'s optional inline shift — same
    validation either way (unknown NPC / invalid band).
    """
    party = next(
        (p for p in record.get("parties", []) if p.get("name", "").strip().lower() == (npc or "").strip().lower()),
        None,
    )
    if party is None:
        names = ", ".join(p["name"] for p in record.get("parties", [])) or "(none)"
        return f"Error: unknown NPC '{npc}' (parties: {names})"
    if to not in NEEDLE_BANDS:
        return f"Error: invalid needle band '{to}' (must be one of {NEEDLE_BANDS})"

    from_band = party["needle"]
    party["needle"] = to
    party["history"].append({"day": day, "from": from_band, "to": to, "note": reason or ""})
    return None


def _stringify_gate(gate: dict) -> str:
    """Render a gate dict as its source-expression shape, e.g. 'tier>=accord OR EGO DC 18'.

    This is the gate CONDITION, not the reveal's content — there is no secret text in
    state to leak, so it's always safe to print.
    """
    clauses = []
    if gate.get("tier"):
        clauses.append(f"tier>={gate['tier']}")
    check = gate.get("check")
    if check:
        clauses.append(f"{check['stat']} DC {check['dc']}")
    return " OR ".join(clauses) if clauses else "(no gate)"


def _do_move(campaign_dir, get_day, *, slug, note, beat, npc, needle) -> str:
    resolved_slug, error = _find_open_slug(campaign_dir, slug)
    if error:
        return _err(error)
    if not note:
        return _err("Error: move requires note")

    data = load_parleys(campaign_dir)
    record = data.get(resolved_slug)
    if not record or record.get("status") != "open":
        return _err(f"Error: no open parley '{resolved_slug}'")

    day = get_day()
    record["log"].append({"day": day, "entry": note})

    lines = [f"Parley '{resolved_slug}': {note}"]

    beat_obj = None
    if beat:
        beat_obj = next(
            (b for tier in record["tiers"] for b in tier["beats"] if b["id"] == beat),
            None,
        )
        if beat_obj is None:
            return _err(f"Error: unknown beat '{beat}'")
        if not beat_obj.get("satisfied"):
            beat_obj["satisfied"] = True
            beat_obj["day"] = day
            beat_obj["note"] = note
            lines.append(f"Beat satisfied: {beat_obj['label']}")

    if bool(npc) != bool(needle):
        return _err("Error: move's needle shift requires both npc= and needle=")
    if npc and needle:
        shift_error = _shift_needle(record, npc=npc, to=needle, reason=note, day=day)
        if shift_error:
            return _err(shift_error)
        lines.append(f"{npc}: needle -> {needle}")

    current_tier = next((t for t in record["tiers"] if t["name"] == record.get("current_tier")), None)
    check = None
    if beat_obj and beat_obj.get("check"):
        check = beat_obj["check"]
    elif current_tier and current_tier.get("check"):
        check = current_tier["check"]

    data[resolved_slug] = record
    save_parleys(campaign_dir, data)

    body = "\n".join(lines)
    if check:
        # Ruling: "push the roll, DM rules" — the engine never resolves a check itself.
        push = _pf.next_block(
            _pf.push_call("roll", action="check", ability=check["stat"], dc=check["dc"], character="<party face>"),
            label="resolve",
        )
    else:
        push = _pf.next_block(_pf.push_call("parley", action="status", slug=resolved_slug), label="orient")
    return body + "\n" + push


def _do_tier(campaign_dir, get_day, *, slug, to, reason) -> str:
    resolved_slug, error = _find_open_slug(campaign_dir, slug)
    if error:
        return _err(error)
    if not to:
        return _err("Error: tier requires to")
    if not reason:
        return _err("Error: tier change requires reason")

    data = load_parleys(campaign_dir)
    record = data.get(resolved_slug)
    if not record or record.get("status") != "open":
        return _err(f"Error: no open parley '{resolved_slug}'")

    tier_names = [t["name"] for t in record["tiers"]]
    if to not in tier_names:
        return _err(f"Error: unknown tier '{to}' (ladder: {', '.join(tier_names)})")

    to_index = tier_names.index(to)
    day = get_day()

    unsatisfied = [
        b["label"]
        for tier in record["tiers"][: to_index + 1]
        for b in tier["beats"]
        if not b.get("satisfied")
    ]

    record["current_tier"] = to
    tier_obj = record["tiers"][to_index]
    if tier_obj.get("reached_day") is None:
        tier_obj["reached_day"] = day

    record["log"].append({"day": day, "entry": f"Tier -> {to} ({reason})"})

    data[resolved_slug] = record
    save_parleys(campaign_dir, data)

    lines = []
    if unsatisfied:
        lines.append("⚠ WARN — unsatisfied checked beats: " + "; ".join(unsatisfied))
    lines.append(f"Parley '{resolved_slug}' tier -> {to}.")
    body = "\n".join(lines)
    return body + "\n" + _pf.next_block(_pf.push_call("parley", action="status", slug=resolved_slug), label="orient")


def _do_needle(campaign_dir, get_day, *, slug, npc, to, reason) -> str:
    resolved_slug, error = _find_open_slug(campaign_dir, slug)
    if error:
        return _err(error)
    if not npc or not to:
        return _err("Error: needle requires npc and to")

    data = load_parleys(campaign_dir)
    record = data.get(resolved_slug)
    if not record or record.get("status") != "open":
        return _err(f"Error: no open parley '{resolved_slug}'")

    day = get_day()
    shift_error = _shift_needle(record, npc=npc, to=to, reason=reason, day=day)
    if shift_error:
        return _err(shift_error)

    data[resolved_slug] = record
    save_parleys(campaign_dir, data)

    body = f"{npc}: needle -> {to}"
    return body + "\n" + _pf.next_block(_pf.push_call("parley", action="status", slug=resolved_slug), label="orient")


def _do_reveal(campaign_dir, get_day, *, slug, label, reason) -> str:
    resolved_slug, error = _find_open_slug(campaign_dir, slug)
    if error:
        return _err(error)
    if not label:
        return _err("Error: reveal requires label")

    data = load_parleys(campaign_dir)
    record = data.get(resolved_slug)
    if not record or record.get("status") != "open":
        return _err(f"Error: no open parley '{resolved_slug}'")

    reveal = next((r for r in record.get("reveals", []) if r["label"] == label), None)
    if reveal is None:
        names = ", ".join(r["label"] for r in record.get("reveals", [])) or "(none)"
        return _err(f"Error: unknown reveal '{label}' (reveals: {names})")

    day = get_day()
    tier_names = [t["name"] for t in record["tiers"]]
    current_index = tier_names.index(record["current_tier"]) if record.get("current_tier") in tier_names else -1
    gate = reveal["gate"]
    gate_tier_index = tier_names.index(gate["tier"]) if gate.get("tier") in tier_names else None
    tier_met = gate_tier_index is not None and current_index >= gate_tier_index

    orient_push = _pf.next_block(_pf.push_call("parley", action="status", slug=resolved_slug), label="orient")

    if tier_met:
        reveal["unlocked"] = True
        reveal["unlocked_day"] = day
        data[resolved_slug] = record
        save_parleys(campaign_dir, data)
        return f"Reveal '{label}': UNLOCKED (tier gate met).\n" + orient_push

    if reason:
        reveal["unlocked"] = True
        reveal["unlocked_day"] = day
        record["log"].append({"day": day, "entry": f"Reveal '{label}' override: {reason}"})
        data[resolved_slug] = record
        save_parleys(campaign_dir, data)
        return f"Reveal '{label}': UNLOCKED (override).\n" + orient_push

    body = f"Reveal '{label}': GATED: requires {_stringify_gate(gate)}"
    if gate.get("check"):
        # Ruling: "push the roll, DM rules" — never resolves the check itself.
        return body + "\n" + _pf.next_block(
            _pf.push_call("roll", action="check", ability=gate["check"]["stat"], dc=gate["check"]["dc"], character="<party face>"),
            label="resolve gate check",
        )
    return body + "\n" + orient_push


def _do_close(campaign_dir, get_day, *, slug, outcome, note) -> str:
    resolved_slug, error = _find_open_slug(campaign_dir, slug)
    if error:
        return _err(error)
    if not outcome:
        return _err("Error: close requires outcome")

    data = load_parleys(campaign_dir)
    record = data.get(resolved_slug)
    if not record or record.get("status") != "open":
        return _err(f"Error: no open parley '{resolved_slug}'")

    day = get_day()
    record["status"] = "closed"
    record["closed_day"] = day
    record["outcome"] = outcome
    entry = f"Closed: {outcome}" + (f" — {note}" if note else "")
    record["log"].append({"day": day, "entry": entry})

    data[resolved_slug] = record
    save_parleys(campaign_dir, data)

    site_key_or_title = record.get("site_key") or record["title"]
    summary = f"Parley '{record['title']}' closed: {outcome}" + (f" — {note}" if note else "")

    body = f"Parley '{resolved_slug}' closed — outcome: {outcome}."
    return body + "\n" + _pf.next_block(
        _pf.push_call(
            "update_location_progress",
            location=site_key_or_title,
            day=day,
            summary=summary,
            status=_pf.raw(json.dumps([f"parley_{resolved_slug}: {outcome.upper()}"])),
        ),
        _pf.push_call(
            "lorebook",
            action="add",
            keywords=record["title"],
            category="scenes",
            status="ESTABLISHED",
            context=summary,
        ),
        label="crystallize outcome",
    )


def _do_list(campaign_dir) -> str:
    open_parleys = get_open(campaign_dir)
    if not open_parleys:
        # Owner ruling: this IS the terminal orientation answer for `list` — the engine
        # never proposes opening a negotiation (that's DM judgment), so no push here.
        return "No open parleys."

    lines = ["Open parleys:"]
    for slug, record in sorted(open_parleys.items()):
        lines.append(f"  {slug}: {record['title']} — tier {record.get('current_tier')}")
    return "\n".join(lines)


def register_social_tools(mcp, campaign_dir, *, get_day=None, get_tool_tags=None) -> None:
    """Register the parley tool (negotiation state machine) with the MCP server."""
    campaign_dir = Path(campaign_dir)
    get_day = get_day or (lambda: 0)

    tool_kwargs = {"annotations": {"readOnlyHint": False, "idempotentHint": False}}
    if get_tool_tags is not None:
        tool_kwargs["tags"] = get_tool_tags("parley")

    @mcp.tool(**tool_kwargs)
    def parley(
        action: str,
        slug: str = None,
        prep: str = None,
        site: str = None,
        title: str = None,
        stakes: str = None,
        parties: list = None,
        note: str = None,
        beat: str = None,
        npc: str = None,
        needle: str = None,
        to: str = None,
        label: str = None,
        reason: str = None,
        outcome: str = None,
    ) -> str:
        """Reach for this WHEN a negotiation, audience, or diplomatic scene needs mechanical structure.

        Triggers: a negotiation/audience/diplomatic scene begins → parley(action="open");
        mid-negotiation orientation → parley(action="status").

        Actions:
            open: Open a new parley from a prep file (slug, prep=<path>|site=<key>, title?) or
                inline (slug, title, stakes?, parties?)
            status: Current tier, unsatisfied beats, party needles, reveal gate labels
                (slug? — infers the single open parley when omitted)
            list: List every open parley, one line each
            move: Log a beat of dialogue/action (slug?, note, beat=<id>?, npc=<name>?, needle=<band>?)
                — marks a named beat satisfied; pushes the roll instead of just logging when the
                beat or the current tier carries a check (never resolves it — DM rules)
            tier: Advance/change the negotiation tier (slug?, to=<tier>, reason=<why>) — reason
                required; warns (never blocks) if unsatisfied beats remain in tiers up to `to`
            needle: Shift an NPC's disposition (slug?, npc=<name>, to=<band>, reason=<why>?)
                — stamps the party's history
            reveal: Attempt to unlock a gated reveal (slug?, label=<id>, reason=<override>?) —
                gate met (or reason given) unlocks; otherwise GATED + pushes the gate's check
                roll if it has one. Never prints reveal content, only labels/gate conditions.
            close: Close the parley (slug?, outcome=<result>, note=<summary>?) — pushes the
                crystallization trail (update_location_progress + lorebook)

        Examples:
            parley(action="open", slug="outer_reach_accord", prep="X_PREP.md", title="Outer Reach Accord")
            parley(action="move", slug="outer_reach_accord", note="The envoy makes their case", beat="assessment_b1")
            parley(action="tier", slug="outer_reach_accord", to="accord", reason="alliance sealed")
            parley(action="status", slug="outer_reach_accord")
            parley(action="list")
        """
        action = (action or "").lower().strip()

        if action == "open":
            return _do_open(
                campaign_dir, get_day,
                slug=slug, prep=prep, site=site, title=title, stakes=stakes, parties=parties,
            )
        if action == "status":
            return _do_status(campaign_dir, slug=slug)
        if action == "list":
            return _do_list(campaign_dir)
        if action == "move":
            return _do_move(campaign_dir, get_day, slug=slug, note=note, beat=beat, npc=npc, needle=needle)
        if action == "tier":
            return _do_tier(campaign_dir, get_day, slug=slug, to=to, reason=reason)
        if action == "needle":
            return _do_needle(campaign_dir, get_day, slug=slug, npc=npc, to=to, reason=reason)
        if action == "reveal":
            return _do_reveal(campaign_dir, get_day, slug=slug, label=label, reason=reason)
        if action == "close":
            return _do_close(campaign_dir, get_day, slug=slug, outcome=outcome, note=note)

        return _err(f"Unknown action '{action}'. Valid actions: " + " | ".join(_ACTIONS))
