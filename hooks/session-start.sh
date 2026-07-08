#!/usr/bin/env bash
# Plugin-level SessionStart hook: inject persistent memory search reminder.
# SessionStart only supports command hooks (not prompt hooks).
set -euo pipefail

# Inject source-of-truth content into Claude's context via additionalContext
SOT="${CLAUDE_PLUGIN_ROOT}/references/source-of-truth.md"
SOT_CONTENT=""
if [[ -f "$SOT" ]]; then
  SOT_CONTENT=$(cat "$SOT")
fi

# Rust build-environment probe — only in Rust sessions (guarded on cargo), and
# cheap enough to stay well within the 5s hook timeout. Reports tool availability
# and the DYNAMICALLY-resolved shared target dir + ledger location (never hardcoded).
RUST_ENV=""
if command -v cargo >/dev/null 2>&1; then
  if command -v cargo-nextest >/dev/null 2>&1; then NX="available"; else NX="NOT installed — do not attempt 'cargo nextest'"; fi
  if command -v sccache >/dev/null 2>&1; then SC="active"; else SC="absent"; fi
  # `|| TGT=""` keeps `set -e`/pipefail from aborting when cargo metadata fails
  # (exit 101 outside a cargo project) — resolution failure is expected, not fatal.
  TGT=$(cargo metadata --format-version 1 --no-deps 2>/dev/null | jq -r '.target_directory // empty' 2>/dev/null) || TGT=""
  [[ -n "$TGT" ]] || TGT="(unresolved — not inside a cargo project)"
  LEDGER="${CLAUDIUS_CACHE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/claudius}/ledger"
  printf -v RUST_ENV '\n\n## Rust build environment\n- Shared target dir: %s — never override CARGO_TARGET_DIR/--target-dir (the cargo-discipline hook denies ad-hoc overrides)\n- sccache: %s; cargo-nextest: %s\n- Verification ledger: %s — route cargo build/test/clippy through scripts/cargo-cached.sh; an identical command on an identical tree replays the recorded log instantly (any agent), CLAUDIUS_FORCE=1 to force a real re-run' "$TGT" "$SC" "$NX" "$LEDGER"
fi

jq -n --arg sot "$SOT_CONTENT" --arg rust "$RUST_ENV" '{
  hookSpecificOutput: {
    hookEventName: "SessionStart",
    additionalContext: ("## Knowledge Source Priorities (Source of Truth)\n\n" + $sot + "\n\n## Memory Actions\n\n**On session start**: If persistent memory tools are available (memcan), search for project context using the categories above. Use `memcan:recall` skill. If memcan is unavailable, skip silently.\n\n**Invoke `claudius:lessons-learned`** when any of these occur:\n- Architecture decision made or changed\n- Coding standard established or clarified\n- Wrong approach corrected (bad-thinking pattern)\n- Non-obvious tool/environment quirk discovered\n- User states a preference or convention\n- Plan changes direction\n- Session ends with new knowledge worth preserving\n\nDo NOT invoke for routine work with no new decisions or corrections." + $rust)
  }
}'
