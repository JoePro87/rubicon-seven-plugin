import server


def test_ud_to_chain():
    assert server._usage_to_chain("Ud8") == "d8"
    assert server._usage_to_chain("ud20") == "d20"
    assert server._usage_to_chain("Ud4") == "d4"
    assert server._usage_to_chain("Expended") == "cured"
    assert server._usage_to_chain("Ud0") == "cured"
    assert server._usage_to_chain("") == "cured"
    assert server._usage_to_chain(None) == "cured"


def test_chain_to_ud():
    assert server._usage_to_ammo("d8") == "Ud8"
    assert server._usage_to_ammo("d20") == "Ud20"
    assert server._usage_to_ammo("cured") == "Expended"
    assert server._usage_to_ammo(None) == "Expended"


def test_weapon_has_tag_engine_and_prose():
    assert server._weapon_has_tag({"engine_tags": ["fungal"]}, "fungal") is True
    assert server._weapon_has_tag(
        {"tags": ["Fungal (regains a step when fed)"]}, "fungal") is True
    assert server._weapon_has_tag(
        {"tags": ["Parasitic (never needs reload)"]}, "parasitic") is True
    assert server._weapon_has_tag({"tags": ["Luminous"]}, "fungal") is False
    assert server._weapon_has_tag({}, "fungal") is False


def test_usage_applies():
    assert server._usage_applies({"range": "ranged", "ammo": "Ud8"}) is True
    assert server._usage_applies({"range": "ranged", "ammo": "Expended"}) is True
    assert server._usage_applies({"range": "melee"}) is False
    assert server._usage_applies({"range": "ranged"}) is False
    assert server._usage_applies({"name": "Sword", "damage": "d8"}) is False


def test_usage_is_parasitic_fungal():
    assert server._usage_is_parasitic({"engine_tags": ["parasitic"]}) is True
    assert server._usage_is_fungal({"tags": ["Fungal"]}) is True
    assert server._usage_is_parasitic({"tags": ["Luminous"]}) is False


def test_usage_is_expended():
    assert server._usage_is_expended({"range": "ranged", "ammo": "Expended"}) is True
    assert server._usage_is_expended({"range": "ranged", "ammo": "Ud4"}) is False
    assert server._usage_is_expended({"range": "melee"}) is False


def test_usage_ammo_max_lazy():
    assert server._usage_ammo_max({"ammo": "Ud8", "ammo_max": "Ud10"}) == "Ud10"
    assert server._usage_ammo_max({"ammo": "Ud8"}) == "Ud8"
    assert server._usage_ammo_max({}) == "Expended"


def _mk_pc_weapon(monkeypatch, **weapon_fields):
    """Stage one PC carrying one ranged weapon; patch the loaders. Returns
    (char, saved) where saved captures _save_single_character writes."""
    weapon = {"name": "Railgun", "type": "ranged_weapon", "damage": "d12",
              "range": "ranged", "ammo": "Ud6", "ammo_max": "Ud6", **weapon_fields}
    char = {"name": "Roscar", "hp": {"current": 23, "max": 23},
            "inventory": {"carried": [weapon]},
            "attacks": [{"name": "Railgun", "damage": "3d12", "ammo": "Ud6"}]}
    data = {"meta": {}, "characters": {"roscar": char}}
    monkeypatch.setattr(server, "_load_characters", lambda: (data, None))
    saved = {}
    monkeypatch.setattr(server, "_save_single_character",
                        lambda k, c, d=None: saved.update({k: c}))
    return char, saved


def test_usage_resolve_and_get(monkeypatch):
    _ = _mk_pc_weapon(monkeypatch)
    h = server._usage_resolve("roscar", "Railgun")
    assert h["key"] == "roscar"
    assert server._usage_get(h) == "Ud6"


def test_usage_resolve_weapon_not_found(monkeypatch):
    _mk_pc_weapon(monkeypatch)
    assert isinstance(server._usage_resolve("roscar", "Bagpipes"), str)


def test_usage_set_writes_carried_and_mirror(monkeypatch):
    char, saved = _mk_pc_weapon(monkeypatch)
    h = server._usage_resolve("roscar", "Railgun")
    server._usage_set(h, "Ud4")
    assert char["inventory"]["carried"][0]["ammo"] == "Ud4"     # authoritative
    assert char["attacks"][0]["ammo"] == "Ud4"                  # mirror synced
    assert saved["roscar"]["inventory"]["carried"][0]["ammo"] == "Ud4"  # persisted


def test_usage_resolve_lazy_inits_ammo_max(monkeypatch):
    _mk_pc_weapon(monkeypatch, ammo_max=None)   # simulate pre-backfill weapon
    h = server._usage_resolve("roscar", "Railgun")
    assert h["weapon"].get("ammo_max") == "Ud6"  # lazy-init from current ammo


def test_usage_carried_ammo(monkeypatch):
    char, _ = _mk_pc_weapon(monkeypatch)
    char["inventory"]["carried"].append(
        {"name": "Slug Canister", "type": "ammo", "ammo": "Ud10"})
    assert "Slug Canister" in server._usage_carried_ammo(char)


def test_usage_set_no_attacks_mirror(monkeypatch):
    char, _ = _mk_pc_weapon(monkeypatch)
    char["attacks"] = []                     # no mirror entry for this weapon
    h = server._usage_resolve("roscar", "Railgun")
    server._usage_set(h, "Ud4")
    assert char["inventory"]["carried"][0]["ammo"] == "Ud4"   # authoritative write still lands


def test_deplete_roll_steps_down_on_1_2(monkeypatch):
    char, _ = _mk_pc_weapon(monkeypatch)
    h = server._usage_resolve("roscar", "Railgun")
    out = server._usage_deplete_roll(h, rng=lambda a, b: 2)   # force a 2
    assert char["inventory"]["carried"][0]["ammo"] == "Ud4"   # Ud6 -> Ud4
    assert "depletes" in out


def test_deplete_roll_holds_on_3_plus(monkeypatch):
    char, _ = _mk_pc_weapon(monkeypatch)
    h = server._usage_resolve("roscar", "Railgun")
    server._usage_deplete_roll(h, rng=lambda a, b: 5)
    assert char["inventory"]["carried"][0]["ammo"] == "Ud6"   # unchanged


def test_deplete_roll_ud4_to_expended(monkeypatch):
    char, _ = _mk_pc_weapon(monkeypatch, ammo="Ud4", ammo_max="Ud4")
    h = server._usage_resolve("roscar", "Railgun")
    server._usage_deplete_roll(h, rng=lambda a, b: 1)
    assert char["inventory"]["carried"][0]["ammo"] == "Expended"


def test_deplete_roll_parasitic_never_depletes(monkeypatch):
    char, _ = _mk_pc_weapon(monkeypatch, tags=["Parasitic"])
    h = server._usage_resolve("roscar", "Railgun")
    out = server._usage_deplete_roll(h, rng=lambda a, b: 1)   # would deplete if rolled
    assert char["inventory"]["carried"][0]["ammo"] == "Ud6"   # untouched
    assert "Parasitic" in out


def test_feed_steps_up_capped(monkeypatch):
    char, _ = _mk_pc_weapon(monkeypatch, ammo="Ud4", ammo_max="Ud8", tags=["Fungal"])
    h = server._usage_resolve("roscar", "Railgun")
    server._usage_feed(h)
    assert char["inventory"]["carried"][0]["ammo"] == "Ud6"   # Ud4 -> Ud6
    server._usage_feed(h)
    assert char["inventory"]["carried"][0]["ammo"] == "Ud8"   # -> Ud8 (== max)
    server._usage_feed(h)
    assert char["inventory"]["carried"][0]["ammo"] == "Ud8"   # capped, no climb


def test_feed_non_fungal_errors(monkeypatch):
    _mk_pc_weapon(monkeypatch)
    h = server._usage_resolve("roscar", "Railgun")
    out = server._usage_feed(h)
    assert "not Fungal" in out


def test_reload_defaults_to_max(monkeypatch):
    char, _ = _mk_pc_weapon(monkeypatch, ammo="Expended", ammo_max="Ud6")
    h = server._usage_resolve("roscar", "Railgun")
    out = server._usage_reload(h)
    assert char["inventory"]["carried"][0]["ammo"] == "Ud6"
    assert "reloaded" in out.lower()


def test_reload_caps_at_max(monkeypatch):
    char, _ = _mk_pc_weapon(monkeypatch, ammo="Ud4", ammo_max="Ud6")
    h = server._usage_resolve("roscar", "Railgun")
    server._usage_reload(h, to="Ud20")     # over-fill request
    assert char["inventory"]["carried"][0]["ammo"] == "Ud6"   # capped


def test_reload_cannot_reload_note_warns(monkeypatch):
    char, _ = _mk_pc_weapon(monkeypatch, ammo="Expended", ammo_max="Ud6",
                            ammo_note="Cannot be reloaded")
    h = server._usage_resolve("roscar", "Railgun")
    out = server._usage_reload(h)            # no explicit `to`
    assert char["inventory"]["carried"][0]["ammo"] == "Expended"   # refused
    assert "Cannot be reloaded" in out


def test_feed_above_cap_no_downgrade(monkeypatch):
    char, _ = _mk_pc_weapon(monkeypatch, ammo="Ud12", ammo_max="Ud8", tags=["Fungal"])
    h = server._usage_resolve("roscar", "Railgun")
    out = server._usage_feed(h)
    assert char["inventory"]["carried"][0]["ammo"] == "Ud12"   # never downgraded
    assert "already at max" in out


def test_reload_junk_to_rejected(monkeypatch):
    char, _ = _mk_pc_weapon(monkeypatch, ammo="Ud4", ammo_max="Ud6")
    h = server._usage_resolve("roscar", "Railgun")
    out = server._usage_reload(h, to="banana")
    assert char["inventory"]["carried"][0]["ammo"] == "Ud4"        # unchanged, not expended
    assert "not a valid ammo die" in out.lower()


def test_reload_cannot_reload_override(monkeypatch):
    char, _ = _mk_pc_weapon(monkeypatch, ammo="Expended", ammo_max="Ud6",
                            ammo_note="Cannot be reloaded")
    h = server._usage_resolve("roscar", "Railgun")
    out = server._usage_reload(h, to="Ud6")    # explicit DM override bypasses the warning
    assert char["inventory"]["carried"][0]["ammo"] == "Ud6"        # override succeeds


def test_dispatch_status_single_weapon(monkeypatch):
    _mk_pc_weapon(monkeypatch)
    out = server._usage_dispatch("status", character="roscar")
    assert "Railgun" in out and "Ud6" in out


def test_dispatch_status_parasitic_shows_infinity(monkeypatch):
    _mk_pc_weapon(monkeypatch, tags=["Parasitic"])
    out = server._usage_dispatch("status", character="roscar")
    assert "∞" in out or "Parasitic" in out   # ∞ or the word


def test_dispatch_roll(monkeypatch):
    char, _ = _mk_pc_weapon(monkeypatch)
    monkeypatch.setattr(server.random, "randint", lambda a, b: 2)
    out = server._usage_dispatch("roll", character="roscar", weapon="Railgun")
    assert "depletes" in out
    assert char["inventory"]["carried"][0]["ammo"] == "Ud4"


def test_dispatch_reload(monkeypatch):
    char, _ = _mk_pc_weapon(monkeypatch, ammo="Expended")
    out = server._usage_dispatch("reload", character="roscar", weapon="Railgun")
    assert char["inventory"]["carried"][0]["ammo"] == "Ud6"


def test_dispatch_feed(monkeypatch):
    char, _ = _mk_pc_weapon(monkeypatch, ammo="Ud4", ammo_max="Ud8", tags=["Fungal"])
    out = server._usage_dispatch("feed", character="roscar", weapon="Railgun")
    assert char["inventory"]["carried"][0]["ammo"] == "Ud6"


def test_dispatch_unknown_action(monkeypatch):
    _mk_pc_weapon(monkeypatch)
    assert "unknown" in server._usage_dispatch("frobnicate", character="roscar").lower()


def test_usage_tool_registered():
    assert "usage" in server.TOOL_TAGS   # server.py: `from tool_tags import ... TOOL_TAGS`


def test_dispatch_status_character_not_found(monkeypatch):
    _mk_pc_weapon(monkeypatch)
    out = server._usage_dispatch("status", character="nobody")
    assert "no character named" in out.lower()


def test_dispatch_status_named_no_usage_weapons(monkeypatch):
    char, _ = _mk_pc_weapon(monkeypatch)
    char["inventory"]["carried"] = []          # strip the weapon
    out = server._usage_dispatch("status", character="roscar")
    # New LOAD-format status: names the character via the LOAD line, and lists
    # NO depletable item lines (no 'use' call surfaced) when none are carried.
    assert "LOAD" in out
    assert "roscar" in out.lower()              # names the specific character
    assert "action='use'" not in out           # no depletables -> no item lines
