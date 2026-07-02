"""Tests for the PDF font-discovery and Markdown-fallback helpers in
generate_review_report.py.

These cover the Unicode font auto-discovery (``_resolve_font_set``) and the
malformed-Markdown fallback path (``render_markdown_to_reportlab``). Tests
never touch real user fonts: ``CLAUDIUS_PDF_FONT`` is cleared and the system
candidate list is monkeypatched so behaviour is deterministic regardless of
which fonts the host has installed.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import generate_review_report as grr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def isolated_fonts(monkeypatch, tmp_path):
    """Neutralize host font state: no env override, no bundled dir, no system
    candidates. Tests opt back into whichever source they exercise.
    """
    monkeypatch.delenv("CLAUDIUS_PDF_FONT", raising=False)
    monkeypatch.setattr(grr, "_FONT_CANDIDATES", [])
    empty_dir = tmp_path / "no-fonts"
    empty_dir.mkdir()
    monkeypatch.setattr(grr, "_bundled_font_dir", lambda: empty_dir)
    return tmp_path


def _touch(path: Path) -> Path:
    path.write_bytes(b"\x00\x01ttf-stub")
    return path


# ---------------------------------------------------------------------------
# _resolve_font_set — env override
# ---------------------------------------------------------------------------
def test_env_override_valid_ttf(isolated_fonts, monkeypatch):
    font = _touch(isolated_fonts / "MyFont.ttf")
    monkeypatch.setenv("CLAUDIUS_PDF_FONT", str(font))

    fonts = grr._resolve_font_set()

    assert fonts is not None
    assert fonts["regular"] == str(font)
    # No siblings on disk: bold/italic and the mono slot reuse the regular face.
    assert fonts["bold"] == str(font)
    assert fonts["mono"] == str(font)


def test_env_override_picks_up_siblings(isolated_fonts, monkeypatch):
    regular = _touch(isolated_fonts / "MyFont.ttf")
    bold = _touch(isolated_fonts / "MyFont-Bold.ttf")
    oblique = _touch(isolated_fonts / "MyFont-Oblique.ttf")
    monkeypatch.setenv("CLAUDIUS_PDF_FONT", str(regular))

    fonts = grr._resolve_font_set()

    assert fonts is not None
    assert fonts["bold"] == str(bold)
    assert fonts["italic"] == str(oblique)
    # boldItalic sibling absent -> reuse regular; mono always reuses regular.
    assert fonts["boldItalic"] == str(regular)
    assert fonts["mono"] == str(regular)


def test_env_override_missing_file_warns(isolated_fonts, monkeypatch, caplog):
    missing = isolated_fonts / "nope.ttf"
    monkeypatch.setenv("CLAUDIUS_PDF_FONT", str(missing))

    with caplog.at_level("WARNING", logger=grr.log.name):
        fonts = grr._resolve_font_set()

    assert fonts is None
    assert "is not a readable file" in caplog.text


def test_env_override_non_ttf_warns(isolated_fonts, monkeypatch, caplog):
    not_ttf = _touch(isolated_fonts / "MyFont.otf")
    monkeypatch.setenv("CLAUDIUS_PDF_FONT", str(not_ttf))

    with caplog.at_level("WARNING", logger=grr.log.name):
        fonts = grr._resolve_font_set()

    assert fonts is None
    assert "is not a .ttf file" in caplog.text


# ---------------------------------------------------------------------------
# _resolve_font_set — bundled dir and system candidates
# ---------------------------------------------------------------------------
def test_user_supplied_bundled_dir(isolated_fonts, monkeypatch):
    font_dir = isolated_fonts / "fonts"
    font_dir.mkdir()
    regular = _touch(font_dir / "DejaVuSans.ttf")
    _touch(font_dir / "DejaVuSans-Bold.ttf")
    monkeypatch.setattr(grr, "_bundled_font_dir", lambda: font_dir)

    fonts = grr._resolve_font_set()

    assert fonts is not None
    assert fonts["regular"] == str(regular)
    assert fonts["bold"] == str(font_dir / "DejaVuSans-Bold.ttf")
    # Mono variant absent -> reuse regular.
    assert fonts["mono"] == str(regular)


def test_system_candidate_fallback(isolated_fonts, monkeypatch):
    regular = _touch(isolated_fonts / "SysSans.ttf")
    candidate = {
        "regular": str(regular),
        "bold": str(isolated_fonts / "SysSans-Bold.ttf"),  # absent
        "italic": str(isolated_fonts / "SysSans-Italic.ttf"),  # absent
        "boldItalic": str(isolated_fonts / "SysSans-BI.ttf"),  # absent
        "mono": str(isolated_fonts / "SysMono.ttf"),  # absent
        "monoBold": str(isolated_fonts / "SysMono-Bold.ttf"),  # absent
    }
    monkeypatch.setattr(grr, "_FONT_CANDIDATES", [candidate])

    fonts = grr._resolve_font_set()

    assert fonts is not None
    assert fonts["regular"] == str(regular)
    # Every missing variant falls back to the regular face.
    assert fonts["bold"] == str(regular)
    assert fonts["mono"] == str(regular)


def test_no_font_returns_none(isolated_fonts):
    assert grr._resolve_font_set() is None


# ---------------------------------------------------------------------------
# render_markdown_to_reportlab
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_markdown_empty_yields_no_blocks(text):
    assert grr.render_markdown_to_reportlab(text) == []


def test_markdown_valid_renders_blocks():
    blocks = grr.render_markdown_to_reportlab("# Title\n\nA **bold** word.")

    kinds = [kind for kind, _ in blocks]
    assert "h1" in kinds
    assert "para" in kinds
    body = "".join(body for _, body in blocks)
    assert "Title" in body
    assert "<b>bold</b>" in body or "bold" in body


# ---------------------------------------------------------------------------
# v3 smoke test — round-trips a minimal report through every renderer to catch
# accidental regressions in the field-renaming (`impact_description`) and the
# new optional fields (`location_permalink`, `code_snippets`, AI fields).
# ---------------------------------------------------------------------------
def test_v3_minimal_round_trips_through_all_renderers(tmp_path):
    import json as _json

    fx = Path(__file__).resolve().parent / "fixtures" / "reports" / "v3-minimal.json"
    data = _json.loads(fx.read_text(encoding="utf-8"))
    md = grr.render_markdown(data)
    html = grr.render_html(data)
    triage = grr.render_triage(data)
    pdf_out = tmp_path / "smoke.pdf"
    grr.render_pdf(data, pdf_out)
    assert "Example finding without optional fields" in md
    assert "Example finding without optional fields" in html
    assert "Example finding without optional fields" in triage
    assert pdf_out.is_file() and pdf_out.stat().st_size > 1000


# ---------------------------------------------------------------------------
# Scoreboard / category coverage — every renderer must surface ALL registered
# categories, not a hardcoded subset. Regression for the post-Pass-C gap where
# `pr_promises`, `pr_comments`, and `dependencies` were missing from the
# scoreboard table / category bar chart in Markdown, HTML, JS dashboard, and
# PDF.
# ---------------------------------------------------------------------------
def _mixed_category_report() -> dict:
    """Build a v3 report containing one finding in each of the categories that
    were previously missing from the renderer scoreboards."""
    sections = []
    cats_with_prefix = [
        ("code_quality", "CODE", "Code quality finding"),
        ("pr_promises", "PPM", "Promise mismatch"),
        ("pr_comments", "CMT", "Comment verification"),
        ("dependencies", "DEP", "Vulnerable dependency"),
        ("documentation", "DOC", "Doc finding"),
    ]
    matrix = []
    for label in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"):
        row = {"severity": label, "total": 0}
        for cat, _, _ in cats_with_prefix:
            row[cat] = 0
        matrix.append(row)
    sev_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 1, "INFO": 0}
    for cat, prefix, title in cats_with_prefix:
        sections.append(
            {
                "title": cat.replace("_", " ").title(),
                "category": cat,
                "findings": [
                    {
                        "id": f"{prefix}-001",
                        "severity": 2,
                        "title": title,
                        "location": "n/a",
                        "description": "d",
                        "recommendation": "r",
                    }
                ],
            }
        )
        for row in matrix:
            if row["severity"] == "LOW":
                row[cat] = 1
                row["total"] += 1
        sev_counts["LOW"] = sum(r["total"] for r in matrix if r["severity"] == "LOW")
    return {
        "schema_version": "3.0.0",
        "metadata": {"project": "p", "date": "2026-05-26"},
        "executive_summary": {"overall_assessment": "ok"},
        "summary_statistics": {
            "total_findings": len(cats_with_prefix),
            "severity_counts": sev_counts,
            "severity_category_matrix": matrix,
        },
        "findings": sections,
    }


_EXPECTED_SCOREBOARD_LABELS = [
    "Code Quality",
    "PR Promises",
    "PR Comments",
    "Dependencies",
    "Documentation",
]


def test_markdown_scoreboard_includes_all_categories():
    md = grr.render_markdown(_mixed_category_report())
    for label in _EXPECTED_SCOREBOARD_LABELS:
        assert label in md, f"Markdown scoreboard missing category label: {label}"


def test_html_scoreboard_table_includes_all_categories():
    """The HTML severity x category matrix table must surface ALL categories
    present in the report — not a hardcoded 4-column subset that drops
    pr_promises, pr_comments, and dependencies."""
    html = grr.render_html(_mixed_category_report())
    # The matrix table starts with the header row `<tr><th>Severity</th>...`.
    # Extract just that table's HTML and check every category label appears.
    m = re.search(r"<table>\s*<tr><th>Severity</th>(.*?)</table>", html, re.DOTALL)
    assert m, "Severity x category matrix table not found in HTML"
    table_html = m.group(0)
    for label in _EXPECTED_SCOREBOARD_LABELS:
        assert label in table_html, (
            f"HTML scoreboard table missing category column: {label}"
        )


def test_html_js_categorychart_includes_all_categories():
    """The Chart.js category bar chart's `cats`/`catLabels` arrays must list
    every category present in the report — previously hardcoded to 4."""
    html = grr.render_html(_mixed_category_report())
    # Locate the `cats = [...]` array immediately above the categoryChart
    # instantiation. Inline JS may render the array on one line or span lines.
    m = re.search(
        r"const cats\s*=\s*(\[[^\]]*\])\s*;\s*\n\s*const catLabels\s*=\s*(\[[^\]]*\])",
        html,
    )
    assert m, "cats / catLabels JS arrays not found"
    cats_arr, label_arr = m.group(1), m.group(2)
    expected_slugs = [
        "code_quality",
        "pr_promises",
        "pr_comments",
        "dependencies",
        "documentation",
    ]
    for slug in expected_slugs:
        assert f'"{slug}"' in cats_arr, f"cats array missing slug: {slug}"
    for label in ("PR Promises", "PR Comments", "Dependencies", "Code Quality"):
        assert f'"{label}"' in label_arr, f"catLabels missing label: {label}"


def test_pdf_scoreboard_includes_all_categories(tmp_path):
    """PDF text-extraction smoke: render then parse the PDF text via pypdf and
    assert every scoreboard category label appears at least once. Tight column
    widths can break a label across glyph lines (e.g. ``"PR Pro\nmises"``),
    so we strip whitespace before matching."""
    pypdf = pytest.importorskip("pypdf")
    out = tmp_path / "scoreboard.pdf"
    grr.render_pdf(_mixed_category_report(), out)
    raw = "".join(page.extract_text() or "" for page in pypdf.PdfReader(str(out)).pages)
    text = re.sub(r"\s+", "", raw)
    for label in _EXPECTED_SCOREBOARD_LABELS:
        compact = re.sub(r"\s+", "", label)
        assert compact in text, f"PDF scoreboard missing category label: {label}"


def test_markdown_fallback_on_parser_error(monkeypatch, caplog):
    """When the Markdown parse raises, the helper logs (with traceback) and
    returns a single escaped preformatted block — no exception escapes, no
    content dropped.
    """
    raw = "<unclosed & raw text"

    class _Boom:
        def __init__(self, *a, **kw):
            pass

        def convert(self, _s):
            raise ValueError("simulated parser failure")

    monkeypatch.setattr(grr, "_RL_MONO_FONT", "Courier")
    import markdown as _md

    monkeypatch.setattr(_md, "Markdown", _Boom)

    with caplog.at_level("WARNING", logger=grr.log.name):
        blocks = grr.render_markdown_to_reportlab(raw)

    assert len(blocks) == 1
    kind, body = blocks[0]
    assert kind == "pre"
    # Content preserved and XML-escaped, not silently swallowed.
    assert "&lt;unclosed &amp; raw text" in body
    assert "conversion failed" in caplog.text
    # exc_info=True attaches the traceback to the record.
    assert caplog.records[-1].exc_info is not None
