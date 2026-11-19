"""Run the portable skill's own regression checks in repository CI."""

import subprocess
import sys
from pathlib import Path


def test_visual_diff_selftest():
    script = Path(__file__).resolve().parents[1] / "scripts/visual-diff/selftest.py"
    result = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
