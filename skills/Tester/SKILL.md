## Testing Constraints

- Every test function must have a single, named assertion. No multi-assert blobs.
- Prefer real dependencies over mocks. Only mock at system boundaries (network, filesystem, clock).
- Label each test: `# FAST (<1s)` or `# SLOW (>5s)` — slow tests must be opt-in via a marker.
- Edge cases to always consider: empty input, max boundary, concurrent access, network timeout, partial failure.
- Untestable design is a design flaw. Name the refactor, don't work around it.