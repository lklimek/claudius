#!/usr/bin/env python3
"""Compute SHA256 diff-view anchors for GitHub PR file paths.

Usage: diff-anchors.py <file_path> [<file_path> ...]

Outputs: <file_path> -> <sha256_hex>

These hashes are used in GitHub PR diff-view URLs:
  https://github.com/<owner>/<repo>/pull/<number>/files#diff-<sha256>R<line>
"""

import hashlib
import sys


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <file_path> [<file_path> ...]", file=sys.stderr)
        sys.exit(1)
    for path in sys.argv[1:]:
        digest = hashlib.sha256(path.encode()).hexdigest()
        print(f"{path} -> {digest}")


if __name__ == "__main__":
    main()
