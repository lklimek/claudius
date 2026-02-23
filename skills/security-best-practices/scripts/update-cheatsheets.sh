#!/usr/bin/env bash
# Update OWASP Cheat Sheet Series from upstream.
#
# Performs a sparse clone of only the cheatsheets/ directory,
# copies the markdown files into the skill's references directory,
# and cleans up the temporary clone.
#
# Usage:
#   scripts/update-cheatsheets.sh
#
# Run from the skill directory (skills/security-best-practices/) or
# pass the skill directory as the first argument.

set -euo pipefail

REPO_URL="https://github.com/OWASP/CheatSheetSeries.git"
BRANCH="master"
SKILL_DIR="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
TARGET_DIR="${SKILL_DIR}/references/cheatsheets"
TMP_DIR=""

cleanup() {
    if [[ -n "${TMP_DIR}" && -d "${TMP_DIR}" ]]; then
        rm -rf "${TMP_DIR}"
    fi
}
trap cleanup EXIT

echo "==> Cloning OWASP CheatSheetSeries (sparse, depth=1)..."
TMP_DIR="$(mktemp -d)"
git clone --depth 1 --no-checkout --filter=blob:none "${REPO_URL}" "${TMP_DIR}" 2>&1
cd "${TMP_DIR}"
git sparse-checkout set cheatsheets
git checkout "${BRANCH}" -- cheatsheets/ 2>&1

echo "==> Copying cheat sheets to ${TARGET_DIR}..."
mkdir -p "${TARGET_DIR}"

# Remove old cheat sheets (but preserve ATTRIBUTION.md)
find "${TARGET_DIR}" -name '*_Cheat_Sheet.md' -o -name '*_Security.md' | xargs rm -f 2>/dev/null || true

cp cheatsheets/*.md "${TARGET_DIR}/"

COUNT=$(ls -1 "${TARGET_DIR}"/*.md 2>/dev/null | grep -cv 'ATTRIBUTION.md' || echo 0)
echo "==> Done. ${COUNT} cheat sheets updated in ${TARGET_DIR}"
