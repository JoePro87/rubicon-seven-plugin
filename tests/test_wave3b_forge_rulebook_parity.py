"""C10 — forge<->rulebook shared-table parity.

14 Crimson Hound tables live in BOTH data/content_forge_tables.json (the live
roll(action="location"/"settlement") generators) and data/rules/rulebook/tables.json
(the certified rulebook copy). Three-plus forge copies had drifted via a
sparse-column misparse (arcology/archive/bounty_hunter) or a mid-column shift
(anomaly/bandit_camp) — all verified against the Crimson Hound book (batch_06
extraction / printed tables): the rulebook copies are book-correct, so the forge
copies were repaired to match. This guard pins ALL shared pairs, with
punctuation/whitespace normalization so the false-positive class (faa_camp's
parens-vs-commas) doesn't trip it. starting_boon is exempt: its forge copy
carries tool-push annotations by design.
"""
import json
import re

import pytest

import engine_core

# forge table key -> rulebook table id (the certified book copy that WINS)
SHARED_PAIRS = {
    "anomaly": "table-anomaly",
    "bandit_camp": "table-bandit-camp",
    "cacklemaw_den": "table-cacklemaw-den",
    "vault": "table-vault-entrance",
    "settlement_government": "table-settlement-government-faith",
    "settlement_values": "table-settlement-values",
    "settlement_asset": "table-settlement-assets",
    "settlement_problem": "table-settlement-problems",
    "settlement_change": "table-settlement-changes",
    "fortress": "table-fortress",
    "faa_camp": "table-faa-nomad-camp",
    "arcology": "table-arcology",
    "archive": "table-archive",
    "bounty_hunter": "table-bounty-hunter-camp",
    # the 7 wilderness sub-tables dual-homed 2026-07-05 (forge copies aligned to
    # the book-correct rulebook copies; ruin/science-mystic paired-row columns
    # mirror the rulebook pairing, ruin column order = book order)
    "grave": "table-grave",
    "holy_place": "table-holy-place",
    "oasis": "table-oasis",
    "ruin": "table-ruin",
    "science_mystic": "table-science-mystic",
    "trade_post": "table-trade-post",
    "wreck": "table-wreck",
}
# forge copy intentionally diverges (adds tool-push hints) — not book data
EXEMPT = {"starting_boon"}


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


def _load():
    forge = json.loads(
        (engine_core.RULES_DATA_DIR.parent / "content_forge_tables.json").read_text(encoding="utf-8")
    )["tables"]
    rb = {
        t["id"]: t
        for t in json.loads(engine_core.read_rules_data("rulebook/tables.json"))["rolling_tables"]
    }
    return forge, rb


def _forge_rows(t):
    return {int(e["roll"]): list(e["fields"].values()) for e in t["entries"]}


def _rb_rows(t):
    return {int(e["roll"]): [v for k, v in e.items() if k != "roll"] for e in t["entries"]}


@pytest.mark.parametrize("fk,rid", sorted(SHARED_PAIRS.items()))
def test_forge_matches_certified_rulebook(fk, rid):
    forge, rb = _load()
    assert fk in forge, f"forge table {fk} missing"
    assert rid in rb, f"rulebook table {rid} missing"
    f = _forge_rows(forge[fk])
    r = _rb_rows(rb[rid])
    assert set(f) == set(r), f"{fk}: roll set differs from {rid}"
    bad = []
    for roll in sorted(f):
        fv, rv = f[roll], r[roll]
        assert len(fv) == len(rv), f"{fk} roll {roll}: column count differs"
        for i, (a, b) in enumerate(zip(fv, rv)):
            if _norm(a) != _norm(b):
                bad.append(f"  roll {roll} col {i}: forge={a!r} rb={b!r}")
    assert not bad, f"{fk} diverges from certified {rid}:\n" + "\n".join(bad)


def test_starting_boon_is_the_only_exempt_pair():
    # guard-the-guard: starting_boon really does still differ (tool-push hints),
    # so the exemption is load-bearing, not masking a silent regression.
    forge, rb = _load()
    f = _forge_rows(forge["starting_boon"])
    r = _rb_rows(rb["table-starting-boon"])
    differs = any(_norm(f[k][0]) != _norm(r[k][0]) for k in set(f) & set(r))
    assert differs, "starting_boon no longer diverges — drop it from EXEMPT"
