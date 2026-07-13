"""R3 backfill: stamps engine_tags from prose AV tags; idempotent; cleans mojibake."""
import json
from pathlib import Path

from scripts.backfill_av_tags_r3 import backfill_dir

# escapes, NOT literals (editors mangle mojibake): \u00e2\u20ac\u201d is the
# cp1252 misread of a utf-8 em dash -- the exact bytes seen on a live sheet.
MOJIBAKE_TAG = ("Dimensional Edge \u00e2\u20ac\u201d attacks treat target AV "
                "as 10 (unarmored)")
CLEAN_TAG = ("Dimensional Edge \u2014 attacks treat target AV "
             "as 10 (unarmored)")


def _seed(tmp_path):
    chars = tmp_path / "characters"
    chars.mkdir()
    (chars / "creenash.json").write_text(json.dumps({
        "name": "Creenash",
        "inventory": {"carried": [
            {"id": "extradimensional_letter_opener",
             "name": "Extradimensional Letter Opener", "damage": "d4",
             "damage_type": "kinetic", "kinetic_subtype": "piercing",
             "tags": [MOJIBAKE_TAG, "Planeyfolk manufacture"],
             "engine_tags": []},
            {"name": "Plain Knife", "damage": "d4", "tags": ["Rusty"],
             "engine_tags": []},
        ], "stored": []},
    }, indent=2), encoding="utf-8")
    return tmp_path


def test_backfill_stamps_and_cleans(tmp_path):
    root = _seed(tmp_path)
    changed = backfill_dir(root)
    assert changed == 1
    data = json.loads((root / "characters" / "creenash.json").read_text(encoding="utf-8"))
    opener = data["inventory"]["carried"][0]
    assert opener["engine_tags"] == ["dimensional-edge"]
    assert opener["tags"][0] == CLEAN_TAG
    # untouched control item
    assert data["inventory"]["carried"][1]["engine_tags"] == []


def test_backfill_idempotent(tmp_path):
    root = _seed(tmp_path)
    backfill_dir(root)
    assert backfill_dir(root) == 0   # second run changes nothing


def test_dry_run_changes_nothing(tmp_path):
    root = _seed(tmp_path)
    n = backfill_dir(root, dry_run=True)
    assert n == 1   # reports what WOULD change
    data = json.loads((root / "characters" / "creenash.json").read_text(encoding="utf-8"))
    assert data["inventory"]["carried"][0]["engine_tags"] == []   # untouched
