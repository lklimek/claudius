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

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

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


def _wrap_section(finding: dict) -> dict:
    """Wrap a finding into a minimal renderable report shape."""
    return {
        "schema_version": "3.0.0",
        "metadata": {"project": "p", "date": "2026-05-26"},
        "executive_summary": {"overall_assessment": "ok"},
        "summary_statistics": {
            "total_findings": 1,
            "severity_counts": {
                "CRITICAL": 0,
                "HIGH": 0,
                "MEDIUM": 0,
                "LOW": 0,
                "INFO": 0,
            },
            "category_counts": {},
            "agent_counts": {},
        },
        "findings": [{"category": "code_quality", "title": "T", "findings": [finding]}],
    }


def test_markdown_orphan_ai_assessment_label_suppressed():
    """A finding with ai_verdict but no ai_assessment must NOT produce an
    orphan 'AI Assessment' label with empty body."""
    finding = {
        "id": "X-001",
        "severity": 2,
        "title": "T",
        "location": "src/x.rs:1",
        "description": "D",
        "recommendation": "R",
        "ai_verdict": "valid",
        "ai_verdict_confidence": 0.8,
    }
    md = grr.render_markdown(_wrap_section(finding))
    # No trailing colon-with-empty-body for the AI block. The label may not
    # appear at all, or must include both verdict info AND non-empty body.
    assert "confidence: 0.80)*: \n" not in md
    assert "confidence: 0.80)*:\n" not in md
    # If the chip/verdict info is rendered, it should be in a self-contained
    # form (no dangling empty body).
    for line in md.splitlines():
        if "AI Assessment" in line:
            # Either no colon body, or it has content after the verdict info.
            assert not line.rstrip().endswith(":")


def test_markdown_snippet_content_with_backticks_uses_longer_fence():
    """A snippet whose content contains a triple-backtick sequence must NOT
    be wrapped in a fence that the content can terminate."""
    finding = {
        "id": "X-001",
        "severity": 2,
        "title": "T",
        "location": "src/x.rs:1",
        "description": "D",
        "recommendation": "R",
        "code_snippets": [
            {
                "language": "markdown",
                "caption": "embedded fence",
                "content": "before\n```\ninside\n```\nafter",
            }
        ],
    }
    md = grr.render_markdown(_wrap_section(finding))
    # The opening fence must be at least 4 backticks so the embedded ``` does
    # not terminate the fence.
    assert "````markdown" in md or "`````markdown" in md
    # The full inner content must appear without break-out.
    assert "before\n```\ninside\n```\nafter" in md


def test_markdown_snippet_caption_is_html_escaped():
    """Producer-supplied caption must not inject HTML into the Markdown output."""
    finding = {
        "id": "X-001",
        "severity": 2,
        "title": "T",
        "location": "src/x.rs:1",
        "description": "D",
        "recommendation": "R",
        "code_snippets": [
            {
                "language": "rust",
                "caption": "evil</summary><script>alert(1)</script>",
                "content": "ok",
            }
        ],
    }
    md = grr.render_markdown(_wrap_section(finding))
    # Raw script tag and closing summary must not survive verbatim.
    assert "<script>alert(1)</script>" not in md
    assert "evil</summary>" not in md
    # Escaped form must appear instead.
    assert "&lt;script&gt;" in md or "&lt;/summary&gt;" in md


def test_markdown_snippet_language_is_sanitized_against_fence_breakout():
    """Producer-supplied snippet `language` must be sanitized — a value
    containing newlines or backticks would otherwise terminate the fence
    early and inject arbitrary Markdown/HTML downstream."""
    finding = {
        "id": "X-001",
        "severity": 2,
        "title": "T",
        "location": "src/x.rs:1",
        "description": "D",
        "recommendation": "R",
        "code_snippets": [
            {
                "language": "python\n```\n<script>alert(1)</script>",
                "caption": "evil-lang",
                "content": "print('ok')",
            }
        ],
    }
    md = grr.render_markdown(_wrap_section(finding))
    # The injected script tag must NOT survive verbatim after the fence —
    # either the language is sanitized to a clean token or omitted entirely,
    # but the embedded raw HTML must never leak through the opening fence.
    assert "<script>alert(1)</script>" not in md
    # The fence itself must remain a single intact line — no embedded newline
    # in the language tag that would split the fence open.
    fence_lines = [ln for ln in md.splitlines() if ln.startswith("```")]
    assert fence_lines, "expected at least one fence line in rendered output"
    for ln in fence_lines:
        # After the backtick run, only allowlist chars (or empty) are valid.
        tail = ln.lstrip("`")
        assert re.fullmatch(
            r"[A-Za-z0-9_+.\-]*", tail
        ), f"fence info-string contains disallowed chars: {ln!r}"


def test_sanitize_snippet_language_legitimate_values_passthrough():
    """Allowlist sanitizer must preserve common legitimate language tokens
    like `python`, `rust`, `c++`, `objective-c`. Tokens containing
    disallowed chars keep only the safe leading run (e.g. `f#` -> `f`)."""
    helper = grr._sanitize_snippet_language
    assert helper("python") == "python"
    assert helper("rust") == "rust"
    assert helper("c++") == "c++"
    assert helper("objective-c") == "objective-c"
    assert helper("Java_Script") == "Java_Script"
    assert helper("ts.x") == "ts.x"
    # Hostile inputs keep only the safe leading run, so the rendered fence
    # carries a benign language tag (or nothing) — never a fence-breaking
    # newline or backtick.
    assert helper("python\n```evil") == "python"
    assert helper("f#") == "f"
    # Empty / whitespace / pure-hostile inputs collapse to empty so the
    # renderer falls back to a bare fence.
    assert helper("") == ""
    assert helper("   ") == ""
    assert helper("```") == ""
    assert helper("\n\n\n") == ""
    assert helper(None) == ""


def test_markdown_snippet_description_passthrough_markdown():
    """Description/recommendation/ai_assessment are documented as Markdown —
    confirm they pass through (so producers can use formatting) and do NOT
    get re-escaped into prose by the Markdown renderer."""
    finding = {
        "id": "X-001",
        "severity": 2,
        "title": "T",
        "location": "src/x.rs:1",
        "description": "**bold** and `code`",
        "recommendation": "* item one\n* item two",
    }
    md = grr.render_markdown(_wrap_section(finding))
    assert "**bold**" in md
    assert "`code`" in md
    assert "* item one" in md


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------
def test_html_permalink_anchor():
    data = _load("v3-full.json")
    html = grr.render_html(data)
    assert 'href="https://github.com/lklimek/claudius/blob/' in html
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


def test_html_renders_visible_float_chips_for_v3_findings():
    """Each finding with risk/impact/scope/overall_severity must surface
    them as visible chips in HTML, not just hover-tooltip."""
    finding = {
        "id": "X-001",
        "risk": 0.6,
        "impact": 0.7,
        "scope": 1.0,
        "overall_severity": 0.77,
        "severity": 4,
        "title": "T",
        "location": "src/x.rs:1",
        "description": "D",
        "recommendation": "R",
    }
    html = grr.render_html(_wrap_section(finding))
    # Chip text — visible, not just tooltip-attribute.
    assert "Overall 0.77" in html
    assert "R 0.60" in html
    assert "I 0.70" in html
    assert "S 1.00" in html
    # Tooltip-as-belt-and-braces still present.
    assert 'title="overall=0.77 risk=0.60 impact=0.70 scope=1.00"' in html


def test_html_omits_chips_when_floats_absent():
    """A minimal finding with the float dimensions absent (legacy / relaxed
    shape, NOT the v3 producer-shape contract which still requires
    ``risk``/``impact``/``scope``) must NOT render empty chips or crash."""
    finding = {
        "id": "X-001",
        "severity": 2,
        "title": "T",
        "location": "src/x.rs:1",
        "description": "D",
        "recommendation": "R",
    }
    html = grr.render_html(_wrap_section(finding))
    # No chip span should appear when the floats are absent (CSS class
    # declaration in <style> always exists; check for actual rendered chips).
    assert 'class="metric-chip' not in html


def test_html_chips_omit_when_floats_are_non_numeric():
    """Defensive guard, NOT the v3 producer-shape contract: a legacy report
    may carry a narrative string in ``impact`` (or any other float dimension)
    instead of a number. The renderer must not crash and must omit the chip
    for that non-numeric field while still rendering numeric peers. The
    producer-shape contract under v3 still requires the floats to be numeric."""
    finding = {
        "id": "X-001",
        # All four float dimensions as non-numeric. ``%.2f`` would raise
        # TypeError if the chip template tried to format these.
        "overall_severity": "high",
        "risk": "likely",
        "impact": "Allows remote code execution.",
        "scope": None,  # already covered by ``is not none`` — sanity peer.
        "severity": 3,
        "title": "T",
        "location": "src/x.rs:1",
        "description": "D",
        "recommendation": "R",
    }
    # Must not raise — the four chips must each be guarded with ``is number``.
    html = grr.render_html(_wrap_section(finding))
    # None of the four chips should appear when their underlying value is
    # non-numeric.
    assert 'class="metric-chip metric-overall"' not in html
    assert 'class="metric-chip metric-risk"' not in html
    assert 'class="metric-chip metric-impact"' not in html
    assert 'class="metric-chip metric-scope"' not in html


def test_html_chips_partial_numeric_renders_only_numeric_dimensions():
    """When some float dimensions are numeric and others are strings, only
    the numeric ones become chips. Guards must be per-field, not all-or-none."""
    finding = {
        "id": "X-001",
        "overall_severity": 0.55,  # numeric — chip expected
        "risk": "high",  # non-numeric — chip omitted
        "impact": 0.8,  # numeric — chip expected
        "scope": "broad",  # non-numeric — chip omitted
        "severity": 3,
        "title": "T",
        "location": "src/x.rs:1",
        "description": "D",
        "recommendation": "R",
    }
    html = grr.render_html(_wrap_section(finding))
    assert "Overall 0.55" in html
    assert "I 0.80" in html
    assert 'class="metric-chip metric-risk"' not in html
    assert 'class="metric-chip metric-scope"' not in html


def test_triage_chips_omit_when_floats_are_non_numeric():
    """Triage shares the HTML template — the same per-field numeric guard
    must hold there."""
    finding = {
        "id": "X-001",
        "overall_severity": "high",
        "risk": "likely",
        "impact": "narrative",
        "scope": "broad",
        "severity": 3,
        "title": "T",
        "location": "src/x.rs:1",
        "description": "D",
        "recommendation": "R",
    }
    triage = grr.render_triage(_wrap_section(finding))
    assert 'class="metric-chip' not in triage


def test_triage_renders_visible_float_chips_for_v3_findings():
    """Triage view inherits from HTML template — chips must surface there too."""
    finding = {
        "id": "X-001",
        "risk": 0.6,
        "impact": 0.7,
        "scope": 1.0,
        "overall_severity": 0.77,
        "severity": 4,
        "title": "T",
        "location": "src/x.rs:1",
        "description": "D",
        "recommendation": "R",
    }
    triage = grr.render_triage(_wrap_section(finding))
    assert "Overall 0.77" in triage
    assert "R 0.60" in triage
    assert "I 0.70" in triage
    assert "S 1.00" in triage


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


def test_html_ai_verdict_without_confidence_renders():
    """Schema makes ai_verdict_confidence optional; HTML/Triage must NOT crash
    when ai_verdict is present without ai_verdict_confidence."""
    finding = {
        "id": "X-001",
        "severity": 2,
        "title": "T",
        "location": "src/x.rs:1",
        "description": "D",
        "recommendation": "R",
        "ai_verdict": "valid",
        # NO ai_verdict_confidence.
    }
    report = _wrap_section(finding)
    # Must not raise.
    html = grr.render_html(report)
    triage = grr.render_triage(report)
    # Default confidence (1.0) chip background is rendered.
    assert "ai-verdict-chip" in html
    assert "ai-verdict-chip" in triage
    # The default-confidence label must read 1.00.
    assert 'title="confidence: 1.00"' in html
    assert 'title="confidence: 1.00"' in triage


def test_html_javascript_scheme_in_permalink_not_rendered_as_href():
    """Defense-in-depth: even if a malformed location_permalink slips through,
    the HTML renderer must not emit it as a clickable javascript: href."""
    finding = {
        "id": "X-001",
        "severity": 2,
        "title": "T",
        "location": "src/x.rs:1",
        "description": "D",
        "recommendation": "R",
        "location_permalink": "javascript:alert(1)",
    }
    html = grr.render_html(_wrap_section(finding))
    # No live javascript: href anywhere.
    assert 'href="javascript:' not in html
    assert "javascript:alert" not in html


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


def test_triage_finding_data_category_preserves_origin_category():
    """Regression: the triage renderer flattens all findings into a single
    `category: "all"` wrapper section. Each finding's `data-category` attribute
    on the rendered `<div>` must still reflect the ORIGINAL section category
    (so the category filter chip works) — not the post-flatten `"all"` value.
    """
    report = {
        "schema_version": "3.0.0",
        "metadata": {"project": "p", "date": "2026-05-26"},
        "executive_summary": {"overall_assessment": "ok"},
        "summary_statistics": {
            "total_findings": 2,
            "severity_counts": {
                "CRITICAL": 0,
                "HIGH": 0,
                "MEDIUM": 0,
                "LOW": 2,
                "INFO": 0,
            },
        },
        "findings": [
            {
                "title": "Security",
                "category": "security",
                "findings": [
                    {
                        "id": "SEC-001",
                        "severity": 2,
                        "title": "S",
                        "location": "src/a.rs:1",
                        "description": "d",
                        "recommendation": "r",
                    }
                ],
            },
            {
                "title": "PR Promises",
                "category": "pr_promises",
                "findings": [
                    {
                        "id": "PPM-001",
                        "severity": 2,
                        "title": "P",
                        "location": "PR-title",
                        "description": "d",
                        "recommendation": "r",
                    }
                ],
            },
        ],
    }
    html = grr.render_triage(report)
    sec_match = re.search(r'id="finding-SEC-001"[^>]*data-category="([^"]*)"', html)
    ppm_match = re.search(r'id="finding-PPM-001"[^>]*data-category="([^"]*)"', html)
    assert sec_match, "SEC-001 div not found in triage HTML"
    assert ppm_match, "PPM-001 div not found in triage HTML"
    assert (
        sec_match.group(1) == "security"
    ), f'SEC-001 data-category collapsed to "{sec_match.group(1)}" — expected "security"'
    assert (
        ppm_match.group(1) == "pr_promises"
    ), f'PPM-001 data-category collapsed to "{ppm_match.group(1)}" — expected "pr_promises"'


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
def test_markdown_matrix_includes_call_tree_column():
    """Stream A: the Markdown scoreboard table must surface the new
    call_tree category column (driven by CATEGORY_LABELS)."""
    data = _load("v3-call-tree.json")
    # The fixture has no pre-computed matrix; compute one to drive the renderer.
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "scripts"))
    import consolidate_reports as cr  # type: ignore

    data["summary_statistics"]["severity_category_matrix"] = cr.compute_statistics(
        data["findings"], []
    )["severity_category_matrix"]
    md = grr.render_markdown(data)
    assert "Call-Tree Inspection" in md, md[:2000]
    # The HIGH row must show the 1 finding under the call_tree column.
    # Find the HIGH line and assert it contains a 1 in the call_tree column.
    high_line = next(line for line in md.splitlines() if line.startswith("| HIGH "))
    # CATEGORY_LABELS order: security, project, code_quality, call_tree, ...
    # cells: | HIGH | sec | proj | cq | call_tree | doc | dep | cmt | ppm | total |
    cells = [c.strip() for c in high_line.split("|")]
    # cells[0] is leading empty, cells[1]="HIGH", then category cells.
    assert cells[1] == "HIGH"
    # The 4th category column is call_tree.
    assert cells[5] == "1", high_line


def test_html_includes_call_tree_in_filter_chip_and_js_labels():
    """Stream A: the HTML renderer must include call_tree in the category
    filter dropdown, the Chart.js category-label list, and the JS catLabels
    lookup — otherwise findings in that category render but can never be
    filtered or scored against."""
    data = _load("v3-call-tree.json")
    html = grr.render_html(data)
    # Filter <option> for category dropdown.
    assert '<option value="call_tree">Call-Tree Inspection</option>' in html
    # JS catLabels lookup carries the slug.
    assert '"call_tree":"Call-Tree Inspection"' in html
    # Chart.js category-label list (CATEGORY_LABELS values) carries the label.
    assert "Call-Tree Inspection" in html
    # The finding card data-category attribute reflects the new category.
    assert 'data-category="call_tree"' in html


def test_triage_includes_call_tree_in_filter_and_data_attribute():
    """The triage renderer shares the template; the filter chip and
    per-finding data-category must carry call_tree there too."""
    data = _load("v3-call-tree.json")
    html = grr.render_triage(data)
    assert '<option value="call_tree">Call-Tree Inspection</option>' in html
    assert 'data-category="call_tree"' in html


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
# Producer-shape report (no coordinator-derived fields) must render cleanly
# through every renderer. Mirrors the relaxed v3 schema — producer skills
# (e.g. check-pr-comments) emit reports with no `severity`, no
# `overall_severity`, no `location_permalink`, no AI fields, and the
# renderers must degrade gracefully instead of crashing.
# ---------------------------------------------------------------------------
def _producer_shape_report() -> dict:
    return {
        "schema_version": "3.0.0",
        "metadata": {"project": "p", "date": "2026-05-27"},
        "executive_summary": {"overall_assessment": "producer shape"},
        "summary_statistics": {
            "total_findings": 1,
            "severity_counts": {
                "CRITICAL": 0,
                "HIGH": 0,
                "MEDIUM": 0,
                "LOW": 1,
                "INFO": 0,
            },
        },
        "findings": [
            {
                "title": "Code Quality",
                "category": "code_quality",
                "findings": [
                    {
                        "id": "CODE-001",
                        "risk": 0.4,
                        "impact": 0.4,
                        "scope": 1.0,
                        "title": "Producer-shape finding",
                        "location": "src/example.rs:10-20",
                        "description": "Producer emitted no coordinator-derived fields.",
                        "recommendation": "Coordinator fills the rest later.",
                    }
                ],
            }
        ],
    }


def test_render_markdown_producer_shape_does_not_crash():
    md = grr.render_markdown(_producer_shape_report())
    assert "Producer-shape finding" in md
    # Sev label must not literally read "None".
    assert "(None)" not in md


def test_render_html_producer_shape_does_not_crash():
    html = grr.render_html(_producer_shape_report())
    assert "Producer-shape finding" in html
    assert "badge-None" not in html
    assert "finding-None" not in html


def test_render_triage_producer_shape_does_not_crash():
    html = grr.render_triage(_producer_shape_report())
    assert "Producer-shape finding" in html
    assert "badge-None" not in html


def test_render_pdf_producer_shape_does_not_crash(tmp_path):
    out = tmp_path / "producer.pdf"
    grr.render_pdf(_producer_shape_report(), out)
    assert out.is_file()
    assert out.stat().st_size > 500


def test_normalize_realigns_total_findings_with_rebuilt_counts():
    """Regression: when ``_normalize_summary_statistics`` rebuilds an all-zero
    ``severity_counts`` block, it must also realign ``total_findings`` so the
    HTML KPI can't disagree with the rebuilt counts. Feed a producer-shape
    report whose statistics block carries all-zero counts and a deliberately
    wrong ``total_findings``, then assert the recompute fixes both."""
    report = _producer_shape_report()
    report["summary_statistics"]["severity_counts"] = {
        "CRITICAL": 0,
        "HIGH": 0,
        "MEDIUM": 0,
        "LOW": 0,
        "INFO": 0,
    }
    report["summary_statistics"]["total_findings"] = 99  # deliberately wrong

    true_count = sum(len(sec["findings"]) for sec in report["findings"])
    grr._normalize_report(report)

    stats = report["summary_statistics"]
    assert stats["total_findings"] == true_count
    assert stats["total_findings"] == sum(stats["severity_counts"].values())


def test_normalize_fills_overall_severity_and_band_from_floats():
    """Regression: a producer-shape finding (floats only, no `severity`, no
    `overall_severity`) must come out of `_normalize_report` with BOTH
    `overall_severity == mean(risk, impact, scope)` AND the correct integer
    band — otherwise the Markdown overall suffix and HTML `data-overall` sort
    key stay empty."""
    report = _producer_shape_report()
    f = report["findings"][0]["findings"][0]
    f.pop("severity", None)
    f.pop("overall_severity", None)

    grr._normalize_report(report)

    expected_overall = (f["risk"] + f["impact"] + f["scope"]) / 3.0
    assert f["overall_severity"] == pytest.approx(expected_overall)
    # risk=0.4, impact=0.4, scope=1.0 -> overall=0.6 -> MEDIUM band (3).
    assert f["severity"] == 3


def test_normalize_fills_overall_severity_when_only_int_severity_present():
    """A finding carrying a valid integer `severity` but no `overall_severity`
    must still get `overall_severity` filled from the floats (the int severity
    is left untouched)."""
    report = _producer_shape_report()
    f = report["findings"][0]["findings"][0]
    f["severity"] = 4  # valid integer, deliberately not the float band
    f.pop("overall_severity", None)

    grr._normalize_report(report)

    expected_overall = (f["risk"] + f["impact"] + f["scope"]) / 3.0
    assert f["overall_severity"] == pytest.approx(expected_overall)
    assert f["severity"] == 4  # pre-existing valid int severity preserved


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


# ---------------------------------------------------------------------------
# Triage decision UI — regression for the v3-cutover silent breakage
# ---------------------------------------------------------------------------
# The triage view used to inject the per-finding decision dropdown via a
# post-hoc string `.replace()` anchored on `"  </dl>\n</div>\n{% endfor %}"`.
# When the v3 cutover (PR #35) added a `code_snippets` for-loop between
# `</dl>` and `</div>`, the anchor stopped matching, `.replace()` silently
# returned the unchanged string, and the decision UI vanished from every
# triage report. These tests pin the structural contract.


def test_triage_renders_decision_ui_for_every_finding():
    """Every finding card in --format triage must carry an action dropdown,
    a rationale input, and a decision-hint span."""
    data = _load("v3-full.json")
    finding_count = sum(len(sec["findings"]) for sec in data["findings"])
    assert finding_count > 0, "fixture must contain at least one finding"
    html = grr.render_triage(data)
    assert html.count('class="triage-action"') == finding_count
    assert html.count('class="triage-rationale"') == finding_count
    assert html.count('class="decision-hint"') == finding_count


def test_triage_renders_data_verdict_attribute_on_findings():
    """The triage filter for comment-check verdicts depends on each finding
    div carrying `data-verdict=...`. This used to be patched in by a separate
    `.replace()`; it now lives in the template behind `{% if triage %}`."""
    data = _load("v3-full.json")
    finding_count = sum(len(sec["findings"]) for sec in data["findings"])
    html = grr.render_triage(data)
    assert html.count("data-verdict=") == finding_count


def test_html_does_not_render_triage_decision_ui():
    """Inverse: the plain `--format html` view must NOT contain the per-finding
    decision dropdown or rationale input — those belong only to triage."""
    data = _load("v3-full.json")
    html = grr.render_html(data)
    assert 'class="triage-action"' not in html
    assert 'class="triage-rationale"' not in html
    assert 'class="decision-hint"' not in html


def test_triage_renders_decision_ui_when_findings_have_code_snippets():
    """Direct regression: a finding carrying `code_snippets` (the structural
    change that broke the old `.replace()` anchor) must still get a decision
    dropdown rendered after its snippet block."""
    finding = {
        "id": "X-001",
        "severity": 3,
        "title": "T",
        "location": "src/x.rs:1",
        "description": "D",
        "recommendation": "R",
        "code_snippets": [
            {"language": "rust", "caption": "snippet", "content": "fn x() {}"}
        ],
    }
    html = grr.render_triage(_wrap_section(finding))
    assert 'class="triage-action"' in html
    assert 'class="triage-rationale"' in html
    # The dropdown must appear AFTER the snippet block, inside the same
    # finding card (i.e. structurally adjacent — same string still present).
    snippet_pos = html.find("language-rust")
    dropdown_pos = html.find('class="triage-action"')
    assert snippet_pos != -1 and dropdown_pos != -1
    assert (
        dropdown_pos > snippet_pos
    ), "decision dropdown must render after the snippet inside the finding card"


# ---------------------------------------------------------------------------
# HTML sanitizer (Markdown -> safe HTML). The `| markdown` filter feeds
# attacker-influenced finding text (e.g. PR comment bodies) into a
# browser-opened report, so the allowlist must strip all active content.
# ---------------------------------------------------------------------------
def test_render_markdown_strips_script_tag():
    """A raw <script> in Markdown must never survive as a live tag."""
    out = str(grr.render_markdown_to_html("hi <script>alert(1)</script> bye"))
    assert "<script>" not in out
    assert "</script>" not in out
    # The literal call must not be reconstructable as executable markup.
    assert "<script" not in out.lower()


def test_render_markdown_strips_event_handler_attribute():
    """`on*` handler attributes (onerror, onclick, ...) must be dropped."""
    out = str(grr.render_markdown_to_html('<img src=x onerror="alert(1)">'))
    assert "onerror" not in out.lower()
    assert "alert(1)" not in out or "onerror" not in out.lower()


def test_render_markdown_strips_javascript_uri():
    """A javascript: URI must not survive as a live href."""
    out = str(grr.render_markdown_to_html("[click](javascript:alert(1))"))
    assert "javascript:" not in out.lower()
    assert 'href="javascript:' not in out.lower()


def test_render_markdown_strips_iframe():
    """<iframe> is active content and must be stripped."""
    out = str(grr.render_markdown_to_html('text <iframe src="evil"></iframe>'))
    assert "<iframe" not in out.lower()


def test_render_markdown_preserves_allowed_markup():
    """The migration must NOT weaken rendering of legitimate Markdown: bold,
    inline code, and http(s) links stay intact."""
    out = str(grr.render_markdown_to_html("**bold** `code` [x](https://example.com)"))
    assert "<strong>bold</strong>" in out
    assert "<code>code</code>" in out
    assert 'href="https://example.com"' in out


def test_render_markdown_empty_returns_empty_markup():
    from markupsafe import Markup

    assert grr.render_markdown_to_html("") == Markup("")
    assert grr.render_markdown_to_html("   ") == Markup("")


def test_html_end_to_end_strips_script_in_description():
    """Defense-in-depth end-to-end: a <script> injected into a finding's
    Markdown description must not reach the rendered HTML as a live tag."""
    finding = {
        "id": "X-001",
        "severity": 3,
        "title": "T",
        "location": "src/x.rs:1",
        "description": "before <script>alert(document.cookie)</script> after",
        "recommendation": "R",
    }
    html = grr.render_html(_wrap_section(finding))
    assert "<script>alert(document.cookie)</script>" not in html
    assert "alert(document.cookie)" in html or "before" in html  # text survives


# ---------------------------------------------------------------------------
# Chart.js supply chain: the report is documented as "self-contained", so it
# must not fetch third-party JS from a CDN at open time (a CDN compromise or a
# malicious `latest` publish would run arbitrary JS in the report's origin).
# ---------------------------------------------------------------------------
def test_html_does_not_load_chartjs_from_unpinned_cdn():
    data = _load("v3-full.json")
    html = grr.render_html(data)
    assert 'src="https://cdn.jsdelivr.net/npm/chart.js"' not in html
    assert "cdn.jsdelivr.net/npm/chart.js<" not in html
    # No remote <script src=...> for charts at all — Chart.js is vendored inline.
    assert 'src="https://cdn.jsdelivr.net/npm/chart.js' not in html


def test_html_inlines_vendored_chartjs():
    """Chart.js must be embedded inline (self-contained) and drives real charts."""
    data = _load("v3-full.json")
    html = grr.render_html(data)
    assert "Chart.js v4.5.1" in html  # vendored UMD banner proves inline embed
    assert "new Chart(" in html  # chart-drawing code still present


def test_vendored_chartjs_matches_pinned_sha256():
    """The vendored blob must match the sha256 pinned in generate_review_report.py.

    The inline-embed test only checks the version banner, which a tampered blob can
    keep verbatim. This pins the exact bytes so any modification to the vendored
    Chart.js fails CI instead of silently shipping arbitrary JS into every report.
    """
    pinned = "ecc3cd1eeb8c34d2178e3f59fd63ec5a3d84358c11730af0b9958dc886d7652a"
    actual = hashlib.sha256(grr._CHARTJS_VENDOR_PATH.read_bytes()).hexdigest()
    assert actual == pinned, (
        f"vendored chart.umd.js sha256 {actual} != pinned {pinned}; "
        "update the pin in generate_review_report.py only for a verified Chart.js build"
    )


def test_triage_does_not_load_chartjs_from_unpinned_cdn():
    data = _load("v3-full.json")
    html = grr.render_triage(data)
    assert 'src="https://cdn.jsdelivr.net/npm/chart.js"' not in html
    assert "Chart.js v4.5.1" in html
