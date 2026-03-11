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
