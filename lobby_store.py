"""Saved lobbies: a JSON snapshot of each lobby the TUI shows, so it can be reopened after the game ends.

Local files only; no network. A snapshot is what was on screen (names as displayed, so streamer mode's hidden names
stay hidden), including every player's loaded rank and history summary. They live under cache/lobbies/, which is
git-ignored. The match result isn't known while the game runs; it is filled in later from your own next history
(backfill_results), which needs no extra requests.
"""
import json
import os
import re
import time
from dataclasses import asdict, fields

from lobby_data import PlayerRow

SNAPSHOT_VERSION = 1
MAX_SAVED = 200  # oldest snapshots beyond this are removed after a save
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_TUPLE_FIELDS = ("rank_rgb", "peak_rgb")
_ROW_FIELDS = {f.name for f in fields(PlayerRow)}


def snapshot_id(match_id, started_at):
    """File stem: the match id when we have a safe one (so a lobby is saved once), else a start-time stamp."""
    return match_id if isinstance(match_id, str) and _SAFE_ID.match(match_id) else f"t{int(started_at)}"


def build_snapshot(model, agent_names, map_names, started_at, summary=None, now=None):
    return {
        "version": SNAPSHOT_VERSION, "started_at": started_at, "saved_at": now if now is not None else time.time(),
        "state": model.state, "map_name": model.map_name, "map_id": model.map_id, "mode": model.mode,
        "server": model.server, "match_id": getattr(model, "match_id", ""), "summary": summary or {},
        "rows": [asdict(row) for row in model.ordered],
        "agent_names": dict(agent_names or {}), "map_names": dict(map_names or {}),
    }


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    os.replace(tmp, path)


def _read(path):
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("version") == SNAPSHOT_VERSION else None


def save(store_dir, snapshot):
    """Write the snapshot (replacing an earlier save of the same lobby), keep its result, prune; returns the path."""
    path = os.path.join(store_dir, snapshot_id(snapshot.get("match_id"), snapshot["started_at"]) + ".json")
    earlier = _read(path)
    if earlier and earlier.get("result") and "result" not in snapshot:
        snapshot = {**snapshot, "result": earlier["result"]}
    _write(path, snapshot)
    prune(store_dir)
    return path


def prune(store_dir, keep=MAX_SAVED):
    try:
        names = [n for n in os.listdir(store_dir) if n.endswith(".json")]
    except OSError:
        return
    paths = sorted((os.path.join(store_dir, n) for n in names), key=lambda p: os.path.getmtime(p), reverse=True)
    for stale in paths[keep:]:
        try:
            os.remove(stale)
        except OSError:
            pass


def list_saved(store_dir, limit=100):
    """Header info for saved lobbies, newest first: path, times, map, mode, state, summary, result, player count."""
    try:
        names = [n for n in os.listdir(store_dir) if n.endswith(".json")]
    except OSError:
        return []
    entries = []
    for name in names:
        path = os.path.join(store_dir, name)
        data = _read(path)
        if data is None or not isinstance(data.get("rows"), list):
            continue
        entries.append({"path": path, "started_at": data.get("started_at") or 0, "saved_at": data.get("saved_at") or 0,
                        "state": data.get("state", ""), "map_name": data.get("map_name", ""),
                        "mode": data.get("mode", ""), "summary": data.get("summary") or {},
                        "result": data.get("result"), "players": len(data["rows"])})
    entries.sort(key=lambda e: e["started_at"], reverse=True)
    return entries[:limit]


def load(path):
    """The snapshot dict, or None when the file is missing, corrupt or from another version."""
    data = _read(path)
    return data if data is not None and isinstance(data.get("rows"), list) else None


def rows_from(snapshot):
    """PlayerRows rebuilt from a snapshot; unknown fields are ignored and colour lists become tuples again."""
    rows = []
    for raw in snapshot.get("rows") or []:
        if not isinstance(raw, dict) or not raw.get("puuid"):
            continue
        values = {k: v for k, v in raw.items() if k in _ROW_FIELDS}
        for key in _TUPLE_FIELDS:
            if isinstance(values.get(key), list):
                values[key] = tuple(values[key])
        rows.append(PlayerRow(**values))
    return rows


def _result_of(match):
    """{"won", "score", "rr"} for one entry of a history summary's "matches", or None."""
    if not isinstance(match, dict) or not isinstance(match.get("won"), bool):
        return None
    attack, defense = match.get("attack") or [0, 0], match.get("defense") or [0, 0]
    won, played = attack[0] + defense[0], attack[1] + defense[1]
    return {"won": match["won"], "score": f"{won}-{played - won}" if played else "", "rr": match.get("rr")}


def backfill_results(store_dir, summary):
    """Write the result of any saved lobby that appears in this (your own) history summary; returns how many.

    # TODO(verify): assumes the pre-game / core-game match id equals matchInfo.matchId, which is what history lists.
    """
    updated = 0
    for match in (summary or {}).get("matches") or []:
        match_id, result = match.get("id") if isinstance(match, dict) else None, _result_of(match)
        if result is None or not isinstance(match_id, str) or not _SAFE_ID.match(match_id):
            continue
        path = os.path.join(store_dir, match_id + ".json")
        data = _read(path)
        if data is not None and data.get("result") != result:
            data["result"] = result
            _write(path, data)
            updated += 1
    return updated
