---
name: severity
description: "This skill should be used when rating findings in reviews, audits, and assessments. Preloaded on finding-producing agents."
---

# Severity Classification

Two independent axes per finding:

- **severity** — how bad is the shipped defect? Derived from the `likelihood`/`impact` floats.
- **merge_class** — does this stop THIS PR? Decided by the **blocker gates** below.

Never encode one in the other. A LOW can block (it trips a gate); a CRITICAL can be `out_of_scope_follow_up` (pre-existing, untouched, no gate reachable through this PR).

## 1. Backstop zone (judge this first)

Before rating anything, answer: **what stands between this defect and irreversible harm?** The answer sets the scope of G-INTENT and the ceiling on `impact`.

| Zone | What backstops the code | Worst realistic outcome | `impact` ceiling |
|---|---|---|---|
| **Backstopped** | A server, consensus, or independent validator rejects bad output before it counts | Scary error, confusion, stuck or wedged client, wasted user time | ~0.7 |
| **Sovereign** | Nothing. This code is the last line — key material, signing, entropy, local persistence, offline/standalone tools | Irreversible loss of funds, keys, or data | 1.0 |
| **Boundary** | This code decides *what crosses into* sovereign territory — assembling the tx to be signed, choosing the destination, composing what the user is asked to approve | Same as Sovereign — the backstop validates the *signature*, not the *intent* | 1.0 |

For **server-side code**, the code owns the data — read it as Sovereign over its own persistence, with the operator's monitoring as the only backstop against silent breakage (hence G-SILENT).

**Zone is per finding, never per repo or per app.** One PR routinely spans all three: a wallet's balance-refresh path is Backstopped, its seed-phrase handling is Sovereign, its send-confirmation screen is Boundary. Judge each finding on the code path it actually sits on, from the PR's own context. Do not assign a project a standing zone.

Unsure between two zones → take the more sovereign one.

## 2. Blocker gates

A gate is a **must-not-ship** condition. Tripping any gate ⇒ `merge_class: blocking`, with `intent_basis` set to the gate ID plus one line of evidence (`"G-SECRET: seed phrase written to debug log at wallet/import.rs:88"`). Severity does not override a gate, and a gate does not raise severity.

| ID | Trips when | Zone |
|---|---|---|
| **G-INTENT** | The PR's stated intent is not met | Backstopped: **happy path only**. Sovereign/Boundary: happy path **plus** edge, error, and adversarial paths |
| **G-DATA** | Data loss or corruption, including silent corruption | all |
| **G-FUNDS** | Loss, theft, or misdirection of funds; wrong amounts; double-spends | all |
| **G-CRYPTO** | Insecure cryptography — home-rolled primitives, weak parameters, bad RNG, nonce/IV reuse | all |
| **G-SECRET** | Keys, seeds, or tokens reach logs, files, telemetry, URLs, or the clipboard | all |
| **G-UI-BROKEN** | Dead controls, unreachable flows, destroyed layout, freeze, or crash | all |
| **G-UI-TEXT** | User-visible text that is scary or confusing — raw exceptions, stack traces, internal jargon, alarming wording for a benign condition | all |
| **G-WYSIWYS** | The confirmation screen does not match what is actually signed or sent | Boundary, Sovereign |
| **G-AMOUNT** | Monetary values are displayed wrongly (unit, precision, rounding, fee omission) | all |
| **G-DOUBLE** | Retry or auto-recovery duplicates a spend, broadcast, or other external side effect | all |
| **G-PHISH** | Untrusted data rendered unescaped or clickable, or able to imitate trusted UI | all |
| **G-BRICK** | Upgrade or migration failure prevents startup or destroys the user profile | all |
| **G-SILENT** | Failures are swallowed — operators cannot detect that it broke | Operated services |
| **G-PRIVACY** | Leaks short of secrets — address linkage, identifying telemetry, financial data in logs | all |
| **G-GROWTH** | Unbounded resource growth under normal load | all |
| **G-DEFAULTS** | Ships an insecure default configuration | all |

### Races and concurrency

One rule, zone-dependent likelihood:

- **GUI**: would a real human plausibly do this? Double-clicking submit is plausible → gate trips. A 3-ms window needing scripted timing is not.
- **Server**: concurrency under normal load is near-certain → trips by default; argue your way out with evidence, not the reverse.
- **Sovereign/Boundary**: GUI likelihood, multiplied by permanence — a rare race that permanently destroys keys still trips.

### Explicitly NOT gates

Getting stuck, one-way migrations, protocol drift, compatibility breaks, agent autonomy limits, accessibility, and update mechanics are **ordinary findings**. Rate them with the floats, classify them normally — they never auto-block. Promote one only when it independently trips a gate above.

## 3. Severity floats

Three 0.0–1.0 numbers per finding. No external methodology; these definitions are the whole specification.

### `likelihood` — how likely is this hit?

Probability that a real user or attacker reaches this defect under zone-realistic usage. Include attacker pressure where an attacker exists; include plausible human error.

| Value | Meaning |
|---|---|
| `1.0` | On the happy path — anyone doing the normal thing hits it |
| `~0.7` | Common, workflow-plausible behavior (impatient re-click, back button, offline moment) |
| `~0.4` | Edge case, unusual sequence, unlucky timing |
| `~0.1` | Pathological only — requires deliberate, unrealistic effort |

**Non-adversarial findings** (correctness, concurrency, robustness — no attacker in the story) have no threat agent, and improvising one inflates every such finding. Place them on the ladder using the operational reality instead:

- **Execution frequency** of the affected path — per-request hot path is near `1.0`; occasional background job mid-ladder; one-time admin-triggered migration near the bottom
- **Precondition probability** — triggered by ordinary input is high; needs unusual config or rare input is mid; requires concurrent callers that structurally cannot exist in the deployment is bottom
- **Triggering actor** — any user or untrusted automation is high; internal automation mid; deliberate action by a trusted operator low

The three are **conjunctive**: the defect is reached only when all three line up, so the most limiting one sets the ceiling. Place the finding at that factor's rung — a bug on a per-request hot path that also needs a precondition which structurally cannot occur is rare, not frequent.

🔴 **Evidence rule** — a low rung on any of these MUST cite its evidence: the reviewer's own call-tree/entry-point trace (already mandatory, see `grumpy-review`), a Context Digest claim carrying evidence (`review-pr` § Context Digest), or an explicit human statement. **Unknown is not benign**: with no evidence for the operational reality, score generically — the same rating the finding would get with no context at all. This axis lowers a score only on evidence, never on assumption, and it never suppresses a finding; it adjusts the floats, and the finding is still reported.

### `impact` — how bad is the worst plausible outcome?

Capped by the backstop zone (§1). Blast radius folds in here — a defect reaching every user is worse than one reaching a rare code path.

| Value | Meaning |
|---|---|
| `1.0` | Irreversible loss of funds, keys, or data |
| `~0.7` | Recoverable loss, security degradation, or an unrecoverable-stuck user |
| `~0.4` | Task fails, scary or confusing UX, restart fixes it |
| `~0.1` | Cosmetic |
| `0.0` | No defect exists — informational only (see below) |

**Informational floor.** A finding that reports no defect — praise, a verified-clean pass, a RESOLVED comment — uses `likelihood = 0.0, impact = 0.0`, `relevance = 0.0`. That derives to `0.0` → INFO, which is the only band whose meaning is "no action required". Use exact zeros, never a small hedge like `0.05`: there is no defect, so the probability and the damage are genuinely zero, and a hedged value both misstates that and drifts across documents. Producers relying on a low third term to sink an informational finding into INFO is a v3 habit that no longer works — `relevance` is not in the mean.

### `relevance` — does it fit what this PR set out to do?

Drives `merge_class` and report ordering. **Not** part of the severity math.

| Value | Meaning |
|---|---|
| `1.0` | The very thing this PR set out to do |
| `~0.5` | Adjacent — in the code this PR touched |
| `~0.1` | Pre-existing, unrelated to the change |
| `0.0` | Informational / resolved / praise |

### Derivation

`overall_severity = (likelihood + impact) / 2`, banded below. Computed in Python by the coordinator — never ask an LLM to do the arithmetic.

| `overall_severity` | int | label |
|---|---|---|
| ≥ 0.9 | 5 | CRITICAL |
| ≥ 0.7 | 4 | HIGH |
| ≥ 0.4 | 3 | MEDIUM |
| ≥ 0.1 | 2 | LOW |
| < 0.1 | 1 | INFO |

`relevance` is deliberately excluded: a pre-existing catastrophe is still a catastrophe, and averaging it with PR-fit used to launder it down to MEDIUM.

Producers emit `likelihood`/`impact`/`relevance`; the coordinator (or `validate-findings` when a producer omits them) writes `overall_severity` and integer `severity`.

The floats are the **single source of truth** for severity. Producers MUST NOT hand-type a severity label anywhere — every human-readable label is derived by the pipeline, and a parallel label drifts and is wrong by construction.

## 4. Levels

In finding JSON, `severity` is the integer, not the label.

| Int | Label | Meaning |
|---|---|---|
| 5 | CRITICAL | Production incident if deployed — exploitable vulnerability, data/funds loss, wrong results |
| 4 | HIGH | Will likely cause real problems; a workaround may exist but is not acceptable long-term |
| 3 | MEDIUM | Real issue needing additional factors to manifest, or a design flaw raising future risk |
| 2 | LOW | Minor issue, defense in depth, hygiene, best-practice deviation |
| 1 | INFO | Positive observation or context. No action required |

### Rules

- Anything that may require action is **LOW or higher**; **INFO** is exclusively praise and context — never a suggestion
- In doubt between two levels, take the higher
- Severity never reflects effort to fix — a one-line fix can be CRITICAL
- UX impact is a real severity input: a scary error dialog on the happy path is `likelihood = 1.0, impact ≈ 0.4` → HIGH, and it trips G-UI-TEXT

## 5. Merge Classification

`merge_class` enum: `blocking | non_blocking | out_of_scope_follow_up | disputed`, plus `intent_basis` (the gate ID and evidence, or the exact requirement; always present for `blocking`).

Coordinator-owned: assigned during consolidation (grumpy-review §5b) or inline by coordinator-run producers (review-pr Pass C, check-pr-comments, review-dependency — each runs as the coordinator with no separate consolidation pass). See `report-format` for schema shape.

### Establishing PR intent (for G-INTENT)

1. Explicit human requirements and acceptance criteria, including session knowledge the coordinator holds
2. Linked issue / spec requirements
3. PR title and behavioral claims in its description
4. Invariants necessarily implied by the requested behavior

Incidental implementation details are NOT requirements unless presented as a behavior, guarantee, or security invariant.

### Decision tree (apply in order)

```
informational/praise (praise, INTENTIONAL downgrade,
  RESOLVED comment, relevance 0.0)                 → omit merge_class
invalid (ai_verdict false_positive | duplicate)    → disputed
trips any blocker gate (§2), reachable through
  this PR's code paths                             → blocking
relevance ≥ ~0.5 (in or adjacent to the change)    → non_blocking
must not survive this review — leaving it in the
  codebase indefinitely is unacceptable            → non_blocking
otherwise (acceptable to leave permanently)        → out_of_scope_follow_up
```

### Pre-existing findings

A gate tripped by code the PR did not touch does not automatically block — but 🔴 **a pre-existing finding tripping G-FUNDS, G-SECRET, G-CRYPTO, or G-DATA is never silently deferred.** Surface it to the human explicitly and let them decide; classifying it `out_of_scope_follow_up` without saying so out loud is a doctrine violation.

Other pre-existing issues block only when the PR relies on them, worsens them, or newly exposes them, or when fixing them is necessary for an explicit stated goal. A residual gap after a partial improvement blocks only when the PR claims full closure of that gap.

### `out_of_scope_follow_up` means "probably never fixed"

🔴 Deferral is not a plan — no follow-up strategy exists; deferred findings have a **low probability of ever being actioned** (realistic outcome: a `TODO` comment that outlives everyone who read the review). Mechanics reinforce this: `out_of_scope_follow_up` findings are summary-only, never inline comments (review-pr § Part B), so nobody is asked to act on them.

Read the class as **"acceptable to never fix"**, not "fix later":

- Because nothing files them, deferrals MUST be surfaced: name the deferred list to the user when presenting results (grumpy-review §5e). An unmentioned deferral is an invisible one, and a user cannot accept a risk they never saw.
- Deferring a finding *because* someone will presumably pick it up later is a mis-classification — that assumption is false. If a finding genuinely must be fixed, classify it for fixing now: `blocking` when a gate trips, `non_blocking` otherwise.
- It stays correct only where permanent non-fix is acceptable: unrelated pre-existing nits, speculative hardening, taste.
- The tradeoff is deliberate: this bias grows PRs and puts more work in front of authors — accepted in exchange for not laundering real defects into a backlog that does not exist.

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
