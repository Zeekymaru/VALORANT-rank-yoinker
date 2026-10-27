"""UI-agnostic lobby data for the TUI: the row model, the events a data source emits, a
model that applies them, and a demo source. No Textual import and no network here, so all of
it is testable on its own. The live source lives in lobby_live.py."""
import re
import threading
from dataclasses import dataclass, fields
from typing import Any, Callable, Optional

from src.constants import NUMBERTORANKS, PARTYICONLIST, SHORT_NUMBERTORANKS

_COLR = re.compile(r"\x1b\[38;2;(\d+);(\d+);(\d+)m(.*?)\x1b\[0m", re.S)

ALLY_RGB = (76, 151, 237)
ENEMY_RGB = (238, 77, 77)
SELF_RGB = (221, 224, 41)


def parse_colr(text):
    """('plain text', (r, g, b) or None) from a string made by colr.color(..., fore=(r, g, b))."""
    match = _COLR.search(str(text))
    if not match:
        return str(text), None
    return match.group(4), (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def readable_rgb(rgb, floor=95):
    """Lift colors too dark to see on a dark background (e.g. the Unranked grey 46,46,46)."""
    if rgb is None:
        return None
    lift = max(0, floor - max(rgb))
    return tuple(min(255, channel + lift) for channel in rgb)


def rank_label(tier, short=False):
    """(name, rgb) for a competitive tier index, from the same tables the console table uses."""
    table = SHORT_NUMBERTORANKS if short else NUMBERTORANKS
    try:
        text, rgb = parse_colr(table[int(tier)])
    except (TypeError, ValueError, IndexError):
        return "?", None
    return text, readable_rgb(rgb)


def party_rgb(index):
    """Color of the nth (1-based) premade group's square, from PARTYICONLIST."""
    if not 1 <= index <= len(PARTYICONLIST):
        return None
    return readable_rgb(parse_colr(PARTYICONLIST[index - 1])[1]) or (200, 200, 200)


@dataclass
class PlayerRow:
    puuid: str
    name: str = ""
    team: str = ""  # "Red" / "Blue"; empty in menus
    ally: bool = True
    is_self: bool = False
    agent_id: str = ""
    agent: str = ""
    locked: bool = True  # False while the agent is only hovered in agent select
    party: int = 0  # 1.. = premade group, 0 = none known
    level: Optional[int] = None
    tier: Optional[int] = None
    rank: str = ""
    rank_rgb: Optional[tuple] = None
    rr: Any = None
    peak: str = ""
    peak_rgb: Optional[tuple] = None
    leaderboard: int = 0
    hs: Any = None  # int or "N/A"
    kd: Any = None
    wr: Any = None  # season win rate, int or "N/A"
    games: int = 0  # season games
    rr_delta: Any = None  # RR earned in the last game, or "N/A"
    history: Optional[dict] = None  # history.summarise() result
    stats_state: str = "pending"  # pending -> done
    history_state: str = "pending"  # pending -> done


_ROW_FIELDS = {f.name for f in fields(PlayerRow)}


@dataclass
class LobbyReset:
    """A new lobby: clear the table and show these rows (names/agents known, the rest still loading)."""
    state: str
    rows: list
    map_name: str = ""
    map_id: str = ""
    mode: str = ""
    server: str = ""


@dataclass
class PlayerUpdate:
    puuid: str
    fields: dict


@dataclass
class Status:
    text: str


class LobbyModel:
    """What the screen shows: the current lobby's rows in display order plus a status line."""

    def __init__(self):
        self.state = ""
        self.map_name = ""
        self.map_id = ""
        self.mode = ""
        self.server = ""
        self.status = "Starting…"
        self.rows = {}

    def apply(self, event):
        """Apply a source event; returns the kind of change: 'reset', 'row', 'status' or ''."""
        if isinstance(event, LobbyReset):
            self.state, self.map_name, self.map_id = event.state, event.map_name, event.map_id
            self.mode, self.server = event.mode, event.server
            self.rows = {row.puuid: row for row in event.rows}
            return "reset"
        if isinstance(event, PlayerUpdate):
            row = self.rows.get(event.puuid)
            if row is None:
                return ""
            for key, value in event.fields.items():
                if key in _ROW_FIELDS:
                    setattr(row, key, value)
            return "row"
        if isinstance(event, Status):
            self.status = event.text
            return "status"
        return ""

    @property
    def ordered(self):
        return list(self.rows.values())

    def progress(self):
        """(ranks loaded, history loaded, rows, rows that will get history) — skipped rows don't count."""
        rows = self.ordered
        return (sum(r.stats_state == "done" for r in rows),
                sum(r.history_state == "done" for r in rows), len(rows),
                sum(r.history_state != "skipped" for r in rows))


# --- demo source -------------------------------------------------------------------------

_DEMO_AGENTS = {  # real agent ids (see history.AGENT_ROLES), display names
    "add6443a-41bd-e414-f6ad-e58d267f4e95": "Jett", "569fdd95-4d10-43ab-ca70-79becc718b46": "Sage",
    "6f2a04ca-43e0-be17-7f36-b3908627744d": "Skye", "320b2a48-4d9b-a075-30f1-1f93a9b638fa": "Sova",
    "707eab51-4836-f488-046a-cda6bf494859": "Viper", "a3bfb853-43b2-7238-a4f1-ad90e9e46bcc": "Reyna",
    "1dbf2edd-4729-0984-3115-daa5eed44993": "Clove", "7c8a4701-4de6-9355-b254-e09bc2a34b72": "Miks",
    "8e253930-4c05-31dd-1b6c-968525494517": "Omen", "eb93336a-449b-9c1b-0a54-a891f7921d69": "Phoenix",
    "0e38b510-41a8-5780-5e8f-568b2a4f2d6c": "Iso", "92eeef5d-43b5-1d4a-8d03-b3927a09034b": "Veto",
    "df1cb487-4902-002e-5c17-d28e83e78588": "Waylay",
}
DEMO_MAP_ID = "/Game/Maps/Ascent/Ascent"
DEMO_MAPS = {"/game/maps/ascent/ascent": "Ascent", "/game/maps/triad/triad": "Haven",
             "/game/maps/jam/jam": "Lotus"}

# name, team, agent, tier, rr, peak tier, level, party, [(agent, won, map, atk, def, rr), ...] newest first
_DEMO_PLAYERS = [
    ("Zikeyo#ivun", "Blue", "Viper", 19, 85, 23, 322, 1, [
        ("Sova", True, "ascent", (7, 12), (6, 8), 21), ("Skye", True, "triad", (6, 11), (7, 9), 18),
        ("Viper", True, "ascent", (8, 12), (5, 9), 22), ("Sova", False, "jam", (4, 10), (6, 13), -17),
        ("Skye", False, "triad", (5, 12), (3, 12), -20)]),
    ("Echo#09110", "Blue", "Skye", 19, 0, 20, 559, 1, [
        ("Clove", False, "ascent", (5, 12), (4, 11), -25), ("Iso", True, "triad", (9, 12), (4, 6), 19),
        ("Clove", False, "jam", (3, 9), (5, 14), -22), ("Skye", True, "ascent", (6, 12), (7, 8), 20),
        ("Clove", False, "triad", (4, 10), (4, 12), -18)]),
    ("IDontLikeSand#UwU", "Blue", "Reyna", 11, 0, 11, 315, 0, [
        ("Reyna", True, "jam", (7, 13), (6, 6), 24), ("Reyna", True, "ascent", (6, 11), (7, 9), 19),
        ("Reyna", True, "triad", (8, 12), (5, 8), 21), ("Reyna", False, "jam", (3, 10), (4, 13), -16),
        ("Reyna", False, "triad", (5, 11), (3, 12), -19)]),
    ("Player", "Blue", "Jett", 16, 27, 17, 126, 0, [
        ("Veto", False, "ascent", (4, 12), (5, 10), -20), ("Waylay", True, "jam", (8, 12), (5, 7), 23),
        ("Sage", True, "triad", (6, 12), (7, 9), 18), ("Veto", False, "ascent", (5, 11), (3, 12), -15),
        ("Veto", True, "jam", (7, 12), (6, 9), 20)]),
    ("ArmaBlanket#gloom", "Blue", "Sage", 13, 10, 14, 0, 0, [
        ("Miks", True, "ascent", (7, 12), (6, 8), 22), ("Sage", True, "jam", (8, 13), (5, 7), 21),
        ("Miks", True, "triad", (6, 11), (7, 9), 19), ("Sage", True, "ascent", (9, 12), (4, 6), 25),
        ("Sage", False, "jam", (5, 12), (4, 11), -14)]),
    ("Re1#Han", "Red", "Sage", 12, 10, 16, 430, 0, [
        ("Sage", True, "ascent", (8, 12), (5, 8), 21), ("Reyna", True, "jam", (7, 12), (6, 9), 18),
        ("Sage", True, "triad", (6, 11), (7, 9), 20), ("Phoenix", True, "ascent", (9, 12), (4, 7), 22),
        ("Sage", False, "jam", (4, 12), (5, 11), -17)]),
    ("Violence#end", "Red", "Omen", 11, 54, 14, 204, 2, [
        ("Omen", False, "ascent", (5, 12), (3, 11), -12), ("Omen", True, "triad", (7, 12), (6, 8), 16),
        ("Phoenix", False, "jam", (4, 11), (5, 13), -14), ("Omen", True, "ascent", (8, 12), (5, 8), 19),
        ("Sage", False, "triad", (3, 10), (4, 12), -15)]),
    ("Askeladd#roman", "Red", "Reyna", 14, 61, 15, 148, 2, [
        ("Jett", False, "ascent", (3, 11), (4, 12), -20), ("Sage", False, "jam", (4, 12), (3, 11), -18),
        ("Omen", False, "triad", (5, 12), (4, 12), -16), ("Jett", False, "ascent", (3, 10), (5, 13), -19),
        ("Jett", False, "jam", (4, 12), (3, 11), -17)]),
    ("Hidden#0001", "Red", "Phoenix", 3, 0, 3, 40, 0, None),
    ("Newbie#new", "Red", "Jett", 0, 0, 0, 12, 0, []),
]


def _demo_match_stats(seed, role, won, rounds):
    """Plausible per-match counts, shaped by role so the demo radars differ between players."""
    import random
    rng = random.Random(seed)
    duel, util = role == "Duelist", role in ("Controller", "Sentinel", "Initiator")
    kills = round(rounds * rng.uniform(0.5, 0.95) * (1.15 if duel else 1.0) * (1.1 if won else 0.9))
    deaths = round(rounds * rng.uniform(0.55, 0.85))
    return {"rounds": rounds, "score": round(rounds * rng.uniform(150, 270) * (1.1 if won else 0.9)),
            "kills": kills, "deaths": deaths, "assists": round(rounds * rng.uniform(0.1, 0.35)),
            "damage": round(rounds * rng.uniform(110, 170) * (1.1 if duel else 1.0)),
            "headshots": round(kills * 1.4), "bodyshots": round(kills * 3.2), "legshots": round(kills * 0.3),
            "first_bloods": round(rounds * rng.uniform(0.05, 0.2 if duel else 0.1)),
            "first_deaths": round(rounds * rng.uniform(0.04, 0.16 if duel else 0.1)),
            "kast_rounds": round(rounds * rng.uniform(0.6, 0.82)),
            "casts": round(rounds * rng.uniform(2.0, 4.5 if util else 2.5)),
            "plants": rng.randint(0, 3), "defuses": rng.randint(0, 1)}


def _demo_summary(history_rows, agent_ids):
    """Build a history.summarise()-shaped dict from compact demo tuples."""
    import history
    import match_stats
    matches, agents, roles, wins = [], {}, {}, 0
    atk = [0, 0]
    dfn = [0, 0]
    for agent, won, map_key, a, d, rr in history_rows:
        agent_id = agent_ids[agent]
        role = history.AGENT_ROLES.get(agent_id, history.UNKNOWN_ROLE)
        matches.append({"id": f"demo-{len(matches)}", "agent": agent_id, "won": won,
                        "map": f"/game/maps/{map_key}/{map_key}", "attack": list(a), "defense": list(d),
                        "rr": rr, "stats": _demo_match_stats(f"{agent}{len(matches)}{a}{d}", role, won,
                                                             a[1] + d[1] or 20)})
        stats = agents.setdefault(agent_id, [0, 0])
        stats[0] += 1
        stats[1] += int(won)
        role = history.AGENT_ROLES.get(agent_id, history.UNKNOWN_ROLE)
        roles[role] = roles.get(role, 0) + 1
        wins += int(won)
        atk[0] += a[0]
        atk[1] += a[1]
        dfn[0] += d[0]
        dfn[1] += d[1]
    top = sorted(agents.items(), key=lambda kv: -kv[1][0])[:history.TOP_AGENT_COUNT]
    return {"available": True, "games": len(matches), "wins": wins, "roles": roles,
            "top_agents": [{"agent_id": a, "games": g, "wins": w} for a, (g, w) in top],
            "attack": {"won": atk[0], "rounds": atk[1]}, "defense": {"won": dfn[0], "rounds": dfn[1]},
            "matches": matches, "stats": match_stats.total([m["stats"] for m in matches])}


class DemoSource:
    """Fake lobby with realistic numbers, so the TUI can be tried without VALORANT running."""

    def __init__(self, delay=0.35):
        self.delay = delay
        self.agent_names = {agent_id: name for agent_id, name in _DEMO_AGENTS.items()}
        self.map_names = dict(DEMO_MAPS)
        self._refresh = threading.Event()

    def request_refresh(self):
        self._refresh.set()

    def run(self, emit: Callable, stop: threading.Event):
        import history
        by_name = {name: agent_id for agent_id, name in _DEMO_AGENTS.items()}
        while not stop.is_set():
            rows = []
            for name, team, agent, tier, rr, peak, level, party, _ in _DEMO_PLAYERS:
                rows.append(PlayerRow(
                    puuid=f"demo-{len(rows)}", name=name, team=team, ally=(team == "Blue"),
                    is_self=(len(rows) == 0), agent_id=by_name[agent], agent=agent,
                    level=level or None, party=party))
            emit(LobbyReset(state="INGAME", rows=rows, map_name="Ascent", map_id=DEMO_MAP_ID,
                            mode="Competitive", server="demo"))
            emit(Status("Loading ranks…"))
            for row, spec in zip(rows, _DEMO_PLAYERS):
                _, _, _, tier, rr, peak, _, _, _ = spec
                label, rgb = rank_label(tier)
                peak_label, peak_rgb = rank_label(peak)
                seed = sum(map(ord, row.name))  # stable, unlike hash()
                emit(PlayerUpdate(row.puuid, {
                    "tier": tier, "rank": label, "rank_rgb": rgb, "rr": rr, "peak": peak_label,
                    "peak_rgb": peak_rgb, "hs": 20 + seed % 20, "kd": "N/A",
                    "wr": 40 + seed % 30, "games": 10 + seed % 40,
                    "rr_delta": seed % 41 - 20, "stats_state": "done"}))
                if stop.wait(self.delay / 3):
                    return
            emit(Status("Loading match history…"))
            for row, spec in zip(rows, _DEMO_PLAYERS):
                history_rows = spec[-1]
                if history_rows is None:
                    summary = history._unavailable(history.REASON_UNAVAILABLE)
                elif not history_rows:
                    summary = history._unavailable(history.REASON_NO_GAMES)
                else:
                    summary = _demo_summary(history_rows, by_name)
                    on_map = [m for m in summary["matches"] if m["map"] == DEMO_MAP_ID.lower()]
                    summary["map"] = {"games": len(on_map), "wins": sum(m["won"] for m in on_map)}
                emit(PlayerUpdate(row.puuid, {"history": summary, "history_state": "done"}))
                if stop.wait(self.delay):
                    return
            emit(Status("Demo data (not a real lobby) — press r to replay"))
            self._refresh.clear()
            while not stop.is_set() and not self._refresh.wait(0.2):
                pass
