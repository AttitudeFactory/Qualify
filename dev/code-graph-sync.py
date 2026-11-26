#!/usr/bin/env python3
"""Sync the CI-built graphify code graph to this machine (m-25129388).

`.github/workflows/code-graph.yml` builds the graph from the tip of main and publishes it as
assets of the fixed release `code-graph`. This script keeps one copy per clone and points
every linked worktree at it, so nobody ever runs `graphify update` by hand.

- Shared store: `<dirname of git's common dir>/graphify-out` — the main checkout's ignored
  `graphify-out/`, derived with git (override `QUALIFY_GRAPH_STORE`, used by the tests only).
- Link step (synchronous, milliseconds): in a linked worktree, `graphify-out/<file>` becomes a
  symlink to the store for each of FILES. File-level links work on old branches that still
  track files under `graphify-out/` and on new ones where the directory does not exist. A
  regular file already there (a worktree with its own local graph) is never replaced.
- Sync step: read the release's `code-graph.json`; when its commit differs from the one last
  installed, download `code-graph.tar.gz` and install it into the store through a temp dir in
  the store and `os.replace` (atomic per file). REST only (`gh api`): GraphQL is blocked in
  cloud sessions, and `gh release` uses it.

Guard rails: a lock (one download per clone at a time), a 30-minute throttle on GitHub calls
(marker in the store), and every failure path exits 0. When something is missing, ONE line
on stdout says what and how to fix it; otherwise silent.

Modes:
  (default)  SessionStart hook: read the hook JSON on stdin (`cwd`), link, start the sync
             detached in the background and return at once.
  --now      foreground: ignore the throttle, link, sync and print what it did.

Runs outside any venv on macOS and Linux: system `python3`, standard library only.
"""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

# The ONE place the graphify version is pinned: code-graph.yml reads it from this line.
GRAPHIFY_VERSION = "0.9.25"

REPO = "repos/AttitudeFactory/Qualify"
TAG = "code-graph"
META_ASSET = "code-graph.json"
TARBALL_ASSET = "code-graph.tar.gz"
FILES = ("graph.json", "GRAPH_REPORT.md", ".graphify_labels.json")
OUT_DIR = "graphify-out"
THROTTLE_SECONDS = 30 * 60
GH_TIMEOUT = 120

# Markers kept in the store (the main checkout's graphify-out/, ignored by git).
INSTALLED = ".code-graph-installed.json"
CHECKED = ".code-graph-checked"
HINT = ".code-graph-hint"
LOCK = ".code-graph.lock"

INSTALL_HINT = f"uv tool install graphifyy=={GRAPHIFY_VERSION}"

# Hooks launched from a desktop app may not inherit the login shell's PATH.
_EXTRA_PATH = (os.path.expanduser("~/.local/bin"), "/opt/homebrew/bin", "/usr/local/bin")


def _env() -> dict[str, str]:
    env = dict(os.environ)
    if env.get("CODE_GRAPH_EXACT_PATH"):  # tests: no fallback dirs, so a stub can be "missing"
        return env
    parts = [p for p in env.get("PATH", "").split(os.pathsep) if p]
    env["PATH"] = os.pathsep.join(parts + [p for p in _EXTRA_PATH if p not in parts])
    return env


def _which(name: str) -> str | None:
    return shutil.which(name, path=_env()["PATH"])


def _git(cwd: str, *args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", cwd, *args],
            capture_output=True,
            text=True,
            timeout=10,
            env=_env(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def resolve(start: str) -> tuple[str, str] | None:
    """(worktree root, shared store) for the checkout containing `start`, or None."""
    top = _git(start, "rev-parse", "--show-toplevel")
    common = _git(start, "rev-parse", "--git-common-dir")
    if not top or not common:
        return None
    if not os.path.isabs(common):
        common = os.path.join(start, common)
    store = os.environ.get("QUALIFY_GRAPH_STORE") or os.path.join(
        os.path.dirname(os.path.realpath(common)), OUT_DIR
    )
    return os.path.realpath(top), os.path.realpath(store)


def link(worktree: str, store: str) -> list[str]:
    """Point the worktree's graphify-out/<file> at the store; returns what changed."""
    out_dir = os.path.join(worktree, OUT_DIR)
    if os.path.realpath(out_dir) == store:
        return []  # this is the checkout that owns the store
    if os.path.islink(out_dir):
        return []  # someone linked the whole directory on purpose; leave it
    changed = []
    try:
        os.makedirs(out_dir, exist_ok=True)
    except OSError:
        return []
    for name in FILES:
        path = os.path.join(out_dir, name)
        target = os.path.join(store, name)
        if os.path.islink(path):
            if os.readlink(path) == target:
                continue
        elif os.path.lexists(path):
            continue  # a regular file: this worktree keeps its own graph
        tmp = f"{path}.link-{os.getpid()}"
        try:
            os.symlink(target, tmp)
            os.replace(tmp, path)
            changed.append(name)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    return changed


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def _write(path: str, text: str) -> None:
    tmp = f"{path}.tmp-{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def _installed_commit(store: str) -> str:
    try:
        return str(json.loads(_read(os.path.join(store, INSTALLED)) or "{}").get("commit", ""))
    except ValueError:
        return ""


def _throttled(store: str) -> bool:
    try:
        return time.time() - os.stat(os.path.join(store, CHECKED)).st_mtime < THROTTLE_SECONDS
    except OSError:
        return False


class GhError(Exception):
    def __init__(self, hint: str = "") -> None:
        super().__init__(hint)
        self.hint = hint


def _gh(*args: str, binary: bool = False) -> bytes:
    gh = _which("gh")
    if not gh:
        raise GhError("code-graph: the GitHub CLI `gh` is missing — run: brew install gh")
    try:
        out = subprocess.run(
            [gh, "api", *args], capture_output=True, timeout=GH_TIMEOUT, env=_env()
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise GhError() from exc
    if out.returncode == 0:
        return out.stdout
    err = out.stderr.decode("utf-8", "replace")
    if out.returncode == 4 or "auth login" in err:
        raise GhError("code-graph: `gh` is not authenticated — run: gh auth login")
    if "HTTP 404" in err and not binary:
        raise GhError("code-graph: no code graph published yet — run: just graph-build")
    raise GhError()


def _asset(release: dict, name: str) -> int:
    for asset in release.get("assets") or []:
        if asset.get("name") == name:
            return int(asset["id"])
    raise GhError("code-graph: no code graph published yet — run: just graph-build")


def _download(asset_id: int) -> bytes:
    return _gh(
        f"{REPO}/releases/assets/{asset_id}", "-H", "Accept: application/octet-stream", binary=True
    )


def _install(store: str, blob: bytes, meta: dict) -> None:
    """Extract only FILES from the tarball into a temp dir in the store, then rename.

    Files are written by hand (no `extractall`): nothing outside FILES, no links, no paths.
    Their mtime is the install time, not the build time: see the code-graph.yml header.
    """
    tmp = tempfile.mkdtemp(prefix=".code-graph-tmp-", dir=store)
    try:
        blob_path = os.path.join(tmp, TARBALL_ASSET)
        with open(blob_path, "wb") as fh:
            fh.write(blob)
        got = []
        with tarfile.open(blob_path, "r:gz") as tar:
            for member in tar.getmembers():
                name = member.name[2:] if member.name.startswith("./") else member.name
                if name not in FILES or not member.isfile():
                    continue
                src = tar.extractfile(member)
                if src is None:
                    continue
                with src, open(os.path.join(tmp, name), "wb") as dst:
                    shutil.copyfileobj(src, dst)
                got.append(name)
        if "graph.json" not in got or os.path.getsize(os.path.join(tmp, "graph.json")) == 0:
            raise GhError()
        for name in got:
            os.replace(os.path.join(tmp, name), os.path.join(store, name))
        _write(os.path.join(store, INSTALLED), json.dumps(meta, indent=2) + "\n")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def sync(store: str) -> str:
    """One check against the release; returns a human summary. Raises GhError."""
    os.makedirs(store, exist_ok=True)
    lock = open(os.path.join(store, LOCK), "w")  # held (and flocked) until return
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return "another session is syncing the code graph right now"
        _write(os.path.join(store, CHECKED), str(int(time.time())))
        release = json.loads(_gh(f"{REPO}/releases/tags/{TAG}"))
        meta = json.loads(_download(_asset(release, META_ASSET)))
        commit = str(meta.get("commit", ""))
        if not commit:
            raise GhError()
        summary = (
            f"{commit[:12]} (built {meta.get('built_at', '?')}, "
            f"{meta.get('nodes', '?')} nodes, graphify {meta.get('graphify_version', '?')})"
        )
        if commit == _installed_commit(store) and os.path.isfile(os.path.join(store, "graph.json")):
            return f"code graph already up to date: {summary}"
        _install(store, _download(_asset(release, TARBALL_ASSET)), meta)
        return f"code graph installed: {summary} -> {store}"
    finally:
        lock.close()


def _record_hint(store: str, hint: str) -> None:
    try:
        path = os.path.join(store, HINT)
        if hint:
            _write(path, hint + "\n")
        elif os.path.exists(path):
            os.unlink(path)
    except OSError:
        pass


def _run_sync(store: str, *, verbose: bool) -> None:
    try:
        summary = sync(store)
        _record_hint(store, "")
        if verbose:
            print(summary)
    except GhError as exc:
        _record_hint(store, exc.hint)
        if verbose:
            print(exc.hint or "code-graph: could not reach the code-graph release (try later)")
    except Exception as exc:  # a hook must never fail the session
        if verbose:
            print(f"code-graph: sync failed ({type(exc).__name__}: {exc})")


def _hook_cwd() -> str:
    """The session cwd from the hook JSON, then $CLAUDE_PROJECT_DIR, then $PWD."""
    if not sys.stdin.isatty():
        try:
            data = json.loads(sys.stdin.read() or "{}")
            cwd = data.get("cwd") if isinstance(data, dict) else None
            if isinstance(cwd, str) and os.path.isdir(cwd):
                return cwd
        except (OSError, ValueError):
            pass
    return os.environ.get("CLAUDE_PROJECT_DIR") or os.environ.get("PWD") or os.getcwd()


def main(argv: list[str]) -> int:
    now = "--now" in argv
    background = "--background" in argv
    try:
        if background:  # the detached child of the hook mode: argv = [--background, store]
            _run_sync(argv[argv.index("--background") + 1], verbose=False)
            return 0
        start = os.getcwd() if now else _hook_cwd()
        where = resolve(start)
        if where is None:
            if now:
                print(f"code-graph: {start} is not inside a git checkout")
            return 0
        worktree, store = where
        changed = link(worktree, store)
        if now:
            if changed:
                print(f"linked {', '.join(changed)} in {worktree}/{OUT_DIR} -> {store}")
            if not _which("graphify"):
                print(f"code-graph: graphify is not installed — run: {INSTALL_HINT}")
            _run_sync(store, verbose=True)
            return 0
        # Hook mode: at most one line, and never wait on the network.
        if not _which("graphify"):
            print(f"code-graph: graphify is not installed — run: {INSTALL_HINT}")
            return 0
        if not _which("gh"):
            print("code-graph: the GitHub CLI `gh` is missing — run: brew install gh")
            return 0
        hint = _read(os.path.join(store, HINT))
        if hint:
            print(hint)
        if not _throttled(store):
            subprocess.Popen(
                [sys.executable, os.path.abspath(__file__), "--background", store],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                env=_env(),
            )
    except Exception:  # every failure path exits 0
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
