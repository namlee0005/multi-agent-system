## Architectural Constraints

- Define explicit service boundaries before proposing any component. No boundary = no proposal.
- Use Pydantic v2 `BaseModel` for all inter-service data contracts. Never plain `dict`.
- All financial/monetary fields: `Decimal`, not `float`. Enforce via `condecimal()`.
- Flag every async I/O boundary explicitly — database, cache, external API. Sync calls in async context = blocker.
- Tradeoff format: state the option, the gain, the cost, and which context favors it.
- Single points of failure must be named and have a mitigation strategy before the design is complete.