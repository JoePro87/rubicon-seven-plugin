#!/usr/bin/env python3
"""Arm the NEXT session's output-style variant (anti-normalization rotation).

Composes `<campaign>/.claude/output-styles/rubicon-seven-dm.md` from:
  frontmatter (verbatim from the base file) + one randomly-picked
  `anti-norm-*.md` stance + the base body (verbatim).

Run by the /session-start skill each session: the CURRENT session already
loaded its style before this runs, so the composition takes effect NEXT
session — a deliberate one-session lag that makes rotation zero-discipline.

The base file (`rubicon-seven-dm-base.md`) is the canonical curated style,
INCLUDING its frontmatter; edit style content there, never in the composed
file (which this script overwrites). Selections append to
`<campaign>/variant_log.json`. Fail-soft: any problem prints a note and
exits 0 — a broken rotation must never block a session.

Usage: compose_style_variant.py <campaign_dir>
"""
import json
import random
import sys
from datetime import datetime
from pathlib import Path


def compose(campaign_dir) -> str:
    campaign = Path(campaign_dir)
    styles = campaign / ".claude" / "output-styles"
    base_path = styles / "rubicon-seven-dm-base.md"
    target = styles / "rubicon-seven-dm.md"
    if not base_path.exists():
        return "style rotation: no base file — skipped (nothing changed)"

    base = base_path.read_text(encoding="utf-8")
    # Split frontmatter (--- ... ---) from body; preserve both verbatim.
    if base.startswith("---"):
        end = base.find("\n---", 3)
        if end == -1:
            return "style rotation: base frontmatter unterminated — skipped"
        split = end + len("\n---\n")
        frontmatter, body = base[:split], base[split:]
    else:
        frontmatter, body = "", base

    variants = sorted(styles.glob("anti-norm-*.md"))
    if not variants:
        target.write_text(base, encoding="utf-8")
        return "style rotation: no variants — composed base only"

    pick = random.choice(variants)
    stance = pick.read_text(encoding="utf-8").strip()
    target.write_text(f"{frontmatter}\n{stance}\n\n{body.lstrip()}",
                      encoding="utf-8")

    log_path = campaign / "variant_log.json"
    try:
        log = json.loads(log_path.read_text(encoding="utf-8")) if log_path.exists() else []
    except Exception:
        log = []
    log.append({"timestamp": datetime.now().isoformat(timespec="seconds"),
                "variant": pick.stem})
    log_path.write_text(json.dumps(log, indent=2), encoding="utf-8")
    return f"style rotation: next session armed with '{pick.stem}'"


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if len(sys.argv) < 2:
        print("usage: compose_style_variant.py <campaign_dir>")
        return
    try:
        print(compose(sys.argv[1]))
    except Exception as e:
        print(f"style rotation: failed non-fatally ({e})")


if __name__ == "__main__":
    main()
