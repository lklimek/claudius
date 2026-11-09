---
name: severity
description: "This skill should be used when rating findings in reviews, audits, and assessments, or deciding whether a finding blocks a merge. It defines the backstop zones, system-scale rating against the project profile, blocker gates, the likelihood/impact/relevance floats, severity bands, and merge classes. Load explicitly before producing findings."
---

# Severity Classification

Two independent axes per finding:

- **severity** — how bad is the shipped defect? Derived from the `likelihood`/`impact` floats.
- **merge_class** — does this stop THIS PR? Decided by the **blocker gates** below.

Never encode one in the other: a LOW can block (it trips a gate); a CRITICAL can be `out_of_scope_follow_up` (pre-existing, outside PR scope, no gate tripped in scope).

## 1. Backstop zone (judge this first)

Before rating anything, answer: **what stands between this defect and irreversible harm?** The answer sets the scope of G-INTENT and the ceiling on `impact`.

| Zone | What backstops the code | Worst realistic outcome | `impact` ceiling |
|---|---|---|---|
| **Backstopped** | A server, consensus, or independent validator rejects bad output before it counts | Scary error, confusion, stuck or wedged client, wasted user time | ~0.7 |
| **Sovereign** | Nothing. This code is the last line — key material, signing, entropy, local persistence, offline/standalone tools | Irreversible loss of funds, keys, or data | 1.0 |
| **Boundary** | This code decides *what crosses into* sovereign territory — assembling the tx to be signed, choosing the destination, composing what the user is asked to approve | Same as Sovereign — the backstop validates the *signature*, not the *intent* | 1.0 |

For **server-side code**, the code owns the data — read it as Sovereign over its own persistence, with the operator's monitoring as the only backstop against silent breakage (hence G-SILENT).

**Zone is per finding, never per repo or app** — one PR routinely spans all three (balance refresh: Backstopped; seed-phrase handling: Sovereign; send-confirmation screen: Boundary). Judge the code path the finding sits on. Unsure between two zones → the more sovereign one.

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

Three 0.0–1.0 numbers per finding; these definitions are the whole specification.

**Rate real-world significance**: the floats measure how much the problem matters to real users and operators in practice — not how wrong the code looks or what could theoretically happen. A minor problem stays minor however the code reads.

### System scale

Rate the whole deployed project — production network, user base, operator fleet — never just the component the finding sits in. First read the project profile ([references/system-rating.md](references/system-rating.md) § Project profile), then open `impact_description` with the **incident headline**: who in production notices what, how often, in concrete units — e.g. *"One of ~400 mainnet validators processes blocks ~2 s late; network unaffected; requires ≥ 1/3 Byzantine voting power."*

What "the system" is depends on the project type (profile `Project type`; mixed repos — judge the finding's code path):

| Type | System | Scale unit | Local-view trap |
|---|---|---|---|
| Network / node | the whole network | nodes, voting power, network liveness/safety | one node's fault read as a network fault |
| GUI app | the user base | share of users reaching the flow × how often | frustration rated cosmetic — friction on a frequent flow (confusing state, lost input, recurring scary errors, lag) erodes trust and drives users away: `impact ≥ 0.4`, not "brief confusion" |
| SDK / library | every consuming app | consumers using the API in typical use | "only a library" — a bad default, footgun, or misleading error repeats in every consumer; developer frustration costs adoption like user frustration costs users |
| Server service | its clients and owned data | requests, tenants, records | a single request's error vs. a hot-path failure for all |
| Tooling / CLI | its operators | operators, frequency of use | a failure with a quick workaround rated as an outage |

One user's irreversible loss stays Sovereign whatever the share of users.

- **Local harm ≠ system harm**: where redundancy, replication, or consensus absorbs the failure (one node, worker, or replica), `impact` is what the system loses, not what the component loses.
- **Dominance**: a precondition outside the project's threat model, or one that already grants a strictly worse outcome than the finding (≥ 1/3 Byzantine power already breaks BFT liveness), caps `likelihood` at `0.1` — state the dominating capability. Still reported.
- **Conjunction**: list independent preconditions, adversarial or not; `likelihood` sits at or below the least likely one, and lower when several are each unlikely.
- **Attacker economics**: an attack costing more than any plausible gain, while a cheaper route to a worse outcome exists, is pathological (`~0.1`).

Dominance and attacker economics lower floats only under the evidence rule below; with no profile, never assume a threat model.

Coordinators re-rate every finding this way before merge classification (§ Rating pass in the reference).

### `likelihood` — how likely is this hit?

Probability that a real user or attacker reaches this defect under zone-realistic usage. Include attacker pressure where an attacker exists; include plausible human error.

| Value | Meaning |
|---|---|
| `1.0` | On the happy path — anyone doing the normal thing hits it |
| `~0.7` | Common, workflow-plausible behavior (impatient re-click, back button, offline moment) |
| `~0.4` | Edge case, unusual sequence, unlucky timing |
| `~0.1` | Pathological only — requires deliberate, unrealistic effort |

**Non-adversarial findings** (correctness, concurrency, robustness — no attacker in the story): don't improvise a threat agent; place them by operational reality, three **conjunctive** factors — the most limiting one sets the ceiling:

- **Execution frequency** — per-request hot path near `1.0`; occasional background job mid; one-time admin migration near the bottom
- **Precondition probability** — ordinary input high; unusual config/rare input mid; concurrent callers that structurally cannot exist bottom
- **Triggering actor** — any user or untrusted automation high; internal automation mid; deliberate trusted-operator action low

🔴 **Evidence rule** — a low rung on any factor MUST cite evidence: the reviewer's own execution-path trace (`review-changes` execution-paths contract), an evidenced Context Digest claim (`review-pr` § Context Digest), a project-profile claim, or an explicit human statement. **Unknown is not benign**: with no evidence, score generically. This axis lowers a score only on evidence, never suppresses a finding — adjusted floats, still reported.

### `impact` — how bad is the worst plausible outcome?

Capped by the backstop zone (§1). Blast radius folds in here — a defect reaching every user is worse than one reaching a rare code path.

| Value | Meaning |
|---|---|
| `1.0` | Irreversible loss of funds, keys, or data |
| `~0.7` | Recoverable loss, security degradation, or an unrecoverable-stuck user |
| `~0.4` | Task fails, scary or confusing UX, restart fixes it |
| `~0.1` | Cosmetic, or brief confusion the user resolves alone |
| `0.0` | No defect exists — informational only (see below) |

**Informational floor.** A finding that reports no defect — praise, a verified-clean pass, a RESOLVED comment — uses `likelihood = 0.0, impact = 0.0`, `relevance = 0.0` → INFO, the only band meaning "no action required". Exact zeros, never a hedge like `0.05` (no defect means genuinely zero, and hedges drift across documents); a low `relevance` cannot sink a finding into INFO — it is not in the mean.

### `relevance` — does it fit what this PR set out to do?

Drives `merge_class` and report ordering. **Not** part of the severity math.

| Value | Meaning |
|---|---|
| `1.0` | The very thing this PR set out to do, or a defect its diff introduces |
| `~0.5` | Pre-existing, but the diff worsens, newly exposes, or relies on it |
| `~0.1` | Pre-existing and untouched by the change, even in a file the diff edits |
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

`relevance` is deliberately excluded: a pre-existing catastrophe is still a catastrophe; averaging in PR-fit used to launder it down to MEDIUM.

Producers emit `likelihood`/`impact`/`relevance`; the coordinator (or the validation pass (`review-changes` § Reports and Validation) when a producer omits them) writes `overall_severity` and integer `severity`. The floats are the **single source of truth** — producers MUST NOT hand-type a severity label anywhere; a parallel label drifts and is wrong by construction.

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
- In doubt between two levels: take the higher in Sovereign/Boundary zones or when the incident headline is unknown; otherwise take the lower — inflated bands bury the findings that matter
- Severity never reflects effort to fix — a one-line fix can be CRITICAL
- UX impact is a real severity input: a scary error dialog on the happy path is `likelihood = 1.0, impact ≈ 0.4` → HIGH, and it trips G-UI-TEXT

## 5. Merge Classification

`merge_class` enum: `blocking | non_blocking | out_of_scope_follow_up | disputed`, plus `intent_basis` (the gate ID and evidence, or the exact requirement; always present for `blocking`). Schema shape: `report-format`.

**Coordinator-owned** — fan-out producers never set it. Assigned during consolidation (`review-changes` § Decide) or inline by coordinator-run producers (review-pr Pass C, check-pr-comments, review-dependency — each runs as the coordinator with no separate consolidation pass).

**PR scope is narrow**: the PR's intent, defects its diff introduces, worsens, newly exposes, or relies on, and its own tests and docs. Anything else is out of scope regardless of severity or proximity, and review fixes never widen the PR beyond it.

**Proportionate to the PR's problem**: what a PR must fix scales with how important the problem it solves is (`references/merge-classification.md` § Rating the PR's problem); a minor PR is one whose problem bands LOW. Below the gates, a finding whose fix outweighs a minor PR's own value — a pre-existing defect the diff worsens or exposes, or a LOW the diff introduces — is deferred; MEDIUM+ defects the diff introduces are always fixed.

**Before assigning any `merge_class`, read `references/merge-classification.md`** — establishing PR intent, the ordered decision tree, pre-existing findings, and the external-reviewer field map. Two rules bind even at a glance:

- 🔴 A pre-existing finding tripping G-FUNDS, G-SECRET, G-CRYPTO, or G-DATA is never silently deferred — surface it to the human explicitly.
- 🔴 `out_of_scope_follow_up` means "not in this PR": never fixed here, never filed automatically, always listed by name with a proposed disposition (separate PR, issue, or drop) for the user to decide.
