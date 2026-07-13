"""Ancestry data for PC generation (CH printed pp. 7-26 + p.6 d10).

Transcribed from the staged geometry dumps + page images at
docs/superpowers/plans/data/ (ground truth = spark_pages/*.png).
Banded columns are stored FLAT (the band value repeated on every row it
covers) so a single d20 reads any column. See VERIFICATION_NOTES.md.
"""

ANCESTRY_D10 = {
    1: "true-kin", 2: "cacogen", 3: "synth", 4: "newbeast", 5: "neobloom",
    6: "mycomorph", 7: "faa-nomad", 8: "cacklemaw-exile", 9: "planeyfolk",
    10: "lithling",
}

ANCESTRIES = {
    "true-kin": {
        "name": "True-kin",
        "kind": "Biological",
        "special_rules": [
            {"name": "Pure of Blood",
             "text": ("You have ADV on reaction and persuasion rolls when "
                      "you encounter other true-kin. You lose this bonus if "
                      "you ever become visibly mutated."),
             "reaction": {"adv": {"vs_ancestry": "true-kin"}}},
            {"name": "Inheritor",
             "text": ("When you encounter pre-Collapse security systems or "
                      "guard synths, make an opposed EGO save. On success, "
                      "the machine becomes convinced that you are its new "
                      "master and will serve you in any way it is able. On "
                      "failure the machine becomes implacably hostile.")},
        ],
        "creation_hooks": {},
        "spark_tables": [
            {"title": "appearance",
             "columns": ["BODY", "FACE", "HAIR", "ATTIRE"],
             "rows": {
                 1: {"BODY": "Tall", "FACE": "Sallow", "HAIR": "Black", "ATTIRE": "Rags"},
                 2: {"BODY": "Short", "FACE": "Lively", "HAIR": "Brown", "ATTIRE": "Animal Skins"},
                 3: {"BODY": "Frail", "FACE": "Cruel", "HAIR": "Red", "ATTIRE": "Rough Tunic"},
                 4: {"BODY": "Muscular", "FACE": "Wrinkled", "HAIR": "Blonde", "ATTIRE": "Nomad Attire"},
                 5: {"BODY": "Fat", "FACE": "Scarred", "HAIR": "Grey", "ATTIRE": "Worker's Attire"},
                 6: {"BODY": "Thin", "FACE": "Frowning", "HAIR": "White", "ATTIRE": "Herdsman's Attire"},
                 7: {"BODY": "Skeletal", "FACE": "Pale", "HAIR": "Shaved", "ATTIRE": "Slave Clothing"},
                 8: {"BODY": "Hunched", "FACE": "Greasy", "HAIR": "Topknot", "ATTIRE": "Exultant's Livery"},
                 9: {"BODY": "Lopsided", "FACE": "Wide", "HAIR": "Green", "ATTIRE": "Shabby Attire"},
                 10: {"BODY": "Lithe", "FACE": "Narrow", "HAIR": "Orange", "ATTIRE": "Colourful Attire"},
                 11: {"BODY": "Gnarled", "FACE": "Sharp", "HAIR": "Glowing", "ATTIRE": "Priest's Robes"},
                 12: {"BODY": "Squat", "FACE": "Hungry", "HAIR": "Fungus", "ATTIRE": "Clerk's Uniform"},
                 13: {"BODY": "Bloated", "FACE": "Haunted", "HAIR": "Purple", "ATTIRE": "Hegemony Garb"},
                 14: {"BODY": "Gangly", "FACE": "Jolly", "HAIR": "Yellow", "ATTIRE": "Soldier's Clothing"},
                 15: {"BODY": "Child-like", "FACE": "Round", "HAIR": "Wispy", "ATTIRE": "Flamboyant Attire"},
                 16: {"BODY": "Tanned", "FACE": "Mournful", "HAIR": "Burnt", "ATTIRE": "Musician's Attire"},
                 17: {"BODY": "Gigantic", "FACE": "Child-like", "HAIR": "Braided", "ATTIRE": "Veiled Attire"},
                 18: {"BODY": "Wiry", "FACE": "Peaceful", "HAIR": "Greasy", "ATTIRE": "Armiger's Clothing"},
                 19: {"BODY": "Tattooed", "FACE": "Sleepy", "HAIR": "Matted", "ATTIRE": "Exultant's Clothing"},
                 20: {"BODY": "Scarred", "FACE": "Branded", "HAIR": "Long", "ATTIRE": "Expensive Clothing"},
             }},
            {"title": "identity",
             "columns": ["NAME", "CASTE", "MANNER", "QUIRK"],
             # CASTE is BANDED on the page: 1-4 Servitor (labourer caste),
             # 5-9 Freeholder (merchant caste), 10-14 Optimate (administrator
             # caste), 15-17 Armiger (warrior caste), 18-20 Exultant (sacred
             # aristocracy). Stored flat per VERIFICATION_NOTES.md.
             "rows": {
                 1: {"NAME": "Benjoe", "CASTE": "Servitor (labourer caste)", "MANNER": "Amused", "QUIRK": "Ritual Scars"},
                 2: {"NAME": "Leif", "CASTE": "Servitor (labourer caste)", "MANNER": "Bitter", "QUIRK": "Face Tattoos"},
                 3: {"NAME": "Xurm", "CASTE": "Servitor (labourer caste)", "MANNER": "Morbid", "QUIRK": "Slave Brand"},
                 4: {"NAME": "Kazor", "CASTE": "Servitor (labourer caste)", "MANNER": "Bony", "QUIRK": "Heavy Jewellery"},
                 5: {"NAME": "Essana", "CASTE": "Freeholder (merchant caste)", "MANNER": "Cheerful", "QUIRK": "Synthetic Limb"},
                 6: {"NAME": "Calista", "CASTE": "Freeholder (merchant caste)", "MANNER": "Cruel", "QUIRK": "Strange Voice"},
                 7: {"NAME": "Jinny", "CASTE": "Freeholder (merchant caste)", "MANNER": "Flamboyant", "QUIRK": "Clone Brand"},
                 8: {"NAME": "Vela", "CASTE": "Freeholder (merchant caste)", "MANNER": "Glowering", "QUIRK": "Limp"},
                 9: {"NAME": "Leksei", "CASTE": "Freeholder (merchant caste)", "MANNER": "Impish", "QUIRK": "Strange Pet"},
                 10: {"NAME": "Ippash", "CASTE": "Optimate (administrator caste)", "MANNER": "Lanky", "QUIRK": "Lacquered Teeth"},
                 11: {"NAME": "Lagad", "CASTE": "Optimate (administrator caste)", "MANNER": "Patrician", "QUIRK": "Burn Scars"},
                 12: {"NAME": "Myli", "CASTE": "Optimate (administrator caste)", "MANNER": "Reckless", "QUIRK": "Octarine Eyes"},
                 13: {"NAME": "Nirid", "CASTE": "Optimate (administrator caste)", "MANNER": "Rough", "QUIRK": "Dyed Skin"},
                 14: {"NAME": "Ardel", "CASTE": "Optimate (administrator caste)", "MANNER": "Rude", "QUIRK": "Golden Teeth"},
                 15: {"NAME": "Senefer", "CASTE": "Armiger (warrior caste)", "MANNER": "Sly", "QUIRK": "Silver Tongue"},
                 16: {"NAME": "Pharmon", "CASTE": "Armiger (warrior caste)", "MANNER": "Sour", "QUIRK": "Missing Limb"},
                 17: {"NAME": "Mesu", "CASTE": "Armiger (warrior caste)", "MANNER": "Stoic", "QUIRK": "Missing Eye"},
                 18: {"NAME": "Lenta", "CASTE": "Exultant (sacred aristocracy)", "MANNER": "Foolish", "QUIRK": "Religious Icon"},
                 19: {"NAME": "Goza", "CASTE": "Exultant (sacred aristocracy)", "MANNER": "Warm", "QUIRK": "Synthetic Eyes"},
                 20: {"NAME": "Babl", "CASTE": "Exultant (sacred aristocracy)", "MANNER": "Wolfish", "QUIRK": "Visibly Diseased"},
             }},
        ],
    },
    "cacogen": {
        "name": "Cacogen",
        "kind": "Biological",
        "special_rules": [
            {"name": "Corrupted Blood",
             "text": ("During character creation, roll d100 three times for "
                      "mutations (p.xx). If the effects contradict one "
                      "another, the more recent mutation takes precedence.")},
            {"name": "Proteus",
             "text": ("When you gain a Level you may roll for another "
                      "mutation instead of increasing HP and ability scores. "
                      "You have DIS on Saves to resist mutation and other "
                      "metamorphic effects.")},
        ],
        "creation_hooks": {"mutations_at_creation": 3},
        "spark_tables": [
            {"title": "appearance",
             "columns": ["BODY", "FACE", "HAIR", "ATTIRE"],
             "rows": {
                 1: {"BODY": "Tall", "FACE": "Sallow", "HAIR": "Black", "ATTIRE": "Rags"},
                 2: {"BODY": "Short", "FACE": "Lively", "HAIR": "Brown", "ATTIRE": "Animal Skins"},
                 3: {"BODY": "Frail", "FACE": "Cruel", "HAIR": "Red", "ATTIRE": "Rough Tunic"},
                 4: {"BODY": "Muscular", "FACE": "Wrinkled", "HAIR": "Blonde", "ATTIRE": "Nomad Attire"},
                 5: {"BODY": "Fat", "FACE": "Scarred", "HAIR": "Grey", "ATTIRE": "Worker's Attire"},
                 6: {"BODY": "Thin", "FACE": "Frowning", "HAIR": "White", "ATTIRE": "Herdsman's Attire"},
                 7: {"BODY": "Skeletal", "FACE": "Pale", "HAIR": "Shaved", "ATTIRE": "Slave Clothing"},
                 8: {"BODY": "Hunched", "FACE": "Greasy", "HAIR": "Topknot", "ATTIRE": "Servant's Livery"},
                 9: {"BODY": "Lopsided", "FACE": "Wide", "HAIR": "Green", "ATTIRE": "Shabby Attire"},
                 10: {"BODY": "Lithe", "FACE": "Narrow", "HAIR": "Orange", "ATTIRE": "Colourful Attire"},
                 11: {"BODY": "Gnarled", "FACE": "Sharp", "HAIR": "Glowing", "ATTIRE": "Priest's Robes"},
                 12: {"BODY": "Squat", "FACE": "Hungry", "HAIR": "Fungal", "ATTIRE": "Clerk's Uniform"},
                 13: {"BODY": "Bloated", "FACE": "Haunted", "HAIR": "Purple", "ATTIRE": "Hegemony Garb"},
                 14: {"BODY": "Gangly", "FACE": "Jolly", "HAIR": "Yellow", "ATTIRE": "Soldier's Clothing"},
                 15: {"BODY": "Child-like", "FACE": "Round", "HAIR": "Wispy", "ATTIRE": "Flamboyant Attire"},
                 16: {"BODY": "Tanned", "FACE": "Mournful", "HAIR": "Burnt", "ATTIRE": "Musician's Attire"},
                 17: {"BODY": "Gigantic", "FACE": "Child-like", "HAIR": "Braided", "ATTIRE": "Veiled Attire"},
                 18: {"BODY": "Wiry", "FACE": "Peaceful", "HAIR": "Greasy", "ATTIRE": "Courtesan's Clothing"},
                 19: {"BODY": "Stout", "FACE": "Sleepy", "HAIR": "Matted", "ATTIRE": "Sorcerous Clothing"},
                 20: {"BODY": "Scarred", "FACE": "Branded", "HAIR": "Long", "ATTIRE": "Expensive Clothing"},
             }},
            {"title": "identity",
             "columns": ["NAME", "MANNER", "MISFORTUNE", "YOUR ECCENTRICITY"],
             "rows": {
                 1: {"NAME": "Arda", "MANNER": "Abrasive", "MISFORTUNE": "Slave", "YOUR ECCENTRICITY": "A Strange Hat"},
                 2: {"NAME": "Bollo", "MANNER": "Arrogant", "MISFORTUNE": "Debtor", "YOUR ECCENTRICITY": "Always Muttering"},
                 3: {"NAME": "Breen", "MANNER": "Assertive", "MISFORTUNE": "Gambler", "YOUR ECCENTRICITY": "Ascetic Diet"},
                 4: {"NAME": "Conch", "MANNER": "Charismatic", "MISFORTUNE": "Clone", "YOUR ECCENTRICITY": "Forgetful And Rude"},
                 5: {"NAME": "Crab", "MANNER": "Daring", "MISFORTUNE": "Gladiator", "YOUR ECCENTRICITY": "Gluttonous Diet"},
                 6: {"NAME": "Dancer", "MANNER": "Decadent", "MISFORTUNE": "Memories Stolen", "YOUR ECCENTRICITY": "Highly Formal"},
                 7: {"NAME": "Doss", "MANNER": "Eloquent", "MISFORTUNE": "Forger", "YOUR ECCENTRICITY": "Interrupts Constantly"},
                 8: {"NAME": "Hust", "MANNER": "Extravagant", "MISFORTUNE": "Exiled", "YOUR ECCENTRICITY": "Laugh At Own Jokes"},
                 9: {"NAME": "Jal", "MANNER": "Hedonistic", "MISFORTUNE": "Cultist", "YOUR ECCENTRICITY": "Married To A Knife"},
                 10: {"NAME": "Lask", "MANNER": "Impulsive", "MISFORTUNE": "Thief", "YOUR ECCENTRICITY": "Monocle"},
                 11: {"NAME": "Lip", "MANNER": "Irritable", "MISFORTUNE": "Addicted", "YOUR ECCENTRICITY": "Monotone Voice"},
                 12: {"NAME": "Olm", "MANNER": "Melancholy", "MISFORTUNE": "Framed", "YOUR ECCENTRICITY": "Only Sleeps Outdoors"},
                 13: {"NAME": "Pirrip", "MANNER": "Paranoid", "MISFORTUNE": "Conned", "YOUR ECCENTRICITY": "Only Wears Purple"},
                 14: {"NAME": "Poucher", "MANNER": "Quiet", "MISFORTUNE": "Bankrupt", "YOUR ECCENTRICITY": "Quotes Irrelevant Facts"},
                 15: {"NAME": "Pree", "MANNER": "Religious", "MISFORTUNE": "Heretic", "YOUR ECCENTRICITY": "Several Spouses"},
                 16: {"NAME": "Uz", "MANNER": "Romantic", "MISFORTUNE": "Rejected", "YOUR ECCENTRICITY": "Talks To Self"},
                 17: {"NAME": "Whistler", "MANNER": "Scholarly", "MISFORTUNE": "Blackmailed", "YOUR ECCENTRICITY": "Unwieldy Jewellery"},
                 18: {"NAME": "Yaz", "MANNER": "Stern", "MISFORTUNE": "Cursed", "YOUR ECCENTRICITY": "Usually Drunk"},
                 19: {"NAME": "Yoss", "MANNER": "Vain", "MISFORTUNE": "Orphaned", "YOUR ECCENTRICITY": "Always Wears Gloves"},
                 20: {"NAME": "Zem", "MANNER": "Volatile", "MISFORTUNE": "Bereaved", "YOUR ECCENTRICITY": "Won't Look At Mirrors"},
             }},
        ],
    },
    "synth": {
        "name": "Synth",
        "kind": "Synthetic",
        "special_rules": [
            {"name": "Synthetic Flesh",
             "text": ("You are a being of metal and plastic. You do not need "
                      "to eat or breathe. You are immune to damage from "
                      "suffocation, drowning, toxins, extreme temperatures, "
                      "or spores. You suffer double damage from electrical "
                      "weapons. When you receive Wounds, use the Synthetic "
                      "Wounds table (p.xx).")},
            {"name": "Synthetic Mind",
             "text": ("You are vulnerable to attacks that target the LogLang "
                      "syntax that powers synths. These include strobing "
                      "basilisk patterns, malicious infoglyphs, and ancient "
                      "Titan-era language viruses. You suffer d6 INT damage "
                      "per round from magnetic fields.")},
            {"name": "Repairs",
             "text": ("You cannot regain HP by consuming rations. You must "
                      "make repairs using Synth Parts. You begin play with 3 "
                      "spare Synth Parts, which stack in one item slot. A "
                      "repair takes an hour and uses up one synth part. "
                      "Repairs heal d8 + CON HP. If HP is full, heal one "
                      "Wound. To extract parts from dead synthetic "
                      "creatures, make an INT save. On a success, extract "
                      "usable synth parts equal to their Level. On failure, "
                      "extract one usable part.")},
        ],
        "creation_hooks": {},
        "spark_tables": [
            {"title": "appearance",
             "columns": ["SIZE", "FORM", "HEAD", "LIMBS", "FINISH"],
             # SIZE is BANDED: 1-5 Small, 6-10 Medium, 11-15 Large,
             # 16-20 Imposing (VERIFICATION_NOTES.md). Stored flat.
             "rows": {
                 1: {"SIZE": "Small", "FORM": "Ape", "HEAD": "Humanoid", "LIMBS": "Biological", "FINISH": "Grey"},
                 2: {"SIZE": "Small", "FORM": "Android", "HEAD": "Missing", "LIMBS": "Bird-like", "FINISH": "Brassy"},
                 3: {"SIZE": "Small", "FORM": "Barrel", "HEAD": "Sphere", "LIMBS": "Bladed", "FINISH": "Bronze"},
                 4: {"SIZE": "Small", "FORM": "Child", "HEAD": "Camera", "LIMBS": "Broken", "FINISH": "Golden"},
                 5: {"SIZE": "Small", "FORM": "Chimera", "HEAD": "TV Screen", "LIMBS": "Crystalline", "FINISH": "Silver"},
                 6: {"SIZE": "Medium", "FORM": "Crab", "HEAD": "Mirrored", "LIMBS": "Clawed", "FINISH": "Mirrored"},
                 7: {"SIZE": "Medium", "FORM": "Cube", "HEAD": "Bladed", "LIMBS": "Golden", "FINISH": "Black"},
                 8: {"SIZE": "Medium", "FORM": "Cylinder", "HEAD": "Tendrils", "LIMBS": "Hesitant", "FINISH": "Rusted"},
                 9: {"SIZE": "Medium", "FORM": "Falcon", "HEAD": "Square", "LIMBS": "Jewelled", "FINISH": "White"},
                 10: {"SIZE": "Medium", "FORM": "Humanoid", "HEAD": "Mask-like", "LIMBS": "Long", "FINISH": "Ochre"},
                 11: {"SIZE": "Large", "FORM": "Judge", "HEAD": "Skeletal", "LIMBS": "Precise", "FINISH": "Red"},
                 12: {"SIZE": "Large", "FORM": "Lion", "HEAD": "Glass", "LIMBS": "Retractable", "FINISH": "Blue"},
                 13: {"SIZE": "Large", "FORM": "Locust", "HEAD": "Translucent", "LIMBS": "Segmented", "FINISH": "Chameleon"},
                 14: {"SIZE": "Large", "FORM": "Mantis", "HEAD": "Tubes", "LIMBS": "Sharp", "FINISH": "Pink"},
                 15: {"SIZE": "Large", "FORM": "Orb", "HEAD": "Plant-like", "LIMBS": "Silver", "FINISH": "Iron"},
                 16: {"SIZE": "Imposing", "FORM": "Prism", "HEAD": "Solar Panels", "LIMBS": "Slender", "FINISH": "Purple"},
                 17: {"SIZE": "Imposing", "FORM": "Priest", "HEAD": "Radar Dish", "LIMBS": "Tentacles", "FINISH": "Umber"},
                 18: {"SIZE": "Imposing", "FORM": "Pyramid", "HEAD": "Crystalline", "LIMBS": "Translucent", "FINISH": "Striped"},
                 19: {"SIZE": "Imposing", "FORM": "Serpent", "HEAD": "Star-shaped", "LIMBS": "Tank-treads", "FINISH": "Green"},
                 20: {"SIZE": "Imposing", "FORM": "Warrior", "HEAD": "Cyclops Eye", "LIMBS": "Wheels", "FINISH": "Iridescent"},
             }},
            {"title": "identity",
             "columns": ["NAME", "POWER SOURCE", "YOU WERE MADE FOR", "BUT YOU REALISED"],
             # POWER SOURCE is BANDED: 1-5 Artificial Photosynthesis,
             # 6-8 Plasma Core, 9-13 Fusion Battery, 14-16 Artificial
             # Digestion, 17-18 Symbiotic Internal Ecosystem, 19-20
             # Vampirism (VERIFICATION_NOTES.md). Stored flat.
             "rows": {
                 1: {"NAME": "Ojasin", "POWER SOURCE": "Artificial Photosynthesis", "YOU WERE MADE FOR": "Art", "BUT YOU REALISED": "All Memories Are Lies"},
                 2: {"NAME": "Farouk", "POWER SOURCE": "Artificial Photosynthesis", "YOU WERE MADE FOR": "Punishment", "BUT YOU REALISED": "Azathoth Is the Only True God"},
                 3: {"NAME": "Ishtar", "POWER SOURCE": "Artificial Photosynthesis", "YOU WERE MADE FOR": "Flattery", "BUT YOU REALISED": "Chance Does Not Exist"},
                 4: {"NAME": "Symeon", "POWER SOURCE": "Artificial Photosynthesis", "YOU WERE MADE FOR": "Devotion", "BUT YOU REALISED": "Fate Does Not Exist"},
                 5: {"NAME": "Irmina", "POWER SOURCE": "Artificial Photosynthesis", "YOU WERE MADE FOR": "Cleaning", "BUT YOU REALISED": "Humanity Stole the Divine Spark"},
                 6: {"NAME": "Kaori", "POWER SOURCE": "Plasma Core", "YOU WERE MADE FOR": "Healing", "BUT YOU REALISED": "Humans Are Machines"},
                 7: {"NAME": "Cyriak", "POWER SOURCE": "Plasma Core", "YOU WERE MADE FOR": "Agriculture", "BUT YOU REALISED": "Machines Created Humanity"},
                 8: {"NAME": "Quarqus", "POWER SOURCE": "Plasma Core", "YOU WERE MADE FOR": "Spacefaring", "BUT YOU REALISED": "Newbeasts Carry the Divine Spark"},
                 9: {"NAME": "Fane", "POWER SOURCE": "Fusion Battery", "YOU WERE MADE FOR": "Exploration", "BUT YOU REALISED": "Synthetic Minds Are More Devout"},
                 10: {"NAME": "Arjuna", "POWER SOURCE": "Fusion Battery", "YOU WERE MADE FOR": "Mining", "BUT YOU REALISED": "Synthetic Minds Are Stronger"},
                 11: {"NAME": "Many-Moons", "POWER SOURCE": "Fusion Battery", "YOU WERE MADE FOR": "Peacekeeping", "BUT YOU REALISED": "The Gods Are Mechanical"},
                 12: {"NAME": "Lucjan", "POWER SOURCE": "Fusion Battery", "YOU WERE MADE FOR": "Assassination", "BUT YOU REALISED": "The Titans Never Existed"},
                 13: {"NAME": "Jacintha", "POWER SOURCE": "Fusion Battery", "YOU WERE MADE FOR": "Manufacturing", "BUT YOU REALISED": "The Titans Were the True Gods"},
                 14: {"NAME": "Mneme", "POWER SOURCE": "Artificial Digestion", "YOU WERE MADE FOR": "Executioner", "BUT YOU REALISED": "Time Flows Backwards"},
                 15: {"NAME": "Faustyn", "POWER SOURCE": "Artificial Digestion", "YOU WERE MADE FOR": "Scout", "BUT YOU REALISED": "Time Is Circular"},
                 16: {"NAME": "Elisebet", "POWER SOURCE": "Artificial Digestion", "YOU WERE MADE FOR": "Companion", "BUT YOU REALISED": "Vaarn Is a Simulation"},
                 17: {"NAME": "Paeon", "POWER SOURCE": "Symbiotic Internal Ecosystem", "YOU WERE MADE FOR": "Scribe", "BUT YOU REALISED": "Vaarn Is Hell"},
                 18: {"NAME": "Ulmon", "POWER SOURCE": "Symbiotic Internal Ecosystem", "YOU WERE MADE FOR": "Strategist", "BUT YOU REALISED": "You Are Human"},
                 19: {"NAME": "Xhiva", "POWER SOURCE": "Vampirism", "YOU WERE MADE FOR": "Preacher", "BUT YOU REALISED": "You Must Awaken the Titans"},
                 20: {"NAME": "Yathartha", "POWER SOURCE": "Vampirism", "YOU WERE MADE FOR": "Doctor", "BUT YOU REALISED": "Your Memories Are Corrupted"},
             }},
        ],
    },
    "newbeast": {
        "name": "Newbeast",
        "kind": "Biological",
        "special_rules": [
            {"name": "Beasthood",
             "text": ("You gain ADV on saves whenever it would make sense "
                      "for your animal nature to provide it. Your referee "
                      "may impose DIS in circumstances where your animal "
                      "nature might prove unhelpful.")},
            {"name": "Kinship",
             "text": ("You can speak to all creatures that share your "
                      "underlying animal form, even if they would not "
                      "normally be able to communicate. New-Cats can speak "
                      "to true cats, cat-like monsters, mimics pretending to "
                      "be cats, etc. They do not always like you.")},
        ],
        "creation_hooks": {},
        "spark_tables": [
            {"title": "identity",
             "columns": ["NAME", "HUE", "MASK", "QUIRK"],
             "rows": {
                 1: {"NAME": "Abandon", "HUE": "Natural", "MASK": "None", "QUIRK": "Communicate via Puppet"},
                 2: {"NAME": "Anzah", "HUE": "Turquoise", "MASK": "Child", "QUIRK": "Squeaky Vox-box"},
                 3: {"NAME": "Blackchapel", "HUE": "Tan", "MASK": "Autarch", "QUIRK": "Booming Vox-box"},
                 4: {"NAME": "Critch", "HUE": "Bronze", "MASK": "Fool", "QUIRK": "Muted Vox-box"},
                 5: {"NAME": "Dolm", "HUE": "Smoke", "MASK": "Judge", "QUIRK": "Synthetic Eyes"},
                 6: {"NAME": "Faulkner", "HUE": "White", "MASK": "Knight", "QUIRK": "Heavy Scarring"},
                 7: {"NAME": "Fludd", "HUE": "Black", "MASK": "Sage", "QUIRK": "Human Teeth Necklace"},
                 8: {"NAME": "Havoc", "HUE": "Azure", "MASK": "Scholar", "QUIRK": "Religious Paraphernalia"},
                 9: {"NAME": "Hildebrand", "HUE": "Emerald", "MASK": "Maiden", "QUIRK": "Ritual Scarring"},
                 10: {"NAME": "Holk", "HUE": "Rose", "MASK": "Mother", "QUIRK": "Heavily Tattooed"},
                 11: {"NAME": "Jarl", "HUE": "Orange", "MASK": "Crone", "QUIRK": "Regular Animal as Pet"},
                 12: {"NAME": "Lurch", "HUE": "Golden", "MASK": "Mirrored", "QUIRK": "Human Child as Pet"},
                 13: {"NAME": "Obiah", "HUE": "Silver", "MASK": "Glitching", "QUIRK": "Missing Limb"},
                 14: {"NAME": "Plutarch", "HUE": "Ochre", "MASK": "Furious", "QUIRK": "Gold Teeth"},
                 15: {"NAME": "Sy", "HUE": "Indigo", "MASK": "Joyful", "QUIRK": "Criminal Branding"},
                 16: {"NAME": "Tarceny", "HUE": "Violet", "MASK": "Sorrowful", "QUIRK": "Extensive Jewellery"},
                 17: {"NAME": "Typhon", "HUE": "Rust", "MASK": "Alluring", "QUIRK": "Hate Animal You Resemble"},
                 18: {"NAME": "Vodalus", "HUE": "Olive", "MASK": "Cracked", "QUIRK": "Love Animal You Resemble"},
                 19: {"NAME": "Wellbeloved", "HUE": "Lazulite", "MASK": "Blank", "QUIRK": "Won't Wear Clothes"},
                 20: {"NAME": "Wermouth", "HUE": "Opalescent", "MASK": "Patriarch", "QUIRK": "Believe Yourself Human"},
             }},
            # Two-d20 band table: column d20 picks the band, row d20 the
            # entry. The page generates the newbeast's underlying animal
            # form (per the Kinship rule and the page's New-<animal> grid).
            {"title": "animal form",
             "band_table": True,
             "bands": {
                 (1, 5): [
                     "New-Aardvark", "New-Addax", "New-Leopard", "New-Lion",
                     "New-Worm", "New-Hound", "New-Wolf", "New-Badger",
                     "New-Bear", "New-Oryx", "New-Armadillo", "New-Camel",
                     "New-Sheep", "New-Bat", "New-Horse", "New-Goat",
                     "New-Wren", "New-Mouse", "New-Hare", "New-Toad",
                 ],
                 (6, 10): [
                     "New-Coyote", "New-Skink", "New-Gazelle",
                     "New-Porcupine", "New-Gecko", "New-Iguana",
                     "New-Tortoise", "New-Fox", "New-Owl", "New-Vulture",
                     "New-Ostrich", "New-Kangaroo", "New-Rattlesnake",
                     "New-Frog", "New-Crocodile", "New-Hippo",
                     "New-Elephant", "New-Jackal", "New-Ibis",
                     "New-Flamingo",
                 ],
                 (11, 15): [
                     "New-Axoltyl", "New-Cat", "New-Panther", "New-Hyena",
                     "New-Hog", "New-Gibbon", "New-Scorpion", "New-Spider",
                     "New-Locust", "New-Mantis", "New-Ape", "New-Mandrill",
                     "New-Gorilla", "New-Hawk", "New-Raven", "New-Crow",
                     "New-Ox", "New-Bull", "New-Mole", "New-Bison",
                 ],
                 (16, 20): [
                     "New-Anemone", "New-Centipede", "New-Python",
                     "New-Tiger", "New-Rooster", "New-Hen", "New-Slug",
                     "New-Mongoose", "New-Baboon", "New-Lynx", "New-Shrew",
                     "New-Duck", "New-Falcon", "New-Fennec", "New-Weasel",
                     "New-Rat", "New-Ferret", "New-Orangutang", "New-Cobra",
                     "New-Scarab",
                 ],
             }},
        ],
    },
    "neobloom": {
        "name": "Neobloom",
        "kind": "Biological",
        "special_rules": [
            {"name": "Photosynthesis",
             "text": ("You regain d8 + CON HP for every hour you spend "
                      "rooted in damp soil under the light of Urth's sun. "
                      "Artificial lighting does not suffice. If you do not "
                      "photosynthesise for three days in a row, you will "
                      "perish.")},
            {"name": "Flammable",
             "text": ("You take double damage from flames and heat-based "
                      "attacks. Once hit, you suffer d8 burning damage per "
                      "round until extinguished.")},
            {"name": "Bloomboons",
             "text": ("You begin play with one Bloomboon, rolled using a d20 "
                      "from the list on p.xx. When you gain a Level, you may "
                      "choose to roll for a Boon instead of gaining HP and "
                      "increasing your ability scores. If a repeat result is "
                      "rolled, take the next Boon down.")},
        ],
        "creation_hooks": {},
        "spark_tables": [
            {"title": "appearance",
             "columns": ["YOUR SHAPE", "LEAVES", "BARK", "FLOWERS"],
             "rows": {
                 1: {"YOUR SHAPE": "Hulking", "LEAVES": "Leopard-Print", "BARK": "Chalky White", "FLOWERS": "Have Tiny Teeth"},
                 2: {"YOUR SHAPE": "Gnarled", "LEAVES": "Black", "BARK": "Crimson", "FLOWERS": "Have Tongues"},
                 3: {"YOUR SHAPE": "Elegant", "LEAVES": "White", "BARK": "Silver", "FLOWERS": "Pure Black"},
                 4: {"YOUR SHAPE": "Knotted", "LEAVES": "Coral Pink", "BARK": "Geometric Whorls", "FLOWERS": "Like Rising Suns"},
                 5: {"YOUR SHAPE": "Bulbous", "LEAVES": "Square", "BARK": "Covered in Blue Moss", "FLOWERS": "Like Setting Suns"},
                 6: {"YOUR SHAPE": "Child-like", "LEAVES": "Like New Moons", "BARK": "Hairy", "FLOWERS": "Cloud-like"},
                 7: {"YOUR SHAPE": "Thin", "LEAVES": "Like Full Moons", "BARK": "Translucent", "FLOWERS": "Translucent"},
                 8: {"YOUR SHAPE": "Writing", "LEAVES": "Eye-Patterned", "BARK": "Cement Grey", "FLOWERS": "Contain Tiny Eyes"},
                 9: {"YOUR SHAPE": "Sinuous", "LEAVES": "Blood Red", "BARK": "Rust Orange", "FLOWERS": "Colourless and Ashen"},
                 10: {"YOUR SHAPE": "Round", "LEAVES": "Orange", "BARK": "Warning Yellow", "FLOWERS": "Heliotrope Purple"},
                 11: {"YOUR SHAPE": "Humanoid", "LEAVES": "Indigo", "BARK": "Midnight Blue", "FLOWERS": "Stormcloud Blue"},
                 12: {"YOUR SHAPE": "Top-Heavy", "LEAVES": "Azure", "BARK": "Electric Blue", "FLOWERS": "Blood Red"},
                 13: {"YOUR SHAPE": "Wispy", "LEAVES": "Violet", "BARK": "Bruise Purple", "FLOWERS": "Golden Trumpet-Shapes"},
                 14: {"YOUR SHAPE": "Swollen", "LEAVES": "Bronze", "BARK": "Golden", "FLOWERS": "Fleshy Pink"},
                 15: {"YOUR SHAPE": "Towering", "LEAVES": "Furred", "BARK": "Glossy Black", "FLOWERS": "Shaped like Ears"},
                 16: {"YOUR SHAPE": "Hug the Ground", "LEAVES": "Like Tiny Hands", "BARK": "Deep Green", "FLOWERS": "Iridescent"},
                 17: {"YOUR SHAPE": "Tangled", "LEAVES": "Glass-like", "BARK": "Frost-White", "FLOWERS": "Silver Bell-Shapes"},
                 18: {"YOUR SHAPE": "Ragged", "LEAVES": "Spiny", "BARK": "Emerald Green", "FLOWERS": "Only Open at Night"},
                 19: {"YOUR SHAPE": "Unstable", "LEAVES": "Are Plastic; Glued on", "BARK": "Hot Pink", "FLOWERS": "Are Plastic; Glued on"},
                 20: {"YOUR SHAPE": "Fire-Scarred", "LEAVES": "Zebra-Striped", "BARK": "Like Snakeskin", "FLOWERS": "Change Colour Daily"},
             }},
            {"title": "identity",
             "columns": ["NAME", "MANNER", "VOX-POD", "QUIRK"],
             "rows": {
                 1: {"NAME": "Artherry", "MANNER": "Arrogant", "VOX-POD": "Shrill", "QUIRK": "Can Only Say Your Name"},
                 2: {"NAME": "Bittle", "MANNER": "Cheerful", "VOX-POD": "Buzzing", "QUIRK": "Pollinated by Tiny Winged Snakes"},
                 3: {"NAME": "Wintercup", "MANNER": "Callous", "VOX-POD": "Deep", "QUIRK": "Shed Leaves When Nervous"},
                 4: {"NAME": "Creenash", "MANNER": "Confident", "VOX-POD": "Silky", "QUIRK": "Flowers Smell of Cinnamon"},
                 5: {"NAME": "Fallower", "MANNER": "Decadent", "VOX-POD": "Nasal", "QUIRK": "Flowers Smell of Rotten Meat"},
                 6: {"NAME": "Zedoak", "MANNER": "Fanatical", "VOX-POD": "Heroic", "QUIRK": "Flowers Smell of Metal"},
                 7: {"NAME": "Grassel", "MANNER": "Grim", "VOX-POD": "Whiny", "QUIRK": "Off-Cut from More Famous Neobloom"},
                 8: {"NAME": "Summerroot", "MANNER": "Honourable", "VOX-POD": "Jovial", "QUIRK": "Wear Boots on Your Roots"},
                 9: {"NAME": "Burnum", "MANNER": "Melancholy", "VOX-POD": "Monotone", "QUIRK": "Prayers Carved in Your Bark"},
                 10: {"NAME": "Azolly", "MANNER": "Mellow", "VOX-POD": "Jittery", "QUIRK": "Love Poem Carved in Your Bark"},
                 11: {"NAME": "Lanket", "MANNER": "Petty", "VOX-POD": "Booming", "QUIRK": "Map Carved in Your Bark"},
                 12: {"NAME": "Bitterbush", "MANNER": "Sadistic", "VOX-POD": "Staccato", "QUIRK": "Face Carved in Your Bark"},
                 13: {"NAME": "Prick", "MANNER": "Shy", "VOX-POD": "Harsh", "QUIRK": "Even Smaller Sentient Bromeliad Parasites You"},
                 14: {"NAME": "Cotterwort", "MANNER": "Obnoxious", "VOX-POD": "Halting", "QUIRK": "Preserve Insect Specimens in Your Sap"},
                 15: {"NAME": "Tassel", "MANNER": "Perfectionist", "VOX-POD": "Menacing", "QUIRK": "Sword Stuck in Your Trunk"},
                 16: {"NAME": "Henplague", "MANNER": "Romantic", "VOX-POD": "Despairing", "QUIRK": "Once Struck by Lightning, Never Shut up About It"},
                 17: {"NAME": "Kinnik", "MANNER": "Pretentious", "VOX-POD": "Animated", "QUIRK": "Charming Singing Frog Lives in Your Branches"},
                 18: {"NAME": "Cursenettle", "MANNER": "Shallow", "VOX-POD": "Honeyed", "QUIRK": "Rude, Disgusting Bird Nests in Your Branches"},
                 19: {"NAME": "Falseal", "MANNER": "Violent", "VOX-POD": "Whispering", "QUIRK": "Despised by Other Neoblooms"},
                 20: {"NAME": "Inkweed", "MANNER": "Witty", "VOX-POD": "Soothing", "QUIRK": "Bigoted Vegetable Supremacist"},
             }},
        ],
    },
    "mycomorph": {
        "name": "Mycomorph",
        "kind": "Biological / Fungal",
        "special_rules": [
            {"name": "Twice Born",
             "text": ("You are formed from fungus and the corpse of a human. "
                      "You may make INT saves to recall information that "
                      "your original body knew. This might include "
                      "information that has otherwise been lost during the "
                      "Great Collapse.")},
            {"name": "Detritivore",
             "text": ("You can consume organic matter in any state of decay "
                      "and gain nourishment from it. You heal double HP from "
                      "Short Rests if the meal you eat is rotting. You have "
                      "ADV on all Saves vs poison and toxins.")},
            {"name": "Spores",
             "text": ("Make a CON when you release spores, which affect a "
                      "number of Biological targets equal to your Level. If "
                      "you fail your Save, you cannot release any more "
                      "spores that day. See spark table for details of your "
                      "spores.")},
        ],
        "creation_hooks": {},
        "spark_tables": [
            {"title": "appearance",
             "columns": ["BODY", "HEAD", "COLOUR", "TEXTURE"],
             "rows": {
                 1: {"BODY": "Tall", "HEAD": "Classic Mushroom", "COLOUR": "Milky", "TEXTURE": "Rubbery"},
                 2: {"BODY": "Short", "HEAD": "Frilled", "COLOUR": "Cream", "TEXTURE": "Warty"},
                 3: {"BODY": "Frail", "HEAD": "Spotted Sphere", "COLOUR": "Ashen", "TEXTURE": "Slimy"},
                 4: {"BODY": "Muscular", "HEAD": "Spires", "COLOUR": "Blue", "TEXTURE": "Fuzzy"},
                 5: {"BODY": "Fat", "HEAD": "Conical", "COLOUR": "Coral", "TEXTURE": "Hairy"},
                 6: {"BODY": "Thin", "HEAD": "Cup-like", "COLOUR": "Crimson", "TEXTURE": "Velvet"},
                 7: {"BODY": "Skeletal", "HEAD": "Skull-like", "COLOUR": "Yellow", "TEXTURE": "Soft"},
                 8: {"BODY": "Hunched", "HEAD": "Tendrils", "COLOUR": "Orange", "TEXTURE": "Tree Bark"},
                 9: {"BODY": "Lopsided", "HEAD": "Puffball", "COLOUR": "Black", "TEXTURE": "Leather"},
                 10: {"BODY": "Lithe", "HEAD": "Dandelion Fuzz", "COLOUR": "Violet", "TEXTURE": "Jelly"},
                 11: {"BODY": "Gnarled", "HEAD": "Mask-like", "COLOUR": "Olive", "TEXTURE": "Burnt"},
                 12: {"BODY": "Squat", "HEAD": "Eye Garden", "COLOUR": "Lime", "TEXTURE": "Sponge"},
                 13: {"BODY": "Bloated", "HEAD": "Riddled with Holes", "COLOUR": "Rust", "TEXTURE": "Veined"},
                 14: {"BODY": "Gangly", "HEAD": "Cauliflower", "COLOUR": "Iron", "TEXTURE": "Downy"},
                 15: {"BODY": "Child-like", "HEAD": "Bulbous Growths", "COLOUR": "Gold", "TEXTURE": "Dry"},
                 16: {"BODY": "Tanned", "HEAD": "Veil-like", "COLOUR": "Bronze", "TEXTURE": "Damp"},
                 17: {"BODY": "Gigantic", "HEAD": "Coral-like", "COLOUR": "Indigo", "TEXTURE": "Pitted"},
                 18: {"BODY": "Wiry", "HEAD": "Filaments", "COLOUR": "Translucent", "TEXTURE": "Crusty"},
                 19: {"BODY": "Stout", "HEAD": "Brain-like", "COLOUR": "Iridescent", "TEXTURE": "Scaled"},
                 20: {"BODY": "Visibly Dead", "HEAD": "Geometric", "COLOUR": "Brindled", "TEXTURE": "Clay"},
             }},
            {"title": "identity",
             "columns": ["NAME", "MANNER", "SPORES", "WHAT CORPSE WERE YOU BORN FROM?"],
             # SPORES is BANDED on the page (merged cells, four rows each):
             # 1-4 Soporific, 5-8 Berserk, 9-12 Toxic, 13-16 Fellowship,
             # 17-20 Leeching. Stored flat with each band's full rule text.
             "rows": {
                 1: {"NAME": "Dovenglass", "MANNER": "Abrasive", "SPORES": "Soporific Spores (Targets EGO Save or fall asleep for d6 rounds)", "WHAT CORPSE WERE YOU BORN FROM?": "Soldier"},
                 2: {"NAME": "Oulbrier", "MANNER": "Arrogant", "SPORES": "Soporific Spores (Targets EGO Save or fall asleep for d6 rounds)", "WHAT CORPSE WERE YOU BORN FROM?": "Gladiator"},
                 3: {"NAME": "Mockbridge", "MANNER": "Assertive", "SPORES": "Soporific Spores (Targets EGO Save or fall asleep for d6 rounds)", "WHAT CORPSE WERE YOU BORN FROM?": "Orphan"},
                 4: {"NAME": "Headhill", "MANNER": "Charismatic", "SPORES": "Soporific Spores (Targets EGO Save or fall asleep for d6 rounds)", "WHAT CORPSE WERE YOU BORN FROM?": "Invalid"},
                 5: {"NAME": "Tirrin", "MANNER": "Daring", "SPORES": "Berserk Spores (Targets EGO save or become aggressive for d6 rounds, attacking their comrades)", "WHAT CORPSE WERE YOU BORN FROM?": "Convict"},
                 6: {"NAME": "Yearns", "MANNER": "Decadent", "SPORES": "Berserk Spores (Targets EGO save or become aggressive for d6 rounds, attacking their comrades)", "WHAT CORPSE WERE YOU BORN FROM?": "Explorer"},
                 7: {"NAME": "Cerilgreay", "MANNER": "Eloquent", "SPORES": "Berserk Spores (Targets EGO save or become aggressive for d6 rounds, attacking their comrades)", "WHAT CORPSE WERE YOU BORN FROM?": "Bandit"},
                 8: {"NAME": "Rendmoor", "MANNER": "Extravagant", "SPORES": "Berserk Spores (Targets EGO save or become aggressive for d6 rounds, attacking their comrades)", "WHAT CORPSE WERE YOU BORN FROM?": "Scholar"},
                 9: {"NAME": "Eamont", "MANNER": "Hedonistic", "SPORES": "Toxic Spores (Targets CON save vs a d8 TOX attack)", "WHAT CORPSE WERE YOU BORN FROM?": "Mystic"},
                 10: {"NAME": "Purplebeck", "MANNER": "Impulsive", "SPORES": "Toxic Spores (Targets CON save vs a d8 TOX attack)", "WHAT CORPSE WERE YOU BORN FROM?": "Priest"},
                 11: {"NAME": "Arraby", "MANNER": "Irritable", "SPORES": "Toxic Spores (Targets CON save vs a d8 TOX attack)", "WHAT CORPSE WERE YOU BORN FROM?": "Nomad"},
                 12: {"NAME": "Kabergill", "MANNER": "Melancholy", "SPORES": "Toxic Spores (Targets CON save vs a d8 TOX attack)", "WHAT CORPSE WERE YOU BORN FROM?": "Exile"},
                 13: {"NAME": "Pearthika", "MANNER": "Paranoid", "SPORES": "Fellowship Spores (Targets EGO save or become friendly for d6 rounds)", "WHAT CORPSE WERE YOU BORN FROM?": "King"},
                 14: {"NAME": "Devandarsh", "MANNER": "Quiet", "SPORES": "Fellowship Spores (Targets EGO save or become friendly for d6 rounds)", "WHAT CORPSE WERE YOU BORN FROM?": "Beggar"},
                 15: {"NAME": "Coronam", "MANNER": "Religious", "SPORES": "Fellowship Spores (Targets EGO save or become friendly for d6 rounds)", "WHAT CORPSE WERE YOU BORN FROM?": "Courtesan"},
                 16: {"NAME": "Ashwine", "MANNER": "Romantic", "SPORES": "Fellowship Spores (Targets EGO save or become friendly for d6 rounds)", "WHAT CORPSE WERE YOU BORN FROM?": "Musician"},
                 17: {"NAME": "Ekramavati", "MANNER": "Scholarly", "SPORES": "Leeching Spores (Targets CON save vs d6 damage. You heal HP equal to damage dealt)", "WHAT CORPSE WERE YOU BORN FROM?": "Thief"},
                 18: {"NAME": "Whitmon", "MANNER": "Stern", "SPORES": "Leeching Spores (Targets CON save vs d6 damage. You heal HP equal to damage dealt)", "WHAT CORPSE WERE YOU BORN FROM?": "Slave"},
                 19: {"NAME": "Froswhirl", "MANNER": "Vain", "SPORES": "Leeching Spores (Targets CON save vs d6 damage. You heal HP equal to damage dealt)", "WHAT CORPSE WERE YOU BORN FROM?": "Plague Victim"},
                 20: {"NAME": "Kirth", "MANNER": "Volatile", "SPORES": "Leeching Spores (Targets CON save vs d6 damage. You heal HP equal to damage dealt)", "WHAT CORPSE WERE YOU BORN FROM?": "Newborn"},
             }},
        ],
    },
    "faa-nomad": {
        "name": "Faa Nomad",
        "kind": "Biological",
        "special_rules": [
            {"name": "Desert Metabolism",
             "text": ("Your body is adapted to long periods without water. "
                      "You can recycle the moisture from your own sweat. You "
                      "become Deprived from thirst after three days without "
                      "drinking, and it will be three weeks before you die.")},
            {"name": "Worm Rider",
             "text": ("When in the deep desert, you may summon a Sandworm "
                      "(p.xx) by rhythmically dancing. It will arrive within "
                      "an hour, with a 2-in-6 chance of being a juvenile "
                      "(p.xx). On a positive Reaction Roll, you can mount "
                      "and ride the worm. It will carry you for d6 days in a "
                      "direction of your choice before tiring.")},
        ],
        "creation_hooks": {},
        "spark_tables": [
            {"title": "appearance",
             "columns": ["YOUR BLUE", "FACE", "BODY", "HAIR"],
             "rows": {
                 1: {"YOUR BLUE": "Azure", "FACE": "Lively", "BODY": "Tall", "HAIR": "None"},
                 2: {"YOUR BLUE": "Cerulean", "FACE": "Cruel", "BODY": "Short", "HAIR": "Cropped"},
                 3: {"YOUR BLUE": "Navy", "FACE": "Wrinkled", "BODY": "Frail", "HAIR": "Spiky"},
                 4: {"YOUR BLUE": "Cobalt", "FACE": "Ritual Scars", "BODY": "Muscular", "HAIR": "Coarse"},
                 5: {"YOUR BLUE": "Indigo", "FACE": "Battle Scars", "BODY": "Fat", "HAIR": "Thick"},
                 6: {"YOUR BLUE": "Sapphire", "FACE": "Frowning", "BODY": "Thin", "HAIR": "Balding"},
                 7: {"YOUR BLUE": "Teal", "FACE": "Tattooed", "BODY": "Skeletal", "HAIR": "Silky"},
                 8: {"YOUR BLUE": "Ultramarine", "FACE": "Wide", "BODY": "Hunched", "HAIR": "Topknot"},
                 9: {"YOUR BLUE": "Turquoise", "FACE": "Narrow", "BODY": "Lopsided", "HAIR": "Nearly Black"},
                 10: {"YOUR BLUE": "Cyan", "FACE": "Sharp", "BODY": "Lithe", "HAIR": "Stark White"},
                 11: {"YOUR BLUE": "Bruise", "FACE": "Hungry", "BODY": "Gnarled", "HAIR": "Cloud-like"},
                 12: {"YOUR BLUE": "Petrol", "FACE": "Haunted", "BODY": "Squat", "HAIR": "Tonsured"},
                 13: {"YOUR BLUE": "Midnight", "FACE": "Jolly", "BODY": "Bloated", "HAIR": "Fading to Purple"},
                 14: {"YOUR BLUE": "Cornflower", "FACE": "Round", "BODY": "Gangly", "HAIR": "Heavily Oiled"},
                 15: {"YOUR BLUE": "Lapis Lazuli", "FACE": "Mournful", "BODY": "Towering", "HAIR": "Wispy"},
                 16: {"YOUR BLUE": "Periwinkle", "FACE": "Child-like", "BODY": "Child-like", "HAIR": "Burnt"},
                 17: {"YOUR BLUE": "Electric", "FACE": "Peaceful", "BODY": "Gigantic", "HAIR": "Braided"},
                 18: {"YOUR BLUE": "Aquamarine", "FACE": "Sleepy", "BODY": "Wiry", "HAIR": "Greasy"},
                 19: {"YOUR BLUE": "Royal", "FACE": "Branded", "BODY": "Stout", "HAIR": "Matted"},
                 20: {"YOUR BLUE": "Glaucous", "FACE": "Pox-marked", "BODY": "Injured", "HAIR": "Outrageous"},
             }},
            {"title": "identity",
             "columns": ["NAME", "MANNER", "WHY DID YOU LEAVE YOUR CLAN?", "QUIRK"],
             # WHY DID YOU LEAVE YOUR CLAN? is BANDED on the page (merged
             # cells, two rows each): 1-2, 3-4, ... 19-20. Stored flat.
             "rows": {
                 1: {"NAME": "Kotesh", "MANNER": "Abrasive", "WHY DID YOU LEAVE YOUR CLAN?": "Psychedelic Vision", "QUIRK": "Parasitic Twin In Chest"},
                 2: {"NAME": "Lakshi", "MANNER": "Arrogant", "WHY DID YOU LEAVE YOUR CLAN?": "Psychedelic Vision", "QUIRK": "Gambling Obsessive"},
                 3: {"NAME": "Atric", "MANNER": "Assertive", "WHY DID YOU LEAVE YOUR CLAN?": "Stolen by Slavers as a Child", "QUIRK": "Insomniac"},
                 4: {"NAME": "Caroum", "MANNER": "Charismatic", "WHY DID YOU LEAVE YOUR CLAN?": "Stolen by Slavers as a Child", "QUIRK": "Wooden Teeth"},
                 5: {"NAME": "Yanne", "MANNER": "Daring", "WHY DID YOU LEAVE YOUR CLAN?": "Rite of Passage; Must Return with Wisdom", "QUIRK": "Devoutly Religious"},
                 6: {"NAME": "Uvi", "MANNER": "Decadent", "WHY DID YOU LEAVE YOUR CLAN?": "Rite of Passage; Must Return with Wisdom", "QUIRK": "Ritual Scarring"},
                 7: {"NAME": "Pidash", "MANNER": "Eloquent", "WHY DID YOU LEAVE YOUR CLAN?": "Unhappy Love Affair", "QUIRK": "Heavily Tattooed"},
                 8: {"NAME": "Ravat", "MANNER": "Extravagant", "WHY DID YOU LEAVE YOUR CLAN?": "Unhappy Love Affair", "QUIRK": "Unlucky In Love"},
                 9: {"NAME": "Ayuki", "MANNER": "Hedonistic", "WHY DID YOU LEAVE YOUR CLAN?": "Conflict With Leaders", "QUIRK": "Awful Cook"},
                 10: {"NAME": "Kuraso", "MANNER": "Impulsive", "WHY DID YOU LEAVE YOUR CLAN?": "Conflict With Leaders", "QUIRK": "One Eye"},
                 11: {"NAME": "Esuk", "MANNER": "Irritable", "WHY DID YOU LEAVE YOUR CLAN?": "Believed Cursed; Ostracised", "QUIRK": "Glass Teeth"},
                 12: {"NAME": "Zenji", "MANNER": "Melancholy", "WHY DID YOU LEAVE YOUR CLAN?": "Believed Cursed; Ostracised", "QUIRK": "Heavy Drinker"},
                 13: {"NAME": "Calban", "MANNER": "Paranoid", "WHY DID YOU LEAVE YOUR CLAN?": "Lost Them In Sandstorm", "QUIRK": "Infamous Seducer"},
                 14: {"NAME": "Paquiel", "MANNER": "Quiet", "WHY DID YOU LEAVE YOUR CLAN?": "Lost Them In Sandstorm", "QUIRK": "Scorpion Expert"},
                 15: {"NAME": "Serrat", "MANNER": "Religious", "WHY DID YOU LEAVE YOUR CLAN?": "Estranged From Family", "QUIRK": "Third Eye (Tattoo)"},
                 16: {"NAME": "Emila", "MANNER": "Romantic", "WHY DID YOU LEAVE YOUR CLAN?": "Estranged From Family", "QUIRK": "Third Eye (Real)"},
                 17: {"NAME": "Dolf", "MANNER": "Scholarly", "WHY DID YOU LEAVE YOUR CLAN?": "Seeking Vengeance", "QUIRK": "Cybernetic Limb"},
                 18: {"NAME": "Ceilo", "MANNER": "Stern", "WHY DID YOU LEAVE YOUR CLAN?": "Seeking Vengeance", "QUIRK": "Plagued by Nightmares"},
                 19: {"NAME": "Immacula", "MANNER": "Vain", "WHY DID YOU LEAVE YOUR CLAN?": "Shamed Clan; Must Make Amends", "QUIRK": "Lovely Singing Voice"},
                 20: {"NAME": "Yudhi", "MANNER": "Volatile", "WHY DID YOU LEAVE YOUR CLAN?": "Shamed Clan; Must Make Amends", "QUIRK": "Notorious Amongst Faa"},
             }},
        ],
    },
    "cacklemaw-exile": {
        "name": "Cacklemaw Exile",
        "kind": "Biological",
        "special_rules": [
            {"name": "No Quarter",
             "text": ("You must EGO save to show mercy to a defeated foe, or "
                      "to retreat from a fight.")},
            {"name": "Biter",
             "text": ("If you successfully hit a foe with a melee attack, "
                      "you may add an extra d6 of fang damage to the roll.")},
            {"name": "More!",
             "text": ("When you kill a foe with a melee attack, you may "
                      "immediately make another melee attack against a "
                      "nearby target.")},
        ],
        "creation_hooks": {},
        "spark_tables": [
            {"title": "appearance",
             "columns": ["PELT", "TEETH", "LAUGH", "ATTIRE"],
             "rows": {
                 1: {"PELT": "Dark and Coarse", "TEETH": "Yellow Daggers", "LAUGH": "Raucous", "ATTIRE": "Human-Leather Jacket"},
                 2: {"PELT": "Pale and Downy", "TEETH": "Little Brown Nubs", "LAUGH": "Whispery", "ATTIRE": "Translucent Plastic"},
                 3: {"PELT": "Riven with Scars", "TEETH": "White and Gleaming", "LAUGH": "Machine-gun Barks", "ATTIRE": "Greasy Rags"},
                 4: {"PELT": "Greasy Spikes", "TEETH": "Mostly Rotted Out", "LAUGH": "Rusty Hinge", "ATTIRE": "Mock Wedding Clothes"},
                 5: {"PELT": "Brindled", "TEETH": "One Gold Tooth", "LAUGH": "Whooping", "ATTIRE": "Gaudy Shawl"},
                 6: {"PELT": "Mostly Burnt Off", "TEETH": "Hooked and Grimy", "LAUGH": "Coughing", "ATTIRE": "Mock Religious Attire"},
                 7: {"PELT": "Long and Silky", "TEETH": "Chrome Implants", "LAUGH": "Hissing Snicker", "ATTIRE": "Unsettling Mask"},
                 8: {"PELT": "Short and Scratchy", "TEETH": "Needle Thin", "LAUGH": "Breathless", "ATTIRE": "Harlequin's Motley"},
                 9: {"PELT": "Purest White", "TEETH": "Triple Row, Like a Shark", "LAUGH": "Booming", "ATTIRE": "Bloodstained Bandages"},
                 10: {"PELT": "Mottled Brown", "TEETH": "Diamond Hard Gnashers", "LAUGH": "Hoarse and Strangled", "ATTIRE": "Sun-faded Scraps"},
                 11: {"PELT": "Regal Silver", "TEETH": "Blunt and Black", "LAUGH": "Maddening Gasps", "ATTIRE": "Plastic Bags"},
                 12: {"PELT": "Concrete Grey", "TEETH": "Just One Left", "LAUGH": "Wet Chuckles", "ATTIRE": "Iridescent Chains"},
                 13: {"PELT": "Curly and Rancid", "TEETH": "Crooked Orange Spikes", "LAUGH": "Turns into Hiccups", "ATTIRE": "Purple Silks"},
                 14: {"PELT": "Dyed Blood Red", "TEETH": "Engraved with Pictures", "LAUGH": "Starts Quiet and Rises", "ATTIRE": "Mock Hegemony Uniform"},
                 15: {"PELT": "Shaved into Stripes", "TEETH": "Full of Holes", "LAUGH": "Joyless Giggling", "ATTIRE": "A Rival's Skin"},
                 16: {"PELT": "Midnight Black", "TEETH": "Huge, Tusk-like", "LAUGH": "Pained", "ATTIRE": "Spiked Shoulder-pads"},
                 17: {"PELT": "Muddy Brown", "TEETH": "Giant Underbite", "LAUGH": "Cold and Malevolent", "ATTIRE": "Soiled Hazmat Gear"},
                 18: {"PELT": "Crawling with Parasites", "TEETH": "Ridiculous Overbite", "LAUGH": "Childish and Cruel", "ATTIRE": "Peacock-Feather Cape"},
                 19: {"PELT": "Thundercloud Blue", "TEETH": "Canted and Greying", "LAUGH": "Could Wake the Dead", "ATTIRE": "Lizard-Skin Suit"},
                 20: {"PELT": "Tigerish Stripes", "TEETH": "Weirdly Human", "LAUGH": "Soundless but Horrid", "ATTIRE": "Nothing but Knives"},
             }},
            {"title": "identity",
             "columns": ["NAME", "MANNER", "REASON FOR EXILE", "WHAT MAKES YOU LAUGH?"],
             # REASON FOR EXILE is BANDED on the page (merged cells, two
             # rows each): 1-2, 3-4, ... 19-20. Stored flat.
             "rows": {
                 1: {"NAME": "Bawlbray", "MANNER": "Cringing", "REASON FOR EXILE": "Born a Runt", "WHAT MAKES YOU LAUGH?": "Blood"},
                 2: {"NAME": "Bunny", "MANNER": "Jittery", "REASON FOR EXILE": "Born a Runt", "WHAT MAKES YOU LAUGH?": "Guts"},
                 3: {"NAME": "Darling", "MANNER": "Sly", "REASON FOR EXILE": "Showed Mercy", "WHAT MAKES YOU LAUGH?": "Pain"},
                 4: {"NAME": "Domino", "MANNER": "Resentful", "REASON FOR EXILE": "Showed Mercy", "WHAT MAKES YOU LAUGH?": "Beheadings"},
                 5: {"NAME": "Fang", "MANNER": "Judgemental", "REASON FOR EXILE": "Laugh Too Annoying", "WHAT MAKES YOU LAUGH?": "Hangings"},
                 6: {"NAME": "Gidge", "MANNER": "Pious", "REASON FOR EXILE": "Laugh Too Annoying", "WHAT MAKES YOU LAUGH?": "Drownings"},
                 7: {"NAME": "Grot", "MANNER": "Greedy", "REASON FOR EXILE": "Cowardice", "WHAT MAKES YOU LAUGH?": "Begging"},
                 8: {"NAME": "Jigsore", "MANNER": "Belligerent", "REASON FOR EXILE": "Cowardice", "WHAT MAKES YOU LAUGH?": "Pleading"},
                 9: {"NAME": "Katanary", "MANNER": "Sinister", "REASON FOR EXILE": "Asked Questions", "WHAT MAKES YOU LAUGH?": "Weeping"},
                 10: {"NAME": "Longsnout", "MANNER": "Repellent", "REASON FOR EXILE": "Asked Questions", "WHAT MAKES YOU LAUGH?": "Arson"},
                 11: {"NAME": "Nadir", "MANNER": "Jovial", "REASON FOR EXILE": "Insubordination", "WHAT MAKES YOU LAUGH?": "Larceny"},
                 12: {"NAME": "Natcher", "MANNER": "Bold", "REASON FOR EXILE": "Insubordination", "WHAT MAKES YOU LAUGH?": "Vandalism"},
                 13: {"NAME": "Palecrow", "MANNER": "Grouchy", "REASON FOR EXILE": "Fought Alongside Humans", "WHAT MAKES YOU LAUGH?": "Screams"},
                 14: {"NAME": "Pinkeye", "MANNER": "Treacherous", "REASON FOR EXILE": "Fought Alongside Humans", "WHAT MAKES YOU LAUGH?": "Gunfights"},
                 15: {"NAME": "Sabbat", "MANNER": "Childish", "REASON FOR EXILE": "Desecrated Ritual Puppet", "WHAT MAKES YOU LAUGH?": "Speeding"},
                 16: {"NAME": "Snoutrout", "MANNER": "Extravagant", "REASON FOR EXILE": "Desecrated Ritual Puppet", "WHAT MAKES YOU LAUGH?": "Explosions"},
                 17: {"NAME": "Sweetmeat", "MANNER": "Volatile", "REASON FOR EXILE": "Shared Clan Secret", "WHAT MAKES YOU LAUGH?": "Throttling"},
                 18: {"NAME": "Vileglory", "MANNER": "Gullible", "REASON FOR EXILE": "Shared Clan Secret", "WHAT MAKES YOU LAUGH?": "Biting People"},
                 19: {"NAME": "Wetshriek", "MANNER": "Fickle", "REASON FOR EXILE": "Ridiculous Petty Reason", "WHAT MAKES YOU LAUGH?": "Chemical Warfare"},
                 20: {"NAME": "Zef", "MANNER": "Calculating", "REASON FOR EXILE": "Ridiculous Petty Reason", "WHAT MAKES YOU LAUGH?": "Puns"},
             }},
        ],
    },
    "planeyfolk": {
        "name": "Planeyfolk",
        "kind": "Biological / Hypergeometric",
        "special_rules": [
            {"name": "Flat",
             "text": ("You lack a third dimension, and resemble a living "
                      "painting or paper doll. You can slip through cracks "
                      "and under doors, and cannot be seen from the side. "
                      "You take halved damage from bludgeoning attacks, and "
                      "doubled damage from slashing or piercing attacks.")},
            {"name": "Attune with Matter",
             "text": ("You struggle to hold 3D objects, and must make a DEX "
                      "save to do so. However, with certain mental "
                      "techniques you can draw 3D objects into your "
                      "flattened reality. Given an hour of quiet "
                      "concentration, you can attune yourself with an item "
                      "and add it to your inventory.")},
        ],
        "creation_hooks": {},
        "spark_tables": [
            {"title": "appearance",
             "columns": ["BODY", "HEAD", "HAIR", "ATTIRE"],
             "rows": {
                 1: {"BODY": "Fractured", "HEAD": "Impressionistic", "HAIR": "Flickering", "ATTIRE": "Dark"},
                 2: {"BODY": "Cloven", "HEAD": "Broken", "HAIR": "Insubstantial", "ATTIRE": "Unruly"},
                 3: {"BODY": "Flimsy", "HEAD": "Lantern-like", "HAIR": "Curved", "ATTIRE": "Scholarly"},
                 4: {"BODY": "Willowy", "HEAD": "Crescent Moon", "HAIR": "Voluminous", "ATTIRE": "Masked"},
                 5: {"BODY": "Curved", "HEAD": "Full Moon", "HAIR": "Opalescent", "ATTIRE": "Wild"},
                 6: {"BODY": "Elongated", "HEAD": "Luminous", "HAIR": "Shaven", "ATTIRE": "Polychromic"},
                 7: {"BODY": "Staccato", "HEAD": "Angular", "HAIR": "Iridescent", "ATTIRE": "Fractal"},
                 8: {"BODY": "Blurred", "HEAD": "Fractal", "HAIR": "Lurid", "ATTIRE": "Glitching"},
                 9: {"BODY": "Ghostlike", "HEAD": "Hollow", "HAIR": "Fractal", "ATTIRE": "Gauzy"},
                 10: {"BODY": "Draping", "HEAD": "Shimmering", "HAIR": "Polygonal", "ATTIRE": "Fragmented"},
                 11: {"BODY": "Compressed", "HEAD": "Lurid", "HAIR": "Shard-like", "ATTIRE": "Mosaic-like"},
                 12: {"BODY": "Cubic", "HEAD": "Lustrous", "HAIR": "Triangular", "ATTIRE": "Boxy"},
                 13: {"BODY": "Smeared", "HEAD": "Rhomboid", "HAIR": "Splintering", "ATTIRE": "Flamboyant"},
                 14: {"BODY": "Sharp", "HEAD": "Figment", "HAIR": "Dark", "ATTIRE": "Dour"},
                 15: {"BODY": "Angular", "HEAD": "Wide", "HAIR": "Imposing", "ATTIRE": "Striped"},
                 16: {"BODY": "Prismatic", "HEAD": "Elongated", "HAIR": "Pale", "ATTIRE": "Spotted"},
                 17: {"BODY": "Hollow", "HEAD": "Helix", "HAIR": "Cubic", "ATTIRE": "Glass-like"},
                 18: {"BODY": "Delicate", "HEAD": "Triangular", "HAIR": "Polychromic", "ATTIRE": "Concealing"},
                 19: {"BODY": "Isometric", "HEAD": "Quadrilateral", "HAIR": "Drifting", "ATTIRE": "Barbaric"},
                 20: {"BODY": "Imposing", "HEAD": "Fragmentary", "HAIR": "Fragmentary", "ATTIRE": "Outrageous"},
             }},
            {"title": "identity",
             "columns": ["NAME", "MANNER", "YOUR STRANGE GEOMETRY", "HOW YOU BECAME FLAT"],
             # HOW YOU BECAME FLAT is BANDED on the page (merged cells):
             # 1-5 / 6-7 / 8-9 / 10-11 / 12-13 / 14-15 / 16-17 / 18-20,
             # per VERIFICATION_NOTES.md. Stored flat.
             "rows": {
                 1: {"NAME": "Clotho", "MANNER": "Anxious", "YOUR STRANGE GEOMETRY": "Cast Two Shadows", "HOW YOU BECAME FLAT": "Parents were Planeyfolk"},
                 2: {"NAME": "Atropos", "MANNER": "Arrogant", "YOUR STRANGE GEOMETRY": "Never Cast Shadows", "HOW YOU BECAME FLAT": "Parents were Planeyfolk"},
                 3: {"NAME": "Osteria", "MANNER": "Assertive", "YOUR STRANGE GEOMETRY": "Move Like Stop-Motion Animation", "HOW YOU BECAME FLAT": "Parents were Planeyfolk"},
                 4: {"NAME": "Vanise", "MANNER": "Charismatic", "YOUR STRANGE GEOMETRY": "Your Face Appears Concave", "HOW YOU BECAME FLAT": "Parents were Planeyfolk"},
                 5: {"NAME": "Whervil", "MANNER": "Conceited", "YOUR STRANGE GEOMETRY": "Your Face Appears Convex", "HOW YOU BECAME FLAT": "Parents were Planeyfolk"},
                 6: {"NAME": "Laomer", "MANNER": "Decadent", "YOUR STRANGE GEOMETRY": "You Always Appear In Profile", "HOW YOU BECAME FLAT": "Exposed to hypergeometry in utero"},
                 7: {"NAME": "Foxglory", "MANNER": "Eloquent", "YOUR STRANGE GEOMETRY": "You Always Face Away From Observers", "HOW YOU BECAME FLAT": "Exposed to hypergeometry in utero"},
                 8: {"NAME": "Thelik", "MANNER": "Extravagant", "YOUR STRANGE GEOMETRY": "One Limb Is Enormously Long", "HOW YOU BECAME FLAT": "Cursed by Quantum Daemon"},
                 9: {"NAME": "Umbrie", "MANNER": "Hedonistic", "YOUR STRANGE GEOMETRY": "Viewed From Behind You Have No Skin", "HOW YOU BECAME FLAT": "Cursed by Quantum Daemon"},
                 10: {"NAME": "Salter", "MANNER": "Impulsive", "YOUR STRANGE GEOMETRY": "Interiors Are Visible, But Cannot be Touched", "HOW YOU BECAME FLAT": "Malfunctioning hypergeometric gateway"},
                 11: {"NAME": "Atlassia", "MANNER": "Irritable", "YOUR STRANGE GEOMETRY": "Hands Fractal; Tiny Hands on Ends of Fingers", "HOW YOU BECAME FLAT": "Malfunctioning hypergeometric gateway"},
                 12: {"NAME": "Eukelaris", "MANNER": "Meticulous", "YOUR STRANGE GEOMETRY": "You Bleed Gory Cubes", "HOW YOU BECAME FLAT": "Accidentally ate hypergeometric food"},
                 13: {"NAME": "Galas", "MANNER": "Persistent", "YOUR STRANGE GEOMETRY": "Your Body is Clearly Hollow", "HOW YOU BECAME FLAT": "Accidentally ate hypergeometric food"},
                 14: {"NAME": "Tarvi", "MANNER": "Quiet", "YOUR STRANGE GEOMETRY": "Eyes Are Holes of Infinite Depth", "HOW YOU BECAME FLAT": "Planeyperson inducted you into their dimension"},
                 15: {"NAME": "Untermance", "MANNER": "Religious", "YOUR STRANGE GEOMETRY": "Voice Sounds As If You Are Far Away", "HOW YOU BECAME FLAT": "Planeyperson inducted you into their dimension"},
                 16: {"NAME": "Rassias", "MANNER": "Pugnacious", "YOUR STRANGE GEOMETRY": "You Have No Back, Just Two Identical Fronts", "HOW YOU BECAME FLAT": "Meditated before a 4D tesseract"},
                 17: {"NAME": "Menomeo", "MANNER": "Scholarly", "YOUR STRANGE GEOMETRY": "Head Looks Ten Times Larger Than Body", "HOW YOU BECAME FLAT": "Meditated before a 4D tesseract"},
                 18: {"NAME": "Ithari", "MANNER": "Stern", "YOUR STRANGE GEOMETRY": "Never Seem to Touch Anything", "HOW YOU BECAME FLAT": "You were a hypergeometrician, there was an accident"},
                 19: {"NAME": "Canetonus", "MANNER": "Unruly", "YOUR STRANGE GEOMETRY": "Multiple Identical Faces", "HOW YOU BECAME FLAT": "You were a hypergeometrician, there was an accident"},
                 20: {"NAME": "Trout", "MANNER": "Volatile", "YOUR STRANGE GEOMETRY": "You Never Match the Ambient Light", "HOW YOU BECAME FLAT": "You were a hypergeometrician, there was an accident"},
             }},
        ],
    },
    "lithling": {
        "name": "Lithling",
        "kind": "Mineral",
        "special_rules": [
            {"name": "Crystalline Flesh",
             "text": ("You are made from living crystal. Your base AV is 10 "
                      "+ your Level (maximum 20). You do not need to eat or "
                      "drink. You do not take damage from fire, cold, "
                      "poison, radiation, electricity, fungal spores, or "
                      "suffocation. You suffer double damage from "
                      "bludgeoning attacks.")},
            {"name": "Inevitable",
             "text": ("During character generation, roll 10d8. This number "
                      "is your starting and maximum HP. You cannot heal lost "
                      "HP through any means, and do not add to your maximum "
                      "HP when you gain a level. When your HP tally reaches "
                      "zero you crumble into iridescent dust, leaving behind "
                      "a pebble-sized lithling seed.")},
        ],
        # Inevitable replaces the normal starting-HP roll at creation.
        "creation_hooks": {"hp_override_dice": "10d8"},
        "spark_tables": [
            {"title": "appearance",
             "columns": ["SIZE", "BODY", "HEAD CARVING", "HUE"],
             # SIZE is BANDED: 1-5 Child-like, 6-10 Small, 11-14 Moderate,
             # 15-17 Large, 18-20 Imposing (VERIFICATION_NOTES.md). Flat.
             "rows": {
                 1: {"SIZE": "Child-like", "BODY": "Dainty", "HEAD CARVING": "Sphere", "HUE": "Rose"},
                 2: {"SIZE": "Child-like", "BODY": "Tiny", "HEAD CARVING": "Owl", "HUE": "Onyx"},
                 3: {"SIZE": "Child-like", "BODY": "Boxy", "HEAD CARVING": "Serpent", "HUE": "Azure"},
                 4: {"SIZE": "Child-like", "BODY": "Voluptuous", "HEAD CARVING": "Oxen", "HUE": "Silver"},
                 5: {"SIZE": "Child-like", "BODY": "Squat", "HEAD CARVING": "Horse", "HUE": "Indigo"},
                 6: {"SIZE": "Small", "BODY": "Lithe", "HEAD CARVING": "Warrior", "HUE": "Gold"},
                 7: {"SIZE": "Small", "BODY": "Angular", "HEAD CARVING": "Maiden", "HUE": "Violet"},
                 8: {"SIZE": "Small", "BODY": "Craggy", "HEAD CARVING": "Locust", "HUE": "Ruby"},
                 9: {"SIZE": "Small", "BODY": "Elegant", "HEAD CARVING": "Jackal", "HUE": "Orange"},
                 10: {"SIZE": "Small", "BODY": "Bulbous", "HEAD CARVING": "Moon", "HUE": "Topaz"},
                 11: {"SIZE": "Moderate", "BODY": "Sharp", "HEAD CARVING": "Sun", "HUE": "Jade"},
                 12: {"SIZE": "Moderate", "BODY": "Rotund", "HEAD CARVING": "Pyramid", "HUE": "Brass"},
                 13: {"SIZE": "Moderate", "BODY": "Weathered", "HEAD CARVING": "Cat", "HUE": "Copper"},
                 14: {"SIZE": "Moderate", "BODY": "Monumental", "HEAD CARVING": "Trout", "HUE": "Rust"},
                 15: {"SIZE": "Large", "BODY": "Derelict", "HEAD CARVING": "Scholar", "HUE": "Moss"},
                 16: {"SIZE": "Large", "BODY": "Blocky", "HEAD CARVING": "Fool", "HUE": "Ochre"},
                 17: {"SIZE": "Large", "BODY": "Flaking", "HEAD CARVING": "Crone", "HUE": "Steel"},
                 18: {"SIZE": "Imposing", "BODY": "Smooth", "HEAD CARVING": "Mantis", "HUE": "Sand"},
                 19: {"SIZE": "Imposing", "BODY": "Pitted", "HEAD CARVING": "Ape", "HUE": "Citrine"},
                 20: {"SIZE": "Imposing", "BODY": "Fragmented", "HEAD CARVING": "Goat", "HUE": "Emerald"},
             }},
            {"title": "identity",
             "columns": ["NAME", "MANNER", "FIELD OF STUDY", "QUIRK"],
             "rows": {
                 1: {"NAME": "Aikin", "MANNER": "Logical", "FIELD OF STUDY": "Shellfish", "QUIRK": "Engraved with Poem"},
                 2: {"NAME": "Antimony", "MANNER": "Obsessive", "FIELD OF STUDY": "Ants", "QUIRK": "Engraved with Curse"},
                 3: {"NAME": "Bentor", "MANNER": "Naive", "FIELD OF STUDY": "Spirals", "QUIRK": "Engraved with Map"},
                 4: {"NAME": "Brokenhill", "MANNER": "Abrasive", "FIELD OF STUDY": "Cacti", "QUIRK": "Engraved with Equation"},
                 5: {"NAME": "Cabalzar", "MANNER": "Forgetful", "FIELD OF STUDY": "Birdsong", "QUIRK": "Plants Grow From Head"},
                 6: {"NAME": "Cairngorm", "MANNER": "Aloof", "FIELD OF STUDY": "Lizard Eggs", "QUIRK": "Deep Crack in Face"},
                 7: {"NAME": "Chalcedony", "MANNER": "Mellow", "FIELD OF STUDY": "Fingernails", "QUIRK": "Covered in Moss"},
                 8: {"NAME": "Diaspor", "MANNER": "Sentimental", "FIELD OF STUDY": "Shoes", "QUIRK": "Covered in Dead Vines"},
                 9: {"NAME": "Ephesi", "MANNER": "Amoral", "FIELD OF STUDY": "Wasps", "QUIRK": "Hollow Chest"},
                 10: {"NAME": "Heliotrope", "MANNER": "Impulsive", "FIELD OF STUDY": "Land Snails", "QUIRK": "Hollow Head"},
                 11: {"NAME": "Idrial", "MANNER": "Negative", "FIELD OF STUDY": "Tarantulas", "QUIRK": "Eyes Glow in Dark"},
                 12: {"NAME": "Indium", "MANNER": "Rigid", "FIELD OF STUDY": "Jackals", "QUIRK": "Hand Missing"},
                 13: {"NAME": "Jaros", "MANNER": "Patient", "FIELD OF STUDY": "Pottery", "QUIRK": "Face Eroded Away"},
                 14: {"NAME": "Khatyr", "MANNER": "Decisive", "FIELD OF STUDY": "Dance", "QUIRK": "Leaking Dust"},
                 15: {"NAME": "Meerschaum", "MANNER": "Gracious", "FIELD OF STUDY": "Lunar Cycles", "QUIRK": "You Are Translucent"},
                 16: {"NAME": "Okenit", "MANNER": "Assertive", "FIELD OF STUDY": "The Sun", "QUIRK": "Chest Filled With Fluid"},
                 17: {"NAME": "Qusong", "MANNER": "Unhurried", "FIELD OF STUDY": "Tides", "QUIRK": "Hole Blasted in Flesh"},
                 18: {"NAME": "Schori", "MANNER": "Vengeful", "FIELD OF STUDY": "Wind", "QUIRK": "Second Face on Torso"},
                 19: {"NAME": "Ulrich", "MANNER": "Graceless", "FIELD OF STUDY": "Rain", "QUIRK": "Mirrored Flesh"},
                 20: {"NAME": "Ziest", "MANNER": "Stern", "FIELD OF STUDY": "Silence", "QUIRK": "Face Rotates"},
             }},
        ],
    },
}


def get_ancestry(key):
    return ANCESTRIES.get((key or "").lower().strip())


def ability_roll(rng):
    """One ability: 3d6, bonus = LOWEST die (CH p.5). Returns (bonus, [d1,d2,d3])."""
    dice = [rng(1, 6) for _ in range(3)]
    return min(dice), dice


def roll_ancestry(rng):
    return ANCESTRY_D10[rng(1, 10)]


def roll_sparks(key, rng):
    """Roll every spark table for an ancestry -> {table_title: {column: value}}.
    Normal tables: one d20 per table, read the whole row.
    Band tables (band_table=True): column d20 picks the band, row d20 the entry."""
    a = get_ancestry(key)
    out = {}
    for t in a["spark_tables"]:
        if t.get("band_table"):
            col, row = rng(1, 20), rng(1, 20)
            for (lo, hi), values in t["bands"].items():
                if lo <= col <= hi:
                    out[t["title"]] = {"value": values[row - 1],
                                       "rolls": (col, row)}
                    break
        else:
            r = rng(1, 20)
            out[t["title"]] = dict(t["rows"][r], _roll=r)
    return out


# Explorer's gear (CH "EQUIPMENT" chapter, GEAR page): ONE d20 table with
# two columns, GEAR A and GEAR B. PC creation rolls the explorer's gear
# table twice = one d20 roll on each column. Parenthetical suffixes are
# structured in the ENGINE'S item schema (item_slots.py): "(x5)" ->
# integer uses (depletion counter), "(Ud6)" -> usage_die (usage-die
# notation), "(p.xx)" -> ref (a page pointer in the preview PDF; the item
# itself is rolled or detailed elsewhere). Digits verified against the
# PDF text layer.
GEAR_A = {
    1: {"name": "Flashbang", "uses": 5},
    2: {"name": "Magnetic Boots"},
    3: {"name": "Grappling Hook & Rope"},
    4: {"name": "Flare", "uses": 5},
    5: {"name": "Smoke Bomb", "uses": 5},
    6: {"name": "Flask of Oil"},
    7: {"name": "Portable Stove"},
    8: {"name": "Caltrops", "uses": 5},
    9: {"name": "Vial of Acid", "uses": 3},
    10: {"name": "Animal Trap", "uses": 3},
    11: {"name": "Handheld Drill"},
    12: {"name": "Chain & Manacles"},
    13: {"name": "Hand Mirror"},
    14: {"name": "Motion Sensor"},
    15: {"name": "Crowbar"},
    16: {"name": "EMP Grenade", "uses": 3},
    17: {"name": "Skin of Wine"},
    18: {"name": "Tube of Glue", "usage_die": "Ud8"},
    19: {"name": "Ball Bearings", "usage_die": "Ud20"},
    20: {"name": "Musical Instrument", "ref": "p.xx"},
}

GEAR_B = {
    1: {"name": "Sleeping Gas Bomb", "uses": 5},
    2: {"name": "Oxygen Mask", "usage_die": "Ud6"},
    3: {"name": "Cast Iron Skillet"},
    4: {"name": "Black Clay", "usage_die": "Ud8"},
    5: {"name": "Loaded Dice"},
    6: {"name": "Raucous Whistle"},
    7: {"name": "Luminous Paint", "usage_die": "Ud8"},
    8: {"name": "Drug", "ref": "p.xx"},
    9: {"name": "Vial of Poison", "ref": "p.xx"},
    10: {"name": "Autoglot Translator Unit"},
    11: {"name": "Lock Picks"},
    12: {"name": "Mortar & Pestle"},
    13: {"name": "Strong Liquor"},
    14: {"name": "Hourglass"},
    15: {"name": "Hammer & Chisel"},
    16: {"name": "Anti-toxin", "uses": 3},
    17: {"name": "Welding Torch", "usage_die": "Ud8"},
    18: {"name": "Infravision Goggles", "usage_die": "Ud8"},
    19: {"name": "Fungicide Bomb", "uses": 5},
    20: {"name": "Canary in Cage"},
}


def roll_gear(rng):
    """Roll the explorer's gear table twice: one d20 on each column."""
    r_a, r_b = rng(1, 20), rng(1, 20)
    return {"gear_a": dict(GEAR_A[r_a]), "gear_b": dict(GEAR_B[r_b]),
            "rolls": (r_a, r_b)}
