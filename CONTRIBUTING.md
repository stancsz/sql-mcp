Contributing Guidelines

Thank you for considering contributing to this project.

- Fork the repository
- Create a feature branch: git checkout -b feature/your-feature
- Write tests and ensure they pass: pytest -q
- Follow code style and add docstrings
- Run linters and formatters before opening a PR
- Open a PR describing your changes and link relevant issues

Developer notes:
- Tests use an in-memory SQLite engine; do not mock or monkeypatch DB behavior in core integration tests.
- The project prefers real integrations for DB drivers; use optional extras in pyproject.toml when required.
