"""Contract tests for the Python agent watchdog."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "agent-watchdog.py"
SPEC = importlib.util.spec_from_file_location("agent_watchdog", SCRIPT)
assert SPEC and SPEC.loader
watchdog = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = watchdog
SPEC.loader.exec_module(watchdog)


def touch(path: Path, epoch: int) -> None:
    """Create a file and set a deterministic mtime."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    os.utime(path, (epoch, epoch))


def write_json(path: Path, value: Any, epoch: int | None = None) -> None:
    """Write an isolated JSON fixture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    if epoch is not None:
        os.utime(path, (epoch, epoch))


def workspace(tmp_path: Path, name: str = "repo") -> Path:
    """Create a monitored non-Git workspace."""
    result = tmp_path / name
    result.mkdir(parents=True)
    return result


def codex_store(
    tmp_path: Path,
    ws: Path,
    jobs: list[dict[str, Any]],
    *,
    version: int = 1,
    state_epoch: int = 100,
) -> tuple[Path, dict[str, str]]:
    """Create a Codex Companion state directory without using real plugin data."""
    env = {
        "CLAUDE_PLUGIN_DATA": str(tmp_path / "plugin-data"),
        "HOME": str(tmp_path / "home"),
    }
    info = watchdog.resolve_workspace(ws, env=env)
    info.state_dir.mkdir(parents=True)
    summaries = []
    for index, job in enumerate(jobs):
        record = {
            "id": job.get("id", f"job-{index}"),
            "sessionId": job.get("sessionId", "session-full"),
            "workspaceRoot": job.get("workspaceRoot", str(ws)),
            "status": job.get("status", "running"),
            "phase": job.get("phase", "running"),
            "createdAt": job.get("createdAt", index),
            "pid": job.get("pid"),
        }
        record.update(job)
        job_path = info.state_dir / "jobs" / f"{record['id']}.json"
        write_json(job_path, record, job.get("epoch", 100))
        if "log_epoch" in job:
            log_path = info.state_dir / "jobs" / f"{record['id']}.log"
            touch(log_path, job["log_epoch"])
            record["logFile"] = str(log_path)
            write_json(job_path, record, job.get("epoch", 100))
        summaries.append(
            {
                "id": record["id"],
                "phase": record["phase"],
                "updatedAt": job.get("updatedAt", "1970-01-01T00:01:40Z"),
            }
        )
    write_json(
        info.state_dir / "state.json",
        {"version": version, "jobs": summaries},
        state_epoch,
    )
    return info.state_dir, env


def record(
    *,
    job_id: str = "job-1",
    workspace_key: str = "repo-abc123",
    status: str = "active",
    phase: str = "running",
    activity: int | None = 100,
    runtime: str = "unknown",
    created_at: float = 0,
    error: str | None = None,
) -> Any:
    """Build a normalized Source D record."""
    return watchdog.CodexRecord(
        key=f"codex:{workspace_key}:{job_id}",
        job_id=job_id,
        workspace_key=workspace_key,
        workspace_root=Path("/work/repo"),
        status=status,
        phase=phase,
        activity_epoch=activity,
        runtime=runtime,
        created_at=created_at,
        error_message=error,
    )


def test_cx_001_and_002_known_slug_hash_examples() -> None:
    """CX-001/CX-002: known paths match state.mjs exactly."""
    first = watchdog.workspace_key(
        Path("/home/ubuntu/git/claudius"),
        Path("/home/ubuntu/git/claudius"),
    )
    second_path = Path("/data/git-worktrees/home-ubuntu-git-claudius-merge-class")
    second = watchdog.workspace_key(second_path, second_path)
    assert first == "claudius-de2bbc61e069e157"
    assert second == "home-ubuntu-git-claudius-merge-class-3b69306d4d22444f"


def test_cx_003_symlink_slug_before_realpath_hash_after(tmp_path: Path) -> None:
    """CX-003: slug and hash use their specified path variants."""
    actual = workspace(tmp_path, "actual")
    alias = tmp_path / "Alias Repo"
    alias.symlink_to(actual, target_is_directory=True)
    key = watchdog.workspace_key(alias, actual.resolve())
    assert key.startswith("Alias-Repo-")
    assert key.endswith(watchdog.sha256_path(actual.resolve()))


@pytest.mark.parametrize(
    ("root", "prefix"),
    [(Path("/x/---"), "workspace-"), (Path("/x/a b!*c"), "a-b-c-")],
)
def test_cx_004_slug_sanitization(root: Path, prefix: str) -> None:
    """CX-004: special characters, trimming, and fallback match state.mjs."""
    assert watchdog.workspace_key(root, root).startswith(prefix)


def test_cx_005_node_temp_environment_semantics(tmp_path: Path) -> None:
    """CX-005: plugin-data absence uses Node-compatible temp selection."""
    env = {"TMPDIR": str(tmp_path / "node-tmp"), "HOME": str(tmp_path / "home")}
    assert watchdog.codex_state_root(env) == Path(env["TMPDIR"]) / "codex-companion"


def test_cx_006_to_010_scanner_scope(tmp_path: Path) -> None:
    """CX-006..CX-010: direct discovery is workspace- and session-scoped."""
    ws = workspace(tmp_path)
    other = workspace(tmp_path, "other")
    _, env = codex_store(
        tmp_path,
        ws,
        [
            {"id": "ours", "sessionId": "session-full"},
            {"id": "foreign-session", "sessionId": "neighbour"},
        ],
    )
    env["CODEX_COMPANION_SESSION_ID"] = "deliberately-mismatched"
    codex_store(
        tmp_path,
        other,
        [{"id": "foreign-workspace", "sessionId": "session-full"}],
    )
    scanner = watchdog.CodexScanner(env=env, proc=watchdog.NullProcInspector())
    result = scanner.scan([ws], "session-full")
    assert [item.job_id for item in result.records] == ["ours"]  # CX-006/007
    assert "foreign-workspace" not in [item.job_id for item in result.records]  # CX-008
    assert scanner.scan([ws], "").records == []  # CX-009
    assert [item.job_id for item in scanner.scan([ws], "session-full").records] == [
        "ours"
    ]  # CX-010: direct scanner is independent of CLI projection environment

    current_state, current_env = codex_store(
        tmp_path / "missing-root",
        Path.cwd(),
        [{"id": "missing-root", "workspaceRoot": ""}],
    )
    assert current_state.exists()
    assert (
        watchdog.CodexScanner(env=current_env, proc=watchdog.NullProcInspector())
        .scan([Path.cwd()], "session-full")
        .records
        == []
    )


def test_short_codex_session_prefix_must_be_unique(tmp_path: Path) -> None:
    """Ambiguous short sessions disable Source D with one diagnostic."""
    ws = workspace(tmp_path)
    _, env = codex_store(
        tmp_path,
        ws,
        [
            {"id": "one", "sessionId": "session-one"},
            {"id": "two", "sessionId": "session-two"},
        ],
    )
    scanner = watchdog.CodexScanner(env=env, proc=watchdog.NullProcInspector())
    first = scanner.scan([ws], "session-")
    assert first.records == [] and len(first.warnings) == 1
    assert scanner.scan([ws], "session-").warnings == []


def test_cx_011_to_015_active_stall_resume_and_build() -> None:
    """CX-011..CX-015: active silence, hysteresis, edges, and build suppression."""
    builds = False
    machine = watchdog.CodexStateMachine(stall_secs=100, resume_secs=20, gone_polls=2)
    stale = record(activity=100)
    assert (
        machine.evaluate([stale], now=100, build_active=lambda _: builds) == []
    )  # 011
    assert machine.evaluate([record(activity=150)], now=200) == []  # 012
    assert machine.evaluate([stale], now=200) == [
        "CODEX_STALL job=job-1 workspace=repo-abc123 idle=100s "
        "phase=running reason=no-progress"
    ]  # 013
    assert machine.evaluate([stale], now=201) == []
    assert machine.evaluate([record(activity=185)], now=200) == [
        "CODEX_RESUMED job=job-1 workspace=repo-abc123 idle=15s "
        "phase=running reason=progress"
    ]  # 014
    assert machine.evaluate([stale], now=200) != []
    assert machine.evaluate([record(activity=150)], now=200) == []  # hysteresis
    builds = True
    machine = watchdog.CodexStateMachine(stall_secs=100, resume_secs=20, gone_polls=2)
    assert machine.evaluate([stale], now=100) == []
    assert machine.evaluate([stale], now=200, build_active=lambda _: builds) == []
    builds = False
    assert machine.evaluate([stale], now=201, build_active=lambda _: builds)[
        0
    ].startswith("CODEX_STALL ")  # 015


def test_cx_016_shared_state_mtime_not_attributed(tmp_path: Path) -> None:
    """CX-016: a shared state.json mtime cannot refresh multiple active jobs."""
    ws = workspace(tmp_path)
    _, env = codex_store(
        tmp_path,
        ws,
        [
            {"id": "one", "epoch": 100, "updatedAt": None},
            {"id": "two", "epoch": 110, "updatedAt": None},
        ],
        state_epoch=999,
    )
    scanner = watchdog.CodexScanner(env=env, proc=watchdog.NullProcInspector())
    records = scanner.scan([ws], "session-full").records
    assert {item.activity_epoch for item in records} == {100, 110}


def test_cx_017_to_021_runtime_gone_unknown_and_recovery() -> None:
    """CX-017..CX-021: verified death is confirmed; unknown is conservative."""
    machine = watchdog.CodexStateMachine(stall_secs=100, resume_secs=20, gone_polls=2)
    assert machine.evaluate([record(runtime="dead")], now=100) == []
    assert machine.evaluate([record(runtime="dead")], now=200) == [
        "CODEX_GONE job=job-1 workspace=repo-abc123 reason=runtime-gone"
    ]  # CX-018
    assert machine.evaluate([record(activity=200, runtime="alive")], now=201) == [
        "CODEX_RESUMED job=job-1 workspace=repo-abc123 phase=running reason=recovered"
    ]  # CX-021

    unknown = watchdog.CodexStateMachine(stall_secs=100, resume_secs=20, gone_polls=2)
    assert unknown.evaluate([record(runtime="unknown")], now=100) == []
    assert unknown.evaluate([record(runtime="unknown")], now=200)[0].startswith(
        "CODEX_STALL "
    )  # CX-019
    null_pid = watchdog.classify_runtime([], [])
    assert null_pid == "unknown"  # CX-020


def test_cx_022_to_026_terminal_events_are_exact_and_deterministic() -> None:
    """CX-022..CX-026: terminal status wins and reports exactly once."""
    machine = watchdog.CodexStateMachine(stall_secs=100, resume_secs=20, gone_polls=2)
    assert machine.evaluate([record(status="active")], now=100) == []
    done = record(status="done", phase="done")
    assert machine.evaluate([done], now=200) == [
        "CODEX_DONE job=job-1 workspace=repo-abc123 phase=done"
    ]  # CX-022
    assert machine.evaluate([done], now=201) == []

    failed = record(
        job_id="bad",
        status="failed",
        phase="failed",
        error="fatal:\n  index.lock\t denied",
    )
    assert machine.evaluate([failed], now=202) == [
        "CODEX_FAILED job=bad workspace=repo-abc123 phase=failed "
        'error="fatal: index.lock denied"'
    ]  # CX-023
    assert machine.evaluate([failed], now=203) == []

    missing_error = record(job_id="bad2", status="failed", error=None)
    assert machine.evaluate([missing_error], now=204)[0].endswith(
        'error="error message unavailable"'
    )  # CX-024
    cancelled = record(job_id="cancel", status="cancelled")
    assert machine.evaluate([cancelled], now=205) == [
        "CODEX_CANCELLED job=cancel workspace=repo-abc123 reason=user-cancelled"
    ]  # CX-025
    simultaneous = [
        record(job_id="z", status="done", phase="done", created_at=2),
        record(job_id="a", status="done", phase="done", created_at=1),
    ]
    lines = machine.evaluate(simultaneous, now=206)
    assert [line.split()[1] for line in lines] == ["job=a", "job=z"]  # CX-026


def test_cx_027_to_032_missing_partial_unknown_and_bootstrap(tmp_path: Path) -> None:
    """CX-027..CX-032: read glitches are tolerated and bootstrap terminals report."""
    ws = workspace(tmp_path)
    state_dir, env = codex_store(tmp_path, ws, [{"id": "job-1", "epoch": 100}])
    scanner = watchdog.CodexScanner(env=env, proc=watchdog.NullProcInspector())
    machine = watchdog.CodexStateMachine(stall_secs=100, resume_secs=20, gone_polls=2)
    first = scanner.scan([ws], "session-full").records
    assert machine.evaluate(first, now=100) == []
    job_file = state_dir / "jobs" / "job-1.json"
    job_file.write_text("{", encoding="utf-8")
    os.utime(job_file, (101, 101))
    assert (
        machine.evaluate(scanner.scan([ws], "session-full").records, now=101) == []
    )  # 027
    write_json(
        job_file,
        {
            "id": "job-1",
            "sessionId": "session-full",
            "workspaceRoot": str(ws),
            "status": "running",
            "phase": "running",
        },
        102,
    )
    assert machine.evaluate(scanner.scan([ws], "session-full").records, now=102) == []
    job_file.unlink()
    assert (
        machine.evaluate(scanner.scan([ws], "session-full").records, now=103) == []
    )  # 028
    assert machine.evaluate(scanner.scan([ws], "session-full").records, now=104) == [
        "CODEX_GONE job=job-1 workspace="
        f"{watchdog.resolve_workspace(ws, env=env).key} reason=record-missing"
    ]  # 029
    empty = workspace(tmp_path, "empty")
    assert scanner.scan([empty], "session-full").records == []  # 030

    bad_state, bad_env = codex_store(
        tmp_path / "unknown",
        workspace(tmp_path / "unknown", "repo"),
        [{"id": "odd", "status": "future"}],
        version=999,
    )
    assert bad_state.exists()
    unknown_scan = watchdog.CodexScanner(
        env=bad_env, proc=watchdog.NullProcInspector()
    ).scan([tmp_path / "unknown" / "repo"], "session-full")
    assert unknown_scan.records == []
    assert len(unknown_scan.warnings) == 1  # CX-031

    boot = watchdog.CodexStateMachine(stall_secs=100, resume_secs=20, gone_polls=2)
    terminal = record(status="done", phase="done")
    assert len(boot.evaluate([terminal], now=100)) == 1
    assert boot.evaluate([terminal], now=101) == []  # CX-032


def test_cx_033_and_034_namespaces_and_healthy_silence() -> None:
    """CX-033/CX-034: Claude grammar is isolated and combined health is silent."""
    claude = watchdog.ClaudeStateMachine(stall_secs=100, resume_secs=20, gone_polls=2)
    codex = watchdog.CodexStateMachine(stall_secs=100, resume_secs=20, gone_polls=2)
    assert claude.evaluate_named("bilby", 100, Path("/work"), {"bilby"}, 100) == []
    assert codex.evaluate([record(activity=100)], now=100) == []
    lines = claude.evaluate_named("bilby", 100, Path("/work"), {"bilby"}, 200)
    assert lines == ["STALL agent=bilby idle=100s reason=owns-in_progress-idle"]
    assert all(not line.startswith("CODEX_") for line in lines)


def test_cx_035_no_gone_still_allows_stall() -> None:
    """CX-035: --no-gone disables only death classification."""
    machine = watchdog.CodexStateMachine(
        stall_secs=100, resume_secs=20, gone_polls=2, gone_enabled=False
    )
    assert machine.evaluate([record(runtime="dead")], now=100) == []
    assert machine.evaluate([record(runtime="dead")], now=200)[0].startswith(
        "CODEX_STALL "
    )


def test_activity_clock_fallback_chain(tmp_path: Path) -> None:
    """Claude activity uses worktree, isolated cwd, then transcript in that order."""
    wt_root = tmp_path / "worktrees"
    wt = wt_root / "agent-bilby"
    cwd = workspace(tmp_path)
    transcript = tmp_path / "agent.jsonl"
    touch(cwd / "work", 20)
    touch(transcript, 30)
    touch(wt / "build" / "artifact", 40)
    os.utime(cwd, (10, 10))
    os.utime(wt / "build", (35, 35))
    os.utime(wt, (35, 35))
    member = watchdog.Member("bilby", cwd, "aid", "developer", "", "")
    assert (
        watchdog.member_activity(member, wt_root, {cwd: 2}, {"bilby": transcript}).epoch
        == 40
    )
    for path in sorted(wt.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        else:
            path.rmdir()
    wt.rmdir()
    assert watchdog.member_activity(member, wt_root, {cwd: 1}, {}).epoch == 20
    assert (
        watchdog.member_activity(member, wt_root, {cwd: 2}, {"bilby": transcript}).epoch
        == 30
    )
    assert watchdog.member_activity(member, wt_root, {cwd: 2}, {}) is None


def test_member_transcript_resolution_is_session_scoped(tmp_path: Path) -> None:
    """Shared-cwd fallback binds an exact agent ID below this lead session."""
    projects = tmp_path / "projects"
    transcript = projects / "slug" / "lead-full" / "subagents" / "agent-1.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text('{"agentId":"internal-id"}\n', encoding="utf-8")
    write_json(
        transcript.with_suffix(".meta.json"),
        {"agentType": "developer-bilby"},
    )
    member = watchdog.Member(
        "bilby", tmp_path, "internal-id", "developer-bilby", "", ""
    )
    team = watchdog.Team(lead_session_id="lead-full", members=(member,), created_at=0)
    assert watchdog.member_transcripts(team, projects, {"other-lead"}) == {
        "bilby": transcript
    }


def test_tmux_binding_requires_unique_positive_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the unique best pane-title match can supply pane commands."""
    member = watchdog.Member(
        "bilby", Path("/work"), "aid", "developer-bilby", "%1", "tmux"
    )
    first, second = Path("/tmp/swarm-1"), Path("/tmp/swarm-2")
    monkeypatch.setattr(watchdog, "swarm_sockets", lambda _: [first, second])
    snapshots = {
        first: [("%1", "sleep", "claudius:developer-bilby")],
        second: [("%1", "sleep", "claudius:developer-other")],
    }
    monkeypatch.setattr(watchdog, "snapshot_panes", snapshots.get)
    commands, socket, score = watchdog.bind_swarm_socket([member], {})
    assert (commands, socket, score) == ({"%1": "sleep"}, first, 1)
    assert watchdog.classify_pane(member, commands) == "alive"
    snapshots[second] = [("%1", "bash", "claudius:developer-bilby")]
    assert watchdog.bind_swarm_socket([member], {}) == ({}, None, 0)
    assert watchdog.classify_pane(member, {}) == "missing"


def test_tmux_snapshot_and_socket_enumeration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tmux helpers keep tab fields intact and include explicit TMUX once."""
    tmux_dir = tmp_path / "tmux"
    tmux_dir.mkdir()
    first = tmux_dir / "claude-swarm-1"
    first.touch()
    explicit = tmp_path / "explicit.sock"
    assert watchdog.swarm_sockets(
        {"TMUX_TMPDIR": str(tmux_dir), "TMUX": f"{explicit},1,2"}
    ) == [first, explicit]
    monkeypatch.setattr(
        watchdog.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, "%1\tsleep\tclaudius:developer-bilby\n", ""
        ),
    )
    assert watchdog.snapshot_panes(first) == [
        ("%1", "sleep", "claudius:developer-bilby")
    ]


def test_watchdog_poll_combines_claude_and_codex_edges(tmp_path: Path) -> None:
    """One poll coordinator preserves Claude grammar beside Source D events."""
    home = tmp_path / "home"
    ws = workspace(tmp_path)
    worktrees = tmp_path / "worktrees"
    agent_worktree = worktrees / "agent-bilby"
    touch(agent_worktree / "work", 100)
    os.utime(agent_worktree, (100, 100))
    team_dir = home / ".claude" / "teams" / "session-short"
    write_json(
        team_dir / "config.json",
        {
            "name": "session-short",
            "leadSessionId": "session-full",
            "members": [
                {
                    "agentType": "team-lead",
                    "name": "lead",
                    "cwd": str(ws),
                    "isActive": True,
                },
                {
                    "agentType": "developer-bilby",
                    "name": "bilby",
                    "cwd": str(ws),
                    "agentId": "aid",
                    "backendType": "local",
                    "isActive": True,
                },
            ],
        },
    )
    tasks = tmp_path / "tasks"
    write_json(
        tasks / "1.json",
        {"status": "in_progress", "owner": "bilby"},
    )
    state_dir, env = codex_store(
        tmp_path,
        ws,
        [{"id": "coexisting", "epoch": 100}],
        state_epoch=100,
    )
    env["HOME"] = str(home)
    options = watchdog.Options(
        team_dir=team_dir,
        tasks_dir=tasks,
        projects_dir=tmp_path / "projects",
        worktrees=worktrees,
        gone_enabled=False,
        stall_secs=100,
        resume_secs=20,
        poll_secs=1,
    )
    proc = tmp_path / "proc"
    proc.mkdir()
    monitor = watchdog.Watchdog(options, env=env, proc_root=proc)
    assert monitor.poll_once(now=200) == [
        "STALL agent=bilby idle=100s reason=owns-in_progress-idle"
    ]
    touch(agent_worktree / "work", 195)
    os.utime(agent_worktree, (195, 195))
    write_json(
        state_dir / "jobs" / "coexisting.json",
        {
            "id": "coexisting",
            "sessionId": "session-full",
            "workspaceRoot": str(ws),
            "status": "completed",
            "phase": "done",
        },
        200,
    )
    assert monitor.poll_once(now=200) == [
        "RESUMED agent=bilby idle=5s",
        f"CODEX_DONE job=coexisting workspace={watchdog.resolve_workspace(ws, env=env).key} "
        "phase=done",
    ]


def test_watchdog_poll_opt_in_source_b_stall_resume(tmp_path: Path) -> None:
    """Anonymous transcripts retain their opt-in stall/resume grammar."""
    home = tmp_path / "home"
    ws = workspace(tmp_path)
    team_dir = home / ".claude" / "teams" / "session-short"
    write_json(
        team_dir / "config.json",
        {
            "name": "session-short",
            "leadSessionId": "lead-full",
            "members": [
                {
                    "agentType": "team-lead",
                    "name": "lead",
                    "cwd": str(ws),
                    "isActive": True,
                }
            ],
        },
    )
    projects = tmp_path / "projects"
    transcript = projects / "slug" / "lead-full" / "subagents" / "agent-bg.jsonl"
    touch(transcript, 100)
    worktrees = tmp_path / "worktrees"
    worktrees.mkdir()
    options = watchdog.Options(
        team_dir=team_dir,
        tasks_dir=tmp_path / "tasks",
        projects_dir=projects,
        worktrees=worktrees,
        watch_subagents=True,
        gone_enabled=False,
        stall_secs=100,
        resume_secs=20,
    )
    monitor = watchdog.Watchdog(
        options,
        env={"HOME": str(home), "CLAUDE_PLUGIN_DATA": str(tmp_path / "plugin")},
        proc_root=tmp_path / "proc",
    )
    assert monitor.poll_once(now=200) == [
        "STALL agent=agent-bg idle=100s reason=subagent-idle"
    ]
    touch(transcript, 195)
    assert monitor.poll_once(now=200) == ["RESUMED agent=agent-bg idle=5s"]


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["cargo", "test"], True),
        (["node", "server.js"], False),
        (["env", "A=1", "bash", "./gradlew", "build"], True),
        (["python3", "-m", "pytest"], True),
        (["npm", "test"], False),
    ],
)
def test_proc_build_detection_is_argv_anchored(argv: list[str], expected: bool) -> None:
    """Build detection unwraps one interpreter but rejects broad substrings."""
    assert watchdog.is_build_command(argv) is expected


def test_proc_build_detection_is_scoped_to_agent(tmp_path: Path) -> None:
    """A build elsewhere on the machine cannot suppress this agent's stall."""
    proc = tmp_path / "proc"
    ours = workspace(tmp_path, "ours")
    other = workspace(tmp_path, "other")
    watchdog.write_fake_process(proc, 101, other, ["cargo", "test"])
    assert not watchdog.build_active_under(ours, proc_root=proc)
    watchdog.write_fake_process(proc, 102, ours / "child", ["cargo", "test"])
    assert watchdog.build_active_under(ours, proc_root=proc)


def test_unevaluable_proc_suppresses_transition() -> None:
    """A wholesale proc failure cannot be interpreted as no build."""
    claude = watchdog.ClaudeStateMachine(
        stall_secs=100,
        resume_secs=20,
        gone_polls=2,
        build_active=lambda _: None,
    )
    assert claude.evaluate_named("bilby", 100, Path("/work"), {"bilby"}, 200) == []
    codex = watchdog.CodexStateMachine(stall_secs=100, resume_secs=20, gone_polls=2)
    assert codex.evaluate([record(activity=100)], now=100) == []
    assert (
        codex.evaluate([record(activity=100)], now=200, build_active=lambda _: None)
        == []
    )


def test_unreadable_proc_evidence_is_unknown(tmp_path: Path) -> None:
    """A transient proc read failure cannot become verified runtime death."""
    proc = tmp_path / "proc"
    (proc / "123").mkdir(parents=True)
    inspector = watchdog.ProcInspector(proc)
    assert inspector.launcher(123, tmp_path) is None
    assert inspector.launcher(999, tmp_path) == "dead"
    assert inspector.launcher(None, tmp_path) is None


def test_codex_proc_evidence_rejects_pid_reuse(tmp_path: Path) -> None:
    """Codex liveness requires compatible argv and cwd, not PID existence."""
    proc = tmp_path / "proc"
    ws = workspace(tmp_path)
    watchdog.write_fake_process(
        proc,
        101,
        ws,
        ["node", "/plugin/codex-companion.mjs", "task-worker"],
    )
    watchdog.write_fake_process(proc, 102, ws, ["sleep", "1000"])
    inspector = watchdog.ProcInspector(proc)
    assert inspector.launcher(101, ws) == "alive"
    assert inspector.launcher(102, ws) == "dead"
    endpoint_dir = tmp_path / "runtime"
    endpoint = endpoint_dir / "broker.sock"
    watchdog.write_fake_process(
        proc,
        103,
        endpoint_dir,
        ["node", "/plugin/app-server-broker.mjs", str(endpoint)],
    )
    assert inspector.broker({"pid": 103, "endpoint": str(endpoint)}, ws) == "alive"
    assert inspector.broker({"pid": 103}, ws) is None
    assert inspector.broker(None, ws) is None


def test_task_store_parsing_tolerates_partial_files(tmp_path: Path) -> None:
    """Only valid in-progress task owners enter the task gate."""
    tasks = tmp_path / "tasks"
    write_json(tasks / "1.json", {"status": "in_progress", "owner": "bilby"})
    write_json(tasks / "2.json", {"status": "completed", "owner": "smythe"})
    (tasks / "partial.json").write_text("{", encoding="utf-8")
    assert watchdog.build_owners(tasks) == {"bilby"}


def test_team_selection_precedence(tmp_path: Path) -> None:
    """Explicit dir beats session, which beats env, then newest mtime wins."""
    teams = tmp_path / "teams"
    one = teams / "session-short1"
    two = teams / "session-short2"
    write_json(one / "config.json", {"leadSessionId": "full-one"}, 100)
    write_json(two / "config.json", {"leadSessionId": "full-two"}, 200)
    assert watchdog.select_team(teams, one, "full-two").directory == one
    assert watchdog.select_team(teams, None, "full-one").directory == one
    assert watchdog.select_team(teams, None, "short2").directory == two
    assert watchdog.select_team(teams, None, "").directory == two


def test_claude_stall_resume_gone_confirmation() -> None:
    """Claude transitions are edge-triggered and require consecutive misses."""
    machine = watchdog.ClaudeStateMachine(stall_secs=100, resume_secs=20, gone_polls=2)
    assert machine.evaluate_named("bilby", 100, Path("/work"), {"bilby"}, 100) == []
    assert machine.evaluate_named("bilby", 100, Path("/work"), {"bilby"}, 200) == [
        "STALL agent=bilby idle=100s reason=owns-in_progress-idle"
    ]
    assert machine.evaluate_named("bilby", 100, Path("/work"), {"bilby"}, 201) == []
    assert machine.prune(set()) == []
    assert machine.prune(set()) == ["RESUMED agent=bilby reason=gone"]
    machine.evaluate_named("bilby", 200, Path("/work"), {"bilby"}, 200)
    assert machine.gone_candidate("bilby", "dead", 200, 200) == []
    assert machine.gone_candidate("bilby", "dead", 200, 201) == [
        "GONE agent=bilby reason=pane-dead"
    ]
    assert machine.recover_gone("bilby") == ["RESUMED agent=bilby reason=recovered"]
    machine = watchdog.ClaudeStateMachine(stall_secs=100, resume_secs=20, gone_polls=1)
    assert machine.gone_candidate("old", "missing", 0, 200) == [
        "GONE agent=old reason=stale-active"
    ]
    assert machine.gone_candidate("fresh", "missing", 200, 200) == [
        "GONE agent=fresh reason=pid-gone"
    ]


def test_cli_validation_and_healthy_silence(tmp_path: Path) -> None:
    """The drop-in CLI preserves validation and emits no healthy stdout."""
    bad = subprocess.run(
        [sys.executable, str(SCRIPT), "--poll-secs", "0"],
        text=True,
        capture_output=True,
        check=False,
        env={"HOME": str(tmp_path / "home"), "PATH": os.environ["PATH"]},
    )
    assert bad.returncode == 1
    assert "--poll-secs must be >= 1" in bad.stderr


def test_cli_preserves_all_flags_and_defaults(tmp_path: Path) -> None:
    """Every Bash flag and default remains available on the Python CLI."""
    defaults = watchdog.parse_args(
        [], {"HOME": str(tmp_path), "CLAUDE_SESSION_ID": "env"}
    )
    assert (
        defaults.session_id,
        defaults.stall_secs,
        defaults.resume_secs,
        defaults.gone_polls,
        defaults.poll_secs,
        defaults.watch_subagents,
        defaults.gone_enabled,
    ) == ("env", 300, 60, 2, 45, False, True)
    options = watchdog.parse_args(
        [
            "--session-id",
            "explicit",
            "--team-dir",
            "/team",
            "--tasks-dir",
            "/tasks",
            "--projects-dir",
            "/projects",
            "--worktrees",
            "/worktrees",
            "--stall-secs",
            "10",
            "--resume-secs",
            "2",
            "--gone-polls",
            "3",
            "--poll-secs",
            "1",
            "--watch-subagents",
            "--no-gone",
        ],
        {"HOME": str(tmp_path), "CLAUDE_SESSION_ID": "env"},
    )
    assert options.session_id == "explicit"
    assert options.team_dir == Path("/team")
    assert options.tasks_dir == Path("/tasks")
    assert options.projects_dir == Path("/projects")
    assert options.worktrees == Path("/worktrees")
    assert (options.stall_secs, options.resume_secs, options.gone_polls) == (10, 2, 3)
    assert options.poll_secs == 1
    assert options.watch_subagents and not options.gone_enabled


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["--unknown"], "unknown argument"),
        (["--team-dir"], "needs a value"),
        (["--gone-polls", "x"], "expects a non-negative integer"),
        (["--gone-polls", "0"], "must be >= 1"),
        (["--stall-secs", "2", "--resume-secs", "2"], "must be <"),
    ],
)
def test_cli_rejects_invalid_arguments(
    argv: list[str], message: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """CLI errors retain the stable prefix and exit status."""
    with pytest.raises(SystemExit) as caught:
        watchdog.parse_args(argv, {"HOME": "/tmp"})
    assert caught.value.code == 1
    assert message in capsys.readouterr().err


def test_cli_help_is_stderr_and_success(capsys: pytest.CaptureFixture[str]) -> None:
    """Help preserves the original stderr channel and successful exit."""
    with pytest.raises(SystemExit) as caught:
        watchdog.parse_args(["--help"], {"HOME": "/tmp"})
    assert caught.value.code == 0
    assert "Usage: agent-watchdog.py" in capsys.readouterr().err


def test_codex_cli_state_store_integration_is_isolated(tmp_path: Path) -> None:
    """The persistent CLI stays healthy-silent, then emits one terminal edge."""
    home = tmp_path / "home"
    ws = workspace(tmp_path)
    team_dir = home / ".claude" / "teams" / "session-short"
    write_json(
        team_dir / "config.json",
        {
            "name": "session-short",
            "leadSessionId": "session-full",
            "members": [
                {
                    "agentType": "team-lead",
                    "name": "lead",
                    "cwd": str(ws),
                    "isActive": True,
                }
            ],
        },
    )
    now = int(time.time())
    state_dir, env = codex_store(
        tmp_path,
        ws,
        [{"id": "cli-job", "epoch": now, "updatedAt": now}],
        state_epoch=now,
    )
    env.update({"HOME": str(home), "PATH": os.environ["PATH"]})
    worktrees = tmp_path / "worktrees"
    tasks = tmp_path / "tasks"
    projects = tmp_path / "projects"
    for directory in (worktrees, tasks, projects):
        directory.mkdir()
    process = subprocess.Popen(
        [
            sys.executable,
            str(SCRIPT),
            "--team-dir",
            str(team_dir),
            "--tasks-dir",
            str(tasks),
            "--projects-dir",
            str(projects),
            "--worktrees",
            str(worktrees),
            "--poll-secs",
            "1",
            "--stall-secs",
            "10",
            "--resume-secs",
            "2",
            "--gone-polls",
            "2",
            "--no-gone",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    try:
        time.sleep(2.2)
        write_json(
            state_dir / "jobs" / "cli-job.json",
            {
                "id": "cli-job",
                "sessionId": "session-full",
                "workspaceRoot": str(ws),
                "status": "failed",
                "phase": "failed",
                "errorMessage": "line one\nline two",
            },
            int(time.time()),
        )
        time.sleep(2.2)
    finally:
        process.terminate()
    stdout, _ = process.communicate(timeout=5)
    assert stdout.splitlines() == [
        f"CODEX_FAILED job=cli-job workspace={watchdog.resolve_workspace(ws, env=env).key} "
        'phase=failed error="line one line two"'
    ]
