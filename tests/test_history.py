"""Tests for history.py. Fixture JSON only; no network calls are made."""
import json
import os

import pytest

import history

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
PD = "https://pd.test"
PUUID = "p-target"
HEADERS = {"Authorization": "Bearer test"}


def fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf8") as file:
        return json.load(file)


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no body")
        return self._payload


class FakeHttp:
    """Stands in for requests.get: URL -> (status, payload), and records calls."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []
        self.params = []

    def __call__(self, url, headers=None, params=None, timeout=None):
        self.calls.append(url)
        self.params.append(params)
        if url not in self.routes:
            raise AssertionError(f"unexpected request: {url}")
        status, payload = self.routes[url]
        return FakeResponse(status, payload)


def history_url(puuid=PUUID):
    return PD + history.HISTORY_PATH.format(puuid=puuid)


def details_url(match_id):
    return PD + history.MATCH_DETAILS_PATH.format(match_id=match_id)


def routes_for(history_payload, match_names):
    routes = {history_url(): (200, history_payload)}
    for match_id, name in match_names.items():
        routes[details_url(match_id)] = (200, fixture(name))
    return routes


@pytest.fixture
def roles():
    return {"agent-jett": "Duelist", "agent-sage": "Sentinel", "agent-omen": "Controller"}


@pytest.fixture
def standard_http():
    return FakeHttp(routes_for(fixture("history_ok.json"),
                               {"match-1": "match-1.json", "match-2": "match-2.json",
                                "match-3": "match-3.json"}))


def run_summary(http, roles, tmp_path, **kwargs):
    return history.summarise(PUUID, PD, HEADERS, roles, cache_dir=str(tmp_path), http_get=http, **kwargs)


def test_normal_aggregation(standard_http, roles, tmp_path):
    summary = run_summary(standard_http, roles, tmp_path)
    assert summary["available"] is True
    assert summary["top_agents"] == [{"agent_id": "agent-jett", "games": 2, "wins": 1},
                                     {"agent_id": "agent-sage", "games": 1, "wins": 1}]
    assert summary["roles"] == {"Duelist": 2, "Sentinel": 1}
    # rounds of the player's own team: match-1 atk 1/2 def 1/1, match-2 atk 0/1 def 0/1, match-3 def 2/3
    assert summary["attack"] == {"won": 1, "rounds": 3}
    assert summary["defense"] == {"won": 3, "rounds": 5}
    assert [(m["id"], m["agent"], m["won"], m["attack"], m["defense"]) for m in summary["matches"]] == [
        ("match-1", "agent-jett", True, [1, 2], [1, 1]),
        ("match-2", "agent-jett", False, [0, 1], [0, 1]),
        ("match-3", "agent-sage", True, [0, 0], [2, 3]),
    ]
    assert [m["map"] for m in summary["matches"]] == ["/game/maps/ascent/ascent", "/game/maps/triad/triad",
                                                      "/game/maps/ascent/ascent"]


def test_rr_earned_is_carried_per_match(roles, tmp_path):
    entries = {"Matches": [{"MatchID": "match-1", "RankedRatingEarned": 21},
                           {"MatchID": "match-2", "RankedRatingEarned": -18},
                           {"MatchID": "match-3"}]}  # no RR field: stays None
    http = FakeHttp(routes_for(entries, {"match-1": "match-1.json", "match-2": "match-2.json",
                                         "match-3": "match-3.json"}))
    summary = run_summary(http, roles, tmp_path)
    assert [m["rr"] for m in summary["matches"]] == [21, -18, None]


def test_win_rate_and_sample_size(standard_http, roles, tmp_path):
    summary = run_summary(standard_http, roles, tmp_path)
    assert (summary["games"], summary["wins"]) == (3, 2)
    cell = history.format_cell(summary, {"agent-jett": "Jett", "agent-sage": "Sage"})
    assert cell == "67% 2/3\nJett 1-1 · Sage 1-0\nDuel2 Sent1\nAtk 33% (3) · Def 60% (5)"


def test_summary_cached_before_per_agent_wins_still_renders():
    legacy = {"available": True, "games": 3, "wins": 2, "roles": {"Duelist": 2, "Sentinel": 1},
              "top_agents": [{"agent_id": "agent-jett", "games": 2}, {"agent_id": "agent-sage", "games": 1}]}
    cell = history.format_cell(legacy, {"agent-jett": "Jett", "agent-sage": "Sage"})
    assert cell == "67% 2/3\nJett ×2 · Sage\nDuel2 Sent1"


def test_cell_styling_hooks(standard_http, roles, tmp_path):
    summary = run_summary(standard_http, roles, tmp_path)
    cell = history.format_cell(summary, {}, wr_color=lambda pct, text: f"<{pct}:{text}>", dim=lambda text: f"[{text}]")
    assert cell.splitlines() == ["<67:67% 2/3>", "Unknown 1-1 · Unknown 1-0", "[Duel2 Sent1]",
                                 "Atk <33:33% (3)> · Def <60:60% (5)>"]
    assert history.format_cell(history._unavailable(), {}, dim=lambda text: f"[{text}]") == "[history unavailable]"


ASCENT = "/Game/Maps/Ascent/Ascent"
TRIAD = "/Game/Maps/Triad/Triad"


def deep_routes():
    """Seven-match history; match-7 is deliberately not routable (must never be fetched)."""
    return routes_for(fixture("history_deep.json"),
                      {"match-1": "match-1.json", "match-2": "match-2.json", "match-3": "match-3.json",
                       "match-4": "match-2.json", "match-5": "match-2.json", "match-6": "match-6.json"})


@pytest.fixture
def deep_http(monkeypatch):
    """The deep history with LIST_DEPTH raised to 20, as when looking further back for a map."""
    monkeypatch.setattr(history, "LIST_DEPTH", 20)
    return FakeHttp(deep_routes())


def test_default_map_lookup_stays_within_the_recent_sample(roles, tmp_path):
    http = FakeHttp(deep_routes())
    summary = run_summary(http, roles, tmp_path, map_id=ASCENT)
    assert http.params[0]["endIndex"] == 5  # LIST_DEPTH defaults to the sample size
    assert summary["map"] == {"games": 2, "wins": 2}  # only match-1 and match-3 are in the 5 newest
    assert len(http.calls) == 6  # one list request + the 5 sampled matches, nothing extra
    assert details_url("match-6") not in http.calls


def test_map_record_asks_for_a_longer_history_and_fetches_only_that_map(deep_http, roles, tmp_path):
    summary = run_summary(deep_http, roles, tmp_path, map_id=ASCENT)
    assert deep_http.params[0]["endIndex"] == history.LIST_DEPTH  # still a single list request
    assert deep_http.calls.count(history_url()) == 1
    assert summary["games"] == 5  # the recent sample is unchanged: the 5 newest matches
    assert summary["map"] == {"games": 3, "wins": 2}  # match-1 W, match-3 W, match-6 L
    assert details_url("match-6") in deep_http.calls  # older than the sample, fetched for the map record
    assert details_url("match-7") not in deep_http.calls  # not on the map and outside the sample


def test_map_matches_cap_limits_extra_fetches(deep_http, roles, tmp_path):
    summary = run_summary(deep_http, roles, tmp_path, map_id=ASCENT, map_matches=2)
    assert summary["map"] == {"games": 2, "wins": 2}
    assert details_url("match-6") not in deep_http.calls


def test_without_a_map_id_the_history_is_not_extended(standard_http, roles, tmp_path):
    summary = run_summary(standard_http, roles, tmp_path)
    assert standard_http.params[0]["endIndex"] == history.DEFAULT_MAX_MATCHES
    assert "map" not in summary


def test_history_entries_without_a_map_field_skip_the_map_record(standard_http, roles, tmp_path):
    summary = run_summary(standard_http, roles, tmp_path, map_id=ASCENT)
    assert "map" not in summary
    assert len(standard_http.calls) == 4  # list + the 3 recent matches, nothing extra


def test_map_summaries_are_cached_per_map(deep_http, roles, tmp_path):
    kwargs = dict(map_matches=3)
    on_ascent = run_summary(deep_http, roles, tmp_path, map_id=ASCENT, **kwargs)
    on_triad = run_summary(deep_http, roles, tmp_path, map_id=TRIAD, **kwargs)
    assert on_ascent["map"] == {"games": 3, "wins": 2}
    assert on_triad["map"] == {"games": 3, "wins": 0}  # match-2, -4, -5 are all losses
    assert run_summary(deep_http, roles, tmp_path, map_id=ASCENT, **kwargs) == on_ascent
    assert deep_http.calls.count(history_url()) == 2  # the repeat Ascent lookup came from the cache


def test_map_line_in_the_cell(deep_http, roles, tmp_path):
    summary = run_summary(deep_http, roles, tmp_path, map_id=ASCENT)
    assert history.format_cell(summary, {}).splitlines()[-1].startswith("Atk ")  # no map name, no map line
    assert history.format_cell(summary, {}, map_name="Ascent").splitlines()[-1] == "Ascent 2-1"
    summary["map"] = {"games": 0, "wins": 0}
    assert history.format_cell(summary, {}, map_name="Ascent").splitlines()[-1] == "Ascent -"


def test_rounds_without_a_winner_or_role_are_ignored():
    details = {"roundResults": [{"winningTeam": "Red"}, {"winningTeamRole": "Attacker"}, "junk",
                                {"winningTeam": "Red", "winningTeamRole": "Attacker"}]}
    assert history._side_rounds("Red", details) == {"Attacker": [1, 1], "Defender": [0, 0]}


def test_win_rate_color_is_always_readable_on_a_dark_background():
    assert history.win_rate_rgb(-5) == history.win_rate_rgb(0) == (235, 80, 80)
    assert history.win_rate_rgb(50) == (235, 205, 70)
    assert history.win_rate_rgb(100) == history.win_rate_rgb(150) == (90, 225, 110)
    assert all(max(history.win_rate_rgb(p)) >= 200 for p in range(0, 101))


def test_ties_go_to_the_most_recent_agent(roles, tmp_path):
    http = FakeHttp(routes_for({"Matches": [{"MatchID": "match-3"}, {"MatchID": "match-1"}]},
                               {"match-3": "match-3.json", "match-1": "match-1.json"}))
    summary = run_summary(http, roles, tmp_path)
    assert [a["agent_id"] for a in summary["top_agents"]] == ["agent-sage", "agent-jett"]


def test_empty_history_is_unavailable(roles, tmp_path):
    http = FakeHttp({history_url(): (200, fixture("history_empty.json"))})
    summary = run_summary(http, roles, tmp_path)
    assert summary["available"] is False
    assert summary["reason"] == "no_games"
    assert http.calls == [history_url()]  # no match details requested
    assert history.format_cell(summary, {}) == "no recent comp games"


@pytest.mark.parametrize("status", [401, 403, 404])
def test_blocked_status_is_unavailable(status, roles, tmp_path):
    http = FakeHttp({history_url(): (status, {"errorCode": "x"})})
    assert history.match_ids_for(PUUID, PD, HEADERS, http_get=http) is None
    summary = run_summary(http, roles, tmp_path)
    assert summary["available"] is False
    assert summary["reason"] == "unavailable"
    assert history.format_cell(summary, {}) == "history unavailable"
    assert http.calls == [history_url()] * 2  # no retries, no other endpoints


def test_player_not_in_match_is_skipped(roles, tmp_path):
    http = FakeHttp(routes_for(fixture("history_ok.json"),
                               {"match-1": "match-1.json", "match-2": "match-noplayer.json",
                                "match-3": "match-3.json"}))
    summary = run_summary(http, roles, tmp_path)
    assert (summary["games"], summary["wins"]) == (2, 2)


def test_team_without_won_field_is_skipped(roles, tmp_path):
    http = FakeHttp(routes_for(fixture("history_ok.json"),
                               {"match-1": "match-1.json", "match-2": "match-nowon.json",
                                "match-3": "match-3.json"}))
    summary = run_summary(http, roles, tmp_path)
    assert (summary["games"], summary["wins"]) == (2, 2)
    assert summary["top_agents"][0] == {"agent_id": "agent-jett", "games": 1, "wins": 1}


def test_only_unknown_outcomes_is_unavailable(roles, tmp_path):
    http = FakeHttp(routes_for({"Matches": [{"MatchID": "match-2"}]},
                               {"match-2": "match-nowon.json"}))
    summary = run_summary(http, roles, tmp_path)
    assert summary["available"] is False
    assert summary["reason"] == "no_result"
    assert history.format_cell(summary, {}) == "history unavailable"


def test_player_cache_ttl_expires(standard_http, roles, tmp_path):
    clock = {"t": 1000.0}
    kwargs = dict(ttl=60, now=lambda: clock["t"])

    first = run_summary(standard_http, roles, tmp_path, **kwargs)
    assert len(standard_http.calls) == 4  # history + 3 matches

    clock["t"] += 59  # still fresh: served from the player cache
    assert run_summary(standard_http, roles, tmp_path, **kwargs) == first
    assert len(standard_http.calls) == 4

    clock["t"] += 2  # expired: history is re-fetched, finished matches stay cached
    assert run_summary(standard_http, roles, tmp_path, **kwargs) == first
    assert standard_http.calls[4:] == [history_url()]


def test_match_details_cache_never_expires(tmp_path):
    http = FakeHttp({details_url("match-1"): (200, fixture("match-1.json"))})
    first = history.match_details("match-1", PD, HEADERS, cache_dir=str(tmp_path), http_get=http)
    again = history.match_details("match-1", PD, HEADERS, cache_dir=str(tmp_path), http_get=http)
    assert first == again == fixture("match-1.json")
    assert len(http.calls) == 1


def test_failed_match_details_are_not_cached(tmp_path):
    http = FakeHttp({details_url("match-1"): (404, None)})
    assert history.match_details("match-1", PD, HEADERS, cache_dir=str(tmp_path), http_get=http) is None
    assert history.match_details("match-1", PD, HEADERS, cache_dir=str(tmp_path), http_get=http) is None
    assert len(http.calls) == 2


def test_unsafe_ids_never_reach_disk_or_network(tmp_path):
    http = FakeHttp({})
    assert history.match_details("../evil", PD, HEADERS, cache_dir=str(tmp_path), http_get=http) is None
    assert history.match_ids_for("../evil", PD, HEADERS, http_get=http) is None
    assert http.calls == []


def test_network_error_never_raises(roles, tmp_path):
    def boom(*args, **kwargs):
        raise ConnectionError("down")

    assert run_summary(boom, roles, tmp_path)["available"] is False


def test_agent_roles_table_is_well_formed():
    assert set(history.AGENT_ROLES.values()) == {"Duelist", "Initiator", "Controller", "Sentinel"}
    assert all(agent_id == agent_id.lower() for agent_id in history.AGENT_ROLES)


def test_agent_missing_from_role_table_counts_as_unknown(tmp_path):
    http = FakeHttp(routes_for(fixture("history_ok.json"),
                               {"match-1": "match-1.json", "match-2": "match-2.json",
                                "match-3": "match-3.json"}))
    summary = run_summary(http, {"agent-jett": "Duelist"}, tmp_path)
    assert summary["roles"] == {"Duelist": 2, "Unknown": 1}


def test_player_results_carry_performance_counts_into_the_summary():
    a = "aaaa0000-0000-0000-0000-000000000001"
    details = fixture("match-stats.json")
    result = history._player_result(a, details)
    assert result["stats"]["kills"] == 1 and result["stats"]["first_deaths"] == 2
    summary = history._aggregate([{**result, "id": "stats-1", "rr": None}], {})
    assert summary["stats"]["games"] == 1 and summary["stats"]["rounds"] == 3
    assert summary["matches"][0]["stats"] == result["stats"]


def test_matches_without_round_data_still_count_without_stats():
    result = history._player_result(PUUID, fixture("match-1.json"))
    assert result is not None and result["stats"] is None  # older fixtures have no per-round data
    summary = history._aggregate([{**result, "id": "match-1", "rr": None}], {})
    assert summary["available"] and summary["stats"] is None
