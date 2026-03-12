# Go Security Patterns

Concrete attack patterns to hunt for during Go code review.
Complements the OWASP checklists with Go-specific concerns.

## Attack Patterns

### Injection & Input Handling

- **Command Injection**: `os/exec` with unsanitized user input, shell interpolation via `sh -c`
- **Path Traversal**: `filepath.Join` doesn't prevent `../` escapes — validate after joining
- **SQL Injection**: string concatenation in `database/sql` queries instead of `?` placeholders
- **SSTI (Template Injection)**: user input passed to `text/template` or `html/template` via `template.New().Parse()` at runtime — attacker can call exported methods on the template data struct, potentially achieving file read or RCE ([OnSecurity research](https://www.onsecurity.io/blog/go-ssti-method-research/))
- **CRLF / Header Injection**: user-controlled values in `http.NewRequest` URL or `Header.Set` without stripping `\r\n` — can inject HTTP headers or smuggle requests (CVE-2019-9741); also affects `mime/multipart.Writer` Content-Disposition fields
- **Log Injection**: unsanitized user input written to structured logs can forge log entries; strip newlines and control characters before logging

### Concurrency & Resource Safety

- **Goroutine Leaks**: goroutines blocked on channels or I/O without timeout/cancellation; missing `defer cancel()` after `context.WithCancel`/`WithTimeout`/`WithDeadline` leaks the child context and its goroutines
- **Race Conditions**: shared state without synchronization (run tests with `-race` flag); TOCTOU races exploitable for privilege escalation
- **Slowloris / Timeout DoS**: `http.ListenAndServe` or bare `http.Server{}` without `ReadTimeout`, `ReadHeaderTimeout`, `WriteTimeout`, `IdleTimeout` — allows connection exhaustion (gosec G112/G114)
- **Deadlock via Channel Misuse**: sending on unbuffered channel with no receiver, or `select` without `default`/timeout in hot paths

### Memory Safety & Type System Bypass

- **Unsafe Package**: any use of `unsafe.Pointer` for type punning or pointer arithmetic — can cause information leaks, memory corruption; `reflect.Value.Pointer()`/`UnsafeAddr()` results must be converted to `unsafe.Pointer` immediately in the same expression or GC may invalidate the address
- **Integer Overflow**: Go integers wrap silently in release builds; unchecked arithmetic on `int32`/`int64` can cause infinite loops or incorrect allocations (CVE-2023-24537, CVE-2022-23772)
- **Slice/Array Bounds via Unsafe**: manually creating slice headers with `unsafe` can set `Len` larger than the backing array — silent out-of-bounds reads with no compiler warning
- **CGo Boundary**: C memory not tracked by Go GC; use-after-free and double-free possible when mixing C and Go memory ownership

### Cryptography & Secrets

- **Cryptography**: custom crypto instead of `crypto/*` standard library packages
- **Timing Attacks**: use `subtle.ConstantTimeCompare` for secret comparison — but note it leaks length information when slices differ in size; ensure inputs are equal length or use HMAC comparison
- **Weak Randomness**: `math/rand` is not cryptographically secure — use `crypto/rand` for tokens, keys, nonces
- **Hardcoded Secrets**: API keys, passwords, or TLS certificates embedded via `//go:embed` directives are compiled into the binary and extractable

### Serialization & Parsing

- **JSON Case-Insensitive Matching**: `encoding/json` matches struct fields case-insensitively (including Unicode folding: `ſ` matches `s`) — can bypass authorization checks when paired with case-sensitive downstream consumers ([Anvil Secure audit](https://www.anvilsecure.com/blog/security-gaps-in-json-unmarshal-lessons-from-a-go-audit.html))
- **JSON Duplicate Keys**: `encoding/json` accepts duplicate keys silently, taking the last value — different parsers pick first vs. last, enabling parser differential attacks (cf. CVE-2017-12635)
- **JSON Tag Pitfalls**: `json:"-,omitempty"` creates a field named `-` instead of hiding it; untagged exported fields are marshaled by default, risking data exposure ([Trail of Bits](https://blog.trailofbits.com/2025/06/17/unexpected-security-footguns-in-gos-parsers/))
- **JSON Unknown Fields**: `json.Unmarshal` silently ignores unknown keys — use `Decoder.DisallowUnknownFields()` to reject unexpected input; for YAML use `KnownFields(true)`
- **YAML Deserialization DoS**: YAML bombs (billion-laughs-style) can cause memory exhaustion; Kubernetes had CVE-2019-11253 from malicious YAML payloads
- **Protobuf Infinite Loop**: `protojson.Unmarshal` can enter infinite loop on malformed JSON with `google.protobuf.Any` values (GO-2024-2611)
- **XML Trailing Garbage**: Go's `encoding/xml` accepts leading/trailing garbage data and ignores unknown elements by default — polyglot documents can parse differently across formats
- **Gob Deserialization**: `encoding/gob` can decode arbitrary types; never decode untrusted gob streams without strict type registration

### HTTP & Network

- **SSRF**: `http.Get`/`http.Client` with user-controlled URLs — validate against allowlist, block private IP ranges; `golang.org/x/net/http/httpproxy` IPv6 zone ID confusion allows proxy bypass (CVE-2025-22870)
- **HTTP Request Smuggling**: `net/http` historically accepted malformed Transfer-Encoding headers (CVE-2022-1705) and forwarded raw query params through `httputil.ReverseProxy` (CVE-2022-2880)
- **HTTP/2 Rapid Reset DoS**: malicious client creating and immediately resetting HTTP/2 streams causes excessive server CPU consumption
- **Expect 100-Continue Abuse**: `httputil.ReverseProxy` mishandles `Expect: 100-continue`, leaving proxy with invalid connections (DoS vector)
- **Multipart/Form Memory Exhaustion**: `mime/multipart.Reader.ReadForm` can consume unlimited memory and disk — always set `maxMemory` parameter appropriately

### Error Handling & Information Leakage

- **Raw Error Propagation**: returning wrapped database/infrastructure errors across API boundaries leaks internal details (table names, query structure, stack traces) — translate to domain errors at service boundaries
- **Panic in HTTP Handlers**: unrecovered panics crash the goroutine; `net/http` recovers panics per-request but logs full stack — custom recovery middleware should sanitize output

### Supply Chain

- **Module Typosquatting**: Go Module Mirror caches modules indefinitely — attackers publish malicious typosquats (e.g., `github.com/boltdb-go/bolt` mimicking `boltdb/bolt`), then rewrite the Git tag to clean code; the cached malicious version persists for years ([Socket research](https://socket.dev/blog/malicious-package-exploits-go-module-proxy-caching-for-persistence))
- **go:generate Abuse**: `go generate` executes arbitrary commands from `//go:generate` directives — review all generate directives in dependencies; malicious code can hide in comments
- **Symlink Races in File Operations**: `filepath.Walk`/`WalkDir` and `os.RemoveAll` are susceptible to TOCTOU symlink races — use `os.Root` (Go 1.24+) or `O_NOFOLLOW`/`O_DIRECTORY` flags for safe traversal ([Go blog](https://go.dev/blog/osroot))
- **Archive Zip Bomb**: `archive/zip` file name indexing is super-linear — maliciously crafted ZIP archives cause DoS on first file open

## Security Scanners

| Category | Tools |
|----------|-------|
| SAST | gosec, staticcheck, semgrep, CodeQL |
| Dependency Scan | govulncheck, nancy, OWASP Dependency-Check |
| Secret Scan | gitleaks, truffleHog |
| Meta-Linter | golangci-lint (integrates gosec, staticcheck, and 50+ linters) |
| Container Scan | trivy, grype |
| Binary Analysis | go vet (unsafe.Pointer misuse, missing cancel calls, printf format errors) |
