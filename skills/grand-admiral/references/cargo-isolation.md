# Cargo Target-Dir Isolation — Reference

Mechanics behind `grand-admiral` § Worktree Isolation's "isolation is automatic" rule. Read when an agent's build lands in the wrong target dir, when locating a wrapper-built artifact, or when pruning build dirs.

## Shared vs isolated

- A raw `cargo build` NOT routed through `scripts/cargo-cached.sh` uses the machine's shared target dir and sccache from `~/.cargo/config.toml` — never override `CARGO_TARGET_DIR` for those builds (the hook denies it).
- ANY invocation routed THROUGH `cargo-cached.sh` auto-derives a per-checkout target dir from the checkout's absolute path (worktree, independent clone, submodule alike) — no coordinator action, no per-agent env var. The hook forces `test`/`clippy`/`nextest` through the wrapper; a routed `build` isolates too. The coordinator's own merge-gate `test`/`clippy` isolates the same way.
- Bare `cargo metadata` OUTSIDE the wrapper reports the shared dir, NOT the isolated one — don't locate a wrapper-built artifact with it.
- Lock-wait contention across agents building DIFFERENT commits in the shared dir is rare, and queueing beats a cold cache — distinct from the same-HEAD hazard (a correctness bug, not rare) in `grand-admiral` § Worktree Isolation.

## Knobs

- `CLAUDIUS_TARGET_PREFIX` places the path-hashed dirs under a chosen root (e.g. `/data/target/<hash>`); unset/empty keeps the canonical `<canonical>/claudius-checkouts/<hash>` default.
- An explicit `CARGO_TARGET_DIR` via `CLAUDIUS_ISOLATE_TARGET=1` takes precedence — a manual escape hatch for cases auto-derivation doesn't cover (e.g. forcing a specific shared location), never routine.

## Caveats

1. rlib sharing across isolated dirs (relink instead of cold rebuild) needs sccache >= 0.14.0 (`SCCACHE_BASEDIRS`); on the installed **sccache 0.7.7 it is a confirmed no-op**, so each checkout pays its own cold rlib build until sccache is upgraded.
2. Derived dirs accumulate PERMANENTLY with no automatic GC (deleting build dirs is destructive) — periodic manual pruning is the coordinator's/user's job.
3. This retires the failure-prone "assign each agent a distinct `CARGO_TARGET_DIR`" doctrine (confirmed failed repeatedly).
