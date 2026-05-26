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

**CRITICAL** — Must fix before merge. Exploitable vulnerability, data loss, correctness bug
causing wrong results, or system breakage. Production incident if deployed.
*CVSS equivalent: 9.0-10.0. Examples: RCE, SQL injection, data breach, silent data corruption.*

**HIGH** — Should fix before merge. Significant risk or correctness issue that will likely
cause problems. Workaround may exist but is not acceptable long-term.
*CVSS equivalent: 7.0-8.9. Examples: privilege escalation, race condition causing data loss,
broken authentication, missing input validation on untrusted data.*

**MEDIUM** — Fix before production. Real issue that requires additional factors to manifest,
or a design flaw that increases future risk. Acceptable to merge with a tracked follow-up.
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

## Scale

**5 (CRITICAL) > 4 (HIGH) > 3 (MEDIUM) > 2 (LOW) > 1 (INFO)**

## Rules

- Everything that may require action must be **LOW or higher**
- **INFO** is exclusively for praise and context — never for suggestions or improvements
- When in doubt between two levels, choose the higher one
- Severity reflects **impact and likelihood**, not effort to fix
- A trivial one-line fix can still be CRITICAL if the impact is severe
- UX/DX impact is a severity factor — a broken user journey or confusing developer experience can be HIGH even if the code compiles and passes tests

## OWASP Risk Rating normalization

Schema v3 decomposes severity along three 0.0–1.0 dimensions per the [OWASP Risk Rating Methodology](https://owasp.org/www-community/OWASP_Risk_Rating_Methodology). The coordinator computes `overall_severity = (risk + impact + scope) / 3` and derives the integer `severity` from the band table below — never ask the LLM to do the arithmetic.

### `risk` (OWASP Likelihood, normalized)

Sum the OWASP Likelihood factor scores (each rated 0–9 per the methodology) and divide by 9.0 to land in 0.0–1.0:

- **Threat agent**: Skill level, Motive, Opportunity, Size
- **Vulnerability**: Ease of discovery, Ease of exploit, Awareness, Intrusion detection

```
risk = average(factor_scores) / 9.0
```

### `impact` (OWASP Impact, normalized)

Same recipe over OWASP Impact factors:

- **Technical**: Loss of confidentiality, integrity, availability, accountability
- **Business**: Financial damage, Reputation damage, Non-compliance, Privacy violation

```
impact = average(factor_scores) / 9.0
```

For pure code-quality findings without a security angle, score the technical factors only and treat business factors as 0 — the average still lands in a sensible band.

### `scope` (PR relevance)

| Value | Meaning |
|-------|---------|
| `1.0` | Directly in the PR diff — introduced or modified by this change |
| `0.5` | Indirectly affected — pre-existing code touched or reachable via the diff |
| `0.0` | Unrelated to the PR — pre-existing issue outside the diff |

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
