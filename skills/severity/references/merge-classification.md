# Merge Classification — Reference

Detail behind `severity` § 5. Read before assigning `merge_class` — coordinator during consolidation, or a coordinator-inline producer. Gate IDs (`G-*`) and the `relevance` scale are defined in `severity` § 2 and § 3.

## Establishing PR intent (for G-INTENT)

1. Explicit human requirements and acceptance criteria, including session knowledge the coordinator holds
2. Linked issue / spec requirements
3. PR title and behavioral claims in its description
4. Invariants necessarily implied by the requested behavior

Incidental implementation details are NOT requirements unless presented as a behavior, guarantee, or security invariant. Review comments, human or bot, are not intent until the user or a human PR author accepts them.

## Decision tree (apply in order)

```
informational/praise (praise, INTENTIONAL downgrade,
  RESOLVED comment, relevance 0.0)                 → omit merge_class
invalid (ai_verdict false_positive | duplicate)    → disputed
trips any blocker gate (`severity` § 2) in PR scope
  (`severity` § 5)                                 → blocking
in PR scope but disproportionate to the PR's
  problem (`severity` § 5)                         → out_of_scope_follow_up
relevance ≥ ~0.5 (in PR scope, `severity` § 5)   → non_blocking
otherwise, whatever its severity or file           → out_of_scope_follow_up
```

## Pre-existing findings

A gate tripped by code the PR did not touch does not automatically block — but 🔴 **a pre-existing finding tripping G-FUNDS, G-SECRET, G-CRYPTO, or G-DATA is never silently deferred.** Surface it to the human explicitly and let them decide; classifying it `out_of_scope_follow_up` without saying so out loud is a doctrine violation.

Other pre-existing issues are in scope only when the PR relies on them, worsens them, or newly exposes them, or when fixing them is necessary for an explicit stated goal — sharing a file or function with the diff is not enough. A residual gap after a partial improvement blocks only when the PR claims full closure of that gap.

## `out_of_scope_follow_up` — not in this PR

Binding rule: `severity` § 5. A separate PR may be stacked on this one. Listing every deferral by name is mandatory — a user cannot accept a risk they never saw.

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
| OWASP `scope` (schema v3) | **nothing.** v3 `scope` was blast radius, which now folds into `impact`. It is NOT `relevance` (PR-goal fit) — never carry a v3 `scope` value into `relevance`; that value decides `merge_class` and a migrated blast radius there is wrong. Migrated v3 findings need `relevance` re-rated by a human or the validation pass (`review-changes` § Reports and Validation). |
