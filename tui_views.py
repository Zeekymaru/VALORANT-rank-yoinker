"""Rich renderables for the TUI: the players-table cells and the graph views.

Pure functions with no Textual import, so they can be checked through their plain text.
Everything here reads PlayerRow / history.summarise() data and never touches the network."""
import math
from itertools import accumulate

from rich.console import Group
from rich.table import Table
from rich.text import Text

import history
import match_stats
import weapons
import player_profile as profile
from lobby_data import ALLY_RGB, ENEMY_RGB, SELF_RGB, party_rgb, rank_label, readable_rgb
from src.constants import AGENTCOLORLIST

GRAPHS = [("form", "Form"), ("sides", "Atk/Def"), ("agents", "Agents"), ("teams", "Teams"), ("rr", "RR trend"),
          ("profile", "Profile"), ("heat", "Heatmap"), ("scatter", "Scatter"), ("compare", "Compare"), ("guns", "Guns")]
GUN_ROWS = 6  # weapons listed in the Guns view
GUN_RATE_MIN_HELD = 20  # rounds with a weapon in hand before its kills-per-100 figure is shown
BUY_LABELS = {"eco": "Eco", "half": "Half buy", "full": "Full buy"}


def graph_key(number):
    """The key that opens the number-th graph: 1-9, then 0 for the tenth."""
    return str(number % 10)


LOBBY_GRAPHS = ("teams", "heat", "scatter")  # about the whole lobby, not the selected player
# the last column is the fingerprint: one block per radar axis (Aim Entry Survival Utility Objective Consistency)
COLUMNS = ["", "Agent", "Name", "Rank", "RR", "Peak", "HS", "WR", "Lvl", "ΔRR", "Recent", "Form", "Threat", "AESUOC"]
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


THREAT_RGB = {"high": RED, "watch": (255, 165, 40)}
TAG_RGB = (110, 200, 235)


def threat_text(flag, full=False):
    """'▲▲ Entry' for a high threat, '▲' to watch, plus any tags; '?' marks a rough guess from few games."""
    if not flag or not (flag["level"] or flag["tags"]):
        return Text("")
    rough = "dim " if flag["rough"] else ""
    text = Text()
    if flag["level"]:
        text.append("▲▲" if flag["level"] == "high" else "▲", style=rough + "bold " + rgb_style(THREAT_RGB[flag["level"]]))
    for tag in flag["tags"]:
        text.append((" " if text.plain else "") + tag, style=rough + rgb_style(TAG_RGB))
    if flag["rough"]:
        text.append(" ?", style=DIM)
    if full and flag["level"]:
        text.append(f"   ACS/ADR higher than {flag['score'] * 100:.0f}% of this lobby", style=DIM)
    return text


def lobby_threats(rows):
    """{puuid: threat flag or None} for every row."""
    return profile.threat_flags(lobby_profiles(rows))


def row_cells(row, axes=None, threat=None):
    """The row's cells, in COLUMNS order. axes are the player's lobby percentiles (for the fingerprint)."""
    return [
        party_text(row), agent_text(row), name_text(row), rank_text(row), Text(_num(row.rr)),
        peak_text(row), hs_text(row), wr_text(row), Text(_num(row.level)), delta_text(row),
        recent_text(row), form_text(row), threat_text(threat), fingerprint(axes, _few_games(row.history)),
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


def recent_block(summary, agent_names, map_name="", axes=None):
    """The card's history lines, like the console's Recent cell:

        60% 3/5  ● ● ○ ● ○
        Sova 1-0 · Skye 0-1 · Viper 1-0
        Init2 Ctrl1 Duel1 Sent1
        Atk 53% (32) · Def 48% (31)
        ACS 227 · ADR 150 · K/D 1.08 · KAST 75%   (once match stats are cached)
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
    perf = profile.derive(summary)
    if perf is not None and perf["acs"] is not None:
        parts = [f"ACS {perf['acs']:.0f}", f"ADR {_fmt(perf['adr'], '.0f')}", f"K/D {_fmt(perf['kd'], '.2f')}",
                 f"KAST {_fmt(None if perf['kast'] is None else perf['kast'] * 100, '.0f')}%"]
        text.append("\n" + " ".join(parts), style=DIM)
    if axes:
        text.append("\nProfile ", style=DIM)
        text.append_text(fingerprint(axes, _few_games(summary), spaced=True))
        text.append("  ")
        text.append_text(archetype_text(profile.archetype(axes, _games(summary)), full=False))
    record = summary.get("map")
    if map_name and record is not None:
        if record["games"]:
            map_pct = percent(record["wins"], record["games"])
            text.append(f"\n{map_name} {record['wins']}-{record['games'] - record['wins']}", style=wr_style(map_pct))
        else:
            text.append(f"\n{map_name} -", style=DIM)
    return text


def card_text(row, agent_names, map_name="", axes=None, threat=None):
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
        text.append_text(recent_block(row.history, agent_names, map_name, axes))
        if threat and (threat["level"] or threat["tags"]):
            text.append("\nThreat ", style=DIM)
            text.append_text(threat_text(threat, full=True))
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


def guns_view(summary):
    """Kills by weapon, pistol-round record and round win rate by buy type across the sampled games."""
    if not _usable(summary):
        return _no_history(summary)
    stats = summary.get("stats") or {}
    guns, pistol, buys = stats.get("guns"), stats.get("pistol"), stats.get("buys")
    if guns is None and pistol is None and buys is None:
        return Text("Weapon and round data isn't in this cached summary yet; it fills in on the next refresh.", style=DIM)
    text = Text(f"Guns, last {stats.get('games') or summary['games']} games\n\n", style="bold")
    kills = sorted(((w, k, h) for w, (k, h) in (guns or {}).items() if k or h), key=lambda t: (-t[1], -t[2], t[0]))
    total = sum(k for _, k, _ in kills)
    if total:
        text.append(f"{'':<9}{'kills':>5}  {'share':<20}{'rounds':>6}  per 100\n", style=DIM)
        for weapon, count, held in kills[:GUN_ROWS]:
            rate = f"{100 * count / held:.0f}" if held >= GUN_RATE_MIN_HELD else "—"
            text.append(f"{weapons.weapon_name(weapon):<9}{count:>5}  ")
            text.append(bar(count / total, 14) + f"{held:>6}  {rate:>7}\n")
        if len(kills) > GUN_ROWS:
            text.append(f"+{len(kills) - GUN_ROWS} more weapons\n", style=DIM)
        text.append("Per 100 = kills per 100 rounds started with it.\n", style=DIM)
    else:
        text.append("No weapon kills recorded.\n", style=DIM)
    text.append("\nPistol rounds\n", style="bold")
    if pistol and pistol.get("rounds"):
        text.append("Team won ")
        text.append(f"{pistol['won']}/{pistol['rounds']}", style=wr_style(percent(pistol["won"], pistol["rounds"])))
        text.append(f" ({percent(pistol['won'], pistol['rounds']):.0f}%)   you {pistol['kills']} kills, {pistol['deaths']} deaths\n")
    else:
        text.append("None recorded.\n", style=DIM)
    text.append("\nBy buy (team's average loadout)\n", style="bold")
    shown = False
    for band in match_stats.BUY_TYPES:
        record = (buys or {}).get(band)
        if not record or not record["rounds"]:
            continue
        shown = True
        win = percent(record["won"], record["rounds"])
        text.append(f"{BUY_LABELS[band]:<9}{record['rounds']:>4} rounds  ")
        text.append(f"{win:>3.0f}% won", style=wr_style(win))
        text.append(f"   {record['kills'] / record['rounds']:.2f} kills/round\n")
    if not shown:
        text.append("No economy data recorded.\n", style=DIM)
    else:
        text.append("Eco < 1500, full >= 3500 per player; pistol rounds left out.\n", style=DIM)
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


SORTS = (("default", "Default"), ("tier", "Rank"), ("acs", "ACS"), ("adr", "ADR"), ("kd", "K/D"), ("kast", "KAST"),
         ("first_blood", "First bloods"), ("threat", "Threat"))
FILTERS = (("all", "Everyone"), ("ally", "Your team"), ("enemy", "Enemies"))


def sort_filter_rows(rows, sort_key="default", filter_key="all"):
    """The rows the players table shows: filtered by team, then ordered best-first by one stat (missing data last).

    Lobby-wide numbers (percentiles, leaders, team averages) are still worked out over every row, not just these."""
    shown = [r for r in rows if filter_key == "all" or r.ally == (filter_key == "ally")]
    if sort_key == "default":
        return shown
    if sort_key == "tier":
        values = {r.puuid: r.tier if isinstance(r.tier, int) and r.tier > 0 else None for r in shown}
    elif sort_key == "threat":
        threats = lobby_threats(rows)
        values = {r.puuid: (threats.get(r.puuid) or {}).get("score") for r in shown}
    else:
        profiles = lobby_profiles(rows)
        values = {r.puuid: (profiles.get(r.puuid) or {}).get(sort_key) for r in shown}
    return sorted(shown, key=lambda r: (values[r.puuid] is None, -(values[r.puuid] or 0)))  # stable: ties keep order


def team_strip(rows, premades_known=True):
    """Two-line summary above the table: one line per team. Premade counts are only trustworthy live, and only
    for your own side: the client doesn't reveal the enemy's groups, and a rebuilt (imported) lobby has none."""
    lines = []
    for label, group in (("YOUR TEAM", [r for r in rows if r.ally]), ("ENEMY TEAM", [r for r in rows if not r.ally])):
        if not group:
            continue
        s = team_stats(group)
        parts = [f"avg {s['avg_rank'] or '—'}",
                 f"recent WR {s['wr']}%" if s["wr"] is not None else "recent WR —",
                 f"Atk {s['attack']}% Def {s['defense']}%" if s["attack"] is not None else "Atk — Def —",
                 f"{s['premades']} premade{'s' if s['premades'] != 1 else ''}"
                 if premades_known and (label == "YOUR TEAM" or s["premades"]) else "premades n/a"]
        lines.append(f"{label:<11}" + " · ".join(parts))
    return Text("\n".join(lines))


def threat_strip(rows, threats):
    """One line naming the enemy players flagged as a threat, highest first (empty when nobody is)."""
    flagged = [(threats[r.puuid]["score"], r) for r in rows
               if not r.ally and threats.get(r.puuid) and (threats[r.puuid]["level"] or threats[r.puuid]["tags"])]
    text = Text("ENEMY THREATS ", style="bold")
    for index, (_, row) in enumerate(sorted(flagged, key=lambda item: -item[0])[:3]):
        text.append(" · " if index else "")
        text.append(row.name.split("#")[0] or "?")
        text.append(" ")
        text.append_text(threat_text(threats[row.puuid]))
    if not flagged:
        text.append("none flagged yet", style=DIM)
    return text


# --- profile radar ------------------------------------------------------------------------

RADAR_RADIUS = 24  # outer hexagon radius in braille dots (4 dots per text row, 2 per column: dots are ~square)
CYAN = (90, 200, 230)
GRID = (95, 95, 105)
RING = (140, 140, 155)
_BRAILLE = ((0x01, 0x08), (0x02, 0x10), (0x04, 0x20), (0x40, 0x80))  # [row in cell][column in cell]


def percentile_rgb(fraction):
    """Red -> yellow -> green for a 0..1 lobby percentile, readable on a dark background."""
    return history.win_rate_rgb(int(round(100 * fraction)))


class _Dots:
    """A canvas of braille dots in layers; a cell shows the union of its layers' dots in the top layer's colour."""

    def __init__(self, cells_wide, cells_high):
        self.w, self.h = cells_wide, cells_high
        self.layers = {name: [[0] * cells_wide for _ in range(cells_high)] for name in ("grid", "ring", "fill", "edge")}

    def plot(self, layer, x, y):
        x, y = int(round(x)), int(round(y))
        if 0 <= x < self.w * 2 and 0 <= y < self.h * 4:
            self.layers[layer][y // 4][x // 2] |= _BRAILLE[y % 4][x % 2]

    def line(self, layer, a, b):
        steps = int(max(abs(b[0] - a[0]), abs(b[1] - a[1]), 1))
        for i in range(steps + 1):
            self.plot(layer, a[0] + (b[0] - a[0]) * i / steps, a[1] + (b[1] - a[1]) * i / steps)

    def circle(self, layer, cx, cy, radius, dotted=False):
        for step in range(0, 360, 3 if dotted else 1):
            angle = math.radians(step)
            self.plot(layer, cx + radius * math.cos(angle), cy + radius * math.sin(angle))

    def fill(self, layer, polygon):
        """Sparse stippled fill (one dot in four) so the grid and ring show through."""
        ys = [p[1] for p in polygon]
        for y in range(int(min(ys)), int(max(ys)) + 1):
            crossings = []
            for (x0, y0), (x1, y1) in zip(polygon, polygon[1:] + polygon[:1]):
                if (y0 <= y < y1) or (y1 <= y < y0):
                    crossings.append(x0 + (y - y0) * (x1 - x0) / (y1 - y0))
            crossings.sort()
            for left, right in zip(crossings[::2], crossings[1::2]):
                for x in range(int(left) + 1, int(right)):
                    if x % 2 == 0 and y % 2 == 0:
                        self.plot(layer, x, y)

    def cell(self, row, col):
        """(braille character or None, layer that colours it)."""
        bits, top = 0, None
        for name in ("grid", "ring", "fill", "edge"):
            value = self.layers[name][row][col]
            if value:
                bits |= value
                top = name
        return (chr(0x2800 + bits), top) if bits else (None, None)


def radar_canvas(values, dimmed=False):
    """The radar as a Text: a braille drawing with the player's shape over the lobby ring, labels coloured by rank.

    values are 0..1 lobby percentiles in profile.AXES order (None = unknown). The grey ring is the lobby middle.
    """
    labels = [label for label, _ in profile.AXES]
    count, radius = len(labels), RADAR_RADIUS
    rows = radius // 2 + 1  # braille rows above and below the centre line
    pad = max(len(label) for label in labels) + 2
    cols = radius + 1 + 2 * pad  # radius dots = radius/2 cells each side
    cells_w = radius + 1
    left = pad
    dots = _Dots(cells_w, rows)
    cx, cy = radius, rows * 2  # centre in dots (rows*4 dots tall, centre line in the middle)

    def point(index, fraction):
        angle = math.pi / 2 - 2 * math.pi * index / count
        return (cx + radius * fraction * math.cos(angle), cy - radius * fraction * math.sin(angle))

    outer = [point(i, 1.0) for i in range(count)]
    for a, b in zip(outer, outer[1:] + outer[:1]):
        dots.line("grid", a, b)
    for p in outer:
        dots.line("grid", (cx, cy), p)
    dots.circle("ring", cx, cy, radius * 0.5, dotted=True)

    known = [(i, v) for i, v in enumerate(values) if v is not None]
    shape = [point(i, max(v, 0.04)) for i, v in known]
    if len(shape) > 2:
        dots.fill("fill", shape)
    if len(shape) > 1:
        for a, b in zip(shape, shape[1:] + shape[:1]):
            dots.line("edge", a, b)

    colours = {"grid": GRID, "ring": RING, "fill": CYAN, "edge": CYAN}
    fade = "dim " if dimmed else ""
    out_rows = [[(" ", "")] * cells_w for _ in range(rows)]
    for r in range(rows):
        for c in range(cells_w):
            char, layer = dots.cell(r, c)
            if char:
                style = fade + rgb_style(colours[layer])
                out_rows[r][c] = (char, ("dim " if layer == "fill" and not dimmed else "") + style
                                  if layer != "edge" else fade + "bold " + rgb_style(CYAN))
    # vertex markers, coloured by rank
    for (index, value), (x, y) in zip(known, shape):
        r, c = min(int(y) // 4, rows - 1), min(int(x) // 2, cells_w - 1)
        out_rows[r][c] = ("●", fade + "bold " + rgb_style(percentile_rgb(value)))

    height = rows + 2  # a label row above the top vertex and below the bottom one
    text_rows = [[(" ", "")] * cols for _ in range(height)]
    for r in range(rows):
        for c in range(cells_w):
            text_rows[r + 1][left + c] = out_rows[r][c]
    for index, label in enumerate(labels):
        x, y = outer[index]
        r, c = min(int(y) // 4, rows - 1) + 1, left + min(int(x) // 2, cells_w - 1)
        if abs(x - cx) < 1:  # top or bottom: centred above / below the vertex
            r += -1 if y < cy else 1
            start = c - len(label) // 2
        elif x > cx:
            start = c + 2
        else:
            start = c - 1 - len(label)
        value = values[index]
        style = fade + (rgb_style(percentile_rgb(value)) + " bold" if value is not None else "dim")
        for offset, char in enumerate(label):
            if 0 <= start + offset < cols:
                text_rows[r][start + offset] = (char, style)
    text = Text()
    for row in text_rows:
        for char, style in row:
            text.append(char, style=style or None)
        text.append("\n")
    return text


def _fmt(value, spec, missing="—"):
    return missing if value is None else format(value, spec)


def profile_view(rows, selected):
    """Radar and numbers for rows[selected] (a PlayerRow), ranked among every row with history in the lobby."""
    row = next((r for r in rows if r.puuid == selected), None)
    if row is None:
        return Text("No player selected yet.", style=DIM)
    summary = row.history if row.history_state == "done" else None
    if not _usable(summary):
        return _no_history(summary)
    profiles = lobby_profiles(rows)
    mine = profiles.get(selected)
    if mine is None:
        return Text("Per-match performance isn't in this cached summary yet; it fills in on the next refresh.",
                    style=DIM)
    axes = profile.radar_axes(profiles)[selected]
    compared = sum(1 for p in profiles.values() if p)
    dimmed = mine["games"] < profile.DIM_BELOW_GAMES
    text = Text(f"Profile vs {compared} player{'s' if compared != 1 else ''} in this lobby · "
                f"{mine['games']} game{'s' if mine['games'] != 1 else ''}, {mine['rounds']} rounds\n", style="bold")
    text.append("ring = lobby middle · outside it = above most of the lobby\n", style=DIM)
    if dimmed:
        text.append("Few games: treat this shape as a rough guess.\n", style=DIM)
    text.append("Style  ")
    text.append_text(archetype_text(profile.archetype(axes, mine["games"])))
    text.append("   (a guess from the axes below, relative to this lobby)\n", style=DIM)
    text.append_text(radar_canvas([axes[label] for label, _ in profile.AXES], dimmed))
    detail = {
        "Aim": f"ADR {_fmt(mine['adr'], '.0f')} · HS {_fmt(None if mine['hs'] is None else mine['hs'] * 100, '.0f')}%",
        "Entry": f"FB {_fmt(None if mine['first_blood'] is None else mine['first_blood'] * 100, '.0f')}%"
                 f" · FD {_fmt(None if mine['first_death'] is None else mine['first_death'] * 100, '.0f')}% of rounds",
        "Survival": f"KAST {_fmt(None if mine['kast'] is None else mine['kast'] * 100, '.0f')}%",
        "Utility": f"{_fmt(mine['util'], '.1f')} casts/round",
        "Objective": f"{_fmt(mine['objective'], '.1f')} plants+defuses/game",
        "Consistency": "score spread between games" if mine["consistency"] is not None else "needs 2+ games",
    }
    for label, _ in profile.AXES:
        value = axes[label]
        text.append(f"{label:<12}")
        if value is None:
            text.append("··········   —  ", style=DIM)
        else:
            colour = rgb_style(percentile_rgb(value))
            text.append(bar(value, 10), style=colour)
            text.append(f" {value * 100:3.0f}  ", style="bold " + colour)
        text.append(detail[label] + "\n", style=DIM)
    text.append(f"\nACS {_fmt(mine['acs'], '.0f')} · K/D {_fmt(mine['kd'], '.2f')} · "
                f"{_fmt(mine['kills'], 'd')}/{_fmt(mine['deaths'], 'd')}/{_fmt(mine['assists'], 'd')}")
    return text


# rate key -> (label, factor applied before printing, format); higher is better for every one of them
COMPARE_METRICS = (("acs", "ACS", 1, ".0f"), ("adr", "ADR", 1, ".0f"), ("kd", "K/D", 1, ".2f"),
                   ("hs", "Headshot %", 100, ".0f"), ("kast", "KAST %", 100, ".0f"),
                   ("first_blood", "First blood % of rounds", 100, ".1f"), ("util", "Casts per round", 1, ".1f"))


def compare_view(rows, selected):
    """You (the row marked is_self) against the selected player: each axis as two bars, then the raw rates with a gap.

    Both are ranked among the same lobby, so the bars are comparable. Green means you are ahead, red behind."""
    row = next((r for r in rows if r.puuid == selected), None)
    me = next((r for r in rows if r.is_self), None)
    if row is None:
        return Text("No player selected yet.", style=DIM)
    if me is None:
        return Text("Can't tell which player is you in this lobby.", style=DIM)
    if row.puuid == me.puuid:
        return Text("That's you. Pick another player to compare against.", style=DIM)
    profiles = lobby_profiles(rows)
    if not profiles.get(me.puuid):
        return Text("Your own performance counts aren't loaded yet (they come from your match history).", style=DIM)
    if not profiles.get(row.puuid):
        return Text(f"{row.name} has no performance counts to compare (private, still loading or not cached yet).",
                    style=DIM)
    mine, theirs = profiles[me.puuid], profiles[row.puuid]
    axes = profile.radar_axes(profiles)
    text = Text(f"You vs {row.name}", style="bold")
    text.append(f"   {mine['games']} vs {theirs['games']} games\n", style=DIM)
    text.append("You   ", style=rgb_style(SELF_RGB))
    text.append_text(archetype_text(profile.archetype(axes[me.puuid], mine["games"])))
    text.append("\n" + f"{row.name[:5]:<6}", style=rgb_style(ALLY_RGB if row.ally else ENEMY_RGB))
    text.append_text(archetype_text(profile.archetype(axes[row.puuid], theirs["games"])))
    text.append("\n\nLobby percentile (0 = lowest, 100 = highest in this lobby)\n", style=DIM)
    for label, _ in profile.AXES:
        a, b = axes[me.puuid][label], axes[row.puuid][label]
        text.append(f"{label:<12}")
        for value in (a, b):
            if value is None:
                text.append("··········   —  ", style=DIM)
            else:
                text.append(bar(value, 10), style=rgb_style(percentile_rgb(value)))
                text.append(f" {value * 100:3.0f}  ", style="bold " + rgb_style(percentile_rgb(value)))
        if a is not None and b is not None:
            gap = (a - b) * 100
            text.append(f"{gap:+4.0f}", style=rgb_style(GREEN if gap > 2 else RED if gap < -2 else (150, 150, 160)))
        text.append("\n")
    text.append(f"\n{'':<26}{'you':>8}{row.name[:8]:>10}{'gap':>9}\n", style=DIM)
    for key, label, factor, spec in COMPARE_METRICS:
        a, b = mine.get(key), theirs.get(key)
        text.append(f"{label:<26}", style=DIM)
        text.append(f"{_fmt(None if a is None else a * factor, spec):>8}")
        text.append(f"{_fmt(None if b is None else b * factor, spec):>10}")
        if a is not None and b is not None:
            gap = (a - b) * factor
            text.append(f"{format(gap, '+' + spec):>9}",
                        style=rgb_style(GREEN if gap > 0 else RED if gap < 0 else (150, 150, 160)))
        text.append("\n")
    return text


# --- fingerprint, heatmap and scatter (lobby-wide) -----------------------------------------

LEVELS = "▁▂▃▄▅▆▇█"
HEAT_HEADERS = {"Aim": "Aim", "Entry": "Entry", "Survival": "Surv", "Utility": "Util", "Objective": "Obj",
                "Consistency": "Cons"}


def lobby_profiles(rows):
    """{puuid: rates or None} for every row; rows whose history hasn't loaded (or has no counts) are None."""
    return {r.puuid: profile.derive(r.history) if r.history_state == "done" else None for r in rows}


def lobby_axes(rows):
    """{puuid: {axis: percentile or None} or None}: each player ranked among the lobby's players."""
    return profile.radar_axes(lobby_profiles(rows))


def _few_games(summary):
    stats = (summary or {}).get("stats") if isinstance(summary, dict) else None
    return isinstance(stats, dict) and (stats.get("games") or 0) < profile.DIM_BELOW_GAMES


def _games(summary):
    stats = (summary or {}).get("stats") if isinstance(summary, dict) else None
    return stats.get("games") if isinstance(stats, dict) else None


def archetype_text(arch, full=True):
    """'Support · steady · also Fragger' (full) or just the style; a '?' marks a rough guess from few games."""
    if not arch:
        return Text("")
    muted = arch["rough"] or arch["label"] == profile.BALANCED
    text = Text(arch["label"], style=DIM if muted else "bold " + rgb_style(CYAN))
    if full:
        if arch["trait"]:
            text.append(f" · {arch['trait']}", style=DIM)
        if arch["also"]:
            text.append(f" · also {arch['also']}", style=DIM)
    if arch["rough"]:
        text.append(" ?", style=DIM)
    return text


def fingerprint(axes, dimmed=False, spaced=False):
    """Six blocks, one per radar axis, as tall as the player's rank in the lobby and coloured red -> green."""
    text = Text()
    if not axes:
        return text
    for index, (label, _) in enumerate(profile.AXES):
        value = axes.get(label)
        if index and spaced:
            text.append(" ")
        if value is None:
            text.append("·", style=DIM)
        else:
            text.append(LEVELS[min(len(LEVELS) - 1, int(value * len(LEVELS)))],
                        style=("dim " if dimmed else "") + rgb_style(percentile_rgb(value)))
    return text


def _heat_cell(value):
    if value is None:
        return Text(" — ", style=DIM, justify="center")
    return Text(f"{value * 100:3.0f} ", style=f"bold black on {rgb_style(percentile_rgb(value))}", justify="center")


def _average(axes_list):
    out = {}
    for label, _ in profile.AXES:
        values = [a[label] for a in axes_list if a and a.get(label) is not None]
        out[label] = sum(values) / len(values) if values else None
    return out


def heat_view(rows, selected):
    """Every player against every axis, coloured by lobby percentile, with a row of team averages per team."""
    profiles = lobby_profiles(rows)
    axes = profile.radar_axes(profiles)
    if not any(axes.values()):
        loaded = any(r.history_state == "done" for r in rows)
        return Text("Per-match performance isn't available for anyone yet; it fills in as history loads or "
                    "after the next refresh." if loaded else "Loading match history…", style=DIM)
    table = Table(box=None, pad_edge=False, header_style="bold", show_edge=False, padding=(0, 1, 0, 0))
    table.add_column("Player", no_wrap=True)
    for label, _ in profile.AXES:
        table.add_column(HEAT_HEADERS[label], justify="center", no_wrap=True)
    table.add_column("Style", no_wrap=True)
    for ally in (True, False):
        group = [r for r in rows if r.ally == ally]
        if not group:
            continue
        for row in group:
            name = name_text(row)
            name.truncate(12, overflow="ellipsis", pad=True)
            if row.puuid == selected:
                name.stylize("bold")
            lead = Text("▶ " if row.puuid == selected else "  ")
            mine = axes.get(row.puuid)
            games = (profiles.get(row.puuid) or {}).get("games")
            table.add_row(lead + name, *[_heat_cell(mine.get(label) if mine else None) for label, _ in profile.AXES],
                          archetype_text(profile.archetype(mine, games), full=False))
        avg = _average([axes.get(r.puuid) for r in group])
        table.add_row(Text("  " + ("Your team avg" if ally else "Enemy avg"), style="italic dim"),
                      *[_heat_cell(avg[label]) for label, _ in profile.AXES], "")
        table.add_row(*[""] * (len(profile.AXES) + 2))
    head = Text(f"Every player against every axis · percentile among the {sum(1 for p in profiles.values() if p)} "
                "players with data\n", style="bold")
    head.append("red = low in this lobby · green = high · 50 = lobby middle · Style is a guess (? = few games)\n\n",
                style=DIM)
    return Group(head, table)


def scatter_points(rows, x_key, y_key, selected=None):
    """One point per player with both rates, scaled for plotting: name, team, selected flag, x, y."""
    profiles = lobby_profiles(rows)
    fx, fy = profile.METRICS[x_key][1], profile.METRICS[y_key][1]
    points = []
    for row in rows:
        p = profiles.get(row.puuid)
        if p and p.get(x_key) is not None and p.get(y_key) is not None:
            points.append({"name": (row.name or "?").split("#")[0], "ally": row.ally,
                           "selected": row.puuid == selected, "x": p[x_key] * fx, "y": p[y_key] * fy})
    return points


def scatter_caption(index, points):
    x_key, y_key = profile.SCATTERS[index % len(profile.SCATTERS)]
    text = Text(f"{profile.METRICS[y_key][0]}  vs  {profile.METRICS[x_key][0]}"
                f"   ({index % len(profile.SCATTERS) + 1}/{len(profile.SCATTERS)}, s = next pairing)\n", style="bold")
    if len(points) < 2:
        text.append("Not enough players with performance data yet.", style=DIM)
    else:
        text.append("top right = high on both · dashed lines = lobby average · "
                    "cyan = your team, red = enemy, yellow = selected", style=DIM)
    return text


def scatter_fallback(index, points):
    """Without textual-plotext: the same pairing as a plain list."""
    x_key, y_key = profile.SCATTERS[index % len(profile.SCATTERS)]
    text = Text("\nInstall requirements-tui-charts.txt for the scatter plot. Values:\n", style=DIM)
    for point in sorted(points, key=lambda p: -p["y"]):
        text.append(f"{point['name']:<14}{profile.METRICS[x_key][0][:10]} {point['x']:>6.1f}   "
                    f"{profile.METRICS[y_key][0][:10]} {point['y']:>6.1f}\n",
                    style=rgb_style(CYAN) if point["ally"] else rgb_style(RED))
    return text


# --- lobby leaders (list view's detail strip) ------------------------------------------------

LEADERS = (("ACS", "acs", ".0f", 1), ("ADR", "adr", ".0f", 1), ("K/D", "kd", ".2f", 1), ("KAST", "kast", "%", 100),
           ("First bloods", "first_blood", "%", 100), ("Util / round", "util", ".1f", 1))


def _leader_value(value, spec):
    return f"{value * 100:.0f}%" if spec == "%" else format(value, spec)


def leaders_view(rows, selected=None):
    """Who tops each stat in the lobby (name coloured by team, you in your own colour) and each team's average."""
    profiles = {r.puuid: p for r, p in ((r, lobby_profiles(rows).get(r.puuid)) for r in rows) if p}
    if not profiles:
        return Text("Lobby leaders appear once players' match stats have loaded.", style=DIM)
    by_puuid = {r.puuid: r for r in rows}
    text = Text("Lobby leaders\n", style="bold")
    for label, key, spec, _ in LEADERS:
        ranked = sorted(((p[key], puuid) for puuid, p in profiles.items() if p.get(key) is not None), reverse=True)
        text.append(f"{label:<13}", style=DIM)
        for value, puuid in ranked[:2]:
            row = by_puuid[puuid]
            name = name_text(row)
            name.truncate(11, overflow="ellipsis")
            if puuid == selected:
                name.stylize("reverse")
            text.append_text(name)
            text.append(f" {_leader_value(value, spec)}  ", style="bold")
        text.append("\n")
    sides = {True: [], False: []}
    for puuid, p in profiles.items():
        sides[by_puuid[puuid].ally].append(p)
    if all(sides.values()):
        text.append("\nTeam average ", style=DIM)
        text.append("(you / enemy)\n", style=DIM)
        for label, key, spec, _ in LEADERS[:4]:
            cells = []
            for ally in (True, False):
                values = [p[key] for p in sides[ally] if p.get(key) is not None]
                cells.append(_leader_value(sum(values) / len(values), spec) if values else "—")
            text.append(f"{label:<13}", style=DIM)
            text.append(f"{cells[0]:>6}", style=rgb_style(ALLY_RGB))
            text.append("  /  ", style=DIM)
            text.append(f"{cells[1]:<6}\n", style=rgb_style(ENEMY_RGB))
    return text


def detail_view(row, rows, agent_names, map_name, axes, threat=None):
    """The list view's detail strip, two parts: (card + lobby leaders, profile) for the selected row."""
    if row is None:
        return Text("No player selected yet.", style=DIM), Text("")
    left = Group(card_text(row, agent_names, map_name, axes, threat), Text(""), leaders_view(rows, row.puuid))
    return left, profile_view(rows, row.puuid)
