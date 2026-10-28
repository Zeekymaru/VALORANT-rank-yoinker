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
ECONOMY_FIELD = "economy"

PISTOL_ROUNDS = (0, 12)  # roundNum of the first round of each half (rounds are numbered from 0)
# TODO(verify): buy bands are a rough reading of the team's average loadoutValue per player in non-pistol rounds
# (a full buy is a rifle plus shield, about 3900+); they are heuristics, not something Riot labels.
ECO_BELOW = 1500
FULL_FROM = 3500
BUY_TYPES = ("eco", "half", "full")

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


def _buy_type(loadouts):
    """eco / half / full from one team's loadout values in a round, or None when the round carries none."""
    values = [v for v in loadouts if v]
    if not values:
        return None
    average = sum(values) / len(values)
    return "eco" if average < ECO_BELOW else "full" if average >= FULL_FROM else "half"


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
           "first_bloods": 0, "first_deaths": 0, "kast_rounds": 0, "plants": 0, "defuses": 0,
           # weapon id -> [kills with it, rounds that started with it in hand]
           "guns": {},
           # the player's own pistol rounds: team rounds played/won, and the player's kills/deaths in them
           "pistol": {"rounds": 0, "won": 0, "kills": 0, "deaths": 0},
           # buy band -> team rounds played/won and the player's kills, outside pistol rounds
           "buys": {}}

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

        # Guns, pistol rounds and buys.
        won_round = rnd.get("winningTeam") == my_team and my_team is not None
        my_kills = sum(1 for k in real if k[1] == me and enemy(k[2]))
        for entry in _dicts(rnd.get(ROUND_STATS_FIELD)):
            subject = str(entry.get("subject", "")).lower()
            if subject == me:
                held = (entry.get(ECONOMY_FIELD) or {}).get("weapon")
                if isinstance(held, str) and held:
                    out["guns"].setdefault(held.lower(), [0, 0])[1] += 1
                for kill in _dicts(entry.get(KILLS_FIELD)):
                    finishing = kill.get("finishingDamage")
                    item = finishing.get("damageItem") if isinstance(finishing, dict) else None
                    if (isinstance(finishing, dict) and finishing.get("damageType") == "Weapon" and isinstance(item, str)
                            and item and str(kill.get("killer", "")).lower() == me and enemy(kill.get("victim"))):
                        out["guns"].setdefault(item.lower(), [0, 0])[0] += 1
        if rnd.get("roundNum") in PISTOL_ROUNDS:
            out["pistol"]["rounds"] += 1
            out["pistol"]["won"] += int(won_round)
            out["pistol"]["kills"] += my_kills
            out["pistol"]["deaths"] += int(death is not None)
        else:
            loadouts = [_number((e.get(ECONOMY_FIELD) or {}).get("loadoutValue")) for e in _dicts(rnd.get(ROUND_STATS_FIELD))
                        if team_of.get(str(e.get("subject", "")).lower()) == my_team]
            band = _buy_type(loadouts)
            if band:
                record = out["buys"].setdefault(band, {"rounds": 0, "won": 0, "kills": 0})
                record["rounds"] += 1
                record["won"] += int(won_round)
                record["kills"] += my_kills

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
    # nested counts: summaries cached before these existed lack them, so they stay None until a match has them
    with_guns = [m for m in usable if isinstance(m.get("guns"), dict)]
    out["guns"] = None
    if with_guns:
        out["guns"] = {}
        for m in with_guns:
            for weapon, (kills, held) in m["guns"].items():
                pair = out["guns"].setdefault(weapon, [0, 0])
                pair[0] += kills
                pair[1] += held
    with_pistol = [m["pistol"] for m in usable if isinstance(m.get("pistol"), dict)]
    out["pistol"] = {k: sum(p.get(k, 0) for p in with_pistol) for k in ("rounds", "won", "kills", "deaths")} if with_pistol else None
    with_buys = [m["buys"] for m in usable if isinstance(m.get("buys"), dict)]
    out["buys"] = None
    if with_buys:
        out["buys"] = {}
        for buys in with_buys:
            for band, record in buys.items():
                merged = out["buys"].setdefault(band, {"rounds": 0, "won": 0, "kills": 0})
                for k in merged:
                    merged[k] += record.get(k, 0)
    return out
