# diseases.py
"""E2+E3 disease catalog (Crimson Hound pp.228-231). Pure data + builders,
sibling of conditions.py. Six organic and six nanomachine afflictions.

All afflictions carry a static Virulence rating (1-5); the save target number to
resist AND to treat is 10 + Virulence (R-E2a). Synths and Lithlings are immune
to organic diseases (the tool's force=True overrides). Nanomachine infections
(family='nanomachine') infect ALL creature types; augmented/synthetic bodies
save to resist at DISADVANTAGE (nano_resist_dis). build_disease_record routes
the condition shell through conditions.normalize_record so validation is
single-sourced.

Book authority: archive/rulebook-source/extraction/batch_08_locations_exotica.md
lines 2681-2787 (organic, pp.228-229) and lines 2795-2893 (nanomachine,
pp.236-237). ASCII-only (imported by server.py).
"""
import conditions as _cnd
import random as _random


def _roll_d6() -> int:
    """A single d6 (1-6). Wrapped so tests can monkeypatch it deterministically.
    Uses stdlib random directly: this is a pure data module and importing the
    server-side dice system would be circular (server.py imports diseases)."""
    return _random.randint(1, 6)


_D6_ABILITY = {1: "STR", 2: "DEX", 3: "CON", 4: "INT", 5: "PSY", 6: "EGO"}

# Species stems that are immune (substring match on a lowercased species string).
# The extraction spells the Lith ancestry both "Lithling" and "Lithing" - match
# the stable stem "lith".
IMMUNE_SPECIES_STEMS = ("synth", "lith")


DISEASES = {
    "Brain Coral": {
        "family": "organic",
        "virulence": 1,
        "tn": 11,
        "symptoms": ("An infestation of psychic fungus that sits over the neck "
                     "and cranium like a strange pink helmet. It boosts the "
                     "host's psychic ability at the cost of vitality."),
        "on_apply": {"roll": "d8", "ability_down": "STR", "ability_up": "PSY",
                     "text": ("roll d8: lose that much STR, gain an equal amount "
                              "of PSY (one-time)")},
        "cure": "antifungal medications will kill the infection, as will extreme cold.",
        "vector": ("cultivated for centuries by mystics; many Vaarnish psychics "
                   "infect themselves and can infect others, and the spores grow "
                   "wild in damp, sunless places."),
    },
    "Wrathworms": {
        "family": "organic",
        "virulence": 2,
        "tn": 12,
        "symptoms": ("A parasitic infestation of the brain and blood that spurs "
                     "the host to outrageous violence; tell-tale blood-red eyes."),
        "rider": ("infected characters deal AND receive doubled damage, and must "
                  "EGO save to retreat from combat (DM adjudicates both - the "
                  "engine does not automate the damage doubling)."),
        "cure": "de-worming tinctures, brewed by Vaarnish apothecaries and alchemists.",
        "vector": ("attacks by an infected creature (see Berserker) or contact "
                   "with their blood and flesh; some Cacklemaw clans infect "
                   "themselves and spread it with their bites."),
    },
    "Jellybones": {
        "family": "organic",
        "virulence": 2,
        "tn": 12,
        "symptoms": ("A degenerative disease of the skeletal system that softens "
                     "the bones and teeth toward a new, more flexible way of life."),
        "tick": {"cadence": "week", "abilities": {"STR": "d4", "CON": "d4"}},
        "rider": ("lose 1 point of base AV Defence; claw/bite attacks lose "
                  "potency (rubbery keratin); can squeeze through narrow gaps; "
                  "take halved damage from bludgeoning attacks (DM adjudicates "
                  "these riders)."),
        "cure": ("a good Stiff Drink - liquor, wet cement, and the crushed shards "
                 "of a Lithling."),
        "vector": "believed carried by soft, ooze-like creatures such as Doppelgellers.",
    },
    "Hivey Hump": {
        "family": "organic",
        "virulence": 3,
        "tn": 13,
        "symptoms": ("Sable Bees twist the host's flesh into a living hive; the "
                     "queen nests in the lungs and lays eggs in the chest cavity, "
                     "and the workers re-wire the nervous system."),
        "tick": {"cadence": "day", "abilities": {"EGO": "1"}},
        "transformation": ("At 0 EGO the victim becomes a Hiveyman NPC, a slave to "
                           "the bees - this is death-equivalent for the PC."),
        "rider": ("after 3 days of infection the bees can deal d4 unblockable "
                  "swarm damage to an opponent per combat round; this rises to d6 "
                  "after 7 days (DM unlocks/runs the swarm attack)."),
        "cure": ("fumigation - special herbs burned in the fumigate fires; all "
                 "desert cultures know the mixture."),
        "vector": ("a Sable Bee queen entering the airways, usually at night; "
                   "during swarming months anyone sleeping without netting has a "
                   "1-in-10 chance of infection per night. Hiveymen also infect; "
                   "after battle, secretly CON save each PC."),
    },
    "Labyrinth Pox": {
        "family": "organic",
        "virulence": 4,
        "tn": 14,
        "symptoms": ("A hypergeometric affliction from the flux-space behind "
                     "Vaarn; the body fills with manifold gouges and apertures of "
                     "infinite depth that multiply until the invalid is nothing "
                     "but glitching labyrinth space."),
        "tick": {"cadence": "week", "max_hp": "d8"},
        "on_max_hp_zero": {"death_in_days": 3},
        "stages": ("Stage 1 (apertures appear, coin-sized, infinite depth) -> "
                   "after 3 days Stage 2 (openings widen; -d8 max HP per week, "
                   "gaining equal inventory slots inside the hollowing body; lasts "
                   "until max HP is 0) -> Stage 3 (no longer a living being, a "
                   "collection of gateways; vanishes completely after 3 days)."),
        "transformation": ("At 0 max HP the victim enters Stage 3 and vanishes "
                           "completely after 3 days - death-equivalent."),
        "cure": ("excision of the afflicted flesh with a hypergeometric blade, or "
                 "exposure to Normality Fields or other anti-hypergeometry; "
                 "mundane antibiotics and surgery are useless. Seek planeyfolk."),
        "vector": ("contact with an infected person, or the bite of any "
                   "hypergeometric creature (insane planeyfolk are a common source)."),
    },
    "Lumenrot": {
        "family": "organic",
        "virulence": 5,
        "tn": 15,
        "symptoms": ("Microbes consume the flesh, creating a telltale green "
                     "phosphorescence; late-stage victims are lurid phantasms, "
                     "their skin a mass of luminous sores. Victims glow in the "
                     "dark and their flesh can be used as a light source."),
        "tick": {"cadence": "day", "abilities": {"CON": "1"},
                 "save": {"ability": "CON", "dc": 15}},
        "transformation": ("At 0 CON the victim dissolves into luminous slime - "
                           "death-equivalent."),
        "cure": ("Lumenrot was a weapon; the cure is a triad of three injection "
                 "syringes stocked by Vaarnish apothecaries. Ulfire light arrests "
                 "the spread but does not cure it."),
        "vector": ("dormant in infected water sources - a 1-in-6 chance that "
                   "stagnant water is infected; water with green phosphorescence "
                   "is best avoided. Contact with the glowing pus also forces a "
                   "CON save."),
    },
    "Goldencough": {
        "family": "nanomachine",
        "virulence": 1,
        "tn": 11,
        "slots": ["CON"],
        "symptoms": ("A nanomachine infestation rooting in the lungs, "
                     "filigreeing the airways with superconductive wire. The "
                     "infected cough out clouds of golden nanofibres that hang "
                     "in the air like solidified light; in extreme cases the "
                     "filaments protrude from the neck and face as golden beards."),
        "on_apply": {"roll": "d6", "ability_down": "CON",
                     "text": "roll d6: lose that much maximum CON (one-time)"},
        "coughing_fit": True,
        "rider": ("on ANY failed CON save the infected is overcome by a coughing "
                  "fit, taking d4 damage and expelling an infectious cloud of "
                  "golden thread (DM adjudicates the fit and the cloud)."),
        "cure": ("a smoke lodge - psychedelic herbs and alchemical unguents "
                 "burned over a day-long ceremony."),
        "vector": "inhaling the golden clouds coughed out by an infected character.",
    },
    "Janus Lenses": {
        "family": "nanomachine",
        "virulence": 2,
        "tn": 12,
        "slots": ["PSY"],
        "symptoms": ("A bolus of parasitic security cameras emerges from the base "
                     "of the host's neck, forcing the head forward to accommodate "
                     "the whirring cyst of recording devices grown behind it. The "
                     "host receives fragmentary flashes of the cameras' visual data."),
        "effects": {"hp_regain_half": True},
        "rider": ("the fragmentary visions make sleep hard - the host regains only "
                  "half their maximum HP from a Long Rest (engine-enforced). In "
                  "exchange they cannot be ambushed while asleep or from behind "
                  "(DM applies)."),
        "cure": "a trained cybernetics surgeon can excise the cameras and prevent regrowth.",
        "vector": ("the touch of a Maladaptor, or contact with an infected "
                   "character's blood."),
    },
    "Usurper Arm": {
        "family": "nanomachine",
        "virulence": 2,
        "tn": 12,
        "slots": ["DEX", "EGO"],
        "symptoms": ("A parasitic cyborg arm grows from an unwanted location on "
                     "the body. Usually dormant, it can awaken and turn unruly."),
        "locale_roll": {"roll": "d6",
                        "table": {1: "below the right arm", 2: "below the left arm",
                                  3: "at the right hip", 4: "at the left hip",
                                  5: "protruding from the back",
                                  6: "jutting from the centre of the chest"}},
        "rider": ("combat lever: the host may call upon the Arm, making an EGO "
                  "save to briefly dominate it. Success = one extra one-hand "
                  "attack that round; failure = the limb attacks the host and "
                  "stays hostile for the rest of combat (the limb is Level 2, AV "
                  "17, deals d6; attacks that MISS the limb hit the host instead). "
                  "DM runs the limb as an NPC."),
        "cure": ("a trained cybernetics surgeon can excise the Arm and prevent "
                 "regrowth; an untrained amputation lets it regrow from the trace "
                 "nanomachinery left in the stump."),
        "vector": ("the touch of a Maladaptor, or contact with an infected "
                   "character's blood."),
    },
    "Dreamcage": {
        "family": "nanomachine",
        "virulence": 3,
        "tn": 13,
        "slots": ["INT", "PSY"],
        "symptoms": ("The ancients recorded nine divine punishments for those who "
                     "denied the Titans' apotheosis; the Dreamcage was one, "
                     "severing the afflicted from the world of dreams. The "
                     "dreamless mind frays into a sleepless wasting."),
        "effects": {"no_hp_regain": True},
        "tick": {"cadence": "day", "abilities": {"PSY": "1"}},
        "transformation": ("At 0 PSY the dreamless mind collapses and the victim "
                           "becomes a hollow somnambulist - death-equivalent for "
                           "the PC."),
        "source": ("R-E3a (Joe homebrew): stats are book-true (Virulence 3, slots "
                   "INT+PSY) but the preview PDF truncates the effects. The "
                   "sleepless-wasting completion - no HP regain, -1 PSY per day, "
                   "somnambulist at PSY 0, cure CON vs 13 - is Joe's ruling."),
        "cure": "a trained cybernetics surgeon (per R-E3a).",
        "vector": ("the touch of a Maladaptor, or contact with an infected "
                   "character's blood."),
    },
    "Fabricator Stoma": {
        "family": "nanomachine",
        "virulence": 4,
        "tn": 14,
        "slots": ["STR", "CON"],
        "symptoms": ("The host's digestive tract is hijacked into a biomechanical "
                     "fabrication chamber; nutrients are diverted into a parasitic "
                     "assembly line that extrudes a finished product through a "
                     "fissure on the abdomen each morning."),
        "effects": {"double_rations": True},
        "extrude_roll": {"roll": "d6",
                         "table": {1: "a white plasteel picnic plate",
                                   2: "a gaudy eight-inch idol of a long-dead Autarch",
                                   3: "spare parts for an obsolete laspistol",
                                   4: "a clear memory crystal containing no data",
                                   5: ("a polished black orb with negative weight (it "
                                       "falls upwards into the sky)"),
                                   6: "a complete set of gaming dice"}},
        "rider": ("the metabolic hijacking doubles the host's appetite - they "
                  "must consume double rations each day or become Deprived "
                  "(engine-enforced). Each morning the same mass-produced object "
                  "is painfully extruded through the stoma."),
        "cure": ("an experienced cybernetics surgeon can remove the Stoma, but "
                 "the operation is not cheap."),
        "vector": ("the touch of a Maladaptor, or contact with an infected "
                   "character's blood or stomach acid."),
    },
    "The Gitch": {
        "family": "nanomachine",
        "virulence": 5,
        "tn": 15,
        "slots": "d6",
        "gitch": True,
        "symptoms": ("Sometimes called Creeping Crystals - parasitic nanotech "
                     "that infects the flesh and constructs painful fractal "
                     "growths beneath the dermis, presumed a remnant weapon of "
                     "the Long Ago."),
        "tick": {"cadence": "day", "save": {"ability": "CON", "dc": 15}},
        "transformation": ("When every available item slot is filled with Gitch "
                           "crystals the host becomes a mindless Gitchghast - "
                           "death-equivalent for the PC."),
        "rider": ("at the start of each day the PC makes a CON save (engine-rolled "
                  "during advance_day); on a failure they mark one item slot with "
                  "a Gitch Crystals wound. Per filled slot: +1 Armour defence and "
                  "-1 to the infected ability (engine-enforced). Characters with "
                  "visible infections are barred from most settlements (DM)."),
        "cure": ("a Gitch Doctor performs crystal debridement - one day per "
                 "occupied slot (DM-managed multi-day), then the treat save "
                 "clears it and the crystal wounds heal via the wound-heal flow."),
        "vector": ("physical contact with an infected character, inhaling "
                   "Gitch-dust, or being bitten by a Gitchghast."),
    },
}


def disease_susceptible_pc(char, family="organic") -> bool:
    """Can this PC contract a disease of the given family?

    Organic afflictions (family='organic'): Synths and Lithlings are immune
    (the immune stems); force=True at the tool overrides for 'otherwise noted'
    cases. Nanomachine infections (family='nanomachine') infect ALL creature
    types - the organic immunity does NOT bar them (book pp.236-237: 'they can
    infect all creature types'). Augmented/synthetic bodies instead SAVE to
    resist with DIS (see nano_resist_dis), which the tool surfaces.
    """
    if not isinstance(char, dict):
        return True
    if str(family).strip().lower() == "nanomachine":
        return True
    species = (char.get("species") or "").strip().lower()
    if any(stem in species for stem in IMMUNE_SPECIES_STEMS):
        return False
    return True


def nano_resist_dis(char) -> bool:
    """True when a PC resists a nanomachine infestation at DISADVANTAGE: the
    species stem is synth/lith OR the sheet carries any installed augmentation
    (a non-None value in char['augmentations']). Book pp.236-237: 'Synths and
    characters with cybernetic implants Save to resist nanomachine infestations
    with DIS.' The resist save stays player-rolled; the tool surfaces the DIS."""
    if not isinstance(char, dict):
        return False
    if char.get("synthetic_type"):
        return True
    species = (char.get("species") or "").strip().lower()
    if any(stem in species for stem in IMMUNE_SPECIES_STEMS):
        return True
    augs = char.get("augmentations")
    if isinstance(augs, dict):
        for v in augs.values():
            # Infection markers (written by the disease tool) must NOT count as
            # implants for the DIS check - only real cybernetics trigger it.
            if v is not None and not (isinstance(v, dict) and v.get("infection")):
                return True
    return False


def build_disease_record(name, day):
    """Mint a stored condition record for a named disease, validated through
    conditions.normalize_record (single-source validation).

    Returns (record, prose_push, "") on success, or (None, None, error) for an
    unknown disease or a validation failure. prose_push is a list of lines the
    tool surfaces (symptoms, cure, transformation/stage riders).
    """
    d = DISEASES.get(name)
    if d is None:
        opts = ", ".join(sorted(DISEASES))
        return None, None, f"Unknown disease '{name}'. Known: {opts}."
    v = d["virulence"]
    family = d.get("family", "organic")
    cause = "nanomachine" if family == "nanomachine" else "disease"
    req = {
        "name": name,
        "cause": cause,
        "save_to_end": {"ability": "CON", "dc": 10 + v},
    }
    gitch_slot = None
    if "tick" in d:
        tick = dict(d["tick"])
        # The Gitch's tick is save-only in the catalog; mint the rolled-slot
        # -1 drain so the record survives normalize_record unchanged (NO grammar
        # change). The slot is a single d6 -> STR..EGO.
        if d.get("gitch") and d.get("slots") == "d6" and "abilities" not in tick:
            gitch_slot = _D6_ABILITY[_roll_d6()]
            tick["abilities"] = {gitch_slot: "1"}
        req["tick"] = tick
    if "on_max_hp_zero" in d:
        req["on_max_hp_zero"] = dict(d["on_max_hp_zero"])
    if "effects" in d and isinstance(d["effects"], dict):
        req["effects"] = dict(d["effects"])
    # apply-time d6 flavor rolls (Usurper Arm locale, Stoma extruded object) -
    # rolled ONCE at mint, stamped into the note so the result persists
    d6_rolled = []
    for roll_key, label in (("locale_roll", "grows"),
                            ("extrude_roll", "extrudes")):
        tbl = d.get(roll_key)
        if isinstance(tbl, dict) and isinstance(tbl.get("table"), dict):
            result = tbl["table"].get(_roll_d6())
            if result:
                d6_rolled.append(f"{label.upper()}: {result}")
    # the 'note' carries the headline rider(s) the engine cannot fully enforce
    note_bits = list(d6_rolled)
    if d.get("rider"):
        note_bits.append(d["rider"])
    if d.get("transformation"):
        note_bits.append(d["transformation"])
    if d.get("source"):
        note_bits.append(d["source"])
    if note_bits:
        req["note"] = " ".join(note_bits)
    rec, err = _cnd.normalize_record(req, day=day)
    if err:
        return None, None, f"{name}: builder produced an invalid record: {err}"
    # Stamp catalog metadata the normalized record does not carry but the
    # advance_day Gitch consumer needs (gitch flag rides the stored record).
    if d.get("gitch"):
        rec["gitch"] = True
    push = [
        f"{name} (Virulence {v}, save TN {d['tn']}): {d['symptoms']}",
        f"Cure: {d['cure']}",
    ]
    if d.get("source"):
        push.append(f"SOURCE: {d['source']}")
    if gitch_slot:
        push.append(f"Gitch slot rolled: {gitch_slot} (the infected ability; "
                    f"each crystal drains -1 {gitch_slot}, grants +1 AV).")
    for line in d6_rolled:
        push.append(f"d6 rolled - {line.lower()} (stamped on the record).")
    if d.get("stages"):
        push.append(f"Stages: {d['stages']}")
    return rec, push, ""
