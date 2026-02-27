#!/usr/bin/env python3
"""triage_server.py — Lightweight HTTP server for interactive finding triage.

Serves the triage HTML UI, receives decisions via POST, and writes them back
to the report JSON file. Auto-opens a browser on startup.

Usage:
    python3 triage_server.py <report.json> [--port PORT] [--verbose]
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

# Resolved paths set by main()
REPORT_PATH: Path = Path()
RENDERER_SCRIPT: Path = Path()
_cached_triage_html: str = ""
_cache_generation: int = 0  # Bumped on invalidation; prevents stale repopulation
_lock = threading.Lock()  # Guards report I/O and HTML cache


def _generate_triage_html() -> str:
    """Generate triage HTML by invoking the renderer script."""
    global _cached_triage_html
    with _lock:
        if _cached_triage_html:
            log.debug("Serving cached triage HTML (%d bytes)", len(_cached_triage_html))
            return _cached_triage_html
        gen = _cache_generation

    # Subprocess runs outside the lock — it only reads the report file.
    t0 = time.monotonic()
    log.debug(
        "Spawning renderer: %s %s --format triage -o -",
        sys.executable,
        RENDERER_SCRIPT,
    )
    result = subprocess.run(
        [
            sys.executable,
            str(RENDERER_SCRIPT),
            str(REPORT_PATH),
            "--format",
            "triage",
            "-o",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    elapsed_ms = (time.monotonic() - t0) * 1000
    if result.returncode != 0:
        log.error("Renderer failed (%.0fms): %s", elapsed_ms, result.stderr)
        import html

        return f"<html><body><h1>Renderer Error</h1><pre>{html.escape(result.stderr)}</pre></body></html>"

    log.debug(
        "Renderer completed in %.0fms, output %d bytes", elapsed_ms, len(result.stdout)
    )

    with _lock:
        # Only populate if no invalidation happened while we were generating.
        if _cache_generation == gen and not _cached_triage_html:
            _cached_triage_html = result.stdout
            log.debug("Triage HTML cached (gen=%d)", gen)
        return _cached_triage_html or result.stdout


def _load_report() -> dict:
    """Load the report JSON."""
    t0 = time.monotonic()
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    log.debug("Loaded report in %.1fms", (time.monotonic() - t0) * 1000)
    return report


def _save_triage(decisions: list[dict], triaged_by: str = "user") -> dict:
    """Merge triage decisions into the report JSON and save."""
    global _cached_triage_html, _cache_generation
    with _lock:
        _cached_triage_html = ""  # Invalidate cache so next GET reflects new decisions
        _cache_generation += 1
        log.debug("Cache invalidated (gen=%d)", _cache_generation)
        report = _load_report()
        report["triage"] = {
            "triaged_by": triaged_by,
            "triaged_at": datetime.now(timezone.utc).isoformat(),
            "decisions": decisions,
        }
        REPORT_PATH.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        log.info(
            "Triage saved: %d decisions written to %s", len(decisions), REPORT_PATH
        )
        return report


def _triage_status(report: dict) -> dict:
    """Compute triage completion status."""
    total = sum(len(s.get("findings", [])) for s in report.get("findings", []))
    triage = report.get("triage", {})
    triaged = len(triage.get("decisions", []))
    status = {"total_findings": total, "triaged": triaged, "remaining": total - triaged}
    vc = report.get("summary_statistics", {}).get("verdict_counts")
    if vc:
        status["verdict_counts"] = vc
    return status


class TriageHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the triage server."""

    # Chrome's HTTPS-First mode sends a TLS ClientHello (first byte 0x16)
    # before trying plain HTTP. The default BaseHTTPRequestHandler waits
    # indefinitely for a valid HTTP request line, causing a ~28s delay.
    # Override parse_request indirectly by setting a short timeout so TLS
    # probes are dropped quickly and Chrome falls back to HTTP.
    timeout = 3

    def log_message(self, fmt: str, *args: object) -> None:
        log.info("HTTP %s", fmt % args)

    def _send_json(
        self, data: object, status: int = 200, *, close: bool = False
    ) -> None:
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if close:
            self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        if close:
            self.close_connection = True

    def _send_html(self, html: str, status: int = 200) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        t0 = time.monotonic()
        if self.path == "/" or self.path == "/index.html":
            html = _generate_triage_html()
            # Inject server mode flag so the triage page enables "Submit to Server"
            html = html.replace(
                "</head>",
                "<script>window.TRIAGE_SERVER = true;</script></head>",
            )
            self._send_html(html)
            log.debug(
                "GET / served in %.0fms (%d bytes)",
                (time.monotonic() - t0) * 1000,
                len(html),
            )
        elif self.path == "/api/report":
            with _lock:
                report = _load_report()
            self._send_json(report)
            log.debug("GET /api/report served in %.0fms", (time.monotonic() - t0) * 1000)
        elif self.path == "/api/status":
            with _lock:
                report = _load_report()
            self._send_json(_triage_status(report))
            log.debug(
                "GET /api/status served in %.0fms", (time.monotonic() - t0) * 1000
            )
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    MAX_BODY = 10 * 1024 * 1024  # 10 MB

    def do_POST(self) -> None:
        t0 = time.monotonic()
        if self.path == "/api/decisions":
            try:
                content_len = int(self.headers.get("Content-Length", 0))
            except (ValueError, TypeError):
                self.send_error(HTTPStatus.BAD_REQUEST, "Invalid Content-Length")
                return
            if content_len > self.MAX_BODY:
                self.send_error(
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    f"Body exceeds {self.MAX_BODY} bytes",
                )
                return
            if content_len == 0:
                self.send_error(HTTPStatus.BAD_REQUEST, "Empty request body")
                return
            log.debug("POST /api/decisions: reading %d bytes", content_len)
            body = self.rfile.read(content_len)
            try:
                payload = json.loads(body)
                decisions = payload.get("decisions", [])
                triaged_by = payload.get("triaged_by", "user")
                report = _save_triage(decisions, triaged_by)
                status = _triage_status(report)
                shutting_down = payload.get("complete", False)
                self._send_json({"ok": True, "status": status}, close=shutting_down)
                log.debug(
                    "POST /api/decisions completed in %.0fms (%d decisions, complete=%s)",
                    (time.monotonic() - t0) * 1000,
                    len(decisions),
                    shutting_down,
                )

                # If all findings are triaged, schedule shutdown
                if shutting_down:
                    log.info("Triage complete — shutting down server.")
                    # Prevent capturing `self` (and its socket) in the thread.
                    srv = self.server
                    threading.Thread(target=srv.shutdown, daemon=True).start()
            except (json.JSONDecodeError, KeyError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    # No CORS headers — same-origin requests from triage UI don't need them.


def _open_browser(url: str) -> None:
    """Try to open a browser, log the URL on failure."""
    try:
        webbrowser.open(url)
        log.info("Browser opened: %s", url)
    except Exception:
        log.info("Could not open browser. Open manually: %s", url)


def main() -> None:
    parser = argparse.ArgumentParser(description="Triage server for review findings")
    parser.add_argument("report", type=Path, help="Path to report.json")
    parser.add_argument(
        "--port", type=int, default=8741, help="Server port (default: 8741)"
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--no-browser", action="store_true", help="Don't auto-open browser"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable debug logging"
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        log.debug("Verbose logging enabled")

    global REPORT_PATH, RENDERER_SCRIPT
    REPORT_PATH = args.report.resolve()
    RENDERER_SCRIPT = (Path(__file__).parent / "generate_review_report.py").resolve()

    if not REPORT_PATH.exists():
        log.error("Report file not found: %s", REPORT_PATH)
        sys.exit(1)
    if not RENDERER_SCRIPT.exists():
        log.error("Renderer script not found: %s", RENDERER_SCRIPT)
        sys.exit(1)

    log.debug("Report: %s", REPORT_PATH)
    log.debug("Renderer: %s", RENDERER_SCRIPT)

    # Validate report before starting
    try:
        t0 = time.monotonic()
        report = _load_report()
        log.info(
            "Loaded report: %d finding sections, %d total findings",
            len(report.get("findings", [])),
            sum(len(s.get("findings", [])) for s in report.get("findings", [])),
        )
        log.debug("Report load took %.0fms", (time.monotonic() - t0) * 1000)
    except (json.JSONDecodeError, KeyError) as exc:
        log.error("Invalid report JSON: %s", exc)
        sys.exit(1)

    class _ReuseServer(ThreadingHTTPServer):
        allow_reuse_address = True
        allow_reuse_port = True

    try:
        server = _ReuseServer((args.host, args.port), TriageHandler)
    except OSError as exc:
        log.error(
            "Cannot bind to port %d: %s. Kill the existing process with: "
            "fuser -k %d/tcp",
            args.port,
            exc,
            args.port,
        )
        sys.exit(1)
    server.daemon_threads = True  # Don't let lingering threads block shutdown
    display_host = "127.0.0.1" if args.host == "0.0.0.0" else args.host
    url = f"http://{display_host}:{args.port}"

    # Pre-warm the HTML cache so the first browser request is instant.
    threading.Thread(target=_generate_triage_html, daemon=True).start()

    log.info("Triage server starting on %s", url)
    print(f"\n  Triage UI: {url}\n")

    if not args.no_browser:
        threading.Timer(0.5, _open_browser, args=[url]).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Server stopped by user.")
    finally:
        server.server_close()
        log.info("Server shut down.")

    # Print final status
    with _lock:
        report = _load_report()
    triage = report.get("triage")
    if triage:
        decisions = triage.get("decisions", [])
        print(f"\nTriage complete: {len(decisions)} decisions saved to {REPORT_PATH}")
        from collections import Counter

        counts = Counter(d.get("action", "unknown") for d in decisions)
        for action, count in counts.most_common():
            print(f"  {action}: {count}")
    else:
        print("\nNo triage decisions were submitted.")


if __name__ == "__main__":
    main()
