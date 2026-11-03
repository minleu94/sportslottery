# Shared contracts and dependency boundaries

## Canonical ownership

Framework-free records shared by domain services and provider adapters are owned by `core/contracts/`:

- `common.py`: prediction signals, Taiwan legs, expert picks, and their stable serialization.
- `market.py`: odds/evidence records, market and selection identity, canonical event IDs, and shared market-line semantics.
- `probability.py`: the probability/edge evaluation result consumed by the edge policy and evidence builder.

`integrations/common/models.py` and `integrations/odds/market_models.py` remain import-compatible re-export modules. They expose the canonical class objects, so old and new import paths have identical class identity and retain the existing field names and `to_dict()` shapes.

Provider adapters may depend on these contracts. The contracts must not import providers, API frameworks, storage, or orchestration modules.

## Market selection identity

`MarketSelectionIdentity` centralizes comparison of market type, selection, and line:

- same-outcome comparison requires matching market and selection and equivalent optional lines;
- opposite spread selections require opposite signed lines (`home -1.5` pairs with `away +1.5`);
- opposite total selections require the same threshold (`over 220.5` pairs with `under 220.5`);
- two-way moneyline selections pair by home/away selection.

The contract is about quote identity. Event/team/time alignment and source/freshness eligibility remain responsibilities of existing policies and adapters.

## Dependency direction

`core` consumes contracts directly. Provider adapters implement and translate external data at the edge. Compatibility modules point inward to `core/contracts`; core no longer imports legacy integration modules for shared types.

Cross-cutting helper functions that do not require pipeline state live in `core/research_helpers.py`. Market scheduler status is supplied to `MarketForwardPipeline` through an optional provider hook. The probability result record lives outside `edge_engine`, so evidence assembly does not need to import the engine module.

The static boundary tests guard these rules and the removal of previously observed module cycles. They are structural checks, not proof of runtime behavior; existing market, research, and probability tests cover the affected call paths.

## Validation and data isolation

`tests/test_shared_contract_compatibility.py` checks class identity across legacy and canonical paths, representative serialization compatibility, and opposing line semantics. `tests/test_core_contract_boundaries.py` checks import direction and provider-free contract modules.

The autouse test fixture redirects wallet and shadow SQLite databases plus the default shadow snapshot path to pytest-owned temporary directories. No migration or copy of existing snapshots or database files is part of this boundary change.
