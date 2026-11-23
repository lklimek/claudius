---
name: pr-fleet
description: "This skill should be used when driving one or several open GitHub PRs through the push, bot-review and fix loop until each waits only for the maintainer — e.g. \"babysit these PRs\", \"drive the PR fleet\", \"get these PRs merge-ready\", \"handle the bot reviews\". It sets when the internal whole-PR review runs, which findings justify a push, when a round closes, when to take in the base, and when to ask the maintainer to merge."
---

# PR Fleet

Coordinator rules for driving PRs until only maintainer actions remain. A delta over [git-and-github](../git-and-github/SKILL.md) (push gates, § Readiness, user-only actions, [stacked PRs](../git-and-github/references/stacked-prs.md)), [check-pr-comments](../check-pr-comments/SKILL.md), [review-changes](../review-changes/SKILL.md), and [grand-admiral](../grand-admiral/SKILL.md) — load them. Bot names, status feeds, gate commands, and waiters are repository-specific: take them from project or user instructions.

## Loop

Per PR: one worktree and one owning implementer, reused for every round (`grand-admiral` § Agent Reuse); heads and decisions go to the tracking file (`delegate` § Tracking).

1. **Push**: the implementer commits; the coordinator audits the commit and pushes per `git-and-github` § Before Every Push.
2. **Internal review** of that push (§ Internal review).
3. **Bot round and CI** on the pushed head (§ Round close).
4. **Decisions**: `check-pr-comments` for every bot and human comment; the maintainer decides each ID. Record each decision with its ID and thread links — later rounds and review briefs reuse it.
5. **Fix round**: implement the decided fixes, push once (§ Fix pushes), back to 2.

Done = only maintainer actions remain: bots finished on the current head, its CI green, every comment decided and executed.

## Internal review

After every later push carrying production code (the push creating a PR gets its creation review, `git-and-github` § Creating a PR) — marking ready, taking over a PR, every fix push including fixes of internal findings and CI fixes — start one independent `review-changes` basic review of the **whole PR** (`<base>...<head>`, never the delta since the last push), in parallel with the push; the push never waits for it.

- One PR per review. Reviewer per `review-changes` § 2 and `delegate`, never the PR's author.
- Pass the maintainer's earlier per-ID decisions on the PR as the review's prior decisions (`review-changes` § 1).
- A coordinator audit never replaces this review. Tests-only, docs-only, empty, and tree-identical merge pushes, and a head the creation review already covered, skip it; the next review covers them.

## Fix pushes

Every push costs a full bot round.

- Internal findings ready **before** the bot starts reviewing the head: push at once only for `blocking` findings and MEDIUM+ defects the PR introduced (`severity` § 5); the rest rides the next push that answers a bot round.
- Bot already reviewing: hold per `git-and-github` § Before Every Push, then fold internal and bot findings into one fix round and one push.

## Round close

A round closes only with the CI result on the pushed head. Red CI is a finding of that round; pending required checks are not green; skipped checks count as absent and block nothing.

## Base updates

Push to take in the base only when the PR conflicts with it or CI is red because of it, together with the round's fixes when there are any; other pushes take it in through the `git-and-github` § Before Every Push gate. Never update a PR that waits only for the maintainer — a new head resets bot reviews, CI, and approvals. Native stack layers follow [stacked-prs.md](../git-and-github/references/stacked-prs.md).

## Merge question

After the third bot round on a PR, ask the maintainer once: merge now or one more round. List the open items with their merge class (`severity` § 5) and a recommendation — merge and decline the rest, or one more round because of a named blocker.

## Maintainer-only actions

`git-and-github` § Safety Rules (8) owns the list. Dismiss a bot's `CHANGES_REQUESTED` only on the maintainer's request for that PR; no standing authorisation exists, even once every blocker is decided.
