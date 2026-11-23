# System-Scale Rating — Reference

Detail behind `severity` § 3 System scale. Producers rate from inside the diff, where a component-local failure looks large; this reference rates at the scale of the whole deployed project.

## Project profile

The project's own facts the floats are measured against. Sources, both optional; the repo file wins on conflict:

1. `.claudius/project-profile.md` in the repository root (works in CI, where MemCan is unavailable). In a PR review read it from the base ref (`git show <BASE_REF>:.claudius/project-profile.md`) — a PR must not lower its own findings' ratings; a profile change is reviewed like any other diff.
2. MemCan memories with metadata `type: project-profile`, scoped to the repo short name: `search(query="project profile threat model scale", project="<repo>")`.

Fields, each a short claim with its source (doc link, maintainer statement, measured number):

```
Project type: <network/node | GUI app | SDK/library | server service | tooling/CLI — `severity` § 3 System scale; mixed repos: one `<path> → <type>` line each (internal modules take their owning app's type; dev, CI, and agent tooling handling only test assets: `<path> → tooling/CLI, internal, not shipped`)>
System & scale: <what runs in production and how much — e.g. "mainnet: ~400 validators, BFT consensus">
Threat model: <assumptions the design relies on — e.g. "< 1/3 Byzantine voting power", "partially synchronous network"; state each actor in or out: remote peer, hostile network data, same-user local process, other local user or physical access, supply chain (CI, release)>
Critical assets: <ranked, most important first — e.g. consensus safety > liveness > single-node performance > tooling>
Accepted risks: <scenarios maintainers decided not to defend against, each with the surface it applies to and the reason>
Anchors: <a few issues/findings with the maintainers' outcome — band, `declined`, or `merged over` — e.g. "#812 HIGH: chain halt on malformed vote extension"; "#930 declined: crash on a crafted local file the user created">
```

Start the file with one line any reviewer can follow without this skill: `Reviewers: rate harm against Critical assets; a precondition outside Threat model or under an Accepted risks line (on the surface it names) is low-likelihood and trips no blocker gate, still reported.`

Profile claims are human statements: they satisfy the `severity` § 3 evidence rule. **Every report summary opens with `Profile: <repo file @base | MemCan | none>`; none → rate generically**; never invent profile claims. To bootstrap one, draft the fields from the repo's README, docs, and specs, mark every claim lacking a source `unconfirmed`, and ask the user to confirm before saving.

## Rating pass

Runs in `review-changes` § Decide, after findings exist and before merge classification; skills rating inline (`check-pr-comments` reports, `triage`) apply `severity` § 3 System scale directly. The rater reads the finding text and the inputs below, never the producer's working, so the finder's investment in a finding does not leak into its rating.

Inputs: the keys to rate — findings surviving duplicate resolution and INTENTIONAL downgrades, as decided by the coordinator — each with its full text (`title`, `location`, `description`, `impact_description`, `recommendation` — from `intermediate.json` `raw_findings`, not the clipped digest; a merged cluster's merged text instead), project profile, anchors (§ Anchors), calibration examples (§ Calibration memory). Rate only those keys: `intermediate.json` predates merging, and an update for a merged-away key fails finalization.

Per finding:

1. **Headline** — make sure `impact_description` opens with the incident headline (`severity` § 3 System scale); write it when missing.
2. **Preconditions** — list them; apply dominance, conjunction, and attacker economics (`severity` § 3 System scale).
3. **Compare** (MEDIUM and above) — name the anchor it outranks and the one that outranks it. A finding rated above an anchor the maintainers would plainly fix first is overrated; lower the floats until the order holds.
   Any band: a `declined` or `merged over` anchor the finding resembles is guidance, not a binding outcome — weigh it, and name any path or harm the anchor lacked.
4. **Counter-argument** (HIGH and above) — write the strongest one-line case that the finding barely matters at project scale. Lower the floats only when that case rests on evidence (`severity` § 3 evidence rule); an unevidenced case leaves the band as it is.
5. **Record** — per changed finding: new floats, and `impact_description` opening with the headline plus a one-line rating reason; the coordinator applies them per `review-changes` consolidation § Decide step 3 (`finding_updates`, or a merged cluster's `updates`).

The rating pass may raise a finding too: a component-local bug can be system-wide (shared library, every node runs the same code path).

## Anchors

The rater's reference points, in order of preference:

1. Profile `Anchors`.
2. Open issues: `gh issue list --repo <owner/repo> --state open --limit 30 --json number,title,labels` — one bounded call per rating pass; use only those whose labels state a severity or priority.
3. Calibration examples (§ Calibration memory).

No anchors available (CI without `gh`, empty backlog) → skip step 3 of the rating pass and say so.

## Calibration memory

Each human correction of a rating or of a blocking label is a calibration example — the project's actual priorities, captured where they are expressed. Save one per **reason class**, not per finding: when a decision states a reason, or two decisions share one, save or update a single memory (MemCan `add_memory`, scoped to the repo short name, metadata `type: severity-calibration`; skip when MemCan is unavailable). Start it with the literal `severity calibration:` — recall matches on it:

```
severity calibration: <class in one line>. <n> findings (<refs>) rated <band | "blocking" by <producer>>; maintainer <declined | merged over | fixed | raised>: "<reason, quoted>".
```

Sources: any recorded maintainer decision on a finding or review comment, whichever skill or coordinator relayed it. A decline with no reason and no sibling is not saved. A class reaching three refs is proposed to the user as a profile `Accepted risks` or `Anchors` line; never added without confirmation. Raters recall the closest examples first: `search(query="severity calibration <component or topic>", project="<repo>")`, at most five.
