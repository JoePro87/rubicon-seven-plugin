#!/usr/bin/env python
"""Launcher for the companion dashboard -- a second-terminal-pane, read-only
Textual view of the live player-view artifacts.

Usage: python scripts/dashboard.py [campaign_dir]
Resolves the campaign dir from argv[1], falling back to $RUBICON_CAMPAIGN_DIR.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from dashboard.app import run  # noqa: E402
except ImportError as e:
    if "textual" in str(e).lower():
        _req = Path(__file__).resolve().parent.parent / "requirements.txt"
        print("The dashboard needs the 'textual' package (added in v0.8.0).")
        print("Your engine venv predates it — sync dependencies with:")
        print(f'  "{sys.executable}" -m pip install -r "{_req}"')
        print("(or re-run /vaarn-start, which does the same thing).")
        sys.exit(1)
    raise


def main() -> int:
    campaign_dir = None
    if len(sys.argv) > 1:
        campaign_dir = sys.argv[1]
    elif os.environ.get("RUBICON_CAMPAIGN_DIR"):
        campaign_dir = os.environ["RUBICON_CAMPAIGN_DIR"]

    if not campaign_dir:
        print("Usage: python scripts/dashboard.py [campaign_dir]")
        print("(or set $RUBICON_CAMPAIGN_DIR)")
        return 1

    run(campaign_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
