---
name: security-best-practices
description: >
  Secure programming best practices based on the OWASP Cheat Sheet Series. Use this skill
  whenever writing, reviewing, or discussing application security, input validation, authentication,
  authorization, cryptography, session management, error handling, logging, or any code that handles
  user input, secrets, HTTP headers, file uploads, or API endpoints. Also use when someone asks about
  preventing common vulnerabilities (XSS, SQL injection, CSRF, SSRF, etc.), securing infrastructure
  (Docker, Kubernetes, CI/CD), or reviewing dependencies for supply chain risks. This skill should be
  consulted proactively during code review and security audit tasks, even if the user does not
  explicitly mention security.
model: opus
allowed-tools: WebFetch, WebSearch
---

# Secure Programming Best Practices

Actionable security checklists organized by OWASP Top 10 (2021) categories. Each item links to the
relevant OWASP Cheat Sheet for detailed guidance.

When you need more detail on a specific topic, fetch the linked cheat sheet URL.

## How to Use

1. Identify which categories are relevant to the code being written or reviewed
2. Walk through the checklist items for those categories
3. **Fetch the linked OWASP cheat sheet for every checklist item that could be relevant** —
   do not rely solely on the checklist summaries here; load the full cheat sheet to get
   detailed, up-to-date guidance. When in doubt about relevance, fetch it.
4. For framework-specific guidance, see the [Framework-Specific Security](#framework-specific-security)
   section and fetch the corresponding cheat sheet
5. Always include OWASP cheat sheet URLs in your output so the reader can follow up

Base URL for all cheat sheets: `https://cheatsheetseries.owasp.org/cheatsheets/`

---

## A01: Broken Access Control

- [ ] Deny access by default; require explicit grants
  ([Access Control](https://cheatsheetseries.owasp.org/cheatsheets/Access_Control_Cheat_Sheet.html))
- [ ] Enforce authorization server-side; never rely on client-side checks
  ([Authorization](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html))
- [ ] Use indirect object references or validate ownership before returning resources
  ([IDOR Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Insecure_Direct_Object_Reference_Prevention_Cheat_Sheet.html))
- [ ] Apply rate limiting and account lockout to prevent brute-force
- [ ] Log all access control failures and alert on repeated attempts
- [ ] Invalidate sessions and tokens on logout and password change
  ([Session Management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html))
- [ ] Validate CORS configuration; avoid `Access-Control-Allow-Origin: *` for authenticated endpoints
  ([HTTP Headers](https://cheatsheetseries.owasp.org/cheatsheets/HTTP_Headers_Cheat_Sheet.html))
- [ ] For multi-tenant systems, enforce tenant isolation at every data access layer
  ([Multi-Tenant Security](https://cheatsheetseries.owasp.org/cheatsheets/Multi_Tenant_Security_Cheat_Sheet.html))

## A02: Cryptographic Failures

- [ ] Use TLS 1.2+ for all data in transit; disable older protocols
  ([TLS](https://cheatsheetseries.owasp.org/cheatsheets/Transport_Layer_Security_Cheat_Sheet.html))
- [ ] Enable HSTS with `includeSubDomains` and adequate `max-age`
  ([HSTS](https://cheatsheetseries.owasp.org/cheatsheets/HTTP_Strict_Transport_Security_Cheat_Sheet.html))
- [ ] Use strong, modern algorithms (AES-256-GCM, ChaCha20-Poly1305); avoid DES, RC4, MD5, SHA-1
  ([Cryptographic Storage](https://cheatsheetseries.owasp.org/cheatsheets/Cryptographic_Storage_Cheat_Sheet.html))
- [ ] Store passwords with Argon2id, bcrypt, or scrypt — never plain hashes
  ([Password Storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html))
- [ ] Manage secrets through a vault or environment variables; never hardcode
  ([Secrets Management](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html))
- [ ] Rotate keys on a defined schedule; support key versioning
  ([Key Management](https://cheatsheetseries.owasp.org/cheatsheets/Key_Management_Cheat_Sheet.html))

## A03: Injection

- [ ] Validate all input: type, length, range, format; use allowlists over denylists
  ([Input Validation](https://cheatsheetseries.owasp.org/cheatsheets/Input_Validation_Cheat_Sheet.html))
- [ ] Use parameterized queries or prepared statements for all SQL
  ([SQL Injection Prevention](https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html),
  [Query Parameterization](https://cheatsheetseries.owasp.org/cheatsheets/Query_Parameterization_Cheat_Sheet.html))
- [ ] Context-escape all output: HTML-encode for HTML, JS-encode for JavaScript, URL-encode for URLs
  ([XSS Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html),
  [DOM-based XSS Prevention](https://cheatsheetseries.owasp.org/cheatsheets/DOM_based_XSS_Prevention_Cheat_Sheet.html))
- [ ] Avoid OS command execution; if unavoidable, use strict allowlists and no shell interpolation
  ([OS Command Injection Defense](https://cheatsheetseries.owasp.org/cheatsheets/OS_Command_Injection_Defense_Cheat_Sheet.html))
- [ ] Sanitize LDAP input using established escape functions
  ([LDAP Injection Prevention](https://cheatsheetseries.owasp.org/cheatsheets/LDAP_Injection_Prevention_Cheat_Sheet.html))
- [ ] Deploy Content Security Policy to mitigate XSS impact
  ([CSP](https://cheatsheetseries.owasp.org/cheatsheets/Content_Security_Policy_Cheat_Sheet.html))
- [ ] Prevent DOM clobbering by avoiding `document.getElementById` on user-controllable IDs
  ([DOM Clobbering Prevention](https://cheatsheetseries.owasp.org/cheatsheets/DOM_Clobbering_Prevention_Cheat_Sheet.html))
- [ ] Guard against prototype pollution in JavaScript by freezing prototypes or using `Object.create(null)`
  ([Prototype Pollution Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Prototype_Pollution_Prevention_Cheat_Sheet.html))

## A04: Insecure Design

- [ ] Perform threat modeling early in the design phase
  ([Threat Modeling](https://cheatsheetseries.owasp.org/cheatsheets/Threat_Modeling_Cheat_Sheet.html))
- [ ] Identify and document abuse cases alongside use cases
  ([Abuse Case](https://cheatsheetseries.owasp.org/cheatsheets/Abuse_Case_Cheat_Sheet.html))
- [ ] Analyze and minimize the attack surface for each feature
  ([Attack Surface Analysis](https://cheatsheetseries.owasp.org/cheatsheets/Attack_Surface_Analysis_Cheat_Sheet.html))
- [ ] Follow secure product design principles: least privilege, defense in depth, fail secure
  ([Secure Product Design](https://cheatsheetseries.owasp.org/cheatsheets/Secure_Product_Design_Cheat_Sheet.html))

## A05: Security Misconfiguration

- [ ] Disable unnecessary features, ports, services, and default accounts
- [ ] Harden Docker containers: non-root user, read-only filesystem, minimal base image
  ([Docker Security](https://cheatsheetseries.owasp.org/cheatsheets/Docker_Security_Cheat_Sheet.html))
- [ ] Apply Kubernetes security best practices: pod security policies, network policies, RBAC
  ([Kubernetes Security](https://cheatsheetseries.owasp.org/cheatsheets/Kubernetes_Security_Cheat_Sheet.html))
- [ ] Scan IaC templates for misconfigurations before deployment
  ([IaC Security](https://cheatsheetseries.owasp.org/cheatsheets/Infrastructure_as_Code_Security_Cheat_Sheet.html))
- [ ] Disable XML external entity processing in all XML parsers
  ([XXE Prevention](https://cheatsheetseries.owasp.org/cheatsheets/XML_External_Entity_Prevention_Cheat_Sheet.html))
- [ ] Set security headers: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, etc.
  ([HTTP Headers](https://cheatsheetseries.owasp.org/cheatsheets/HTTP_Headers_Cheat_Sheet.html))
- [ ] Secure CI/CD pipelines: least-privilege tokens, signed artifacts, audit logs
  ([CI/CD Security](https://cheatsheetseries.owasp.org/cheatsheets/CI_CD_Security_Cheat_Sheet.html))

## A06: Vulnerable and Outdated Components

- [ ] Maintain an inventory of all dependencies and their versions
  ([Dependency Graph / SBOM](https://cheatsheetseries.owasp.org/cheatsheets/Dependency_Graph_SBOM_Cheat_Sheet.html))
- [ ] Continuously scan dependencies for known vulnerabilities
  ([Vulnerable Dependency Management](https://cheatsheetseries.owasp.org/cheatsheets/Vulnerable_Dependency_Management_Cheat_Sheet.html))
- [ ] Audit third-party JavaScript for integrity and behavior
  ([Third Party JS Management](https://cheatsheetseries.owasp.org/cheatsheets/Third_Party_Javascript_Management_Cheat_Sheet.html))
- [ ] Use lockfiles and verify package integrity hashes
  ([NPM Security](https://cheatsheetseries.owasp.org/cheatsheets/NPM_Security_Cheat_Sheet.html))
- [ ] Review supply chain security practices for critical dependencies
  ([Software Supply Chain Security](https://cheatsheetseries.owasp.org/cheatsheets/Software_Supply_Chain_Security_Cheat_Sheet.html))

## A07: Identification and Authentication Failures

- [ ] Enforce minimum password complexity and check against breached password lists
  ([Authentication](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html))
- [ ] Implement MFA for privileged and sensitive operations
  ([MFA](https://cheatsheetseries.owasp.org/cheatsheets/Multifactor_Authentication_Cheat_Sheet.html))
- [ ] Generate session IDs server-side with high entropy; regenerate after authentication
  ([Session Management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html))
- [ ] Secure password reset flows: time-limited tokens, side-channel verification
  ([Forgot Password](https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html))
- [ ] Prevent credential stuffing with rate limiting, CAPTCHA, and device fingerprinting
  ([Credential Stuffing Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Credential_Stuffing_Prevention_Cheat_Sheet.html))
- [ ] Implement OAuth 2.0 with PKCE for public clients
  ([OAuth 2.0](https://cheatsheetseries.owasp.org/cheatsheets/OAuth2_Cheat_Sheet.html))
- [ ] Set cookie attributes: `Secure`, `HttpOnly`, `SameSite`, proper `Path` and `Domain`
  ([Cookie Theft Mitigation](https://cheatsheetseries.owasp.org/cheatsheets/Cookie_Theft_Mitigation_Cheat_Sheet.html))

## A08: Software and Data Integrity Failures

- [ ] Never deserialize untrusted data; if required, validate schema and use safe libraries
  ([Deserialization](https://cheatsheetseries.owasp.org/cheatsheets/Deserialization_Cheat_Sheet.html))
- [ ] Protect against mass assignment: explicitly allowlist assignable fields
  ([Mass Assignment](https://cheatsheetseries.owasp.org/cheatsheets/Mass_Assignment_Cheat_Sheet.html))
- [ ] Validate file uploads: check type via magic bytes (not just extension or Content-Type header),
  enforce size limits, and re-encode/re-process content to strip metadata and neutralize polyglots.
  Store outside webroot with random names. **Explicitly reject dangerous types**: SVG (can contain
  embedded JavaScript), HTML, executable files (.exe, .sh, .bat), and server-side scripts (.php, .jsp).
  ([File Upload](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html))
- [ ] Verify integrity of software artifacts with checksums and signatures

## A09: Security Logging and Monitoring Failures

- [ ] Log authentication events, access control failures, input validation failures, and application errors
  ([Logging](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html))
- [ ] Use consistent log format and vocabulary for automated analysis
  ([Logging Vocabulary](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Vocabulary_Cheat_Sheet.html))
- [ ] Never log sensitive data: passwords, tokens, PII, credit card numbers
- [ ] Return generic error messages to users; log detailed errors server-side
  ([Error Handling](https://cheatsheetseries.owasp.org/cheatsheets/Error_Handling_Cheat_Sheet.html))
- [ ] Set up alerts for anomalous patterns: brute force, privilege escalation, unusual data access

## A10: Server-Side Request Forgery (SSRF)

- [ ] Validate and sanitize all user-supplied URLs
  ([SSRF Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html))
- [ ] Use allowlists for permitted domains and protocols
- [ ] Block requests to internal/private IP ranges (127.0.0.0/8, 10.0.0.0/8, 169.254.0.0/16, etc.)
- [ ] Disable unnecessary URL schemes (file://, gopher://, ftp://)
- [ ] Run server-side HTTP clients in network-restricted environments when possible

---

## API Security

- [ ] Authenticate and authorize every API request
  ([REST Security](https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html))
- [ ] Validate request content types and reject unexpected media types
- [ ] Apply rate limiting and request size limits
- [ ] For GraphQL: limit query depth and complexity; disable introspection in production
  ([GraphQL](https://cheatsheetseries.owasp.org/cheatsheets/GraphQL_Cheat_Sheet.html))
- [ ] For gRPC: use TLS, validate protobuf messages, implement interceptor-based auth
  ([gRPC Security](https://cheatsheetseries.owasp.org/cheatsheets/gRPC_Security_Cheat_Sheet.html))
- [ ] For WebSockets: validate origin, authenticate the handshake, validate all messages
  ([WebSocket Security](https://cheatsheetseries.owasp.org/cheatsheets/WebSocket_Security_Cheat_Sheet.html))
- [ ] Prevent CSRF with synchronizer tokens or SameSite cookies
  ([CSRF Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html))
- [ ] Validate redirect URLs against an allowlist
  ([Unvalidated Redirects](https://cheatsheetseries.owasp.org/cheatsheets/Unvalidated_Redirects_and_Forwards_Cheat_Sheet.html))

## AI and LLM Security

- [ ] Validate and sanitize all LLM inputs and outputs
  ([LLM Prompt Injection Prevention](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html))
- [ ] Apply least privilege to AI agent tool access and actions
  ([AI Agent Security](https://cheatsheetseries.owasp.org/cheatsheets/AI_Agent_Security_Cheat_Sheet.html))
- [ ] Secure model serving infrastructure: access controls, input limits, monitoring
  ([Secure AI Model Ops](https://cheatsheetseries.owasp.org/cheatsheets/Secure_AI_Model_Ops_Cheat_Sheet.html))

## Framework-Specific Security

When working with a specific framework, consult the relevant cheat sheet for framework-specific pitfalls and mitigations:

| Framework | Cheat Sheet |
|-----------|-------------|
| Django | [Django Security](https://cheatsheetseries.owasp.org/cheatsheets/Django_Security_Cheat_Sheet.html), [Django REST Framework](https://cheatsheetseries.owasp.org/cheatsheets/Django_REST_Framework_Cheat_Sheet.html) |
| Laravel | [Laravel](https://cheatsheetseries.owasp.org/cheatsheets/Laravel_Cheat_Sheet.html) |
| Symfony | [Symfony](https://cheatsheetseries.owasp.org/cheatsheets/Symfony_Cheat_Sheet.html) |
| Ruby on Rails | [Ruby on Rails](https://cheatsheetseries.owasp.org/cheatsheets/Ruby_on_Rails_Cheat_Sheet.html) |
| Node.js | [Node.js Security](https://cheatsheetseries.owasp.org/cheatsheets/Nodejs_Security_Cheat_Sheet.html), [Node.js Docker](https://cheatsheetseries.owasp.org/cheatsheets/NodeJS_Docker_Cheat_Sheet.html) |
| .NET | [.NET Security](https://cheatsheetseries.owasp.org/cheatsheets/DotNet_Security_Cheat_Sheet.html) |
| Java | [Java Security](https://cheatsheetseries.owasp.org/cheatsheets/Java_Security_Cheat_Sheet.html), [Injection Prevention in Java](https://cheatsheetseries.owasp.org/cheatsheets/Injection_Prevention_in_Java_Cheat_Sheet.html) |
| C/C++ | [C-Based Toolchain Hardening](https://cheatsheetseries.owasp.org/cheatsheets/C-Based_Toolchain_Hardening_Cheat_Sheet.html) |

## Additional References

For topics not covered above, browse the full index:
[OWASP Cheat Sheet Series Index](https://cheatsheetseries.owasp.org/)
