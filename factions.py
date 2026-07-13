"""Faction reputation data + Minor-faction generator (Crimson Hound pp.83-84, 90-91).

Pure data + functions, no I/O. The server owns persistence (factions.json) and the
faction tool. Standing scale is the book's 7-band RAW (Joe ruling 2026-06-13), NOT
the campaign's older 9-band homebrew.
"""

import random

# REP is held in [-10, 10] by the ledger; bands treat the endpoints as open
# (Hero at >=10, Nemesis at <=-10) so the book's "10+" / "-10 or lower" read true.
STANDING_BANDS = [
    {"label": "Hero", "min": 10, "max": 9999, "reaction": "favorable",
     "effect": "You are a hero to the faction and its members. They will die to assist you if need be."},
    {"label": "Friend", "min": 4, "max": 9, "reaction": "favorable",
     "effect": "You are a friend to the faction. Members will help you in any way they can. They will never attack you without cause."},
    {"label": "Liked", "min": 1, "max": 3, "reaction": "ADV",
     "effect": "The faction has a warm opinion of you. When you encounter a member, the reaction roll has ADV."},
    {"label": "Neutral", "min": 0, "max": 0, "reaction": "standard",
     "effect": "The faction has no opinion of you. Encounters use the standard reaction table."},
    {"label": "Disliked", "min": -3, "max": -1, "reaction": "DIS",
     "effect": "The faction has a cold opinion of you. When you encounter a member, the reaction roll has DIS."},
    {"label": "Enemy", "min": -9, "max": -4, "reaction": "hostile",
     "effect": "Faction members are sworn to harm you. They will always attack you, hinder you, lie to you, or otherwise cause you mischief."},
    {"label": "Nemesis", "min": -9999, "max": -10, "reaction": "hostile",
     "effect": "You are considered a deadly threat to the faction and will be hunted down by the most committed members. If the faction is not generally in the business of killing, they hire a third party who is."},
]


def standing_for(rep):
    """Return the band record for an integer REP value (handles out-of-clamp too)."""
    r = int(rep)
    for band in STANDING_BANDS:
        if band["min"] <= r <= band["max"]:
            return band
    return STANDING_BANDS[3]  # defensive: Neutral (unreachable given the ranges)


# d20 tables, index 0 == roll 1 (Crimson Hound p.91). Spellings are book-verbatim.
MINOR_FACTION_TABLES = {
    "reputation": [
        "Venerable", "Saintly", "Untrustworthy", "Morbid", "Corrupt", "Thuggish",
        "Refined", "Charitable", "Pious", "Reliable", "Upstart", "Decadent",
        "Secretive", "Collapsing", "Snobbish", "Bloodthirsty", "Quarrelsome",
        "Sinister", "Greedy", "Paranoid",
    ],
    "type": [
        "Alchemical College", "Water Prospectors' Guild", "Mystic College",
        "Death Cult", "Mercenary Regiment", "Guild of Philosophers",
        "Merchant Cartel", "Trade Union", "Autarch Cult", "Monastic Order",
        "Bounty Hunters' Guild", "Circus", "Sky Pirate Crew", "Fungusmongers' Guild",
        "Scrap Scavengers' Guild", "Science-Witch Coven", "Exorcist's Circle",
        "Quantum Daemon Cult", "Orchard Keeper's Association", "Fool's Guild",
    ],
    "goal": [
        "Revenge on Rival Faction", "Increase Membership", "Decrease Membership",
        "Eliminate Rival Faction", "Revive Buried Power", "Increase Material Wealth",
        "Increase Political Influence", "Discredit a Rival Faction",
        "Retrieve Lost Treasure", "Uncover a Secret", "Eradicate Local Monster",
        "Protect a Secret", "Aquire Exotica", "Protect their Livelihood",
        "Unmask a Traitor", "Cultivate Natural Resource", "Destroy Natural Resource",
        "Restore Past Glory", "Relocate Faction Base", "Serve Cosmic Being",
    ],
    "leader": [
        "Pretends to be Stupid", "Pretends to be Intelligent", "Incompetent, Unfriendly",
        "Ruthless and Jovial", "Obssesses Over Trivia", "Consumed By Past Regrets",
        "Vain and Sickly", "Consumes a Drug to Excess", "Relies on Strange Advisor",
        "Communes with the Stars", "Morbid and Paranoid", "Brash and Hasty",
        "Always Slow to React", "Thought Overly Merciful", "Boring but Competent",
        "Violent Temper", "Scholarly, Lazy", "Prophecy-Addled Idiot",
        "Walking Disaster", "Generally Well Liked",
    ],
    "assets": [
        "Vast Material Wealth", "Political Connections", "Deal with Local Faa",
        "Spy Network", "Hidden Stronghold", "Mobile Stronghold", "Own Item of Exotica",
        "Secret Source of Fresh Water", "Popular with Locals", "Protected by Major Faction",
        "Control Trade Secrets", "Own Valuable Map", "Own Religious Relic",
        "Control Rare Resource", "Control Over Local Monster", "Deal With Local Cacklemaw",
        "Private Oracle", "Local Monopoly", "Owed Life Debt by Local Ruler",
        "Pact with Quantum Daemon",
    ],
    "rival": [
        "Water Prospectors' Guild", "Trade Union", "Sky Pirate Crew",
        "Scrap Scavengers' Guild", "Science-Witch Coven", "Quantum Daemon Cult",
        "Orchard Keeper's Association", "Mystic College", "Monastic Order",
        "Merchant Cartel", "Mercenary Regiment", "Guild of Philosophers",
        "Fungusmongers' Guild", "Fool's Guild", "Exorcist's Circle", "Death Cult",
        "Circus", "Bounty Hunters' Guild", "Autarch Cult", "Alchemical College",
    ],
}


def generate_minor_faction(rolls=None, rng=random.randint):
    """Roll/forced-roll a Minor faction (CH p.91). Returns data only — committing it to
    the ledger is a separate `faction add` call.

    rolls: optional dict of forced d20 face values
        {reputation,type,goal,leader,rival: int 1-20, assets: [int, int]}.
        Any missing key is rolled via rng(1, 20).
    """
    rolls = rolls or {}

    def pick(key):
        face = rolls.get(key)
        if not isinstance(face, int):
            face = rng(1, 20)
        face = max(1, min(20, face))
        return MINOR_FACTION_TABLES[key][face - 1]

    asset_faces = rolls.get("assets")
    if not (isinstance(asset_faces, list) and len(asset_faces) == 2
            and all(isinstance(f, int) for f in asset_faces)):
        asset_faces = [rng(1, 20), rng(1, 20)]
    assets = [MINOR_FACTION_TABLES["assets"][max(1, min(20, f)) - 1] for f in asset_faces]

    return {
        "reputation_adjective": pick("reputation"),
        "type": pick("type"),
        "goal": pick("goal"),
        "leader": pick("leader"),
        "assets": assets,
        "rival": pick("rival"),
    }
