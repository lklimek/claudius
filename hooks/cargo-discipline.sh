#!/usr/bin/env bash
# Plugin-level PreToolUse (Bash) hook: cargo invocation discipline.
#
# FAIL-OPEN by design. This is an EFFICIENCY gate, not a security gate: a missed
# dedup wastes a compile cycle, but a false block wedges an agent. So any internal
# error (missing jq, unparseable stdin, failed target-dir resolution) ALLOWS the
# command. This is the DELIBERATE OPPOSITE of hooks/block-github-writes.sh, which
# fails CLOSED because it guards a real capability. Do not "harmonize" the two.
#
# Quoting/escaping bypasses (e.g. `cargo "test"`, backslash-continued `cargo\
# test`, CLAUDIUS_FORCE=1 appearing anywhere rather than command-leading) are
# accepted limitations, not gaps to close — this hook has no real shell lexer,
# and hardening it further isn't worth the false-positive risk for what remains
# an efficiency gate on cooperative agents, not a security boundary.
#
# Rules (all overridable with CLAUDIUS_FORCE=1 anywhere in the command):
#   1. bare `cargo check` is banned — clippy is a strict superset.
#   2. no 2+ chained COMPILING cargo subcommands in one Bash call (`cargo fmt`
#      may still chain — it does not compile).
#   3. no ad-hoc CARGO_TARGET_DIR=/--target-dir override that differs from the
#      dynamically-resolved canonical target dir (via `cargo metadata`). Scoped
#      override: CLAUDIUS_ISOLATE_TARGET=1 clears ONLY this rule (for the
#      documented concurrent-worktree isolation case in grand-admiral § Worktree
#      Isolation) — unlike CLAUDIUS_FORCE=1, it leaves Rules 1/2/4 enforced and
#      does NOT set the wrapper's own CLAUDIUS_FORCE env var, so ledger replay
#      stays intact for the isolated target dir.
#   4. verification invocations (test|clippy|nextest) must route through
#      scripts/cargo-cached.sh (the verification ledger). Plain `cargo build` is
#      intentionally NOT forced: the ledger replays a recorded VERDICT (a test /
#      clippy pass-fail + log), which a build does not produce — its output is the
#      on-disk artifact, unreplayable. Forcing build would also break the common
#      `cargo fmt && cargo build` step and make a canonical-target-dir build
#      (Rule 3's allow case) unreachable. Build dedup stays available via the
#      wrapper, just not mandated.
#
# CLAUDIUS_FORCE=1 is a GLOBAL allow (clears all four rules, and separately
# tells scripts/cargo-cached.sh to skip its own ledger lookup) — reserve it for
# genuine one-off exceptions. CLAUDIUS_ISOLATE_TARGET=1 is the narrow, routine
# token for concurrent-wave target-dir isolation; it does not touch Rules 1/2/4
# or ledger replay.
set -uo pipefail

allow() { exit 0; }
deny() {
  jq -n --arg r "$1" \
    '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'
  exit 0
}

# jq unavailable -> cannot parse payload -> fail open (allow).
command -v jq >/dev/null 2>&1 || allow

input=$(cat) || allow
# Fast path: if the raw payload never mentions cargo, skip JSON parsing entirely.
case "$input" in *cargo*) ;; *) allow ;; esac

cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // ""' 2>/dev/null) || allow
[[ "$cmd" == *cargo* ]] || allow
# Documented escape hatch — a single literal string siblings' docs reference.
[[ "$cmd" == *CLAUDIUS_FORCE=1* ]] && allow
# Scoped escape hatch — clears Rule 3 only (checked at that rule), not a global allow.
claudius_isolate_target=0
[[ "$cmd" == *CLAUDIUS_ISOLATE_TARGET=1* ]] && claudius_isolate_target=1

hook_cwd=$(printf '%s' "$input" | jq -r '.cwd // ""' 2>/dev/null) || hook_cwd=""
WRAPPER="${CLAUDE_PLUGIN_ROOT:-}/scripts/cargo-cached.sh"

# Match `cargo <sub>` and `cargo +toolchain <sub>` (toolchain override must not
# slip past). `cargo[[:space:]]+` requires whitespace after cargo, so the wrapper
# path "cargo-cached.sh" (cargo followed by '-') never matches. POSIX classes keep
# the regexes portable (no \s / \b GNU-isms).
LEAD='(^|[;&|(]|[[:space:]])'
CARGO='cargo[[:space:]]+(\+[^[:space:]]+[[:space:]]+)?'
TRAIL='([[:space:]]|;|&|\||$)'

# Data, not invocation: a commit message, grep pattern, or echoed string can
# contain the literal text "cargo test" without invoking anything — matching
# raw $cmd would deny e.g. `git commit -m "fix: cargo test now passes"`. Best-
# effort quote-blanking (not a real shell lexer — doesn't handle nested/escaped
# quotes) so Rules 1/2/4 only see text that could plausibly BE a command.
scan=$(sed -E 's/"[^"]*"/""/g; s/'"'"'[^'"'"']*'"'"'/'"''"'/g' <<<"$cmd")

# --- Rule 1: cargo check is banned -----------------------------------------
if grep -qE "${LEAD}${CARGO}check${TRAIL}" <<<"$scan"; then
  deny "cargo check is banned (rust-best-practices): clippy is a strict superset and check artifacts do not seed the clippy cache, so check->clippy compiles twice. Run: $WRAPPER clippy <same scope> -- -D warnings. Rarely-justified override: prefix CLAUDIUS_FORCE=1."
fi

# --- Rule 2: no chained COMPILING cargo commands in one Bash call -----------
# Split on ; & | so each subcommand lands on its own line, then count matching
# lines. `cargo fmt` is not in the compiling set, so fmt && build == 1 (allowed).
n=$(grep -cE "${LEAD}${CARGO}(build|test|clippy|nextest|check|doc|bench)${TRAIL}" \
      <<<"$(tr ';&|' '\n' <<<"$scan")")
if (( n >= 2 )); then
  deny "Chained cargo compile commands waste full compile cycles (rust-best-practices: never chain, never pre-compile). Run ONE command for the outcome you need; combine crate scopes as '-p a -p b' instead of '&&'. cargo fmt may still be chained (it does not compile). Override: prefix CLAUDIUS_FORCE=1."
fi

# --- Rule 3: no ad-hoc target-dir override that differs from canonical ------
# Resolve the canonical dir dynamically (whatever ~/.cargo/config.toml / env this
# machine has). Never compare against a literal path. Resolution failure => allow.
resolve_target_dir() {
  local dir="$1" mc="cargo"
  command -v timeout >/dev/null 2>&1 && mc="timeout 3 cargo"
  ( if [[ -n "$dir" && -d "$dir" ]]; then cd "$dir" 2>/dev/null || exit 0; fi
    $mc metadata --format-version 1 --no-deps 2>/dev/null \
      | jq -r '.target_directory // empty' 2>/dev/null )
}
extract_target_dirs() {
  local c="$1"
  { grep -oE 'CARGO_TARGET_DIR=[^[:space:];&|]+' <<<"$c" | sed 's/^CARGO_TARGET_DIR=//'
    grep -oE '\-\-target-dir[=[:space:]][^[:space:];&|]+' <<<"$c" | sed -E 's/^--target-dir[=[:space:]]//'
  } 2>/dev/null
}
if grep -qE 'CARGO_TARGET_DIR=|--target-dir' <<<"$scan"; then
  canonical=$(resolve_target_dir "$hook_cwd")
  if [[ -n "$canonical" ]]; then
    canonical="${canonical%/}"
    while IFS= read -r ov; do
      [[ -z "$ov" ]] && continue
      ov="${ov//\"/}"; ov="${ov//\'/}"; ov="${ov%/}"
      if [[ -n "$ov" && "$ov" != "$canonical" && "$claudius_isolate_target" != 1 ]]; then
        deny "Ad-hoc target-dir override ('$ov') opts out of the shared cargo target dir ('$canonical', resolved from cargo metadata) and its sccache. Drop the override so builds stay shared. For the documented concurrent-worktree isolation case, prefix CLAUDIUS_ISOLATE_TARGET=1 instead — it clears only this rule and keeps ledger routing enforced. Blanket override (rarely justified): prefix CLAUDIUS_FORCE=1."
      fi
    done <<<"$(extract_target_dirs "$scan")"
  fi
fi

# --- Rule 4: route verification invocations through the ledger --------------
# test|clippy|nextest only — see the header note on why plain build is excluded.
if grep -qE "${LEAD}${CARGO}(test|clippy|nextest)${TRAIL}" <<<"$scan" \
   && [[ "$scan" != *cargo-cached.sh* ]]; then
  deny "Use the verification ledger instead of raw cargo: $WRAPPER <same args, without the leading 'cargo'>. If this exact command already ran on this exact tree (by ANY agent) it replays the recorded log instantly; otherwise it runs, captures the full log, and records the result. Force a real re-run on an identical tree: prefix CLAUDIUS_FORCE=1."
fi

allow
