"""Combat descriptor pool for enemy naming.

Provides 50+ narrative descriptors to differentiate enemies of the same type.
Used by combat system to avoid generic numbering (#1, #2, #3).
"""

import random
from typing import Set

# Descriptor categories (50+ total)
DESCRIPTOR_POOL = {
    "physical": [
        "tall", "short", "hulking", "wiry", "scarred",
        "limping", "one-eyed", "grizzled", "young",
        "lanky", "stocky", "gaunt", "muscular",
        "weathered", "pale"
    ],  # 15 descriptors

    "equipment": [
        "rifle", "blade", "club", "nets", "torch",
        "shield", "heavy armor", "tattered gear",
        "blue sash", "goggles", "bandolier", "scrap armor"
    ],  # 12 descriptors

    "position": [
        "leader", "second", "left flank", "right flank",
        "rear guard", "scout", "vanguard", "lookout",
        "veteran", "rookie"
    ],  # 10 descriptors

    "behavior": [
        "nervous", "confident", "aggressive", "cautious",
        "reckless", "calculating", "hesitant", "eager",
        "disciplined", "panicked"
    ],  # 10 descriptors

    "appearance": [
        "red bandana", "torn cloak", "brass mask",
        "painted face", "tattooed", "shaved head",
        "long hair", "bloodstained"
    ],  # 8 descriptors

    "stance": [
        "defensive", "circling", "advancing",
        "holding ground", "retreating"
    ],  # 5 descriptors
}

def get_all_descriptors() -> list[str]:
    """Get flat list of all 50+ descriptors."""
    descriptors = []
    for category in DESCRIPTOR_POOL.values():
        descriptors.extend(category)
    return descriptors

def assign_descriptor(creature_type: str, used_descriptors: Set[str], count: int) -> str:
    """Assign unique descriptor to enemy.

    Args:
        creature_type: Base creature name (e.g., "Gene Thief")
        used_descriptors: Already-used descriptors in this combat
        count: Which enemy this is (1st, 2nd, etc.)

    Returns:
        Full descriptor string (e.g., "Gene Thief (scarred)")
    """
    all_descriptors = get_all_descriptors()
    available = [d for d in all_descriptors if d not in used_descriptors]

    # Priority by count
    if count <= 5:
        # First 5: prefer physical + position
        priority = DESCRIPTOR_POOL["physical"] + DESCRIPTOR_POOL["position"]
        available_priority = [d for d in priority if d not in used_descriptors]
        if available_priority:
            descriptor = random.choice(available_priority)
        elif available:
            descriptor = random.choice(available)
        else:
            # Pool exhausted, use combined
            descriptor = f"{random.choice(DESCRIPTOR_POOL['physical'])} {random.choice(DESCRIPTOR_POOL['behavior'])}"

    elif count <= 10:
        # 6-10: add equipment + appearance
        if available:
            descriptor = random.choice(available)
        else:
            descriptor = f"{random.choice(DESCRIPTOR_POOL['equipment'])} {random.choice(DESCRIPTOR_POOL['position'])}"

    elif count <= 15:
        # 11-15: use all categories
        if available:
            descriptor = random.choice(available)
        else:
            # Combine categories
            cat1 = random.choice(list(DESCRIPTOR_POOL.keys()))
            cat2 = random.choice(list(DESCRIPTOR_POOL.keys()))
            descriptor = f"{random.choice(DESCRIPTOR_POOL[cat1])} {random.choice(DESCRIPTOR_POOL[cat2])}"

    else:
        # 16+: fallback to numbers with category
        category = random.choice(list(DESCRIPTOR_POOL.keys()))
        desc = random.choice(DESCRIPTOR_POOL[category])
        descriptor = f"#{count} ({desc})"

    return f"{creature_type} ({descriptor})"
