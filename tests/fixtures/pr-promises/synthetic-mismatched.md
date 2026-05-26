# Pass C fixture — mismatched PR

Drives all three Pass C audit axes. Expected output: exactly 3 findings (`PPM-001`, `PPM-002`, `PPM-003`), one per axis.

## PR Title

```
fix: PDF rendering crashes on Unicode glyphs
```

## PR Body

```markdown
## Summary

- Implement an in-memory response cache for the gRPC client to cut redundant fetches.
- Add retry/backoff to the gRPC transport.

## Out of scope

- Auth service migration to OAuth2 — tracked separately in #999.
```

## PR Diff (excerpt)

```diff
diff --git a/src/grpc/transport.go b/src/grpc/transport.go
@@ -10,6 +10,18 @@ func (c *Client) Call(ctx context.Context, req *Req) (*Resp, error) {
+    for attempt := 0; attempt < c.maxRetries; attempt++ {
+        resp, err := c.transport.RoundTrip(ctx, req)
+        if err == nil { return resp, nil }
+        time.Sleep(backoff(attempt))
+    }
     return nil, ErrExhausted
 }

diff --git a/src/auth/oauth_migration.go b/src/auth/oauth_migration.go
@@ -0,0 +1,42 @@
+package auth
+
+// MigrateLegacyToOAuth2 walks the legacy user table and re-issues OAuth2 credentials.
+func MigrateLegacyToOAuth2(ctx context.Context, db *sql.DB) error {
+    rows, err := db.QueryContext(ctx, "SELECT id, legacy_token FROM users")
+    if err != nil { return err }
+    defer rows.Close()
+    for rows.Next() {
+        // ... 35 more lines wiring the OAuth2 issuer ...
+    }
+    return nil
+}

diff --git a/tests/grpc/retry_test.go b/tests/grpc/retry_test.go
@@ -0,0 +1,24 @@
+package grpc_test
+
+func TestRetryOnTransientFailure(t *testing.T) {
+    // ... exercises the new retry loop ...
+}
```

## Expected Pass C findings

1. **Axis 1 (title ↔ diff)** — title claims `fix: PDF rendering crashes on Unicode glyphs` but no `pdf` / `render` / `glyph` paths or symbols appear in the diff. Off-target. `location: PR-title`.
2. **Axis 2 (body Summary ↔ diff)** — Summary bullet 1 promises an in-memory response cache; no cache code in the diff. Missing claim. `location: PR-body:summary-bullet-1`.
3. **Axis 3 (out-of-scope enforcement)** — body declares the auth/OAuth2 migration out of scope, yet `src/auth/oauth_migration.go` ships 42 lines of exactly that migration. Scope creep. `location: PR-body:out-of-scope-item-1`.

Summary bullet 2 (retry/backoff) IS implemented by the diff and must NOT trigger a finding.

<!-- expected: {
  "expected_finding_count": 3,
  "title_alignment": "off_target",
  "summary_alignment": "missing_claim",
  "out_of_scope": "scope_creep",
  "required_sections": ["## PR Title", "## PR Body", "## PR Diff (excerpt)", "## Out of scope"]
} -->

