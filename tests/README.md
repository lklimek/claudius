# Claudius Plugin Permission Tests

Automated test suite for verifying the permission model and structural integrity
of the [Claudius](https://github.com/lklimek/claudius) Claude Code plugin.

## Test Categories

1. **Plugin Structure** — Validates manifest, directory layout, and file presence
2. **Script Input Validation** — Tests all shell scripts reject malicious/invalid inputs
3. **Skill Tool Consistency** — Verifies `allowed-tools` match skill purposes
4. **Settings Coverage** — Ensures `settings.example.json` covers all skill tool patterns
5. **Deny List Effectiveness** — Confirms dangerous git operations are blocked
6. **Read/Write Classification** — Validates read-only skills lack write tools
7. **Agent Tool Boundaries** — Checks agents have minimal required tool sets
8. **Cross-Skill Conflicts** — Detects permission pattern overlaps or contradictions
9. **CLI Plugin Loading** — Verifies Claude CLI can load and list the plugin

## Running

```bash
cd /tmp/claude
python3 test_claudius_permissions.py
```

## Constraints

- All tests are read-only: no GitHub state is modified
- No PRs are created, modified, or commented on
- Scripts are tested only with invalid/edge-case inputs to verify rejection
