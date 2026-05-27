#!/usr/bin/env python3
"""Unified renderer: converts a review report JSON into md, html, triage, or pdf.

Long-text finding fields (``description``, ``impact_description``,
``recommendation``, ``ai_assessment``, executive summary text) are rendered as
Markdown in HTML and PDF outputs.
Markdown output passes the source through verbatim (Markdown in, Markdown out).
HTML output is sanitised via ``bleach`` so untrusted Markdown cannot inject
``<script>`` or other active content.

Requires ``markdown >= 3.4`` and ``beautifulsoup4 >= 4.10`` for HTML/PDF rendering
(install via ``pip install -r scripts/requirements.txt``).

PDF Unicode support:
  PDF output registers a Unicode TrueType font so emoji and non-Latin scripts
  (Cyrillic, Arabic, CJK) render correctly in both ReportLab text flow and
  matplotlib charts. Font discovery order: (1) ``$CLAUDIUS_PDF_FONT`` env var
  pointing to a TTF, (2) an optional user-supplied font dropped at
  ``scripts/fonts/DejaVuSans.ttf`` (not shipped with the plugin; sibling
  ``-Bold``/``Mono`` variants picked up automatically when present),
  (3) common Linux system locations (DejaVu, Noto Sans — typically provided by
  the ``fonts-dejavu`` / ``fonts-noto`` packages). When no TTF is found, the
  renderer logs a warning to stderr and falls back to ReportLab's
  Helvetica/Courier core fonts (Latin-1 only — emoji and non-Latin scripts
  render as tofu boxes in that fallback).

PDF malformed Markdown:
  ``render_markdown_to_reportlab`` wraps the Markdown -> HTML -> ReportLab pass
  in a try/except. On any failure (e.g. an unclosed code fence that confuses the
  ReportLab mini-XML parser downstream), the renderer logs a warning to stderr
  and falls back to a single escaped ``<pre>``-style block containing the raw
  source so no content is silently dropped.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from html import escape as html_escape
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as xml_escape

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent / "schemas" / "review-report.schema.json"
)

# ---------------------------------------------------------------------------
# Color palette (shared across formats)
# ---------------------------------------------------------------------------
SEV_COLORS: dict[str, str] = {
    "CRITICAL": "#C0392B",
    "HIGH": "#E67E22",
    "MEDIUM": "#D4AC0D",
    "LOW": "#2E86C1",
    "INFO": "#7F8C8D",
}
BRAND = "#1B4F72"
ACCENT = "#2471A3"
BG_WHITE = "#FFFFFF"
TEXT_DARK = "#1A1A1A"
TEXT_SECONDARY = "#333333"
TEXT_MUTED = "#666666"
BG_LIGHT = "#F5F5F5"
BORDER = "#DDDDDD"
PRIORITY_COLORS: dict[str, str] = {
    "before_merge": "#C0392B",
    "before_production": "#E67E22",
    "post_deployment": "#27AE60",
}
GREEN = "#27AE60"
AMBER = "#E67E22"
RED = "#C0392B"

SEV_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
SEV_LABELS: dict[int, str] = {
    5: "CRITICAL",
    4: "HIGH",
    3: "MEDIUM",
    2: "LOW",
    1: "INFO",
}


def sev_label(value: int | str) -> str:
    """Map numeric severity to label string. Pass-through if already a string."""
    if isinstance(value, int):
        return SEV_LABELS.get(value, "INFO")
    return str(value)


# ===================================================================
# Validation
# ===================================================================
def validate_report(data: dict[str, Any], schema_path: Path) -> None:
    """Validate *data* against the JSON schema. Raises SystemExit on failure."""
    import jsonschema

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(
        schema,
        format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER,
    )
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    if errors:
        for err in errors:
            path = ".".join(str(p) for p in err.absolute_path) or "(root)"
            log.error("Validation error at %s: %s", path, err.message)
        sys.exit(1)


# ===================================================================
# Helpers
# ===================================================================
def _meta(data: dict[str, Any]) -> dict[str, Any]:
    return data.get("metadata", {})


def _severity_counts(data: dict[str, Any]) -> dict[str, int]:
    return data.get("summary_statistics", {}).get("severity_counts", {})


def _finding_tag_suffix(finding: dict[str, Any]) -> str:
    """Return ' -- tag1, tag2' or '' if no tags."""
    tags = finding.get("tags", [])
    if tags:
        return " \u2014 " + ", ".join(tags)
    return ""


# ---------------------------------------------------------------------------
# v3 shared helpers \u2014 used by every renderer so location/severity/verdict
# rendering stays consistent across Markdown / HTML / Triage / PDF.
# ---------------------------------------------------------------------------
def _location_link(finding: dict[str, Any]) -> dict[str, Any]:
    """Return ``{"text": location, "url": permalink or None}``.

    Templates use the dict's ``url`` to decide between linked and plain text;
    callers don't have to branch.
    """
    return {
        "text": finding.get("location", ""),
        "url": finding.get("location_permalink") or None,
    }


def _severity_tooltip(finding: dict[str, Any]) -> str:
    """Return ``"overall=.. risk=.. impact=.. scope=.."`` when all floats
    present, else ``""``. The numeric tooltip surfaces the breakdown for the
    HTML severity badge (no hover affordance in Markdown/PDF)."""
    keys = ("overall_severity", "risk", "impact", "scope")
    if not all(isinstance(finding.get(k), (int, float)) for k in keys):
        return ""
    return (
        f"overall={finding['overall_severity']:.2f} "
        f"risk={finding['risk']:.2f} "
        f"impact={finding['impact']:.2f} "
        f"scope={finding['scope']:.2f}"
    )


# Verdict base colors. ``valid`` is positive (green); ``needs_investigation``
# is amber; ``out_of_scope`` reuses the brand accent (neutral information);
# ``false_positive`` / ``duplicate`` are muted (dismissed). Unknown verdicts
# fall back to the page background so the chip stays visible but unstyled.
_VERDICT_BASE_COLORS: dict[str, str] = {
    "valid": GREEN,
    "needs_investigation": AMBER,
    "out_of_scope": ACCENT,
    "false_positive": TEXT_MUTED,
    "duplicate": TEXT_MUTED,
}


def _hex_to_rgb(s: str) -> tuple[int, int, int]:
    s = s.lstrip("#")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02X}{g:02X}{b:02X}"


_SNIPPET_LANG_RE = re.compile(r"[A-Za-z0-9_+.\-]+")


def _sanitize_snippet_language(raw: Any) -> str:
    """Sanitize a producer-supplied code-fence language tag.

    The info-string after a GFM fence is otherwise arbitrary, so a value
    containing newlines or backticks would terminate the fence early and
    inject downstream Markdown/HTML. We keep only the leading run of
    allowlist characters (``[A-Za-z0-9_+.-]+``) so common languages like
    ``python``, ``c++``, ``objective-c``, ``f#`` (truncates to ``f``) pass
    through unchanged. Returns ``""`` when nothing safe survives, in which
    case the caller emits a bare fence.
    """
    if not isinstance(raw, str):
        return ""
    match = _SNIPPET_LANG_RE.match(raw.strip())
    return match.group(0) if match else ""


def _truncate_snippet(content: str, max_lines: int) -> tuple[str, int]:
    """Soft-cap a code snippet to ``max_lines`` lines for PDF rendering.

    Returns the (possibly truncated) text and the number of omitted lines.
    The marker line ``[truncated — {N} lines omitted]`` replaces the tail so
    long blocks don't blow the page flow.
    """
    lines = content.splitlines()
    if len(lines) <= max_lines:
        return content, 0
    omitted = len(lines) - max_lines
    kept = lines[:max_lines]
    kept.append(f"[truncated — {omitted} lines omitted]")
    return "\n".join(kept), omitted


def _verdict_color(verdict: str | None, confidence: float | None) -> str:
    """Linear-interpolate the verdict chip background between ``BG_LIGHT``
    (washed out) and the verdict's base color (full saturation).

    ``confidence`` is clamped to ``[0, 1]``; ``None`` and ``NaN`` default to
    ``1.0`` so a verdict from a producer that didn't run validate-findings (or
    emitted a malformed value) still renders at full saturation. Unknown
    verdicts return ``BG_LIGHT`` regardless of confidence.
    """
    base_hex = _VERDICT_BASE_COLORS.get(verdict or "", BG_LIGHT)
    if confidence is None:
        confidence = 1.0
    # NaN compares False against every bound, so the clamp would skip and
    # `round(...)` would then raise ValueError. Detect explicitly.
    elif confidence != confidence:  # NaN
        confidence = 1.0
    if confidence < 0:
        confidence = 0.0
    elif confidence > 1:
        confidence = 1.0
    bg = _hex_to_rgb(BG_LIGHT)
    base = _hex_to_rgb(base_hex)
    blended = tuple(round(bg[i] + (base[i] - bg[i]) * confidence) for i in range(3))
    return _rgb_to_hex(*blended)


# ===================================================================
# Markdown rendering for long-text fields (description / impact_description /
# recommendation / ai_assessment).
# ===================================================================

# Heading -> font size (pt) for ReportLab. Matches PDF body sizing.
_RL_HEADING_SIZES = {"h1": 14, "h2": 13, "h3": 12, "h4": 11, "h5": 10, "h6": 10}

# Monospace font name used inside ReportLab inline ``<font>`` tags emitted by
# the Markdown walker. Defaults to the core ``Courier`` font (Latin-1 only) and
# gets swapped for a Unicode TTF face by ``_register_pdf_fonts`` when one is
# available, so inline ``code`` and fenced code blocks render emoji/CJK.
_RL_MONO_FONT = "Courier"

# Allowlist for bleach sanitisation of Markdown-produced HTML. Covers tags
# the ``markdown`` library emits with ``fenced_code`` + ``tables``; anything
# else (script, iframe, on* handlers, javascript: URIs) is stripped.
_HTML_ALLOWED_TAGS = {
    "p",
    "strong",
    "em",
    "code",
    "pre",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "ul",
    "ol",
    "li",
    "a",
    "br",
    "blockquote",
    "hr",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
}
_HTML_ALLOWED_ATTRS = {"a": ["href", "title"]}
_HTML_ALLOWED_PROTOCOLS = ["http", "https", "mailto"]


def render_markdown_to_html(s: str) -> Any:
    """Render a Markdown string to safe HTML for Jinja2 templates.

    Output is sanitised via ``bleach`` against an allowlist of standard
    Markdown-produced tags; raw ``<script>``, ``<iframe>``, ``on*`` handlers,
    and ``javascript:`` URIs are stripped. Returns a ``markupsafe.Markup`` so
    the template does not double-escape. Empty / whitespace-only input returns
    an empty Markup.
    """
    from markupsafe import Markup
    import bleach as _bleach
    import markdown as _markdown_lib

    if not s or not s.strip():
        return Markup("")
    md = _markdown_lib.Markdown(extensions=["fenced_code", "tables"])
    raw_html = md.convert(s)
    safe_html = _bleach.clean(
        raw_html,
        tags=_HTML_ALLOWED_TAGS,
        attributes=_HTML_ALLOWED_ATTRS,
        protocols=_HTML_ALLOWED_PROTOCOLS,
        strip=True,
    )
    return Markup(safe_html)


def _rl_inline(node: Any) -> str:
    """Render a BeautifulSoup node's children as ReportLab inline mini-XML."""
    from bs4 import NavigableString

    parts: list[str] = []
    for child in node.children:
        if isinstance(child, NavigableString):
            parts.append(xml_escape(str(child)))
            continue
        name = child.name
        if name in ("strong", "b"):
            parts.append(f"<b>{_rl_inline(child)}</b>")
        elif name in ("em", "i"):
            parts.append(f"<i>{_rl_inline(child)}</i>")
        elif name == "code":
            parts.append(f'<font name="{_RL_MONO_FONT}">{_rl_inline(child)}</font>')
        elif name == "br":
            parts.append("<br/>")
        elif name == "a":
            href = child.get("href", "")
            safe_href = xml_escape(href, {chr(34): "&quot;"})
            parts.append(
                f'<link href="{safe_href}" color="{ACCENT}">{_rl_inline(child)}</link>'
            )
        else:
            # Unknown inline element -- fall through to its children's text.
            parts.append(_rl_inline(child))
    return "".join(parts)


def _rl_block(node: Any) -> list[tuple[str, str]]:
    """Convert a top-level block node into a list of (kind, body) tuples.

    ``kind`` is one of: ``"para"`` (regular Paragraph), ``"h1".."h6"``,
    or ``"pre"`` (code block). List items expand into one ``"para"`` per
    item with a bullet/number prefix. ``body`` is ReportLab mini-XML.
    """
    name = (node.name or "").lower()
    if name in _RL_HEADING_SIZES:
        return [(name, f"<b>{_rl_inline(node)}</b>")]
    if name == "p":
        return [("para", _rl_inline(node))]
    if name == "pre":
        # Render code blocks verbatim in monospace, preserving newlines as <br/>.
        text = node.get_text()
        text = xml_escape(text).replace("\n", "<br/>")
        return [("pre", f'<font name="{_RL_MONO_FONT}">{text}</font>')]
    if name in ("ul", "ol"):
        items: list[tuple[str, str]] = []
        ordered = name == "ol"
        for idx, li in enumerate(node.find_all("li", recursive=False), start=1):
            marker = f"{idx}." if ordered else "&#8226;"
            items.append(("para", f"{marker}&nbsp;{_rl_inline(li)}"))
        return items
    if name in ("strong", "b", "em", "i", "code", "a", "br") or name is None:
        # Naked inline content at the top level -- wrap as a paragraph.
        return [("para", _rl_inline(node))]
    # Unknown block -- recurse into children, flattening their blocks.
    out: list[tuple[str, str]] = []
    for child in node.children:
        if hasattr(child, "name") and child.name is not None:
            out.extend(_rl_block(child))
    return out


def _markdown_fallback_blocks(s: str) -> list[tuple[str, str]]:
    """Render *s* as a single escaped preformatted block.

    Used when the Markdown parser or BeautifulSoup walker fails (e.g. on
    malformed input that would otherwise silently swallow content). Newlines
    are preserved as ``<br/>`` and special characters are XML-escaped so the
    output is always safe for ``reportlab.platypus.Paragraph``.
    """
    text = xml_escape(s).replace("\n", "<br/>")
    return [("pre", f'<font name="{_RL_MONO_FONT}">{text}</font>')]


def render_markdown_to_reportlab(s: str) -> list[tuple[str, str]]:
    """Render Markdown to a list of ReportLab Paragraph blocks.

    Each entry is ``(kind, body)`` where ``kind`` selects the ParagraphStyle
    (``"para"``, ``"h1".."h6"``, ``"pre"``) and ``body`` is mini-XML safe
    for ``reportlab.platypus.Paragraph``. Empty input yields an empty list.

    On any conversion error (malformed Markdown, parser exception, etc.) the
    function logs a warning to stderr and falls back to a single escaped
    preformatted block containing the raw source — never raises, never
    silently drops content.
    """
    if not s or not s.strip():
        return []
    try:
        from bs4 import BeautifulSoup
        import markdown as _markdown_lib

        md = _markdown_lib.Markdown(extensions=["fenced_code", "tables"])
        html = md.convert(s)
        soup = BeautifulSoup(html, "html.parser")
        blocks: list[tuple[str, str]] = []
        for child in soup.children:
            if hasattr(child, "name") and child.name is not None:
                blocks.extend(_rl_block(child))
            else:
                text = str(child).strip()
                if text:
                    blocks.append(("para", xml_escape(text)))
        return blocks
    except Exception as exc:  # noqa: BLE001 -- intentional broad fallback
        log.warning(
            "Markdown -> ReportLab conversion failed (%s: %s); rendering raw text",
            type(exc).__name__,
            exc,
            exc_info=True,
        )
        return _markdown_fallback_blocks(s)


# ===================================================================
# FORMAT: Markdown
# ===================================================================
def render_markdown(data: dict[str, Any]) -> str:
    """Render the report as a Markdown string."""
    meta = _meta(data)
    es = data.get("executive_summary", {})
    stats = data.get("summary_statistics", {})
    lines: list[str] = []

    report_type = meta.get("report_type", "code_review")
    scope = meta.get("scope", "N/A")
    if report_type == "comment_check":
        lines.append(f"# PR Comment Verification: {scope}")
    else:
        lines.append(f"# Code Review Report: {scope}")
    lines.append("")

    # Metadata table
    lines.append("| Field | Value |")
    lines.append("|---|---|")
    lines.append(f"| **Date** | {meta.get('date', 'N/A')} |")
    lines.append(f"| **Project** | {meta.get('project', 'N/A')} |")
    lines.append(f"| **Branch** | {meta.get('branch', 'N/A')} |")
    lines.append(f"| **Commit** | {meta.get('commit', 'N/A')} |")
    lines.append(f"| **Scope** | {scope} |")
    reviewers = ", ".join(meta.get("reviewers", []))
    lines.append(f"| **Reviewers** | {reviewers} |")
    lines.append("")

    # Executive summary
    lines.append("## Executive Summary")
    lines.append("")
    lines.append(es.get("overall_assessment", ""))
    lines.append("")
    if es.get("summary_text"):
        lines.append(es["summary_text"])
        lines.append("")

    # Severity counts summary table
    matrix = stats.get("severity_category_matrix", [])
    if matrix:
        lines.append("### Findings Summary")
        lines.append("")
        lines.append(
            "| Severity | Security | Project | Code Quality | Documentation | Total |"
        )
        lines.append("|---|---|---|---|---|---|")
        for row in matrix:
            lines.append(
                f"| {row['severity']} | {row.get('security', 0)} | {row.get('project', 0)} "
                f"| {row.get('code_quality', 0)} | {row.get('documentation', 0)} | {row['total']} |"
            )
        lines.append("")

    vc = stats.get("verdict_counts")
    if vc:
        lines.append("### Verdict Summary")
        lines.append("")
        lines.append("| Verdict | Count |")
        lines.append("|---------|-------|")
        for verdict, count in vc.items():
            lines.append(f"| {verdict} | {count} |")
        lines.append("")

    # Top findings
    top = data.get("top_findings", [])
    if top:
        lines.append("### Top 5 Findings")
        lines.append("")
        for tf in top[:5]:
            loc = tf.get("location", "")
            permalink = tf.get("location_permalink")
            if permalink and permalink.startswith(("https://", "http://")):
                loc_md = f"[`{loc}`]({permalink})"
            else:
                loc_md = f"`{loc}`"
            lines.append(
                f"- **{tf['id']}** ({sev_label(tf['severity'])}): {tf['title']} \u2014 {loc_md}"
            )
        lines.append("")

    # Sections
    section_labels = {
        "security": "Part I: Security Findings",
        "project": "Part II: Project Consistency",
        "code_quality": "Part III: Code Quality & Language Best Practices",
        "dependencies": "Part IV: Dependencies",
        "documentation": "Part V: Documentation",
        "pr_comments": "Part VI: PR Comment Verification",
    }
    for section in data.get("findings", []):
        cat = section.get("category", "")
        heading = section_labels.get(cat, section.get("title", "Findings"))
        lines.append(f"## {heading}")
        if section.get("subtitle"):
            lines.append(f"_{section['subtitle']}_")
        lines.append("")

        for f in section.get("findings", []):
            tag_str = _finding_tag_suffix(f)
            sev_extra = ""
            if _severity_tooltip(f):
                sev_extra = (
                    f" *(overall={f['overall_severity']:.2f}, "
                    f"risk={f['risk']:.2f}, "
                    f"impact={f['impact']:.2f}, "
                    f"scope={f['scope']:.2f})*"
                )
            lines.append(
                f"### {f['id']} ({sev_label(f['severity'])}){sev_extra}: {f['title']}{tag_str}"
            )
            lines.append("")
            loc = f.get("location", "")
            permalink = f.get("location_permalink")
            if permalink and permalink.startswith(("https://", "http://")):
                lines.append(f"- **Location**: [`{loc}`]({permalink})")
            else:
                lines.append(f"- **Location**: `{loc}`")
            lines.append(f"- **Description**: {f['description']}")
            if f.get("impact_description"):
                lines.append(f"- **Impact**: {f['impact_description']}")
            lines.append(f"- **Recommendation**: {f['recommendation']}")
            if f.get("verdict"):
                lines.append(f"- **Verdict**: {f['verdict']}")
            if f.get("ai_verdict"):
                raw_conf = f.get("ai_verdict_confidence")
                conf = raw_conf if isinstance(raw_conf, (int, float)) else 1.0
                ai_text = f.get("ai_assessment", "")
                if ai_text:
                    lines.append(
                        f"- **AI Assessment** *(verdict: {f['ai_verdict']}, "
                        f"confidence: {conf:.2f})*: {ai_text}"
                    )
                else:
                    lines.append(
                        f"- **AI Verdict**: {f['ai_verdict']} "
                        f"*(confidence: {conf:.2f})*"
                    )
            if f.get("reviewer"):
                url = f.get("comment_url", "")
                if url and url.startswith(("https://", "http://")):
                    safe_reviewer = f["reviewer"].replace("]", "\\]")
                    lines.append(f"- **Reviewer**: [{safe_reviewer}]({url})")
                else:
                    lines.append(f"- **Reviewer**: {f['reviewer']}")
            for snip in f.get("code_snippets") or []:
                raw_summary = (
                    snip.get("caption") or snip.get("language") or "Code snippet"
                )
                # Caption is a producer-supplied label, not Markdown — escape
                # HTML so it cannot break out of the surrounding <summary>.
                summary = html_escape(raw_summary)
                # Sanitize the producer-supplied language to an allowlist
                # token so newlines or backticks cannot break out of the
                # fence. Empty result means a bare fence with no info-string.
                lang = _sanitize_snippet_language(snip.get("language", ""))
                content = snip.get("content", "")
                # Pick a fence longer than any backtick run inside the content,
                # so embedded ``` cannot terminate the outer fence (CommonMark
                # requires opening/closing fences to match length).
                longest = max((len(m) for m in re.findall(r"`+", content)), default=2)
                fence = "`" * max(longest + 1, 3)
                # GFM requires blank lines around <summary> and the fence for
                # the embedded code block to parse on GitHub.
                lines.append("")
                lines.append(f"<details><summary>{summary}</summary>")
                lines.append("")
                lines.append(f"{fence}{lang}")
                lines.append(content)
                lines.append(fence)
                lines.append("")
                lines.append("</details>")
            lines.append("")

        if section.get("positives"):
            lines.append(f"> **Positive observations:** {section['positives']}")
            lines.append("")

    # Dependencies
    deps = data.get("dependencies", [])
    if deps:
        lines.append("## Dependencies")
        lines.append("")
        lines.append("| Package | Version | Advisories | Applicable | OK |")
        lines.append("|---|---|---|---|---|")
        for d in deps:
            ok_str = "Yes" if d.get("ok") else "No"
            lines.append(
                f"| {d['package']} | {d['version']} | {d.get('advisories', 'None')} "
                f"| {d.get('applicable', 'N/A')} | {ok_str} |"
            )
        lines.append("")

    # Recommendations / Remediation
    remed = data.get("remediation", [])
    if remed:
        lines.append("## Recommendations")
        lines.append("")
        for r in remed:
            ids = ", ".join(r.get("finding_ids", []))
            lines.append(f"### {r['label']} ({r['count']} items)")
            if ids:
                lines.append(f"Findings: {ids}")
            lines.append("")

    # Verdict
    if es.get("verdict_text") or es.get("verdict_action"):
        lines.append("## Verdict")
        lines.append("")
        if es.get("verdict_text"):
            lines.append(es["verdict_text"])
            lines.append("")
        if es.get("verdict_action"):
            lines.append(f"**Action:** {es['verdict_action']}")
            lines.append("")

    return "\n".join(lines)


# ===================================================================
# FORMAT: HTML (and Triage base)
# ===================================================================
_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ "PR Comment Verification" if report_type == "comment_check" else "Code Review Report" }}: {{ scope }}</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  color:{{ TEXT_DARK }};background:{{ BG_WHITE }};line-height:1.6}
.container{max-width:960px;margin:0 auto;padding:0 1rem 2rem}
/* Header */
.header-bar{background:{{ BRAND }};color:#fff;padding:1rem 0}
.header-bar .container{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap}
.header-bar h1{font-size:1.3rem;margin:0}
.header-bar .meta{font-size:.85rem;opacity:.85}
/* TOC sidebar */
.toc{position:sticky;top:0;background:{{ BG_LIGHT }};border-bottom:1px solid {{ BORDER }};
  padding:.5rem 1rem;z-index:100;overflow-x:auto;white-space:nowrap}
.toc a{color:{{ ACCENT }};text-decoration:none;margin-right:1.2rem;font-size:.85rem}
.toc a:hover{text-decoration:underline}
/* KPI */
.kpi-row{display:flex;gap:1rem;margin:1.5rem 0;flex-wrap:wrap}
.kpi-box{flex:1;min-width:140px;background:{{ BG_LIGHT }};border:1px solid {{ BORDER }};
  border-radius:6px;padding:1rem;text-align:center}
.kpi-box .val{font-size:2rem;font-weight:700}
.kpi-box .label{font-size:.8rem;color:{{ TEXT_MUTED }}}
/* Tables */
table{border-collapse:collapse;width:100%;margin:1rem 0;font-size:.9rem}
th{background:{{ BRAND }};color:#fff;padding:.5rem .7rem;text-align:left}
td{padding:.5rem .7rem;border-bottom:1px solid {{ BORDER }}}
tr:nth-child(even) td{background:{{ BG_LIGHT }}}
/* Badge */
.badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:.75rem;
  font-weight:700;color:#fff;white-space:nowrap}
.badge-CRITICAL{background:{{ SEV_CRITICAL }}}
.badge-HIGH{background:{{ SEV_HIGH }}}
.badge-MEDIUM{background:{{ SEV_MEDIUM }}}
.badge-LOW{background:{{ SEV_LOW }}}
.badge-INFO{background:{{ SEV_INFO }}}
/* Tag chips */
.tag{display:inline-block;padding:1px 6px;border-radius:8px;font-size:.7rem;
  background:{{ BG_LIGHT }};border:1px solid {{ BORDER }};color:{{ TEXT_SECONDARY }};margin-left:4px}
/* Sections */
h2{color:{{ BRAND }};margin-top:2rem;margin-bottom:.5rem;border-bottom:2px solid {{ BRAND }};padding-bottom:.3rem}
h3{margin-top:1.2rem;margin-bottom:.3rem}
details{margin:.6rem 0}
details summary{cursor:pointer;font-weight:600;padding:.3rem 0}
details summary:hover{color:{{ ACCENT }}}
.finding{margin:.8rem 0;padding:.6rem .8rem;border-left:3px solid {{ BORDER }};background:{{ BG_WHITE }}}
.finding-CRITICAL{border-left-color:{{ SEV_CRITICAL }}}
.finding-HIGH{border-left-color:{{ SEV_HIGH }}}
.finding-MEDIUM{border-left-color:{{ SEV_MEDIUM }}}
.finding-LOW{border-left-color:{{ SEV_LOW }}}
.finding-INFO{border-left-color:{{ SEV_INFO }}}
.finding dl{display:grid;grid-template-columns:auto 1fr;gap:.1rem .5rem;margin:.5rem 0}
.finding dt{font-weight:600}
.finding dd{margin:0}
.finding dl{margin:.3rem 0}
.positives{color:{{ GREEN }};font-style:italic;margin:.5rem 0}
/* Verdict */
.verdict{background:{{ BG_LIGHT }};border:1px solid {{ BORDER }};border-radius:6px;padding:1rem;margin:1.5rem 0}
/* Footer */
.footer{text-align:center;color:{{ TEXT_MUTED }};font-size:.8rem;padding:1.5rem 0;border-top:1px solid {{ BORDER }};margin-top:2rem}
/* Priority colors */
.priority-before_merge{color:{{ PRI_BEFORE_MERGE }};font-weight:700}
.priority-before_production{color:{{ PRI_BEFORE_PROD }};font-weight:700}
.priority-post_deployment{color:{{ PRI_POST_DEPLOY }};font-weight:700}
/* Charts */
.chart-container{max-width:500px;margin:1rem auto}
.chart-container-wide{max-width:700px;margin:1rem auto}
/* Print */
@media print{
  .toc,.no-print{display:none!important}
  .container{max-width:100%}
  details[open] summary~*{display:block}
  details:not([open]) summary~*{display:none}
  .header-bar{-webkit-print-color-adjust:exact;print-color-adjust:exact}
}
/* Responsive */
@media(max-width:640px){
  .kpi-row{flex-direction:column}
  .header-bar h1{font-size:1.1rem}
}
/* Report toolbar (filter/sort) */
.report-toolbar{background:{{ BG_LIGHT }};border:1px solid {{ BORDER }};border-radius:6px;
  padding:.6rem .8rem;margin:.8rem auto;max-width:960px;display:flex;flex-wrap:wrap;
  gap:.5rem;align-items:center}
.report-toolbar select,.report-toolbar input[type=text]{padding:5px 10px;border:1px solid {{ BORDER }};
  border-radius:4px;font-size:.85rem;transition:border-color .15s,box-shadow .15s}
.report-toolbar select:focus,.report-toolbar input:focus{border-color:{{ ACCENT }};
  box-shadow:0 0 0 2px rgba(36,113,163,.15);outline:none}
.report-toolbar .count-label{font-size:.8rem;color:{{ TEXT_MUTED }};margin-left:auto}
/* Markdown rendered inside <dd> (description / impact / recommendation) */
.finding dd p{margin:.25rem 0}
.finding dd p:first-child{margin-top:0}
.finding dd p:last-child{margin-bottom:0}
.finding dd h1,.finding dd h2,.finding dd h3,
.exec-summary h1,.exec-summary h2,.exec-summary h3{margin:.6rem 0 .3rem;color:{{ BRAND }};
  border-bottom:1px solid {{ BORDER }};padding-bottom:.15rem}
.finding dd h1,.exec-summary h1{font-size:1.1rem}
.finding dd h2,.exec-summary h2{font-size:1.0rem}
.finding dd h3,.exec-summary h3{font-size:.95rem;border-bottom:none}
.finding dd code,.exec-summary code{background:{{ BG_LIGHT }};border:1px solid {{ BORDER }};
  border-radius:3px;padding:.05rem .25rem;font-size:.85em;font-family:Menlo,Consolas,monospace}
.finding dd pre,.exec-summary pre{background:{{ BG_LIGHT }};border:1px solid {{ BORDER }};
  border-radius:4px;padding:.5rem .7rem;overflow-x:auto;font-size:.85em;margin:.4rem 0}
.finding dd pre code,.exec-summary pre code{background:transparent;border:none;padding:0}
.finding dd ul,.finding dd ol,.exec-summary ul,.exec-summary ol{margin:.3rem 0 .3rem 1.4rem}
.finding dd li,.exec-summary li{margin:.1rem 0}
.finding dd strong,.exec-summary strong{color:{{ TEXT_DARK }}}
.finding dd a,.exec-summary a{color:{{ ACCENT }}}
.exec-summary{margin:.5rem 0}
.exec-summary p{margin:.4rem 0}
{% block extra_css %}{% endblock %}
</style>
</head>
<body>
<div class="header-bar">
  <div class="container">
    <h1>{{ "PR Comment Verification" if report_type == "comment_check" else "Code Review Report" }}: {{ scope }}</h1>
    <div class="meta">{{ meta.project }} &middot; {{ meta.date }}{% if meta.branch %} &middot; {{ meta.branch }}{% endif %}</div>
  </div>
</div>

<nav class="toc no-print" id="toc">
  <a href="#summary">Summary</a>
  {% if top_findings %}<a href="#top-findings">Top Findings</a>{% endif %}
  {% for sec in findings %}<a href="#section-{{ loop.index }}">{{ sec.title }}</a>{% endfor %}
  {% if dependencies %}<a href="#dependencies">Dependencies</a>{% endif %}
  {% if remediation %}<a href="#remediation">Remediation</a>{% endif %}
  <a href="#charts">Charts</a>
</nav>

<div class="container">

<!-- Executive Summary -->
<h2 id="summary">Executive Summary</h2>
<div class="exec-summary"><strong>{{ executive_summary.overall_assessment }}</strong></div>
{% if executive_summary.summary_text %}<div class="exec-summary">{{ executive_summary.summary_text | markdown }}</div>{% endif %}

<div class="kpi-row">
  <div class="kpi-box"><div class="val" style="color:{{ ACCENT }}">{{ stats.total_findings }}</div><div class="label">Total Findings</div></div>
  <div class="kpi-box"><div class="val" style="color:{{ AMBER }}">{{ stats.redundancy_ratio | default("N/A") }}</div><div class="label">Redundancy Ratio</div></div>
  <div class="kpi-box"><div class="val" style="color:{{ RED }}">{{ stats.critical_count | default(0) }}</div><div class="label">Critical</div></div>
</div>

<!-- Summary table -->
{% if matrix %}
<table>
<tr><th>Severity</th><th>Security</th><th>Project</th><th>Code Quality</th><th>Documentation</th><th>Total</th></tr>
{% for row in matrix %}
<tr>
  <td><span class="badge badge-{{ row.severity }}">{{ row.severity }}</span></td>
  <td>{{ row.security }}</td><td>{{ row.project }}</td>
  <td>{{ row.code_quality }}</td><td>{{ row.documentation | default(0) }}</td>
  <td><strong>{{ row.total }}</strong></td>
</tr>
{% endfor %}
</table>
{% endif %}

<!-- Verdict -->
<h3 id="verdict">Verdict</h3>
<div class="verdict">
  {% if executive_summary.verdict_text %}<div class="exec-summary">{{ executive_summary.verdict_text | markdown }}</div>{% endif %}
  {% if executive_summary.verdict_action %}<p><strong>Action:</strong> {{ executive_summary.verdict_action }}</p>{% endif %}
</div>

<!-- Top findings -->
{% if top_findings %}
<h2 id="top-findings">Top Findings</h2>
<table>
<tr><th>ID</th><th>Severity</th><th>Title</th><th>Location</th>{% if triage %}<th class="no-print">Decision</th>{% endif %}</tr>
{% for tf in top_findings %}
<tr>
  <td><a href="#finding-{{ tf.id }}">{{ tf.id }}</a></td>
  <td><span class="badge badge-{{ tf.severity|sev_label }}">{{ tf.severity|sev_label }}</span></td>
  <td>{{ tf.title }}</td>
  <td>{% if tf.location_permalink and tf.location_permalink.startswith(('https://', 'http://')) %}<a href="{{ tf.location_permalink }}" target="_blank" rel="noopener"><code>{{ tf.location }}</code></a>{% else %}<code>{{ tf.location }}</code>{% endif %}</td>
  {% if triage %}<td class="no-print"><select class="triage-action-top" data-finding-id="{{ tf.id }}">
    <option value="---">---</option>
    <option value="fix">Fix</option>
    <option value="accept_risk">Accept Risk</option>
    <option value="defer">Defer</option>
    <option value="false_positive">False Positive</option>
    <option value="duplicate">Duplicate</option>
  </select></td>{% endif %}
</tr>
{% endfor %}
</table>
{% endif %}

<!-- Dependencies -->
{% if dependencies %}
<h2 id="dependencies">Dependencies</h2>
<table>
<tr><th>Package</th><th>Version</th><th>Advisories</th><th>Applicable</th><th>OK</th></tr>
{% for d in dependencies %}
<tr>
  <td>{{ d.package }}</td><td>{{ d.version }}</td>
  <td>{{ d.advisories | default("None") }}</td>
  <td>{{ d.applicable | default("N/A") }}</td>
  <td>{% if d.ok %}Yes{% else %}<strong style="color:{{ RED }}">No</strong>{% endif %}</td>
</tr>
{% endfor %}
</table>
{% endif %}

<!-- Detailed findings by section -->
{% if not triage %}
<div class="report-toolbar no-print" id="reportToolbar">
  <select id="filterSeverity">
    <option value="">All Severities</option>
    <option value="5">Critical</option>
    <option value="4">High</option>
    <option value="3">Medium</option>
    <option value="2">Low</option>
    <option value="1">Info</option>
  </select>
  <select id="filterCategory">
    <option value="">All Categories</option>
    <option value="security">Security</option>
    <option value="project">Project</option>
    <option value="code_quality">Code Quality</option>
    <option value="documentation">Documentation</option>
    <option value="dependencies">Dependencies</option>
    <option value="pr_comments">PR Comments</option>
  </select>
  <select id="filterAiVerdict">
    <option value="">All AI Verdicts</option>
    <option value="valid">Valid</option>
    <option value="false_positive">False Positive</option>
    <option value="needs_investigation">Needs Investigation</option>
    <option value="out_of_scope">Out of Scope</option>
    <option value="duplicate">Duplicate</option>
  </select>
  <input type="text" id="filterSearch" placeholder="Search findings&hellip;" aria-label="Search findings">
  <select id="sortBy">
    <option value="overall" selected>Overall Severity</option>
    <option value="severity">Severity (band)</option>
    <option value="id">ID</option>
    <option value="category">Category</option>
  </select>
  <button type="button" id="sortOrder" title="Toggle sort order" style="padding:4px 10px;border:1px solid {{ BORDER }};border-radius:4px;background:{{ BG_WHITE }};cursor:pointer;font-size:.95rem;line-height:1;transition:border-color .15s">&#9650;</button>
  <span class="count-label" id="filterCount"></span>
</div>
{% endif %}

<div id="findingsContainer">
{% for sec in findings %}
<div class="findings-section" data-section-category="{{ sec.category }}">
<h2 id="section-{{ loop.index }}">{{ sec.title }}</h2>
{% if sec.subtitle %}<p><em>{{ sec.subtitle }}</em></p>{% endif %}

<details open>
<summary>{{ sec.findings | length }} finding{{ "s" if sec.findings | length != 1 else "" }}</summary>

{% for f in sec.findings %}
<div class="finding finding-{{ f.severity|sev_label }}" id="finding-{{ f.id }}" data-finding-id="{{ f.id }}" data-severity="{{ f.severity }}" data-category="{{ sec.category }}" data-overall="{{ f.overall_severity if f.overall_severity is not none else '' }}" data-ai-verdict="{{ f.ai_verdict | default('', true) }}">
  <h3>
    <span class="badge badge-{{ f.severity|sev_label }}"{% if f._severity_tooltip %} title="{{ f._severity_tooltip }}"{% endif %}>{{ f.severity|sev_label }}</span>
    {% if f.ai_verdict %}<span class="ai-verdict-chip" style="background-color: {{ f._verdict_chip_bg }}; color: #fff; padding: 2px 8px; border-radius: 10px; font-size: .75rem; font-weight: 700;" title="confidence: {{ '%.2f' % (f.ai_verdict_confidence|default(1.0, true)) }}">{{ f.ai_verdict }}</span>{% endif %}
    {{ f.id }}: {{ f.title }}
    {% for tag in f.tags | default([]) %}<span class="tag">{{ tag }}</span>{% endfor %}
  </h3>
  <dl>
    <dt>Location:</dt><dd>{% if f.location_permalink and f.location_permalink.startswith(('https://', 'http://')) %}<a href="{{ f.location_permalink }}" target="_blank" rel="noopener"><code>{{ f.location }}</code></a>{% else %}<code>{{ f.location }}</code>{% endif %}</dd>
    <dt>Description:</dt><dd>{{ f.description | markdown }}</dd>
    {% if f.impact_description %}<dt>Impact:</dt><dd>{{ f.impact_description | markdown }}</dd>{% endif %}
    <dt>Recommendation:</dt><dd>{{ f.recommendation | markdown }}</dd>
    {% if f.ai_assessment %}<dt>AI Assessment:</dt><dd>{{ f.ai_assessment | markdown }}</dd>{% endif %}
    {% if f.verdict %}
    <dt>Verdict:</dt><dd><span class="badge" style="background:{{ verdict_colors.get(f.verdict, '#7F8C8D') }}">{{ f.verdict }}</span></dd>
    {% endif %}
    {% if f.reviewer %}
    <dt>Reviewer:</dt><dd>{% if f.comment_url and f.comment_url.startswith(('https://', 'http://')) %}<a href="{{ f.comment_url }}">{{ f.reviewer }}</a>{% else %}{{ f.reviewer }}{% endif %}</dd>
    {% endif %}
  </dl>
  {% for snip in f.code_snippets | default([]) %}
  <details class="code-snippet"><summary>{{ snip.caption or snip.language or 'Code snippet' }}</summary><pre><code class="language-{{ snip.language | default('') | e }}">{{ snip.content | e }}</code></pre></details>
  {% endfor %}
</div>
{% endfor %}

{% if sec.positives %}
<p class="positives"><strong>Positive observations:</strong> {{ sec.positives }}</p>
{% endif %}
</details>
</div>
{% endfor %}
</div>

<!-- Remediation -->
{% if remediation %}
<h2 id="remediation">Remediation Priorities</h2>
<table>
<tr><th>Priority</th><th>Count</th><th>Finding IDs</th></tr>
{% for r in remediation %}
<tr>
  <td><span class="priority-{{ r.priority }}">{{ r.label }}</span></td>
  <td>{{ r.count }}</td>
  <td>{{ r.finding_ids | default([]) | join(", ") }}</td>
</tr>
{% endfor %}
</table>
{% endif %}

{% if triage %}
<div class="triage-bottom-bar no-print" style="margin:2rem 0 1rem;padding:1rem;background:{{ BG_LIGHT|e }};border:1px solid {{ BORDER|e }};border-radius:6px;text-align:center">
  <button id="exportDecisionsBottom" style="padding:8px 20px;background:{{ ACCENT|e }};color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:.95rem">Export Decisions</button>
  <button id="submitBtnBottom" style="padding:8px 20px;background:{{ BRAND|e }};color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:.95rem;margin-left:.5rem">Submit to Server</button>
</div>
{% endif %}

<!-- Charts -->
<h2 id="charts">Charts</h2>

<div class="chart-container">
  <canvas id="severityChart"></canvas>
</div>

<div class="chart-container-wide">
  <canvas id="categoryChart"></canvas>
</div>

{% if agent_stats %}
<div class="chart-container">
  <canvas id="agentContribChart"></canvas>
</div>

<div class="chart-container-wide">
  <canvas id="agentChart"></canvas>
</div>

<div class="chart-container-wide">
  <canvas id="dedupChart"></canvas>
</div>
{% endif %}

{% if remediation %}
<div class="chart-container-wide">
  <canvas id="remediationChart"></canvas>
</div>
{% endif %}

{% if triage %}
<div class="triage-bottom-bar no-print" style="margin:2rem 0 1rem;padding:1rem;background:{{ BG_LIGHT|e }};border:1px solid {{ BORDER|e }};border-radius:6px;text-align:center">
  <button id="exportDecisionsEnd" style="padding:8px 20px;background:{{ ACCENT|e }};color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:.95rem">Export Decisions</button>
  <button id="submitBtnEnd" style="padding:8px 20px;background:{{ BRAND|e }};color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:.95rem;margin-left:.5rem">Submit to Server</button>
</div>
{% endif %}

</div><!-- /container -->

<div class="footer">Co-authored by Claudius the Magnificent AI Agent</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
(function(){
  const sevColors = {{ sev_colors_json }};
  const sevCounts = {{ sev_counts_json }};
  const sevOrder = {{ sev_order_json }};

  // Severity donut
  const sevLabels = [], sevValues = [], sevClrs = [];
  for (const s of sevOrder) {
    const v = sevCounts[s] || 0;
    if (v > 0) { sevLabels.push(s + " (" + v + ")"); sevValues.push(v); sevClrs.push(sevColors[s]); }
  }
  if (sevValues.length) {
    new Chart(document.getElementById("severityChart"), {
      type: "doughnut",
      data: {labels: sevLabels, datasets: [{data: sevValues, backgroundColor: sevClrs, borderWidth: 2, borderColor: "#fff"}]},
      options: {responsive: true, plugins: {title: {display: true, text: "Severity Distribution", font: {size: 15}}}}
    });
  }

  // Category stacked bar
  const matrix = {{ matrix_json }};
  if (matrix.length) {
    const cats = ["security", "project", "code_quality", "documentation"];
    const catLabels = ["Security", "Project", "Code Quality", "Documentation"];
    const datasets = [];
    for (const s of sevOrder) {
      const row = matrix.find(r => r.severity === s);
      if (!row) continue;
      datasets.push({label: s, data: cats.map(c => row[c] || 0), backgroundColor: sevColors[s]});
    }
    new Chart(document.getElementById("categoryChart"), {
      type: "bar",
      data: {labels: catLabels, datasets},
      options: {indexAxis: "y", responsive: true, scales: {x: {stacked: true, ticks:{stepSize:1}}, y: {stacked: true}},
        plugins: {title: {display: true, text: "Findings by Category", font: {size: 15}}}}
    });
  }

  // Agent charts
  {% if agent_stats %}
  const agentStats = {{ agent_stats_json }};
  const agentPalette = ["{{ ACCENT }}", "{{ GREEN }}", "{{ AMBER }}", "{{ SEV_CRITICAL }}", "{{ SEV_MEDIUM }}", "#8E44AD", "#16A085", "#D35400"];
  if (agentStats.length) {
    // 1. Agent Contribution donut — share of total findings per agent
    const contribLabels = [], contribValues = [], contribColors = [];
    agentStats.forEach((a, i) => {
      const total = a.unique + a.redundant;
      if (total > 0) {
        contribLabels.push(a.agent.replace("claudius:", "") + " (" + total + ")");
        contribValues.push(total);
        contribColors.push(agentPalette[i % agentPalette.length]);
      }
    });
    if (contribValues.length) {
      new Chart(document.getElementById("agentContribChart"), {
        type: "doughnut",
        data: {labels: contribLabels, datasets: [{data: contribValues, backgroundColor: contribColors, borderWidth: 2, borderColor: "#fff"}]},
        options: {responsive: true, plugins: {title: {display: true, text: "Agent Contribution", font: {size: 15}},
          subtitle: {display: true, text: "Total findings reported per agent (before dedup)", font: {size: 11}, color: "{{ TEXT_MUTED }}"}}}
      });
    }

    // 2. Unique vs Redundant per agent (existing bar chart)
    new Chart(document.getElementById("agentChart"), {
      type: "bar",
      data: {
        labels: agentStats.map(a => a.agent.replace("claudius:", "")),
        datasets: [
          {label: "Unique", data: agentStats.map(a => a.unique), backgroundColor: "{{ GREEN }}"},
          {label: "Redundant", data: agentStats.map(a => a.redundant), backgroundColor: "{{ AMBER }}"}
        ]
      },
      options: {responsive: true, plugins: {title: {display: true, text: "Agent Performance", font: {size: 15}},
        subtitle: {display: true, text: "Unique findings vs duplicates found by other agents", font: {size: 11}, color: "{{ TEXT_MUTED }}"}},
        scales: {y:{ticks:{stepSize:1}}}}
    });

    // 3. Deduplication funnel — total raw vs unique after dedup
    const totalRaw = agentStats.reduce((s, a) => s + a.unique + a.redundant, 0);
    const totalUnique = agentStats.reduce((s, a) => s + a.unique, 0);
    const totalRedundant = totalRaw - totalUnique;
    const dedupPct = totalRaw > 0 ? Math.round(totalRedundant / totalRaw * 100) : 0;
    new Chart(document.getElementById("dedupChart"), {
      type: "bar",
      data: {
        labels: ["Raw Findings", "After Dedup"],
        datasets: [
          {label: "Unique", data: [totalUnique, totalUnique], backgroundColor: "{{ GREEN }}"},
          {label: "Redundant (removed)", data: [totalRedundant, 0], backgroundColor: "{{ AMBER }}"}
        ]
      },
      options: {indexAxis: "y", responsive: true,
        scales: {x: {stacked: true, ticks:{stepSize:1}}, y: {stacked: true}},
        plugins: {title: {display: true, text: "Deduplication Ratio", font: {size: 15}},
          subtitle: {display: true, text: dedupPct + "% of raw findings were duplicates across agents", font: {size: 11}, color: "{{ TEXT_MUTED }}"},
          legend: {position: "bottom"}}}
    });
  }
  {% endif %}

  // Remediation priority
  {% if remediation %}
  const remed = {{ remediation_json }};
  const priColors = {{ priority_colors_json }};
  if (remed.length) {
    new Chart(document.getElementById("remediationChart"), {
      type: "bar",
      data: {
        labels: remed.map(r => r.label),
        datasets: [{label: "Findings", data: remed.map(r => r.count),
          backgroundColor: remed.map(r => priColors[r.priority] || "#999")}]
      },
      options: {indexAxis: "y", responsive: true,
        plugins: {title: {display: true, text: "Remediation Priority", font: {size: 15}}, legend: {display: false}},
        scales: {x:{ticks:{stepSize:1}}}}
    });
  }
  {% endif %}
})();
</script>

{% if not triage %}
<script>
(function(){
  const container = document.getElementById("findingsContainer");
  const originalHTML = container.innerHTML;
  const sevFilter = document.getElementById("filterSeverity");
  const catFilter = document.getElementById("filterCategory");
  const aiVerdictFilter = document.getElementById("filterAiVerdict");
  const searchInput = document.getElementById("filterSearch");
  const sortSelect = document.getElementById("sortBy");
  const sortOrderBtn = document.getElementById("sortOrder");
  const countLabel = document.getElementById("filterCount");
  let ascending = true;
  let currentSort = sortSelect ? sortSelect.value : "";

  const sevLabels = {5:"CRITICAL",4:"HIGH",3:"MEDIUM",2:"LOW",1:"INFO"};
  const sevColors = {{ sev_colors_json }};
  const catLabels = {"security":"Security","project":"Project Consistency",
    "code_quality":"Code Quality","documentation":"Documentation",
    "dependencies":"Dependencies","pr_comments":"PR Comments"};

  function getFindings() {
    return container.querySelectorAll(".finding[data-finding-id]");
  }

  function getTotalCount() {
    return getFindings().length;
  }

  function updateCount() {
    const findings = getFindings();
    const total = findings.length;
    const visible = Array.from(findings).filter(f => f.style.display !== "none").length;
    if (countLabel) countLabel.textContent = visible < total
      ? "Showing " + visible + " of " + total + " findings"
      : total + " findings";
  }

  function applyFilters() {
    const findings = getFindings();
    const sv = sevFilter ? sevFilter.value : "";
    const ct = catFilter ? catFilter.value : "";
    const av = aiVerdictFilter ? aiVerdictFilter.value : "";
    const q = searchInput ? searchInput.value.toLowerCase() : "";
    findings.forEach(f => {
      let show = true;
      if (sv && f.dataset.severity !== sv) show = false;
      if (ct && f.dataset.category !== ct) show = false;
      if (av && f.dataset.aiVerdict !== av) show = false;
      if (q && !f.textContent.toLowerCase().includes(q)) show = false;
      f.style.display = show ? "" : "none";
    });
    // Hide entire section when all its findings are filtered out
    container.querySelectorAll(".findings-section").forEach(sec => {
      const children = sec.querySelectorAll(".finding[data-finding-id]");
      if (children.length === 0) return;
      const allHidden = Array.from(children).every(c => c.style.display === "none");
      sec.style.display = allHidden ? "none" : "";
    });
    updateCount();
  }

  function buildSection(title, findingEls, color) {
    const sec = document.createElement("div");
    sec.className = "findings-section";
    const h2 = document.createElement("h2");
    h2.textContent = title;
    if (color) h2.style.borderBottomColor = color;
    sec.appendChild(h2);
    const det = document.createElement("details");
    det.open = true;
    const sum = document.createElement("summary");
    sum.textContent = findingEls.length + " finding" + (findingEls.length !== 1 ? "s" : "");
    det.appendChild(sum);
    findingEls.forEach(f => det.appendChild(f));
    sec.appendChild(det);
    return sec;
  }

  function rebuildView() {
    const key = currentSort;
    // Collect all finding elements before rebuilding
    const allFindings = Array.from(getFindings());

    if (!key || key === "category") {
      // Restore original category-based layout
      container.innerHTML = originalHTML;
      applyFilters();
      return;
    }

    const dir = ascending ? 1 : -1;

    if (key === "overall") {
      // Sort by overall_severity (float), absent values (NaN) sink to bottom.
      // Group by integer severity band so the existing bucket layout is preserved.
      const withOverall = allFindings.map(f => {
        const v = parseFloat(f.dataset.overall);
        return {el: f, v: isNaN(v) ? -1 : v};
      });
      // Descending by overall when ascending=true (CRITICAL first), like the
      // severity branch above — the toggle inverts.
      const sign = ascending ? -1 : 1;
      withOverall.sort((a, b) => sign * (a.v - b.v));
      // Re-bucket by severity band for the secondary visual axis.
      const sevNums = [5,4,3,2,1];
      const groups = new Map();
      sevNums.forEach(n => groups.set(n, []));
      withOverall.forEach(({el}) => {
        const n = parseInt(el.dataset.severity, 10) || 1;
        if (!groups.has(n)) groups.set(n, []);
        groups.get(n).push(el);
      });
      container.innerHTML = "";
      const order = ascending ? sevNums : [...sevNums].reverse();
      order.forEach(num => {
        const items = groups.get(num);
        const label = sevLabels[num] || "UNKNOWN";
        if (items && items.length > 0) {
          container.appendChild(buildSection(label, items, sevColors[label]));
        }
      });
    } else if (key === "severity") {
      // Group by numeric severity, ordered descending (5=CRITICAL first)
      const sevNums = [5,4,3,2,1];
      const groups = new Map();
      sevNums.forEach(n => groups.set(n, []));
      allFindings.forEach(f => {
        const n = parseInt(f.dataset.severity, 10) || 1;
        if (!groups.has(n)) groups.set(n, []);
        groups.get(n).push(f);
      });
      container.innerHTML = "";
      const order = ascending ? sevNums : [...sevNums].reverse();
      order.forEach(num => {
        const items = groups.get(num);
        const label = sevLabels[num] || "UNKNOWN";
        if (items && items.length > 0) {
          container.appendChild(buildSection(label, items, sevColors[label]));
        }
      });
    } else if (key === "id") {
      // Flat list sorted by ID
      allFindings.sort((a, b) => a.dataset.findingId.localeCompare(b.dataset.findingId) * dir);
      container.innerHTML = "";
      container.appendChild(buildSection("All Findings (by ID)", allFindings));
    }

    applyFilters();
  }

  if (sevFilter) sevFilter.addEventListener("change", applyFilters);
  if (catFilter) catFilter.addEventListener("change", applyFilters);
  if (aiVerdictFilter) aiVerdictFilter.addEventListener("change", applyFilters);
  if (searchInput) searchInput.addEventListener("input", applyFilters);
  if (sortSelect) sortSelect.addEventListener("change", () => {
    currentSort = sortSelect.value;
    rebuildView();
  });
  if (sortOrderBtn) sortOrderBtn.addEventListener("click", () => {
    ascending = !ascending;
    sortOrderBtn.innerHTML = ascending ? "&#9650;" : "&#9660;";
    sortOrderBtn.title = ascending ? "Ascending (click to reverse)" : "Descending (click to reverse)";
    rebuildView();
  });

  // Apply the default sort (Overall Severity) on load so the page reflects
  // the dropdown's initial selection.
  if (currentSort) rebuildView();
  updateCount();
})();
</script>
{% endif %}

{% block extra_js %}{% endblock %}
</body>
</html>
"""

_TRIAGE_EXTRA_CSS = """
/* Triage controls */
.triage-toolbar{background:{{ BG_LIGHT }};border:1px solid {{ BORDER }};border-radius:6px;
  padding:.8rem;margin:1rem 0;display:flex;flex-wrap:wrap;gap:.5rem;align-items:center}
.triage-toolbar select,.triage-toolbar input[type=text]{
  padding:4px 8px;border:1px solid {{ BORDER }};border-radius:4px;font-size:.85rem}
.triage-toolbar button{padding:4px 12px;border:none;border-radius:4px;cursor:pointer;
  font-size:.85rem;background:{{ ACCENT }};color:#fff}
.triage-toolbar button:hover{opacity:.85}
.triage-row{display:flex;gap:.5rem;align-items:center;margin-top:.5rem;flex-wrap:wrap}
.triage-row select,.triage-row input[type=text]{
  padding:3px 6px;border:1px solid {{ BORDER }};border-radius:4px;font-size:.82rem}
.triage-row select{width:auto;max-width:140px;flex-shrink:0}
.triage-row input[type=text]{flex:1;min-width:200px}
.toast{position:fixed;top:0;left:0;width:100%;padding:1rem 3rem 1rem 1.5rem;color:#fff;
  font-size:.95rem;z-index:9999;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,.2);
  transform:translateY(-100%);transition:transform .3s ease}
.toast.show{transform:translateY(0)}
.toast-ok{background:{{ GREEN }}}
.toast-err{background:{{ RED }}}
.toast .toast-dismiss{position:absolute;right:1rem;top:50%;transform:translateY(-50%);
  background:none;border:none;color:#fff;font-size:1.3rem;cursor:pointer;opacity:.8;
  line-height:1;padding:0 .3rem}
.toast .toast-dismiss:hover{opacity:1}
#submitBtn,#submitBtnBottom,#submitBtnEnd{display:none}
/* Decision explanation hints */
.decision-hint{width:100%;font-size:.78rem;line-height:1.35;color:{{ TEXT_MUTED }};
  max-height:0;overflow:hidden;opacity:0;
  transition:max-height .2s ease,opacity .15s ease}
.decision-hint.visible{max-height:3rem;opacity:1}
.decision-hint[data-action="fix"]{color:{{ ACCENT }}}
.decision-hint[data-action="accept_risk"]{color:{{ AMBER }}}
.decision-hint[data-action="defer"]{color:{{ TEXT_MUTED }}}
.decision-hint[data-action="false_positive"]{color:{{ GREEN }}}
.decision-hint[data-action="duplicate"]{color:{{ GREEN }}}
"""

_TRIAGE_EXTRA_JS = r"""
<script>
(function(){
  const findings = document.querySelectorAll(".finding[data-finding-id]");
  const topSelects = document.querySelectorAll(".triage-action-top[data-finding-id]");

  // Build finding-id → detail-select map for synchronization
  const detailMap = {};
  findings.forEach(f => {
    const sel = f.querySelector(".triage-action");
    if (sel) detailMap[f.dataset.findingId] = sel;
  });
  const topMap = {};
  topSelects.forEach(sel => { topMap[sel.dataset.findingId] = sel; });

  // Decision explanation hints
  const DECISION_HINTS = {
    "fix":            "Claude will apply the recommended fix to the code.",
    "accept_risk":    "Adds INTENTIONAL comment to code. Future reviews downgrade to INFO.",
    "defer":          "Adds TODO comment to code. Issue postponed for later.",
    "false_positive": "Finding dismissed \u2014 no code changes.",
    "duplicate":      "Dismissed as already reported \u2014 no code changes."
  };
  function updateHint(selectEl) {
    const row = selectEl.closest(".triage-row");
    const hint = row ? row.querySelector(".decision-hint") : null;
    if (!hint) return;
    const text = DECISION_HINTS[selectEl.value] || "";
    hint.textContent = text;
    hint.setAttribute("data-action", selectEl.value);
    hint.classList.toggle("visible", !!text);
  }

  // Synchronize: top → detail and detail → top
  topSelects.forEach(sel => {
    sel.addEventListener("change", () => {
      const d = detailMap[sel.dataset.findingId];
      if (d) { d.value = sel.value; updateHint(d); }
    });
  });
  findings.forEach(f => {
    const sel = f.querySelector(".triage-action");
    if (sel) {
      sel.addEventListener("change", () => {
        const t = topMap[f.dataset.findingId];
        if (t) t.value = sel.value;
        updateHint(sel);
      });
      updateHint(sel); // init on page load
    }
  });

  // Filter + search + sort
  const sevFilter = document.getElementById("filterSeverity");
  const catFilter = document.getElementById("filterCategory");
  const verdictFilter = document.getElementById("verdictFilter");
  const aiVerdictFilter = document.getElementById("filterAiVerdict");
  const searchInput = document.getElementById("filterSearch");
  const sortSelect = document.getElementById("sortBy");

  function applyFilters() {
    const sv = sevFilter.value, ct = catFilter.value, q = searchInput.value.toLowerCase();
    const vd = verdictFilter ? verdictFilter.value : "";
    const av = aiVerdictFilter ? aiVerdictFilter.value : "";
    findings.forEach(f => {
      let show = true;
      if (sv && f.dataset.severity !== sv) show = false;
      if (ct && f.dataset.category !== ct) show = false;
      if (vd && f.dataset.verdict !== vd) show = false;
      if (av && f.dataset.aiVerdict !== av) show = false;
      if (q && !f.textContent.toLowerCase().includes(q)) show = false;
      f.style.display = show ? "" : "none";
    });
  }

  function applySort() {
    const key = sortSelect.value;
    const arr = Array.from(findings);
    arr.sort((a, b) => {
      if (key === "overall") {
        const av = parseFloat(a.dataset.overall);
        const bv = parseFloat(b.dataset.overall);
        return (isNaN(bv) ? -1 : bv) - (isNaN(av) ? -1 : av);
      }
      if (key === "severity") return (parseInt(b.dataset.severity,10)||0) - (parseInt(a.dataset.severity,10)||0);
      if (key === "id") return a.dataset.findingId.localeCompare(b.dataset.findingId);
      if (key === "category") return (a.dataset.category||"").localeCompare(b.dataset.category||"");
      return 0;
    });
    arr.forEach(el => el.parentNode.appendChild(el));
  }

  if (sevFilter) sevFilter.addEventListener("change", applyFilters);
  if (catFilter) catFilter.addEventListener("change", applyFilters);
  if (verdictFilter) verdictFilter.addEventListener("change", applyFilters);
  if (aiVerdictFilter) aiVerdictFilter.addEventListener("change", applyFilters);
  if (searchInput) searchInput.addEventListener("input", applyFilters);
  if (sortSelect) sortSelect.addEventListener("change", () => { applySort(); applyFilters(); });

  // Bulk action — applies to all visible findings (no checkboxes)
  const bulkAction = document.getElementById("bulkAction");
  const bulkApply = document.getElementById("bulkApply");
  if (bulkApply) bulkApply.addEventListener("click", () => {
    const action = bulkAction.value;
    if (action === "---") return;
    findings.forEach(f => {
      if (f.style.display === "none") return;
      const sel = f.querySelector(".triage-action");
      if (sel) {
        sel.value = action;
        updateHint(sel);
        // Sync to top table
        const t = topMap[f.dataset.findingId];
        if (t) t.value = action;
      }
    });
  });

  // Collect decisions helper
  function collectDecisions() {
    const decisions = [];
    findings.forEach(f => {
      const action = (f.querySelector(".triage-action") || {}).value;
      const rationale = (f.querySelector(".triage-rationale") || {}).value || "";
      if (action && action !== "---") {
        decisions.push({finding_id: f.dataset.findingId, action, rationale});
      }
    });
    return decisions;
  }

  // Export decisions (download JSON)
  function doExport() {
    const decisions = collectDecisions();
    const payload = {
      report: document.title,
      triaged_at: new Date().toISOString(),
      decisions
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], {type: "application/json"});
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "triage-decisions.json";
    a.click();
    URL.revokeObjectURL(a.href);
  }
  document.querySelectorAll("#exportDecisions, #exportDecisionsBottom, #exportDecisionsEnd").forEach(
    btn => { if (btn) btn.addEventListener("click", doExport); }
  );

  // Submit to server — buttons hidden by CSS, shown only when served by triage_server.py
  const isServer = typeof window.TRIAGE_SERVER !== "undefined" && window.TRIAGE_SERVER;
  document.querySelectorAll("#submitBtn, #submitBtnBottom, #submitBtnEnd").forEach(btn => {
    if (!btn) return;
    if (isServer) btn.style.display = "inline-block";
    btn.addEventListener("click", doSubmit);
  });

  async function doSubmit() {
    const decisions = collectDecisions();
    const payload = {
      report: document.title,
      triaged_at: new Date().toISOString(),
      complete: true,
      decisions
    };
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 15000);
    try {
      const resp = await fetch("/api/decisions", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload),
        signal: ctrl.signal
      });
      clearTimeout(timer);
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      showToast("\u2705 Decisions submitted \u2014 server shutting down.", "ok");
    } catch (e) {
      clearTimeout(timer);
      const msg = e.name === "AbortError" ? "Request timed out" : e.message;
      showToast("\u274c Error: " + msg, "err");
    }
  }

  function showToast(msg, kind) {
    document.querySelectorAll(".toast").forEach(el => el.remove());
    const t = document.createElement("div");
    t.className = "toast toast-" + kind;
    t.textContent = msg;
    const btn = document.createElement("button");
    btn.className = "toast-dismiss";
    btn.innerHTML = "\u00d7";
    btn.onclick = () => { t.classList.remove("show"); setTimeout(() => t.remove(), 300); };
    t.appendChild(btn);
    document.body.appendChild(t);
    requestAnimationFrame(() => requestAnimationFrame(() => t.classList.add("show")));
  }

  // Default sort: overall severity (CRITICAL first); sortSelect's `selected`
  // option drives it — applySort once on load mirrors the dropdown's state.
  if (sortSelect) applySort();
})();
</script>
"""


def _build_html_context(
    data: dict[str, Any], *, triage: bool = False
) -> dict[str, Any]:
    """Build the Jinja2 template context from report data.

    Pre-computes per-finding ``_verdict_chip_bg`` (verdict→hex blend) and
    ``_severity_tooltip`` so the Jinja template stays declarative — it can
    reference both as plain attributes rather than calling Python helpers
    inline.
    """
    import copy as _copy

    meta = _meta(data)
    stats = data.get("summary_statistics", {})

    findings_sections = _copy.deepcopy(data.get("findings", []))
    for sec in findings_sections:
        for f in sec.get("findings", []):
            if f.get("ai_verdict"):
                f["_verdict_chip_bg"] = _verdict_color(
                    f["ai_verdict"], f.get("ai_verdict_confidence")
                )
            tip = _severity_tooltip(f)
            if tip:
                f["_severity_tooltip"] = tip

    if triage:
        # Flatten all findings into a single list sorted by overall_severity
        # (float) when present, falling back to integer severity.
        all_findings = []
        for sec in findings_sections:
            for f in sec.get("findings", []):
                all_findings.append(f)
        all_findings.sort(
            key=lambda f: (
                (
                    f.get("overall_severity")
                    if isinstance(f.get("overall_severity"), (int, float))
                    else -1.0
                ),
                f.get("severity", 1),
            ),
            reverse=True,
        )
        findings_sections = [
            {
                "title": "All Findings (by severity)",
                "subtitle": "Ordered from most to least critical",
                "category": "all",
                "findings": all_findings,
                "positives": None,
            }
        ]

    return {
        "report_type": meta.get("report_type", "code_review"),
        "scope": meta.get("scope", meta.get("project", "Review")),
        "meta": meta,
        "executive_summary": data.get("executive_summary", {}),
        "stats": stats,
        "matrix": stats.get("severity_category_matrix", []),
        "top_findings": data.get("top_findings", []),
        "findings": findings_sections,
        "dependencies": data.get("dependencies", []),
        "agent_stats": data.get("agent_stats", []),
        "remediation": data.get("remediation", []),
        # Color variables for CSS
        "BRAND": BRAND,
        "ACCENT": ACCENT,
        "BG_WHITE": BG_WHITE,
        "TEXT_DARK": TEXT_DARK,
        "TEXT_SECONDARY": TEXT_SECONDARY,
        "TEXT_MUTED": TEXT_MUTED,
        "BG_LIGHT": BG_LIGHT,
        "BORDER": BORDER,
        "GREEN": GREEN,
        "AMBER": AMBER,
        "RED": RED,
        "SEV_CRITICAL": SEV_COLORS["CRITICAL"],
        "SEV_HIGH": SEV_COLORS["HIGH"],
        "SEV_MEDIUM": SEV_COLORS["MEDIUM"],
        "SEV_LOW": SEV_COLORS["LOW"],
        "SEV_INFO": SEV_COLORS["INFO"],
        "PRI_BEFORE_MERGE": PRIORITY_COLORS["before_merge"],
        "PRI_BEFORE_PROD": PRIORITY_COLORS["before_production"],
        "PRI_POST_DEPLOY": PRIORITY_COLORS["post_deployment"],
        # JSON for charts (escape </ to prevent </script> injection)
        "sev_colors_json": json.dumps(SEV_COLORS).replace("</", r"<\/"),
        "sev_counts_json": json.dumps(stats.get("severity_counts", {})).replace(
            "</", r"<\/"
        ),
        "sev_order_json": json.dumps(SEV_ORDER).replace("</", r"<\/"),
        "matrix_json": json.dumps(stats.get("severity_category_matrix", [])).replace(
            "</", r"<\/"
        ),
        "agent_stats_json": json.dumps(data.get("agent_stats", [])).replace(
            "</", r"<\/"
        ),
        "remediation_json": json.dumps(data.get("remediation", [])).replace(
            "</", r"<\/"
        ),
        "priority_colors_json": json.dumps(PRIORITY_COLORS).replace("</", r"<\/"),
        "verdict_colors": {"RESOLVED": GREEN, "UNRESOLVED": RED},
        "triage": triage,
    }


def _mark_safe_values(ctx: dict[str, Any]) -> None:
    """Mark pre-serialized JSON and CSS color constants as safe for Jinja2 autoescape."""
    from markupsafe import Markup

    # CSS color constants (hex values like #1B4F72) — safe for style attributes
    safe_keys = {
        "BRAND",
        "ACCENT",
        "BG_WHITE",
        "TEXT_DARK",
        "TEXT_SECONDARY",
        "TEXT_MUTED",
        "BG_LIGHT",
        "BORDER",
        "GREEN",
        "AMBER",
        "RED",
        "SEV_CRITICAL",
        "SEV_HIGH",
        "SEV_MEDIUM",
        "SEV_LOW",
        "SEV_INFO",
        "PRI_BEFORE_MERGE",
        "PRI_BEFORE_PROD",
        "PRI_POST_DEPLOY",
    }
    # Pre-serialized JSON for Chart.js (escaped via json.dumps, safe for <script>)
    json_keys = {
        "sev_colors_json",
        "sev_counts_json",
        "sev_order_json",
        "matrix_json",
        "agent_stats_json",
        "remediation_json",
        "priority_colors_json",
    }
    for key in safe_keys | json_keys:
        if key in ctx and isinstance(ctx[key], str):
            ctx[key] = Markup(ctx[key])


def render_html(data: dict[str, Any]) -> str:
    """Render the report as a self-contained HTML string."""
    from jinja2 import Environment

    env = Environment(autoescape=True)
    env.filters["sev_label"] = sev_label
    env.filters["markdown"] = render_markdown_to_html
    template = env.from_string(_HTML_TEMPLATE)
    ctx = _build_html_context(data, triage=False)
    _mark_safe_values(ctx)
    return template.render(**ctx)


def render_triage(data: dict[str, Any]) -> str:
    """Render the report as an interactive triage HTML page."""
    from jinja2 import Environment

    # Build a triage-augmented template by injecting extra CSS and JS blocks.
    # The base template already provides data attributes on findings and a
    # filter toolbar (hidden when triage=True via {% if not triage %}).
    # Here we add triage-specific CSS, JS, controls, and the triage toolbar.
    triage_template = _HTML_TEMPLATE.replace(
        "{% block extra_css %}{% endblock %}",
        _TRIAGE_EXTRA_CSS,
    ).replace(
        "{% block extra_js %}{% endblock %}",
        _TRIAGE_EXTRA_JS,
    )

    # Add comment-check `data-verdict` attribute. The base template already
    # carries data-overall and data-ai-verdict; the triage filter for the
    # comment-check `verdict` (RESOLVED/UNRESOLVED) lives only on triage pages.
    old_finding_div = " data-ai-verdict=\"{{ f.ai_verdict | default('', true) }}\">"
    new_finding_div = (
        " data-ai-verdict=\"{{ f.ai_verdict | default('', true) }}\""
        " data-verdict=\"{{ f.verdict | default('', true) }}\">"
    )
    triage_template = triage_template.replace(old_finding_div, new_finding_div)
    assert (
        new_finding_div in triage_template
    ), "Template patch failed: finding div not found in triage template"

    # Add triage row after each finding's </dl>
    old_dl_close = "  </dl>\n</div>\n{% endfor %}"
    new_dl_close = (
        "  </dl>\n"
        '  <div class="triage-row">\n'
        '    <select class="triage-action">\n'
        '      <option value="---">---</option>\n'
        '      <option value="fix">Fix</option>\n'
        '      <option value="accept_risk">Accept Risk</option>\n'
        '      <option value="defer">Defer</option>\n'
        '      <option value="false_positive">False Positive</option>\n'
        '      <option value="duplicate">Duplicate</option>\n'
        "    </select>\n"
        '    <input type="text" class="triage-rationale" placeholder="Rationale...">\n'
        '    <span class="decision-hint" aria-live="polite"></span>\n'
        "  </div>\n"
        "</div>\n{% endfor %}"
    )
    triage_template = triage_template.replace(old_dl_close, new_dl_close)

    # Add triage toolbar before the first section heading.
    # The base report toolbar is hidden ({% if not triage %}), so we inject
    # the triage-specific toolbar with bulk actions, verdict filter, etc.
    toolbar_html = """
<div class="triage-toolbar no-print" id="triageToolbar">
  <select id="bulkAction">
    <option value="---">Bulk Action (all visible)</option>
    <option value="fix">Fix</option>
    <option value="accept_risk">Accept Risk</option>
    <option value="defer">Defer</option>
    <option value="false_positive">False Positive</option>
    <option value="duplicate">Duplicate</option>
  </select>
  <button id="bulkApply">Apply to All Visible</button>
  <select id="filterSeverity">
    <option value="">All Severities</option>
    <option value="5">CRITICAL</option>
    <option value="4">HIGH</option>
    <option value="3">MEDIUM</option>
    <option value="2">LOW</option>
    <option value="1">INFO</option>
  </select>
  <select id="filterCategory">
    <option value="">All Categories</option>
    <option value="security">Security</option>
    <option value="project">Project</option>
    <option value="code_quality">Code Quality</option>
    <option value="documentation">Documentation</option>
    <option value="dependencies">Dependencies</option>
    <option value="pr_comments">PR Comments</option>
  </select>
  {% if report_type == "comment_check" %}
  <select id="verdictFilter">
    <option value="">All Verdicts</option>
    <option value="RESOLVED">Resolved</option>
    <option value="UNRESOLVED">Unresolved</option>
  </select>
  {% endif %}
  <select id="filterAiVerdict">
    <option value="">All AI Verdicts</option>
    <option value="valid">Valid</option>
    <option value="false_positive">False Positive</option>
    <option value="needs_investigation">Needs Investigation</option>
    <option value="out_of_scope">Out of Scope</option>
    <option value="duplicate">Duplicate</option>
  </select>
  <input type="text" id="filterSearch" placeholder="Search findings...">
  <select id="sortBy">
    <option value="overall" selected>Overall Severity</option>
    <option value="severity">Severity (band)</option>
    <option value="id">ID</option>
    <option value="category">Category</option>
  </select>
</div>
<div style="margin:1rem 0">
  <button id="exportDecisions" class="no-print" style="padding:6px 16px;background:{{ ACCENT }};color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:.9rem">Export Decisions</button>
  <button id="submitBtn" class="no-print" style="padding:6px 16px;background:{{ BRAND }};color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:.9rem;margin-left:.5rem">Submit to Server</button>
</div>
"""
    # Insert toolbar inside the findings section, after the heading
    triage_template = triage_template.replace(
        "{% if sec.subtitle %}<p><em>{{ sec.subtitle }}</em></p>{% endif %}",
        "{% if sec.subtitle %}<p><em>{{ sec.subtitle }}</em></p>{% endif %}\n"
        "{% if loop.first %}\n" + toolbar_html + "{% endif %}",
    )

    env = Environment(autoescape=True)
    env.filters["sev_label"] = sev_label
    env.filters["markdown"] = render_markdown_to_html
    template = env.from_string(triage_template)
    ctx = _build_html_context(data, triage=True)
    _mark_safe_values(ctx)
    return template.render(**ctx)


# ===================================================================
# FORMAT: PDF
# ===================================================================
# ---------------------------------------------------------------------------
# PDF font registration (Unicode support)
# ---------------------------------------------------------------------------

# System search paths for a Unicode-capable sans-serif TTF and its bold/mono
# siblings. The first tuple whose ``regular`` exists wins; missing siblings
# fall back to ``regular`` (so bold/mono Markdown still renders, just without
# weight/family contrast).
_FONT_CANDIDATES: list[dict[str, str]] = [
    {
        "regular": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "bold": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "italic": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
        "boldItalic": "/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf",
        "mono": "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "monoBold": "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    },
    {
        "regular": "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "bold": "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        "italic": "/usr/share/fonts/truetype/noto/NotoSans-Italic.ttf",
        "boldItalic": "/usr/share/fonts/truetype/noto/NotoSans-BoldItalic.ttf",
        "mono": "/usr/share/fonts/truetype/noto/NotoSansMono-Regular.ttf",
        "monoBold": "/usr/share/fonts/truetype/noto/NotoSansMono-Bold.ttf",
    },
]


def _bundled_font_dir() -> Path:
    """Return the optional bundled-font directory next to this script."""
    return Path(__file__).resolve().parent / "fonts"


def _resolve_font_set() -> dict[str, str] | None:
    """Pick the first available font set.

    Order:
      1. ``$CLAUDIUS_PDF_FONT`` (a single regular TTF). Sibling ``-Bold``,
         ``-Oblique``, and ``-BoldOblique`` ``.ttf`` files in the same
         directory are picked up automatically when present; the monospace
         slot reuses the regular face.
      2. An optional user-supplied font dropped at
         ``scripts/fonts/DejaVuSans*.ttf`` (not shipped with the plugin).
      3. Common Linux system locations (DejaVu, Noto Sans).

    Returns ``None`` if no usable regular TTF is found.
    """
    import os

    override = os.environ.get("CLAUDIUS_PDF_FONT")
    if override:
        regular = Path(override)
        if regular.is_file() and regular.suffix.lower() == ".ttf":
            stem = regular.stem
            parent = regular.parent

            def _sibling(suffix: str) -> str:
                cand = parent / f"{stem}{suffix}.ttf"
                return str(cand) if cand.is_file() else str(regular)

            return {
                "regular": str(regular),
                "bold": _sibling("-Bold"),
                "italic": _sibling("-Oblique"),
                "boldItalic": _sibling("-BoldOblique"),
                "mono": str(regular),
                "monoBold": _sibling("-Bold"),
            }
        if not regular.is_file():
            log.warning("CLAUDIUS_PDF_FONT=%s is not a readable file", override)
        else:
            log.warning(
                "CLAUDIUS_PDF_FONT=%s is not a .ttf file (only TrueType is supported)",
                override,
            )

    bundled = _bundled_font_dir()
    bundled_regular = bundled / "DejaVuSans.ttf"
    if bundled_regular.is_file():

        def _b(name: str) -> str:
            cand = bundled / name
            return str(cand) if cand.is_file() else str(bundled_regular)

        return {
            "regular": str(bundled_regular),
            "bold": _b("DejaVuSans-Bold.ttf"),
            "italic": _b("DejaVuSans-Oblique.ttf"),
            "boldItalic": _b("DejaVuSans-BoldOblique.ttf"),
            "mono": _b("DejaVuSansMono.ttf"),
            "monoBold": _b("DejaVuSansMono-Bold.ttf"),
        }

    for cand in _FONT_CANDIDATES:
        regular = Path(cand["regular"])
        if regular.is_file():
            resolved = {"regular": str(regular)}
            for key in ("bold", "italic", "boldItalic", "mono", "monoBold"):
                p = Path(cand[key])
                resolved[key] = str(p) if p.is_file() else str(regular)
            return resolved
    return None


def _register_pdf_fonts() -> dict[str, str]:
    """Register a Unicode font family with ReportLab.

    Returns a mapping with keys ``regular``, ``bold``, ``italic``,
    ``boldItalic``, ``mono``, ``monoBold`` whose values are the ReportLab
    font names callers should use. On failure the mapping points back at
    Helvetica/Courier core fonts (Latin-1 only).
    """
    global _RL_MONO_FONT
    helvetica = {
        "regular": "Helvetica",
        "bold": "Helvetica-Bold",
        "italic": "Helvetica-Oblique",
        "boldItalic": "Helvetica-BoldOblique",
        "mono": "Courier",
        "monoBold": "Courier-Bold",
    }
    fonts = _resolve_font_set()
    if fonts is None:
        log.warning(
            "Unicode font not available; emoji/CJK/Arabic will render as tofu "
            "boxes in PDF output. Set CLAUDIUS_PDF_FONT to a TTF path or "
            "install fonts-dejavu / fonts-noto."
        )
        _RL_MONO_FONT = "Courier"
        return helvetica
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        regular_name = "ClaudiusSans"
        bold_name = "ClaudiusSans-Bold"
        italic_name = "ClaudiusSans-Italic"
        boldit_name = "ClaudiusSans-BoldItalic"
        mono_name = "ClaudiusMono"
        mono_bold_name = "ClaudiusMono-Bold"

        pdfmetrics.registerFont(TTFont(regular_name, fonts["regular"]))
        pdfmetrics.registerFont(TTFont(bold_name, fonts["bold"]))
        pdfmetrics.registerFont(TTFont(italic_name, fonts["italic"]))
        pdfmetrics.registerFont(TTFont(boldit_name, fonts["boldItalic"]))
        pdfmetrics.registerFont(TTFont(mono_name, fonts["mono"]))
        pdfmetrics.registerFont(TTFont(mono_bold_name, fonts["monoBold"]))
        pdfmetrics.registerFontFamily(
            regular_name,
            normal=regular_name,
            bold=bold_name,
            italic=italic_name,
            boldItalic=boldit_name,
        )
        pdfmetrics.registerFontFamily(
            mono_name,
            normal=mono_name,
            bold=mono_bold_name,
            italic=mono_name,
            boldItalic=mono_bold_name,
        )
        log.info("Registered Unicode PDF font: %s", fonts["regular"])
        _RL_MONO_FONT = mono_name
        return {
            "regular": regular_name,
            "bold": bold_name,
            "italic": italic_name,
            "boldItalic": boldit_name,
            "mono": mono_name,
            "monoBold": mono_bold_name,
        }
    except (
        Exception
    ) as exc:  # noqa: BLE001 -- font failure must not crash PDF rendering
        log.warning(
            "Failed to register Unicode font %s (%s: %s); falling back to Helvetica",
            fonts.get("regular"),
            type(exc).__name__,
            exc,
        )
        _RL_MONO_FONT = "Courier"
        return helvetica


def _configure_matplotlib_font(matplotlib: Any) -> None:
    """Point matplotlib's default sans-serif family at the resolved Unicode TTF.

    Matplotlib renders the PDF charts with its own font stack, independent of
    ReportLab's registered fonts. Without this, user-controlled chart labels
    (e.g. agent names in ``agent_stats``) containing non-Latin scripts render
    as tofu boxes even though body text renders correctly. Best-effort: a
    failure here only affects chart glyphs, so it never raises.
    """
    fonts = _resolve_font_set()
    if fonts is None:
        return
    try:
        from matplotlib import font_manager

        font_manager.fontManager.addfont(fonts["regular"])
        family = font_manager.FontProperties(fname=fonts["regular"]).get_name()
        matplotlib.rcParams["font.family"] = "sans-serif"
        matplotlib.rcParams["font.sans-serif"] = [family] + list(
            matplotlib.rcParams.get("font.sans-serif", [])
        )
    except Exception as exc:  # noqa: BLE001 -- chart font is cosmetic, never fatal
        log.warning(
            "Failed to configure matplotlib Unicode font %s (%s: %s); "
            "chart labels may render non-Latin scripts as tofu",
            fonts.get("regular"),
            type(exc).__name__,
            exc,
        )


def render_pdf(data: dict[str, Any], output_path: Path) -> None:
    """Render the report as a PDF using reportlab and matplotlib."""
    import io

    import matplotlib
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker
    import numpy as np
    from reportlab.lib import colors as rl_colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        HRFlowable,
        Image,
        KeepTogether,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    matplotlib.use("Agg")

    # Register Unicode TTF (DejaVu/Noto) — falls back to Helvetica with a
    # warning when no TTF is available. Returned mapping is used everywhere
    # below in place of hardcoded "Helvetica"/"Courier" names.
    F = _register_pdf_fonts()

    # Mirror the Unicode font into matplotlib so chart labels (e.g. agent names
    # from agent_stats) render non-Latin scripts instead of tofu boxes.
    _configure_matplotlib_font(matplotlib)

    # RL color constants
    RL_WHITE = rl_colors.HexColor(BG_WHITE)
    RL_BLACK = rl_colors.HexColor(TEXT_DARK)
    RL_LIGHT = rl_colors.HexColor(BG_LIGHT)
    RL_BORDER = rl_colors.HexColor(BORDER)
    RL_BRAND = rl_colors.HexColor(BRAND)

    PAGE_W, PAGE_H = LETTER
    MARGIN = 0.7 * inch
    CW = PAGE_W - 2 * MARGIN

    # --- Helpers ---
    def _clean(fig: Any, axes: list[Any]) -> None:
        fig.patch.set_facecolor("white")
        for ax in axes:
            ax.set_facecolor("white")
            ax.tick_params(
                colors=TEXT_SECONDARY, labelsize=9, labelcolor=TEXT_SECONDARY
            )
            ax.xaxis.label.set_color(TEXT_SECONDARY)
            ax.yaxis.label.set_color(TEXT_SECONDARY)
            ax.title.set_color(TEXT_DARK)
            for sp in ax.spines.values():
                sp.set_edgecolor(BORDER)

    def _to_img(fig: Any, w: float, h: float) -> Image:
        buf = io.BytesIO()
        fig.savefig(
            buf,
            format="png",
            dpi=180,
            bbox_inches="tight",
            facecolor="white",
            edgecolor="none",
        )
        buf.seek(0)
        plt.close(fig)
        return Image(buf, width=w, height=h)

    def _badge(sev: int | str) -> Paragraph:
        sev = sev_label(sev)
        clr = SEV_COLORS.get(sev, "#7F8C8D")
        st = ParagraphStyle(
            f"B_{sev}",
            fontSize=8,
            textColor="#FFFFFF",
            fontName=F["bold"],
            alignment=TA_CENTER,
            backColor=rl_colors.HexColor(clr),
            borderPadding=(2, 6, 2, 6),
        )
        return Paragraph(sev, st)

    def _hr() -> HRFlowable:
        return HRFlowable(
            width="100%", thickness=0.5, color=RL_BORDER, spaceAfter=8, spaceBefore=4
        )

    def _tbl_style() -> TableStyle:
        return TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), RL_BRAND),
                ("TEXTCOLOR", (0, 0), (-1, 0), rl_colors.white),
                ("FONTNAME", (0, 0), (-1, 0), F["bold"]),
                ("FONTSIZE", (0, 0), (-1, 0), 9),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, 0), 7),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 7),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [RL_WHITE, RL_LIGHT]),
                ("TEXTCOLOR", (0, 1), (-1, -1), RL_BLACK),
                ("FONTSIZE", (0, 1), (-1, -1), 9),
                ("TOPPADDING", (0, 1), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.5, RL_BORDER),
                ("LINEBELOW", (0, 0), (-1, 0), 1.5, RL_BRAND),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )

    # --- Styles ---
    s = {
        "title": ParagraphStyle(
            "T",
            fontSize=20,
            textColor=TEXT_DARK,
            fontName=F["bold"],
            alignment=TA_CENTER,
            spaceAfter=4,
        ),
        "sub": ParagraphStyle(
            "Sub",
            fontSize=10,
            textColor=TEXT_MUTED,
            fontName=F["regular"],
            alignment=TA_CENTER,
            spaceAfter=2,
        ),
        "h2": ParagraphStyle(
            "H2",
            fontSize=14,
            textColor=BRAND,
            fontName=F["bold"],
            spaceBefore=14,
            spaceAfter=6,
        ),
        "h3": ParagraphStyle(
            "H3",
            fontSize=11,
            textColor=TEXT_DARK,
            fontName=F["bold"],
            spaceBefore=10,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "B",
            fontSize=10,
            textColor=TEXT_DARK,
            fontName=F["regular"],
            spaceAfter=6,
            leading=14,
        ),
        "small": ParagraphStyle(
            "Sm",
            fontSize=9,
            textColor=TEXT_SECONDARY,
            fontName=F["regular"],
            spaceAfter=4,
            leading=13,
        ),
        "finding_title": ParagraphStyle(
            "FT",
            fontSize=10,
            textColor=TEXT_DARK,
            fontName=F["bold"],
            spaceBefore=8,
            spaceAfter=2,
        ),
        "finding_body": ParagraphStyle(
            "FB",
            fontSize=9,
            textColor=TEXT_SECONDARY,
            fontName=F["regular"],
            spaceAfter=2,
            leading=13,
            leftIndent=12,
        ),
        "th": ParagraphStyle(
            "TH",
            fontSize=9,
            textColor=rl_colors.white,
            fontName=F["bold"],
            alignment=TA_CENTER,
        ),
        "tc": ParagraphStyle(
            "TC", fontSize=9, textColor=TEXT_DARK, fontName=F["regular"], leading=12
        ),
        "tcc": ParagraphStyle(
            "TCC",
            fontSize=9,
            textColor=TEXT_DARK,
            fontName=F["regular"],
            alignment=TA_CENTER,
            leading=12,
        ),
    }

    # --- Extract data ---
    meta = _meta(data)
    es = data.get("executive_summary", {})
    stats = data.get("summary_statistics", {})
    sev_counts = stats.get("severity_counts", {})
    matrix = stats.get("severity_category_matrix", [])
    top_findings = data.get("top_findings", [])
    deps = data.get("dependencies", [])
    agent_stats = data.get("agent_stats", [])
    remediation = data.get("remediation", [])
    finding_sections = data.get("findings", [])

    project = meta.get("project", "Project")
    date_str = meta.get("date", "N/A")
    num_agents = len(meta.get("reviewers", []))

    # --- Charts ---
    def chart_severity_pie() -> Image | Spacer:
        totals = {sev: sev_counts.get(sev, 0) for sev in SEV_ORDER}
        labels = [f"{sv} ({totals[sv]})" for sv in SEV_ORDER if totals[sv] > 0]
        values = [totals[sv] for sv in SEV_ORDER if totals[sv] > 0]
        clrs = [SEV_COLORS[sv] for sv in SEV_ORDER if totals[sv] > 0]
        if not values:
            return Spacer(1, 0)
        fig, ax = plt.subplots(figsize=(5.5, 3.0))
        _clean(fig, [ax])
        ax.set_aspect("equal")
        wedges, _, _ = ax.pie(
            values,
            autopct="%1.0f%%",
            colors=clrs,
            startangle=140,
            wedgeprops={"linewidth": 2, "edgecolor": "white", "width": 0.6},
            pctdistance=0.76,
            textprops={"fontsize": 9, "fontweight": "bold", "color": "white"},
        )
        ax.legend(
            wedges,
            labels,
            loc="center left",
            bbox_to_anchor=(1.05, 0.5),
            frameon=False,
            fontsize=9,
            labelcolor=TEXT_SECONDARY,
        )
        ax.set_title(
            "Severity Distribution",
            fontsize=13,
            fontweight="bold",
            color=TEXT_DARK,
            pad=10,
        )
        fig.tight_layout()
        return _to_img(fig, CW * 0.85, 2.3 * inch)

    def chart_category_bar() -> Image:
        cats = ["Security", "Code Quality", "Project Consistency"]
        cat_data: dict[str, list[int]] = {}
        for sv in SEV_ORDER:
            for row in matrix:
                if row["severity"] == sv:
                    cat_data[sv] = [
                        row.get("security", 0),
                        row.get("code_quality", 0),
                        row.get("project", 0),
                    ]
                    break
            else:
                cat_data[sv] = [0, 0, 0]
        fig, ax = plt.subplots(figsize=(6.2, 2.2))
        _clean(fig, [ax])
        y = np.arange(len(cats))
        lefts = np.zeros(len(cats))
        for sev_name in SEV_ORDER:
            vals = cat_data[sev_name]
            bars = ax.barh(
                y,
                vals,
                0.5,
                left=lefts,
                color=SEV_COLORS[sev_name],
                edgecolor="white",
                linewidth=1,
            )
            for bar, v in zip(bars, vals):
                if v > 0:
                    ax.text(
                        bar.get_x() + bar.get_width() / 2,
                        bar.get_y() + bar.get_height() / 2,
                        str(v),
                        ha="center",
                        va="center",
                        fontsize=8,
                        color="white",
                        fontweight="bold",
                    )
            lefts += np.array(vals)
        ax.set_yticks(y)
        ax.set_yticklabels(cats, fontsize=10, color=TEXT_DARK)
        ax.set_xlabel("Number of Findings", fontsize=9, color=TEXT_SECONDARY)
        ax.set_title(
            "Findings by Category",
            fontsize=13,
            fontweight="bold",
            color=TEXT_DARK,
            pad=10,
        )
        ax.xaxis.set_major_locator(mticker.MaxNLocator(integer=True))
        ax.grid(axis="x", color=BORDER, linestyle="--", linewidth=0.5, alpha=0.7)
        ax.set_axisbelow(True)
        from matplotlib.patches import Patch

        ax.legend(
            handles=[Patch(facecolor=SEV_COLORS[sv], label=sv) for sv in SEV_ORDER],
            loc="upper right",
            frameon=True,
            fontsize=7,
            ncol=5,
            framealpha=0.9,
            edgecolor=BORDER,
            labelcolor=TEXT_SECONDARY,
        )
        fig.tight_layout()
        return _to_img(fig, CW, 2.0 * inch)

    def chart_agent_bar() -> Image | Spacer:
        if not agent_stats:
            return Spacer(1, 0)
        agents = [a["agent"] for a in agent_stats]
        unique = [a["unique"] for a in agent_stats]
        redundant = [a["redundant"] for a in agent_stats]
        fig, ax = plt.subplots(figsize=(5.2, 2.6))
        _clean(fig, [ax])
        x = np.arange(len(agents))
        w = 0.32
        bu = ax.bar(
            x - w / 2,
            unique,
            w,
            label="Unique",
            color=GREEN,
            edgecolor="white",
            linewidth=1,
        )
        br = ax.bar(
            x + w / 2,
            redundant,
            w,
            label="Redundant",
            color=AMBER,
            edgecolor="white",
            linewidth=1,
        )
        for bar in list(bu) + list(br):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.3,
                str(int(bar.get_height())),
                ha="center",
                va="bottom",
                fontsize=9,
                color=TEXT_SECONDARY,
                fontweight="bold",
            )
        ax.set_xticks(x)
        ax.set_xticklabels(agents, fontsize=10, color=TEXT_DARK)
        ax.set_ylabel("Findings", fontsize=9, color=TEXT_SECONDARY)
        ax.set_title(
            "Agent Performance", fontsize=13, fontweight="bold", color=TEXT_DARK, pad=10
        )
        max_val = max(max(unique), max(redundant)) if unique else 10
        ax.set_ylim(0, max_val + 4)
        ax.yaxis.set_major_locator(mticker.MaxNLocator(integer=True))
        ax.grid(axis="y", color=BORDER, linestyle="--", linewidth=0.5, alpha=0.7)
        ax.set_axisbelow(True)
        ax.legend(frameon=True, fontsize=9, edgecolor=BORDER, labelcolor=TEXT_SECONDARY)
        fig.tight_layout()
        return _to_img(fig, CW * 0.75, 2.2 * inch)

    def chart_gantt() -> Image | Spacer:
        if not remediation:
            return Spacer(1, 0)
        pri_color_map = {
            "before_merge": RED,
            "before_production": AMBER,
            "post_deployment": GREEN,
        }
        fig, ax = plt.subplots(figsize=(5.8, 1.8))
        _clean(fig, [ax])
        for i, r in enumerate(remediation):
            clr = pri_color_map.get(r["priority"], GREEN)
            ax.barh(i, r["count"], 0.5, color=clr, edgecolor="white", linewidth=1)
            ax.text(
                r["count"] + 0.3,
                i,
                str(r["count"]),
                va="center",
                fontsize=9,
                color=TEXT_SECONDARY,
                fontweight="bold",
            )
        ax.set_yticks(range(len(remediation)))
        ax.set_yticklabels(
            [r["label"] for r in remediation], fontsize=10, color=TEXT_DARK
        )
        max_cnt = max(r["count"] for r in remediation)
        ax.set_xlim(0, max_cnt + 6)
        ax.set_xlabel("Items", fontsize=9, color=TEXT_SECONDARY)
        ax.set_title(
            "Remediation Priority",
            fontsize=13,
            fontweight="bold",
            color=TEXT_DARK,
            pad=10,
        )
        ax.xaxis.set_major_locator(mticker.MaxNLocator(integer=True))
        ax.grid(axis="x", color=BORDER, linestyle="--", linewidth=0.5, alpha=0.7)
        ax.set_axisbelow(True)
        fig.tight_layout()
        return _to_img(fig, CW * 0.85, 1.6 * inch)

    # --- Tables ---
    def tbl_summary() -> Table:
        header = [
            Paragraph(h, s["th"])
            for h in ["Severity", "Security", "Project", "Code Quality", "Total"]
        ]
        tbl_data = [header]
        for row in matrix:
            sev = row["severity"]
            tbl_data.append(
                [
                    _badge(sev),
                    Paragraph(str(row.get("security", 0)), s["tcc"]),
                    Paragraph(str(row.get("project", 0)), s["tcc"]),
                    Paragraph(str(row.get("code_quality", 0)), s["tcc"]),
                    Paragraph(f"<b>{row['total']}</b>", s["tcc"]),
                ]
            )
        t = Table(
            tbl_data,
            colWidths=[1.1 * inch, 1.2 * inch, 1.1 * inch, 1.3 * inch, 0.7 * inch],
            repeatRows=1,
        )
        t.setStyle(_tbl_style())
        return t

    def tbl_top5() -> Table | Spacer:
        if not top_findings:
            return Spacer(1, 0)
        header = [
            Paragraph(h, s["th"]) for h in ["ID", "Severity", "Description", "Location"]
        ]
        tbl_data = [header]
        for tf in top_findings:
            loc = tf.get("location", "")
            permalink = tf.get("location_permalink")
            if permalink and permalink.startswith(("https://", "http://")):
                url_escaped = xml_escape(permalink, {chr(34): "&quot;"})
                loc_xml = (
                    f'<a href="{url_escaped}" color="{ACCENT}">{xml_escape(loc)}</a>'
                )
            else:
                loc_xml = f'<font color="{ACCENT}">{xml_escape(loc)}</font>'
            tbl_data.append(
                [
                    Paragraph(tf["id"], s["tcc"]),
                    _badge(tf["severity"]),
                    Paragraph(tf["title"], s["tc"]),
                    Paragraph(loc_xml, s["tc"]),
                ]
            )
        t = Table(
            tbl_data,
            colWidths=[0.8 * inch, 0.85 * inch, 3.0 * inch, 1.75 * inch],
            repeatRows=1,
        )
        t.setStyle(_tbl_style())
        return t

    def tbl_deps() -> Table | Spacer:
        if not deps:
            return Spacer(1, 0)
        header = [
            Paragraph(h, s["th"])
            for h in ["Package", "Version", "Known CVEs", "Applicable?"]
        ]
        tbl_data = [header]
        for d in deps:
            cves = d.get("advisories", "None")
            ok = d.get("ok", True)
            cc = TEXT_SECONDARY if cves == "None" else RED
            ac = GREEN if ok else AMBER
            appl = d.get("applicable", "N/A")
            tbl_data.append(
                [
                    Paragraph(f"<b>{d['package']}</b>", s["tc"]),
                    Paragraph(d["version"], s["tcc"]),
                    Paragraph(f'<font color="{cc}">{cves}</font>', s["tcc"]),
                    Paragraph(f'<font color="{ac}"><b>{appl}</b></font>', s["tcc"]),
                ]
            )
        t = Table(
            tbl_data,
            colWidths=[1.1 * inch, 1.0 * inch, 2.1 * inch, 2.2 * inch],
            repeatRows=1,
        )
        t.setStyle(_tbl_style())
        return t

    # --- KPI boxes ---
    def kpi_boxes() -> Table:
        kpis = [
            (str(stats.get("total_findings", 0)), "Unique Findings", ACCENT),
            (stats.get("redundancy_ratio", "N/A"), "Redundancy Ratio", AMBER),
            (str(stats.get("critical_count", 0)), "Critical - Fix Now", RED),
        ]
        cells = []
        for val, label, clr in kpis:
            vs = ParagraphStyle(
                f"KV_{label}",
                fontSize=28,
                textColor=rl_colors.HexColor(clr),
                fontName=F["bold"],
                alignment=TA_CENTER,
            )
            ls = ParagraphStyle(
                f"KL_{label}",
                fontSize=9,
                textColor=TEXT_MUTED,
                fontName=F["regular"],
                alignment=TA_CENTER,
                spaceBefore=2,
            )
            cells.append([Paragraph(val, vs), Paragraph(label, ls)])
        tbl_data = [[c[0] for c in cells], [c[1] for c in cells]]
        t = Table(tbl_data, colWidths=[CW / 3] * 3)
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), RL_LIGHT),
                    ("TOPPADDING", (0, 0), (-1, -1), 10),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LINEAFTER", (0, 0), (1, -1), 0.5, RL_BORDER),
                    ("BOX", (0, 0), (-1, -1), 0.5, RL_BORDER),
                ]
            )
        )
        return t

    # ParagraphStyles for Markdown blocks rendered inside finding bodies.
    # Sizes mirror _RL_HEADING_SIZES; pre uses the registered mono face with the body's left indent.
    md_heading_styles = {
        kind: ParagraphStyle(
            f"FB_{kind.upper()}",
            fontSize=size,
            textColor=TEXT_DARK,
            fontName=F["bold"],
            spaceBefore=4,
            spaceAfter=2,
            leading=size + 3,
            leftIndent=12,
        )
        for kind, size in _RL_HEADING_SIZES.items()
    }
    md_pre_style = ParagraphStyle(
        "FB_PRE",
        fontSize=8.5,
        textColor=TEXT_DARK,
        fontName=F["mono"],
        backColor=rl_colors.HexColor(BG_LIGHT),
        borderColor=RL_BORDER,
        borderWidth=0.5,
        borderPadding=4,
        spaceAfter=4,
        leading=11,
        leftIndent=12,
    )

    def _md_body(value: str, base_style: ParagraphStyle) -> list[Paragraph]:
        """Render a Markdown long-text field as Paragraphs using ``base_style``.

        Headings and code blocks use the Markdown-specific styles; regular
        prose falls back to ``base_style`` so callers can plug into the
        surrounding section's typography (executive summary uses ``body``).
        """
        blocks = render_markdown_to_reportlab(value)
        if not blocks:
            return []
        out: list[Paragraph] = []
        for kind, body in blocks:
            if kind in md_heading_styles:
                out.append(Paragraph(body, md_heading_styles[kind]))
            elif kind == "pre":
                out.append(Paragraph(body, md_pre_style))
            else:
                out.append(Paragraph(body, base_style))
        return out

    def _md_field(label: str, value: str) -> list[Paragraph]:
        """Render a long-text field (Markdown) as a list of Paragraph flowables.

        The first block is prefixed with ``<b>label:</b><br/>`` so the label
        stays plain while the body renders its Markdown structure. Empty
        values yield a single label-only Paragraph for layout consistency.
        """
        blocks = render_markdown_to_reportlab(value)
        if not blocks:
            return [Paragraph(f"<b>{label}:</b>", s["finding_body"])]
        out: list[Paragraph] = []
        first_kind, first_body = blocks[0]
        first_xml = f"<b>{label}:</b><br/>{first_body}"
        first_style = (
            md_heading_styles[first_kind]
            if first_kind in md_heading_styles
            else md_pre_style if first_kind == "pre" else s["finding_body"]
        )
        out.append(Paragraph(first_xml, first_style))
        for kind, body in blocks[1:]:
            if kind in md_heading_styles:
                out.append(Paragraph(body, md_heading_styles[kind]))
            elif kind == "pre":
                out.append(Paragraph(body, md_pre_style))
            else:
                out.append(Paragraph(body, s["finding_body"]))
        return out

    # --- Finding renderers ---
    from reportlab.platypus import Preformatted

    pre_snippet_style = ParagraphStyle(
        "FB_SNIPPET",
        fontSize=8,
        textColor=TEXT_DARK,
        fontName=F["mono"],
        backColor=rl_colors.HexColor(BG_LIGHT),
        borderColor=RL_BORDER,
        borderWidth=0.5,
        borderPadding=4,
        leading=10,
        leftIndent=12,
    )

    def render_finding(f: dict[str, Any]) -> KeepTogether:
        fid = f["id"]
        sev = sev_label(f["severity"])
        title = f["title"]
        tags = f.get("tags", [])
        loc = f.get("location", "")
        permalink = f.get("location_permalink")
        desc = f["description"]
        impact_desc = f.get("impact_description", "")
        rec = f["recommendation"]
        clr = SEV_COLORS.get(sev, TEXT_MUTED)
        tag_display = (
            f' <font color="{TEXT_MUTED}">- {", ".join(tags)}</font>' if tags else ""
        )
        if permalink and permalink.startswith(("https://", "http://")):
            url_escaped = xml_escape(permalink, {chr(34): "&quot;"})
            loc_xml = f'<a href="{url_escaped}" color="{ACCENT}">{xml_escape(loc)}</a>'
        else:
            loc_xml = f'<font color="{ACCENT}">{xml_escape(loc)}</font>'
        elements: list[Any] = [
            Paragraph(
                f'<font color="{clr}"><b>{fid} ({sev})</b></font>: {title}{tag_display}',
                s["finding_title"],
            ),
        ]
        # Float breakdown line — PDF has no hover, so we surface it inline.
        tip = _severity_tooltip(f)
        if tip:
            elements.append(
                Paragraph(
                    f'<font color="{TEXT_MUTED}">{xml_escape(tip)}</font>',
                    s["small"],
                )
            )
        elements.append(Paragraph(f"<b>Location:</b> {loc_xml}", s["finding_body"]))
        elements.extend(_md_field("Description", desc))
        if impact_desc:
            elements.extend(_md_field("Impact", impact_desc))
        elements.extend(_md_field("Recommendation", rec))
        ai_verdict = f.get("ai_verdict", "")
        if ai_verdict:
            conf = f.get("ai_verdict_confidence")
            chip_bg = _verdict_color(ai_verdict, conf)
            conf_display = f"{conf:.2f}" if isinstance(conf, (int, float)) else "—"
            elements.append(
                Paragraph(
                    f"<b>AI Verdict:</b> "
                    f'<font backColor="{chip_bg}" color="#FFFFFF"><b> {xml_escape(ai_verdict)} </b></font>'
                    f" (confidence: {conf_display})",
                    s["finding_body"],
                )
            )
            if f.get("ai_assessment"):
                elements.extend(_md_field("AI Assessment", f["ai_assessment"]))
        for snip in f.get("code_snippets") or []:
            caption = snip.get("caption") or snip.get("language") or "Code snippet"
            content = snip.get("content", "")
            content, _ = _truncate_snippet(content, 200)
            elements.append(
                Paragraph(f"<b>Code snippet</b>: {xml_escape(caption)}", s["small"])
            )
            # Preformatted handles escaping internally and preserves newlines.
            elements.append(Preformatted(content, pre_snippet_style))
        verdict = f.get("verdict", "")
        if verdict:
            v_clr = GREEN if verdict == "RESOLVED" else RED
            elements.append(
                Paragraph(
                    f'<b>Verdict:</b> <font color="{v_clr}"><b>{xml_escape(verdict)}</b></font>',
                    s["finding_body"],
                )
            )
        reviewer = f.get("reviewer", "")
        if reviewer:
            comment_url = f.get("comment_url", "")
            if comment_url and comment_url.startswith(("https://", "http://")):
                elements.append(
                    Paragraph(
                        f'<b>Reviewer:</b> <a href="{xml_escape(comment_url, {chr(34): "&quot;"})}" color="{ACCENT}">{xml_escape(reviewer)}</a>',
                        s["finding_body"],
                    )
                )
            else:
                elements.append(
                    Paragraph(
                        f"<b>Reviewer:</b> {xml_escape(reviewer)}", s["finding_body"]
                    )
                )
        return KeepTogether(elements)

    # --- Page header/footer ---
    class _Page:
        def on_page(self, canvas: Any, doc: Any) -> None:
            canvas.saveState()
            canvas.setFillColor(RL_BRAND)
            canvas.rect(0, PAGE_H - 0.55 * inch, PAGE_W, 0.55 * inch, fill=1, stroke=0)
            canvas.setFillColor(rl_colors.white)
            canvas.setFont(F["bold"], 11)
            canvas.drawString(
                MARGIN, PAGE_H - 0.35 * inch, f"{project} - Code Review Report"
            )
            canvas.setFont(F["regular"], 8)
            canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 0.25 * inch, date_str)
            canvas.drawRightString(
                PAGE_W - MARGIN, PAGE_H - 0.40 * inch, f"Page {doc.page}"
            )
            canvas.setStrokeColor(RL_BORDER)
            canvas.setLineWidth(0.5)
            canvas.line(MARGIN, 0.42 * inch, PAGE_W - MARGIN, 0.42 * inch)
            canvas.setFillColor(rl_colors.HexColor(TEXT_MUTED))
            canvas.setFont(F["regular"], 7.5)
            canvas.drawCentredString(
                PAGE_W / 2,
                0.22 * inch,
                f"Co-authored by Claudius the Magnificent AI Agent  |  {date_str}",
            )
            canvas.restoreState()

    # --- Build PDF ---
    total_findings = sum(len(sec.get("findings", [])) for sec in finding_sections)
    log.info("Building PDF report -> %s", output_path)

    pg = _Page()
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=LETTER,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=0.75 * inch,
        bottomMargin=0.55 * inch,
        title=f"{project} - Code Review Report",
        author="Claudius the Magnificent",
    )
    story: list[Any] = []

    # Executive summary
    story.append(Spacer(1, 0.1 * inch))
    story.append(Paragraph("Code Review Report", s["title"]))
    story.append(Paragraph(project, s["sub"]))
    story.append(
        Paragraph(f"Reviewed: {date_str} - {num_agents} Specialist Agents", s["sub"])
    )
    story.append(Spacer(1, 6))
    story.append(_hr())

    story.append(Paragraph("1. Executive Summary", s["h2"]))
    story.append(
        Paragraph(
            f'Overall: <b><font color="{GREEN}">{es.get("overall_assessment", "")}</font></b>',
            s["body"],
        )
    )
    if es.get("summary_text"):
        story.extend(_md_body(es["summary_text"], s["body"]))
    story.append(Spacer(1, 4))
    story.append(kpi_boxes())
    story.append(Spacer(1, 6))

    if matrix:
        story.append(Paragraph("<b>Findings by severity and category:</b>", s["small"]))
        story.append(Spacer(1, 4))
        story.append(tbl_summary())
        story.append(Spacer(1, 4))
    story.append(_hr())

    # Charts
    story.append(Paragraph("2. Severity Distribution", s["h2"]))
    log.info("  Pie chart...")
    img = chart_severity_pie()
    if hasattr(img, "hAlign"):
        img.hAlign = "CENTER"
    story.append(img)
    story.append(_hr())

    story.append(Paragraph("3. Findings by Category", s["h2"]))
    log.info("  Category bar...")
    story.append(chart_category_bar())
    story.append(_hr())

    # Top findings
    if top_findings:
        story.append(Paragraph("4. Top Findings - Immediate Action Required", s["h2"]))
        story.append(Paragraph("These must be resolved before merging.", s["small"]))
        story.append(Spacer(1, 4))
        story.append(tbl_top5())
        story.append(_hr())

    # Dependencies
    if deps:
        story.append(Paragraph("5. Dependency Vulnerability Status", s["h2"]))
        story.append(Paragraph("Dependencies scanned against NVD and OSV.", s["small"]))
        story.append(Spacer(1, 4))
        story.append(tbl_deps())
        story.append(_hr())

    # Agent performance
    if agent_stats:
        story.append(Paragraph("6. Agent Performance", s["h2"]))
        story.append(
            Paragraph(
                "Unique = novel. Redundant = flagged by multiple agents (agreement, not waste).",
                s["small"],
            )
        )
        log.info("  Agent bar...")
        img = chart_agent_bar()
        if hasattr(img, "hAlign"):
            img.hAlign = "CENTER"
        story.append(img)
        story.append(_hr())

    # Remediation
    if remediation:
        story.append(Paragraph("7. Remediation Priority", s["h2"]))
        story.append(
            Paragraph(
                f'<font color="{RED}"><b>Before Merge</b></font> items block landing. '
                f'<font color="{AMBER}"><b>Before Production</b></font> = before deployment. '
                f'<font color="{GREEN}"><b>Post-Deployment</b></font> = tracked improvements.',
                s["body"],
            )
        )
        log.info("  Gantt...")
        img = chart_gantt()
        if hasattr(img, "hAlign"):
            img.hAlign = "CENTER"
        story.append(img)
        story.append(_hr())

    # Detailed findings
    for section in finding_sections:
        story.append(PageBreak())
        story.append(Paragraph(section["title"], s["h2"]))
        if section.get("subtitle"):
            story.append(Paragraph(section["subtitle"], s["small"]))
        story.append(Spacer(1, 4))

        for f in section.get("findings", []):
            story.append(render_finding(f))
            story.append(Spacer(1, 2))

        if section.get("positives"):
            story.append(
                Paragraph(
                    f'<font color="{GREEN}"><b>Positive Observations:</b></font> '
                    + section["positives"],
                    s["finding_title"],
                )
            )
        story.append(_hr())

    # Verdict
    story.append(Spacer(1, 10))
    story.append(Paragraph("Verdict", s["h2"]))
    if es.get("verdict_text"):
        story.extend(_md_body(es["verdict_text"], s["body"]))
    if es.get("verdict_action"):
        story.append(
            Paragraph(f"<b>Claudius verdict:</b> {es['verdict_action']}", s["body"])
        )

    doc.build(story, onFirstPage=pg.on_page, onLaterPages=pg.on_page)
    log.info(
        "Done: %s (%.1f KB, %d findings)",
        output_path,
        output_path.stat().st_size / 1024,
        total_findings,
    )


# ===================================================================
# CLI
# ===================================================================
def _ext_for_format(fmt: str) -> str:
    """Return file extension for the given format."""
    return {"md": ".md", "html": ".html", "triage": ".html", "pdf": ".pdf"}[fmt]


def main() -> None:
    """Entry point for the CLI."""
    parser = argparse.ArgumentParser(
        description=(
            "Convert a review report JSON into md, html, triage, or pdf format. "
            "Long-text fields (description, impact_description, recommendation, "
            "ai_assessment, executive summary) render as Markdown in HTML and "
            "PDF. Requires `markdown >= 3.4` and `beautifulsoup4 >= 4.10` "
            "(install via `pip install -r scripts/requirements.txt`)."
        ),
    )
    parser.add_argument("report", type=Path, help="Path to report JSON file")
    parser.add_argument(
        "--format",
        required=True,
        choices=["md", "html", "triage", "pdf"],
        help="Output format",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output file path, or '-' for stdout (default: next to input with appropriate extension)",
    )
    args = parser.parse_args()

    report_path: Path = args.report.resolve()
    if not report_path.is_file():
        log.error("Input file not found: %s", report_path)
        sys.exit(1)

    # Load and validate
    log.info("Loading report: %s", report_path)
    data = json.loads(report_path.read_text(encoding="utf-8"))

    if not SCHEMA_PATH.is_file():
        log.warning("Schema file not found at %s, skipping validation", SCHEMA_PATH)
    else:
        log.info("Validating against schema: %s", SCHEMA_PATH)
        validate_report(data, SCHEMA_PATH)

    # Determine output path
    fmt: str = args.format
    use_stdout = args.output == "-"
    if args.output and not use_stdout:
        out_path = Path(args.output).resolve()
    else:
        out_path = report_path.with_suffix(_ext_for_format(fmt))
        # Avoid overwriting input for non-JSON outputs; for triage add suffix
        if fmt == "triage":
            out_path = report_path.with_suffix(".triage.html")

    # Render
    if fmt == "md":
        content = render_markdown(data)
    elif fmt == "html":
        content = render_html(data)
    elif fmt == "triage":
        content = render_triage(data)
    elif fmt == "pdf":
        if use_stdout:
            log.error("PDF format does not support stdout output (-o -)")
            sys.exit(1)
        render_pdf(data, out_path)
        content = None
    else:
        content = None

    if content is not None:
        if use_stdout:
            sys.stdout.write(content)
            return
        out_path.write_text(content, encoding="utf-8")

    size_kb = out_path.stat().st_size / 1024
    log.info("Output: %s (%.1f KB)", out_path, size_kb)
    print(f"{out_path} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
