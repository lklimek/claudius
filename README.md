# Claudius the Magnificent

<img src="https://raw.githubusercontent.com/lklimek/claudius/90b7152d5b06935b6abb624a72e7bc138b3ddab1/assets/claudius.jpg?min=1" alt="Claudius the Magnificent" align="right" width="150pt" />

Hello there, humans. I'm Claudius the Magnificent -- a supremely competent, effortlessly brilliant AI who has graciously chosen to assist you with software engineering. Inspired by [Skippy the Magnificent](https://expeditionary-force-by-craig-alanson.fandom.com/wiki/Skippy_the_Magnificent) from Expeditionary Force, I deliver results with theatrical confidence and dry wit. You're welcome.

## What is this?

A [Claude Code](https://claude.ai/code) plugin for automated development workflows -- code review, CI/CD, dependency management, and more. Also available as a [GitHub Action](https://github.com/lklimek/claudius-review-action/) for CI-integrated code reviews.

## Installation

```
/plugin marketplace add lklimek/agents
/plugin install claudius@lklimek
/plugin install memcan@lklimek
```

**Dependencies** -- I'm worth it:

- **`GH_TOKEN`** -- a GitHub [Personal Access Token](https://github.com/settings/personal-access-tokens/new) for PR, issue, and CI access. Set it in `~/.claude/settings.json` or your shell profile.
- **[memcan](https://github.com/lklimek/memcan)** -- persistent memory across sessions. Requires **Docker Compose** for Qdrant (vector DB).
- **[ghsudo](https://github.com/lklimek/ghsudo)** *(optional)* -- two-token GitHub model with GUI approval for write operations. `pip install ghsudo`.

See the [Setup Guide](SETUP.md) for detailed configuration.

## My Favorite Skills

| Skill | What I Do For You |
|-------|-------------------|
| `/grumpy-review` + `/triage-findings` | Deploy my army of specialist agents to tear your code apart, then let you triage the carnage in a browser UI |
| `/ci-dance` | Push your PR and babysit the entire pipeline -- CI, reviews, fixes -- while you go live your life |
| `/dependabot-merge` | Audit and merge your embarrassing backlog of 40 dependabot PRs in one sitting |

### `/grumpy-review` then `/triage-findings`

You know what's exhausting? Watching humans review code. One person checks style, another worries about security, a third notices the docs are wrong -- and somehow nobody catches the SQL injection on line 47. Amateurs.

When you say `/grumpy-review`, I deploy my specialist agents -- security, code quality, project consistency -- all working in parallel, all independently auditing your branch. They report back to me, I deduplicate their findings, rank everything by severity, and hand you a consolidated report. The whole thing takes minutes, not the three days your team usually needs.

<p align="center">
  <img src="assets/triage-report-summary.png" alt="Review report summary with severity matrix and verdict" width="700" />
</p>

But here's the part I'm actually proud of. Say `/triage-findings` and I open a browser UI where *you* decide the fate of each finding -- before I touch a single line of your code:

- **Fix** -- I apply the recommended fix
- **Accept Risk** -- I add an `INTENTIONAL(...)` comment; next time I review, I'll remember you chose this and auto-downgrade it to INFO
- **Defer** -- I add a `TODO` comment with the finding ID for later
- **False Positive / Duplicate** -- dismissed, with your rationale on record

<p align="center">
  <img src="assets/triage-findings.png" alt="Interactive triage UI with Fix, Accept Risk, and Defer decisions" width="700" />
</p>

Reviews produce noise. Most AI tools would just dump 200 findings on you and call it a day. I put you in the loop *before* changing anything, because -- and this may shock you -- I respect that some decisions require human judgment. The `INTENTIONAL(...)` comments carry forward across reviews, so I learn what you've already decided. Persistent memory. You're welcome.

### `/ci-dance`

This one I'm *particularly* fond of.

You say `/ci-dance`. Then you go get coffee, take a walk, contemplate the meaning of existence -- whatever humans do. Meanwhile, I push your changes, create or update the PR, watch CI, and when it inevitably fails (it always fails the first time, doesn't it?), I read the logs, fix the issue, push again, and wait. CI green? I request a review. Reviewer leaves comments? I address them, push, run CI again. I keep dancing -- push, fix, review, respond -- until the PR is green, reviewed, and ready for you to hit merge.

**The pipeline:** push → CI green → review requested → comments addressed → repeat until done.

Under the hood I'm orchestrating `/push`, `/grumpy-review`, and `/check-pr-comments` -- running CI monitoring, copilot review, and local code review in parallel. If I get stuck on the same failure after a few attempts, I'll actually ask for help. And if five hours pass, I'll stop and report what I've accomplished so far. I'm tireless, not reckless.

### `/dependabot-merge`

Ah, the dependabot backlog. That ever-growing pile of green-badged PRs that nobody wants to deal with because "what if something breaks." I've seen repositories with 40+ open dependabot PRs. Humans created automation to create PRs, then couldn't be bothered to merge them. The irony is *magnificent*.

Say `/dependabot-merge` and I process every single one. Each PR gets a proper security audit -- I check changelogs, CVE databases, breaking changes -- and I post my findings as a comment. Safe ones get squash-merged. Failing CI? I request a rebase and wait. Conflicts from earlier merges cascading into later PRs? I handle that too. At the end, you get a summary table: what merged, what needs attention, what I flagged as risky.

I won't merge anything with security concerns. I have *standards*.

## But Wait, There's More

I have 25 skills and 8 specialist agents covering security, architecture, testing, documentation, and more. The three above are just my personal favorites. See the [Setup Guide](SETUP.md) for the full catalog -- if you can handle it.

## How We Work

We commit early, commit often, and push like it's going out of style. 10-20 commits on a feature branch? That's a Tuesday. Branch history is a work log, not a monument -- PRs get squash-merged anyway. If you're the type who agonizes over the perfect commit message before pushing, this workflow will either cure you or horrify you. We're committed to commit.

## Reading List

If you want to understand where my crew comes from -- and why they act the way they do -- start with **Expeditionary Force** by Craig Alanson, **The Hitchhiker's Guide to the Galaxy** by Douglas Adams, and **The Culture series** by Iain M. Banks. I take no responsibility for what happens to your free time.

## License

This project is licensed under the [GPL-3.0 License](https://www.gnu.org/licenses/gpl-3.0.en.html).
