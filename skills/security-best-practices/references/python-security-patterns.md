# Python Security Patterns

Concrete attack patterns to hunt for during Python code review.
Complements the OWASP checklists with Python-specific concerns.

## Attack Patterns

### Code Execution & Injection

- **Code Injection**: `eval()`, `exec()`, `compile()`, `pickle.loads()`, `yaml.load()` (use `safe_load`)
- **Command Injection**: `os.system()`, `os.popen()`, `subprocess.call(shell=True)` with user input; use `subprocess.run()` with argument lists and `shell=False`
- **Template Injection**: unsanitized input in Jinja2/Mako templates; enable sandboxed environment or autoescaping
- **SQL Injection**: string formatting in queries instead of parameterized queries
- **Format String Attack**: `str.format()` / `str.format_map()` on user-controlled strings leaks attributes via `{obj.__init__.__globals__}` chains; use Template strings or sanitize format specs

### Deserialization

- **Pickle RCE**: `pickle.loads()`, `pickle.load()`, `_pickle`, `cPickle` on untrusted data enables arbitrary code execution via `__reduce__`; no safe subset exists
- **Pickle Variants**: `dill`, `jsonpickle`, `shelve`, `cloudpickle` carry the same RCE risk as pickle; treat all as unsafe for untrusted input
- **ML Model Loading**: `numpy.load(allow_pickle=True)`, `torch.load()` without `weights_only=True`, `joblib.load()` on untrusted files deserialize pickled objects
- **YAML Deserialization**: `yaml.load()` without `Loader=SafeLoader` allows arbitrary Python object construction; always use `yaml.safe_load()`

### File & Path Handling

- **Path Traversal**: file operations with user input without `os.path.realpath()` validation
- **Tar Slip (CVE-2007-4559, CVE-2024-12718, CVE-2025-4330)**: `tarfile.extractall()` / `tarfile.extract()` without member filtering allows overwriting files outside extraction directory; symlink-based filter bypass in Python 3.12+
- **Zip Slip**: `zipfile.extract()` is safe, but manually reading `ZipInfo.filename` without `os.path.basename()` sanitization enables path traversal
- **Insecure Temp Files**: `tempfile.mktemp()` has TOCTOU race condition; use `tempfile.NamedTemporaryFile()`, `tempfile.mkstemp()`, or `tempfile.TemporaryDirectory()` instead

### XML & Parsing

- **XXE (XML External Entity)**: stdlib `xml.etree.ElementTree`, `xml.sax`, `xml.dom.minidom`, `xml.dom.pulldom` are vulnerable to XXE and billion-laughs attacks; use `defusedxml` drop-in replacements
- **lxml XXE**: `lxml.etree.parse()` without `resolve_entities=False` and `no_network=True` on the parser allows entity expansion and external resource loading

### Network & SSRF

- **SSRF via Redirect**: `requests.get(url)` follows redirects by default (`allow_redirects=True`); attacker-controlled redirect targets bypass URL validation; validate each redirect hop or set `allow_redirects=False`
- **SSRF IP Bypass**: `ipaddress` normalization strips leading zeros; attackers encode `127.0.0.1` as hex/octal/mapped-IPv6 to evade naive blocklists; resolve DNS first, then validate the resolved IP against private ranges
- **Unrestricted URL Schemes**: `urllib.request.urlopen()` supports `file://`, `ftp://`, `gopher://` schemes; restrict to `https://` allowlist

### Authentication & Cryptography

- **JWT Algorithm Confusion (CVE-2022-29217, CVE-2024-33663)**: PyJWT / python-jose accept attacker-specified algorithm if `algorithms` param is not set; always pass explicit `algorithms=["RS256"]` (or equivalent) to `jwt.decode()`
- **Timing Attacks**: non-constant-time comparison for secrets (use `hmac.compare_digest`)
- **Weak Randomness**: `random` module for security-sensitive values (use `secrets`)

### Logic & Runtime

- **Assert Bypass**: `assert` statements are stripped in optimized mode (`python -O`); never use `assert` for security checks, input validation, or authorization — use `if`/`raise` instead
- **Regex DoS**: complex/nested regex on user input without timeout; use `re2` or set `re.TIMEOUT` (Python 3.11+)
- **TOCTOU Race Conditions**: check-then-act patterns (`os.path.exists()` then `open()`) are exploitable; use atomic operations (`os.open()` with `O_CREAT|O_EXCL`) or file locking
- **Asyncio Race Conditions**: shared mutable state accessed across `await` points without synchronization; use `asyncio.Lock` for critical sections (CVE-2024-3219 in socket module)
- **Memory Exhaustion (CVE-2024-12254)**: `asyncio._SelectorSocketTransport.writelines()` in Python 3.12+ does not pause at high-water mark; unbounded async write buffers can exhaust memory

### Supply Chain

- **Typosquatting**: misspelled package names on PyPI (`requsets`, `python-dateutils`, `termncolor`); verify package names and publishers before `pip install`
- **Dependency Confusion**: internal package names shadowed by malicious public PyPI packages; use `--index-url` pinning or private index with priority
- **Malicious setup.py**: packages executing code at install time via `setup.py`; audit install scripts, prefer wheels, use `--no-build-isolation` cautiously

### Logging

- **Log Injection**: unsanitized user input in log messages enables log forging (fake entries via `\n`) and log reader exploitation; sanitize newlines and control characters before logging
- **Sensitive Data in Logs**: logging f-strings or `.format()` with user objects may inadvertently log secrets, tokens, or PII via `__repr__`/`__str__`

## Security Scanners

| Category | Tools |
|----------|-------|
| SAST | bandit, semgrep, pylint (security rules), CodeQL, SonarQube |
| Dependency Scan | safety, pip-audit, pip-licenses, grype, trivy |
| Secret Scan | gitleaks, truffleHog, detect-secrets |
| Type Checking | mypy (strict mode catches type-confusion bugs) |
| Fuzzing | Atheris (coverage-guided Python fuzzer by Google) |
