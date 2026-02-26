"""
generate_report_pdf.py — Professional code review PDF report.

Template bundled with the claudius:report-pdf skill.
Copy to the project directory and customize the CONFIG and FINDINGS sections.

White background, dark text, WCAG AA compliant.
Summary first (charts + tables), then every finding in detail.
"""

from __future__ import annotations

import io
import logging
import sys
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable, Image, KeepTogether, PageBreak, Paragraph,
    SimpleDocTemplate, Spacer, Table, TableStyle,
)

matplotlib.use("Agg")
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)


# ===========================================================================
# CONFIG — Customize per project
# ===========================================================================
CONFIG = {
    "title": "Code Review Report",
    "subtitle": "Project Name",
    "date": "YYYY-MM-DD",
    "agents": 3,                    # Number of specialist agents used
    "unique_findings": 0,           # Total unique findings (after dedup)
    "redundancy_ratio": "0%",       # e.g., "51%"
    "critical_count": 0,            # Number of CRITICAL findings
    "overall_assessment": "Assessment text here.",
    "summary_text": "Summary description of the review.",
    "verdict_text": "Final verdict text.",
    "verdict_action": "Recommended actions.",
    "output": "REVIEW-REPORT.pdf",  # Output path (relative or absolute)
}

# Severity × category matrix: (severity, security, project, code_quality, total)
SUMMARY_TABLE = [
    ("CRITICAL", "0", "0", "0", "0"),
    ("HIGH",     "0", "0", "0", "0"),
    ("MEDIUM",   "0", "0", "0", "0"),
    ("LOW",      "0", "0", "0", "0"),
    ("INFO",     "0", "0", "0", "0"),
]

# Top findings requiring immediate action: (id, severity, description, location)
TOP_FINDINGS = []

# Dependency CVE status: (package, version, cves, applicable, ok_bool)
DEPENDENCY_TABLE = []

# Agent performance: (agent_label, unique_count, redundant_count)
AGENT_STATS = []

# Remediation priority: (label, count, text_label, color_key)
# color_key: "red", "amber", or "green"
REMEDIATION = []

# ---------------------------------------------------------------------------
# FINDINGS — Fill in from the markdown report
#
# Security findings (8-tuple):
#   (id, severity, title, owasp_tag, location, description, impact, recommendation)
#
# Other findings (7-tuple):
#   (id, severity, title, location, description, impact, recommendation)
#
# Each category is a dict: {"title": "...", "subtitle": "...", "findings": [], "positives": ""}
# ---------------------------------------------------------------------------
FINDING_SECTIONS = [
    # {
    #     "title": "Part I: Security Findings (12)",
    #     "subtitle": "All security findings with OWASP Top 10 classification.",
    #     "type": "security",  # "security" for 8-tuple, "standard" for 7-tuple
    #     "findings": [],
    #     "positives": "",  # Optional positive observations text
    # },
]


# ===========================================================================
# Palette — high contrast on white (DO NOT CHANGE)
# ===========================================================================
WHITE = "#FFFFFF"
NEAR_BLACK = "#1A1A1A"
DARK_GRAY = "#333333"
MID_GRAY = "#666666"
LIGHT_GRAY = "#F5F5F5"
BORDER_GRAY = "#DDDDDD"
BRAND_BLUE = "#1B4F72"
ACCENT_BLUE = "#2471A3"
SEV = {
    "CRITICAL": "#C0392B", "HIGH": "#E67E22", "MEDIUM": "#D4AC0D",
    "LOW": "#2E86C1", "INFO": "#7F8C8D",
}
GREEN = "#27AE60"
AMBER = "#E67E22"
RED = "#C0392B"
PRIORITY_COLORS = {"red": RED, "amber": AMBER, "green": GREEN}

RL_WHITE = colors.HexColor(WHITE)
RL_BLACK = colors.HexColor(NEAR_BLACK)
RL_LIGHT = colors.HexColor(LIGHT_GRAY)
RL_BORDER = colors.HexColor(BORDER_GRAY)
RL_BRAND = colors.HexColor(BRAND_BLUE)

PAGE_W, PAGE_H = LETTER
MARGIN = 0.7 * inch
CW = PAGE_W - 2 * MARGIN


# ===========================================================================
# Matplotlib helpers
# ===========================================================================
def _clean(fig, axes):
    fig.patch.set_facecolor("white")
    for ax in axes:
        ax.set_facecolor("white")
        ax.tick_params(colors=DARK_GRAY, labelsize=9, labelcolor=DARK_GRAY)
        ax.xaxis.label.set_color(DARK_GRAY)
        ax.yaxis.label.set_color(DARK_GRAY)
        ax.title.set_color(NEAR_BLACK)
        for sp in ax.spines.values():
            sp.set_edgecolor(BORDER_GRAY)


def _to_img(fig, w, h):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=180, bbox_inches="tight",
                facecolor="white", edgecolor="none")
    buf.seek(0)
    plt.close(fig)
    return Image(buf, width=w, height=h)


# ===========================================================================
# Charts
# ===========================================================================
def chart_severity_pie():
    """Donut chart of severity distribution. Reads from SUMMARY_TABLE."""
    sev_order = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
    totals = {row[0]: int(row[4]) for row in SUMMARY_TABLE}
    labels = [f"{s} ({totals[s]})" for s in sev_order if totals[s] > 0]
    values = [totals[s] for s in sev_order if totals[s] > 0]
    clrs = [SEV[s] for s in sev_order if totals[s] > 0]

    if not values:
        return Spacer(1, 0)

    fig, ax = plt.subplots(figsize=(5.5, 3.0))
    _clean(fig, [ax])
    ax.set_aspect("equal")

    wedges, _, _ = ax.pie(
        values, autopct="%1.0f%%", colors=clrs, startangle=140,
        wedgeprops={"linewidth": 2, "edgecolor": "white", "width": 0.6},
        pctdistance=0.76,
        textprops={"fontsize": 9, "fontweight": "bold", "color": "white"},
    )
    ax.legend(wedges, labels, loc="center left", bbox_to_anchor=(1.05, 0.5),
              frameon=False, fontsize=9, labelcolor=DARK_GRAY)
    ax.set_title("Severity Distribution", fontsize=13, fontweight="bold",
                 color=NEAR_BLACK, pad=10)
    fig.tight_layout()
    return _to_img(fig, CW * 0.85, 2.3 * inch)


def chart_category_bar():
    """Horizontal stacked bar chart of findings by category."""
    cats = ["Security", "Code Quality", "Project Consistency"]
    sev_order = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
    data = {s: [int(row[i]) for row in SUMMARY_TABLE if row[0] == s][0]
            if any(row[0] == s for row in SUMMARY_TABLE) else [0, 0, 0]
            for s in sev_order}
    # Rebuild from SUMMARY_TABLE columns: security=1, project=2, code_quality=3
    data = {}
    for s in sev_order:
        for row in SUMMARY_TABLE:
            if row[0] == s:
                data[s] = [int(row[1]), int(row[3]), int(row[2])]
                break
        else:
            data[s] = [0, 0, 0]

    fig, ax = plt.subplots(figsize=(6.2, 2.2))
    _clean(fig, [ax])

    y = np.arange(len(cats))
    lefts = np.zeros(len(cats))
    for sev_name in sev_order:
        vals = data[sev_name]
        bars = ax.barh(y, vals, 0.5, left=lefts, color=SEV[sev_name],
                       edgecolor="white", linewidth=1)
        for bar, v in zip(bars, vals):
            if v > 0:
                ax.text(bar.get_x() + bar.get_width() / 2,
                        bar.get_y() + bar.get_height() / 2,
                        str(v), ha="center", va="center",
                        fontsize=8, color="white", fontweight="bold")
        lefts += np.array(vals)

    ax.set_yticks(y)
    ax.set_yticklabels(cats, fontsize=10, color=NEAR_BLACK)
    ax.set_xlabel("Number of Findings", fontsize=9, color=DARK_GRAY)
    ax.set_title("Findings by Category", fontsize=13, fontweight="bold",
                 color=NEAR_BLACK, pad=10)
    ax.xaxis.set_major_locator(mticker.MaxNLocator(integer=True))
    ax.grid(axis="x", color=BORDER_GRAY, linestyle="--", linewidth=0.5, alpha=0.7)
    ax.set_axisbelow(True)

    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(facecolor=SEV[s], label=s) for s in SEV],
              loc="upper right", frameon=True, fontsize=7, ncol=5,
              framealpha=0.9, edgecolor=BORDER_GRAY, labelcolor=DARK_GRAY)
    fig.tight_layout()
    return _to_img(fig, CW, 2.0 * inch)


def chart_agent_bar():
    """Grouped bar chart comparing unique vs redundant findings per agent."""
    if not AGENT_STATS:
        return Spacer(1, 0)

    agents = [a[0] for a in AGENT_STATS]
    unique = [a[1] for a in AGENT_STATS]
    redundant = [a[2] for a in AGENT_STATS]

    fig, ax = plt.subplots(figsize=(5.2, 2.6))
    _clean(fig, [ax])
    x = np.arange(len(agents))
    w = 0.32
    bu = ax.bar(x - w / 2, unique, w, label="Unique", color=GREEN,
                edgecolor="white", linewidth=1)
    br = ax.bar(x + w / 2, redundant, w, label="Redundant", color=AMBER,
                edgecolor="white", linewidth=1)
    for bar in list(bu) + list(br):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
                str(int(bar.get_height())), ha="center", va="bottom",
                fontsize=9, color=DARK_GRAY, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(agents, fontsize=10, color=NEAR_BLACK)
    ax.set_ylabel("Findings", fontsize=9, color=DARK_GRAY)
    ax.set_title("Agent Performance", fontsize=13, fontweight="bold",
                 color=NEAR_BLACK, pad=10)
    max_val = max(max(unique), max(redundant)) if unique else 10
    ax.set_ylim(0, max_val + 4)
    ax.yaxis.set_major_locator(mticker.MaxNLocator(integer=True))
    ax.grid(axis="y", color=BORDER_GRAY, linestyle="--", linewidth=0.5, alpha=0.7)
    ax.set_axisbelow(True)
    ax.legend(frameon=True, fontsize=9, edgecolor=BORDER_GRAY, labelcolor=DARK_GRAY)
    fig.tight_layout()
    return _to_img(fig, CW * 0.75, 2.2 * inch)


def chart_gantt():
    """Horizontal bar chart of remediation priorities."""
    if not REMEDIATION:
        return Spacer(1, 0)

    fig, ax = plt.subplots(figsize=(5.8, 1.8))
    _clean(fig, [ax])
    for i, (lbl, cnt, txt, clr_key) in enumerate(REMEDIATION):
        clr = PRIORITY_COLORS.get(clr_key, GREEN)
        ax.barh(i, cnt, 0.5, color=clr, edgecolor="white", linewidth=1)
        ax.text(cnt + 0.3, i, txt, va="center", fontsize=9,
                color=DARK_GRAY, fontweight="bold")
    ax.set_yticks(range(len(REMEDIATION)))
    ax.set_yticklabels([r[0] for r in REMEDIATION], fontsize=10, color=NEAR_BLACK)
    max_cnt = max(r[1] for r in REMEDIATION)
    ax.set_xlim(0, max_cnt + 6)
    ax.set_xlabel("Items", fontsize=9, color=DARK_GRAY)
    ax.set_title("Remediation Priority", fontsize=13, fontweight="bold",
                 color=NEAR_BLACK, pad=10)
    ax.xaxis.set_major_locator(mticker.MaxNLocator(integer=True))
    ax.grid(axis="x", color=BORDER_GRAY, linestyle="--", linewidth=0.5, alpha=0.7)
    ax.set_axisbelow(True)
    fig.tight_layout()
    return _to_img(fig, CW * 0.85, 1.6 * inch)


# ===========================================================================
# ReportLab styles
# ===========================================================================
def _s():
    return {
        "title": ParagraphStyle("T", fontSize=20, textColor=NEAR_BLACK,
                                fontName="Helvetica-Bold", alignment=TA_CENTER, spaceAfter=4),
        "sub": ParagraphStyle("Sub", fontSize=10, textColor=MID_GRAY,
                              fontName="Helvetica", alignment=TA_CENTER, spaceAfter=2),
        "h2": ParagraphStyle("H2", fontSize=14, textColor=BRAND_BLUE,
                             fontName="Helvetica-Bold", spaceBefore=14, spaceAfter=6),
        "h3": ParagraphStyle("H3", fontSize=11, textColor=NEAR_BLACK,
                             fontName="Helvetica-Bold", spaceBefore=10, spaceAfter=4),
        "body": ParagraphStyle("B", fontSize=10, textColor=NEAR_BLACK,
                               fontName="Helvetica", spaceAfter=6, leading=14),
        "small": ParagraphStyle("Sm", fontSize=9, textColor=DARK_GRAY,
                                fontName="Helvetica", spaceAfter=4, leading=13),
        "finding_title": ParagraphStyle("FT", fontSize=10, textColor=NEAR_BLACK,
                                        fontName="Helvetica-Bold", spaceBefore=8, spaceAfter=2),
        "finding_body": ParagraphStyle("FB", fontSize=9, textColor=DARK_GRAY,
                                       fontName="Helvetica", spaceAfter=2, leading=13,
                                       leftIndent=12),
        "th": ParagraphStyle("TH", fontSize=9, textColor=colors.white,
                             fontName="Helvetica-Bold", alignment=TA_CENTER),
        "tc": ParagraphStyle("TC", fontSize=9, textColor=NEAR_BLACK,
                             fontName="Helvetica", leading=12),
        "tcc": ParagraphStyle("TCC", fontSize=9, textColor=NEAR_BLACK,
                              fontName="Helvetica", alignment=TA_CENTER, leading=12),
    }


def _badge(sev):
    clr = SEV.get(sev, "#7F8C8D")
    st = ParagraphStyle(f"B_{sev}", fontSize=8, textColor="#FFFFFF",
                        fontName="Helvetica-Bold", alignment=TA_CENTER,
                        backColor=colors.HexColor(clr), borderPadding=(2, 6, 2, 6))
    return Paragraph(sev, st)


def _hr():
    return HRFlowable(width="100%", thickness=0.5, color=RL_BORDER,
                      spaceAfter=8, spaceBefore=4)


def _tbl_style():
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), RL_BRAND),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
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
    ])


# ===========================================================================
# Tables
# ===========================================================================
def tbl_summary(s):
    header = [Paragraph(h, s["th"]) for h in
              ["Severity", "Security", "Project", "Code Quality", "Total"]]
    data = [header]
    for sev, *vals in SUMMARY_TABLE:
        data.append([_badge(sev)] + [Paragraph(v, s["tcc"]) for v in vals[:-1]]
                    + [Paragraph(f"<b>{vals[-1]}</b>", s["tcc"])])
    t = Table(data, colWidths=[1.1*inch, 1.2*inch, 1.1*inch, 1.3*inch, 0.7*inch],
              repeatRows=1)
    t.setStyle(_tbl_style())
    return t


def tbl_top5(s):
    if not TOP_FINDINGS:
        return Spacer(1, 0)
    header = [Paragraph(h, s["th"]) for h in ["ID", "Severity", "Description", "Location"]]
    data = [header]
    for rid, sev, desc, loc in TOP_FINDINGS:
        data.append([
            Paragraph(rid, s["tcc"]), _badge(sev), Paragraph(desc, s["tc"]),
            Paragraph(f'<font color="{ACCENT_BLUE}">{loc}</font>', s["tc"]),
        ])
    t = Table(data, colWidths=[0.8*inch, 0.85*inch, 3.0*inch, 1.75*inch], repeatRows=1)
    t.setStyle(_tbl_style())
    return t


def tbl_deps(s):
    if not DEPENDENCY_TABLE:
        return Spacer(1, 0)
    header = [Paragraph(h, s["th"]) for h in ["Package", "Version", "Known CVEs", "Applicable?"]]
    data = [header]
    for pkg, ver, cves, appl, ok in DEPENDENCY_TABLE:
        cc = DARK_GRAY if cves == "None" else RED
        ac = GREEN if ok else AMBER
        data.append([
            Paragraph(f"<b>{pkg}</b>", s["tc"]), Paragraph(ver, s["tcc"]),
            Paragraph(f'<font color="{cc}">{cves}</font>', s["tcc"]),
            Paragraph(f'<font color="{ac}"><b>{appl}</b></font>', s["tcc"]),
        ])
    t = Table(data, colWidths=[1.1*inch, 1.0*inch, 2.1*inch, 2.2*inch], repeatRows=1)
    t.setStyle(_tbl_style())
    return t


# ===========================================================================
# KPI boxes
# ===========================================================================
def kpi_boxes():
    c = CONFIG
    kpis = [(str(c["unique_findings"]), "Unique Findings", ACCENT_BLUE),
            (c["redundancy_ratio"], "Redundancy Ratio", AMBER),
            (str(c["critical_count"]), "Critical - Fix Now", RED)]
    cells = []
    for val, label, clr in kpis:
        vs = ParagraphStyle(f"KV_{label}", fontSize=28, textColor=colors.HexColor(clr),
                            fontName="Helvetica-Bold", alignment=TA_CENTER)
        ls = ParagraphStyle(f"KL_{label}", fontSize=9, textColor=MID_GRAY,
                            fontName="Helvetica", alignment=TA_CENTER, spaceBefore=2)
        cells.append([Paragraph(val, vs), Paragraph(label, ls)])
    data = [[c[0] for c in cells], [c[1] for c in cells]]
    t = Table(data, colWidths=[CW / 3] * 3)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), RL_LIGHT),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEAFTER", (0, 0), (1, -1), 0.5, RL_BORDER),
        ("BOX", (0, 0), (-1, -1), 0.5, RL_BORDER),
    ]))
    return t


# ===========================================================================
# Finding renderers
# ===========================================================================
def render_finding_security(f, s):
    """Render a security finding (8-tuple) as flowables."""
    fid, sev, title, owasp, loc, desc, impact, rec = f
    clr = SEV.get(sev, MID_GRAY)
    elements = [
        Paragraph(f'<font color="{clr}"><b>{fid} ({sev})</b></font>: {title} '
                  f'<font color="{MID_GRAY}">- {owasp}</font>', s["finding_title"]),
        Paragraph(f'<b>Location:</b> <font color="{ACCENT_BLUE}">{loc}</font>', s["finding_body"]),
        Paragraph(f'<b>Description:</b> {desc}', s["finding_body"]),
        Paragraph(f'<b>Impact:</b> {impact}', s["finding_body"]),
        Paragraph(f'<b>Recommendation:</b> {rec}', s["finding_body"]),
    ]
    return KeepTogether(elements)


def render_finding(f, s):
    """Render a standard finding (7-tuple) as flowables."""
    fid, sev, title, loc, desc, impact, rec = f
    clr = SEV.get(sev, MID_GRAY)
    elements = [
        Paragraph(f'<font color="{clr}"><b>{fid} ({sev})</b></font>: {title}', s["finding_title"]),
        Paragraph(f'<b>Location:</b> <font color="{ACCENT_BLUE}">{loc}</font>', s["finding_body"]),
        Paragraph(f'<b>Description:</b> {desc}', s["finding_body"]),
        Paragraph(f'<b>Impact:</b> {impact}', s["finding_body"]),
        Paragraph(f'<b>Recommendation:</b> {rec}', s["finding_body"]),
    ]
    return KeepTogether(elements)


# ===========================================================================
# Page header / footer
# ===========================================================================
class _Page:
    def on_page(self, canvas, doc):
        canvas.saveState()
        c = CONFIG
        # Header bar
        canvas.setFillColor(RL_BRAND)
        canvas.rect(0, PAGE_H - 0.55 * inch, PAGE_W, 0.55 * inch, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 11)
        canvas.drawString(MARGIN, PAGE_H - 0.35 * inch,
                          f"{c['subtitle']} - {c['title']}")
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 0.25 * inch, c["date"])
        canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 0.40 * inch, f"Page {doc.page}")
        # Footer
        canvas.setStrokeColor(RL_BORDER)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, 0.42 * inch, PAGE_W - MARGIN, 0.42 * inch)
        canvas.setFillColor(colors.HexColor(MID_GRAY))
        canvas.setFont("Helvetica", 7.5)
        canvas.drawCentredString(PAGE_W / 2, 0.22 * inch,
                                 f"Co-authored by Claudius the Magnificent AI Agent  |  {c['date']}")
        canvas.restoreState()


# ===========================================================================
# Build
# ===========================================================================
def build():
    c = CONFIG
    output = Path(c["output"])
    total_findings = sum(len(sec["findings"]) for sec in FINDING_SECTIONS)
    log.info("Building full PDF report -> %s", output)

    pg = _Page()
    doc = SimpleDocTemplate(
        str(output), pagesize=LETTER,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=0.75 * inch, bottomMargin=0.55 * inch,
        title=f"{c['subtitle']} - {c['title']}",
        author="Claudius the Magnificent",
    )
    s = _s()
    story = []

    # ==================== PART A: EXECUTIVE SUMMARY ====================
    story.append(Spacer(1, 0.1 * inch))
    story.append(Paragraph(c["title"], s["title"]))
    story.append(Paragraph(c["subtitle"], s["sub"]))
    story.append(Paragraph(f"Reviewed: {c['date']} - {c['agents']} Specialist Agents", s["sub"]))
    story.append(Spacer(1, 6))
    story.append(_hr())

    story.append(Paragraph("1. Executive Summary", s["h2"]))
    story.append(Paragraph(
        f'Overall: <b><font color="{GREEN}">{c["overall_assessment"]}</font></b>',
        s["body"]))
    story.append(Paragraph(c["summary_text"], s["body"]))
    story.append(Spacer(1, 4))
    story.append(kpi_boxes())
    story.append(Spacer(1, 6))
    story.append(Paragraph("<b>Findings by severity and category:</b>", s["small"]))
    story.append(Spacer(1, 4))
    story.append(tbl_summary(s))
    story.append(Spacer(1, 4))
    story.append(_hr())

    # Charts
    story.append(Paragraph("2. Severity Distribution", s["h2"]))
    log.info("  Pie chart...")
    img = chart_severity_pie()
    if hasattr(img, 'hAlign'):
        img.hAlign = "CENTER"
    story.append(img)
    story.append(_hr())

    story.append(Paragraph("3. Findings by Category", s["h2"]))
    log.info("  Category bar...")
    story.append(chart_category_bar())
    story.append(_hr())

    # Top findings
    if TOP_FINDINGS:
        story.append(Paragraph("4. Top Findings - Immediate Action Required", s["h2"]))
        story.append(Paragraph("These must be resolved before merging.", s["small"]))
        story.append(Spacer(1, 4))
        story.append(tbl_top5(s))
        story.append(_hr())

    # Dependencies
    if DEPENDENCY_TABLE:
        story.append(Paragraph("5. Dependency Vulnerability Status", s["h2"]))
        story.append(Paragraph(
            "Dependencies scanned against NVD and OSV.", s["small"]))
        story.append(Spacer(1, 4))
        story.append(tbl_deps(s))
        story.append(_hr())

    # Agent performance
    if AGENT_STATS:
        story.append(Paragraph("6. Agent Performance", s["h2"]))
        story.append(Paragraph(
            "Unique = novel. Redundant = flagged by multiple agents (agreement, not waste).",
            s["small"]))
        log.info("  Agent bar...")
        img = chart_agent_bar()
        if hasattr(img, 'hAlign'):
            img.hAlign = "CENTER"
        story.append(img)
        story.append(_hr())

    # Remediation
    if REMEDIATION:
        story.append(Paragraph("7. Remediation Priority", s["h2"]))
        story.append(Paragraph(
            f'<font color="{RED}"><b>Before Merge</b></font> items block landing. '
            f'<font color="{AMBER}"><b>Before Production</b></font> = before deployment. '
            f'<font color="{GREEN}"><b>Post-Deployment</b></font> = tracked improvements.',
            s["body"]))
        log.info("  Gantt...")
        img = chart_gantt()
        if hasattr(img, 'hAlign'):
            img.hAlign = "CENTER"
        story.append(img)
        story.append(_hr())

    # ==================== PART B: DETAILED FINDINGS ====================
    for section in FINDING_SECTIONS:
        story.append(PageBreak())
        story.append(Paragraph(section["title"], s["h2"]))
        if section.get("subtitle"):
            story.append(Paragraph(section["subtitle"], s["small"]))
        story.append(Spacer(1, 4))

        renderer = render_finding_security if section.get("type") == "security" else render_finding
        for f in section["findings"]:
            story.append(renderer(f, s))
            story.append(Spacer(1, 2))

        if section.get("positives"):
            story.append(Paragraph(
                f'<font color="{GREEN}"><b>Positive Observations:</b></font> '
                + section["positives"], s["finding_title"]))
        story.append(_hr())

    # ==================== VERDICT ====================
    story.append(Spacer(1, 10))
    story.append(Paragraph("Verdict", s["h2"]))
    story.append(Paragraph(c["verdict_text"], s["body"]))
    story.append(Paragraph(f"<b>Claudius verdict:</b> {c['verdict_action']}", s["body"]))

    doc.build(story, onFirstPage=pg.on_page, onLaterPages=pg.on_page)
    log.info("Done: %s (%.1f KB, %d findings)", output,
             output.stat().st_size / 1024, total_findings)


if __name__ == "__main__":
    build()
    print(f"Report: {Path(CONFIG['output']).resolve()}")
