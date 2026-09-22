---
name: python-best-practices
description: "This skill should be used when writing, reviewing, or discussing Python code — PEP 8, type hints, testing, error handling, and code quality tooling."
allowed-tools: Read
---

# Python Best Practices

## Standards
- Python 3.9+; PEP 8 via ruff/black; type hints on all public APIs (mypy/pyright); pytest with coverage.py, minimum 80%; bandit for security
- One-line docstring per public function/class, expanded only when non-obvious (Google/NumPy/Sphinx style)
- Specific exception types with proper messages; no bare `except`
- Dependencies via uv or poetry, always in a virtual environment (uv creates one)

## Practices
- Context managers for resources; composition over inheritance; dataclasses or Pydantic for data structures; generators for large datasets; `logging`, not `print`; async/await for I/O-bound work when beneficial; no mutable default arguments

## Code Review Checklist
- PEP 8 compliance and consistent style
- Type hint coverage on public APIs
- Docstring presence and accuracy
- DRY compliance: duplicated logic, copy-paste patterns
- Naming clarity: variables, functions, classes, modules
- Context managers for resource management
- Exception types are specific, not bare except
- Test quality: meaningful assertions, edge cases, error paths, proper mocking
- Code brevity: flag code that can be expressed in fewer lines without losing clarity

Use `PY-NNN` prefix for all findings.
