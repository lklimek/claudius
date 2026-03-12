# TypeScript / JavaScript Security Patterns

Concrete attack patterns to hunt for during TypeScript/JavaScript code review.
Complements the OWASP checklists with TS/JS-specific concerns.

## Attack Patterns

### Injection & Code Execution

- **eval/Function**: `eval()`, `new Function()`, `setTimeout(string)`, `setInterval(string)` with dynamic input
- **Command Injection**: `child_process.exec()` or `child_process.execSync()` with user input; prefer `execFile()` or `spawn()` which bypass the shell. Watch for shell metacharacters: `;`, `|`, `$()`, backticks, `>`, `<`
- **Template Literal Injection**: user input interpolated into template literals via `${...}` can achieve RCE when combined with `eval()`, `exec()`, or server-side template engines (Nunjucks, EJS, Pug). CSS-to-JS module converters (e.g., esm.sh `?module`) have been exploited this way (GHSA-hcpf-qv9m-vfgp)
- **Server-Side Template Injection (SSTI)**: Nunjucks, EJS, Pug, Handlebars rendering user-controlled strings as templates
- **SQL/NoSQL Injection**: string concatenation in queries; for MongoDB watch `$where`, `$regex`, `$gt` operator injection via JSON body parsing

### Prototype & Object Manipulation

- **Prototype Pollution**: `Object.assign()`, spread operator, deep merge/clone (lodash `_.merge`, `_.defaultsDeep`, `_.set`), or recursive key assignment with user-controlled keys. Check for `__proto__`, `constructor`, `prototype` in input. Lodash <= 4.17.22 `_.omit`/`_.unset` vulnerable (CVE-2025-13465)
- **Constructor Pollution via Deserialization**: `JSON.parse()` is safe, but libraries like `node-serialize`, `serialize-to-js`, `devalue` can enable RCE through IIFE injection or prototype manipulation (CVE-2025-57820). Never deserialize untrusted data with libraries that reconstruct functions
- **Mass Assignment**: Express/Koa body parsers passing `req.body` directly to ORM create/update without field allowlisting

### XSS & DOM Attacks

- **XSS via DOM APIs**: `innerHTML`, `outerHTML`, `document.write()`, `insertAdjacentHTML()` with unsanitized input
- **React XSS**: `dangerouslySetInnerHTML` without DOMPurify sanitization, `javascript:` protocol in `href` attributes bypasses React's auto-escaping, ref-based DOM manipulation
- **React Server Components RCE**: CVE-2025-55182 (CVSS 10.0) — RSC Flight payload decoding flaw in React 19.0–19.2.0; affects Next.js, React Router, Waku. Upgrade to React >= 19.0.1/19.1.2/19.2.1
- **DOM Clobbering**: user-controlled `id`/`name` attributes overriding global variables via `document.getElementById` or named access on `window`
- **Vue XSS**: `v-html` directive with unsanitized content; server-side rendering template injection
- **Angular XSS**: DOM sanitizer bypass via SVG/MathML attributes (CVE-2025-66412 in Angular <= 21.0.1)

### Path Traversal & File System

- **Path Traversal**: `path.join()`, `path.resolve()` with user input in `fs.*` operations; `../` sequences escaping intended directory. Always validate resolved path starts with expected base directory
- **Symlink Attacks**: Node.js permission model bypass via crafted symlink chains (CVE in Node.js 20.x/22.x); use `fs.realpath()` before access checks
- **File Descriptor Misuse**: `fs.fchown`/`fs.fchmod` on read-only descriptors can change permissions (Node.js permission model bypass)

### Network & SSRF

- **SSRF in Node.js**: user-supplied URLs passed to `fetch()`, `axios`, `http.get()`, `got`, `node-fetch` without validation. Block private IP ranges, `file://` scheme, DNS rebinding. Check redirect chains — initial domain may resolve to public IP but redirect to internal
- **Next.js SSRF**: Server Actions building internal URLs from `Host` header (CVE-2024-34351, fixed 14.1.1). Middleware reflecting sensitive headers via `NextResponse.next()` (CVE-2025-57822, fixed 14.2.32/15.4.7)
- **Next.js Middleware Auth Bypass**: `x-middleware-subrequest` header spoofing bypasses authorization middleware (CVE-2025-29927, affects 11.1.4–15.2.2)
- **DNS Rebinding**: SSRF protections that validate IP only at DNS resolution time can be bypassed if attacker-controlled DNS returns different IPs on subsequent lookups

### Type System & Coercion

- **Type Coercion Bypass**: loose equality `==` enabling auth/validation bypass (e.g., `"0" == false`, `[] == false`, `null == undefined`). Always use strict equality `===`
- **Type Confusion**: Express `req.query`/`req.body` values may be strings, arrays, or objects depending on input; missing type checks enable injection or logic bypass. Use schema validation (Zod, Joi, ajv)
- **parseInt Gotchas**: `parseInt("08")` octal issues, `parseInt("123abc")` silently ignoring trailing chars; use `Number()` or `Number.parseInt()` with radix

### Denial of Service

- **ReDoS**: complex regex patterns with nested quantifiers on user input (e.g., `(.*)+`, `(a|aa)+`, `([a-z]+)*`). Single-threaded Node.js event loop blocks entirely during exponential backtracking. Use `re2` library or enforce input length limits
- **Event Loop Blocking**: synchronous operations (`fs.readFileSync`, `crypto.pbkdf2Sync`, CPU-intensive JSON parsing) in request handlers blocking all concurrent requests
- **Zip/Decompression Bombs**: unchecked decompression of user uploads via `zlib`, `tar`, `unzip` exhausting memory/disk
- **GraphQL Abuse**: deeply nested queries, alias-based batching, and unbounded list queries without depth/complexity limits

### Supply Chain & Dependencies

- **Dependency Risk**: unpinned deps without lockfile, `postinstall`/`preinstall` scripts in dependencies executing arbitrary code on `npm install`
- **Typosquatting**: malicious packages with names similar to popular ones (e.g., `expres` vs `express`, `lodahs` vs `lodash`)
- **Maintainer Account Compromise**: phishing campaigns targeting npm maintainers (Sep 2025 attack compromised 18 packages with 2B+ weekly downloads). Verify package provenance, use npm `--ignore-scripts` in CI
- **Polyfill.io Supply Chain Attack**: domain acquisition weaponizing trusted CDN-hosted polyfills (Jun 2024, 100K+ sites affected). Self-host or use SRI for third-party scripts
- **Worm Propagation**: Shai-Hulud npm worm (2024–2025) — self-replicating via stolen credentials, GitHub Actions injection, pre-install hooks. Audit CI workflows for unexpected steps
- **Dependency Confusion**: private package names published to public npm registry; configure `.npmrc` with scoped registry mappings

### Authentication & Session

- **JWT Misuse**: `algorithm: "none"` bypass, symmetric/asymmetric key confusion (RS256 vs HS256), missing expiration validation, secrets in client-side code
- **Cookie Misconfiguration**: missing `Secure`, `HttpOnly`, `SameSite` attributes; overly broad `Domain`/`Path` scope
- **Timing Attacks**: string comparison for tokens/secrets using `===` instead of `crypto.timingSafeEqual()`

### Secrets & Configuration

- **Hardcoded Secrets**: API keys, tokens, passwords in source; `.env` files committed to git
- **Environment Variable Leakage**: `process.env` serialized to client bundles (Next.js `NEXT_PUBLIC_*` prefix, Vite `VITE_*` prefix expose to browser); server-only secrets must never use these prefixes
- **Source Map Exposure**: production deployments serving `.map` files revealing original source code

## Security Scanners

| Category | Tools |
|----------|-------|
| SAST | eslint-plugin-security, semgrep, CodeQL, SonarJS |
| Dependency Scan | npm audit, snyk, socket.dev, Dependabot |
| Secret Scan | gitleaks, truffleHog, GitHub secret scanning |
| Type Safety | TypeScript strict mode, Zod/Joi for runtime validation |
| ReDoS Detection | re2 (safe regex engine), eslint-plugin-security `detect-unsafe-regex` |
| Supply Chain | socket.dev (install-time behavior analysis), npm `--ignore-scripts`, lockfile-lint |
| Framework-Specific | next-safe-action (Next.js), helmet (Express headers) |
