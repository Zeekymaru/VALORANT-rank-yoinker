"""Moneyball-style checks on the cached match details: which stats are signal, which are noise, and what wins rounds.

Standard library only, no network (weapon names are the fixed table in weapons.py, from valorant-api.com). Run from the repo
root:  python tools/moneyball.py [--cache cache] [--out report.md]

What the cache can and cannot support: it holds ~560 competitive matches but almost every player appears once, so
"does a player's earlier form predict a later game" cannot be tested (most players have no earlier cached game).
Within a game it can be, so this script runs:

  1. Halftime test. Per match, each team's first-half stats (rounds 0-11) against how that team did in the second
     half (rounds 12-23). A stat that predicts the second half is carrying something stable (skill, comp, map read);
     one that only describes the first half is just a restatement of the score so far. "Beyond score" is the partial
     correlation after removing the first-half score gap, i.e. what the stat adds that the scoreboard didn't.
  2. Repeatability. Each player's first-half value of a stat against their own second-half value: the stat's
     split-half correlation (r) and its full-game reliability (Spearman-Brown, 2r / (1 + r)).
  3. Round-level facts: first blood, pistol rounds, economy, weapons.

Caveats printed with the report: ~560 matches means only large effects are visible, sides swap at halftime (attack
vs defense differs by map), and the matches are the ones from lobbies this app has seen, not a random sample.
"""
import argparse
import json
import math
import os
import random
import sys
from collections import Counter, defaultdict
from statistics import mean, pstdev

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import match_stats  # noqa: E402
from weapons import WEAPONS  # noqa: E402

HALF = 12  # rounds per half; overtime (24+) is left out of every half-based number
MIN_H2_ROUNDS = 4
MIN_HALF_ROUNDS = 8  # a player-half needs this many rounds to count in the repeatability table
BOOTSTRAPS = 300



def load_matches(cache_dir):
    matches = []
    folder = os.path.join(cache_dir, "matches")
    for name in sorted(os.listdir(folder)):
        try:
            with open(os.path.join(folder, name), encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            continue
        info = data.get("matchInfo") if isinstance(data, dict) else None
        if isinstance(info, dict) and info.get("queueID") == "competitive" and info.get("isCompleted")                 and data.get("roundResults") and len(data.get("players") or []) == 10:
            matches.append(data)
    return matches


def _enemy(team_of, me, other):
    a, b = team_of.get(me), team_of.get(other)
    return a is not None and b is not None and a != b


_ROUNDS = {}


def rounds_of(details):
    """[{num, winner, winner_role, rows: {subject: per-round numbers}}] for the rounds that were actually played."""
    key = details["matchInfo"]["matchId"]
    if key not in _ROUNDS:
        _ROUNDS[key] = _rounds_of(details)
    return _ROUNDS[key]


def _rounds_of(details):
    team_of = {str(p["subject"]).lower(): p.get("teamId") for p in details["players"]}
    out = []
    for rnd in details["roundResults"]:
        if not rnd.get("winningTeam") or rnd.get("roundResultCode") in ("", "Surrendered", None):
            continue
        kills = [(t, str(k).lower(), str(v).lower(), [a.lower() for a in assists])
                 for t, k, v, assists in match_stats._round_kills(rnd)]
        real = [k for k in kills if _enemy(team_of, k[1], k[2])]
        first = real[0] if real else None
        rows = {}
        for entry in rnd.get("playerStats") or []:
            me = str(entry.get("subject", "")).lower()
            if me not in team_of:
                continue
            row = {"team": team_of[me], "kills": 0, "deaths": 0, "assists": 0, "dmg": 0, "hs": 0, "bs": 0, "ls": 0,
                   "score": entry.get("score") or 0, "fb": 0, "fd": 0, "kast": 0, "plant": 0, "defuse": 0}
            for hit in entry.get("damage") or []:
                if _enemy(team_of, me, str(hit.get("receiver", "")).lower()):
                    row["dmg"] += hit.get("damage") or 0
                    row["hs"] += hit.get("headshots") or 0
                    row["bs"] += hit.get("bodyshots") or 0
                    row["ls"] += hit.get("legshots") or 0
            row["kills"] = sum(1 for k in real if k[1] == me)
            row["assists"] = sum(1 for k in real if me in k[3])
            death = next((k for k in kills if k[2] == me), None)
            row["deaths"] = int(death is not None)
            if first:
                row["fb"], row["fd"] = int(first[1] == me), int(first[2] == me)
            traded = death is not None and any(
                k[2] == death[1] and 0 <= k[0] - death[0] <= match_stats.TRADE_WINDOW_MS
                and team_of.get(k[1]) == team_of[me] and k[1] != me for k in real)
            row["kast"] = int(row["kills"] > 0 or row["assists"] > 0 or death is None or traded)
            row["plant"] = int(str(rnd.get("bombPlanter", "")).lower() == me)
            row["defuse"] = int(str(rnd.get("bombDefuser", "")).lower() == me)
            economy = entry.get("economy") or {}
            row["loadout"], row["weapon"] = economy.get("loadoutValue") or 0, str(economy.get("weapon") or "").lower()
            rows[me] = row
        winner_role = rnd.get("winningTeamRole")
        out.append({"num": rnd.get("roundNum"), "winner": rnd["winningTeam"], "winner_role": winner_role,
                    "rows": rows, "first_team": team_of.get(first[1]) if first else None,
                    "kills": [(k[1], (kk.get("finishingDamage") or {})) for k, kk in zip(kills, _raw_kills(rnd))]})
    return out


def role_of(rnd, team):
    """The side `team` played in this round, from who won it and the side the winner was on."""
    if rnd["winner_role"] not in ("Attacker", "Defender"):
        return None
    if rnd["winner"] == team:
        return rnd["winner_role"]
    return "Defender" if rnd["winner_role"] == "Attacker" else "Attacker"


def attack_win_rates(matches):
    """{map id: share of rounds the attackers won}, over every cached round on that map."""
    won, played = Counter(), Counter()
    for details in matches:
        map_id = details["matchInfo"].get("mapId")
        for r in rounds_of(details):
            if r["winner_role"] in ("Attacker", "Defender"):
                played[map_id] += 1
                won[map_id] += int(r["winner_role"] == "Attacker")
    return {m: won[m] / played[m] for m in played}


def _raw_kills(rnd):
    """The raw kill dicts in the same order match_stats._round_kills sorts them."""
    raw = [k for e in rnd.get("playerStats") or [] for k in e.get("kills") or [] if isinstance(k, dict)]
    return sorted(raw, key=lambda k: k.get("roundTime") or 0)


# --- statistics (stdlib) ------------------------------------------------------------------

def pearson(xs, ys):
    if len(xs) < 3:
        return None
    mx, my = mean(xs), mean(ys)
    sx, sy = math.sqrt(sum((x - mx) ** 2 for x in xs)), math.sqrt(sum((y - my) ** 2 for y in ys))
    if not sx or not sy:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def stripper(controls):
    """A function that removes what a vector shares with every control (a list of vectors), built once per set.

    Gram-Schmidt on centred copies of the controls; the controls are the same for every stat, so a bootstrap builds
    this once per resample instead of once per stat."""
    basis = []
    for control in controls:
        c = [v - mean(control) for v in control]
        for vec, norm in basis:
            k = sum(x * y for x, y in zip(c, vec)) / norm if norm else 0.0
            c = [x - k * y for x, y in zip(c, vec)]
        basis.append((c, sum(v * v for v in c)))

    def strip(values):
        out = [v - mean(values) for v in values]
        for vec, norm in basis:
            k = sum(x * y for x, y in zip(out, vec)) / norm if norm else 0.0
            out = [x - k * y for x, y in zip(out, vec)]
        return out
    return strip


def auc(scores, labels):
    """P(a random positive outranks a random negative); ties count half. labels are booleans."""
    pos = [s for s, l in zip(scores, labels) if l]
    neg = [s for s, l in zip(scores, labels) if not l]
    if not pos or not neg:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def fmt(value, spec="+.2f"):
    return "—" if value is None else format(value, spec)


def interval(low, high):
    return "" if low is None else f" [{low:+.2f}, {high:+.2f}]"


# --- 1. halftime test ---------------------------------------------------------------------

def team_features(rows_by_player, rounds, ranks):
    """Team-level first-half numbers from {subject: [per-round rows]} for one team."""
    totals = {k: sum(r[k] for rows in rows_by_player.values() for r in rows)
              for k in ("kills", "deaths", "assists", "dmg", "hs", "bs", "ls", "score", "fb", "fd", "kast", "plant", "defuse")}
    n = len(rows_by_player)
    per_player_acs = [sum(r["score"] for r in rows) / len(rows) for rows in rows_by_player.values() if rows]
    shots = totals["hs"] + totals["bs"] + totals["ls"]
    return {
        "K/D": totals["kills"] / max(totals["deaths"], 1),
        "ADR": totals["dmg"] / (n * rounds),
        "ACS": totals["score"] / (n * rounds),
        "KAST": totals["kast"] / (n * rounds),
        "Headshot %": totals["hs"] / shots if shots else None,
        "First bloods per round": totals["fb"] / rounds,
        "Entry (FB - FD) per round": (totals["fb"] - totals["fd"]) / rounds,
        "Assists per round": totals["assists"] / (n * rounds),
        "Plants + defuses per round": (totals["plant"] + totals["defuse"]) / rounds,
        "Best player's ACS (star)": max(per_player_acs),
        "Weakest player's ACS (weak link)": min(per_player_acs),
        "ACS spread (std dev)": pstdev(per_player_acs),
        "Average rank tier (pre-game)": mean(ranks) if ranks else None,
    }


def halftime_table(matches, rng):
    samples = []
    attack_rate = attack_win_rates(matches)
    for details in matches:
        rounds = [r for r in rounds_of(details) if r["num"] is not None and r["num"] < 2 * HALF]
        h1, h2 = [r for r in rounds if r["num"] < HALF], [r for r in rounds if r["num"] >= HALF]
        teams = sorted({p["teamId"] for p in details["players"]})
        if len(teams) != 2 or len(h1) < HALF or len(h2) < MIN_H2_ROUNDS:
            continue
        a, b = teams
        feats, ranks = {}, {t: [p["competitiveTier"] for p in details["players"]
                                if p["teamId"] == t and isinstance(p.get("competitiveTier"), int) and p["competitiveTier"] > 0]
                            for t in teams}
        for team in teams:
            by_player = defaultdict(list)
            for r in h1:
                for subject, row in r["rows"].items():
                    if row["team"] == team:
                        by_player[subject].append(row)
            if len(by_player) != 5:
                break
            feats[team] = team_features(by_player, len(h1), ranks[team])
        else:
            wins = lambda rs, t: sum(1 for r in rs if r["winner"] == t)  # noqa: E731
            h2_role = "Defender" if role_of(h1[0], a) == "Attacker" else "Attacker"  # a swaps sides at half time
            edge = 2 * attack_rate.get(details["matchInfo"].get("mapId"), 0.5) - 1  # how much the map favours attackers
            samples.append({
                "side": edge if h2_role == "Attacker" else -edge,  # side's expected edge for a in the second half
                "feat": {k: (None if feats[a][k] is None or feats[b][k] is None else feats[a][k] - feats[b][k])
                         for k in feats[a]},
                "h1_score": (wins(h1, a) - wins(h1, b)) / len(h1),
                "h2": (wins(h2, a) - wins(h2, b)) / len(h2),
            })
    samples = [s for s in samples if all(v is not None for v in s["feat"].values())]
    names = list(samples[0]["feat"]) if samples else []
    n = len(samples)
    cols = {name: [s["feat"][name] for s in samples] for name in names}
    y, score, side = [s["h2"] for s in samples], [s["h1_score"] for s in samples], [s["side"] for s in samples]
    strip = stripper([score, side])
    y_clean, clean = strip(y), {name: strip(col) for name, col in cols.items()}
    boot = {name: ([], []) for name in names}  # per stat: resampled r and resampled partial r
    for _ in range(BOOTSTRAPS):
        idx = [rng.randrange(n) for _ in range(n)]
        pick = lambda v: [v[i] for i in idx]  # noqa: E731
        resample_strip = stripper([pick(score), pick(side)])
        y_b, y_strip = pick(y), resample_strip(pick(y))
        for name in names:
            boot[name][0].append(pearson(pick(cols[name]), y_b))
            boot[name][1].append(pearson(resample_strip(pick(cols[name])), y_strip))

    def interval_of(values):
        values = sorted(v for v in values if v is not None)
        return (values[int(0.025 * len(values))], values[int(0.975 * len(values)) - 1]) if len(values) > 40 else (None, None)

    rows = []
    for name in names:
        decided = [(x, v > 0) for x, v in zip(cols[name], y) if v != 0]
        rows.append({"name": name, "n": n, "describes": pearson(cols[name], score), "predicts": pearson(cols[name], y),
                     "ci": interval_of(boot[name][0]), "auc": auc([d[0] for d in decided], [d[1] for d in decided]),
                     "beyond": pearson(clean[name], y_clean), "beyond_ci": interval_of(boot[name][1])})
    baseline = pearson([s["h1_score"] for s in samples], [s["h2"] for s in samples])
    side_only = pearson([s["side"] for s in samples], [s["h2"] for s in samples])
    return rows, baseline, side_only, len(samples)


# --- 2. repeatability ---------------------------------------------------------------------

def player_stats(rows):
    n = len(rows)
    shots = sum(r["hs"] + r["bs"] + r["ls"] for r in rows)
    return {
        "Kills per round": sum(r["kills"] for r in rows) / n,
        "Deaths per round": sum(r["deaths"] for r in rows) / n,
        "K/D": sum(r["kills"] for r in rows) / max(sum(r["deaths"] for r in rows), 1),
        "ADR": sum(r["dmg"] for r in rows) / n,
        "ACS": sum(r["score"] for r in rows) / n,
        "KAST": sum(r["kast"] for r in rows) / n,
        "Headshot %": sum(r["hs"] for r in rows) / shots if shots >= 15 else None,
        "First bloods per round": sum(r["fb"] for r in rows) / n,
        "First deaths per round": sum(r["fd"] for r in rows) / n,
        "Assists per round": sum(r["assists"] for r in rows) / n,
    }


def repeatability(matches):
    """Per stat: split-half r across the lobby ("raw") and with each player measured against their own teammates.

    Raw correlations are dragged around by team-level swings (a team that survives a lot in one half often doesn't in
    the other), which can even turn the sign negative for survival stats. The within-team version takes the team's
    average for that half off each player first, so it asks "does the better player on this team in the first half stay
    the better player in the second?". Taking each side's average off (attack/defence, or per map) changed nothing."""
    pairs = defaultdict(list)
    for details in matches:
        rounds = [r for r in rounds_of(details) if r["num"] is not None and r["num"] < 2 * HALF]
        halves = ([r for r in rounds if r["num"] < HALF], [r for r in rounds if r["num"] >= HALF])
        if min(len(h) for h in halves) < MIN_HALF_ROUNDS:
            continue
        by_team = defaultdict(lambda: defaultdict(list))
        for subject in details["players"]:
            who = str(subject["subject"]).lower()
            got = [[r["rows"][who] for r in h if who in r["rows"]] for h in halves]
            if min(len(g) for g in got) < MIN_HALF_ROUNDS:
                continue
            a, b = player_stats(got[0]), player_stats(got[1])
            for key in a:
                if a[key] is not None and b[key] is not None:
                    by_team[key][subject["teamId"]].append((a[key], b[key]))
        for key, teams in by_team.items():
            for items in teams.values():
                if len(items) < 3:
                    continue
                m1, m2 = mean(i[0] for i in items), mean(i[1] for i in items)
                pairs[key] += [(first, second, first - m1, second - m2) for first, second in items]
    out = []
    for key, items in pairs.items():
        raw = pearson([i[0] for i in items], [i[1] for i in items])
        within = pearson([i[2] for i in items], [i[3] for i in items])
        out.append({"name": key, "n": len(items), "raw": raw, "within": within,
                    "full": None if within is None else 2 * within / (1 + within)})
    return sorted(out, key=lambda x: -(x["within"] if x["within"] is not None else -1))


# --- 3. round-level facts -----------------------------------------------------------------

def round_facts(matches):
    fb = {"all": [0, 0], "Attacker": [0, 0], "Defender": [0, 0]}  # [rounds won by the first-blood team, rounds]
    pistol = {"after": [0, 0], "no": [0, 0]}  # won / played the round after a pistol, by whether that pistol was won
    pistol_match = defaultdict(lambda: [0, 0])  # pistols won (0-2) -> [matches won, matches]
    econ = defaultdict(lambda: [0, 0])
    weapon_kills, weapon_rounds, other_kills = Counter(), Counter(), Counter()
    for details in matches:
        rounds = rounds_of(details)
        by_num = {r["num"]: r for r in rounds}
        won_match = {t["teamId"]: t["won"] for t in details["teams"] if isinstance(t.get("won"), bool)}
        for r in rounds:
            role_of = {r["winner"]: r["winner_role"]}
            other = next((t for t in {p["teamId"] for p in details["players"]} if t != r["winner"]), None)
            if r["winner_role"] in ("Attacker", "Defender") and other:
                role_of[other] = "Defender" if r["winner_role"] == "Attacker" else "Attacker"
            if r["first_team"]:
                for key in ("all", role_of.get(r["first_team"])):
                    if key in fb:
                        fb[key][0] += int(r["first_team"] == r["winner"])
                        fb[key][1] += 1
            for subject, k in r["kills"]:
                item = k.get("damageItem")
                if k.get("damageType") == "Weapon" and item:
                    weapon_kills[str(item).lower()] += 1
                else:
                    other_kills[k.get("damageType") or "Other"] += 1
            for row in r["rows"].values():
                if row["weapon"]:
                    weapon_rounds[row["weapon"]] += 1
            num = r["num"]
            if num is not None and 0 < num < 2 * HALF and num not in (HALF,):  # a normal buy round, not a pistol
                totals = defaultdict(int)
                for row in r["rows"].values():
                    totals[row["team"]] += row["loadout"]
                if len(totals) == 2 and sum(totals.values()):
                    for team, value in totals.items():
                        share = value / sum(totals.values())
                        bucket = min(int(share * 10), 9) if share < 1 else 9
                        econ[bucket][0] += int(r["winner"] == team)
                        econ[bucket][1] += 1
        for pistol_round, next_round in ((0, 1), (HALF, HALF + 1)):
            p, nxt = by_num.get(pistol_round), by_num.get(next_round)
            if p and nxt:
                pistol["after"][0] += int(nxt["winner"] == p["winner"])
                pistol["after"][1] += 1
        r0, r12 = by_num.get(0), by_num.get(HALF)
        if r0 and r12 and won_match:
            for team in won_match:
                wins = int(r0["winner"] == team) + int(r12["winner"] == team)
                pistol_match[wins][0] += int(won_match[team])
                pistol_match[wins][1] += 1
    return fb, pistol, pistol_match, econ, weapon_kills, weapon_rounds, other_kills


def pct(pair):
    return "—" if not pair[1] else f"{100 * pair[0] / pair[1]:.1f}%"


# --- report -------------------------------------------------------------------------------

def report(matches, seed=7):
    rng = random.Random(seed)
    lines = [f"# Moneyball check on {len(matches)} cached competitive matches", ""]
    rows, baseline, side_only, n = halftime_table(matches, rng)
    lines += [
        f"## 1. Halftime test ({n} matches)", "",
        "Team first-half stat gap (Blue minus Red) against the second half's round-win gap. "
        f"For reference, the first-half **score** gap alone correlates **{baseline:+.2f}** with the second half, and the "
        f"map's side advantage alone (who defends what) **{side_only:+.2f}**.", "",
        "| Stat | Describes H1 (r with H1 score) | Predicts H2 (r) [95% CI] | AUC | Adds beyond score and side (partial r) [95% CI] |",
        "|---|---|---|---|---|"]
    for row in sorted(rows, key=lambda r: -(r["predicts"] or -1)):
        lines.append(f"| {row['name']} | {fmt(row['describes'])} | {fmt(row['predicts'])}{interval(*row['ci'])} | "
                     f"{fmt(row['auc'], '.2f')} | {fmt(row['beyond'])}{interval(*row['beyond_ci'])} |")
    lines += ["", "Read it as: a big number in the first column and a small one in the second means the stat mostly "
              "restates the scoreboard. A stat is Moneyball-useful if it predicts the second half and keeps a "
              "partial r whose interval stays clear of zero. Thirteen stats are tested at once and several overlap "
              "heavily (ACS, ADR and K/D mostly measure the same thing), so one lone borderline interval is weak evidence.", ""]
    lines += ["## 2. Repeatability: the same player, first half vs second half", "",
              "| Stat | Player-halves | Split-half r, whole lobby | Split-half r, within own team | "
              "Full-game reliability (within team) |", "|---|---|---|---|---|"]
    for row in repeatability(matches):
        lines.append(f"| {row['name']} | {row['n']} | {fmt(row['raw'], '.2f')} | {fmt(row['within'], '.2f')} | "
                     f"{fmt(row['full'], '.2f')} |")
    lines += ["", "Higher means the stat is more a property of the player and less of the half they happened to have. "
              "The whole-lobby column mixes in team-level swings (which is why survival stats can go negative there); the within-team column asks whether the better player on a team in the first half stays the better one in the second.", ""]
    fb, pistol, pistol_match, econ, weapon_kills, weapon_rounds, other_kills = round_facts(matches)
    lines += ["## 3. Round-level facts", "", "### First blood", "",
              "| Situation | Rounds | Team with the first kill wins the round |", "|---|---|---|"]
    for key, label in (("all", "All rounds"), ("Attacker", "First blood by the attackers"),
                       ("Defender", "First blood by the defenders")):
        lines.append(f"| {label} | {fb[key][1]} | {pct(fb[key])} |")
    lines += ["", "### Pistol rounds", "", f"Winning a pistol round and then the next round (the bonus round): "
              f"{pct(pistol['after'])} of {pistol['after'][1]}.", "",
              "| Pistol rounds won (of 2) | Matches (per team) | Won the match |", "|---|---|---|"]
    for wins in sorted(pistol_match):
        lines.append(f"| {wins} | {pistol_match[wins][1]} | {pct(pistol_match[wins])} |")
    lines += ["", "### Economy", "", "Team's share of the combined loadout value at round start (pistol rounds and "
              "overtime left out), against winning the round.", "", "| Loadout share | Rounds | Won the round |", "|---|---|---|"]
    for bucket in sorted(econ):
        lines.append(f"| {bucket * 10}-{bucket * 10 + 10}% | {econ[bucket][1]} | {pct(econ[bucket])} |")
    lines += ["", "### Weapons", "", "Kills by weapon, and kills per 100 rounds that started with it in hand. The two "
              "counts differ when someone picks a gun up mid-round, so read the rate as rough.", "",
              "| Weapon | Kills | Share of weapon kills | Rounds started with it | Kills per 100 of those rounds |",
              "|---|---|---|---|---|"]
    total = sum(weapon_kills.values())
    for uuid, kills in weapon_kills.most_common(12):
        held = weapon_rounds.get(uuid, 0)
        rate = f"{100 * kills / held:.0f}" if held >= 200 else "—"
        lines.append(f"| {WEAPONS.get(uuid, 'unlisted id ' + uuid[:8])} | {kills} | {100 * kills / total:.1f}% | {held} | {rate} |")
    if other_kills:
        lines.append("")
        lines.append("Kills not made with a gun: " + ", ".join(f"{'weapon without an id' if k == 'Weapon' else k} {v}" for k, v in other_kills.most_common()) + ".")
    lines += ["", "## Caveats", "",
              "- About 560 matches: only large effects are visible. Differences smaller than the intervals are noise.",
              "- Sides swap at halftime and the map favours one side: the partial correlations control for both the first-half score and the map's side edge, which is a rough adjustment, not a full model.",
              "- The matches come from lobbies this app has seen, not a random sample of ranked games, and most of the "
              "players are Gold to Ascendant.",
              "- Nothing here tests whether earlier games predict a later one for the same player: the cache has no "
              "player with enough earlier games.", ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--cache", default="cache")
    parser.add_argument("--out", help="also write the report to this file")
    args = parser.parse_args(argv)
    matches = load_matches(args.cache)
    if not matches:
        sys.exit(f"No competitive matches found under {args.cache}/matches")
    text = report(matches)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")


if __name__ == "__main__":
    main()
