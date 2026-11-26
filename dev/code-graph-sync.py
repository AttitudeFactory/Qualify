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
  regular file already there (a worktree with its own local graph) is never replaced. Where
  symlinks are not allowed (Windows without Developer Mode) the file is hardlinked, or copied,
  and recorded in `graphify-out/.code-graph-placed.json` so it is re-placed when the store's
  build changes; only files recorded there are ever replaced.
- Sync step: read the release's `code-graph.json`; when its build (commit + `built_at`)
  differs from the one last installed, download `code-graph.tar.gz` and install it into the
  store through a temp dir in the store and `os.replace` (atomic per file). REST only
  (`gh api`): GraphQL is blocked in cloud sessions, and `gh release` uses it.

Guard rails: a lock (one download per clone at a time), a 30-minute throttle on GitHub calls
(marker in the store), and every failure path exits 0. When something is missing, ONE line
on stdout says what and how to fix it; otherwise silent.

Modes:
  (default)  SessionStart hook: read the hook JSON on stdin (`cwd`), link, start the sync
             detached in the background and return at once.
  --now      foreground: ignore the throttle, link, sync and print what it did.

Runs outside any venv on macOS, Linux and Windows (Git Bash): system `python3` — or `python`
where `python3` is the Microsoft Store alias — standard library only.
"""

from __future__ import annotations

import glob
import json
import os
import platform
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
PLACED = ".code-graph-placed.json"  # in a worktree's graphify-out/: our hardlinks/copies

INSTALL_HINT = f"uv tool install graphifyy=={GRAPHIFY_VERSION}"
GH_HINT = "code-graph: the GitHub CLI `gh` is missing — run: " + (
    "brew install gh"
    if platform.system() == "Darwin"
    else "see https://cli.github.com (then gh auth login)"
)

# Hooks launched from a desktop app may not inherit the login shell's PATH.
_EXTRA_PATH = (os.path.expanduser("~/.local/bin"), "/opt/homebrew/bin", "/usr/local/bin") + (
    (r"C:\Program Files\GitHub CLI",) if sys.platform == "win32" else ()
)


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


def _stamp(path: str) -> list[int]:
    st = os.stat(path)
    return [st.st_size, st.st_mtime_ns]


def _place(target: str, tmp: str) -> list[int] | None:
    """Symlink tmp -> target; else hardlink, else copy. None for a symlink, else the stamp."""
    try:
        os.symlink(target, tmp)
        return None
    except OSError:
        if not os.path.isfile(target):
            raise  # nothing to hardlink or copy yet: the sync re-links after installing
    try:
        os.link(target, tmp)
    except OSError:
        shutil.copy2(target, tmp)
    return _stamp(target)


def link(worktree: str, store: str) -> tuple[list[str], list[str]]:
    """Point the worktree's graphify-out/<file> at the store.

    Returns (names linked now, names kept as this worktree's own regular files).
    """
    out_dir = os.path.join(worktree, OUT_DIR)
    changed: list[str] = []
    kept: list[str] = []
    if os.path.realpath(out_dir) == store:
        return changed, kept  # this is the checkout that owns the store
    if os.path.islink(out_dir):
        return changed, kept  # someone linked the whole directory on purpose; leave it
    try:
        os.makedirs(out_dir, exist_ok=True)
    except OSError:
        return changed, kept
    marker = os.path.join(out_dir, PLACED)
    try:
        placed = json.loads(_read(marker) or "{}")
    except ValueError:
        placed = {}
    if not isinstance(placed, dict):
        placed = {}
    before = dict(placed)
    for name in FILES:
        path = os.path.join(out_dir, name)
        target = os.path.join(store, name)
        if os.path.islink(path):
            if os.readlink(path) == target:
                continue
        elif os.path.lexists(path):
            if name not in placed:
                kept.append(name)  # a regular file: this worktree keeps its own graph
                continue
            rec = placed[name]  # [own size, own mtime_ns, store size, store mtime_ns]
            try:
                if _stamp(path) != rec[:2]:
                    # Rewritten in the worktree (in place or as a new file): its own graph now.
                    del placed[name]
                    kept.append(name)
                    continue
                if _stamp(target) == rec[2:]:
                    continue  # our hardlink/copy of the current build
            except OSError:
                continue  # store file missing: keep ours until the sync brings it back
        tmp = f"{path}.link-{os.getpid()}"
        try:
            stamp = _place(target, tmp)
            os.replace(tmp, path)  # Windows: fails while graphify holds it open; next run retries
            changed.append(name)
            if stamp is None:
                placed.pop(name, None)
            else:
                placed[name] = _stamp(path) + stamp
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    if placed != before:
        try:
            _write(marker, json.dumps(placed) + "\n")
        except OSError:
            pass
    return changed, kept


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


def _key(meta: object) -> tuple[str, str] | None:
    """What identifies a build: commit AND built_at (a forced rebuild keeps the commit)."""
    if not isinstance(meta, dict) or not meta.get("commit"):
        return None
    return str(meta["commit"]), str(meta.get("built_at", ""))


def _installed_keys(store: str) -> set[tuple[str, str]]:
    """Keys of the installed build: the meta inside its tarball, and the release meta seen."""
    try:
        marker = json.loads(_read(os.path.join(store, INSTALLED)) or "{}")
    except ValueError:
        return set()
    if not isinstance(marker, dict):
        return set()
    keys = {_key(marker.get("installed")), _key(marker.get("seen"))}
    return {k for k in keys if k}


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
        raise GhError(GH_HINT)
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


def _install(store: str, blob: bytes, seen: dict) -> dict:
    """Extract only FILES from the tarball into a temp dir in the store, then rename.

    Files are written by hand (no `extractall`): only regular members named in FILES (or the
    tarball's own code-graph.json), no links, no paths. Their mtime is the install time, not
    the build time: see the code-graph.yml header. Returns the installed build's meta — the
    copy inside the tarball, which is the truth about what was installed.
    """
    tmp = tempfile.mkdtemp(prefix=".code-graph-tmp-", dir=store)
    try:
        blob_path = os.path.join(tmp, TARBALL_ASSET)
        with open(blob_path, "wb") as fh:
            fh.write(blob)
        got = []
        inner: object = None
        with tarfile.open(blob_path, "r:gz") as tar:
            for member in tar.getmembers():
                name = member.name[2:] if member.name.startswith("./") else member.name
                if name not in (*FILES, META_ASSET) or not member.isfile():
                    continue
                src = tar.extractfile(member)
                if src is None:
                    continue
                if name == META_ASSET:
                    with src:
                        inner = json.loads(src.read().decode("utf-8"))
                    continue
                with src, open(os.path.join(tmp, name), "wb") as dst:
                    shutil.copyfileobj(src, dst)
                got.append(name)
        if "graph.json" not in got or os.path.getsize(os.path.join(tmp, "graph.json")) == 0:
            raise GhError()
        installed = inner if isinstance(inner, dict) and _key(inner) else seen
        for name in got:
            # Windows: a file open elsewhere (a worktree hardlink of it included) can block this
            # replace; the error ends this run without the marker, so the next run retries.
            os.replace(os.path.join(tmp, name), os.path.join(store, name))
        marker = {"installed": installed, "seen": seen}
        _write(os.path.join(store, INSTALLED), json.dumps(marker, indent=2) + "\n")
        return installed
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _summary(meta: dict) -> str:
    return (
        f"{str(meta.get('commit', '?'))[:12]} (built {meta.get('built_at', '?')}, "
        f"{meta.get('nodes', '?')} nodes, graphify {meta.get('graphify_version', '?')})"
    )


def _try_lock(fh: object) -> bool:
    """Non-blocking exclusive lock on an open file: flock on POSIX, msvcrt on Windows."""
    try:
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
        else:
            import fcntl

            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _spawn(cmd: list[str], popen: object = subprocess.Popen) -> object:
    """Start cmd detached, so the background sync outlives the hook (and its console)."""
    kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "env": _env(),
    }
    if sys.platform != "win32":
        return popen(cmd, start_new_session=True, **kwargs)
    # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP (literals: the names exist only on Windows)
    flags = 0x00000008 | 0x00000200
    try:  # + CREATE_BREAKAWAY_FROM_JOB: survive a job object that kills its members on close
        return popen(cmd, creationflags=flags | 0x01000000, **kwargs)
    except PermissionError:  # the job forbids breakaway (access denied)
        return popen(cmd, creationflags=flags, **kwargs)


def sync(store: str) -> str:
    """One check against the release; returns a human summary. Raises GhError."""
    os.makedirs(store, exist_ok=True)
    lock = open(os.path.join(store, LOCK), "w")  # held (and locked) until return
    try:
        if not _try_lock(lock):
            return "another session is syncing the code graph right now"
        # Under the lock nobody else is installing: any temp dir left is from a killed run.
        for stale in glob.glob(os.path.join(glob.escape(store), ".code-graph-tmp-*")):
            shutil.rmtree(stale, ignore_errors=True)
        _write(os.path.join(store, CHECKED), str(int(time.time())))
        release = json.loads(_gh(f"{REPO}/releases/tags/{TAG}"))
        meta = json.loads(_download(_asset(release, META_ASSET)))
        key = _key(meta)
        if key is None:
            raise GhError()
        if key in _installed_keys(store) and os.path.isfile(os.path.join(store, "graph.json")):
            return f"code graph already up to date: {_summary(meta)}"
        installed = _install(store, _download(_asset(release, TARBALL_ASSET)), meta)
        return f"code graph installed: {_summary(installed)} -> {store}"
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
            print(
                exc.hint
                or "code-graph: could not reach the code-graph release — retry: just graph-sync"
            )
    except Exception as exc:  # a hook must never fail the session
        if verbose:
            print(f"code-graph: sync failed ({type(exc).__name__}: {exc}) — retry: just graph-sync")


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
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, OSError, ValueError):
        pass
    try:
        if background:  # the detached child of the hook mode: [--background, store, worktree]
            store, worktree = argv[argv.index("--background") + 1 :][:2]
            _run_sync(store, verbose=False)
            link(worktree, store)  # hardlinks/copies need the installed files
            return 0
        start = os.getcwd() if now else _hook_cwd()
        where = resolve(start)
        if where is None:
            if now:
                print(
                    f"code-graph: {start} is not inside a git checkout — "
                    "run it from the repo or a worktree"
                )
            return 0
        worktree, store = where
        changed, kept = link(worktree, store)
        if now:
            if not _which("graphify"):
                print(f"code-graph: graphify is not installed — run: {INSTALL_HINT}")
            _run_sync(store, verbose=True)
            changed += [n for n in link(worktree, store)[0] if n not in changed]
            if changed:
                print(f"linked {', '.join(changed)} in {worktree}/{OUT_DIR} -> {store}")
            if kept:
                own = os.path.join(worktree, OUT_DIR)
                print(
                    f"code-graph: {own} keeps its own {', '.join(kept)} (regular files, not "
                    f"synced) — to use the CI graph: rm {' '.join(kept)} there, "
                    "then just graph-sync"
                )
            return 0
        # Hook mode: at most one line, and never wait on the network.
        if not _which("graphify"):
            print(f"code-graph: graphify is not installed — run: {INSTALL_HINT}")
            return 0
        if not _which("gh"):
            print(GH_HINT)
            return 0
        hint = _read(os.path.join(store, HINT))
        if hint:
            print(hint)
        if not _throttled(store):
            _spawn([sys.executable, os.path.abspath(__file__), "--background", store, worktree])
    except Exception:  # every failure path exits 0
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
