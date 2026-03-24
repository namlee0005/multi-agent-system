"""
Balance simulation for Cyber-Neon Roguelike.
Simulates 1000 runs and reports survival rates, bottleneck floors, and item drop adequacy.

Usage:
    python3 scripts/balance-test.py
    python3 scripts/balance-test.py --runs 5000 --seed 42
"""
import argparse
import random
import statistics
from dataclasses import dataclass
from typing import Optional

# ---------------------------------------------------------------------------
# Data models — mirror src/entities/enemy.ts values exactly
# ---------------------------------------------------------------------------

@dataclass
class EnemyTemplate:
    name: str
    hp: int
    attack: int
    defense: int
    xp_reward: int
    drop_rate: float          # 0.0–1.0 probability of dropping a heal item
    drop_heal_amount: int     # HP restored on drop

ENEMY_TEMPLATES: dict[str, EnemyTemplate] = {
    "drone":    EnemyTemplate("Drone",    hp=10,  attack=3,  defense=1, xp_reward=10, drop_rate=0.35, drop_heal_amount=8),
    "guard":    EnemyTemplate("Guard",    hp=22,  attack=5,  defense=2, xp_reward=22, drop_rate=0.30, drop_heal_amount=12),
    "enforcer": EnemyTemplate("Enforcer", hp=40,  attack=8,  defense=3, xp_reward=40, drop_rate=0.30, drop_heal_amount=18),
    "boss":     EnemyTemplate("Boss",     hp=80,  attack=10, defense=5,  xp_reward=100, drop_rate=0.80, drop_heal_amount=30),
}

# Floor composition: list of enemy template keys per floor
FLOOR_ENEMY_POOL: dict[int, list[str]] = {
    1: ["drone"] * 3,
    2: ["drone"] * 2 + ["guard"] * 2,
    3: ["guard"] * 2 + ["enforcer"],
    4: ["guard"] + ["enforcer"] * 2,
    5: ["boss"],
}

PLAYER_START_HP = 100
PLAYER_START_ATTACK = 8
PLAYER_START_DEFENSE = 2
LEVEL_ATTACK_BONUS = 2        # attack gained per level-up
LEVEL_DEFENSE_BONUS = 1       # defense gained per level-up
XP_PER_LEVEL = 50             # flat XP threshold per level


# ---------------------------------------------------------------------------
# Simulation engine
# ---------------------------------------------------------------------------

@dataclass
class PlayerState:
    hp: int = PLAYER_START_HP
    max_hp: int = PLAYER_START_HP
    attack: int = PLAYER_START_ATTACK
    defense: int = PLAYER_START_DEFENSE
    xp: int = 0
    level: int = 1
    floors_cleared: int = 0
    kills: int = 0

    def is_alive(self) -> bool:
        return self.hp > 0

    def gain_xp(self, amount: int) -> None:
        self.xp += amount
        while self.xp >= XP_PER_LEVEL * self.level:
            self.xp -= XP_PER_LEVEL * self.level
            self.level += 1
            self.attack += LEVEL_ATTACK_BONUS
            self.defense += LEVEL_DEFENSE_BONUS


def simulate_combat(player: PlayerState, enemy: EnemyTemplate, rng: random.Random) -> bool:
    """Returns True if player survives. Mutates player HP."""
    enemy_hp = enemy.hp

    while enemy_hp > 0 and player.is_alive():
        player_dmg = max(1, player.attack - enemy.defense + rng.randint(-2, 2))
        enemy_hp -= player_dmg

        if enemy_hp <= 0:
            break

        enemy_dmg = max(1, enemy.attack - player.defense + rng.randint(-2, 2))
        player.hp -= enemy_dmg

    if player.is_alive():
        player.gain_xp(enemy.xp_reward)
        player.kills += 1
        if rng.random() < enemy.drop_rate:
            player.hp = min(player.max_hp, player.hp + enemy.drop_heal_amount)
        return True

    return False


def simulate_run(seed: Optional[int] = None) -> dict:
    rng = random.Random(seed)
    player = PlayerState()

    for floor_num in range(1, len(FLOOR_ENEMY_POOL) + 1):
        enemies = list(FLOOR_ENEMY_POOL[floor_num])
        rng.shuffle(enemies)

        for enemy_key in enemies:
            enemy = ENEMY_TEMPLATES[enemy_key]
            survived = simulate_combat(player, enemy, rng)
            if not survived:
                return {
                    "won": False,
                    "floors_cleared": player.floors_cleared,
                    "death_floor": floor_num,
                    "death_enemy": enemy.name,
                    "final_hp": 0,
                    "final_level": player.level,
                    "kills": player.kills,
                }

        player.floors_cleared = floor_num

    return {
        "won": True,
        "floors_cleared": player.floors_cleared,
        "death_floor": None,
        "death_enemy": None,
        "final_hp": player.hp,
        "final_level": player.level,
        "kills": player.kills,
    }


# ---------------------------------------------------------------------------
# Analysis & reporting
# ---------------------------------------------------------------------------

def run_simulation(n: int, base_seed: Optional[int]) -> list:
    return [(base_seed + i if base_seed is not None else None) for i in range(n)]


def analyze(results: list[dict]) -> None:
    n = len(results)
    wins = [r for r in results if r["won"]]
    losses = [r for r in results if not r["won"]]
    win_rate = len(wins) / n * 100

    death_by_floor: dict[int, int] = {}
    death_by_enemy: dict[str, int] = {}
    for r in losses:
        f = r["death_floor"]
        e = r["death_enemy"]
        death_by_floor[f] = death_by_floor.get(f, 0) + 1
        death_by_enemy[e] = death_by_enemy.get(e, 0) + 1

    survivor_hp = [r["final_hp"] for r in wins]
    level_dist = [r["final_level"] for r in results]

    print(f"\n{'='*60}")
    print(f"  CYBER-NEON ROGUELIKE — Balance Simulation ({n} runs)")
    print(f"{'='*60}")
    print(f"\n  Win rate:          {win_rate:.1f}%  ({len(wins)}/{n})")
    print(f"  Target win rate:   15–25% (roguelike sweet spot)")

    if wins:
        print(f"\n  Survivor stats:")
        print(f"    Avg final HP:    {statistics.mean(survivor_hp):.1f}")
        print(f"    Median final HP: {statistics.median(survivor_hp):.1f}")
        print(f"    Min final HP:    {min(survivor_hp)}")

    print(f"\n  Level distribution (all runs):")
    for lvl in sorted(set(level_dist)):
        count = level_dist.count(lvl)
        bar = "█" * max(1, count * 30 // n)
        print(f"    Lvl {lvl:>2}: {bar} {count}")

    if death_by_floor:
        print(f"\n  Deaths by floor:")
        for floor in sorted(death_by_floor):
            pct = death_by_floor[floor] / len(losses) * 100
            print(f"    Floor {floor}: {death_by_floor[floor]:>4} deaths ({pct:.1f}%)")

        print(f"\n  Deaths by enemy:")
        for enemy, cnt in sorted(death_by_enemy.items(), key=lambda x: -x[1]):
            pct = cnt / len(losses) * 100
            print(f"    {enemy:<12}: {cnt:>4} deaths ({pct:.1f}%)")

    print(f"\n{'='*60}")
    print("  BALANCE ASSESSMENT")
    print(f"{'='*60}")

    issues = []

    if win_rate > 30:
        issues.append("WARN  Win rate too HIGH (>30%) — game is too easy. Raise enemy attack or reduce drop rate.")
    elif win_rate < 10:
        issues.append("WARN  Win rate too LOW (<10%) — game is too hard. Lower enemy attack or raise drop rate.")
    else:
        issues.append("OK    Win rate within target range (10–30%).")

    top_death_floor = max(death_by_floor, key=death_by_floor.get) if death_by_floor else None
    if top_death_floor and len(losses) > 0 and death_by_floor[top_death_floor] / len(losses) > 0.50:
        issues.append(f"WARN  Floor {top_death_floor} is a hard wall (>50% of deaths). "
                      f"Add mid-floor heal chest or reduce floor {top_death_floor} enemy count by 1.")

    if "Boss" in death_by_enemy and len(losses) > 0:
        boss_pct = death_by_enemy["Boss"] / len(losses)
        if boss_pct < 0.10:
            issues.append("WARN  Boss too easy (<10% of deaths). Raise Boss.attack by 3-5.")
        elif boss_pct > 0.60:
            issues.append("WARN  Boss kills >60% of losers — final floor spike. Lower Boss.attack by 2 or raise drop_rate to 0.90.")

    for msg in issues:
        print(f"  {msg}")

    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Balance simulation for Cyber-Neon Roguelike")
    parser.add_argument("--runs", type=int, default=1000, help="Number of simulated runs (default: 1000)")
    parser.add_argument("--seed", type=int, default=None, help="Base RNG seed for reproducibility")
    args = parser.parse_args()

    seeds = [(args.seed + i if args.seed is not None else None) for i in range(args.runs)]
    results = [simulate_run(s) for s in seeds]
    analyze(results)


if __name__ == "__main__":
    main()
