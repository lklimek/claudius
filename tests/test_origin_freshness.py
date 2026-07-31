"""Tests for scripts/origin_freshness.py — the SessionStart staleness probe.

Two things carry the weight here. The headline scenario — a feature branch in
sync with its OWN upstream while the base branch moved underneath it — is the
one that silently costs a merge-time conflict, so it is covered both as a
scripted-fake unit test and as a real local-repo integration test; a mock
contract alone cannot prove the argv is right. And the fail-open paths, which
must every one of them yield empty stdout and exit 0, because that is what rots
unnoticed.

No test touches a network remote: git is injected, and the integration tests
clone over a local file path.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "origin_freshness.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import origin_freshness as of  # noqa: E402

# ---------------------------------------------------------------------------
# Scripted git double
# ---------------------------------------------------------------------------


def _kind(args: list[str]) -> str:
    """Collapse a git argv to the response key it should be answered from."""
    cmd = args[0]
    if cmd == "symbolic-ref":
        return "head" if args[-1] == "HEAD" else "remote-head"
    if cmd == "config":
        return "config.remote" if args[-1].endswith(".remote") else "config.merge"
    if cmd == "rev-parse":
        return f"rev-parse:{args[-1].rsplit('/', 1)[-1]}"
    if cmd in ("rev-list", "log", "diff"):
        return f"{cmd}:{args[-1].rsplit('..', 1)[-1].rsplit('/', 1)[-1]}"
    return cmd


class FakeGit:
    """Answers git calls from a keyed response table; records every call."""

    def __init__(self, **responses: object) -> None:
        self.responses = responses
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str], timeout: float) -> str | None:
        self.calls.append(args)
        return self.responses[_kind(args)]  # type: ignore[return-value]

    def argv(self, command: str) -> list[list[str]]:
        return [call for call in self.calls if call[0] == command]


# The default is the scenario that motivates the whole probe: a feature branch
# current with its own upstream, sitting on a base that has moved three ahead.
HAPPY = {
    "head": "feature\n",
    "config.remote": "origin\n",
    "config.merge": "refs/heads/feature\n",
    "remote": "origin\nupstream\n",
    "remote-head": "refs/remotes/origin/main\n",
    "rev-parse:main": "",
    "rev-parse:master": "",
    "fetch": "",
    "rev-list:feature": "0\n",
    "rev-list:main": "3\n",
    "log:feature": "",
    "diff:feature": "",
    "log:main": "a1b2c3d fix: one\nb2c3d4e feat: two\nc3d4e5f docs: three\n",
    "diff:main": "scripts/thing.py\ndocs/thing.md\n",
}


def fake(**overrides: object) -> FakeGit:
    """Happy-path git double with selected responses overridden."""
    return FakeGit(**{**HAPPY, **overrides})


def run_main(git: FakeGit, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = of.main(run=git)
    return code, capsys.readouterr().out


def context_of(out: str) -> str:
    payload = json.loads(out)["hookSpecificOutput"]
    assert payload["hookEventName"] == "SessionStart"
    return payload["additionalContext"]


# ---------------------------------------------------------------------------
# The headline case: base moved, own upstream current
# ---------------------------------------------------------------------------


def test_base_moved_while_own_upstream_is_current(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out = run_main(fake(), capsys)
    assert code == 0
    context = context_of(out)
    assert "## Base branch has moved" in context
    assert "`feature` is 3 commits behind `origin/main`" in context
    assert "## Branch upstream has moved" not in context
    assert "a1b2c3d fix: one" in context
    assert "scripts/thing.py" in context
    assert "git log -p HEAD..origin/main" in context


def test_report_sections_for_the_headline_case() -> None:
    report = of.freshness_report(fake())
    assert report == {
        "branch": "feature",
        "sections": [
            {
                "kind": "base",
                "ref": "origin/main",
                "behind": 3,
                "commits": HAPPY["log:main"].splitlines(),
                "paths": ["scripts/thing.py", "docs/thing.md"],
                "hidden_paths": 0,
            }
        ],
    }


def test_both_refs_travel_in_one_fetch() -> None:
    git = fake()
    of.freshness_report(git)
    assert git.argv("fetch") == [
        [
            "fetch",
            "--quiet",
            "--no-tags",
            "--",
            "origin",
            "+refs/heads/feature:refs/remotes/origin/feature",
            "+refs/heads/main:refs/remotes/origin/main",
        ]
    ]


def test_both_moved_reports_base_first(capsys: pytest.CaptureFixture[str]) -> None:
    _, out = run_main(fake(**{"rev-list:feature": "2\n"}), capsys)
    context = context_of(out)
    assert context.index("## Base branch has moved") < context.index(
        "## Branch upstream has moved"
    )
    assert "2 commits behind `origin/feature` — someone else pushed" in context


def test_upstream_only_when_base_is_current(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, out = run_main(
        fake(**{"rev-list:main": "0\n", "rev-list:feature": "1\n"}), capsys
    )
    context = context_of(out)
    assert "## Base branch has moved" not in context
    assert "`feature` is 1 commit behind `origin/feature`" in context


# ---------------------------------------------------------------------------
# Base-branch resolution — offline, fail-open
# ---------------------------------------------------------------------------


def test_base_falls_back_to_main_when_remote_head_is_absent() -> None:
    git = fake(**{"remote-head": None, "rev-parse:main": "deadbee\n"})
    report = of.freshness_report(git)
    assert report is not None
    assert [section["ref"] for section in report["sections"]] == ["origin/main"]


def test_base_falls_back_to_master() -> None:
    git = fake(
        **{
            "remote-head": None,
            "rev-parse:main": None,
            "rev-parse:master": "deadbee\n",
            "rev-list:master": "4\n",
            "log:master": "aaaaaaa old: one\n",
            "diff:master": "a.txt\n",
        }
    )
    report = of.freshness_report(git)
    assert report is not None
    assert [section["ref"] for section in report["sections"]] == ["origin/master"]


def test_unresolvable_base_still_reports_the_upstream(
    capsys: pytest.CaptureFixture[str],
) -> None:
    git = fake(
        **{
            "remote-head": None,
            "rev-parse:main": None,
            "rev-parse:master": None,
            "rev-list:feature": "2\n",
            "log:feature": "a1b2c3d fix: pushed by someone else\n",
            "diff:feature": "scripts/thing.py\n",
        }
    )
    code, out = run_main(git, capsys)
    assert code == 0
    context = context_of(out)
    assert "## Base branch has moved" not in context
    assert "`feature` is 2 commits behind `origin/feature`" in context
    # Only the upstream ref is fetchable — no refspec for a base we could not name.
    assert git.argv("fetch") == [
        [
            "fetch",
            "--quiet",
            "--no-tags",
            "--",
            "origin",
            "+refs/heads/feature:refs/remotes/origin/feature",
        ]
    ]


def test_never_shells_out_to_a_forge_cli() -> None:
    git = fake()
    of.freshness_report(git)
    assert all(call[0] != "gh" for call in git.calls)


# ---------------------------------------------------------------------------
# Dedupe: the current branch IS the base
# ---------------------------------------------------------------------------


def test_current_branch_is_base_emits_one_section(
    capsys: pytest.CaptureFixture[str],
) -> None:
    git = fake(**{"config.merge": "refs/heads/main\n", "head": "main\n"})
    code, out = run_main(git, capsys)
    assert code == 0
    context = context_of(out)
    assert context.count("`main` is 3 commits behind `origin/main`") == 1
    assert "## Branch upstream has moved" not in context
    assert git.argv("fetch") == [
        [
            "fetch",
            "--quiet",
            "--no-tags",
            "--",
            "origin",
            "+refs/heads/main:refs/remotes/origin/main",
        ]
    ]


def test_nested_branch_name_keeps_its_slashes() -> None:
    git = fake(
        **{
            "config.merge": "refs/heads/release/7.x\n",
            "rev-list:7.x": "1\n",
            "log:7.x": "a1b2c3d fix: one\n",
            "diff:7.x": "a.txt\n",
        }
    )
    report = of.freshness_report(git)
    assert report is not None
    assert {section["ref"] for section in report["sections"]} == {
        "origin/main",
        "origin/release/7.x",
    }


# ---------------------------------------------------------------------------
# Fail-open paths — the ones that rot silently
# ---------------------------------------------------------------------------

FAIL_OPEN_CASES = {
    "detached_head_or_not_a_repo": {"head": None},
    "no_upstream_remote_configured": {"config.remote": None},
    "no_upstream_merge_ref_configured": {"config.merge": None},
    "remote_listing_fails": {"remote": None},
    "remote_not_registered": {"remote": "upstream\n"},
    "local_only_upstream": {"config.remote": ".\n"},
    "fetch_fails_offline_or_auth": {"fetch": None},
    "rev_list_fails": {"rev-list:main": None, "rev-list:feature": None},
    "rev_list_output_unparseable": {"rev-list:main": "lots\n", "rev-list:feature": ""},
    "everything_current": {},
    "negative_count": {"rev-list:main": "-2\n"},
}
FAIL_OPEN_CASES["everything_current"] = {"rev-list:main": "0\n"}


@pytest.mark.parametrize("case", sorted(FAIL_OPEN_CASES), ids=sorted(FAIL_OPEN_CASES))
def test_fail_open_is_silent(case: str, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run_main(fake(**FAIL_OPEN_CASES[case]), capsys)
    assert (code, out) == (0, "")


def test_no_network_attempt_when_remote_missing() -> None:
    git = fake(remote="upstream\n")
    assert of.freshness_report(git) is None
    assert git.argv("fetch") == []


def test_unexpected_exception_is_swallowed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def exploding(args: list[str], timeout: float) -> str | None:
        raise RuntimeError("boom")

    assert of.main(run=exploding) == 0
    assert capsys.readouterr().out == ""


def test_no_command_writes_to_the_checkout() -> None:
    git = fake(**{"rev-list:feature": "2\n"})
    of.freshness_report(git)
    forbidden = {"checkout", "switch", "merge", "rebase", "reset", "pull", "branch"}
    assert [call for call in git.calls if call[0] in forbidden] == []


# ---------------------------------------------------------------------------
# Runner: process-level failures and the shared deadline
# ---------------------------------------------------------------------------


class _Completed:
    def __init__(self, returncode: int, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout


def _runner(monkeypatch: pytest.MonkeyPatch, outcome: object) -> of.DeadlineGitRunner:
    def fake_run(*args: object, **kwargs: object) -> object:
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(of.subprocess, "run", fake_run)
    return of.DeadlineGitRunner()


@pytest.mark.parametrize(
    "outcome",
    [
        FileNotFoundError("git"),
        PermissionError("git"),
        subprocess.TimeoutExpired("git", 5.0),
        subprocess.SubprocessError("weird"),
        _Completed(128),
    ],
    ids=["git_absent", "not_executable", "timeout", "subprocess_error", "nonzero_exit"],
)
def test_runner_returns_none_on_failure(
    monkeypatch: pytest.MonkeyPatch, outcome: object
) -> None:
    assert _runner(monkeypatch, outcome)(["status"], 1.0) is None


def test_runner_returns_stdout_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _runner(monkeypatch, _Completed(0, "ok\n"))(["status"], 1.0) == "ok\n"


def test_runner_stops_once_budget_is_spent(monkeypatch: pytest.MonkeyPatch) -> None:
    ticks = iter([0.0, of.TOTAL_BUDGET_SEC + 1.0])
    monkeypatch.setattr(of.subprocess, "run", lambda *a, **k: _Completed(0, "nope"))
    runner = of.DeadlineGitRunner(clock=lambda: next(ticks))
    assert runner(["status"], 1.0) is None


def test_runner_clamps_timeout_to_remaining_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, float] = {}

    def fake_run(*args: object, **kwargs: object) -> object:
        seen["timeout"] = kwargs["timeout"]  # type: ignore[assignment]
        return _Completed(0, "")

    monkeypatch.setattr(of.subprocess, "run", fake_run)
    ticks = iter([0.0, of.TOTAL_BUDGET_SEC - 1.0])
    of.DeadlineGitRunner(clock=lambda: next(ticks))(["fetch"], of.FETCH_TIMEOUT_SEC)
    assert seen["timeout"] == pytest.approx(1.0)


def test_runner_env_blocks_interactive_credential_prompts() -> None:
    env = of.git_env({"PATH": "/usr/bin", "GIT_ASKPASS": "/usr/bin/gui-askpass"})
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_ASKPASS"] == "echo"
    assert env["SSH_ASKPASS"] == "echo"
    assert "BatchMode=yes" in env["GIT_SSH_COMMAND"]


def test_runner_env_keeps_user_ssh_command() -> None:
    env = of.git_env({"GIT_SSH_COMMAND": "ssh -i /key"})
    assert env["GIT_SSH_COMMAND"] == "ssh -i /key"


# ---------------------------------------------------------------------------
# Output shaping
# ---------------------------------------------------------------------------


def test_commit_list_is_capped_and_remainder_reported(
    capsys: pytest.CaptureFixture[str],
) -> None:
    log = "".join(f"c{i:07d} commit {i}\n" for i in range(of.MAX_COMMITS))
    _, out = run_main(fake(**{"rev-list:main": "42\n", "log:main": log}), capsys)
    context = context_of(out)
    assert context.count("\n- c") == of.MAX_COMMITS
    assert f"{42 - of.MAX_COMMITS} more" in context


def test_path_list_is_capped_and_remainder_reported(
    capsys: pytest.CaptureFixture[str],
) -> None:
    diff = "".join(f"src/f{i}.py\n" for i in range(of.MAX_PATHS + 7))
    _, out = run_main(fake(**{"diff:main": diff}), capsys)
    context = context_of(out)
    assert context.count("\n- src/f") == of.MAX_PATHS
    assert "7 more files" in context


def test_missing_detail_output_still_reports_the_divergence(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A failing log/diff downgrades detail; it must not suppress the warning."""
    _, out = run_main(fake(**{"log:main": None, "diff:main": None}), capsys)
    assert "3 commits behind `origin/main`" in context_of(out)


def test_singular_commit_wording(capsys: pytest.CaptureFixture[str]) -> None:
    _, out = run_main(fake(**{"rev-list:main": "1\n"}), capsys)
    assert "1 commit behind" in context_of(out)


# ---------------------------------------------------------------------------
# Wiring: the declared hook timeout must outlive the internal budget
# ---------------------------------------------------------------------------


def test_hook_is_wired_with_a_timeout_above_the_internal_budget() -> None:
    hooks = json.loads((REPO_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    entries = [
        hook
        for group in hooks["hooks"]["SessionStart"]
        for hook in group["hooks"]
        if "origin_freshness.py" in hook["command"]
    ]
    assert len(entries) == 1, "probe must be wired exactly once into SessionStart"
    assert entries[0]["timeout"] > of.TOTAL_BUDGET_SEC


# ---------------------------------------------------------------------------
# Integration — local file remote only, no network
# ---------------------------------------------------------------------------

GIT_ISOLATION = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "T",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "T",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "init.defaultBranch=main", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, **GIT_ISOLATION},
    ).stdout


def probe(cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={**os.environ, **GIT_ISOLATION},
    )


@pytest.fixture
def repos(tmp_path: Path) -> tuple[Path, Path]:
    """An origin on `main` plus a clone on a `feature` branch tracking origin/feature.

    This is the shape that matters: the feature branch has its own upstream, so an
    own-upstream-only check reports "fresh" no matter what happens to main.
    """
    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init", "-q")
    (origin / "a.txt").write_text("one\n", encoding="utf-8")
    git(origin, "add", "a.txt")
    git(origin, "commit", "-qm", "one")

    git(tmp_path, "clone", "-q", str(origin), "work")
    work = tmp_path / "work"
    git(work, "checkout", "-q", "-b", "feature")
    (work / "f.txt").write_text("feature\n", encoding="utf-8")
    git(work, "add", "f.txt")
    git(work, "commit", "-qm", "feature work")
    git(work, "push", "-q", "-u", "origin", "feature")

    # Guard the fixture against the coincidence it exists to avoid: if the clone's
    # tracking ref were the base, (a) and (b) would collapse into one comparison
    # and every base-drift test below would pass against an own-upstream-only
    # implementation. Assert the branch tracks ITSELF.
    assert git(work, "config", "--get", "branch.feature.merge").strip() == (
        "refs/heads/feature"
    )
    return origin, work


def advance_main(origin: Path) -> None:
    (origin / "b.txt").write_text("two\n", encoding="utf-8")
    git(origin, "add", "b.txt")
    git(origin, "commit", "-qm", "base moves on")


def test_integration_silent_when_nothing_moved(repos: tuple[Path, Path]) -> None:
    result = probe(repos[1])
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_integration_detects_base_drift_on_a_current_feature_branch(
    repos: tuple[Path, Path],
) -> None:
    """The #85-under-#86 shape: own upstream untouched, base one commit ahead."""
    origin, work = repos
    advance_main(origin)

    before = git(work, "rev-parse", "HEAD", "feature", "refs/remotes/origin/feature")

    result = probe(work)
    assert result.returncode == 0
    context = context_of(result.stdout)
    assert "## Base branch has moved" in context
    assert "is 1 commit behind `origin/main`" in context
    assert "base moves on" in context
    assert "b.txt" in context
    assert "## Branch upstream has moved" not in context

    assert (
        git(work, "rev-parse", "HEAD", "feature", "refs/remotes/origin/feature")
        == before
    )
    assert git(work, "status", "--porcelain") == ""
    assert not (work / "b.txt").exists()


def test_integration_detects_base_drift_without_remote_head(
    repos: tuple[Path, Path],
) -> None:
    origin, work = repos
    git(work, "symbolic-ref", "-d", "refs/remotes/origin/HEAD")
    advance_main(origin)
    context = context_of(probe(work).stdout)
    assert "is 1 commit behind `origin/main`" in context


def test_integration_silent_outside_a_repository(tmp_path: Path) -> None:
    result = probe(tmp_path)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_integration_silent_on_detached_head(repos: tuple[Path, Path]) -> None:
    origin, work = repos
    advance_main(origin)
    git(work, "checkout", "-q", "--detach", "HEAD")
    result = probe(work)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_integration_silent_when_remote_is_gone(repos: tuple[Path, Path]) -> None:
    origin, work = repos
    advance_main(origin)
    git(work, "remote", "remove", "origin")
    result = probe(work)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_integration_silent_when_remote_is_unreachable(
    repos: tuple[Path, Path], tmp_path: Path
) -> None:
    origin, work = repos
    advance_main(origin)
    git(work, "remote", "set-url", "origin", str(tmp_path / "vanished"))
    result = probe(work)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
