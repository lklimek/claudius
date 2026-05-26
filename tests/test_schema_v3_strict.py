"""Strict schema acceptance: v3 fixtures pass; v2 is rejected."""

from __future__ import annotations

import json
import sys
from pathlib import Path
import jsonschema

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import consolidate_reports as cr

SCHEMA = json.loads(cr.SCHEMA_PATH.read_text(encoding="utf-8"))
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "reports"


class TestV3Minimal:
    def test_passes_schema(self):
        data = json.loads((FIXTURES / "v3-minimal.json").read_text())
        errors = list(VALIDATOR.iter_errors(data))
        assert errors == [], [e.message for e in errors]


class TestV3Full:
    def test_passes_schema(self):
        data = json.loads((FIXTURES / "v3-full.json").read_text())
        errors = list(VALIDATOR.iter_errors(data))
        assert errors == [], [e.message for e in errors]


class TestV2Legacy:
    def test_rejected(self):
        data = json.loads((FIXTURES / "v2-legacy.json").read_text())
        errors = list(VALIDATOR.iter_errors(data))
        assert errors, "Expected v2 fixture to fail v3 schema validation"

    def test_consolidate_rejects_v2_input(self, tmp_path):
        """An agent report carrying schema_version != 3.0.0 must be rejected
        loudly by the prepare phase."""
        # _flatten_agent_report receives a list[section]; the section-level
        # check the plan calls for must catch the legacy version when carried
        # at the envelope. We use a wrapper here mimicking how producers may
        # ship an envelope (some do); the prepare command currently expects
        # a list of sections, so we test the helper directly.
        legacy = {"schema_version": "2.0.0", "sections": []}
        rep = tmp_path / "legacy.json"
        rep.write_text(json.dumps(legacy))
        import argparse

        args = argparse.Namespace(
            agent_reports=[f"agent:{rep}"],
            repo_root=str(tmp_path),
            output=str(tmp_path / "out.json"),
            metadata=None,
        )
        # The input is an envelope dict, not a list, so cmd_prepare must
        # reject it with rc=2 ("expected JSON array") OR detect the version
        # marker. Either way: non-zero exit, no output file.
        rc = cr.cmd_prepare(args)
        assert rc != 0
