# Go Security Patterns

Read when reviewing Go code: non-obvious, library/version-specific traps.

## Attack Patterns

### Injection & Parsing

- **SSTI**: user input passed to `template.New().Parse()` at runtime — attacker calls exported methods on the data struct (file read/RCE).
- **CRLF/header injection**: unstripped `\r\n` in `http.NewRequest` URL, `Header.Set`, `mime/multipart.Writer` Content-Disposition fields (CVE-2019-9741).
- **`encoding/json` case-insensitive matching** (incl. Unicode folding `ſ`→`s`): bypasses authz checks when a case-sensitive consumer sits downstream.
- **JSON duplicate keys**: last wins silently; parser differentials vs first-wins parsers (cf. CVE-2017-12635).
- **JSON tag traps**: `json:"-,omitempty"` yields a field named `-` (does not hide it); untagged exported fields are always marshaled.
- **Unknown fields ignored**: use `Decoder.DisallowUnknownFields()`; YAML `KnownFields(true)`.
- **`encoding/xml`**: accepts leading/trailing garbage and ignores unknown elements — polyglot documents parse differently across formats.
- **`encoding/gob`**: decodes arbitrary registered types; never on untrusted streams.
- **`protojson.Unmarshal`** infinite loop on malformed JSON with `google.protobuf.Any` (GO-2024-2611).
- **YAML bombs**: billion-laughs memory exhaustion (Kubernetes CVE-2019-11253).

### Concurrency & Resources

- **Missing `defer cancel()`** after `context.WithCancel/WithTimeout/WithDeadline` leaks the child context and goroutines.
- **Bare `http.ListenAndServe` / `http.Server{}`** without `ReadHeaderTimeout`/`ReadTimeout`/`WriteTimeout`/`IdleTimeout` — Slowloris (gosec G112/G114).
- **`mime/multipart.Reader.ReadForm`** consumes unbounded disk/memory unless `maxMemory` is set.
- **`archive/zip`**: file-name indexing is super-linear — crafted archives DoS on first file open.
- **HTTP/2 Rapid Reset**: create-then-reset streams exhaust server CPU (patch Go/`x/net`).
- **`httputil.ReverseProxy`**: `Expect: 100-continue` mishandling leaves invalid connections (DoS); forwarded raw query params (CVE-2022-2880); malformed Transfer-Encoding accepted by `net/http` (CVE-2022-1705).

### Memory & Types

- **`unsafe`**: `reflect.Value.Pointer()`/`UnsafeAddr()` results must become `unsafe.Pointer` in the same expression or GC may invalidate them; hand-built slice headers can set `Len` past the backing array.
- **Integer wrap** is silent: size/index arithmetic on `int32`/`int64` → infinite loops, bad allocations (CVE-2023-24537, CVE-2022-23772).
- **CGo**: C memory is outside GC; use-after-free/double-free at ownership boundaries.

### Crypto & Secrets

- **`subtle.ConstantTimeCompare`** leaks length on size mismatch — compare equal-length values or HMACs.
- **`//go:embed`** of keys/certs/credentials: compiled into the binary and extractable.

### HTTP & Network

- **`x/net/http/httpproxy`** IPv6 zone ID confusion bypasses proxy rules and SSRF checks (CVE-2025-22870).

### Errors

- **Panic recovery**: `net/http` recovers per request but logs the full stack; custom recovery middleware must sanitize output.

### Supply Chain & Filesystem

- **Module Mirror caching**: typosquats (e.g. `github.com/boltdb-go/bolt`) stay cached after the Git tag is rewritten to clean code — verify module paths, not just current tag content.
- **`//go:generate`** runs arbitrary commands; review directives in dependencies.
- **`filepath.Walk`/`WalkDir`, `os.RemoveAll`**: TOCTOU symlink races — use `os.Root` (Go 1.24+) or `O_NOFOLLOW`/`O_DIRECTORY`.
