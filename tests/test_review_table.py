"""Review HTML shares the comment-table presentation without losing findings."""

import json
import sys
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import generate_review_report as grr  # noqa: E402


def report():
    return json.loads((ROOT / "tests/fixtures/reports/v4-full.json").read_text())


def test_each_finding_is_one_table_row_with_analysis_and_action():
    data = report()
    soup = BeautifulSoup(grr.render_html(data), "html.parser")
    rows = soup.select(".review-findings-table > tbody > tr.finding")
    expected = [f for s in data["findings"] for f in s["findings"]]
    assert len(rows) == len(expected)
    for row, finding in zip(rows, expected):
        assert row["id"] == f"finding-{finding['id']}"
        assert len(row.find_all("td", recursive=False)) == 6
        text = row.get_text(" ", strip=True)
        for field in ["id", "title", "location"]:
            assert finding[field] in text
        for field in ["description", "recommendation"]:
            plain = BeautifulSoup(
                str(grr.render_markdown_to_html(finding[field])), "html.parser"
            ).get_text(" ", strip=True)
            assert plain in text


def test_optional_evidence_and_source_links_survive_in_table():
    data = report()
    finding = data["findings"][0]["findings"][0]
    finding.update(
        {
            "ai_assessment": "Verified evidence",
            "intent_basis": "G-INTENT: verified requirement",
            "reviewer": "reviewer",
            "comment_url": "https://example.org/comment",
            "code_snippets": [
                {
                    "language": "python",
                    "caption": "example.py:1",
                    "content": "value = '<literal>'",
                }
            ],
        }
    )
    soup = BeautifulSoup(grr.render_html(data), "html.parser")
    row = soup.select_one(".review-findings-table > tbody > tr.finding")
    assert "Verified evidence" in row.get_text()
    assert "G-INTENT: verified requirement" in row.get_text()
    assert "likelihood" in row.select_one(".risk-metrics[title]")["title"]
    assert "value = '<literal>'" in row.get_text()
    assert row.select_one('a[href="https://example.org/comment"]')
    assert soup.select_one(".report-heading h1")
    categories = {
        option.get("value") for option in soup.select("#filterCategory option")
    }
    assert {"architecture", "ux"} <= categories


def test_triage_keeps_its_existing_decision_controls():
    soup = BeautifulSoup(grr.render_triage(report()), "html.parser")
    assert soup.select("div.finding .triage-action")
    assert not soup.select(".review-findings-table")
