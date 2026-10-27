# main.py code notes

Written while preparing the `feature/lobby-history` branch. These are reading
notes only: nothing here was run against a live client, and none of the bugs
listed below are fixed on this branch.

## Structure

`main.py` is a single top-level script. All functions are defined inside one
big `try:` block, and the whole program ends in a bare `except:`. As a result
`main.py` cannot be imported (for tests or otherwise), which is why the history
feature lives in its own module, `history.py`.

## Authentication

1. `get_lockfile()` reads
   `%LOCALAPPDATA%\Riot Games\Riot Client\Config\lockfile`. The file holds
   `name:PID:port:password:protocol`, which is split on `:` into a dict.
2. `get_headers()` calls the local Riot Client at
   `https://127.0.0.1:<port>/entitlements/v1/token` with HTTP basic auth
   `riot:<lockfile password>`. The response gives the player's `subject`
   (PUUID), `accessToken` and `token` (the entitlements JWT).
3. Those become the headers used for the remote `pd` and `glz` hosts:
   `Authorization: Bearer <accessToken>`, `X-Riot-Entitlements-JWT: <token>`,
   a fixed base64 `X-Riot-ClientPlatform` blob, and `X-Riot-ClientVersion`.
4. Headers are cached in the global `headers`. Any non-OK response resets the
   cache to `{}`, forcing a fresh token fetch on the next call.

Everything uses `verify=False`: needed for the local client's self-signed
certificate, but it is also applied to the real Riot hosts.

## Region and game version (ShooterGame.log)

Both read `%LOCALAPPDATA%\VALORANT\Saved\Logs\ShooterGame.log`:

- `get_region()` scans line by line. A line containing
  `.a.pvp.net/account-xp/v1/` gives the shard for the `pd` host (the token
  before `.a.pvp.net`). A line containing `https://glz` gives the `glz` region
  and shard (`glz-<region>.<shard>.a.pvp.net`). It returns once both are seen.
  The result builds `pd_url = https://pd.<shard>.a.pvp.net` and
  `glz_url = https://glz-<region>.<shard>.a.pvp.net`.
- `get_current_version()` finds `CI server version: <v>`, splits on `-`,
  inserts `shipping` at index 2 and rejoins. The result is sent as
  `X-Riot-ClientVersion`.

## Per-player rank

`getRank(puuid, seasonID)` does `GET {pd_url}/mmr/v1/players/{puuid}` via
`fetch("pd", ...)` and reads
`QueueSkills.competitive.SeasonalInfoBySeasonID[seasonID]`:

- `CompetitiveTier` is the rank index into `number_to_ranks`.
- `RankedRating` is RR.
- `LeaderboardRank` is only read for tier >= 21 (Immortal and up).
- Peak rank is the highest key seen in any season's `WinsByTier`.

`seasonID` comes from the content service (`get_content()` then
`get_latest_season_id()`, the season with `IsActive`).

The main loop polls local presence for the game state (`INGAME`, `PREGAME`,
`MENUS`). When it changes it fetches the roster from `glz` (`core-game` or
`pregame`), resolves names via `name-service/v2/players`, then calls `getRank`
once per player and adds a row to a PrettyTable.

## Existing bugs noticed (not fixed here)

1. `getRank`: when the response is not OK, `r` is never assigned, but the code
   below the `try` still does `r["QueueSkills"]...`. That raises
   `UnboundLocalError` and falls into the bare `except`, so the
   "rate limited, waiting 10 seconds" retry loop is unreachable for that case.
2. `fetch()`: on any non-OK response it clears `headers` and recurses with no
   retry limit or backoff. A persistent 4xx recurses until `RecursionError`.
   After the recursion unwinds, the outer call still returns data from the
   shared global `response`.
3. `fetch()` also returns `None` (implicitly) after a JSON decode error, and
   several callers index into the result without checking.
4. `get_region()` and `get_current_version()` loop on `readline()` with no EOF
   check. If the log never contains the expected line, `readline()` returns
   `''` forever and the program spins at 100% CPU. `get_region` also detects
   "found" via `locals().keys()`.
5. `log()` builds the path with `os.getcwd() + "\logs"`, an invalid escape
   sequence (`\l`) and Windows-only. The log-number parsing uses fixed slice
   offsets (`filename[9:-4]`), which break if the filename format changes.
6. `exit()` shadows the builtin, and its log message has a stray `v`
   (`error code v{status}`).
7. PREGAME party icons: `partyCount += 1` sits outside the
   `if party not in partyIcons` block, so it increments for every party member
   instead of once per party. INGAME has it inside the block. Icons can skip
   colors or run past the 8-entry list.
8. `get_matchLoadouts` assumes `Loadouts[i]` lines up with `Players[i]` by
   position.
9. `get_party_members` uses `party_id` before assignment if the user's own
   presence is not valid.
10. `configDialog` writes to a file handle that was opened read-only when
    `cooldown` is missing from an existing `config.json`
    (`io.UnsupportedOperation`).
11. The bare `except:` around the whole program also swallows
    `KeyboardInterrupt` and `SystemExit`, and `os._exit(1)` skips cleanup.
12. No `requests` call has a timeout, so a stalled connection hangs the loop.
13. `verify=False` is applied to the remote Riot hosts, not just the local
    client's self-signed cert.
14. The rate-limit retry loops (`while not rankStatus`) have no cap.
15. PREGAME shows the literal text `None` for a player whose `CharacterID` is
    not in `agent_dict` (`str(agent_dict.get(...))`).
16. Windows-only calls (`os.system('cls')`, `title`, `LOCALAPPDATA`) run at
    import time.
