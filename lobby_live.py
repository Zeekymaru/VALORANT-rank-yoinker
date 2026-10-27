"""Live lobby source for the TUI.

Uses the same src/ classes as main.py (requests, rank, names, presences, ...), but polls the
local client's presence for the game state instead of using the websocket, and skips the
Discord / mobile-server extras. It emits lobby_data events; nothing here touches the screen.

NOT YET RUN AGAINST A LIVE CLIENT: the logic mirrors main.py's INGAME / PREGAME / MENUS
branches, including its streamer-mode rules for names and levels."""
import threading
import traceback
from types import SimpleNamespace

import history
from lobby_data import LobbyReset, PlayerRow, PlayerUpdate, Status, rank_label
from src.constants import gamemodes, hide_levels, hide_names

POLL_SECONDS = 2.0


class LiveLobbySource:
    def __init__(self, components):
        """components: log, requests, cfg, rank, pstats, names, presences, menu, pregame, coregame,
        agent_dict, map_urls, season_id (see connect(); tests pass fakes)."""
        self.c = components
        self.agent_names = components.agent_dict
        self.map_names = components.map_urls
        self._refresh = threading.Event()
        self._rank_cache = {}  # (match id, puuid) -> rank/stats fields, so pregame data is reused in game

    @classmethod
    def connect(cls):
        """Build the real components like main.py does. Blocks (and prints) until the client is ready."""
        import urllib3

        from src.account_manager.account_auth import AccountAuth
        from src.account_manager.account_config import AccountConfig
        from src.account_manager.account_manager import AccountManager
        from src.config import Config
        from src.constants import NUMBERTORANKS, before_ascendant_seasons, version
        from src.content import Content
        from src.errors import Error
        from src.logs import Logging
        from src.names import Names
        from src.player_stats import PlayerStats
        from src.presences import Presences
        from src.rank import Rank
        from src.requestsV import Requests
        from src.states.coregame import Coregame
        from src.states.menu import Menu
        from src.states.pregame import Pregame

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        log = Logging().log
        error = Error(log, AccountManager(log, AccountConfig, AccountAuth, NUMBERTORANKS))
        requests_ = Requests(version, log, error)
        cfg = Config(log)
        content = Content(requests_, log)
        presences = Presences(requests_, log)
        game_content = content.get_content()
        components = SimpleNamespace(
            log=log, requests=requests_, cfg=cfg, presences=presences,
            rank=Rank(requests_, log, content, before_ascendant_seasons),
            pstats=PlayerStats(requests_, log, cfg), names=Names(requests_, log),
            menu=Menu(requests_, log, presences), pregame=Pregame(requests_, log),
            coregame=Coregame(requests_, log), agent_dict=content.get_all_agents(),
            map_urls=content.get_map_urls(content.get_all_maps()),
            season_id=content.get_latest_season_id(game_content))
        history.set_log_sink(log)
        return cls(components)

    def request_refresh(self):
        self._refresh.set()

    # --- main loop -----------------------------------------------------------------------

    def run(self, emit, stop):
        last_state, waiting = None, False
        while not stop.is_set():
            try:
                state = self._current_state()
            except Exception as exc:
                self.c.log(f"tui: reading the game state failed: {exc!r}")
                state = None
            if state is None:
                if not waiting:
                    emit(Status("Waiting for VALORANT…"))
                    waiting = True
                last_state = None
            else:
                waiting = False
                if state != last_state or self._refresh.is_set():
                    self._refresh.clear()
                    last_state = state
                    try:
                        self._load(state, emit, stop)
                    except Exception as exc:
                        self.c.log(f"tui: loading {state} failed\n{traceback.format_exc()}")
                        emit(Status(f"Error loading {state}: {exc!r} — press r to retry"))
            stop.wait(POLL_SECONDS)

    def _current_state(self):
        presence = self.c.presences.get_presence()
        return self.c.presences.get_game_state(presence) if presence else None

    # --- one lobby -------------------------------------------------------------------------

    def _load(self, state, emit, stop):
        c = self.c
        presence = c.presences.get_presence() or []
        me = c.requests.puuid
        try:
            my_party = [m["Subject"] for m in c.menu.get_party_members(me, presence)]
        except Exception as exc:
            c.log(f"tui: party members failed: {exc!r}")
            my_party = []

        map_id, server, match_id = "", "", None
        if state == "INGAME":
            stats = c.coregame.get_coregame_stats()
            if not isinstance(stats, dict) or "Players" not in stats:
                emit(Status("Game found but no player data yet — press r to retry"))
                return
            players, match_id = stats["Players"], c.coregame.match_id
            map_id, server = stats.get("MapID", ""), stats.get("GamePodID", "")
        elif state == "PREGAME":
            stats = c.pregame.get_pregame_stats()
            if not isinstance(stats, dict) or "AllyTeam" not in stats:
                emit(Status("Agent select found but no player data yet — press r to retry"))
                return
            players, match_id = stats["AllyTeam"]["Players"], stats.get("ID")
            map_id, server = stats.get("MapID", ""), stats.get("GamePodID", "")
        elif state == "MENUS":
            players = c.menu.get_party_members(me, presence)
            self._rank_cache.clear()
            c.rank.invalidate_cached_responses()
            if hasattr(c.pstats, "clear_runtime_cache"):
                c.pstats.clear_runtime_cache()
        else:
            emit(Status(f"Unknown game state {state!r}"))
            return

        my_team = next((p.get("TeamID", "") for p in players if p["Subject"] == me), "")
        players = sorted(players, key=lambda p: (p.get("TeamID", "") != my_team,
                                                 -(p.get("PlayerIdentity", {}).get("AccountLevel") or 0)))
        puuids = [p["Subject"] for p in players]
        try:
            names = c.names.get_names_from_puuids(players)
        except Exception as exc:
            c.log(f"tui: names failed: {exc!r}")
            names = {}
        try:
            party_groups = c.menu.get_party_json(puuids, presence) if state != "MENUS" else {}
        except Exception as exc:
            c.log(f"tui: party json failed: {exc!r}")
            party_groups = {}

        want_history = state != "MENUS" and bool(c.cfg.table.get("lobby_history", True))
        rows, party_numbers = [], {}
        for p in players:
            puuid = p["Subject"]
            ident = p.get("PlayerIdentity", {})
            agent_id = (p.get("CharacterID") or "").lower()
            agent = c.agent_dict.get(agent_id, "Unknown") if agent_id else ""
            party = 0
            for group, members in party_groups.items():
                if puuid in members:
                    party = party_numbers.setdefault(group, len(party_numbers) + 1)
            rows.append(PlayerRow(
                puuid=puuid, name=self._display_name(puuid, names, ident, agent, me, my_party, state),
                team=p.get("TeamID", ""), ally=(state != "INGAME" or p.get("TeamID") == my_team),
                is_self=(puuid == me), agent_id=agent_id, agent=agent,
                locked=(p.get("CharacterSelectionState", "locked") == "locked"), party=party,
                level=self._level(ident, puuid, me, my_party, state),
                history_state="pending" if want_history else "skipped"))

        emit(LobbyReset(state=state, rows=rows, map_name=c.map_urls.get((map_id or "").lower()) or "",
                        map_id=map_id or "", mode=self._mode(), server=server))
        emit(Status("Loading ranks…"))
        for row in rows:
            if stop.is_set():
                return
            emit(PlayerUpdate(row.puuid, self._rank_fields(row.puuid, match_id)))

        if not want_history:
            emit(Status("Ready"))
            return
        emit(Status("Loading match history…"))
        lobby_map = map_id if c.cfg.table.get("map_history", True) else None
        for row in rows:
            if stop.is_set():
                return
            summary = history.summarise(row.puuid, c.requests.pd_url, c.requests.get_headers(),
                                        history.AGENT_ROLES, map_id=lobby_map)
            emit(PlayerUpdate(row.puuid, {"history": summary, "history_state": "done"}))
        emit(Status("Ready"))

    # --- helpers mirroring main.py's rules ---------------------------------------------------

    @staticmethod
    def _display_name(puuid, names, ident, agent, me, my_party, state):
        real = names.get(puuid, puuid[:8])
        if state == "MENUS" or puuid == me or puuid in my_party:
            return real
        if ident.get("Incognito") and hide_names:  # streamer mode: show the agent, as the console does
            return agent or "Player"
        return real

    @staticmethod
    def _level(ident, puuid, me, my_party, state):
        level = ident.get("AccountLevel")
        if state == "INGAME" and ident.get("HideAccountLevel"):
            return level if (puuid == me or puuid in my_party or not hide_levels) else None
        return level

    def _mode(self):
        try:
            private = self.c.presences.get_private_presence(self.c.presences.get_presence())
            if private.get("provisioningFlow") == "CustomGame":
                return "Custom Game"
            return gamemodes.get(private.get("queueId"), "") or ""
        except Exception:
            return ""

    def _rank_fields(self, puuid, match_id):
        key = (match_id, puuid) if match_id else None
        if key in self._rank_cache:
            return self._rank_cache[key]
        c = self.c
        try:
            rank = c.rank.get_rank(puuid, c.season_id)
            stats = c.pstats.get_stats(puuid)
        except Exception as exc:  # one player's failure must not break the lobby
            c.log(f"tui: rank/stats failed for a player: {exc!r}")
            return {"tier": 0, "rank": "?", "stats_state": "done"}
        short = c.cfg.get_feature_flag("short_ranks")
        label, rgb = rank_label(rank.get("rank") or 0, short)
        peak_label, peak_rgb = rank_label(rank.get("peakrank") or 0, short)
        ep, act = rank.get("peakrankep"), rank.get("peakrankact")
        if c.cfg.get_feature_flag("peak_rank_act") and ep is not None:
            has_letter = any(ch.isalpha() for ch in str(ep))
            peak_label += f" ({ep}a{act})" if has_letter else f" (e{ep}a{act})"
        fields = {
            "tier": rank.get("rank") or 0, "rank": label, "rank_rgb": rgb, "rr": rank.get("rr"),
            "peak": peak_label, "peak_rgb": peak_rgb, "leaderboard": rank.get("leaderboard") or 0,
            "wr": rank.get("wr"), "games": rank.get("numberofgames") or 0,
            "hs": stats.get("hs"), "kd": stats.get("kd"), "rr_delta": stats.get("RankedRatingEarned"),
            "stats_state": "done",
        }
        if key:
            self._rank_cache[key] = fields
        return fields
