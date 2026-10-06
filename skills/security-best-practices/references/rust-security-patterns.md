# Rust Security Patterns

Read when reviewing Rust code: non-obvious, crate/version-specific traps.

## Attack Patterns

### Unsafe & Soundness

- **Manual `unsafe impl Send/Sync`** on generics, interior mutability or raw pointers: verify bounds on every type parameter.
- **Self-referential types** relying on pinning must not be `Unpin` — check for missing `PhantomPinned`.
- **`mem::forget` / `ManuallyDrop`**: safe, but code whose correctness depends on destructors (lock guards, file handles) breaks.
- **Panic safety**: drop handlers and mutex poisoning leaving corrupted state after unwinding.

### Async & Concurrency

- **`std::sync::Mutex`/`RwLock` guard held across `.await`** deadlocks/blocks the tokio runtime — drop before awaiting or use `tokio::sync::Mutex`.
- **`unbounded_channel` and unlimited `tokio::spawn` on attacker-controlled input**: memory/task exhaustion — bounded channels, `Semaphore`, `buffer_unordered`.

### Parsing & Archives

- **Archive traversal**: `tar`, `async-tar`, `tokio-tar`, `zip` crates (CVE-2025-62518 "TARmageddon", CVE-2025-29787) — validate extracted paths stay inside the target dir.
- **Recursion limits**: deeply nested serde input or compressed data → stack overflow.

### Std & FFI

- **CVE-2024-24576 "BatBadBut"** (CVSS 10.0): `std::process::Command` on Windows mis-escaped args to `.bat`/`.cmd`; incomplete fix bypassed via trailing whitespace (CVE-2024-43402) — need Rust ≥ 1.81.0.
- **`std::fs::remove_dir_all`** symlink-following race (Rust < 1.58.1, GHSA-r9cc-f5pr-p3j2) — audit privileged filesystem code for similar TOCTOU.
- **Linux kernel CVE-2025-68260**: first Rust kernel CVE, a UAF from a race in an `unsafe` block — check concurrent access at FFI boundaries.

### Crypto

- **LLVM may turn constant-time masking into branches**; use the `subtle` crate, never `==` on secrets.
- **`SmallRng` / `StdRng`** seeded from non-crypto sources are not for secrets; use `OsRng` or `thread_rng`.

### Supply Chain & Regex

- **`build.rs` and proc-macros** run arbitrary code at compile time with host privileges; audit them in dependencies (`cargo-deny` source restrictions).
- **Malicious crates** (e.g. `faster_log`, `async_println` stealing keys, 2025) — verify provenance.
- **`regex`** is linear-time (ReDoS-safe), but `fancy-regex` (backreferences) and `pcre2` bindings are not — check the engine when patterns are user-controlled.
