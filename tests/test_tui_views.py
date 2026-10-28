"""Tests for tui_views.py: table cells and the five graph views, checked through their plain text."""
import io

from rich.console import Console

import history
import tui_views
from lobby_data import PlayerRow

NAMES = {"agent-jett": "Jett", "agent-sage": "Sage"}
MAPS = {"/game/maps/ascent/ascent": "Ascent"}


def summary(**overrides):
    data = {
        "available": True, "games": 3, "wins": 2,
        "top_agents": [{"agent_id": "agent-jett", "games": 2, "wins": 1},
                       {"agent_id": "agent-sage", "games": 1, "wins": 1}],
        "roles": {"Duelist": 2, "Sentinel": 1},
        "attack": {"won": 1, "rounds": 3}, "defense": {"won": 3, "rounds": 5},
        "matches": [
            {"id": "m1", "agent": "agent-jett", "won": True, "map": "/game/maps/ascent/ascent",
             "attack": [1, 2], "defense": [1, 1], "rr": 21},
            {"id": "m2", "agent": "agent-jett", "won": False, "map": None, "attack": [0, 1], "defense": [0, 1],
             "rr": -18},
            {"id": "m3", "agent": "agent-sage", "won": True, "map": "/game/maps/ascent/ascent",
             "attack": [0, 0], "defense": [2, 3], "rr": None},
        ],
    }
    data.update(overrides)
    return data


def loaded_row(**fields):
    row = PlayerRow(puuid="p", name="Zeek#1", agent="Jett", level=120, party=1, stats_state="done",
                    tier=14, rank="Gold 3", rr=40, peak="Plat 1 (e7a3)", hs=22, wr=51, games=30, rr_delta=18,
                    history=summary(), history_state="done")
    for key, value in fields.items():
        setattr(row, key, value)
    return row


def plain(renderable):
    if hasattr(renderable, "plain"):
        return renderable.plain
    console = Console(file=io.StringIO(), width=100, color_system=None)
    console.print(renderable)
    return console.file.getvalue()


def test_bar_and_sparkline():
    assert tui_views.bar(0.5, 10) == "█████░░░░░"
    assert tui_views.bar(-1, 4) == "░░░░" and tui_views.bar(9, 4) == "████"
    assert tui_views.sparkline([]) == ""
    assert tui_views.sparkline([5, 5, 5]) == "▄▄▄"
    assert tui_views.sparkline([0, 10]) == "▁█"
    assert tui_views.percent(2, 3) == 67 and tui_views.percent(0, 0) is None


def test_row_cells_match_the_columns():
    cells = tui_views.row_cells(loaded_row())
    assert len(cells) == len(tui_views.COLUMNS)
    assert [c.plain for c in cells] == ["■", "Jett", "Zeek#1", "Gold 3", "40", "Plat 1 (e7a3)", "22", "51 (30)",
                                        "120", "+18", "67% 2/3", "● ○ ● ", "", ""]


def test_cells_while_loading_and_when_data_is_missing():
    row = PlayerRow(puuid="p", name="Zeek#1")
    cells = [c.plain for c in tui_views.row_cells(row)]
    assert cells[3] == "…" and cells[10] == "…"  # rank and recent are still loading
    row = loaded_row(hs="N/A", wr="N/A", rr_delta="N/A", level=None, party=0, history=history._unavailable())
    cells = [c.plain for c in tui_views.row_cells(row)]
    assert (cells[0], cells[6], cells[7], cells[8], cells[9], cells[10]) == ("", "N/A", "N/A", "", "N/A", "unavailable")
    assert tui_views.recent_text(loaded_row(history=history._unavailable(history.REASON_NO_GAMES))).plain == "no comp games"
    assert tui_views.recent_text(loaded_row(history_state="skipped")).plain == ""
    assert tui_views.form_text(loaded_row(history=None)).plain == ""


def test_form_view_lists_each_game():
    text = tui_views.form_view(summary(), NAMES, MAPS).plain
    assert "Last 3 competitive games, newest first" in text
    assert " W " in text and " L " in text
    lines = text.splitlines()
    assert any(line.startswith(" 1  W  Jett") and "Ascent" in line and "Atk 1/2" in line and "Def 1/1" in line
               and "+21 RR" in line for line in lines)
    assert any(line.startswith(" 2  L  Jett") and "—" in line and "-18 RR" in line for line in lines)  # unknown map
    assert any(line.startswith(" 3  W  Sage") and "RR" not in line for line in lines)  # no RR value


def test_card_text_has_identity_season_stats_and_recent_history():
    row = loaded_row(history=summary(map={"games": 2, "wins": 1}))
    lines = tui_views.card_text(row, NAMES, "Ascent").plain.splitlines()
    assert lines == [
        "■ Zeek#1",
        "Jett  Lvl 120",
        "Gold 3 (40)   peak Plat 1 (e7a3)",
        "HS 22  WR 51 (30)  ΔRR +18",
        "",
        "67% 2/3   ● ○ ● ",
        "Jett 1-1 · Sage 1-0",
        "Duel2 Sent1",
        "Atk 33% (3) · Def 60% (5)",
        "Ascent 1-1",
    ]


def test_card_text_while_loading_and_without_history():
    row = PlayerRow(puuid="p", name="Zeek#1", agent="Jett")
    text = tui_views.card_text(row, NAMES, "Ascent").plain
    assert text.splitlines()[0] == "Zeek#1" and text.endswith("history …")  # no party square, still loading
    assert "…" in text.splitlines()[2]  # rank not loaded yet

    skipped = tui_views.card_text(loaded_row(history_state="skipped"), NAMES).plain
    assert skipped.splitlines()[-1].startswith("HS ")  # menus: no history block at all

    for reason, message in ((history.REASON_NO_GAMES, "no recent comp games"),
                            (history.REASON_UNAVAILABLE, "history unavailable")):
        card = tui_views.card_text(loaded_row(history=history._unavailable(reason)), NAMES).plain
        assert card.splitlines()[-1] == message


def test_recent_block_leaves_out_what_the_summary_lacks():
    legacy = summary(top_agents=[{"agent_id": "agent-jett", "games": 2}])
    del legacy["attack"], legacy["defense"], legacy["matches"]
    lines = tui_views.recent_block(legacy, NAMES, "Ascent").plain.splitlines()
    assert lines == ["67% 2/3   ", "Jett ×2", "Duel2 Sent1"]  # no sides, no form dots, no map record
    assert tui_views.recent_block(summary(map={"games": 0, "wins": 0}), NAMES, "Ascent").plain.endswith("Ascent -")
    assert "Ascent" not in tui_views.recent_block(summary(map={"games": 2, "wins": 1}), NAMES, "").plain


def test_views_explain_missing_data():
    assert "Loading" in plain(tui_views.form_view(None, NAMES, MAPS))
    assert "No recent competitive games" in plain(tui_views.sides_view(history._unavailable(history.REASON_NO_GAMES)))
    assert "readable result" in plain(tui_views.agents_view(history._unavailable(history.REASON_NO_RESULT), NAMES))
    assert "unavailable" in plain(tui_views.rr_view(history._unavailable()))
    legacy = summary()
    del legacy["matches"], legacy["attack"], legacy["defense"]
    assert "fills in on the next refresh" in plain(tui_views.form_view(legacy, NAMES, MAPS))
    assert "fills in on the next refresh" in plain(tui_views.sides_view(legacy))


def test_sides_view():
    text = tui_views.sides_view(summary()).plain
    assert "Attack" in text and "33%  (1/3)" in text
    assert "Defense" in text and "60%  (3/5)" in text
    empty = summary(attack={"won": 0, "rounds": 0})
    assert "no rounds" in tui_views.sides_view(empty).plain


def test_agents_view_shows_records_and_roles():
    text = tui_views.agents_view(summary(), NAMES).plain
    assert "Jett" in text and "1-1" in text and "Sage" in text and "1-0" in text
    assert "Duelist" in text and "Sentinel" in text
    legacy = summary(top_agents=[{"agent_id": "agent-jett", "games": 2}])
    assert "×2" in tui_views.agents_view(legacy, NAMES).plain  # cached before per-agent wins existed


def test_rr_series_and_view():
    assert tui_views.rr_series(summary()) == [-18, 21]  # oldest first, games without RR skipped
    text = tui_views.rr_view(summary()).plain
    assert "net +3" in text and "-18" in text and "+21" in text
    assert "No RR data" in tui_views.rr_view(summary(matches=[{"rr": None, "won": True}])).plain
    assert tui_views.rr_series(None) == []


def test_team_stats_and_views():
    ally = [loaded_row(puuid="a", tier=14, party=1), loaded_row(puuid="b", tier=16, party=1),
            loaded_row(puuid="c", tier=0, party=0, history=history._unavailable())]
    enemy = [loaded_row(puuid="d", ally=False, tier=11, party=2)]
    stats = tui_views.team_stats(ally)
    assert (stats["players"], stats["history_loaded"], stats["premades"]) == (3, 2, 1)
    assert stats["wr"] == 67 and stats["attack"] == 33 and stats["defense"] == 60
    assert stats["avg_rank"] == history_rank(15)  # unranked players are left out of the average

    text = plain(tui_views.teams_view(ally + enemy))
    assert "Your team" in text and "Enemy team" in text and "67%" in text and "2/3" in text
    assert "hidden" in plain(tui_views.teams_view(ally))  # agent select: the enemy team isn't visible

    strip = tui_views.team_strip(ally + enemy).plain.splitlines()
    assert strip[0].startswith("YOUR TEAM") and "recent WR 67%" in strip[0] and "1 premade" in strip[0]
    assert strip[1].startswith("ENEMY TEAM")
    assert tui_views.team_strip([]).plain == ""


def history_rank(tier):
    from lobby_data import rank_label
    return rank_label(tier)[0]


def _stats(**overrides):
    base = {"games": 3, "rounds": 60, "score": 12000, "kills": 40, "deaths": 36, "assists": 12, "damage": 9000,
            "headshots": 20, "bodyshots": 60, "legshots": 20, "first_bloods": 6, "first_deaths": 5,
            "kast_rounds": 44, "casts": 150, "plants": 1, "defuses": 1}
    base.update(overrides)
    return base


def _with_stats(**overrides):
    data = summary(stats=_stats(**overrides))
    for match in data["matches"]:
        match["stats"] = {"score": 4000, "rounds": 20}
    return data


def test_profile_view_ranks_the_selected_player_within_the_lobby():
    rows = [loaded_row(puuid="p1", history=_with_stats()),
            loaded_row(puuid="p2", history=_with_stats(damage=12000, kast_rounds=55)),
            loaded_row(puuid="p3", history=history._unavailable())]
    text = tui_views.profile_view(rows, "p1").plain
    assert text.startswith("Profile vs 2 players in this lobby · 3 games, 60 rounds")
    assert all(label in text for label, _ in tui_views.profile.AXES)
    assert "ADR 150" in text and "KAST 73%" in text and "ACS 200" in text and "40/36/12" in text
    assert "●" in text and "Few games" not in text
    assert "Few games" in tui_views.profile_view(
        [loaded_row(puuid="p1", history=_with_stats(games=2))], "p1").plain


def test_profile_view_explains_missing_data():
    assert "No player selected" in plain(tui_views.profile_view([], "x"))
    assert "unavailable" in plain(tui_views.profile_view([loaded_row(history=history._unavailable())], "p"))
    assert "Loading" in plain(tui_views.profile_view([loaded_row(history_state="pending", history=None)], "p"))
    legacy = loaded_row()  # a summary cached before performance counts existed
    assert "fills in on the next refresh" in plain(tui_views.profile_view([legacy], "p"))


def test_radar_canvas_marks_each_known_axis_and_the_ring():
    text = tui_views.radar_canvas([1.0, 0.5, 0.2, None, 0.8, 0.5]).plain
    assert text.count("●") == 5  # one marker per known axis
    assert any(0x2801 <= ord(ch) <= 0x28FF for ch in text)  # the drawing is braille
    assert all(label in text for label, _ in tui_views.profile.AXES)


def test_card_shows_a_performance_line_when_stats_exist():
    lines = tui_views.recent_block(_with_stats(), NAMES, "").plain.splitlines()
    assert "ACS 200 ADR 150 K/D 1.11 KAST 73%" in lines
    assert not any(line.startswith("ACS") for line in tui_views.recent_block(summary(), NAMES, "").plain.splitlines())


def test_percentile_colours_run_from_red_to_green():
    low, high = tui_views.percentile_rgb(0.0), tui_views.percentile_rgb(1.0)
    assert low[0] > low[1] and high[1] > high[0]


def test_radar_canvas_dims_for_small_samples_and_survives_few_points():
    styles = {str(span.style) for span in tui_views.radar_canvas([0.9, 0.1, 0.5, 0.5, 0.5, 0.5], dimmed=True).spans}
    assert styles and all("dim" in s for s in styles if "rgb" in s)
    assert tui_views.radar_canvas([None] * 6).plain.count("●") == 0
    assert tui_views.radar_canvas([0.7, None, None, None, None, None]).plain.count("●") == 1


def _lobby():
    return [loaded_row(puuid="a1", name="Zeek#1", history=_with_stats()),
            loaded_row(puuid="a2", name="Mate#2", history=_with_stats(damage=12000, kast_rounds=55, first_bloods=12)),
            loaded_row(puuid="e1", name="Foe#3", ally=False, history=_with_stats(damage=6000, first_bloods=2)),
            loaded_row(puuid="e2", name="Hidden#4", ally=False, history=history._unavailable())]


def test_fingerprint_is_one_block_per_axis_as_tall_as_the_rank():
    axes = {"Aim": 1.0, "Entry": 0.5, "Survival": 0.0, "Utility": None, "Objective": 0.99, "Consistency": 0.25}
    assert tui_views.fingerprint(axes).plain == "█▅▁·█▃"
    assert tui_views.fingerprint(axes, spaced=True).plain == "█ ▅ ▁ · █ ▃"
    assert tui_views.fingerprint(None).plain == "" and tui_views.fingerprint({}).plain == ""
    assert all("dim" in str(s.style) for s in tui_views.fingerprint(axes, dimmed=True).spans if "rgb" in str(s.style))
    assert len(tui_views.COLUMNS) == len(tui_views.row_cells(loaded_row()))


def test_the_list_row_and_card_carry_the_fingerprint():
    rows = _lobby()
    axes = tui_views.lobby_axes(rows)
    assert axes["e2"] is None
    cells = tui_views.row_cells(rows[1], axes["a2"])
    assert len(cells[-1].plain) == 6 and cells[-1].plain != ""
    card = tui_views.card_text(rows[1], NAMES, "Ascent", axes["a2"]).plain
    assert any(line.startswith("Profile ") for line in card.splitlines())
    assert "Profile" not in tui_views.card_text(rows[1], NAMES, "Ascent").plain


def test_heat_view_ranks_everyone_and_averages_each_team():
    text = plain(tui_views.heat_view(_lobby(), "a2"))
    assert "percentile among the 3 players with data" in text
    assert all(header in text for header in tui_views.HEAT_HEADERS.values())
    lines = text.splitlines()
    assert any(line.lstrip().startswith("▶ Mate#2") for line in lines)  # the selected player is marked
    assert any("Zeek#1" in line and "▶" not in line for line in lines)
    assert any("Your team avg" in line for line in lines) and any("Enemy avg" in line for line in lines)
    hidden = next(line for line in lines if "Hidden#4" in line)
    assert hidden.count("—") == 6  # no data: dashes rather than numbers
    assert "Loading" in plain(tui_views.heat_view([loaded_row(history_state="pending", history=None)], "p"))
    assert "isn't available" in plain(tui_views.heat_view([loaded_row(history=history._unavailable())], "p"))


def test_scatter_points_scale_the_rates_and_skip_players_without_data():
    points = tui_views.scatter_points(_lobby(), "adr", "first_blood", "a2")
    assert [p["name"] for p in points] == ["Zeek", "Mate", "Foe"]  # the hidden player has no point
    zeek, mate, foe = points
    assert zeek["x"] == 150 and round(zeek["y"], 1) == 10.0  # ADR as is; first bloods as % of rounds
    assert mate["selected"] and not zeek["selected"] and zeek["ally"] and not foe["ally"]
    assert all(set(p) == {"name", "ally", "selected", "x", "y"} for p in points)


def test_scatter_caption_and_fallback():
    points = tui_views.scatter_points(_lobby(), "adr", "first_blood")
    caption = tui_views.scatter_caption(0, points).plain
    assert caption.startswith("First-blood rate (% of rounds)  vs  ADR") and "1/5" in caption and "top right" in caption
    assert "2/5" in tui_views.scatter_caption(1, points).plain
    assert tui_views.scatter_caption(5, points).plain.startswith("First-blood")  # wraps around
    assert "Not enough players" in tui_views.scatter_caption(0, points[:1]).plain
    fallback = tui_views.scatter_fallback(0, points).plain
    assert "requirements-tui-charts.txt" in fallback and "Mate" in fallback


def test_archetype_text_shows_style_trait_runner_up_and_roughness():
    full = {"label": "Support", "score": 0.8, "also": "Fragger", "trait": "steady", "rough": False}
    assert tui_views.archetype_text(full).plain == "Support · steady · also Fragger"
    assert tui_views.archetype_text(full, full=False).plain == "Support"
    assert tui_views.archetype_text(dict(full, rough=True)).plain.endswith(" ?")
    assert tui_views.archetype_text(None).plain == ""


def test_archetype_shows_on_the_card_profile_view_and_heatmap():
    rows = _lobby()
    axes = tui_views.lobby_axes(rows)
    card = tui_views.card_text(rows[1], NAMES, "", axes["a2"]).plain
    profile_line = next(line for line in card.splitlines() if line.startswith("Profile "))
    assert len(profile_line) > len("Profile ") + 11  # blocks plus a style name
    view = tui_views.profile_view(rows, "a2").plain
    assert "Style  " in view and "relative to this lobby" in view
    heat = plain(tui_views.heat_view(rows, "a2"))
    assert "Style" in heat.splitlines()[3] or any("Style" in line for line in heat.splitlines()[:6])


def test_leaders_view_names_the_top_player_per_stat_and_both_team_averages():
    text = plain(tui_views.leaders_view(_lobby()))
    assert "Lobby leaders" in text and "ACS" in text and "KAST" in text and "Team average" in text
    assert plain(tui_views.leaders_view([])).startswith("Lobby leaders appear")


def test_compare_view_sets_you_against_the_selected_player():
    rows = [loaded_row(puuid="me", name="Me#1", is_self=True, history=_with_stats()),
            loaded_row(puuid="p2", name="Foe#2", ally=False, history=_with_stats(damage=12000, kast_rounds=55)),
            loaded_row(puuid="p3", history=history._unavailable())]
    text = tui_views.compare_view(rows, "p2").plain
    assert text.startswith("You vs Foe#2   3 vs 3 games")
    assert all(label in text for label, _ in tui_views.profile.AXES)
    assert "ADR" in text and "150" in text and "200" in text  # your ADR 150 and ACS 200 are printed
    assert "+" in text or "-" in text  # a gap column exists


def test_compare_view_explains_what_is_missing():
    me = loaded_row(puuid="me", is_self=True, history=_with_stats())
    other = loaded_row(puuid="p2", history=_with_stats())
    assert "No player selected" in plain(tui_views.compare_view([me], "x"))
    assert "That's you" in plain(tui_views.compare_view([me, other], "me"))
    assert "which player is you" in plain(tui_views.compare_view([other], "p2"))
    pending = loaded_row(puuid="p2", history_state="pending", history=None)
    assert "has no performance counts" in plain(tui_views.compare_view([me, pending], "p2"))
    gone = loaded_row(puuid="me", is_self=True, history=history._unavailable())
    assert "aren't loaded yet" in plain(tui_views.compare_view([gone, other], "p2"))


def test_sort_filter_rows_orders_best_first_and_leaves_missing_data_last():
    rows = [loaded_row(puuid="p1", ally=True, tier=10, history=_with_stats()),
            loaded_row(puuid="p2", ally=False, tier=21, history=_with_stats(damage=12000)),
            loaded_row(puuid="p3", ally=False, tier=14, history=history._unavailable())]
    ids = lambda **kw: [r.puuid for r in tui_views.sort_filter_rows(rows, **kw)]  # noqa: E731
    assert ids() == ["p1", "p2", "p3"]
    assert ids(sort_key="tier") == ["p2", "p3", "p1"]
    assert ids(sort_key="adr") == ["p2", "p1", "p3"]  # p2 dealt more damage; p3 has no counts, so it goes last
    assert ids(sort_key="adr", filter_key="enemy") == ["p2", "p3"]
    assert ids(filter_key="ally") == ["p1"]
    assert len(rows) == 3  # the input is untouched


def test_team_strip_does_not_claim_zero_premades_where_they_cannot_be_known():
    rows = [loaded_row(puuid="a", ally=True, party=0), loaded_row(puuid="e", ally=False, party=0)]
    assert tui_views.team_strip(rows).plain.splitlines()[0].endswith("0 premades")
    lines = tui_views.team_strip(rows).plain.splitlines()
    assert lines[1].endswith("premades n/a")  # the enemy's groups aren't visible live
    assert all(line.endswith("premades n/a") for line in tui_views.team_strip(rows, premades_known=False).plain.splitlines())


def _threat_profile(acs, adr, first_blood=0.1, hs=0.2, games=5):
    return {"acs": acs, "adr": adr, "first_blood": first_blood, "hs": hs, "games": games}


def test_threat_flags_rank_acs_and_adr_within_the_lobby():
    profiles = {f"p{i}": _threat_profile(150 + 20 * i, 100 + 12 * i) for i in range(10)}
    profiles["none"] = None
    flags = tui_views.profile.threat_flags(profiles)
    assert flags["none"] is None
    # ten evenly spaced players sit at the 5th, 15th ... 95th percentile: the top two are high, the next watch
    assert [flags[f"p{i}"]["level"] for i in (9, 8, 7, 6, 0)] == ["high", "high", "watch", None, None]
    assert flags["p9"]["score"] > flags["p7"]["score"] > flags["p0"]["score"]


def test_threat_tags_and_the_rough_marker_and_the_small_lobby_rule():
    profiles = {f"p{i}": _threat_profile(200, 130, first_blood=0.05 + 0.01 * i, hs=0.1 + 0.02 * i, games=2)
                for i in range(10)}
    flags = tui_views.profile.threat_flags(profiles)
    assert flags["p9"]["tags"] == ["Entry", "Aim"] and flags["p0"]["tags"] == [] and flags["p9"]["rough"] is True
    assert tui_views.threat_text(flags["p9"]).plain.endswith("Entry Aim ?")
    few = tui_views.profile.threat_flags({f"p{i}": _threat_profile(200 + i, 100) for i in range(3)})
    assert all(flag is None for flag in few.values())  # three players with data is too few to rank anyone


def test_threat_text_and_strip_name_the_enemy_threats_only():
    rows = [loaded_row(puuid=f"p{i}", name=f"N{i}#1", ally=i < 5, history=_with_stats(damage=4000 + 1500 * i, score=9000 + 1500 * i))
            for i in range(10)]
    threats = tui_views.lobby_threats(rows)
    strip = tui_views.threat_strip(rows, threats).plain
    assert strip.startswith("ENEMY THREATS") and "N9" in strip and "N0" not in strip
    assert tui_views.threat_strip(rows[:5], tui_views.lobby_threats(rows[:5])).plain.endswith("none flagged yet")
    card = tui_views.card_text(rows[9], NAMES, "Ascent", None, threats["p9"]).plain
    assert "Threat ▲▲" in card and "higher than" in card
    assert "Threat" not in tui_views.card_text(rows[0], NAMES, "Ascent", None, threats["p0"]).plain
    ordered = [r.puuid for r in tui_views.sort_filter_rows(rows, "threat")]
    assert ordered[0] == "p9" and ordered[-1] == "p0"


def test_guns_view_lists_weapons_pistol_record_and_buys():
    stats = {"games": 4, "guns": {"v1": [30, 100], "p1": [10, 80], "g1": [1, 5]},
             "pistol": {"rounds": 8, "won": 6, "kills": 7, "deaths": 3},
             "buys": {"eco": {"rounds": 10, "won": 2, "kills": 4}, "full": {"rounds": 50, "won": 30, "kills": 40}}}
    summary = {"available": True, "games": 4, "stats": stats}
    plain = tui_views.guns_view(summary).plain
    assert tui_views.weapons.weapon_name("v1").startswith("id v1")  # unknown ids are shown, not hidden
    assert "30" in plain and "75%" in plain  # pistols won 6/8
    assert "Eco" in plain and "20% won" in plain and "Full buy" in plain and "60% won" in plain and "0.80 kills/round" in plain
    assert "—" in plain  # the 5-round weapon is too thin for a per-100 rate


def test_guns_view_handles_old_summaries_and_missing_data():
    old = {"available": True, "games": 3, "stats": {"games": 3, "kills": 5}}
    assert "next refresh" in tui_views.guns_view(old).plain
    assert tui_views.guns_view({"available": False}).plain  # same no-history text as the other views


def test_graph_keys_run_one_to_nine_then_zero():
    assert [tui_views.graph_key(n) for n in (1, 9, 10)] == ["1", "9", "0"]
    assert tui_views.GRAPHS[-1][0] == "guns"
