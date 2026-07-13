"""C23 — generate(npc) crystallization push.

_generate_npc is the highest-frequency generator and was the only major
generate() branch that pushed nothing. It now ends with an npc(action="set")
baton prefilling what it MINTED (name, wants from the drive roll, secret when
rolled), with disposition left as a placeholder (not minted) and the persist
decision labeled as DM judgment.
"""
import re
import generators


def _gen(**kw):
    return generators._generate_npc(**kw)


def test_npc_ends_with_set_push():
    out = _gen(ancestry="True-kin", name_style="A", include_secret=True)
    assert "NEXT" in out
    assert 'npc(action="set"' in out
    # persist stays DM judgment
    assert "persist IF this NPC will recur" in out


def test_push_prefills_minted_name():
    out = _gen(ancestry="Synth", name_style="D", include_secret=False)
    # the pushed name must equal the NPC's rolled name (the "NPC: <name>" header)
    header = re.search(r"NPC: (.+)", out).group(1).strip()
    m = re.search(r'npc\(action="set", name="([^"]+)"', out)
    assert m and m.group(1) == header


def test_push_carries_secret_only_when_rolled():
    with_secret = _gen(ancestry="Cacogen", name_style="A", include_secret=True)
    assert "secret=" in with_secret.split("NEXT")[-1]
    without = _gen(ancestry="Cacogen", name_style="A", include_secret=False)
    assert "secret=" not in without.split("NEXT")[-1]


def test_disposition_is_placeholder_not_minted():
    out = _gen(ancestry="Synth", name_style="A", include_secret=False)
    assert 'disposition="<disposition after first meeting>"' in out


def test_wants_prefilled_from_drive():
    # wants should be a non-empty quoted value drawn from the drive roll
    out = _gen(ancestry="Synth", name_style="A", include_secret=False)
    m = re.search(r'wants="([^"]+)"', out)
    assert m and m.group(1).strip()
