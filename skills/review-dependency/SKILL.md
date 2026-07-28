---
name: review-dependency
description: "This skill should be used when the user asks to \"review a dependency update\", \"audit this dependency bump\", or assess the security of an upgraded or newly added dependency."
agent: claudius
context: fork
allowed-tools: Read, Grep, Glob, WebFetch, WebSearch, Bash(mktemp *), Bash(git diff *), Bash(git log *), Bash(git show *), Bash(git tag *), Bash(git rev-parse *), Bash(git clone --depth=* --config core.hooksPath=/dev/null -- *), Bash(gh api /advisories*), Bash(rm -rf /tmp/claude/*), Bash(govulncheck *), Bash(cargo audit *), Bash(npm audit *), Bash(pip-audit *)
---

# Dependency Security Review

Security-focused review of a dependency update.

**Argument**: `$ARGUMENTS` — dependency name (e.g., `github.com/lib/pq`, `express`, `tokio`), optionally with version range (e.g., `github.com/lib/pq 1.11.1..1.11.2`). If empty, auto-detect from the current branch by diffing the dependency manifest against the main branch.

## 1. Identify the Dependency Change

Detect the ecosystem and locate the manifest:

| Ecosystem | Manifest files |
|---|---|
| Go | `go.mod`, `go.sum` |
| Rust | `Cargo.toml`, `Cargo.lock` |
| Python | `pyproject.toml`, `requirements*.txt`, `Pipfile.lock`, `poetry.lock` |
| Node.js | `package.json`, `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml` |
| Other | Identify automatically |

Diff the manifest against the base branch: package name, old version, new version, and any other dependency changes bundled in the same commit.

## 2. Gather Upstream Intelligence

Run in parallel:

### 2a. Changelog and Diff
- Fetch release notes from the upstream releases/tags page
- Fetch the comparison between old and new versions
- Summarize: what changed, how many commits, which files, nature of changes

### 2b. Clone the Library
Create a session temp dir (if not already created) and clone the new version into it.

```bash
SESSION_DIR=$(mkdir -p /tmp/claude && mktemp -d /tmp/claude/XXXXXX)
```

**Input validation**: before using the package name in any shell command, validate it contains only alphanumerics, hyphens, underscores, dots, forward slashes, and `@`. Reject any input containing shell metacharacters (`;`, `|`, `&`, `$`, `` ` ``, `(`, `)`, `<`, `>`, `!`, `#`, `~`, `{`, `}`).

```bash
git clone --depth=100 --config core.hooksPath=/dev/null -- <upstream-repo-url> "$SESSION_DIR/<package-name>"
```

### 2c. Known Vulnerability Scan

| Source | Method |
|---|---|
| OSV.dev | `POST https://api.osv.dev/v1/query` with package name and ecosystem |
| GitHub Advisory Database | `gh api /advisories?ecosystem=<eco>&affects=<pkg>` |
| NVD | Web search for package CVEs |
| Ecosystem-specific | `govulncheck` (Go), `cargo audit` (Rust), `npm audit` (Node), `pip-audit` (Python) |
| Web search | `<package-name> CVE vulnerability security advisory` |

Check for commonly confused similarly-named packages that may pollute search results.

### 2d. Reconcile the Documented Change Against the Actual Diff

Run after 2a and 2b complete — this cross-checks 2a's claimed changes against 2b's real commit history and diff, which is the first line of defense against a compromised or tampered release (the update itself may not be trustworthy, independent of whether the resulting code has exploitable bugs).

- **Tag/commit integrity**: confirm the tag or version cloned in 2b resolves to the same commit the changelog/release page/registry metadata references (`git rev-parse <tag>`, compare against the release notes' linked commit or the registry's recorded commit hash where available). A moved tag pointing at a different commit than what was publicly reviewed is a known attack pattern.
- **Undocumented files/commits**: list every file and commit in the actual diff (`git log`, `git diff --stat` against the prior version's ref) and flag anything not explained by the changelog or commit messages — especially changes with no corresponding entry at all.
- **Lifecycle/install hooks**: flag any new or modified build/install/publish scripts — npm `preinstall`/`postinstall`/`prepare` in `package.json`, Python `setup.py` custom `cmdclass`/`build_ext` hooks, Makefile install targets, CI/release workflow files. These run with elevated trust and are a common injection point.
- **New network calls or exfiltration paths**: source changes that add outbound requests, especially to domains not previously referenced, or that read environment variables/credentials they didn't read before.
- **Obfuscation**: minified, heavily encoded (base64/hex blobs), or otherwise non-human-reviewable content added to *source* (not generated/vendored build output that was already opaque before this update).
- **Diff shape vs. claimed change type**: a "patch"/bugfix release with an unusually large or broad diff, or changes touching files unrelated to the stated fix, warrants explanation before proceeding.
- **Contributor provenance**: a security-sensitive change landed by a contributor with no prior history in the project, or a maintainer change/handoff around the time of this release, raises the bar for scrutiny.

Anything found here becomes explicit input to step 3 — surface the specific files/commits flagged so the audit reads them directly rather than re-discovering them independently.

## 3. Security Audit of the Library

Spawn a `security-engineer-smythe` agent to review the cloned source at `$SESSION_DIR/<package-name>`.

### Scope
- **Primary**: all changes between old and new version (the diff)
- **Secondary**: full audit of security-critical code paths
- **Any file/commit flagged by step 2d** as undocumented or suspicious — verify it directly, don't take the changelog's silence as evidence of safety

### Audit Checklist

Apply the categories relevant to the library's purpose:

**Network / Protocol libraries** — TLS certificate validation and defaults, protocol message parsing and length validation, authentication mechanisms (password handling, token security), connection string / URL parsing injection, buffer safety and unbounded allocations from network data

**Data access libraries** — Query injection (SQL, NoSQL, LDAP, etc.), input escaping and parameterization, connection security defaults, credential exposure in errors or logs

**HTTP libraries** — SSRF and redirect following, header injection (CRLF), request smuggling, cookie security, response body size limits

**Cryptographic libraries** — Algorithm strength, CSPRNG usage, nonce/IV reuse, side-channel resistance, key management and zeroing

**Serialization libraries** — Deserialization attacks and type confusion, resource exhaustion (recursion bombs, billion laughs), malformed input handling

**All libraries** — Input validation and sanitization, memory safety and resource limits, error handling and information disclosure, concurrency safety (races, deadlocks), file system operations (path traversal, symlink attacks), transitive dependency risk, debug/logging modes that may leak sensitive data

### Output Format
Rate findings: **CRITICAL / HIGH / MEDIUM / LOW / INFO** (see `severity` skill). When emitting v3 report JSON, the coordinator running this skill also assigns `merge_class`/`intent_basis` per `severity` skill § Merge Classification (coordinator-inline classification — DEP- findings have no separate consolidation pass).
Include: file:line references, CWE IDs where applicable, impact, and remediation.

## 4. Vulnerability Research

Spawn an `architect-nagatha` agent in parallel with step 3, to:

- Query all major vulnerability databases from step 2c
- Search the library's issue tracker for security discussions and responsible disclosures
- Identify **unregistered security fixes** — code fixes never assigned CVEs/GHSAs
- Assess security posture: `SECURITY.md` presence, disclosure process, CVE registration discipline, maintainer activity
- Check whether ecosystem vulnerability tooling actually covers this library

## 5. Codebase Impact Assessment

After upstream review completes, assess how the dependency is used in **our** codebase:

- How is the library imported? Direct API use vs transitive/side-effect import?
- Which APIs are called? Any deprecated or known-insecure APIs?
- How are configurations (connection strings, URLs, credentials) constructed? From trusted sources?
- Are errors from this library exposed to end users or external APIs?
- Are security-critical settings (TLS mode, auth method, timeouts) explicitly configured or left to defaults?
- Is there input validation on data passed to this library from untrusted sources?

## 6. Consolidated Report

Present a single report:

### Change Summary
Package, old version, new version, commit count, nature of changes (bug fix / feature / security fix / breaking change).

### Diff Integrity
Whether the actual diff/commit history matches the documented changes (step 2d): tag/commit integrity result, and every undocumented, hidden, or otherwise suspicious file/commit/hook found — or state plainly that the diff fully matches what's documented. Treat any unresolved finding here as grounds to escalate the overall risk rating regardless of what the code-level audit (step 3) finds, since it calls the trustworthiness of the update itself into question, not just its code quality.

### Known Vulnerabilities
Table of CVEs/advisories found (or "None found"), affected versions, whether the new version is impacted. Note any commonly confused packages.

### Library Audit Findings
Table: Severity | Finding | Location | CWE — grouped by severity, CRITICAL first.

### Codebase Compliance
Table: Recommendation | Status | Action Needed? — for each finding, assess whether our usage is affected.

### Risk Assessment
- Overall rating: **Safe / Low Risk / Medium Risk / High Risk / Do Not Upgrade**
- Key concerns and mitigations
- Flag poor CVE registration discipline (automated scanning may be blind)
- Any unresolved Diff Integrity finding floors the rating at High Risk or worse, even with a clean code audit — an untrustworthy update is disqualifying on its own

### Recommendations
Numbered actionable items for our codebase, plus long-term considerations (e.g., migration to alternatives).

## 7. Cleanup

```bash
rm -rf "$SESSION_DIR"
```
