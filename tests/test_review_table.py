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
        assert len(row.find_all("td", recursive=False)) == 5
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
    assert "likelihood" in row.select_one(".finding-head .badge[title]")["title"]
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


def test_combined_cells_and_final_decision_column():
    data = report()
    finding = data["findings"][0]["findings"][0]
    finding["tags"] = ["kv-keys", "upgrade-path"]
    soup = BeautifulSoup(grr.render_html(data), "html.parser")
    row = soup.select_one(".review-findings-table > tbody > tr")
    cells = row.find_all("td", recursive=False)
    assert (
        finding["id"] in cells[0].get_text()
        and finding["location"] in cells[0].get_text()
    )
    assert finding["title"] in cells[1].get_text()
    assert [tag.get_text() for tag in cells[1].select(".tag")] == finding["tags"]
    assert cells[-1].select_one("select.review-action")
    assert cells[-1].select_one("textarea.review-rationale")
    assert not row.select(".risk-metrics")
    assert soup.select_one("#exportReviewDecisions")
    for link in soup.select("#toc a"):
        assert len(link.get_text().split()) <= 3


def test_long_markdown_is_folded_by_text_length_without_cutting_html():
    env = grr._html_environment()
    render = env.filters["markdown"]
    assert "folded-text" not in str(render("x" * 1000))
    html = str(render("**" + "ą" * 1001 + "**\n\n[tail](https://example.org/path)"))
    soup = BeautifulSoup(html, "html.parser")
    assert len(soup.select_one(".text-preview").get_text()) == 1001
    full = soup.select_one(".text-full")
    assert full.has_attr("hidden")
    assert full.select_one("strong").get_text() == "ą" * 1001
    assert full.select_one("a")["href"] == "https://example.org/path"
    assert soup.select_one("button.text-toggle")["aria-expanded"] == "false"
    long_url = "https://example.org/" + "x" * 1500
    assert "folded-text" not in str(render(f"[ok]({long_url})"))


def test_collapsing_counts_visible_whitespace_and_preserves_literal_text():
    env = grr._html_environment()
    spaces = "A" + " " * 1500 + "B"
    assert "folded-text" not in str(env.filters["markdown"]("x" * 1000 + " <em> </em>"))
    assert "folded-text" not in str(env.filters["markdown"](spaces))
    assert "folded-text" in str(env.filters["markdown"]("```\n" + spaces + "\n```"))
    assert "folded-text" in str(env.filters["fold_literal"](spaces))
    assert "folded-text" not in str(env.filters["markdown"]("x" * 998 + " <em> B</em>"))
    assert "folded-text" in str(env.filters["markdown"]("x" * 999 + " <em> B</em>"))
    assert "folded-text" not in str(
        env.filters["markdown"]("<p>" + "x" * 1000 + " </p>")
    )


def test_long_titles_positive_observations_and_verdict_action_are_folded():
    data = report()
    data["findings"][0]["findings"][0]["title"] = "title " * 250
    data["findings"][0]["positives"] = "positive " * 200
    data["executive_summary"]["verdict_action"] = "action " * 200
    soup = BeautifulSoup(grr.render_html(data), "html.parser")
    assert soup.select_one(".finding-title .text-toggle")
    assert soup.select_one(".positives .text-toggle")
    assert soup.select_one(".verdict .text-toggle")
