---
name: review-dependency
description: "This skill should be used when the user asks to \"review a dependency update\", \"audit this dependency bump\", or assess the security of an upgraded or newly added dependency. It reconciles the documented change against the real upstream diff, audits the changed source, checks our usage, and returns one risk-rated report."
agent: claudius
context: fork
allowed-tools: Read, Grep, Glob, WebFetch, WebSearch, Agent, Bash(mktemp *), Bash(git diff *), Bash(git log *), Bash(git show *), Bash(git tag *), Bash(git rev-parse *), Bash(git clone --depth=100 --config core.hooksPath=/dev/null -- *), Bash(gh api /advisories*), Bash(rm -rf /tmp/claude/dep-review-*), Bash(govulncheck *), Bash(cargo audit *), Bash(npm audit *), Bash(pip-audit *)
---

# Dependency Security Review

Security-focused review of a dependency update. Produces and returns a report — **it never posts anywhere** (`allowed-tools` has no GitHub write tool). Say "returned" or "written to `<path>`", never "posted"/"published"; the invoking skill or coordinator publishes it (e.g. `dependabot-merge` § 5) and verifies the publish happened.

**Argument**: `$ARGUMENTS` — dependency name (e.g., `github.com/lib/pq`, `express`, `tokio`), optionally with a version range (`github.com/lib/pq 1.11.1..1.11.2`). If empty, auto-detect by diffing the dependency manifests and lockfiles against the base branch.

## 1. Identify the Change

From the manifest/lockfile diff: package, old version, new version, and any other dependency changes bundled in the same commit.

## 2. Gather Upstream Intelligence

**Input validation first**: before the package name reaches any shell command, confirm it contains only alphanumerics, `-`, `_`, `.`, `/`, and `@`; reject anything else.

In parallel:

- **Changelog and comparison** — release notes plus the old..new comparison: what changed, how many commits, which files.
- **Clone** the new version into a session dir:

  ```bash
  SESSION_DIR=$(mkdir -p /tmp/claude && mktemp -d /tmp/claude/dep-review-XXXXXX)
  git clone --depth=100 --config core.hooksPath=/dev/null -- <upstream-repo-url> "$SESSION_DIR/<package-name>"
  ```

- **Known vulnerabilities** — OSV.dev, `gh api /advisories?ecosystem=<eco>&affects=<pkg>`, the ecosystem scanner (`govulncheck`, `cargo audit`, `npm audit`, `pip-audit`), and a web search. Watch for similarly-named packages polluting results.

### 2d. Reconcile the Documented Change Against the Actual Diff

After the changelog and clone are in hand. The update itself may be untrustworthy independent of code quality — this is the first line of defense against a compromised or tampered release.

- **Tag/commit integrity**: the cloned tag resolves (`git rev-parse <tag>`) to the commit the release page or registry metadata references. A moved tag is a known attack pattern.
- **Everything in the real diff is accounted for**: list every file and commit (`git log`, `git diff --stat` against the prior version's ref) and flag whatever the changelog or commit messages do not explain — plus the usual supply-chain signals (install/build/publish hooks, new outbound calls or credential reads, obfuscated or encoded source (not vendored/generated output already opaque before the update), a diff too broad for the claimed release type, security-sensitive changes from a new contributor or around a maintainer handoff).

Every flagged file/commit is explicit input to step 3.

## 3. Security Audit

Spawn ONE `security-engineer-smythe` agent on the cloned source at `$SESSION_DIR/<package-name>` — no second agent for vulnerability research; Smythe owns it.

- **Primary scope**: the old..new diff, and every file/commit step 2d flagged — verify directly; the changelog's silence is not evidence of safety.
- **Secondary**: security-critical code paths relevant to the library's purpose.
- **Research**: beyond registered advisories, the issue tracker for **unregistered security fixes** (fixes never assigned a CVE/GHSA), the project's security posture (`SECURITY.md`, disclosure and CVE-registration discipline, maintainer activity), and whether ecosystem vulnerability tooling covers this library at all.

Findings carry `likelihood`/`impact`/`relevance` floats per `severity` skill § 3 — never a hand-typed label — with file:line, CWE, impact, remediation. This skill runs coordinator-inline (`agent: claudius`, `context: fork`, no consolidation pass), so like review-pr Pass C and check-pr-comments it assigns `merge_class`/`intent_basis` directly (`severity` § Merge Classification) in the v4 report JSON it emits (`claudius:report-format`).

## 4. Codebase Impact

How **our** code uses the dependency: direct API use vs transitive import; which APIs (any deprecated or known-insecure); where configuration, URLs, and credentials passed to it come from; whether its errors reach end users; whether security-critical settings (TLS mode, auth, timeouts) are explicit or defaulted; whether untrusted input is validated before it reaches the library.

## 5. Consolidated Report

One report with these sections:

- **Change Summary** — package, versions, commit count, nature of change.
- **Diff Integrity** — tag/commit integrity result and every undocumented or suspicious file/commit/hook from step 2d, or a plain statement that the diff fully matches what is documented.
- **Known Vulnerabilities** — CVEs/advisories (or "None found"), affected versions, whether the new version is impacted; commonly confused packages.
- **Library Audit Findings** — Severity | Finding | Location | CWE, CRITICAL first.
- **Codebase Compliance** — Recommendation | Status | Action Needed?, per finding.
- **Risk Assessment** — overall rating **Safe / Low Risk / Medium Risk / High Risk / Do Not Upgrade**, key concerns and mitigations. Flag poor CVE-registration discipline (automated scanning may be blind). **Any unresolved Diff Integrity finding floors the rating at High Risk**, even with a clean code audit — an untrustworthy update is disqualifying on its own.
- **Recommendations** — numbered actions for our codebase, plus long-term considerations.

## 6. Cleanup

```bash
rm -rf "$SESSION_DIR"
```
