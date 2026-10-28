"""Per-match performance counts, checked against a hand-built three-round match (fixtures/match-stats.json).

A is the player under test (Blue, with teammate B); C and D are Red. By hand:
  round 1: A kills C (first blood, assisted by B), hits C for 150 (1 head, 2 body) and a teammate for 20, plants.
  round 2: C kills A (first death), B kills C 2s later (A is traded); B defuses.
  round 3: A kills teammate B (a teamkill, ignored), D kills A (first death, no trade, no kill).
"""
import json
import os

import match_stats

A = "aaaa0000-0000-0000-0000-000000000001"
FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "match-stats.json")


def details():
    with open(FIXTURE, encoding="utf-8") as handle:
        return json.load(handle)


def team_of(match):
    return {p["subject"].lower(): p["teamId"] for p in match["players"]}


def stats_for(puuid=A, match=None):
    match = match or details()
    return match_stats.player_match_stats(puuid, match, team_of(match))


def test_counts_for_the_player_under_test():
    s = stats_for()
    assert (s["rounds"], s["score"], s["kills"], s["deaths"], s["assists"]) == (3, 700, 1, 2, 0)
    assert (s["damage"], s["headshots"], s["bodyshots"], s["legshots"]) == (150, 1, 2, 0)  # teammate damage left out
    assert (s["first_bloods"], s["first_deaths"]) == (1, 2)  # the teamkill doesn't count as a first blood
    assert s["kast_rounds"] == 2  # round 1 kill, round 2 traded, round 3 nothing
    assert (s["plants"], s["defuses"]) == (1, 0)
    assert s["casts"] == 3  # a null cast count is skipped


def test_uppercase_ids_and_other_players():
    s = stats_for(A.upper())
    assert s["kills"] == 1
    b = stats_for("bbbb0000-0000-0000-0000-000000000002")
    assert b["defuses"] == 1 and b["casts"] is None  # no abilityCasts recorded -> None, not 0


def test_a_trade_must_be_by_a_teammate_within_the_window():
    match = details()
    match["roundResults"][1]["playerStats"][1]["kills"][0]["roundTime"] = 5000 + match_stats.TRADE_WINDOW_MS + 1
    assert stats_for(match=match)["kast_rounds"] == 1


def test_payloads_without_round_data_give_none():
    match = details()
    match["roundResults"] = []
    assert stats_for(match=match) is None
    assert match_stats.player_match_stats(A, "nope", {}) is None
    assert stats_for("ffff0000-0000-0000-0000-00000000dead") is None
    match = details()
    del match["players"][0]["stats"]
    assert stats_for(match=match) is None


def test_total_sums_and_skips_missing_counts():
    one, two = stats_for(), dict(stats_for(), casts=None)
    total = match_stats.total([one, two, None])
    assert total["games"] == 2 and total["kills"] == 2 and total["casts"] == 3
    assert match_stats.total([None]) is None


GHOST = "1baa85b4-4c70-1284-64bb-6481dfc3bb4e"
VANDAL = "9c82e19d-4575-0200-1a81-3eacf00cf872"
CLASSIC = "29a0cfab-485b-f5d5-779a-b59f85e204a8"


def test_guns_count_enemy_weapon_kills_and_rounds_held():
    s = stats_for()
    # A's one real kill was a Ghost kill in round 0; the Vandal teamkill in round 2 doesn't count
    assert s["guns"] == {GHOST: [1, 1], VANDAL: [0, 2]}
    assert stats_for("bbbb0000-0000-0000-0000-000000000002")["guns"] == {CLASSIC: [0, 1], VANDAL: [1, 2]}


def test_non_weapon_kills_are_not_gun_kills():
    match = details()
    match["roundResults"][0]["playerStats"][0]["kills"][0]["finishingDamage"] = {"damageType": "Ability", "damageItem": "Ultimate"}
    assert stats_for(match=match)["guns"][GHOST] == [0, 1]


def test_pistol_round_record_is_the_players_own_team():
    assert stats_for()["pistol"] == {"rounds": 1, "won": 1, "kills": 1, "deaths": 0}
    red = stats_for("cccc0000-0000-0000-0000-000000000003")["pistol"]
    assert red == {"rounds": 1, "won": 0, "kills": 0, "deaths": 1}


def test_buys_are_banded_by_team_average_loadout_and_skip_pistols():
    s = stats_for()
    # round 1: Blue averages 4000 (full) and wins, A gets no kill; round 2: Blue averages 3950 (full) and loses
    assert s["buys"] == {"full": {"rounds": 2, "won": 1, "kills": 0}}
    red = stats_for("cccc0000-0000-0000-0000-000000000003")["buys"]
    assert red["eco"] == {"rounds": 1, "won": 0, "kills": 1}  # C killed A in round 1
    assert red["full"] == {"rounds": 1, "won": 1, "kills": 0}


def test_total_merges_guns_pistol_and_buys_and_stays_none_for_old_summaries():
    one = stats_for()
    merged = match_stats.total([one, one])
    assert merged["guns"][GHOST] == [2, 2] and merged["pistol"]["won"] == 2 and merged["buys"]["full"]["rounds"] == 4
    old = {k: v for k, v in one.items() if k not in ("guns", "pistol", "buys")}
    legacy = match_stats.total([old])
    assert legacy["guns"] is None and legacy["pistol"] is None and legacy["buys"] is None
    assert match_stats.total([old, one])["guns"] == one["guns"]
