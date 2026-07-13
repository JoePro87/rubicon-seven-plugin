"""Backfill `ammo_max` = `ammo` on every weapon entry that has `ammo` but no
`ammo_max`, across a campaign's split character sheets. Idempotent: re-running
changes nothing once stamped. Walks both inventory.carried[] and attacks[].

Usage:
    .venv/Scripts/python.exe scripts/backfill_ammo_max.py <characters_dir>
"""
import json
import sys
from pathlib import Path


def _stamp(entries) -> int:
    changed = 0
    for e in entries or []:
        if isinstance(e, dict) and e.get("ammo") and not e.get("ammo_max"):
            e["ammo_max"] = e["ammo"]
            changed += 1
    return changed


def main(chars_dir: str) -> None:
    d = Path(chars_dir)
    total = 0
    for fp in sorted(d.glob("*.json")):
        if fp.name.startswith("_"):   # skip _meta.json
            continue
        raw_bytes = fp.read_bytes()         # read bytes so EOL style survives detection
        raw = raw_bytes.decode("utf-8")
        sheet = json.loads(raw)
        n = _stamp(sheet.get("inventory", {}).get("carried", []))
        n += _stamp(sheet.get("attacks", []))
        if n:
            text = json.dumps(sheet, indent=2, ensure_ascii=False)
            if raw_bytes.endswith(b"\n"):    # preserve a trailing newline only if the original had one
                text += "\n"
            if b"\r\n" in raw_bytes:         # preserve CRLF if the original used it
                text = text.replace("\n", "\r\n")
            fp.write_bytes(text.encode("utf-8"))
            print(f"{fp.name}: stamped {n} ammo_max")
            total += n
    print(f"Done. {total} entries stamped.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else
         "../rubicon-seven-campaign/characters")
