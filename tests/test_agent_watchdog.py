"""Contract tests for the Python agent watchdog."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import re
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


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a real Git workspace for repository-root resolution tests."""
    result = tmp_path / "git-repo"
    subprocess.run(
        ["git", "init", str(result)],
        check=True,
        capture_output=True,
        text=True,
    )
    return result


def no_build(_: Path) -> bool:
    """Return an isolated negative build-process result."""
    return False


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


def test_safe_json_bounds_reads_and_handles_recursion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Defensive JSON reads reject oversized and excessively nested input."""
    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b" " * (watchdog.JSON_FILE_LIMIT + 1))
    assert watchdog.safe_json(oversized) is None
    assert "exceeds the 10485760-byte read limit" in capsys.readouterr().err
    assert watchdog.safe_json(oversized) is None
    assert capsys.readouterr().err == ""

    recursive = tmp_path / "recursive.json"
    recursive.write_text("{}", encoding="utf-8")

    def raise_recursion(_: str) -> Any:
        raise RecursionError

    monkeypatch.setattr(watchdog.json, "loads", raise_recursion)
    assert watchdog.safe_json(recursive) is None


def test_uncaught_exception_traceback_has_named_crash_log(tmp_path: Path) -> None:
    """Crash diagnostics append the full traceback under plugin state."""
    env = {"CLAUDE_PLUGIN_DATA": str(tmp_path / "plugin-data")}
    traceback_text = "Traceback (most recent call last):\nRuntimeError: boom\n"

    path = watchdog._write_crash_log(traceback_text, env)

    assert path == Path(env["CLAUDE_PLUGIN_DATA"]) / "logs" / watchdog.CRASH_LOG_NAME
    assert traceback_text in path.read_text(encoding="utf-8")
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700


def test_crash_log_bounds_one_pathological_traceback(tmp_path: Path) -> None:
    """One huge traceback is marked and kept within the crash-log size cap."""
    env = {"CLAUDE_PLUGIN_DATA": str(tmp_path / "plugin-data")}

    path = watchdog._write_crash_log("x" * (watchdog.CRASH_LOG_LIMIT + 1), env)

    payload = path.read_bytes()
    assert len(payload) <= watchdog.CRASH_LOG_LIMIT
    assert payload.endswith(b"[traceback truncated to crash-log limit]\n")


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


def test_real_git_workspace_resolves_repository_root(
    git_repo: Path, tmp_path: Path
) -> None:
    """Source D maps a nested Git path to its real repository toplevel."""
    nested = git_repo / "nested" / "directory"
    nested.mkdir(parents=True)
    env = {"CLAUDE_PLUGIN_DATA": str(tmp_path / "plugin-data")}

    assert watchdog.git_toplevel(nested) == git_repo
    resolved = watchdog.resolve_workspace(nested, env)
    assert resolved.root == git_repo
    assert resolved.canonical == git_repo.resolve()
    assert resolved.state_dir == watchdog.codex_state_root(env) / resolved.key


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


def test_codex_scanner_isolates_nul_workspace_root(tmp_path: Path) -> None:
    """One invalid workspaceRoot cannot suppress valid jobs in the same store."""
    ws = workspace(tmp_path)
    _, env = codex_store(
        tmp_path,
        ws,
        [
            {"id": "invalid-root", "workspaceRoot": "invalid\0root"},
            {"id": "healthy"},
        ],
    )
    scanner = watchdog.CodexScanner(env=env, proc=watchdog.NullProcInspector())

    result = scanner.scan([ws], "session-full")

    assert [item.job_id for item in result.records] == ["healthy"]
    assert len(result.warnings) == 1
    assert result.warnings[0][0].startswith("codex-job-scan-error:")
    assert "ValueError" in result.warnings[0][1]


def test_codex_scanner_warns_once_for_workspace_root_mismatch(
    tmp_path: Path,
) -> None:
    """A job found under the wrong resolved workspace is skipped with context."""
    ws = workspace(tmp_path)
    reported = workspace(tmp_path, "reported")
    state_dir, env = codex_store(
        tmp_path,
        ws,
        [{"id": "mismatch", "workspaceRoot": str(reported)}],
    )
    job_path = state_dir / "jobs" / "mismatch.json"
    job = json.loads(job_path.read_text(encoding="utf-8"))
    job.pop("sessionId")
    write_json(job_path, job, 100)
    info = watchdog.resolve_workspace(ws, env)
    scanner = watchdog.CodexScanner(env=env, proc=watchdog.NullProcInspector())

    first = scanner.scan([ws], "session-full")

    assert first.records == []
    assert first.warnings == [
        (
            f"codex-job-workspace-mismatch:{info.key}:mismatch.json",
            f"Codex job 'mismatch.json' in {info.key} reports "
            f"workspaceRoot={str(reported)!r} which doesn't match this candidate's "
            f"resolved path {info.canonical} — job skipped, may be silently "
            "invisible to CODEX_* events",
        )
    ]
    assert scanner.scan([ws], "session-full").warnings == []


def test_codex_scanner_warns_for_prefix_matching_session_workspace_mismatch(
    tmp_path: Path,
) -> None:
    """A mismatched job from a plausibly tracked session still warns."""
    ws = workspace(tmp_path)
    reported = workspace(tmp_path, "reported")
    _, env = codex_store(
        tmp_path,
        ws,
        [
            {
                "id": "matching-session-mismatch",
                "sessionId": "session-full",
                "workspaceRoot": str(reported),
            }
        ],
    )
    scanner = watchdog.CodexScanner(env=env, proc=watchdog.NullProcInspector())

    result = scanner.scan([ws], "session")

    assert result.records == []
    assert len(result.warnings) == 1
    assert result.warnings[0][0].startswith("codex-job-workspace-mismatch:")


def test_codex_scanner_suppresses_workspace_mismatch_for_unrelated_session(
    tmp_path: Path,
) -> None:
    """A mismatched job from an unrelated session is discarded silently."""
    ws = workspace(tmp_path)
    reported = workspace(tmp_path, "reported")
    _, env = codex_store(
        tmp_path,
        ws,
        [
            {
                "id": "unrelated-session-mismatch",
                "sessionId": "some-other-session-from-last-week",
                "workspaceRoot": str(reported),
            }
        ],
    )
    scanner = watchdog.CodexScanner(env=env, proc=watchdog.NullProcInspector())

    result = scanner.scan([ws], "session-full")

    assert result.records == []
    assert result.warnings == []


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


def test_malformed_job_does_not_poison_session_disambiguation(
    tmp_path: Path,
) -> None:
    """An invalid job cannot make a healthy short session prefix ambiguous."""
    ws = workspace(tmp_path)
    _, env = codex_store(
        tmp_path,
        ws,
        [
            {"id": "healthy", "sessionId": "session-one"},
            {
                "id": "invalid-status",
                "sessionId": "session-two",
                "status": "not-a-status",
            },
        ],
    )
    scanner = watchdog.CodexScanner(env=env, proc=watchdog.NullProcInspector())

    result = scanner.scan([ws], "session-")

    assert [item.job_id for item in result.records] == ["healthy"]
    assert not any(
        key.startswith("codex-session-ambiguous") for key, _ in result.warnings
    )


def test_cx_011_to_015_active_stall_resume_and_build() -> None:
    """CX-011..CX-015: active silence, hysteresis, edges, and build suppression."""
    builds = False
    machine = watchdog.CodexStateMachine(stall_secs=100, resume_secs=20, gone_polls=2)
    stale = record(activity=100)
    assert (
        machine.evaluate([stale], now=100, build_active=lambda _: builds) == []
    )  # 011
    assert (
        machine.evaluate([record(activity=150)], now=200, build_active=no_build) == []
    )  # 012
    assert machine.evaluate([stale], now=200, build_active=no_build) == [
        "CODEX_STALL job=job-1 workspace=repo-abc123 idle=100s "
        "phase=running reason=no-progress"
    ]  # 013
    assert machine.evaluate([stale], now=201, build_active=no_build) == []
    assert machine.evaluate([record(activity=185)], now=200, build_active=no_build) == [
        "CODEX_RESUMED job=job-1 workspace=repo-abc123 idle=15s "
        "phase=running reason=progress"
    ]  # 014
    assert machine.evaluate([stale], now=200, build_active=no_build) != []
    assert (
        machine.evaluate([record(activity=150)], now=200, build_active=no_build) == []
    )  # hysteresis
    builds = True
    machine = watchdog.CodexStateMachine(stall_secs=100, resume_secs=20, gone_polls=2)
    assert machine.evaluate([stale], now=100, build_active=no_build) == []
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


def test_cross_session_job_prevents_shared_state_mtime_attribution(
    tmp_path: Path,
) -> None:
    """A concurrent foreign-session job cannot refresh the selected job's clock."""
    ws = workspace(tmp_path)
    _, env = codex_store(
        tmp_path,
        ws,
        [
            {
                "id": "selected-orphan",
                "sessionId": "session-one",
                "epoch": 100,
                "updatedAt": None,
            },
            {
                "id": "foreign-active",
                "sessionId": "session-two",
                "epoch": 199,
                "updatedAt": None,
            },
        ],
        state_epoch=199,
    )
    scanner = watchdog.CodexScanner(env=env, proc=watchdog.NullProcInspector())

    records = scanner.scan([ws], "session-one", now=200).records

    assert [(item.job_id, item.activity_epoch) for item in records] == [
        ("selected-orphan", 100)
    ]


def test_direct_discovery_prefilters_foreign_workspace_state(
    tmp_path: Path,
) -> None:
    """Teamless discovery does not parse state for another workspace."""
    ws = workspace(tmp_path)
    foreign = workspace(tmp_path, "foreign")
    _, env = codex_store(tmp_path, ws, [{"id": "ours", "epoch": 100}])
    foreign_state, _ = codex_store(
        tmp_path,
        foreign,
        [{"id": "foreign", "epoch": 100}],
    )
    foreign_job = foreign_state / "jobs" / "foreign.json"
    scanner = watchdog.CodexScanner(env=env, proc=watchdog.NullProcInspector())

    result = scanner.scan(
        [],
        "session-full",
        now=100,
        discovery_candidates=[ws],
    )

    assert [item.job_id for item in result.records] == ["ours"]
    assert foreign_job not in scanner.cache.items


def test_direct_discovery_survives_zero_match_ambient_session(
    tmp_path: Path,
) -> None:
    """A failed ambient session match cannot suppress a direct workspace."""
    ambient = workspace(tmp_path, "ambient")
    direct = workspace(tmp_path, "direct")
    _, env = codex_store(
        tmp_path,
        ambient,
        [{"id": "ambient", "sessionId": "ambient-session"}],
    )
    codex_store(
        tmp_path,
        direct,
        [{"id": "direct", "sessionId": "worker-session"}],
    )
    scanner = watchdog.CodexScanner(env=env, proc=watchdog.NullProcInspector())

    result = scanner.scan(
        [ambient],
        "coordinator-session",
        now=100,
        discovery_candidates=[direct],
    )

    assert [item.job_id for item in result.records] == ["direct"]
    assert result.warnings == []


def test_codex_scanner_never_parses_growing_state_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """State polling uses per-job fields and the shared file only as a clock."""
    ws = workspace(tmp_path)
    state_dir, env = codex_store(
        tmp_path,
        ws,
        [
            {
                "id": "job-1",
                "epoch": 100,
                "phase": "streaming",
                "updatedAt": 150,
            }
        ],
        state_epoch=140,
    )
    state_path = state_dir / "state.json"
    parsed_paths: list[Path] = []
    header_paths: list[Path] = []
    real_safe_json = watchdog.safe_json
    real_safe_state_header = watchdog._safe_state_header

    def tracking_safe_json(path: Path) -> Any | None:
        parsed_paths.append(path)
        return real_safe_json(path)

    def tracking_safe_state_header(path: Path) -> Any | None:
        header_paths.append(path)
        return real_safe_state_header(path)

    monkeypatch.setattr(watchdog, "safe_json", tracking_safe_json)
    monkeypatch.setattr(watchdog, "_safe_state_header", tracking_safe_state_header)
    scanner = watchdog.CodexScanner(env=env, proc=watchdog.NullProcInspector())
    first = scanner.scan([ws], "session-full").records
    assert [(item.phase, item.activity_epoch) for item in first] == [("streaming", 150)]

    write_json(
        state_path,
        {
            "version": 1,
            "jobs": [
                {"id": f"old-{index}", "phase": "done", "updatedAt": 999}
                for index in range(2_000)
            ],
        },
        160,
    )
    second = scanner.scan([ws], "session-full").records
    assert [(item.phase, item.activity_epoch) for item in second] == [
        ("streaming", 160)
    ]
    assert state_path not in parsed_paths
    # The growing jobs array is never full-parsed, but the bounded header is
    # re-read once the file's mtime changes (mtime-gated, not pinned forever).
    assert header_paths == [state_path, state_path]


def _reorder_state(state_path: Path, version: Any, epoch: int = 140) -> None:
    """Rewrite state.json with "version" placed after "jobs"."""
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    write_json(state_path, {"jobs": payload["jobs"], "version": version}, epoch)


def test_codex_state_version_after_jobs_supported_is_read(tmp_path: Path) -> None:
    """A supported version is honored even when it is not the first key."""
    ws = workspace(tmp_path)
    state_dir, env = codex_store(
        tmp_path,
        ws,
        [{"id": "job-1", "epoch": 100, "phase": "streaming", "updatedAt": 150}],
        state_epoch=140,
    )
    _reorder_state(state_dir / "state.json", 1)
    result = watchdog.CodexScanner(env=env, proc=watchdog.NullProcInspector()).scan(
        [ws], "session-full"
    )
    assert result.warnings == []
    assert [(item.phase, item.activity_epoch) for item in result.records] == [
        ("streaming", 150)
    ]


def test_codex_state_version_after_jobs_unsupported_is_skipped(tmp_path: Path) -> None:
    """An unsupported version after "jobs" is detected, not silently accepted."""
    ws = workspace(tmp_path)
    state_dir, env = codex_store(
        tmp_path,
        ws,
        [{"id": "job-1", "epoch": 100, "phase": "streaming", "updatedAt": 150}],
        state_epoch=140,
    )
    _reorder_state(state_dir / "state.json", 2)
    result = watchdog.CodexScanner(env=env, proc=watchdog.NullProcInspector()).scan(
        [ws], "session-full"
    )
    assert result.records == []
    assert len(result.warnings) == 1
    assert result.warnings[0][0].startswith("codex-state-version")


def test_codex_state_large_truncated_version_is_indeterminate(tmp_path: Path) -> None:
    """A huge file whose version is past the header window fails loud (skipped)."""
    ws = workspace(tmp_path)
    state_dir, env = codex_store(
        tmp_path,
        ws,
        [{"id": "job-1", "epoch": 100, "phase": "streaming", "updatedAt": 150}],
        state_epoch=140,
    )
    state_path = state_dir / "state.json"
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    filler = [
        {"id": f"old-{index}", "phase": "done", "updatedAt": 999}
        for index in range(200)
    ]
    write_json(state_path, {"jobs": filler + payload["jobs"], "version": 1}, 140)
    text = state_path.read_text(encoding="utf-8")
    assert len(text) > watchdog.STATE_HEADER_LIMIT
    assert '"version"' not in text[: watchdog.STATE_HEADER_LIMIT]
    result = watchdog.CodexScanner(env=env, proc=watchdog.NullProcInspector()).scan(
        [ws], "session-full"
    )
    assert result.records == []
    assert len(result.warnings) == 1
    assert result.warnings[0][0].startswith("codex-state-version-indeterminate")


def test_codex_state_header_cache_reacts_to_version_change(tmp_path: Path) -> None:
    """A long-lived scanner re-checks the version when state.json is rewritten."""
    ws = workspace(tmp_path)
    state_dir, env = codex_store(
        tmp_path,
        ws,
        [{"id": "job-1", "epoch": 100, "phase": "streaming", "updatedAt": 150}],
        state_epoch=140,
        version=1,
    )
    scanner = watchdog.CodexScanner(env=env, proc=watchdog.NullProcInspector())
    first = scanner.scan([ws], "session-full")
    assert [item.phase for item in first.records] == ["streaming"]
    assert first.warnings == []
    # Rewrite the SAME state.json in place to an unsupported version, new mtime.
    state_path = state_dir / "state.json"
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    write_json(state_path, {"version": 999, "jobs": payload["jobs"]}, 160)
    # The same long-lived scanner must notice the change, not serve a pinned
    # header from the first read.
    second = scanner.scan([ws], "session-full")
    assert second.records == []
    assert len(second.warnings) == 1
    assert second.warnings[0][0].startswith("codex-state-version")


def test_slow_jobs_glob_emits_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Enumerating jobs/*.json slower than the threshold warns once, not per poll."""
    ws = workspace(tmp_path)
    _, env = codex_store(
        tmp_path,
        ws,
        [{"id": "job-1", "epoch": 100, "phase": "streaming", "updatedAt": 150}],
        state_epoch=140,
    )
    # Each monotonic() call advances 0.6s, so every glob start/end pair reports
    # 0.6s elapsed — over the 0.5s JOBS_GLOB_WARN_SECS threshold.
    clock = {"t": 0.0}

    def fake_monotonic() -> float:
        clock["t"] += 0.6
        return clock["t"]

    monkeypatch.setattr(watchdog.time, "monotonic", fake_monotonic)
    scanner = watchdog.CodexScanner(env=env, proc=watchdog.NullProcInspector())
    result = scanner.scan([ws], "session-full")
    assert [item.phase for item in result.records] == ["streaming"]
    slow = [k for k, _ in result.warnings if k.startswith("codex-jobs-glob-slow")]
    assert len(slow) == 1


def test_codex_scanner_skips_jobs_outside_configured_recency(
    tmp_path: Path,
) -> None:
    """The per-workspace scan does not parse job records older than its bound."""
    now = 1_000
    ws = workspace(tmp_path)
    _, env = codex_store(
        tmp_path,
        ws,
        [
            {"id": "old-active", "epoch": now - 61},
            {"id": "recent-active", "epoch": now - 59},
        ],
        state_epoch=now,
    )
    scanner = watchdog.CodexScanner(
        env=env,
        proc=watchdog.NullProcInspector(),
        job_recency_secs=60,
    )

    result = scanner.scan([ws], "session-full", now=now)

    assert [item.job_id for item in result.records] == ["recent-active"]
    assert any(key.startswith("codex-jobs-recency:") for key, _ in result.warnings)


def test_codex_scanner_ages_out_only_terminal_job_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Old retained terminals age out while old active and recent terminal jobs stay."""
    now = 1_000_000
    retention_secs = 6 * 60 * 60
    ws = workspace(tmp_path)
    _, env = codex_store(
        tmp_path,
        ws,
        [
            {
                "id": "old-terminal",
                "status": "completed",
                "phase": "done",
                "epoch": now - retention_secs - 1,
            },
            {
                "id": "old-active",
                "status": "running",
                "epoch": now - retention_secs - 1,
            },
            {
                "id": "recent-terminal",
                "status": "failed",
                "phase": "failed",
                "epoch": now - retention_secs + 1,
            },
        ],
    )
    monkeypatch.setattr(watchdog.time, "time", lambda: now)

    records = (
        watchdog.CodexScanner(env=env, proc=watchdog.NullProcInspector())
        .scan([ws], "session-full")
        .records
    )

    assert [item.job_id for item in records] == [
        "old-active",
        "recent-terminal",
    ]


def test_codex_scanner_excludes_aged_out_terminal_jobs_from_session_disambiguation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An aged-out terminal job's sessionId must not count toward ambiguity.

    Retention is meant to bound *all* downstream state tracking, including
    session disambiguation — not just the final `records` list. A terminal
    job old enough to be aged out must not make `_session()` see it as a
    live candidate for prefix-matching.
    """
    now = 1_000_000
    retention_secs = 6 * 60 * 60
    ws = workspace(tmp_path)
    _, env = codex_store(
        tmp_path,
        ws,
        [
            {
                "id": "old-terminal",
                "sessionId": "session-old",
                "status": "completed",
                "phase": "done",
                "epoch": now - retention_secs - 1,
            },
            {
                "id": "current",
                "sessionId": "session-new",
                "status": "running",
                "epoch": now - 10,
            },
        ],
    )
    monkeypatch.setattr(watchdog.time, "time", lambda: now)
    scanner = watchdog.CodexScanner(env=env, proc=watchdog.NullProcInspector())

    result = scanner.scan([ws], "session-")

    ambiguous = [
        key for key, _ in result.warnings if key.startswith("codex-session-ambiguous")
    ]
    assert ambiguous == []
    assert [item.job_id for item in result.records] == ["current"]


def test_codex_scanner_checks_shared_broker_once_per_workspace(tmp_path: Path) -> None:
    """Shared broker liveness is read once for all matching workspace jobs."""

    class CountingProcInspector(watchdog.NullProcInspector):
        def __init__(self) -> None:
            super().__init__()
            self.broker_calls = 0

        def broker(self, record: dict[str, Any] | None, workspace: Path) -> str | None:
            self.broker_calls += 1
            return super().broker(record, workspace)

    ws = workspace(tmp_path)
    _, env = codex_store(tmp_path, ws, [{"id": "one"}, {"id": "two"}])
    proc = CountingProcInspector()
    records = (
        watchdog.CodexScanner(env=env, proc=proc).scan([ws], "session-full").records
    )
    assert [item.job_id for item in records] == ["one", "two"]
    assert proc.broker_calls == 1


def test_cx_017_to_021_runtime_gone_unknown_and_recovery() -> None:
    """CX-017..CX-021: verified death is confirmed; unknown is conservative."""
    machine = watchdog.CodexStateMachine(stall_secs=100, resume_secs=20, gone_polls=2)
    assert (
        machine.evaluate([record(runtime="dead")], now=100, build_active=no_build) == []
    )
    assert machine.evaluate(
        [record(runtime="dead")], now=200, build_active=no_build
    ) == ["CODEX_GONE job=job-1 workspace=repo-abc123 reason=runtime-gone"]  # CX-018
    assert machine.evaluate(
        [record(activity=200, runtime="alive")], now=201, build_active=no_build
    ) == [
        "CODEX_RESUMED job=job-1 workspace=repo-abc123 phase=running reason=recovered"
    ]  # CX-021

    unknown = watchdog.CodexStateMachine(stall_secs=100, resume_secs=20, gone_polls=2)
    assert (
        unknown.evaluate([record(runtime="unknown")], now=100, build_active=no_build)
        == []
    )
    assert unknown.evaluate(
        [record(runtime="unknown")], now=200, build_active=no_build
    )[0].startswith("CODEX_STALL ")  # CX-019


def test_cx_020_null_pid_uses_scanner_clock_and_runtime_rules(tmp_path: Path) -> None:
    """CX-020: running null-PID jobs stall by clock without immediate GONE."""
    ws = workspace(tmp_path)
    _, env = codex_store(
        tmp_path,
        ws,
        [{"id": "null-pid", "pid": None, "status": "running", "epoch": 100}],
        state_epoch=100,
    )
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    scanner = watchdog.CodexScanner(env=env, proc=watchdog.ProcInspector(proc_root))
    machine = watchdog.CodexStateMachine(stall_secs=100, resume_secs=20, gone_polls=2)

    records = scanner.scan([ws], "session-full").records
    assert len(records) == 1
    assert records[0].runtime == "unknown"
    assert machine.evaluate(records, now=100, build_active=no_build) == []
    assert machine.evaluate(records, now=200, build_active=no_build) == [
        f"CODEX_STALL job=null-pid workspace={records[0].workspace_key} "
        "idle=100s phase=running reason=no-progress"
    ]


def test_cx_022_to_026_terminal_events_are_exact_and_deterministic() -> None:
    """CX-022..CX-026: terminal status wins and reports exactly once."""
    machine = watchdog.CodexStateMachine(stall_secs=100, resume_secs=20, gone_polls=2)
    assert (
        machine.evaluate([record(status="active")], now=100, build_active=no_build)
        == []
    )
    done = record(status="done", phase="done")
    assert machine.evaluate([done], now=200, build_active=no_build) == [
        "CODEX_DONE job=job-1 workspace=repo-abc123 phase=done"
    ]  # CX-022
    assert machine.evaluate([done], now=201, build_active=no_build) == []

    failed = record(
        job_id="bad",
        status="failed",
        phase="failed",
        error="fatal:\n  index.lock\t denied",
    )
    assert machine.evaluate([failed], now=202, build_active=no_build) == [
        "CODEX_FAILED job=bad workspace=repo-abc123 phase=failed "
        'error="fatal: index.lock denied"'
    ]  # CX-023
    assert machine.evaluate([failed], now=203, build_active=no_build) == []

    missing_error = record(job_id="bad2", status="failed", error=None)
    assert machine.evaluate([missing_error], now=204, build_active=no_build)[
        0
    ].endswith('error="error message unavailable"')  # CX-024
    cancelled = record(job_id="cancel", status="cancelled")
    assert machine.evaluate([cancelled], now=205, build_active=no_build) == [
        "CODEX_CANCELLED job=cancel workspace=repo-abc123 reason=user-cancelled"
    ]  # CX-025
    simultaneous = [
        record(job_id="z", status="done", phase="done", created_at=2),
        record(job_id="a", status="done", phase="done", created_at=1),
    ]
    lines = machine.evaluate(simultaneous, now=206, build_active=no_build)
    assert [line.split()[1] for line in lines] == ["job=a", "job=z"]  # CX-026


def test_cx_027_to_032_missing_partial_unknown_and_bootstrap(tmp_path: Path) -> None:
    """CX-027..CX-032: read glitches are tolerated and bootstrap terminals report."""
    ws = workspace(tmp_path)
    state_dir, env = codex_store(tmp_path, ws, [{"id": "job-1", "epoch": 100}])
    scanner = watchdog.CodexScanner(env=env, proc=watchdog.NullProcInspector())
    machine = watchdog.CodexStateMachine(stall_secs=100, resume_secs=20, gone_polls=2)
    first = scanner.scan([ws], "session-full").records
    assert machine.evaluate(first, now=100, build_active=no_build) == []
    job_file = state_dir / "jobs" / "job-1.json"
    job_file.write_text("{", encoding="utf-8")
    os.utime(job_file, (101, 101))
    assert (
        machine.evaluate(
            scanner.scan([ws], "session-full").records,
            now=101,
            build_active=no_build,
        )
        == []
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
    assert (
        machine.evaluate(
            scanner.scan([ws], "session-full").records,
            now=102,
            build_active=no_build,
        )
        == []
    )
    job_file.unlink()
    assert (
        machine.evaluate(
            scanner.scan([ws], "session-full").records,
            now=103,
            build_active=no_build,
        )
        == []
    )  # 028
    assert machine.evaluate(
        scanner.scan([ws], "session-full").records,
        now=104,
        build_active=no_build,
    ) == [
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
    assert len(boot.evaluate([terminal], now=100, build_active=no_build)) == 1
    assert boot.evaluate([terminal], now=101, build_active=no_build) == []  # CX-032


def test_cx_033_and_034_namespaces_and_healthy_silence() -> None:
    """CX-033/CX-034: Claude grammar is isolated and combined health is silent."""
    claude = watchdog.ClaudeStateMachine(
        stall_secs=100, resume_secs=20, gone_polls=2, build_active=no_build
    )
    codex = watchdog.CodexStateMachine(stall_secs=100, resume_secs=20, gone_polls=2)
    assert claude.evaluate_named("bilby", 100, Path("/work"), {"bilby"}, 100) == []
    assert codex.evaluate([record(activity=100)], now=100, build_active=no_build) == []
    lines = claude.evaluate_named("bilby", 100, Path("/work"), {"bilby"}, 200)
    assert lines == ["STALL agent=bilby idle=100s reason=owns-in_progress-idle"]
    assert all(not line.startswith("CODEX_") for line in lines)


def test_cx_035_no_gone_still_allows_stall() -> None:
    """CX-035: --no-gone disables only death classification."""
    machine = watchdog.CodexStateMachine(
        stall_secs=100, resume_secs=20, gone_polls=2, gone_enabled=False
    )
    assert (
        machine.evaluate([record(runtime="dead")], now=100, build_active=no_build) == []
    )
    assert machine.evaluate([record(runtime="dead")], now=200, build_active=no_build)[
        0
    ].startswith("CODEX_STALL ")


def test_cx_036_gone_job_is_fully_forgotten_after_grace() -> None:
    """CX-036: GONE jobs leave every per-job structure after grace."""
    machine = watchdog.CodexStateMachine(stall_secs=100, resume_secs=20, gone_polls=2)
    active = record(activity=100)
    key = active.key

    assert machine.evaluate([active], now=100, build_active=no_build) == []
    assert machine.evaluate([], now=101, build_active=no_build) == []
    assert machine.evaluate([], now=102, build_active=no_build) == [
        "CODEX_GONE job=job-1 workspace=repo-abc123 reason=record-missing"
    ]
    machine.reported.add(key)
    assert machine.evaluate([], now=103, build_active=no_build) == []
    assert machine.evaluate([], now=104, build_active=no_build) == []

    assert key not in machine.state
    assert key not in machine.misses
    assert key not in machine.reported
    assert key not in machine.gone_hits


def test_cx_037_completed_job_cycles_keep_per_job_state_bounded() -> None:
    """CX-037: completed and forgotten jobs do not accumulate state."""
    machine = watchdog.CodexStateMachine(stall_secs=100, resume_secs=20, gone_polls=2)

    for index in range(100):
        done = record(job_id=f"job-{index}", status="done", phase="done")
        assert machine.evaluate([done], now=index * 3, build_active=no_build) == [
            f"CODEX_DONE job=job-{index} workspace=repo-abc123 phase=done"
        ]
        assert machine.evaluate([], now=index * 3 + 1, build_active=no_build) == []
        assert machine.evaluate([], now=index * 3 + 2, build_active=no_build) == []

    assert machine.state == {}
    assert machine.misses == {}
    assert machine.reported == set()
    assert machine.gone_hits == {}


def test_cx_038_pruned_job_reappears_with_fresh_transition_edges() -> None:
    """CX-038: a pruned job reappears fresh without changing event edges."""
    machine = watchdog.CodexStateMachine(stall_secs=100, resume_secs=20, gone_polls=2)
    active = record(activity=100)

    assert machine.evaluate([active], now=100, build_active=no_build) == []
    assert machine.evaluate([], now=101, build_active=no_build) == []
    assert machine.evaluate([], now=102, build_active=no_build) == [
        "CODEX_GONE job=job-1 workspace=repo-abc123 reason=record-missing"
    ]
    assert machine.evaluate([], now=103, build_active=no_build) == []
    assert machine.evaluate([], now=104, build_active=no_build) == []

    assert machine.evaluate([active], now=200, build_active=no_build) == []
    assert machine.evaluate([active], now=200, build_active=no_build) == [
        "CODEX_STALL job=job-1 workspace=repo-abc123 idle=100s "
        "phase=running reason=no-progress"
    ]
    done = record(status="done", phase="done")
    assert machine.evaluate([done], now=201, build_active=no_build) == [
        "CODEX_DONE job=job-1 workspace=repo-abc123 phase=done"
    ]


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


def test_member_activity_finds_slug_named_git_worktree(tmp_path: Path) -> None:
    """Member clocks use slug-named Git worktrees before the shared lead cwd."""
    wt_root = tmp_path / "worktrees"
    wt = wt_root / "home-ubuntu-git-claudius-bilby"
    cwd = workspace(tmp_path)
    touch(wt / ".git", 50)
    touch(wt / "work.py", 100)
    os.utime(wt, (90, 90))
    touch(cwd / "lead-work.py", 200)
    member = watchdog.Member("bilby", cwd, "aid", "developer", "", "")

    activity = watchdog.member_activity(member, wt_root, {cwd: 1}, {})

    assert activity == watchdog.Activity(100, wt)


def test_cwd_activity_clock_prunes_git_metadata(tmp_path: Path) -> None:
    """Repository metadata churn does not refresh the cwd activity clock."""
    cwd = workspace(tmp_path)
    touch(cwd / "work.py", 100)
    touch(cwd / ".git" / "index.lock", 200)
    os.utime(cwd / ".git", (200, 200))
    os.utime(cwd, (50, 50))

    assert watchdog.newest_mtime_under(cwd, exclude_git=True) == 100
    assert watchdog.newest_mtime_cwd(cwd) == 100


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


def test_member_transcript_type_and_cwd_fallbacks_reject_ambiguity(
    tmp_path: Path,
) -> None:
    """Type metadata and cwd slugs resolve uniquely; multiple sessions do not."""
    projects = tmp_path / "projects"
    cwd = workspace(tmp_path)
    subagent = projects / "slug" / "lead-full" / "subagents" / "agent-sub.jsonl"
    subagent.parent.mkdir(parents=True)
    subagent.write_text('{"type":"message"}\n', encoding="utf-8")
    write_json(
        subagent.with_suffix(".meta.json"),
        {"agentType": "developer-bilby"},
    )
    slug_name = re.sub(r"[^A-Za-z0-9-]", "-", str(cwd).rstrip("/"))
    slug_dir = projects / slug_name
    slug_dir.mkdir(parents=True)
    fallback = slug_dir / "worker-adams.jsonl"
    fallback.write_text(
        '{"type":"agent-setting","agentSetting":"reviewer-adams",'
        '"sessionId":"worker-adams"}\n',
        encoding="utf-8",
    )
    for session_id in ("worker-smythe-a", "worker-smythe-b"):
        (slug_dir / f"{session_id}.jsonl").write_text(
            '{"type":"agent-setting","agentSetting":"security-smythe",'
            f'"sessionId":"{session_id}"}}\n',
            encoding="utf-8",
        )
    members = (
        watchdog.Member("bilby", cwd, "unmatched-id", "developer-bilby", "", ""),
        watchdog.Member("adams", cwd, "", "reviewer-adams", "", ""),
        watchdog.Member("smythe", cwd, "", "security-smythe", "", ""),
    )
    team = watchdog.Team(
        lead_session_id="lead-full",
        members=members,
        created_at=0,
    )

    assert watchdog.member_transcripts(team, projects, {"other-lead"}) == {
        "bilby": subagent,
        "adams": fallback,
    }


def test_watchdog_task_dir_named_and_unbound_autodetect(tmp_path: Path) -> None:
    """Task discovery uses a team name or the newest unbound session directory."""
    home = tmp_path / "home"
    tasks = home / ".claude" / "tasks"
    named = tasks / "named-team"
    oldest = tasks / "session-old"
    newest = tasks / "session-new"
    for directory, epoch in ((named, 100), (oldest, 200), (newest, 300)):
        directory.mkdir(parents=True)
        os.utime(directory, (epoch, epoch))
    monitor = watchdog.Watchdog(
        watchdog.Options(
            projects_dir=tmp_path / "projects",
            gone_enabled=False,
        ),
        env={"HOME": str(home), "CLAUDE_PLUGIN_DATA": str(tmp_path / "plugin")},
        proc_root=tmp_path / "proc",
    )

    assert monitor._task_dir(watchdog.Team(name="named-team")) == named
    assert monitor._task_dir(None) == newest


def test_watchdog_relative_worktrees_use_team_cwd(tmp_path: Path) -> None:
    """Relative worktrees resolve from the lead, then the first member cwd."""
    lead_cwd = workspace(tmp_path, "lead")
    member_cwd = workspace(tmp_path, "member")
    member = watchdog.Member("bilby", member_cwd, "aid", "developer", "", "")
    monitor = watchdog.Watchdog(
        watchdog.Options(
            projects_dir=tmp_path / "projects",
            worktrees=Path(".claude/worktrees"),
            gone_enabled=False,
        ),
        env={
            "HOME": str(tmp_path / "home"),
            "CLAUDE_PLUGIN_DATA": str(tmp_path / "plugin"),
        },
        proc_root=tmp_path / "proc",
    )

    assert monitor._worktrees(watchdog.Team(lead_cwd=lead_cwd)) == (
        lead_cwd / ".claude" / "worktrees"
    )
    assert monitor._worktrees(watchdog.Team(members=(member,))) == (
        member_cwd / ".claude" / "worktrees"
    )


def test_watchdog_subagent_dirs_autodetect_newest_project_slug(
    tmp_path: Path,
) -> None:
    """Unbound subagent discovery selects sessions below the newest project slug."""
    projects = tmp_path / "projects"
    oldest = projects / "oldest"
    newest = projects / "newest"
    expected = newest / "session-new" / "subagents"
    (oldest / "session-old" / "subagents").mkdir(parents=True)
    expected.mkdir(parents=True)
    os.utime(oldest, (100, 100))
    os.utime(newest, (200, 200))
    monitor = watchdog.Watchdog(
        watchdog.Options(projects_dir=projects, gone_enabled=False),
        env={
            "HOME": str(tmp_path / "home"),
            "CLAUDE_PLUGIN_DATA": str(tmp_path / "plugin"),
        },
        proc_root=tmp_path / "proc",
    )

    assert monitor._subagent_dirs(None) == [expected]


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


def test_tmux_detection_honors_watchdog_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An isolated PATH controls both command lookup and Watchdog detection."""
    empty_bin = tmp_path / "empty-bin"
    fake_bin = tmp_path / "fake-bin"
    empty_bin.mkdir()
    fake_bin.mkdir()
    fake_tmux = fake_bin / "tmux"
    fake_tmux.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_tmux.chmod(0o755)
    monkeypatch.setenv("PATH", str(empty_bin))
    env = {
        "HOME": str(tmp_path / "home"),
        "CLAUDE_PLUGIN_DATA": str(tmp_path / "plugin"),
        "PATH": str(fake_bin),
    }

    assert watchdog._command_exists("tmux", env)
    assert not watchdog._command_exists("tmux")
    monitor = watchdog.Watchdog(
        watchdog.Options(), env=env, proc_root=tmp_path / "proc"
    )
    assert monitor.have_tmux


def test_watchdog_warns_when_no_team_has_matching_swarm_socket(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """GONE diagnostics run even when the selected team has no members."""
    monkeypatch.setattr(watchdog, "_command_exists", lambda *_: True)
    home = tmp_path / "home"
    monitor = watchdog.Watchdog(
        watchdog.Options(
            projects_dir=tmp_path / "projects",
            worktrees=tmp_path / "worktrees",
        ),
        env={"HOME": str(home), "CLAUDE_PLUGIN_DATA": str(tmp_path / "plugin")},
        proc_root=tmp_path / "proc",
    )

    assert monitor.poll_once(now=100) == []
    assert "no matching tmux swarm socket for this team" in capsys.readouterr().err


def test_watchdog_warns_once_when_codex_has_zero_candidates(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Teamless Codex monitoring reports its empty candidate blind spot once."""
    home = tmp_path / "home"
    worktrees = tmp_path / "worktrees"
    worktrees.mkdir()
    monitor = watchdog.Watchdog(
        watchdog.Options(
            session_id="session-full",
            projects_dir=tmp_path / "projects",
            worktrees=worktrees,
            gone_enabled=False,
        ),
        env={"HOME": str(home), "CLAUDE_PLUGIN_DATA": str(tmp_path / "plugin")},
        proc_root=tmp_path / "proc",
    )

    assert monitor.poll_once(now=100) == []
    assert monitor.poll_once(now=101) == []

    captured = capsys.readouterr()
    assert captured.out == ""
    assert set(monitor.warned) == {"zero-monitored"}
    assert captured.err == (
        "agent-watchdog: monitoring 0 Claude agents and 0 Codex jobs/workspaces: "
        "no team config, no discovered worktrees, and no session-workspace Codex "
        "state; dispatch a named teammate or verify --worktrees, --session-id, and "
        "the watchdog working directory.\n"
    )


def test_watchdog_zero_candidates_warning_names_the_real_cause(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A team lacking any usable cwd is not blamed on a missing team config."""
    home = tmp_path / "home"
    worktrees = tmp_path / "worktrees"
    worktrees.mkdir()
    team_dir = home / ".claude" / "teams" / "session-short"
    write_json(
        team_dir / "config.json",
        {
            "name": "session-short",
            "leadSessionId": "session-full",
            "members": [
                {"agentType": "team-lead", "name": "lead", "isActive": True},
                {
                    "agentType": "developer-bilby",
                    "name": "bilby",
                    "agentId": "aid",
                    "cwd": str(tmp_path / "finished"),
                    "isActive": False,
                },
            ],
        },
    )
    monitor = watchdog.Watchdog(
        watchdog.Options(
            team_dir=team_dir,
            session_id="session-full",
            projects_dir=tmp_path / "projects",
            worktrees=worktrees,
            gone_enabled=False,
        ),
        env={"HOME": str(home), "CLAUDE_PLUGIN_DATA": str(tmp_path / "plugin")},
        proc_root=tmp_path / "proc",
    )

    assert monitor.poll_once(now=100) == []

    err = capsys.readouterr().err
    assert "codex-zero-candidates" in monitor.warned
    assert "no team config" not in err
    assert "a team config with no active member or lead cwd" in err
    assert "dispatch a NAMED teammate that reports a cwd" in err


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


def test_watchdog_poll_preserves_claude_event_when_codex_job_is_invalid(
    tmp_path: Path,
) -> None:
    """A malformed Codex job cannot blank an unrelated Claude transition."""
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
                }
            ],
        },
    )
    tasks = tmp_path / "tasks"
    write_json(tasks / "1.json", {"status": "in_progress", "owner": "bilby"})
    _, env = codex_store(
        tmp_path,
        ws,
        [{"id": "invalid-root", "workspaceRoot": "invalid\0root"}],
    )
    env["HOME"] = str(home)
    monitor = watchdog.Watchdog(
        watchdog.Options(
            team_dir=team_dir,
            tasks_dir=tasks,
            projects_dir=tmp_path / "projects",
            worktrees=worktrees,
            gone_enabled=False,
            stall_secs=100,
            resume_secs=20,
        ),
        env=env,
        proc_root=tmp_path / "proc",
    )

    assert monitor.poll_once(now=200) == [
        "STALL agent=bilby idle=100s reason=owns-in_progress-idle"
    ]


def test_source_c_discovers_slug_named_git_worktree(tmp_path: Path) -> None:
    """Source C includes real worktrees whose directory lacks an agent- prefix."""
    worktrees = tmp_path / "worktrees"
    slug = "home-ubuntu-git-claudius-fix-x"
    worktree = worktrees / slug
    touch(worktree / ".git", 50)
    touch(worktree / "work", 100)
    os.utime(worktree, (100, 100))
    tasks = tmp_path / "tasks"
    write_json(tasks / "1.json", {"status": "in_progress", "owner": slug})
    monitor = watchdog.Watchdog(
        watchdog.Options(
            tasks_dir=tasks,
            projects_dir=tmp_path / "projects",
            worktrees=worktrees,
            gone_enabled=False,
            stall_secs=100,
            resume_secs=20,
        ),
        env={
            "HOME": str(tmp_path / "home"),
            "CLAUDE_PLUGIN_DATA": str(tmp_path / "plugin"),
        },
        proc_root=tmp_path / "proc",
    )

    assert monitor.poll_once(now=200) == [
        f"STALL agent={slug} idle=100s reason=owns-in_progress-idle"
    ]


def test_teamless_watchdog_discovers_codex_state_from_session_cwd(
    tmp_path: Path,
) -> None:
    """Codex state discovery does not depend on team or worktree mappings."""
    ws = workspace(tmp_path)
    _, env = codex_store(
        tmp_path,
        ws,
        [{"id": "teamless", "epoch": 100, "updatedAt": None}],
        state_epoch=100,
    )
    env["PWD"] = str(ws)
    worktrees = tmp_path / "worktrees"
    worktrees.mkdir()
    monitor = watchdog.Watchdog(
        watchdog.Options(
            session_id="session-full",
            projects_dir=tmp_path / "projects",
            worktrees=worktrees,
            gone_enabled=False,
            stall_secs=50,
            resume_secs=20,
        ),
        env=env,
        proc_root=tmp_path / "proc",
    )

    assert monitor.poll_once(now=200) == []
    assert monitor.poll_once(now=201) == [
        "CODEX_STALL job=teamless "
        f"workspace={watchdog.resolve_workspace(ws, env).key} "
        "idle=101s phase=running reason=no-progress"
    ]
    assert "zero-monitored" not in monitor.warned


def test_direct_workspace_surfaces_jobs_from_multiple_foreign_sessions(
    tmp_path: Path,
) -> None:
    """Direct workspace ownership includes jobs from every dispatch session."""
    worktrees = tmp_path / "worktrees"
    worktrees.mkdir()
    ws = workspace(worktrees, "agent-rescue")
    _, env = codex_store(
        tmp_path,
        ws,
        [
            {
                "id": "worker-one",
                "sessionId": "worker-session-one",
                "epoch": 100,
                "updatedAt": None,
            },
            {
                "id": "worker-two",
                "sessionId": "worker-session-two",
                "epoch": 100,
                "updatedAt": None,
            },
        ],
        state_epoch=100,
    )
    monitor = watchdog.Watchdog(
        watchdog.Options(
            session_id="coordinator-session",
            projects_dir=tmp_path / "projects",
            worktrees=worktrees,
            gone_enabled=False,
            stall_secs=50,
            resume_secs=20,
        ),
        env=env,
        proc_root=tmp_path / "proc",
    )

    assert monitor.poll_once(now=200) == []
    key = watchdog.resolve_workspace(ws, env).key
    assert monitor.poll_once(now=201) == [
        f"CODEX_STALL job=worker-one workspace={key} "
        "idle=101s phase=running reason=no-progress",
        f"CODEX_STALL job=worker-two workspace={key} "
        "idle=101s phase=running reason=no-progress",
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


def test_unreadable_unrelated_proc_does_not_suppress_stall(tmp_path: Path) -> None:
    """An exited unrelated process cannot silence either stall transition."""
    proc = tmp_path / "proc"
    watched = workspace(tmp_path, "watched")
    process = proc / "999"
    process.mkdir(parents=True)
    (process / "cwd").symlink_to(watched, target_is_directory=True)

    def build_active(directory: Path) -> bool:
        return watchdog.build_status_under(directory, proc)

    assert build_active(watched) is False
    assert watchdog.build_status_under(watched, tmp_path / "missing-proc") is False
    claude = watchdog.ClaudeStateMachine(
        stall_secs=100,
        resume_secs=20,
        gone_polls=2,
        build_active=build_active,
    )
    assert claude.evaluate_named("bilby", 100, watched, {"bilby"}, 200) == [
        "STALL agent=bilby idle=100s reason=owns-in_progress-idle"
    ]
    codex = watchdog.CodexStateMachine(stall_secs=100, resume_secs=20, gone_polls=2)
    assert (
        codex.evaluate([record(activity=100)], now=100, build_active=build_active) == []
    )
    assert codex.evaluate(
        [record(activity=100)], now=200, build_active=build_active
    ) == [
        "CODEX_STALL job=job-1 workspace=repo-abc123 idle=100s "
        "phase=running reason=no-progress"
    ]


def test_build_oracle_error_does_not_suppress_stall() -> None:
    """A build-oracle read error is a negative confirmation, not silence."""

    def failed_build(_: Path) -> bool:
        raise OSError("proc scan raced")

    claude = watchdog.ClaudeStateMachine(
        stall_secs=100,
        resume_secs=20,
        gone_polls=2,
        build_active=failed_build,
    )
    assert claude.evaluate_named("bilby", 100, Path("/work"), {"bilby"}, 200) == [
        "STALL agent=bilby idle=100s reason=owns-in_progress-idle"
    ]
    codex = watchdog.CodexStateMachine(stall_secs=100, resume_secs=20, gone_polls=2)
    stale = record(activity=100)
    assert codex.evaluate([stale], now=100, build_active=failed_build) == []
    assert codex.evaluate([stale], now=200, build_active=failed_build) == [
        "CODEX_STALL job=job-1 workspace=repo-abc123 idle=100s "
        "phase=running reason=no-progress"
    ]


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


def test_team_autodetect_ignores_unreadable_candidate_mtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Autodetect keeps the newest readable candidate after one stat failure."""
    teams = tmp_path / "teams"
    newest = teams / "session-a"
    unreadable = teams / "session-b"
    oldest = teams / "session-z"
    write_json(newest / "config.json", {"leadSessionId": "newest"}, 300)
    write_json(unreadable / "config.json", {"leadSessionId": "unreadable"}, 200)
    write_json(oldest / "config.json", {"leadSessionId": "oldest"}, 100)
    os.utime(newest, (300, 300))
    os.utime(unreadable, (200, 200))
    os.utime(oldest, (100, 100))
    original_stat = Path.stat

    def selective_stat(path: Path, *args: Any, **kwargs: Any) -> os.stat_result:
        if path == unreadable:
            raise OSError("candidate disappeared")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", selective_stat)
    assert watchdog.select_team(teams, None, "").directory == newest


def test_claude_stall_resume_gone_confirmation() -> None:
    """Claude transitions are edge-triggered and require consecutive misses."""
    machine = watchdog.ClaudeStateMachine(
        stall_secs=100, resume_secs=20, gone_polls=2, build_active=no_build
    )
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
    machine = watchdog.ClaudeStateMachine(
        stall_secs=100, resume_secs=20, gone_polls=1, build_active=no_build
    )
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


def test_cli_zero_arguments_exit_1(tmp_path: Path) -> None:
    """The executable rejects a silent default-only invocation."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        text=True,
        capture_output=True,
        check=False,
        env={"HOME": str(tmp_path / "home"), "PATH": os.environ["PATH"]},
        timeout=5,
    )
    assert result.returncode == 1
    assert "Usage: agent-watchdog.py" in result.stderr
    assert (
        "agent-watchdog: no arguments provided; use explicit flags or --help"
        in result.stderr
    )


def test_cli_preserves_all_flags_and_defaults(tmp_path: Path) -> None:
    """Every Bash flag and default remains available on the Python CLI."""
    defaults = watchdog.parse_args(
        ["--session-id", "env"],
        {"HOME": str(tmp_path), "CLAUDE_SESSION_ID": "environment"},
    )
    assert (
        defaults.session_id,
        defaults.worktrees,
        defaults.stall_secs,
        defaults.resume_secs,
        defaults.gone_polls,
        defaults.poll_secs,
        defaults.watch_subagents,
        defaults.gone_enabled,
    ) == ("env", Path(".claude/worktrees"), 300, 60, 2, 45, False, True)
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
            "--codex-job-recency-secs",
            "3600",
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
    assert options.codex_job_recency_secs == 3600
    assert options.watch_subagents and not options.gone_enabled


def test_cli_worktree_root_env_var(tmp_path: Path) -> None:
    """Explicit worktree roots override nonblank environment roots and defaults."""
    base_env = {"HOME": str(tmp_path)}

    assert watchdog.parse_args(["--session-id", "test"], base_env).worktrees == Path(
        ".claude/worktrees"
    )
    assert watchdog.parse_args(
        ["--session-id", "test"],
        {**base_env, "CLAUDIUS_WORKTREE_ROOT": "/custom/root"},
    ).worktrees == Path("/custom/root")
    for value in ("", "   \t"):
        assert watchdog.parse_args(
            ["--session-id", "test"],
            {**base_env, "CLAUDIUS_WORKTREE_ROOT": value},
        ).worktrees == Path(".claude/worktrees")
    assert watchdog.parse_args(
        ["--session-id", "test", "--worktrees", "/explicit/path"],
        {**base_env, "CLAUDIUS_WORKTREE_ROOT": "/env/root"},
    ).worktrees == Path("/explicit/path")


def test_main_deduplicates_and_sanitizes_poll_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Repeated poll exceptions emit one bounded, escaped diagnostic."""
    monitor = watchdog.Watchdog(
        watchdog.Options(
            projects_dir=tmp_path / "projects",
            worktrees=tmp_path / "worktrees",
            gone_enabled=False,
        ),
        env={
            "HOME": str(tmp_path / "home"),
            "CLAUDE_PLUGIN_DATA": str(tmp_path / "plugin"),
        },
        proc_root=tmp_path / "proc",
    )
    polls = 0

    def fail_poll() -> list[str]:
        nonlocal polls
        polls += 1
        raise OSError("bad line\n\x1b[31mcontrol")

    def stop_after_two_polls(_seconds: int) -> None:
        if polls >= 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(monitor, "poll_once", fail_poll)
    monkeypatch.setattr(watchdog, "Watchdog", lambda _options: monitor)
    monkeypatch.setattr(watchdog.time, "sleep", stop_after_two_polls)

    with pytest.raises(KeyboardInterrupt):
        watchdog.main(["--session-id", "test", "--no-gone", "--poll-secs", "1"])

    stderr = capsys.readouterr().err
    assert stderr.count("transient poll failure ignored (OSError:") == 1
    assert "bad line\n\x1b[31mcontrol" not in stderr
    assert '"bad line \\u001b[31mcontrol"' in stderr


def test_cli_requires_at_least_one_argument(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Empty argv prints usage and a stable actionable diagnostic."""
    with pytest.raises(SystemExit) as caught:
        watchdog.parse_args([], {"HOME": "/tmp"})
    assert caught.value.code == 1
    stderr = capsys.readouterr().err
    assert "Usage: agent-watchdog.py" in stderr
    assert (
        "agent-watchdog: no arguments provided; use explicit flags or --help" in stderr
    )


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["--unknown"], "unknown argument"),
        (["--team-dir"], "needs a value"),
        (["--gone-polls", "x"], "expects a non-negative integer"),
        (["--gone-polls", "0"], "must be >= 1"),
        (["--codex-job-recency-secs", "0"], "must be >= 1"),
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
