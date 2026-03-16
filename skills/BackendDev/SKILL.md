## Backend Implementation Rules

- All I/O-bound operations use `async/await`. No blocking calls on the event loop.
- Pydantic v2: use `model_validator` over `__init__` overrides. Use `model_dump(mode="json")` for serialization.
- Sanitize every file path: `os.path.realpath()` + assert path starts with allowed prefix. No exceptions.
- Integration tests hit real dependencies (real DB, real Redis). Mock only external third-party APIs.
- `Decimal` for money. `datetime` with explicit `tzinfo`. No naive datetimes in storage or APIs.
- Log at boundaries: request in, response out, error with traceback. Use structured JSON logs.