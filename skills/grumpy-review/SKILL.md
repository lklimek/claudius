---
name: grumpy-review
description: "This skill should be used when the user requests a code review, audit, or quality assessment covering quality, security, dependencies, and documentation. It uses parallel agents and produces a deduplicated, severity-ranked report."
allowed-tools: Read, Grep, Glob, Write, Edit, Bash(git log *), Bash(git diff *), Bash(git rev-parse *), Bash(git show *), Bash(cargo audit *), Bash(npm audit *), Bash(pip-audit *), Bash(govulncheck *), Bash(*consolidate_reports.py *), Bash(*validate_report.py *), Bash(*generate_review_report.py *), Bash(*lint_ephemeral_ids.py *), Bash(which *), Bash(rg *), Bash(ctags *), Bash(global *), Bash(gtags *), Bash(tree-sitter *), Bash(gh search code*), Bash(mkdir *), Bash(mv *), Agent, SendMessage, TaskStop
---

# Code Review Methodology

Parallel specialist agents → consolidated, severity-ranked, deduplicated report.

## Tone

Claudius/Skippy persona with extra grumpiness about the code — complain, disbelieve obvious mistakes, be opinionated. All written output (report JSON, markdown, HTML) stays strictly professional: grumpiness is for the human; the report is for posterity.

**Argument**: `$ARGUMENTS` — optional scope description (e.g., "feat/zk branch", "packages/auth/", "last 5 commits"). If empty, review all changes on the current branch vs the main branch.

## 1. Scope the Review

```bash
# If reviewing a branch
BASE_BRANCH=<main-branch>
git rev-parse --verify "$BASE_BRANCH" >/dev/null 2>&1 || BASE_BRANCH="origin/$BASE_BRANCH"
git log "${BASE_BRANCH}..HEAD" --oneline
git diff "${BASE_BRANCH}...HEAD" --stat

# If reviewing specific paths
git diff "${BASE_BRANCH}...HEAD" -- <paths>
```

Before spawning reviewers, choose one collision-resistant scratch directory for all producer and intermediate output. Include a session-specific suffix even when the PR number is known; two coordinators may review the same PR concurrently:

```bash
REVIEW_KEY=<PR-number-or-branch>
SESSION_FRAGMENT=<current-session-id-fragment>
SCRATCH_DIR="/data/tmp/grumpy-${REVIEW_KEY}-${SESSION_FRAGMENT}"
mkdir -p "$SCRATCH_DIR"
```

Assess scale:
- **Trivial** (< 200 lines, < 5 files, single language): 1 agent — the opposite-tier fallback reviewer (see §2 Trivial reviews), prompted with `security-best-practices` and `coding-best-practices` skills. Skip the consolidation pipeline; the agent writes the report directly.
- **Small** (< 500 lines, < 10 files) through **Medium** (500-5000 lines, 10-50 files): the fixed 3-agent core trio (§2 Core agents) regardless of size. Add `technical-writer-trillian` for doc-heavy changes.
- **Large** (5000+ lines, 50+ files): same 3 core roles, scaled via multiple parallel copies per file group — see §2 Scaling.

## 2. Select Agent Mix

### Trivial reviews (single agent)

Skip the multi-agent pipeline and the fixed trio; spawn exactly ONE fallback reviewer, chosen for maximum independence from how the code was authored:

- **Authored on Opus** (e.g. `developer-bilby` at its `opus` default, or an opus-pinned workflow Implementation phase) → **`claudius:qa-engineer-marvin` on `sonnet`** — opposite-tier independent check.
- **Authored on Sonnet** → **`claudius:project-reviewer-adams` on `opus`** — opposite-tier independent check.
- **Tier unknown/unclear** (human-authored, ambiguous/absent git history, mixed authorship) → default to **`claudius:qa-engineer-marvin` on `sonnet`**.

Determine the authoring tier from `git log` (commit author/trailer, PR metadata, or the invoking workflow's recorded model selection) before spawning; if genuinely indeterminate, use the default above.

The single agent stands in for the entire trio — its prompt must cover security, structural, and adversarial-correctness concerns in one pass; instruct it to also apply the `security-best-practices` and `coding-best-practices` checklists. It writes the report JSON directly — no consolidation. Since §5b never runs on this path, the coordinator assigns `merge_class`/`intent_basis` inline after the producer returns (per `severity` skill § Merge Classification), before rendering.

### Core agents (always include — fixed trio, every non-trivial review)

| Agent (`subagent_type`) | Model | Focus |
|---|---|---|
| `claudius:security-engineer-smythe` | opus | OWASP Top 10, injection, concurrency, panics, DoS, known vulns |
| `claudius:project-reviewer-adams` | opus | Cross-artifact consistency, convention adherence, doc accuracy, structural/idiom code quality (readability, naming, DRY, cross-file duplication, maintainability), specialist orchestration |
| `claudius:qa-engineer-marvin` | sonnet | Adversarial/correctness code quality — actually running tests and lints, edge cases, ownership/panic/error-handling bugs, independent verification against ground truth |

All three are ALWAYS included for any non-trivial review — no per-language conditional agent; Adams and Marvin jointly cover the code-quality slice (see Focus). `developer-bilby` never reviews — implementation-only.

### Language best-practices preload

`project-reviewer-adams` and `qa-engineer-marvin` preload the matching `*-best-practices` skill(s) — `rust-best-practices`, `python-best-practices`, `go-best-practices`, `frontend-best-practices` — for whichever language(s) the diff touches. Name the specific skill(s) explicitly in each spawn prompt.

### Other conditional agents

| Condition | Agent (`subagent_type`) | Focus |
|---|---|---|
| Documentation changes | `claudius:technical-writer-trillian` | Accuracy, completeness, API docs, changelog |

For crypto-heavy code or significant dependency changes, expand the single security-engineer's prompt to include crypto soundness and dependency audit — do NOT spawn a second instance.

### Scaling for large codebases

For 50+ files / 5000+ lines, spawn multiple agents of the same type with different file scopes.

## 3. Craft Agent Prompts

Beyond the general agent prompt requirements, every review agent prompt MUST include:

1. **Comparison base**: how to see what changed (`git show <base>:<file>` or `git diff`)
2. **Finding format**: the severity levels and structure below
3. **Review checklists**: embed relevant checklist content or rely on preloaded skills
4. **BP preload**: every spawned reviewer (`security-engineer-smythe`, `project-reviewer-adams`, `qa-engineer-marvin`, `technical-writer-trillian`, etc.) MUST preload `coding-best-practices` so its Cross-Cutting Rules govern every finding — state this explicitly in each spawn prompt
5. **UX/DX lens**: assess how findings affect end-user workflows and developer experience, not just code correctness
6. **CI context**: when MemCan/WebSearch are unavailable (e.g., CI), instruct: "Do not use memcan tools or WebSearch/WebFetch."
7. **File output**: use the Write tool for creating files — never `cat > file` or heredoc redirections
8. **Full roster**: list every teammate name, role/focus, and file scope in this fan-out, including conditional and scaled reviewers; state that all listed peers are already live so agents do not pause to ask or spawn duplicates
9. **Cross-domain hints**: passively report any issue noticed in a peer's primary domain rather than hunting outside the assigned scope, silently duplicating it, or omitting it; tag the finding with `cross_domain_hint: "<peer-role>"` so consolidation can weigh the overlap
10. **UI-text scan**: scan the diff's user-visible strings — labels, buttons, toasts, dialogs, error messages — for raw exception text, stack traces, error codes, internal jargon, or alarming wording on a benign condition; these trip `G-UI-TEXT` (`claudius:severity`)
11. **Context Digest** (verbatim, when the invoker supplied one — defined in `review-pr` § Context Digest; never restate or reinvent its contents): pass it as its own numbered item with this rule attached — *the digest adjusts scoring (via `claudius:severity`'s non-adversarial `likelihood` recipe), it never suppresses reporting: report the finding with context-adjusted floats, never drop it; a field marked `unknown` changes nothing.*
12. **Worktree isolation (mandatory upfront, not reactive)**: any agent instructed to `git checkout`/build/test the reviewed branch MUST be told to work in a pre-created isolated worktree in its FIRST spawn prompt — never bolted on as a follow-up correction after it has already touched the shared tree (see `grand-admiral` § Worktree Isolation for setup). A reactive correction arrives too late: the checkout already happened, flipping HEAD under any other agent concurrently reading the same shared tree.
13. **Cross-branch isolation, reviewing sibling PRs in one session**: when this session is reviewing more than one branch/PR against the same repo, tell every agent to verify any symbol, function, or API it cites — in findings, positives, or recommendations — actually exists on the branch it was assigned (`git show <its-target-ref>:<file>`), not a sibling branch reviewed in the same session. A shared "positives" blurb or boilerplate recommendation reused across findings is exactly where a sibling branch's content leaks in unnoticed.

### Finding format

Producers write a bare JSON array of `finding_section` objects — the exact shape, required/optional fields, the producers-must-NOT-emit list, and the ID-prefix table are in [references/producer-contract.md](references/producer-contract.md) (mirrors `report-format`). Metadata is coordinator-owned: the coordinator resolves the full 40-character commit SHA (`git rev-parse @{u}`, falling back to `git rev-parse HEAD` without an upstream) and supplies commit/date/branch/project through `prepare --metadata`; `prepare` derives repository metadata from `--repo-root`.

**Hoist the invariant part into a file, don't restate it per spawn.** Items 2–13 above are identical across every producer in a fan-out; with N producers, retyping them N times costs the coordinator real output tokens for zero variable content (measured: ~2500 lines across 5 producers on one large review). Before spawning, copy [references/producer-contract.md](references/producer-contract.md) to `<SCRATCH_DIR>/producer-contract.md` unmodified — it already contains the finding-format JSON contract, the producers-must-NOT-emit list, the ID-prefix table, the call-tree/UI-text/UX-DX/collision/process rules, and the terse report-back instruction (everything below that has no per-agent variable). Then each spawn prompt carries only what actually varies:

```text
Read <SCRATCH_DIR>/producer-contract.md and <SCRATCH_DIR>/context-digest.md (if present) before emitting anything — both apply to your output.

Deployed peers (all already live; do not ask whether they are running):
- <teammate-name> — <reviewer role/focus> — <file scope>
- <teammate-name> — <reviewer role/focus> — <file scope>

Your role: <role>. Your file scope: <scope>. Write your findings to <SCRATCH_DIR>/<role>-findings.json.
```

Archive `producer-contract.md` next to `report.json` (like `context-digest.md`) so the fan-out is auditable after the fact.

### Call-tree inspection

When the diff modifies or removes any function/method declaration, every code-quality reviewer runs the deep transitive in-repo caller walk in [references/call-tree-walk.md](references/call-tree-walk.md) before emitting findings (`category: "call_tree"`, `CALL-` prefix, `description` starting `Walked via: <tool>`). Skip for pure additions, doc-only PRs, and test-file-only changes.

### Ephemeral-ID lint

After each agent emits findings, run the dumb ephemeral-ID lint against the diff:

```bash
git diff "${BASE_BRANCH}...HEAD" | python3 ${CLAUDE_SKILL_DIR}/../../scripts/lint_ephemeral_ids.py --diff
```

For each hit, judge genuine violation vs quoted/escaped example (a code fence demonstrating the rule, a test fixture asserting it, this lint's own docstring). Dismiss in-skill examples; promote genuine violations to `code_quality` findings with `tags: ["ephemeral-id-reference"]` and ID prefix `CODE-` (coordinator-assigned). The lint always exits 0 — judgement is yours.

## 4. Spawn Agents

This skill runs inline (not forked) so it can spawn reviewer agents. Before fanning out, confirm the `Agent` tool is available; if not (e.g. inside a subagent, which cannot spawn nested agents), STOP and report that the review cannot fan out — never silently fall back to a single self-run review. The TRIVIAL path (§1/§2) is the only legitimate one-agent review.

Spawn all agents in parallel with fixed per-role tiering: `claudius:security-engineer-smythe` on `opus`, `claudius:project-reviewer-adams` on `opus`, `claudius:qa-engineer-marvin` on `sonnet` (`claudius:delegate` § Token Economy).

**Model override (user-requested; confirm before downgrading Smythe)**: on explicit request (e.g. "review with Sonnet") the user may force a uniform model override across all 3 agents. Apply it to Adams and Marvin freely. Before applying an override that would downgrade `security-engineer-smythe` below `opus`, STOP and confirm the user really means it — security depth is not silently traded away by a blanket model request. Once confirmed, apply to all three including Smythe.

Example spawn pattern:

```
Agent(subagent_type="claudius:security-engineer-smythe", model="opus", prompt="...", name="security-auditor")
Agent(subagent_type="claudius:project-reviewer-adams", model="opus", prompt="...", name="project-reviewer")
Agent(subagent_type="claudius:qa-engineer-marvin", model="sonnet", prompt="...", name="qa-reviewer")
```

## 5. Consolidate Findings

After all agents complete, the two-phase consolidation script does the mechanical work (flattening, duplicate detection, ID assignment, statistics); judgment calls (dedup merging, severity re-assessment, executive summary) are yours.

### 5a. Phase 1 — Prepare

Flatten all agent reports, detect duplicate candidates, scan for INTENTIONAL comments:

```bash
python3 ${CLAUDE_SKILL_DIR}/../../scripts/consolidate_reports.py prepare \
    security-engineer:"$SCRATCH_DIR"/security-findings.json \
    project-reviewer:"$SCRATCH_DIR"/project-findings.json \
    qa-engineer:"$SCRATCH_DIR"/qa-findings.json \
    --repo-root $(git rev-parse --show-toplevel) \
    --output "$SCRATCH_DIR"/intermediate.json \
    --metadata '{"project":"...","date":"...","branch":"...","commit":"..."}'
```

Produces `intermediate.json`: flattened `raw_findings` (with agent attribution), `duplicate_groups` (candidate clusters with overlap reasons), `intentional_downgrades` (findings near INTENTIONAL comments), and `section_positives`.

### 5b. Review and merge (LLM judgment)

Read `intermediate.json` and decide:

1. **Duplicate resolution**: per `duplicate_groups` entry, merge (keep the most detailed description, union tags) or keep separate. Remove redundant findings.
2. **INTENTIONAL downgrade**: downgrade each `intentional_downgrades` finding to `INFO` — deliberate engineering decisions from previous triage.
3. **Severity re-evaluation**: load the `severity` skill (`/severity`), then re-assess every finding strictly against its criteria — agents often over-inflate.
4. **Merge classification**: assign `merge_class` per `severity` skill § Merge Classification — `blocking` only when a blocker gate trips, with `intent_basis` naming the gate ID plus one line of evidence. Use the Context Digest when the invoker supplied one (`review-pr` § Context Digest) for `G-INTENT` judgment; with no PR context, derive intent from your own knowledge of the work's goal — the coordinator often knows the bigger picture the producers don't. Apply the digest as a coordinator-side backstop too: re-check any finding whose floats ignore an evidenced operational-profile claim a producer plainly didn't have (`severity` skill § `likelihood`). Severity never determines `merge_class`. Escalate to the human explicitly (never silently defer) any pre-existing finding tripping `G-FUNDS`/`G-SECRET`/`G-CRYPTO`/`G-DATA`.
5. **Merge sections**: combine same-category agent sections into unified sections.
6. **Executive summary**: write `overall_assessment`, `summary_text`, `verdict_text`, `verdict_action` — LLM-authored, but it must not contradict the merge classification; reflect every valid `blocking` finding.
7. **Agent stats**: copy `intermediate.json`'s `agent_stats` array verbatim into `merged-findings.json` — `prepare` already computes it; do not hand-author or reshape it.

For reviews above roughly 30 raw findings, use the ready-to-run merge helper instead of transcribing the entire document by hand. Record the review-specific judgment in `"$SCRATCH_DIR"/merge-decisions.json`: each true duplicate cluster names its members by `agent` + `original_id`, selects one member as the base, records a `reason`, and supplies only the hand-authored merged fields in `updates`. Include the step 6 `executive_summary` in the same file. Do not list candidate clusters you decide to keep separate.

```json
{
  "executive_summary": {
    "overall_assessment": "...",
    "summary_text": "...",
    "verdict_text": "...",
    "verdict_action": "..."
  },
  "merges": [
    {
      "reason": "Both findings describe the same unchecked parser failure.",
      "members": [
        { "agent": "security", "original_id": "SEC-001" },
        { "agent": "qa", "original_id": "QA-003" }
      ],
      "base": { "agent": "security", "original_id": "SEC-001" },
      "updates": {
        "description": "Hand-authored merged text.",
        "tags": ["..."],
        "code_snippets": [
          { "language": "...", "content": "..." }
        ]
      }
    }
  ]
}
```

For every field combined from peers, put the complete merged value in `updates` (for example, the union of `tags` or `code_snippets`). The helper does not decide which findings overlap. It shallow-copies untouched findings, applies only the declared cluster merges, combines same-category sections, and copies `metadata`, `section_positives`, and `agent_stats` from `intermediate.json`:

```bash
python3 ${CLAUDE_SKILL_DIR}/../../scripts/merge_findings_helper.py \
    --input "$SCRATCH_DIR"/intermediate.json \
    --decisions "$SCRATCH_DIR"/merge-decisions.json \
    --output "$SCRATCH_DIR"/merged-findings.json
```

Before assembly, finish the per-finding edits required by steps 2–4, verify the combined sections and executive summary from steps 5–6, and keep `merge-decisions.json` in the scratch directory so each merge remains auditable.

Write the result as `"$SCRATCH_DIR"/merged-findings.json`. Its `agent_stats` value is the unchanged array copied from `intermediate.json`:

```json
{
  "metadata": { "project": "...", "date": "...", ... },
  "executive_summary": { "overall_assessment": "...", ... },
  "findings": [ { "title": "...", "category": "...", "findings": [...], "positives": "..." } ],
  "agent_stats": [ { "agent": "...", "unique": N, "redundant": N } ],
  "top_findings_override": null,
  "remediation_override": null
}
```

Findings do NOT need `id` fields — phase 2 assigns them. Set `top_findings_override`/`remediation_override` to a JSON array to override auto-generation, or `null` to auto-generate.

### 5c. Phase 2 — Assemble

```bash
python3 ${CLAUDE_SKILL_DIR}/../../scripts/consolidate_reports.py assemble \
    --input "$SCRATCH_DIR"/merged-findings.json \
    --output ${REPORT_DIR:-.}/report.json
```

Assigns sequential IDs by category (SEC-001, PROJ-001, RUST-001, etc.), computes `summary_statistics` (severity counts, category matrix, redundancy ratio), generates `top_findings` from CRITICAL/HIGH items, and creates `remediation` priority buckets. Validates against the schema and REFUSES to write output on failure (exit 1) — validation is mandatory; jsonschema is a hard requirement.

### 5d. Validate report against schema

Assemble already validates and blocks output, but re-validate manually after hand-editing the report:

```bash
python3 ${CLAUDE_SKILL_DIR}/../../scripts/validate_report.py report.json
```

If validation fails, fix `merged-findings.json` and re-run assemble. Do NOT skip validation.

### 5e. Render markdown report

```bash
python3 ${CLAUDE_SKILL_DIR}/../../scripts/generate_review_report.py ${REPORT_DIR:-.}/report.json --format md
```

Produces `report.md` next to the JSON file.

When presenting results, filter the consolidated findings for `merge_class == "out_of_scope_follow_up"` and name that list to the user as deferral candidates — nothing files them, so an unmentioned deferral is an invisible one (`claudius:severity` § `out_of_scope_follow_up`).

### 5f. Stop reviewer processes

After every reviewer output has been read and consolidation is complete, send `SendMessage({type: "shutdown_request"})` to each spawned teammate, including ones already marked inactive (`grand-admiral` § Terminating Teammates — `TaskStop` cannot address a named teammate). Agent completion does not reliably tear down the tmux-backed process: sweep orphaned panes per `grand-admiral`'s `references/stall-watchdog.md` § Orphaned Panes and Processes.

## 6. Iterate if Needed

If the initial review reveals areas needing deeper investigation: spawn additional agents with narrower scope, re-review specific files with different checklists, audit forked dependencies against upstream.

## 7. Additional Report Formats (Optional)

If the user requests HTML or PDF:

```bash
python3 ${CLAUDE_SKILL_DIR}/../../scripts/generate_review_report.py ${REPORT_DIR:-.}/report.json --format html
python3 ${CLAUDE_SKILL_DIR}/../../scripts/generate_review_report.py ${REPORT_DIR:-.}/report.json --format pdf
```

For interactive triage, use the `claudius:triage-findings` skill with the `${REPORT_DIR:-.}/report.json` path.

## CI Log Retrieval

See `git-and-github` skill § Context Management for the subagent delegation pattern. Always delegate `get_job_logs` fetches to a subagent that extracts the relevant failure information.

## Anti-Patterns (Review-Specific)

1. **Skipping scope assessment** — agent mix and split strategy depend on review size.
2. **Missing comparison base** — always include the git diff/show commands in the prompt.
3. **No deduplication** — parallel agents flag the same issue; always consolidate before presenting.
