"""gh-common.sh run_gh: stdin handling and the scripts that call it.

Under the Claude Code Bash tool stdin is a non-TTY pipe that never reaches EOF,
so run_gh must not read stdin unless the gh arguments ask for a payload.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
GH_COMMON = SCRIPTS / "gh-common.sh"
RESOLVE = SCRIPTS / "gh-resolve-review-threads.sh"
TIMEOUT = 10

RESOLVED = '{"data":{"t0":{"thread":{"isResolved":true}}}}'
FORBIDDEN_JSON = (
    '{"data":{"t0":null},"errors":[{"type":"FORBIDDEN","path":["t0"],'
    '"message":"Resource not accessible by personal access token"}]}'
)


def _stub(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text(f"#!/usr/bin/env bash\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


def _env(tmp_path: Path, gh: str, ghsudo: str) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub(bin_dir, "gh", gh)
    _stub(bin_dir, "ghsudo", ghsudo)
    home = tmp_path / "home"
    home.mkdir()
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
            "CAP": str(tmp_path),
        }
    )
    return env


def _run_with_open_stdin(
    argv: list[str], env: dict[str, str], tmp_path: Path
) -> tuple[int, str, str]:
    """Run argv with stdin on a pipe whose write end stays open (no EOF)."""
    read_fd, write_fd = os.pipe()
    out_path, err_path = tmp_path / "out", tmp_path / "err"
    try:
        with out_path.open("w") as out, err_path.open("w") as err:
            proc = subprocess.Popen(
                argv, stdin=read_fd, stdout=out, stderr=err, env=env
            )
            os.close(read_fd)
            read_fd = -1
            try:
                rc = proc.wait(timeout=TIMEOUT)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                pytest.fail(f"{argv} blocked on an open, empty stdin")
    finally:
        if read_fd != -1:
            os.close(read_fd)
        os.close(write_fd)
    return rc, out_path.read_text(), err_path.read_text()


def test_run_gh_without_payload_ignores_open_stdin(tmp_path):
    env = _env(tmp_path, 'echo "ok $*"', "exit 99")
    argv = ["bash", "-c", 'source "$1"; run_gh api x', "_", str(GH_COMMON)]
    rc, out, err = _run_with_open_stdin(argv, env, tmp_path)
    assert (rc, out.strip()) == (0, "ok api x"), err


@pytest.mark.parametrize(
    "raw_args",
    [["-f", "body=@-"], ["-fbody=@-"], ["--raw-field", "body=@-"]],
)
def test_run_gh_raw_field_at_dash_is_not_a_payload(tmp_path, raw_args):
    env = _env(tmp_path, 'echo "ok $*"', "exit 99")
    argv = ["bash", "-c", 'source "$1"; shift; run_gh api x "$@"', "_"]
    rc, out, err = _run_with_open_stdin(
        argv + [str(GH_COMMON), *raw_args], env, tmp_path
    )
    assert (rc, out.strip()) == (0, "ok api x " + " ".join(raw_args)), err


@pytest.mark.parametrize(
    "args",
    [
        ["o/r", "1", "--id", "PRRT_kwDOabc"],
        ["PRRT_kwDOabc"],
    ],
    ids=["id-mode", "legacy-mode"],
)
def test_resolve_review_threads_ignores_open_stdin(tmp_path, args):
    env = _env(tmp_path, f"echo '{RESOLVED}'", "exit 99")
    rc, out, err = _run_with_open_stdin([str(RESOLVE), *args], env, tmp_path)
    assert rc == 0, err
    assert '"isResolved":true' in out


@pytest.mark.parametrize(
    "payload_args",
    [
        ["--input", "-"],
        ["--input=-"],
        ["-F", "body=@-"],
        ["-Fbody=@-"],
        ["--field", "body=@-"],
        ["--field=body=@-"],
    ],
)
def test_run_gh_replays_stdin_payload_on_ghsudo_retry(tmp_path, payload_args):
    env = _env(
        tmp_path,
        'cat > "$CAP/gh.stdin"; echo "HTTP 403: Forbidden" >&2; exit 1',
        'shift; cat > "$CAP/ghsudo.stdin"; echo retried',
    )
    proc = subprocess.run(
        ["bash", "-c", 'source "$1"; shift; run_gh api x "$@"', "_", str(GH_COMMON)]
        + payload_args,
        input='{"body":"payload"}',
        capture_output=True,
        text=True,
        env=env,
        timeout=TIMEOUT,
        check=False,
    )
    assert (proc.returncode, proc.stdout.strip()) == (0, "retried"), proc.stderr
    assert (tmp_path / "gh.stdin").read_text() == '{"body":"payload"}'
    assert (tmp_path / "ghsudo.stdin").read_text() == '{"body":"payload"}'


def test_resolve_forbidden_pat_fails_with_actionable_message(tmp_path):
    forbidden = (
        f"echo '{FORBIDDEN_JSON}'; "
        'echo "gh: Resource not accessible by personal access token" >&2; exit 1'
    )
    env = _env(tmp_path, forbidden, f"shift; {forbidden}")
    proc = subprocess.run(
        [str(RESOLVE), "o/r", "1", "--id", "PRRT_kwDOabc"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        env=env,
        timeout=TIMEOUT,
        check=False,
    )
    assert proc.returncode != 0
    assert "fine-grained" in proc.stderr
    assert "classic" in proc.stderr and "GitHub UI" in proc.stderr
