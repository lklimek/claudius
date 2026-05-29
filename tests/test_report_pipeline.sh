#!/usr/bin/env bash
# End-to-end test: validate report fixtures through the full pipeline.
# Checks schema validation, severity integrity, sort order, and rendering.
#
# Usage: ./tests/test_report_pipeline.sh [fixture.json ...]
# If no args, runs all v3 happy-path fixtures in tests/fixtures/reports/v3-*.json.
# Negative/legacy fixtures live under tests/fixtures/legacy/ and are driven by
# tests/test_schema_v3_strict.py, not this pipeline.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
FIXTURES_DIR="$SCRIPT_DIR/fixtures/reports"

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

pass=0
fail=0

ok()   { echo -e "  ${GREEN}✓${NC} $1"; ((pass++)) || true; }
fail() { echo -e "  ${RED}✗${NC} $1"; ((fail++)) || true; }

# Collect fixtures
if [ $# -gt 0 ]; then
  fixtures=("$@")
else
  fixtures=("$FIXTURES_DIR"/v3-*.json)
fi

if [ ${#fixtures[@]} -eq 0 ]; then
  echo "No fixtures found in $FIXTURES_DIR"
  exit 1
fi

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

for fixture in "${fixtures[@]}"; do
  name=$(basename "$fixture" .json)
  echo "=== $name ==="

  # 1. Schema validation
  if python3 "$REPO_ROOT/scripts/validate_report.py" "$fixture" 2>/dev/null; then
    ok "schema validation"
  else
    fail "schema validation"
    continue  # skip remaining checks if schema fails
  fi

  # 2. All severity values are integers in range [1,5]
  bad_sevs=$(python3 -c "
import json, sys
r = json.load(open('$fixture'))
bad = []
for s in r.get('findings', []):
    for f in s.get('findings', []):
        sev = f.get('severity')
        if not isinstance(sev, int) or not 1 <= sev <= 5:
            bad.append(f'{f.get(\"id\",\"?\")}: {sev}')
if bad:
    print('\n'.join(bad))
    sys.exit(1)
" 2>&1) && ok "severity values are integers [1,5]" || fail "severity values: $bad_sevs"

  # 3. Findings sorted by severity descending within each section
  sort_ok=$(python3 -c "
import json, sys
r = json.load(open('$fixture'))
for s in r.get('findings', []):
    sevs = [f['severity'] for f in s.get('findings', [])]
    if any(sevs[i] < sevs[i+1] for i in range(len(sevs)-1)):
        print(f'Section {s.get(\"category\",\"?\")}: {sevs}')
        sys.exit(1)
" 2>&1) && ok "sort order (severity descending)" || fail "sort order: $sort_ok"

  # 4. severity_counts labels are strings, values are non-negative ints
  counts_ok=$(python3 -c "
import json, sys
r = json.load(open('$fixture'))
counts = r.get('summary_statistics', {}).get('severity_counts', {})
expected_keys = {'CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO'}
if set(counts.keys()) != expected_keys:
    print(f'keys: {set(counts.keys())} != {expected_keys}')
    sys.exit(1)
for k, v in counts.items():
    if not isinstance(v, int) or v < 0:
        print(f'{k}: {v}')
        sys.exit(1)
" 2>&1) && ok "severity_counts structure" || fail "severity_counts: $counts_ok"

  # 5. total_findings matches actual count
  total_ok=$(python3 -c "
import json, sys
r = json.load(open('$fixture'))
actual = sum(len(s.get('findings', [])) for s in r.get('findings', []))
reported = r.get('summary_statistics', {}).get('total_findings', -1)
if actual != reported:
    print(f'reported={reported} actual={actual}')
    sys.exit(1)
" 2>&1) && ok "total_findings consistent" || fail "total_findings: $total_ok"

  # 6. Finding IDs are unique
  ids_ok=$(python3 -c "
import json, sys
r = json.load(open('$fixture'))
ids = [f['id'] for s in r.get('findings', []) for f in s.get('findings', [])]
dupes = [x for x in ids if ids.count(x) > 1]
if dupes:
    print(f'duplicates: {set(dupes)}')
    sys.exit(1)
" 2>&1) && ok "finding IDs unique" || fail "finding IDs: $ids_ok"

  # 7. Render to markdown (smoke test)
  md_out="$TMPDIR/${name}.md"
  if python3 "$REPO_ROOT/scripts/generate_review_report.py" "$fixture" --format md --output "$md_out" 2>/dev/null && [ -s "$md_out" ]; then
    ok "markdown render"
  else
    fail "markdown render"
  fi

  # 8. Render to HTML (smoke test)
  html_out="$TMPDIR/${name}.html"
  if python3 "$REPO_ROOT/scripts/generate_review_report.py" "$fixture" --format html --output "$html_out" 2>/dev/null && [ -s "$html_out" ]; then
    ok "html render"
  else
    fail "html render"
  fi

  echo ""
done

# === producer-shape (check-pr-comments) report ===
# Floats, no integer severity, all-zero severity_counts. Must validate, then
# render with NON-zero counts (renderer derives severity + recomputes stats).
echo "=== producer-shape ==="
PRODUCER="$TMPDIR/producer.json"
cat > "$PRODUCER" << 'JSON'
{
  "schema_version": "3.1.0",
  "metadata": {"project": "p", "date": "2026-05-29", "report_type": "comment_check"},
  "executive_summary": {"overall_assessment": "ok"},
  "summary_statistics": {
    "total_findings": 1,
    "severity_counts": {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "INFO": 0}
  },
  "findings": [
    {
      "title": "PR Comments",
      "category": "pr_comments",
      "findings": [
        {
          "id": "CMT-001",
          "risk": 0.8,
          "impact": 0.8,
          "scope": 1.0,
          "author_type": "bot",
          "title": "Unresolved review comment",
          "location": "src/x.py:1",
          "description": "d",
          "recommendation": "r"
        }
      ]
    }
  ]
}
JSON

if python3 "$REPO_ROOT/scripts/validate_report.py" "$PRODUCER" >/dev/null 2>&1; then
  ok "producer-shape schema validation"
else
  fail "producer-shape schema validation"
fi

if python3 "$REPO_ROOT/scripts/generate_review_report.py" "$PRODUCER" --format md -o - 2>/dev/null \
    | grep -qE '^\| HIGH .*\| 1 \|$'; then
  ok "producer-shape renders non-zero HIGH count"
else
  fail "producer-shape renders non-zero HIGH count"
fi
echo ""

echo "=== Results: $pass passed, $fail failed ==="
[ "$fail" -eq 0 ]
