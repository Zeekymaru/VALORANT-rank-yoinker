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

# rate key -> (label, factor applied before plotting or printing as a percentage / plain number)
METRICS = {
    "adr": ("ADR", 1), "acs": ("ACS", 1), "kd": ("K/D", 1), "hs": ("Headshot %", 100),
    "first_blood": ("First-blood rate (% of rounds)", 100), "kast": ("KAST %", 100),
    "util": ("Ability casts per round", 1),
}
# (x rate, y rate) pairings the scatter plot cycles through
SCATTERS = (("adr", "first_blood"), ("kast", "adr"), ("hs", "adr"), ("acs", "kd"), ("util", "kast"))


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


# --- archetypes ---------------------------------------------------------------------------
# A heuristic label from the lobby-relative axes, not a Riot stat. A *style* is a weighted blend of axes (a negative
# weight means "low on that axis", so the axis is flipped); the best blend at or above ARCHETYPE_MIN wins. How steady
# the player is between games is a separate *trait*, because one axis on its own would outrank every style.
ARCHETYPE_MIN = 0.68
STYLES = (
    ("Entry fragger", (("Entry", 3), ("Aim", 2))),
    ("Fragger", (("Aim", 3), ("Survival", 2), ("Entry", -1))),
    ("Support", (("Utility", 3), ("Survival", 1), ("Objective", 1))),
    ("Anchor", (("Survival", 3), ("Entry", -2), ("Objective", 1))),
    ("Objective player", (("Objective", 3), ("Utility", 1))),
)
BALANCED = "Balanced"
TRAIT_STEADY, TRAIT_STREAKY = "steady", "streaky"
TRAIT_HIGH, TRAIT_LOW = 0.75, 0.25  # consistency percentiles that earn a trait


def _blend(axes, weights):
    """Weighted mean (0..1) of the axes in weights, or None when under half the weight has data."""
    total = used = 0.0
    for axis, weight in weights:
        value = axes.get(axis)
        if value is None:
            continue
        total += abs(weight) * (value if weight > 0 else 1 - value)
        used += abs(weight)
    return total / used if used >= sum(abs(w) for _, w in weights) / 2 else None


def archetype(axes, games=None):
    """{"label", "score", "also", "trait", "rough"} for one player's axes, or None without data.

    label is the best-fitting style ("Balanced" when none clears the threshold), also the runner-up style if it
    clears it too, trait "steady" / "streaky" from the consistency axis (or None), and rough is True when fewer
    than DIM_BELOW_GAMES games stand behind the numbers.
    """
    if not axes or all(v is None for v in axes.values()):
        return None
    scored = sorted(((score, label) for label, weights in STYLES
                     if (score := _blend(axes, weights)) is not None), reverse=True)
    passing = [(s, l) for s, l in scored if s >= ARCHETYPE_MIN]
    consistency = axes.get("Consistency")
    trait = (TRAIT_STEADY if consistency >= TRAIT_HIGH else TRAIT_STREAKY if consistency <= TRAIT_LOW else None) \
        if consistency is not None else None
    rough = games is not None and games < DIM_BELOW_GAMES
    if not passing:
        return {"label": BALANCED, "score": scored[0][0] if scored else None, "also": None, "trait": trait,
                "rough": rough}
    return {"label": passing[0][1], "score": passing[0][0], "also": passing[1][1] if len(passing) > 1 else None,
            "trait": trait, "rough": rough}
