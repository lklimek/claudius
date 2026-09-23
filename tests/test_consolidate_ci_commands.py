"""Tests for the round-saving consolidate_reports.py commands: gate, digest, finalize."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import consolidate_reports as cr  # noqa: E402

PLUGIN_JSON = Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json"


def _f(fid: str, likelihood: float, impact: float, **extra: Any) -> dict[str, Any]:
    finding: dict[str, Any] = {
        "id": fid,
        "likelihood": likelihood,
        "impact": impact,
        "relevance": 0.5,
        "title": f"Title {fid}",
        "location": f"src/{fid.lower()}.py:10-12",
        "description": f"Description of {fid}.",
        "recommendation": "Fix it.",
    }
    finding.update(extra)
    return finding


def _write(path: Path, data: Any) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.mark.parametrize("command", ["gate", "prepare"])
def test_directory_report_exits_2_without_traceback(command, tmp_path):
    argv = [command, str(tmp_path)]
    if command == "prepare":
        argv = [command, f"qa:{tmp_path}", "--output", str(tmp_path / "i.json")]
        argv += ["--repo-root", str(tmp_path)]
    proc = subprocess.run(
        [sys.executable, str(Path(cr.__file__)), *argv],
        capture_output=True,
        text=True,
    )
    output = proc.stdout + proc.stderr
    assert proc.returncode == 2
    assert "ERROR:" in output and "Traceback" not in output
    assert str(tmp_path) in output
    assert not (tmp_path / "i.json").exists()


@pytest.mark.parametrize("command", ["gate", "prepare"])
@pytest.mark.parametrize("error_type", [PermissionError, OSError])
def test_report_read_oserror_is_clean(
    command, error_type, tmp_path, monkeypatch, capsys, caplog
):
    path = _write(tmp_path / "qa.json", [])

    def fail_read(*args, **kwargs):
        raise error_type("cannot read producer report")

    monkeypatch.setattr(Path, "read_text", fail_read)
    argv = [command, str(path)]
    if command == "prepare":
        argv = [command, f"qa:{path}", "--output", str(tmp_path / "i.json")]
        argv += ["--repo-root", str(tmp_path)]
    assert cr.main(argv) == 2
    output = capsys.readouterr().out + caplog.text
    assert "ERROR" in output and "cannot read producer report" in output
    assert not (tmp_path / "i.json").exists()


# ---------------------------------------------------------------------------
# gate
# ---------------------------------------------------------------------------
class TestGate:
    def test_reports_max_band_candidates_and_counts(self, tmp_path, capsys):
        path = _write(
            tmp_path / "qa-findings.json",
            [
                {
                    "title": "QA",
                    "category": "code_quality",
                    "findings": [
                        _f("QA-001", 0.8, 0.8),  # HIGH
                        _f("QA-002", 0.5, 0.5),  # MEDIUM
                        _f("QA-003", 0.05, 0.05),  # INFO
                    ],
                }
            ],
        )
        assert cr.main(["gate", str(path)]) == 0
        out = capsys.readouterr().out.splitlines()
        assert out[0] == "MAX: HIGH BLOCKING: no"
        assert out[1] == "CANDIDATES: QA-001 (HIGH)"
        assert out[2] == "COUNTS: CRITICAL=0 HIGH=1 MEDIUM=1 LOW=0 INFO=1 TOTAL=3"

    def test_gate_citation_makes_low_finding_a_blocking_candidate(
        self, tmp_path, capsys
    ):
        path = _write(
            tmp_path / "sec.json",
            [
                {
                    "title": "Sec",
                    "category": "security",
                    "findings": [
                        _f("SEC-001", 0.2, 0.2, tags=["CWE-532", "G-SECRET"]),
                        _f(
                            "SEC-002",
                            0.2,
                            0.2,
                            merge_class="blocking",
                            intent_basis="G-INTENT: contradicts the PR goal",
                        ),
                    ],
                }
            ],
        )
        assert cr.main(["gate", str(path)]) == 0
        out = capsys.readouterr().out.splitlines()
        assert out[0] == "MAX: LOW BLOCKING: yes"
        assert out[1] == "CANDIDATES: SEC-001 (G-SECRET), SEC-002 (G-INTENT)"

    def test_blocking_without_gate_citation_is_a_candidate(self, tmp_path, capsys):
        finding = _f(
            "QA-001",
            0.2,
            0.2,
            merge_class="blocking",
            intent_basis="Breaks the requested behavior",
            tags=[{"x": 1}],
        )
        path = _write(
            tmp_path / "qa.json",
            [{"title": "QA", "category": "code_quality", "findings": [finding]}],
        )
        # non-string tags do not crash gate; the schema rejects them, so INVALID
        assert cr.main(["gate", str(path)]) == 1
        out = capsys.readouterr().out.splitlines()
        assert out[:2] == ["MAX: LOW BLOCKING: yes", "CANDIDATES: QA-001 (blocking)"]
        assert any(line.startswith("INVALID") and "tags" in line for line in out)

    def test_empty_array_reports_none(self, tmp_path, capsys):
        path = _write(tmp_path / "empty.json", [])
        assert cr.main(["gate", str(path)]) == 0
        out = capsys.readouterr().out.splitlines()
        assert out[0] == "MAX: NONE BLOCKING: no"
        assert out[1] == "CANDIDATES: none"

    def test_flags_findings_prepare_would_drop(self, tmp_path, capsys):
        bad = _f("QA-002", 0.9, 0.9)
        del bad["recommendation"]
        path = _write(
            tmp_path / "qa.json",
            [{"title": "QA", "category": "code_quality", "findings": [bad]}],
        )
        assert cr.main(["gate", str(path)]) == 1
        out = capsys.readouterr().out
        assert "INVALID: 1 finding(s) would be dropped by prepare" in out

    def test_envelope_object_is_rejected_with_fix_hint(self, tmp_path, capsys):
        path = _write(tmp_path / "env.json", {"findings": [_f("QA-001", 0.5, 0.5)]})
        assert cr.main(["gate", str(path)]) == 2
        assert "bare JSON array" in capsys.readouterr().out

    def test_missing_file_is_a_file_error(self, tmp_path):
        assert cr.main(["gate", str(tmp_path / "nope.json")]) == 2

    def _gate(self, tmp_path: Path, findings: list[Any]) -> int:
        path = _write(
            tmp_path / "qa.json",
            [{"title": "QA", "category": "code_quality", "findings": findings}],
        )
        return cr.main(["gate", str(path)])

    @pytest.mark.parametrize(
        "basis",
        [{}, {"intent_basis": None}, {"intent_basis": ""}, {"intent_basis": " \t\n"}],
    )
    def test_blocking_requires_nonempty_intent_basis(self, tmp_path, capsys, basis):
        finding = _f("QA-001", 0.2, 0.2, merge_class="blocking", **basis)
        assert self._gate(tmp_path, [finding]) == 1
        lines = capsys.readouterr().out.splitlines()
        assert any(
            line.startswith("INVALID:") and "QA-001" in line and "intent_basis" in line
            for line in lines
        )
        assert "CANDIDATES: QA-001 (blocking)" in lines

    def test_blocking_with_intent_basis_passes_gate(self, tmp_path, capsys):
        finding = _f(
            "QA-001",
            0.2,
            0.2,
            merge_class="blocking",
            intent_basis="Breaks the requested behavior",
        )
        assert self._gate(tmp_path, [finding]) == 0
        assert "CANDIDATES: QA-001 (blocking)" in capsys.readouterr().out

    def test_band_comes_from_floats_not_producer_severity(self, tmp_path, capsys):
        assert self._gate(tmp_path, [_f("QA-001", 1.0, 0.9, severity=2)]) == 0
        assert capsys.readouterr().out.startswith("MAX: CRITICAL")

    def test_string_severity_label_does_not_drop_a_rated_finding(
        self, tmp_path, capsys
    ):
        assert self._gate(tmp_path, [_f("QA-001", 1.0, 1.0, severity="CRITICAL")]) == 0
        assert capsys.readouterr().out.startswith("MAX: CRITICAL")

    @pytest.mark.parametrize(
        ("findings", "needle"),
        [
            ([{k: v for k, v in _f("QA-001", 0.5, 0.5).items() if k != "id"}], "id"),
            ([_f("", 0.5, 0.5)], "id"),
            ([_f("QA-001", 0.5, 0.5), _f("QA-001", 0.2, 0.2)], "duplicate"),
            (
                [
                    {
                        k: v
                        for k, v in _f("QA-001", 0.5, 0.5).items()
                        if k not in ("likelihood", "impact", "relevance")
                    }
                ],
                "likelihood",
            ),
            ([_f("QA-001", 0.5, 0.5, relevance=None)], "relevance"),
            ([_f("QA-001", 0.5, 0.5, title=7)], "title"),
            ([_f("QA-001", 0.5, 0.5, recommendation=["x"])], "recommendation"),
            ([_f("QA-001", 0.5, 0.5, title=" ")], "title"),
            ([_f("QA-001", 0.5, 0.5, description="\t")], "description"),
            (
                [{k: v for k, v in _f("QA-001", 0.5, 0.5).items() if k != "location"}],
                "location",
            ),
        ],
    )
    def test_flags_what_finalize_would_reject(self, tmp_path, capsys, findings, needle):
        assert self._gate(tmp_path, findings) == 1
        out = capsys.readouterr().out
        assert "INVALID" in out and needle in out

    @pytest.mark.parametrize(
        ("section", "needle"),
        [
            ({"title": "QA", "category": "securty"}, "category"),
            ({"title": 7, "category": "code_quality"}, "title"),
            (
                {"title": "QA", "category": "code_quality", "positives": ["x"]},
                "positives",
            ),
        ],
    )
    def test_flags_invalid_section_fields(self, tmp_path, capsys, section, needle):
        path = _write(
            tmp_path / "qa.json", [{**section, "findings": [_f("QA-001", 0.5, 0.5)]}]
        )
        assert cr.main(["gate", str(path)]) == 1
        out = capsys.readouterr().out
        assert any(
            line.startswith("INVALID") and needle in line for line in out.splitlines()
        )

    def test_rescued_bare_findings_are_not_section_errors(self, tmp_path, capsys):
        path = _write(tmp_path / "qa.json", [_f("QA-001", 0.5, 0.5)])
        assert cr.main(["gate", str(path)]) == 0

    @pytest.mark.parametrize(
        "data",
        [
            ["oops"],
            [{"title": "S", "findings": None}],
            [{"title": "S", "findings": ["oops"]}],
            [{"title": "S", "findings": "nope"}],
        ],
    )
    def test_malformed_shapes_exit_2_cleanly(self, tmp_path, capsys, data):
        path = _write(tmp_path / "bad.json", data)
        assert cr.main(["gate", str(path)]) == 2
        assert "ERROR" in capsys.readouterr().out

    def test_malformed_shape_rejected_by_prepare_too(self, tmp_path):
        path = _write(tmp_path / "bad.json", [{"title": "S", "findings": None}])
        argv = ["prepare", f"qa:{path}", "--output", str(tmp_path / "i.json")]
        argv += ["--repo-root", str(tmp_path)]
        assert cr.main(argv) == 2


# ---------------------------------------------------------------------------
# prepare: plugin_version + --digest
# ---------------------------------------------------------------------------
def _prepare(tmp_path: Path, *, digest: bool, reports: dict[str, Any]) -> Path:
    specs = [
        f"{agent}:{_write(tmp_path / f'{agent}.json', data)}"
        for agent, data in reports.items()
    ]
    out = tmp_path / "intermediate.json"
    args = argparse.Namespace(
        agent_reports=specs,
        repo_root=str(tmp_path),
        output=str(out),
        metadata=json.dumps({"project": "p", "date": "2026-09-23"}),
        digest=digest,
    )
    assert cr.cmd_prepare(args) == 0
    return out


@pytest.mark.parametrize("metadata", ["[]", '"x"', "7", "null"])
def test_prepare_non_object_metadata_exits_2(tmp_path, metadata):
    args = argparse.Namespace(
        agent_reports=[f"qa:{_write(tmp_path / 'qa.json', [])}"],
        repo_root=str(tmp_path),
        output=str(tmp_path / "intermediate.json"),
        metadata=metadata,
        digest=False,
    )
    assert cr.cmd_prepare(args) == 2
    assert not (tmp_path / "intermediate.json").exists()


def _dup_reports() -> dict[str, Any]:
    long_desc = "x" * 1000
    return {
        "security": [
            {
                "title": "Sec",
                "category": "security",
                "findings": [
                    _f("SEC-001", 0.8, 0.8, location="src/a.py:10"),
                    _f("SEC-002", 0.2, 0.2, location="src/b.py:3"),
                ],
            }
        ],
        "qa": [
            {
                "title": "QA",
                "category": "code_quality",
                "findings": [
                    _f(
                        "QA-001",
                        0.5,
                        0.5,
                        title="Title SEC-001",
                        location="src/a.py:10",
                        description=long_desc,
                    )
                ],
            }
        ],
    }


class TestPrepare:
    def test_records_plugin_version_in_metadata(self, tmp_path):
        out = _prepare(tmp_path, digest=False, reports={"qa": []})
        expected = json.loads(PLUGIN_JSON.read_text())["version"]
        assert json.loads(out.read_text())["metadata"]["plugin_version"] == expected

    def test_explicit_plugin_version_is_not_overwritten(self, tmp_path):
        rep = _write(tmp_path / "qa.json", [])
        out = tmp_path / "intermediate.json"
        args = argparse.Namespace(
            agent_reports=[f"qa:{rep}"],
            repo_root=str(tmp_path),
            output=str(out),
            metadata=json.dumps(
                {"project": "p", "date": "2026-09-23", "plugin_version": "1.2.3"}
            ),
        )
        assert cr.cmd_prepare(args) == 0
        assert json.loads(out.read_text())["metadata"]["plugin_version"] == "1.2.3"

    def test_digest_is_written_and_printed(self, tmp_path, capsys):
        out = _prepare(tmp_path, digest=True, reports=_dup_reports())
        digest_path = out.parent / "digest.md"
        assert digest_path.is_file()
        text = digest_path.read_text()
        assert capsys.readouterr().out.strip() == text.strip()

        assert "3 raw findings" in text
        assert "`security:SEC-001` HIGH (L0.80 I0.80 R0.50)" in text
        assert "`src/a.py:10`" in text
        # most severe first
        assert text.index("security:SEC-001") < text.index("qa:QA-001")
        assert text.index("qa:QA-001") < text.index("security:SEC-002")
        # description truncated to ~300 chars
        assert "x" * 300 not in text
        assert "x" * 290 in text
        # duplicate group lists keys, not indices
        dup_line = next(line for line in text.splitlines() if line.startswith("- G1"))
        assert "security:SEC-001" in dup_line and "qa:QA-001" in dup_line

    def test_digest_is_far_smaller_than_intermediate(self, tmp_path, capsys):
        out = _prepare(tmp_path, digest=True, reports=_dup_reports())
        capsys.readouterr()
        assert (out.parent / "digest.md").stat().st_size < out.stat().st_size / 2

    def test_no_digest_by_default(self, tmp_path):
        out = _prepare(tmp_path, digest=False, reports={"qa": []})
        assert not (out.parent / "digest.md").exists()


# ---------------------------------------------------------------------------
# finalize
# ---------------------------------------------------------------------------
class TestFinalize:
    def _run(self, tmp_path: Path, decisions: dict[str, Any], *fmt: str) -> int:
        intermediate = _prepare(tmp_path, digest=False, reports=_dup_reports())
        decisions_path = _write(tmp_path / "merge-decisions.json", decisions)
        argv = [
            "finalize",
            "--input",
            str(intermediate),
            "--decisions",
            str(decisions_path),
            "--output",
            str(tmp_path / "out" / "report.json"),
        ]
        for f in fmt:
            argv += ["--format", f]
        return cr.main(argv)

    @staticmethod
    def _decisions(**extra: Any) -> dict[str, Any]:
        data: dict[str, Any] = {
            "executive_summary": {"overall_assessment": "Needs work."},
            "merges": [
                {
                    "reason": "Same issue.",
                    "members": [
                        {"agent": "security", "original_id": "SEC-001"},
                        {"agent": "qa", "original_id": "QA-001"},
                    ],
                    "base": {"agent": "security", "original_id": "SEC-001"},
                    "updates": {},
                }
            ],
            "finding_updates": {
                "security:SEC-001": {"merge_class": "non_blocking"},
                "security:SEC-002": {"merge_class": "out_of_scope_follow_up"},
            },
        }
        data.update(extra)
        return data

    def test_merges_assembles_validates_and_renders(self, tmp_path):
        assert self._run(tmp_path, self._decisions(), "md", "html") == 0
        report = json.loads((tmp_path / "out" / "report.json").read_text())
        ids = [f["id"] for s in report["findings"] for f in s["findings"]]
        assert sorted(ids) == ["SEC-001", "SEC-002"]
        assert report["metadata"]["plugin_version"]
        assert (tmp_path / "out" / "report.md").is_file()
        assert (tmp_path / "out" / "report.html").is_file()
        # the merged intermediate is kept next to the decisions for auditability
        assert (tmp_path / "merged-findings.json").is_file()

    def test_default_format_is_markdown(self, tmp_path):
        assert self._run(tmp_path, self._decisions()) == 0
        assert (tmp_path / "out" / "report.md").is_file()
        assert not (tmp_path / "out" / "report.html").exists()

    def test_missing_merge_class_blocks_output(self, tmp_path, caplog):
        decisions = self._decisions(finding_updates={})
        assert self._run(tmp_path, decisions) == 1
        assert "security:SEC-001" in caplog.text
        assert not (tmp_path / "out" / "report.json").exists()

    def test_schema_failure_blocks_output(self, tmp_path):
        decisions = self._decisions(executive_summary={"verdict_text": "no summary"})
        assert self._run(tmp_path, decisions) == 1
        assert not (tmp_path / "out" / "report.json").exists()

    def test_empty_review_still_writes_report(self, tmp_path):
        intermediate = _prepare(tmp_path, digest=False, reports={"qa": []})
        decisions_path = _write(
            tmp_path / "merge-decisions.json",
            {"executive_summary": {"overall_assessment": "Clean."}},
        )
        out = tmp_path / "report.json"
        argv = ["finalize", "--input", str(intermediate)]
        argv += ["--decisions", str(decisions_path), "--output", str(out)]
        assert cr.main(argv) == 0
        assert json.loads(out.read_text())["summary_statistics"]["total_findings"] == 0

    def test_render_failure_leaves_nothing_behind(self, tmp_path, monkeypatch):
        failing = tmp_path / "render.py"
        failing.write_text(
            "import sys, pathlib\n"
            "pathlib.Path(sys.argv[1]).with_suffix('.pdf').write_text('partial')\n"
            "sys.exit(1)\n"
        )
        monkeypatch.setattr(cr, "RENDERER", failing)
        assert self._run(tmp_path, self._decisions(), "pdf") == 1
        out_dir = tmp_path / "out"
        assert not out_dir.exists() or list(out_dir.iterdir()) == []
        assert not (tmp_path / "merged-findings.json").exists()

    def test_schema_failure_leaves_no_merged_findings(self, tmp_path):
        decisions = self._decisions(executive_summary={"overall_assessment": 5})
        assert self._run(tmp_path, decisions) == 1
        assert not (tmp_path / "merged-findings.json").exists()

    def test_missing_executive_summary_defaults_like_merge_helper(self, tmp_path):
        decisions = self._decisions()
        del decisions["executive_summary"]
        assert self._run(tmp_path, decisions) == 0
        report = json.loads((tmp_path / "out" / "report.json").read_text())
        assert report["executive_summary"] == {"overall_assessment": ""}

    def test_empty_decisions_on_empty_review(self, tmp_path):
        intermediate = _prepare(tmp_path, digest=False, reports={"qa": []})
        decisions_path = _write(tmp_path / "merge-decisions.json", {})
        argv = ["finalize", "--input", str(intermediate)]
        argv += ["--decisions", str(decisions_path)]
        argv += ["--output", str(tmp_path / "report.json")]
        assert cr.main(argv) == 0

    def test_missing_input_exits_2(self, tmp_path):
        decisions_path = _write(tmp_path / "merge-decisions.json", {})
        argv = ["finalize", "--input", str(tmp_path / "nope.json")]
        argv += ["--decisions", str(decisions_path)]
        argv += ["--output", str(tmp_path / "report.json")]
        assert cr.main(argv) == 2

    def test_unparseable_decisions_exit_2(self, tmp_path):
        intermediate = _prepare(tmp_path, digest=False, reports={"qa": []})
        bad = tmp_path / "merge-decisions.json"
        bad.write_text("{not json")
        argv = ["finalize", "--input", str(intermediate), "--decisions", str(bad)]
        argv += ["--output", str(tmp_path / "report.json")]
        assert cr.main(argv) == 2

    def test_invalid_decision_exits_1(self, tmp_path, caplog):
        decisions = self._decisions(
            finding_updates={"security:SEC-001": {"merge_class": "blocking"}}
        )
        assert self._run(tmp_path, decisions) == 1
        assert "intent_basis" in caplog.text
        assert not (tmp_path / "out" / "report.json").exists()

    def test_failure_moves_stale_outputs_aside(self, tmp_path):
        assert self._run(tmp_path, self._decisions(), "md", "html") == 0
        out_dir = tmp_path / "out"
        stale = ["report.json", "report.md", "report.html"]
        assert self._run(tmp_path, self._decisions(finding_updates={})) == 1
        for name in stale:
            assert not (out_dir / name).exists()
            assert (out_dir / f"{name}.stale").is_file()
        assert not (tmp_path / "merged-findings.json").exists()
        assert (tmp_path / "merged-findings.json.stale").is_file()

    def test_load_failure_also_moves_stale_report_aside(self, tmp_path):
        assert self._run(tmp_path, self._decisions()) == 0
        bad = tmp_path / "merge-decisions.json"
        bad.write_text("{not json")
        argv = ["finalize", "--input", str(tmp_path / "intermediate.json")]
        argv += ["--decisions", str(bad)]
        argv += ["--output", str(tmp_path / "out" / "report.json")]
        assert cr.main(argv) == 2
        assert not (tmp_path / "out" / "report.json").exists()
        assert (tmp_path / "out" / "report.json.stale").is_file()

    def test_success_retires_renders_of_unrequested_formats(self, tmp_path):
        assert self._run(tmp_path, self._decisions(), "html") == 0
        assert self._run(tmp_path, self._decisions(), "md") == 0
        out_dir = tmp_path / "out"
        assert (out_dir / "report.md").is_file()
        assert not (out_dir / "report.html").exists()
        assert (out_dir / "report.html.stale").is_file()

    def test_audit_copy_failure_publishes_nothing(self, tmp_path, monkeypatch):
        assert self._run(tmp_path, self._decisions()) == 0

        def boom(*_args, **_kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(cr.mfh, "write_merged_findings", boom)
        assert self._run(tmp_path, self._decisions()) == 1
        out_dir = tmp_path / "out"
        assert not (out_dir / "report.json").exists()
        assert (out_dir / "report.json.stale").is_file()
        assert not list(out_dir.glob(".finalize-*"))

    def test_unwritable_output_dir_exits_1_without_traceback(self, tmp_path, caplog):
        intermediate = _prepare(tmp_path, digest=False, reports={"qa": []})
        decisions = _write(tmp_path / "merge-decisions.json", {})
        blocker = tmp_path / "blocker"
        blocker.write_text("not a dir")
        argv = ["finalize", "--input", str(intermediate), "--decisions", str(decisions)]
        argv += ["--output", str(blocker / "sub" / "report.json")]
        assert cr.main(argv) == 1
        assert "blocker" in caplog.text

    def test_unexpected_error_still_sets_aside_stale_outputs(
        self, tmp_path, monkeypatch
    ):
        assert self._run(tmp_path, self._decisions()) == 0

        def boom(*_args, **_kwargs):
            raise TypeError("unsupported operand")

        monkeypatch.setattr(cr, "_assemble_and_write", boom)
        assert self._run(tmp_path, self._decisions()) == 1
        assert not (tmp_path / "out" / "report.json").exists()
        assert (tmp_path / "out" / "report.json.stale").is_file()

    def test_success_leaves_no_stale_files(self, tmp_path):
        assert self._run(tmp_path, self._decisions()) == 0
        assert self._run(tmp_path, self._decisions()) == 0
        assert not list(tmp_path.rglob("*.stale"))


@pytest.mark.parametrize("command", ["gate", "finalize"])
def test_new_commands_are_registered(command):
    with pytest.raises(SystemExit) as exc:
        cr.parse_args([command, "--help"])
    assert exc.value.code == 0
