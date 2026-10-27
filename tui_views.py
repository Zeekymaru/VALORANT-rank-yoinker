"""Rich renderables for the TUI: the players-table cells and the five graph views.

Pure functions with no Textual import, so they can be checked through their plain text.
Everything here reads PlayerRow / history.summarise() data and never touches the network."""
from itertools import accumulate

from rich.table import Table
from rich.text import Text

import history
from lobby_data import ALLY_RGB, ENEMY_RGB, SELF_RGB, party_rgb, rank_label, readable_rgb
from src.constants import AGENTCOLORLIST

GRAPHS = [("form", "Form"), ("sides", "Atk/Def"), ("agents", "Agents"), ("teams", "Teams"), ("rr", "RR trend")]
COLUMNS = ["", "Agent", "Name", "Rank", "RR", "Peak", "HS", "WR", "Lvl", "ΔRR", "Recent", "Form"]
BAR_WIDTH = 20
SPARK = "▁▂▃▄▅▆▇█"
GREEN = (90, 225, 110)
RED = (235, 80, 80)
DIM = "dim"


def rgb_style(rgb):
    return f"rgb({rgb[0]},{rgb[1]},{rgb[2]})" if rgb else ""


def wr_style(percent):
    return rgb_style(history.win_rate_rgb(percent))


def percent(won, played):
    return int(100 * won / played + 0.5) if played else None


def bar(fraction, width=BAR_WIDTH):
    filled = round(max(0.0, min(1.0, fraction)) * width)
    return "█" * filled + "░" * (width - filled)


def sparkline(values):
    if not values:
        return ""
    low, high = min(values), max(values)
    if high == low:
        return SPARK[3] * len(values)
    return "".join(SPARK[round((v - low) / (high - low) * (len(SPARK) - 1))] for v in values)


# --- players table cells -----------------------------------------------------------------

def _num(value):
    return "" if value is None else str(value)


def name_text(row):
    rgb = SELF_RGB if row.is_self else (ALLY_RGB if row.ally else ENEMY_RGB)
    return Text(row.name or "…", style=rgb_style(rgb))


def agent_text(row):
    if not row.agent:
        return Text("")
    rgb = readable_rgb(AGENTCOLORLIST.get(row.agent.lower(), (230, 230, 230)))
    return Text(row.agent, style=rgb_style(rgb) + ("" if row.locked else " dim"))


def party_text(row):
    return Text("■", style=rgb_style(party_rgb(row.party))) if row.party else Text("")


def rank_text(row):
    if row.stats_state != "done":
        return Text("…", style=DIM)
    return Text(row.rank or "?", style=rgb_style(row.rank_rgb))


def peak_text(row):
    return Text(row.peak, style=rgb_style(row.peak_rgb)) if row.stats_state == "done" else Text("")


def delta_text(row):
    value = row.rr_delta
    if isinstance(value, (int, float)):
        return Text(f"{value:+d}" if value else "0", style=rgb_style(GREEN if value > 0 else RED if value < 0 else None))
    return Text("N/A" if row.stats_state == "done" else "", style=DIM)


def wr_text(row):
    if isinstance(row.wr, int):
        return Text(f"{row.wr} ({row.games})", style=wr_style(row.wr))
    return Text("N/A" if row.stats_state == "done" else "", style=DIM)


def recent_text(row):
    if row.history_state == "skipped":
        return Text("")
    if row.history_state != "done":
        return Text("…", style=DIM)
    summary = row.history or {}
    if not summary.get("available"):
        return Text("no comp games" if summary.get("reason") == history.REASON_NO_GAMES else "unavailable",
                    style=DIM)
    pct = percent(summary["wins"], summary["games"])
    return Text(f"{pct}% {summary['wins']}/{summary['games']}", style=wr_style(pct))


def _form_dots(summary):
    """One dot per sampled game, newest first: filled green = win, hollow red = loss."""
    text = Text()
    for match in (summary or {}).get("matches", []):
        text.append("● " if match["won"] else "○ ", style=rgb_style(GREEN if match["won"] else RED))
    return text


def form_text(row):
    return _form_dots(row.history if row.history_state == "done" else None)


def hs_text(row):
    if isinstance(row.hs, (int, float)):
        return Text(str(row.hs))
    return Text("N/A" if row.stats_state == "done" else "", style=DIM)


def row_cells(row):
    """The row's cells, in COLUMNS order."""
    return [
        party_text(row), agent_text(row), name_text(row), rank_text(row), Text(_num(row.rr)),
        peak_text(row), hs_text(row), wr_text(row), Text(_num(row.level)), delta_text(row),
        recent_text(row), form_text(row),
    ]


# --- card view ----------------------------------------------------------------------------

def _agent_record(name, games, wins):
    """'Sage 2-0' (wins-losses); summaries cached before per-agent wins existed give 'Sage ×2'."""
    if wins is None:
        return name if games == 1 else f"{name} ×{games}"
    return f"{name} {wins}-{games - wins}"


def _sides_line(summary):
    if "attack" not in summary or "defense" not in summary:
        return None
    line = Text()
    for index, (label, key) in enumerate((("Atk", "attack"), ("Def", "defense"))):
        record = summary[key]
        pct = percent(record["won"], record["rounds"])
        line.append(" · " if index else "")
        line.append(f"{label} ")
        if pct is None:
            line.append("-", style=DIM)
        else:
            line.append(f"{pct}% ({record['rounds']})", style=wr_style(pct))
    return line


def recent_block(summary, agent_names, map_name=""):
    """The card's history lines, like the console's Recent cell:

        60% 3/5  ● ● ○ ● ○
        Sova 1-0 · Skye 0-1 · Viper 1-0
        Init2 Ctrl1 Duel1 Sent1
        Atk 53% (32) · Def 48% (31)
        Ascent 2-1
    """
    if not _usable(summary):
        reason = (summary or {}).get("reason")
        return Text("no recent comp games" if reason == history.REASON_NO_GAMES else "history unavailable", style=DIM)
    pct = percent(summary["wins"], summary["games"])
    text = Text(f"{pct}% {summary['wins']}/{summary['games']}", style=wr_style(pct) + " bold")
    text.append("   ")
    text.append_text(_form_dots(summary))
    text.append("\n" + " · ".join(_agent_record(agent_names.get(a["agent_id"], "Unknown"), a["games"], a.get("wins"))
                                  for a in summary["top_agents"]))
    roles = " ".join(f"{history.ROLE_SHORT.get(role, role)}{count}" for role, count in
                     sorted(summary["roles"].items(), key=lambda kv: (-kv[1], kv[0])))
    text.append("\n" + roles, style=DIM)
    sides = _sides_line(summary)
    if sides is not None:
        text.append("\n")
        text.append_text(sides)
    record = summary.get("map")
    if map_name and record is not None:
        if record["games"]:
            map_pct = percent(record["wins"], record["games"])
            text.append(f"\n{map_name} {record['wins']}-{record['games'] - record['wins']}", style=wr_style(map_pct))
        else:
            text.append(f"\n{map_name} -", style=DIM)
    return text


def card_text(row, agent_names, map_name=""):
    """Everything about one player for the card view: identity, rank, season stats, then recent history."""
    text = Text()
    if row.party:
        text.append_text(party_text(row))
        text.append(" ")
    name = name_text(row)
    name.stylize("bold")
    text.append_text(name)
    text.append("\n")
    text.append_text(agent_text(row))
    if row.level is not None:
        text.append(f"  Lvl {row.level}", style=DIM)
    text.append("\n")
    text.append_text(rank_text(row))
    if row.rr not in (None, ""):
        text.append(f" ({row.rr})")
    if row.peak:
        text.append("   peak ", style=DIM)
        text.append_text(peak_text(row))
    text.append("\nHS ")
    text.append_text(hs_text(row))
    text.append("  WR ")
    text.append_text(wr_text(row))
    text.append("  ΔRR ")
    text.append_text(delta_text(row))
    if row.history_state == "skipped":
        return text
    text.append("\n\n")
    if row.history_state != "done":
        text.append("history …", style=DIM)
    else:
        text.append_text(recent_block(row.history, agent_names, map_name))
    return text


# --- graph views --------------------------------------------------------------------------

def _no_history(summary):
    if summary is None:
        return Text("Loading match history…", style=DIM)
    reason = summary.get("reason")
    message = {
        history.REASON_NO_GAMES: "No recent competitive games.",
        history.REASON_NO_RESULT: "Matches were found but none had a readable result.",
    }.get(reason, "History unavailable (private profile, an error, or rate limiting).")
    return Text(message, style=DIM)


def _usable(summary):
    return bool(summary) and summary.get("available")


def form_view(summary, agent_names, map_names):
    """Last games newest first: a W/L strip, then agent, map, side rounds and RR for each."""
    if not _usable(summary):
        return _no_history(summary)
    matches = summary.get("matches")
    if matches is None:
        return Text("Per-match detail isn't in this cached summary yet; it fills in on the next refresh.", style=DIM)
    text = Text(f"Last {len(matches)} competitive games, newest first\n\n", style="bold")
    for match in matches:
        text.append(" W " if match["won"] else " L ",
                    style=f"bold black on {rgb_style(GREEN if match['won'] else RED)}")
        text.append(" ")
    text.append("\n\n")
    for number, match in enumerate(matches, 1):
        agent = agent_names.get(match["agent"], "Unknown")
        map_name = map_names.get(match.get("map") or "", "—")
        text.append(f"{number:>2}  ")
        text.append("W" if match["won"] else "L", style=rgb_style(GREEN if match["won"] else RED) + " bold")
        text.append(f"  {agent:<9}{map_name:<10}")
        text.append(f"Atk {match['attack'][0]}/{match['attack'][1]:<3} Def {match['defense'][0]}/{match['defense'][1]:<3}")
        rr = match.get("rr")
        if rr is not None:
            text.append(f"  {rr:+d} RR", style=rgb_style(GREEN if rr > 0 else RED if rr < 0 else None))
        text.append("\n")
    return text


def _side_line(label, record):
    rounds = record["rounds"]
    pct = percent(record["won"], rounds)
    line = Text(f"{label:<8}")
    if pct is None:
        line.append("no rounds", style=DIM)
    else:
        line.append(bar(pct / 100), style=wr_style(pct))
        line.append(f" {pct}%  ({record['won']}/{rounds})")
    return line


def sides_view(summary):
    """The player's team's round win rate on attack and on defense across the sampled games."""
    if not _usable(summary):
        return _no_history(summary)
    if "attack" not in summary:
        return Text("Round data isn't in this cached summary yet; it fills in on the next refresh.", style=DIM)
    text = Text("Round win rate by side\n\n", style="bold")
    text.append_text(_side_line("Attack", summary["attack"]))
    text.append("\n")
    text.append_text(_side_line("Defense", summary["defense"]))
    text.append("\n\nThe player's team's rounds in the sampled games, not their own stats.", style=DIM)
    return text


def agents_view(summary, agent_names):
    """Top agents (share of games, wins-losses) and the role split."""
    if not _usable(summary):
        return _no_history(summary)
    games = summary["games"]
    text = Text(f"Agents, last {games} games (wins-losses)\n\n", style="bold")
    for agent in summary["top_agents"]:
        wins = agent.get("wins")
        record = f"{wins}-{agent['games'] - wins}" if wins is not None else f"×{agent['games']}"
        name = agent_names.get(agent["agent_id"], "Unknown")
        rgb = readable_rgb(AGENTCOLORLIST.get(name.lower(), (230, 230, 230)))
        text.append(f"{name:<10}", style=rgb_style(rgb))
        text.append(bar(agent["games"] / games, 14) + f"  {record}\n")
    text.append("\nRoles (games)\n\n", style="bold")
    for role, count in sorted(summary["roles"].items(), key=lambda kv: (-kv[1], kv[0])):
        text.append(f"{role:<11}")
        text.append(bar(count / games, 14) + f"  {count}\n")
    return text


def team_stats(rows):
    """Aggregates for one team's rows: recent win rate, side win rates, average rank, premades."""
    wins = games = attack_won = attack_rounds = defense_won = defense_rounds = loaded = 0
    tiers, parties = [], set()
    for row in rows:
        summary = row.history if row.history_state == "done" else None
        if _usable(summary):
            loaded += 1
            wins += summary["wins"]
            games += summary["games"]
            if "attack" in summary:
                attack_won += summary["attack"]["won"]
                attack_rounds += summary["attack"]["rounds"]
                defense_won += summary["defense"]["won"]
                defense_rounds += summary["defense"]["rounds"]
        if row.tier is not None and row.tier >= 3:  # tiers 0-2 are unranked
            tiers.append(row.tier)
        if row.party:
            parties.add(row.party)
    return {
        "players": len(rows), "history_loaded": loaded,
        "wr": percent(wins, games), "attack": percent(attack_won, attack_rounds),
        "defense": percent(defense_won, defense_rounds),
        "avg_rank": rank_label(round(sum(tiers) / len(tiers)))[0] if tiers else None,
        "premades": len(parties),
    }


def _pct_cell(value):
    if value is None:
        return Text("—", style=DIM)
    cell = Text(bar(value / 100, 12), style=wr_style(value))
    cell.append(f" {value}%")
    return cell


def teams_view(rows):
    """Your team vs the enemy team, side by side."""
    ally = team_stats([r for r in rows if r.ally])
    enemy_rows = [r for r in rows if not r.ally]
    enemy = team_stats(enemy_rows) if enemy_rows else None
    table = Table(title="Team comparison (sampled competitive games)", title_justify="left", box=None,
                  padding=(0, 2), expand=False)
    table.add_column("")
    table.add_column("Your team", no_wrap=True)
    table.add_column("Enemy team", no_wrap=True)
    for label, key in (("Recent WR", "wr"), ("Attack", "attack"), ("Defense", "defense")):
        table.add_row(label, _pct_cell(ally[key]), _pct_cell(enemy[key]) if enemy else Text("hidden", style=DIM))
    table.add_row("Avg rank", Text(ally["avg_rank"] or "—"),
                  Text((enemy["avg_rank"] or "—") if enemy else "hidden", style="" if enemy else DIM))
    table.add_row("Premades", Text(str(ally["premades"])), Text(str(enemy["premades"]) if enemy else "hidden",
                                                              style="" if enemy else DIM))
    table.add_row("History", Text(f"{ally['history_loaded']}/{ally['players']}"),
                  Text(f"{enemy['history_loaded']}/{enemy['players']}") if enemy else Text("hidden", style=DIM))
    return table


def rr_series(summary):
    """RR earned in each sampled game that has it, oldest first."""
    return [m["rr"] for m in reversed((summary or {}).get("matches") or []) if m.get("rr") is not None]


def rr_view(summary):
    """Net RR over the sampled games as a sparkline, plus each game's change."""
    if not _usable(summary):
        return _no_history(summary)
    series = rr_series(summary)
    if not series:
        return Text("No RR data for these games (the history entries carried no RankedRatingEarned).", style=DIM)
    net = list(accumulate(series))
    text = Text("Net RR over the sampled games, oldest → newest\n\n", style="bold")
    text.append(sparkline([0] + net), style=rgb_style(GREEN if net[-1] >= 0 else RED))
    text.append(f"   net {net[-1]:+d}\n\n")
    for change in series:
        text.append(f"{change:+d}  ", style=rgb_style(GREEN if change > 0 else RED if change < 0 else None))
    return text


def team_strip(rows):
    """Two-line summary above the table: one line per team."""
    lines = []
    for label, group in (("YOUR TEAM", [r for r in rows if r.ally]), ("ENEMY TEAM", [r for r in rows if not r.ally])):
        if not group:
            continue
        s = team_stats(group)
        parts = [f"avg {s['avg_rank'] or '—'}",
                 f"recent WR {s['wr']}%" if s["wr"] is not None else "recent WR —",
                 f"Atk {s['attack']}% Def {s['defense']}%" if s["attack"] is not None else "Atk — Def —",
                 f"{s['premades']} premade{'s' if s['premades'] != 1 else ''}"]
        lines.append(f"{label:<11}" + " · ".join(parts))
    return Text("\n".join(lines))
