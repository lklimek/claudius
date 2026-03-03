---
name: python-best-practices
description: "Python best practices — PEP 8, type hints, testing, error handling, code quality tools. Use when writing, reviewing, or discussing Python code."
allowed-tools: Read
---

# Python Best Practices

## Technical Standards
- **Python Version**: 3.9+ features
- **Code Style**: PEP 8, use black/ruff for formatting
- **Type Hints**: typing module for all public APIs
- **Testing**: pytest with minimum 80% coverage
- **Documentation**: One-line docstring for every public function/class; expand only when non-obvious (Google/NumPy/Sphinx style)
- **Error Handling**: Specific exception types, proper error messages
- **Dependencies**: poetry or pip-tools
- **Virtual Environments**: Always use virtual environments

## Best Practices
- Context managers (with statements) for resource management
- Prefer composition over inheritance
- Use dataclasses or Pydantic for data structures
- Generators for memory efficiency with large datasets
- Proper logging (logging module, not print)
- async/await for I/O-bound operations when beneficial
- No mutable default arguments

## Code Quality Tools
- **Linting**: pylint, flake8, or ruff
- **Formatting**: black or ruff
- **Type Checking**: mypy or pyright
- **Testing**: pytest with coverage.py
- **Security**: bandit for security checks

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
