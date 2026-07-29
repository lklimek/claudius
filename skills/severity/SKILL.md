---
name: severity
description: "This skill should be used when rating findings in reviews, audits, and assessments. Preloaded on finding-producing agents."
---

# Severity Classification

Levels for rating findings in reviews, audits, and assessments. Based on [CVSS v4.0](https://www.first.org/cvss/v4.0/specification-document) qualitative ratings and [OWASP Risk Rating](https://owasp.org/www-community/OWASP_Risk_Rating_Methodology), adapted for general code review beyond pure security.

## Levels

In finding JSON, `severity` is the integer, not the label.

| Int | Label | Meaning | CVSS | Examples |
|---|---|---|---|---|
| 5 | CRITICAL | Exploitable vulnerability, data loss, correctness bug causing wrong results, or system breakage — production incident if deployed | 9.0–10.0 | RCE, SQL injection, data breach, silent data corruption |
| 4 | HIGH | Significant risk or correctness issue that will likely cause problems; workaround may exist but is not acceptable long-term | 7.0–8.9 | Privilege escalation, race condition causing data loss, broken authentication, missing input validation on untrusted data |
| 3 | MEDIUM | Real issue requiring additional factors to manifest, or design flaw increasing future risk; typically fixed before production | 4.0–6.9 | Information disclosure, missing rate limiting, code duplication creating maintenance risk, error handling that swallows context |
| 2 | LOW | Improvement recommended: minor issue, defense in depth, code hygiene, or best-practice deviation; no immediate risk but worth addressing | 0.1–3.9 | Non-idiomatic code, missing documentation, inconsistent naming, suboptimal algorithm for current scale |
| 1 | INFO | Positive observation: something done well, a good pattern, or context that helps readers understand the codebase; no action required | none (0.0) | Well-structured error handling, good test coverage, clean separation of concerns, effective use of type system |

## Rules

- Anything that may require action is **LOW or higher**; **INFO** is exclusively praise and context — never suggestions or improvements
- When in doubt between two levels, choose the higher
- Severity reflects **impact and likelihood**, never effort to fix — a trivial one-line fix can still be CRITICAL
- Severity states shipped impact only — whether a finding blocks THIS PR is the orthogonal `merge_class` axis (see Merge Classification below); never encode merge-worthiness in the severity floats or label
- UX/DX impact is a severity factor — a broken user journey or confusing developer experience can be HIGH even if the code compiles and passes tests

## OWASP Risk Rating normalization

Schema v3 decomposes severity into three 0.0–1.0 dimensions per the [OWASP Risk Rating Methodology](https://owasp.org/www-community/OWASP_Risk_Rating_Methodology). The coordinator computes `overall_severity = (risk + impact + scope) / 3` and derives integer `severity` from the band table below — never ask the LLM to do the arithmetic.

### `risk` (OWASP Likelihood, normalized)

Score each factor 0–9, then `risk = average(factor_scores) / 9.0`. Two recipes — pick by whether an adversary is required to trigger the finding.

**Adversarial findings** (security: an attacker must act) — the OWASP Likelihood factors:

- **Threat agent**: Skill level, Motive, Opportunity, Size
- **Vulnerability**: Ease of discovery, Ease of exploit, Awareness, Intrusion detection

**Non-adversarial findings** (correctness, concurrency, robustness, maintainability — no attacker in the story) — the operational factors, since threat-agent motive is meaningless there and improvising it inflates every such finding:

- **Execution frequency** of the affected path: one-time admin-triggered migration ≈ 0–2; occasional background job ≈ 4–6; per-request hot path ≈ 7–9
- **Precondition probability**: requires concurrent callers that structurally cannot exist in the deployment ≈ 0–1; needs an unusual config or rare input ≈ 3–5; triggered by ordinary input ≈ 7–9
- **Triggering actor**: deliberate action by a trusted operator ≈ 0–2; internal automation ≈ 4–6; any user or untrusted automation ≈ 7–9

🔴 **Evidence rule** — a low operational score MUST cite its evidence: the reviewer's own call-tree/entry-point trace (already mandatory, see `grumpy-review`), a Context Digest claim carrying evidence (`review-pr` § Context Digest), or an explicit human statement. **Unknown is not benign**: with no evidence for the operational reality, score the factors generically — the same rating the finding would get without any context. This axis lowers a score only on evidence, never on assumption, and it never suppresses a finding — it adjusts the floats, the finding is still reported.

### `impact` (OWASP Impact, normalized)

Same recipe over the Impact factors:

- **Technical**: Loss of confidentiality, integrity, availability, accountability
- **Business**: Financial damage, Reputation damage, Non-compliance, Privacy violation

For pure code-quality findings without a security angle, score technical factors only and treat business factors as 0.

### `scope` (blast radius)

The **actual blast radius** — fraction of users / surface / call-sites the finding reaches. Rate per finding from evidence — **never** a default `1.0` unless the issue genuinely affects the whole surface; a lazy `1.0` floors the mean at MEDIUM and inflates every report.

| Value | Blast radius |
|-------|---------|
| `1.0` | Repo-wide — all users / the entire public surface / every call-site |
| `~0.5` | A module or subsystem — one bounded component |
| `~0.2` | A single call-site, rare path, or narrow edge case |
| `0.0` | None remaining — resolved, informational, or no remaining surface (derives to INFO) |

Blast radius ONLY — PR-relevance and intent-matching live exclusively in `merge_class`, never here. A pre-existing repo-wide issue still rates `~1.0`; a diff-introduced single-call-site issue still rates `~0.2`. Rate the radius — never paste `1.0`.

### Band table (`overall_severity` → integer `severity`)

CVSS v4.0-aligned bands, applied by the coordinator:

| `overall_severity` | int | label |
|---|---|---|
| ≥ 0.9 | 5 | CRITICAL |
| ≥ 0.7 | 4 | HIGH |
| ≥ 0.4 | 3 | MEDIUM |
| ≥ 0.1 | 2 | LOW |
| < 0.1 | 1 | INFO |

Producers emit `risk`/`impact`/`scope` floats; the coordinator (or `validate-findings` when a producer omits them) writes `overall_severity` and integer `severity`.

The float trio is the **single source of truth** for severity. Producers MUST NOT hand-type a severity label (CRITICAL/HIGH/…) in a companion document or alongside the floats — every human-readable label is *derived* from the floats by the pipeline; a label authored in parallel drifts and is wrong by construction.

## Merge Classification (orthogonal axis)

`merge_class` answers **does this finding prevent THIS PR from merging?**; severity answers **what is the shipped impact?** The axes are independent. 🔴 **Blocking is a merge class, never a severity**: a LOW can block (violates an explicit acceptance criterion); a HIGH can be follow-up (pre-existing, unchanged, not required by this PR). Severity and `ai_verdict_confidence` never upgrade a finding to blocking.

Coordinator-owned: assigned during consolidation (grumpy-review §5b, using the Context Digest when available, else the coordinator's own knowledge of the work's goal) or inline by coordinator-run producers (review-pr Pass C, check-pr-comments). Fields: `merge_class` enum `blocking|non_blocking|out_of_scope_follow_up|disputed`, `intent_basis` (the exact requirement/claim; always cite it for `blocking`), `deferred_to` (tracking ref; required at MEDIUM+ for `out_of_scope_follow_up`). See `report-format` for schema shape.

### Establish PR intent (priority order)

1. Explicit human requirements and acceptance criteria (incl. session knowledge the coordinator holds)
2. Linked issue / spec requirements
3. PR title and behavioral claims in its description
4. Invariants necessarily implied by the requested behavior

Incidental implementation details are NOT requirements unless presented as a behavior, guarantee, or security invariant.

### Decision tree (apply in order)

```
informational/praise (INFO-intended: praise, INTENTIONAL downgrade,
  RESOLVED comment, scope=0.0 convention)          → omit merge_class
invalid (ai_verdict false_positive | duplicate)    → disputed
required to satisfy explicit PR intent             → blocking
introduced, worsened, or newly exposed by the diff
  AND material                                     → blocking
valid and related to the change                    → non_blocking
must not survive this review — leaving it in the
  codebase indefinitely is unacceptable
    fixing it grows the PR beyond its stated intent
      AND it is filed as a tracked issue
      (deferred_to set)                            → out_of_scope_follow_up
    otherwise                                      → non_blocking
otherwise (acceptable to leave permanently)        → out_of_scope_follow_up
```

Branch order matters: intent-required and diff-introduced-and-material findings already resolved to `blocking` above, so only valid, pre-existing, not-intent-required findings ever reach the tracked-deferral branch.

**Material** = observable incorrect behavior, security/safety invariant failure, data loss/corruption, crash, invalid persistence/API behavior, or duplicate external operations. Style, speculative hardening, and minor maintainability improvements are NOT material.

**Pre-existing issues** block only when the PR relies on them, worsens or newly exposes them, or fixing them is necessary for an explicit stated goal. A residual gap after a partial improvement blocks only when the PR claims full closure of that gap.

### `out_of_scope_follow_up` requires a filed `deferred_to`

🔴 An **untracked** deferral is not a plan — nothing carries it forward; such findings have a **low probability of ever being actioned** (realistic outcome: a `TODO` comment that outlives everyone who read the review). Mechanics reinforce this: `out_of_scope_follow_up` findings are summary-only, never inline comments (review-pr § Part B), so nobody is asked to act on them.

Read the class as **"acceptable to never fix — only because it is filed"**:

- `deferred_to` (issue URL or `owner/repo#N`) is what makes the class valid at MEDIUM+. An unfiled MEDIUM+ deferral is a **mis-classification**, not a valid disposition: file it, or classify it for fixing now — `blocking` when PR intent requires it, `non_blocking` otherwise. `validate_report.py` warns (advisorily) on exactly this shape.
- Deferring *because* someone will presumably pick it up later, with no issue filed, is the failure mode above — that assumption is false without a tracker entry.
- Filing procedure (search-for-duplicate first, then `gh issue create`, then record the ref): `review-pr` § Filing procedure — the single copy.
- Without `deferred_to` the class stays correct only where permanent non-fix is genuinely acceptable and nobody needs to be told: unrelated pre-existing nits at LOW/INFO, speculative hardening, taste.
- The tradeoff is deliberate: requiring a filed ref costs one issue per deferral — accepted in exchange for not laundering real defects into a backlog that does not exist.

### HIGH+ security findings are never silently deferred

A security-relevant finding at HIGH or CRITICAL must never be auto-deferred without a human seeing it: surface it in the review summary as an explicit disposition question — fix now, or defer with a filed `deferred_to` — and state the residual exposure. `out_of_scope_follow_up` on such a finding is a decision for the human, never a coordinator convenience.

### External-reviewer compatibility map

| External field | Claudius equivalent |
|---|---|
| `validity: valid / disputed` | `ai_verdict` (`false_positive`/`duplicate` ≈ disputed) |
| `merge_class` | `merge_class` (same 4 values) |
| `impact_severity` | derived `severity` label (INFORMATIONAL ≈ INFO) |
| `confidence` | `ai_verdict_confidence` |
| `intent_basis` | `intent_basis` |
| `material_impact` | `impact_description` |
