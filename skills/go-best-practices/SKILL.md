---
name: go-best-practices
description: "This skill should be used when writing, reviewing, or discussing Go code — idioms, error handling, concurrency, and testing patterns."
allowed-tools: Read
---

# Go Best Practices

## Standards
- Go 1.21+; gofmt/goimports; golangci-lint (staticcheck, errcheck, govet, …); gosec; `go mod tidy`/`go mod verify`
- `go test -race -cover ./...` with table-driven tests; `go test -bench=. -benchmem` for benchmarks
- One-line Godoc per exported identifier, expanded only when non-obvious

## Practices
- Accept interfaces, return structs; keep interfaces small; don't over-use them early; composition over embedding; `internal/` for private code; standard library first
- Errors: always checked (never `_`); wrapped with `fmt.Errorf("context: %w", err)`; custom types for sentinels, checked with `errors.Is`/`errors.As`; last return value; no panics in library code
- `context.Context` as first parameter for cancellation/timeouts; `defer` for cleanup; every goroutine has a known exit; `sync.WaitGroup` to wait; channels for communication, mutexes for state; `select` for multiplexing; understand buffered-channel blocking
- Patterns: functional options for constructors; `io.Reader`/`Writer`/`Closer`; middleware as handler wrapping; channel-based worker pools; graceful shutdown via signal + context cancellation
- Avoid excessive globals and `init()`

## Code Review Checklist
- Idiomatic Go style (Effective Go compliance)
- Error handling: explicit checks, no ignored errors, proper wrapping with %w
- Goroutine lifecycle: clear start/stop, no leaks
- Interface design: small, focused, used appropriately
- Context propagation for cancellation
- Defer usage for cleanup
- DRY compliance: duplicated logic, copy-paste patterns
- Naming clarity: exported vs unexported, package naming
- Test quality: table-driven tests, meaningful assertions, race condition coverage
- Code brevity: flag code that can be expressed in fewer lines without losing clarity

Use `GO-NNN` prefix for all findings.
