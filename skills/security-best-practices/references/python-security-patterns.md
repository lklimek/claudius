# Python Security Patterns

Read when reviewing Python code: non-obvious, library/version-specific traps.

## Attack Patterns

### Injection & Deserialization

- **`str.format()` / `format_map()` on user-controlled strings** leaks attributes (`{obj.__init__.__globals__}`); use `string.Template`.
- **Pickle variants**: `dill`, `jsonpickle`, `shelve`, `cloudpickle`, `joblib.load`, `numpy.load(allow_pickle=True)`, `torch.load()` without `weights_only=True` — same RCE as pickle.

### Files & Archives

- **`tarfile.extract/extractall`** without member filtering (`filter=`): path escape (CVE-2007-4559); symlink-based filter bypasses (CVE-2024-12718, CVE-2025-4330).
- **`zipfile`**: `extract()` sanitizes, but code that joins `ZipInfo.filename` itself is traversable.
- **`tempfile.mktemp()`**: TOCTOU race; use `mkstemp`/`NamedTemporaryFile`/`TemporaryDirectory`.
- **Check-then-act** (`os.path.exists()` then `open()`): use `os.open(..., O_CREAT|O_EXCL)` or locking.

### XML

- **Stdlib XML** (`xml.etree`, `xml.sax`, `xml.dom.minidom`, `xml.dom.pulldom`): no external-entity (XXE) resolution by default, but entity-expansion DoS (billion laughs, quadratic blowup) depends on the linked Expat version; use `defusedxml` for untrusted input. Classic XXE needs an explicitly enabled feature or `lxml`.
- **`lxml`**: parser needs `resolve_entities=False, no_network=True`.

### Network & SSRF

- **`requests`** follows redirects by default — redirect hops bypass URL validation; set `allow_redirects=False` or validate each hop.
- **IP-literal bypass**: `127.0.0.1` as hex/octal/mapped-IPv6; resolve DNS first, then check the resolved IP.
- **`urllib.request.urlopen`** accepts `file://`, `ftp://`, `gopher://`.

### Auth

- **PyJWT / python-jose algorithm confusion** (CVE-2022-29217, CVE-2024-33663): always pass explicit `algorithms=[...]` to `jwt.decode()`.

### Runtime

- **`assert`** is stripped under `python -O`; never use for authz/validation.
- **Regex DoS**: nested/complex regex on user input without timeout; use `re2` (note: stdlib `re` has no `re.TIMEOUT`).
- **asyncio**: shared state across `await` without `asyncio.Lock`; CVE-2024-3219 (socket module); CVE-2024-12254 — `_SelectorSocketTransport.writelines()` ignores the high-water mark, unbounded buffer growth (3.12.0–3.12.8, 3.13.0–3.13.1; fixed in 3.12.9 / 3.13.2).
- **Log forging / secrets in logs**: newlines in logged input; `__repr__`/`__str__` of user objects leaking tokens or PII.

### Supply Chain

- **Dependency confusion**: internal names shadowed on public PyPI; pin the index (`--index-url`) or use a private index with priority.
- **`setup.py`** executes at install time; prefer wheels.
