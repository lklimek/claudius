#!/usr/bin/env bash
# Plugin-level PreToolUse (Bash) hook: cargo invocation discipline.
#
# FAIL-OPEN by design. This is an EFFICIENCY gate, not a security gate: a missed
# dedup wastes a compile cycle, but a false block wedges an agent. So any internal
# error (missing jq, unparseable stdin, failed target-dir resolution) ALLOWS the
# command. This is the DELIBERATE OPPOSITE of hooks/block-github-writes.sh, which
# fails CLOSED because it guards a real capability. Do not "harmonize" the two.
#
# Rules (all overridable with a leading CLAUDIUS_FORCE=1):
#   1. bare `cargo check` is banned — clippy is a strict superset.
#   2. no 2+ chained COMPILING cargo subcommands in one Bash call (`cargo fmt`
#      may still chain — it does not compile).
#   3. no ad-hoc CARGO_TARGET_DIR=/--target-dir override that differs from the
#      dynamically-resolved canonical target dir (via `cargo metadata`).
#   4. verification invocations (test|clippy|nextest) must route through
#      scripts/cargo-cached.sh (the verification ledger). Plain `cargo build` is
#      intentionally NOT forced: the ledger replays a recorded VERDICT (a test /
#      clippy pass-fail + log), which a build does not produce — its output is the
#      on-disk artifact, unreplayable. Forcing build would also break the common
#      `cargo fmt && cargo build` step and make a canonical-target-dir build
#      (Rule 3's allow case) unreachable. Build dedup stays available via the
#      wrapper, just not mandated.
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

hook_cwd=$(printf '%s' "$input" | jq -r '.cwd // ""' 2>/dev/null) || hook_cwd=""
WRAPPER="${CLAUDE_PLUGIN_ROOT:-}/scripts/cargo-cached.sh"

# Match `cargo <sub>` and `cargo +toolchain <sub>` (toolchain override must not
# slip past). `cargo[[:space:]]+` requires whitespace after cargo, so the wrapper
# path "cargo-cached.sh" (cargo followed by '-') never matches. POSIX classes keep
# the regexes portable (no \s / \b GNU-isms).
LEAD='(^|[;&|(]|[[:space:]])'
CARGO='cargo[[:space:]]+(\+[^[:space:]]+[[:space:]]+)?'
TRAIL='([[:space:]]|;|&|\||$)'

# --- Rule 1: cargo check is banned -----------------------------------------
if grep -qE "${LEAD}${CARGO}check${TRAIL}" <<<"$cmd"; then
  deny "cargo check is banned (rust-best-practices): clippy is a strict superset and check artifacts do not seed the clippy cache, so check->clippy compiles twice. Run: $WRAPPER clippy <same scope> -- -D warnings. Rarely-justified override: prefix CLAUDIUS_FORCE=1."
fi

# --- Rule 2: no chained COMPILING cargo commands in one Bash call -----------
# Split on ; & | so each subcommand lands on its own line, then count matching
# lines. `cargo fmt` is not in the compiling set, so fmt && build == 1 (allowed).
n=$(grep -cE "${LEAD}${CARGO}(build|test|clippy|nextest|check|doc|bench)${TRAIL}" \
      <<<"$(tr ';&|' '\n' <<<"$cmd")")
if (( n >= 2 )); then
  deny "Chained cargo compile commands waste full compile cycles (rust-best-practices: never chain, never pre-compile). Run ONE command for the outcome you need; combine crate scopes as '-p a -p b' instead of '&&'. cargo fmt may still be chained (it does not compile). Override: prefix CLAUDIUS_FORCE=1."
fi

# --- Rule 3: no ad-hoc target-dir override that differs from canonical ------
# Resolve the canonical dir dynamically (whatever ~/.cargo/config.toml / env this
# machine has). Never compare against a literal path. Resolution failure => allow.
resolve_target_dir() {
  local dir="$1"
  ( if [[ -n "$dir" && -d "$dir" ]]; then cd "$dir" 2>/dev/null || exit 0; fi
    cargo metadata --format-version 1 --no-deps 2>/dev/null \
      | jq -r '.target_directory // empty' 2>/dev/null )
}
extract_target_dirs() {
  local c="$1"
  { grep -oE 'CARGO_TARGET_DIR=[^[:space:];&|]+' <<<"$c" | sed 's/^CARGO_TARGET_DIR=//'
    grep -oE '\-\-target-dir[=[:space:]][^[:space:];&|]+' <<<"$c" | sed -E 's/^--target-dir[=[:space:]]//'
  } 2>/dev/null
}
if grep -qE 'CARGO_TARGET_DIR=|--target-dir' <<<"$cmd"; then
  canonical=$(resolve_target_dir "$hook_cwd")
  if [[ -n "$canonical" ]]; then
    canonical="${canonical%/}"
    while IFS= read -r ov; do
      [[ -z "$ov" ]] && continue
      ov="${ov//\"/}"; ov="${ov//\'/}"; ov="${ov%/}"
      if [[ -n "$ov" && "$ov" != "$canonical" ]]; then
        deny "Ad-hoc target-dir override ('$ov') opts out of the shared cargo target dir ('$canonical', resolved from cargo metadata) and its sccache. Drop the override so builds stay shared. If isolation is genuinely required, raise it with the coordinator — do not invent a path. Override: prefix CLAUDIUS_FORCE=1."
      fi
    done <<<"$(extract_target_dirs "$cmd")"
  fi
fi

# --- Rule 4: route verification invocations through the ledger --------------
# test|clippy|nextest only — see the header note on why plain build is excluded.
if grep -qE "${LEAD}${CARGO}(test|clippy|nextest)${TRAIL}" <<<"$cmd" \
   && [[ "$cmd" != *cargo-cached.sh* ]]; then
  deny "Use the verification ledger instead of raw cargo: $WRAPPER <same args, without the leading 'cargo'>. If this exact command already ran on this exact tree (by ANY agent) it replays the recorded log instantly; otherwise it runs, captures the full log, and records the result. Force a real re-run on an identical tree: prefix CLAUDIUS_FORCE=1."
fi

allow
