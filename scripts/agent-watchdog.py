#!/usr/bin/env python3
"""Edge-triggered Claude and Codex multi-agent stall watchdog.

Claude named agents stall only while owning an ``in_progress`` task, their
per-agent activity clock is at or beyond the threshold, and no build/test runs
under their own workspace. Activity resolves in order from an isolated
worktree, to an unshared cwd excluding ``.git``, to the agent's own transcript.
Anonymous transcript monitoring remains opt-in. Tmux GONE detection binds one
session's swarm socket positively by pane ID and agent type before trusting pane
absence, and all disappearance signals require consecutive confirmation.

Codex Companion jobs are a separate Source D state machine. Candidate state
directories are derived only from the selected team's lead, active members,
and Source C worktrees. Detailed records must match both the effective Claude
session and canonical workspace. Healthy work is silent; terminal status,
stall, recovery, verified runtime disappearance, and confirmed record removal
emit only the documented transition grammar.

Stdout is a hard protocol: it contains transition lines only. Startup details,
selection notes, unsupported private-store formats, and transient diagnostics
go to stderr. Filesystem, JSON, tmux, and /proc read failures never synthesize a
transition on their first occurrence, and missing clocks are never epoch zero.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter, OrderedDict, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Callable, Iterable, Mapping, Sequence


ACTIVE_STATUSES = {"queued", "pending", "running"}
TERMINAL_STATUSES = {
    "completed": "done",
    "failed": "failed",
    "cancelled": "cancelled",
    "canceled": "cancelled",
}
SUPPORTED_STATE_VERSIONS = {1}
STATE_HEADER_LIMIT = 4096
# Per-poll cost scales with the number of retained jobs/*.json files in a
# workspace (the Codex Companion keeps terminal job records on disk). Warn once
# per workspace when enumerating them exceeds this, signalling the directory has
# grown enough to justify pruning old records or a bounded-scan optimization.
JOBS_GLOB_WARN_SECS = 0.5
# Keep active jobs indefinitely, but age terminal records out after six hours.
TERMINAL_JOB_RETENTION_SECS = 6 * 60 * 60
STATE_VERSION_PREFIX = re.compile(r'^\s*\{\s*"version"\s*:\s*')
# Sentinel: the state file is a JSON object but its version could not be read
# from the bounded header (file too large and "version" is not near the start).
# Treated as unsupported so the scanner skips the file loudly instead of
# silently assuming it is the current supported version.
_INDETERMINATE_VERSION = object()
SAFE_FIELD = re.compile(r"^[A-Za-z0-9._-]+$")
SHELL_COMMANDS = {
    "sh",
    "-sh",
    "bash",
    "-bash",
    "zsh",
    "-zsh",
    "dash",
    "-dash",
    "ksh",
    "-ksh",
    "fish",
    "-fish",
    "login",
    "cd",
}
SIMPLE_BUILD_COMMANDS = {
    "rustc",
    "cc1",
    "cc1plus",
    "gcc",
    "g++",
    "clang",
    "clang++",
    "ld",
    "make",
    "cmake",
    "ninja",
    "gradle",
    "gradlew",
    "mvn",
    "mvnw",
    "bazel",
    "tsc",
    "webpack",
    "pytest",
    "jest",
}
SUBCOMMAND_BUILDS = {
    "cargo": {"build", "test", "check", "clippy", "run"},
    "go": {"build", "test", "run"},
    "dotnet": {"build", "test", "run"},
    "pip": {"install"},
    "pip3": {"install"},
}


@dataclass(frozen=True)
class Member:
    """An active non-lead team member."""

    name: str
    cwd: Path | None
    agent_id: str
    agent_type: str
    tmux_pane_id: str
    backend_type: str


@dataclass(frozen=True)
class Team:
    """Parsed team configuration used by all discovery sources."""

    name: str = ""
    lead_session_id: str = ""
    lead_cwd: Path | None = None
    members: tuple[Member, ...] = ()
    created_at: float = 0.0


@dataclass(frozen=True)
class TeamSelection:
    """Result of the multi-session team precedence rules."""

    mode: str
    directory: Path | None
    lead_session_id: str
    candidate_count: int
    other_leads: tuple[str, ...] = ()


@dataclass(frozen=True)
class Activity:
    """One evaluable per-agent clock and its build-detection directory."""

    epoch: int
    directory: Path


@dataclass(frozen=True)
class WorkspaceInfo:
    """Codex Companion workspace mapping derived from state.mjs."""

    root: Path
    canonical: Path
    key: str
    state_dir: Path


@dataclass(frozen=True)
class _StateHeader:
    """Bounded metadata read from a Codex Companion state file."""

    shape_supported: bool
    version: Any = None


@dataclass(frozen=True)
class CodexRecord:
    """Minimal normalized Codex job record consumed by the state machine."""

    key: str
    job_id: str
    workspace_key: str
    workspace_root: Path
    status: str
    phase: str
    activity_epoch: int | None
    runtime: str
    created_at: float
    error_message: str | None = None


@dataclass(frozen=True)
class ScanResult:
    """One isolated Source D scan result."""

    records: list[CodexRecord]
    warnings: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class Options:
    """Validated watchdog command-line configuration."""

    team_dir: Path | None = None
    session_id: str = ""
    tasks_dir: Path | None = None
    projects_dir: Path = field(
        default_factory=lambda: Path.home() / ".claude" / "projects"
    )
    worktrees: Path = Path(".claude/worktrees")
    watch_subagents: bool = False
    gone_enabled: bool = True
    gone_polls: int = 2
    stall_secs: int = 300
    resume_secs: int = 60
    poll_secs: int = 45


def canonical_label(label: str) -> str:
    """Strip one leading ``agent-`` from a Claude agent label."""
    return label[6:] if label.startswith("agent-") else label


def safe_json(path: Path) -> Any | None:
    """Read JSON defensively, returning None for transient failures."""
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def _safe_state_header(path: Path) -> _StateHeader | None:
    """Read the fixed state header without decoding its growing jobs array."""
    try:
        with path.open(encoding="utf-8") as handle:
            prefix = handle.read(STATE_HEADER_LIMIT + 1)
    except (OSError, UnicodeError):
        return None
    sample = prefix[:STATE_HEADER_LIMIT]
    stripped = sample.lstrip()
    if not stripped:
        return None
    if not stripped.startswith("{"):
        # A JSON object must open with "{"; anything else is an unsupported
        # top-level shape regardless of whether the file was truncated.
        return _StateHeader(False)
    truncated = len(prefix) > STATE_HEADER_LIMIT
    match = STATE_VERSION_PREFIX.match(sample)
    if match is not None:
        # Fast path: "version" is the first key, so decode just that scalar
        # without touching the (possibly huge) jobs array — works even when
        # the file is truncated.
        try:
            version, end = json.JSONDecoder().raw_decode(sample, match.end())
        except json.JSONDecodeError:
            return _StateHeader(True, _INDETERMINATE_VERSION)
        remainder = sample[end:].lstrip()
        if not remainder or remainder[0] not in ",}":
            return _StateHeader(True, _INDETERMINATE_VERSION)
        return _StateHeader(True, version)
    if not truncated:
        # The whole object fit in the bounded window, so a full parse is safe
        # and finds "version" wherever it sits among the keys.
        try:
            value = json.loads(prefix)
        except (TypeError, json.JSONDecodeError):
            return None
        if not isinstance(value, dict):
            return _StateHeader(False)
        return _StateHeader(True, value.get("version"))
    # Truncated object and "version" is not near the start: the version is
    # indeterminate. Fail loud — skip the file with a warning rather than
    # silently assuming it is supported.
    return _StateHeader(True, _INDETERMINATE_VERSION)


def safe_mtime(path: Path) -> int | None:
    """Return an integer mtime or None when the path cannot be stated."""
    try:
        return int(path.stat().st_mtime)
    except OSError:
        return None


def newest_mtime_under(directory: Path, exclude_git: bool = False) -> int | None:
    """Return the newest entry mtime below a directory, optionally pruning .git."""
    try:
        if not directory.is_dir():
            return None
    except OSError:
        return None
    try:
        newest: float | None = directory.stat().st_mtime
    except OSError:
        newest = None
    stack = [directory]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if exclude_git and entry.name == ".git":
                        continue
                    try:
                        value = entry.stat(follow_symlinks=False).st_mtime
                        newest = value if newest is None else max(newest, value)
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                    except OSError:
                        continue
        except OSError:
            continue
    return int(newest) if newest is not None else None


def newest_mtime_cwd(directory: Path) -> int | None:
    """Return a cwd activity clock while excluding repository metadata."""
    return newest_mtime_under(directory, exclude_git=True)


def parse_team(config_path: Path) -> Team | None:
    """Parse active members from a team config without exposing partial JSON."""
    value = safe_json(config_path)
    if not isinstance(value, dict):
        return None
    members: list[Member] = []
    lead_cwd: Path | None = None
    for raw in value.get("members", []):
        if not isinstance(raw, dict):
            continue
        if raw.get("agentType") == "team-lead":
            if raw.get("cwd"):
                lead_cwd = Path(str(raw["cwd"]))
            continue
        if raw.get("isActive") is not True or not raw.get("name"):
            continue
        cwd = Path(str(raw["cwd"])) if raw.get("cwd") else None
        members.append(
            Member(
                name=str(raw["name"]),
                cwd=cwd,
                agent_id=str(raw.get("agentId") or ""),
                agent_type=str(raw.get("agentType") or ""),
                tmux_pane_id=str(raw.get("tmuxPaneId") or ""),
                backend_type=str(raw.get("backendType") or ""),
            )
        )
    created = value.get("createdAt") or 0
    try:
        created_at = float(created)
        if created_at > 1e11:
            created_at /= 1000
    except (TypeError, ValueError):
        created_at = 0.0
    return Team(
        name=str(value.get("name") or ""),
        lead_session_id=str(value.get("leadSessionId") or ""),
        lead_cwd=lead_cwd,
        members=tuple(members),
        created_at=created_at,
    )


def _prefix_matches(left: str, right: str) -> bool:
    return bool(
        left
        and right
        and (left == right or left.startswith(right) or right.startswith(left))
    )


def select_team(
    teams_dir: Path,
    explicit_team_dir: Path | None,
    session_id: str,
) -> TeamSelection:
    """Select one team using explicit, session, then newest-mtime precedence."""
    candidates: list[Path] = []
    try:
        candidates = sorted(
            path
            for path in teams_dir.glob("session-*")
            if (path / "config.json").is_file()
        )
    except OSError:
        pass

    def lead(path: Path) -> str:
        team = parse_team(path / "config.json")
        return team.lead_session_id if team else ""

    selected: Path | None = None
    mode = "none"
    if explicit_team_dir is not None:
        selected = explicit_team_dir
        mode = "explicit"
    elif session_id:
        for candidate in candidates:
            suffix = candidate.name[len("session-") :]
            if _prefix_matches(suffix, session_id):
                selected = candidate
                break
        if selected is None:
            for candidate in candidates:
                if _prefix_matches(lead(candidate), session_id):
                    selected = candidate
                    break
        mode = "matched" if selected else "none"
    elif candidates:

        def mtime(path: Path) -> float:
            try:
                return path.stat().st_mtime
            except OSError:
                return 0.0

        selected = max(candidates, key=mtime)
        mode = "autodetect"
    selected_real = os.path.realpath(selected) if selected else ""
    others = tuple(
        candidate_lead
        for candidate in candidates
        if os.path.realpath(candidate) != selected_real
        for candidate_lead in [lead(candidate)]
        if candidate_lead
    )
    return TeamSelection(
        mode,
        selected,
        lead(selected) if selected else "",
        len(candidates),
        others,
    )


def build_owners(tasks_dir: Path | None) -> set[str]:
    """Read owners of in-progress tasks from one session-scoped task store."""
    if tasks_dir is None:
        return set()
    owners: set[str] = set()
    try:
        paths = tasks_dir.glob("*.json")
        for path in paths:
            task = safe_json(path)
            if isinstance(task, dict) and task.get("status") == "in_progress":
                owner = task.get("owner")
                if owner:
                    owners.add(str(owner))
    except OSError:
        pass
    return owners


def owns_work(label: str, owners: set[str]) -> bool:
    """Match canonical and agent-prefixed task owners."""
    return label in owners or f"agent-{label}" in owners


def member_activity(
    member: Member,
    worktrees_dir: Path,
    cwd_counts: Mapping[Path, int],
    transcript_map: Mapping[str, Path],
) -> Activity | None:
    """Resolve worktree, cwd, then transcript activity for one team member."""
    key = canonical_label(member.name)
    worktree = worktrees_dir / f"agent-{key}"
    if worktree.is_dir():
        epoch = newest_mtime_under(worktree)
        return Activity(epoch, worktree) if epoch is not None else None
    if member.cwd and cwd_counts.get(member.cwd, 0) >= 2:
        transcript = transcript_map.get(key)
        epoch = safe_mtime(transcript) if transcript else None
        return Activity(epoch, member.cwd) if epoch is not None else None
    if member.cwd:
        epoch = newest_mtime_cwd(member.cwd)
        return Activity(epoch, member.cwd) if epoch is not None else None
    return None


def _basename(value: str) -> str:
    return os.path.basename(value.rstrip("/"))


def is_build_command(argv: Sequence[str]) -> bool:
    """Recognize anchored build/test argv, unwrapping one interpreter layer."""
    if not argv:
        return False
    index = 0
    if _basename(argv[0]) == "env":
        index = 1
        while index < len(argv) and (argv[index].startswith("-") or "=" in argv[index]):
            index += 1
    if index >= len(argv):
        return False
    command = _basename(argv[index])
    if command in {
        "sh",
        "bash",
        "dash",
        "zsh",
        "ksh",
        "perl",
        "ruby",
        "node",
        "nodejs",
    }:
        index += 1
    elif command in {"python", "python2", "python3"}:
        if index + 1 < len(argv) and argv[index + 1] == "-m":
            module = _basename(argv[index + 2]) if index + 2 < len(argv) else ""
            if module in {"pytest", "build"}:
                return True
            if module == "pip":
                return index + 3 < len(argv) and _basename(argv[index + 3]) == "install"
            return False
        index += 1
    if index >= len(argv):
        return False
    command = _basename(argv[index])
    if command in SIMPLE_BUILD_COMMANDS:
        return True
    subcommand = _basename(argv[index + 1]) if index + 1 < len(argv) else ""
    return subcommand in SUBCOMMAND_BUILDS.get(command, set())


def _try_read_cmdline(path: Path) -> list[str] | None:
    try:
        return [
            item.decode(errors="replace")
            for item in path.read_bytes().split(b"\0")
            if item
        ]
    except OSError:
        return None


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def build_status_under(directory: Path, proc_root: Path = Path("/proc")) -> bool:
    """Return whether a build is positively confirmed under the workspace."""
    try:
        processes = proc_root.iterdir()
        for process in processes:
            if not process.name.isdigit():
                continue
            try:
                cwd = (process / "cwd").resolve(strict=True)
            except OSError:
                continue
            if not _is_under(cwd, directory):
                continue
            argv = _try_read_cmdline(process / "cmdline")
            if argv is None:
                continue
            if is_build_command(argv):
                return True
    except OSError:
        return False
    return False


def build_active_under(directory: Path, proc_root: Path = Path("/proc")) -> bool:
    """Return whether a build is positively active under the workspace."""
    return build_status_under(directory, proc_root)


def write_fake_process(
    proc_root: Path, pid: int, cwd: Path, argv: Sequence[str]
) -> None:
    """Create an isolated proc-style fixture for tests."""
    cwd.mkdir(parents=True, exist_ok=True)
    process = proc_root / str(pid)
    process.mkdir(parents=True, exist_ok=True)
    (process / "cwd").symlink_to(cwd, target_is_directory=True)
    (process / "cmdline").write_bytes(b"\0".join(x.encode() for x in argv) + b"\0")


class ProcInspector:
    """Read compatible Codex launcher and broker evidence from a proc filesystem."""

    def __init__(self, proc_root: Path = Path("/proc")) -> None:
        self.proc_root = proc_root

    def _evidence(
        self,
        pid: Any,
        workspace: Path,
        required_fragment: str,
        endpoint: str = "",
        require_workspace: bool = True,
    ) -> str | None:
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            return None
        process = self.proc_root / str(pid)
        try:
            process.stat()
        except FileNotFoundError:
            return "dead"
        except OSError:
            return None
        argv = _try_read_cmdline(process / "cmdline")
        if argv is None:
            return None
        try:
            cwd = (process / "cwd").resolve(strict=True)
        except OSError:
            return None
        command_matches = any(
            _basename(argument) == required_fragment for argument in argv
        )
        compatible = command_matches and (
            _is_under(cwd, workspace) or not require_workspace
        )
        if endpoint:
            endpoint_parent = str(Path(endpoint).parent)
            joined = "\0".join(argv)
            compatible = compatible and (
                endpoint in joined
                or endpoint_parent in joined
                or _is_under(cwd, Path(endpoint_parent))
            )
        return "alive" if compatible else "dead"

    def launcher(self, pid: Any, workspace: Path) -> str | None:
        """Classify one persisted job launcher PID."""
        return self._evidence(pid, workspace, "codex-companion.mjs")

    def broker(self, record: Mapping[str, Any] | None, workspace: Path) -> str | None:
        """Classify one persisted broker PID."""
        if not isinstance(record, Mapping):
            return None
        endpoint = str(record.get("endpoint") or "")
        if not endpoint:
            return None
        return self._evidence(
            record.get("pid"),
            workspace,
            "app-server-broker.mjs",
            endpoint,
            False,
        )


class NullProcInspector(ProcInspector):
    """Proc inspector returning unknown evidence, useful for isolated scans."""

    def __init__(self) -> None:
        super().__init__(Path("/nonexistent"))

    def launcher(self, pid: Any, workspace: Path) -> str | None:
        return None

    def broker(self, record: Mapping[str, Any] | None, workspace: Path) -> str | None:
        return None


def classify_runtime(
    launcher_evidence: Iterable[str | None],
    broker_evidence: Iterable[str | None],
) -> str:
    """Combine available liveness evidence into alive, dead, or unknown."""
    evidence = [
        value
        for value in [*launcher_evidence, *broker_evidence]
        if value in {"alive", "dead"}
    ]
    if "alive" in evidence:
        return "alive"
    if evidence and all(value == "dead" for value in evidence):
        return "dead"
    return "unknown"


def git_toplevel(candidate: Path) -> Path | None:
    """Resolve a Git workspace root without invoking a shell."""
    try:
        result = subprocess.run(
            ["git", "-C", str(candidate), "rev-parse", "--show-toplevel"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip()
    return Path(value) if result.returncode == 0 and value else None


def sha256_path(canonical: Path) -> str:
    """Hash the exact canonical workspace string as state.mjs does."""
    return hashlib.sha256(str(canonical).encode()).hexdigest()[:16]


def workspace_key(workspace_root: Path, canonical: Path) -> str:
    """Build the sanitized basename plus canonical-path hash state key."""
    source = workspace_root.name or "workspace"
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", source).strip("-") or "workspace"
    return f"{slug}-{sha256_path(canonical)}"


def codex_state_root(env: Mapping[str, str] | None = None) -> Path:
    """Resolve CLAUDE_PLUGIN_DATA or Node-compatible temporary state root."""
    environment = os.environ if env is None else env
    plugin_data = environment.get("CLAUDE_PLUGIN_DATA", "")
    if plugin_data:
        return Path(plugin_data) / "state"
    for variable in ("TMPDIR", "TMP", "TEMP"):
        if environment.get(variable):
            return Path(environment[variable]) / "codex-companion"
    return Path("/tmp") / "codex-companion"


def resolve_workspace(
    candidate: Path, env: Mapping[str, str] | None = None
) -> WorkspaceInfo:
    """Map a monitored path forward to its Codex Companion state directory."""
    root = git_toplevel(candidate) or candidate
    try:
        canonical = root.resolve(strict=True)
    except OSError:
        canonical = Path(os.path.realpath(root))
    key = workspace_key(root, canonical)
    return WorkspaceInfo(root, canonical, key, codex_state_root(env) / key)


def _parse_timestamp(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        return int(number / 1000 if number > 1e11 else number)
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp())
    except ValueError:
        return None


def _safe_phase(value: Any) -> str:
    phase = str(value or "unknown")
    return phase if SAFE_FIELD.fullmatch(phase) else "unknown"


class _JsonCache:
    """Bounded mtime-gated JSON cache for the long-lived poller."""

    def __init__(self, limit: int = 512) -> None:
        self.limit = limit
        self.items: OrderedDict[Path, tuple[tuple[int, int], Any]] = OrderedDict()

    def read(
        self, path: Path, projector: Callable[[Any], Any] | None = None
    ) -> Any | None:
        try:
            stat = path.stat()
            signature = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            self.items.pop(path, None)
            return None
        cached = self.items.get(path)
        if cached and cached[0] == signature:
            self.items.move_to_end(path)
            return cached[1]
        value = safe_json(path)
        if value is None:
            return None
        if projector is not None:
            value = projector(value)
        self.items[path] = (signature, value)
        self.items.move_to_end(path)
        while len(self.items) > self.limit:
            self.items.popitem(last=False)
        return value


class _StateHeaderCache:
    """Bounded mtime-gated cache of state.json headers for the long-lived poller."""

    def __init__(self, limit: int = 512) -> None:
        self.limit = limit
        self.items: OrderedDict[Path, tuple[tuple[int, int], _StateHeader]] = (
            OrderedDict()
        )

    def read(self, state_dir: Path, state_path: Path) -> _StateHeader | None:
        try:
            stat = state_path.stat()
            signature = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            self.items.pop(state_dir, None)
            return None
        # Gate on the state.json file's own mtime/size, like _JsonCache — the
        # directory inode is stable across in-place rewrites, so keying on it
        # would pin the first version read for the process's lifetime and
        # defeat the version guard on every later poll.
        cached = self.items.get(state_dir)
        if cached and cached[0] == signature:
            self.items.move_to_end(state_dir)
            return cached[1]
        header = _safe_state_header(state_path)
        if header is None:
            return None
        self.items[state_dir] = (signature, header)
        self.items.move_to_end(state_dir)
        while len(self.items) > self.limit:
            self.items.popitem(last=False)
        return header


class CodexScanner:
    """Discover minimal session-scoped Source D job records."""

    def __init__(
        self,
        env: Mapping[str, str] | None = None,
        proc: ProcInspector | None = None,
        cache_limit: int = 512,
    ) -> None:
        self.env = dict(os.environ if env is None else env)
        self.proc = proc or ProcInspector()
        self.cache = _JsonCache(cache_limit)
        self.state_headers = _StateHeaderCache(cache_limit)
        self.warned: set[str] = set()

    def _warning(self, key: str, message: str, warnings: list[tuple[str, str]]) -> None:
        if key not in self.warned:
            self.warned.add(key)
            warnings.append((key, message))

    def _session(
        self,
        requested: str,
        values: set[str],
        warnings: list[tuple[str, str]],
    ) -> str:
        if not requested:
            return ""
        if requested in values or not values:
            return requested
        matches = sorted(value for value in values if _prefix_matches(value, requested))
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            self._warning(
                f"codex-session-ambiguous:{requested}",
                f"Codex Source D disabled: session prefix {requested!r} matches "
                f"{len(matches)} job sessions in monitored workspaces",
                warnings,
            )
        return ""

    @staticmethod
    def _minimal_job(value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        fields = (
            "id",
            "sessionId",
            "workspaceRoot",
            "status",
            "phase",
            "updatedAt",
            "createdAt",
            "pid",
            "logFile",
            "errorMessage",
        )
        return {field: value.get(field) for field in fields}

    @staticmethod
    def _minimal_broker(value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        return {"pid": value.get("pid"), "endpoint": value.get("endpoint")}

    def scan(
        self,
        candidates: Iterable[Path],
        effective_session: str,
        now: float | None = None,
    ) -> ScanResult:
        """Scan active and recent matching jobs without enumerating global state."""
        warnings: list[tuple[str, str]] = []
        if not effective_session:
            return ScanResult([], warnings)
        terminal_cutoff = (
            time.time() if now is None else now
        ) - TERMINAL_JOB_RETENTION_SECS
        workspaces: dict[Path, WorkspaceInfo] = {}
        for candidate in candidates:
            try:
                if not candidate.is_dir():
                    continue
            except OSError:
                continue
            info = resolve_workspace(candidate, self.env)
            workspaces.setdefault(info.canonical, info)

        raw_by_workspace: list[
            tuple[
                WorkspaceInfo,
                list[tuple[Path, dict[str, Any]]],
                int | None,
            ]
        ] = []
        sessions: set[str] = set()
        for info in workspaces.values():
            if not info.state_dir.is_dir():
                continue
            state_path = info.state_dir / "state.json"
            state_header = self.state_headers.read(info.state_dir, state_path)
            if state_header is not None and not state_header.shape_supported:
                self._warning(
                    f"codex-state-shape:{info.key}",
                    f"Codex state {info.key} has an unsupported top-level shape; skipped",
                    warnings,
                )
                continue
            version = state_header.version if state_header is not None else None
            if version is _INDETERMINATE_VERSION:
                self._warning(
                    f"codex-state-version-indeterminate:{info.key}",
                    f"Codex state {info.key} version could not be read from the "
                    "bounded header (file too large); skipped",
                    warnings,
                )
                continue
            try:
                version_supported = (
                    version is None or version in SUPPORTED_STATE_VERSIONS
                )
            except TypeError:
                version_supported = False
            if not version_supported:
                self._warning(
                    f"codex-state-version:{info.key}:{version}",
                    f"Codex state {info.key} has unsupported version {version!r}; skipped",
                    warnings,
                )
                continue
            jobs: list[tuple[Path, dict[str, Any]]] = []
            glob_start = time.monotonic()
            try:
                job_paths = sorted((info.state_dir / "jobs").glob("*.json"))
            except OSError:
                job_paths = []
            glob_elapsed = time.monotonic() - glob_start
            if glob_elapsed > JOBS_GLOB_WARN_SECS:
                self._warning(
                    f"codex-jobs-glob-slow:{info.key}",
                    f"Codex job enumeration for {info.key} took {glob_elapsed:.2f}s "
                    f"({len(job_paths)} files); per-poll cost scales with retained "
                    "jobs/*.json — prune old job records",
                    warnings,
                )
            for job_path in job_paths:
                raw = self.cache.read(job_path, self._minimal_job)
                if not isinstance(raw, dict):
                    continue
                workspace_root = raw.get("workspaceRoot")
                if not isinstance(workspace_root, str) or not workspace_root:
                    continue
                try:
                    raw_canonical = Path(workspace_root).resolve(strict=True)
                except OSError:
                    raw_canonical = Path(os.path.realpath(workspace_root))
                if raw_canonical != info.canonical:
                    continue
                session = raw.get("sessionId")
                if isinstance(session, str) and session:
                    sessions.add(session)
                jobs.append((job_path, raw))
            raw_by_workspace.append((info, jobs, safe_mtime(state_path)))

        session = self._session(effective_session, sessions, warnings)
        if not session:
            return ScanResult([], warnings)
        records: list[CodexRecord] = []
        for info, jobs, state_mtime in raw_by_workspace:
            matching: list[tuple[Path, dict[str, Any], str]] = []
            for job_path, raw in jobs:
                if raw.get("sessionId") != session:
                    continue
                job_id = raw.get("id")
                if not isinstance(job_id, str) or not SAFE_FIELD.fullmatch(job_id):
                    self._warning(
                        f"codex-job-id:{info.key}:{job_path.name}",
                        f"Codex state {info.key} contains an unsafe/missing job id; skipped",
                        warnings,
                    )
                    continue
                persisted_status = raw.get("status")
                if persisted_status in ACTIVE_STATUSES:
                    status = "active"
                else:
                    status = TERMINAL_STATUSES.get(str(persisted_status), "")
                if not status:
                    self._warning(
                        f"codex-job-status:{info.key}:{job_id}:{persisted_status}",
                        f"Codex job {job_id} has unknown status {persisted_status!r}; skipped",
                        warnings,
                    )
                    continue
                job_mtime = safe_mtime(job_path)
                if (
                    status != "active"
                    and job_mtime is not None
                    and job_mtime < terminal_cutoff
                ):
                    continue
                matching.append((job_path, raw, status))
            active_count = sum(status == "active" for _, _, status in matching)
            broker = self.cache.read(
                info.state_dir / "broker.json", self._minimal_broker
            )
            broker_record = broker if isinstance(broker, dict) else None
            broker_evidence = (
                self.proc.broker(broker_record, info.canonical) if matching else None
            )
            for job_path, raw, status in matching:
                job_id = str(raw["id"])
                clocks = [safe_mtime(job_path)]
                log_file = raw.get("logFile")
                declared = Path(str(log_file)) if log_file else None
                sibling = info.state_dir / "jobs" / f"{job_id}.log"
                log_path = declared if declared and declared.exists() else sibling
                clocks.append(safe_mtime(log_path))
                clocks.append(_parse_timestamp(raw.get("updatedAt")))
                if status == "active" and active_count == 1:
                    clocks.append(state_mtime)
                valid_clocks = [value for value in clocks if value is not None]
                activity = max(valid_clocks) if valid_clocks else None
                if activity is not None and activity > int(time.time()) + 5:
                    self._warning(
                        f"codex-clock-future:{info.key}:{job_id}",
                        f"Codex job {job_id} has a future activity clock; idle clamped to zero",
                        warnings,
                    )
                launcher = self.proc.launcher(raw.get("pid"), info.canonical)
                runtime = classify_runtime([launcher], [broker_evidence])
                try:
                    created = float(raw.get("createdAt") or 0)
                except (TypeError, ValueError):
                    created = 0.0
                records.append(
                    CodexRecord(
                        key=f"codex:{info.key}:{job_id}",
                        job_id=job_id,
                        workspace_key=info.key,
                        workspace_root=info.canonical,
                        status=status,
                        phase=_safe_phase(raw.get("phase")),
                        activity_epoch=activity,
                        runtime=runtime,
                        created_at=created,
                        error_message=(
                            str(raw["errorMessage"])
                            if raw.get("errorMessage") is not None
                            else None
                        ),
                    )
                )
        records.sort(key=lambda item: (item.created_at, item.job_id))
        return ScanResult(records, warnings)


class ClaudeStateMachine:
    """Namespaced edge state for Claude Sources A, B, and C."""

    def __init__(
        self,
        stall_secs: int,
        resume_secs: int,
        gone_polls: int,
        build_active: Callable[[Path], bool] = build_status_under,
    ) -> None:
        self.stall_secs = stall_secs
        self.resume_secs = resume_secs
        self.gone_polls = gone_polls
        self.build_active = build_active
        self.state: dict[str, str] = {}
        self.misses: dict[str, int] = {}
        self.gone_hits: dict[str, int] = {}

    def evaluate_named(
        self,
        key: str,
        activity_epoch: int,
        directory: Path,
        owners: set[str],
        now: int,
    ) -> list[str]:
        """Evaluate one task-gated named Claude agent."""
        idle = now - activity_epoch
        state = self.state.get(key, "OK")
        owns = owns_work(key, owners)
        if idle >= self.stall_secs and owns and state != "STALLED":
            try:
                building = self.build_active(directory)
            except OSError:
                building = False
            if not building:
                self.state[key] = "STALLED"
                return [f"STALL agent={key} idle={idle}s reason=owns-in_progress-idle"]
        elif state == "STALLED" and (idle < self.resume_secs or not owns):
            self.state[key] = "OK"
            return [f"RESUMED agent={key} idle={idle}s"]
        return []

    def evaluate_anon(self, key: str, activity_epoch: int, now: int) -> list[str]:
        """Evaluate one opt-in anonymous transcript clock."""
        idle = now - activity_epoch
        state = self.state.get(key, "OK")
        if idle >= self.stall_secs and state != "STALLED":
            self.state[key] = "STALLED"
            return [f"STALL agent={key} idle={idle}s reason=subagent-idle"]
        if state == "STALLED" and idle < self.resume_secs:
            self.state[key] = "OK"
            return [f"RESUMED agent={key} idle={idle}s"]
        return []

    def gone_candidate(
        self, key: str, pane_state: str, activity_epoch: int | None, now: int
    ) -> list[str]:
        """Confirm a positively scoped absent Claude process."""
        idle = now - activity_epoch if activity_epoch is not None else -1
        if idle >= self.stall_secs:
            reason = "stale-active"
        elif pane_state == "dead":
            reason = "pane-dead"
        else:
            reason = "pid-gone"
        self.gone_hits[key] = self.gone_hits.get(key, 0) + 1
        if self.gone_hits[key] >= self.gone_polls and self.state.get(key) != "GONE":
            self.state[key] = "GONE"
            return [f"GONE agent={key} reason={reason}"]
        return []

    def recover_gone(self, key: str) -> list[str]:
        """Clear GONE only after positive pane liveness."""
        self.gone_hits[key] = 0
        if self.state.get(key, "OK") == "GONE":
            self.state[key] = "OK"
            return [f"RESUMED agent={key} reason=recovered"]
        return []

    def reset_gone(self, key: str) -> None:
        """Reset an absence streak when pane liveness is unknown."""
        self.gone_hits[key] = 0

    def prune(self, alive: set[str]) -> list[str]:
        """Forget signalless Claude states only after consecutive misses."""
        events: list[str] = []
        for key in list(self.state):
            if key in alive:
                self.misses[key] = 0
                continue
            self.misses[key] = self.misses.get(key, 0) + 1
            if self.misses[key] < self.gone_polls:
                continue
            if self.state[key] == "STALLED":
                events.append(f"RESUMED agent={key} reason=gone")
            self.state.pop(key, None)
            self.misses.pop(key, None)
            self.gone_hits.pop(key, None)
        for key in list(self.gone_hits):
            if key not in alive and key not in self.state:
                self.gone_hits.pop(key, None)
        return events


def _error_field(value: str | None) -> str:
    normalized = " ".join((value or "error message unavailable").split())
    if len(normalized) > 240:
        normalized = normalized[:237] + "..."
    return json.dumps(normalized, ensure_ascii=False)


class CodexStateMachine:
    """Fully namespaced edge state for Codex Source D jobs."""

    def __init__(
        self,
        stall_secs: int,
        resume_secs: int,
        gone_polls: int,
        gone_enabled: bool = True,
    ) -> None:
        self.stall_secs = stall_secs
        self.resume_secs = resume_secs
        self.gone_polls = gone_polls
        self.gone_enabled = gone_enabled
        self.state: dict[str, str] = {}
        self.misses: dict[str, int] = {}
        self.gone_hits: dict[str, int] = {}
        self.reported: set[str] = set()

    def _terminal(self, record: CodexRecord) -> list[str]:
        if record.key in self.reported:
            return []
        self.reported.add(record.key)
        self.state[record.key] = record.status.upper()
        if record.status == "done":
            return [
                f"CODEX_DONE job={record.job_id} workspace={record.workspace_key} "
                f"phase={record.phase}"
            ]
        if record.status == "failed":
            return [
                f"CODEX_FAILED job={record.job_id} workspace={record.workspace_key} "
                f"phase={record.phase} error={_error_field(record.error_message)}"
            ]
        return [
            f"CODEX_CANCELLED job={record.job_id} "
            f"workspace={record.workspace_key} reason=user-cancelled"
        ]

    def _active(
        self,
        record: CodexRecord,
        now: int,
        build_active: Callable[[Path], bool],
    ) -> list[str]:
        state = self.state.get(record.key)
        first_observation = state is None
        if first_observation:
            self.state[record.key] = "ACTIVE"
            self.gone_hits[record.key] = 0
            state = "ACTIVE"
        idle = (
            max(0, now - record.activity_epoch)
            if record.activity_epoch is not None
            else None
        )
        if self.gone_enabled and record.runtime == "dead":
            self.gone_hits[record.key] = self.gone_hits.get(record.key, 0) + 1
            if self.gone_hits[record.key] >= self.gone_polls and state != "GONE":
                self.state[record.key] = "GONE"
                return [
                    f"CODEX_GONE job={record.job_id} "
                    f"workspace={record.workspace_key} reason=runtime-gone"
                ]
            return []
        self.gone_hits[record.key] = 0
        if first_observation:
            return []
        if state == "GONE" and (
            record.runtime == "alive" or (idle is not None and idle < self.stall_secs)
        ):
            self.state[record.key] = "ACTIVE"
            return [
                f"CODEX_RESUMED job={record.job_id} workspace={record.workspace_key} "
                f"phase={record.phase} reason=recovered"
            ]
        if state == "GONE":
            return []
        if idle is None:
            return []
        if state == "STALLED":
            if idle < self.resume_secs:
                self.state[record.key] = "ACTIVE"
                return [
                    f"CODEX_RESUMED job={record.job_id} "
                    f"workspace={record.workspace_key} idle={idle}s "
                    f"phase={record.phase} reason=progress"
                ]
            return []
        if idle < self.stall_secs:
            return []
        try:
            building = build_active(record.workspace_root)
        except OSError:
            building = False
        if building:
            return []
        self.state[record.key] = "STALLED"
        return [
            f"CODEX_STALL job={record.job_id} workspace={record.workspace_key} "
            f"idle={idle}s phase={record.phase} reason=no-progress"
        ]

    def evaluate(
        self,
        records: Iterable[CodexRecord],
        now: int,
        build_active: Callable[[Path], bool] = build_status_under,
    ) -> list[str]:
        """Evaluate every record deterministically, then apply missing-record grace."""
        ordered = sorted(records, key=lambda item: (item.created_at, item.job_id))
        seen = {record.key for record in ordered}
        events: list[str] = []
        for record in ordered:
            self.misses[record.key] = 0
            if record.status in {"done", "failed", "cancelled"}:
                events.extend(self._terminal(record))
            else:
                events.extend(self._active(record, now, build_active))
        events.extend(self.prune(seen))
        return events

    def prune(self, alive: set[str]) -> list[str]:
        """Forget signalless Codex states only after consecutive misses."""
        events: list[str] = []
        for key in list(self.state):
            if key in alive:
                self.misses[key] = 0
                continue
            self.misses[key] = self.misses.get(key, 0) + 1
            if self.misses[key] < self.gone_polls:
                continue
            state = self.state[key]
            if state in {"ACTIVE", "STALLED"} and self.gone_enabled:
                _, workspace_key, job_id = key.split(":", 2)
                self.state[key] = "GONE"
                self.misses[key] = 0
                events.append(
                    f"CODEX_GONE job={job_id} workspace={workspace_key} "
                    "reason=record-missing"
                )
            else:
                self.state.pop(key, None)
                self.misses.pop(key, None)
                self.reported.discard(key)
                self.gone_hits.pop(key, None)
        for key in set(self.misses) | self.reported | set(self.gone_hits):
            if key not in alive and key not in self.state:
                self.misses.pop(key, None)
                self.reported.discard(key)
                self.gone_hits.pop(key, None)
        return events


def _first_agent_id(path: Path) -> str:
    try:
        with path.open(errors="ignore") as handle:
            for _ in range(40):
                line = handle.readline()
                if not line:
                    break
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if value.get("agentId"):
                    return str(value["agentId"])
    except OSError:
        pass
    return ""


def _agent_setting(path: Path) -> tuple[str, str]:
    try:
        with path.open(errors="ignore") as handle:
            for _ in range(12):
                line = handle.readline()
                if not line:
                    break
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if value.get("type") == "agent-setting":
                    return str(value.get("agentSetting") or ""), str(
                        value.get("sessionId") or ""
                    )
    except OSError:
        pass
    return "", ""


def _project_slug_dirs(projects_dir: Path, cwd: Path) -> list[Path]:
    raw = str(cwd).rstrip("/")
    names = [re.sub(r"[^A-Za-z0-9-]", "-", raw), re.sub(r"[/.]", "-", raw)]
    result: list[Path] = []
    for name in names:
        path = projects_dir / name
        if path not in result and path.is_dir():
            result.append(path)
    return result


def member_transcripts(
    team: Team,
    projects_dir: Path,
    other_leads: set[str],
) -> dict[str, Path]:
    """Resolve session-safe transcript clocks for shared-cwd members."""
    type_counts = Counter(
        member.agent_type for member in team.members if member.agent_type
    )
    by_id: dict[str, Path] = {}
    sub_by_type: defaultdict[str, list[tuple[float, Path]]] = defaultdict(list)
    if team.lead_session_id:
        try:
            subdirs = projects_dir.glob(f"*/{team.lead_session_id}/subagents")
            for subdir in subdirs:
                for path in subdir.glob("agent-*.jsonl"):
                    mtime = safe_mtime(path)
                    if mtime is None:
                        continue
                    agent_id = _first_agent_id(path)
                    if agent_id:
                        by_id.setdefault(agent_id, path)
                    meta = safe_json(path.with_suffix(".meta.json"))
                    if isinstance(meta, dict) and meta.get("agentType"):
                        sub_by_type[str(meta["agentType"])].append((mtime, path))
        except OSError:
            pass
    slug_cache: dict[Path, defaultdict[str, list[tuple[float, Path, str]]]] = {}

    def by_type(cwd: Path) -> defaultdict[str, list[tuple[float, Path, str]]]:
        if cwd in slug_cache:
            return slug_cache[cwd]
        found: defaultdict[str, list[tuple[float, Path, str]]] = defaultdict(list)
        for slug_dir in _project_slug_dirs(projects_dir, cwd):
            for path in slug_dir.glob("*.jsonl"):
                mtime = safe_mtime(path)
                if mtime is None or (team.created_at and mtime < team.created_at - 5):
                    continue
                agent_type, session_id = _agent_setting(path)
                if (
                    not agent_type
                    or not session_id
                    or session_id == team.lead_session_id
                    or session_id in other_leads
                ):
                    continue
                found[agent_type].append((mtime, path, session_id))
        slug_cache[cwd] = found
        return found

    result: dict[str, Path] = {}
    for member in team.members:
        path: Path | None = None
        if member.agent_id in by_id:
            path = by_id[member.agent_id]
        elif member.agent_type and type_counts[member.agent_type] == 1:
            if sub_by_type.get(member.agent_type):
                path = max(sub_by_type[member.agent_type])[1]
            elif member.cwd:
                candidates = by_type(member.cwd).get(member.agent_type, [])
                if len({candidate[2] for candidate in candidates}) == 1:
                    path = max(candidates)[1]
        if path:
            result[canonical_label(member.name)] = path
    return result


def swarm_sockets(env: Mapping[str, str]) -> list[Path]:
    """Enumerate deduplicated per-session tmux swarm socket candidates."""
    directory = Path(
        env.get("TMUX_TMPDIR")
        or f"/tmp/tmux-{getattr(os, 'getuid', lambda: int(env.get('UID', '0')))()}"
    )
    sockets: list[Path] = []
    try:
        sockets.extend(sorted(directory.glob("claude-swarm-*")))
    except OSError:
        pass
    tmux = env.get("TMUX", "").split(",", 1)[0]
    if tmux and Path(tmux) not in sockets:
        sockets.append(Path(tmux))
    return sockets


def snapshot_panes(socket: Path) -> list[tuple[str, str, str]] | None:
    """Take one best-effort pane snapshot from a specific tmux socket."""
    try:
        result = subprocess.run(
            [
                "tmux",
                "-S",
                str(socket),
                "list-panes",
                "-a",
                "-F",
                "#{pane_id}\t#{pane_current_command}\t#{pane_title}",
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    panes: list[tuple[str, str, str]] = []
    for line in result.stdout.splitlines():
        fields = line.split("\t", 2)
        if len(fields) == 3:
            panes.append((fields[0], fields[1], fields[2]))
    return panes


def bind_swarm_socket(
    members: Iterable[Member], env: Mapping[str, str]
) -> tuple[dict[str, str], Path | None, int]:
    """Bind uniquely to the socket with the strongest pane-title evidence."""
    expected = {
        member.tmux_pane_id: member.agent_type
        for member in members
        if member.backend_type == "tmux"
        and member.tmux_pane_id.startswith("%")
        and member.agent_type
    }
    best_socket: Path | None = None
    best_panes: list[tuple[str, str, str]] = []
    best_score = 0
    tied = False
    if expected:
        for socket in swarm_sockets(env):
            panes = snapshot_panes(socket)
            if panes is None:
                continue
            score = sum(
                pane in expected and expected[pane] in title for pane, _, title in panes
            )
            if score > best_score:
                best_socket, best_panes, best_score, tied = socket, panes, score, False
            elif score == best_score and score > 0:
                tied = True
    if best_score < 1 or tied or best_socket is None:
        return {}, None, 0
    return {pane: command for pane, command, _ in best_panes}, best_socket, best_score


def classify_pane(member: Member, pane_commands: Mapping[str, str]) -> str:
    """Classify a member pane from one positively bound socket."""
    if member.backend_type != "tmux" or not member.tmux_pane_id.startswith("%"):
        return "unknown"
    if member.tmux_pane_id not in pane_commands:
        return "missing"
    return "dead" if pane_commands[member.tmux_pane_id] in SHELL_COMMANDS else "alive"


class Watchdog:
    """Stateful poll coordinator for Claude Sources A/B/C and Codex Source D."""

    def __init__(
        self,
        options: Options,
        env: Mapping[str, str] | None = None,
        proc_root: Path = Path("/proc"),
    ) -> None:
        self.options = options
        self.env = dict(os.environ if env is None else env)
        self.home = Path(self.env.get("HOME", str(Path.home())))
        self.warned: set[str] = set()
        self.claude = ClaudeStateMachine(
            options.stall_secs,
            options.resume_secs,
            options.gone_polls,
            lambda path: build_status_under(path, proc_root),
        )
        self.codex = CodexStateMachine(
            options.stall_secs,
            options.resume_secs,
            options.gone_polls,
            options.gone_enabled,
        )
        self.scanner = CodexScanner(self.env, ProcInspector(proc_root))
        self.have_tmux = options.gone_enabled and _command_exists("tmux", self.env)

    def warn_once(self, key: str, message: str) -> None:
        """Emit one diagnostic to stderr without touching protocol stdout."""
        if key in self.warned:
            return
        self.warned.add(key)
        print(f"agent-watchdog: {message}", file=sys.stderr, flush=True)

    def _task_dir(self, team: Team | None) -> Path | None:
        if self.options.tasks_dir:
            return self.options.tasks_dir
        if team and team.name:
            candidate = self.home / ".claude" / "tasks" / team.name
            return candidate if candidate.is_dir() else None
        if not self.options.session_id:
            base = self.home / ".claude" / "tasks"
            try:
                candidates = [path for path in base.glob("session-*") if path.is_dir()]
                return (
                    max(candidates, key=lambda path: path.stat().st_mtime)
                    if candidates
                    else None
                )
            except OSError:
                return None
        return None

    def _worktrees(self, team: Team | None) -> Path:
        path = self.options.worktrees
        if path.is_absolute():
            return path
        base: Path | None = team.lead_cwd if team else None
        if base is None and team and team.members:
            base = team.members[0].cwd
        return base / path if base else path

    def _subagent_dirs(self, team: Team | None) -> list[Path]:
        if team and team.lead_session_id:
            try:
                return list(
                    self.options.projects_dir.glob(
                        f"*/{team.lead_session_id}/subagents"
                    )
                )[:1]
            except OSError:
                return []
        if not self.options.session_id:
            try:
                slugs = [
                    path
                    for path in self.options.projects_dir.iterdir()
                    if path.is_dir()
                ]
                if not slugs:
                    return []
                newest = max(slugs, key=lambda path: path.stat().st_mtime)
                return [path for path in newest.glob("*/subagents") if path.is_dir()]
            except OSError:
                return []
        return []

    def poll_once(self, now: int | None = None) -> list[str]:
        """Collect one transient-tolerant snapshot and return transition lines."""
        epoch = int(time.time()) if now is None else now
        selection = select_team(
            self.home / ".claude" / "teams",
            self.options.team_dir,
            self.options.session_id,
        )
        if (
            selection.mode == "autodetect"
            and selection.candidate_count > 1
            and selection.directory
        ):
            self.warn_once(
                f"autodetect:{selection.directory.name}",
                f"ambiguous team autodetect: {selection.candidate_count} candidate team dirs "
                f"on this host; bound to {selection.directory.name} "
                f"(leadSessionId={selection.lead_session_id or '?'}) by NEWEST mtime — "
                "this may be ANOTHER session's team. Pass --session-id "
                "$CLAUDE_SESSION_ID (or --team-dir) to track THIS session's team.",
            )
        elif selection.mode in {"matched", "explicit"} and selection.directory:
            self.warn_once(
                f"bind:{selection.directory.name}",
                f"session-scoped to {selection.directory.name} "
                f"(leadSessionId={selection.lead_session_id or '?'}, mode={selection.mode})",
            )
        team = (
            parse_team(selection.directory / "config.json")
            if selection.directory and (selection.directory / "config.json").is_file()
            else None
        )
        if selection.directory and team is None:
            self.warn_once(
                f"cfgparse:{selection.directory}",
                f"team config at {selection.directory} unreadable/partial; Source A empty this poll",
            )
        owners = build_owners(self._task_dir(team))
        worktrees = self._worktrees(team)
        cwd_counts: Counter[Path] = Counter()
        if team:
            if team.lead_cwd:
                cwd_counts[team.lead_cwd] += 1
            cwd_counts.update(member.cwd for member in team.members if member.cwd)

        pane_commands: dict[str, str] = {}
        if self.have_tmux:
            members = team.members if team else ()
            pane_commands, socket, score = bind_swarm_socket(members, self.env)
            if socket:
                self.warn_once(
                    f"swarmsock:{socket.name}",
                    f"bound GONE detection to tmux swarm socket {socket.name} "
                    f"({score} member pane(s) matched)",
                )
            else:
                self.warn_once(
                    "noswarmsock",
                    "no matching tmux swarm socket for this team; GONE detection idle",
                )

        transcripts = (
            member_transcripts(
                team, self.options.projects_dir, set(selection.other_leads)
            )
            if team
            else {}
        )
        seen: set[str] = set()
        alive: set[str] = set()
        events: list[str] = []
        if team:
            for member in team.members:
                key = canonical_label(member.name)
                if key in seen:
                    continue
                activity = member_activity(member, worktrees, cwd_counts, transcripts)
                if (
                    activity is None
                    and member.cwd
                    and cwd_counts.get(member.cwd, 0) >= 2
                ):
                    self.warn_once(
                        f"sharedcwd:{key}",
                        f"no per-agent file signal for {key} (cwd shared with the "
                        "team-lead or another member, so its mtime is polluted) and no "
                        "transcript resolved — give it an isolated worktree to monitor",
                    )
                pane_state = (
                    classify_pane(member, pane_commands)
                    if self.options.gone_enabled and self.have_tmux and pane_commands
                    else "unknown"
                )
                if pane_state in {"dead", "missing"}:
                    seen.add(key)
                    alive.add(key)
                    events.extend(
                        self.claude.gone_candidate(
                            key,
                            pane_state,
                            activity.epoch if activity else None,
                            epoch,
                        )
                    )
                    continue
                if pane_state == "alive":
                    events.extend(self.claude.recover_gone(key))
                else:
                    self.claude.reset_gone(key)
                if pane_state == "alive" and activity is None:
                    seen.add(key)
                    alive.add(key)
                    continue
                if activity is None:
                    continue
                seen.add(key)
                alive.add(key)
                events.extend(
                    self.claude.evaluate_named(
                        key, activity.epoch, activity.directory, owners, epoch
                    )
                )
        try:
            source_c = sorted(
                path for path in worktrees.glob("agent-*") if path.is_dir()
            )
        except OSError:
            source_c = []
        if not worktrees.is_dir():
            self.warn_once(
                f"nowt:{worktrees}",
                f"worktrees dir {worktrees} absent; Source C inactive",
            )
        for directory in source_c:
            key = canonical_label(directory.name)
            if key in seen:
                continue
            activity = newest_mtime_under(directory)
            if activity is None:
                continue
            seen.add(key)
            alive.add(key)
            events.extend(
                self.claude.evaluate_named(key, activity, directory, owners, epoch)
            )
        if self.options.watch_subagents:
            for directory in self._subagent_dirs(team):
                try:
                    paths = directory.glob("agent-*.jsonl")
                    for path in paths:
                        key = path.stem
                        if key in seen:
                            continue
                        activity = safe_mtime(path)
                        if activity is None:
                            continue
                        seen.add(key)
                        alive.add(key)
                        events.extend(self.claude.evaluate_anon(key, activity, epoch))
                except OSError:
                    continue
        events.extend(self.claude.prune(alive))

        effective_session = ""
        if team and team.lead_session_id:
            effective_session = team.lead_session_id
        elif selection.lead_session_id:
            effective_session = selection.lead_session_id
        elif self.options.session_id:
            effective_session = self.options.session_id
        codex_candidates: list[Path] = []
        if team:
            if team.lead_cwd:
                codex_candidates.append(team.lead_cwd)
            codex_candidates.extend(member.cwd for member in team.members if member.cwd)
        codex_candidates.extend(source_c)
        codex_records: Iterable[CodexRecord] = ()
        if effective_session:
            scan = self.scanner.scan(codex_candidates, effective_session, epoch)
            for warning_key, message in scan.warnings:
                self.warn_once(warning_key, message)
            codex_records = scan.records
        events.extend(
            self.codex.evaluate(
                codex_records,
                epoch,
                lambda path: build_status_under(path, self.scanner.proc.proc_root),
            )
        )
        return events


USAGE = """agent-watchdog.py -- edge-triggered agent-stall watchdog (silent when healthy)
Usage: agent-watchdog.py [--session-id ID] [--team-dir DIR] [--tasks-dir DIR]
                         [--projects-dir DIR] [--worktrees DIR] [--watch-subagents]
                         [--no-gone] [--gone-polls N] [--stall-secs N]
                         [--resume-secs N] [--poll-secs N]
STALL = owns an in_progress task AND idle >= threshold AND no build under the
agent's worktree/cwd. An idle agent owning no in_progress task is never flagged.
--session-id (default $CLAUDE_SESSION_ID) scopes ALL discovery to THIS session's
team; precedence --team-dir > --session-id > $CLAUDE_SESSION_ID > newest autodetect.
Emits ONLY transition lines to stdout; diagnostics to stderr.
"""


def die(message: str) -> None:
    """Exit with the watchdog's stable diagnostic prefix."""
    print(f"agent-watchdog: {message}", file=sys.stderr)
    raise SystemExit(1)


def _integer(flag: str, value: str) -> int:
    if not value.isdigit():
        die(f"{flag} expects a non-negative integer, got: {value}")
    return int(value)


def parse_args(argv: Sequence[str], env: Mapping[str, str] | None = None) -> Options:
    """Parse the exact Bash-compatible CLI surface and defaults."""
    environment = os.environ if env is None else env
    home = Path(environment.get("HOME", str(Path.home())))
    options = Options(
        session_id=environment.get("CLAUDE_SESSION_ID", ""),
        projects_dir=home / ".claude" / "projects",
    )
    index = 0
    value_flags = {
        "--team-dir",
        "--session-id",
        "--tasks-dir",
        "--projects-dir",
        "--worktrees",
        "--gone-polls",
        "--stall-secs",
        "--resume-secs",
        "--poll-secs",
    }
    while index < len(argv):
        argument = argv[index]
        if argument in {"-h", "--help"}:
            print(USAGE, file=sys.stderr, end="")
            raise SystemExit(0)
        if argument == "--watch-subagents":
            options.watch_subagents = True
            index += 1
            continue
        if argument == "--no-gone":
            options.gone_enabled = False
            index += 1
            continue
        if argument not in value_flags:
            die(f"unknown argument: {argument} (try --help)")
        if index + 1 >= len(argv):
            die(f"{argument} needs a value")
        value = argv[index + 1]
        if argument == "--team-dir":
            options.team_dir = Path(value)
        elif argument == "--session-id":
            options.session_id = value
        elif argument == "--tasks-dir":
            options.tasks_dir = Path(value)
        elif argument == "--projects-dir":
            options.projects_dir = Path(value)
        elif argument == "--worktrees":
            options.worktrees = Path(value)
        elif argument == "--gone-polls":
            options.gone_polls = _integer(argument, value)
        elif argument == "--stall-secs":
            options.stall_secs = _integer(argument, value)
        elif argument == "--resume-secs":
            options.resume_secs = _integer(argument, value)
        elif argument == "--poll-secs":
            options.poll_secs = _integer(argument, value)
        index += 2
    if options.poll_secs < 1:
        die("--poll-secs must be >= 1")
    if options.gone_polls < 1:
        die("--gone-polls must be >= 1")
    if options.resume_secs >= options.stall_secs:
        die(
            f"--resume-secs ({options.resume_secs}) must be < "
            f"--stall-secs ({options.stall_secs})"
        )
    return options


def _command_exists(command: str, env: Mapping[str, str] | None = None) -> bool:
    environment = os.environ if env is None else env
    path = environment.get("PATH", os.defpath)
    return any(
        (Path(directory) / command).is_file()
        and os.access(Path(directory) / command, os.X_OK)
        for directory in path.split(os.pathsep)
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the persistent monitor until interrupted."""
    options = parse_args(sys.argv[1:] if argv is None else argv)
    monitor = Watchdog(options)
    print(
        "agent-watchdog: "
        f"poll={options.poll_secs}s stall={options.stall_secs}s "
        f"resume={options.resume_secs}s gone-polls={options.gone_polls} "
        f"gone-detect={int(options.gone_enabled)} tmux={int(monitor.have_tmux)} "
        f"session={options.session_id or '<auto>'} "
        f"team-dir={options.team_dir or '<auto>'} "
        f"tasks-dir={options.tasks_dir or '<auto>'} worktrees={options.worktrees} "
        f"watch-subagents={int(options.watch_subagents)}",
        file=sys.stderr,
        flush=True,
    )
    while True:
        try:
            events = monitor.poll_once()
            for event in events:
                print(event, flush=True)
        except Exception as error:
            monitor.warn_once(
                f"poll-error:{type(error).__name__}",
                f"transient poll failure ignored ({type(error).__name__})",
            )
        try:
            time.sleep(options.poll_secs)
        except InterruptedError:
            continue


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(0) from None
