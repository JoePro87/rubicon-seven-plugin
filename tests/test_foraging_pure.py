"""S2 pure helpers: yield resolution, text-dice rendering, carried credit math."""
import survival as sv


def fixed(n):
    """roll_fn stub returning a constant."""
    return lambda notation: n


def test_resolve_yield_flat_and_dice():
    out = sv.resolve_yield({"water": "d8", "food": 3}, fixed(5))
    assert out["water"] == 5 and out["food"] == 3
    assert out["detail"] == ["water d8=5"]


def test_resolve_yield_omits_zero_keys():
    out = sv.resolve_yield({"food": "2d12"}, fixed(13))
    assert out == {"water": 0, "food": 13, "detail": ["food 2d12=13"]}


def test_resolve_yield_clamps_negative_to_zero():
    # A hand-authored table mistake must never become a hidden debit.
    out = sv.resolve_yield({"water": -1}, fixed(5))
    assert out == {"water": 0, "food": 0, "detail": []}


def test_roll_dice_in_text_annotates_each_expression():
    txt = "You find d6 Glass Tigers guarding 2d4 camels."
    assert sv.roll_dice_in_text(txt, fixed(4)) == \
        "You find d6=4 Glass Tigers guarding 2d4=4 camels."


def test_roll_dice_in_text_ignores_non_dice_words():
    assert sv.roll_dice_in_text("a dead Zorse", fixed(9)) == "a dead Zorse"
    assert sv.roll_dice_in_text("rifles (Ud10)", fixed(9)) == "rifles (Ud10)"


def test_roll_dice_in_text_uppercase_D_is_dice():
    # Uppercase D IS book dice notation; matching it is deliberate (CH row 63).
    assert sv.roll_dice_in_text("D4 enormous black eggs", fixed(2)) == \
        "d4=2 enormous black eggs"


def _char(items):
    return {"name": "Vela", "inventory": {"carried": list(items)}}


def test_adjust_carried_tops_up_then_mints():
    c = _char([{"name": "Water Rations", "ration_type": "water", "rations": 2, "slots": 1}])
    notes = sv.adjust_carried(c, water=5)
    items = c["inventory"]["carried"]
    assert [i["rations"] for i in items if i["ration_type"] == "water"] == [3, 3, 1]
    assert all(i["slots"] == 1 for i in items)
    assert notes == ["+5 water"]


def test_adjust_carried_debit_drains_and_deletes_empties():
    c = _char([
        {"name": "Water Rations", "ration_type": "water", "rations": 3, "slots": 1},
        {"name": "Water Rations", "ration_type": "water", "rations": 1, "slots": 1},
    ])
    notes = sv.adjust_carried(c, water=-4)
    assert [i for i in c["inventory"]["carried"] if i.get("ration_type") == "water"] == []
    assert notes == ["-4 water"]


def test_adjust_carried_debit_caps_at_zero_and_says_so():
    c = _char([{"name": "Food Rations", "ration_type": "food", "rations": 2, "slots": 1}])
    notes = sv.adjust_carried(c, food=-5)
    assert c["inventory"]["carried"] == []
    assert notes == ["-2 food (only that many on hand)"]


def test_adjust_carried_water_tokens_currency_untouched():
    # The S1 rule: "Water Tokens" are CURRENCY (no ration_type) — never drained.
    c = _char([{"name": "Water Tokens", "amount": 400, "slots": 0}])
    sv.adjust_carried(c, water=-1)
    assert c["inventory"]["carried"][0]["amount"] == 400
