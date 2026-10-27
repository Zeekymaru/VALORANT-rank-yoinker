"""Rates and the lobby-relative radar, from summaries shaped like history.summarise() output."""
import player_profile as pp


def counts(**overrides):
    base = {"games": 2, "rounds": 40, "score": 8000, "kills": 30, "deaths": 20, "assists": 8, "damage": 6000,
            "headshots": 10, "bodyshots": 30, "legshots": 10, "first_bloods": 6, "first_deaths": 4,
            "kast_rounds": 30, "casts": 100, "plants": 2, "defuses": 2}
    base.update(overrides)
    return base


def summary(stats=None, per_game=((4000, 20), (4000, 20)), **top):
    matches = [{"stats": {"score": s, "rounds": r}} for s, r in per_game]
    out = {"available": True, "stats": counts(**top) if stats is None else stats, "matches": matches}
    return out


def test_rates():
    p = pp.derive(summary())
    assert (p["acs"], p["adr"], p["kd"]) == (200, 150, 1.5)
    assert p["hs"] == 0.2 and p["kast"] == 0.75 and p["util"] == 2.5
    assert p["first_blood"] == 0.15 and p["entry"] == 0.05
    assert p["objective"] == 2.0  # (2 plants + 2 defuses) over 2 games
    assert p["consistency"] == 1.0  # identical ACS in both games


def test_consistency_drops_with_a_spread_and_needs_two_games():
    assert pp.derive(summary(per_game=((2000, 20), (6000, 20))))["consistency"] < 0.6
    assert pp.derive(summary(per_game=((4000, 20),)))["consistency"] is None


def test_zero_deaths_and_missing_counts():
    assert pp.derive(summary(deaths=0))["kd"] == 30.0
    p = pp.derive(summary(casts=None, plants=None, first_bloods=None))
    assert p["util"] is None and p["objective"] is None and p["entry"] is None and p["acs"] == 200


def test_no_profile_without_counts():
    assert pp.derive(None) is None
    assert pp.derive({"available": False}) is None
    assert pp.derive({"available": True, "matches": []}) is None  # a summary cached before stats existed
    assert pp.derive(summary(stats={"rounds": 0})) is None


def test_radar_ranks_players_within_the_lobby():
    profiles = {"low": pp.derive(summary(damage=4000, kast_rounds=20)),
                "mid": pp.derive(summary(damage=5000, kast_rounds=25)),
                "high": pp.derive(summary(damage=7000, kast_rounds=35)),
                "none": None}
    axes = pp.radar_axes(profiles)
    assert axes["none"] is None
    assert axes["low"]["Survival"] < axes["mid"]["Survival"] < axes["high"]["Survival"]
    assert axes["mid"]["Survival"] == 0.5 and axes["high"]["Aim"] > axes["low"]["Aim"]
    assert all(axes[k]["Utility"] == 0.5 for k in ("low", "mid", "high"))  # identical -> the middle


def test_a_lone_player_sits_in_the_middle_and_missing_axes_are_none():
    axes = pp.radar_axes({"only": pp.derive(summary(casts=None))})["only"]
    assert axes["Aim"] == 0.5 and axes["Utility"] is None
