# React 與 API response contracts

## FastAPI response schemas

下列 React 主要頁面入口以 Pydantic response model 將穩定欄位寫入 OpenAPI：

| Endpoint | Response schema | Frontend consumer |
| --- | --- | --- |
| `GET /api/radar` | `RadarResponse` | Radar view / main page |
| `GET /api/legs` | `LegsResponse` | Radar view / main page |
| `GET /api/market/research-summary` | `MarketResearchSummaryResponse` | Research view |
| `GET /api/market/evaluation` | `ForwardEvaluationResponse` | Research view |
| `GET /api/research/analytics` | `ResearchAnalyticsResponse` | Research view |
| `POST /api/parlays/search` | `ParlaySearchResponse` | Parlay view / evidence sheet |

Nested row models preserve additive fields so older UI extensions and diagnostics can continue to evolve without silently dropping response data. Required identity and display fields remain typed in OpenAPI. Parlay responses include the bucket `tier` and omit the engine's internal `raw_legs` objects; the normalized `legs` field is the UI contract.

The analytics payloads are typed at the TypeScript service boundary from the current Python response definitions. Their flexible metric buckets remain records because their labels are data-driven; stable summary fields for data quality, sample qualification, market alignment, and scheduler state are explicit.

## Regression evidence

- `tests/test_api_contract.py` checks the OpenAPI response-model references and stable nested fields in addition to the pre-refactor route/request contract.
- `tests/test_frontend_api_contracts.py` uses offline fixtures to verify Radar, Legs, Research, and Parlay JSON envelopes, representative nested rows, additive compatibility fields, explicit tier labels, and removal of internal raw leg objects.
- `npm run build` runs `tsc -b` and Vite. This checks the `Sheet`, Radar, Parlay, Research, and main app consumers against shared response types.
- `ResearchView` labels offline CI evidence separately from live quote availability and successful Taiwan-to-international event alignment.

No provider query, real Odds API credit, production snapshot, or formal wallet data is used by these contract checks.
