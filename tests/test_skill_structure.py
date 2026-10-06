"""Structural regression guard for skills, their references, and cross-file citations.

Keeps the context-footprint work honest: SKILL.md stays small and loadable, references
stay leaf files (a reference never routes to another reference — the owning SKILL.md
does), nothing mentions a removed skill, and every ``<skill> § <Section>`` citation still
resolves to a heading (or bold lead-in) in the cited skill.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
SKILL_FILES = sorted(SKILLS_DIR.glob("*/SKILL.md"))
REFERENCE_FILES = sorted(SKILLS_DIR.glob("*/references/*.md"))
AGENT_FILES = sorted((REPO_ROOT / "agents").glob("*.md"))

MAX_BODY_LINES = 500
MAX_DESCRIPTION_CHARS = 1024
CONTENTS_THRESHOLD_LINES = 100
CONTENTS_WINDOW_LINES = 30

REMOVED_SKILLS = (
    "track-minions",
    "workflow-simplified",
    "rust-best-practices",
    "python-best-practices",
    "go-best-practices",
    "frontend-best-practices",
)

# Files scanned for stale names (CHANGELOG.md is history and exempt).
STALE_SCAN_ROOTS = ("skills", "agents", "hooks", "scripts")
STALE_SCAN_FILES = ("README.md", "SETUP.md")
TEXT_SUFFIXES = {".md", ".sh", ".py", ".json", ".yml", ".yaml", ".txt"}

# Files scanned for ``<skill> § <Section>`` citations.
CITATION_SOURCES = (
    *SKILLS_DIR.glob("**/*.md"),
    *AGENT_FILES,
    *(REPO_ROOT / "hooks").glob("*.sh"),
    *(REPO_ROOT / "scripts").glob("*.py"),
)


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def _split_frontmatter(path: Path) -> tuple[str, str]:
    _, front, body = path.read_text(encoding="utf-8").split("---", 2)
    return front, body


def _id(path: Path) -> str:
    return path.parent.name if path.name == "SKILL.md" else _rel(path)


# --------------------------------------------------------------------------- SKILL.md shape


@pytest.mark.parametrize("path", SKILL_FILES, ids=_id)
def test_body_within_line_budget(path: Path) -> None:
    _, body = _split_frontmatter(path)
    lines = body.strip("\n").count("\n") + 1
    assert lines <= MAX_BODY_LINES, (
        f"{_rel(path)}: {lines} body lines > {MAX_BODY_LINES}"
    )


@pytest.mark.parametrize("path", SKILL_FILES, ids=_id)
def test_description_is_single_line_within_limit(path: Path) -> None:
    front, _ = _split_frontmatter(path)
    raw = re.search(r"^description:[ \t]*(.*)$", front, re.MULTILINE)
    assert raw, f"{_rel(path)}: no description"
    assert not raw.group(1).startswith((">", "|")), (
        f"{_rel(path)}: folded/literal scalar"
    )
    description = yaml.safe_load(front)["description"]
    assert isinstance(description, str) and "\n" not in description.strip(), (
        f"{_rel(path)}: description spans multiple lines"
    )
    assert len(description) <= MAX_DESCRIPTION_CHARS, (
        f"{_rel(path)}: description {len(description)} chars > {MAX_DESCRIPTION_CHARS}"
    )


REFERENCE_PATH = re.compile(
    r"(?:(?:skills|\.\.)/(?P<skill>[\w-]+)/)?references/(?P<name>[\w.-]+\.\w+)"
)


@pytest.mark.parametrize("path", SKILL_FILES, ids=_id)
def test_mentioned_reference_files_exist(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for m in REFERENCE_PATH.finditer(text):
        # "`other-skill`'s `references/x.md`" names the owner just before the path
        possessive = re.search(
            r"`([\w-]+)`'s\s+`$", text[max(0, m.start() - 60) : m.start()]
        )
        skill = m["skill"] or (possessive.group(1) if possessive else None)
        owner = SKILLS_DIR / (skill or path.parent.name)
        candidates = [owner / "references" / m["name"]]
        if not skill:
            candidates.append(REPO_ROOT / "references" / m["name"])
        assert any(c.is_file() for c in candidates), (
            f"{_rel(path)}: mentions {m.group(0)!r} but no such file"
        )


# --------------------------------------------------------------------------- reference files


@pytest.mark.parametrize("path", REFERENCE_FILES, ids=_id)
def test_long_references_have_contents_list(path: Path) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) <= CONTENTS_THRESHOLD_LINES:
        pytest.skip("short reference")
    head = "\n".join(lines[:CONTENTS_WINDOW_LINES])
    assert re.search(
        r"^(?:#{1,6}\s+|\*\*)(?:Table of )?Contents\b", head, re.I | re.M
    ), (
        f"{_rel(path)}: {len(lines)} lines but no contents list in the first "
        f"{CONTENTS_WINDOW_LINES} lines"
    )


MD_LINK = re.compile(r"\]\(\s*<?([^)\s>#]+\.md)(?:#[^)\s]*)?\s*>?\)")


@pytest.mark.parametrize("path", REFERENCE_FILES, ids=_id)
def test_reference_does_not_route_to_another_reference(path: Path) -> None:
    """Depth-one rule: the owning SKILL.md links references; references never chain."""
    text = path.read_text(encoding="utf-8")
    offenders = []
    for m in MD_LINK.finditer(text):
        target = (path.parent / m.group(1)).resolve()
        if target != path.resolve() and target.parent.name == "references":
            offenders.append(m.group(0))
    for m in REFERENCE_PATH.finditer(text):
        if m["name"] != path.name or m["skill"]:
            offenders.append(m.group(0))
    assert not offenders, (
        f"{_rel(path)}: references another reference file: {offenders}"
    )


@pytest.mark.parametrize("path", REFERENCE_FILES, ids=_id)
def test_reference_has_no_claude_variables(path: Path) -> None:
    """References are read via Read: ``${CLAUDE_…}`` is never substituted there."""
    text = path.read_text(encoding="utf-8")
    found = re.findall(r"\$\{CLAUDE_\w+\}", text)
    assert not found, f"{_rel(path)}: unsubstituted variables {sorted(set(found))}"


# --------------------------------------------------------------------------- agents and removed skills


def _agent_skills(path: Path) -> list[str]:
    front, _ = _split_frontmatter(path)
    value = (yaml.safe_load(front) or {}).get("skills") or []
    if isinstance(value, str):
        value = re.split(r"[,\s]+", value.strip())
    return [s.removeprefix("claudius:") for s in value if s]


@pytest.mark.parametrize("path", AGENT_FILES, ids=lambda p: p.name)
def test_agent_preloaded_skills_exist(path: Path) -> None:
    missing = [
        s for s in _agent_skills(path) if not (SKILLS_DIR / s / "SKILL.md").is_file()
    ]
    assert not missing, f"{_rel(path)}: skills: names a missing skill {missing}"


def _stale_scan_files() -> list[Path]:
    files = [REPO_ROOT / f for f in STALE_SCAN_FILES]
    for root in STALE_SCAN_ROOTS:
        files += [
            p
            for p in (REPO_ROOT / root).rglob("*")
            if p.is_file() and p.suffix in TEXT_SUFFIXES and "vendor" not in p.parts
        ]
    return sorted(f for f in files if f.is_file())


@pytest.mark.parametrize("name", REMOVED_SKILLS)
def test_removed_skill_is_not_mentioned(name: str) -> None:
    pattern = re.compile(rf"(?<![\w-]){re.escape(name)}(?![\w-])")
    offenders = [
        f"{_rel(p)}:{n}"
        for p in _stale_scan_files()
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line)
    ]
    assert not offenders, f"removed skill {name!r} still mentioned at {offenders}"


# --------------------------------------------------------------------------- § citations

# `skill` § Name  |  `claudius:skill` skill § Name  (name may follow §, §-less spacing ok)
CITE = re.compile(r"`(?:claudius:)?(?P<skill>[a-z][a-z0-9-]*)`(?:\s+skill(?:'s)?)?\s*§")
SECTION_MARK = re.compile(r"§\s*")
FENCE = re.compile(r"^(```|~~~).*?^\1[ \t]*$", re.M | re.S)
HEADING = re.compile(r"^#{1,6}[ \t]+(.+?)[ \t#]*$", re.M)
BOLD_LEAD = re.compile(r"^[ \t>|*+-]*(?:\d+[.)][ \t]+)?\*\*([^*\n]+?)\*\*", re.M)
CHAIN_SPLIT = re.compile(r"\s*(?:→|->)\s*")
NUMBER_PREFIX = re.compile(r"^(?:step |phase |part )?\d+[a-z]?(?![a-z0-9])\s*")
NUMBER_TOKEN = re.compile(r"^(?:step |phase |part )?(\d+[a-z]?)(?![a-z0-9])", re.I)


def _norm(text: str) -> str:
    text = re.sub(r"[`*_\"“”‘’]", "", text.lower())
    text = re.sub(r"[^\w\s/§-]", " ", text)
    return re.sub(r"\s+", " ", text).strip(" -—/")


def _section_titles(skill: str) -> set[str]:
    """Normalised headings and bold lead-ins of a skill's SKILL.md and references."""
    titles: set[str] = set()
    root = SKILLS_DIR / skill
    for path in [root / "SKILL.md", *sorted((root / "references").glob("*.md"))]:
        if not path.is_file():
            continue
        text = FENCE.sub("", path.read_text(encoding="utf-8"))
        for regex in (HEADING, BOLD_LEAD):
            for m in regex.finditer(text):
                raw = m.group(1)
                title = _norm(raw)
                titles.add(title)
                titles.add(
                    _norm(re.split(r" [—–-] |: ", raw)[0])
                )  # "Name — subtitle" ← "Name"
                titles.add(
                    NUMBER_PREFIX.sub("", title)
                )  # "5. Merge Classification" ← "Merge Classification"
    titles.discard("")
    return titles


_TITLES: dict[str, set[str]] = {}


def _titles(skill: str) -> set[str]:
    if skill not in _TITLES:
        _TITLES[skill] = _section_titles(skill)
    return _TITLES[skill]


def _capture(text: str) -> str:
    """The section-name words right after a ``§`` — up to the first prose delimiter."""
    text = text.lstrip()
    if text.startswith("`"):
        end = text.find("`", 1)
        if end > 0:
            return text[: end + 1]
    return re.split(r"[,;:.()<>§|\n]| — | - | \[|\]", text, maxsplit=1)[0]


def _segment_resolves(segment: str, titles: set[str]) -> bool:
    words = _norm(segment)
    if not words:
        return True  # nothing citable captured (e.g. a bare "§")
    number = NUMBER_TOKEN.match(words)
    if number:
        token = number.group(1)
        return any(
            (m := NUMBER_TOKEN.match(t)) is not None and m.group(1) == token
            for t in titles
        )
    # A heading equals some word-prefix of the capture (prose may trail the name), or the
    # capture is itself a prefix of a longer heading.
    parts = words.split()
    prefixes = {" ".join(parts[:i]) for i in range(1, len(parts) + 1)}
    return any(t in prefixes or t.startswith(words) for t in titles)


def _citations(text: str) -> list[tuple[str, str]]:
    """(skill, name-segment) pairs; a skill mention governs every § until the sentence ends."""
    found: list[tuple[str, str]] = []
    for cite in CITE.finditer(text):
        tail = text[cite.end() :]
        stop = re.search(
            r"\n|\.\s|`(?:claudius:)?[a-z][a-z0-9-]*`(?:\s+skill)?\s*§", tail
        )
        tail = tail[: stop.start()] if stop else tail
        # first § is the one the regex consumed; later ones in the same sentence share the skill
        names = [text[cite.end() : cite.end() + len(tail)]]
        names += [tail[m.end() :] for m in SECTION_MARK.finditer(tail)]
        for name in names:
            for segment in CHAIN_SPLIT.split(_capture(name)):
                found.append((cite["skill"], segment))
    return found


def _citation_cases() -> list[tuple[str, str, str]]:
    cases = []
    for path in sorted(set(CITATION_SOURCES)):
        text = path.read_text(encoding="utf-8")
        for skill, segment in _citations(text):
            cases.append((_rel(path), skill, segment))
    return sorted(set(cases))


@pytest.mark.parametrize(
    ("source", "skill", "segment"),
    _citation_cases(),
    ids=lambda v: v if len(str(v)) < 40 else str(v)[:40],
)
def test_section_citation_resolves(source: str, skill: str, segment: str) -> None:
    assert (SKILLS_DIR / skill / "SKILL.md").is_file(), (
        f"{source}: cites unknown skill {skill!r}"
    )
    assert _segment_resolves(segment, _titles(skill)), (
        f"{source}: `{skill}` § {segment.strip()!r} matches no heading or bold lead-in"
    )


# --------------------------------------------------------------------------- matcher self-tests


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "see `severity` skill § Merge Classification. Next",
            [("severity", "Merge Classification")],
        ),
        (
            "`grand-admiral` § Recovery → Stall Watchdog, then",
            [("grand-admiral", "Recovery"), ("grand-admiral", "Stall Watchdog")],
        ),
        (
            "`claudius:severity` § `out_of_scope_follow_up`)",
            [("severity", "`out_of_scope_follow_up`")],
        ),
        ("`severity` § 2 and § 3.", [("severity", "2 and "), ("severity", "3")]),
        (
            "`grumpy-review` §5a/§5c)",
            [("grumpy-review", "5a/"), ("grumpy-review", "5c")],
        ),
    ],
)
def test_citation_extraction(text: str, expected: list[tuple[str, str]]) -> None:
    assert [(s, seg) for s, seg in _citations(text)] == expected


def test_matcher_rejects_renamed_section_but_tolerates_trailing_prose() -> None:
    titles = {
        _norm("Merge Classification"),
        _norm("2. Blocker gates"),
        _norm("5d. Stop reviewers"),
    }
    assert _segment_resolves("Merge Classification before routing", titles)
    assert _segment_resolves("merge classification", titles)
    assert _segment_resolves("2", titles)
    assert _segment_resolves("5d", titles)
    assert not _segment_resolves("Merge Class Routing", titles)
    assert not _segment_resolves("7", titles)
