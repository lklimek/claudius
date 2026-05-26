"""Tests for the PDF font-discovery and Markdown-fallback helpers in
generate_review_report.py.

These cover the Unicode font auto-discovery (``_resolve_font_set``) and the
malformed-Markdown fallback path (``render_markdown_to_reportlab``). Tests
never touch real user fonts: ``CLAUDIUS_PDF_FONT`` is cleared and the system
candidate list is monkeypatched so behaviour is deterministic regardless of
which fonts the host has installed.
"""

from __future__ import annotations

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
