"""Saved lobbies: snapshot, save, list, load, prune and result backfill (all on a temp directory, no network)."""
import json
import os

import pytest

import lobby_store
from lobby_data import LobbyModel, LobbyReset, PlayerRow


def make_model(match_id="match-1", state="INGAME"):
    rows = [PlayerRow(puuid="p1", name="Zeek#1", ally=True, is_self=True, agent="Jett", rank="Gold 3",
                      rank_rgb=(10, 20, 30), peak_rgb=(1, 2, 3), tier=14, history_state="done",
                      history={"available": True, "games": 3, "wins": 2, "stats": {"games": 3}}),
            PlayerRow(puuid="p2", name="Foe#2", ally=False, history_state="skipped")]
    model = LobbyModel()
    model.apply(LobbyReset(state=state, rows=rows, map_name="Ascent", map_id="/Game/Maps/Ascent/Ascent",
                           mode="Competitive", server="pod", match_id=match_id))
    return model


def snap(model=None, started=1000.0, **kwargs):
    return lobby_store.build_snapshot(model or make_model(), {"a1": "Jett"}, {"/m": "Ascent"}, started,
                                      {"you": "Jett", "ally_avg": "Gold 3", "enemy_avg": ""}, now=started + 60, **kwargs)


def test_round_trip_keeps_rows_history_names_and_tuples(tmp_path):
    path = lobby_store.save(str(tmp_path), snap())
    assert os.path.basename(path) == "match-1.json"
    loaded = lobby_store.load(path)
    assert loaded["map_name"] == "Ascent" and loaded["mode"] == "Competitive" and loaded["match_id"] == "match-1"
    assert loaded["agent_names"] == {"a1": "Jett"} and loaded["map_names"] == {"/m": "Ascent"}
    rows = lobby_store.rows_from(loaded)
    assert [r.puuid for r in rows] == ["p1", "p2"] and rows[0].is_self and not rows[1].ally
    assert rows[0].rank_rgb == (10, 20, 30) and rows[0].peak_rgb == (1, 2, 3)  # tuples again, not lists
    assert rows[0].history["wins"] == 2 and rows[1].history_state == "skipped"


def test_saving_the_same_lobby_again_replaces_it(tmp_path):
    lobby_store.save(str(tmp_path), snap())
    lobby_store.save(str(tmp_path), snap(started=2000.0))
    assert len(os.listdir(tmp_path)) == 1


def test_a_lobby_without_a_usable_match_id_is_named_by_its_start_time(tmp_path):
    for bad in ("", None, "../evil", "a/b", "x" * 80):
        path = lobby_store.save(str(tmp_path), snap(make_model(match_id=bad), started=1234.9))
        assert os.path.dirname(path) == str(tmp_path) and os.path.basename(path) == "t1234.json"


def test_list_is_newest_first_and_skips_unreadable_files(tmp_path):
    lobby_store.save(str(tmp_path), snap(make_model("old"), started=1000.0))
    lobby_store.save(str(tmp_path), snap(make_model("new", state="PREGAME"), started=5000.0))
    (tmp_path / "broken.json").write_text("{not json")
    (tmp_path / "other.json").write_text(json.dumps({"version": 99, "rows": []}))
    (tmp_path / "notes.txt").write_text("ignore me")
    entries = lobby_store.list_saved(str(tmp_path))
    assert [os.path.basename(e["path"]) for e in entries] == ["new.json", "old.json"]
    first = entries[0]
    assert first["map_name"] == "Ascent" and first["state"] == "PREGAME" and first["players"] == 2
    assert first["summary"]["you"] == "Jett" and first["result"] is None
    assert lobby_store.list_saved(str(tmp_path / "missing")) == []
    assert len(lobby_store.list_saved(str(tmp_path), limit=1)) == 1


def test_load_rejects_missing_corrupt_and_foreign_files(tmp_path):
    assert lobby_store.load(str(tmp_path / "nope.json")) is None
    (tmp_path / "bad.json").write_text("{")
    assert lobby_store.load(str(tmp_path / "bad.json")) is None
    (tmp_path / "v.json").write_text(json.dumps({"version": 2, "rows": []}))
    assert lobby_store.load(str(tmp_path / "v.json")) is None


def test_rows_from_ignores_unknown_fields_and_rows_without_an_id():
    rows = lobby_store.rows_from({"rows": [{"puuid": "a", "name": "A", "future_field": 1}, {"name": "no id"}, 7]})
    assert [r.puuid for r in rows] == ["a"] and rows[0].name == "A"


def test_prune_keeps_only_the_newest(tmp_path):
    for index in range(5):
        path = lobby_store.save(str(tmp_path), snap(make_model(f"m{index}"), started=1000.0 + index))
        os.utime(path, (1000 + index, 1000 + index))
    lobby_store.prune(str(tmp_path), keep=2)
    assert sorted(os.listdir(tmp_path)) == ["m3.json", "m4.json"]


def history_with(*matches):
    return {"available": True, "matches": list(matches)}


def test_results_are_filled_in_from_your_own_history(tmp_path):
    lobby_store.save(str(tmp_path), snap(make_model("won-game")))
    lobby_store.save(str(tmp_path), snap(make_model("lost-game")))
    summary = history_with(
        {"id": "won-game", "won": True, "attack": [8, 12], "defense": [5, 11], "rr": 21},
        {"id": "lost-game", "won": False, "attack": [4, 12], "defense": [4, 12], "rr": None},
        {"id": "not-saved", "won": True, "attack": [1, 1], "defense": [1, 1]},
        {"id": "../evil", "won": True, "attack": [1, 1], "defense": [1, 1]},
        {"id": "no-outcome", "won": None})
    assert lobby_store.backfill_results(str(tmp_path), summary) == 2
    results = {os.path.basename(e["path"]): e["result"] for e in lobby_store.list_saved(str(tmp_path))}
    assert results["won-game.json"] == {"won": True, "score": "13-10", "rr": 21}
    assert results["lost-game.json"] == {"won": False, "score": "8-16", "rr": None}
    assert lobby_store.backfill_results(str(tmp_path), summary) == 0  # nothing new the second time
    assert lobby_store.backfill_results(str(tmp_path), None) == 0


def test_a_later_save_keeps_the_result_already_filled_in(tmp_path):
    lobby_store.save(str(tmp_path), snap())
    lobby_store.backfill_results(str(tmp_path), history_with(
        {"id": "match-1", "won": True, "attack": [7, 12], "defense": [6, 12], "rr": 10}))
    lobby_store.save(str(tmp_path), snap())  # e.g. the lobby is flushed again on quit
    assert lobby_store.list_saved(str(tmp_path))[0]["result"]["won"] is True


@pytest.mark.parametrize("attack,defense,score", [([0, 0], [0, 0], ""), ([13, 20], [0, 3], "13-10")])
def test_result_score_from_side_rounds(attack, defense, score):
    assert lobby_store._result_of({"won": True, "attack": attack, "defense": defense})["score"] == score


def test_history_filters_hide_imports_and_dodges_by_default():
    entry = lambda state, imported=False, result=None: {"state": state, "imported": imported, "result": result}  # noqa: E731
    entries = [entry("INGAME", result={"won": True}), entry("INGAME", result={"won": False}), entry("INGAME"),
               entry("PREGAME"), entry("INGAME", imported=True, result={"won": True})]
    count = lambda mode: len(lobby_store.filter_entries(entries, mode))  # noqa: E731
    assert (count("played"), count("all"), count("won"), count("lost"), count("imported"), count("dodged")) == \
        (3, 5, 2, 1, 1, 1)
    assert count("nonsense") == 3  # an unknown mode falls back to played games
