import json
import os
import subprocess
from pathlib import Path
from typing import Optional


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "gh-fetch-reviews.sh"


def _run_script(
    tmp_path: Path,
    gh_source: str,
    jq_source: Optional[str] = None,
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_gh = bin_dir / "gh"
    fake_gh.write_text(gh_source, encoding="utf-8")
    fake_gh.chmod(0o755)
    if jq_source is not None:
        fake_jq = bin_dir / "jq"
        fake_jq.write_text(jq_source, encoding="utf-8")
        fake_jq.chmod(0o755)
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home_dir),
            "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
        }
    )
    return subprocess.run(
        [str(SCRIPT), "owner/repo", "83"],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )


def test_fetch_reviews_slurps_pages_before_transforming(
    tmp_path: Path,
) -> None:
    result = _run_script(
        tmp_path,
        """#!/usr/bin/env bash
if [[ " $* " == *" --slurp "* && " $* " == *" --jq "* ]]; then
  echo "the --slurp option is not supported with --jq or --template" >&2
  exit 1
fi
if [[ "$*" != "api repos/owner/repo/pulls/83/reviews --paginate --slurp" ]]; then
  echo "unexpected arguments: $*" >&2
  exit 2
fi
cat <<'JSON'
[[{"id":101,"state":"APPROVED","submitted_at":"2026-07-27T12:00:00Z","body":"Looks good","user":{"login":"alice"},"ignored":"first"}],[{"id":102,"state":"CHANGES_REQUESTED","submitted_at":"2026-07-28T09:30:00Z","body":"Please fix","user":{"login":"bob"},"ignored":"second"}]]
JSON
""",
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [
        {
            "id": 101,
            "state": "APPROVED",
            "submitted_at": "2026-07-27T12:00:00Z",
            "body": "Looks good",
            "user": "alice",
        },
        {
            "id": 102,
            "state": "CHANGES_REQUESTED",
            "submitted_at": "2026-07-28T09:30:00Z",
            "body": "Please fix",
            "user": "bob",
        },
    ]


def test_fetch_reviews_propagates_gh_failure(tmp_path: Path) -> None:
    result = _run_script(
        tmp_path,
        """#!/usr/bin/env bash
echo "mock gh failed" >&2
exit 23
""",
    )

    assert result.returncode == 23
    assert "mock gh failed" in result.stderr


def test_fetch_reviews_propagates_jq_failure(tmp_path: Path) -> None:
    result = _run_script(
        tmp_path,
        """#!/usr/bin/env bash
printf '%s\n' '[]'
""",
        """#!/usr/bin/env bash
echo "mock jq failed" >&2
exit 24
""",
    )

    assert result.returncode == 24
    assert "mock jq failed" in result.stderr
