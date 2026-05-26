"""Tests for the verdict-chip color blender (`_verdict_color`).

Each verdict maps to a base color; ``confidence`` linearly blends RGB between
``BG_LIGHT`` (0.0) and the base color (1.0). Default confidence is 1.0 when
``None`` so a verdict with the LLM-confidence field absent still renders at
full saturation.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import generate_review_report as grr


def _hex_to_rgb(s: str) -> tuple[int, int, int]:
    s = s.lstrip("#")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


# ---------------------------------------------------------------------------
# Boundary: confidence = 1.0 → base color, 0.0 → BG_LIGHT.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "verdict, base",
    [
        ("valid", grr.GREEN),
        ("needs_investigation", grr.AMBER),
        ("out_of_scope", grr.ACCENT),
        ("false_positive", grr.TEXT_MUTED),
        ("duplicate", grr.TEXT_MUTED),
    ],
)
def test_full_confidence_is_base_color(verdict, base):
    assert grr._verdict_color(verdict, 1.0).upper() == base.upper()


@pytest.mark.parametrize(
    "verdict",
    ["valid", "needs_investigation", "out_of_scope", "false_positive", "duplicate"],
)
def test_zero_confidence_is_bg_light(verdict):
    assert grr._verdict_color(verdict, 0.0).upper() == grr.BG_LIGHT.upper()


# ---------------------------------------------------------------------------
# Midpoint: confidence = 0.5 → RGB halfway between BG_LIGHT and base.
# ---------------------------------------------------------------------------
def test_midpoint_is_linear_blend():
    base_r, base_g, base_b = _hex_to_rgb(grr.GREEN)
    bg_r, bg_g, bg_b = _hex_to_rgb(grr.BG_LIGHT)
    out = grr._verdict_color("valid", 0.5)
    r, g, b = _hex_to_rgb(out)
    assert abs(r - round((bg_r + base_r) / 2)) <= 1
    assert abs(g - round((bg_g + base_g) / 2)) <= 1
    assert abs(b - round((bg_b + base_b) / 2)) <= 1


# ---------------------------------------------------------------------------
# Default confidence when None → full saturation.
# ---------------------------------------------------------------------------
def test_none_confidence_defaults_to_full_saturation():
    assert grr._verdict_color("valid", None).upper() == grr.GREEN.upper()


def test_unknown_verdict_yields_bg_light_at_full_confidence():
    """An unrecognised verdict has no base color — render as plain background
    so the chip stays visible but neutral."""
    out = grr._verdict_color("totally_made_up", 1.0)
    assert out.upper() == grr.BG_LIGHT.upper()


# ---------------------------------------------------------------------------
# Confidence out of range — clamped, never raises.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("conf", [-0.5, 1.5, 2.0])
def test_confidence_clamped(conf):
    out = grr._verdict_color("valid", conf)
    if conf <= 0:
        assert out.upper() == grr.BG_LIGHT.upper()
    else:
        assert out.upper() == grr.GREEN.upper()


def test_output_is_hex_rrggbb():
    out = grr._verdict_color("valid", 0.7)
    assert out.startswith("#")
    assert len(out) == 7
    int(out[1:], 16)  # raises if not hex
