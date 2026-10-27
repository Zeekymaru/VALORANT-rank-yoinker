"""Tests for tui_views.py: table cells and the five graph views, checked through their plain text."""
import io

from rich.console import Console

import history
import tui_views
from lobby_data import PlayerRow

NAMES = {"agent-jett": "Jett", "agent-sage": "Sage"}
MAPS = {"/game/maps/ascent/ascent": "Ascent"}


def summary(**overrides):
    data = {
        "available": True, "games": 3, "wins": 2,
        "top_agents": [{"agent_id": "agent-jett", "games": 2, "wins": 1},
                       {"agent_id": "agent-sage", "games": 1, "wins": 1}],
        "roles": {"Duelist": 2, "Sentinel": 1},
        "attack": {"won": 1, "rounds": 3}, "defense": {"won": 3, "rounds": 5},
        "matches": [
            {"id": "m1", "agent": "agent-jett", "won": True, "map": "/game/maps/ascent/ascent",
             "attack": [1, 2], "defense": [1, 1], "rr": 21},
            {"id": "m2", "agent": "agent-jett", "won": False, "map": None, "attack": [0, 1], "defense": [0, 1],
             "rr": -18},
            {"id": "m3", "agent": "agent-sage", "won": True, "map": "/game/maps/ascent/ascent",
             "attack": [0, 0], "defense": [2, 3], "rr": None},
        ],
    }
    data.update(overrides)
    return data


def loaded_row(**fields):
    row = PlayerRow(puuid="p", name="Zeek#1", agent="Jett", level=120, party=1, stats_state="done",
                    tier=14, rank="Gold 3", rr=40, peak="Plat 1 (e7a3)", hs=22, wr=51, games=30, rr_delta=18,
                    history=summary(), history_state="done")
    for key, value in fields.items():
        setattr(row, key, value)
    return row


def plain(renderable):
    if hasattr(renderable, "plain"):
        return renderable.plain
    console = Console(file=io.StringIO(), width=100, color_system=None)
    console.print(renderable)
    return console.file.getvalue()


def test_bar_and_sparkline():
    assert tui_views.bar(0.5, 10) == "█████░░░░░"
    assert tui_views.bar(-1, 4) == "░░░░" and tui_views.bar(9, 4) == "████"
    assert tui_views.sparkline([]) == ""
    assert tui_views.sparkline([5, 5, 5]) == "▄▄▄"
    assert tui_views.sparkline([0, 10]) == "▁█"
    assert tui_views.percent(2, 3) == 67 and tui_views.percent(0, 0) is None


def test_row_cells_match_the_columns():
    cells = tui_views.row_cells(loaded_row())
    assert len(cells) == len(tui_views.COLUMNS)
    assert [c.plain for c in cells] == ["■", "Jett", "Zeek#1", "Gold 3", "40", "Plat 1 (e7a3)", "22", "51 (30)",
                                        "120", "+18", "67% 2/3", "● ○ ● "]


def test_cells_while_loading_and_when_data_is_missing():
    row = PlayerRow(puuid="p", name="Zeek#1")
    cells = [c.plain for c in tui_views.row_cells(row)]
    assert cells[3] == "…" and cells[10] == "…"  # rank and recent are still loading
    row = loaded_row(hs="N/A", wr="N/A", rr_delta="N/A", level=None, party=0, history=history._unavailable())
    cells = [c.plain for c in tui_views.row_cells(row)]
    assert (cells[0], cells[6], cells[7], cells[8], cells[9], cells[10]) == ("", "N/A", "N/A", "", "N/A", "unavailable")
    assert tui_views.recent_text(loaded_row(history=history._unavailable(history.REASON_NO_GAMES))).plain == "no comp games"
    assert tui_views.recent_text(loaded_row(history_state="skipped")).plain == ""
    assert tui_views.form_text(loaded_row(history=None)).plain == ""


def test_form_view_lists_each_game():
    text = tui_views.form_view(summary(), NAMES, MAPS).plain
    assert "Last 3 competitive games, newest first" in text
    assert " W " in text and " L " in text
    lines = text.splitlines()
    assert any(line.startswith(" 1  W  Jett") and "Ascent" in line and "Atk 1/2" in line and "Def 1/1" in line
               and "+21 RR" in line for line in lines)
    assert any(line.startswith(" 2  L  Jett") and "—" in line and "-18 RR" in line for line in lines)  # unknown map
    assert any(line.startswith(" 3  W  Sage") and "RR" not in line for line in lines)  # no RR value


def test_views_explain_missing_data():
    assert "Loading" in plain(tui_views.form_view(None, NAMES, MAPS))
    assert "No recent competitive games" in plain(tui_views.sides_view(history._unavailable(history.REASON_NO_GAMES)))
    assert "readable result" in plain(tui_views.agents_view(history._unavailable(history.REASON_NO_RESULT), NAMES))
    assert "unavailable" in plain(tui_views.rr_view(history._unavailable()))
    legacy = summary()
    del legacy["matches"], legacy["attack"], legacy["defense"]
    assert "fills in on the next refresh" in plain(tui_views.form_view(legacy, NAMES, MAPS))
    assert "fills in on the next refresh" in plain(tui_views.sides_view(legacy))


def test_sides_view():
    text = tui_views.sides_view(summary()).plain
    assert "Attack" in text and "33%  (1/3)" in text
    assert "Defense" in text and "60%  (3/5)" in text
    empty = summary(attack={"won": 0, "rounds": 0})
    assert "no rounds" in tui_views.sides_view(empty).plain


def test_agents_view_shows_records_and_roles():
    text = tui_views.agents_view(summary(), NAMES).plain
    assert "Jett" in text and "1-1" in text and "Sage" in text and "1-0" in text
    assert "Duelist" in text and "Sentinel" in text
    legacy = summary(top_agents=[{"agent_id": "agent-jett", "games": 2}])
    assert "×2" in tui_views.agents_view(legacy, NAMES).plain  # cached before per-agent wins existed


def test_rr_series_and_view():
    assert tui_views.rr_series(summary()) == [-18, 21]  # oldest first, games without RR skipped
    text = tui_views.rr_view(summary()).plain
    assert "net +3" in text and "-18" in text and "+21" in text
    assert "No RR data" in tui_views.rr_view(summary(matches=[{"rr": None, "won": True}])).plain
    assert tui_views.rr_series(None) == []


def test_team_stats_and_views():
    ally = [loaded_row(puuid="a", tier=14, party=1), loaded_row(puuid="b", tier=16, party=1),
            loaded_row(puuid="c", tier=0, party=0, history=history._unavailable())]
    enemy = [loaded_row(puuid="d", ally=False, tier=11, party=2)]
    stats = tui_views.team_stats(ally)
    assert (stats["players"], stats["history_loaded"], stats["premades"]) == (3, 2, 1)
    assert stats["wr"] == 67 and stats["attack"] == 33 and stats["defense"] == 60
    assert stats["avg_rank"] == history_rank(15)  # unranked players are left out of the average

    text = plain(tui_views.teams_view(ally + enemy))
    assert "Your team" in text and "Enemy team" in text and "67%" in text and "2/3" in text
    assert "hidden" in plain(tui_views.teams_view(ally))  # agent select: the enemy team isn't visible

    strip = tui_views.team_strip(ally + enemy).plain.splitlines()
    assert strip[0].startswith("YOUR TEAM") and "recent WR 67%" in strip[0] and "1 premade" in strip[0]
    assert strip[1].startswith("ENEMY TEAM")
    assert tui_views.team_strip([]).plain == ""


def history_rank(tier):
    from lobby_data import rank_label
    return rank_label(tier)[0]
