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
