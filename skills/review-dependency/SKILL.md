---
name: review-dependency
description: Use for security review of dependency updates — bumps, upgrades, or new dependencies.
agent: claudius
context: fork
allowed-tools: Read, Grep, Glob, WebFetch, WebSearch, Bash(mktemp *), Bash(git diff *), Bash(git clone --depth=* --config core.hooksPath=/dev/null -- *), Bash(gh api /advisories*), Bash(rm -rf /tmp/claude/*), Bash(govulncheck *), Bash(cargo audit *), Bash(npm audit *), Bash(pip-audit *)
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

## 3. Security Audit of the Library

Spawn a `security-engineer-smythe` agent to review the cloned source at `$SESSION_DIR/<package-name>`.

### Scope
- **Primary**: all changes between old and new version (the diff)
- **Secondary**: full audit of security-critical code paths

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

### Recommendations
Numbered actionable items for our codebase, plus long-term considerations (e.g., migration to alternatives).

## 7. Cleanup

```bash
rm -rf "$SESSION_DIR"
```
