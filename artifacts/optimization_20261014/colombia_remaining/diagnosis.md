# Colombia unmatched event diagnostic

Captured: 2026-10-16T06:05Z (UTC)
Scope: read-only investigation of the 15 `NO_UNIQUE_RESULT_MATCH` snapshots in `data/research_pipeline/runs/20261016T0600Z/data/settlement_audit.json`. No code, cache, or settlement data was changed. Raw public responses and their hashes are in `manifest.json`.

## Target in the saved records

The 15 observations all refer to PlaySport source event ID `1150`, with no provider event ID. The saved odds ledger records event start `2026-10-14T01:30:00Z`, home `百萬富翁` (Millonarios), away `卡爾達斯` (Once Caldas), and observations at 00:57, 01:05, and 01:15 UTC. The settlement audit reports Colombia coverage `AVAILABLE`, two fetched ESPN games, 15 snapshots, zero matches, zero provider fetch errors, and 15 `NO_UNIQUE_RESULT_MATCH` observations.

## ESPN evidence

Public ESPN Colombia Primera A scoreboard responses for `dates=20261012` through `dates=20261016` all returned HTTP 200. On Oct 13 the feed contains only event 401877951 (Águilas Doradas–Atlético Bucaramanga, FT 1–1, 23:30Z). On Oct 14 it contains only event 401878008 (Deportivo Pereira–Atlético Junior, FT 1–1, 21:30Z). The Oct 12, 15, and 16 responses contain zero events. Neither target team appears in the Oct 13/14 scoreboard events.

The ESPN league team index identifies Millonarios as provider team ID `5484` and Once Caldas as `2919`. Their 2026 Clausura team schedules return HTTP 200 and contain 33 and 34 events. Neither schedule contains the target home/away fixture at Oct 14 01:30Z, nor any fixture dated Oct 11–16 pairing those two teams. Both schedules do contain event `401850828` on Mar 21 23:20Z, named “Millonarios at Once Caldas”; ESPN lists Once Caldas (ID 2919) at home and Millonarios (ID 5484) away. That is a different date and reversed home/away order, so it is not a valid match for the saved observation.

## Conclusion and limits

The checked ESPN scoreboard and 2026 team schedules do not support the PlaySport event as a scheduled Oct 14 fixture, and they provide no rescheduled date or postponement status for it. This is evidence of a source/schedule discrepancy or an ESPN coverage omission; it does not establish which occurred. No exact identity-and-time result was found, and there is no evidence to settle these observations. Keep the 15 snapshots unresolved. Do not infer a postponement or reuse the March fixture.

ESPN is the only result/schedule provider checked here. The evidence is a point-in-time public API response captured Oct 16 UTC; it does not prove the league's official status or rule out incomplete ESPN coverage.

## Captured files

`manifest.json` contains request URLs, capture timestamps, response hashes, and event summaries. Raw responses are retained beside it:

- `col1_scoreboard_20261012.json` … `col1_scoreboard_20261016.json`
- `col1_teams.json`
- `millonarios_schedule_2026.json`
- `once_caldas_schedule_2026.json`
