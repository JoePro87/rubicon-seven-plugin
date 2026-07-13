import dice_chain as dc


def test_chain_order():
    assert dc.CHAIN == ["cured", "d4", "d6", "d8", "d10", "d12", "d20"]


def test_size():
    assert dc.size("d4") == 4
    assert dc.size("d20") == 20
    assert dc.size("cured") == 0
    assert dc.size(None) == 0


def test_step_down_walks_chain():
    assert dc.step_down("d20") == "d12"
    assert dc.step_down("d8") == "d6"
    assert dc.step_down("d4") == "cured"
    assert dc.step_down("cured") == "cured"
    assert dc.step_down(None) == "cured"


def test_escalate_bigger_wins():
    assert dc.escalate("d8", "d6") == "d8"
    assert dc.escalate("d8", "d8") == "d8"
    assert dc.escalate("d8", "d12") == "d12"
    assert dc.escalate("cured", "d6") == "d6"
    assert dc.escalate(None, "d4") == "d4"


def test_roll_bounds_and_injection():
    assert dc.roll("d8", rng=lambda lo, hi: hi) == 8
    assert dc.roll("d8", rng=lambda lo, hi: lo) == 1
    assert dc.roll("cured", rng=lambda lo, hi: hi) == 0
    for _ in range(50):
        assert 1 <= dc.roll("d6") <= 6
