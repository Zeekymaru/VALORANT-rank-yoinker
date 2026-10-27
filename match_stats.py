"""Per-match performance counts for one player, read from a match-details payload we already fetched.

No network and no I/O here: history.py hands in the payload, profile.py turns the counts into rates.
Every field read here was checked against the cached payloads of live matches; the checks are in
tests/test_match_stats.py. A field that is missing makes that count None rather than 0 so the
profile can tell "not recorded" from "none".
"""

TRADE_WINDOW_MS = 5000  # a death is "traded" if a teammate kills the killer within this long

# TODO(verify): field names below match live payloads from 2026-10 (1170 player rows checked: derived kills equal
# stats.kills once teamkills are excluded); re-check if Riot changes the match-details schema.
STATS_FIELD = "stats"
ROUNDS_FIELD = "roundResults"
ROUND_STATS_FIELD = "playerStats"
KILLS_FIELD = "kills"
DAMAGE_FIELD = "damage"
ROUND_PLANTER_FIELD = "bombPlanter"
ROUND_DEFUSER_FIELD = "bombDefuser"
CAST_FIELD = "abilityCasts"

COUNT_KEYS = ("rounds", "score", "kills", "deaths", "assists", "damage", "headshots", "bodyshots", "legshots",
              "first_bloods", "first_deaths", "kast_rounds", "casts", "plants", "defuses")


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _casts(stats):
    casts = stats.get(CAST_FIELD)
    if not isinstance(casts, dict):
        return None
    values = [_number(v) for v in casts.values()]
    return sum(v for v in values if v is not None) if any(v is not None for v in values) else None


def _dicts(items):
    return [x for x in items or [] if isinstance(x, dict)]


def _round_kills(rnd):
    """Every kill in the round as (time_ms, killer, victim, assistants), oldest first."""
    kills = []
    for entry in _dicts(rnd.get(ROUND_STATS_FIELD)):
        for kill in _dicts(entry.get(KILLS_FIELD)):
            kills.append((_number(kill.get("roundTime")) or 0, kill.get("killer"), kill.get("victim"),
                          [a for a in kill.get("assistants") or [] if isinstance(a, str)]))
    return sorted(kills, key=lambda k: k[0])


def player_match_stats(puuid, details, team_of):
    """Counts for puuid in one match, or None when the payload carries no per-round data for them.

    team_of maps subject -> teamId for the match's players (the caller already built it).
    """
    if not isinstance(details, dict):
        return None
    me = puuid.lower()
    players = {str(p.get("subject", "")).lower(): p for p in _dicts(details.get("players"))}
    mine = players.get(me)
    if mine is None or not isinstance(mine.get(STATS_FIELD), dict):
        return None
    rounds = _dicts(details.get(ROUNDS_FIELD))
    if not rounds:
        return None
    stats = mine[STATS_FIELD]
    my_team = team_of.get(me)

    def enemy(subject):
        team = team_of.get(str(subject).lower())
        return team is not None and team != my_team

    out = {"rounds": _number(stats.get("roundsPlayed")) or len(rounds), "score": _number(stats.get("score")),
           "kills": _number(stats.get("kills")), "deaths": _number(stats.get("deaths")),
           "assists": _number(stats.get("assists")), "casts": _casts(stats),
           "damage": 0, "headshots": 0, "bodyshots": 0, "legshots": 0,
           "first_bloods": 0, "first_deaths": 0, "kast_rounds": 0, "plants": 0, "defuses": 0}

    for rnd in rounds:
        kills = [(t, str(k).lower(), str(v).lower(), [a.lower() for a in assists])
                 for t, k, v, assists in _round_kills(rnd)]
        # Round-level damage dealt by me, enemies only.
        for entry in _dicts(rnd.get(ROUND_STATS_FIELD)):
            if str(entry.get("subject", "")).lower() != me:
                continue
            for hit in _dicts(entry.get(DAMAGE_FIELD)):
                if enemy(hit.get("receiver")):
                    out["damage"] += _number(hit.get("damage")) or 0
                    out["headshots"] += _number(hit.get("headshots")) or 0
                    out["bodyshots"] += _number(hit.get("bodyshots")) or 0
                    out["legshots"] += _number(hit.get("legshots")) or 0

        real = [k for k in kills if enemy(k[2]) != enemy(k[1])]  # drop teamkills and suicides
        if real:
            first = real[0]
            out["first_bloods"] += int(first[1] == me)
            out["first_deaths"] += int(first[2] == me)

        got_kill = any(k[1] == me and enemy(k[2]) for k in real)
        got_assist = any(me in k[3] for k in real)
        death = next((k for k in kills if k[2] == me), None)
        survived = death is None
        traded = False
        if death is not None:
            traded = any(k[2] == death[1] and k[0] - death[0] <= TRADE_WINDOW_MS and k[0] >= death[0]
                         and team_of.get(k[1]) == my_team and k[1] != me for k in real)
        out["kast_rounds"] += int(got_kill or got_assist or survived or traded)

        out["plants"] += int(str(rnd.get(ROUND_PLANTER_FIELD, "")).lower() == me)
        out["defuses"] += int(str(rnd.get(ROUND_DEFUSER_FIELD, "")).lower() == me)
    return out


def total(per_match):
    """Sum each count over the matches that recorded it (None entries skipped); None if no match did.

    Also carries "games" (matches with stats) so rates can say how much data stands behind them.
    """
    usable = [m for m in per_match if isinstance(m, dict)]
    if not usable:
        return None
    out = {"games": len(usable)}
    for key in COUNT_KEYS:
        values = [m[key] for m in usable if m.get(key) is not None]
        out[key] = sum(values) if values else None
    return out
