# NPC Generation Tables from TOPAZ CHARIOT pp.126-145
# Extracted December 2024

# ============================================
# BASIC NPC TABLE (d20)
# ============================================

ANCESTRY_TABLE = {
    1: "True-kin", 2: "True-kin", 3: "True-kin",
    4: "Cacogen", 5: "Cacogen", 6: "Newbeast",
    7: "Newbeast", 8: "Mycomorph", 9: "Mycomorph",
    10: "Mycomorph", 11: "Synth", 12: "Synth",
    13: "Faa Nomad", 14: "Faa Nomad", 15: "Cacklemaw Exile",
    16: "Cacklemaw Exile", 17: "Neobloom", 18: "Neobloom",
    19: "Planeyfolk", 20: "Lithling"
}

MANNER_TABLE = {
    1: "Abrasive", 2: "Arrogant", 3: "Assertive", 4: "Charismatic",
    5: "Daring", 6: "Decadent", 7: "Eloquent", 8: "Extravagant",
    9: "Hedonistic", 10: "Impulsive", 11: "Irritable", 12: "Melancholy",
    13: "Paranoid", 14: "Quiet", 15: "Religious", 16: "Romantic",
    17: "Scholarly", 18: "Stern", 19: "Vain", 20: "Volatile"
}

VOICE_TABLE = {
    1: "Breathy", 2: "Shrill", 3: "Deep", 4: "Sonorous",
    5: "Mumbles", 6: "Spits", 7: "Sing-song", 8: "Drawls",
    9: "Raspy", 10: "Whispers", 11: "Hasty", 12: "Weird Laugh",
    13: "Monotone", 14: "Jovial", 15: "Sinister", 16: "Husky",
    17: "Smoky", 18: "Smooth", 19: "Gravelly", 20: "Can't Speak"
}

DRIVE_TABLE = {
    1: "Addicted to Drug",
    2: "Religious Pilgrimage",
    3: "Seeking Revenge",
    4: "Pay Off Debts",
    5: "Fleeing the Law",
    6: "Collect a Debt",
    7: "Craves Fame",
    8: "Craves Material Wealth",
    9: "Craves Knowledge",
    10: "Craves Power",
    11: "Seeks Downfall of a Rival",
    12: "Hunting Escaped Prisoner",
    13: "Seeking Missing Bond (see below)",
    14: "Searching for Fabled Lost Location",
    15: "Find Cure for Rare Disease",
    16: "Unrequited Love (Same Ancestry)",
    17: "Forbidden Love (Different Ancestry)",
    18: "Seeks Heroic Death",
    19: "Compose Great Poem",
    20: "Create Great Art"
}

# ============================================
# FURTHER DETAILS TABLE (d20)
# ============================================

SECRET_TABLE = {
    1: "Is secretly wealthy",
    2: "Is secretly destitute", 
    3: "Has a secret lover",
    4: "Has a secret child",
    5: "Is secretly dying",
    6: "Has murdered someone",
    7: "Is a spy or informant",
    8: "Has stolen something valuable",
    9: "Knows a dangerous secret",
    10: "Has a hidden addiction",
    11: "Is in hiding from enemies",
    12: "Has betrayed someone close",
    13: "Is not who they claim to be",
    14: "Has a secret faith",
    15: "Is cursed or haunted",
    16: "Has psychic abilities hidden",
    17: "Owes a dangerous debt",
    18: "Has committed treason",
    19: "Knows location of treasure",
    20: "Is a clone of someone else"
}

BOND_TABLE = {
    1: "Mother", 2: "Father", 3: "Sister", 4: "Brother",
    5: "Uncle", 6: "Aunt", 7: "Spouse", 8: "Eldest Child",
    9: "Middle Child", 10: "Youngest Child", 11: "Grandfather",
    12: "Grandmother", 13: "Own Clone", 14: "Adopted Child",
    15: "Mentor Figure", 16: "Pet", 17: "Tame Monster",
    18: "Childhood Friend", 19: "Childhood Friend (Simulating Hologram)",
    20: "Inanimate Object Which They Talk To"
}

FAITH_TABLE = {
    1: "Church of Promised Sun", 2: "Church of Promised Sun",
    3: "Church of the Everbleeding Wound", 4: "Church of the Everbleeding Wound",
    5: "Vaa, Blue Goddess of Empty Spaces", 6: "Vaa, Blue Goddess of Empty Spaces",
    7: "Seekers of Eyeless Wisdom", 8: "Seekers of Eyeless Wisdom",
    9: "Binary Devotion", 10: "Binary Devotion",
    11: "Titan Cult", 12: "Autarch Cult",
    13: "Ghoul Cult", 14: "Fungus Cult",
    15: "Grim-Grin Worshipper", 16: "Worships Giant Immortal Animal",
    17: "Worships Only Themselves", 18: "Worships Quantum Daemon",
    19: "Brotherhood of the Black Sun", 20: "Brotherhood of the Black Sun"
}

FACTION_REPUTATION_TABLE = {
    1: "Hegemony (Hero)", 2: "Hegemony (Traitor)",
    3: "Hegemony (Outlaw, Wanted By)", 4: "Faa Nomads (Hero)",
    5: "Faa Nomads (Traitor)", 6: "Faa Nomads (Outlaw, Wanted By)",
    7: "Cacklemaw (Beloved)", 8: "Cacklemaw (Hated)",
    9: "Seekers of Eyeless Wisdom (Beloved)", 10: "Seekers of Eyeless Wisdom (Hated)",
    11: "Court of the Jigsaw Autarch (Loved)", 12: "Court of the Jigsaw Autarch (Hated)",
    13: "Titan Cults (Loved)", 14: "Titan Cults (Hated)",
    15: "Lithic Lyceum (Loved)", 16: "Lithic Lyceum (Hated)",
    17: "College of Indigo Tigers (Loved)", 18: "College of Indigo Tigers (Hated)",
    19: "Children of the Darkling Sun (Loved)", 20: "Children of the Darkling Sun (Hated)"
}

# ============================================
# NAMES TABLE (d100 x 4 columns)
# ============================================

NAMES_A = {
    1: "Abiah", 2: "Ahlber", 3: "Amur", 4: "Angda", 5: "Arnfreyn",
    6: "Arthar", 7: "Azuko", 8: "Baptist", 9: "Bathiel", 10: "Beitus",
    11: "Bellin", 12: "Bethod", 13: "Bhutaro", 14: "Boaz", 15: "Brinnr",
    16: "Byzou", 17: "Birk", 18: "Cassian", 19: "Corwin", 20: "Cossmoss",
    21: "Cyriak", 22: "Estaro", 23: "Everney", 24: "Fane", 25: "Farouk",
    26: "Faustyn", 27: "Fflaa", 28: "Frum", 29: "Fulgold", 30: "Gawain",
    31: "Getakehiko", 32: "Gorse", 33: "Grick", 34: "Haldib", 35: "Hikaru",
    36: "Indo", 37: "Ish", 38: "Jarl", 39: "Jask", 40: "Johar",
    41: "Juvenus", 42: "Kaphil", 43: "Katsu", 44: "Kayuko", 45: "Kircha",
    46: "Kondir", 47: "Lachiel", 48: "Lew", 49: "Lucjan", 50: "Masaor",
    51: "Masaori", 52: "Masatorald", 53: "Masios", 54: "Matheo", 55: "Maximiel",
    56: "Meussau", 57: "Minius", 58: "Mundur", 59: "Nihallen", 60: "Nörril",
    61: "Okhov", 62: "Ollon", 63: "Otger", 64: "Otringen", 65: "Paeon",
    66: "Parcas", 67: "Peneb", 68: "Phand", 69: "Porthim", 70: "Pushani",
    71: "Qeterius", 72: "Quarqus", 73: "Quiel", 74: "Rahamen", 75: "Robeflory",
    76: "Ryusuko", 77: "Saintjohn", 78: "Saintpaul", 79: "Salar", 80: "Salka",
    81: "Seisuke", 82: "Simorpheus", 83: "Solomon", 84: "Sprinus", 85: "Symeon",
    86: "Takami", 87: "Tarut", 88: "Taysk", 89: "Trian", 90: "Turms",
    91: "Tyche", 92: "Tytus", 93: "Ulmon", 94: "Vitus", 95: "Vult",
    96: "Weston", 97: "Xylenes", 98: "Yarapis", 99: "Yasuke", 100: "Zlator"
}

NAMES_B = {
    1: "Addi", 2: "Agupta", 3: "Alsafil", 4: "Andra", 5: "Anníva",
    6: "Anukesha", 7: "Arael", 8: "Aran", 9: "Arare", 10: "Arjuna",
    11: "Ashwari", 12: "Aubeahi", 13: "Augustinia", 14: "Auri", 15: "Auriel",
    16: "Avalon", 17: "Aveyn", 18: "Beneva", 19: "Bhakali", 20: "Bjarta",
    21: "Caela", 22: "Cayendra", 23: "Chah", 24: "Elel", 25: "Elisebet",
    26: "Emizan", 27: "Fendrel", 28: "Fingel", 29: "Fomanyana", 30: "Freyr",
    31: "Grence", 32: "Hadraklona", 33: "Haulë", 34: "Helis", 35: "Hrishna",
    36: "Idrika", 37: "Imrahma", 38: "Indur", 39: "Irmina", 40: "Isandrea",
    41: "Ishili", 42: "Ishtar", 43: "Isiopeia", 44: "Isolde", 45: "Jacintha",
    46: "Jikinio", 47: "Jikit", 48: "Jindel", 49: "Julinna", 50: "Jupindi",
    51: "Kaori", 52: "Karra", 53: "Kathik", 54: "Lami", 55: "Leloryl",
    56: "Lirockite", 57: "Lumo", 58: "Lunahl", 59: "Maeri", 60: "Malamue",
    61: "Maleli", 62: "Maneva", 63: "Mayana", 64: "Meena", 65: "Menka",
    66: "Mneme", 67: "Moneflower", 68: "Mosefina", 69: "Murthwaite", 70: "Muthael",
    71: "Nahl", 72: "Nehmet", 73: "Nisite", 74: "Ojasin", 75: "Olanele",
    76: "Othoba", 77: "Penta", 78: "Poe", 79: "Pomory", 80: "Puloma",
    81: "Pupienua", 82: "Qusamira", 83: "Rolfinnura", 84: "Selal", 85: "Septi",
    86: "Solasa", 87: "Solm", 88: "Sophla", 89: "Soraila", 90: "Tillux",
    91: "Vespassia", 92: "Xhiva", 93: "Ximinta", 94: "Yathartha", 95: "Yoshar",
    96: "Zeta", 97: "Zoelel", 98: "Zofi", 99: "Zumi", 100: "Zuzanna"
}

NAMES_C = {
    1: "Ambrosia", 2: "Andromeda", 3: "Ash", 4: "Basik", 5: "Be-True",
    6: "Big-Spit", 7: "Bilge", 8: "Bleakblade", 9: "Blackchapel", 10: "Blue",
    11: "Boots", 12: "Bronzeguts", 13: "Brown", 14: "Chairman", 15: "Conch",
    16: "Crab", 17: "Crow", 18: "Cusp", 19: "Dog", 20: "Domino",
    21: "Duke", 22: "Easter", 23: "Faithful", 24: "Feasts-With-Fools", 25: "Foxglory",
    26: "Glass Jaw", 27: "Glitch", 28: "Goldtongue", 29: "Goodluck", 30: "Gorgeous",
    31: "Grace", 32: "Gravedigger", 33: "Green", 34: "Heartsease", 35: "Holiday",
    36: "Indigo", 37: "Iris", 38: "Jigsaw", 39: "Jingle", 40: "Knot",
    41: "Koan", 42: "Light-The-Lantern", 43: "Lilt", 44: "Little-Spit", 45: "Lovely",
    46: "Longtooth", 47: "Look-Home", 48: "Looks-to-the-Dawn", 49: "Lotus", 50: "Lucky-And-True",
    51: "Mandala", 52: "Many-Moons", 53: "Merry", 54: "Mirage", 55: "Morrow",
    56: "Moth", 57: "Nectar", 58: "Nine-Eyes", 59: "Ochre", 60: "Opal",
    61: "Paledawn", 62: "Pentecost", 63: "Pincher", 64: "Pinkie", 65: "Prays-For-Rain",
    66: "Provost", 67: "Puke", 68: "Purple-Dusk", 69: "Quill", 70: "Raven",
    71: "Ribs", 72: "Saffron", 73: "Saint", 74: "Salt", 75: "Seeks-The-Path",
    76: "Seven", 77: "Silver", 78: "Sir-Madam", 79: "Skybreak", 80: "Sleeps-In-Amber",
    81: "Sloe", 82: "Slowly", 83: "Sovereign", 84: "Static", 85: "Stoutfoot",
    86: "Stonecipher", 87: "Swan", 88: "Teal", 89: "Ten-Stars", 90: "Trinity",
    91: "Tusk", 92: "Two Times", 93: "Ultra", 94: "Vespers", 95: "Warthog",
    96: "White-Eye", 97: "Whiteknife", 98: "Winterlamp", 99: "Wren", 100: "Zooth"
}

NAMES_D = {
    1: "Abandon", 2: "Achefoot", 3: "Alzina", 4: "Anthur", 5: "Aran",
    6: "Arb", 7: "Ariyei", 8: "Asaj", 9: "Aumatell", 10: "Awasad",
    11: "Bana", 12: "Bargh", 13: "Basai", 14: "Berruzo", 15: "Bitar",
    16: "Blame", 17: "Blueback", 18: "Bountyfull", 19: "Brazen", 20: "Brunan",
    21: "Cawl", 22: "Castarle", 23: "Chasa", 24: "Coma", 25: "Comabella",
    26: "Cunill", 27: "Dragger", 28: "Exald", 29: "Faswar", 30: "Ferrater",
    31: "Fouler", 32: "Fraguas", 33: "Fres", 34: "Fusta", 35: "Garau",
    36: "Gharikh", 37: "Ghogu", 38: "Gnomonborn", 39: "Greathall", 40: "Greenlance",
    41: "Grey", 42: "Gura", 43: "Hanger", 44: "Hasikh", 45: "Hiccup",
    46: "Horehound", 47: "Hush", 48: "Ishish", 49: "Kinsella", 50: "Latch",
    51: "Levijeans", 52: "Lonrot", 53: "Mairg", 54: "Make-Peace", 55: "Marsal",
    56: "Mellod", 57: "Merry", 58: "Miaza", 59: "Miribiki", 60: "Morey",
    61: "Moudan", 62: "Nafour", 63: "No-Luck", 64: "Noro", 65: "Osk",
    66: "Pallak", 67: "Paradise", 68: "Pepsi-Kola", 69: "Pig-Wise", 70: "Posas",
    71: "Prince", 72: "Recto", 73: "Richter", 74: "Roper", 75: "Sabbad",
    76: "Sanaye", 77: "Scar", 78: "Seagreen", 79: "Sharas", 80: "Shases",
    81: "Shiningcoin", 82: "Sleba", 83: "Sledge", 84: "Stillborn", 85: "Stirrup",
    86: "Sunbearer", 87: "Thule", 88: "Trulls", 89: "Truth", 90: "Umber",
    91: "Utterly", 92: "Valvern", 93: "Verdagu", 94: "Vurt", 95: "Whitsand",
    96: "Windblown", 97: "Wing", 98: "Xalabar", 99: "Yawngawp", 100: "Xan Zophiel"
}

# ============================================
# CAREERS TABLE (d100) with items
# ============================================

CAREERS_TABLE = {
    1: {"career": "Actor", "items": "Wig, False Nose, Book of Playscripts"},
    2: {"career": "Adorcist", "items": "GIFT: Embrace Spirit, Ritual Hat (+1 EGO while worn), Prayer Beads"},
    3: {"career": "Aeromancer", "items": "GIFT: Raise the Winds, Billowing Cape (11 AV), Wind Instrument"},
    4: {"career": "Alchemist", "items": "Hazard Wrap (AV 12), Vial of Acid, Vial of Poison (d10 TOX)"},
    5: {"career": "Ape Catcher", "items": "Weighted Net (Target DEX saves vs Entangled), Bludgeon (d6), Ape Snares (3)"},
    6: {"career": "Apostle", "items": "Holy Text, Sacred Icon, Incense"},
    7: {"career": "Artifex", "items": "Welding Tools, Pliers, Random Exotica"},
    8: {"career": "Assassin", "items": "Hidden Blade (d6), Silenced Pistol (d6), Poison Pill (d8 TOX)"},
    9: {"career": "Astronomer", "items": "Astrolabe, Star Map, Telescope"},
    10: {"career": "Baker", "items": "Rolling Pin (d6), Bag of Flour, Fresh Loaves (3)"},
    11: {"career": "Barber-surgeon", "items": "Razor (d6), Badger Hair Brush, Copper Bowl"},
    12: {"career": "Barkeep", "items": "Shotgun (d8, 2 slots), Amphorae of Wine, Ice-cube Maker"},
    13: {"career": "Bastard Farmer", "items": "Cryo-Flask (Human Embryo), Cryo-Flask (Empty), Pistol (d6)"},
    14: {"career": "Beggar", "items": "Alms Bowl, Trained Ferret (Level 1, AV 11, Bite d4), Club (d6)"},
    15: {"career": "Blacksmith", "items": "Great Hammer (d8, 2 slots), Sky-Iron Helm (+1 AV), Tongs"},
    16: {"career": "Bookbinder", "items": "Marbled Paper, Awl (d4), Random Book"},
    17: {"career": "Butcher", "items": "Cleaver (d6), Salt, String of Zorse-meat Sausages"},
    18: {"career": "Caravan Guard", "items": "Lizardskin Jerkin (AV 13, 3 slots), Desert Rifle (d8, 2 slots), Binoculars"},
    19: {"career": "Carpenter", "items": "Saw, Hammer (d6), Nails (100)"},
    20: {"career": "Charioteer", "items": "Racing Cape (+1 EGO), Whip (d6), Gilded Trophy"},
    21: {"career": "Chromepriest", "items": "Mirrored Robes (AV 11, half damage from Beams), Random Cybernetic Implant, Random Cybernetic Implant"},
    22: {"career": "Clairvoyant", "items": "Three-eyed Mask (+1 AV), GIFT: Second Sight, GIFT: Telepathy"},
    23: {"career": "Clerk", "items": "Stylus, Wax Tablet, Abacus"},
    24: {"career": "Clockmaker", "items": "Magnifying Glasses, Precision Tools, Broken Clock"},
    25: {"career": "Clone Catcher", "items": "Handcannon (d8, 2 slots), Genepeeker, Flask of Whiskey"},
    26: {"career": "Clown", "items": "Jolly Bludgeon (d6), Foolish Attire, Mock Gun (fires confetti)"},
    27: {"career": "Confessor", "items": "Purple Robes (11 AV), Book of Confessions, Absolving Oil"},
    28: {"career": "Cook", "items": "Kitchen Knife (d6), Cast Iron Skillet, Rare Spices (3)"},
    29: {"career": "Courtesan", "items": "Wig, Makeup, Prophylactics"},
    30: {"career": "Cybernetics Surgeon", "items": "Scalpel (d6), Antibiotics, Random Cybernetic Implant"},
    31: {"career": "Cyromancer", "items": "Thermo-equilibrium Suit (AV 12, Immune to Heat/Cold), GIFT: Cyrokinesis"},
    32: {"career": "Daemonologist", "items": "Ritual Dagger (d4), Ritual Chalk, Book of Quantum Daemon Names"},
    33: {"career": "Diviner", "items": "GIFT: Augury, Golden Bowl, Flagon of Prophetic Wine"},
    34: {"career": "Doomsinger", "items": "GIFT: Deathsong, Black Robes (AV 11), Vocal Amplifier (d6 sonic weapon)"},
    35: {"career": "Drunkard", "items": "Bottle of Strong Liquor (flammable), Set of Playing Cards, Automatic Cocktail Maker"},
    36: {"career": "Duellist", "items": "Duelling Gloves (white), Rapier (d6), Two Duelling Pistols (d8, one shot each)"},
    37: {"career": "Embroiderer", "items": "War Needle (d6, concealed), Embroidered Brigandine (13 AV), Half-finished Tapestry"},
    38: {"career": "Exorcist", "items": "GIFT: Rebuke Spirit, Exorcist's Bells, White Sword (d8)"},
    39: {"career": "Faith Healer", "items": "GIFT: Healing Hands, Acupuncture Kit, 3 Cleansing Orbs (neutralise poison)"},
    40: {"career": "Falconer", "items": "Leather Glove, Training Whistle, Hooded Falcon (Level 1, AV 17, Peck d4)"},
    41: {"career": "Fire Singer", "items": "Scarlet Robes (AV 11, 1 slot, half damage from flames), Flameburst Mask (+1 AV), GIFT: Pyrokinesis"},
    42: {"career": "Flagellant", "items": "Scourge (d6), Doomsday Pamphlet, Insta-Scab Clotting Spray (3 doses)"},
    43: {"career": "Fungusmonger", "items": "Sporegun (d8, 2 slots), Deathcap Mushroom (d12 TOX), Exotica: Dried Mycomorph"},
    44: {"career": "Gambler", "items": "Flamboyant Scarf, Loaded Dice, Deck of Cards"},
    45: {"career": "Gladiator", "items": "Showy AV (AV 15, 5 slots), Flashy Weapon (d8, 2 slots), Grisly Trophy"},
    46: {"career": "Goatherd", "items": "Shepherd's Staff (d6), Loyal Goat (Level 1, AV 11, d4 butt), Goat Cheese"},
    47: {"career": "Graverobber", "items": "Shovel (d6), Crowbar (d6), Hooded Lantern"},
    48: {"career": "Gunslinger", "items": "Revolver (d6), Scattergun (d8, close), Wide-brimmed Hat (+1 EGO)"},
    49: {"career": "Hangman", "items": "Black Hood, Long Rope, Pack of Cigarettes"},
    50: {"career": "Hegemony Deserter", "items": "Hegemony Rifle (d8, 2 slots), Hegemony AV (Armour 14, 4 slots), Cybernetic Implant"},
    51: {"career": "Hermit", "items": "Walking Staff (d8, 2 slots), Random Gift"},
    52: {"career": "High Priest", "items": "Ornate Headpiece (+1 AV), Ornate Robes (AV 13, 3 slots), Ritual Mace (d8, 2 slots)"},
    53: {"career": "Hunter", "items": "Crossbow (d8, 2 slots), Bird-mimic Whistle, Snap-traps (3)"},
    54: {"career": "Hydromancer", "items": "GIFT: Water Manipulation, Aquamarine Robes (AV 11), Glass Headdress (+1 AV, shatters if opponent rolls a 20)"},
    55: {"career": "Hypergeometer", "items": "Manifold Dagger (d6, hypergeometric), Hypergeometric Ruler, GIFT: Carve Portal"},
    56: {"career": "Illusionist", "items": "Mirrored Shield (+1 AV), Radiant Lantern, GIFT: Light Manipulation"},
    57: {"career": "Inquisitor", "items": "Querulous Blade (d6), Truth Serum (3 doses), Hegemony Law Books"},
    58: {"career": "Leechmonger", "items": "Tongs, Plastic Bags, 3 Medicinal Leeches (cure poison/disease, die after use)"},
    59: {"career": "Lithomancer", "items": "Petrified Robes (AV 16, 6 slots), GIFT: Stone Manipulation"},
    60: {"career": "Lizard Rancher", "items": "Lasso, Lizard Treats (5), Tame War Lizard (Level 1, AV 14, d6 bite)"},
    61: {"career": "Mask Maker", "items": "Unsettling Mask, Jaunty Mask, Holy Mask"},
    62: {"career": "Medium", "items": "Scrying Crystal, Ritual Oils, GIFT: Spirit Calling"},
    63: {"career": "Mercenary", "items": "Gambeson (AV 12, 2 slots), Plasma Fusil (d8, 2 slots), 3 Plasma Grenades (d10 blast)"},
    64: {"career": "Miner", "items": "Pick-axe (d6), Illuminating Helm (+1 AV, creates light), Caged Finch"},
    65: {"career": "Monk", "items": "Monastic Robes (AV 11), Icon of Random Petty God, Illuminated Manuscript"},
    66: {"career": "Musician", "items": "Sitar, Electric Harp, Book of Poems"},
    67: {"career": "Mystic", "items": "Begging Bowl, Random GIFT, Random GIFT"},
    68: {"career": "Necromancer", "items": "Skull-helmed Garb (AV 14, 4 slots), Sable Sword (d8, 2 slots), GIFT: Brief Resurrection"},
    69: {"career": "Olive Merchant", "items": "Debt Ledger, Set of Scales, 300 preserved olives (3 slots)"},
    70: {"career": "Oracle", "items": "Blindfold, Random Drug, GIFT: Precognition"},
    71: {"career": "Outlaw", "items": "Rifle (d8, 2 slots), Grenades (d10 blast, 3), Shabby Leather (AV 13, 3 slots)"},
    72: {"career": "Painter", "items": "Set of Brushes, Oil Paints, Half-finished Masterpiece"},
    73: {"career": "Philosopher", "items": "Orator's Mask (amplifies voice), Scribbled Treatise, Random Book"},
    74: {"career": "Poacher", "items": "Bow (d6), Animal Traps (3), Handheld Motion Detector"},
    75: {"career": "Priest of Sevenscore Moons", "items": "Moondark Mask (AV +1), Waning Blade (d6), Draught of Merciful Tranquility (CON Save vs Death)"},
    76: {"career": "Priest of the Promised Sun", "items": "Sunburst Mask (AV +1), Sun Staff (d6), Medicinal Gourds (3, d8 heal)"},
    77: {"career": "Professional Lamenter", "items": "Somber Garb (AV 11), Lachrymax Pills (3 doses, induces intense grief), Liquid Sunshine (3 syringes, induces manic euphoria)"},
    78: {"career": "Psychonaut", "items": "Random Gift, Random Drug, Random Drug"},
    79: {"career": "Relic Thief", "items": "Grappling Hook Gun, Blackened Dagger (d6), Void-Saint's Pickled Finger"},
    80: {"career": "Sacred Executioner", "items": "Greatsword (d10, 3 slots), Fuligin Robes (11 AV, ADV to hide in shadows), Holy Claw"},
    81: {"career": "Sailor (Void)", "items": "Voidsuit (AV 12, 2 slots, Breathe in Vacuum), Suit-cutter (d6), Glowstone"},
    82: {"career": "Sailor (Wind-Barge)", "items": "Compass, Coil of Rope, Flask of Whiskey (flammable)"},
    83: {"career": "Scavenger", "items": "Metal Detector, Random Vault Trinket"},
    84: {"career": "Science-Mystic's Apprentice", "items": "Stolen Beam-pistol (d6, beam), Random GIFT, Random Drug"},
    85: {"career": "Scribe", "items": "Stylus, Bottle of Ink, Autoglot Translator Unit"},
    86: {"career": "Sin Eater", "items": "Ritual Dining Fork (d8, 2 slots), Large Napkin, Indigestible Sin Hidden In Box"},
    87: {"career": "Slave (Escaped)", "items": "Broken Chains (d6)"},
    88: {"career": "Smuggler", "items": "Revolver (d6), Forged Customs Forms, Counterfeit Water-Debt Tokens (10)"},
    89: {"career": "Spy", "items": "Stylus-Gun (d6, resembles pen), Suicide Pill (d12 TOX), Cryptography Machine"},
    90: {"career": "Synth Hunter", "items": "Basilisk-Pattern Shield (+1 AV, Synths DIS to hit wearer), Lightning Pistol (d6 electrical), 3 EMP Bombs (Synths CON save vs shutdown)"},
    91: {"career": "Synth-surgeon", "items": "Surgeon's Toolkit (remove 1 Wound from Synths per day), Memory Bank Backpack (+1 INT), Random Cybernetic Implant"},
    92: {"career": "Tanner", "items": "Leather Coat (13 AV), Fleshing Knife (d6), Pumice Stone"},
    93: {"career": "Torturer", "items": "Peeler (d6), Pliers (d6), Pain Amplifier Serum (3 doses)"},
    94: {"career": "Travelling Scholar", "items": "Random Book, Random Book, Outdated Field Guide to Vaarn (2nd Edition)"},
    95: {"career": "Water Diviner", "items": "Dowsing Rod, Scent-Amplifier Mask, Damp Detector"},
    96: {"career": "Watermonger", "items": "Water Purification Tablets (x5), Water Wealth (3d20 rations)"},
    97: {"career": "Witch", "items": "Iron Cauldron, TALLHAT™ Psionic Amplifier (+1 PSY), Random GIFT"},
    98: {"career": "Woodcarver", "items": "Knife (d6), Chisel, Wooden Animal"},
    99: {"career": "Wormtamer", "items": "Sandworm Bridle, Sandworm Stirrups, Thumper (Summons Sandworm on open sands, 4-in-6 Juvenile, 2-in-6 Adult)"},
    100: {"career": "Zeppelin Guard", "items": "Blunderbore (d8, 2 slots), Grappling Hook and Rope, Parachute"}
}
