"""Guard: the blocker-gate vocabulary in code matches the doctrine.

`skills/severity/SKILL.md` §2 is the source of truth for the gates;
`severity_util.GATE_IDS` mirrors it so the pipeline can enforce what the
doctrine states. Two copies drift silently unless something compares them, and
a gate present in the doctrine but missing from the code is unenforceable —
exactly the hole that let `intent_basis` accept any non-empty string.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from severity_util import GATE_CITATION_RE, GATE_IDS  # noqa: E402

SKILL = ROOT / "skills" / "severity" / "SKILL.md"
# Gate table rows: | **G-ID** | trips when ... | zone |
_GATE_ROW_RE = re.compile(r"^\|\s*\*\*(G-[A-Z-]+)\*\*\s*\|", re.MULTILINE)


def documented_gates() -> list[str]:
    return _GATE_ROW_RE.findall(SKILL.read_text(encoding="utf-8"))


def test_skill_still_documents_a_gate_table():
    """Guards the guard: a reworded table must not silently empty this file."""
    assert len(documented_gates()) >= 10


def test_code_vocabulary_matches_the_doctrine_exactly():
    assert list(GATE_IDS) == documented_gates()


def test_gate_ids_are_unique():
    assert len(set(GATE_IDS)) == len(GATE_IDS)


@pytest.mark.parametrize("gate", GATE_IDS)
def test_every_gate_is_citable(gate):
    """Each ID must satisfy the citation pattern the validator enforces —
    otherwise a correctly cited gate would be rejected as malformed."""
    match = GATE_CITATION_RE.match(f"{gate}: evidence here")
    assert match is not None
    assert match.group(1) == gate
    assert match.group(2).strip() == "evidence here"


@pytest.mark.parametrize(
    "text",
    [
        "The PR acceptance criteria require this behavior.",  # bare quote
        "g-secret: lowercase",
        "GINTENT: no hyphen",
        "see G-SECRET: cited mid-sentence",
        "",
    ],
)
def test_non_citations_do_not_match(text):
    match = GATE_CITATION_RE.match(text)
    assert match is None or match.group(1) not in GATE_IDS


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
