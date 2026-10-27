"""Textual TUI for vRY: a live lobby (compact list or player cards) plus a graph panel you switch with buttons or keys.

    python tui.py          live lobby (VALORANT must be running)
    python tui.py --demo   fake lobby with realistic numbers, no VALORANT needed

Needs the optional requirements: pip install -r requirements-tui.txt (charts: requirements-tui-charts.txt).
The console app (main.py) is untouched and still works as before."""
import argparse
import threading

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.widgets import Button, ContentSwitcher, DataTable, Footer, Static

from lobby_data import DemoSource, LobbyModel, Status
from tui_views import (COLUMNS, GRAPHS, agents_view, card_text, form_view, profile_view, row_cells, rr_series, rr_view,
                       sides_view, team_strip, teams_view)

try:  # optional: real charts for the RR trend (pip install -r requirements-tui-charts.txt)
    from textual_plotext import PlotextPlot
except ImportError:  # pragma: no cover - depends on the environment
    PlotextPlot = None

STATE_LABELS = {"INGAME": "In-Game", "PREGAME": "Agent Select", "MENUS": "In-Menus"}
VIEWS = {"list": "players", "cards": "cards"}  # view name -> id of the widget that shows it
CARD_WIDTH = 40  # columns per card, including its border and gap


class PlayerCard(Static, can_focus=True):
    """One player as a card. Focusing or clicking it selects the player; the arrow keys move between cards."""

    BINDINGS = [
        Binding("left", "step(-1, 0)", "Previous", show=False),
        Binding("right", "step(1, 0)", "Next", show=False),
        Binding("up", "step(0, -1)", "Up", show=False),
        Binding("down", "step(0, 1)", "Down", show=False),
    ]

    def __init__(self, puuid, content, **kwargs):
        super().__init__(content, **kwargs)
        self.puuid = puuid

    def on_click(self):
        self.app.select_player(self.puuid, focus_card=True)

    def on_focus(self):
        self.app.select_player(self.puuid)

    def action_step(self, dx: int, dy: int):
        self.app.step_selection(dx, dy)


class CardView(VerticalScroll):
    """Your team's cards, then the enemy team's, each in a grid that fits as many columns as the width allows."""

    columns = 1

    def compose(self) -> ComposeResult:
        yield Static("YOUR TEAM", id="ally-title", classes="team-title")
        yield Grid(id="cards-ally", classes="card-grid")
        yield Static("ENEMY TEAM", id="enemy-title", classes="team-title")
        yield Grid(id="cards-enemy", classes="card-grid")

    def on_resize(self, event):
        self.fit_columns()

    def fit_columns(self):
        self.columns = max(1, (self.size.width - 2) // CARD_WIDTH)
        for grid in self.query(Grid):
            grid.styles.grid_size_columns = self.columns


class LobbyApp(App):
    TITLE = "vRY lobby"
    CSS = """
    #topbar { height: 3; }
    #status { width: 1fr; height: 3; padding: 0 1; background: $boost; content-align: left middle; }
    #btn-view { min-width: 22; }
    #summary { height: 2; padding: 0 1; }
    #body { height: 1fr; }
    #views { width: 3fr; }
    LobbyApp.-cards #views { width: 4fr; }
    #side { width: 2fr; min-width: 46; padding: 0 1; border-left: solid $primary-darken-2; }
    #graph-buttons { height: 3; }
    #graph-buttons Button { min-width: 9; margin-right: 1; }
    #graph-title { height: 1; text-style: bold; margin-bottom: 1; }
    #graphs { height: 1fr; }
    #rr-plot { height: 14; }
    .team-title { height: 1; margin-top: 1; padding: 0 1; text-style: bold; color: $text-muted; }
    .card-grid { grid-size: 2; grid-rows: auto; grid-gutter: 0 1; height: auto; padding: 0 1; }
    PlayerCard { height: auto; min-height: 9; padding: 0 1; border: round $primary-darken-3; }
    PlayerCard.-selected { border: round $accent; }
    PlayerCard:focus { border: heavy $accent; }
    """
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("v", "toggle_view", "List/Cards"),
        *[Binding(str(number), f"graph('{key}')", label) for number, (key, label) in enumerate(GRAPHS, 1)],
    ]

    def __init__(self, source, **kwargs):
        super().__init__(**kwargs)
        self.source = source
        self.model = LobbyModel()
        self.stop_event = threading.Event()
        self.selected = None  # puuid of the highlighted player, in either view
        self.graph = GRAPHS[0][0]
        self.view = "list"
        self._column_keys = []
        self._cards = {}

    # --- layout -------------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Horizontal(id="topbar"):
            yield Static(id="status")
            yield Button("v View: List", id="btn-view")
        yield Static(id="summary")
        with Horizontal(id="body"):
            with ContentSwitcher(initial=VIEWS["list"], id="views"):
                yield DataTable(id="players")
                yield CardView(id="cards")
            with Vertical(id="side"):
                with Horizontal(id="graph-buttons"):
                    for number, (key, label) in enumerate(GRAPHS, 1):
                        yield Button(f"{number} {label}", id=f"btn-{key}")
                yield Static(id="graph-title")
                with ContentSwitcher(initial=f"g-{GRAPHS[0][0]}", id="graphs"):
                    for key, _ in GRAPHS:
                        if key == "rr" and PlotextPlot is not None:
                            with Vertical(id="g-rr"):
                                yield Static(id="rr-text")
                                yield PlotextPlot(id="rr-plot")
                        else:
                            yield Static(id=f"g-{key}")
        yield Footer()

    def on_mount(self):
        table = self.query_one("#players", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        self._column_keys = list(table.add_columns(*COLUMNS))
        table.focus()
        self.show_graph(self.graph)
        self._refresh_chrome()
        self.run_source()

    def on_unmount(self):
        self.stop_event.set()

    # --- data source (runs in a worker thread) -------------------------------------------

    @work(thread=True, exclusive=True, group="source")
    def run_source(self):
        try:
            self.source.run(self._emit, self.stop_event)
        except Exception as exc:  # keep the screen up and say what happened
            self._emit(Status(f"Data source stopped: {exc!r}"))

    def _emit(self, event):
        try:
            self.call_from_thread(self.handle_event, event)
        except Exception:  # the app is closing
            pass

    async def handle_event(self, event):
        kind = self.model.apply(event)
        if kind == "reset":
            self._rebuild_table()
            await self._rebuild_cards()
        elif kind == "row":
            self._update_row(event.puuid)
        self._refresh_chrome()
        if kind in ("reset", "row"):
            self._refresh_graph()

    # --- the two views ----------------------------------------------------------------------

    def _rebuild_table(self):
        table = self.query_one("#players", DataTable)
        table.clear()
        for row in self.model.ordered:
            table.add_row(*row_cells(row), key=row.puuid)
        puuids = [row.puuid for row in self.model.ordered]
        if self.selected not in puuids:
            self.selected = puuids[0] if puuids else None
        if puuids:
            table.move_cursor(row=puuids.index(self.selected))

    async def _rebuild_cards(self):
        view = self.query_one("#cards", CardView)
        ally_grid, enemy_grid = self.query_one("#cards-ally", Grid), self.query_one("#cards-enemy", Grid)
        await ally_grid.remove_children()
        await enemy_grid.remove_children()
        self._cards = {}
        for row in self.model.ordered:
            card = PlayerCard(row.puuid, self._card_content(row), id=f"card-{len(self._cards)}")
            self._cards[row.puuid] = card
            await (ally_grid if row.ally else enemy_grid).mount(card)
        has_enemy = any(not row.ally for row in self.model.ordered)
        self.query_one("#enemy-title").display = has_enemy
        enemy_grid.display = has_enemy
        view.fit_columns()
        self._mark_selected()

    def _card_content(self, row):
        return card_text(row, self.source.agent_names, self.model.map_name)

    def _update_row(self, puuid):
        row = self.model.rows.get(puuid)
        if row is None:
            return
        table = self.query_one("#players", DataTable)
        for column_key, cell in zip(self._column_keys, row_cells(row)):
            table.update_cell(puuid, column_key, cell, update_width=True)
        card = self._cards.get(puuid)
        if card is not None:
            card.update(self._card_content(row))

    def action_toggle_view(self):
        self.view = "cards" if self.view == "list" else "list"
        self.query_one("#views", ContentSwitcher).current = VIEWS[self.view]
        self.set_class(self.view == "cards", "-cards")  # the cards get more of the width (more per row)
        self.query_one("#btn-view", Button).label = f"v View: {'Cards' if self.view == 'cards' else 'List'}"
        self._focus_active_view()

    def _focus_active_view(self):
        if self.view == "cards" and self.selected in self._cards:
            self._cards[self.selected].focus()
        else:
            self.query_one("#players", DataTable).focus()

    # --- selection (shared by both views) ---------------------------------------------------

    def select_player(self, puuid, focus_card=False):
        if puuid in self.model.rows and puuid != self.selected:
            self.selected = puuid
            table = self.query_one("#players", DataTable)
            order = [row.puuid for row in self.model.ordered]
            if table.cursor_row != order.index(puuid):
                table.move_cursor(row=order.index(puuid))
            self._mark_selected()
            self._refresh_graph()
        if focus_card and puuid in self._cards:
            self._cards[puuid].focus()

    def _mark_selected(self):
        for puuid, card in self._cards.items():
            card.set_class(puuid == self.selected, "-selected")

    def _card_positions(self):
        """puuid -> (row, column) in the card layout: your team's grid first, then the enemy team's."""
        columns = self.query_one("#cards", CardView).columns
        positions, row_offset = {}, 0
        for ally in (True, False):
            group = [r.puuid for r in self.model.ordered if r.ally == ally]
            for index, puuid in enumerate(group):
                positions[puuid] = (row_offset + index // columns, index % columns)
            row_offset += -(-len(group) // columns)  # rows used, rounded up
        return positions

    def step_selection(self, dx, dy):
        """Arrow keys in the card view: left/right walk the cards in order, up/down move one grid row."""
        order = [row.puuid for row in self.model.ordered]
        if self.selected not in order:
            return
        index = order.index(self.selected)
        if dx:
            target = order[max(0, min(len(order) - 1, index + dx))]
        else:
            positions = self._card_positions()
            row, column = positions[self.selected]
            candidates = [p for p, (r, _) in positions.items() if r == row + dy]
            if not candidates:
                return
            target = min(candidates, key=lambda p: abs(positions[p][1] - column))
        self.select_player(target, focus_card=True)

    def on_data_table_row_highlighted(self, event):
        if event.row_key is None or event.row_key.value is None:
            return
        if event.cursor_row != event.data_table.cursor_row:
            return  # stale: the table was cleared or rebuilt since this event was posted
        try:
            self.select_player(event.row_key.value)
        except NoMatches:  # a late event while the app is shutting down
            pass

    # --- status, summary, graphs ----------------------------------------------------------

    def _refresh_chrome(self):
        model = self.model
        stats_done, history_done, total, history_total = model.progress()
        head = " · ".join(part for part in (STATE_LABELS.get(model.state, model.state), model.map_name, model.mode) if part)
        counts = f"   ranks {stats_done}/{total}" if total else ""
        if history_total:
            counts += f" · history {history_done}/{history_total}"
        self.query_one("#status", Static).update(Text(f"{head or 'Waiting'}{counts}   {model.status}"))
        self.query_one("#summary", Static).update(team_strip(model.ordered))

    def show_graph(self, key):
        self.graph = key
        self.query_one("#graphs", ContentSwitcher).current = f"g-{key}"
        for other, _ in GRAPHS:
            self.query_one(f"#btn-{other}", Button).variant = "primary" if other == key else "default"
        self._refresh_graph()

    def action_graph(self, key: str):
        self.show_graph(key)

    def on_button_pressed(self, event: Button.Pressed):
        button_id = event.button.id or ""
        if button_id == "btn-view":
            self.action_toggle_view()
        elif button_id.startswith("btn-"):
            self.show_graph(button_id[len("btn-"):])
            self._focus_active_view()  # keep the arrow keys moving through players

    def _refresh_graph(self):
        row = self.model.rows.get(self.selected)
        label = dict(GRAPHS)[self.graph]
        if self.graph == "teams":
            title, renderable = "Lobby", teams_view(self.model.ordered)
        elif self.graph == "profile":
            title = f"{row.name} — {label}" if row else label
            renderable = profile_view(self.model.ordered, self.selected)
        elif row is None:
            title, renderable = label, Text("No player selected yet.", style="dim")
        else:
            summary = row.history if row.history_state == "done" else None
            names, maps = self.source.agent_names, self.source.map_names
            title = f"{row.name} — {label}"
            renderable = {
                "form": lambda: form_view(summary, names, maps),
                "sides": lambda: sides_view(summary),
                "agents": lambda: agents_view(summary, names),
                "rr": lambda: rr_view(summary),
            }[self.graph]()
            if self.graph == "rr":
                self._refresh_rr_plot(summary)
        self.query_one("#graph-title", Static).update(Text(title, style="bold"))
        target = "#rr-text" if self.graph == "rr" and PlotextPlot is not None else f"#g-{self.graph}"
        self.query_one(target, Static).update(renderable)

    def _refresh_rr_plot(self, summary):
        if PlotextPlot is None:
            return
        try:
            plot = self.query_one("#rr-plot", PlotextPlot)
            series = rr_series(summary)
            plt = plot.plt
            plt.clear_data()
            if series:
                net, total = [0], 0
                for change in series:
                    total += change
                    net.append(total)
                plt.plot(net, marker="braille")
                plt.title("Net RR (oldest → newest)")
            plot.refresh()
        except Exception:  # a chart problem must never take the screen down
            pass

    # --- actions ----------------------------------------------------------------------------

    def action_refresh(self):
        request = getattr(self.source, "request_refresh", None)
        if request:
            request()
            self.model.apply(Status("Refreshing…"))
            self._refresh_chrome()

    async def action_quit(self):
        self.stop_event.set()
        self.exit()


def main(argv=None):
    parser = argparse.ArgumentParser(description="vRY lobby TUI")
    parser.add_argument("--demo", action="store_true", help="show a fake lobby (no VALORANT needed)")
    args = parser.parse_args(argv)
    if args.demo:
        source = DemoSource()
    else:
        from lobby_live import LiveLobbySource

        print("Connecting to VALORANT… (start the game and log in if this waits)")
        source = LiveLobbySource.connect()
    LobbyApp(source).run()


if __name__ == "__main__":
    main()
