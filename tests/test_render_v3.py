"""End-to-end render tests for v3 fields across Markdown / HTML / Triage / PDF.

Covers:
- Permalink rendering (location wrapped in `<a>` / `[text](url)`).
- Code-snippet HTML escape (no XSS sneak-through).
- Markdown GFM `<details>` blank-line placement.
- PDF 200-line snippet truncation.
- Graceful fallback when every optional field is absent.
- Verdict chip background gradient between high- and low-confidence fixtures.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import generate_review_report as grr

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "reports"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def test_location_link_with_permalink():
    f = {"location": "src/a.rs:1-2", "location_permalink": "https://example/x"}
    link = grr._location_link(f)
    assert link["text"] == "src/a.rs:1-2"
    assert link["url"] == "https://example/x"


def test_location_link_without_permalink():
    f = {"location": "src/a.rs:1-2"}
    link = grr._location_link(f)
    assert link["text"] == "src/a.rs:1-2"
    assert link["url"] is None


def test_severity_tooltip_with_floats():
    f = {"overall_severity": 0.9, "risk": 0.8, "impact": 1.0, "scope": 1.0}
    tip = grr._severity_tooltip(f)
    assert "overall=0.90" in tip
    assert "risk=0.80" in tip
    assert "impact=1.00" in tip
    assert "scope=1.00" in tip


def test_severity_tooltip_absent_floats():
    assert grr._severity_tooltip({}) == ""


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------
def test_markdown_permalink_renders_as_link():
    data = _load("v3-full.json")
    md = grr.render_markdown(data)
    # SEC-001 has a permalink — location should appear inside a Markdown link.
    assert "[`src/auth.rs:42-56`](https://github.com/" in md


def test_markdown_severity_breakdown_appended():
    data = _load("v3-full.json")
    md = grr.render_markdown(data)
    # SEC-001 has overall=1.0 risk=1.0 impact=1.0 scope=1.0.
    assert "overall=1.00" in md and "risk=1.00" in md


def test_markdown_ai_block_present():
    data = _load("v3-full.json")
    md = grr.render_markdown(data)
    assert "AI Assessment" in md
    assert "verdict: valid" in md
    assert "confidence: 0.95" in md


def test_markdown_code_snippet_has_blank_lines_around_details_and_fence():
    data = _load("v3-full.json")
    md = grr.render_markdown(data)
    # Required for GitHub's renderer: blank line before `<details>`,
    # blank line after `<summary>`, blank line around fenced code, blank
    # line before `</details>`.
    pat = re.compile(
        r"\n\n<details><summary>[^\n]+</summary>\n\n```\w*\n.*?\n```\n\n</details>\n",
        re.DOTALL,
    )
    assert pat.search(md), f"snippet block not formatted correctly:\n{md[:2000]}"


def test_markdown_minimal_fixture_renders_cleanly():
    data = _load("v3-minimal.json")
    md = grr.render_markdown(data)
    # No `<details>` because no snippets; no AI Assessment block; no permalink.
    assert "<details>" not in md
    assert "AI Assessment" not in md
    assert "`src/example.rs:10-20`" in md  # plain backticked location
    assert "](http" not in md  # no permalink link


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------
def test_html_permalink_anchor():
    data = _load("v3-full.json")
    html = grr.render_html(data)
    assert 'href="https://github.com/lklimek_test/claudius/blob/' in html
    assert 'target="_blank"' in html


def test_html_severity_badge_tooltip():
    data = _load("v3-full.json")
    html = grr.render_html(data)
    assert "overall=1.00 risk=1.00 impact=1.00 scope=1.00" in html


def test_html_ai_verdict_chip_present():
    data = _load("v3-full.json")
    html = grr.render_html(data)
    assert "ai-verdict-chip" in html
    assert ">valid<" in html


def test_html_code_snippet_content_is_escaped():
    """Producers may emit arbitrary code — snippet content must be HTML-escaped,
    not Markdown-rendered. A `<script>` in the content must NOT survive as a
    live tag in the output.
    """
    data = _load("v3-full.json")
    # Inject a script tag into a snippet content and confirm it's escaped.
    data["findings"][0]["findings"][0]["code_snippets"][0][
        "content"
    ] = "<script>alert('xss')</script>\nlet x = 1;"
    html = grr.render_html(data)
    assert "&lt;script&gt;alert(" in html
    assert "<script>alert('xss')</script>" not in html


def test_html_data_overall_and_data_ai_verdict_present():
    """The non-triage HTML carries `data-overall` (float, for sort) and
    `data-ai-verdict` (AI verdict, for filter). The comment-check
    `data-verdict` lives only on triage pages."""
    data = _load("v3-full.json")
    html = grr.render_html(data)
    assert 'data-overall="1.0"' in html
    assert 'data-ai-verdict="valid"' in html


def test_html_ai_verdict_filter_uses_distinct_id():
    """The AI verdict filter must use `filterAiVerdict`, distinct from the
    comment-check `verdictFilter` id, so both can coexist."""
    data = _load("v3-full.json")
    html = grr.render_html(data)
    assert 'id="filterAiVerdict"' in html


def test_html_sort_by_overall_option_and_default():
    data = _load("v3-full.json")
    html = grr.render_html(data)
    # Option present.
    assert '<option value="overall"' in html
    # Default-selected (the dropdown should mark overall as the default).
    assert 'value="overall" selected' in html or 'selected value="overall"' in html


def test_html_minimal_fixture_renders_cleanly():
    """Graceful degradation: no permalinks, no snippets, no AI fields."""
    data = _load("v3-minimal.json")
    html = grr.render_html(data)
    assert "ai-verdict-chip" not in html  # no AI fields
    assert "<details><summary>" not in html  # no snippets
    # Plain text location (no anchor wrapping the location code).
    assert "<code>src/example.rs:10-20</code>" in html
    assert 'href="None"' not in html
    assert 'href=""' not in html


def test_html_verdict_chip_gradient_differs_between_high_and_low_confidence():
    """A confidence=0.95 chip and a confidence=0.3 chip must render with
    distinct background colors — proves the gradient logic flows through
    to the rendered markup."""
    data = _load("v3-full.json")
    html = grr.render_html(data)
    # SEC-001 has valid @ 0.95; CODE-001 has valid @ 0.3. The chip background
    # for the latter is heavily faded toward BG_LIGHT.
    sec_color = grr._verdict_color("valid", 0.95)
    code_color = grr._verdict_color("valid", 0.3)
    assert sec_color.upper() != code_color.upper()
    assert sec_color in html or sec_color.upper() in html.upper()
    assert code_color in html or code_color.upper() in html.upper()


# ---------------------------------------------------------------------------
# Triage
# ---------------------------------------------------------------------------
def test_triage_has_ai_verdict_filter():
    data = _load("v3-full.json")
    html = grr.render_triage(data)
    assert 'id="filterAiVerdict"' in html


def test_triage_minimal_renders():
    data = _load("v3-minimal.json")
    html = grr.render_triage(data)
    assert "<html" in html
    assert "ai-verdict-chip" not in html


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
def test_pdf_full_renders(tmp_path):
    data = _load("v3-full.json")
    out = tmp_path / "out.pdf"
    grr.render_pdf(data, out)
    assert out.is_file()
    assert out.stat().st_size > 1000  # non-trivial


def test_pdf_minimal_renders(tmp_path):
    data = _load("v3-minimal.json")
    out = tmp_path / "min.pdf"
    grr.render_pdf(data, out)
    assert out.is_file()


def test_pdf_truncates_long_snippet(tmp_path):
    """A snippet longer than 200 lines must get a truncation marker. We can't
    introspect PDF content easily, so we drive `render_finding` indirectly via
    the helper that prepares the snippet text."""
    long = "\n".join(f"line {i}" for i in range(500))
    truncated, omitted = grr._truncate_snippet(long, 200)
    assert truncated.count("\n") <= 200
    assert omitted == 500 - 200
    assert "[truncated" in truncated


def test_pdf_short_snippet_not_truncated():
    short = "\n".join(f"line {i}" for i in range(10))
    truncated, omitted = grr._truncate_snippet(short, 200)
    assert truncated == short
    assert omitted == 0


# ---------------------------------------------------------------------------
# Pre-computed verdict chip background on context
# ---------------------------------------------------------------------------
def test_build_html_context_precomputes_chip_bg():
    data = _load("v3-full.json")
    ctx = grr._build_html_context(data)
    # The first section's first finding has ai_verdict + confidence.
    sec = ctx["findings"][0]
    f = sec["findings"][0]
    assert "_verdict_chip_bg" in f
    assert f["_verdict_chip_bg"].startswith("#")


def test_build_html_context_omits_chip_bg_when_no_verdict():
    data = _load("v3-minimal.json")
    ctx = grr._build_html_context(data)
    f = ctx["findings"][0]["findings"][0]
    assert f.get("_verdict_chip_bg") is None or "_verdict_chip_bg" not in f


# ---------------------------------------------------------------------------
# Regression: existing v2 `impact` string handling is gone — `impact` is now a
# float; `impact_description` carries the narrative.
# ---------------------------------------------------------------------------
def test_markdown_uses_impact_description_not_impact_float():
    data = _load("v3-full.json")
    md = grr.render_markdown(data)
    # SEC-001's narrative lives in impact_description.
    assert "Anyone with disk access can recover production credentials." in md
    # The float `1.0` must not appear as the "Impact" body line.
    assert "- **Impact**: 1.0" not in md


def test_html_uses_impact_description_not_impact_float():
    data = _load("v3-full.json")
    html = grr.render_html(data)
    assert "Anyone with disk access can recover production credentials." in html
    # If we accidentally rendered the float, we'd see ">1.0<" inside the Impact dd.
    assert "<dd>1.0</dd>" not in html
