# Moneyball check on 566 cached competitive matches

## 1. Halftime test (491 matches)

Team first-half stat gap (Blue minus Red) against the second half's round-win gap. For reference, the first-half **score** gap alone correlates **+0.17** with the second half, and the map's side advantage alone (who defends what) **+0.04**.

| Stat | Describes H1 (r with H1 score) | Predicts H2 (r) [95% CI] | AUC | Adds beyond score and side (partial r) [95% CI] |
|---|---|---|---|---|
| ACS | +0.88 | +0.21 [+0.11, +0.29] | 0.57 | +0.12 [+0.04, +0.19] |
| ADR | +0.86 | +0.20 [+0.12, +0.29] | 0.57 | +0.12 [+0.04, +0.20] |
| K/D | +0.92 | +0.19 [+0.09, +0.28] | 0.57 | +0.08 [-0.01, +0.17] |
| Assists per round | +0.53 | +0.18 [+0.10, +0.27] | 0.57 | +0.11 [+0.02, +0.19] |
| Plants + defuses per round | +0.94 | +0.17 [+0.07, +0.26] | 0.57 | +0.03 [-0.06, +0.11] |
| Best player's ACS (star) | +0.57 | +0.16 [+0.07, +0.25] | 0.57 | +0.08 [-0.01, +0.17] |
| KAST | +0.82 | +0.16 [+0.07, +0.25] | 0.55 | +0.04 [-0.06, +0.12] |
| Entry (FB - FD) per round | +0.51 | +0.14 [+0.06, +0.22] | 0.55 | +0.07 [-0.02, +0.15] |
| First bloods per round | +0.51 | +0.14 [+0.06, +0.22] | 0.55 | +0.07 [-0.02, +0.15] |
| Headshot % | +0.18 | +0.11 [+0.01, +0.19] | 0.54 | +0.08 [-0.01, +0.17] |
| ACS spread (std dev) | +0.26 | +0.10 [+0.01, +0.19] | 0.55 | +0.06 [-0.04, +0.15] |
| Weakest player's ACS (weak link) | +0.48 | +0.09 [-0.01, +0.18] | 0.51 | +0.01 [-0.09, +0.10] |
| Average rank tier (pre-game) | +0.05 | -0.05 [-0.13, +0.03] | 0.46 | -0.05 [-0.14, +0.02] |

Read it as: a big number in the first column and a small one in the second means the stat mostly restates the scoreboard. A stat is Moneyball-useful if it predicts the second half and keeps a partial r whose interval stays clear of zero. Thirteen stats are tested at once and several overlap heavily (ACS, ADR and K/D mostly measure the same thing), so one lone borderline interval is weak evidence.

## 2. Repeatability: the same player, first half vs second half

| Stat | Player-halves | Split-half r, whole lobby | Split-half r, within own team | Full-game reliability (within team) |
|---|---|---|---|---|
| Headshot % | 2633 | 0.42 | 0.33 | 0.50 |
| ADR | 3770 | 0.22 | 0.25 | 0.40 |
| ACS | 3770 | 0.21 | 0.24 | 0.39 |
| Kills per round | 3770 | 0.16 | 0.22 | 0.36 |
| Assists per round | 3770 | 0.19 | 0.22 | 0.35 |
| First bloods per round | 3770 | 0.16 | 0.18 | 0.31 |
| Deaths per round | 3770 | -0.08 | 0.15 | 0.27 |
| K/D | 3770 | 0.03 | 0.15 | 0.26 |
| First deaths per round | 3770 | 0.13 | 0.15 | 0.26 |
| KAST | 3770 | -0.05 | 0.08 | 0.15 |

Higher means the stat is more a property of the player and less of the half they happened to have. The whole-lobby column mixes in team-level swings (which is why survival stats can go negative there); the within-team column asks whether the better player on a team in the first half stays the better one in the second.

## 3. Round-level facts

### First blood

| Situation | Rounds | Team with the first kill wins the round |
|---|---|---|
| All rounds | 11851 | 68.5% |
| First blood by the attackers | 5753 | 69.9% |
| First blood by the defenders | 6098 | 67.3% |

### Pistol rounds

Winning a pistol round and then the next round (the bonus round): 80.9% of 1111.

| Pistol rounds won (of 2) | Matches (per team) | Won the match |
|---|---|---|
| 0 | 303 | 27.1% |
| 1 | 504 | 48.8% |
| 2 | 303 | 71.6% |

### Economy

Team's share of the combined loadout value at round start (pistol rounds and overtime left out), against winning the round.

| Loadout share | Rounds | Won the round |
|---|---|---|
| 0-10% | 67 | 11.9% |
| 10-20% | 509 | 15.1% |
| 20-30% | 881 | 19.3% |
| 30-40% | 1957 | 32.4% |
| 40-50% | 7046 | 45.0% |
| 50-60% | 7081 | 54.9% |
| 60-70% | 1969 | 67.5% |
| 70-80% | 878 | 80.8% |
| 80-90% | 513 | 84.8% |
| 90-100% | 67 | 88.1% |

### Weapons

Kills by weapon, and kills per 100 rounds that started with it in hand. The two counts differ when someone picks a gun up mid-round, so read the rate as rough.

| Weapon | Kills | Share of weapon kills | Rounds started with it | Kills per 100 of those rounds |
|---|---|---|---|---|
| Vandal | 39050 | 45.4% | 46832 | 83 |
| Phantom | 15473 | 18.0% | 18551 | 83 |
| Ghost | 5098 | 5.9% | 6793 | 75 |
| Sheriff | 4303 | 5.0% | 8831 | 49 |
| Spectre | 3713 | 4.3% | 5729 | 65 |
| Classic | 3130 | 3.6% | 11330 | 28 |
| Operator | 2630 | 3.1% | 3268 | 80 |
| Guardian | 2435 | 2.8% | 3688 | 66 |
| unlisted id 856d9a7e | 1352 | 1.6% | 0 | — |
| Bulldog | 1276 | 1.5% | 1832 | 70 |
| Bandit | 1224 | 1.4% | 1988 | 62 |
| Odin | 1030 | 1.2% | 1208 | 85 |

Kills not made with a gun: Ability 1984, Bomb 371, Fall 167, weapon without an id 100, Melee 83, Crush 2.

## Caveats

- About 560 matches: only large effects are visible. Differences smaller than the intervals are noise.
- Sides swap at halftime and the map favours one side: the partial correlations control for both the first-half score and the map's side edge, which is a rough adjustment, not a full model.
- The matches come from lobbies this app has seen, not a random sample of ranked games, and most of the players are Gold to Ascendant.
- Nothing here tests whether earlier games predict a later one for the same player: the cache has no player with enough earlier games.

