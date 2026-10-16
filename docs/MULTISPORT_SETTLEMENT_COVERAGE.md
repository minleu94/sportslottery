# Result coverage for newly observed soccer competitions

## Why these leagues were selected

The latest isolated Playsport scale snapshot available during this change was
`data/research_pipeline/snapshots/20261014_013518_scale_4.json`. It contained
58 soccer events and 290 betting options. Colombia Primera A and Costa Rica
Primera each contributed two events and ten options. The isolated prediction
ledger had 15 snapshots for each league. They tied for the largest currently
uncovered production scope, so both were added together.

The source labels are exact Playsport competition names:

- `哥倫比亞甲級聯賽` maps to `COLOMBIA_PRIMERA_A` / ESPN `soccer/col.1`.
- `哥斯大黎加甲級聯賽` maps to `COSTA_RICA_PRIMERA` / ESPN `soccer/crc.1`.

Other Colombian or Costa Rican competitions remain unknown unless their exact
competition label is added explicitly.

## Source evidence and checks

ESPN public scoreboard feeds are third-party result sources, not official
league feeds. Raw responses and a URL/status/time/hash manifest are preserved
in `artifacts/improvements_20261014/football_sources/`.

For `dates=20261013`, the captured response SHA-256 values are:

- Colombia `col.1_scoreboard_20261013.json`: `066816a1eee24ac8751dc09a79410c346b4dc1c49462444e883dc0970c6c6e4b`.
- Costa Rica `crc.1_scoreboard_20261013.json`: `f7cdadc83350432a75ca87a1eda3be19e8bf1a83faa84a316af72455de5deddc`.

The matching ESPN team-list responses captured on `20261014` are also kept in
the same directory: `col.1_teams.json` (`2ca9a7f2cff9f1ce2739dc675e20bdd073f0a302f41d57f3e146bb4ca4e72c3a`)
and `crc.1_teams.json` (`6f6718feafbaf14074dccc9b13be2aa317ba8b534caec0a91e28920b0168b741`).
They supply provider team names/IDs; exact traditional Chinese aliases are
the names observed in the Playsport cache.

The fixtures include three final games and one postponed game matching the
current isolated ledger by exact canonical teams and aware UTC start time, with
no provider event ID on the prediction snapshot. Regression coverage confirms
90-minute soccer settlement for a draw, two winning sides, and a postponed
event remaining pending.

The original isolated ledger contained four pairs per league. The verified
Oct. 14 events added two exact Colombia teams and four exact Costa Rica teams,
each with source names and ESPN IDs. ESPN teams outside those observed sets
remain unresolved until their exact Playsport aliases are verified and added.
That is intentional: league feed availability alone does not establish team
identity coverage.

## Additional ready-slate coverage captured on Oct. 15, 2026

Counts below come from `data/research_pipeline/runs/20261015T0015Z/data/source_legs.json`.
“Ready at observation” means `assess_leg` evaluated each row at its own saved
`odds_scraped_at`; it does not mean the quote is still fresh now. Event matching
requires the exact registered away/home identities and UTC start time. ESPN is
a third-party public feed, not an official league result source.

| Playsport competition | Options / events | Ready options / events at observation | ESPN source and same-date identity evidence | Registered team scope | Remaining limitation |
| --- | ---: | ---: | --- | ---: | --- |
| AFC Champions League Two | 55 / 11 | 30 / 6 | `soccer/afc.cup`; same-date scoreboard includes 11 exact time/team pairs | 22 teams | 10 events agree on away/home sides. Shanghai Shenhua–Preah Khan Reach Svay Rieng has the exact UTC time and team pair but ESPN's home/away order is reversed; strict matcher leaves it unmatched. This is observed-slate coverage, not a full-roster guarantee. |
| Saudi Pro League | 15 / 3 | 15 / 3 | `soccer/ksa.1`; ESPN metadata identifies “Saudi Pro League”; all 3 Oct. 15 events match exact UTC time and away/home teams | 6 teams | All three were scheduled/upcoming when captured; no final scores were present yet. The feed and identities are verified, but settlement awaits final status. |
| CONMEBOL Libertadores | 5 / 1 | 5 / 1 | `soccer/conmebol.libertadores`; ESPN metadata identifies “CONMEBOL Libertadores”; Oct. 14 feed contains event `401912522`, Palmeiras at Fluminense at `2026-10-15T00:30Z` | 2 teams | Match was in progress at capture, so no settlement was recorded. ESPN `dates=20261015` returned a different Oct. 16 UTC event; the adjacent Oct. 14 feed is the exact-date match. This is one observed pair, not full-roster coverage. |

The raw Oct. 15 scoreboard and teams responses, including request URL, UTC
observation time, HTTP status, byte count, and SHA-256, are in
`artifacts/program_review_20261014/source_comparison_20261015/saudi_libertadores/manifest.json`.
The AFC and NBA comparison captures from the preceding batch are in the sibling
`afc_cup/` directory and the parent manifest.

The same snapshot contained these other unrecognized competition counts:

| Unrecognized Playsport label | Options / events | Ready options / events at observation | Status |
| --- | ---: | ---: | --- |
| German 3. Liga | 25 / 5 | 0 / 0 | Uncovered; no team/result mapping was added. |
| English Championship | 20 / 4 | 0 / 0 | Uncovered; no team/result mapping was added. |
| Turkish First League | 15 / 3 | 5 / 1 | Uncovered and still has a ready event. ESPN's `tur.1` reference is explicitly Turkish Super Lig, which is a different competition; no distinct First League result route and exact team scope were verified. |
| Belarusian Premier League | 10 / 2 | 5 / 1 | Uncovered and still has a ready event. The ESPN Belarus result located in this pass was a national-team fixture; no domestic league scoreboard/team route and exact club scope were verified. |
| Czech First League; Estonian Premier League; Argentine Primera División; Copa Sudamericana | 5 / 1 each | 0 / 0 each | Uncovered; retain explicit unsupported status until a ready slate and exact source evidence justify work. |

No market was added solely because a provider endpoint returned a league
metadata name. Saudi and Libertadores identity coverage is limited to the
captured teams above; other clubs, competitions and unknown labels remain
unresolved until their own exact mappings and match evidence are available.
The unverified-source reasons for Turkey and Belarus are recorded in
`config/result_coverage_evidence.yaml` for the research health panel. This means
the leagues remain unresolved; it does not assert that results or providers do
not exist. Deployment and account recovery instructions are in
`docs/DEPLOYMENT_AND_RECOVERY.md`.
