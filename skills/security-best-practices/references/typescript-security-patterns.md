# TypeScript / JavaScript Security Patterns

Read when reviewing TS/JS code: non-obvious, framework/version-specific traps.

## Attack Patterns

### Injection & Prototype

- **Template literal injection**: `${...}` feeding `eval`/`exec`/server-side template engines (Nunjucks, EJS, Pug); CSS-to-JS converters such as esm.sh `?module` (GHSA-hcpf-qv9m-vfgp).
- **NoSQL operator injection**: MongoDB `$where`, `$regex`, `$gt` smuggled via JSON body parsing.
- **Prototype pollution**: lodash `_.merge`, `_.defaultsDeep`, `_.set`, plus `_.omit`/`_.unset` in lodash ≤ 4.17.22 (CVE-2025-13465); check `__proto__`/`constructor`/`prototype` keys in deep merge/clone.
- **Function-reconstructing deserializers**: `node-serialize`, `serialize-to-js`, `devalue` — IIFE/prototype RCE (CVE-2025-57820); `JSON.parse` itself is safe.
- **Mass assignment**: `req.body` passed straight to ORM create/update.

### Framework CVEs

- **React Server Components RCE** CVE-2025-55182 (CVSS 10.0): Flight payload decoding in React 19.0–19.2.0 (Next.js, React Router, Waku); fixed in 19.0.1/19.1.2/19.2.1.
- **Next.js middleware auth bypass** CVE-2025-29927: `x-middleware-subrequest` spoofing, 11.1.4–15.2.2.
- **Next.js SSRF**: Server Actions building URLs from `Host` (CVE-2024-34351, fixed 14.1.1); middleware reflecting headers via `NextResponse.next()` (CVE-2025-57822, fixed 14.2.32/15.4.7).
- **Angular** sanitizer bypass via SVG/MathML attributes (CVE-2025-66412, ≤ 21.0.1).
- **React**: `javascript:` URLs in `href` bypass auto-escaping.
- **DOM clobbering**: user-controlled `id`/`name` overriding globals via `getElementById`/named `window` access.

### Node.js Runtime

- **Permission model bypasses** (20.x/22.x): crafted symlink chains (resolve with `fs.realpath()` before checks); `fs.fchown`/`fs.fchmod` on read-only descriptors.
- **SSRF**: redirect chains from a public host to internal ones; DNS rebinding when the IP is validated only at resolution time.
- **Type confusion**: `req.query`/`req.body` values may be string, array or object — validate with a schema (Zod, Joi, ajv).
- **`parseInt`**: silently ignores trailing chars (`"123abc"`); pass a radix or use `Number()`.
- **Event-loop blocking**: `*Sync` fs/crypto calls and large JSON parsing in handlers; ReDoS stalls the whole process (`re2`).
- **GraphQL**: depth/complexity/alias-batching limits.

### Supply Chain

- **Install scripts**: `postinstall`/`preinstall` in dependencies; `--ignore-scripts` in CI.
- **Sep 2025 maintainer phishing**: 18 packages (2B+ weekly downloads) compromised — verify provenance.
- **Polyfill.io** (Jun 2024, 100K+ sites): CDN domain acquisition; self-host or use SRI.
- **Shai-Hulud worm** (2024–2025): spreads via stolen credentials, GitHub Actions injection, pre-install hooks — audit CI workflows for unexpected steps.
- **Dependency confusion**: scope-map registries in `.npmrc`.

### Config & Secrets

- **Client-bundle leakage**: `NEXT_PUBLIC_*` / `VITE_*` prefixes expose env vars to the browser.
- **Source maps**: production `.map` files expose original source.
- **`crypto.timingSafeEqual()`** for token comparison instead of `===`.
