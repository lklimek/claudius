# Host-Supplied Data

A host that fetched the PR itself supplies `pr-data/` and wants the report only. Paths are relative to `pr-data/`; an absent file is empty.

| File | Content |
|---|---|
| `manifest.json` | `{repo: "<owner>/<repo>", pr, head, pr_author, maintainers: [login], bots: [login]}` |
| `threads.json` | `gh-list-review-threads.sh` output |
| `review-comments.json` | `gh-fetch-review-comments.sh` output (all inline comments and replies) |
| `reviews.json` | `gh-fetch-reviews.sh` output |
| `comments.json` | `gh pr view --json comments` `.comments` |
| `conventions/` | the base branch's convention files: the project's rules |
| `ids.json` | `{next_id: <int>, items: [{id, key, quote?, decision?}]}` — earlier rows; `key` is the thread node ID, `review:<id>:<k>` or `comment:<id>:<k>`; `decision` is a maintainer's standing decision (a `recorded_decision` kind) |
| `scope.json` | `{threads: [<node ID>], sources: [<review or comment URL>]}` — what to assess |

- Skip steps 1–2. The checkout is the code judged: `metadata.commit` = `git rev-parse HEAD`. `gh` stays available for pre-analysis searches.
- Step 3 assesses only `scope.json`: its threads, and the itemised requests of its sources. Everything else is context.
- Only `maintainers` decide (a commenter may still withdraw their own request); the PR author's statements are claims to verify. Accounts in `bots` are bots.
- IDs: a row for the same comment or request as an `ids.json` item reuses its ID and honours its `decision`; new rows take `CMT-<next_id>` upward, zero-padded to three digits.
- No step 4 table or questions, no steps 7–8, nothing posted or changed.
- Steps 5–6 with `metadata.input_mode: "host_supplied"`, written where the host says; validation must pass.
