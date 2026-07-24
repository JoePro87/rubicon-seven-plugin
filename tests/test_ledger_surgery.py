"""Ledger surgery: substring-matched, dry-run default, abort on ambiguity."""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "thyricost_ledger_surgery.py"


def _seed(tmp_path, facts):
    maps = tmp_path / "maps"
    maps.mkdir()
    state = {"revealed_ledger": [
        {"fact": f, "day": 134, "source_room": "", "source_action": "reveal"} for f in facts
    ]}
    (maps / "thyricost_map.json").write_text(json.dumps(state), encoding="utf-8")
    return maps / "thyricost_map.json"


def _run(tmp_path, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--campaign-dir", str(tmp_path), *args],
        capture_output=True, text=True)


FACTS = [
    "Tessith spoke: she was Anchor of Node Thirteen; Ceruline is Node Four; traffic 4,312 years ago",
    "Tessith knew Bathiel personally — sixty years of Compact correspondence and doctrine arguments",
    "Tessith on the vision: Node Thirteen's original purpose WAS desalination; the stacks still stand",
    "The Anchor's household was entered into the polity record (Tesslyn conducting the roll): Vela, Kess",
    "Salt-bore: 60m shaft, fragile lip",
]


def test_dry_run_writes_nothing(tmp_path):
    p = _seed(tmp_path, FACTS)
    before = p.read_text(encoding="utf-8")
    r = _run(tmp_path)
    assert r.returncode == 0 and "DRY RUN" in r.stdout
    assert p.read_text(encoding="utf-8") == before


def test_execute_applies_all_four_and_backs_up(tmp_path):
    p = _seed(tmp_path, FACTS)
    r = _run(tmp_path, "--execute")
    assert r.returncode == 0, r.stderr
    data = json.loads(p.read_text(encoding="utf-8"))
    facts = [e["fact"] for e in data["revealed_ledger"]]
    assert not any("Node Four" in f for f in facts)
    assert not any("Bathiel" in f for f in facts)
    assert not any("purpose WAS desalination" in f for f in facts)
    assert any(f.startswith("The party was entered into the polity record") for f in facts)
    assert any("Salt-bore" in f for f in facts)          # untouched entries survive
    assert len(facts) == 4                                # exactly one deletion
    assert list(tmp_path.glob("maps/*.bak"))


def test_ambiguous_match_aborts(tmp_path):
    _seed(tmp_path, FACTS + ["Another note: Ceruline is Node Four they said"])
    r = _run(tmp_path, "--execute")
    assert r.returncode != 0 and "abort" in (r.stdout + r.stderr).lower()
