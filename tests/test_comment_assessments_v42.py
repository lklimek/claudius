"""Schema 4.2: optional comment-assessment fields, host-supplied mode, version tie."""

import copy
import json
import re
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import generate_review_report as grr  # noqa: E402
import validate_report as vr  # noqa: E402

FIXTURES = ROOT / "tests/fixtures/reports"
HOST = FIXTURES / "v4-comment-assessments-host.json"
V41 = FIXTURES / "v4-comment-assessments.json"
SCHEMA = json.loads((ROOT / "schemas/review-report.schema.json").read_text())
VALIDATOR = jsonschema.Draft202012Validator(
    SCHEMA, format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER
)
SKILL = ROOT / "skills/check-pr-comments/SKILL.md"

V42_FIELDS = {
    "source_quote": "Please avoid sending the balance request twice.",
    "gates": [{"gate": "G-DATA", "evidence": "rows dropped on retry"}],
    "proposed_decision": {"kind": "fix_here"},
    "recorded_decision": {
        "kind": "withdrawn",
        "by": "alice",
        "comment_url": "https://github.com/example/repo/pull/42#issuecomment-9",
        "quote": "Never mind, this is fine.",
    },
    "merged_thread_ids": ["PRRT_other"],
    "merged_urls": ["https://github.com/example/repo/pull/42#discussion_r9"],
    "pre_existing": True,
    "fix_size": "M",
    "category": "data-loss",
}


@pytest.fixture
def host():
    return json.loads(HOST.read_text())


@pytest.fixture
def v41():
    return json.loads(V41.read_text())


def errors(report):
    return list(VALIDATOR.iter_errors(report))


def run_validator(report, tmp_path):
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report))
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts/validate_report.py"), str(path)],
        capture_output=True,
        text=True,
    )


def row(report, rid):
    return next(r for r in report["comment_assessments"] if r["id"] == rid)


# --------------------------------------------------------------- valid reports


def test_host_fixture_is_valid(host, tmp_path):
    assert errors(host) == []
    result = run_validator(host, tmp_path)
    assert result.returncode == 0, result.stderr
    assert "[consistency]" not in result.stderr


def test_41_report_stays_valid(v41, tmp_path):
    assert errors(v41) == []
    assert run_validator(v41, tmp_path).returncode == 0


def test_41_rows_declared_42_are_valid_without_new_fields(v41):
    v41["schema_version"] = "4.2.0"
    assert errors(v41) == []


def test_fetched_mode_needs_no_host_fields(v41):
    v41["schema_version"] = "4.2.0"
    v41["metadata"]["input_mode"] = "fetched"
    assert errors(v41) == []


@pytest.mark.parametrize("field", sorted(V42_FIELDS))
def test_each_42_field_is_optional_and_valid_on_42(v41, field):
    v41["schema_version"] = "4.2.0"
    v41["comment_assessments"][1][field] = copy.deepcopy(V42_FIELDS[field])
    assert errors(v41) == []


# ------------------------------------------------------------- version tie


@pytest.mark.parametrize("field", sorted(V42_FIELDS))
def test_41_report_using_a_42_field_is_rejected(v41, field, tmp_path):
    v41["comment_assessments"][1][field] = copy.deepcopy(V42_FIELDS[field])
    assert any(list(e.absolute_path) == ["schema_version"] for e in errors(v41))
    assert run_validator(v41, tmp_path).returncode == 1


@pytest.mark.parametrize("mode", ["fetched", "host_supplied"])
def test_input_mode_requires_42(host, mode, tmp_path):
    host["schema_version"] = "4.1.0"
    host["metadata"]["input_mode"] = mode
    for r in host["comment_assessments"]:
        for field in V42_FIELDS:
            r.pop(field, None)
    assert any(list(e.absolute_path) == ["schema_version"] for e in errors(host))
    assert run_validator(host, tmp_path).returncode == 1


@pytest.mark.parametrize(
    ("report_type", "valid"),
    [("comment_check", True), ("code_review", False), (None, False)],
)
def test_input_mode_requires_comment_check(host, report_type, valid):
    del host["comment_assessments"]
    host["metadata"]["input_mode"] = "fetched"
    host["metadata"].pop("report_type")
    if report_type:
        host["metadata"]["report_type"] = report_type
    assert (errors(host) == []) is valid


def test_unknown_input_mode_is_rejected(host):
    host["metadata"]["input_mode"] = "cached"
    assert errors(host)


# comment_assessment properties of schema 4.1.0; anything added later needs a version tie.
V41_ROW_PROPERTIES = {
    "id",
    "finding_id",
    "reviewer",
    "author_type",
    "source_kind",
    "comment_id",
    "comment_url",
    "thread_id",
    "thread_state",
    "location",
    "location_permalink",
    "description",
    "assessment",
    "reasoning",
    "evidence",
    "proposed_action",
    "proposed_reply",
    "action_taken",
}


def _row_fields_tied_to_42():
    for rule in SCHEMA["allOf"]:
        then_version = rule["then"].get("properties", {}).get("schema_version")
        rows = rule["if"].get("properties", {}).get("comment_assessments", {})
        if then_version == {"const": "4.2.0"} and "contains" in rows:
            return {branch["required"][0] for branch in rows["contains"]["anyOf"]}
    return set()


def test_every_row_property_added_after_41_is_version_tied():
    properties = set(SCHEMA["$defs"]["comment_assessment"]["properties"])
    added = properties - V41_ROW_PROPERTIES
    assert added == _row_fields_tied_to_42()
    assert added == set(V42_FIELDS)


# ---------------------------------------------------------- host-mode rules


@pytest.mark.parametrize("rid", ["CMT-002", "CMT-1000"])
def test_host_body_and_comment_rows_require_source_quote(host, rid, tmp_path):
    row(host, rid).pop("source_quote")
    assert errors(host)
    result = run_validator(host, tmp_path)
    assert result.returncode == 1
    assert "source_quote" in result.stderr


def test_host_inline_rows_need_no_source_quote(host):
    assert "source_quote" not in row(host, "CMT-001")
    assert errors(host) == []


def test_fetched_body_rows_need_no_source_quote(host):
    host["metadata"]["input_mode"] = "fetched"
    row(host, "CMT-002").pop("source_quote")
    assert errors(host) == []


@pytest.mark.parametrize("rid", ["CMT-001", "CMT-002", "CMT-1000", "CMT-004"])
def test_host_assessed_rows_require_proposed_decision(host, rid):
    row(host, rid).pop("proposed_decision")
    assert errors(host)


def test_host_context_rows_need_no_proposed_decision(host):
    assert "proposed_decision" not in row(host, "CMT-005")
    assert "proposed_decision" not in row(host, "CMT-006")
    assert errors(host) == []


def test_host_inline_rows_require_thread_id(host):
    row(host, "CMT-004").pop("thread_id")
    assert errors(host)


@pytest.mark.parametrize("field", ["pr_number", "commit"])
def test_host_metadata_requires_pr_and_commit(host, field):
    host["metadata"].pop(field)
    assert errors(host)


@pytest.mark.parametrize("missing", [True, False])
def test_host_requires_nonempty_assessments(host, missing, tmp_path):
    if missing:
        host.pop("comment_assessments")
    else:
        host["comment_assessments"] = []
    assert errors(host)
    assert run_validator(host, tmp_path).returncode == 1


# ----------------------------------------------------- proposed_decision


@pytest.mark.parametrize(
    ("decision", "valid"),
    [
        ({"kind": "handled_in_pr"}, False),
        ({"kind": "handled_in_pr", "target_pr": 7}, True),
        (
            {"kind": "handled_in_pr", "target_url": "https://github.com/o/r/pull/7"},
            True,
        ),
        ({"kind": "follow_up_pr"}, False),
        ({"kind": "follow_up_pr", "target_pr": 8}, True),
        ({"kind": "follow_up_pr", "title": "Cache fee estimates"}, True),
        ({"kind": "upstream_issue"}, False),
        ({"kind": "upstream_issue", "title": "Precise fee rules"}, False),
        (
            {
                "kind": "upstream_issue",
                "target_url": "https://github.com/o/sdk",
                "title": "Precise fee rules",
            },
            True,
        ),
        ({"kind": "resolve"}, True),
        (
            {"kind": "resolve", "fixed_in": "0123456789abcdef0123456789abcdef01234567"},
            True,
        ),
        ({"kind": "fix_here"}, True),
        ({"kind": "reject"}, True),
        ({"kind": "todo", "title": "Revisit fee caching"}, True),
        ({"kind": "todo"}, True),
        ({"kind": "deferred"}, False),
        ({"kind": "resolve", "fixed_in": "abc12"}, False),
        ({"kind": "resolve", "fixed_in": "ABCDEF1"}, False),
        ({"kind": "handled_in_pr", "target_pr": 0}, False),
        (
            {"kind": "handled_in_pr", "target_url": "http://github.com/o/r/pull/7"},
            False,
        ),
        ({"kind": "follow_up_pr", "title": "x" * 121}, False),
        ({"kind": "follow_up_pr", "title": ""}, False),
        ({"kind": "fix_here", "note": "closed object"}, False),
        ({}, False),
    ],
)
def test_proposed_decision_shapes(host, decision, valid, tmp_path):
    row(host, "CMT-004")["proposed_decision"] = decision
    assert (errors(host) == []) is valid
    assert (run_validator(host, tmp_path).returncode == 0) is valid


# ----------------------------------------------------------- other fields


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_quote", ""),
        ("source_quote", "q" * 601),
        ("gates", [{"gate": "G-UNKNOWN", "evidence": "x"}]),
        ("gates", [{"gate": "G-DATA"}]),
        ("gates", [{"gate": "G-DATA", "evidence": ""}]),
        ("gates", [{"gate": "G-DATA", "evidence": "x", "extra": 1}]),
        ("gates", "G-DATA"),
        ("merged_thread_ids", [""]),
        ("merged_thread_ids", ["PRRT_a", "PRRT_a"]),
        ("merged_urls", ["http://github.com/o/r/pull/1#discussion_r1"]),
        ("merged_urls", ["javascript:alert(1)"]),
        ("pre_existing", "no"),
        ("fix_size", "L"),
        ("category", "other"),
        ("category", "other:"),
        ("category", "other: one"),
        ("category", "other: far too many words"),
        ("category", "styling"),
        ("unknown_field", "closed object"),
    ],
)
def test_malformed_42_fields_are_rejected(host, field, value):
    row(host, "CMT-001")[field] = value
    assert errors(host)


@pytest.mark.parametrize(
    ("change", "valid"),
    [
        ({}, True),
        ({"kind": "deferred"}, True),
        ({"kind": "withdrawn"}, True),
        ({"kind": "upstream_issue"}, True),
        ({"kind": "approved"}, False),
        ({"by": ""}, False),
        ({"quote": "q" * 601}, False),
        ({"quote": ""}, False),
        ({"comment_url": "http://github.com/o/r/pull/1#issuecomment-1"}, False),
        ({"target_pr": 80}, True),
        ({"target_url": "https://github.com/o/r/pull/80"}, True),
        ({"target_pr": 0}, False),
        ({"target_pr": "80"}, False),
        ({"target_url": "http://github.com/o/r/pull/80"}, False),
        ({"target_url": "https://"}, False),
        ({"extra": True}, False),
    ],
)
def test_recorded_decision_shapes(host, change, valid):
    decision = row(host, "CMT-1000")["recorded_decision"]
    decision.update(change)
    assert (errors(host) == []) is valid


@pytest.mark.parametrize("field", ["kind", "by", "comment_url", "quote"])
def test_recorded_decision_requires_every_field(host, field):
    row(host, "CMT-1000")["recorded_decision"].pop(field)
    assert errors(host)


@pytest.mark.parametrize("version", ["4.1.0", "4.2.0"])
def test_recorded_targets_are_version_tied(v41, version):
    v41["schema_version"] = version
    v41["comment_assessments"][1]["recorded_decision"] = {
        **V42_FIELDS["recorded_decision"],
        "target_pr": 80,
        "target_url": "https://github.com/o/r/pull/80",
    }
    assert (errors(v41) == []) is (version == "4.2.0")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", "CMT-004\n"),
        ("id", "CMT-١٢٣"),
        ("finding_id", "CMT-004\n"),
        ("finding_id", "CMT-١٢٣"),
        ("proposed_decision", {"kind": "resolve", "fixed_in": "abc1234\n"}),
        ("proposed_decision", {"kind": "resolve", "fixed_in": "abc١٢٣٤"}),
        ("category", "other: fee caching\n"),
    ],
)
def test_patterns_reject_newlines_and_non_ascii_digits(host, field, value):
    row(host, "CMT-004")[field] = value
    assert errors(host)


@pytest.mark.parametrize("rid", ["CMT-004\n", "CMT-١٢٣"])
def test_finding_ids_reject_newlines_and_non_ascii_digits(host, rid):
    host["findings"][0]["findings"][0]["id"] = rid
    assert errors(host)


@pytest.mark.parametrize(
    "url",
    ["https://", "https://a b <x>", "https://\nevil", "https://example.org/\n"],
)
@pytest.mark.parametrize(
    "field",
    ["proposed_decision", "recorded_decision", "recorded_target", "merged_urls"],
)
def test_https_fields_require_a_host_and_no_whitespace(host, field, url):
    item = row(host, "CMT-1000")
    if field == "merged_urls":
        item[field] = [url]
    elif field == "proposed_decision":
        item[field] = {"kind": "handled_in_pr", "target_url": url}
    elif field == "recorded_target":
        item["recorded_decision"]["target_url"] = url
    else:
        item[field]["comment_url"] = url
    assert errors(host)


def test_category_accepts_two_and_three_word_other_labels(host):
    for label in ("other: fee caching", "other: fee estimate caching"):
        row(host, "CMT-1000")["category"] = label
        assert errors(host) == []


def _documented_categories():
    text = SKILL.read_text(encoding="utf-8")
    table = text.split("| Slug | Covers | Gates |", 1)[1].split("\n- ", 1)[0]
    return re.findall(r"^\s*\| `([a-z-]+)` \|", table, re.MULTILINE)


def test_category_slugs_match_the_skill_catalogue():
    documented = _documented_categories()
    assert len(documented) >= 10
    category = SCHEMA["$defs"]["comment_assessment"]["properties"]["category"]
    enum = next(branch["enum"] for branch in category["anyOf"] if "enum" in branch)
    assert enum == [slug for slug in documented if slug != "other"]


# ------------------------------------------------------------------------ IDs


@pytest.mark.parametrize("rid", ["CMT-12", "CMT-01a", "SEC-001"])
def test_comment_ids_need_three_or_more_digits(host, rid):
    row(host, "CMT-004")["id"] = rid
    assert errors(host)


def test_four_digit_ids_validate_in_rows_and_findings(host):
    assert row(host, "CMT-1000")["finding_id"] == "CMT-1000"
    assert host["findings"][0]["findings"][1]["id"] == "CMT-1000"
    assert errors(host) == []


# ---------------------------------------------------------- pipeline scripts


def test_merge_class_fields_are_supported_on_42(host):
    assert "4.2.0" in vr._MERGE_CLASS_SCHEMA_VERSIONS
    assert not any("require schema_version" in w for w in vr.check_consistency(host))


def test_regenerate_keeps_42_and_rows(host, tmp_path):
    path = tmp_path / "report.json"
    path.write_text(json.dumps(host))
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/consolidate_reports.py"),
            "regenerate",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    updated = json.loads(path.read_text())
    assert updated["schema_version"] == "4.2.0"
    assert updated["metadata"]["input_mode"] == "host_supplied"
    assert updated["comment_assessments"] == host["comment_assessments"]


@pytest.mark.parametrize("renderer", [grr.render_html, grr.render_triage])
def test_renderers_accept_42_rows(host, renderer):
    soup = BeautifulSoup(renderer(host), "html.parser")
    rows = soup.select("#comment-assessments .assessment-table > tbody > tr")
    assert len(rows) == len(host["comment_assessments"])


def test_generator_cli_validates_42(host, tmp_path):
    path = tmp_path / "report.json"
    path.write_text(json.dumps(host))
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/generate_review_report.py"),
            str(path),
            "--format",
            "md",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


# Producer instructions are the contract for behavior implemented by the model.
@pytest.mark.parametrize(
    "rule",
    [
        "copied verbatim from the supplied (cleaned) text",
        "at least 12 characters (the whole text when shorter), distinct within its source",
        "`comment_url` equals the source URL in `scope.json`",
        "contains, or is contained in, its `ids.json` quote",
        "a merged row takes the ID of its own `thread_id`/source",
        "propose the standing `decision` unless the code at its lines changed",
        "`proposed_reply` is the single reply for `proposed_decision` only",
        'without the attribution footer or "post only after the fix lands" marker',
    ],
)
def test_host_producer_contract(rule):
    text = (SKILL.parent / "references/host-supplied.md").read_text()
    assert rule in text


def test_host_entry_point_skips_fetch_and_overrides_worker_reply_contract():
    text = SKILL.read_text()
    assert "## 1. Fetch All Comments (host-supplied mode: skip)" in text
    brief = (SKILL.parent / "references/verify-worker.md").read_text()
    assert "../SKILL.md" in brief
    assert "single-reply override" in brief


@pytest.mark.parametrize(
    "renderer", [grr.render_html, grr.render_triage, grr.render_markdown]
)
def test_fetched_descriptions_preserve_duplicate_and_decision_links(host, renderer):
    contract = (
        ROOT / "skills/report-format/references/comment-assessments.md"
    ).read_text()
    assert "Outside host mode" in contract
    assert "`description`" in contract
    assert "`recorded_decision.comment_url`" in contract
    host["metadata"]["input_mode"] = "fetched"
    item = row(host, "CMT-1000")
    item["merged_urls"] = row(host, "CMT-001")["merged_urls"]
    decision = item["recorded_decision"]
    links = [*item.get("merged_urls", []), decision["comment_url"]]
    assert len(links) >= 2
    item["description"] += " " + " ".join(f"[Source]({url})" for url in links)
    item["description"] += f" {decision['by']}: {decision['quote']}"
    rendered = renderer(host)
    for url in links:
        assert url in rendered
    assert decision["by"] in rendered


def test_pdf_keeps_description_links_and_recorded_author(host, tmp_path, monkeypatch):
    from reportlab.platypus import SimpleDocTemplate

    captured = []
    build = SimpleDocTemplate.build

    def capture(doc, story, *args, **kwargs):
        captured.extend(getattr(part, "text", "") for part in story)
        return build(doc, story, *args, **kwargs)

    monkeypatch.setattr(SimpleDocTemplate, "build", capture)
    host["metadata"]["input_mode"] = "fetched"
    item = row(host, "CMT-1000")
    decision = item["recorded_decision"]
    links = [*row(host, "CMT-001")["merged_urls"], decision["comment_url"]]
    item["description"] += " " + " ".join(f"[Source]({url})" for url in links)
    item["description"] += f" {decision['by']}: {decision['quote']}"
    output = tmp_path / "comments.pdf"
    grr.render_pdf(host, output)
    assert output.read_bytes().startswith(b"%PDF-")
    for url in links:
        assert url in " ".join(captured)
    assert decision["by"] in " ".join(captured)
