---
name: severity
description: Use when rating findings in reviews, audits, and assessments. Preloaded on finding-producing agents.
---

# Severity Classification

Use these levels when rating findings in reviews, audits, and assessments.

Inspired by [CVSS v4.0](https://www.first.org/cvss/v4.0/specification-document) qualitative
ratings and [OWASP Risk Rating](https://owasp.org/www-community/OWASP_Risk_Rating_Methodology),
adapted for general code review findings beyond pure security.

## Levels

**CRITICAL** — Exploitable vulnerability, data loss, correctness bug causing wrong results,
or system breakage. Production incident if deployed.
*CVSS equivalent: 9.0-10.0. Examples: RCE, SQL injection, data breach, silent data corruption.*

**HIGH** — Significant risk or correctness issue that will likely cause problems.
Workaround may exist but is not acceptable long-term.
*CVSS equivalent: 7.0-8.9. Examples: privilege escalation, race condition causing data loss,
broken authentication, missing input validation on untrusted data.*

**MEDIUM** — Real issue that requires additional factors to manifest, or a design flaw that
increases future risk. Typically fixed before production.
*CVSS equivalent: 4.0-6.9. Examples: information disclosure, missing rate limiting, code
duplication creating maintenance risk, error handling that swallows context.*

**LOW** — Improvement recommended. Minor issue, defense in depth, code hygiene, or deviation
from best practices. No immediate risk but worth addressing.
*CVSS equivalent: 0.1-3.9. Examples: non-idiomatic code, missing documentation, inconsistent
naming, suboptimal algorithm for current scale.*

**INFO** — Positive observation. Something done well, a good pattern worth noting, or context
that helps readers understand the codebase. No action required.
*CVSS equivalent: None (0.0). Examples: well-structured error handling, good test coverage,
clean separation of concerns, effective use of type system.*

## Numeric Mapping

Emit severity as an integer in finding JSON:

| Value | Label    |
|-------|----------|
| 5     | CRITICAL |
| 4     | HIGH     |
| 3     | MEDIUM   |
| 2     | LOW      |
| 1     | INFO     |

## Rules

- Everything that may require action must be **LOW or higher**
- **INFO** is exclusively for praise and context — never for suggestions or improvements
- When in doubt between two levels, choose the higher one
- Severity reflects **impact and likelihood**, not effort to fix
- Severity states shipped impact only — whether a finding blocks THIS PR is the orthogonal `merge_class` axis (see Merge Classification below); never encode merge-worthiness in the severity floats or label
- A trivial one-line fix can still be CRITICAL if the impact is severe
- UX/DX impact is a severity factor — a broken user journey or confusing developer experience can be HIGH even if the code compiles and passes tests

## OWASP Risk Rating normalization

Schema v3 decomposes severity along three 0.0–1.0 dimensions per the [OWASP Risk Rating Methodology](https://owasp.org/www-community/OWASP_Risk_Rating_Methodology). The coordinator computes `overall_severity = (risk + impact + scope) / 3` and derives the integer `severity` from the band table below — never ask the LLM to do the arithmetic.

### `risk` (OWASP Likelihood, normalized)

Score each OWASP Likelihood factor 0–9 per the methodology, take the arithmetic mean, then divide by 9.0 to land in 0.0–1.0:

- **Threat agent**: Skill level, Motive, Opportunity, Size
- **Vulnerability**: Ease of discovery, Ease of exploit, Awareness, Intrusion detection

```
risk = average(factor_scores) / 9.0
```

### `impact` (OWASP Impact, normalized)

Same recipe over OWASP Impact factors — score 0–9 per factor, average, divide by 9.0:

- **Technical**: Loss of confidentiality, integrity, availability, accountability
- **Business**: Financial damage, Reputation damage, Non-compliance, Privacy violation

```
impact = average(factor_scores) / 9.0
```

For pure code-quality findings without a security angle, score the technical factors only and treat business factors as 0 — the average still lands in a sensible band.

### `scope` (blast radius)

`scope` is the **actual blast radius** — the fraction of users / surface / call-sites the finding reaches. Rate it per finding from the evidence; it is **not** a default-`1.0` field and **MUST NOT** be left at `1.0` unless the issue genuinely affects the whole surface. A lazy `1.0` floors the mean at MEDIUM and inflates every report.

| Value | Blast radius |
|-------|---------|
| `1.0` | Repo-wide — all users / the entire public surface / every call-site |
| `~0.5` | A module or subsystem — one bounded component |
| `~0.2` | A single call-site, rare path, or narrow edge case |
| `0.0` | None remaining — resolved, informational, or out-of-PR (derives to INFO) |

PR-relevance maps onto this axis: an issue introduced by and reaching across the diff is high-blast (`~1.0`); a resolved comment or informational note has none (`0.0`). Rate the radius — never paste `1.0`.

### Band table (`overall_severity` → integer `severity`)

CVSS v4.0-aligned bands, applied by the coordinator:

| `overall_severity` | int | label |
|---|---|---|
| ≥ 0.9 | 5 | CRITICAL |
| ≥ 0.7 | 4 | HIGH |
| ≥ 0.4 | 3 | MEDIUM |
| ≥ 0.1 | 2 | LOW |
| < 0.1 | 1 | INFO |

Producers emit `risk`/`impact`/`scope` floats; the coordinator (or `validate-findings` when a producer omits them) writes `overall_severity` and the integer `severity`.

The float trio is the **single source of truth** for severity. Producers MUST NOT hand-type a severity label (CRITICAL/HIGH/…) in a companion document or alongside the floats — every human-readable label is *derived* from `risk`/`impact`/`scope` by the pipeline. A label authored in parallel drifts from the floats and is wrong by construction.

## Merge Classification (orthogonal axis)

`merge_class` answers one question — **does this finding prevent THIS PR from merging?** — while severity answers another: **what is the shipped impact?** The axes are independent. 🔴 **Blocking is a merge class, never a severity**: a LOW can block (it violates an explicit acceptance criterion); a HIGH can be follow-up (pre-existing, unchanged, not required by this PR). Severity and `ai_verdict_confidence` never upgrade a finding to blocking.

Coordinator-owned: assigned during consolidation (grumpy-review §5b, using the intent digest when available, else the coordinator's own knowledge of the work's goal) or inline by coordinator-run producers (review-pr Pass C, check-pr-comments). Fields: `merge_class` enum `blocking|non_blocking|out_of_scope_follow_up|disputed` + `intent_basis` (the exact requirement/claim; always cite it for `blocking`). See `report-format` for schema shape.

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
  codebase indefinitely is unacceptable            → non_blocking
otherwise (acceptable to leave permanently)        → out_of_scope_follow_up
```

**Material** = observable incorrect behavior, security/safety invariant failure, data loss/corruption, crash, invalid persistence/API behavior, or duplicate external operations. Style, speculative hardening, and minor maintainability improvements are NOT material.

**Pre-existing issues** block only when the PR relies on them, worsens or newly exposes them, or fixing them is necessary for an explicit stated goal. A residual gap after a partial improvement blocks only when the PR claims full closure of that gap.

### `out_of_scope_follow_up` means "probably never fixed"

🔴 Deferral is not a plan. There is no follow-up strategy behind this class: deferred findings have a **low probability of ever being actioned**. The realistic outcome is a `TODO` comment that outlives everyone who read the review. Mechanics reinforce this — `out_of_scope_follow_up` findings are summary-only, never posted as inline comments (review-pr § Part B), so nobody is asked to act on them.

Read the class as **"acceptable to never fix"**, not "fix later". Consequences when classifying:

- Deferring a finding *because* someone will presumably pick it up later is a mis-classification — that assumption is false. If a finding genuinely must be fixed, classify it for fixing now: `blocking` when PR intent requires it, `non_blocking` otherwise.
- `out_of_scope_follow_up` stays correct only where permanent non-fix is an acceptable outcome: unrelated pre-existing nits, speculative hardening, taste.
- The tradeoff is deliberate and stated: this bias grows PRs and puts more work in front of authors at review time. That cost is accepted in exchange for not laundering real defects into a backlog that does not exist.

### External-reviewer compatibility map

| External field | Claudius equivalent |
|---|---|
| `validity: valid / disputed` | `ai_verdict` (`false_positive`/`duplicate` ≈ disputed) |
| `merge_class` | `merge_class` (same 4 values) |
| `impact_severity` | derived `severity` label (INFORMATIONAL ≈ INFO) |
| `confidence` | `ai_verdict_confidence` |
| `intent_basis` | `intent_basis` |
| `material_impact` | `impact_description` |
