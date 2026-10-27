"""Headless tests of the Textual app against the demo source (skipped if Textual isn't installed).

pytest-asyncio isn't a dependency, so each test drives Textual's async test harness with asyncio.run."""
import asyncio

import pytest

pytest.importorskip("textual")

from textual.widgets import Button, ContentSwitcher, DataTable, Static  # noqa: E402

import tui  # noqa: E402
from lobby_data import DemoSource, Status  # noqa: E402

SIZE = (200, 46)


def text_of(widget):
    content = getattr(widget, "content", None)
    if content is None:
        content = getattr(widget, "renderable", "")
    return getattr(content, "plain", str(content))


async def loaded_app(pilot, app):
    for _ in range(100):
        await pilot.pause(0.1)
        if app.model.progress()[1] == 10 and app.model.status.startswith("Demo data"):
            return
    raise AssertionError(f"demo lobby never finished loading: {app.model.progress()} {app.model.status}")


def run(scenario):
    async def main():
        app = tui.LobbyApp(DemoSource(delay=0))
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
            await pilot.press(str(number))
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
        assert app.view == "list" and views.current == "players"
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
        assert app.view == "list" and views.current == "players" and not app.has_class("-cards")
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
