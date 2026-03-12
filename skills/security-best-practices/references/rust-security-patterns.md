# Rust Security Patterns

Concrete attack patterns to hunt for during Rust code review.
Complements the OWASP checklists with Rust-specific concerns.

## Attack Patterns

### Unsafe Code & Soundness

- **Unsafe Code**: review every `unsafe` block for soundness — memory safety, aliasing, uninitialized data
- **Memory Safety**: verify lifetimes and borrowing correctness in `unsafe` code
- **Transmute Abuse**: `std::mem::transmute` can bypass type safety — verify alignment, validity, and provenance of every transmuted type ([CVE patterns in RustSec](https://rustsec.org/categories/memory-corruption.html))
- **Incorrect Send/Sync**: manual `unsafe impl Send` or `unsafe impl Sync` on types with interior mutability or raw pointers causes data races — verify bounds on generic parameters ([Rustonomicon: Send and Sync](https://doc.rust-lang.org/nomicon/send-and-sync.html))
- **Pin/Unpin Misuse**: types relying on pinning for soundness must not implement `Unpin` — check for missing `PhantomPinned` fields in self-referential types ([Unsoundness in Pin](https://internals.rust-lang.org/t/unsoundness-in-pin/11311))
- **mem::forget / ManuallyDrop**: leaking values is safe but can cause resource exhaustion DoS — audit code that depends on destructors running for correctness (e.g., lock guards, file handles) ([Rustonomicon: Leaking](https://doc.rust-lang.org/nomicon/leaking.html))

### Integer & Arithmetic

- **Integer Overflow**: arithmetic overflow wraps silently in release mode (use `checked_*` or `saturating_*`)

### Concurrency & Async

- **Panic Safety**: ensure no data corruption on panic (drop handlers, mutex poisoning)
- **Lock Across Await**: holding `std::sync::Mutex` or `RwLock` guard across `.await` blocks the tokio runtime — use `tokio::sync::Mutex` or restructure to drop guard before await ([Turso: How to deadlock Tokio](https://turso.tech/blog/how-to-deadlock-tokio-application-in-rust-with-just-a-single-mutex))
- **Unbounded Queues/Channels**: `tokio::sync::mpsc::unbounded_channel` and unbounded `tokio::spawn` fanout allow memory exhaustion DoS — prefer bounded channels with backpressure ([Tokio docs: Channels](https://tokio.rs/tokio/tutorial/channels))
- **Uncontrolled Task Spawning**: `tokio::spawn` on attacker-controlled input without concurrency limits enables DoS — use `Semaphore` or `buffer_unordered` with limits ([Sherlock Rust Security Guide](https://sherlock.xyz/post/rust-security-auditing-guide-2026))

### Serialization & Input

- **Deserialization**: validate untrusted input schema before `serde` deserialization
- **Archive Path Traversal**: `tar`, `async-tar`, `tokio-tar`, and `zip` crates are vulnerable to directory traversal (Zip-Slip) via `../` in filenames — validate extracted paths stay within target directory (CVE-2025-62518 "TARmageddon", [CVE-2025-29787](https://security.snyk.io/vuln/SNYK-RUST-ZIP-9460813))
- **Stack Overflow via Decompression**: deeply nested or maliciously crafted compressed input can cause stack overflow — enforce recursion limits on deserialization and decompression ([RustSec DoS advisories](https://rustsec.org/categories/denial-of-service.html))

### FFI & System Interfaces

- **FFI Boundaries**: audit all `extern "C"` interfaces for null pointers, buffer sizes, lifetime mismatches
- **Command Injection (Windows)**: `std::process::Command` on Windows did not properly escape arguments to batch files (`.bat`, `.cmd`) — CVE-2024-24576 "BatBadBut" (CVSS 10.0), incomplete fix bypassed via trailing whitespace in CVE-2024-43402 — update to Rust >= 1.81.0 ([Rust Blog: CVE-2024-24576](https://blog.rust-lang.org/2024/04/09/cve-2024-24576.html))
- **TOCTOU in std::fs**: `std::fs::remove_dir_all` had a symlink-following race condition enabling privilege escalation (Rust < 1.58.1) — audit filesystem operations in privileged contexts for similar TOCTOU patterns ([GHSA-r9cc-f5pr-p3j2](https://github.com/rust-lang/rust/security/advisories/GHSA-r9cc-f5pr-p3j2))
- **Use-After-Free in unsafe FFI**: the first Rust CVE in the Linux kernel (CVE-2025-68260) was a UAF in an unsafe block caused by a race condition — audit unsafe blocks at FFI boundaries for concurrent access ([Penligent: CVE-2025-68260](https://www.penligent.ai/hackinglabs/rusts-first-breach-cve-2025-68260-marks-the-first-rust-vulnerability-in-the-linux-kernel/))

### Cryptography

- **Timing Side-Channels**: LLVM may optimize constant-time bitwise masking into branches — use the `subtle` crate for constant-time comparisons, never `==` on secrets ([Trail of Bits: optimization barriers](https://blog.trailofbits.com/2022/01/26/part-1-the-life-of-an-optimization-barrier/))
- **Weak RNG**: use `rand::rngs::OsRng` or `rand::thread_rng` (ChaCha-based) for cryptographic randomness — never `rand::rngs::SmallRng` or `rand::rngs::StdRng` seeded from non-crypto sources

### Supply Chain

- **Build Script Code Execution**: `build.rs` and proc-macros execute arbitrary code at compile time with full host privileges — audit `build.rs` in dependencies, use ephemeral/isolated build environments ([Rust Supply Chain Security Guide](https://rust-secure-code.github.io/rust-supply-chain-security/build.html))
- **Typosquatting on crates.io**: malicious crates mimicking popular names (e.g., `faster_log` / `async_println` stealing crypto keys, 8,424 downloads in 2025) — verify crate provenance, use `cargo-deny` source restrictions ([Rust Blog: malicious crates](https://blog.rust-lang.org/2025/09/24/crates.io-malicious-crates-fasterlog-and-asyncprintln/))
- **Proc-Macro Supply Chain**: proc-macro crates run at compile time and can exfiltrate data or modify the build host — treat proc-macro dependencies with the same scrutiny as build scripts ([rust-lang/rust-analyzer#14375](https://github.com/rust-lang/rust-analyzer/issues/14375))

### Regex

- **ReDoS Resistance**: Rust's `regex` crate uses Thompson NFA (guaranteed linear time) and is safe from ReDoS, but crates using backreferences or PCRE bindings (e.g., `fancy-regex`, `pcre2`) are vulnerable — audit regex engine choice for user-controlled patterns ([Rust regex design](https://docs.rs/regex))

## Security Scanners

| Category | Tools |
|----------|-------|
| SAST | clippy (security lints), semgrep, MIRAI (abstract interpretation) |
| Unsafe Analysis | cargo-geiger (unsafe usage stats), Rudra (unsafe soundness bugs), Miri (UB detection via interpretation) |
| Dependency Scan | cargo audit (RustSec DB), cargo deny (licenses + sources + advisories), cargo vet (supply chain trust) |
| Secret Scan | gitleaks, truffleHog |
| Fuzzing | cargo-fuzz (libFuzzer), AFL.rs, honggfuzz-rs |
