---
name: security-best-practices
description: "This skill should be used when reviewing or writing code that handles authentication, cryptography, untrusted input, secrets, deserialization, or API endpoints, and before a security review of Rust, Go, Python, or TypeScript code. It routes to language-specific pitfall references that go beyond general OWASP knowledge and fixes the citation vocabulary for security findings."
allowed-tools: Read, Grep
---

# Security Best Practices

OWASP Top 10, ASVS 5.0, the OWASP API and LLM Top 10, and the OWASP Cheat Sheet Series are assumed knowledge — apply them without a local checklist. This skill holds only what is not general knowledge.

## Language pitfalls

Before reviewing or writing security-relevant code in one of these languages, read the matching file in full — concrete advisories and library-specific traps, not textbook items:

- Rust → `${CLAUDE_SKILL_DIR}/references/rust-security-patterns.md`
- Go → `${CLAUDE_SKILL_DIR}/references/go-security-patterns.md`
- Python → `${CLAUDE_SKILL_DIR}/references/python-security-patterns.md`
- TypeScript / JavaScript → `${CLAUDE_SKILL_DIR}/references/typescript-security-patterns.md`

## Citing

- Tag each finding with its OWASP Top 10:2025 category: A01 Broken Access Control (includes SSRF) · A02 Security Misconfiguration · A03 Software Supply Chain Failures · A04 Cryptographic Failures · A05 Injection · A06 Insecure Design · A07 Authentication Failures · A08 Software or Data Integrity Failures · A09 Security Logging and Alerting Failures · A10 Mishandling of Exceptional Conditions. The 2021 edition numbers differently — name the edition.
- Add the CWE ID and, where one applies, the ASVS 5.0 requirement ID (`V<chapter>.<section>.<requirement>`). Look an ID up (`search_standards` MCP if available, else the published standard) or omit it — never cite one from memory alone.
