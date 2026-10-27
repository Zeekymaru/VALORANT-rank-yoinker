"""Tests for lobby_live.py with fake components: no VALORANT, no network.

They check the logic mirrored from main.py (names, levels, party numbers, ordering, caching,
skipped history) and that one broken call never takes the whole lobby down."""
import threading
from types import SimpleNamespace

import pytest

import history
from lobby_data import LobbyModel, LobbyReset, PlayerUpdate, Status
from lobby_live import LiveLobbySource

ME, ALLY, ENEMY, STREAMER, HIDDEN = "me", "ally1", "enemy1", "streamer1", "hidden1"
JETT = "add6443a-41bd-e414-f6ad-e58d267f4e95"


def player(puuid, team, level, incognito=False, hide_level=False, agent=JETT, selection="locked"):
    return {"Subject": puuid, "TeamID": team, "CharacterID": agent, "CharacterSelectionState": selection,
            "PlayerIdentity": {"AccountLevel": level, "Incognito": incognito, "HideAccountLevel": hide_level}}


class Calls:
    def __init__(self):
        self.rank = []


def make_components(state="INGAME", players=None, rank_error_for=None, party_groups=None, history_on=True):
    calls = Calls()
    players = players if players is not None else [
        player(ENEMY, "Red", 300), player(ALLY, "Blue", 100), player(ME, "Blue", 50),
        player(STREAMER, "Red", 20, incognito=True), player(HIDDEN, "Red", 400, hide_level=True)]
    names = {p["Subject"]: f"{p['Subject']}#TAG" for p in players}

    def get_rank(puuid, season):
        calls.rank.append(puuid)
        if puuid == rank_error_for:
            raise UnboundLocalError("the upstream getRank bug")
        return {"rank": 14, "rr": 40, "peakrank": 16, "peakrankep": 7, "peakrankact": 3, "leaderboard": 0,
                "wr": 51, "numberofgames": 30}

    c = SimpleNamespace(
        log=lambda message: None,
        requests=SimpleNamespace(puuid=ME, pd_url="https://pd.test", get_headers=lambda: {}),
        cfg=SimpleNamespace(table={"lobby_history": history_on, "map_history": True},
                            get_feature_flag=lambda key: key == "peak_rank_act"),
        presences=SimpleNamespace(
            get_presence=lambda: [{"puuid": ME}], get_game_state=lambda presence: state,
            get_private_presence=lambda presence: {"queueId": "competitive", "provisioningFlow": ""}),
        rank=SimpleNamespace(get_rank=get_rank, invalidate_cached_responses=lambda: None),
        pstats=SimpleNamespace(get_stats=lambda puuid: {"hs": 22, "kd": 1.1, "RankedRatingEarned": 18},
                               clear_runtime_cache=lambda: None),
        names=SimpleNamespace(get_names_from_puuids=lambda ps: names),
        menu=SimpleNamespace(
            get_party_members=lambda me, presence: [{"Subject": ME, "PlayerIdentity": {"AccountLevel": 50}}],
            get_party_json=lambda puuids, presence: party_groups or {}),
        coregame=SimpleNamespace(get_coregame_stats=lambda: {"Players": players, "MapID": "/Game/Maps/Ascent/Ascent",
                                                             "GamePodID": "pod"}, match_id="match-1"),
        pregame=SimpleNamespace(get_pregame_stats=lambda: {"AllyTeam": {"Players": players}, "ID": "match-1",
                                                           "MapID": "/Game/Maps/Ascent/Ascent"}),
        agent_dict={JETT: "Jett"}, map_urls={"/game/maps/ascent/ascent": "Ascent"}, season_id="season")
    return c, calls


@pytest.fixture(autouse=True)
def fake_history(monkeypatch):
    """summarise() would hit the network; return a canned summary and remember the arguments."""
    seen = []

    def fake_summarise(puuid, pd_url, headers, roles, map_id=None, **kwargs):
        seen.append((puuid, map_id))
        return {"available": True, "games": 1, "wins": 1, "top_agents": [], "roles": {}, "matches": []}

    monkeypatch.setattr(history, "summarise", fake_summarise)
    return seen


def load(source, state, stop=None):
    events = []
    source._load(state, events.append, stop or threading.Event())
    return events


def model_of(events):
    model = LobbyModel()
    for event in events:
        model.apply(event)
    return model


def test_ingame_rows_order_names_and_levels():
    c, _ = make_components()
    events = load(LiveLobbySource(c), "INGAME")
    reset = events[0]
    assert isinstance(reset, LobbyReset) and (reset.state, reset.map_name, reset.mode) == ("INGAME", "Ascent",
                                                                                          "Competitive")
    rows = {r.puuid: r for r in reset.rows}
    # my team first (highest level first), then the other team
    assert [r.puuid for r in reset.rows] == [ALLY, ME, HIDDEN, ENEMY, STREAMER]
    assert rows[ME].ally and rows[ALLY].ally and not rows[ENEMY].ally and rows[ME].is_self
    assert rows[ENEMY].name == "enemy1#TAG"
    assert rows[STREAMER].name == "Jett"  # streamer mode: the agent is shown, like the console
    assert rows[ME].name == "me#TAG"
    assert rows[HIDDEN].level is None  # a hidden account level stays hidden for strangers
    assert rows[ENEMY].level == 300


def test_party_numbers_are_assigned_by_first_appearance():
    c, _ = make_components(party_groups={"g1": [ENEMY, STREAMER], "g2": [ALLY, ME]})
    rows = {r.puuid: r for r in load(LiveLobbySource(c), "INGAME")[0].rows}
    assert (rows[ALLY].party, rows[ME].party) == (1, 1)  # sorted first, so group g2 is numbered 1
    assert (rows[ENEMY].party, rows[STREAMER].party) == (2, 2)
    assert rows[HIDDEN].party == 0


def test_ranks_then_history_fill_in_each_row(fake_history):
    c, _ = make_components()
    events = load(LiveLobbySource(c), "INGAME")
    model = model_of(events)
    assert model.progress() == (5, 5, 5, 5) and model.status == "Ready"
    row = model.rows[ME]
    assert (row.rank, row.rr, row.hs, row.rr_delta, row.wr, row.games) == ("Gold 3", 40, 22, 18, 51, 30)
    assert row.peak.endswith("(e7a3)") and row.history["available"]
    assert {map_id for _, map_id in fake_history} == {"/Game/Maps/Ascent/Ascent"}  # the lobby's map is passed on
    assert [p for p, _ in fake_history] == [ALLY, ME, HIDDEN, ENEMY, STREAMER]


def test_pregame_shows_the_agent_state_and_menus_skip_history(fake_history):
    players = [player(ME, "Blue", 50, selection="locked"), player(ALLY, "Blue", 60, selection="selected")]
    c, _ = make_components(state="PREGAME", players=players)
    model = model_of(load(LiveLobbySource(c), "PREGAME"))
    assert model.rows[ALLY].locked is False and model.rows[ME].locked is True
    assert model.map_name == "Ascent" and all(r.ally for r in model.ordered)

    c, _ = make_components(state="MENUS", players=[player(ME, "", 50)])
    c.menu.get_party_members = lambda me, presence: [{"Subject": ME, "PlayerIdentity": {"AccountLevel": 50}}]
    fake_history.clear()
    model = model_of(load(LiveLobbySource(c), "MENUS"))
    assert model.rows[ME].history_state == "skipped" and fake_history == []
    assert model.progress()[3] == 0


def test_history_can_be_switched_off(fake_history):
    c, _ = make_components(history_on=False)
    model = model_of(load(LiveLobbySource(c), "INGAME"))
    assert fake_history == [] and all(r.history_state == "skipped" for r in model.ordered)
    assert model.status == "Ready"


def test_one_players_rank_failure_does_not_break_the_lobby():
    c, _ = make_components(rank_error_for=ENEMY)
    model = model_of(load(LiveLobbySource(c), "INGAME"))
    assert model.rows[ENEMY].rank == "?" and model.rows[ENEMY].stats_state == "done"
    assert model.rows[ME].rank == "Gold 3"


def test_rank_fields_are_cached_per_match():
    c, calls = make_components()
    source = LiveLobbySource(c)
    load(source, "INGAME")
    load(source, "INGAME")
    assert sorted(calls.rank) == sorted([ALLY, ME, HIDDEN, ENEMY, STREAMER])  # fetched once, not twice


def test_loading_stops_when_asked():
    c, calls = make_components()
    stop = threading.Event()
    stop.set()
    events = load(LiveLobbySource(c), "INGAME", stop)
    assert isinstance(events[0], LobbyReset) and calls.rank == []


def test_missing_game_data_reports_a_status_instead_of_crashing():
    c, _ = make_components()
    c.coregame.get_coregame_stats = lambda: None
    events = load(LiveLobbySource(c), "INGAME")
    assert len(events) == 1 and isinstance(events[0], Status) and "press r" in events[0].text
    events = load(LiveLobbySource(c), "SOMETHING_NEW")
    assert "Unknown game state" in events[0].text


def test_run_loop_loads_on_state_changes_and_survives_errors():
    c, _ = make_components()
    states = iter(["INGAME", "INGAME", None, "MENUS", RuntimeError("client hiccup")])
    stop = threading.Event()
    loads = []

    class Source(LiveLobbySource):
        def _current_state(self):
            value = next(states, "MENUS")
            if isinstance(value, Exception):
                stop.set()  # last round: the error must be swallowed, then the loop ends
                raise value
            return value

        def _load(self, state, emit, stop_event):
            loads.append(state)

    events = []
    import lobby_live
    original, lobby_live.POLL_SECONDS = lobby_live.POLL_SECONDS, 0
    try:
        Source(c).run(events.append, stop)
    finally:
        lobby_live.POLL_SECONDS = original
    assert loads == ["INGAME", "MENUS"]  # no reload while the state is unchanged
    assert [e.text for e in events if isinstance(e, Status)] == ["Waiting for VALORANT…"] * 2


def test_refresh_forces_a_reload():
    c, _ = make_components()
    stop, loads = threading.Event(), []
    rounds = {"n": 0}

    class Source(LiveLobbySource):
        def _current_state(self):
            rounds["n"] += 1
            if rounds["n"] == 2:
                self.request_refresh()
            if rounds["n"] > 3:
                stop.set()
            return "INGAME"

        def _load(self, state, emit, stop_event):
            loads.append(state)

    import lobby_live
    original, lobby_live.POLL_SECONDS = lobby_live.POLL_SECONDS, 0
    try:
        Source(c).run(lambda e: None, stop)
    finally:
        lobby_live.POLL_SECONDS = original
    assert loads == ["INGAME", "INGAME"]
