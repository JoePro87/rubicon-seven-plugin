"""reflex_budget: the editor with a page limit (Reflex Layer Component 3).
URGENT always prints; CHANGED next; AMBIENT only if room. Empty -> "".
Pure module: no I/O, no campaign reads — composition and diff only."""
import reflex_budget as rb


def E(tier, text):
    return rb.Entry(tier=tier, text=text)


def test_empty_entries_zero_output():
    assert rb.compose([]) == ""
    assert rb.compose([E(rb.AMBIENT, "")]) == ""


def test_urgent_always_included_even_over_cap():
    big = "X" * 900
    out = rb.compose([E(rb.URGENT, big)], cap_chars=100)
    assert big in out


def test_tier_order_urgent_changed_ambient():
    out = rb.compose([E(rb.AMBIENT, "ambient"), E(rb.URGENT, "urgent"), E(rb.CHANGED, "changed")])
    lines = out.splitlines()
    assert lines == ["urgent", "changed", "ambient"]


def test_cap_cuts_ambient_first_and_reports_drops():
    entries = [E(rb.URGENT, "U" * 40), E(rb.CHANGED, "C" * 40), E(rb.AMBIENT, "A" * 40)]
    out = rb.compose(entries, cap_chars=90)
    assert "U" * 40 in out and "C" * 40 in out
    assert "A" * 40 not in out
    assert "(+1 quiet)" in out


def test_stable_within_tier_order():
    out = rb.compose([E(rb.CHANGED, "first"), E(rb.CHANGED, "second")])
    assert out.index("first") < out.index("second")


# --- snapshot diff ---

def test_diff_reports_changed_keys_only():
    old = {"die:Vela|Blowtorch": "Ud8", "wounds:Roscar": "1", "load:Vela": "8/10"}
    new = {"die:Vela|Blowtorch": "Ud6", "wounds:Roscar": "1", "load:Vela": "8/10"}
    lines = rb.diff_lines(old, new)
    assert lines == ["Δ Vela|Blowtorch Ud8→Ud6"]


def test_diff_new_and_removed_keys():
    old = {"wounds:Roscar": "1"}
    new = {"wounds:Roscar": "2", "wounds:Vela": "1"}
    lines = rb.diff_lines(old, new)
    assert "Δ Roscar 1→2" in lines
    assert "Δ Vela none→1" in lines


def test_diff_metric_in_label_distinguishes_kinds():
    """Same PC, two metrics changed -> two textually distinct Δ lines
    (the metric name lives in the label half of the key)."""
    old = {"wounds:Vela wounds": "0", "load:Vela load": "4/13"}
    new = {"wounds:Vela wounds": "1", "load:Vela load": "6/13"}
    lines = rb.diff_lines(old, new)
    assert "Δ Vela wounds 0→1" in lines
    assert "Δ Vela load 4/13→6/13" in lines
    assert len(set(lines)) == 2


def test_diff_empty_old_snapshot_is_silent():
    """First turn of a session: no baseline -> no Δ spam."""
    assert rb.diff_lines({}, {"wounds:Vela": "1"}) == []
