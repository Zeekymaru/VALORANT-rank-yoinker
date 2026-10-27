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

    def __call__(self, url, headers=None, params=None, timeout=None):
        self.calls.append(url)
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
    assert summary["top_agents"] == [{"agent_id": "agent-jett", "games": 2},
                                     {"agent_id": "agent-sage", "games": 1}]
    assert summary["roles"] == {"Duelist": 2, "Sentinel": 1}


def test_win_rate_and_sample_size(standard_http, roles, tmp_path):
    summary = run_summary(standard_http, roles, tmp_path)
    assert (summary["games"], summary["wins"]) == (3, 2)
    agents, rate, role_text = history.format_columns(
        summary, {"agent-jett": "Jett", "agent-sage": "Sage"})
    assert rate == "67% (2/3)"
    assert agents == "Jett (2), Sage (1)"
    assert role_text == "Duelist 2, Sentinel 1"


def test_empty_history_is_unavailable(roles, tmp_path):
    http = FakeHttp({history_url(): (200, fixture("history_empty.json"))})
    summary = run_summary(http, roles, tmp_path)
    assert summary["available"] is False
    assert http.calls == [history_url()]  # no match details requested
    assert history.format_columns(summary, {})[0] == "history unavailable"


@pytest.mark.parametrize("status", [401, 403, 404])
def test_blocked_status_is_unavailable(status, roles, tmp_path):
    http = FakeHttp({history_url(): (status, {"errorCode": "x"})})
    assert history.match_ids_for(PUUID, PD, HEADERS, http_get=http) is None
    summary = run_summary(http, roles, tmp_path)
    assert summary["available"] is False
    assert history.format_columns(summary, {})[0] == "history unavailable"
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
    assert summary["top_agents"][0] == {"agent_id": "agent-jett", "games": 1}


def test_only_unknown_outcomes_is_unavailable(roles, tmp_path):
    http = FakeHttp(routes_for({"History": [{"MatchID": "match-2", "QueueID": "competitive"}]},
                               {"match-2": "match-nowon.json"}))
    assert run_summary(http, roles, tmp_path)["available"] is False


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
