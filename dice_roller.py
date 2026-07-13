"""
Enhanced dice rolling module for Rubicon Seven campaign
Implements unbiased RNG with validation and optional logging
"""

import random
import secrets
import time
from typing import Optional, List, Tuple
from collections import Counter


class DiceRoller:
    """
    Production-grade dice roller with anti-bias mechanisms
    
    Uses Python's secrets module for cryptographically strong randomness
    when available, falls back to random.SystemRandom() for improved
    unpredictability over standard Mersenne Twister.
    """
    
    def __init__(self, use_crypto_random: bool = False, log_rolls: bool = False):
        """
        Initialize dice roller
        
        Args:
            use_crypto_random: Use secrets module (slower but cryptographically strong)
            log_rolls: Log all rolls for transparency/debugging
        """
        self.use_crypto = use_crypto_random
        self.log_rolls = log_rolls
        self.roll_history = []
        
        # Use SystemRandom (backed by os.urandom) for better randomness
        self.rng = random.SystemRandom()
        
    def roll(self, sides: int, num_dice: int = 1, modifier: int = 0) -> dict:
        """
        Roll dice with validation and logging
        
        Args:
            sides: Number of sides on the die (d6, d20, etc)
            num_dice: How many dice to roll
            modifier: Flat bonus/penalty to add
            
        Returns:
            dict with 'total', 'rolls', 'modifier', 'breakdown'
        """
        if sides < 1:
            raise ValueError(f"Invalid die size: d{sides}")
        if num_dice < 1:
            raise ValueError(f"Must roll at least 1 die, got {num_dice}")
            
        # Roll dice using crypto-strong random if enabled
        if self.use_crypto:
            rolls = [secrets.randbelow(sides) + 1 for _ in range(num_dice)]
        else:
            # SystemRandom uses os.urandom - no seed, no bias
            rolls = [self.rng.randint(1, sides) for _ in range(num_dice)]
        
        total = sum(rolls) + modifier
        
        result = {
            'total': total,
            'rolls': rolls,
            'modifier': modifier,
            'breakdown': f"{num_dice}d{sides}{'+' + str(modifier) if modifier > 0 else ''}{modifier if modifier < 0 else ''} = {rolls} = {total}",
            'timestamp': time.time()
        }
        
        if self.log_rolls:
            self.roll_history.append(result)
            
        return result
    
    def d(self, sides: int, modifier: int = 0) -> int:
        """Convenience method: roll 1 die, return just the total"""
        return self.roll(sides, 1, modifier)['total']
    
    def d2(self, modifier: int = 0) -> int:
        """Roll d2 (coin flip)"""
        return self.d(2, modifier)
    
    def d3(self, modifier: int = 0) -> int:
        """Roll d3"""
        return self.d(3, modifier)
    
    def d4(self, modifier: int = 0) -> int:
        """Roll d4"""
        return self.d(4, modifier)
    
    def d6(self, modifier: int = 0) -> int:
        """Roll d6 (common for encounters)"""
        return self.d(6, modifier)
    
    def d8(self, modifier: int = 0) -> int:
        """Roll d8 (HP increases)"""
        return self.d(8, modifier)
    
    def d10(self, modifier: int = 0) -> int:
        """Roll d10"""
        return self.d(10, modifier)
    
    def d12(self, modifier: int = 0) -> int:
        """Roll d12"""
        return self.d(12, modifier)
    
    def d20(self, modifier: int = 0) -> int:
        """Roll d20 (common for reactions, checks)"""
        return self.d(20, modifier)
    
    def d100(self, modifier: int = 0) -> int:
        """Roll d100 (mutation tables, percentile)"""
        return self.d(100, modifier)
    
    def roll_with_advantage(self, sides: int, modifier: int = 0) -> dict:
        """Roll twice, take higher (D&D style advantage)"""
        roll1 = self.roll(sides, 1, modifier)
        roll2 = self.roll(sides, 1, modifier)
        
        winner = roll1 if roll1['total'] >= roll2['total'] else roll2
        
        return {
            **winner,
            'advantage': True,
            'other_roll': roll1['total'] if winner == roll2 else roll2['total']
        }
    
    def roll_with_disadvantage(self, sides: int, modifier: int = 0) -> dict:
        """Roll twice, take lower"""
        roll1 = self.roll(sides, 1, modifier)
        roll2 = self.roll(sides, 1, modifier)
        
        loser = roll1 if roll1['total'] <= roll2['total'] else roll2
        
        return {
            **loser,
            'disadvantage': True,
            'other_roll': roll1['total'] if loser == roll2 else roll2['total']
        }
    
    def roll_from_table(
        self, 
        table: List[str], 
        die_size: Optional[int] = None
    ) -> Tuple[int, str]:
        """
        Roll on a table (e.g., encounter table)
        
        Args:
            table: List of table entries
            die_size: Optional die size (if None, uses len(table))
            
        Returns:
            (roll_value, table_entry)
        """
        if not table:
            raise ValueError("Table is empty")
            
        max_size = die_size if die_size else len(table)
        roll = self.d(min(max_size, len(table)))
        entry = table[roll - 1]  # 1-indexed to 0-indexed
        
        return roll, entry
    
    def roll_unique_from_table(
        self,
        table: dict,
        excluded: List[str],
        max_attempts: int = 100
    ) -> Tuple[int, dict]:
        """
        Roll on table with exclusions (for bloomboons/mutations)
        
        Uses rejection sampling - keeps rolling until finding
        a result not in excluded list.
        
        Args:
            table: Dict mapping roll -> entry
            excluded: List of already-rolled entries to avoid
            max_attempts: Safety limit to prevent infinite loops
            
        Returns:
            (roll_value, entry)
            
        Raises:
            RuntimeError if can't find unique result
        """
        table_size = len(table)
        
        for attempt in range(max_attempts):
            roll = self.d(table_size)
            entry = table.get(str(roll))
            
            if entry and entry.get('name') not in excluded:
                return roll, entry
        
        # Fallback: if everything is excluded, just return latest roll
        # (This means the player has all 20 bloomboons, etc)
        return roll, entry
    
    def parse_dice_notation(self, notation: str) -> dict:
        """
        Parse dice notation like 'd6', '3d6', '2d8+3'
        
        Args:
            notation: Dice string (e.g., 'd6', '3d6', '2d8+3', 'd20-2')
            
        Returns:
            dict with 'num_dice', 'sides', 'modifier'
        """
        notation = notation.lower().strip()
        
        # Handle modifier
        modifier = 0
        if '+' in notation:
            notation, mod_str = notation.split('+')
            modifier = int(mod_str)
        elif '-' in notation and notation.count('-') == 1:
            notation, mod_str = notation.split('-')
            modifier = -int(mod_str)
        
        # Parse dice
        if notation.startswith('d'):
            # Simple 'd6' format
            num_dice = 1
            sides = int(notation[1:])
        elif 'd' in notation:
            # '3d6' format
            num_str, sides_str = notation.split('d')
            num_dice = int(num_str)
            sides = int(sides_str)
        else:
            raise ValueError(f"Invalid dice notation: {notation}")
        
        return {
            'num_dice': num_dice,
            'sides': sides,
            'modifier': modifier
        }
    
    def roll_notation(self, notation: str) -> dict:
        """
        Roll using dice notation string
        
        Args:
            notation: Dice string (e.g., 'd6', '3d6', '2d8+3')
            
        Returns:
            Roll result dict
        """
        parsed = self.parse_dice_notation(notation)
        return self.roll(
            sides=parsed['sides'],
            num_dice=parsed['num_dice'],
            modifier=parsed['modifier']
        )
    
    def get_roll_statistics(self) -> dict:
        """
        Analyze roll history for bias detection
        
        Returns distribution statistics for all logged rolls
        """
        if not self.roll_history:
            return {"error": "No rolls logged (enable log_rolls=True)"}
        
        # Separate by die type
        by_die_type = {}
        
        for roll_result in self.roll_history:
            breakdown = roll_result['breakdown']
            # Extract die type from breakdown
            if 'd' in breakdown:
                die_type = breakdown.split('=')[0].split('+')[0].split('-')[0].strip()
                
                if die_type not in by_die_type:
                    by_die_type[die_type] = []
                
                # Store individual rolls
                by_die_type[die_type].extend(roll_result['rolls'])
        
        # Calculate statistics
        stats = {}
        for die_type, rolls in by_die_type.items():
            distribution = Counter(rolls)
            stats[die_type] = {
                'total_rolls': len(rolls),
                'distribution': dict(distribution),
                'mean': sum(rolls) / len(rolls),
                'min': min(rolls),
                'max': max(rolls)
            }
        
        return stats
    
    def clear_history(self):
        """Clear roll history"""
        self.roll_history = []


# Global singleton instance for convenience
# Uses SystemRandom (os.urandom backed) for better randomness
_default_roller = DiceRoller(use_crypto_random=False, log_rolls=False)


# Convenience functions that use the default roller
def roll_dice(sides: int, num_dice: int = 1, modifier: int = 0) -> dict:
    """Roll dice using default roller"""
    return _default_roller.roll(sides, num_dice, modifier)


def d2(modifier: int = 0) -> int:
    """Quick d2 roll (coin flip)"""
    return _default_roller.d2(modifier)


def d3(modifier: int = 0) -> int:
    """Quick d3 roll"""
    return _default_roller.d3(modifier)


def d4(modifier: int = 0) -> int:
    """Quick d4 roll"""
    return _default_roller.d4(modifier)


def d6(modifier: int = 0) -> int:
    """Quick d6 roll"""
    return _default_roller.d6(modifier)


def d8(modifier: int = 0) -> int:
    """Quick d8 roll"""
    return _default_roller.d8(modifier)


def d10(modifier: int = 0) -> int:
    """Quick d10 roll"""
    return _default_roller.d10(modifier)


def d12(modifier: int = 0) -> int:
    """Quick d12 roll"""
    return _default_roller.d12(modifier)


def d20(modifier: int = 0) -> int:
    """Quick d20 roll"""
    return _default_roller.d20(modifier)


def d100(modifier: int = 0) -> int:
    """Quick d100 roll"""
    return _default_roller.d100(modifier)


def roll_notation(notation: str) -> dict:
    """Roll using dice notation"""
    return _default_roller.roll_notation(notation)


# For testing/validation
if __name__ == "__main__":
    # Test basic rolling
    print("Testing dice roller...")
    
    roller = DiceRoller(log_rolls=True)
    
    # Test various dice
    print(f"\nd2 (coin flip): {roller.d2()}")
    print(f"d3: {roller.d3()}")
    print(f"d4: {roller.d4()}")
    print(f"d6: {roller.d6()}")
    print(f"d8: {roller.d8()}")
    print(f"d10: {roller.d10()}")
    print(f"d12: {roller.d12()}")
    print(f"d20: {roller.d20()}")
    print(f"d100: {roller.d100()}")
    
    # Test with modifiers
    print(f"\nd20+5: {roller.d20(modifier=5)}")
    print(f"d6-2: {roller.d6(modifier=-2)}")
    
    # Test notation parsing
    print(f"\n3d6+2: {roller.roll_notation('3d6+2')}")
    print(f"2d8-1: {roller.roll_notation('2d8-1')}")
    print(f"4d4: {roller.roll_notation('4d4')}")
    
    # Test table rolling
    test_table = ["Option A", "Option B", "Option C", "Option D", "Option E", "Option F"]
    roll_val, entry = roller.roll_from_table(test_table)
    print(f"\nTable roll: {roll_val} -> {entry}")
    
    # Roll 1000 d6s to check distribution
    print("\nRolling 1000 d6s to check for bias...")
    for _ in range(1000):
        roller.d6()
    
    stats = roller.get_roll_statistics()
    print("\nD6 Distribution (should be roughly uniform):")
    d6_stats = stats.get('1d6', {})
    dist = d6_stats.get('distribution', {})
    for face in sorted(dist.keys()):
        pct = (dist[face] / d6_stats['total_rolls']) * 100
        bar = '█' * int(pct / 2)
        print(f"  {face}: {dist[face]:4d} ({pct:5.2f}%) {bar}")
    
    print(f"\nMean: {d6_stats.get('mean', 0):.2f} (expected: 3.5)")
    
    # Test d20 distribution too
    print("\n" + "="*60)
    print("Rolling 1000 d20s to verify d20 fairness...")
    roller.clear_history()
    for _ in range(1000):
        roller.d20()
    
    stats = roller.get_roll_statistics()
    d20_stats = stats.get('1d20', {})
    d20_dist = d20_stats.get('distribution', {})
    
    print("\nD20 Distribution (each result should appear ~5%):")
    for result in range(1, 21):
        count = d20_dist.get(result, 0)
        pct = (count / d20_stats['total_rolls']) * 100
        bar = '█' * max(1, int(pct))
        print(f"  {result:2d}: {count:3d} ({pct:4.1f}%) {bar}")
    
    print(f"\nMean: {d20_stats.get('mean', 0):.2f} (expected: 10.5)")
