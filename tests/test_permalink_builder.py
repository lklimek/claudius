"""Tests for permalink construction and git-metadata derivation helpers."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import consolidate_reports as cr


# ---------------------------------------------------------------------------
# _derive_metadata_repository
# ---------------------------------------------------------------------------
class TestDeriveMetadataRepository:
    def _init_repo(self, path: Path, remote_url: str | None) -> None:
        subprocess.run(["git", "init", "-q", str(path)], check=True)
        if remote_url:
            subprocess.run(
                ["git", "-C", str(path), "remote", "add", "origin", remote_url],
                check=True,
            )

    def test_https_github_url(self, tmp_path):
        self._init_repo(tmp_path, "https://github.com/octo/widgets.git")
        assert cr._derive_metadata_repository(str(tmp_path)) == {
            "owner": "octo",
            "repo": "widgets",
        }

    def test_https_no_dot_git(self, tmp_path):
        self._init_repo(tmp_path, "https://github.com/octo/widgets")
        assert cr._derive_metadata_repository(str(tmp_path)) == {
            "owner": "octo",
            "repo": "widgets",
        }

    def test_ssh_scp_form(self, tmp_path):
        self._init_repo(tmp_path, "git@github.com:octo/widgets.git")
        assert cr._derive_metadata_repository(str(tmp_path)) == {
            "owner": "octo",
            "repo": "widgets",
        }

    def test_ssh_url_form(self, tmp_path):
        self._init_repo(tmp_path, "ssh://git@github.com/octo/widgets.git")
        assert cr._derive_metadata_repository(str(tmp_path)) == {
            "owner": "octo",
            "repo": "widgets",
        }

    def test_non_git_directory_returns_none(self, tmp_path):
        assert cr._derive_metadata_repository(str(tmp_path)) is None

    def test_gitlab_remote_returns_none(self, tmp_path):
        self._init_repo(tmp_path, "https://gitlab.com/octo/widgets.git")
        assert cr._derive_metadata_repository(str(tmp_path)) is None

    def test_bitbucket_remote_returns_none(self, tmp_path):
        self._init_repo(tmp_path, "git@bitbucket.org:octo/widgets.git")
        assert cr._derive_metadata_repository(str(tmp_path)) is None

    def test_no_origin_returns_none(self, tmp_path):
        self._init_repo(tmp_path, None)
        assert cr._derive_metadata_repository(str(tmp_path)) is None


# ---------------------------------------------------------------------------
# _full_sha
# ---------------------------------------------------------------------------
class TestFullSha:
    def test_already_full_sha_passes_through(self, tmp_path):
        sha = "a" * 40
        assert cr._full_sha(sha, str(tmp_path)) == sha

    def test_empty_returns_none(self, tmp_path):
        assert cr._full_sha("", str(tmp_path)) is None
        assert cr._full_sha(None, str(tmp_path)) is None

    def test_short_sha_expanded(self, tmp_path):
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
        subprocess.run(
            ["git", "-C", str(tmp_path), "config", "user.email", "t@t"], check=True
        )
        subprocess.run(
            ["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True
        )
        (tmp_path / "f.txt").write_text("hello")
        subprocess.run(["git", "-C", str(tmp_path), "add", "f.txt"], check=True)
        subprocess.run(
            ["git", "-C", str(tmp_path), "commit", "-q", "-m", "init"], check=True
        )
        full = subprocess.check_output(
            ["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True
        ).strip()
        short = full[:7]
        assert cr._full_sha(short, str(tmp_path)) == full

    def test_unresolvable_short_returns_none(self, tmp_path):
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
        assert cr._full_sha("deadbee", str(tmp_path)) is None

    def test_non_git_directory_returns_none(self, tmp_path):
        assert cr._full_sha("deadbee", str(tmp_path)) is None


# ---------------------------------------------------------------------------
# _build_permalink
# ---------------------------------------------------------------------------
class TestBuildPermalink:
    SHA = "0123456789abcdef0123456789abcdef01234567"
    REPO = {"owner": "octo", "repo": "widgets"}

    def test_range_location(self):
        url = cr._build_permalink(self.REPO, self.SHA, "src/auth.rs:42-56")
        assert url == (
            "https://github.com/octo/widgets/blob/" f"{self.SHA}/src/auth.rs#L42-L56"
        )

    def test_single_line_location(self):
        url = cr._build_permalink(self.REPO, self.SHA, "src/auth.rs:42")
        assert url == (
            "https://github.com/octo/widgets/blob/" f"{self.SHA}/src/auth.rs#L42"
        )

    def test_missing_repository(self):
        assert cr._build_permalink(None, self.SHA, "src/x.rs:1") is None

    def test_missing_sha(self):
        assert cr._build_permalink(self.REPO, None, "src/x.rs:1") is None
        assert cr._build_permalink(self.REPO, "", "src/x.rs:1") is None

    def test_unparseable_location(self):
        assert cr._build_permalink(self.REPO, self.SHA, "no-line-info") is None
        assert cr._build_permalink(self.REPO, self.SHA, "") is None
