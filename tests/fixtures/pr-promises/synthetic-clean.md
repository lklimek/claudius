# Pass C fixture — clean PR

Title, Summary, and out-of-scope claims all align with the diff. Expected output: zero `PPM-` findings.

## PR Title

```
feat(grpc): add retry/backoff to client transport
```

## PR Body

```markdown
## Summary

- Add an exponential-backoff retry loop to `grpc.Client.Call` (3 attempts, 100ms base).
- Add `TestRetryOnTransientFailure` covering the new retry path.

## Out of scope

- In-memory response cache — deferred to a follow-up PR.
- Auth/OAuth2 migration — tracked in #999.
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

diff --git a/tests/grpc/retry_test.go b/tests/grpc/retry_test.go
@@ -0,0 +1,24 @@
+package grpc_test
+
+func TestRetryOnTransientFailure(t *testing.T) {
+    // ... exercises the new retry loop ...
+}
```

## Expected Pass C findings

None. The title topic (`grpc retry/backoff`) is exercised by both production and test diff hunks; every Summary bullet maps to a hunk; neither out-of-scope item appears in the diff.

<!-- expected: {
  "expected_finding_count": 0,
  "title_alignment": "aligned",
  "summary_alignment": "aligned",
  "out_of_scope": "aligned",
  "required_sections": ["## PR Title", "## PR Body", "## PR Diff (excerpt)", "## Out of scope"]
} -->

