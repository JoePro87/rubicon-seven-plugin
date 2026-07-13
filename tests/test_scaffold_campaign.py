"""scaffold_campaign.py — the single source of truth for the blank Day-1 campaign.

Guards: the scaffolder writes the full expected structure, and reset_to_base.py
shares the SAME content (so the blank-campaign structure can never drift between
the onboarding scaffolder and the reset tool).
"""
import sys
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import scaffold_campaign as sc  # noqa: E402
import reset_to_base as rb      # noqa: E402


def _scaffold_tmp():
    root = Path(tempfile.mkdtemp(prefix="scaffold_test_"))
    sc.scaffold(root, "2026-06-20")
    return root


def test_scaffold_writes_full_structure():
    root = _scaffold_tmp()
    try:
        for f in ["CURRENT_STATUS.md", "MASTER_CONTINUITY_CURRENT.md",
                  "ANTAGONIST_CULTIVATION.md", "lorebook.json", "NPC_ROSTER.md",
                  ".gitignore", "characters/_meta.json"]:
            assert (root / f).is_file(), f"missing file {f}"
        for d in sc.BLANK_DIRS:
            assert (root / d).is_dir(), f"missing dir {d}"
        # the load-bearing fields the engine/check_canon need on Day 1
        assert '"campaign_day": 1' in (root / "characters/_meta.json").read_text()
        assert "2026-06-20" in (root / "characters/_meta.json").read_text()
        assert (root / "lorebook.json").read_text().strip() == '{\n  "entries": []\n}'
        assert "**Last 3 Beats:**" in (root / "CURRENT_STATUS.md").read_text()
        assert ".claude/memories.json" in (root / ".gitignore").read_text()  # leak guard
    finally:
        shutil.rmtree(root)


def test_scaffold_skips_existing_unless_force():
    root = _scaffold_tmp()
    try:
        # hand-edit a file, re-scaffold without force -> preserved
        (root / "CURRENT_STATUS.md").write_text("PLAYER PROGRESS")
        sc.scaffold(root, "2026-06-20")
        assert (root / "CURRENT_STATUS.md").read_text() == "PLAYER PROGRESS"
        # with force -> reset to blank
        sc.scaffold(root, "2026-06-20", overwrite=True)
        assert "PLAYER PROGRESS" not in (root / "CURRENT_STATUS.md").read_text()
        assert "CURRENT STATUS - DAY 1" in (root / "CURRENT_STATUS.md").read_text()
    finally:
        shutil.rmtree(root)


def test_reset_and_scaffold_share_one_source():
    # reset_to_base must REWRITE exactly what scaffold WRITES (no second definition).
    blank = sc.blank_files("x")
    for rel, content in rb.RESET_FILES.items():
        assert content == blank[rel], f"{rel} content diverged between reset and scaffold"
    # the engine-repo guard is shared too
    assert rb.ENGINE_SIGNATURES is sc.ENGINE_SIGNATURES
