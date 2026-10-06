# Merge Classification — Reference

Detail behind `severity` § 5. Read before assigning `merge_class` — coordinator during consolidation, or a coordinator-inline producer. Gate IDs (`G-*`) and the `relevance` scale are defined in `severity` § 2 and § 3.

## Establishing PR intent (for G-INTENT)

1. Explicit human requirements and acceptance criteria, including session knowledge the coordinator holds
2. Linked issue / spec requirements
3. PR title and behavioral claims in its description
4. Invariants necessarily implied by the requested behavior

Incidental implementation details are NOT requirements unless presented as a behavior, guarantee, or security invariant.

## Decision tree (apply in order)

```
informational/praise (praise, INTENTIONAL downgrade,
  RESOLVED comment, relevance 0.0)                 → omit merge_class
invalid (ai_verdict false_positive | duplicate)    → disputed
trips any blocker gate (`severity` § 2), reachable through
  this PR's code paths                             → blocking
relevance ≥ ~0.5 (in or adjacent to the change)    → non_blocking
must not survive this review — leaving it in the
  codebase indefinitely is unacceptable            → non_blocking
otherwise (acceptable to leave permanently)        → out_of_scope_follow_up
```

## Pre-existing findings

A gate tripped by code the PR did not touch does not automatically block — but 🔴 **a pre-existing finding tripping G-FUNDS, G-SECRET, G-CRYPTO, or G-DATA is never silently deferred.** Surface it to the human explicitly and let them decide; classifying it `out_of_scope_follow_up` without saying so out loud is a doctrine violation.

Other pre-existing issues block only when the PR relies on them, worsens them, or newly exposes them, or when fixing them is necessary for an explicit stated goal. A residual gap after a partial improvement blocks only when the PR claims full closure of that gap.

## `out_of_scope_follow_up` means "probably never fixed"

🔴 Deferral is not a plan — nothing files these findings (summary-only, never inline: review-pr § Part B), so they have a **low probability of ever being actioned**. Read the class as **"acceptable to never fix"**:

- Deferrals MUST be surfaced by name when presenting results (grumpy-review §5c) — a user cannot accept a risk they never saw.
- Deferring *because* someone will presumably pick it up later is a mis-classification. A finding that must be fixed is classified for fixing now: `blocking` when a gate trips, `non_blocking` otherwise.
- Correct only where permanent non-fix is acceptable: unrelated pre-existing nits, speculative hardening, taste. The bias toward larger PRs is deliberate — better than laundering real defects into a backlog that does not exist.

## External-reviewer compatibility map

| External field | Claudius equivalent |
|---|---|
| `validity: valid / disputed` | `ai_verdict` (`false_positive`/`duplicate` ≈ disputed) |
| `merge_class` | `merge_class` (same 4 values) |
| `impact_severity` | derived `severity` label (INFORMATIONAL ≈ INFO) |
| `confidence` | `ai_verdict_confidence` |
| `intent_basis` | `intent_basis` |
| `material_impact` | `impact_description` |
| OWASP `risk` (schema v3) | `likelihood` — near-equivalent, migrates by rename |
| OWASP `scope` (schema v3) | **nothing.** v3 `scope` was blast radius, which now folds into `impact`. It is NOT `relevance` (PR-goal fit) — never carry a v3 `scope` value into `relevance`; that value decides `merge_class` and a migrated blast radius there is wrong. Migrated v3 findings need `relevance` re-rated by a human or `validate-findings`. |
