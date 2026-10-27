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

One extra **Recent** column for each player in the lobby (INGAME and PREGAME), three lines per player:

```
60% 3/5                      win rate and sample size (colored like the WR column)
Sova · Skye · Viper          top 3 agents in recent competitive matches (×N when played more than once)
Init2 Ctrl1 Duel1 Sent1      matches per role
```

Players whose history is private or unavailable show `history unavailable`; players with no recent competitive games
show `no recent comp games`.

* Windows-only, and **unverified against the live API**: every unchecked endpoint/field is marked `# TODO(verify)` in
  `history.py`.
* Uses the local client's tokens, like the rest of vRY. A 401, 403 or 404 means "unavailable" and is not worked around.
* At most 5 matches per player. Finished matches and per-player results are cached in `cache/` (git-ignored; it holds
  other players' IDs from match data). Agent roles come from a table in `history.py`; a new agent shows as `Unknown`
  until it is added.
* Turn it off with `"lobby_history": false` in the `table` section of `config.json`.
* Riot's API policy (see below) applies here too. Whether other players' match history counts as data the client hides
  is not verified.
* The **Party** column (same-colored squares mark players queued together) is switched on in this fork; set
  `"party": false` in the `table` section of `config.json` to hide it again. Not verified live yet.
* Tests: `pip install -r requirements-dev.txt`, then `pytest`.

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
