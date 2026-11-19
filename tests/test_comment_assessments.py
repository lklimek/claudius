"""Comment assessments share review envelopes without inventing risk scores."""

import copy
import json
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import generate_review_report as grr  # noqa: E402

FIXTURE = ROOT / "tests/fixtures/reports/v4-comment-assessments.json"
SCHEMA = json.loads((ROOT / "schemas/review-report.schema.json").read_text())


@pytest.fixture
def report():
    return json.loads(FIXTURE.read_text())


def test_assessments_validate_without_risk_scores_on_non_findings(report):
    jsonschema.Draft202012Validator(SCHEMA).validate(report)
    assert {r.get("assessment") for r in report["comment_assessments"]} >= {
        "valid",
        "already_fixed",
        "out_of_scope",
        "wrong",
    }
    for row in report["comment_assessments"]:
        assert "likelihood" not in row
    assert report["comment_assessments"][0]["thread_state"] == "resolved"
    assert report["comment_assessments"][0]["assessment"] == "valid"


def test_assessment_extension_requires_41(report):
    report["schema_version"] = "4.0.0"
    assert list(jsonschema.Draft202012Validator(SCHEMA).iter_errors(report))


def test_actual_findings_still_require_risk_scores(report):
    del report["findings"][0]["findings"][0]["likelihood"]
    assert list(jsonschema.Draft202012Validator(SCHEMA).iter_errors(report))


@pytest.mark.parametrize("renderer", [grr.render_html, grr.render_triage])
def test_html_keeps_reasoning_and_proposed_action_in_each_row(report, renderer):
    soup = BeautifulSoup(renderer(report), "html.parser")
    rows = soup.select(".assessment-table > tbody > tr")
    assert len(rows) == len(report["comment_assessments"])
    for row, item in zip(rows, report["comment_assessments"]):
        assert item["id"] in row.get_text()
        assert item["reasoning"] in row.get_text()
        assert item["proposed_action"] in row.get_text()
    assert soup.select_one("#assessment-search")
    assert soup.select_one("#assessment-filter")
    assert soup.select_one("#thread-state-filter")
    assert "Proposed action" in soup.get_text()
    assert "Action taken" in soup.get_text()


def test_html_escapes_content_and_rejects_active_links(report):
    row = report["comment_assessments"][0]
    row["reviewer"] = '<img src=x onerror="alert(1)">'
    row["comment_url"] = 'javascript:alert("bad")'
    row["location_permalink"] = "data:text/html,bad"
    row["reasoning"] = '<script>alert("bad")</script>'
    row["proposed_reply"] = "[bad](javascript:alert(1))"
    soup = BeautifulSoup(grr.render_html(report), "html.parser")
    table = soup.select_one("#comment-assessments")
    assert not table.select("script, img")
    assert row["reviewer"] in table.get_text()
    for link in table.select("a[href]"):
        assert link["href"].startswith(("https://", "http://", "#"))


def test_markdown_contains_unscored_items_and_both_action_states(report):
    md = grr.render_markdown(report)
    for row in report["comment_assessments"]:
        assert row["reasoning"] in md
        assert row["proposed_action"] in md
    assert "Recorded as complete" in md


@pytest.mark.parametrize(
    "mutation", ["duplicate", "dangling", "misidentified", "unlinked"]
)
def test_invalid_assessment_references_fail_both_clis(report, tmp_path, mutation):
    if mutation == "duplicate":
        report["comment_assessments"].append(
            copy.deepcopy(report["comment_assessments"][0])
        )
    elif mutation == "dangling":
        report["comment_assessments"][0]["finding_id"] = "CMT-099"
    elif mutation == "misidentified":
        report["comment_assessments"][0]["id"] = "CMT-090"
    else:
        report["comment_assessments"][0].pop("finding_id")
        report["comment_assessments"][0]["assessment"] = "wrong"
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report))
    for script, args in [
        ("validate_report.py", []),
        ("generate_review_report.py", ["--format", "html"]),
    ]:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / script), str(path), *args],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0, result.stdout


def test_pdf_preserves_assessment_details(report, tmp_path, monkeypatch):
    from reportlab.platypus import SimpleDocTemplate

    captured = []
    original_build = SimpleDocTemplate.build

    def capture_story(doc, story, *args, **kwargs):
        captured.extend(x.getPlainText() for x in story if hasattr(x, "getPlainText"))
        return original_build(doc, story, *args, **kwargs)

    monkeypatch.setattr(SimpleDocTemplate, "build", capture_story)
    report["comment_assessments"][0]["proposed_reply"] = (
        "Use `name` literally. [details](https://example.org/)"
    )
    output = tmp_path / "comments.pdf"
    grr.render_pdf(report, output)
    assert output.read_bytes().startswith(b"%PDF-")
    text = " ".join(captured)
    for item in report["comment_assessments"]:
        assert item["reasoning"] in text
    assert report["comment_assessments"][0]["proposed_reply"] in text
    assert report["comment_assessments"][0]["location_permalink"] in text


def test_derive_preserves_comment_schema_and_items(report, tmp_path):
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report))
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/consolidate_reports.py"),
            "regenerate",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    updated = json.loads(path.read_text())
    assert updated["schema_version"] == "4.1.0"
    assert updated["comment_assessments"] == report["comment_assessments"]


@pytest.mark.parametrize("include_rows", [True, False])
def test_comment_rows_cannot_be_misread_as_an_automatic_approval(report, include_rows):
    import post_pr_review

    if not include_rows:
        del report["comment_assessments"]
    with pytest.raises(post_pr_review.ReportError, match="comment assessments"):
        post_pr_review.validate_report(report)


def test_markdown_preserves_literal_proposed_reply(report):
    reply = "Use `name` literally. [details](https://example.org/)\n```example```"
    report["comment_assessments"][0]["proposed_reply"] = reply
    html = str(grr.render_markdown_to_html(grr.render_markdown(report)))
    assert reply in BeautifulSoup(html, "html.parser").get_text()


def test_inline_thread_with_missing_state_is_unknown(report):
    report["comment_assessments"][0].pop("thread_state")
    soup = BeautifulSoup(grr.render_html(report), "html.parser")
    row = soup.select_one(".assessment-table > tbody > tr")
    assert row["data-thread-state"] == "unknown"
    assert "Thread: unknown" in row.get_text()
    general = soup.select_one("#assessment-CMT-003")
    assert general["data-thread-state"] == "none"


def test_pdf_markdown_table_retains_cells(report):
    evidence = report["comment_assessments"][0]["evidence"]
    text = " ".join(body for _, body in grr.render_markdown_to_reportlab(evidence))
    for cell in ["Caller", "Input", "save", "unchecked"]:
        assert cell in text


def test_pdf_prose_links_allow_http_and_mailto_targets():
    source = (
        "[anchor](#missing) [active](javascript:alert(1)) [safe](https://example.org/) "
        "[email](mailto:reviewer@example.org)"
    )
    blocks = grr.render_markdown_to_reportlab(source)
    rendered = " ".join(body for _, body in blocks)
    assert "anchor" in rendered and "active" in rendered
    assert 'href="#' not in rendered and 'href="javascript:' not in rendered
    assert 'href="https://example.org/"' in rendered
    assert 'href="mailto:reviewer@example.org"' in rendered
    assert grr._safe_url("mailto:reviewer@example.org\n", allow_mailto=True) == ""
