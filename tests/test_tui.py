"""Headless tests of the Textual app against the demo source (skipped if Textual isn't installed).

pytest-asyncio isn't a dependency, so each test drives Textual's async test harness with asyncio.run."""
import asyncio
import io
import os

import pytest
from rich.console import Console

pytest.importorskip("textual")

from textual.widgets import Button, ContentSwitcher, DataTable, Static  # noqa: E402

import tui  # noqa: E402
from lobby_data import DemoSource, Status  # noqa: E402

SIZE = (200, 46)


def text_of(widget):
    content = getattr(widget, "content", None)
    if content is None:
        content = getattr(widget, "renderable", "")
    if hasattr(content, "plain"):
        return content.plain
    if isinstance(content, str):
        return content
    console = Console(file=io.StringIO(), width=120, color_system=None)  # a Group or Table: draw it to text
    console.print(content)
    return console.file.getvalue()


async def loaded_app(pilot, app):
    for _ in range(100):
        await pilot.pause(0.1)
        if app.model.progress()[1] == 10 and app.model.status.startswith("Demo data"):
            return
    raise AssertionError(f"demo lobby never finished loading: {app.model.progress()} {app.model.status}")


def run(scenario, store_dir=None):
    async def main():
        app = tui.LobbyApp(DemoSource(delay=0), store_dir=store_dir)
        async with app.run_test(size=SIZE) as pilot:
            await loaded_app(pilot, app)
            await scenario(app, pilot)
        assert app.stop_event.is_set()  # leaving the app stops the data source

    asyncio.run(main())


def test_lobby_loads_row_by_row_and_shows_status():
    async def scenario(app, pilot):
        table = app.query_one("#players", DataTable)
        assert table.row_count == 10 and app.selected == "demo-0"
        status = text_of(app.query_one("#status", Static))
        assert "In-Game" in status and "Ascent" in status and "ranks 10/10" in status and "history 10/10" in status
        summary = text_of(app.query_one("#summary", Static))
        assert summary.startswith("YOUR TEAM") and "ENEMY TEAM" in summary

    run(scenario)


def test_number_keys_switch_the_graph_and_highlight_the_button():
    async def scenario(app, pilot):
        switcher = app.query_one("#graphs", ContentSwitcher)
        for number, (key, label) in enumerate(tui.GRAPHS, 1):
            await pilot.press(tui.graph_key(number))
            await pilot.pause(0.1)
            assert app.graph == key and switcher.current == f"g-{key}"
            for other, _ in tui.GRAPHS:
                variant = app.query_one(f"#btn-{other}", Button).variant
                assert variant == ("primary" if other == key else "default")

    run(scenario)


def test_clicking_a_button_switches_the_graph_and_keeps_the_arrow_keys_working():
    async def scenario(app, pilot):
        await pilot.click("#btn-agents")
        await pilot.pause(0.1)
        assert app.graph == "agents" and "Agents, last 5 games" in text_of(app.query_one("#g-agents", Static))
        await pilot.press("down")  # focus must be back on the players table
        await pilot.pause(0.1)
        assert app.selected == "demo-1"
        assert "Echo#09110 — Agents" in text_of(app.query_one("#graph-title", Static))

    run(scenario)


def test_the_graph_follows_the_selected_player():
    async def scenario(app, pilot):
        first = text_of(app.query_one("#g-form", Static))
        await pilot.press("down")
        await pilot.pause(0.1)
        assert text_of(app.query_one("#g-form", Static)) != first
        for _ in range(7):  # down to the player whose profile is hidden
            await pilot.press("down")
        await pilot.pause(0.1)
        assert app.selected == "demo-8"
        assert "History unavailable" in text_of(app.query_one("#g-form", Static))
        await pilot.press("down")
        await pilot.pause(0.1)
        assert "No recent competitive games" in text_of(app.query_one("#g-form", Static))

    run(scenario)


def test_team_comparison_is_about_the_whole_lobby():
    async def scenario(app, pilot):
        await pilot.press("4")
        await pilot.pause(0.1)
        assert text_of(app.query_one("#graph-title", Static)) == "Lobby"
        await pilot.press("down")  # moving the selection doesn't change a lobby-wide view
        await pilot.pause(0.1)
        assert text_of(app.query_one("#graph-title", Static)) == "Lobby"

    run(scenario)


def test_refresh_key_restarts_the_demo():
    async def scenario(app, pilot):
        await pilot.press("r")
        for _ in range(50):
            await pilot.pause(0.1)
            if app.model.progress()[1] == 10 and app.model.status.startswith("Demo data"):
                break
        assert app.model.progress() == (10, 10, 10, 10)

    run(scenario)


def test_v_toggles_between_list_and_cards_and_back():
    async def scenario(app, pilot):
        views = app.query_one("#views", ContentSwitcher)
        assert app.view == "list" and views.current == "players-pane"
        await pilot.press("v")
        await pilot.pause(0.2)
        assert app.view == "cards" and views.current == "cards" and app.has_class("-cards")
        assert str(app.query_one("#btn-view", Button).label) == "v View: Cards"
        assert len(app.query(tui.PlayerCard)) == 10
        assert len(app.query_one("#cards-ally").children) == 5 and len(app.query_one("#cards-enemy").children) == 5
        assert app.query_one("#card-0", tui.PlayerCard).has_class("-selected")
        assert app.focused is app.query_one("#card-0")  # the selected card takes the keyboard

        await pilot.press("v")
        await pilot.pause(0.2)
        assert app.view == "list" and views.current == "players-pane" and not app.has_class("-cards")
        assert app.focused is app.query_one("#players")

    run(scenario)


def test_the_view_button_toggles_too():
    async def scenario(app, pilot):
        await pilot.click("#btn-view")
        await pilot.pause(0.2)
        assert app.view == "cards"
        await pilot.click("#btn-view")
        await pilot.pause(0.2)
        assert app.view == "list"

    run(scenario)


def test_cards_show_each_players_recent_history():
    async def scenario(app, pilot):
        await pilot.press("v")
        await pilot.pause(0.2)
        first = text_of(app.query_one("#card-0", tui.PlayerCard))
        assert first.startswith("■ Zikeyo#ivun") and "60% 3/5" in first and "Atk " in first and "Ascent" in first
        hidden = text_of(app.query_one("#card-8", tui.PlayerCard))
        assert hidden.endswith("history unavailable")
        assert text_of(app.query_one("#card-9", tui.PlayerCard)).endswith("no recent comp games")

    run(scenario)


def test_arrow_keys_walk_the_cards_in_the_grid():
    async def scenario(app, pilot):
        await pilot.press("v")
        await pilot.pause(0.2)
        assert app.query_one(tui.CardView).columns == 3  # 200 columns wide: three cards per row
        await pilot.press("right")
        await pilot.pause(0.1)
        assert app.selected == "demo-1" and app.focused is app.query_one("#card-1")
        await pilot.press("left", "left")  # clamps at the first card
        await pilot.pause(0.1)
        assert app.selected == "demo-0"
        await pilot.press("down")  # one grid row down: card 3
        await pilot.pause(0.1)
        assert app.selected == "demo-3"
        await pilot.press("right", "down")  # card 4 is the last of your team; down lands in the enemy grid
        await pilot.pause(0.1)
        assert app.selected == "demo-6"
        await pilot.press("up", "up")
        await pilot.pause(0.1)
        assert app.selected == "demo-1"  # back up to your team's first row, same column
        assert "Echo#09110 — Form" in text_of(app.query_one("#graph-title", Static))

    run(scenario)


def test_clicking_a_card_selects_it_and_the_selection_is_shared_with_the_list():
    async def scenario(app, pilot):
        await pilot.press("v")
        await pilot.pause(0.2)
        await pilot.click("#card-4")
        await pilot.pause(0.2)
        assert app.selected == "demo-4"
        assert app.query_one("#card-4").has_class("-selected") and not app.query_one("#card-0").has_class("-selected")
        assert "ArmaBlanket#gloom — Form" in text_of(app.query_one("#graph-title", Static))
        await pilot.press("v")
        await pilot.pause(0.2)
        assert app.query_one("#players", DataTable).cursor_row == 4  # the list highlights the same player
        await pilot.press("up")
        await pilot.pause(0.1)
        await pilot.press("v")
        await pilot.pause(0.2)
        assert app.selected == "demo-3" and app.query_one("#card-3").has_class("-selected")

    run(scenario)


def test_graph_buttons_keep_the_keyboard_in_the_active_view():
    async def scenario(app, pilot):
        await pilot.press("v")
        await pilot.pause(0.2)
        await pilot.click("#btn-sides")
        await pilot.pause(0.2)
        assert app.graph == "sides" and app.focused is app.query_one("#card-0")
        await pilot.press("right")
        await pilot.pause(0.1)
        assert app.selected == "demo-1"

    run(scenario)


def test_reloading_in_the_card_view_keeps_the_cards_and_the_selection():
    async def scenario(app, pilot):
        await pilot.press("v")
        await pilot.press("right", "right")
        await pilot.pause(0.1)
        await pilot.press("r")
        for _ in range(50):
            await pilot.pause(0.1)
            if app.model.progress()[1] == 10 and app.model.status.startswith("Demo data"):
                break
        assert len(app.query(tui.PlayerCard)) == 10 and app.selected == "demo-2"
        assert app.query_one("#card-2").has_class("-selected")

    run(scenario)


def test_reloading_in_the_list_view_keeps_the_selected_player():
    async def scenario(app, pilot):
        await pilot.press("down", "down")
        await pilot.pause(0.1)
        assert app.selected == "demo-2"
        await pilot.press("r")
        for _ in range(50):
            await pilot.pause(0.1)
            if app.model.progress()[1] == 10 and app.model.status.startswith("Demo data"):
                break
        await pilot.pause(0.2)  # let any queued highlight events from the rebuild arrive
        assert app.selected == "demo-2" and app.query_one("#players", DataTable).cursor_row == 2

    run(scenario)


def test_the_enemy_section_is_hidden_when_only_your_team_is_visible():
    from lobby_data import LobbyReset, PlayerRow

    class AgentSelect:
        agent_names, map_names = {}, {}

        def run(self, emit, stop):
            rows = [PlayerRow(puuid=f"p{i}", name=f"Ally{i}#1", ally=True, agent="Jett") for i in range(3)]
            emit(LobbyReset(state="PREGAME", rows=rows, map_name="Ascent"))
            stop.wait(30)

    async def main():
        app = tui.LobbyApp(AgentSelect())
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause(0.5)
            await pilot.press("v")
            await pilot.pause(0.2)
            assert len(app.query(tui.PlayerCard)) == 3
            assert app.query_one("#enemy-title").display is False and app.query_one("#cards-enemy").display is False

    asyncio.run(main())


def test_a_crashing_source_is_reported_instead_of_taking_the_screen_down():
    class Broken:
        agent_names, map_names = {}, {}

        def run(self, emit, stop):
            emit(Status("about to fail"))
            raise RuntimeError("boom")

    async def main():
        app = tui.LobbyApp(Broken())
        async with app.run_test(size=SIZE) as pilot:
            for _ in range(30):
                await pilot.pause(0.1)
                if "stopped" in app.model.status:
                    break
            assert "Data source stopped" in app.model.status and "boom" in app.model.status
            assert "Data source stopped" in text_of(app.query_one("#status", Static))

    asyncio.run(main())


def test_profile_graph_draws_the_radar_for_the_selected_player():
    async def scenario(app, pilot):
        await pilot.press("6")
        await pilot.pause(0.2)
        assert app.graph == "profile"
        assert "Zikeyo#ivun — Profile" in text_of(app.query_one("#graph-title", Static))
        first = text_of(app.query_one("#g-profile", Static))
        assert "Profile vs" in first and "Consistency" in first and "●" in first
        await pilot.press("down")
        await pilot.pause(0.1)
        assert text_of(app.query_one("#g-profile", Static)) != first
        assert "Echo#09110 — Profile" in text_of(app.query_one("#graph-title", Static))

    run(scenario)


def test_list_has_a_fingerprint_column_that_fills_in_as_history_arrives():
    async def scenario(app, pilot):
        table = app.query_one("#players", DataTable)
        assert str(table.columns[app._column_keys[-1]].label) == "AESUOC"
        assert len(table.get_row("demo-0")[-1].plain) == 6
        assert table.get_row("demo-8")[-1].plain == ""  # a player with no history gets no fingerprint

    run(scenario)


def test_heatmap_graph_lists_the_whole_lobby_and_follows_the_selection():
    async def scenario(app, pilot):
        await pilot.press("7")
        await pilot.pause(0.2)
        assert app.graph == "heat" and text_of(app.query_one("#graph-title", Static)) == "Lobby"
        first = text_of(app.query_one("#g-heat", Static))
        assert "Your team avg" in first and "Enemy avg" in first and "▶ Zikeyo#ivun" in first
        await pilot.press("down")
        await pilot.pause(0.1)
        assert "▶ Echo#09110" in text_of(app.query_one("#g-heat", Static))

    run(scenario)


def test_scatter_graph_plots_the_lobby_and_s_cycles_the_pairing():
    async def scenario(app, pilot):
        await pilot.press("s")  # from another graph, s jumps to the scatter without skipping a pairing
        await pilot.pause(0.2)
        assert app.graph == "scatter" and app.scatter_index == 0
        assert "First-blood rate" in text_of(app.query_one("#scatter-text", Static))
        assert app.query_one("#scatter-plot", tui.PlotextPlot) is not None
        await pilot.press("s")
        await pilot.pause(0.2)
        assert app.scatter_index == 1 and "KAST %" in text_of(app.query_one("#scatter-text", Static))
        await pilot.click("#scatter-next")
        await pilot.pause(0.2)
        assert app.scatter_index == 2

    run(scenario)


def test_scatter_without_textual_plotext_lists_the_values(monkeypatch):
    monkeypatch.setattr(tui, "PlotextPlot", None)

    async def main():
        app = tui.LobbyApp(DemoSource(delay=0))
        async with app.run_test(size=SIZE) as pilot:
            await loaded_app(pilot, app)
            await pilot.press("8")
            await pilot.pause(0.2)
            text = text_of(app.query_one("#g-scatter", Static))
            assert "requirements-tui-charts.txt" in text and "Echo" in text

    asyncio.run(main())


def test_the_app_works_without_textual_plotext(monkeypatch):
    monkeypatch.setattr(tui, "PlotextPlot", None)

    async def main():
        app = tui.LobbyApp(DemoSource(delay=0))
        async with app.run_test(size=SIZE) as pilot:
            await loaded_app(pilot, app)
            await pilot.press("5")
            await pilot.pause(0.2)
            assert "Net RR over the sampled games" in text_of(app.query_one("#g-rr", Static))

    asyncio.run(main())


def test_profile_graph_names_the_players_style():
    async def scenario(app, pilot):
        await pilot.press("6")
        await pilot.pause(0.2)
        assert "Style  " in text_of(app.query_one("#g-profile", Static))
        await pilot.press("7")
        await pilot.pause(0.2)
        assert "Style" in text_of(app.query_one("#g-heat", Static))

    run(scenario)


def test_a_loaded_lobby_is_saved_and_can_be_reopened_while_the_live_one_keeps_going(tmp_path):
    import lobby_store

    async def scenario(app, pilot):
        await pilot.pause(0.3)
        saved = lobby_store.list_saved(str(tmp_path))
        assert len(saved) == 1 and saved[0]["players"] == 10 and saved[0]["map_name"] == "Ascent"
        assert saved[0]["summary"]["you"] == "Viper"

        await pilot.press("h")
        await pilot.pause(0.3)
        assert isinstance(app.screen, tui.HistoryScreen)
        table = app.screen.query_one("#history-table", DataTable)
        assert table.row_count == 1
        await pilot.press("enter")
        await pilot.pause(0.3)
        assert app.viewing is not None and app.model is not app.live_model and app.has_class("-viewing")
        status = text_of(app.query_one("#status", Static))
        assert status.startswith("SAVED LOBBY") and "Ascent" in status and "back to the live lobby" in status
        assert app.query_one("#players", DataTable).row_count == 10 and app.selected == "demo-0"
        await pilot.press("6")  # the graphs work on the saved lobby (names come from the snapshot)
        await pilot.pause(0.2)
        assert "Zikeyo#ivun — Profile" in text_of(app.query_one("#graph-title", Static))

        app.live_model.apply(tui.Status("live keeps loading"))  # live events don't touch the saved view
        assert app.model.status != "live keeps loading"

        await pilot.press("l")
        await pilot.pause(0.3)
        assert app.viewing is None and app.model is app.live_model and not app.has_class("-viewing")
        assert not text_of(app.query_one("#status", Static)).startswith("SAVED LOBBY")

    run(scenario, store_dir=str(tmp_path))


def test_history_screen_explains_when_nothing_is_saved_and_closes_with_escape(tmp_path):
    async def scenario(app, pilot):
        await pilot.press("h")
        await pilot.pause(0.2)
        assert isinstance(app.screen, tui.HistoryScreen)
        assert "Nothing saved yet" in text_of(app.screen.query_one("#history-empty", Static))
        await pilot.press("escape")
        await pilot.pause(0.2)
        assert not isinstance(app.screen, tui.HistoryScreen) and app.viewing is None

    async def main():
        app = tui.LobbyApp(DemoSource(delay=0), store_dir=str(tmp_path / "empty"))
        app._flush = lambda: None  # keep this lobby from being saved so the list is empty
        app._after_row = lambda event: None
        async with app.run_test(size=SIZE) as pilot:
            await loaded_app(pilot, app)
            await scenario(app, pilot)

    asyncio.run(main())


def test_without_a_store_directory_nothing_is_written_and_h_says_so(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    async def scenario(app, pilot):
        await pilot.press("h")
        await pilot.pause(0.2)
        assert not isinstance(app.screen, tui.HistoryScreen)
        assert not os.path.exists(tmp_path / "cache")

    run(scenario)


def test_reload_returns_to_the_live_lobby_and_saves_the_one_that_ended(tmp_path):
    import lobby_store

    async def scenario(app, pilot):
        await pilot.press("h")
        await pilot.pause(0.2)
        await pilot.press("enter")
        await pilot.pause(0.3)
        assert app.viewing is not None
        await pilot.press("r")
        await pilot.pause(0.3)
        assert app.viewing is None and app.model is app.live_model
        assert lobby_store.list_saved(str(tmp_path))

    run(scenario, store_dir=str(tmp_path))


def test_list_view_detail_strip_follows_the_selected_player():
    async def scenario(app, pilot):
        card = text_of(app.query_one("#detail-card", Static))
        more = text_of(app.query_one("#detail-more", Static))
        first = app.model.rows[app.selected].name
        assert first in card and "Lobby leaders" in card and "Profile vs" in more
        await pilot.press("down")
        await pilot.pause(0.1)
        assert app.model.rows[app.selected].name in text_of(app.query_one("#detail-card", Static))

    run(scenario)


def test_compare_graph_pits_you_against_the_selected_player():
    async def scenario(app, pilot):
        await pilot.press("9")
        await pilot.pause(0.2)
        assert app.graph == "compare"
        me = next(r for r in app.model.ordered if r.is_self)
        assert app.selected == me.puuid
        assert "That's you" in text_of(app.query_one("#g-compare", Static))
        await pilot.press("down")
        await pilot.pause(0.1)
        body = text_of(app.query_one("#g-compare", Static))
        assert "You vs" in body and "Consistency" in body and "gap" in body

    run(scenario)


def test_sort_and_show_keys_reorder_and_filter_the_players_table():
    async def scenario(app, pilot):
        table = app.query_one("#players", DataTable)
        default = [row.puuid for row in app.model.ordered]
        await pilot.press("o")  # sort: Rank
        await pilot.pause(0.1)
        order = [app._shown_rows()[i].puuid for i in range(table.row_count)]
        tiers = [app.model.rows[p].tier or 0 for p in order]
        assert tiers == sorted(tiers, reverse=True) and "sort: Rank" in text_of(app.query_one("#summary", Static))
        await pilot.press("f", "f")  # show: Your team, then Enemies
        await pilot.pause(0.1)
        assert table.row_count == sum(1 for r in app.model.ordered if not r.ally)
        assert "show: Enemies" in text_of(app.query_one("#summary", Static))
        assert app.selected in [r.puuid for r in app._shown_rows()]
        await pilot.press("f")  # back to everyone
        await pilot.pause(0.1)
        assert table.row_count == len(default)

    run(scenario)


def test_saved_lobby_list_defaults_to_played_games_and_f_widens_it(tmp_path):
    import lobby_store

    async def scenario(app, pilot):
        await pilot.pause(0.3)
        base = lobby_store.list_saved(str(tmp_path))[0]
        for name, extra in (("dodge", {"state": "PREGAME"}), ("imp", {"imported": True})):
            snapshot = lobby_store.load(base["path"])
            snapshot.update(extra, match_id=name, started_at=base["started_at"] - 100)
            lobby_store.save(str(tmp_path), snapshot)
        await pilot.press("h")
        await pilot.pause(0.3)
        table = app.screen.query_one("#history-table", DataTable)
        assert table.row_count == 1
        await pilot.press("f")  # Everything
        await pilot.pause(0.1)
        assert table.row_count == 3 and "Everything (3 of 3)" in text_of(app.screen.query_one("#history-title", Static))

    run(scenario, store_dir=str(tmp_path))


def test_agent_select_alone_is_not_saved(tmp_path):
    from lobby_data import LobbyReset, PlayerRow

    class AgentSelect:
        agent_names, map_names = {}, {}

        def run(self, emit, stop):
            rows = [PlayerRow(puuid=f"p{i}", name=f"A{i}#1", ally=True, agent="Jett", stats_state="done",
                              history_state="done") for i in range(2)]
            emit(LobbyReset(state="PREGAME", rows=rows, map_name="Ascent"))
            stop.wait(30)

    async def main():
        app = tui.LobbyApp(AgentSelect(), store_dir=str(tmp_path))
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause(0.5)
            app._dirty = True
            app._flush()
        assert os.listdir(tmp_path) == []

    asyncio.run(main())


def test_threat_column_and_strip_show_and_the_t_sort_orders_by_threat():
    async def scenario(app, pilot):
        table = app.query_one("#players", DataTable)
        labels = [str(table.columns[key].label) for key in app._column_keys]
        assert labels[-2:] == ["Threat", "AESUOC"]
        assert text_of(app.query_one("#summary", Static)).splitlines()[-1].startswith("ENEMY THREATS")
        scores = [(app._threats.get(r.puuid) or {}).get("score") for r in app.model.ordered]
        assert any(score is not None for score in scores)
        for _ in range(len(tui.SORTS)):  # cycle to the Threat sort
            await pilot.press("o")
            if tui.SORTS[app.sort_index][0] == "threat":
                break
        await pilot.pause(0.1)
        shown = [(app._threats.get(r.puuid) or {}).get("score") or -1 for r in app._shown_rows()]
        assert shown == sorted(shown, reverse=True)
        await pilot.press("f", "f")  # hide the allies, then check a late refresh doesn't trip over missing rows
        app._refresh_prints()

    run(scenario)
