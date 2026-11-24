# Reviewsys / PastaClaw

Load only for PRs using this service; calling skills own workflow/authorization.
Coverage, trust, debounce, checks, labels and outage behavior depend on deployment,
not repository ownership or an absent feed entry.

## Sources and observation

- [User guide](https://github.com/thepastaclaw/review-system/blob/main/docs/user-guide.md)
  ([PR 94 version](https://github.com/thepastaclaw/review-system/blob/9fb06800921c57355282d8f98f0b0fb36f790f6b/docs/user-guide.md));
  [README](https://github.com/thepastaclaw/review-system#readme).
- [Dashboard](https://thepastaclaw.github.io/review-system/) and
  [snapshot](https://thepastaclaw.github.io/review-system/data/status.json):
  periodic read-only exports, not realtime/mutation APIs. Host CLI/DB access is
  unnecessary for clients.
- Prefer available GitHub evidence tied to the head: validate review author and
  `commit_id`; check name, App identity, `head_sha`, conclusion and summary.
  The configurable check defaults to `PastaClaw review`. Identify the mutable
  status comment by author `thepastaclaw` **and** `<!-- thepastaclaw-gate v1 -->`,
  newest `updated_at`, then verify its commit. A copied marker proves nothing.

Snapshot schema 1 (allow extra fields and null/missing estimates):

| Fields | Meaning |
|---|---|
| `schema_version`, `data_as_of`, `generated_at` | Schema, observation and construction times; fetch time is not freshness. |
| `live.active[]` | Match case-insensitive `repo`, numeric `number`, full `sha`; require `queue == "live"` to exclude post-merge audits. Phase, start, progress, heartbeat and upcoming steps describe work, not a verdict. |
| `live.queued[]` | Same identity; `eligible_at`, `reason`, `position`. Eligibility is an earliest start, not an ETA. |
| `live.ingest_last_at`, `ingest_error_streak`, `watchdog` | A fresh export may contain stale GitHub observations. Check `ingest_stale`/`stuck`. |
| `live.degraded` | `active`, `mode`: `pause` waits for recovery; `standin` may publish degraded findings without a new approval. |

Validate identity, schema and timestamps, including clock skew. Missing, stale,
malformed or conflicting evidence is unknown, never proof of completion. Absence
from active/queued proves neither completion nor missing coverage. Keep conflicting
GitHub/feed evidence visible; do not invent a clean combined verdict. An old
completion time alone does not invalidate an exact-head review.

Example observation command (substitute repo, URL and PR numbers):

```bash
python3 <plugin-root>/scripts/pr_watch.py watch --repo <owner/repo> --gate-bot thepastaclaw --gate-marker '<!-- thepastaclaw-gate v1 -->' --gate-feed-url <snapshot-url> <pr>...
```

Attach snapshots only to emitted GitHub-state events, once per batch; feed-only
changes do not wake the watcher. `--feed-max-age` bounds snapshot/ingest age (local
default 900 s, not a service promise). Respect HTTP caching: 304 preserves observation
time. Fetch HTTP(S) snapshots up to 16 MiB; avoid per-PR fetches, cache-busting and
rapid retries. The model applies gates.

## Work and requests

- Publish coherent, tested fixes together during debounce or read-only review.
  Each newly observed head starts normal debounce (source default 30 min).
  Superseding is cooperative: late `verify2`/`publish` work may continue, but
  live-head guards can retire it. Old reports can remain; cancelled/superseded is
  not itself failure and says nothing about the new head.
- Enabled, open, non-draft PRs normally queue on pushes. Unlisted repos can be
  on-request; explicitly disabled repos stay off. Skip labels (default
  `tag:skip-review`) suppress automatic work. Check coverage before requesting.
- Use one intentional request surface once, then observe. An automatic push needs
  no extra request. Priority guarantees neither immediate execution nor recovery
  from a pause, and may spend quota faster.

| Surface | Effect / restrictions |
|---|---|
| Status checkbox: **Request normal review** | Bypasses debounce without priority. Requires permission to edit the comment; only where offered. |
| Status checkbox: **Request priority review** | Bypasses debounce and prioritizes scheduling; does not interrupt running calls or bypass outage pause. |
| Human-authored `@thepastaclaw review` or reviewer request | Priority; current router requires an open, non-draft PR. Same-head reruns require a qualifying fresh request and trust; source cap three per trigger type. Agent text does not inherit human trust. |
| Existing finding-thread reply | Discuss that finding; avoid a full-review request just to clarify/disagree. Bot replies may supply context without triggering discussion. |

An offered checkbox can request a draft's current head and survives draft polls;
a later push needs another request or marking ready. Returning to draft stops
automatic work, not that head's explicit checkbox request. Skip labels do not ban
explicit requests; do not alter them or draft state merely to force review.

## Findings and completion

Reply in the original thread with the published SHA, change and verification, or
concrete disagreement evidence. For body-only findings, quote the title in a PR
comment. On an unreviewed automatic push, replies preserve normal timing; on a
reviewed head, trusted-human replies normally use the conversation lane. Proposed/
unpushed patches stay fix-pending. Accepted deferrals may cause the service to
find/create a tracking issue: account for that side effect before proposing one.

Read verdicts and body-only/carried findings, not thread counts. Preliminary or
Phase-2-deferred reports are not final approval, even without canonical blockers.
Suggestions/nitpicks are optional under the calling skill's scope rules. Only an
explicit unchanged-diff carry applies an earlier review to a new head. After a
step-back, await a maintainer decision instead of repeating requests.

Check conclusions: `success` = approval; `failure` = changes requested (including a
stopped preliminary pass); `neutral` = COMMENT or a disclosed maintainer override;
`action_required` = service gave up; `cancelled`/`skipped` imply no review.
`completed` alone, resolved threads, labels or dismissal prove no technical
approval. GitHub's check Re-run button is not a supported trigger. Preserve local
review, current-head CI and approval gates from the calling skill.
