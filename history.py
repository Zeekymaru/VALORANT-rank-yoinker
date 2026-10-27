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

CACHE_DIR = "cache"  # created at runtime, ignored by git
DEFAULT_TTL_SECONDS = 6 * 60 * 60
NEGATIVE_TTL_SECONDS = 5 * 60  # "unavailable" results are re-checked sooner
DEFAULT_MAX_MATCHES = 5
REQUEST_TIMEOUT = 10
TOP_AGENT_COUNT = 3
UNAVAILABLE_TEXT = "history unavailable"
UNAVAILABLE_STATUSES = (401, 403, 404)

# TODO(verify): path, and that it lives on the pd host.
HISTORY_PATH = "/match-history/v1/history/{puuid}"
# TODO(verify): query parameter names/semantics (startIndex, endIndex, queue)
# and the max page size allowed.
HISTORY_QUEUE = "competitive"
# TODO(verify): path, and that it lives on the pd host.
MATCH_DETAILS_PATH = "/match-details/v1/matches/{match_id}"
# valorant-api.com is the same third-party host main.py already uses for skins.
# TODO(verify): URL and the isPlayableCharacter parameter.
AGENTS_URL = "https://valorant-api.com/v1/agents"

# Response field names.
# TODO(verify): "History" list in the match-history response.
HISTORY_LIST_FIELD = "History"
# TODO(verify): per-entry match id field.
HISTORY_MATCH_ID_FIELD = "MatchID"
# TODO(verify): per-entry queue field and its value for competitive.
HISTORY_QUEUE_FIELD = "QueueID"
# TODO(verify): "players" list in the match details, and the per-player
# fields "subject", "teamId" and "characterId" below.
DETAILS_PLAYERS_FIELD = "players"
PLAYER_SUBJECT_FIELD = "subject"
PLAYER_TEAM_FIELD = "teamId"
PLAYER_AGENT_FIELD = "characterId"
# TODO(verify): "teams" list with "teamId" and a boolean "won".
DETAILS_TEAMS_FIELD = "teams"
TEAM_ID_FIELD = "teamId"
TEAM_WON_FIELD = "won"
# TODO(verify): valorant-api.com agent fields: "data", "uuid", and the role
# name at role.displayName.
AGENTS_DATA_FIELD = "data"
AGENT_UUID_FIELD = "uuid"
AGENT_ROLE_FIELD = "role"
AGENT_ROLE_NAME_FIELD = "displayName"

UNKNOWN_ROLE = "Unknown"
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _unavailable():
    return {"available": False, "games": 0, "wins": 0, "top_agents": [], "roles": {}}


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
        log.warning("history cache write failed: %s", exc)


def _get_json(url, headers, params=None, http_get=None):
    """GET and parse JSON. None for 401/403/404, any non-2xx, or any failure."""
    http_get = http_get or requests.get
    try:
        response = http_get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
        if response.status_code in UNAVAILABLE_STATUSES:
            return None
        if not 200 <= response.status_code < 300:
            log.warning("history request got HTTP %s", response.status_code)
            return None
        return response.json()
    except Exception as exc:  # network error, bad JSON, ...: never crash the lobby table
        log.warning("history request failed: %s", exc)
        return None


def match_ids_for(puuid, pd_url, headers, *, max_matches=DEFAULT_MAX_MATCHES, http_get=None):
    """Recent competitive match IDs for a player, newest first.

    Returns None if the history is unavailable (401/403/404 or any failure),
    and [] if the history is reachable but empty.
    """
    if not _SAFE_ID.match(str(puuid)):
        return None
    data = _get_json(
        pd_url + HISTORY_PATH.format(puuid=puuid),
        headers,
        params={"startIndex": 0, "endIndex": max_matches, "queue": HISTORY_QUEUE},
        http_get=http_get,
    )
    if not isinstance(data, dict) or not isinstance(data.get(HISTORY_LIST_FIELD), list):
        return None
    ids = []
    for entry in data[HISTORY_LIST_FIELD]:
        if not isinstance(entry, dict) or not isinstance(entry.get(HISTORY_MATCH_ID_FIELD), str):
            continue
        # Also filter client side in case the queue parameter is ignored.
        if entry.get(HISTORY_QUEUE_FIELD, HISTORY_QUEUE) != HISTORY_QUEUE:
            continue
        ids.append(entry[HISTORY_MATCH_ID_FIELD])
    return ids[:max_matches]


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


def build_role_map(agents):
    """Map lowercase agent ID -> role name from valorant-api.com agent entries."""
    roles = {}
    for agent in agents or []:
        if not isinstance(agent, dict):
            continue
        role = agent.get(AGENT_ROLE_FIELD)
        uuid = agent.get(AGENT_UUID_FIELD)
        if isinstance(role, dict) and uuid and role.get(AGENT_ROLE_NAME_FIELD):
            roles[str(uuid).lower()] = role[AGENT_ROLE_NAME_FIELD]
    return roles


def load_role_map(http_get=None):
    """Download agent data once and build the role map; {} on any failure."""
    data = _get_json(AGENTS_URL, None, params={"isPlayableCharacter": "true"}, http_get=http_get)
    if not isinstance(data, dict):
        return {}
    return build_role_map(data.get(AGENTS_DATA_FIELD))


def _player_result(puuid, details):
    """(agent_id, won) for this player in one match, or None.

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
    return str(me[PLAYER_AGENT_FIELD]).lower(), team[TEAM_WON_FIELD]


def _aggregate(results, agent_roles):
    if not results:
        return _unavailable()
    agents = Counter(agent for agent, _ in results)
    roles = Counter(agent_roles.get(agent, UNKNOWN_ROLE) for agent, _ in results)
    top = sorted(agents.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_AGENT_COUNT]
    return {
        "available": True,
        "games": len(results),
        "wins": sum(1 for _, won in results if won),
        "top_agents": [{"agent_id": agent, "games": games} for agent, games in top],
        "roles": dict(roles),
    }


def _summarise(puuid, pd_url, headers, agent_roles, max_matches, ttl, cache_dir, now, http_get):
    now_ts = (now or time.time)()
    path = _cache_path(cache_dir, "players", f"{puuid}.json") if _SAFE_ID.match(str(puuid)) else None
    cached = _read_json(path) if path else None
    if isinstance(cached, dict) and isinstance(cached.get("summary"), dict):
        age = now_ts - cached.get("fetched_at", float("-inf"))
        limit = ttl if cached["summary"].get("available") else min(ttl, NEGATIVE_TTL_SECONDS)
        if 0 <= age < limit:
            return cached["summary"]

    ids = match_ids_for(puuid, pd_url, headers, max_matches=max_matches, http_get=http_get)
    results = []
    fetch_failed = False
    for match_id in ids or []:
        details = match_details(match_id, pd_url, headers, cache_dir=cache_dir, http_get=http_get)
        if details is None:
            fetch_failed = True
            continue
        result = _player_result(puuid, details)
        if result is not None:
            results.append(result)
    summary = _aggregate(results, agent_roles or {})
    # Don't pin a partial sample (some match fetches failed) for the full TTL.
    if path and not fetch_failed:
        _write_json(path, {"fetched_at": now_ts, "summary": summary})
    return summary


def summarise(puuid, pd_url, headers, agent_roles, *, max_matches=DEFAULT_MAX_MATCHES,
              ttl=DEFAULT_TTL_SECONDS, cache_dir=None, now=None, http_get=None):
    """Summary of a player's recent competitive matches. Never raises.

    {"available": bool, "games": int, "wins": int,
     "top_agents": [{"agent_id": str, "games": int}, ...], "roles": {role: games}}

    "games" is the sample size: matches where the player was found and the
    result was known. Others are skipped. Unavailable, private or empty
    history gives available=False.
    """
    try:
        return _summarise(puuid, pd_url, headers, agent_roles, max_matches, ttl, cache_dir, now, http_get)
    except Exception:
        log.exception("history summary failed for a player")
        return _unavailable()


def format_columns(summary, agent_names):
    """[top agents, win rate (wins/games), roles] as table cell strings.

    agent_names maps lowercase agent ID -> display name (main.py's agent_dict).
    """
    if not summary.get("available"):
        return [UNAVAILABLE_TEXT, "-", "-"]
    games, wins = summary["games"], summary["wins"]
    agents = ", ".join(f"{agent_names.get(a['agent_id'], 'Unknown')} ({a['games']})"
                       for a in summary["top_agents"])
    rate = f"{int(100 * wins / games + 0.5)}% ({wins}/{games})"
    roles = ", ".join(f"{role} {n}" for role, n in
                      sorted(summary["roles"].items(), key=lambda kv: (-kv[1], kv[0])))
    return [agents, rate, roles]
