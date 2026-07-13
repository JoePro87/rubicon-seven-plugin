"""R3: stamp engine_tags for the four AV-special weapon tags on live sheets.

Sweeps characters/*.json and vehicles/*.json inventories for items whose
prose tags resolve (via weapon_schema.resolve_tag) to one of the R3 keys
(vibroactive / piercing / mauling / dimensional-edge) and appends any missing
key to engine_tags. Also repairs the known mojibake em dash in prose tags.
Idempotent. Run with the Windows venv python. --dry-run previews.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import weapon_schema as ws

CAMPAIGN = Path(__file__).resolve().parents[2] / "rubicon-seven-campaign"
R3_KEYS = {"vibroactive", "piercing", "mauling", "dimensional-edge"}
# The cp1252 misread of UTF-8 em dash (0xE2 0x80 0x94) produces three chars:
# U+00E2 U+20AC U+201D  --  encoded here as \u escapes, never as literals.
MOJIBAKE_EMDASH = "\u00e2\u20ac\u201d"
EMDASH = "\u2014"


def _fix_item(item: dict) -> bool:
    """Stamp missing R3 engine keys + clean mojibake. True if item changed."""
    tags = item.get("tags")
    if not isinstance(tags, list):
        return False
    changed = False
    for i, t in enumerate(tags):
        if isinstance(t, str) and MOJIBAKE_EMDASH in t:
            tags[i] = t.replace(MOJIBAKE_EMDASH, EMDASH)
            changed = True
    engine = item.setdefault("engine_tags", [])
    for t in tags:
        key = ws.resolve_tag(t)
        if key in R3_KEYS and key not in engine:
            engine.append(key)
            changed = True
    return changed


def backfill_dir(root: Path, dry_run: bool = False) -> int:
    """Backfill all sheets under root. Returns number of files changed."""
    files_changed = 0
    for sub in ("characters", "vehicles"):
        d = root / sub
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.json")):
            data = json.loads(f.read_text(encoding="utf-8"))
            inv = data.get("inventory") or {}
            touched = False
            for section in ("carried", "stored"):
                for item in inv.get(section) or []:
                    if isinstance(item, dict) and _fix_item(item):
                        touched = True
                        print(f"  {f.name}: {item.get('name', '?')} -> "
                              f"engine_tags={item.get('engine_tags')}")
            if touched:
                files_changed += 1
                if not dry_run:
                    f.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                                 encoding="utf-8")
    return files_changed


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    n = backfill_dir(CAMPAIGN, dry_run=dry)
    print(f"{'DRY RUN: would change' if dry else 'Changed'} {n} file(s).")
