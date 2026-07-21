# Issue Body Template

Canonical issue-body skeleton for `git-and-github` §Issues — same plain-language-first
shape as [`pr-body-template.md`](pr-body-template.md). Drop whole sections or sub-sections
that don't apply, keep the section order. `TL;DR` / `User story` / `Scenario` are
plain-language and user-facing; `Detailed discussion` is technical, for implementors and
AI agents.

For a bug report, `Scenario` is the reproduction: `Base flow` gets there, `Actual behavior`
is the bug, `Expected behavior` is the fix target. For a feature request with nothing to
reproduce, drop `Scenario` and describe the gap in `User story` / `Detailed discussion`
instead.

```markdown
**TL;DR:** <one plain-language sentence describing the problem or request>

## User story
As a **<role>**, I want to <what-to-do>, to achieve <user-goal>.

## Scenario
### Base flow
<the ordinary steps that lead to this situation — plain narrative>

### Actual behavior
<what happens today — the bug, gap, or missing capability>

### Expected behavior
<what should happen, or become possible, once this is addressed>

## Detailed discussion
<technical notes, proposed approach, logs, links>

### Attribution

### Prior work
<links to possibly related or similar PRs/issues, each with a one-sentence summary of how it relates to this one; omit if none>
```
