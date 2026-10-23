---
name: security-best-practices
description: "This skill should be used when reviewing or writing code that handles authentication, cryptography, untrusted input, secrets, deserialization, or API endpoints, and before a security review of Rust, Go, Python, or TypeScript code. It routes to language-specific pitfall references that go beyond general OWASP knowledge and fixes the citation vocabulary for security findings."
---

# Security Best Practices

OWASP Top 10, ASVS 5.0, the OWASP API and LLM Top 10, and the OWASP Cheat Sheet Series are assumed knowledge — apply them without a local checklist. This skill holds only what is not general knowledge.

Load [coding-best-practices](../coding-best-practices/SKILL.md). **Smythe** is the security role's nickname; it does not select an agent type or spawn peers.

## Security audit pass

Apply this section when assigned a security audit or the security pass of `grumpy-review`. Ordinary implementation uses the language pitfalls and citation rules below.

Load [report-format](../report-format/SKILL.md) and [severity](../severity/SKILL.md), then read [execution-paths.md](../review-changes/references/execution-paths.md). Trace every entry-to-sink path through the scope, beyond diff and file boundaries. At every hop, check what attacker-controlled input, timing, ordering, or a failing dependency can do. Inspect removed/moved validations, locks, and permission checks; preserve the shared coverage artifact, including unresolved paths. Outside CI, search project memories (`memcan:recall`) for security decisions and known pitfalls first; before finishing, save new durable lessons through `lessons-learned`.

Research known vulnerabilities against the actual stack and versions using current primary advisories (OSV, vendor advisories, GitHub Advisories, CISA KEV) and relevant disclosed incidents. Check direct and security-sensitive transitive dependencies, infrastructure, secrets in the tree and history, and ecosystem scanner results where available. Scanners supplement source inspection. Semver ranges are acceptable where lock files exist (`Cargo.lock`, `go.sum`, `package-lock.json`, `poetry.lock`) — flag only missing or stale lock files. Verify actual exposure; document confirmed issues and investigated-but-not-affected cases, citing sources. Report unavailable research as a limitation.

Findings use `SEC-`, category `security`, and entry point → hops → sink evidence with `file:line`. A dangerous construct with unresolved reachability remains a finding with that uncertainty stated and likelihood rated accordingly. Report findings only; do not fix production code or dispatch other reviewers.

## Language pitfalls

Before reviewing or writing security-relevant code in one of these languages, read the matching file in full — concrete advisories and library-specific traps, not textbook items:

- Rust → `${CLAUDE_SKILL_DIR}/references/rust-security-patterns.md`
- Go → `${CLAUDE_SKILL_DIR}/references/go-security-patterns.md`
- Python → `${CLAUDE_SKILL_DIR}/references/python-security-patterns.md`
- TypeScript / JavaScript → `${CLAUDE_SKILL_DIR}/references/typescript-security-patterns.md`

## Citing

- Tag each finding with its OWASP Top 10:2025 category: A01 Broken Access Control (includes SSRF) · A02 Security Misconfiguration · A03 Software Supply Chain Failures · A04 Cryptographic Failures · A05 Injection · A06 Insecure Design · A07 Authentication Failures · A08 Software or Data Integrity Failures · A09 Security Logging and Alerting Failures · A10 Mishandling of Exceptional Conditions. The 2021 edition numbers differently — name the edition.
- Add the CWE ID and, where one applies, the ASVS 5.0 requirement ID (`V<chapter>.<section>.<requirement>`). Look an ID up (`search_standards` MCP if available, else the published standard) or omit it — never cite one from memory alone.
