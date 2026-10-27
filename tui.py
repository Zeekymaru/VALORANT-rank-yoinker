"""Textual TUI for vRY: a live lobby (compact list or player cards) plus a graph panel you switch with buttons or keys.

    python tui.py          live lobby (VALORANT must be running)
    python tui.py --demo   fake lobby with realistic numbers, no VALORANT needed

Needs the optional requirements: pip install -r requirements-tui.txt (charts: requirements-tui-charts.txt).
The console app (main.py) is untouched and still works as before."""
import argparse
import os
import threading
import time

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Button, ContentSwitcher, DataTable, Footer, Static

import history
import lobby_store
from lobby_data import DemoSource, LobbyModel, LobbyReset, Status
import player_profile
from tui_views import (COLUMNS, GRAPHS, LOBBY_GRAPHS, agents_view, card_text, fingerprint, form_view, heat_view,
                       lobby_axes, profile_view, row_cells, rr_series, rr_view, scatter_caption, scatter_fallback,
                       scatter_points, sides_view, detail_view, team_stats, team_strip, teams_view, _few_games)

try:  # optional: real charts for the RR trend (pip install -r requirements-tui-charts.txt)
    from textual_plotext import PlotextPlot
except ImportError:  # pragma: no cover - depends on the environment
    PlotextPlot = None

STATE_LABELS = {"INGAME": "In-Game", "PREGAME": "Agent Select", "MENUS": "In-Menus"}
VIEWS = {"list": "players-pane", "cards": "cards"}  # view name -> id of the widget that shows it
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


class HistoryScreen(ModalScreen):
    """The saved lobbies, newest first. Enter opens one; Escape or h closes."""

    BINDINGS = [Binding("escape", "close", "Close"), Binding("h", "close", "Close", show=False)]
    DEFAULT_CSS = """
    HistoryScreen { align: center middle; }
    #history-box { width: 92%; max-width: 130; height: 80%; border: round $accent; background: $surface; padding: 0 1; }
    #history-title { height: 1; text-style: bold; margin-bottom: 1; }
    #history-table { height: 1fr; }
    """
    COLUMNS = ("When", "Result", "Map", "Mode", "Stage", "You", "Your team", "Enemy team")

    def __init__(self, entries, **kwargs):
        super().__init__(**kwargs)
        self.entries = entries

    def compose(self) -> ComposeResult:
        with Vertical(id="history-box"):
            yield Static(f"Saved lobbies ({len(self.entries)}) · Enter opens one · Esc closes", id="history-title")
            if self.entries:
                yield DataTable(id="history-table", cursor_type="row", zebra_stripes=True)
            else:
                yield Static("Nothing saved yet. A lobby is saved automatically once its ranks and history have "
                             "loaded, and when it ends.", id="history-empty")

    def on_mount(self):
        if not self.entries:
            return
        table = self.query_one("#history-table", DataTable)
        table.add_columns(*self.COLUMNS)
        for entry in self.entries:
            summary = entry["summary"]
            table.add_row(time.strftime("%d %b %H:%M", time.localtime(entry["started_at"])), result_text(entry["result"]),
                          entry["map_name"] or "—", entry["mode"] or "—", STATE_LABELS.get(entry["state"], entry["state"]),
                          summary.get("you") or "—", summary.get("ally_avg") or "—", summary.get("enemy_avg") or "—",
                          key=entry["path"])
        table.focus()

    def on_data_table_row_highlighted(self, event):
        event.stop()  # the app's own handler is about the players table

    def on_data_table_row_selected(self, event):
        event.stop()
        self.dismiss(event.row_key.value)

    def action_close(self):
        self.dismiss(None)


def result_text(result):
    """'W 13-10 +21' / 'L 8-13 -18' for a saved lobby's result, or a dash while it isn't known."""
    if not result:
        return Text("—", style="dim")
    rr = result.get("rr")
    label = f"{'W' if result['won'] else 'L'} {result.get('score') or ''}".strip() + (f" {rr:+d}" if rr is not None else "")
    return Text(label, style="bold green" if result["won"] else "bold red")


class LobbyApp(App):
    TITLE = "vRY lobby"
    CSS = """
    #topbar { height: 3; }
    #status { width: 1fr; height: 3; padding: 0 1; background: $boost; content-align: left middle; }
    #btn-view { min-width: 22; }
    LobbyApp.-viewing #status { background: $warning-darken-2; }
    #summary { height: 2; padding: 0 1; }
    #body { height: 1fr; }
    #views { width: 3fr; }
    #players { height: auto; max-height: 14; }
    #detail { height: 1fr; border-top: solid $primary-darken-2; margin-top: 1; }
    #detail-left { width: 54; padding: 0 1; }
    #detail-right { width: 1fr; padding: 0 1; border-left: solid $primary-darken-3; }
    LobbyApp.-cards #views { width: 4fr; }
    #side { width: 2fr; min-width: 46; padding: 0 1; border-left: solid $primary-darken-2; }
    #graph-buttons { layout: grid; grid-size: 4; grid-gutter: 0 1; grid-rows: 3; height: 6; }
    #graph-buttons Button { width: 100%; min-width: 9; }
    #scatter-next { margin-bottom: 1; }
    #scatter-plot { height: 22; }
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
        Binding("s", "next_scatter", "Scatter pairing"),
        Binding("h", "history", "Saved lobbies"),
        Binding("l", "live", "Live lobby"),
        *[Binding(str(number), f"graph('{key}')", label) for number, (key, label) in enumerate(GRAPHS, 1)],
    ]

    def __init__(self, source, store_dir=None, **kwargs):
        super().__init__(**kwargs)
        self.source = source
        self.store_dir = store_dir  # where lobbies are saved and reopened from; None turns saving off
        self.live_model = LobbyModel()  # always fed by the source, even while a saved lobby is on screen
        self.model = self.live_model  # what the screen shows: the live lobby or a saved one
        self.viewing = None  # header of the saved lobby on screen, or None for live
        self.agent_names, self.map_names = source.agent_names, source.map_names
        self._dirty, self._started = False, time.time()
        self.stop_event = threading.Event()
        self.selected = None  # puuid of the highlighted player, in either view
        self.graph = GRAPHS[0][0]
        self.view = "list"
        self._column_keys = []
        self._cards = {}
        self._axes = {}  # puuid -> lobby percentiles, for the fingerprints
        self.scatter_index = 0

    # --- layout -------------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Horizontal(id="topbar"):
            yield Static(id="status")
            yield Button("v View: List", id="btn-view")
        yield Static(id="summary")
        with Horizontal(id="body"):
            with ContentSwitcher(initial=VIEWS["list"], id="views"):
                with Vertical(id="players-pane"):
                    yield DataTable(id="players")
                    with Horizontal(id="detail"):
                        yield VerticalScroll(Static(id="detail-card"), id="detail-left")
                        yield VerticalScroll(Static(id="detail-more"), id="detail-right")
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
                        elif key == "scatter" and PlotextPlot is not None:
                            with VerticalScroll(id="g-scatter"):
                                yield Static(id="scatter-text")
                                yield Button("s  Next pairing", id="scatter-next")
                                yield PlotextPlot(id="scatter-plot")
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
        if isinstance(event, LobbyReset):
            self._flush()  # the lobby that is ending is saved before the new one replaces it
            self._started = time.time()
        kind = self.live_model.apply(event)
        if kind in ("row", "reset"):
            self._dirty = True
        if kind == "row":
            self._after_row(event)
        if self.viewing is not None:  # a saved lobby is on screen: the live one keeps loading behind it
            self._refresh_chrome()
            return
        if kind == "reset":
            self._rebuild_table()
            await self._rebuild_cards()
        elif kind == "row":
            self._update_row(event.puuid)
            self._refresh_prints()
        self._refresh_chrome()
        if kind in ("reset", "row"):
            self._refresh_graph()

    # --- the two views ----------------------------------------------------------------------

    def _rebuild_table(self):
        table = self.query_one("#players", DataTable)
        table.clear()
        self._axes = lobby_axes(self.model.ordered)
        for row in self.model.ordered:
            table.add_row(*row_cells(row, self._axes.get(row.puuid)), key=row.puuid)
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
        return card_text(row, self.agent_names, self.model.map_name, self._axes.get(row.puuid))

    def _update_row(self, puuid):
        row = self.model.rows.get(puuid)
        if row is None:
            return
        table = self.query_one("#players", DataTable)
        for column_key, cell in zip(self._column_keys, row_cells(row, self._axes.get(puuid))):
            table.update_cell(puuid, column_key, cell, update_width=True)
        card = self._cards.get(puuid)
        if card is not None:
            card.update(self._card_content(row))
        self._refresh_detail()

    def _refresh_prints(self):
        """A player's rank in the lobby changes whenever anyone's history arrives, so redo every fingerprint."""
        self._axes = lobby_axes(self.model.ordered)
        table = self.query_one("#players", DataTable)
        for row in self.model.ordered:
            axes = self._axes.get(row.puuid)
            table.update_cell(row.puuid, self._column_keys[-1], fingerprint(axes, _few_games(row.history)))
            card = self._cards.get(row.puuid)
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
        if self.viewing is not None:
            when = time.strftime("%d %b %H:%M", time.localtime(self.viewing["started_at"]))
            outcome = f" · {result_text(self.viewing['result']).plain}" if self.viewing["result"] else ""
            line = f"SAVED LOBBY · {when} · {head}{outcome}   l = back to the live lobby"
            self.query_one("#status", Static).update(Text(line, style="bold"))
        else:
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
        elif button_id == "scatter-next":
            self.action_next_scatter()
            self._focus_active_view()
        elif button_id.startswith("btn-"):
            self.show_graph(button_id[len("btn-"):])
            self._focus_active_view()  # keep the arrow keys moving through players

    def _refresh_detail(self):
        """The strip under the list: the selected player's card, profile and the lobby leaders."""
        try:
            left, right = detail_view(self.model.rows.get(self.selected), self.model.ordered, self.agent_names,
                                      self.model.map_name, self._axes.get(self.selected))
            self.query_one("#detail-card", Static).update(left)
            self.query_one("#detail-more", Static).update(right)
        except NoMatches:  # shutting down
            pass

    def _refresh_graph(self):
        self._refresh_detail()
        row = self.model.rows.get(self.selected)
        label = dict(GRAPHS)[self.graph]
        if self.graph in LOBBY_GRAPHS:
            title = "Lobby"
            renderable = self._lobby_graph()
        elif self.graph == "profile":
            title = f"{row.name} — {label}" if row else label
            renderable = profile_view(self.model.ordered, self.selected)
        elif row is None:
            title, renderable = label, Text("No player selected yet.", style="dim")
        else:
            summary = row.history if row.history_state == "done" else None
            names, maps = self.agent_names, self.map_names
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
        target = f"#g-{self.graph}"
        if PlotextPlot is not None and self.graph in ("rr", "scatter"):
            target = "#rr-text" if self.graph == "rr" else "#scatter-text"
        self.query_one(target, Static).update(renderable)

    def _lobby_graph(self):
        rows = self.model.ordered
        if self.graph == "teams":
            return teams_view(rows)
        if self.graph == "heat":
            return heat_view(rows, self.selected)
        x_key, y_key = player_profile.SCATTERS[self.scatter_index % len(player_profile.SCATTERS)]
        points = scatter_points(rows, x_key, y_key, self.selected)
        caption = scatter_caption(self.scatter_index, points)
        if PlotextPlot is None:
            caption.append_text(scatter_fallback(self.scatter_index, points))
        else:
            self._draw_scatter(x_key, y_key, points)
        return caption

    def _draw_scatter(self, x_key, y_key, points):
        try:
            plot = self.query_one("#scatter-plot", PlotextPlot)
            plt = plot.plt
            plt.clear_figure()
            plt.xlabel(player_profile.METRICS[x_key][0])
            plt.ylabel(player_profile.METRICS[y_key][0])
            if len(points) >= 2:
                plt.vline(sum(p["x"] for p in points) / len(points), "gray")
                plt.hline(sum(p["y"] for p in points) / len(points), "gray")
                for ally, colour in ((True, (90, 200, 230)), (False, (235, 80, 80))):
                    group = [p for p in points if p["ally"] == ally and not p["selected"]]
                    if group:
                        plt.scatter([p["x"] for p in group], [p["y"] for p in group], color=colour, marker="●")
                chosen = [p for p in points if p["selected"]]
                if chosen:
                    plt.scatter([p["x"] for p in chosen], [p["y"] for p in chosen], color=(255, 215, 0), marker="●")
                xs, ys = [p["x"] for p in points], [p["y"] for p in points]
                span, yspan = max(xs) - min(xs) or 1, max(ys) - min(ys) or 1
                plt.xlim(min(xs) - 0.08 * span, max(xs) + 0.4 * span)  # room on the right for the labels
                plt.ylim(min(ys) - 0.1 * yspan, max(ys) + 0.1 * yspan)
                for p in points:  # label just right of the marker so it doesn't cover it
                    plt.text(p["name"][:9], p["x"] + 0.025 * span, p["y"], alignment="left",
                             color=(255, 215, 0) if p["selected"] else (150, 150, 160))
            plot.refresh()
        except Exception:  # a chart problem must never take the screen down
            pass

    def action_next_scatter(self):
        if self.graph == "scatter":
            self.scatter_index = (self.scatter_index + 1) % len(player_profile.SCATTERS)
        self.show_graph("scatter")

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

    async def action_refresh(self):
        await self.action_live()
        request = getattr(self.source, "request_refresh", None)
        if request:
            request()
            self.live_model.apply(Status("Refreshing…"))
            self._refresh_chrome()

    async def action_quit(self):
        self._flush()
        self.stop_event.set()
        self.exit()

    # --- saved lobbies ------------------------------------------------------------------------

    def _summary_for(self, model):
        rows = model.ordered
        me = next((r for r in rows if r.is_self), None)
        allies, enemies = [r for r in rows if r.ally], [r for r in rows if not r.ally]
        return {"you": me.agent if me else "", "ally_avg": team_stats(allies)["avg_rank"] or "" if allies else "",
                "enemy_avg": team_stats(enemies)["avg_rank"] or "" if enemies else ""}

    def _flush(self):
        """Save the live lobby if anything changed since the last save (never raises: saving is a convenience)."""
        model = self.live_model
        if not self.store_dir or not self._dirty or model.state not in ("INGAME", "PREGAME") or not model.rows:
            return
        self._dirty = False
        try:
            lobby_store.save(self.store_dir, lobby_store.build_snapshot(
                model, self.source.agent_names, self.source.map_names, self._started, self._summary_for(model)))
        except Exception:  # a full disk or a locked file must not take the screen down
            pass

    def _after_row(self, event):
        """Fill in a past game's result from your own history, and save the lobby once everything has loaded."""
        model = self.live_model
        row = model.rows.get(event.puuid)
        if self.store_dir and row is not None and row.is_self and row.history_state == "done" and row.history:
            try:
                lobby_store.backfill_results(self.store_dir, row.history)
            except Exception:
                pass
        stats_done, history_done, total, history_total = model.progress()
        if total and stats_done == total and history_done == history_total:
            self._flush()

    def action_history(self):
        if not self.store_dir:
            self.notify("Saving is off for this session.", severity="warning")
            return
        self.push_screen(HistoryScreen(lobby_store.list_saved(self.store_dir)), self._open_saved)

    async def _open_saved(self, path):
        if not path:
            return
        snapshot = lobby_store.load(path)
        if snapshot is None:
            self.notify("That saved lobby couldn't be read.", severity="error")
            return
        model = LobbyModel()
        model.apply(LobbyReset(state=snapshot.get("state", ""), rows=lobby_store.rows_from(snapshot),
                               map_name=snapshot.get("map_name", ""), map_id=snapshot.get("map_id", ""),
                               mode=snapshot.get("mode", ""), server=snapshot.get("server", ""),
                               match_id=snapshot.get("match_id", "")))
        self.model = model
        self.viewing = {"started_at": snapshot.get("started_at") or 0, "result": snapshot.get("result")}
        self.agent_names, self.map_names = snapshot.get("agent_names") or {}, snapshot.get("map_names") or {}
        self.add_class("-viewing")
        await self._show_model()

    async def action_live(self):
        if self.viewing is None:
            return
        self.model, self.viewing = self.live_model, None
        self.agent_names, self.map_names = self.source.agent_names, self.source.map_names
        self.remove_class("-viewing")
        await self._show_model()

    async def _show_model(self):
        """Rebuild both views from self.model (the live lobby or a saved one)."""
        self.selected = None
        self._axes = lobby_axes(self.model.ordered)
        self._rebuild_table()
        await self._rebuild_cards()
        self._refresh_chrome()
        self._refresh_graph()
        self._focus_active_view()


def main(argv=None):
    parser = argparse.ArgumentParser(description="vRY lobby TUI")
    parser.add_argument("--demo", action="store_true", help="show a fake lobby (no VALORANT needed)")
    args = parser.parse_args(argv)
    if args.demo:
        source = DemoSource()
        store_dir = os.path.join(history.CACHE_DIR, "lobbies-demo")  # kept apart from your real lobbies
    else:
        from lobby_live import LiveLobbySource

        print("Connecting to VALORANT… (start the game and log in if this waits)")
        source = LiveLobbySource.connect()
        store_dir = os.path.join(history.CACHE_DIR, "lobbies")
    LobbyApp(source, store_dir=store_dir).run()


if __name__ == "__main__":
    main()
