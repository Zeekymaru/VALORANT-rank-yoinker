"""Lobby-level match history stats for VALORANT rank yoinker.

EXPERIMENTAL and UNVERIFIED against the live API. Every endpoint, parameter
and field name below that has not been checked is marked "# TODO(verify)".

Rules this module follows:
- It only uses the headers main.py already builds from the local client.
- HTTP 401/403/404 mean "unavailable". There is no retry or workaround.
- One player's failure never raises; it yields an "unavailable" summary.
- Requests are bounded: at most `max_matches` matches per player, finished
  matches are cached forever, and per-player summaries are cached with a TTL.
"""
import json
import logging
import os
import re
import time
from collections import Counter

import requests

log = logging.getLogger(__name__)
_log_sink = None


def set_log_sink(sink):
    """Send this module's diagnostics to the host app's logger (callable taking a str)."""
    global _log_sink
    _log_sink = sink


def _log(message):
    (_log_sink or log.warning)(f"history: {message}")

CACHE_DIR = "cache"  # created at runtime, ignored by git
DEFAULT_TTL_SECONDS = 6 * 60 * 60
NEGATIVE_TTL_SECONDS = 5 * 60  # "unavailable" results are re-checked sooner
DEFAULT_MAX_MATCHES = 5  # recent matches sampled per player (win rate, agents, roles, sides)
LIST_DEPTH = 20  # history entries asked for when a map record is wanted (still one request per player)
DEFAULT_MAP_MATCHES = 5  # at most this many matches on the lobby's map are fetched for the map record
REQUEST_TIMEOUT = 10
TOP_AGENT_COUNT = 3
UNAVAILABLE_TEXT = "history unavailable"
NO_GAMES_TEXT = "no recent comp games"
UNAVAILABLE_STATUSES = (401, 403, 404)
# Why a summary is not available (the "reason" key; absent when available).
REASON_UNAVAILABLE = "unavailable"  # 401/403/404, request failure, bad response
REASON_NO_GAMES = "no_games"  # reachable but the history list is empty
REASON_NO_RESULT = "no_result"  # matches found but none usable (see _player_result)
ROLE_SHORT = {"Duelist": "Duel", "Initiator": "Init", "Controller": "Ctrl",
              "Sentinel": "Sent", "Unknown": "?"}

# The vRY 2.94 code (src/player_stats.py) already calls this path with
# startIndex=0&endIndex=1&queue=competitive for the user's own puuid and reads
# Matches[].MatchID. Observed working live on 2026-10-27 for other lobby
# players' puuids with endIndex=5.
# TODO(verify): what it returns for a private profile (401/403/404 or empty?);
# no 403 has been seen yet, so unavailable vs. empty can't be told apart there.
HISTORY_PATH = "/mmr/v1/players/{puuid}/competitiveupdates"
HISTORY_QUEUE = "competitive"
# vRY 2.94 already calls this path and reads players[].subject / .stats.
# Observed working live on 2026-10-27 for other lobby players' matches.
MATCH_DETAILS_PATH = "/match-details/v1/matches/{match_id}"

# Response field names.
# vRY 2.94 reads "Matches" and "MatchID" from competitiveupdates (see above).
HISTORY_LIST_FIELD = "Matches"
HISTORY_MATCH_ID_FIELD = "MatchID"
# TODO(verify): each competitiveupdates entry carries the map id in this field,
# in the same path style as the lobby's MapID (e.g. /Game/Maps/Triad/Triad).
# If it is missing the map record is skipped and no extra matches are fetched.
HISTORY_MAP_FIELD = "MapID"
# Seen in 81 cached live match files (2026-10-27): matchInfo.mapId, and per round
# winningTeam plus winningTeamRole ("Attacker" / "Defender").
DETAILS_INFO_FIELD = "matchInfo"
INFO_MAP_FIELD = "mapId"
DETAILS_ROUNDS_FIELD = "roundResults"
ROUND_WINNER_FIELD = "winningTeam"
ROUND_WINNER_ROLE_FIELD = "winningTeamRole"
ROLE_ATTACKER = "Attacker"
ROLE_DEFENDER = "Defender"
# "players" and "subject" are read by vRY 2.94 (src/player_stats.py). The
# fields below (teamId, characterId, teams[].teamId, teams[].won) produced
# sensible agents, roles and win rates in a live run on 2026-10-27, but were
# only checked by eye, not against an independent source.
DETAILS_PLAYERS_FIELD = "players"
PLAYER_SUBJECT_FIELD = "subject"
PLAYER_TEAM_FIELD = "teamId"
PLAYER_AGENT_FIELD = "characterId"
DETAILS_TEAMS_FIELD = "teams"
TEAM_ID_FIELD = "teamId"
TEAM_WON_FIELD = "won"

# Agent ID (lowercase) -> role. Hardcoded on purpose: roles of existing agents
# don't change and new agents arrive rarely. Generated 2026-10-27 from
# valorant-api.com (/v1/agents?isPlayableCharacter=true). An agent missing from
# this table counts as UNKNOWN_ROLE; add a line when a new agent ships.
# The IDs are only useful if they match the match-details characterId; that is
# covered by the TODO(verify) on PLAYER_AGENT_FIELD above.
AGENT_ROLES = {
    "41fb69c1-4189-7b37-f117-bcaf1e96f1bf": "Controller",  # Astra
    "5f8d3a7f-467b-97f3-062c-13acf203c006": "Initiator",  # Breach
    "9f0d8ba9-4140-b941-57d3-a7ad57c6b417": "Controller",  # Brimstone
    "22697a3d-45bf-8dd7-4fec-84a9e28c69d7": "Sentinel",  # Chamber
    "1dbf2edd-4729-0984-3115-daa5eed44993": "Controller",  # Clove
    "117ed9e3-49f3-6512-3ccf-0cada7e3823b": "Sentinel",  # Cypher
    "cc8b64c8-4b25-4ff9-6e7f-37b4da43d235": "Sentinel",  # Deadlock
    "dade69b4-4f5a-8528-247b-219e5a1facd6": "Initiator",  # Fade
    "e370fa57-4757-3604-3648-499e1f642d3f": "Initiator",  # Gekko
    "95b78ed7-4637-86d9-7e41-71ba8c293152": "Controller",  # Harbor
    "0e38b510-41a8-5780-5e8f-568b2a4f2d6c": "Duelist",  # Iso
    "add6443a-41bd-e414-f6ad-e58d267f4e95": "Duelist",  # Jett
    "601dbbe7-43ce-be57-2a40-4abd24953621": "Initiator",  # KAY/O
    "1e58de9c-4950-5125-93e9-a0aee9f98746": "Sentinel",  # Killjoy
    "7c8a4701-4de6-9355-b254-e09bc2a34b72": "Controller",  # Miks
    "bb2a4828-46eb-8cd1-e765-15848195d751": "Duelist",  # Neon
    "8e253930-4c05-31dd-1b6c-968525494517": "Controller",  # Omen
    "eb93336a-449b-9c1b-0a54-a891f7921d69": "Duelist",  # Phoenix
    "f94c3b30-42be-e959-889c-5aa313dba261": "Duelist",  # Raze
    "a3bfb853-43b2-7238-a4f1-ad90e9e46bcc": "Duelist",  # Reyna
    "569fdd95-4d10-43ab-ca70-79becc718b46": "Sentinel",  # Sage
    "6f2a04ca-43e0-be17-7f36-b3908627744d": "Initiator",  # Skye
    "320b2a48-4d9b-a075-30f1-1f93a9b638fa": "Initiator",  # Sova
    "b444168c-4e35-8076-db47-ef9bf368f384": "Initiator",  # Tejo
    "92eeef5d-43b5-1d4a-8d03-b3927a09034b": "Sentinel",  # Veto
    "707eab51-4836-f488-046a-cda6bf494859": "Controller",  # Viper
    "efba5359-4016-a1e5-7626-b1ae76895940": "Sentinel",  # Vyse
    "df1cb487-4902-002e-5c17-d28e83e78588": "Duelist",  # Waylay
    "7f94d92c-4234-0a36-9646-3a87eb8b5c89": "Duelist",  # Yoru
}
UNKNOWN_ROLE = "Unknown"
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _unavailable(reason=REASON_UNAVAILABLE):
    return {"available": False, "reason": reason, "games": 0, "wins": 0, "top_agents": [], "roles": {}}


def _cache_path(cache_dir, *parts):
    return os.path.join(cache_dir or CACHE_DIR, *parts)


def _read_json(path):
    try:
        with open(path, "r", encoding="utf8") as file:
            return json.load(file)
    except (OSError, ValueError):
        return None


def _write_json(path, data):
    """Best effort atomic write; a cache that can't be written is not fatal."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf8") as file:
            json.dump(data, file)
        os.replace(tmp, path)
    except OSError as exc:
        _log(f"cache write failed: {exc}")


def _get_json(url, headers, params=None, http_get=None):
    """GET and parse JSON. None for 401/403/404, any non-2xx, or any failure."""
    http_get = http_get or requests.get
    # TODO(verify): default TLS verification works against the pd hosts
    # (main.py passes verify=False everywhere; this module deliberately doesn't).
    try:
        response = http_get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
        if response.status_code in UNAVAILABLE_STATUSES:
            return None
        if not 200 <= response.status_code < 300:
            _log(f"request got HTTP {response.status_code}: {url}")
            return None
        return response.json()
    except Exception as exc:  # network error, bad JSON, ...: never crash the lobby table
        _log(f"request failed: {exc}")
        return None


def match_ids_for(puuid, pd_url, headers, *, max_matches=DEFAULT_MAX_MATCHES, http_get=None):
    """Recent competitive match IDs for a player, newest first.

    Returns None if the history is unavailable (401/403/404 or any failure),
    and [] if the history is reachable but empty.
    """
    entries = match_entries_for(puuid, pd_url, headers, depth=max_matches, http_get=http_get)
    return None if entries is None else [entry["id"] for entry in entries]


def match_entries_for(puuid, pd_url, headers, *, depth=DEFAULT_MAX_MATCHES, http_get=None):
    """[{"id": match id, "map": lowercase map id or None}, ...], newest first, at most `depth`.

    One request. None if unavailable (401/403/404 or any failure), [] if empty.
    """
    if not _SAFE_ID.match(str(puuid)):
        return None
    data = _get_json(
        pd_url + HISTORY_PATH.format(puuid=puuid),
        headers,
        params={"startIndex": 0, "endIndex": depth, "queue": HISTORY_QUEUE},
        http_get=http_get,
    )
    if not isinstance(data, dict) or not isinstance(data.get(HISTORY_LIST_FIELD), list):
        return None
    entries = []
    for entry in data[HISTORY_LIST_FIELD]:
        if not isinstance(entry, dict) or not isinstance(entry.get(HISTORY_MATCH_ID_FIELD), str):
            continue
        map_id = entry.get(HISTORY_MAP_FIELD)
        entries.append({"id": entry[HISTORY_MATCH_ID_FIELD],
                        "map": map_id.lower() if isinstance(map_id, str) and map_id else None})
    return entries[:depth]


def match_details(match_id, pd_url, headers, *, cache_dir=None, http_get=None):
    """Details of one finished match, cached on disk by match ID with no expiry.

    Returns None if unavailable. Failures are never cached.
    """
    if not _SAFE_ID.match(str(match_id)):  # also keeps the ID out of path tricks
        return None
    path = _cache_path(cache_dir, "matches", f"{match_id}.json")
    cached = _read_json(path)
    if isinstance(cached, dict):
        return cached
    data = _get_json(pd_url + MATCH_DETAILS_PATH.format(match_id=match_id), headers, http_get=http_get)
    if not isinstance(data, dict):
        return None
    _write_json(path, data)
    return data


def _player_result(puuid, details):
    """{"agent", "won", "map", "sides"} for this player in one match, or None.

    None when the player isn't in the match or the outcome can't be told
    (team missing or no boolean "won"); such matches are left out of the sample.
    """
    if not isinstance(details, dict):
        return None
    players = [p for p in details.get(DETAILS_PLAYERS_FIELD) or [] if isinstance(p, dict)]
    me = next((p for p in players if str(p.get(PLAYER_SUBJECT_FIELD, "")).lower() == puuid.lower()), None)
    if me is None or not me.get(PLAYER_AGENT_FIELD):
        return None
    teams = [t for t in details.get(DETAILS_TEAMS_FIELD) or [] if isinstance(t, dict)]
    team = next((t for t in teams if t.get(TEAM_ID_FIELD) == me.get(PLAYER_TEAM_FIELD)), None)
    if team is None or not isinstance(team.get(TEAM_WON_FIELD), bool):
        return None
    info = details.get(DETAILS_INFO_FIELD)
    map_id = info.get(INFO_MAP_FIELD) if isinstance(info, dict) else None
    return {
        "agent": str(me[PLAYER_AGENT_FIELD]).lower(),
        "won": team[TEAM_WON_FIELD],
        "map": map_id.lower() if isinstance(map_id, str) and map_id else None,
        "sides": _side_rounds(me.get(PLAYER_TEAM_FIELD), details),
    }


def _side_rounds(team_id, details):
    """{"Attacker": [won, played], "Defender": [won, played]} for team_id's rounds.

    A round's winning team and the role it won as are given; the other team had
    the opposite role and lost. Rounds missing either field are left out.
    """
    sides = {ROLE_ATTACKER: [0, 0], ROLE_DEFENDER: [0, 0]}
    for rnd in details.get(DETAILS_ROUNDS_FIELD) or []:
        if not isinstance(rnd, dict):
            continue
        winner, role = rnd.get(ROUND_WINNER_FIELD), rnd.get(ROUND_WINNER_ROLE_FIELD)
        if not winner or role not in sides:
            continue
        mine = winner == team_id
        my_role = role if mine else (ROLE_DEFENDER if role == ROLE_ATTACKER else ROLE_ATTACKER)
        sides[my_role][1] += 1
        sides[my_role][0] += int(mine)
    return sides


def _aggregate(results, agent_roles):
    if not results:
        return _unavailable(REASON_NO_RESULT)
    agents = Counter(r["agent"] for r in results)
    agent_wins = Counter(r["agent"] for r in results if r["won"])
    roles = Counter(agent_roles.get(r["agent"], UNKNOWN_ROLE) for r in results)
    # results are newest first and sorted() is stable, so ties go to the most recent agent
    top = sorted(agents.items(), key=lambda kv: -kv[1])[:TOP_AGENT_COUNT]

    def side_total(role):
        return {"won": sum(r["sides"][role][0] for r in results),
                "rounds": sum(r["sides"][role][1] for r in results)}

    return {
        "available": True,
        "games": len(results),
        "wins": sum(1 for r in results if r["won"]),
        "top_agents": [{"agent_id": agent, "games": games, "wins": agent_wins[agent]}
                       for agent, games in top],
        "roles": dict(roles),
        "attack": side_total(ROLE_ATTACKER),
        "defense": side_total(ROLE_DEFENDER),
    }


def _summarise(puuid, pd_url, headers, agent_roles, max_matches, ttl, cache_dir, now, http_get,
               map_id, map_matches):
    now_ts = (now or time.time)()
    map_key = map_id.lower() if isinstance(map_id, str) and map_id else None
    # The map record differs per map, so each (player, map) gets its own cached summary.
    name = f"{puuid}--{re.sub(r'[^a-z0-9]+', '_', map_key).strip('_')}" if map_key else str(puuid)
    path = _cache_path(cache_dir, "players", f"{name}.json") if _SAFE_ID.match(str(puuid)) else None
    cached = _read_json(path) if path else None
    if isinstance(cached, dict) and isinstance(cached.get("summary"), dict):
        age = now_ts - cached.get("fetched_at", float("-inf"))
        limit = ttl if cached["summary"].get("available") else min(ttl, NEGATIVE_TTL_SECONDS)
        if 0 <= age < limit:
            return cached["summary"]

    depth = max(max_matches, LIST_DEPTH) if map_key else max_matches
    entries = match_entries_for(puuid, pd_url, headers, depth=depth, http_get=http_get)
    fetch_failed = False
    by_id = {}  # match id -> this player's result (None if unusable), for matches fetched so far

    def result_for(match_id):
        nonlocal fetch_failed
        if match_id not in by_id:
            details = match_details(match_id, pd_url, headers, cache_dir=cache_dir, http_get=http_get)
            if details is None:
                fetch_failed = True
            by_id[match_id] = None if details is None else _player_result(puuid, details)
        return by_id[match_id]

    if entries is None:
        summary = _unavailable(REASON_UNAVAILABLE)
    elif not entries:
        summary = _unavailable(REASON_NO_GAMES)
    else:
        recent = [result_for(entry["id"]) for entry in entries[:max_matches]]
        summary = _aggregate([r for r in recent if r is not None], agent_roles or {})
        if summary["available"] and map_key and any(entry["map"] for entry in entries):
            on_map = [entry for entry in entries if entry["map"] == map_key][:map_matches]
            results = [result_for(entry["id"]) for entry in on_map]
            results = [r for r in results if r is not None and r["map"] in (None, map_key)]
            summary["map"] = {"games": len(results), "wins": sum(1 for r in results if r["won"])}
    # Don't pin a partial sample (some match fetches failed) for the full TTL.
    if path and not fetch_failed:
        _write_json(path, {"fetched_at": now_ts, "summary": summary})
    return summary


def summarise(puuid, pd_url, headers, agent_roles, *, max_matches=DEFAULT_MAX_MATCHES,
              ttl=DEFAULT_TTL_SECONDS, cache_dir=None, now=None, http_get=None,
              map_id=None, map_matches=DEFAULT_MAP_MATCHES):
    """Summary of a player's recent competitive matches. Never raises.

    {"available": bool, "games": int, "wins": int,
     "top_agents": [{"agent_id": str, "games": int, "wins": int}, ...],
     "roles": {role: games},
     "attack": {"won": int, "rounds": int}, "defense": {"won": int, "rounds": int}}

    "games" is the sample size: matches where the player was found and the
    result was known. Others are skipped. Unavailable, private or empty
    history gives available=False. "attack"/"defense" are the player's team's
    rounds won/played on each side across those matches.

    With map_id (the lobby's map), the history list is requested LIST_DEPTH
    deep (still one request) and up to map_matches matches on that map are
    fetched, adding "map": {"games": int, "wins": int}. If the list entries
    carry no map id, "map" is left out and nothing extra is fetched.
    """
    try:
        return _summarise(puuid, pd_url, headers, agent_roles, max_matches, ttl, cache_dir, now, http_get,
                          map_id, map_matches)
    except Exception as exc:
        _log(f"summary failed for a player: {exc!r}")
        return _unavailable()


def win_rate_rgb(percent):
    """(r, g, b) for a win rate: red at 0, yellow at 50, green at 100; never too dark to read."""
    stops = [(0, (235, 80, 80)), (50, (235, 205, 70)), (100, (90, 225, 110))]
    percent = max(0, min(100, percent))
    for (low, start), (high, end) in zip(stops, stops[1:]):
        if percent <= high:
            ratio = (percent - low) / (high - low)
            return tuple(round(a + (b - a) * ratio) for a, b in zip(start, end))


def _agent_label(name, games, wins=None):
    """'Sage 2-0' (wins-losses with that agent). Summaries cached before per-agent
    wins existed have no 'wins'; those fall back to 'Sage ×2'."""
    if wins is None:
        return name if games == 1 else f"{name} ×{games}"
    return f"{name} {wins}-{games - wins}"


def _percent(won, played):
    return int(100 * won / played + 0.5)


def format_cell(summary, agent_names, wr_color=None, dim=None, map_name=None):
    """One compact table cell:

        60% 3/5                          win rate over the sampled games
        Sova 1-0 · Skye 0-1 · Viper 1-0  wins-losses per agent (top 3)
        Init2 Ctrl1 Duel1 Sent1          games per role
        Atk 54% (32) · Def 48% (31)      round win rate on each side (rounds played)
        Ascent 2-1                       wins-losses on the lobby's map (map_name given)

    The attack/defense and map lines appear only when the summary has them.

    agent_names maps lowercase agent ID -> display name (main.py's agent_dict).
    wr_color(percent, text) -> str colors a win-rate text, and dim(text) -> str
    mutes the secondary lines. Both are optional styling hooks (main.py passes
    colour helpers); plain text is used without them.
    """
    wr_color = wr_color or (lambda percent, text: text)
    dim = dim or str
    if not summary.get("available"):
        return dim(NO_GAMES_TEXT if summary.get("reason") == REASON_NO_GAMES else UNAVAILABLE_TEXT)
    games, wins = summary["games"], summary["wins"]
    percent = _percent(wins, games)
    rate = wr_color(percent, f"{percent}% {wins}/{games}")
    agents = " · ".join(_agent_label(agent_names.get(a["agent_id"], "Unknown"), a["games"], a.get("wins"))
                        for a in summary["top_agents"])
    roles = " ".join(f"{ROLE_SHORT.get(role, role)}{n}" for role, n in
                     sorted(summary["roles"].items(), key=lambda kv: (-kv[1], kv[0])))
    lines = [rate, agents, dim(roles)]

    if "attack" in summary and "defense" in summary:
        def side(label, record):
            rounds = record["rounds"]
            if not rounds:
                return f"{label} -"
            pct = _percent(record["won"], rounds)
            return f"{label} {wr_color(pct, f'{pct}% ({rounds})')}"

        lines.append(f"{side('Atk', summary['attack'])} · {side('Def', summary['defense'])}")

    record = summary.get("map")
    if map_name and record is not None:
        if record["games"]:
            lines.append(wr_color(_percent(record["wins"], record["games"]),
                                  f"{map_name} {record['wins']}-{record['games'] - record['wins']}"))
        else:
            lines.append(dim(f"{map_name} -"))
    return "\n".join(lines)
