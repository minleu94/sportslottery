# Parlay search coverage

`ParlayEngine.search_parlays` keeps its three result buckets and its ranking
limits (up to 12 results per bucket) for compatibility with existing callers.
The search now considers all ready options from all eligible events after the
selected quality filter. It no longer reduces each event to two options or
truncates the event set at `max_matches_pool`; that argument remains accepted
but is ignored for compatibility.

The search uses an odds interval bound. For any partial selection, the
smallest and largest possible products from the remaining distinct events are
computed. If that interval cannot intersect the requested odds band, the whole
branch is safely skipped. Only one selection can be chosen per event, so
Taiwan Sports Lottery mutual exclusion is preserved.

The default budget is 250,000 visited search nodes. Callers may set
`search_budget` explicitly. With diagnostics enabled, `search_complete` and
`search_status` distinguish a complete search from a budget-limited result;
`visited_nodes`, `odds_pruned_nodes`, `checked_combinations`, and
`odds_matching_combinations` describe the examined scope. If
`search_status == "BUDGET_EXHAUSTED"`, empty result buckets mean no qualifying
combination was found within the examined portion, not that no combination
exists. A complete search with empty buckets means all eligible options were
searched and the odds interval contained no valid combination.

The returned three buckets are ranked display sets, not exhaustive lists.
They may contain the same combination across buckets, and each bucket retains
at most its top 12 results.
