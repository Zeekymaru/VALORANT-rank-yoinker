"""Turn a player's summed match counts into rates, and place those rates on a lobby-relative radar.

Rates come from the "stats" block history.py adds to each summary (see match_stats.py). A radar axis is a
percentile among the players in this lobby, so the chart answers "who stands out here": 0.5 is the middle
of the lobby, and the same player can look different in another lobby. Nothing here touches the network.
"""
from statistics import mean, pstdev

MIN_GAMES_FOR_CONSISTENCY = 2
DIM_BELOW_GAMES = 3  # a profile built from fewer games than this is drawn dimmed

# axis label -> the rates averaged to place it
AXES = (
    ("Aim", ("adr", "hs")),
    ("Entry", ("entry",)),
    ("Survival", ("kast",)),
    ("Utility", ("util",)),
    ("Objective", ("objective",)),
    ("Consistency", ("consistency",)),
)


def _ratio(num, den):
    return None if num is None or not den else num / den


def derive(summary):
    """Rates for one summary, or None when it carries no performance counts (private, legacy cache, ...)."""
    if not isinstance(summary, dict) or not summary.get("available"):
        return None
    stats = summary.get("stats")
    if not isinstance(stats, dict) or not stats.get("rounds"):
        return None
    rounds, games = stats["rounds"], stats.get("games") or 0
    shots = sum(stats.get(k) or 0 for k in ("headshots", "bodyshots", "legshots"))
    first_b, first_d = stats.get("first_bloods"), stats.get("first_deaths")
    plants, defuses = stats.get("plants"), stats.get("defuses")
    kills, deaths, assists = stats.get("kills"), stats.get("deaths"), stats.get("assists")
    per_game = [_ratio(m["stats"].get("score"), m["stats"].get("rounds"))
                for m in summary.get("matches") or [] if isinstance(m.get("stats"), dict)]
    per_game = [x for x in per_game if x is not None]
    consistency = None
    if len(per_game) >= MIN_GAMES_FOR_CONSISTENCY and mean(per_game) > 0:
        consistency = max(0.0, 1 - pstdev(per_game) / mean(per_game))
    return {
        "games": games, "rounds": rounds,
        "acs": _ratio(stats.get("score"), rounds),
        "adr": _ratio(stats.get("damage"), rounds),
        "kd": _ratio(kills, deaths) if deaths else (float(kills) if kills is not None else None),
        "kills": kills, "deaths": deaths, "assists": assists,
        "hs": _ratio(stats.get("headshots"), shots),
        "first_blood": _ratio(first_b, rounds), "first_death": _ratio(first_d, rounds),
        "entry": None if first_b is None or first_d is None else (first_b - first_d) / rounds,
        "kast": _ratio(stats.get("kast_rounds"), rounds),
        "util": _ratio(stats.get("casts"), rounds),
        "objective": None if plants is None or defuses is None or not games else (plants + defuses) / games,
        "consistency": consistency,
    }


def _percentile(value, values):
    below = sum(1 for v in values if v < value)
    equal = sum(1 for v in values if v == value)
    return (below + 0.5 * equal) / len(values)


def radar_axes(profiles):
    """{key: {axis label: 0..1 or None}} for {key: derive(...) or None}.

    A player with no profile gets None. An axis is None for a player who lacks every rate it needs; a
    two-rate axis uses whichever of its rates exist. Each rate is ranked among the players who have it.
    """
    out = {key: None for key in profiles}
    pools = {}
    for rate in {r for _, rates in AXES for r in rates}:
        pools[rate] = [p[rate] for p in profiles.values() if p and p.get(rate) is not None]
    for key, profile in profiles.items():
        if not profile:
            continue
        axes = {}
        for label, rates in AXES:
            scores = [_percentile(profile[r], pools[r]) for r in rates if profile.get(r) is not None]
            axes[label] = mean(scores) if scores else None
        out[key] = axes
    return out
