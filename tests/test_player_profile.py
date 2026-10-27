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


def axes(**values):
    base = {"Aim": 0.5, "Entry": 0.5, "Survival": 0.5, "Utility": 0.5, "Objective": 0.5, "Consistency": 0.5}
    base.update(values)
    return base


def test_styles_come_from_blends_of_axes():
    assert pp.archetype(axes(Entry=0.95, Aim=0.8))["label"] == "Entry fragger"
    assert pp.archetype(axes(Aim=0.95, Survival=0.85, Entry=0.3))["label"] == "Fragger"
    assert pp.archetype(axes(Utility=0.95, Survival=0.7))["label"] == "Support"
    assert pp.archetype(axes(Survival=0.95, Entry=0.1, Objective=0.6))["label"] == "Anchor"
    assert pp.archetype(axes(Objective=0.95, Utility=0.7))["label"] == "Objective player"


def test_a_flat_profile_is_balanced_and_nothing_without_data():
    flat = pp.archetype(axes())
    assert flat["label"] == pp.BALANCED and flat["also"] is None and flat["trait"] is None
    assert pp.archetype(None) is None and pp.archetype({}) is None
    assert pp.archetype({label: None for label, _ in pp.AXES}) is None


def test_consistency_is_a_trait_not_a_style():
    assert pp.archetype(axes(Consistency=0.9))["trait"] == "steady"
    assert pp.archetype(axes(Consistency=0.1))["trait"] == "streaky"
    assert pp.archetype(axes(Consistency=0.1))["label"] == pp.BALANCED  # one low axis doesn't make a style
    assert pp.archetype(axes(Consistency=None))["trait"] is None


def test_runner_up_style_and_rough_flag():
    both = pp.archetype(axes(Aim=0.95, Survival=0.95, Utility=0.9, Entry=0.4))
    assert both["label"] in ("Fragger", "Support") and both["also"] in ("Fragger", "Support")
    assert both["label"] != both["also"]
    assert pp.archetype(axes(), games=2)["rough"] and not pp.archetype(axes(), games=3)["rough"]
    assert not pp.archetype(axes())["rough"]  # unknown games: not flagged


def test_missing_axes_are_skipped_but_a_style_needs_half_its_weight():
    def only(**values):
        blank = {label: None for label, _ in pp.AXES}
        blank.update(values)
        return pp.archetype(blank)

    assert only(Aim=0.9)["label"] == "Fragger"  # Aim is half of Fragger's weight, so it can be judged on that alone
    assert only(Objective=0.9)["label"] == "Objective player"  # too little of Support's or Anchor's weight to count
    only_trait = only(Consistency=0.9)
    assert only_trait["label"] == pp.BALANCED and only_trait["score"] is None and only_trait["trait"] == "steady"
