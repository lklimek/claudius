"""Tests for triage_server.py report loading and the non-finite JSON guard.

``reject_non_finite_constant`` is wired into every report-loading
``json.loads``/``json.load`` call across the pipeline (consolidate_reports,
validate_report, generate_review_report, and here in triage_server's
``_load_report``) so bare NaN/Infinity/-Infinity constants are rejected at
parse time instead of silently corrupting severity math.
"""

from __future__ import annotations

import http.client
import json
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import triage_server as ts


def _report(relevance: Any) -> dict:
    return {
        "metadata": {"project": "x", "date": "2026-01-01"},
        "findings": [
            {
                "category": "security",
                "title": "Sec",
                "findings": [
                    {
                        "id": "SEC-001",
                        "severity": 4,
                        "title": "T",
                        "location": "src/db.rs:1",
                        "description": "D",
                        "recommendation": "R",
                        "likelihood": 0.9,
                        "impact": 0.9,
                        "relevance": relevance,
                    }
                ],
            }
        ],
    }


class TestLoadReportRejectsNonFinite:
    @pytest.mark.parametrize(
        "bad", [float("nan"), float("inf"), float("-inf")], ids=["nan", "inf", "-inf"]
    )
    def test_load_report_rejects_non_finite_float(self, tmp_path, monkeypatch, bad):
        report_path = tmp_path / "report.json"
        report_path.write_text(
            json.dumps(_report(bad))
        )  # json.dumps emits bare NaN/Infinity
        monkeypatch.setattr(ts, "REPORT_PATH", report_path)
        with pytest.raises(ValueError, match="non-finite"):
            ts._load_report()

    def test_load_report_accepts_finite_report(self, tmp_path, monkeypatch):
        report_path = tmp_path / "report.json"
        report_path.write_text(json.dumps(_report(0.5)))
        monkeypatch.setattr(ts, "REPORT_PATH", report_path)
        report = ts._load_report()
        assert report["findings"][0]["findings"][0]["relevance"] == 0.5


class TestDoPostHandlesNonFiniteReport:
    """_save_triage (called from do_POST) must surface the guard as a clean
    ValueError, not let it fall through do_POST's narrower except clause."""

    def test_save_triage_raises_on_corrupt_report(self, tmp_path, monkeypatch):
        report_path = tmp_path / "report.json"
        report_path.write_text(json.dumps(_report(float("nan"))))
        monkeypatch.setattr(ts, "REPORT_PATH", report_path)
        with pytest.raises(ValueError, match="non-finite"):
            ts._save_triage([], "user")


class TestPostDecisionsRejectsNonFiniteBody:
    """A POST /api/decisions body is client input (the triage UI, or any
    hand-crafted request) and was parsed with plain json.loads — a bare
    NaN/Infinity in the *decisions* payload sailed straight through, got
    merged into report["triage"]["decisions"], and was written back to disk
    with default allow_nan=True. The next _load_report() (guarded against
    non-finite JSON constants on read) would then permanently reject that
    self-inflicted corruption. Both ends must now be guarded: the POST body
    parse (primary fix — reject at ingestion, before anything is written)
    and the save-side json.dumps (defense in depth — allow_nan=False so no
    path can write a non-finite value even if one is ever constructed in
    Python directly).
    """

    @staticmethod
    def _start_server(tmp_path, monkeypatch):
        report_path = tmp_path / "report.json"
        report_path.write_text(json.dumps(_report(0.5)))
        monkeypatch.setattr(ts, "REPORT_PATH", report_path)
        server = ThreadingHTTPServer(("127.0.0.1", 0), ts.TriageHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread, report_path

    def test_post_with_nan_in_decisions_is_rejected_not_written(
        self, tmp_path, monkeypatch
    ):
        server, thread, report_path = self._start_server(tmp_path, monkeypatch)
        original_bytes = report_path.read_bytes()
        try:
            # json.dumps can't emit NaN with allow_nan=False, so hand-build the
            # malicious body — this is exactly the untrusted-input shape a
            # real attacker or buggy client would send.
            body = (
                b'{"decisions": [{"finding_id": "SEC-001", "confidence": NaN}], '
                b'"triaged_by": "attacker"}'
            )
            conn = http.client.HTTPConnection(*server.server_address, timeout=5)
            conn.request(
                "POST",
                "/api/decisions",
                body=body,
                headers={"Content-Length": str(len(body))},
            )
            resp = conn.getresponse()
            payload = json.loads(resp.read())
            conn.close()
        finally:
            server.shutdown()
            thread.join(timeout=5)

        assert resp.status == 400
        assert payload["ok"] is False
        assert "non-finite" in payload["error"]
        # The whole point: no corrupted write ever reached disk.
        assert report_path.read_bytes() == original_bytes

    def test_save_triage_write_side_rejects_non_finite_value(
        self, tmp_path, monkeypatch
    ):
        """Defense-in-depth: even if a non-finite float reached _save_triage
        by some other path, json.dumps(allow_nan=False) must refuse to
        write it rather than silently persisting a bare NaN token."""
        report_path = tmp_path / "report.json"
        report_path.write_text(json.dumps(_report(0.5)))
        monkeypatch.setattr(ts, "REPORT_PATH", report_path)
        with pytest.raises(ValueError, match="Out of range float"):
            ts._save_triage([{"finding_id": "SEC-001", "confidence": float("nan")}])
