---
name: go-best-practices
description: "Go best practices — idioms, error handling, concurrency, testing patterns. Use when writing, reviewing, or discussing Go code."
allowed-tools: Read
---

# Go Best Practices

## Technical Standards
- **Go Version**: 1.21+ (or latest stable)
- **Code Style**: gofmt/goimports enforced
- **Linting**: golangci-lint with comprehensive checks
- **Testing**: go test with table-driven tests
- **Documentation**: One-line Godoc comment for every exported identifier; expand only when non-obvious
- **Error Handling**: Explicit with error wrapping (fmt.Errorf with %w)
- **Modules**: Go modules for dependency management
- **Context**: context.Context for cancellation and timeouts

## Best Practices
- Accept interfaces, return structs
- Keep interfaces small (single-method often best)
- Use context.Context for cancellation propagation
- Always check errors — don't ignore with `_`
- Use defer for cleanup (close files, unlock mutexes)
- Goroutines: always know when they exit
- Channels for communication, mutexes for state
- Prefer composition over embedding
- Use `internal/` package for private code
- Prefer standard library first

## Common Patterns
- **Error Wrapping**: `fmt.Errorf("context: %w", err)`
- **Options Pattern**: Functional options for constructors
- **Context**: Pass as first parameter
- **Interfaces**: io.Reader, io.Writer, io.Closer patterns
- **Middleware**: Handler wrapping for HTTP servers
- **Worker Pools**: Channel-based task distribution
- **Graceful Shutdown**: Signal handling with context cancellation

## Concurrency
- Always handle goroutine lifecycle — know when they exit
- Use context for cancellation propagation
- Protect shared state with mutexes or channels
- Use sync.WaitGroup to wait for goroutines
- Use buffered channels carefully — understand blocking
- Use select for channel multiplexing
- Implement worker pools for bounded concurrency

## Error Handling
- Wrap errors with context: `fmt.Errorf("failed to read: %w", err)`
- Define custom error types for sentinel errors
- Use errors.Is() and errors.As() for checking
- Return errors as last return value
- Don't panic in library code — return errors
- Log errors at the right level in the call stack

## Code Quality Tools
- **Formatting**: gofmt, goimports
- **Linting**: golangci-lint (staticcheck, errcheck, govet, etc.)
- **Testing**: `go test -race -cover ./...`
- **Security**: gosec
- **Dependencies**: `go mod tidy`, `go mod verify`
- **Benchmarks**: `go test -bench=. -benchmem`

## Common Pitfalls
- Don't ignore errors
- Don't use goroutines without understanding their lifecycle
- Don't use global variables excessively
- Don't use init() unless absolutely necessary
- Don't over-use interfaces early — add when needed
- Don't forget to close resources (files, connections)
- Don't use panic/recover for normal error handling

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
