import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import compose_style_variant as csv_mod  # noqa: E402

FRONT = "---\nname: Rubicon Seven DM\ndescription: \"rich june description\"\nkeep-coding-instructions: false\n---\n"
BODY = "## Anti-Normalization\n\nShort first.\n\n## Voice and Register\n\nDying-earth.\n"


def _campaign(tmp_path, variants=("alpha", "beta")):
    styles = tmp_path / ".claude" / "output-styles"
    styles.mkdir(parents=True)
    (styles / "rubicon-seven-dm-base.md").write_text(FRONT + BODY, encoding="utf-8")
    for v in variants:
        (styles / f"anti-norm-{v}.md").write_text(
            f"## Session Stance: {v.title()}\n\nLean {v}.\n", encoding="utf-8")
    return tmp_path


def test_compose_structure_and_frontmatter_verbatim(tmp_path):
    camp = _campaign(tmp_path)
    msg = csv_mod.compose(camp)
    assert "armed with 'anti-norm-" in msg
    out = (camp / ".claude" / "output-styles" / "rubicon-seven-dm.md").read_text(encoding="utf-8")
    assert out.startswith(FRONT)                      # frontmatter verbatim, first
    assert "## Session Stance:" in out                # stance spliced in
    assert out.index("## Session Stance:") < out.index("## Anti-Normalization")
    assert BODY.strip() in out                        # base body intact


def test_log_appended(tmp_path):
    camp = _campaign(tmp_path)
    csv_mod.compose(camp)
    csv_mod.compose(camp)
    log = json.loads((camp / "variant_log.json").read_text(encoding="utf-8"))
    assert len(log) == 2 and all(e["variant"].startswith("anti-norm-") for e in log)


def test_no_variants_composes_base_only(tmp_path):
    camp = _campaign(tmp_path, variants=())
    msg = csv_mod.compose(camp)
    assert "base only" in msg
    out = (camp / ".claude" / "output-styles" / "rubicon-seven-dm.md").read_text(encoding="utf-8")
    assert out == FRONT + BODY


def test_missing_base_is_a_noop(tmp_path):
    (tmp_path / ".claude" / "output-styles").mkdir(parents=True)
    msg = csv_mod.compose(tmp_path)
    assert "skipped" in msg
    assert not (tmp_path / ".claude" / "output-styles" / "rubicon-seven-dm.md").exists()
