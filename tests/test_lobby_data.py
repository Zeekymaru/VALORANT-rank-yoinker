"""Tests for lobby_data.py: color parsing, the row model, and the demo source. No Textual, no network."""
import threading

import lobby_data
from lobby_data import LobbyModel, LobbyReset, PlayerRow, PlayerUpdate, Status


def test_parse_colr_reads_text_and_color():
    from colr import color
    assert lobby_data.parse_colr(color("Iron 1", fore=(72, 69, 62))) == ("Iron 1", (72, 69, 62))
    assert lobby_data.parse_colr("plain") == ("plain", None)


def test_dark_colors_are_lifted_but_bright_ones_are_not():
    assert max(lobby_data.readable_rgb((46, 46, 46))) >= 95  # the Unranked grey is invisible otherwise
    assert lobby_data.readable_rgb((200, 100, 50)) == (200, 100, 50)
    assert lobby_data.readable_rgb(None) is None


def test_rank_label_uses_the_console_tables():
    assert lobby_data.rank_label(3)[0] == "Iron 1"
    assert lobby_data.rank_label(0)[0] == "Unranked"
    assert lobby_data.rank_label(21)[0] == "Ascendant 1"
    assert lobby_data.rank_label(27)[0] == "Radiant"
    from src.constants import SHORT_NUMBERTORANKS
    assert lobby_data.rank_label(3, short=True)[0] == lobby_data.parse_colr(SHORT_NUMBERTORANKS[3])[0]
    assert lobby_data.rank_label(999) == ("?", None)
    assert lobby_data.rank_label(None) == ("?", None)


def test_party_colors():
    assert lobby_data.party_rgb(0) is None
    assert lobby_data.party_rgb(1) is not None
    assert lobby_data.party_rgb(99) is None


def test_model_applies_events_and_ignores_unknown_ones():
    model = LobbyModel()
    rows = [PlayerRow(puuid="a", name="A"), PlayerRow(puuid="b", name="B", history_state="skipped")]
    assert model.apply(LobbyReset(state="INGAME", rows=rows, map_name="Ascent", mode="Competitive")) == "reset"
    assert (model.state, model.map_name, model.mode) == ("INGAME", "Ascent", "Competitive")

    assert model.apply(PlayerUpdate("a", {"rank": "Gold 1", "stats_state": "done", "not_a_field": 1})) == "row"
    assert model.rows["a"].rank == "Gold 1" and not hasattr(model.rows["a"], "not_a_field")
    assert model.apply(PlayerUpdate("missing", {"rank": "x"})) == ""
    assert model.apply(Status("Loading")) == "status" and model.status == "Loading"
    assert model.apply(object()) == ""

    model.apply(PlayerUpdate("a", {"history_state": "done"}))
    assert model.progress() == (1, 1, 2, 1)  # the skipped row doesn't count towards history

    model.apply(LobbyReset(state="MENUS", rows=[]))  # a new lobby replaces the old rows
    assert model.ordered == [] and model.progress() == (0, 0, 0, 0)


def test_demo_source_emits_a_complete_lobby():
    events, stop = [], threading.Event()
    finished = threading.Event()

    def emit(event):
        events.append(event)
        if isinstance(event, Status) and "Demo data" in event.text:
            finished.set()

    source = lobby_data.DemoSource(delay=0)
    thread = threading.Thread(target=source.run, args=(emit, stop), daemon=True)
    thread.start()
    assert finished.wait(10)
    stop.set()
    thread.join(5)

    model = LobbyModel()
    for event in events:
        model.apply(event)
    rows = model.ordered
    assert len(rows) == 10 and model.state == "INGAME" and model.map_name == "Ascent"
    assert model.progress() == (10, 10, 10, 10)
    assert sum(r.is_self for r in rows) == 1 and any(not r.ally for r in rows)
    available = [r for r in rows if r.history and r.history["available"]]
    assert len(available) == 8
    for row in available:
        summary = row.history
        assert summary["games"] == len(summary["matches"]) == 5
        assert summary["wins"] == sum(m["won"] for m in summary["matches"])
        assert all(a in source.agent_names for a in (t["agent_id"] for t in summary["top_agents"]))
    assert {r.history["reason"] for r in rows if not r.history["available"]} == {"unavailable", "no_games"}
