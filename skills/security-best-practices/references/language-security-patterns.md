# Language-Specific Security Patterns

Concrete attack patterns to hunt for during code review, organized by language.
These complement the OWASP checklists with language-level specifics.

## Python

- **Code Injection**: `eval()`, `exec()`, `compile()`, `pickle.loads()`, `yaml.load()` (use `safe_load`)
- **Path Traversal**: file operations with user input without `os.path.realpath()` validation
- **Template Injection**: unsanitized input in Jinja2/Mako templates
- **SQL Injection**: string formatting in queries instead of parameterized queries
- **Regex DoS**: complex/nested regex on user input without timeout
- **Timing Attacks**: non-constant-time comparison for secrets (use `hmac.compare_digest`)
- **Weak Randomness**: `random` module for security-sensitive values (use `secrets`)

## Rust

- **Unsafe Code**: review every `unsafe` block for soundness — memory safety, aliasing, uninitialized data
- **Integer Overflow**: arithmetic overflow wraps silently in release mode (use `checked_*` or `saturating_*`)
- **Panic Safety**: ensure no data corruption on panic (drop handlers, mutex poisoning)
- **Memory Safety**: verify lifetimes and borrowing correctness in `unsafe` code
- **Deserialization**: validate untrusted input schema before `serde` deserialization
- **FFI Boundaries**: audit all `extern "C"` interfaces for null pointers, buffer sizes, lifetime mismatches

## Go

- **Command Injection**: `os/exec` with unsanitized user input, shell interpolation via `sh -c`
- **Path Traversal**: `filepath.Join` doesn't prevent `../` escapes — validate after joining
- **SQL Injection**: string concatenation in `database/sql` queries instead of `?` placeholders
- **Goroutine Leaks**: goroutines blocked on channels or I/O without timeout/cancellation
- **Race Conditions**: shared state without synchronization (run tests with `-race` flag)
- **Unsafe Package**: any use of `unsafe.Pointer` for type punning or pointer arithmetic
- **Cryptography**: custom crypto instead of `crypto/*` standard library packages

## TypeScript / JavaScript

- **Prototype Pollution**: `Object.assign()`, spread operator, or deep merge with user-controlled keys
- **XSS**: direct DOM manipulation with `innerHTML`, `document.write()`, unescaped template literals
- **Dependency Risk**: unpinned deps without lockfile, `postinstall` scripts in dependencies
- **eval/Function**: `eval()`, `new Function()`, `setTimeout(string)` with dynamic input
- **Path Traversal**: `path.join()` with user input in Node.js file operations
- **ReDoS**: complex regex patterns on user input without input length limits

## Security Scanners by Language

| Language | SAST | Dependency Scan | Secret Scan |
|----------|------|-----------------|-------------|
| Python | bandit, semgrep | safety, pip-audit | gitleaks, truffleHog |
| Rust | clippy (security lints), semgrep | cargo audit | gitleaks, truffleHog |
| Go | gosec, staticcheck, semgrep | govulncheck, nancy | gitleaks, truffleHog |
| TypeScript/JS | eslint-plugin-security, semgrep | npm audit, snyk | gitleaks, truffleHog |
| Multi-language | semgrep, CodeQL | trivy, snyk, grype | detect-secrets, GitGuardian |
| Container | — | trivy, snyk, grype | — |
