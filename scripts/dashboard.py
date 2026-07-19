#!/usr/bin/env python
"""Launcher for the companion dashboard -- a second-terminal-pane, read-only
Textual view of the live player-view artifacts.

Usage: python scripts/dashboard.py [campaign_dir]
Resolves the campaign dir from argv[1], falling back to $RUBICON_CAMPAIGN_DIR,
falling back to the conventional sibling campaign dir ../rubicon-seven-campaign.
"""
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

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


def resolve_campaign_dir(argv, env, repo_root: Path):
    """Pick the campaign dir: argv[1] > $RUBICON_CAMPAIGN_DIR > the
    conventional sibling ../rubicon-seven-campaign (if it exists) > None.

    Returns (campaign_dir_or_None, source) where source is one of
    "arg", "env", "sibling-default", or None. Pure function -- no I/O beyond
    checking existence of the candidate sibling dir -- so it's unit-testable.
    """
    if len(argv) > 1:
        return argv[1], "arg"
    if env.get("RUBICON_CAMPAIGN_DIR"):
        return env["RUBICON_CAMPAIGN_DIR"], "env"
    sibling = repo_root.parent / "rubicon-seven-campaign"
    if sibling.exists():
        return str(sibling), "sibling-default"
    return None, None


def main() -> int:
    campaign_dir, source = resolve_campaign_dir(sys.argv, os.environ, _REPO_ROOT)

    if not campaign_dir:
        print("Usage: python scripts/dashboard.py [campaign_dir]")
        print("(or set $RUBICON_CAMPAIGN_DIR)")
        print(f"(no campaign dir found at the conventional sibling location "
              f"either: {_REPO_ROOT.parent / 'rubicon-seven-campaign'})")
        return 1

    if source == "sibling-default":
        print(f"No campaign dir given -- using conventional sibling: {campaign_dir}")

    run(campaign_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
