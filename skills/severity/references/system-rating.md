# System-Scale Rating — Reference

Detail behind `severity` § 3 System scale. Producers rate from inside the diff, where a component-local failure looks large; this reference rates at the scale of the whole deployed project.

## Project profile

The project's own facts the floats are measured against. Sources, both optional; the repo file wins on conflict:

1. `.claudius/project-profile.md` in the repository root (works in CI, where MemCan is unavailable).
2. MemCan memories with metadata `type: project-profile`, scoped to the repo short name: `search(query="project profile threat model scale", project="<repo>")`.

Fields, each a short claim with its source (doc link, maintainer statement, measured number):

```
System & scale: <what runs in production and how much — e.g. "mainnet: ~400 validators, BFT consensus">
Threat model: <assumptions the design relies on — e.g. "< 1/3 Byzantine voting power", "partially synchronous network">
Critical assets: <ranked, most important first — e.g. consensus safety > liveness > single-node performance > tooling>
Accepted risks: <scenarios maintainers decided not to defend against, with reason>
Anchors: <a few issues/findings with an agreed severity, for comparison — e.g. "#812 HIGH: chain halt on malformed vote extension">
```

Profile claims are human statements: they satisfy the `severity` § 3 evidence rule. **No profile → rate generically and state "no project profile" in the summary**; never invent profile claims. To bootstrap one, draft the fields from the repo's README, docs, and specs, mark every claim lacking a source `unconfirmed`, and ask the user to confirm before saving.

## Rating pass

Runs after findings exist and before merge classification — `review-changes` § Decide, `check-pr-comments` reports, `triage`. The rater reads finding text and the inputs below, never the producer's reasoning beyond it, so the finder's investment in a finding does not leak into its rating.

Inputs: findings (digest or report), project profile, anchors (§ Anchors), calibration examples (§ Calibration memory).

Per finding:

1. **Headline** — make sure `impact_description` opens with the incident headline (`severity` § 3 System scale); write it when missing.
2. **Preconditions** — list them; apply dominance, conjunction, and attacker economics (`severity` § 3 System scale).
3. **Compare** (MEDIUM and above) — name the anchor it outranks and the one that outranks it. A finding rated above an anchor the maintainers would plainly fix first is overrated; lower the floats until the order holds.
4. **Counter-argument** (HIGH and above) — write the strongest one-line case that the finding barely matters at project scale. Keep the band only if evidence rebuts it; otherwise lower the floats.
5. **Record** — float changes with a one-line reason; the coordinator applies them (`finding_updates` in review-changes).

The rating pass may raise a finding too: a component-local bug can be system-wide (shared library, every node runs the same code path).

## Anchors

The rater's reference points, in order of preference:

1. Profile `Anchors`.
2. Open issues carrying severity or priority labels: `gh issue list --repo <owner/repo> --state open --limit 30 --json number,title,labels` — one bounded call per rating pass.
3. Calibration examples (§ Calibration memory).

No anchors available (CI without `gh`, empty backlog) → skip step 3 of the rating pass and say so.

## Calibration memory

Each human correction of a rating is a calibration example — the project's actual priorities, captured where they are expressed. Save one per correction (MemCan `add_memory`, scoped to the repo short name, metadata `type: severity-calibration`; skip when MemCan is unavailable):

```
<repo> severity calibration: <component> — <finding in one line>. Rated <band> by review; maintainer judged it <overrated|underrated> (<target band if given>): <reason>.
```

Sources: `triage-findings` decisions with `severity_feedback`; a user's rejection or re-rating of a finding or PR comment as unimportant (or more important) at project scale in `check-pr-comments`, `triage`, or chat. Raters recall the closest examples first: `search(query="severity calibration <component or topic>", project="<repo>")`, at most five.
