"""Mystic Gift generation + Gleam Test data (Crimson Hound printed pp. 47-50).

Transcribed directly from the preview PDF (pdfplumber indices 53-56) on 2026-06-12;
the text-extraction batches garble these pages, so the PDF is the source of truth.
Verification record: engine memory project_g1_verification.md.

Table geometry (book-literal): Quality and Form are each 20 rows x 4 column-bands
(d20 bands 1-5 / 6-10 / 11-15 / 16-20). A gift name = one roll on each table, and
each table roll is TWO d20s: column d20 picks the band, row d20 picks the row.
The book gives only the NAME - players + referee collectively agree the effect.
"""

# --- Gift Quality (p.48 top; footer label "Gift quality") ---
# Keys are the column-band d20 ranges; each list is rows 1-20 in order.
GIFT_QUALITY = {
    (1, 5): ["Bashing", "Binding", "Blinding", "Burning", "Choking", "Consuming",
             "Corroding", "Crushing", "Deafening", "Detonating", "Disintegrating",
             "Draining", "Electrifying", "Excruciating", "Freezing", "Withering",
             "Impaling", "Imprisoning", "Infecting", "Liquefying"],
    (6, 10): ["Absorbing", "Armouring", "Banishing", "Concealing", "Countering",
              "Curing", "Cushioning", "Deflecting", "Disappearing", "Disarming",
              "Disguising", "Entangling", "Warding", "Guarding", "Shielding",
              "Healing", "Hindering", "Invigorating", "Mending", "Nullifying"],
    (11, 15): ["Adhering", "Addicting", "Blackening", "Blossoming", "Cacophonous",
               "Dazzling", "Dividing", "Duplicating", "Evolving", "Extinguishing",
               "Fusing", "Ghostly", "Grasping", "Inflating", "Inverting",
               "Invulnerable", "Prismatic", "Transmuting", "Teleporting", "Whispering"],
    (16, 20): ["Bewildering", "Calming", "Charming", "Commanding", "Enticing",
               "Horrifying", "Hysterical", "Maddening", "Mesmerising", "Mocking",
               "Revealing", "Whirling", "Slithering", "Dreaming", "Encoding",
               "Enraging", "Pulsing", "Saddening", "Scrying", "Subtle"],
}

# --- Gift Form (p.48 bottom; footer label "Gift form") ---
# "Stone" appears in both the 1-5 and 6-10 bands - printed that way in the book.
GIFT_FORM = {
    (1, 5): ["Claw", "Clay", "Crystal", "Flesh", "Mould", "Flower", "Fungus",
             "Fruit", "Glass", "Ice", "Iron", "Ivory", "Leaf", "Stone", "Moss",
             "Hand", "Gaze", "Roots", "Beam", "Cascade"],
    (6, 10): ["Salt", "Sand", "Silk", "Skin", "Soil", "Stone", "Sugar", "Ray",
              "Thorn", "Vine", "Rust", "Void", "Ash", "Blizzard", "Breath",
              "Cloud", "Dust", "Fog", "Mist", "Fragrance"],
    (11, 15): ["Hail", "Haze", "Wind", "Shard", "Miasma", "Perfume", "Pollen",
               "Plague", "Rain", "Sandstorm", "Orb", "Bolt", "Snow", "Smoke",
               "Arc", "Sphere", "Shield", "Helix", "Web", "Wound"],
    (16, 20): ["Chaos", "Cold", "Darkness", "Prism", "Distortion", "Dream",
               "River", "Fire", "Frost", "Ghost", "Gravity", "Growth", "Song",
               "Voice", "Light", "Lightning", "Thread", "Parasite", "Paradox",
               "Entropy"],
}

# --- Sample gifts (p.47): d20 -> (SOURCE OF POWER, GIFT) ---
# Row 8 is printed "Parastic Spirit Entity" - normalized to "Parasitic".
# Row 12 column-wrap resolved by word x-positions in the PDF (source column x~290,
# gift column x~375): source = Devouring Memories, gift = Inhuman Speed.
GIFT_SAMPLE = {
    1: ("Mystical Crystal", "Telekinesis"),
    2: ("Ritual Cannibalism", "Pyrokinesis"),
    3: ("Psychoactive Fungus", "Telepathy"),
    4: ("Nanomachine Infection", "Memory Extraction"),
    5: ("Irradiated at Birth", "Mind Control"),
    6: ("Meditation", "Invisibility"),
    7: ("Dream Quest", "Astral Projection"),
    8: ("Parasitic Spirit Entity", "Healing Hands"),
    9: ("Mental Mutation", "Paralysing Touch"),
    10: ("Addictive Rare Drug", "Eye Lasers"),
    11: ("Brain Implants", "Augury"),
    12: ("Devouring Memories", "Inhuman Speed"),
    13: ("Brain Surgery", "Second Sight"),
    14: ("Secret Religion", "Force Wall"),
    15: ("Ancient Mask", "Generate Lightning"),
    16: ("Cursed Ring", "Ultrasonic Scream"),
    17: ("Born During Eclipse", "Create Paradox-Clone"),
    18: ("Found Weird Orb", "Summon Orbs"),
    19: ("Beheld Azathoth, the Daemon Sultan", "Cryokinesis"),
    20: ("Studied in Lost Archives", "Induce Sleep"),
}

# --- Gleam Test (p.50): d20 + Gleam -> outcome. 1-15 = nothing; 35+ = cap. ---
# Threat rows carry structured clock metadata so the engine can wind a World Tick
# thread clock: count_die rolls how many arrive (None = fixed), arrival_die rolls
# the days until arrival (None = immediate/within the hour).
GLEAM_TEST = {
    16: {"text": "The PC is granted a brief vision from the intangible psychic aether. "
                 "A single person or entity relevant to their current quest can be glimpsed."},
    17: {"text": "The PC unwittingly broadcasts into the intangible psychic aether. A single "
                 "person or entity relevant to their current quest glimpses them."},
    18: {"text": "The PC detects an ancient cry for help, encoded in the psychic aether. "
                 "It contains coordinates towards a location 2d6 days away."},
    19: {"text": "The PC detects some ancient line of psychic force, which leads towards a "
                 "nearby locus point or shrine. Here a new randomly-rolled Mystic Gift can be obtained."},
    20: {"text": "d4 Seekers of Eyeless Wisdom have sensed the character, and set out to "
                 "convert them to their faith. They arrive within d6 days.",
         "threat": "Seekers of Eyeless Wisdom (conversion)", "count_die": 4, "arrival_die": 6},
    21: {"text": "The PC is granted a prescient dream. They may roll 1d20 and record the "
                 "number. At any time during the next in-game week they may replace a dice "
                 "result with this number, acting upon their prophetic dream."},
    22: {"text": "The PC is granted an extended vision from the intangible psychic aether. "
                 "A single person or entity relevant to their current quest can be seen in "
                 "detail, along with their surroundings."},
    23: {"text": "The PC unwittingly broadcasts strongly into the intangible psychic aether. "
                 "A single person or entity relevant to their current quest sees the PC in "
                 "detail, along with their immediate surroundings. This entity begins to seek "
                 "the PC if they have not met already."},
    24: {"text": "A Lesser Quantum Daemon has sensed the character, and now moves through "
                 "the halls of the multiverse to contact them in their dreams. Roll for the "
                 "daemon's form and motivations.",
         "threat": "Lesser Quantum Daemon (dream contact)", "count_die": None, "arrival_die": None},
    25: {"text": "The PC is contacted at great distance by a seemingly-benevolent mass mind, "
                 "which seeks new members. It does not know their exact location."},
    26: {"text": "The PC is contacted at great distance by a kind of psychic spam-ad "
                 "transmitter, which floods their consciousness and dreams with jarring and "
                 "bizarre product infomercials."},
    27: {"text": "d6 Seekers of Eyeless Wisdom have sensed the character, and set out to "
                 "forcefully convert the PC to their blind faith. They arrive in d6 days.",
         "threat": "Seekers of Eyeless Wisdom (forceful conversion)", "count_die": 6, "arrival_die": 6},
    28: {"text": "An alternate universe version of the PC has detected them, and begins "
                 "trying to insinuate themselves into the PC's reality. Their motives for "
                 "doing so are unclear."},
    29: {"text": "The PC emits a psychic scream so loud that all surrounding creatures are "
                 "aware of the PC's location. Roll on the local encounter table: whatever the "
                 "result, they know the party's position and will arrive within an hour.",
         "threat": "psychic scream (local encounter)", "count_die": None, "arrival_die": None},
    30: {"text": "A hungry Psyche Leech has caught sight of the character and will attack "
                 "within d6 days.",
         "threat": "Psyche Leech (attack)", "count_die": None, "arrival_die": 6},
    31: {"text": "The Children of the Darkling Sun have sensed the character, and dispatch "
                 "emissaries to forcibly convert them to the faith. They arrive in d6 days.",
         "threat": "Children of the Darkling Sun emissaries", "count_die": None, "arrival_die": 6},
    32: {"text": "A Greater Quantum Daemon has sensed the character, and now moves through "
                 "the halls of the multiverse to contact them in their dreams. Roll for the "
                 "daemon's form and motivations.",
         "threat": "Greater Quantum Daemon (dream contact)", "count_die": None, "arrival_die": None},
    33: {"text": "d10 Seekers of Eyeless Wisdom have sensed the character, and fearfully set "
                 "out to devour and absorb their mind before the PC can prove a threat to the "
                 "sect. They attack within d6 days.",
         "threat": "Seekers of Eyeless Wisdom (devour)", "count_die": 10, "arrival_die": 6},
    34: {"text": "An Extradimensional Mystic Hunter teleports into Vaarn and begins to seek "
                 "the PC. It will find them in d6 days.",
         "threat": "Extradimensional Mystic Hunter (seeking)", "count_die": None, "arrival_die": 6},
    35: {"text": "An Extradimensional Mystic Hunter teleports into Vaarn and immediately "
                 "attacks the PC, seeking to absorb their mind.",
         "threat": "Extradimensional Mystic Hunter (IMMEDIATE ATTACK)",
         "count_die": None, "arrival_die": None},
}

GLEAM_TEST_CADENCE_DAYS = 7  # "at the start of each adventuring week" (p.49)


def _band_entry(table, column_roll, row_roll):
    for (lo, hi), rows in table.items():
        if lo <= column_roll <= hi:
            return rows[row_roll - 1]
    raise ValueError(f"column roll {column_roll} outside d20")


def roll_gift_name(rng, quality_rolls=None, form_rolls=None):
    """Roll a gift name: (column d20, row d20) on Quality, then on Form.

    rng is randint-shaped. quality_rolls/form_rolls force (column, row) pairs
    for tests/replays. Returns (name, detail_dict).
    """
    q_col, q_row = quality_rolls or (rng(1, 20), rng(1, 20))
    f_col, f_row = form_rolls or (rng(1, 20), rng(1, 20))
    quality = _band_entry(GIFT_QUALITY, q_col, q_row)
    form = _band_entry(GIFT_FORM, f_col, f_row)
    return f"{quality} {form}", {
        "quality": quality, "form": form,
        "quality_rolls": (q_col, q_row), "form_rolls": (f_col, f_row),
    }


def gleam_outcome(total):
    """Map a d20+Gleam total onto the Gleam Test table (1-15 nothing, 35+ cap)."""
    if total <= 15:
        return None
    return GLEAM_TEST[min(total, 35)]
