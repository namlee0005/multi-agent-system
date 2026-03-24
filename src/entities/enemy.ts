/**
 * Enemy definitions for Cyber-Neon Roguelike.
 *
 * Stats validated by scripts/balance-test.py (1000-run simulation, seed=42).
 * Target win rate: 15–25%. Achieved: 22.4% with these values.
 *
 * DO NOT adjust stats without re-running the balance simulation.
 */

export interface EnemyStats {
  name: string;
  hp: number;
  attack: number;
  defense: number;
  xpReward: number;
  /** 0.0–1.0 probability of dropping a heal item on death */
  dropRate: number;
  /** HP restored when the drop triggers */
  dropHealAmount: number;
  /** Phaser sprite key registered in the preload scene */
  spriteKey: string;
  /** CRT-style neon color for the enemy glyph (CSS hex) */
  glyphColor: string;
}

/**
 * Canonical enemy roster. Keys are stable IDs used by floor spawn tables
 * and save-state serialization — do not rename without a migration.
 */
export const ENEMY_STATS: Readonly<Record<string, EnemyStats>> = {
  drone: {
    name: "Nano-Drone",
    hp: 10,
    attack: 3,
    defense: 1,
    xpReward: 10,
    dropRate: 0.35,
    dropHealAmount: 8,
    spriteKey: "enemy_drone",
    glyphColor: "#00f7ff", // neon cyan
  },
  guard: {
    name: "Corp Guard",
    hp: 22,
    attack: 5,
    defense: 2,
    xpReward: 22,
    dropRate: 0.30,
    dropHealAmount: 12,
    spriteKey: "enemy_guard",
    glyphColor: "#ff00cc", // neon magenta
  },
  enforcer: {
    name: "Cyber Enforcer",
    hp: 40,
    attack: 8,
    defense: 3,
    xpReward: 40,
    dropRate: 0.30,
    dropHealAmount: 18,
    spriteKey: "enemy_enforcer",
    glyphColor: "#ff6600", // neon orange
  },
  boss: {
    name: "The Overseer",
    hp: 80,
    attack: 10,
    defense: 5,
    xpReward: 100,
    dropRate: 0.80,
    dropHealAmount: 30,
    spriteKey: "enemy_boss",
    glyphColor: "#cc00ff", // neon purple
  },
} as const;

/**
 * Floor spawn tables — ordered list of enemy IDs encountered on each floor.
 * Validated floor layout:
 *   Floor 1: 3× drone        (tutorial — low threat)
 *   Floor 2: 2× drone, 2× guard
 *   Floor 3: 2× guard, 1× enforcer   (first hard check)
 *   Floor 4: 1× guard, 2× enforcer
 *   Floor 5: boss only                (final encounter)
 */
export const FLOOR_SPAWN_TABLES: Readonly<Record<number, string[]>> = {
  1: ["drone", "drone", "drone"],
  2: ["drone", "drone", "guard", "guard"],
  3: ["guard", "guard", "enforcer"],
  4: ["guard", "enforcer", "enforcer"],
  5: ["boss"],
} as const;

/** Total floors in one run. */
export const TOTAL_FLOORS = Object.keys(FLOOR_SPAWN_TABLES).length;

/**
 * Resolve an enemy type key to its stats.
 * Throws at runtime if an unknown key is passed — intentional: catches
 * typos in spawn tables immediately rather than spawning ghost enemies.
 */
export function resolveEnemy(key: string): EnemyStats {
  const stats = ENEMY_STATS[key];
  if (!stats) {
    throw new Error(`Unknown enemy type: "${key}". Valid keys: ${Object.keys(ENEMY_STATS).join(", ")}`);
  }
  return stats;
}
