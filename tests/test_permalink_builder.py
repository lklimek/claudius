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
            f"https://github.com/octo/widgets/blob/{self.SHA}/src/auth.rs#L42-L56"
        )

    def test_single_line_location(self):
        url = cr._build_permalink(self.REPO, self.SHA, "src/auth.rs:42")
        assert url == (
            f"https://github.com/octo/widgets/blob/{self.SHA}/src/auth.rs#L42"
        )

    def test_missing_repository(self):
        assert cr._build_permalink(None, self.SHA, "src/x.rs:1") is None

    def test_missing_sha(self):
        assert cr._build_permalink(self.REPO, None, "src/x.rs:1") is None
        assert cr._build_permalink(self.REPO, "", "src/x.rs:1") is None

    def test_unparseable_location(self):
        assert cr._build_permalink(self.REPO, self.SHA, "no-line-info") is None
        assert cr._build_permalink(self.REPO, self.SHA, "") is None

    def test_path_with_spaces_is_url_encoded(self):
        url = cr._build_permalink(self.REPO, self.SHA, "src/file with spaces.rs:42")
        assert url is not None
        # Space must be URL-encoded; the literal space breaks links.
        assert " " not in url
        assert "file%20with%20spaces.rs" in url

    def test_path_with_unicode_is_url_encoded(self):
        url = cr._build_permalink(self.REPO, self.SHA, "src/café.rs:1")
        assert url is not None
        assert "café" not in url
        # %C3%A9 is UTF-8 encoded "é".
        assert "%C3%A9" in url

    def test_path_with_fragment_char_is_encoded(self):
        # A '#' in the path would otherwise hijack the URL fragment.
        url = cr._build_permalink(self.REPO, self.SHA, "src/weird#name.rs:1")
        assert url is not None
        # Only one '#' allowed — the anchor. The '#' in the path is encoded.
        assert url.count("#") == 1
        assert "%23" in url

    def test_path_with_newline_rejected_or_encoded(self):
        url = cr._build_permalink(self.REPO, self.SHA, "src/foo.rs\nX-Inj: 1:1")
        # Either rejected outright or fully encoded — but never a raw newline.
        assert url is None or "\n" not in url

    def test_path_slashes_preserved(self):
        url = cr._build_permalink(self.REPO, self.SHA, "a/b/c/file.rs:1")
        assert url is not None
        assert "/a/b/c/file.rs" in url


# ---------------------------------------------------------------------------
# _GITHUB_REMOTE_RE — strict anchoring and charset
# ---------------------------------------------------------------------------
class TestGithubRemoteRegex:
    def test_rejects_embedded_newline_in_repo(self):
        # CRLF-injection-shaped remote URL must not match.
        m = cr._GITHUB_REMOTE_RE.match("git@github.com:owner/repo\nX-Inject: 1")
        assert m is None

    def test_rejects_whitespace_in_owner(self):
        m = cr._GITHUB_REMOTE_RE.match("https://github.com/owner space/repo.git")
        assert m is None

    def test_accepts_dots_dashes_underscores(self):
        m = cr._GITHUB_REMOTE_RE.match(
            "https://github.com/my-org.name/my_repo.name.git"
        )
        assert m is not None
        assert m["owner"] == "my-org.name"
        assert m["repo"] == "my_repo.name"
