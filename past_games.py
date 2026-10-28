"""Rebuild saved lobbies for games played while the TUI wasn't running, from match details already in the cache.

Local files only; no network. Every cached match-details payload lists all ten players with their agent, team,
account level and the rank they held in that game, so a lobby can be reconstructed for any cached game you were in.
What can't be reconstructed is anything fetched live: season stats, peak rank, RR, and premade groups (the payload's
partyId is the whole team's id, not the premade). A reconstructed player's history is
built from the *other* cached matches that started before the game (the same view the live lobby had), so players
we have no earlier matches for show as having no history. Imported snapshots are marked "imported".
"""
import functools
import json
import os
import time
from collections import defaultdict

import history
import lobby_store
from lobby_data import rank_label

CACHE_LIMIT = 48  # parsed match payloads kept in memory at once
DEFAULT_LIMIT = 40  # most recent games imported per run, so a big cache can't crowd out the saved-lobby limit
MODES = {"competitive": "Competitive", "unrated": "Unrated", "swiftplay": "Swiftplay", "spikerush": "Spike Rush"}


def _read(path):
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _players(details):
    return [p for p in details.get("players") or [] if isinstance(p, dict) and p.get("subject") and not p.get("isObserver")]


def scan(matches_dir):
    """{match id: {"path", "start", "players": set of lowercase subjects}} for every readable cached match."""
    index = {}
    try:
        names = os.listdir(matches_dir)
    except OSError:
        return index
    for name in names:
        if not name.endswith(".json"):
            continue
        path = os.path.join(matches_dir, name)
        details = _read(path)
        info = details.get("matchInfo") if details else None
        if not isinstance(info, dict) or not info.get("matchId"):
            continue
        start = info.get("gameStartMillis")
        index[info["matchId"]] = {"path": path, "start": start / 1000 if isinstance(start, (int, float)) else None,
                                  "players": {str(p["subject"]).lower() for p in _players(details)}}
    return index


def _result(details, my_team):
    teams = {t.get("teamId"): t for t in details.get("teams") or [] if isinstance(t, dict)}
    mine = teams.get(my_team)
    if not mine or not isinstance(mine.get("won"), bool):
        return None
    theirs = next((t for key, t in teams.items() if key != my_team), None)
    score = ""
    if theirs and isinstance(mine.get("roundsWon"), int) and isinstance(theirs.get("roundsWon"), int):
        score = f"{mine['roundsWon']}-{theirs['roundsWon']}"
    return {"won": mine["won"], "score": score, "rr": None}


def import_past(cache_dir, store_dir, puuids, agent_names, map_names, *, limit=DEFAULT_LIMIT, now=None):
    """Save a lobby for each cached game that one of `puuids` played in and that isn't saved yet; returns how many.

    Newest games first, at most `limit` per call. Games already in the saved-lobby folder are left alone.
    """
    wanted = {p.lower() for p in puuids if p}
    if not wanted:
        return 0
    index = scan(os.path.join(cache_dir, "matches"))
    done = {n[:-5] for n in os.listdir(store_dir)} if os.path.isdir(store_dir) else set()
    todo = sorted(((mid, m) for mid, m in index.items() if m["start"] and m["players"] & wanted and mid not in done),
                  key=lambda item: item[1]["start"], reverse=True)[:limit]

    @functools.lru_cache(maxsize=CACHE_LIMIT)
    def load(match_id):
        return _read(index[match_id]["path"])

    by_player = defaultdict(list)  # subject -> [(start, match id)], newest first
    for mid, meta in index.items():
        for subject in meta["players"]:
            by_player[subject].append((meta["start"] or 0, mid))
    for entries in by_player.values():
        entries.sort(reverse=True)
    memo = {}

    def result_for(subject, match_id):
        if (subject, match_id) not in memo:
            details = load(match_id)
            memo[(subject, match_id)] = history._player_result(subject, details) if details else None
        return memo[(subject, match_id)]

    def summary_for(subject, before, map_key):
        results = []
        for start, match_id in by_player[subject]:
            if start >= before:
                continue
            result = result_for(subject, match_id)
            if result is not None:
                results.append({**result, "id": match_id, "rr": None})
            if len(results) >= history.DEFAULT_MAX_MATCHES:
                break
        summary = history._aggregate(results, history.AGENT_ROLES)
        if summary["available"] and map_key:
            on_map = [r for r in results if r["map"] == map_key]
            summary["map"] = {"games": len(on_map), "wins": sum(1 for r in on_map if r["won"])}
        return summary

    saved = 0
    for match_id, meta in todo:
        details = load(match_id)
        info = (details or {}).get("matchInfo") or {}
        players = _players(details or {})
        me = next((p for p in players if str(p["subject"]).lower() in wanted), None)
        if me is None or not info.get("isCompleted", True):
            continue
        map_id = info.get("mapId") or ""
        map_key = map_id.lower() or None
        rows = []
        for player in sorted(players, key=lambda p: (p.get("teamId") != me.get("teamId"), p is not me)):
            subject = str(player["subject"]).lower()
            tier = player.get("competitiveTier")
            rank, rgb = rank_label(tier)
            agent_id = str(player.get("characterId") or "").lower()
            name = f"{player.get('gameName') or ''}#{player.get('tagLine') or ''}".strip("#")
            rows.append({
                "puuid": subject, "name": name or "?", "team": str(player.get("teamId") or ""),
                "ally": player.get("teamId") == me.get("teamId"), "is_self": player is me,
                "agent_id": agent_id, "agent": agent_names.get(agent_id) or "", "locked": True,
                "party": 0, "level": player.get("accountLevel"),
                "tier": tier, "rank": rank, "rank_rgb": list(rgb) if rgb else None, "rr": None, "peak": "",
                "peak_rgb": None, "leaderboard": 0, "hs": "N/A", "kd": None, "wr": "N/A", "games": 0,
                "rr_delta": "N/A", "history": summary_for(subject, meta["start"], map_key),
                "stats_state": "done", "history_state": "done",
            })
        allies, enemies = [r for r in rows if r["ally"]], [r for r in rows if not r["ally"]]

        def average(group):
            tiers = [r["tier"] for r in group if isinstance(r["tier"], int) and r["tier"] > 0]
            return rank_label(round(sum(tiers) / len(tiers)))[0] if tiers else ""

        queue = str(info.get("queueID") or "")
        started = meta["start"]
        snapshot = {
            "version": lobby_store.SNAPSHOT_VERSION, "started_at": started, "saved_at": now if now is not None else time.time(),
            "state": "INGAME", "map_name": map_names.get(map_key) or "", "map_id": map_id,
            "mode": MODES.get(queue.lower(), queue.title()), "server": info.get("gamePodId") or "",
            "match_id": match_id, "imported": True,
            "summary": {"you": next(r["agent"] for r in rows if r["is_self"]), "ally_avg": average(allies),
                        "enemy_avg": average(enemies)},
            "rows": rows, "agent_names": dict(agent_names), "map_names": dict(map_names),
        }
        result = _result(details, me.get("teamId"))
        if result:
            snapshot["result"] = result
        if lobby_store.save_past(store_dir, snapshot):
            saved += 1
    lobby_store.prune(store_dir)
    return saved
