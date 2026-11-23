# Host-Supplied Data

A host that fetched the PR itself supplies `pr-data/` and wants the report only. Paths are relative to `pr-data/`; absent context files are empty. `manifest.json` and `scope.json` are required.

The source-selection, identity and deduplication rules below override step 3 and the worker brief.

| File | Content |
|---|---|
| `manifest.json` | `{repo: "<owner>/<repo>", pr, head, base_ref, base_sha, title, body, pr_author, maintainers: [login], bots: [login]}`; optional `delegates: [login]` (default `[]`), trusted to relay maintainer decisions |
| `threads.json` | `gh-list-review-threads.sh` output |
| `review-comments.json` | JSON array, never JSON Lines: `gh-fetch-review-comments.sh` output; inline comments/replies include `created_at`, `commit_id`, `pull_request_review_id` |
| `reviews.json` | JSON array: `gh-fetch-reviews.sh` output, including `html_url`, `commit_id`, `submitted_at` |
| `comments.json` | `gh pr view --json comments` `.comments` |
| `conventions/` | the base branch's convention files: the project's rules |
| `ids.json` | `{next_id: <int>, items: [{id, key, source_kind?, quote?, decision?}]}` — earlier rows; `key` is the thread node ID, `review:<id>:<k>` or `comment:<id>:<k>`; `<k>` is the item's 1-based index. `source_kind` defaults from the key to `inline`, `review_body`, `pr_comment`; `decision` is a maintainer's standing decision (a `recorded_decision` kind) |
| `scope.json` | `{threads: [<node ID>], sources: [<review or comment URL>]}` — what to assess |

- Skip steps 1–2. The checkout is the code judged: `metadata.commit` = `git rev-parse HEAD`. `gh` stays available for pre-analysis searches.
- The PR's stated goal is `title`/`body` (necessity gate); pre-existing means present at `base_sha`, whose branch is `base_ref`. Use these supplied facts without a `gh pr view` fetch.
- Read `pr-data` through filters for `scope.json`: extract its threads/sources and their reply chains with `jq` or Python; never print whole comment/review files. Read other items only as needed context. Do not read the schema or validator source; use the loaded report contract and compact example below, then fix validator diagnostics.
- Step 3 assesses only `scope.json`: its threads, and every itemised request of its sources, including bot round bodies and reply comments that restate threads, decisions or earlier rounds. Keep these as `review_body`/`pr_comment`, even if settled; `status` is only text that asks nothing. A reused ID keeps its `source_kind`; never switch an offered item to `status` or `reply`.
- `source_quote`: copied verbatim from the supplied (cleaned) text, at least 12 characters (the whole text when shorter), distinct within its source; `comment_url` equals the source URL in `scope.json`.
- Only `maintainers`' decisions and explicit maintainer relays by `delegates` bind the disposition (a commenter may withdraw their own request); others' decisions remain claims to verify. Accounts in `bots` are bots; bot status does not cancel delegate authority.
- Record every reply-chain decision with its real posting author, link and quote as `recorded_decision`, maintainer or not. Keep the controlling decision on the item; preserve additional decisions in separate `reply` rows with their own IDs, never by changing the item's kind. For a trusted relay (e.g. "Per maintainer decision"), `by` is the posting delegate; set `on_behalf_of` only when the quote names the actual maintainer. Never infer an unnamed author or treat an ordinary bot claim as a trusted relay.
- Every in-scope source maps to a row. Merge duplicate threads or items within one source as usual. A duplicate in another in-scope review/comment source keeps its own ID, kind, URL, quote and proposal, with `merged_into` pointing directly to the canonical row; omit its `assessment` and `finding_id`. Add its URL to the canonical row's `merged_urls` (and thread ID to `merged_thread_ids` when applicable). Never swallow a scope source into `merged_urls` alone or score its concern twice.
- IDs: reuse the matching `ids.json` ID; a reused body-item quote contains, or is contained in, its `ids.json` quote; a merged row takes the ID of its own `thread_id`/source. New rows take `CMT-<next_id>` upward, zero-padded to three digits.
- For reused IDs, propose the standing `decision` unless the code at its lines changed or `recorded_decision` contradicts it. Preserve its kind/target in `proposed_decision` (`deferred` → `todo`, `withdrawn` → `reject`); never fabricate `recorded_decision` provenance.
- `proposed_reply` is the single reply for `proposed_decision` only, without the attribution footer or "post only after the fix lands" marker.
- No step 4 table or questions, no steps 7–8, nothing posted or changed.
- Steps 5–6 with `metadata.input_mode: "host_supplied"`, written where the host says; validation must pass. When `ids.json` exists, append `--ids <pr-data>/ids.json` to step 6 to check reused kinds.

Compact host row (inside `comment_assessments`; ordinary envelope and scored findings follow the loaded report contract):

```json
{"id":"CMT-002","reviewer":"alice","source_kind":"review_body","comment_url":"https://github.com/example/repo/pull/42#pullrequestreview-102","source_quote":"Please avoid duplicate balance requests.","description":"Avoid duplicate balance requests.","assessment":"already_fixed","reasoning":"The current refresh reuses the cached request.","proposed_action":"Resolve: verified in abc1234.","proposed_decision":{"kind":"resolve","fixed_in":"abc1234"},"proposed_reply":"The refresh reuses the cached request."}
```
