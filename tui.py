"""Textual TUI for vRY: a live lobby table plus a graph panel you switch with buttons or keys.

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
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, ContentSwitcher, DataTable, Footer, Static

from lobby_data import DemoSource, LobbyModel, Status
from tui_views import (COLUMNS, GRAPHS, agents_view, form_view, row_cells, rr_series, rr_view, sides_view,
                       team_strip, teams_view)

try:  # optional: real charts for the RR trend (pip install -r requirements-tui-charts.txt)
    from textual_plotext import PlotextPlot
except ImportError:  # pragma: no cover - depends on the environment
    PlotextPlot = None

STATE_LABELS = {"INGAME": "In-Game", "PREGAME": "Agent Select", "MENUS": "In-Menus"}


class LobbyApp(App):
    TITLE = "vRY lobby"
    CSS = """
    #status { height: 1; padding: 0 1; background: $boost; }
    #summary { height: 2; padding: 0 1; }
    #body { height: 1fr; }
    #players { width: 3fr; }
    #side { width: 2fr; min-width: 46; padding: 0 1; border-left: solid $primary-darken-2; }
    #graph-buttons { height: 3; }
    #graph-buttons Button { min-width: 9; margin-right: 1; }
    #graph-title { height: 1; text-style: bold; margin-bottom: 1; }
    #graphs { height: 1fr; }
    #rr-plot { height: 14; }
    """
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        *[Binding(str(number), f"graph('{key}')", label) for number, (key, label) in enumerate(GRAPHS, 1)],
    ]

    def __init__(self, source, **kwargs):
        super().__init__(**kwargs)
        self.source = source
        self.model = LobbyModel()
        self.stop_event = threading.Event()
        self.selected = None  # puuid of the highlighted row
        self.graph = GRAPHS[0][0]
        self._column_keys = []

    # --- layout -------------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static(id="status")
        yield Static(id="summary")
        with Horizontal(id="body"):
            yield DataTable(id="players")
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

    def handle_event(self, event):
        kind = self.model.apply(event)
        if kind == "reset":
            self._rebuild_table()
        elif kind == "row":
            self._update_row(event.puuid)
        self._refresh_chrome()
        if kind in ("reset", "row"):
            self._refresh_graph()

    # --- players table --------------------------------------------------------------------

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

    def _update_row(self, puuid):
        row = self.model.rows.get(puuid)
        if row is None:
            return
        table = self.query_one("#players", DataTable)
        for column_key, cell in zip(self._column_keys, row_cells(row)):
            table.update_cell(puuid, column_key, cell, update_width=True)

    def on_data_table_row_highlighted(self, event):
        if event.row_key is not None and event.row_key.value is not None:
            self.selected = event.row_key.value
            self._refresh_graph()

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
        if event.button.id and event.button.id.startswith("btn-"):
            self.show_graph(event.button.id[len("btn-"):])
            self.query_one("#players", DataTable).focus()  # keep the arrow keys moving through players

    def _refresh_graph(self):
        row = self.model.rows.get(self.selected)
        label = dict(GRAPHS)[self.graph]
        if self.graph == "teams":
            title, renderable = "Lobby", teams_view(self.model.ordered)
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
