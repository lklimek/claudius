#!/usr/bin/env python3
"""ghsu — GitHub Sudo: re-execute commands with an elevated GitHub token.

Two-token model: Claude normally uses a read-only token. When a command gets
HTTP 403 (Forbidden), ghsu re-runs it with a stored read-write token after
the user confirms via GUI popup or terminal prompt.

Supports per-organization tokens: each GitHub org/owner gets its own encrypted
token file. The org is auto-detected from command arguments or git remotes.

Token is stored AES-256-GCM encrypted, keyed to machine characteristics.
"""

from __future__ import annotations

import getpass
import hashlib
import os
import platform
import re
import shlex
import socket
import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PREFIX = "[ghsu]"
_VERSION_BYTE = b"\x01"
_PBKDF2_SALT = b"ghsu-claudius-token-encryption-v1"
_PBKDF2_ITERATIONS = 600_000
_NONCE_LEN = 12  # 96-bit nonce for AES-GCM
_GUI_TIMEOUT = 60  # seconds — dialog auto-denies if user doesn't respond

_CONFIG_DIR = Path.home() / ".config" / "ghsu"
_TOKENS_DIR = _CONFIG_DIR / "tokens"

_README_URL = "https://github.com/lklimek/claudius#ghsu--elevated-github-access"

# Exit codes
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_DENIED = 2
EXIT_NO_INTERACTIVE = 3
EXIT_NO_TOKEN = 4


_VERBOSE = os.environ.get("GHSU_DEBUG", "") != ""
_T0 = time.monotonic()


def _err(msg: str) -> None:
    print(f"{_PREFIX} {msg}", file=sys.stderr)


def _info(msg: str) -> None:
    print(f"{_PREFIX} {msg}", file=sys.stderr)


def _debug(msg: str) -> None:
    if _VERBOSE:
        elapsed = time.monotonic() - _T0
        print(f"{_PREFIX} [{elapsed:6.3f}s] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Machine key derivation
# ---------------------------------------------------------------------------


def _get_machine_id() -> str | None:
    """Return a stable, platform-specific machine identifier."""
    system = platform.system()

    if system == "Linux":
        for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            try:
                return Path(path).read_text().strip()
            except OSError:
                continue
        return None

    if system == "Darwin":
        try:
            out = subprocess.run(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in out.stdout.splitlines():
                if "IOPlatformUUID" in line:
                    return line.split('"')[-2]
        except (subprocess.SubprocessError, IndexError):
            pass
        return None

    if system == "Windows":
        # Try WMI first
        try:
            out = subprocess.run(
                ["wmic", "csproduct", "get", "UUID", "/value"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in out.stdout.splitlines():
                if line.startswith("UUID="):
                    return line.split("=", 1)[1].strip()
        except (subprocess.SubprocessError, FileNotFoundError):
            pass
        # Fallback: registry
        try:
            import winreg  # noqa: PLC0415

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
            ) as key:
                val, _ = winreg.QueryValueEx(key, "MachineGuid")
                return str(val)
        except Exception:  # noqa: BLE001
            pass
        return None

    return None


def _derive_machine_key() -> bytes:
    """Derive a 32-byte AES-256 key from stable machine identifiers."""
    _debug("deriving machine key")
    components: list[str] = []

    mid = _get_machine_id()
    if mid:
        components.append(mid)

    components.append(socket.gethostname())
    components.append(getpass.getuser())

    if not components:
        raise RuntimeError("Cannot derive machine key: no stable identifiers")

    raw = "|".join(components).encode("utf-8")
    key = hashlib.pbkdf2_hmac(
        "sha256", raw, _PBKDF2_SALT, _PBKDF2_ITERATIONS
    )
    _debug("machine key derived")
    return key


# ---------------------------------------------------------------------------
# Encryption (AES-256-GCM)
# ---------------------------------------------------------------------------


def _require_cryptography():
    """Import and return AESGCM, or exit with actionable message."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import (  # noqa: PLC0415
            AESGCM,
        )

        return AESGCM
    except ImportError:
        _err("Required package 'cryptography' not installed.")
        _err("Install it with:  pip install cryptography")
        sys.exit(EXIT_ERROR)


def _encrypt_token(token: str, key: bytes) -> bytes:
    AESGCM = _require_cryptography()
    nonce = os.urandom(_NONCE_LEN)
    ct = AESGCM(key).encrypt(nonce, token.encode("utf-8"), None)
    return _VERSION_BYTE + nonce + ct


def _decrypt_token(data: bytes, key: bytes) -> str:
    AESGCM = _require_cryptography()
    if len(data) < 1 + _NONCE_LEN + 1:
        raise ValueError("Token file is too short or corrupted")
    version = data[0:1]
    if version != _VERSION_BYTE:
        raise ValueError(f"Unknown token format version: {version!r}")
    nonce = data[1 : 1 + _NONCE_LEN]
    ct = data[1 + _NONCE_LEN :]
    return AESGCM(key).decrypt(nonce, ct, None).decode("utf-8")


# ---------------------------------------------------------------------------
# Token storage (per-org)
# ---------------------------------------------------------------------------

_ORG_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _validate_org_name(org: str) -> str:
    """Validate and normalize an org/owner name."""
    org = org.strip().lower()
    if not _ORG_NAME_RE.match(org):
        _err(f"Invalid org name: {org!r}")
        _err("Must match: letters, digits, dots, hyphens, underscores.")
        sys.exit(EXIT_ERROR)
    return org


def _token_path(org: str) -> Path:
    return _TOKENS_DIR / f"{org}.enc"


def _list_orgs() -> list[str]:
    """Return sorted list of orgs with stored tokens."""
    if not _TOKENS_DIR.exists():
        return []
    return sorted(p.stem for p in _TOKENS_DIR.glob("*.enc"))


def _save_token(org: str, token: str) -> None:
    key = _derive_machine_key()
    blob = _encrypt_token(token, key)
    _TOKENS_DIR.mkdir(parents=True, exist_ok=True)
    path = _token_path(org)
    path.write_bytes(blob)
    try:
        path.chmod(0o600)
    except OSError:
        pass  # Windows — rely on user-profile ACLs


def _load_token(org: str) -> str:
    path = _token_path(org)
    if not path.exists():
        orgs = _list_orgs()
        _err(f"ERROR: No token stored for org '{org}'.\n")
        if orgs:
            _err(f"Available orgs: {', '.join(orgs)}\n")
        _err("To set up a token, run:")
        _err(f"    python3 {Path(__file__).resolve()} --setup {org}\n")
        _err(
            "This will prompt you for a GitHub Personal Access Token with"
        )
        _err("write permissions and store it encrypted on this machine.\n")
        _err(f"See: {_README_URL}")
        sys.exit(EXIT_NO_TOKEN)

    key = _derive_machine_key()
    data = path.read_bytes()
    try:
        return _decrypt_token(data, key)
    except Exception:  # noqa: BLE001
        _err(f"Failed to decrypt token for org '{org}'.")
        _err(
            "Was it stored on a different machine, or did the hostname change?"
        )
        _err(f"Re-run:  python3 {Path(__file__).resolve()} --setup {org}")
        sys.exit(EXIT_ERROR)


# ---------------------------------------------------------------------------
# Org auto-detection
# ---------------------------------------------------------------------------


def _detect_org_from_args(cmd: list[str]) -> str | None:
    """Extract org from -R/--repo owner/repo in gh command args."""
    for i, arg in enumerate(cmd):
        if arg in ("-R", "--repo") and i + 1 < len(cmd):
            repo_arg = cmd[i + 1]
            if "/" in repo_arg:
                return repo_arg.split("/")[0].lower()
        # Handle --repo=owner/repo
        if arg.startswith("--repo="):
            repo_arg = arg.split("=", 1)[1]
            if "/" in repo_arg:
                return repo_arg.split("/")[0].lower()
        if arg.startswith("-R") and len(arg) > 2:
            repo_arg = arg[2:]
            if "/" in repo_arg:
                return repo_arg.split("/")[0].lower()
    return None


def _detect_org_from_git_remote() -> str | None:
    """Extract org from the current repo's origin remote."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None
        url = result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        return None

    # SSH: git@github.com:owner/repo.git
    m = re.match(r"git@github\.com:([^/]+)/", url)
    if m:
        return m.group(1).lower()

    # HTTPS: https://github.com/owner/repo.git
    m = re.match(r"https?://github\.com/([^/]+)/", url)
    if m:
        return m.group(1).lower()

    return None


def _detect_org(cmd: list[str]) -> str | None:
    """Auto-detect org from command args, then git remote."""
    org = _detect_org_from_args(cmd)
    if org:
        return org
    return _detect_org_from_git_remote()


# ---------------------------------------------------------------------------
# GUI approval dialogs
# ---------------------------------------------------------------------------


def _escape_for_applescript(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _escape_for_powershell(s: str) -> str:
    return s.replace("`", "``").replace('"', '`"').replace("$", "`$")


def _run_gui(cmd: list[str]) -> int | None:
    """Run a GUI command with timeout. Returns exit code, or None on failure.

    Properly kills the child process on timeout (subprocess.run doesn't).
    """
    _debug(f"gui: launching {cmd[0]}")
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        _debug(f"gui: {cmd[0]} not found")
        return None

    try:
        proc.wait(timeout=_GUI_TIMEOUT)
        _debug(f"gui: {cmd[0]} exited with {proc.returncode}")
        return proc.returncode
    except subprocess.TimeoutExpired:
        _debug(f"gui: {cmd[0]} timed out after {_GUI_TIMEOUT}s, killing")
        proc.kill()
        proc.wait()
        return None


def _format_approval_msg(cmd_str: str, org: str) -> str:
    return (
        "A GitHub command requires elevated (write) permissions.\n\n"
        f"Organization: {org}\n"
        f"Command to execute:\n  {cmd_str}\n\n"
        "Allow this command to run with elevated GitHub permissions?"
    )


def _ask_xmessage(cmd_str: str, org: str) -> bool | None:
    """Lightweight X11 dialog. Returns True=approved, False=denied, None=unavailable."""
    msg = _format_approval_msg(cmd_str, org)
    rc = _run_gui([
        "xmessage", "-center",
        "-xrm", "*international:true",
        "-xrm", "*form.message.Scroll:WhenNeeded",
        "-xrm", "*form.minimumWidth:500",
        "-buttons", "Allow:0,Deny:1",
        "-default", "Deny", msg,
    ])
    if rc is None:
        return None
    return rc == 0


def _ask_zenity(cmd_str: str, org: str) -> bool | None:
    """Returns True=approved, False=denied, None=unavailable."""
    msg = _format_approval_msg(cmd_str, org)
    rc = _run_gui([
        "zenity", "--question",
        "--title=GitHub Elevated Access (ghsu)",
        f"--text={msg}", "--width=500",
        "--ok-label=Allow", "--cancel-label=Deny",
    ])
    if rc is None:
        return None  # not installed or timed out
    return rc == 0


def _ask_kdialog(cmd_str: str, org: str) -> bool | None:
    """Returns True=approved, False=denied, None=unavailable."""
    msg = _format_approval_msg(cmd_str, org)
    rc = _run_gui([
        "kdialog", "--title", "GitHub Elevated Access (ghsu)",
        "--yesno", msg,
        "--yes-label", "Allow", "--no-label", "Deny",
    ])
    if rc is None:
        return None
    return rc == 0


def _ask_osascript(cmd_str: str, org: str) -> bool | None:
    """Returns True=approved, False=denied, None=unavailable."""
    escaped = _escape_for_applescript(
        _format_approval_msg(cmd_str, org).replace("\n", "\\n")
    )
    # "cancel button" makes Deny return exit code 1.
    script = (
        f'display dialog "{escaped}" '
        f'buttons {{"Deny", "Allow"}} cancel button "Deny" '
        f'default button "Deny" '
        f'with title "GitHub Elevated Access (ghsu)" with icon caution'
    )
    rc = _run_gui(["osascript", "-e", script])
    if rc is None:
        return None
    return rc == 0


def _ask_powershell(cmd_str: str, org: str) -> bool | None:
    """Returns True=approved, False=denied, None=unavailable."""
    escaped = _escape_for_powershell(cmd_str)
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$r = [System.Windows.Forms.MessageBox]::Show("
        f"\"A GitHub command requires elevated (write) permissions."
        f"`n`nOrganization: {org}"
        f"`nCommand to execute:`n  {escaped}`n`n"
        f"Allow this command to run with elevated GitHub permissions?\","
        f"\"GitHub Elevated Access (ghsu)\","
        "[System.Windows.Forms.MessageBoxButtons]::YesNo,"
        "[System.Windows.Forms.MessageBoxIcon]::Warning); "
        'if ($r -eq "Yes") { exit 0 } else { exit 1 }'
    )
    rc = _run_gui(["powershell", "-Command", ps])
    if rc is None:
        return None
    return rc == 0


def _ask_terminal(cmd_str: str, org: str) -> bool:
    if not sys.stdin.isatty():
        return False
    _info("GitHub elevated access required.")
    _info(f"Organization: {org}")
    _info(f"Command: {cmd_str}")
    try:
        answer = input(f"{_PREFIX} Allow? (yes/no): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer in ("yes", "y")


def _has_display() -> bool:
    """Check if a graphical display is available."""
    system = platform.system()
    if system == "Darwin":
        return True  # macOS always has a window server when logged in
    if system == "Windows":
        return True
    # Linux/BSD: check DISPLAY or WAYLAND_DISPLAY
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _ask_approval(cmd_str: str, org: str, *, no_gui: bool = False) -> bool:
    """Ask the user to approve the command. Returns True if approved."""
    system = platform.system()
    _debug(f"approval: system={system}, no_gui={no_gui}, has_display={_has_display()}")

    if not no_gui and _has_display():
        gui_result = None
        if system == "Linux":
            # Try lightest first: xmessage → zenity → kdialog
            gui_result = _ask_xmessage(cmd_str, org)
            if gui_result is None:
                gui_result = _ask_zenity(cmd_str, org)
            if gui_result is None:
                gui_result = _ask_kdialog(cmd_str, org)
        elif system == "Darwin":
            gui_result = _ask_osascript(cmd_str, org)
        elif system == "Windows":
            gui_result = _ask_powershell(cmd_str, org)

        # If a GUI tool gave a definitive answer, use it (no terminal re-ask)
        if gui_result is not None:
            return gui_result

    # Terminal fallback (only reached if GUI unavailable/timed out)
    if _ask_terminal(cmd_str, org):
        return True

    if not sys.stdin.isatty():
        _err("Cannot request approval: no display and no terminal available.")
        sys.exit(EXIT_NO_INTERACTIVE)

    return False


# ---------------------------------------------------------------------------
# Token validation
# ---------------------------------------------------------------------------


def _validate_token(token: str) -> dict | None:
    """Validate a GitHub token by calling /user. Returns user info or None."""
    import json  # noqa: PLC0415
    from urllib.error import URLError  # noqa: PLC0415
    from urllib.request import Request, urlopen  # noqa: PLC0415

    req = Request(
        "https://api.github.com/user",
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "ghsu/1.0",
        },
    )
    try:
        with urlopen(req, timeout=10) as resp:  # noqa: S310
            data = json.loads(resp.read())
            return {"login": data.get("login", "unknown")}
    except (URLError, json.JSONDecodeError, KeyError):
        return None


def _get_token_scopes(token: str) -> str | None:
    """Get the OAuth scopes for a token."""
    from urllib.error import URLError  # noqa: PLC0415
    from urllib.request import Request, urlopen  # noqa: PLC0415

    req = Request(
        "https://api.github.com/user",
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "ghsu/1.0",
        },
    )
    try:
        with urlopen(req, timeout=10) as resp:  # noqa: S310
            return resp.headers.get("X-OAuth-Scopes", "")
    except URLError:
        return None


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def cmd_setup(org: str) -> int:
    """Store an encrypted GitHub PAT for a specific org."""
    org = _validate_org_name(org)
    path = _token_path(org)

    _info("GitHub Elevated Access — Token Setup")
    _info("")
    _info(f"Organization: {org}")
    _info("This will store an encrypted GitHub Personal Access Token")
    _info("for use when Claude needs write permissions.")
    _info("")
    _info("The token will be encrypted with a key derived from this")
    _info(f"machine's characteristics and stored in {path}")
    _info("")

    if path.exists():
        _info(f"A token for '{org}' is already stored.")
        try:
            answer = input(f"{_PREFIX} Overwrite? (yes/no): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return EXIT_ERROR
        if answer not in ("yes", "y"):
            _info("Aborted.")
            return EXIT_ERROR

    try:
        token = getpass.getpass(f"{_PREFIX} Paste your GitHub PAT (input hidden): ")
    except (EOFError, KeyboardInterrupt):
        _info("\nAborted.")
        return EXIT_ERROR

    if not token.strip():
        _err("Empty token. Aborted.")
        return EXIT_ERROR
    token = token.strip()

    _info("Verifying token...")
    user_info = _validate_token(token)
    if not user_info:
        _err("Token validation failed. Check that the token is valid.")
        return EXIT_ERROR

    scopes = _get_token_scopes(token) or "unknown"
    _info(f"OK (user: {user_info['login']}, scopes: {scopes})")

    _save_token(org, token)
    _info(f"Token for '{org}' encrypted and saved.")
    return EXIT_OK


def cmd_run(cmd: list[str], *, org: str | None = None, no_gui: bool = False) -> int:
    """Show approval dialog, then re-execute command with elevated token."""
    if not cmd:
        _err("No command specified.")
        _err(f"Usage: ghsu.py <command...>")
        return EXIT_ERROR

    # Determine org
    _debug("detecting org")
    if not org:
        org = _detect_org(cmd)
    _debug(f"org={org}")
    if not org:
        orgs = _list_orgs()
        if len(orgs) == 1:
            org = orgs[0]
            _info(f"Auto-selected org: {org} (only one configured)")
        elif orgs:
            _err("Cannot determine target organization.\n")
            _err(f"Available orgs: {', '.join(orgs)}")
            _err("Use --org <name> to specify, e.g.:")
            _err(f"    ghsu.py --org {orgs[0]} {shlex.join(cmd)}")
            return EXIT_ERROR
        else:
            _err("No tokens configured.\n")
            _err("To set up a token, run:")
            _err(f"    python3 {Path(__file__).resolve()} --setup <org>")
            _err(f"\nSee: {_README_URL}")
            sys.exit(EXIT_NO_TOKEN)

    org = _validate_org_name(org)

    # Verify token exists before asking the user for approval
    _debug("loading token")
    token = _load_token(org)
    _debug("token loaded")

    cmd_str = shlex.join(cmd)

    _debug("requesting approval")
    if not _ask_approval(cmd_str, org, no_gui=no_gui):
        _info("Permission denied by user.")
        return EXIT_DENIED
    _debug("approved, executing command")

    env = os.environ.copy()
    env["GH_TOKEN"] = token
    env["GITHUB_TOKEN"] = token

    result = subprocess.run(cmd, env=env)  # noqa: S603
    _debug(f"command exited with {result.returncode}")
    return result.returncode


def cmd_verify(org: str | None = None) -> int:
    """Verify stored token(s) can be decrypted and are valid."""

    if org:
        return _verify_one(_validate_org_name(org))

    # Verify all
    orgs = _list_orgs()
    if not orgs:
        _err("No tokens stored.")
        _err(f"Run:  python3 {Path(__file__).resolve()} --setup <org>")
        return EXIT_NO_TOKEN

    failures = 0
    for o in orgs:
        _info(f"--- {o} ---")
        if _verify_one(o) != EXIT_OK:
            failures += 1

    if failures:
        _err(f"\n{failures}/{len(orgs)} token(s) failed verification.")
        return EXIT_ERROR

    _info(f"\nAll {len(orgs)} token(s) verified OK.")
    return EXIT_OK


def _verify_one(org: str) -> int:
    """Verify a single org's token."""
    token = _load_token(org)
    _info(f"Token for '{org}' decrypted successfully.")
    _info("Validating against GitHub API...")

    user_info = _validate_token(token)
    if not user_info:
        _err(f"Token for '{org}' rejected by GitHub. It may be expired.")
        _err(f"Re-run:  python3 {Path(__file__).resolve()} --setup {org}")
        return EXIT_ERROR

    scopes = _get_token_scopes(token) or "unknown"
    _info(f"OK (user: {user_info['login']}, scopes: {scopes})")
    return EXIT_OK


def cmd_revoke(org: str | None = None) -> int:
    """Delete stored encrypted token(s)."""

    if org:
        return _revoke_one(_validate_org_name(org))

    # Revoke all
    orgs = _list_orgs()
    if not orgs:
        _info("No tokens stored. Nothing to revoke.")
        return EXIT_OK

    _info(f"This will revoke tokens for: {', '.join(orgs)}")
    if sys.stdin.isatty():
        try:
            answer = input(f"{_PREFIX} Revoke all? (yes/no): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return EXIT_ERROR
        if answer not in ("yes", "y"):
            _info("Aborted.")
            return EXIT_ERROR

    for o in orgs:
        _revoke_one(o)

    return EXIT_OK


def _revoke_one(org: str) -> int:
    """Delete a single org's token."""
    path = _token_path(org)
    if not path.exists():
        _info(f"No token found for '{org}'. Nothing to revoke.")
        return EXIT_OK

    path.unlink()
    _info(f"Token for '{org}' deleted.")

    # Clean up empty dirs
    try:
        _TOKENS_DIR.rmdir()
    except OSError:
        pass
    try:
        _CONFIG_DIR.rmdir()
    except OSError:
        pass

    return EXIT_OK


def cmd_list() -> int:
    """List organizations with stored tokens."""
    orgs = _list_orgs()
    if not orgs:
        _info("No tokens stored.")
        _info(f"Run:  python3 {Path(__file__).resolve()} --setup <org>")
        return EXIT_OK

    _info(f"Stored tokens ({len(orgs)}):")
    for org in orgs:
        _info(f"  {org}")
    return EXIT_OK


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

_USAGE = """\
usage: ghsu.py [options] <command...>
       ghsu.py --setup <org>
       ghsu.py --list | --verify [org] | --revoke [org]

GitHub Sudo — re-execute commands with per-org elevated tokens.

Anything not prefixed with -- is the command to run:
  ghsu.py gh pr merge 123
  ghsu.py --org dashpay gh pr list

Options:
  --org ORG       Target org (auto-detected from -R flag or git remote)
  --no-gui        Skip GUI dialog, use terminal prompt only
  --setup ORG     Store encrypted GitHub PAT for an org
  --verify [ORG]  Verify stored token(s)
  --revoke [ORG]  Revoke stored token(s)
  --list          List orgs with stored tokens
  -h, --help      Show this help
"""


def main() -> int:
    argv = sys.argv[1:]

    if not argv or "-h" in argv or "--help" in argv:
        print(_USAGE, file=sys.stderr)
        return EXIT_OK if ("-h" in argv or "--help" in argv) else EXIT_ERROR

    # Parse -- flags, collect the rest as the command
    org: str | None = None
    no_gui = False
    cmd: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--setup":
            if i + 1 >= len(argv):
                _err("--setup requires an org name.")
                return EXIT_ERROR
            return cmd_setup(argv[i + 1])
        elif arg == "--list":
            return cmd_list()
        elif arg == "--verify":
            verify_org = argv[i + 1] if i + 1 < len(argv) and not argv[i + 1].startswith("--") else None
            return cmd_verify(verify_org)
        elif arg == "--revoke":
            revoke_org = argv[i + 1] if i + 1 < len(argv) and not argv[i + 1].startswith("--") else None
            return cmd_revoke(revoke_org)
        elif arg == "--org":
            if i + 1 >= len(argv):
                _err("--org requires an org name.")
                return EXIT_ERROR
            org = argv[i + 1]
            i += 2
            continue
        elif arg == "--no-gui":
            no_gui = True
            i += 1
            continue
        else:
            # Everything from here on is the command
            cmd = argv[i:]
            break
        i += 1

    return cmd_run(cmd, org=org, no_gui=no_gui)


if __name__ == "__main__":
    sys.exit(main())
