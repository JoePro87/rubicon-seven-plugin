#!/usr/bin/env python3
"""Deterministic bestiary rebuild from VERIFIED Crimson Hound extraction.

Reads:  rulebook/_ch_extract/*.json   (book-sourced records, no-invention creed)
        rulebook/bestiary.json        (provisional/suspect; source of campaign metadata)
Writes: rulebook/bestiary.rebuilt.json + rulebook/_rebuild_changelog.md

Rules:
- Book record is ground truth for: type, level, hp, av, morale, encountered,
  attacks, special, resistances, flags. Conditional AV -> primary int + combat_note.
- Our entry is source of: id, keywords, categories, contexts, lore_refs (campaign metadata).
- Resistances: start from book structured fields, then PATCH prose-vulnerability gaps
  found in the record's resistances.notes (the extraction occasionally stated a
  vulnerability/immunity in prose but left the structured bucket empty).
- Explicit decisions (dedup, keying, human-ruling holds) live in tables below.
This script makes NO network/PDF calls; it is fully reproducible.
"""
import json, re, glob, os

ROOT = os.path.dirname(os.path.abspath(__file__))
EXTRACT = sorted(glob.glob(os.path.join(ROOT, "_ch_extract", "*.json")))
BESTIARY = os.path.join(ROOT, "bestiary.json")
OUT = os.path.join(ROOT, "bestiary.rebuilt.json")
CHANGELOG = os.path.join(ROOT, "_rebuild_changelog.md")

DAMAGE_VOCAB = {"kinetic","bludgeoning","slashing","piercing","fire","cold","electrical",
    "acid","poison","radiation","beam","fungicide","hypergeometric","suffocation",
    "fungal_spores","extreme_temperature"}

STOP = {"the", "of", "a", "an"}
def norm(s):
    """Normalize for matching: lowercase, drop apostrophe-s, stopwords, all non-alnum.
    Appositives are KEPT (so 'Quantum Daemon, Lesser' != 'Quantum Daemon, Greater');
    short-vs-long names are reconciled by prefix matching, not by stripping."""
    s = (s or "").lower()
    s = re.sub(r"'s\b", "", s)                 # consul's -> consul
    s = re.sub(r"[^a-z0-9 ]", " ", s)          # commas/hyphens/apostrophes -> space
    toks = [t for t in s.split() if t and t not in STOP]
    return "".join(toks)

def slugify(name):
    return "creature-" + re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")

# ---- Explicit decisions (from BESTIARY_REBUILD_DIFF_2026-06-07.md) ----
# Dedup: keep canonical id, drop the duplicate id (its keywords get merged in).
DEDUP_DROP = {
    "creature-child-darkling-sun",      # keep creature-child-of-the-darkling-sun
    "creature-master-eyeless-wisdom",   # keep creature-master-of-eyeless-wisdom
    "creature-seeker-eyeless-wisdom",   # keep creature-seeker-of-eyeless-wisdom
    "creature-bacteria-gestalt-colony", # keep creature-bacterial-gestalt-colony
}
# Keyword cleanups: remove a wrongly-claimed keyword from an entry (id -> keyword to drop).
KEYWORD_REMOVE = {
    "creature-anthrophage": ["babble bird"],  # Babble Bird is a separate book creature
}
# Keyword additions: ensure a lookup-friendly name resolves to the right entry (id -> keywords to add).
KEYWORD_ADD = {
    "creature-cacklemaw-virago": ["cacklemaw virago"],  # so 'Cacklemaw Virago' lookups hit the Virago, not the base
}
# Human-ruling HOLDS: keep OUR current resistances. (Joe 2026-06-07: follow the book;
# ruling #12 was based on hallucinated data. NONE held now.)
RESIST_HOLD = set()
# Authoritative per-creature resistance overrides read DIRECTLY from the PDF (book is master).
# Buckets here are creature-specific; the type-matrix union still adds type rules on top.
OVERRIDE_RESIST = {
    # Planeyfolk (Ancestry, printed p.23): Flat trait = halved damage from bludgeoning,
    # doubled damage from slashing OR piercing. (Verified 2026-06-07 audit remediation,
    # PDF page 30 / printed p.23. Prior single-clause "double slashing" was an incomplete transcription.)
    # Bio/Hypergeometric type union adds double hypergeometric on top.
    "planeyfolk": {"half": ["bludgeoning"], "double": ["slashing", "piercing"]},
    # Lanchra, the Pale Shadow (printed p.294): type Hypergeometric, stat block has NO Flat
    # trait -> no slashing weakness. Empty here -> type matrix gives double hypergeometric.
    "lanchra": {},
}
# Creatures with the INCORPOREAL rule = immune to all damage EXCEPT hypergeometric damage
# or anti-paradoxical weapons (book p.205). ONLY Spectre fits this exact rule; Chromavore
# (vulnerable to sunlight) and Quantum Daemons (immune until manifested) have distinct rules
# left as varies + notes.
INCORPOREAL = {"spectreofindifference"}
# Our entries to DROP entirely (confirmed fabricated).
DROP_ENTRY = {"creature-utility-snake"}  # Joe 2026-06-07: 100% made up.
# Our entries that are table-mentions with NO published stat block -> keep as lore, NOT combat.
NONCOMBAT_NOBLOCK = {"creature-desiccator"}  # Joe 2026-06-07: in a table, no stat block, no verifiable truth.
# Book records to NEVER add as new entries (abbreviated re-references of core creatures
# that appear again in adventure sections; verified same stat block as the canonical entry).
BOOK_SKIP_NEW = {"bacteriagestaltcolony"}  # p.295 re-ref of Bacterial Gestalt Colony (p.186)
# Prose-gap resistance PATCHES verified against book text (creature norm-name -> additions).
RESIST_PATCH = {
    # Bacterial Gestalt Colony: book "vulnerable to fungal spores or other antibiotics".
    "bacterialgestaltcolony": {"double": ["fungal_spores"]},
}

def parse_av(av):
    """Return (int_av, note). Handles '20 (10 abdomen)' / '12 (24 in cap)' / 20 / '20'."""
    if isinstance(av, int):
        return av, ""
    if av is None:
        return None, ""
    m = re.match(r"\s*(\d+)\s*(?:\(([^)]*)\))?", str(av))
    if not m:
        return None, str(av)
    n = int(m.group(1))
    note = f"Conditional AV: {m.group(2).strip()}" if m.group(2) else ""
    return n, note

def parse_morale(ml):
    """Numeric -> int; otherwise keep cleaned string (Special, =LVL, +2d6, =Group Size)."""
    if isinstance(ml, int):
        return ml
    s = str(ml or "").strip()
    m = re.fullmatch(r"\+?(\d+)", s)
    if m:
        return int(m.group(1))
    return s.lstrip("+") if s else ""

def clean_resist(r):
    """Keep only canonical damage types in buckets; preserve varies + notes."""
    out = {"immune": [], "minimum": [], "double": [], "half": [], "varies": bool(r.get("varies", False))}
    for b in ("immune","minimum","double","half"):
        seen = []
        for d in r.get(b, []) or []:
            d = str(d).strip().lower()
            if d in DAMAGE_VOCAB and d not in seen:
                seen.append(d)
        out[b] = sorted(seen)
    if r.get("notes"):
        out["notes"] = r["notes"]
    return out

# ---- Load book records, de-duped by normalized name (prefer higher confidence / richer) ----
CONF = {"high": 3, "medium": 2, "low": 1, "": 0}
book = {}
for fp in EXTRACT:
    for rec in json.load(open(fp)):
        name = rec.get("name", "").strip()
        if not name:
            continue
        k = norm(name)
        prev = book.get(k)
        if prev is None or CONF.get(rec.get("confidence",""),0) > CONF.get(prev.get("confidence",""),0):
            book[k] = rec

book_by_slug = {slugify(rec["name"]): rec for rec in book.values()}
book_norm_keys = list(book.keys())

def match_book(e):
    """Find this entry's book record. Returns (rec, book_norm_key) or (None, None).
    Strategies in priority: exact keyword norm -> slug equality -> prefix (len>=6 guard)."""
    for kw in e.get("keywords", []):
        if norm(kw) in book:
            return book[norm(kw)], norm(kw)
    if e["id"] in book_by_slug:
        rec = book_by_slug[e["id"]]
        return rec, norm(rec["name"])
    cands = [norm(kw) for kw in e.get("keywords", [])]
    cands.append(e["id"].replace("creature-", "").replace("-", ""))
    for c in cands:
        if len(c) < 6:
            continue
        for bk in book_norm_keys:
            if bk.startswith(c) or c.startswith(bk):
                return book[bk], bk
    # contains: our distinctive name sits inside a title-prefixed book name
    # (e.g. 'eldwallloonflower' in 'commandereldwallloonflowerhegemonycommander')
    for c in cands:
        if len(c) < 10:
            continue
        for bk in book_norm_keys:
            if c in bk:
                return book[bk], bk
    return None, None

# ---- Load our entries; index by every keyword (normalized) ----
data = json.load(open(BESTIARY))
entries = data["entries"]
by_norm = {}
for e in entries:
    for kw in e.get("keywords", []):
        by_norm.setdefault(norm(kw), e)

MATRIX = json.load(open(os.path.join(ROOT, "creature_resistances.json")))
EXPAND = {"extreme_temperature": ["fire", "cold"]}
def expand(items):
    out = []
    for d in items or []:
        out.extend(EXPAND.get(d, [d]))
    return out
def types_of(rec, our_entry):
    raw = rec.get("type") or (our_entry or {}).get("stats", {}).get("type") or ""
    return [p.strip() for p in str(raw).replace(",", "/").split("/") if p.strip()]

def build_resistances(rec, our_entry):
    nm = norm(rec.get("name",""))
    if any(nm.startswith(h) for h in RESIST_HOLD) and our_entry:
        held = dict(our_entry.get("stats",{}).get("resistances") or {})
        held["notes"] = (held.get("notes","") + " [HELD pending Joe: book bestiary shows different; ruling #12.]").strip()
        return held
    ov = next((v for k, v in OVERRIDE_RESIST.items() if nm.startswith(k)), None)
    r = clean_resist(ov if ov is not None else (rec.get("resistances", {}) or {}))
    patch = RESIST_PATCH.get(nm)
    if patch:
        for b, vals in patch.items():
            r[b] = sorted(set(r.get(b, [])) | set(vals))
    # Engine uses REPLACE semantics: a non-empty per-creature profile overrides the type
    # matrix entirely. So when a creature carries ANY creature-specific resistance, union the
    # type-matrix defaults in (book: multi-type = union of all type immunities/weaknesses), or
    # the type rules would be silently lost. Empty profiles are left empty -> matrix applies at runtime.
    nonempty = any(r.get(b) for b in ("immune","minimum","double","half")) or r.get("varies")
    if nonempty:
        for t in types_of(rec, our_entry):
            d = MATRIX.get(t, {})
            if d.get("varies"):
                r["varies"] = True
            for b in ("immune","minimum","double","half"):
                r[b] = sorted(set(r.get(b, [])) | set(expand(d.get(b, []))))
    return r

changelog = {"updated_stats": [], "resistance_changes": [], "new": [], "deduped": [],
             "keying": [], "held": [], "no_book_match_kept": [], "low_confidence": [],
             "dropped_fabricated": [], "noncombat_noblock": []}

matched_norms = set()
new_entries = []

# ---- Rebuild existing entries from book where matched ----
result = []
for e in entries:
    if e["id"] in DEDUP_DROP:
        changelog["deduped"].append(e["id"])
        continue
    # keyword cleanup
    if e["id"] in KEYWORD_REMOVE:
        before = list(e.get("keywords", []))
        e["keywords"] = [k for k in e["keywords"] if k not in KEYWORD_REMOVE[e["id"]]]
        changelog["keying"].append(f'{e["id"]}: removed {set(before)-set(e["keywords"])}')
    if e["id"] in KEYWORD_ADD:
        for kw in KEYWORD_ADD[e["id"]]:
            if kw not in e.get("keywords", []):
                e.setdefault("keywords", []).append(kw)
                changelog["keying"].append(f'{e["id"]}: added keyword {kw!r}')

    # find book match (multi-strategy)
    rec, bk_key = match_book(e)
    if rec is not None:
        matched_norms.add(bk_key)

    if rec is None:
        if e["id"] in DROP_ENTRY:
            changelog["dropped_fabricated"].append(e["id"])
            continue
        st = e.setdefault("stats", {})
        st.setdefault("resistances", {"immune":[],"minimum":[],"double":[],"half":[],"varies":False})
        if e["id"] in NONCOMBAT_NOBLOCK:
            e["contexts"] = [c for c in e.get("contexts", []) if c != "combat_active"]
            # Idempotent: strip any prior copies of this note before adding exactly one
            # (a plain append duplicated the note on every rebuild — see desiccator).
            _nc = "[No published stat block - table mention only; NOT combat-runnable. Stats unverifiable.]"
            _base = st.get("combat_note", "").replace(_nc, "").strip()
            st["combat_note"] = (_base + " " + _nc).strip()
            changelog["noncombat_noblock"].append(e["id"])
        elif "combat_active" in e.get("contexts", []):
            _uv = "[UNVERIFIED: no match in read Crimson Hound pages; verify source.]"
            _base = st.get("combat_note", "").replace(_uv, "").strip()
            st["combat_note"] = (_base + " " + _uv).strip()
            changelog["no_book_match_kept"].append(e["id"])
        e["lore_refs"] = []  # dead campaign metadata — zero on rebuild (2026-06-07 dedup)
        result.append(e)
        continue

    # MERGE book stats into our entry, preserving campaign metadata
    st = e.setdefault("stats", {})
    old = dict(st)
    av, av_note = parse_av(rec.get("av"))
    st["type"] = rec.get("type") or st.get("type") or ""
    # Book value wins WHEN PRESENT; else preserve our provisional value (don't null it out).
    st["level"] = rec.get("level") if rec.get("level") is not None else old.get("level")
    st["hp"] = rec.get("hp") if rec.get("hp") is not None else old.get("hp")
    st["av"] = av if av is not None else old.get("av")
    if rec.get("morale") not in (None, ""):
        st["morale"] = parse_morale(rec.get("morale"))
    # Derive HP = Level x 4 when the book printed no explicit HP (book rule, printed p.185).
    if st.get("hp") is None and isinstance(st.get("level"), int):
        st["hp"] = st["level"] * 4
        av_note = (av_note + " HP derived as LVL x4 (book printed no explicit HP).").strip()
    if rec.get("enc"): st["encountered"] = rec["enc"]
    if rec.get("attacks"): st["attacks"] = rec["attacks"]
    if rec.get("special"): st["special"] = rec["special"]
    st["resistances"] = build_resistances(rec, e)
    # flags
    fl = rec.get("flags", {}) or {}
    for f in ("mystic_gift_immune","ranged_immune","mimic"):
        if fl.get(f): st[f] = True
    cn = " ".join(x for x in [rec.get("combat_note",""), av_note] if x).strip()
    if cn: st["combat_note"] = cn
    if norm(rec.get("name","")) in INCORPOREAL:
        st["incorporeal"] = True
    e["source"] = f'Crimson Hound printed p.{rec.get("printed_pages","?")}'
    # lore_refs are dead campaign metadata (no code reads them; 163/170 were
    # dangling) — zero them on rebuild (2026-06-07 dedup). Empty list keeps the
    # schema stable (new entries already get []).
    e["lore_refs"] = []

    if any(norm(rec["name"]).startswith(h) for h in RESIST_HOLD):
        changelog["held"].append(e["id"])
    if rec.get("confidence") and rec["confidence"] != "high":
        changelog["low_confidence"].append(f'{e["id"]} ({rec["confidence"]})')
    if any(old.get(k) != st.get(k) for k in ("level","hp","av","morale","type")):
        changelog["updated_stats"].append(
            f'{e["id"]}: L{old.get("level")}->{st["level"]} HP{old.get("hp")}->{st["hp"]} '
            f'AV{old.get("av")}->{st["av"]} ML{old.get("morale")}->{st["morale"]} type{old.get("type")!r}->{st["type"]!r}')
    if (old.get("resistances") or {}) != st.get("resistances"):
        changelog["resistance_changes"].append(e["id"])
    result.append(e)

# ---- Add NEW book creatures with no match ----
existing_ids = {e["id"] for e in result}
for k, rec in book.items():
    if k in matched_norms or k in BOOK_SKIP_NEW:
        continue
    av, av_note = parse_av(rec.get("av"))
    cn = " ".join(x for x in [rec.get("combat_note",""), av_note] if x).strip()
    nid = slugify(rec["name"])
    if nid in existing_ids:
        nid = f'{nid}-p{rec.get("printed_pages","x")}'
    existing_ids.add(nid)
    nhp = rec.get("hp")
    if nhp is None and isinstance(rec.get("level"), int):
        nhp = rec["level"] * 4
        cn = (cn + " HP derived as LVL x4 (book printed no explicit HP).").strip()
    ne = {
        "id": nid,
        "keywords": [rec["name"].lower()],
        "categories": ["bestiary"],
        "contexts": ["combat_active"],
        "stats": {
            "type": rec.get("type") or "",
            "level": rec.get("level"), "hp": nhp, "av": av,
            "morale": parse_morale(rec.get("morale")),
            "encountered": rec.get("enc",""),
            "attacks": rec.get("attacks", []),
            "special": rec.get("special", []),
            "resistances": clean_resist(rec.get("resistances", {}) or {}),
        },
        "lore_refs": [],
        "source": f'Crimson Hound printed p.{rec.get("printed_pages","?")}',
    }
    for f in ("mystic_gift_immune","ranged_immune","mimic"):
        if (rec.get("flags") or {}).get(f): ne["stats"][f] = True
    if cn: ne["stats"]["combat_note"] = cn
    result.append(ne)
    changelog["new"].append(f'{ne["id"]} (p.{rec.get("printed_pages","?")})')

data["entries"] = result
json.dump(data, open(OUT, "w"), indent=1, ensure_ascii=True)

# ---- changelog ----
with open(CHANGELOG, "w") as f:
    f.write("# Bestiary Rebuild Changelog (candidate -> bestiary.rebuilt.json)\n\n")
    f.write(f"Book records (unique): {len(book)} | Our entries in: {len(entries)} | Out: {len(result)}\n\n")
    for sec in ("updated_stats","resistance_changes","new","deduped","keying","held",
                "no_book_match_kept","low_confidence","dropped_fabricated","noncombat_noblock"):
        f.write(f"## {sec} ({len(changelog[sec])})\n")
        for line in changelog[sec]:
            f.write(f"- {line}\n")
        f.write("\n")

print(f"OUT entries: {len(result)}  (was {len(entries)})")
print(f"book unique: {len(book)}  matched: {len(matched_norms)}  new: {len(changelog['new'])}")
print(f"deduped: {len(changelog['deduped'])}  stat-updates: {len(changelog['updated_stats'])}  "
      f"resist-changes: {len(changelog['resistance_changes'])}  held: {len(changelog['held'])}  "
      f"no-book-match: {len(changelog['no_book_match_kept'])}")
