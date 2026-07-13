"""Content generators — decomposition slice 1 (2026-06-17).

Extracted VERBATIM from server.py: the d100/table-driven generators behind the
`generate` and `lookup` tools (exotica, weapons, armour, NPCs, factions, gifts,
poisons, codices, drugs, elixirs, crucibles). The tool DISPATCHERS stay in
server.py and import-and-alias these back; this module never imports server.

Four data tables are shared with the live poison/elixir/combat systems and stay
in server.py — they are injected here via register_generators(srv) at startup,
along with the _stamp_slots_uses helper. Bound to None at import; never reassigned.
"""
import json
import random
from pathlib import Path
from typing import Optional

from pydantic import Field

import weapon_schema as ws
import gifts as _gifts
import factions as _factions
import push_format as _pf
from content_forge import ContentForge
from engine_core import CAMPAIGN_DIR, RULES_DATA_DIR, read_file, write_file, read_rules_data, dice
from npc_tables import (
    ANCESTRY_TABLE, MANNER_TABLE, VOICE_TABLE, DRIVE_TABLE,
    SECRET_TABLE, BOND_TABLE, FAITH_TABLE, FACTION_REPUTATION_TABLE,
    NAMES_A, NAMES_B, NAMES_C, NAMES_D, CAREERS_TABLE,
)

# Injected from server.py at registration (shared with poison/elixir/combat — by
# reference, never reassigned). Bound to None until register_generators() runs.
VAARNISH_POISONS = None
VAARNISH_ELIXIRS = None
MELEE_WEAPONS = None
RANGED_WEAPONS = None
_stamp_slots_uses = None


EXOTICA_TABLE = {
    1: {"name": "Active Camouflage Ring", "description": "The user vanishes from visible spectrums of light, adding +10 to their AV. Creatures which do not use conventional means to see are unaffected.", "slots_uses": "1/Ud6"},
    2: {"name": "Amaranthine Sugar", "description": "A fabulously valuable substance, extracted through patient husbandry from the bodies of adult sandworms. Resembles reddish-purple sugar. If consumed, the sugar grants a random Mystic Gift.", "slots_uses": "1/x1 use"},
    3: {"name": "Ansible", "description": "Crystalline orb. Allows faster-than-light communication with a linked Ansible.", "slots_uses": "1/Unlimited"},
    4: {"name": "Bluescreen Dagger", "description": "Synthetic creatures must EGO Save vs d20 EGO damage when struck. Does not damage other creature types.", "slots_uses": "1/Ud8"},
    5: {"name": "C-Foam Puddings", "description": "Resemble plastic wrapped, milk-coloured puddings. When thrown expand into blancmanges of highly adhesive, quick-setting foam. Entrap human-sized creatures in a matter of seconds (DEX save vs paralysis). The foam loosens over a period of eight hours. Saltwater shortens this disintegration.", "slots_uses": "1/x6 uses"},
    6: {"name": "Desiccation Spike", "description": "Vile biotech weapon. Deals d6 CON damage to Biological creatures and produces 1 ration of water per successful hit.", "slots_uses": "1/Ud10"},
    7: {"name": "Empathy Bomb", "description": "Target Biological creatures must EGO Save or be overcome with compassion for others. This effect lasts d4 hours.", "slots_uses": "1/x1 use"},
    8: {"name": "Exotic Melee Weapon", "description": "Generate an Exotic Melee Weapon using the tables on p.200", "slots_uses": "See p.200"},
    9: {"name": "Exotic Ranged Weapon", "description": "Generate an Exotic Ranged Weapon using the tables on p.201", "slots_uses": "See p.201"},
    10: {"name": "Fortuitous Polyhedron", "description": "20-sided polyhedral quantum anomaly. Allows user to enter a reality where they passed rather than failed a Save. Vanishes after use.", "slots_uses": "1/x1 use"},
    11: {"name": "Fuligin Garb", "description": "Fuligin is the colour that is darker than black. Fuligin clothing completely conceals the wearer when in shadows, with no Save required. Creatures which do not use conventional means to see are unaffected.", "slots_uses": "1/Unlimited"},
    12: {"name": "Hesitant Urn", "description": "A hypergeometric pot, baked from pale green clay and engraved with the seals of master hypergeometers. The urn has an opening in the top and a small hole bored at the bottom. Any liquid poured into the urn vanishes from rational space-time, and will trickle out of the hole at the bottom after a delay of exactly seven minutes.", "slots_uses": "1/Unlimited"},
    13: {"name": "Lithifying Ray", "description": "Experimental weapon shaped like a snake-haired maiden. The ray changes organic material into stone. For each round that the ray is held on a biological target, they permanently lose d6 DEX and gain +2 Armour. At 0 DEX they become a remarkably lifelike statue.", "slots_uses": "2/Ud6"},
    14: {"name": "Mirror Armour", "description": "Dazzling suit of lightweight mirror plate. Grants AV16 and immunity from Beam attacks. Cannot hide in shadows.", "slots_uses": "3 slots"},
    15: {"name": "Oneiric Bridge", "description": "A peculiar conflux of wires. Allows the user to enter the dreams of a sleeping creature and influence their thoughts.", "slots_uses": "1/Ud8"},
    16: {"name": "Pacifying Glove", "description": "Biological creatures touched with the glove must EGO Save or fall asleep for d6 hours.", "slots_uses": "1/Ud6"},
    17: {"name": "Portable Hole", "description": "Creates a six-inch hypergeometric borehole straight through any solid object. Causes no harm to the structure or creature. When you're done using it, peel the Portable Hole off the surface and put it back in your pocket.", "slots_uses": "1/Ud4"},
    18: {"name": "Serenity Sphere", "description": "A sphere of polished neuroactive crystal, roughly the size and weight of a grapefruit. Resting the sphere in both hands produces the feeling of being immersed in a comforting warm bath, allowing the bearer to endure minor discomforts with ease.", "slots_uses": "1/Unlimited"},
    19: {"name": "Singularity Bomb", "description": "A glass sphere that contains a miniature gravity singularity. When released the gravity singularity draws in all objects in the room. DEX Save vs instant death inside the singularity.", "slots_uses": "1/x1 use"},
    20: {"name": "Sovereign Glue", "description": "Unbreakably stick two objects together.", "slots_uses": "1/Ud6"},
    21: {"name": "Stasis Bomb", "description": "Any creatures caught in the blast are marooned outside space-time for 2d6 combat rounds. They cannot take any action, nor be harmed nor touched.", "slots_uses": "1/x1 use"},
    22: {"name": "Ulfire Paint", "description": "Ulfire is the ninth visible colour, and its light is visible through solid objects. Anything marked with ulfire paint can be seen through walls.", "slots_uses": "1/Ud6"},
    23: {"name": "Ultra-kinetic Gel", "description": "Green gel that temporarily amplifies kinetic energy on any surface it coats. Increase speed of mechanisms, create temporary jump-pads, create the world's most dangerous frisbee, etc.", "slots_uses": "1/Ud6"},
    24: {"name": "Visualiser Helm", "description": "Golden bubble-helmet. When worn, the wearer's thoughts are projected as images on the surface of the bubble, whether they will it or not.", "slots_uses": "1/Unlimited"},
    25: {"name": "Wand of Annihilation", "description": "A rod of golden plasteel, a hand's span in length. Can be used, when one has line of sight to the sky, to call down an orbital laser strike from an ancient war satellite. This attack deals d100 beam damage to any target indicated with the golden wand.", "slots_uses": "1/Ud4"},
    26: {"name": "Adamant Linen", "description": "A robe of flowing linen that protects the wearer like it were hewn from steel. Grants AV18 to the wearer.", "slots_uses": "2/Unlimited"},
    27: {"name": "Apocalypse Glass", "description": "Dark looking-glass which shows not your reflection, but an extra-solar culture consumed by unimaginable horror. Of interest to some collectors.", "slots_uses": "1/Unlimited"},
    28: {"name": "Ardar-Eld's Grail", "description": "Liquids poured into this golden goblet become drinking water.", "slots_uses": "1/Unlimited"},
    29: {"name": "Belligerent Paste", "description": "If applied to a corpse, turns that corpse into an Exotic Weapon. The nature of the weapon depends upon the corpse used (the Referee should use p.200 as a starting point).", "slots_uses": "1/x1 use"},
    30: {"name": "Bounty Beacon", "description": "Use under open sky to call down a supply package from an orbiting military satellite (generate as Large Supply Cache, p.194).", "slots_uses": "1/x1 use"},
    31: {"name": "Cat Ring", "description": "Antigravity device. Arrests wearer's fall just above the ground, preventing fall damage.", "slots_uses": "1/x9 uses"},
    32: {"name": "Compass of Origin", "description": "A device that unerringly points towards the holder's location of birth. Urth's magnetic field is no longer what it was, so this is more useful than it might seem.", "slots_uses": "1/Unlimited"},
    33: {"name": "Cybernetic Cocoon", "description": "Human-sized black cocoon. Installs a random Advanced Cybernetic Implant.", "slots_uses": "6/x1 use"},
    34: {"name": "Dopplegun", "description": "Biotech pistol that births a rapidly-aging, dangerously insane clone of any Biological-type creature its bullets hit. The clone has their stats and abilities, and survives for d6 rounds before dying of cancer.", "slots_uses": "1/Ud8"},
    35: {"name": "Fascinator Helm", "description": "+1 AV. When activated, all Biological creatures in visual range must EGO save or be transfixed by the flickering patterns on this helmet. They cannot move until damaged or until the helm is out of view.", "slots_uses": "1/Ud8"},
    36: {"name": "Friend Fabricator", "description": "Matter fabricating cocoon. When activated, creates a randomly generated creature from the local encounter table. The creature is neurally altered so as to love the cocoon's user (treat them as a Pet, see p.48).", "slots_uses": "3/x1 use"},
    37: {"name": "Hard Light Projector", "description": "Projects a flat wide bridge of weightless hard light, with effective range of ten feet. Could be walked across.", "slots_uses": "2/Ud8"},
    38: {"name": "Hover Boots", "description": "Antigravity boots. Allow brief sojourns into thin air.", "slots_uses": "1/Ud8"},
    39: {"name": "Hushboots", "description": "Sable, supple footwear that utterly silence footsteps. ADV when sneaking or attacking blind creatures.", "slots_uses": "1/Unlimited"},
    40: {"name": "Instant Table", "description": "An elegant dining table, compressed using hypergeometry to be the size of a matchbox. Unfurls when thrown to the ground. Cannot be folded up again.", "slots_uses": "1/x1 use"},
    41: {"name": "Mirror Shield", "description": "+1 AV. DEX Save to reflect beam attacks back at their source.", "slots_uses": "1/Unlimited"},
    42: {"name": "Mord-Red's Grail", "description": "Liquids poured into this silver goblet become deadly poison (d12 TOX).", "slots_uses": "1/Unlimited"},
    43: {"name": "Moonbeast Carapace", "description": "The flayed carapace of a vile Moonbeast. The wearer has AV16, and immunity to radiation. Once worn the carapace cannot be removed.", "slots_uses": "3/Unlimited"},
    44: {"name": "Phase Cape", "description": "Hypergeometric cloth; allows wearer to slip out of lucid reality for d4 rounds. You cannot be touched by anyone, but neither can you touch them. You are still visible.", "slots_uses": "1/Ud6"},
    45: {"name": "Presence Drone", "description": "Small floating sphere that announces one's presence in a loud, pompous voice. DIS on encounter rolls. Impossible to hide. Once activated must be destroyed or traded away to stop it following you.", "slots_uses": "None (floats nearby)"},
    46: {"name": "Spirit Prison (Empty)", "description": "Manifold crystal prison designed to trap paradoxical creatures. This example is empty. When thrown at Hypergeometric or Outsider-type creatures, they must EGO Save or be trapped forever inside the prison, to be released at the bearer's pleasure.", "slots_uses": "1/Unlimited"},
    47: {"name": "Spirit Prison (Occupied)", "description": "Manifold crystal prison designed to trap paradoxical creatures. This example is occupied: roll on the Paradoxical Outsiders table to determine which entity is imprisoned.", "slots_uses": "1/Unlimited"},
    48: {"name": "Sprayflesh", "description": "Canister that sprays healing pseudoflesh over wounds. Remove 1 Wound from Biological target per use.", "slots_uses": "1/Ud6"},
    49: {"name": "Starskin", "description": "A biomechanoid space-suit, worn by voidfarers of antiquity. Grants AV16, and immunity to suffocation. Move freely in antigravity.", "slots_uses": "3/Unlimited"},
    50: {"name": "Ulfire Lantern", "description": "Shines ulfire light. Can see through solid objects and be seen. Blocked by lead.", "slots_uses": "1/Ud8"},
    51: {"name": "Universal Ration", "description": "Thick white nutrient-cake containing everything a human body needs. Full heal for Biological creatures.", "slots_uses": "1/Feeds four PCs"},
    52: {"name": "Ammunition Fabricator", "description": "Use to refill the ammunition for any ranged weapon in your possession.", "slots_uses": "1/x1 use"},
    53: {"name": "Ardent Maggots", "description": "A gourd of strange synthetic grubs that can strip a corpse to the bone in seconds. Will not eat live flesh.", "slots_uses": "1/Ud4"},
    54: {"name": "Autarch's Fork", "description": "Obsidian dining fork that glows green when it is stuck into poison.", "slots_uses": "1/Unlimited"},
    55: {"name": "Autarch's Nectar", "description": "Honeyed golden tonic containing gene-sculpting nanomachines. When drunk by a Biological creature, grants a permanent +1 boost to three Ability scores.", "slots_uses": "1/x1 use"},
    56: {"name": "Babel Bomb", "description": "Neuro-active hand grenade. All living creatures caught within the blast will find themselves unable to understand spoken or written language, and their own speech is likewise gibberish. The effect lasts for a day.", "slots_uses": "1/x1 use"},
    57: {"name": "Bedazzling Blade", "description": "Off-handed parrying sword (d6), forged in the Fallen Autarchy. Has an inbuilt trickÃ¢â‚¬â€the blade can briefly glow as brightly as the sun. Opponents DEX Save vs d6 rounds of Blindness.", "slots_uses": "1/Ud8"},
    58: {"name": "Blue Rust", "description": "Alchemical compound that turns any metal into rust within moments. D6 CON damage to Synthetic creatures per round.", "slots_uses": "1/x1 use"},
    59: {"name": "Bottled Thicket", "description": "Glass vial containing weaponised seeds. When the vial is broken, the seeds germinate and begin an astoundingly rapid lifecycle, sprouting into a dense tangle of iridescent vines within seconds. Fills entire room, strangling all living creatures for d8 damage per round. STR Save to break free.", "slots_uses": "1/x1 use"},
    60: {"name": "Ditto Gun", "description": "Revolver that generates weaponised temporal anomalies when its bullets impact a target. These anomalies inflict a wound identical to the most recent injury suffered by the target, with a matching damage value.", "slots_uses": "1/Ud10"},
    61: {"name": "Gecko Gloves", "description": "Finely woven nano-cloth gloves. Allow the wearer's hands to stick to any flat surface with a near-unbreakable grip. Can climb impossible distances.", "slots_uses": "1/Unlimited"},
    62: {"name": "Hedondroid", "description": "Factory-sealed package containing a synthetic party crasher. Crude android powered by alcohol, and can unerringly locate parties, orgies, weddings etc. within a five-day radius. Once activated, joins your party as a Follower.", "slots_uses": "5/x1 use"},
    63: {"name": "Lazarus Cap", "description": "+1 AV. Grim necrotech helm. If applied to the head of a fresh corpse, will re-activate the brain. The effect only lasts while the cap is worn, and does nothing to arrest the decay of the flesh (wearer loses d4 CON per day).", "slots_uses": "1/x1 use"},
    64: {"name": "Magnetic Orb", "description": "Large silver orb which emits powerful magnetic field when active. All nearby metal objects and Synthetic-type creatures are irresistibly drawn towards it.", "slots_uses": "2/Ud8"},
    65: {"name": "Mind Shield", "description": "+1 AV. Golden cage worn around head. Protects from psychic intrusion. Cannot use Mystic Gifts. Exempt from Gleam Tests.", "slots_uses": "1/Unlimited"},
    66: {"name": "Not-Sword", "description": "A sword (d8) engraved with paradoxical LogLang glyphs. Synthetic creatures cannot recognise this weapon as a blade, nor can they recognise the bearer of the sword as a living being.", "slots_uses": "2/Unlimited"},
    67: {"name": "Phase Grenades", "description": "Every physical object caught in the blast becomes briefly de-synched with reality; others can pass through like mist. The effect does not last long and is not harmful.", "slots_uses": "1/x4 uses"},
    68: {"name": "Philosopher's Dirk", "description": "Neuroactive dagger which deals d4 INT damage per stab. At 0 INT the victim adopts your point of view.", "slots_uses": "1/Ud6"},
    69: {"name": "Prison Orb of the Miniature Beast", "description": "A hypergeometric orb the size of a grapefruit, with a scarlet upper hemisphere and a pallid lower hemisphere. Used by the citizens of a long-faded civilisation to imprison a collection of tiny fighting-beasts, and compel them to do battle with other beast-masters. 4-in-6 chance the Orb still contains a Citrine-coated Volt Rat, hungry and trained to kill without hesitation. 2-in-6 chance the Orb holds nothing but the desiccated corpse of a forgotten beast.", "slots_uses": "1/Unlimited"},
    70: {"name": "Psybernetic Helm", "description": "+1 AV. When worn for first time, installs a random Mystic Gift.", "slots_uses": "1/x1 use"},
    71: {"name": "Quantum Umbilical", "description": "Strange device that links the destiny of two creatures. While one lives, the other cannot truly die.", "slots_uses": "2/Ud4"},
    72: {"name": "Tech Wand", "description": "Miraculous silver wand. Use to re-activate or deactivate a piece of arcane technology.", "slots_uses": "1/Ud4"},
    73: {"name": "Tempest Cannon", "description": "Creates localised, incredibly violent thunderstorms wherever its shells explode (d12, blast, electrical). Reload with 3 rations of water.", "slots_uses": "3/Ud4"},
    74: {"name": "The Book of Sand", "description": "Hypergeometric object that resembles a book with an infinite number of pages, each one containing an infinite number of tiny paragraphs written in illegible text. Decoding the book is impossible, although its infinite length could provide fuel for an endlessly burning fire.", "slots_uses": "1/Infinite"},
    75: {"name": "The Crimson Cantos", "description": "Small, unassuming volume of poetry, bound in crimson leather. The book's contents are neuro-active, and always guaranteed to fling the reader into a murderous rage. Readers must EGO save or violently attack the nearest living creature.", "slots_uses": "1/Unlimited"},
    76: {"name": "Watchful Ferret", "description": "A small golden synthetic ferret that sits on your shoulder. Nips you if it detects an unseen danger. Does not need to eat or breathe.", "slots_uses": "1/Unlimited"},
    77: {"name": "Anti-Gravity Field Generator", "description": "A tetrahedron of lusterless black metal. When activated, excludes Urth's gravity within throwing distance of the user. Creatures not adapted to zero gravity environments must DEX Save to move or else float helplessly.", "slots_uses": "3/Ud6"},
    78: {"name": "Biotic Field Generator", "description": "A golden beacon. When planted on the floor, emits a cloud of healing nanomachines for 6 rounds. All Biological creatures in melee range regain +d10 HP per round while in the cloud.", "slots_uses": "1/Ud4"},
    79: {"name": "Black Cloud Bomb", "description": "Releases a cloud of nanomachines that consume all biological material in the area, dealing d6 unblockable damage per round. With each kill, the cloud grows in size and deals an extra d6 of damage. The cloud expands until it cannot find more biological material to consume, at which point it hibernates.", "slots_uses": "1/x1 use"},
    80: {"name": "Cybernetics Pack", "description": "Contains a factory-sealed cybernetic implant (generate from p.96).", "slots_uses": "2/x1"},
    81: {"name": "Demiurge Crayon", "description": "An hypergeometric artefact of unimaginable power, which resembles an unassuming child's crayon. Any item, creature, or other object drawn with this crayon becomes real.", "slots_uses": "1/Ud4"},
    82: {"name": "Disguise Ring", "description": "Holographic disguise. Projects a hologram around the wearer. Can be programmed to show an image of any creatures or entities that are nearby. Perfect visual replica but anyone attempting to touch the hologram shell will realise the deception. Comes pre-loaded with disguise patterned on a creature from the local encounter table.", "slots_uses": "1/Ud8"},
    83: {"name": "Fate Inverter", "description": "Peculiar paradox-device. When activated, all nearby failed Saves become successes, and all successful Saves become failures. Likewise missed attacks hit, and attacks that hit will miss.", "slots_uses": "1/Ud4"},
    84: {"name": "Horror Helm", "description": "+2 AV. Autarch's war-helm. When activated, the helm bellows terrifying neuroactive threats. All Biological foes in earshot must make a Morale Save or flee.", "slots_uses": "1/Ud8"},
    85: {"name": "Huntsman Fly", "description": "Cocoon containing tiny synth-fly. If given a drop of blood or other DNA sample, can unerringly locate the target. Dies once mission is complete.", "slots_uses": "1/x1 use"},
    86: {"name": "Quantum Daemon Horn", "description": "Sound to draw the attention of a Greater Quantum Daemon. They will arrive immediately and are bound to perform one boon for you.", "slots_uses": "1/x1 use"},
    87: {"name": "Lithling Seed", "description": "The corpse (and hence embryo) of a Lithling. If immersed in a bath of the correct chemicals, will slowly crystallize into an adult Lithling. Follow the character generation procedure on p.26.", "slots_uses": "1/x1 use"},
    88: {"name": "Manifold Box", "description": "A hypergeometric box which is much larger on the inside than on the outside. The Manifold Box can hold 10 slots of items weightlessly within itself. Retrieving them during combat takes an action.", "slots_uses": "1/Unlimited"},
    89: {"name": "Pale Fire", "description": "A wooden flask in which is held a hueless flame, kindled from some extradimensional anti-ember. Burns bitterly cold and consumes substances that would not usually burn: metal and water are favoured fuels. It can be extinguished with oil or another flammable liquid.", "slots_uses": "1/x1 use"},
    90: {"name": "Philosopher's Bridge", "description": "A device which creates a pair of round hypergeometric portals on solid walls, one blue and one orange. The portals may be passed through like mundane apertures, with any objects that pass through retaining their momentum. The user may close both portals at will.", "slots_uses": "2/Ud6"},
    91: {"name": "Scatter-Shoal Ring", "description": "When activated, projects 9 hard-light holograms of the wearer which scatter like frightened fish in all directions. The holograms are solid and react when 'hurt', although they cannot speak. Opponents have a 1-in-10 chance of targeting the correct image of the wearer.", "slots_uses": "1/Ud6"},
    92: {"name": "Snakemaker", "description": "A gun that makes and fires synthetic snakes (Lvl 0, AV 11, d4 bite). They do not like or obey the wielder.", "slots_uses": "1/Ud8"},
    93: {"name": "Stormcaller", "description": "Accursed flute that disturbs the kingdoms of the upper air. When played beneath an open sky, a Prismatic Tempest will form overhead.", "slots_uses": "1/Ud6"},
    94: {"name": "TALLHAT Amplifier", "description": "A psionic amplifier system, hidden inside a black conical hat. When worn, +1 to all mental stats. Identifies one as a Witch of the Mooncradle Mountains.", "slots_uses": "1/Unlimited"},
    95: {"name": "Thinking Cap", "description": "+1 AV, +2 INT. If wearer was not previously sentient, it now becomes so.", "slots_uses": "2/Unlimited"},
    96: {"name": "Titancreed Fragment: KILL", "description": "A fragment of the language of the Titan AIs. When read aloud, all Synthetic creatures in hearing range must EGO Save or fly into a killing frenzy.", "slots_uses": "1/Ud4"},
    97: {"name": "Titancreed Fragment: OBEY", "description": "A fragment of the language of the Titan AIs. When read aloud, all Synthetic creatures in hearing range must EGO Save or obey one verbal command from the reader.", "slots_uses": "1/Ud4"},
    98: {"name": "Titancreed Fragment: SLEEP", "description": "A fragment of the language of the Titan AIs. When read aloud, all Synthetic creatures in hearing range must EGO Save or fall into a resting state.", "slots_uses": "1/Ud4"},
    99: {"name": "Vimana Map", "description": "Small chunk of crystal. When activated, projects a holographic map guiding the user to the location of a lost Autarch's Vimana.", "slots_uses": "1/Unlimited"},
    100: {"name": "Wind-up Haruspex", "description": "Clockwork fortune teller. When provided the entrails and stomach of a recently-butchered animal or person, it can discern the likely course of the future using the guts. Can only answer one question at a time. Can only give the answers YES, NO, or PERHAPS.", "slots_uses": "3/Unlimited"},
}

def _roll_exotica(
    specific_roll: Optional[int] = Field(default=None, description="Specify 1-100, or empty to roll d100")
) -> str:
    """Roll d100 on Exotica table. Use for treasure rolls, vault loot, or when party discovers ancient tech."""
    # Determine the roll
    if specific_roll is not None:
        if specific_roll < 1 or specific_roll > 100:
            return f"Ã¢ÂÅ’ Invalid roll: {specific_roll}. Must be 1-100."
        roll = specific_roll
        roll_method = "specified"
    else:
        roll = dice.d100()
        roll_method = "d100"
    
    # Get the exotica entry — copy so we never mutate the shared table constant
    _raw = EXOTICA_TABLE.get(roll)

    if not _raw:
        return f"Ã¢ÂÅ’ Error: No entry for roll {roll}"

    # stamp a per-result copy: _roll_exotica is the concrete mint path (_generate_exotica is the creative-seed roller, no item dict)
    # Stamp a shallow copy with structured slots/usage fields; never mutate the table constant
    exotica = _stamp_slots_uses(dict(_raw))

    # Format the output
    result = f"""{'='*60}
EXOTICA ROLL: {roll} ({roll_method})
{'='*60}

**{exotica['name']}**

{exotica['description']}

**Slots/Uses:** {exotica['slots_uses']}

{'='*60}"""
    
    # Add special notes for entries that reference other tables
    special_notes = []
    
    if roll == 8:
        special_notes.append("Ã°Å¸â€œâ€¹ Use the Exotic Melee Weapon tables (p.200) to generate this weapon")
    elif roll == 9:
        special_notes.append("Ã°Å¸â€œâ€¹ Use the Exotic Ranged Weapon tables (p.201) to generate this weapon")
    elif roll == 33:
        special_notes.append("Ã°Å¸â€œâ€¹ Roll on Advanced Cybernetic Implants table (p.96)")
    elif roll == 47:
        special_notes.append("Ã°Å¸â€œâ€¹ Roll on Paradoxical Outsiders table to determine imprisoned entity")
    elif roll == 69:
        # Roll to see if there's a creature
        creature_roll = dice.d6()
        if creature_roll <= 4:
            special_notes.append(f"Ã°Å¸Ââ‚¬ Roll {creature_roll}/6: Contains a Citrine-coated Volt Rat! (Lvl 1, AV 11, d6 electric bite)")
        else:
            special_notes.append(f"Ã°Å¸â€™â‚¬ Roll {creature_roll}/6: Contains only a desiccated beast corpse")
    elif roll == 70:
        special_notes.append("Ã°Å¸â€œâ€¹ Roll on Mystic Gifts table when worn for the first time")
    elif roll == 80:
        special_notes.append("Ã°Å¸â€œâ€¹ Roll on Cybernetic Implants table (p.96)")
    elif roll == 82:
        special_notes.append("Ã°Å¸â€œâ€¹ Roll on local encounter table to determine pre-loaded disguise")
    elif roll == 87:
        special_notes.append("Ã°Å¸â€œâ€¹ Use Lithling character generation (p.26) if activated")
    elif roll == 93:
        special_notes.append("Ã¢Å¡Â¡ A Prismatic Tempest forms (see weather tables)")
    
    if special_notes:
        result += "\n" + "\n".join(special_notes)
    
    return result

def _lookup_exotica(
    name_fragment: str = Field(description="Part of item name to search")
) -> str:
    """Search Exotica table by name. Use when player mentions an exotica item or you need to verify its properties."""
    fragment_lower = name_fragment.lower()
    matches = []
    
    for roll, exotica in EXOTICA_TABLE.items():
        if fragment_lower in exotica['name'].lower() or fragment_lower in exotica['description'].lower():
            matches.append((roll, exotica))
    
    if not matches:
        return f"Ã¢ÂÅ’ No Exotica found matching '{name_fragment}'"
    
    result = [f"**Exotica matching '{name_fragment}':** ({len(matches)} found)", ""]
    
    for roll, exotica in matches:
        result.append(f"**{roll}.** {exotica['name']}")
        result.append(f"   {exotica['slots_uses']}")
        # Truncate long descriptions
        desc = exotica['description']
        if len(desc) > 100:
            desc = desc[:100] + "..."
        result.append(f"   _{desc}_")
        result.append("")
    
    return "\n".join(result)

_exotica_generator_data = None

def _load_exotica_generator():
    """Load and cache exotica generator tables."""
    global _exotica_generator_data
    if _exotica_generator_data is not None:
        return _exotica_generator_data
    gen_path = RULES_DATA_DIR / "rulebook" / "exotica_generator.json"
    if not gen_path.exists():
        return None
    with open(gen_path, 'r') as f:
        _exotica_generator_data = json.load(f)
    return _exotica_generator_data

def _generate_faction():
    """Roll a Minor faction (CH p.91) and propose it as a ledger record."""
    rec = _factions.generate_minor_faction()
    assets = ", ".join(rec["assets"])
    body = (
        "**GENERATED MINOR FACTION (CH p.91):**\n"
        f"- Reputation: {rec['reputation_adjective']}\n"
        f"- Type: {rec['type']}\n"
        f"- Goal: {rec['goal']}\n"
        f"- Leader: {rec['leader']}\n"
        f"- Assets: {assets}\n"
        f"- Rival: {rec['rival']}\n"
    )
    baton = _pf.next_block(
        _pf.push_call("faction", action="add",
                      name=_pf.raw('"<faction name>"'),
                      scope="minor", type=rec["type"], goal=rec["goal"],
                      leader=rec["leader"], assets=assets, rival=rec["rival"], rep=0),
        label="name it and commit to the ledger (REP starts 0; earn/set to adjust)")
    return body + baton

def _generate_gift(sample=False, roll=None, rng=random.randint):
    """Mystic Gift name generator (CH p.48) or sample-table roll (p.47).

    roll: int forces the sample-table d20 row; the string form 'qcol,qrow,fcol,frow'
    (tests/replays only) forces all four d20s of the Quality+Form generation.
    """
    if not isinstance(roll, (int, str)) or isinstance(roll, bool):
        roll = None  # direct calls bypass pydantic: a FieldInfo default is not a roll

    if sample:
        row = max(1, min(20, int(roll))) if roll else rng(1, 20)
        source, gift_name = _gifts.GIFT_SAMPLE[row]
        return (f"**SAMPLE GIFT (d20={row}, CH p.47):** **{gift_name}**\n"
                f"Source of power: {source}\n"
                f"Uses one item slot; baseline cost d6 HP (gift action=cost for the target-level die).\n"
                + _pf.next_block(
                    _pf.push_call("gift", action="add",
                                  character_name=_pf.raw('"<PC>"'),
                                  gift_name=gift_name,
                                  effect=_pf.raw('"<effect as the book/table defines>"'),
                                  source=source),
                    label="persist once granted in-fiction"))

    forced_q = forced_f = None
    if isinstance(roll, str) and "," in roll:
        try:
            parts = [int(p) for p in roll.split(",")]
            forced_q, forced_f = (parts[0], parts[1]), (parts[2], parts[3])
        except (ValueError, IndexError):
            return "Forced gift rolls must be 'qcol,qrow,fcol,frow' (four d20 values)."
    name, detail = _gifts.roll_gift_name(rng, quality_rolls=forced_q, form_rolls=forced_f)
    qc, qr = detail["quality_rolls"]
    fc, fr = detail["form_rolls"]
    return (f"**RANDOM GIFT (CH p.48):** **{name}**\n"
            f"Quality: {detail['quality']} (column d20={qc}, row d20={qr}) | "
            f"Form: {detail['form']} (column d20={fc}, row d20={fr})\n"
            "The book gives only the NAME - players and referee collectively agree "
            "the specific effect. Uses one item slot; baseline cost d6 HP.\n"
            + _pf.next_block(
                _pf.push_call("gift", action="add",
                              character_name=_pf.raw('"<PC>"'),
                              gift_name=name,
                              effect=_pf.raw('"<the effect the table agrees>"'),
                              source=_pf.raw('"<how it was obtained>"')),
                label="persist once granted in-fiction"))

def _generate_poison(roll=None, rng=random.randint):
    """One d20 reads the whole Poison Generator row (CH p.56) - single-roll table."""
    if not isinstance(roll, (int, str)) or (isinstance(roll, bool)):
        roll = None  # direct calls bypass pydantic: a FieldInfo default is not a roll
    roll = int(roll) if roll else rng(1, 20)
    row = VAARNISH_POISONS.get(roll)
    if not row:
        return f"Poison roll must be 1-20, got {roll}."
    apply_call = _pf.push_call("affliction", kind="toxin", action="poison_apply",
                               target=_pf.raw('"<victim>"'),
                               poison=_pf.raw(roll))
    lines = [f"**VAARNISH POISON** (d20={roll})",
             f"  {row['colour']} {row['form'].lower()} - {row['delivery']}",
             f"  Effect: {row['effect_text']}",
             "",
             _pf.next_block(apply_call, label="apply to a victim")]
    if row["delivery"] == "Coated on weapon":
        coat_call = _pf.push_call("affliction", kind="toxin", action="poison_coat",
                                  target=_pf.raw('"<pc>"'),
                                  weapon=_pf.raw('"<weapon>"'),
                                  poison=_pf.raw(roll))
        lines.append("  " + _pf.next_block(coat_call, label="or coat a weapon"))
    return "\n".join(lines)

def _generate_codex(roll=None, rng=random.randint):
    """G2: mint a complete codex - d100 equation (CH pp.59-60) + d20
    physical appearance (CH p.57). [INT] stays verbatim; codex
    action="use" substitutes the reader's INT bonus at read time."""
    if not isinstance(roll, (int, str)) or isinstance(roll, bool):
        roll = None  # direct calls bypass pydantic: FieldInfo is not a roll
    roll = int(roll) if roll else rng(1, 100)
    row = None
    for idx, r in HYPERGEOMETRIC_EQUATIONS.items():
        lo, hi = r["d100"]
        if lo <= roll <= hi:
            row = r
            break
    if row is None:
        return f"Equation roll must be 1-100, got {roll}."
    look_roll = rng(1, 20)
    look = CODEX_APPEARANCES[look_roll]
    short_name = f"Codex of {row['name']}"
    add_call = _pf.push_call(
        "codex", action="add",
        character_name=_pf.raw('"<PC>"'),
        codex_name=_pf.raw(f'"{short_name}"'),
        equation_name=_pf.raw(f'"{row["name"]}"'),
        effect=_pf.raw(f'"{row["effect_text"]}"'))
    lines = [f"**HYPERGEOMETRIC CODEX** (d100={roll}, appearance d20={look_roll})",
             f"  Form: {look}",
             f"  Equation: **{row['name']}** (band {row['d100'][0]}-{row['d100'][1]})",
             f"  Effect: {row['effect_text']}",
             "  ([INT] = the reader's INT bonus, substituted at read time.)",
             "",
             _pf.next_block(add_call, label="when a PC claims it (1 item slot)")]
    return "\n".join(lines)

def _generate_drug(rolls=None, rng=random.randint):
    """CH p.45 (printed) drug generator: d20 per column, EFFECT rolled
    TWICE (the book's 'EFFECT (X2)' header). Prose-only -- the push applies
    the high as a condition; duration is DM-set with a next-day failsafe.
    R-B4a: addiction deferred until the full edition; no mechanics here."""
    if isinstance(rolls, str):
        try:
            rolls = [int(x) for x in rolls.split(",")]
        except ValueError:
            return f"rolls must be five d20 integers, got: {rolls}"
    if not isinstance(rolls, list) or not rolls:
        rolls = [rng(1, 20) for _ in range(5)]
    if len(rolls) != 5 or not all(
            isinstance(r, int) and 1 <= r <= 20 for r in rolls):
        return f"rolls must be five d20 integers (hue, form, ingested_by, effect, effect), got: {rolls}"
    hue_r, form_r, ing_r, eff1_r, eff2_r = rolls
    t = VAARNISH_DRUGS
    name = f"{t['hue'][hue_r]} {t['form'][form_r]}"
    eff1, eff2 = t["effect"][eff1_r], t["effect"][eff2_r]
    if eff1_r == eff2_r:
        effects = f"{eff1} (rolled twice -- DM adjudicates what a double means)"
        effects_note = "doubled effect (see above)"
    else:
        effects = f"{eff1} + {eff2}"
        effects_note = effects
    apply_call = _pf.push_call(
        "condition", action="apply",
        character=_pf.raw('"<PC>"'),
        name=_pf.raw(f'"{name} high"'),
        cause=_pf.raw(f'"VAARNISH drug ({t["ingested_by"][ing_r]})"'),
        note=_pf.raw(f'"{effects_note}; duration DM-set"'))
    lines = [f"**VAARNISH DRUG** (d20 x5 = {hue_r}/{form_r}/{ing_r}/{eff1_r}/{eff2_r})",
             f"  **{name}** -- {t['ingested_by'][ing_r]}",
             f"  Effects: {effects}",
             "",
             _pf.next_block(apply_call, label="when a PC takes it")]
    return "\n".join(lines)

def _elixir_row_for(roll: int):
    for idx, row in VAARNISH_ELIXIRS.items():
        lo, hi = row["d100"]
        if lo <= roll <= hi:
            return idx, row
    return None, None

def _generate_elixir(forced_roll: int = None, rng=random.randint) -> str:
    if not isinstance(forced_roll, int) or isinstance(forced_roll, bool):
        forced_roll = None  # direct calls bypass pydantic: a FieldInfo is not a roll
    roll = forced_roll if forced_roll is not None else rng(1, 100)
    idx, row = _elixir_row_for(roll)
    if row is None:
        return f"Elixir roll must be 1-100, got {roll}."
    lines = [f"**VAARNISH ELIXIR** (d100 = {roll})",
             f"**{row['name']}** -- POT {row['pot']}",
             f"Component: {row['component']}",
             f"Effect: {row['effect_text']}",
             "",
             f'NEXT: character(action="drink_elixir", name="<PC>", '
             f'elixir={idx}) when consumed '
             f'(application: {row["application"]}).']
    return "\n".join(lines)

def _generate_exotica(
    reroll_column: Optional[str] = Field(default=None, description="Reroll a specific column: material, form, theme, or action")
) -> str:
    """Generate a custom Exotica seed using the 4d100 generator. Rolls Material + Form + Theme + Action.
    The DM interprets the combination into a specific item with mechanics.
    Use instead of roll(action='exotica') when you want a themed/custom item rather than a pre-defined one."""

    gen_data = _load_exotica_generator()
    if gen_data is None:
        return "Error: exotica_generator.json not found in rulebook/"

    tables = gen_data.get('tables', {})

    valid_columns = ['material', 'form', 'theme', 'action']
    if reroll_column and reroll_column.lower() not in valid_columns:
        return f"Error: invalid column '{reroll_column}'. Must be one of: {', '.join(valid_columns)}"

    # Roll 4d100
    results = {}
    for column in valid_columns:
        table = tables.get(column, [])
        if not table:
            return f"Error: empty {column} table"
        roll = dice.d100()
        idx = min(roll - 1, len(table) - 1)
        results[column] = {'roll': roll, 'value': table[idx]}

    # Format output
    seed = f"{results['material']['value']} {results['form']['value']} of {results['theme']['value']}, {results['action']['value']}"

    return f"""{'='*60}
EXOTICA GENERATOR (4d100)
{'='*60}

**{seed}**

| Column | d100 | Result |
|--------|------|--------|
| Material | {results['material']['roll']} | {results['material']['value']} |
| Form | {results['form']['roll']} | {results['form']['value']} |
| Theme | {results['theme']['roll']} | {results['theme']['value']} |
| Action | {results['action']['roll']} | {results['action']['value']} |

Interpret this seed into a specific item with mechanics.
{'='*60}"""

_story_seeds_data = None


def _load_story_seeds_table():
    """Load + cache the d100 Story Seeds table (CH pp.87-89) from the engine
    rulebook data. Returns the table dict (columns + entries) or None."""
    global _story_seeds_data
    if _story_seeds_data is not None:
        return _story_seeds_data
    try:
        data = json.loads(read_rules_data("rulebook/tables.json"))
    except (OSError, ValueError):
        return None
    for t in data.get("rolling_tables", []):
        if t.get("id") == "table-story-seeds":
            _story_seeds_data = t
            return _story_seeds_data
    return None


def _generate_story_seed(
    reroll_column: Optional[str] = Field(default=None, description="Reroll a specific column: who, what, with, or why")
) -> str:
    """Roll the book's d100 Story Seeds generator (CH pp.87-89): four INDEPENDENT
    d100s, one per WHO/WHAT/WITH/WHY column. The DM reads the combination into a
    hook -- a backstory, a rumour, an NPC motive, a room's contents, a new force.
    Persist via thread/antagonist/character as fits what it becomes."""
    if not isinstance(reroll_column, str):
        reroll_column = None  # direct calls bypass pydantic: FieldInfo is not a column

    table = _load_story_seeds_table()
    if table is None:
        return "Error: table-story-seeds not found in rulebook data."

    columns = table.get("columns", ["who", "what", "with", "why"])
    entries = table.get("entries", [])
    if not entries:
        return "Error: empty story-seeds table."

    if reroll_column and reroll_column.lower() not in columns:
        return f"Error: invalid column '{reroll_column}'. Must be one of: {', '.join(columns)}"

    results = {}
    for column in columns:
        roll = dice.d100()
        idx = min(roll - 1, len(entries) - 1)
        results[column] = {"roll": roll, "value": entries[idx].get(column, "?")}

    seed = " / ".join(results[c]["value"] for c in columns)
    label = {"who": "WHO", "what": "WHAT", "with": "WITH", "why": "WHY"}
    rows = "\n".join(
        f"| {label.get(c, c.upper())} | {results[c]['roll']} | {results[c]['value']} |"
        for c in columns)

    # Crystallization batons: a story seed can become an unfolding thread, a
    # cultivated threat, or (if the WHO becomes a recurring statted character) a
    # registered sheet. Which one is DM judgment.
    thread_call = _pf.push_call(
        "thread", action="add",
        title=_pf.raw('"<name the thread>"'),
        description=_pf.raw(f'"{seed}"'))
    antag_call = _pf.push_call(
        "antagonist", action="add_seed",
        threat_name=_pf.raw('"<name the threat>"'),
        details=_pf.raw(f'"{seed}"'))
    reg_call = _pf.push_call(
        "character", action="register",
        name=_pf.raw(f'"{results[columns[0]]["value"]}"'),
        sheet=_pf.raw('"<full sheet JSON>"'))

    return f"""{'='*60}
STORY SEEDS GENERATOR (4d100 — CH pp.87-89)
{'='*60}

**{seed}**

| Column | d100 | Result |
|--------|------|--------|
{rows}

Read this into a hook — backstory, rumour, NPC motive, room contents, a new force.
{'='*60}
{_pf.next_block(thread_call, label="crystallize as an unfolding thread")}
{_pf.next_block(antag_call, label="or cultivate as an antagonist seed")}
{_pf.next_block(reg_call, label="or register the WHO as a full NPC if it recurs")}"""


BASIC_TAGS = {
    1: {"name": "Ancient", "effect": "Half base trade value."},
    2: {"name": "Bejewelled", "effect": "Triple base trade value."},
    3: {"name": "Blasphemous", "effect": "Cursed by a religious leader. DIS on reaction rolls when encountering followers of said religion."},
    4: {"name": "Bone", "effect": "Double trade value with Cacklemaw and Ghouls."},
    5: {"name": "Corroded", "effect": "Half base trade value."},
    6: {"name": "Crystalline", "effect": "If natural 1 is rolled, the weapon shatters beyond repair. Double base trade value."},
    7: {"name": "Delicate", "effect": "Half base slot weight, minimum one slot, breaks on a to-hit roll of 1-2."},
    8: {"name": "Elegant", "effect": "Half base slot weight, minimum one slot."},
    9: {"name": "Fungal", "effect": "Deals no damage to Fungal creatures. Regains an Ammo die step when fed decaying animal or vegetable matter."},
    10: {"name": "Gilded", "effect": "Double base trade value."},
    11: {"name": "Lacquered", "effect": "Double base trade value. Cannot rust or be corroded."},
    12: {"name": "Luminous", "effect": "Can be used as light source, double base trade value."},
    13: {"name": "Nomad's", "effect": "Made by Faa Nomads, double trade value with Faa nomads."},
    14: {"name": "Ornate", "effect": "Double base trade value."},
    15: {"name": "Polychrome", "effect": "Double base trade value."},
    16: {"name": "Quicksilver", "effect": "Half base slot weight, minimum one slot."},
    17: {"name": "Ritual", "effect": "Used in an occult ritual. Double trade value with Mystics."},
    18: {"name": "Sacred", "effect": "Blessed by a religious leader. ADV on reaction rolls when encountering followers of said religion."},
    19: {"name": "Shoddy", "effect": "Damage dice one step smaller (minimum d4)."},
    20: {"name": "Translucent", "effect": "Double base trade value."},
}

ADVANCED_TAGS = {
    1: {"name": "Agonising", "effect": "Biological targets Morale save or flee. PCs damaged must EGO save or move away."},
    2: {"name": "Anti-Paradoxical", "effect": "Double damage to Outsider-type creatures."},
    3: {"name": "Blasting", "effect": "Can hit multiple targets in same area. Roll to-hit once, compare to AV of all targets."},
    4: {"name": "Blinding", "effect": "Targets must DEX Save vs 1 round of Blindness."},
    5: {"name": "Concussive", "effect": "Targets STR save or are moved away from their location."},
    6: {"name": "Corrosive", "effect": "On hit: deal damage OR reduce target's AV by 1 (attacker's choice)."},
    7: {"name": "Electrical", "effect": "Double damage to Synthetic creatures, metal armour wearers, and targets in water."},
    8: {"name": "Entangling", "effect": "Targets DEX save or become Entangled (AV 09, attack with DIS, DEX Save to break free)."},
    9: {"name": "Eroding", "effect": "Double damage to Mineral-type creatures, vehicles, and structures."},
    10: {"name": "Flaming", "effect": "Ignites flammable objects. Cannot be used underwater."},
    11: {"name": "Freezing", "effect": "Targets CON save vs d4 DEX damage. At 0 DEX they are frozen solid."},
    12: {"name": "Heavy", "effect": "Double damage, double slot weight. Minimum STR +3 to use."},
    13: {"name": "Hypergeometric", "effect": "Exists partially outside Euclidean space. Double damage to Hypergeometric creatures."},
    14: {"name": "Mauling", "effect": "Extra damage die vs AV 13 or lower. Half damage vs AV 16 or higher."},
    15: {"name": "Parasitic", "effect": "Alive, cannot unequip without surgery. Double rations required. Never needs reload."},
    16: {"name": "Piercing", "effect": "Extra damage die vs AV 16 or higher. Half damage vs AV 13 or lower."},
    17: {"name": "Psyche-Suppressant", "effect": "Double damage to Psychic creatures. Cannot use Mystic Gifts while holding."},
    18: {"name": "Strong", "effect": "Double base damage. If weapon would break, it does not."},
    19: {"name": "Unstable", "effect": "On to-hit roll of 1, weapon explodes dealing 2d6 damage to wielder."},
    20: {"name": "Vampiric", "effect": "When damaging biological creatures, wielder regains HP equal to half damage."},
}

EXOTIC_TAGS = {
    1: {"name": "Aegis-Bearing", "effect": "Projects personal warding field. Grants +5 AV while held."},
    2: {"name": "Annihilating", "effect": "Target must CON save or crumble to dust. Wielder loses 1 max HP each time drawn."},
    3: {"name": "Autarch's", "effect": "Once an Autarch's. Highest quality. Gains 4 additional damage dice."},
    4: {"name": "Blood-Rapturous", "effect": "When target is killed, user heals for target's maximum HP."},
    5: {"name": "Colossal", "effect": "Triple base damage, triple slot weight. Minimum STR +6 to use."},
    6: {"name": "Extra-Dimensional", "effect": "Forged in another dimension. Has Hypergeometric AND Anti-Paradoxical tags. 5x trade value."},
    7: {"name": "Hard Light", "effect": "Made from hard light, projected from wrist-mounted prism. Weight: 0 slots."},
    8: {"name": "Heat-Seeking", "effect": "Always hits warm-blooded creatures."},
    9: {"name": "Indestructible", "effect": "Cannot be broken or destroyed by any means, natural or supernatural."},
    10: {"name": "Lithifying", "effect": "Targets take d8 DEX damage and gain +1 AV. At 0 DEX they turn to stone."},
    11: {"name": "Nano-edged", "effect": "Gains 2 additional damage dice."},
    12: {"name": "Necrotic", "effect": "Biological targets suffer d6 STR damage alongside base damage."},
    13: {"name": "Neurotoxic", "effect": "Biological targets CON save vs death."},
    14: {"name": "Polymorphic", "effect": "Can swap between two forms at will. Roll alternate base type."},
    15: {"name": "Reflecting", "effect": "Missed attacks against wielder damage the attacker instead."},
    16: {"name": "Psionic", "effect": "Operated by psychic power. To-hit with PSY bonus, EGO bonus added to damage."},
    17: {"name": "Rocket Boosted", "effect": "+d10 damage when charging into melee. Can be used to gain altitude."},
    18: {"name": "Stim-Boosting", "effect": "Boosts reaction times. Make one extra combat action per round."},
    19: {"name": "Ultra-Corrosive", "effect": "Reduces AV by 2 on hit. Targets take d8 CON damage alongside base damage."},
    20: {"name": "Vibroactive", "effect": "Vibrates at atomic frequency. Hits as though target was unarmoured."},
}

def _generate_weapon_obj(
    tier: str,
    weapon_type: str,
    base_roll=None,
    basic_roll=None,
    adv_roll=None,
    exotic_roll=None,
) -> dict:
    """Mint a structured weapon object for the given tier/type.

    When roll args are supplied (for deterministic tests), those values are used
    directly; otherwise each is drawn from dice exactly as _generate_weapon did.
    Returns a ws.build_weapon() dict plus display-only keys the renderer needs
    (full_name, tag_details, base_roll, roll_method, alternate_form,
    special_notes, tier, weapon_type, base_weapon).
    """
    tier = tier.lower()
    weapon_type = weapon_type.lower()
    weapon_table = MELEE_WEAPONS if weapon_type == "melee" else RANGED_WEAPONS

    # --- Roll for base weapon ---
    if base_roll is None:
        if tier == "basic":
            base_roll = dice.d12()
            roll_method = "d12"
        elif tier == "advanced":
            base_roll = dice.d20()
            roll_method = "d20"
        else:
            roll1 = dice.d20()
            roll2 = dice.d20()
            base_roll = max(roll1, roll2)
            roll_method = f"d20 ADV ({roll1}, {roll2})"
    else:
        # Deterministic path -- infer roll_method from tier for display
        if tier == "basic":
            roll_method = "d12"
        elif tier == "advanced":
            roll_method = "d20"
        else:
            roll_method = "d20 ADV (fixed)"

    base_weapon = weapon_table[base_roll].copy()

    # --- Roll Basic Tag (all tiers) ---
    if basic_roll is None:
        basic_roll = dice.d20()
    basic_tag = BASIC_TAGS[basic_roll]

    # --- Roll Advanced Tag (advanced + exotic) ---
    if tier in ["advanced", "exotic"] and adv_roll is None:
        adv_roll = dice.d20()
    adv_tag = ADVANCED_TAGS[adv_roll] if adv_roll is not None else None

    # --- Roll Exotic Tag (exotic only) ---
    alternate_form = None
    if tier == "exotic" and exotic_roll is None:
        exotic_roll = dice.d20()
    exotic_tag = EXOTIC_TAGS[exotic_roll] if exotic_roll is not None else None

    # Handle Polymorphic alternate form
    if exotic_roll == 14:
        alt_roll = dice.d20()
        alt_weapon = weapon_table[alt_roll]
        alternate_form = f"Alternate Form: {alt_weapon['name']} ({alt_weapon['damage']}, {alt_weapon['slots']} slots)"

    # --- Build prose tag strings (same wording as before) ---
    tag_details = []
    tag_details.append(f"**{basic_tag['name']}** (Basic, roll {basic_roll}): {basic_tag['effect']}")
    if adv_tag is not None:
        tag_details.append(f"**{adv_tag['name']}** (Advanced, roll {adv_roll}): {adv_tag['effect']}")
    if exotic_tag is not None:
        tag_details.append(f"**{exotic_tag['name']}** (Exotic, roll {exotic_roll}): {exotic_tag['effect']}")

    # --- Build full weapon name ---
    tag_names = [basic_tag['name']]
    if adv_tag is not None:
        tag_names.append(adv_tag['name'])
    if exotic_tag is not None:
        tag_names.append(exotic_tag['name'])
    full_name = " ".join(tag_names) + " " + base_weapon['name']

    # --- Compute final damage / slots (same multiplier logic) ---
    final_damage = base_weapon['damage']
    final_slots = base_weapon['slots']
    damage_multiplier = 1
    slot_multiplier = 1
    special_notes = []

    if adv_roll is not None:
        if adv_roll == 12:  # Heavy
            damage_multiplier *= 2
            slot_multiplier *= 2
            special_notes.append("Requires STR +3")
        if adv_roll == 18:  # Strong
            damage_multiplier *= 2

    if exotic_roll is not None:
        if exotic_roll == 3:  # Autarch's
            damage_multiplier *= 3
        if exotic_roll == 5:  # Colossal
            damage_multiplier *= 3
            slot_multiplier *= 3
            special_notes.append("Requires STR +6")
        if exotic_roll == 7:  # Hard Light
            final_slots = 0
        if exotic_roll == 11:  # Nano-edged
            damage_multiplier *= 3

    # Apply slot weight modifiers from basic tags
    if basic_roll in [8, 9, 17]:  # Delicate, Elegant, Quicksilver
        final_slots = max(1, final_slots // 2)

    # Format final damage
    if damage_multiplier > 1:
        final_damage = f"{damage_multiplier}{base_weapon['damage']}"

    # Apply slot multiplier
    if slot_multiplier > 1 and exotic_roll != 7:  # Don't multiply if Hard Light
        final_slots = final_slots * slot_multiplier

    # --- Assemble prose_tags list for build_weapon ---
    # Includes inherent base-weapon tags + rolled tag names
    prose_tags = list(base_weapon['tags']) + tag_names

    # --- Mint the structured object via build_weapon ---
    obj = ws.build_weapon(
        name=base_weapon['name'],
        damage=final_damage,
        slots=final_slots,
        prose_tags=prose_tags,
        range=weapon_type,
        ammo=base_weapon.get('ammo'),
    )

    # Attach display-only fields (validate_weapon ignores unknown keys)
    obj["full_name"] = full_name
    obj["tag_details"] = tag_details
    obj["base_roll"] = base_roll
    obj["roll_method"] = roll_method
    obj["alternate_form"] = alternate_form
    obj["special_notes"] = special_notes
    obj["tier"] = tier
    obj["weapon_type"] = weapon_type
    obj["base_weapon"] = base_weapon

    return obj

def _render_weapon_markdown(obj: dict) -> str:
    """Render a structured weapon object (from _generate_weapon_obj) to the
    same markdown block that _generate_weapon used to produce directly."""
    tier = obj["tier"]
    weapon_type = obj["weapon_type"]
    base_weapon = obj["base_weapon"]
    full_name = obj["full_name"]
    base_roll = obj["base_roll"]
    roll_method = obj["roll_method"]
    final_damage = obj["damage"]
    final_slots = obj["slots"]
    tag_details = obj["tag_details"]
    special_notes = obj["special_notes"]
    alternate_form = obj["alternate_form"]

    result = [
        f"{'='*60}",
        f"{tier.upper()} {weapon_type.upper()} WEAPON",
        f"{'='*60}",
        f"",
        f"**{full_name}**",
        f"",
        f"**Base:** {base_weapon['name']} ({base_weapon['damage']}, {base_weapon['slots']} slots) — Roll: {base_roll} ({roll_method})",
    ]

    # Add ammo for ranged
    if weapon_type == "ranged":
        result.append(f"**Ammo:** {base_weapon.get('ammo', 'N/A')}")

    # Add inherent tags
    if base_weapon['tags']:
        result.append(f"**Inherent Tags:** {', '.join(base_weapon['tags'])}")

    result.extend([
        f"",
        f"**Final Stats:**",
        f"  Damage: {final_damage}",
        f"  Slots: {final_slots}",
    ])

    if special_notes:
        result.append(f"  Requirements: {', '.join(special_notes)}")

    result.extend([
        f"",
        f"**Tags Applied:**",
    ])

    for detail in tag_details:
        result.append(f"  • {detail}")

    if alternate_form:
        result.append(f"")
        result.append(f"**{alternate_form}**")

    # Add repair/reload notes based on tier
    result.append(f"")
    result.append(f"**Notes:**")

    if tier == "basic":
        result.append(f"  • Repairs: 1 day")
        if weapon_type == "ranged":
            result.append(f"  • Reload: Any settlement")
    elif tier == "advanced":
        result.append(f"  • Repairs: d10 - INT days")
        result.append(f"  • Breaks on natural 1")
        if weapon_type == "ranged":
            result.append(f"  • Reload: Cities only")
    else:  # exotic
        result.append(f"  • Cannot be repaired if broken")
        result.append(f"  • Breaks on natural 1")
        result.append(f"  • Counts as Exotica for XP")
        if weapon_type == "ranged":
            result.append(f"  • Cannot be reloaded when empty")

    result.append(f"")
    result.append(f"{'='*60}")

    return "\n".join(result)

def _generate_weapon(
    tier: str = Field(default="exotic", description="'basic', 'advanced', or 'exotic'"),
    weapon_type: Optional[str] = Field(default=None, description="'melee' or 'ranged', or empty for random")
) -> str:
    """Generate random weapon with tags. Use for Exotica rolls 8-9, treasure caches, or when party finds a weapon."""
    # Validate tier
    tier = tier.lower()
    if tier not in ["basic", "advanced", "exotic"]:
        return f"❌ Invalid tier '{tier}'. Use: basic, advanced, or exotic"

    # Determine weapon type
    if weapon_type is None:
        weapon_type = "melee" if dice.d6() <= 3 else "ranged"
    else:
        weapon_type = weapon_type.lower()
        if weapon_type not in ["melee", "ranged"]:
            return f"❌ Invalid weapon_type '{weapon_type}'. Use: melee or ranged"

    obj = _generate_weapon_obj(tier=tier, weapon_type=weapon_type)
    return _render_weapon_markdown(obj)

def _lookup_weapon_tag(
    tag_name: str = Field(description="Part of tag name to search")
) -> str:
    """Search weapon tags by name. Use to check tag effects during combat or when generating weapons."""
    search = tag_name.lower()
    matches = []
    
    for roll, tag in BASIC_TAGS.items():
        if search in tag['name'].lower() or search in tag['effect'].lower():
            matches.append(("Basic", roll, tag))
    
    for roll, tag in ADVANCED_TAGS.items():
        if search in tag['name'].lower() or search in tag['effect'].lower():
            matches.append(("Advanced", roll, tag))
    
    for roll, tag in EXOTIC_TAGS.items():
        if search in tag['name'].lower() or search in tag['effect'].lower():
            matches.append(("Exotic", roll, tag))
    
    if not matches:
        return f"Ã¢ÂÅ’ No weapon tags found matching '{tag_name}'"
    
    result = [f"**Weapon tags matching '{tag_name}':** ({len(matches)} found)", ""]
    
    for tier, roll, tag in matches:
        result.append(f"**[{tier}] {tag['name']}** (roll {roll})")
        result.append(f"  {tag['effect']}")
        result.append("")
    
    return "\n".join(result)

def _generate_armour_obj(body_roll: Optional[int] = None) -> dict:
    """Mint a structured armour object from the body_armour table.

    body_roll: specific d20 roll (1-20); if None, rolls randomly.
    The listed AV is the worn AV; av_bonus = AV - 10 (bonus over unarmoured AV 10).
    Field keys in body_armour: Quality, Type, AV, Weight (slots parsed from Weight).
    Returns a ws.build_armour() dict plus display-only keys: full_name, av, weight, roll.
    """
    _data_dir = Path(__file__).parent / "data"
    forge = ContentForge(_data_dir)
    entry, actual_roll, err = forge.roll_on_table("body_armour", body_roll)
    if err:
        raise ValueError(f"_generate_armour_obj error: {err}")
    f = entry["fields"]
    quality = f.get("Quality", "")
    armour_type = f.get("Type", "Unknown")
    av_str = f.get("AV", "10")
    weight_str = f.get("Weight", "1 Slot")
    full_name = f"{quality} {armour_type}".strip() if quality else armour_type
    av = int(av_str)
    av_bonus = av - 10
    # Parse slots from Weight field (e.g. "3 Slots" or "1 Slot")
    try:
        slots = int(weight_str.split()[0])
    except (ValueError, IndexError):
        slots = 1
    # Attach the book-cited situational property (if any) as a prose tag.
    # These are DM-adjudicated save/skill modifiers — NOT engine_tags.
    prose_tags = []
    book_prop = ws.ARMOUR_TYPE_PROPERTIES.get(armour_type)
    if book_prop:
        prose_tags.append(book_prop)
    obj = ws.build_armour(name=full_name, av_bonus=av_bonus, slots=slots, prose_tags=prose_tags)
    # Attach display-only fields
    obj["full_name"] = full_name
    obj["av"] = av
    obj["weight"] = weight_str
    obj["roll"] = actual_roll
    return obj

def _render_armour_markdown(obj: dict) -> str:
    """Render a structured armour object (from _generate_armour_obj) to a
    markdown block consistent with _render_weapon_markdown."""
    result = [
        f"{'='*60}",
        f"BODY ARMOUR",
        f"{'='*60}",
        f"",
        f"**{obj['full_name']}**",
        f"",
        f"**Roll:** {obj['roll']} (d20)",
        f"",
        f"**Stats:**",
        f"  AV: {obj['av']} (+{obj['av_bonus']} over unarmoured)",
        f"  Slots: {obj['slots']} ({obj['weight']})",
        f"",
        f"{'='*60}",
    ]
    return "\n".join(result)

def _generate_npc(
    ancestry: Optional[str] = Field(default=None, description="Ancestry, or empty to roll: True-kin, Cacogen, Synth, Newbeast, Neobloom, Mycomorph, Faa Nomad, Cacklemaw Exile, Planeyfolk, Lithling"),
    name_style: Optional[str] = Field(default=None, description="A (formal), B (feminine), C (descriptive), D (surname), or empty for random"),
    include_secret: bool = Field(default=True, description="Include a secret for referee")
) -> str:
    """Generate random NPC with ancestry, personality, career, and secret. Use when party meets unnamed NPCs or populating a location."""
    result = []
    
    # Roll or use specified ancestry
    if ancestry:
        npc_ancestry = ancestry
    else:
        ancestry_roll = dice.d20()
        npc_ancestry = ANCESTRY_TABLE[ancestry_roll]
    
    # Roll personality traits
    manner_roll = dice.d20()
    voice_roll = dice.d20()
    drive_roll = dice.d20()
    
    manner = MANNER_TABLE[manner_roll]
    voice = VOICE_TABLE[voice_roll]
    drive = DRIVE_TABLE[drive_roll]
    
    # Roll bonds and allegiances
    bond_roll = dice.d20()
    faith_roll = dice.d20()
    faction_roll = dice.d20()
    
    bond = BOND_TABLE[bond_roll]
    faith = FAITH_TABLE[faith_roll]
    faction = FACTION_REPUTATION_TABLE[faction_roll]
    
    # Generate name
    name_tables = {'A': NAMES_A, 'B': NAMES_B, 'C': NAMES_C, 'D': NAMES_D}
    if name_style and name_style.upper() in name_tables:
        name_table = name_tables[name_style.upper()]
        style_used = name_style.upper()
    else:
        style_used = random.choice(['A', 'B', 'C', 'D'])
        name_table = name_tables[style_used]
    
    name_roll = dice.d100()
    npc_name = name_table[name_roll]
    
    # Roll career
    career_roll = dice.d100()
    career_data = CAREERS_TABLE[career_roll]
    career = career_data['career']
    items = career_data['items']
    
    # Roll secret if requested
    secret = None
    if include_secret:
        secret_roll = dice.d20()
        secret = SECRET_TABLE[secret_roll]
    
    # Format output
    result.append(f"{'='*60}")
    result.append(f"NPC: {npc_name}")
    result.append(f"{'='*60}")
    result.append(f"")
    result.append(f"**Ancestry:** {npc_ancestry}")
    result.append(f"**Career:** {career}")
    result.append(f"")
    result.append(f"**Personality:**")
    result.append(f"  Ã¢â‚¬Â¢ Manner: {manner}")
    result.append(f"  Ã¢â‚¬Â¢ Voice: {voice}")
    result.append(f"  Ã¢â‚¬Â¢ Drive: {drive}")
    result.append(f"")
    result.append(f"**Relationships:**")
    result.append(f"  Ã¢â‚¬Â¢ Closest Bond: {bond}")
    result.append(f"  Ã¢â‚¬Â¢ Faith: {faith}")
    result.append(f"  Ã¢â‚¬Â¢ Faction Standing: {faction}")
    result.append(f"")
    result.append(f"**Carried Items:**")
    result.append(f"  {items}")
    
    if secret:
        result.append(f"")
        result.append(f"**SECRET (Referee Only):**")
        result.append(f"  {secret}")
    
    # Voice differentiation for roleplay
    result.append(f"")
    result.append(f"**Speech Guide (for DM):**")

    # Derive speech register from manner + voice combination
    formal_manners = {"Guarded", "Haughty", "Gracious", "Pious", "Fastidious"}
    terse_manners = {"Laconic", "Nervous", "Paranoid", "Bitter", "Cold"}
    verbose_manners = {"Grandiose", "Manic", "Melodramatic", "Eccentric", "Gregarious"}

    if manner in formal_manners:
        register = "Formal — complete sentences, measured diction, avoids contractions"
    elif manner in terse_manners:
        register = "Terse — short sentences, clipped answers, silences instead of elaboration"
    elif manner in verbose_manners:
        register = "Verbose — tangents, asides, decorative language, rarely stops talking"
    else:
        register = "Casual — contractions, dropped words, conversational rhythm"

    result.append(f"  Register: {register}")

    # Derive verbal tic from ancestry
    ancestry_tics = {
        "True-kin": "Pauses before proper nouns, as if verifying they still exist",
        "Cacogen": "Slips between registers mid-sentence — high formal to gutter slang",
        "Newbeast": "Uses sensory metaphors for abstract concepts (\"that idea smells wrong\")",
        "Mycomorph": "Refers to self in plural when stressed (\"we think\", \"we remember\")",
        "Synth": "Occasionally restates own sentences more precisely, correcting nuance",
        "Faa Nomad": "Measures everything in distances and days of travel",
        "Neobloom": "Botanical metaphors woven through speech (\"that plan has shallow roots\")",
        "Lithling": "Speaks in declarative statements — rarely asks questions, states observations instead",
    }
    tic = ancestry_tics.get(npc_ancestry, "No distinctive verbal pattern")
    result.append(f"  Verbal tic: {tic}")

    # Add hook based on drive
    result.append(f"")
    result.append(f"**Plot Hook:**")
    result.append(f"  This {manner.lower()} {npc_ancestry.lower()} {career.lower()} is driven to {drive.lower()}.")
    if "Missing Bond" in drive:
        result.append(f"  (Their missing bond is their {bond}.)")
    
    result.append(f"")
    result.append(f"{'='*60}")
    result.append(f"Name Style: {style_used} | Rolls: d20={manner_roll},{voice_roll},{drive_roll} | d100={name_roll},{career_roll}")
    result.append(f"{'='*60}")

    # Crystallization baton: prefill what the generator MINTED (name, wants from
    # the drive roll, secret when one was rolled). Disposition is NOT minted --
    # it emerges at first meeting -- so it stays a placeholder. Persist stays DM
    # judgment: a walk-on can evaporate; a recurring NPC gets a record.
    set_kwargs = dict(
        action="set",
        name=_pf.raw(f'"{npc_name}"'),
        disposition=_pf.raw('"<disposition after first meeting>"'),
        wants=_pf.raw(f'"{drive}"'),
    )
    if secret:
        set_kwargs["secret"] = _pf.raw(f'"{secret}"')
    set_call = _pf.push_call("npc", **set_kwargs)
    result.append("")
    result.append(_pf.next_block(
        set_call, label="persist IF this NPC will recur (walk-ons can evaporate)"))

    return "\n".join(result)

def _lookup_career(
    career_name: str = Field(description="Part of career name to search for, e.g., 'priest', 'hunter'")
) -> str:
    """Search NPC careers by name. Use when assigning a career to a generated NPC or checking career equipment."""
    search = career_name.lower()
    matches = []
    
    for roll, data in CAREERS_TABLE.items():
        if search in data['career'].lower() or search in data['items'].lower():
            matches.append((roll, data))
    
    if not matches:
        return f"Ã¢ÂÅ’ No careers found matching '{career_name}'"
    
    result = [f"**Careers matching '{career_name}':** ({len(matches)} found)", ""]
    
    for roll, data in matches:
        result.append(f"**[{roll}] {data['career']}**")
        result.append(f"  Items: {data['items']}")
        result.append("")
    
    return "\n".join(result)

HYPERGEOMETRIC_EQUATIONS = {
    1: {"d100": (1, 3), "name": "Antithetical Copy",
        "effect_text": "Creates a daemonic, insanely evil copy of a target entity, violently opposed to the original's existence - physical contact between the two destroys both explosively. The antithesis crumbles to ash after [INT] hours."},
    2: {"d100": (4, 6), "name": "Diminish",
        "effect_text": "The reader or another targeted entity shrinks to half of their original size and mass. Lasts [INT] hours."},
    3: {"d100": (7, 9), "name": "Erase Paradox",
        "effect_text": "Targeted Hypergeometric or Outsider-type entity must EGO save vs 10+[INT]. On failure the entity accepts the fundamental implausibility of their presence and ceases to exist."},
    4: {"d100": (10, 12), "name": "Exchange Coordinates",
        "effect_text": "The reader swaps physical positions with a targeted entity. If a Hypergeometric Mishap is rolled, they become stuck together."},
    5: {"d100": (13, 15), "name": "Expand",
        "effect_text": "The reader or another targeted entity grows to double their original size and mass. Lasts [INT] hours."},
    6: {"d100": (16, 18), "name": "Flatten",
        "effect_text": "The reader or another targeted entity is transformed into a 2D hypergeometric entity. Lasts [INT] hours."},
    7: {"d100": (19, 21), "name": "Golem",
        "effect_text": "Imbues an inanimate object with mobility and sentience. It lives for [INT] hours. Make a Reaction Roll to determine its disposition."},
    8: {"d100": (22, 24), "name": "Imperfect Copy",
        "effect_text": "Creates [INT] copies of a target entity. They are colourless and lifeless, resembling sculptures made from ash."},
    9: {"d100": (25, 27), "name": "Increase Gravity",
        "effect_text": "Target entity feels the effects of gravity at ten times the usual force - unable to move or fight. Lasts [INT] combat rounds."},
    10: {"d100": (28, 30), "name": "Invert Gravity",
         "effect_text": "Target entity's gravitational polarity is reversed for [INT] combat rounds, falling towards the sky. When the effect ends, they take d6 falling damage for each round they fell skywards."},
    11: {"d100": (31, 33), "name": "Kinetic Ward",
         "effect_text": "Creates an invisible wall of hypergeometric force that negates all physical attacks. The barrier can protect one entity for [INT] combat rounds, or [INT] entities for one combat round."},
    12: {"d100": (34, 36), "name": "Perfect Copy",
         "effect_text": "Creates a perfect copy of a target entity, resembling the original in all respects. It crumbles to ash after [INT] hours."},
    13: {"d100": (37, 39), "name": "Phase",
         "effect_text": "The reader or another targeted entity is placed out of sync with the material realm - visible but unable to touch anything (except other phased entities). Lasts [INT] combat rounds."},
    14: {"d100": (40, 42), "name": "Portal",
         "effect_text": "The reader creates a pair of linked portals, which must sit on two flat surfaces that they can see. The portals persist for [INT] combat rounds."},
    15: {"d100": (43, 44), "name": "Return Fixed Coordinates",
         "effect_text": "The reader and/or [INT] other entities are transported to a predetermined point in space. The codex only connects to this pre-written point. (R-G2a band: 43-44.)"},
    16: {"d100": (45, 46), "name": "Return Random Coordinates",
         "effect_text": "The reader and/or [INT] other entities are transported to a random point in space which the reader has previously occupied. (R-G2a band: 45-46.)"},
    17: {"d100": (47, 50), "name": "Singularity",
         "effect_text": "Creates a miniature black hole for [INT] combat rounds, drawing in all unsecured entities in the room. Anything engulfed is destroyed. Living beings must STR save vs 10+[INT] to avoid being drawn in."},
    18: {"d100": (51, 53), "name": "Stasis",
         "effect_text": "A single entity is stranded outside the flow of time for [INT] combat rounds. They cannot be moved, harmed, or interacted with in any way."},
    19: {"d100": (54, 56), "name": "Summon",
         "effect_text": "The reader plucks a creature from the manifold halls of creation. Roll on the Monster Generator tables (content-forge) to determine the nature and disposition of the entity. Make a Reaction Roll as normal."},
    20: {"d100": (57, 59), "name": "Vanish",
         "effect_text": "The reader or another targeted entity is no longer visible in the normal spectrum of light. Infrared vision will still detect the hidden entity. Lasts [INT] hours."},
    21: {"d100": (60, 61), "name": "Accelerate",
         "effect_text": "Target entity moves at double speed for [INT] combat rounds, and makes twice their normal number of attacks."},
    22: {"d100": (62, 63), "name": "Assert Normality",
         "effect_text": "Reader sketches a circle of enforced normality, free of space-time aberrations, lasting [INT] combat rounds. Hypergeometric and Outsider-type creatures are physically repelled and may not enter. Mystic Gifts and Exotica relying on space-time distortion cannot be used inside."},
    23: {"d100": (64, 65), "name": "Attraction",
         "effect_text": "Target entity attracts objects of the same type, as though powerfully magnetised - a glass object attracts and sticks to other glass objects, etc. Lasts [INT] hours."},
    24: {"d100": (66, 67), "name": "Blink",
         "effect_text": "Reader teleports to a location in line of sight. If a Hypergeometric Mishap is rolled, they become stuck inside a nearby physical object."},
    25: {"d100": (68, 69), "name": "Create Cube",
         "effect_text": "Reader creates a cube, [INT] feet in height and depth, wholly comprised of any material they can currently touch. The cube's slot weight is [INT]."},
    26: {"d100": (70, 71), "name": "Darkness",
         "effect_text": "Reader expels a jet of complete darkness, blinding [INT] creatures for d6 combat rounds. Any light source caught within the jet is permanently extinguished."},
    27: {"d100": (72, 73), "name": "Dismantle",
         "effect_text": "A target entity you can touch is separated into its constituent parts, grouped according to the caster's whim (by colour, by size, by material, etc). Living targets can EGO save vs 10+[INT] to resist being broken down."},
    28: {"d100": (74, 75), "name": "Freeze",
         "effect_text": "Create a localised supercoolant cloud, dealing [INT]d6 DEX damage to a target. Creatures reduced to 0 DEX are frozen solid and cannot move until thawed."},
    29: {"d100": (76, 77), "name": "Invert Fate",
         "effect_text": "Target entity's destiny is inverted: all failed Saves and attack rolls are successes and all successful Saves and attack rolls are failures. Lasts [INT] combat rounds."},
    30: {"d100": (78, 79), "name": "Klein Bottle",
         "effect_text": "Reader creates a paradoxical hypergeometric bottle, which can contain [INT] doses of any fluid, even those that could not normally be safely transported (magma, acid, sable ikor)."},
    31: {"d100": (80, 81), "name": "Labyrinth Seed",
         "effect_text": "Create a fissure which leads to Vaarn's hypergeometric Labyrinth. Permanent; grows in size over time."},
    32: {"d100": (82, 83), "name": "Map of Fate",
         "effect_text": "Roll [INT]d20. Whenever the reader, or any other PC or NPC, makes a dice roll, they are obliged to choose from these d20 results. Until the pool is expended, no other dice can be rolled. Using Map of Fate again before the dice are expended results in an immediate Hypergeometric Mishap."},
    33: {"d100": (84, 85), "name": "Pale Fire",
         "effect_text": "Kindle an impossible pale fire, which exclusively burns non-flammable materials. May be extinguished by flammable gases or liquids."},
    34: {"d100": (86, 87), "name": "Phantasms",
         "effect_text": "Create up to [INT] light-distortion anomalies, which may appear to be solid objects or living creatures. They have no weight or depth and do not match the ambient light of their surroundings."},
    35: {"d100": (88, 89), "name": "Psychometry",
         "effect_text": "Reader attunes to the full 4D shape of a held object. They may ask the Referee [INT] Yes or No questions about the object's past, present, and possible futures."},
    36: {"d100": (90, 91), "name": "Radiance",
         "effect_text": "Reader manifests a searing flash of blinding red sunlight. All nearby creatures with eyes must DEX save vs [INT] rounds of Blindness."},
    37: {"d100": (92, 93), "name": "Reflective Ward",
         "effect_text": "Create a hyper-reflective surface the size of a hand-mirror, which can reflect up to [INT] attacks of any type back at the source before breaking. Lasts one combat round."},
    38: {"d100": (94, 95), "name": "Repel",
         "effect_text": "Target entity repels objects of the same type, as though powerfully anti-magnetised - a glass object repels and flies away from other glass objects, etc. Lasts [INT] hours."},
    39: {"d100": (96, 97), "name": "Sever",
         "effect_text": "The reader severs one of the target's body parts from the whole. For the next [INT] hours the severed part can move separately from its host body, but otherwise operates as normal - eyes still transmit visual information, hands can grasp, etc."},
    40: {"d100": (98, 100), "name": "Web",
         "effect_text": "Target entity is entangled in a web of hypergeometric threads for [INT] rounds, or [INT] entities are entangled for one round. They lose -5 AV and cannot move."},
}

CODEX_APPEARANCES = {
    1: "A goblet so black it drinks in light, the inner rim of which is inlaid with spiralling equations.",
    2: "The dried skin of a toad, tattooed with hypergeometric proofs.",
    3: "A book cast from iron, the pages of which must be turned with a mechanical crank.",
    4: "A tablet carved from pale lunar stone, which feels as light as a feather.",
    5: "A hat scaled with coins, the inverse sides of which are carved with hypergeometric sigils.",
    6: "A chunk of crystal, veined with hypergeometric glyphs when one holds it up to the light.",
    7: "The foot-long fang of a gigantic Ur-Snake, carved with frantic equations.",
    8: "A broken mirror, which displays the equation as though written upon the observer's reflected face.",
    9: "A lump of amber; the contorted shapes of insects trapped within spell out the equation's proofs.",
    10: "A ring set with polychrome gemstones; the equation is printed on the inner curve, hiding it while worn.",
    11: "A child's drawing tablet, the equation scribbled in chalk amongst naive doodles.",
    12: "An ancient set of binoculars; when raised to the eyes all one can see is the hypergeometric proof, written across the sky in mile-high letters of divine fire.",
    13: "A black book the size of a thumbnail yet heavy as sin; the pages must be turned with tweezers.",
    14: "A human heart, blue with putrescence yet still beating; the equation is written upon the muscle with luminous ink.",
    15: "A chrome skull, its brain cavity filled with scraps of burned paper on which the equation is repeated endlessly.",
    16: "A broken sword, the blade molten and warped into the shape of hypergeometric proofs.",
    17: "An ordinary looking wine-jar, sealed with a stopper made from black wax. Remove the stopper and a voice whispers from within the jar, endlessly repeating the equation.",
    18: "A dining plate, painted with innumerable dancing blue and red figures; stare at the plate with an empty mind and an equation begins to emerge from the whirl of colour.",
    19: "An ornate lady's fan, on which the equation is painted in the flowery court script of the Fallen Autarchy.",
    20: "An infinite Mobius strip made from ancient parchment; the equation is written along the paradoxical coiling faces.",
}

VAARNISH_DRUGS = {
    "hue": {
        1: "Red", 2: "Blue", 3: "Yellow", 4: "White", 5: "Black",
        6: "Pink", 7: "Orange", 8: "Viridian", 9: "Olive", 10: "Silver",
        11: "Gold", 12: "Bronze", 13: "Umber", 14: "Steel", 15: "Smoke",
        16: "Indigo", 17: "Azure", 18: "Violet", 19: "Octarine", 20: "Ulfire",
    },
    "form": {
        1: "Sugar", 2: "Leaf", 3: "Crystal", 4: "Cactus", 5: "Fungus",
        6: "Brain", 7: "Pearl", 8: "Slime", 9: "Meat", 10: "Honey",
        11: "Insect", 12: "Liquid", 13: "Stone", 14: "Glyph", 15: "Biotech",
        16: "Sand", 17: "Root", 18: "Blood", 19: "Clay", 20: "Tooth",
    },
    "ingested_by": {
        1: "Snorting", 2: "Injected", 3: "Stewed", 4: "Boiled in Tea",
        5: "Swallow Whole", 6: "Lick It", 7: "Brain Interface",
        8: "Hold on Tongue", 9: "Smoke It", 10: "Touch to Eyes",
        11: "Absorbed in Skin", 12: "Stare at It",
        13: "Burn and Watch the Flames", 14: "Infused into Honey",
        15: "Drunk in Urine", 16: "Burn and Eat the Ash",
        17: "Bake in Bread", 18: "Place in Ear", 19: "Only Affects Synths",
        20: "Smell It",
    },
    "effect": {
        1: "Euphoria", 2: "Paranoia", 3: "Auditory Hallucinations",
        4: "Visual Hallucinations", 5: "No Pain", 6: "Fearless",
        7: "Ego Death", 8: "Levitation", 9: "Anxious Sweats",
        10: "Itchy Eyeballs", 11: "Nasal Drip", 12: "Split Personality",
        13: "Nausea", 14: "Behold Azathoth", 15: "Supernatural Hearing",
        16: "Paralysed", 17: "Murderous Rage", 18: "Can't Stop Dancing",
        19: "Very Mellow", 20: "Heightened Empathy",
    },
}

CRUCIBLE_QUALITIES = {
    1: "Ultraviolet", 2: "Engraved", 3: "Flexglass", 4: "Crystalline",
    5: "Ceramic", 6: "Polychrome", 7: "Quicksilver", 8: "Spiny",
    9: "Transparent", 10: "Bejewelled", 11: "Stone", 12: "Plasteel",
    13: "Flowstone", 14: "Luminous", 15: "Golden", 16: "Bronze",
    17: "Sky-Iron", 18: "Azure", 19: "Magnetised", 20: "Lurid",
}

CRUCIBLE_SHAPES = {
    1: "Cauldron", 2: "Pot", 3: "Skull", 4: "Urn", 5: "Vase",
    6: "Sphere", 7: "Pyramid", 8: "Helm", 9: "Gourd", 10: "Kettle",
    11: "Bottle", 12: "Amphora", 13: "Flagon", 14: "Jug", 15: "Teapot",
    16: "Chalice", 17: "Barrel", 18: "Cube", 19: "Thermos", 20: "Eyeball",
}

def _generate_crucible(rolls=None, rng=random.randint):
    """B5: d20 Crucible flavor (CH p.51) - quality + shape. Mints
    nothing; the DM decides if it enters play. A Crucible takes 1 item
    slot and is the alchemist's primary tool."""
    if isinstance(rolls, str):
        try:
            rolls = [int(x) for x in rolls.split(",")]
        except ValueError:
            return f"rolls must be two d20 integers, got: {rolls}"
    if not isinstance(rolls, list) or not rolls:
        rolls = [rng(1, 20), rng(1, 20)]
    if len(rolls) != 2 or not all(
            isinstance(r, int) and 1 <= r <= 20 for r in rolls):
        return f"rolls must be two d20 integers (quality, shape), got: {rolls}"
    q, s = rolls
    name = f"{CRUCIBLE_QUALITIES[q]} {CRUCIBLE_SHAPES[s]}"
    return ("\n".join([
        f"**ALCHEMICAL CRUCIBLE** (d20 x2 = {q}/{s})",
        f"  **{name}** -- 1 item slot; hollow, fire-proof, corrosion-resistant.",
        "  The alchemist's primary tool. Brewing rules: "
        'lookup(action="alchemy").']))


def _roll_cacogen_mutation(roll: int = None) -> dict:
    """Roll one mutation off CACOGEN_MUTATIONS.json (d100). Returns the stored
    shape {'name','effect','source':'d100=N'}. THE single mutation mint path —
    reused by Proteus level-ups, Pseudo-Womb-fail resurrection, AND (via injection)
    the content forge's roll(action="mutation")/chargen. `roll` forces a specific
    d100 result (the forge's specific_roll); None rolls live."""
    mutations = json.loads(read_rules_data("CACOGEN_MUTATIONS.json"))
    if roll is None:
        roll = dice.d100()
    m = mutations.get(str(roll), {"name": "Unknown", "effect": "Error loading mutation"})
    return {"name": m["name"], "effect": m["effect"], "source": f"d100={roll}"}


_INJECTED = ('VAARNISH_POISONS', 'VAARNISH_ELIXIRS', 'MELEE_WEAPONS', 'RANGED_WEAPONS', '_stamp_slots_uses')


def register_generators(srv):
    """Inject the shared data tables + helper that stay resident in server.py."""
    g = globals()
    for _name in _INJECTED:
        g[_name] = getattr(srv, _name)
