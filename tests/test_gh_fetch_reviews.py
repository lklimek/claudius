import json
import os
import subprocess
from pathlib import Path
from typing import Optional

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "gh-fetch-reviews.sh"
COMMENTS_SCRIPT = SCRIPT.with_name("gh-fetch-review-comments.sh")


def _run_script(
    tmp_path: Path,
    gh_source: str,
    jq_source: Optional[str] = None,
    script: Path = SCRIPT,
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
        [str(script), "owner/repo", "83"],
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
[[{"id":101,"state":"APPROVED","submitted_at":"2026-07-27T12:00:00Z","body":"Looks good","user":{"login":"alice"},"html_url":"https://github.com/owner/repo/pull/83#pullrequestreview-101","commit_id":"abc1234","ignored":"first"}],[{"id":102,"state":"CHANGES_REQUESTED","submitted_at":"2026-07-28T09:30:00Z","body":"Please fix","user":{"login":"bob"},"html_url":"https://github.com/owner/repo/pull/83#pullrequestreview-102","commit_id":"def5678","ignored":"second"}]]
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
            "html_url": "https://github.com/owner/repo/pull/83#pullrequestreview-101",
            "commit_id": "abc1234",
        },
        {
            "id": 102,
            "state": "CHANGES_REQUESTED",
            "submitted_at": "2026-07-28T09:30:00Z",
            "body": "Please fix",
            "user": "bob",
            "html_url": "https://github.com/owner/repo/pull/83#pullrequestreview-102",
            "commit_id": "def5678",
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


@pytest.mark.parametrize("pages", [[], [[], []], [[101], [102, 103]]])
def test_fetch_comments_returns_one_array_with_round_provenance(tmp_path, pages):
    source_pages = [
        [
            {
                "id": cid,
                "path": "src/input.py",
                "line": None,
                "original_line": 12,
                "body": "Please validate this.\nIncluding replies.",
                "user": {"login": "alice"},
                "in_reply_to_id": 100 if cid > 101 else None,
                "html_url": f"https://github.com/owner/repo/pull/83#discussion_r{cid}",
                "created_at": "2026-11-23T12:00:00Z",
                "commit_id": "abc1234",
                "pull_request_review_id": 99,
                "ignored": "drop this",
            }
            for cid in page
        ]
        for page in pages
    ]
    result = _run_script(
        tmp_path,
        "#!/usr/bin/env bash\n"
        '[[ "$*" == "api repos/owner/repo/pulls/83/comments --paginate --slurp" ]] || exit 2\n'
        "cat <<'JSON'\n" + json.dumps(source_pages) + "\nJSON\n",
        script=COMMENTS_SCRIPT,
    )
    assert result.returncode == 0, result.stderr
    expected = [
        {**{k: v for k, v in c.items() if k != "ignored"}, "user": "alice"}
        for page in source_pages
        for c in page
    ]
    assert json.loads(result.stdout) == expected


@pytest.mark.parametrize("failure", ["gh", "jq"])
def test_fetch_comments_propagates_failure(tmp_path, failure):
    result = _run_script(
        tmp_path,
        "#!/usr/bin/env bash\nexit 23\n"
        if failure == "gh"
        else "#!/usr/bin/env bash\nprintf '%s\\n' '[]'\n",
        "#!/usr/bin/env bash\nexit 24\n" if failure == "jq" else None,
        script=COMMENTS_SCRIPT,
    )
    assert result.returncode == (23 if failure == "gh" else 24)
