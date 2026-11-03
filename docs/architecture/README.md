# Architecture documentation index

This index defines the authority order for current implementation and engineering decisions.

## Current source of truth

1. [Final validation and known limits](08-final-validation.md) records the latest code-level architecture measurements and offline acceptance evidence.
2. [Target architecture](01-target-architecture.md) defines the modular-monolith boundaries and dependency direction.
3. [Boundary documents](#domain-and-platform-boundaries) and [ADRs](#architecture-decisions) describe the current implementation contracts and accepted trade-offs.
4. [Discovery baseline](00-discovery.md) is a historical comparison captured at `831e048aeda578c98c4ffaa44d805e9329d0b6ec`; its code references and module counts describe that baseline, not current `dev`.

When a dated audit, handoff manual, or local operations note conflicts with these documents and the code, use the current code and the documents above. Historical material remains in place for context and is not silently treated as current behavior.

## Domain and platform boundaries

- [API routers and service lifecycle](02-api-boundaries.md)
- [Market intelligence and offline replay](03-market-boundaries.md)
- [Shared contracts and import boundaries](04-shared-contracts.md)
- [Storage paths and test isolation](05-storage-boundaries.md)
- [React and API response contracts](06-ui-api-contracts.md)
- [Dependency, lock-file, and test-data governance](07-governance.md)

## Architecture decisions

- [ADR-0001: Modular monolith and incremental migration](adr/0001-modular-monolith.md)
- [ADR-0002: Data and compatibility boundaries](adr/0002-data-and-compatibility-boundaries.md)
- [ADR-0003: Market evidence and forward-evaluation cohorts](adr/0003-market-evidence-boundary.md)

## Related operational and historical references

- [README](../../README.md): user-facing feature and development entry point.
- [Historical product architecture](../../CURRENT_PRODUCT_ARCHITECTURE.md): retained for prior-version context.
- [LINE handoff and operations manual](../AGENT_HANDOFF_AND_LINE_BOT_MANUAL.md): retained as operational reference; confirm commands against current code before use.
- [Local storage deployment note](../STORAGE_AND_SSD_PROTECTION.md): specific Windows host history, not a portable storage contract.
- [Source capability matrix](../SOURCE_CAPABILITY_MATRIX.md): source-specific capability evidence; live availability still requires runtime checks.
