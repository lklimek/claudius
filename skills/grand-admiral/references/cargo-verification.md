# Cargo Verification — Reference

Detail behind `grand-admiral` § Verification Economy and the cargo rules of § Worktree Isolation. Read before briefing or verifying agents that run cargo, when a build lands in the wrong target dir, when locating a wrapper-built artifact, or when pruning build dirs.

## Verification economy

Every cargo build/test/clippy pays a compile-time floor that no cache erases. The cargo-discipline hook (`hooks/cargo-discipline.sh`) and the verification ledger (`scripts/cargo-cached.sh`; `CLAUDIUS_CACHE_DIR`, XDG cache dir by default) make redundant runs visible and replay the recorded log/exit instead of recompiling.

- **Verification is a role, not a step every agent repeats.** Bilby runs the narrowest relevant scope once through the wrapper before committing; Marvin owns adversarial execution; a programme-manager coordinator executes nothing — it verifies by reading ledger records and logs.
- **Targeted scope throughout — CI is the full-suite backstop.** Never mandate a full local suite run, including at the merge gate (`coding-best-practices` § Code Quality Tool Timing).
- **A ledger record IS the verification.** `{command, tree key, exit 0, log path}` for the CURRENT tree means that command passed on exactly this code.
- **Post-merge re-verification is cheap.** A merged tree is a new tree key; re-running each contributing agent's own scope costs only the per-command floor — no forced full workspace run.
- **Feature matrices are per-tree, not per-agent.** Never brief two agents to run the same feature-combination sweep.
- **Stale diagnostics**: check the ledger for the current tree key first; a fresh build is warranted only when no record exists (`CLAUDIUS_FORCE=1` only for a suspected flake or corrupted fingerprint).

## Provenance check

A green exit and an aggregate pass count are not proof — `cargo test <filter-matching-nothing>` exits 0 and prints "test result: ok". Every verification report must grep the ledger log for the specific new/changed test names and confirm `passed + filtered == expected total`. A green whose log doesn't name your tests is not a green. This also catches residual target-dir collisions where auto-derivation didn't apply.

## Same-HEAD hazard (confirmed silent corruption)

N worktree agents forked from the SAME commit sharing a target dir (an unwrapped `cargo build`, or auto-derivation failing, e.g. `cargo metadata` resolution failed) produce identical artifact paths; cargo mtime-checks A's edits against B's binary, declares A "fresh", and runs B's binary — reporting B's result as A's. A sub-few-second "fresh" `cargo test`/`clippy` result during a same-commit wave is not trustworthy on its face; `cargo-cached.sh` warns on implausibly fast real runs (`CLAUDIUS_MIN_PLAUSIBLE_DUR`) — treat that as a hard re-verify signal.

## Target-dir isolation

- A raw `cargo build` NOT routed through `scripts/cargo-cached.sh` uses the machine's shared target dir and sccache from `~/.cargo/config.toml` — never override `CARGO_TARGET_DIR` for those builds (the hook denies it).
- ANY invocation routed THROUGH `cargo-cached.sh` auto-derives a per-checkout target dir from the checkout's absolute path (worktree, independent clone, submodule alike) — no coordinator action, no per-agent env var. The hook forces `test`/`clippy`/`nextest` through the wrapper; a routed `build` isolates too.
- Bare `cargo metadata` OUTSIDE the wrapper reports the shared dir, NOT the isolated one — don't locate a wrapper-built artifact with it.
- Lock-wait contention across agents building DIFFERENT commits in the shared dir is rare, and queueing beats a cold cache — distinct from the same-HEAD hazard above.

Knobs: `CLAUDIUS_TARGET_PREFIX` places the path-hashed dirs under a chosen root (e.g. `/data/target/<hash>`); unset keeps `<canonical>/claudius-checkouts/<hash>`. An explicit `CARGO_TARGET_DIR` via `CLAUDIUS_ISOLATE_TARGET=1` takes precedence — a manual escape hatch, never routine.

Caveats:

1. rlib sharing across isolated dirs (relink instead of cold rebuild) needs sccache >= 0.14.0 (`SCCACHE_BASEDIRS`); on older sccache it is a no-op, so each checkout pays its own cold rlib build.
2. Derived dirs accumulate PERMANENTLY with no automatic GC (deleting build dirs is destructive) — periodic manual pruning is the coordinator's/user's job.
