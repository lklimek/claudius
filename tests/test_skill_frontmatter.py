"""Regression guard: every skill/agent YAML frontmatter must parse cleanly via PyYAML.

A skill or agent whose frontmatter fails to parse loads with empty metadata at
runtime — all frontmatter fields are silently dropped, breaking tool permissions,
descriptions, model selection, and skills preloading. Catching this in CI keeps
authors from shipping a SKILL.md with an unquoted colon, a stray tab, or any
other YAML poison that `claude plugin validate` rejects.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

FRONTMATTER_FILES = sorted(REPO_ROOT.glob("skills/*/SKILL.md")) + sorted(
    REPO_ROOT.glob("agents/*.md")
)


def _extract_frontmatter(path: Path) -> str:
    """Return the raw YAML frontmatter block between the first two `---` fences."""
    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise AssertionError(f"{path}: no `---` frontmatter delimiters found")
    return parts[1]


@pytest.mark.parametrize(
    "path", FRONTMATTER_FILES, ids=lambda p: str(p.relative_to(REPO_ROOT))
)
def test_frontmatter_parses(path: Path) -> None:
    raw = _extract_frontmatter(path)
    data = yaml.safe_load(raw)
    assert isinstance(
        data, dict
    ), f"{path}: frontmatter parsed to {type(data).__name__}, expected dict"
    assert "name" in data, f"{path}: frontmatter missing required `name` field"


def test_corpus_not_empty() -> None:
    """Guard against the glob silently matching nothing (e.g. after a directory rename)."""
    assert (
        FRONTMATTER_FILES
    ), "No SKILL.md or agent .md files discovered — glob is broken"
