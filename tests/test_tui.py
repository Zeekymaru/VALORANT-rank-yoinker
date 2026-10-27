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
        switcher = app.query_one(ContentSwitcher)
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
