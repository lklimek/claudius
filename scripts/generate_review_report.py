#!/usr/bin/env python3
"""Unified renderer: converts a review report JSON into md, html, triage, or pdf."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

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


# ===================================================================
# Validation
# ===================================================================
def validate_report(data: dict[str, Any], schema_path: Path) -> None:
    """Validate *data* against the JSON schema. Raises SystemExit on failure."""
    import jsonschema

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
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


# ===================================================================
# FORMAT: Markdown
# ===================================================================
def render_markdown(data: dict[str, Any]) -> str:
    """Render the report as a Markdown string."""
    meta = _meta(data)
    es = data.get("executive_summary", {})
    stats = data.get("summary_statistics", {})
    lines: list[str] = []

    scope = meta.get("scope", "N/A")
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

    # Top findings
    top = data.get("top_findings", [])
    if top:
        lines.append("### Top 5 Findings")
        lines.append("")
        for tf in top[:5]:
            lines.append(
                f"- **{tf['id']}** ({tf['severity']}): {tf['title']} \u2014 `{tf['location']}`"
            )
        lines.append("")

    # Sections
    section_labels = {
        "security": "Part I: Security Findings",
        "project": "Part II: Project Consistency",
        "code_quality": "Part III: Code Quality & Language Best Practices",
        "dependencies": "Part IV: Dependencies",
        "documentation": "Part V: Documentation",
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
            lines.append(f"### {f['id']} ({f['severity']}): {f['title']}{tag_str}")
            lines.append("")
            lines.append(f"- **Location**: `{f['location']}`")
            lines.append(f"- **Description**: {f['description']}")
            if f.get("impact"):
                lines.append(f"- **Impact**: {f['impact']}")
            lines.append(f"- **Recommendation**: {f['recommendation']}")
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
<title>Code Review Report: {{ scope }}</title>
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
.finding dt{font-weight:600;display:inline}
.finding dd{display:inline;margin:0}
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
{% block extra_css %}{% endblock %}
</style>
</head>
<body>
<div class="header-bar">
  <div class="container">
    <h1>Code Review Report: {{ scope }}</h1>
    <div class="meta">{{ meta.project }} &middot; {{ meta.date }}{% if meta.branch %} &middot; {{ meta.branch }}{% endif %}</div>
  </div>
</div>

<nav class="toc no-print" id="toc">
  <a href="#summary">Summary</a>
  <a href="#charts">Charts</a>
  {% if top_findings %}<a href="#top-findings">Top Findings</a>{% endif %}
  {% for sec in findings %}<a href="#section-{{ loop.index }}">{{ sec.title }}</a>{% endfor %}
  {% if dependencies %}<a href="#dependencies">Dependencies</a>{% endif %}
  {% if remediation %}<a href="#remediation">Remediation</a>{% endif %}
  <a href="#verdict">Verdict</a>
</nav>

<div class="container">

<!-- Executive Summary -->
<h2 id="summary">Executive Summary</h2>
<p><strong>{{ executive_summary.overall_assessment }}</strong></p>
{% if executive_summary.summary_text %}<p>{{ executive_summary.summary_text }}</p>{% endif %}

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

<!-- Charts -->
<h2 id="charts">Charts</h2>

<div class="chart-container">
  <canvas id="severityChart"></canvas>
</div>

<div class="chart-container-wide">
  <canvas id="categoryChart"></canvas>
</div>

{% if agent_stats %}
<div class="chart-container-wide">
  <canvas id="agentChart"></canvas>
</div>
{% endif %}

{% if remediation %}
<div class="chart-container-wide">
  <canvas id="remediationChart"></canvas>
</div>
{% endif %}

<!-- Top findings -->
{% if top_findings %}
<h2 id="top-findings">Top Findings</h2>
<table>
<tr><th>ID</th><th>Severity</th><th>Title</th><th>Location</th>{% if triage %}<th class="no-print">Decision</th>{% endif %}</tr>
{% for tf in top_findings %}
<tr>
  <td><a href="#finding-{{ tf.id }}">{{ tf.id }}</a></td>
  <td><span class="badge badge-{{ tf.severity }}">{{ tf.severity }}</span></td>
  <td>{{ tf.title }}</td>
  <td><code>{{ tf.location }}</code></td>
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
{% for sec in findings %}
<h2 id="section-{{ loop.index }}">{{ sec.title }}</h2>
{% if sec.subtitle %}<p><em>{{ sec.subtitle }}</em></p>{% endif %}

<details open>
<summary>{{ sec.findings | length }} finding{{ "s" if sec.findings | length != 1 else "" }}</summary>

{% for f in sec.findings %}
<div class="finding finding-{{ f.severity }}" id="finding-{{ f.id }}">
  <h3>
    <span class="badge badge-{{ f.severity }}">{{ f.severity }}</span>
    {{ f.id }}: {{ f.title }}
    {% for tag in f.tags | default([]) %}<span class="tag">{{ tag }}</span>{% endfor %}
  </h3>
  <dl>
    <dt>Location: </dt><dd><code>{{ f.location }}</code></dd><br>
    <dt>Description: </dt><dd>{{ f.description }}</dd><br>
    {% if f.impact %}<dt>Impact: </dt><dd>{{ f.impact }}</dd><br>{% endif %}
    <dt>Recommendation: </dt><dd>{{ f.recommendation }}</dd>
  </dl>
</div>
{% endfor %}

{% if sec.positives %}
<p class="positives"><strong>Positive observations:</strong> {{ sec.positives }}</p>
{% endif %}
</details>
{% endfor %}

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

<!-- Verdict -->
<h2 id="verdict">Verdict</h2>
<div class="verdict">
  {% if executive_summary.verdict_text %}<p>{{ executive_summary.verdict_text }}</p>{% endif %}
  {% if executive_summary.verdict_action %}<p><strong>Action:</strong> {{ executive_summary.verdict_action }}</p>{% endif %}
</div>

{% if triage %}
<div class="triage-bottom-bar no-print" style="margin:2rem 0 1rem;padding:1rem;background:{{ BG_LIGHT|e }};border:1px solid {{ BORDER|e }};border-radius:6px;text-align:center">
  <button id="exportDecisionsBottom" style="padding:8px 20px;background:{{ ACCENT|e }};color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:.95rem">Export Decisions</button>
  <button id="submitBtnBottom" style="padding:8px 20px;background:{{ BRAND|e }};color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:.95rem;margin-left:.5rem">Submit to Server</button>
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

  // Agent performance
  {% if agent_stats %}
  const agentStats = {{ agent_stats_json }};
  if (agentStats.length) {
    new Chart(document.getElementById("agentChart"), {
      type: "bar",
      data: {
        labels: agentStats.map(a => a.agent),
        datasets: [
          {label: "Unique", data: agentStats.map(a => a.unique), backgroundColor: "{{ GREEN }}"},
          {label: "Redundant", data: agentStats.map(a => a.redundant), backgroundColor: "{{ AMBER }}"}
        ]
      },
      options: {responsive: true, plugins: {title: {display: true, text: "Agent Performance", font: {size: 15}}},
        scales: {y:{ticks:{stepSize:1}}}}
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
.triage-row input[type=text]{flex:1;min-width:120px}
.toast{position:fixed;bottom:1rem;right:1rem;padding:.8rem 1.2rem;border-radius:6px;color:#fff;
  font-size:.9rem;z-index:999;opacity:0;transition:opacity .3s}
.toast.show{opacity:1}
.toast-ok{background:{{ GREEN }}}
.toast-err{background:{{ RED }}}
#submitBtn,#submitBtnBottom{display:none}
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

  // Synchronize: top → detail and detail → top
  topSelects.forEach(sel => {
    sel.addEventListener("change", () => {
      const d = detailMap[sel.dataset.findingId];
      if (d) d.value = sel.value;
    });
  });
  findings.forEach(f => {
    const sel = f.querySelector(".triage-action");
    if (sel) sel.addEventListener("change", () => {
      const t = topMap[f.dataset.findingId];
      if (t) t.value = sel.value;
    });
  });

  // Filter + search + sort
  const sevFilter = document.getElementById("filterSeverity");
  const catFilter = document.getElementById("filterCategory");
  const searchInput = document.getElementById("filterSearch");
  const sortSelect = document.getElementById("sortBy");

  function applyFilters() {
    const sv = sevFilter.value, ct = catFilter.value, q = searchInput.value.toLowerCase();
    findings.forEach(f => {
      let show = true;
      if (sv && f.dataset.severity !== sv) show = false;
      if (ct && f.dataset.category !== ct) show = false;
      if (q && !f.textContent.toLowerCase().includes(q)) show = false;
      f.style.display = show ? "" : "none";
    });
  }

  function applySort() {
    const key = sortSelect.value;
    const sevRank = {"CRITICAL":0,"HIGH":1,"MEDIUM":2,"LOW":3,"INFO":4};
    const arr = Array.from(findings);
    arr.sort((a, b) => {
      if (key === "severity") return (sevRank[a.dataset.severity]||9) - (sevRank[b.dataset.severity]||9);
      if (key === "id") return a.dataset.findingId.localeCompare(b.dataset.findingId);
      if (key === "category") return (a.dataset.category||"").localeCompare(b.dataset.category||"");
      return 0;
    });
    arr.forEach(el => el.parentNode.appendChild(el));
  }

  if (sevFilter) sevFilter.addEventListener("change", applyFilters);
  if (catFilter) catFilter.addEventListener("change", applyFilters);
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
  document.querySelectorAll("#exportDecisions, #exportDecisionsBottom").forEach(
    btn => { if (btn) btn.addEventListener("click", doExport); }
  );

  // Submit to server
  const isServer = typeof window.TRIAGE_SERVER !== "undefined" && window.TRIAGE_SERVER;
  document.querySelectorAll("#submitBtn, #submitBtnBottom").forEach(btn => {
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
    try {
      const resp = await fetch("/api/decisions", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload)
      });
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      showToast("Decisions submitted — server shutting down.", "ok");
    } catch (e) {
      showToast("Error: " + e.message, "err");
    }
  }

  function showToast(msg, kind) {
    const t = document.createElement("div");
    t.className = "toast toast-" + kind + " show";
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => { t.classList.remove("show"); setTimeout(() => t.remove(), 500); }, 3000);
  }

  // Default sort: severity (CRITICAL first)
  if (sortSelect) { sortSelect.value = "severity"; applySort(); }
})();
</script>
"""


def _build_html_context(
    data: dict[str, Any], *, triage: bool = False
) -> dict[str, Any]:
    """Build the Jinja2 template context from report data."""
    meta = _meta(data)
    stats = data.get("summary_statistics", {})

    findings_sections = data.get("findings", [])
    if triage:
        # Flatten all findings into a single list sorted by severity
        sev_rank = {s: i for i, s in enumerate(SEV_ORDER)}
        all_findings = []
        for sec in findings_sections:
            for f in sec.get("findings", []):
                all_findings.append(f)
        all_findings.sort(key=lambda f: sev_rank.get(f.get("severity", "INFO"), 99))
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
    template = env.from_string(_HTML_TEMPLATE)
    ctx = _build_html_context(data, triage=False)
    _mark_safe_values(ctx)
    return template.render(**ctx)


def render_triage(data: dict[str, Any]) -> str:
    """Render the report as an interactive triage HTML page."""
    from jinja2 import Environment

    # Build a triage-augmented template by injecting extra CSS and JS blocks
    triage_template = _HTML_TEMPLATE.replace(
        "{% block extra_css %}{% endblock %}",
        _TRIAGE_EXTRA_CSS,
    ).replace(
        "{% block extra_js %}{% endblock %}",
        _TRIAGE_EXTRA_JS,
    )

    # Augment the finding divs to include triage controls and data attributes
    # We do this by replacing the finding div in the template
    old_finding_div = (
        '<div class="finding finding-{{ f.severity }}" id="finding-{{ f.id }}">'
    )
    new_finding_div = (
        '<div class="finding finding-{{ f.severity }}" id="finding-{{ f.id }}"'
        ' data-finding-id="{{ f.id }}" data-severity="{{ f.severity }}"'
        ' data-category="{{ sec.category }}">'
    )
    triage_template = triage_template.replace(old_finding_div, new_finding_div)

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
        "  </div>\n"
        "</div>\n{% endfor %}"
    )
    triage_template = triage_template.replace(old_dl_close, new_dl_close)

    # Add toolbar before the first section heading
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
    <option value="CRITICAL">CRITICAL</option>
    <option value="HIGH">HIGH</option>
    <option value="MEDIUM">MEDIUM</option>
    <option value="LOW">LOW</option>
    <option value="INFO">INFO</option>
  </select>
  <select id="filterCategory">
    <option value="">All Categories</option>
    <option value="security">Security</option>
    <option value="project">Project</option>
    <option value="code_quality">Code Quality</option>
    <option value="documentation">Documentation</option>
    <option value="dependencies">Dependencies</option>
  </select>
  <input type="text" id="filterSearch" placeholder="Search findings...">
  <select id="sortBy">
    <option value="">Sort By...</option>
    <option value="severity">Severity</option>
    <option value="id">ID</option>
    <option value="category">Category</option>
  </select>
</div>
<div style="margin:1rem 0">
  <button id="exportDecisions" class="no-print" style="padding:6px 16px;background:{{ ACCENT }};color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:.9rem">Export Decisions</button>
  <button id="submitBtn" class="no-print" style="padding:6px 16px;background:{{ BRAND }};color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:.9rem;margin-left:.5rem">Submit to Server</button>
</div>
"""
    # Insert toolbar before the first section loop
    triage_template = triage_template.replace(
        "<!-- Detailed findings by section -->",
        "<!-- Detailed findings by section -->\n" + toolbar_html,
    )

    env = Environment(autoescape=True)
    template = env.from_string(triage_template)
    ctx = _build_html_context(data, triage=True)
    _mark_safe_values(ctx)
    return template.render(**ctx)


# ===================================================================
# FORMAT: PDF
# ===================================================================
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

    def _badge(sev: str) -> Paragraph:
        clr = SEV_COLORS.get(sev, "#7F8C8D")
        st = ParagraphStyle(
            f"B_{sev}",
            fontSize=8,
            textColor="#FFFFFF",
            fontName="Helvetica-Bold",
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
            ]
        )

    # --- Styles ---
    s = {
        "title": ParagraphStyle(
            "T",
            fontSize=20,
            textColor=TEXT_DARK,
            fontName="Helvetica-Bold",
            alignment=TA_CENTER,
            spaceAfter=4,
        ),
        "sub": ParagraphStyle(
            "Sub",
            fontSize=10,
            textColor=TEXT_MUTED,
            fontName="Helvetica",
            alignment=TA_CENTER,
            spaceAfter=2,
        ),
        "h2": ParagraphStyle(
            "H2",
            fontSize=14,
            textColor=BRAND,
            fontName="Helvetica-Bold",
            spaceBefore=14,
            spaceAfter=6,
        ),
        "h3": ParagraphStyle(
            "H3",
            fontSize=11,
            textColor=TEXT_DARK,
            fontName="Helvetica-Bold",
            spaceBefore=10,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "B",
            fontSize=10,
            textColor=TEXT_DARK,
            fontName="Helvetica",
            spaceAfter=6,
            leading=14,
        ),
        "small": ParagraphStyle(
            "Sm",
            fontSize=9,
            textColor=TEXT_SECONDARY,
            fontName="Helvetica",
            spaceAfter=4,
            leading=13,
        ),
        "finding_title": ParagraphStyle(
            "FT",
            fontSize=10,
            textColor=TEXT_DARK,
            fontName="Helvetica-Bold",
            spaceBefore=8,
            spaceAfter=2,
        ),
        "finding_body": ParagraphStyle(
            "FB",
            fontSize=9,
            textColor=TEXT_SECONDARY,
            fontName="Helvetica",
            spaceAfter=2,
            leading=13,
            leftIndent=12,
        ),
        "th": ParagraphStyle(
            "TH",
            fontSize=9,
            textColor=rl_colors.white,
            fontName="Helvetica-Bold",
            alignment=TA_CENTER,
        ),
        "tc": ParagraphStyle(
            "TC", fontSize=9, textColor=TEXT_DARK, fontName="Helvetica", leading=12
        ),
        "tcc": ParagraphStyle(
            "TCC",
            fontSize=9,
            textColor=TEXT_DARK,
            fontName="Helvetica",
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
            tbl_data.append(
                [
                    Paragraph(tf["id"], s["tcc"]),
                    _badge(tf["severity"]),
                    Paragraph(tf["title"], s["tc"]),
                    Paragraph(
                        f'<font color="{ACCENT}">{tf["location"]}</font>', s["tc"]
                    ),
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
                fontName="Helvetica-Bold",
                alignment=TA_CENTER,
            )
            ls = ParagraphStyle(
                f"KL_{label}",
                fontSize=9,
                textColor=TEXT_MUTED,
                fontName="Helvetica",
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

    # --- Finding renderers ---
    def render_finding(f: dict[str, Any]) -> KeepTogether:
        fid = f["id"]
        sev = f["severity"]
        title = f["title"]
        tags = f.get("tags", [])
        loc = f["location"]
        desc = f["description"]
        impact = f.get("impact", "")
        rec = f["recommendation"]
        clr = SEV_COLORS.get(sev, TEXT_MUTED)
        tag_display = (
            f' <font color="{TEXT_MUTED}">- {", ".join(tags)}</font>' if tags else ""
        )
        elements = [
            Paragraph(
                f'<font color="{clr}"><b>{fid} ({sev})</b></font>: {title}{tag_display}',
                s["finding_title"],
            ),
            Paragraph(
                f'<b>Location:</b> <font color="{ACCENT}">{loc}</font>',
                s["finding_body"],
            ),
            Paragraph(f"<b>Description:</b> {desc}", s["finding_body"]),
        ]
        if impact:
            elements.append(Paragraph(f"<b>Impact:</b> {impact}", s["finding_body"]))
        elements.append(Paragraph(f"<b>Recommendation:</b> {rec}", s["finding_body"]))
        return KeepTogether(elements)

    # --- Page header/footer ---
    class _Page:
        def on_page(self, canvas: Any, doc: Any) -> None:
            canvas.saveState()
            canvas.setFillColor(RL_BRAND)
            canvas.rect(0, PAGE_H - 0.55 * inch, PAGE_W, 0.55 * inch, fill=1, stroke=0)
            canvas.setFillColor(rl_colors.white)
            canvas.setFont("Helvetica-Bold", 11)
            canvas.drawString(
                MARGIN, PAGE_H - 0.35 * inch, f"{project} - Code Review Report"
            )
            canvas.setFont("Helvetica", 8)
            canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 0.25 * inch, date_str)
            canvas.drawRightString(
                PAGE_W - MARGIN, PAGE_H - 0.40 * inch, f"Page {doc.page}"
            )
            canvas.setStrokeColor(RL_BORDER)
            canvas.setLineWidth(0.5)
            canvas.line(MARGIN, 0.42 * inch, PAGE_W - MARGIN, 0.42 * inch)
            canvas.setFillColor(rl_colors.HexColor(TEXT_MUTED))
            canvas.setFont("Helvetica", 7.5)
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
        story.append(Paragraph(es["summary_text"], s["body"]))
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
        story.append(Paragraph(es["verdict_text"], s["body"]))
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
        description="Convert a review report JSON into md, html, triage, or pdf format.",
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
