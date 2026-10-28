"""Tests for past_games.py: lobbies rebuilt from cached match details, no network."""
import json
import os

import lobby_store
import past_games

AGENTS = {"agent-jett": "Jett", "agent-sage": "Sage"}
MAPS = {"/game/maps/ascent/ascent": "Ascent"}
ME = "aaaaaaaa-0000-0000-0000-000000000001"


def player(index, team, agent="agent-jett", tier=14):
    return {"subject": f"aaaaaaaa-0000-0000-0000-{index:012d}", "gameName": f"P{index}", "tagLine": "EUW",
            "teamId": team, "partyId": f"team-{team}", "characterId": agent,
            "competitiveTier": tier, "accountLevel": 100 + index, "stats": {"score": 4000, "roundsPlayed": 20}}


def write_match(cache, match_id, start_ms, won=True, queue="competitive", completed=True):
    players = [player(i, "Blue" if i <= 5 else "Red") for i in range(1, 11)]
    players[0]["characterId"] = "agent-sage"
    details = {"matchInfo": {"matchId": match_id, "mapId": "/Game/Maps/Ascent/Ascent", "gameStartMillis": start_ms,
                             "queueID": queue, "isCompleted": completed, "gamePodId": "pod"},
               "players": players,
               "teams": [{"teamId": "Blue", "won": won, "roundsWon": 13 if won else 9},
                         {"teamId": "Red", "won": not won, "roundsWon": 9 if won else 13}],
               "roundResults": []}
    os.makedirs(os.path.join(cache, "matches"), exist_ok=True)
    with open(os.path.join(cache, "matches", f"{match_id}.json"), "w") as handle:
        json.dump(details, handle)


def run_import(tmp_path, **kwargs):
    cache, store = str(tmp_path / "cache"), str(tmp_path / "cache" / "lobbies")
    return cache, store, lambda: past_games.import_past(cache, store, [ME], AGENTS, MAPS, **kwargs)


def test_import_rebuilds_a_lobby_with_ranks_parties_result_and_history_from_earlier_games(tmp_path):
    cache, store, do_import = run_import(tmp_path)
    write_match(cache, "m-old", 1_000_000_000_000)
    write_match(cache, "m-new", 1_000_001_000_000, won=False)
    assert do_import() == 2
    snapshot = lobby_store.load(os.path.join(store, "m-new.json"))
    assert snapshot["imported"] and snapshot["map_name"] == "Ascent" and snapshot["mode"] == "Competitive"
    assert snapshot["result"] == {"won": False, "score": "9-13", "rr": None}
    rows = {r.puuid: r for r in lobby_store.rows_from(snapshot)}
    me = rows[ME]
    assert me.is_self and me.agent == "Sage" and me.rank == "Gold 3" and me.level == 101 and me.ally
    assert sum(1 for r in rows.values() if r.ally) == 5 and len(rows) == 10
    assert all(r.party == 0 for r in rows.values())  # the payload's partyId is the team's, so no premades are shown
    # history is only what came before this game: the old match, not the new one itself
    assert me.history["available"] and me.history["games"] == 1 and me.history["matches"][0]["id"] == "m-old"
    oldest = lobby_store.load(os.path.join(store, "m-old.json"))
    assert not any(r.history["available"] for r in lobby_store.rows_from(oldest))
    assert snapshot["summary"] == {"you": "Sage", "ally_avg": "Gold 3", "enemy_avg": "Gold 3"}


def test_import_is_repeatable_and_leaves_existing_saves_alone(tmp_path):
    cache, store, do_import = run_import(tmp_path)
    write_match(cache, "m1", 1_000_000_000_000)
    os.makedirs(store)
    with open(os.path.join(store, "m1.json"), "w") as handle:
        json.dump({"version": 1, "started_at": 1, "rows": [], "marker": "live"}, handle)
    write_match(cache, "m2", 1_000_001_000_000)
    assert do_import() == 1  # m1 was already saved
    assert json.load(open(os.path.join(store, "m1.json")))["marker"] == "live"
    assert do_import() == 0


def test_import_skips_games_you_were_not_in_unfinished_games_and_unknown_users(tmp_path):
    cache, store, do_import = run_import(tmp_path)
    write_match(cache, "unfinished", 1_000_000_000_000, completed=False)
    assert do_import() == 0
    other = past_games.import_past(cache, store, ["ffffffff-0000-0000-0000-000000000099"], AGENTS, MAPS)
    assert other == 0 and past_games.import_past(cache, store, [], AGENTS, MAPS) == 0


def test_import_keeps_the_newest_games_when_limited_and_dates_files_to_the_game(tmp_path):
    cache, store, do_import = run_import(tmp_path, limit=2)
    for n in range(4):
        write_match(cache, f"m{n}", 1_000_000_000_000 + n * 1_000_000)
    assert do_import() == 2
    assert sorted(os.listdir(store)) == ["m2.json", "m3.json"]
    assert int(os.path.getmtime(os.path.join(store, "m3.json"))) == 1_000_003_000


def test_saved_import_is_listed_as_imported_and_self_puuids_are_found(tmp_path):
    cache, store, do_import = run_import(tmp_path)
    write_match(cache, "m1", 1_000_000_000_000)
    do_import()
    assert [e["imported"] for e in lobby_store.list_saved(store)] == [True]
    assert lobby_store.self_puuids(store) == {ME}
    assert lobby_store.self_puuids(str(tmp_path / "missing")) == set()
