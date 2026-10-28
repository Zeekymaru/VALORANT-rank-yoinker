<p align="center">
    <a href="https://github.com/isaacKenyon/valorant-rank-yoinker/">
        <img src="assets/Logo.png" alt="Logo" width="160" height="160">
    </a>
<h5 align="center"> VALORANT rank yoinker</h5>

[![Discord][discord-shield]][discord-url]
[![Downloads][downloads-shield]][downloads-url]

> [!CAUTION]
> vRY has published its final release, no changes will be made to the code.
> 
> [Community forks](COMMUNITY.md) may be maintained.

---

  <ol>
    <li><a href="#about-the-project">About The Project</a></li>
    <li><a href="#usage">Usage</a></li>
    <li><a href="#contributing">Contributing</a></li>
    <li><a href="#contact">Contact</a></li>
    <li><a href="#acknowledgements">Acknowledgements</a></li>
    <li><a href="#disclaimer">Disclaimer</a></li>
  </ol>


## About The Project

![Screenshot](assets/Example.png)
![Skin Showcase Image](assets/SkinShowcase.png)

|Current Skin|Current Rank|Rank Rating|Peak Rank|Account Level|
|:---:|:---:|:---:|:---:|:---:|
|![Skin](assets/Skin.png)|![Rank](assets/Rank.png)|![Rating](assets/Rating.png)|![Peak](assets/PeakRank.png)|![Level](assets/Level.png)|


## Usage
**VALORANT must be open**.

### Bundled Release:

1) Download [Microsoft Visual C++ Libraries](https://github.com/abbodi1406/vcredist/releases)
2) Download the [release](https://github.com/isaacKenyon/valorant-rank-yoinker/releases/latest).
3) Extract **all** files.
4) Run vRY.exe.

### Running from source:

1) Download Python [3.11](https://www.python.org/downloads/release/python-3119/) or [3.10](https://www.python.org/downloads/release/python-31011/), make sure it is added to the PATH. (This is an option on installation.)
2) Download the [source](https://github.com/isaacKenyon/VALORANT-rank-yoinker/archive/refs/heads/main.zip).
3) Run **`INSTALL.bat`** file (or use `pip install -r requirements.txt` in the terminal)
4) Run **`START.bat`** file (or use `python main.py` in the terminal)

### Compiling from source:

1) `pip install cx_Freeze`
2) `python setup.py build`
3)  Open the new Build folder and find vRY.exe.

> `-` You can change the desired weapon by editing the gun in `config.json`, or by deleting the file for vRY re-prompt you.

> `-` View all skins: <https://vry.netlify.app/matchLoadouts>.

### Letting Github Build It:

The latest commits to the `main` branch will be built by a [Github Actions](https://github.com/isaacKenyon/VALORANT-rank-yoinker/actions) workflow
and a successful build should result in a compiled artifact that you can download and try out.
See the [Actions tab](https://github.com/isaacKenyon/VALORANT-rank-yoinker/actions), click on the `Build` workflow,
select a particular workflow run, and it should have an artifact available for download.

If you want to make a small change to the application, you can:
1) [Fork](https://github.com/isaacKenyon/VALORANT-rank-yoinker/fork) this project.
2) Change the code in your forked repository.
3) Let the Github Actions workflow build vRY.exe for you.
4) Download it and test it.
5) Submit a Pull Request if you would like your change included in future releases.

## Lobby history (experimental)

One extra **Recent** column for each player in the lobby (INGAME and PREGAME), up to five lines per player:

```
60% 3/5                           win rate and sample size over the last 5 competitive games
Sova 1-0 · Skye 1-0 · Viper 1-0   top 3 agents in those games, as wins-losses with each agent
Init2 Ctrl1 Duel1 Sent1           games per role (not wins), across all the sampled games
Atk 54% (32) · Def 48% (31)       the player's team's round win rate on each side (rounds played)
Ascent 2-1                        wins-losses on the current map (see below)
```

The attack/defense line is the team's rounds in those games, not the player's own stats.

Players whose history is private or unavailable show `history unavailable`; players with no recent competitive games
show `no recent comp games`.

* Windows-only, and **unverified against the live API**: every unchecked endpoint/field is marked `# TODO(verify)` in
  `history.py`.
* Uses the local client's tokens, like the rest of vRY. A 401, 403 or 404 means "unavailable" and is not worked around.
* The 5-game sample costs one history request plus up to 5 match-detail requests per player. The **map record** only
  looks at those same 5 games (`LIST_DEPTH = 5` in `history.py`), so it costs nothing extra but is often empty
  (`Ascent -`) or a single game. Raise `LIST_DEPTH` (e.g. to 20) to look further back: the history request stays one
  request, but up to 5 more matches on the lobby's map are then fetched per player (`DEFAULT_MAP_MATCHES`), which
  roughly doubles a cold lobby's requests. Turn the map line off with `"map_history": false` under `table` in
  `config.json`. It relies on the history entries carrying a map ID (unverified); without one it is skipped and
  nothing extra is fetched. Finished matches and per-player results are cached in `cache/` (git-ignored; it holds other players' IDs
  from match data). Agent roles come from a table in `history.py`; a new agent shows as `Unknown`
  until it is added.
* Turn it off with `"lobby_history": false` in the `table` section of `config.json`.
* Riot's API policy (see below) applies here too. Whether other players' match history counts as data the client hides
  is not verified.
* The **Party** column (same-colored squares mark players queued together) is switched on in this fork; set
  `"party": false` in the `table` section of `config.json` to hide it again. Not verified live yet.
* Tests: `pip install -r requirements-dev.txt`, then `pytest`.

## TUI (experimental)

An interactive Textual screen next to the console app (`main.py` is untouched). Players fill in row by row, and a
side panel switches between five graphs with the buttons or the 1-5 keys: **Form** (last games, newest first, with
agent, map, side rounds and RR), **Atk/Def** (the team's round win rate per side), **Agents** (wins-losses per agent
and the role split), **Teams** (your team vs the enemy side by side) and **RR trend** (a sparkline, or a line chart
if `textual-plotext` is installed) and **Profile** (key 6), **Heatmap** (key 7), **Scatter** (key 8) and **Compare** (key 9), see below. Arrow keys pick the player the graph is about, `r` reloads, `q` quits.

The left side has two views, switched with `v` or the **View** button. **List** is one compact line per player.
Under the table, the list view has a **detail strip** for the selected player: their card, a **Lobby leaders** block
(who tops ACS, ADR, K/D, KAST, first bloods and utility, plus each team's average) and their profile radar, all
following the arrow keys. **Cards** shows each player as a card (identity, rank, season stats and the full Recent block), your team and the
enemy team in separate sections, three cards per row on a wide terminal. In the card view the arrow keys move
between cards and clicking a card selects it. The selected player is shared between the views, and the graph panel
follows it.

**Profile** is a radar chart of six axes for the selected player: Aim (ADR and headshot %), Entry (first bloods minus
first deaths), Survival (KAST), Utility (ability casts per round), Objective (plants and defuses per game) and
Consistency (how steady their score is between games). Each axis is the player's **percentile among the players in this
lobby**, so the dotted ring is the middle of the lobby and a point outside it beats most of the lobby; it isn't an
absolute skill rating, and the same player can look different in another lobby. It rests on the same 5 games as
the rest, so with fewer than 3 games it is drawn dimmed. Cards also get an `ACS ADR K/D KAST` line and a fingerprint.

* **Fingerprint:** six blocks, one per radar axis in the order Aim, Entry, Survival, Utility, Objective, Consistency
  (the `AESUOC` column in the list, a `Profile` line on the cards). A block is as tall as the player's rank in the
  lobby and coloured red (low) to green (high); a dot means no data. It is recomputed whenever anyone's history arrives.
* **Heatmap (7):** every player against every axis as coloured percentiles, plus a team-average row for each side and
  each player's style.
* **Style (archetype):** a guess from the axes, relative to this lobby, shown on the cards, in the Profile view
  and in the heatmap. A style is a weighted blend of axes: **Entry fragger** (entry + aim), **Fragger** (aim + survival,
  not entry), **Support** (utility + survival + objective), **Anchor** (survival, not entry) and **Objective player**
  (plants/defuses + utility); the best blend at 0.68 or above wins, otherwise **Balanced**. Consistency isn't a style but
  a trait: *steady* (75th percentile or above) or *streaky* (25th or below). A runner-up style is shown as "also ...",
  and a `?` means fewer than 3 games stand behind it. It is a rough label, not a Riot stat, and the rules are in
  `player_profile.py` (`STYLES`).
* **Compare (9):** you against the selected player. Each radar axis is shown as two bars (yours, theirs) ranked in the
  same lobby, with the gap; below that the raw rates (ACS, ADR, K/D, HS %, KAST %, first-blood %, casts per round)
  with green where you are ahead and red where you are behind. Selecting yourself says so; a player without
  performance counts is explained rather than shown empty.
* **Scatter (8):** one point per player, your team cyan, the enemy red, the selected player yellow, with dashed
  lobby-average lines. `s` (or the button) cycles the pairing: ADR vs first-blood rate, KAST vs ADR, HS vs ADR,
  ACS vs K/D, casts vs KAST. It needs `textual-plotext` (`requirements-tui-charts.txt`); without it the same pairing
  is listed as numbers. All of it comes
from match details already fetched (`match_stats.py`, `player_profile.py`); there are no extra requests. Summaries
cached before this existed show "fills in on the next refresh".

**Saved lobbies.** Each agent-select and in-game lobby is saved automatically (once its ranks and history have loaded,
and again when it ends or you quit), so you can look at it after the game. Press **`h`** for the list, newest first
(when, result, map, mode, your agent and both teams' average rank), **Enter** to open one, **`l`** to go back to the
live lobby (`r` also goes back). A saved lobby opens in the same list, cards and graphs, with a coloured banner while
you're looking at it; the live lobby keeps loading behind it.

* The **result** (`W 13-10 +21`) isn't known during the game. It is filled in from *your own* match history the next
  time that history loads (the next lobby you open), so it costs no extra requests and can be a game behind.
  Unverified: it assumes the lobby's match id is the one your history lists.
* A saved lobby is exactly what was on screen, so streamer mode's hidden names stay hidden. The files are local
  (`cache/lobbies/`, git-ignored), contain other players' names and match data, and are never uploaded; delete the
  folder to clear them. The newest 200 are kept. `--demo` saves to `cache/lobbies-demo/` instead.
* **Sort and show (`o`, `f`):** `o` cycles how the players table is ordered (default, rank, ACS, ADR, K/D, KAST, first
  bloods; best first, players without data last) and `f` cycles Everyone / Your team / Enemies. Percentiles, leaders and
  team averages are still worked out over the whole lobby. In the saved-lobbies list `f` cycles Played games (the
  default) / Everything / Wins / Losses / Imported / Agent select only.
* **Dodges:** a lobby is saved only once the game has started. Agent select on its own may be a dodge, so it isn't saved.
  Premade counts are only meaningful for your own side live (the client doesn't reveal the enemy's groups); the enemy line
  and imported lobbies say `premades n/a` rather than `0`.
* **Import past games (`i`):** rebuilds a saved lobby for each game you played without the TUI that is still in the
  match cache (`cache/matches/`), newest first, up to 40 per press. No network. Each lobby has the ten players, agents,
  teams, the ranks they held in that game and the result; a player's history is built from the other cached matches
  from before that game, so players we never fetched show no history. Season stats, peak rank, RR and premade groups
  can't be recovered. Games already saved are left alone, and they are listed as `Imported`.
* Menus (party) screens aren't saved, and a lobby you weren't running the TUI for can't be recovered afterwards.

Use a **separate venv**: Textual needs `rich>=14.2` and `Pygments>=2.19.2`, while `requirements.txt` pins older ones.

```
py -3.12 -m venv venv-tui
venv-tui\Scripts\python.exe -m pip install -r requirements.txt
venv-tui\Scripts\python.exe -m pip install -r requirements-tui-charts.txt   (or requirements-tui.txt, no charts)
venv-tui\Scripts\python.exe tui.py --demo     a fake lobby, no VALORANT needed
venv-tui\Scripts\python.exe tui.py            the live lobby (VALORANT must be running); START-TUI.bat does the same
```

* **Not run against a live client yet.** The demo and the test suite (headless Textual plus a fake client) pass, but
  `lobby_live.py`, which mirrors `main.py`'s INGAME / PREGAME / MENUS logic and its streamer-mode rules for names and
  levels, still needs a real lobby.
* It polls the client's presence every 2 seconds for the game state, and leaves out the skin column, Discord status
  and the mobile web server. Rank, HS, WR, level, ΔRR, party squares and the history data come from the same code as
  the console table. The lobby history settings above (`lobby_history`, `map_history`) apply here too.
* **Saved lobbies:** see below.
* Not built yet: sorting and filtering.

## What about that Tweet?

The [Tweet](https://twitter.com/PlayVALORANT/status/1539728676815642624), which details Riot's API policies, outlines how
applications are not allowed to expose data hidden by the game client. As of Version 1.262, vRY respects streamer mode.

## Contributing

Any contributions you make are **greatly appreciated**.

## Contact

Join the community discord:

[![Discord Banner 2][discord-banner]][discord-url]

## Acknowledgements

- [Valorant-API.com](https://valorant-api.com/)
- [Hamper](https://hamper.dev/)
- [D3CRYPT](https://d3crypt360.pages.dev/)

## Disclaimer

THIS PROJECT IS NOT ASSOCIATED OR ENDORSED BY RIOT GAMES. Riot Games, and all associated properties are trademarks or registered trademarks of Riot Games, Inc.

Whilst effort has been made to abide by Riot's API rules; you acknowledge that use of this software is done so at your own risk.


[discord-shield]: https://img.shields.io/discord/872101595037446144?color=7289da&label=Support&logo=discord&logoColor=7289da&style=for-the-badge
[discord-url]: https://discord.gg/HeTKed64Ka
[discord-banner]: https://discordapp.com/api/guilds/872101595037446144/widget.png?style=banner2

[downloads-shield]: https://img.shields.io/github/downloads/zayKenyon/VALORANT-rank-yoinker/total?style=for-the-badge&logo=github
[downloads-url]: https://github.com/zayKenyon/VALORANT-rank-yoinker/releases/latest
