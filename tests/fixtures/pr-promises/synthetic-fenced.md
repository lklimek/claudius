# Pass C fixture — fully-fenced PR body

Exercises the **fenced-body unwrap** heuristic: the entire PR body is wrapped in
a single code fence, so the column-0-anchored Summary/Out-of-scope regexes match
nothing until the outer fence is stripped and the content dedented.

## PR Title

```
feat(resolver): add LRU caching layer
```

## PR Body (raw — wholly fenced)

The body as received from the API is a single fenced block. The `## Summary`
and `## Out of scope` headers below sit INSIDE the fence:

```
    # Add caching layer to the resolver

    ## Summary

    - Add an LRU cache to `Resolver::lookup`
    - Expose `CacheConfig` with a configurable capacity

    ## Out of scope

    - Distributed cache backends (separate PR)
```

## Expected Pass C behaviour

After the fenced-body unwrap (strip outer fence + dedent), the `## Summary`
header becomes visible at column 0 and the two bullets are extracted normally;
the out-of-scope item is enforced against the diff. No unparseable-body finding
is emitted because the dedent exposes a real Summary header. The
`expected_finding_count` below reflects the documented dedent rule, not an
executed audit (no diff is supplied).

<!-- expected: {
  "expected_finding_count": 0,
  "title_alignment": "aligned",
  "summary_alignment": "aligned",
  "out_of_scope": "aligned",
  "required_sections": ["## PR Title", "## PR Body (raw — wholly fenced)"]
} -->
