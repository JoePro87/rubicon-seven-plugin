#!/usr/bin/env python3
"""Standalone ChromaDB staleness check -- READ-ONLY.

Reports doc count, per-source counts, and the max indexed day found in the live
history collection's metadata, compared against the campaign's CURRENT day (read
from CURRENT_STATUS.md, falling back to characters/_meta.json's campaign_day
field -- same two homes get_current_day_safe() in server.py reads, mirrored here
rather than imported so this script has no import-time dependency on server.py's
full boot path).

Read-only by construction: the only chromadb calls made are get_collection(),
.count(), and .get(include=["metadatas"]) -- no add/update/upsert/delete anywhere
in this file.

Exit codes:
  0 = fresh (lag <= --max-lag-days)
  1 = stale (lag > --max-lag-days)
  2 = error (chromadb unavailable, store missing, campaign day unknown, etc.)

MUST run under the Windows venv (chromadb 1.3.7 -- see requirements.txt):
    .venv/Scripts/python.exe scripts/chroma_staleness.py [--campaign-dir PATH] [--max-lag-days N] [--json]

Campaign dir resolution mirrors every other script here: --campaign-dir wins,
else rubicon_paths.campaign_dir() ($RUBICON_CAMPAIGN_DIR or the engine dir's
sibling named rubicon-seven-campaign).
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root
import rubicon_paths

# Same regex server.get_current_day_safe() uses against CURRENT_STATUS.md.
_DAY_RE = re.compile(r'(?:Campaign Day|Day)\s*[:\*]*\s*(\d+)', re.IGNORECASE)


def get_campaign_day(campaign_dir: Path):
    """Return (day, source_label) or (None, None). Mirrors server.get_current_day_safe(),
    with a fallback to characters/_meta.json's campaign_day field when
    CURRENT_STATUS.md is absent or unparseable."""
    status_path = campaign_dir / "CURRENT_STATUS.md"
    if status_path.exists():
        try:
            content = status_path.read_text(encoding="utf-8")
            m = _DAY_RE.search(content)
            if m:
                return int(m.group(1)), "CURRENT_STATUS.md"
        except Exception:
            pass
    meta_path = campaign_dir / "characters" / "_meta.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if "campaign_day" in meta:
                return int(meta["campaign_day"]), "characters/_meta.json"
        except Exception:
            pass
    return None, None


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--campaign-dir", type=Path, default=None,
                         help="Campaign data dir (default: rubicon_paths.campaign_dir())")
    parser.add_argument("--max-lag-days", type=int, default=3,
                         help="Lag threshold in days before reporting stale (default: 3)")
    parser.add_argument("--json", action="store_true",
                         help="Emit machine-readable JSON instead of text")
    args = parser.parse_args()

    campaign_dir = args.campaign_dir or rubicon_paths.campaign_dir()

    try:
        import chromadb
    except ImportError:
        print("ERROR: chromadb not importable. Run under the Windows venv: "
              ".venv/Scripts/python.exe scripts/chroma_staleness.py", file=sys.stderr)
        return 2

    chroma_path = campaign_dir / "chroma-db"
    if not chroma_path.exists():
        print(f"ERROR: no chroma-db directory at {chroma_path} "
              f"(pass --campaign-dir or set $RUBICON_CAMPAIGN_DIR)", file=sys.stderr)
        return 2

    try:
        client = chromadb.PersistentClient(path=str(chroma_path))
        try:
            collection = client.get_collection("campaign_history_tiered_v2")
            coll_name = "campaign_history_tiered_v2 (cosine)"
        except Exception:
            collection = client.get_collection("campaign_history_tiered")
            coll_name = "campaign_history_tiered (legacy L2)"
        count = collection.count()
        metadatas = collection.get(include=["metadatas"])["metadatas"]
    except Exception as e:
        print(f"ERROR: could not read chroma-db at {chroma_path}: {e}", file=sys.stderr)
        return 2

    sources = {}
    max_day = 0
    for meta in metadatas:
        src = meta.get("source", "unknown")
        sources[src] = sources.get(src, 0) + 1
        try:
            d = int(meta.get("day", 0))
            if d > max_day:
                max_day = d
        except Exception:
            pass

    campaign_day, day_source = get_campaign_day(campaign_dir)
    lag = (campaign_day - max_day) if campaign_day is not None else None

    result = {
        "collection": coll_name,
        "doc_count": count,
        "sources": sources,
        "max_indexed_day": max_day,
        "campaign_day": campaign_day,
        "campaign_day_source": day_source,
        "lag_days": lag,
        "max_lag_days": args.max_lag_days,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Collection: {coll_name}")
        print(f"Documents: {count}")
        print("Sources:")
        for src, cnt in sorted(sources.items()):
            print(f"  {src}: {cnt}")
        print(f"Max indexed day: {max_day}")
        if campaign_day is not None:
            print(f"Campaign day: {campaign_day} (from {day_source})")
            print(f"Lag: {lag} day(s) (threshold {args.max_lag_days})")
        else:
            print("Campaign day: UNKNOWN (no CURRENT_STATUS.md or characters/_meta.json campaign_day field)")

    if campaign_day is None:
        print("STALENESS: UNKNOWN (cannot determine campaign day)", file=sys.stderr)
        return 2
    if lag > args.max_lag_days:
        print(f"STALENESS: STALE (lag {lag} > threshold {args.max_lag_days})")
        return 1
    print("STALENESS: FRESH")
    return 0


if __name__ == "__main__":
    sys.exit(main())
