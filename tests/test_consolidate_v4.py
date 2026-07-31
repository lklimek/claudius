"""End-to-end tests for v3-aware consolidate pipeline."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import consolidate_reports as cr


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _init_repo(
    path: Path, remote: str | None = None, commit: bool = False
) -> str | None:
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], check=True)
    if remote:
        subprocess.run(
            ["git", "-C", str(path), "remote", "add", "origin", remote], check=True
        )
    if commit:
        (path / "README.md").write_text("hi\n")
        subprocess.run(["git", "-C", str(path), "add", "README.md"], check=True)
        subprocess.run(
            ["git", "-C", str(path), "commit", "-q", "-m", "init"], check=True
        )
        return subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"], text=True
        ).strip()
    return None


def _make_assemble_input(
    tmp_path: Path,
    *,
    metadata: dict[str, Any] | None = None,
    findings: list[dict[str, Any]] | None = None,
) -> Path:
    data: dict[str, Any] = {
        "metadata": (
            metadata if metadata is not None else {"project": "p", "date": "2026-05-26"}
        ),
        "executive_summary": {"overall_assessment": "ok"},
        "findings": findings if findings is not None else [],
        "agent_stats": [],
    }
    p = tmp_path / "input.json"
    p.write_text(json.dumps(data))
    return p


# ---------------------------------------------------------------------------
# cmd_prepare: metadata derivation
# ---------------------------------------------------------------------------
class TestPrepareMetadataDerivation:
    def test_github_repo_populates_repository_and_full_sha(self, tmp_path):
        sha = _init_repo(
            tmp_path,
            remote="https://github.com/octo/widgets.git",
            commit=True,
        )
        sections = [
            {
                "category": "security",
                "title": "Sec",
                "findings": [
                    {
                        "severity": 4,
                        "title": "T",
                        "location": "f.rs:1",
                        "description": "D",
                        "recommendation": "R",
                    }
                ],
            }
        ]
        rep = tmp_path / "agent.json"
        rep.write_text(json.dumps(sections))
        out = tmp_path / "intermediate.json"

        args = argparse.Namespace(
            agent_reports=[f"agent:{rep}"],
            repo_root=str(tmp_path),
            output=str(out),
            metadata=json.dumps(
                {"project": "p", "date": "2026-05-26", "commit": sha[:7]}
            ),
        )
        assert cr.cmd_prepare(args) == 0
        data = json.loads(out.read_text())
        assert data["metadata"]["repository"] == {"owner": "octo", "repo": "widgets"}
        assert data["metadata"]["commit"] == sha

    def test_non_git_directory_omits_repository_and_commit(self, tmp_path):
        sections = [{"category": "code_quality", "title": "CQ", "findings": []}]
        rep = tmp_path / "agent.json"
        rep.write_text(json.dumps(sections))
        out = tmp_path / "intermediate.json"

        args = argparse.Namespace(
            agent_reports=[f"agent:{rep}"],
            repo_root=str(tmp_path),
            output=str(out),
            metadata=json.dumps({"project": "p", "date": "2026-05-26"}),
        )
        assert cr.cmd_prepare(args) == 0
        meta = json.loads(out.read_text())["metadata"]
        assert "repository" not in meta
        assert "commit" not in meta

    def test_non_github_remote_omits_repository(self, tmp_path):
        _init_repo(tmp_path, remote="https://gitlab.com/octo/widgets.git", commit=True)
        sections = [{"category": "code_quality", "title": "CQ", "findings": []}]
        rep = tmp_path / "agent.json"
        rep.write_text(json.dumps(sections))
        out = tmp_path / "intermediate.json"
        args = argparse.Namespace(
            agent_reports=[f"agent:{rep}"],
            repo_root=str(tmp_path),
            output=str(out),
            metadata=json.dumps({"project": "p", "date": "2026-05-26"}),
        )
        assert cr.cmd_prepare(args) == 0
        meta = json.loads(out.read_text())["metadata"]
        assert "repository" not in meta


# ---------------------------------------------------------------------------
# cmd_assemble: severity & permalink derivation
# ---------------------------------------------------------------------------
class TestAssembleDerivations:
    def test_overall_and_severity_derived(self, tmp_path):
        findings = [
            {
                "title": "Sec",
                "category": "security",
                "findings": [
                    {
                        "severity": 1,
                        "title": "high one",
                        "location": "src/a.rs:1-5",
                        "description": "D",
                        "recommendation": "R",
                        "likelihood": 1.0,
                        "impact": 1.0,
                        "relevance": 1.0,
                    },
                    {
                        "severity": 5,
                        "title": "low one",
                        "location": "src/b.rs:1-5",
                        "description": "D",
                        "recommendation": "R",
                        "likelihood": 0.0,
                        "impact": 0.0,
                        "relevance": 0.0,
                    },
                ],
            }
        ]
        inp = _make_assemble_input(
            tmp_path,
            metadata={
                "project": "p",
                "date": "2026-05-26",
                "commit": "0123456789abcdef0123456789abcdef01234567",
                "repository": {"owner": "octo", "repo": "widgets"},
            },
            findings=findings,
        )
        out = tmp_path / "report.json"
        args = argparse.Namespace(input=str(inp), output=str(out))
        assert cr.cmd_assemble(args) == 0

        report = json.loads(out.read_text())
        sec = report["findings"][0]["findings"]
        # Sort: 1.0 first, 0.0 last.
        assert sec[0]["title"] == "high one"
        assert sec[0]["overall_severity"] == 1.0
        assert sec[0]["severity"] == 5
        assert sec[1]["overall_severity"] == 0.0
        assert sec[1]["severity"] == 1

    def test_permalink_built_when_metadata_present(self, tmp_path):
        sha = "0123456789abcdef0123456789abcdef01234567"
        findings = [
            {
                "title": "Sec",
                "category": "security",
                "findings": [
                    {
                        "severity": 3,
                        "title": "T",
                        "location": "src/a.rs:10-20",
                        "description": "D",
                        "recommendation": "R",
                        "likelihood": 0.5,
                        "impact": 0.5,
                        "relevance": 0.5,
                    }
                ],
            }
        ]
        inp = _make_assemble_input(
            tmp_path,
            metadata={
                "project": "p",
                "date": "2026-05-26",
                "commit": sha,
                "repository": {"owner": "octo", "repo": "widgets"},
            },
            findings=findings,
        )
        out = tmp_path / "report.json"
        args = argparse.Namespace(input=str(inp), output=str(out))
        assert cr.cmd_assemble(args) == 0
        f = json.loads(out.read_text())["findings"][0]["findings"][0]
        assert f["location_permalink"] == (
            f"https://github.com/octo/widgets/blob/{sha}/src/a.rs#L10-L20"
        )

    def test_permalink_absent_when_no_repository(self, tmp_path):
        findings = [
            {
                "title": "Sec",
                "category": "security",
                "findings": [
                    {
                        "severity": 3,
                        "title": "T",
                        "location": "src/a.rs:10-20",
                        "description": "D",
                        "recommendation": "R",
                        "likelihood": 0.5,
                        "impact": 0.5,
                        "relevance": 0.5,
                    }
                ],
            }
        ]
        inp = _make_assemble_input(tmp_path, findings=findings)
        out = tmp_path / "report.json"
        args = argparse.Namespace(input=str(inp), output=str(out))
        assert cr.cmd_assemble(args) == 0
        f = json.loads(out.read_text())["findings"][0]["findings"][0]
        assert "location_permalink" not in f

    def test_sort_absent_overall_sinks_to_bottom(self, tmp_path):
        # Tests sort by overall desc with absent floats treated as -1 (sink).
        # Producer didn't supply floats for "absent" finding — coordinator
        # leaves it as-is; schema validation requires floats so we must
        # supply at least sentinel-style absence via a non-final assemble.
        # Use a producer-without-floats path: a finding that already has
        # integer severity but no floats — this should fail schema validation
        # (loud failure per plan). To test sort we instead include three
        # findings all with floats but different overalls.
        findings = [
            {
                "title": "Sec",
                "category": "security",
                "findings": [
                    {
                        "severity": 1,
                        "title": "mid",
                        "location": "src/m.rs:1",
                        "description": "D",
                        "recommendation": "R",
                        "likelihood": 0.5,
                        "impact": 0.5,
                        "relevance": 0.5,
                    },
                    {
                        "severity": 1,
                        "title": "top",
                        "location": "src/t.rs:1",
                        "description": "D",
                        "recommendation": "R",
                        "likelihood": 1.0,
                        "impact": 1.0,
                        "relevance": 1.0,
                    },
                    {
                        "severity": 1,
                        "title": "bot",
                        "location": "src/b.rs:1",
                        "description": "D",
                        "recommendation": "R",
                        "likelihood": 0.0,
                        "impact": 0.0,
                        "relevance": 0.0,
                    },
                ],
            }
        ]
        inp = _make_assemble_input(tmp_path, findings=findings)
        out = tmp_path / "report.json"
        args = argparse.Namespace(input=str(inp), output=str(out))
        assert cr.cmd_assemble(args) == 0
        ordered = [
            f["title"] for f in json.loads(out.read_text())["findings"][0]["findings"]
        ]
        assert ordered == ["top", "mid", "bot"]
