# Playsport source identity diagnostics

The Playsport scale scraper reports `identity_total_count`, `identity_complete_count`,
`identity_incomplete_count`, `identity_completeness_rate`, and grouped extraction
diagnostics in `get_scale_source_status()`. When using the default production
scraper, it also appends one JSONL observation to `data/source_health/playsport.jsonl`
per scale fetch. The history stores source timestamps, status, counts, and reason
counts; it deliberately omits team names, picks, odds, and other row-level content.
Pass `source_health_history_path` to direct observations elsewhere. Isolated
scrapers created with `cache_dir` do not write production history by default.

For football, Playsport groups three outer `game-set` rows by identical `gameid`.
The nested `td-teaminfo` scoreboard contains the two participants in DOM order;
the first participant maps to the adjacent `客` outcome row and the second to
`主`. The classes `winnerteam` and `secondteam` describe score-result styling,
so they do not determine event side. The third row supplies `和` draw odds.
Nested scoreboard rows are excluded from outer event iteration.

An unresolved or placeholder team pair is marked incomplete and does not enter
the canonical event/team registries. `assess_leg()` independently rejects blank,
placeholder, or identical team fields, even when an upstream identity flag is
missing. A name absent from the canonical registry is distinct from incomplete
source identity: valid raw team names can remain identifiable without asserting
successful canonical normalization.

The reduced live DOM excerpt and its SHA-256 are recorded under
`artifacts/source_integrity_review_20261013/`. Its three events are parser
regression evidence only and are not model-performance evidence.
