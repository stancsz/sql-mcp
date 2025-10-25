# Task: Harden read-only SQL validation and add comprehensive unit tests

Summary
- Make `_is_read_only_sql` robust against evasion and multi-statement injections.
- Add comprehensive unit tests covering adversarial and edge-case inputs (>= 20 cases).
- Ensure `SQLMCPTools.execute_read_only_sql` only permits safe read-only queries and returns clear errors for rejected input.

Files to modify
- sql_mcp_server/tools.py
- tests/test_tools.py
- tests/test_tools_extra.py

Goal / Acceptance criteria
1. New unit tests include at least 20 adversarial / edge cases and pass.
2. Implementation rejects inputs that contain:
   - Multiple statements (semicolon-separated more than one logical statement).
   - Any statement type other than allowed read-only statements (allow at minimum: SELECT, WITH, EXPLAIN, VALUES).
   - Forbidden keywords anywhere outside safe contexts, including: INSERT, UPDATE, DELETE, CREATE, DROP, ALTER, TRUNCATE, GRANT, REVOKE, MERGE, COPY, BEGIN, COMMIT, ROLLBACK, SET, ATTACH, VACUUM.
3. Legitimate complex read-only queries (CTEs, nested selects, parentheses, EXPLAIN) are accepted.
4. Unit tests added to the repository and run via `pytest` succeed.
5. A brief docstring in `tools.py` describes allowed statements and the validation strategy.

Suggested implementation approach
- Prefer tokenization with `sqlparse` if available:
  - Use `sqlparse.split()` to ensure a single statement.
  - Parse and ensure the first meaningful token is in the allowed set.
  - Walk flattened tokens, skipping comments and string literals, and reject Keyword tokens matching forbidden list.
- Fallback to conservative regex-based checks:
  - Strip comments, remove outer parentheses, ensure exactly one statement, ensure first token is allowed, and reject if forbidden keywords appear.
- Err on the side of safety: when in doubt, reject and return a clear ValueError message.

Example commands (developer)
```bash
# install constraints
python -m pip install -r requirements-constraints.txt

# run full test suite
pytest -q

# run tools tests only
pytest -q tests/test_tools.py tests/test_tools_extra.py
```

Testing guidance / sample test cases to include
- Accept:
  - Complex SELECT with CTEs
  - Nested parentheses around a SELECT
  - EXPLAIN SELECT ...
  - VALUES (1),(2)
  - SELECT with semicolon only at the very end (single-statement)
- Reject:
  - "SELECT 1; DROP TABLE users;"
  - Multi-statement with BEGIN/COMMIT
  - Statements containing forbidden keywords as top-level keywords
  - COPY, SET, VACUUM, ATTACH, or other non-read-only commands
  - Inputs with forbidden keywords outside quoted literals (verify sqlparse handles string literals)

Developer notes
- Keep behavior deterministic and documented.
- If using sqlparse, add tests that cover both code paths (sqlparse available / not available) if feasible.
- Return a ValueError with a clear message when rejecting queries so the HTTP layer can return a 400.

Deliverables
- Modified `sql_mcp_server/tools.py` with improved validation and docstring.
- New/updated tests in `tests/test_tools.py` and/or `tests/test_tools_extra.py`.
- Test output (pytest run) showing green tests.
- Short PR description summarizing changes and trade-offs.

Priority & estimate
- Priority: High (security-critical)
- Estimated effort: 3–6 hours
